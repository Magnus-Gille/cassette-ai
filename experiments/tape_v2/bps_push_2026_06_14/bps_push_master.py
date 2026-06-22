"""bps_push_master.py -- assemble the BPS-push morning master tape (2026-06-14).

THE DELIVERABLE.  One physical recording, ONE global sync (chirp pair + front
sounder reused VERBATIM from make_master2 so analyze_master2.global_sync_and_resample
works unchanged), then the 6-rung adjudicated ladder from
results/recommended_ladder.json -- conservative -> aggressive, anchored on the
proven r8 (5791) floor and reaching to the stacked-bulkframe TOP (model_net 8535).

LAYOUT (m10_master architecture, reused verbatim where it matters):
  1 s lead silence
  global up-chirp (tx_chirp0)              -- 500->5000 Hz, the speed/clock anchor
  0.40 s gap
  front Schroeder sounder (~45 s)          -- 2x 64-tone probe + 12 s 3 kHz + 3 s sil
  0.40 s gap
  RUNGS (each: one or more frames; 0.12 s frame-gap; 0.40 s gap after the rung)
    anchor_r8_proven        D2X_P22_N256_sp2 DQPSK   RS179  short frame  (the floor)
    r8_bulkframe_safe       same r8 PHY, ONE long ~59-cw frame  RS191    (multiplier)
    dapsk_8dpsk3            8-DPSK on 3 CSI-clean carriers       RS184    (1st higher-order)
    stack_8dpsk3_ext4      8-DPSK x3 + 4 ext DBPSK carriers     RS173    (levers add)
    stack_bulkframe_TOP    8-DPSK x3 + 6 ext, ONE long frame    RS191    (the TOP, 8535)
    robustness_hedge_dapsk7 8-DPSK on 7 CSI-clean carriers      RS173    (carrier-flip hedge)
  1 s silence
  global down-chirp (tx_chirp1)
  0.40 s gap
  1 s tail silence
  -> peak-normalize the whole mix to 0.70 (SOP).

FRAMING (clean RS(255,k) + CRC32-per-codeword + column-interleave, matching the
proven m10/x10 acceptance pipeline; reedsolo + zlib.crc32):
  * payload = seeded-random bytes, seed per rung (logged).  message_bytes =
    codewords * rs_k, codewords = round((frame_payload_bits/8)/255) (>=1).
  * RS(255,rs_k)-encode each rs_k-byte message chunk -> 255-byte codewords.
  * CRC32 of each codeword's MESSAGE bytes -> manifest (the ONLY acceptance channel
    the decoder uses; no truth at decode time).
  * column-major interleave the codewords (byte j of every codeword travels
    together) so one corrupted symbol-block hits few bytes per codeword (RS-friendly,
    interleave depth = whole rung).
  * the interleaved coded bitstream = ONE long bit array fed to scheme.modulate ->
    ONE preamble per frame.  The bulk rungs are ONE long frame.

A HARD GATE lives in bps_push_decode.py --selfcheck: this master MUST self-decode
byte-exact with no channel, every rung.  Build does its own clean self-check too.

Run:
    python3 bps_push_master.py [--out master/bps_push_master.wav]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
import pathlib
import sys
import warnings
import zlib

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "tape_v2", _HERE / "harness", _HERE / "candidates"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from reedsolo import RSCodec                                # noqa: E402
from make_master2 import (                                   # noqa: E402
    GLOBAL_CHIRP_T, _build_sounder, _make_global_chirp, _silence,
)
import evaluate as ev                                        # noqa: E402

SR = 48_000
RS_N = 255

MASTER_ID = "bps_push_v1"
OUT_DIR = _HERE / "master"
WAV_PATH = OUT_DIR / "bps_push_master.wav"
MANIFEST_PATH = OUT_DIR / "bps_push_manifest.json"
LADDER_JSON = _HERE / "results" / "recommended_ladder.json"

# Layout constants (m10_master values, verbatim).
LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
PEAK = 0.70

# Per-rung deterministic payload seeds (logged; one per rung).
PAYLOAD_SEED_BASE = 20260614


# ---------------------------------------------------------------------------
# Candidate module loaders (hyphenated filenames -> importlib spec)
# ---------------------------------------------------------------------------
def _load_candidate(filename: str, modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, _HERE / "candidates" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dapsk = _load_candidate("dapsk16-strongmids.py", "dapsk16_strongmids")
_stack = _load_candidate("stacked_flagship.py", "stacked_flagship")


def build_rung_scheme(rung_name: str, rs_k: int):
    """Return the FuncScheme for a rung by name, with rs_k attached.

    The exact build args are fixed by the recommended_ladder (the decoder builds
    the SAME object from the manifest's module+build_args, so this mapping is the
    single source of truth for both encode and decode)."""
    if rung_name == "anchor_r8_proven":
        fs = ev.build_dense2x_candidate(22, rs_k)
    elif rung_name == "r8_bulkframe_safe":
        fs = ev.build_dense2x_candidate(22, rs_k)
    elif rung_name == "dapsk_8dpsk3":
        fs = _dapsk.build("d")
    elif rung_name == "stack_8dpsk3_ext4":
        fs = _stack.build(3, 4)
    elif rung_name == "stack_bulkframe_TOP":
        fs = _stack.build(3, 6)
    elif rung_name == "robustness_hedge_dapsk7":
        fs = _dapsk.build("e")
    else:
        raise ValueError(f"unknown rung {rung_name!r}")
    fs.rs_k = int(rs_k)
    return fs


# ---------------------------------------------------------------------------
# Clean RS(255,k) + CRC32-per-codeword + column-interleave framing layer.
# Mirrors m3_codec.encode_payload (RS + column interleave) but adds the explicit
# CRC32-per-codeword manifest that the decoder uses as its only acceptance channel.
# ---------------------------------------------------------------------------
def codewords_for(frame_payload_bits: int) -> int:
    """codewords = round((frame_payload_bits/8)/255), at least 1.

    frame_payload_bits is the coded-body BUDGET; the realized coded body is
    codewords*255*8 (close to the budget).  round() keeps it nearest."""
    return max(1, int(round((frame_payload_bits / 8.0) / RS_N)))


def encode_rung(message: bytes, rs_k: int):
    """RS(255,rs_k)-encode + column-interleave -> (coded_bits, crc32_codewords, meta).

    message length MUST be an exact multiple of rs_k (we size it so).  Returns the
    interleaved coded BIT array (uint8), the per-codeword message CRC32 list, and a
    meta dict the decoder needs to invert (n_codewords, rs_k, message_len)."""
    message = bytes(message)
    assert len(message) % rs_k == 0, (len(message), rs_k)
    rsc = RSCodec(RS_N - rs_k)
    n_cw = len(message) // rs_k

    crc32_codewords = []
    cw_list = []
    for i in range(n_cw):
        msg_chunk = message[i * rs_k:(i + 1) * rs_k]
        crc32_codewords.append(zlib.crc32(msg_chunk) & 0xFFFFFFFF)
        cw_list.append(bytes(rsc.encode(msg_chunk)))           # 255-byte codeword

    # column-major interleave: byte j of every codeword travels together.
    mat = np.frombuffer(b"".join(cw_list), np.uint8).reshape(n_cw, RS_N)
    tx_bytes = mat.T.reshape(-1)                               # (RS_N * n_cw,)
    coded_bits = np.unpackbits(tx_bytes).astype(np.uint8)      # (RS_N*n_cw*8,)

    meta = {
        "rs_n": RS_N, "rs_k": int(rs_k), "n_codewords": int(n_cw),
        "message_len": len(message), "coded_bits": int(len(coded_bits)),
    }
    return coded_bits, crc32_codewords, meta


def _codeword_crcs(message: bytes, rs_k: int) -> list[int]:
    n_cw = len(message) // rs_k
    return [zlib.crc32(message[i * rs_k:(i + 1) * rs_k]) & 0xFFFFFFFF
            for i in range(n_cw)]


# ===========================================================================
def build(out_wav: pathlib.Path = WAV_PATH) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ladder = json.loads(LADDER_JSON.read_text())["recommended_ladder"]

    parts: list[np.ndarray] = []
    pos = 0

    def add_raw(sig: np.ndarray) -> None:
        nonlocal pos
        sig = np.asarray(sig, dtype=np.float32)
        parts.append(sig)
        pos += len(sig)

    def add_gap(d: float = GAP_S) -> None:
        add_raw(_silence(d))

    manifest: dict = {
        "master_id": MASTER_ID,
        "SR": SR,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "payload_seed_base": PAYLOAD_SEED_BASE,
        "reference_to_beat": json.loads(LADDER_JSON.read_text())["reference_to_beat"],
        "rungs": [],
    }

    # ---- lead + global up-chirp ----
    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (verbatim) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # ---- rungs ----
    total_info_bytes = 0
    print(f"[build] master_id={MASTER_ID}  ({len(ladder)} rungs)")
    print(f"[build] {'rung':24s} {'scheme':30s} {'rs_k':>4} {'cw':>3} "
          f"{'msgB':>6} {'gross':>7} {'net':>7} {'sec':>6}")
    for ri, rung in enumerate(ladder):
        rung_name = rung["rung_name"]
        rs_k = int(rung["rs_k"])
        fpb = int(rung["frame_payload_bits"])
        seed = PAYLOAD_SEED_BASE + ri

        fs = build_rung_scheme(rung_name, rs_k)
        sc = getattr(fs, "_scheme", None) or getattr(fs, "tx_scheme", None)
        bits_per_sym = int(sc.bits_per_sym)

        # payload sizing: codewords from the coded-bit budget, message = cw * rs_k.
        n_cw = codewords_for(fpb)
        message_bytes = n_cw * rs_k
        rng = np.random.default_rng(seed)
        payload = rng.integers(0, 256, size=message_bytes, dtype=np.uint8).tobytes()
        total_info_bytes += message_bytes

        # encode -> coded interleaved bits + per-codeword CRC32
        coded_bits, crc32_cw, fmeta = encode_rung(payload, rs_k)
        assert crc32_cw == _codeword_crcs(payload, rs_k)

        # modulate ONE long frame (one preamble) from the coded bits.
        mod_ref = getattr(fs, "_modulate_ref", None)
        if mod_ref is not None:
            mod_ref._nbits = len(coded_bits)          # dense2x adapter needs nd
        frame_start = pos
        audio = np.asarray(fs.modulate(coded_bits), dtype=np.float32)
        body_end = frame_start + len(audio)        # exact end of the modulated body
        add_raw(audio)
        add_raw(_silence(FRAME_GAP_S))
        seg_end = pos
        add_gap()

        nd = int(math.ceil(len(coded_bits) / bits_per_sym))
        gross = float(fs.gross_bps)
        net = gross * rs_k / RS_N
        sec_s = (seg_end - frame_start) / SR

        entry = {
            "name": rung_name,
            "module": rung["module"],
            "build_args": rung["build_args"],
            "scheme_name": fs.name,
            "rs_k": rs_k,
            "rs_n": RS_N,
            "n_codewords": n_cw,
            "message_bytes": message_bytes,
            "info_bytes": message_bytes,
            "frame_payload_bits_target": fpb,
            "coded_bits": int(len(coded_bits)),
            "bits_per_sym": bits_per_sym,
            "n_data_symbols": nd,
            "is_bulk_frame": bool(fpb > 20000),
            "gross_bps": gross,
            "projected_net_bps": net,
            "model_net_recommended": rung.get("model_net"),
            "risk": rung.get("risk", ""),
            "payload_seed": seed,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "crc32_codewords": crc32_cw,
            "segment_start_sample": int(frame_start),
            "body_end_sample": int(body_end),           # exact end of modulated body
            "body_samples": int(len(audio)),            # preamble + (nd+1)*N
            "segment_end_sample": int(seg_end),
            "frame_starts": [int(frame_start)],         # one long frame per rung
            "preamble_seconds": float(getattr(sc, "preamble_seconds", 0.25)),
        }
        manifest["rungs"].append(entry)
        print(f"[build] {rung_name:24s} {fs.name:30s} {rs_k:>4} {n_cw:>3} "
              f"{message_bytes:>6} {gross:>7.0f} {net:>7.0f} {sec_s:>5.1f}s")

    # ---- global down-chirp + tail (>=1 s silence around end chirp per SOP) ----
    add_raw(_silence(1.0))
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()
    add_raw(_silence(TAIL))

    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * PEAK).astype(np.float32)
    dur_s = len(audio_full) / SR

    manifest["duration_seconds"] = dur_s
    manifest["total_info_bytes"] = total_info_bytes

    sf.write(str(out_wav), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"\n[build] {out_wav} {dur_s:.1f}s ({dur_s/60:.2f} min), peak {PEAK}")
    print(f"[build] manifest -> {MANIFEST_PATH} (master_id={MASTER_ID})")
    print(f"[build] total info bytes: {total_info_bytes}")
    return (f"{out_wav.name} {dur_s:.1f}s ({dur_s/60:.2f} min), "
            f"{len(manifest['rungs'])} rungs, {total_info_bytes} info bytes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    print(build(pathlib.Path(args.out)))
