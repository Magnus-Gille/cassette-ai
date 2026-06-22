"""bps_push_decode.py -- decode a WAV of the BPS-push master against its manifest.

The receiver for bps_push_master.py.  Global chirp sync + clock recovery (reusing
analyze_master2.global_sync_and_resample VERBATIM -- the proven up/down-chirp
matched filter + 0.80..1.10 speed scan + whole-recording resample to nominal),
then per-rung: locate the segment from the manifest (chirp0-aligned), rebuild the
SAME scheme (module + build_args), demodulate, truncate to the coded-bit count,
de-interleave the column-major codeword matrix, RS(255,rs_k)-decode each codeword
with CRC32-per-codeword as the ONLY acceptance channel, compare to the seeded
payload regenerated from payload_seed.

Reports per rung:
  byte_exact            -- recovered message == seeded payload (the deliverable test)
  codewords_passed/total -- per-codeword CRC32 acceptance (no truth used)
  raw_ber               -- pre-FEC bit error rate (re-encode the known payload to
                           get tx coded bits; Hamming vs rx coded bits)
  model_net_bps         -- model-closure achievable net bps from the raw BER:
                           E = 255*(1-(1-ber)^8); k_max = floor(255-2E);
                           gross * max(0,k_max)/255  (same yardstick as score.py)

Usage:
    python3 bps_push_decode.py <wav> [--selfcheck] [--out-tag TAG]

  --selfcheck : the HARD GATE.  Decode the master directly (no channel); EVERY
                rung MUST be byte_exact=True or the master+decoder are inconsistent.

Results -> results/<tag>_decode.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sys
import warnings
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "tape_v2", _HERE / "harness", _HERE / "candidates"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from reedsolo import RSCodec, ReedSolomonError              # noqa: E402
import analyze_master2 as am2                                # noqa: E402

# Reuse the master's own scheme-builder + framing helpers (single source of truth).
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "bps_push_master", _HERE / "bps_push_master.py")
_bpm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bpm)

build_rung_scheme = _bpm.build_rung_scheme
encode_rung = _bpm.encode_rung
codewords_for = _bpm.codewords_for

SR = 48_000
RS_N = 255
MANIFEST_PATH = _HERE / "master" / "bps_push_manifest.json"
RESULTS_DIR = _HERE / "results"


# ---------------------------------------------------------------------------
# model-closure net bps from raw BER (the score.py yardstick, verbatim math)
# ---------------------------------------------------------------------------
def model_net_bps(gross: float, ber: float) -> float:
    ber = max(0.0, min(1.0, float(ber)))
    E = RS_N * (1.0 - (1.0 - ber) ** 8)          # expected RS byte-errors / codeword
    k_max = int(np.floor(RS_N - 2.0 * E))
    k_max = max(0, min(RS_N - 1, k_max))
    return float(gross) * k_max / RS_N


def _hamming_ber(tx: np.ndarray, rx: np.ndarray) -> float:
    n = len(tx)
    if n == 0:
        return 0.0
    m = min(n, len(rx))
    errs = int(np.count_nonzero(tx[:m] != rx[:m])) if m else 0
    errs += (n - m)                               # missing tail bits == errors
    return errs / n


def _regenerate_payload(seed: int, message_bytes: int) -> bytes:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=message_bytes, dtype=np.uint8).tobytes()


# ---------------------------------------------------------------------------
# de-interleave + RS-decode with CRC32-per-codeword acceptance
# ---------------------------------------------------------------------------
def decode_rung_bits(rx_coded_bits: np.ndarray, rs_k: int, n_cw: int,
                     crc32_codewords: list[int]):
    """Inverse of encode_rung: truncate to the exact coded length, de-interleave,
    RS(255,rs_k)-decode each codeword, accept iff the recovered message CRC32
    matches the manifest's stored CRC32 (the no-truth acceptance channel).

    Returns (message_bytes, codewords_passed, per_cw_ok list)."""
    rsc = RSCodec(RS_N - rs_k)
    need_bits = n_cw * RS_N * 8
    rx = np.asarray(rx_coded_bits, np.uint8).ravel()
    if len(rx) < need_bits:
        rx = np.concatenate([rx, np.zeros(need_bits - len(rx), np.uint8)])
    rx = rx[:need_bits]

    rx_bytes = np.packbits(rx)[:n_cw * RS_N]
    rx_mat = rx_bytes.reshape(RS_N, n_cw).T        # de-interleave -> (n_cw, 255)

    out = bytearray()
    per_cw_ok = []
    for i in range(n_cw):
        msg = None
        try:
            decoded = rsc.decode(bytes(rx_mat[i]))[0]   # rs_k message bytes
            if len(decoded) == rs_k:
                msg = bytes(decoded)
        except (ReedSolomonError, Exception):
            msg = None
        ok = (msg is not None and
              (zlib.crc32(msg) & 0xFFFFFFFF) == crc32_codewords[i])
        per_cw_ok.append(bool(ok))
        out += (msg if (msg is not None and len(msg) == rs_k) else bytes(rs_k))
    return bytes(out), int(sum(per_cw_ok)), per_cw_ok


# ---------------------------------------------------------------------------
# main decode
# ---------------------------------------------------------------------------
def decode(wav_path: str, *, selfcheck: bool = False, out_tag: str | None = None,
           verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["master_id"] == "bps_push_v1", manifest["master_id"]

    audio, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)

    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - sync["expected_chirp0"]
    pad = int(0.30 * SR)                            # generous window for the modem

    rows = []
    for entry in manifest["rungs"]:
        rung_name = entry["name"]
        rs_k = int(entry["rs_k"])
        n_cw = int(entry["n_codewords"])
        message_bytes = int(entry["message_bytes"])
        coded_bits = int(entry["coded_bits"])
        bits_per_sym = int(entry["bits_per_sym"])
        crc32_cw = entry["crc32_codewords"]

        # regenerate the exact transmitted payload + tx coded bits (for raw BER)
        payload = _regenerate_payload(entry["payload_seed"], message_bytes)
        assert hashlib.sha256(payload).hexdigest() == entry["payload_sha256"]
        tx_coded_bits, _, _ = encode_rung(payload, rs_k)
        assert len(tx_coded_bits) == coded_bits, (len(tx_coded_bits), coded_bits)

        fs = build_rung_scheme(rung_name, rs_k)

        # Locate the segment (chirp0-aligned) and hand the modem a window.  CRITICAL:
        # the dapsk/stacked self-syncing demods infer the symbol count from the
        # window LENGTH (total = round((len-ds)/N)), so ANY trailing data beyond the
        # body (the 0.12 s frame-gap, the next rung, even a sub-symbol guard that
        # tips round() over) inflates nd and shifts the whole carrier-block layout
        # -> ~chance BER.  We trim the trailing edge to EXACTLY the body end so
        # (len-ds) == (nd+1)*N; find_preamble's few-sample ds jitter is absorbed by
        # round() (tolerance N/2 = 128 samples) and the last symbol's analysis
        # window is zero-padded by the demod if it runs a hair past the edge.  A
        # generous LEADING pad is fine -- find_preamble fine-syncs within it.  The
        # dense2x adapter uses _nbits (immune to window length) so the trim is
        # harmless there too.
        sc = getattr(fs, "_scheme", None) or getattr(fs, "tx_scheme", None)
        N = int(getattr(sc, "N", 256))
        start = int(entry["segment_start_sample"]) + align
        body_end = int(entry["body_end_sample"]) + align
        w_lo = max(0, start - pad)
        w_hi = min(len(audio_nom), body_end)            # trim exactly to body end
        window = np.asarray(audio_nom[w_lo:w_hi], np.float32)

        # the dense2x adapter needs nd; the dapsk/stack schemes self-size from audio
        mod_ref = getattr(fs, "_modulate_ref", None)
        if mod_ref is not None:
            mod_ref._nbits = coded_bits

        rx_bits = np.asarray(fs.demodulate(window, SR), np.uint8)

        raw_ber = _hamming_ber(tx_coded_bits, rx_bits)
        gross = float(fs.gross_bps)
        net = model_net_bps(gross, raw_ber)

        msg, cw_passed, _ = decode_rung_bits(rx_bits, rs_k, n_cw, crc32_cw)
        recovered = msg[:message_bytes]
        byte_exact = (recovered == payload)

        rows.append({
            "name": rung_name,
            "scheme": fs.name,
            "rs_k": rs_k,
            "n_codewords": n_cw,
            "codewords_passed": cw_passed,
            "byte_exact": bool(byte_exact),
            "raw_ber": float(raw_ber),
            "gross_bps": gross,
            "projected_net_bps": float(gross * rs_k / RS_N),
            "model_net_bps": float(net),
            "info_bytes": message_bytes,
        })

    result = {
        "wav": str(wav_path),
        "master_id": manifest["master_id"],
        "selfcheck": bool(selfcheck),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "rungs": rows,
        "all_byte_exact": all(r["byte_exact"] for r in rows),
    }

    if verbose:
        _print_table(wav_path, sync, rows, selfcheck)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(wav_path).stem
    out_json = RESULTS_DIR / f"{tag}_decode.json"
    out_json.write_text(json.dumps(result, indent=2, default=float))
    if verbose:
        print(f"[decode] wrote {out_json}")

    if selfcheck and not result["all_byte_exact"]:
        failed = [r["name"] for r in rows if not r["byte_exact"]]
        raise AssertionError(
            f"HARD GATE FAILED: rungs not byte-exact on the no-channel "
            f"self-check: {failed}. Master+decoder are inconsistent.")

    return result


def _print_table(wav_path, sync, rows, selfcheck):
    mode = "SELF-CHECK (no channel)" if selfcheck else "through channel"
    print(f"[decode] {wav_path}  [{mode}]")
    print(f"  recovered clock: {sync['speed']:.4f}x "
          f"(offset {sync['speed_offset']*100:+.2f}%), "
          f"spacing {sync['measured_spacing']}/{sync['expected_spacing']}")
    print(f"  {'rung':24s} {'rs_k':>4} {'cw_ok':>7} {'exact':>6} "
          f"{'raw_ber':>9} {'gross':>7} {'net@k':>7} {'model_net':>9}")
    for r in rows:
        exact = "YES" if r["byte_exact"] else "no"
        print(f"  {r['name']:24s} {r['rs_k']:>4} "
              f"{r['codewords_passed']:>3}/{r['n_codewords']:<3} {exact:>6} "
              f"{r['raw_ber']:>9.5f} {r['gross_bps']:>7.0f} "
              f"{r['projected_net_bps']:>7.0f} {r['model_net_bps']:>9.0f}")
    n_ok = sum(r["byte_exact"] for r in rows)
    print(f"  -> {n_ok}/{len(rows)} rungs byte-exact")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--selfcheck", action="store_true",
                    help="HARD GATE: no-channel decode, every rung MUST be byte-exact")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.wav, selfcheck=args.selfcheck, out_tag=args.out_tag)
