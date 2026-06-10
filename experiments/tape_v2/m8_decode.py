"""m8_decode.py -- recover the merged master8 ladder from a captured (or clean) WAV.

Manifest-driven, m7 pattern: ONE global sync (chirp pair + front sounder), then
each section decoded with its proper path:

  * WS sections (M16 K1/K2/K3) -> m6_decode._decode_section (per-rung geometry).
  * WS-M32 sections (combo=True) ALSO get the H6 combo path: H5's timing-
    trajectory front-end (bw 0.25 Hz) -> errors-and-erasures RS decode
    (fixed policy frac:0.25|gap|mean) with a RECEIVER-SIDE miscorrection guard
    (CRC32-per-codeword table from the manifest -- no truth leak). Both the
    plain and combo results are reported per section.
  * DQPSK sections -> h4_dqpsk.DQPSKScheme.demod (self-referencing pilot).

Every section's RS output is the H9-PACKED blob; we unpack_payload it and verify
against the manifest sha256 of the original + packed bytes. effective_bps =
projected_net_bps * orig_len / packed_len.

Output: results/m8_results_<capture>.json (m7 format + effective_bps, pack/unpack
ok, combo_decode results, crc_check).

Usage:
    python3 experiments/tape_v2/m8_decode.py experiments/tape_v2/master8.wav
    python3 experiments/tape_v2/m8_decode.py experiments/tape_v2/captures/tape8_run1.wav
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sys
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

# DQPSK/combo demod windows are zero-padded (silent tails, lead-in); the complex
# DFT correlators harmlessly hit divide/overflow on all-zero segments. Silence
# those numerically-benign warnings so decode logs stay readable.
np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2  # noqa: E402
import hyp_common as hc  # noqa: E402
import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
from m6_decode import _decode_section  # noqa: E402  (per-rung WS section decoder)
from h4_dqpsk import DQPSKScheme, FS as DQ_FS, PAD_LO_S, PAD_HI_S  # noqa: E402
from h9_payload_codec import unpack_payload  # noqa: E402

# H6 combo machinery (reused verbatim; modules have __main__ guards)
import h5_pll_decode as h5  # noqa: E402
from h6_combo_decode import ComboEngine, _decode_guarded  # noqa: E402
from h2_erasure_decode import _stream_bytes_and_rel  # noqa: E402

SR = codec.FS
MANIFEST_PATH = _HERE / "master8_manifest.json"
RESULTS_DIR = _HERE / "results"

# H6 combo fixed configuration (the real-tape-proven policy / loop bandwidth).
COMBO_BW_HZ = 0.25
COMBO_POLICY = {"kind": "frac", "param": 0.25, "metric": "gap", "agg": "mean"}


# ---------------------------------------------------------------------------
# DQPSK section decode (h4 demod, m5-style frame train)
# ---------------------------------------------------------------------------
def _decode_dqpsk_section(audio_nom, sec: dict, align: int) -> tuple[dict, bytes]:
    dq = sec["dqpsk_params"]
    sch = DQPSKScheme(dq["P"], dq["N"], dq["spacing"])
    meta = sec["meta"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()

    # nominal per-frame bit counts (m5/h4 convention)
    fb = meta["frame_bits"]
    n_frames = meta["n_frames"]
    nom_bits = [fb] * (n_frames - 1) + [meta["stream_bits"] - fb * (n_frames - 1)]

    pad_lo, pad_hi = int(PAD_LO_S * DQ_FS), int(PAD_HI_S * DQ_FS)
    # frame audio length for a full frame (for the window end)
    full_frame = np.asarray(
        sch.modulate(np.zeros(fb, np.uint8)), np.float32)
    flen_full = len(full_frame)

    raw_err = raw_tot = 0
    rx_frames: list[np.ndarray] = []
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(audio_nom), st + flen_full + pad_hi)
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        bits, _diag = sch.demod(win, nd)
        rx_frames.append(np.asarray(bits, np.uint8))
        raw_tot += nom_bits[fi]

    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    byte_err = sum(a != b for a, b in zip(recovered, expected_packed)) + abs(
        len(recovered) - len(expected_packed))
    res = {
        "name": sec["name"],
        "kind": "dqpsk",
        "role": sec.get("role", ""),
        "scheme": sec["phy"],
        "phy": sec["phy"],
        "llm_offset": sec.get("llm_offset", 0),
        "payload_bytes": len(expected_packed),
        "n_frames": meta["n_frames"],
        "n_codewords": meta["n_codewords"],
        "raw_ber": None,  # DQPSK path scores at RS level only here
        "rs_codewords_failed": cw_failed,
        "byte_errors": byte_err,
        "byte_exact": recovered == expected_packed,
        "rs_n": meta["rs_n"],
        "rs_k": meta["rs_k"],
        "gross_bps": sec.get("gross_bps"),
        "projected_net_bps": sec.get("projected_net_bps"),
    }
    return res, recovered


# ---------------------------------------------------------------------------
# WS-M32 combo decode (H6: timing-trajectory front-end + errors-and-erasures)
# ---------------------------------------------------------------------------
def _make_erase_fn(meta):
    twot = meta["rs_n"] - meta["rs_k"]
    F = int(round(COMBO_POLICY["param"] * twot))
    if F == 0:
        return lambda rel: []
    return lambda rel: sorted(int(i) for i in np.argsort(rel)[:F])


def _combo_decode_section(audio_nom, sec, align, sounder) -> dict:
    """H6 combo: pass-1 greedy demod -> timing trajectory (bw 0.25) -> steered
    instrumented re-demod -> errors-and-erasures RS with manifest-CRC guard.
    Truth is never used; the miscorrection guard uses the manifest CRC table."""
    eng = ComboEngine(sec, sounder)
    meta = sec["meta"]
    bps = eng.bps
    nF = meta["n_frames"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    crc_table = sec["crc32_codewords"]

    si_arr = np.zeros((nF, eng.nsym), np.int64)
    lock_arr = np.zeros((nF, eng.nsym), np.float64)
    gap_arr = np.zeros((nF, eng.nsym), np.float64)

    for fi, start in enumerate(sec["frame_starts"]):
        yy = h5.frame_window(audio_nom, eng, start, align)
        ds = hc.find_preamble(yy.astype(np.float32), eng.ws.preamble_seconds)
        # pass-1 greedy (gives d offsets for the timing trajectory)
        _si, d, _lock, _ok, _eps = eng.demod_frame_pass1(yy, ds)
        tau = h5.build_tau_timing(d, eng.fs_sym, COMBO_BW_HZ)
        si, lock, gap = eng.demod_frame_steered_instr(yy, int(ds), tau)
        si_arr[fi], lock_arr[fi], gap_arr[fi] = si, lock, gap

    bits_mat = np.stack([eng.bits_from_si(si) for si in si_arr])
    rel = gap_arr if COMBO_POLICY["metric"] == "gap" else lock_arr
    rx_mat, rel_cw = _stream_bytes_and_rel(bits_mat, rel, meta, bps, COMBO_POLICY["agg"])

    # receiver-side miscorrection guard: compare each decoded codeword message's
    # CRC32 against the manifest table (no truth bytes leaked).
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    from reedsolo import RSCodec, ReedSolomonError
    rsc = RSCodec(rs_n - rs_k)
    erase_fn = _make_erase_fn(meta)
    recovered = bytearray()
    cw_failed = 0
    miscorrected = 0
    n_erase = 0
    for i in range(n_cw):
        epos = erase_fn(rel_cw[i])
        n_erase += len(epos)
        try:
            if epos:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()), erase_pos=epos)[0]
            else:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()))[0]
            msg = bytes(dec)
            if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
                miscorrected += 1   # CRC says this RS "success" is a miscorrection
            recovered += msg
        except (ReedSolomonError, Exception):
            cw_failed += 1
            recovered += bytes(rs_k)
    out = bytes(recovered)[:meta["payload_len"]]
    byte_err = sum(a != b for a, b in zip(out, expected_packed)) + abs(
        len(out) - len(expected_packed))
    return {
        "policy": f"{COMBO_POLICY['kind']}:{COMBO_POLICY['param']}|"
                  f"{COMBO_POLICY['metric']}|{COMBO_POLICY['agg']}",
        "loop_bandwidth_hz": COMBO_BW_HZ,
        "rs_codewords_failed": cw_failed,
        "miscorrected_cw": miscorrected,
        "mean_erasures_per_cw": n_erase / max(1, n_cw),
        "byte_errors": byte_err,
        "byte_exact": out == expected_packed,
        "recovered_packed": out,
    }


# ---------------------------------------------------------------------------
def decode(recording_path: str, out_tag: str | None = None, verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(recording_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)

    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    except Exception as exc:
        sounder = {"error": str(exc)}

    results = []
    for sec in manifest["ws_payloads"]:
        if sec["kind"] == "dqpsk":
            r, recovered_packed = _decode_dqpsk_section(audio_nom, sec, align)
        else:
            r = _decode_section(audio_nom, sec, align, sounder)
            r["kind"] = "ws"
            # re-decode the PACKED payload to recover the actual bytes for unpacking
            recovered_packed = _ws_recovered_packed(audio_nom, sec, align, sounder)

        # ---- combo timing-trajectory rescue for ALL WS sections ----
        # The H5/H6 combo front-end (timing trajectory bw 0.25 Hz +
        # errors-and-erasures + manifest-CRC guard) is the proven real-tape
        # rescue. It is the HEADLINE decode for the WS-M32 rungs (combo=True),
        # but we run it on every WS section as a fallback: the single linear
        # chirp-to-chirp resample leaves residual flutter wander that grows
        # deep into the tape, and the per-symbol timing trajectory corrects it
        # (raw BER rises with distance from the front sounder; the trajectory
        # tracks that out). Truth is never used; the guard is the manifest CRC.
        # combo front-end (h5.SectionEngine) supports K in {1,2} only; the K=3
        # lottery rung uses its plain decode path (no combo rescue available).
        if sec["kind"] == "ws" and sec["meta"]["K"] <= 2:
            try:
                combo = _combo_decode_section(audio_nom, sec, align, sounder)
            except Exception as exc:  # combo never blocks the plain result
                combo = {"error": str(exc)}
            r["combo_decode"] = {k: v for k, v in combo.items()
                                 if k != "recovered_packed"}
            # if plain failed but combo succeeded, adopt combo's packed bytes
            if (not r["byte_exact"]) and combo.get("byte_exact"):
                recovered_packed = combo["recovered_packed"]
                r["rescued_by_combo"] = True

        # ---- unpack + integrity ----
        pack = sec["pack"]
        crc_ok = None
        unpack_ok = None
        orig_exact = None
        try:
            recovered_orig = unpack_payload(recovered_packed)
            unpack_ok = True
            sha_o = hashlib.sha256(recovered_orig).hexdigest()
            orig_exact = (sha_o == pack["sha256_orig"]
                          and len(recovered_orig) == pack["orig_len"])
            crc_ok = orig_exact
        except Exception as exc:
            unpack_ok = False
            recovered_orig = b""
            r["unpack_error"] = str(exc)
        r["effective_bps"] = sec.get("effective_bps")
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        r["unpack_ok"] = unpack_ok
        r["orig_byte_exact"] = orig_exact
        r["crc_check"] = crc_ok
        r["combo"] = sec.get("combo", False)
        # best-path packed-exact: plain OR combo rescue
        cb = r.get("combo_decode") or {}
        r["byte_exact_best"] = bool(r["byte_exact"] or cb.get("byte_exact"))
        results.append(r)

    if verbose:
        _print_table(recording_path, sync, sounder, align, results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    out = {
        "recording": str(recording_path),
        "tape": "master8",
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {
            k: v for k, v in (sounder or {}).items()
            if k not in ("H_db", "snr_db_per_tone", "sounder_freqs")
        },
        "payloads": results,
        "n_byte_exact_packed": sum(r["byte_exact"] for r in results),
        "n_orig_exact": sum(bool(r.get("orig_byte_exact")) for r in results),
        "n_payloads": len(results),
    }
    json_path = RESULTS_DIR / f"m8_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m8_decode] wrote {json_path}")
    return out


def _ws_recovered_packed(audio_nom, sec, align, sounder) -> bytes:
    """Re-run the m6 WS section decode but RETURN the recovered packed bytes
    (the _decode_section public result only carries byte_exact/byte_errors).
    Mirrors m6_decode._decode_section's demod exactly."""
    from assault_widespace import _demod_frame_achievable, build as ws_build
    from m6_decode import _ws_eq_from_sounder
    phy = sec["phy_params"]
    ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
    eq = _ws_eq_from_sounder(ws, sounder)
    meta = sec["meta"]
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                rs_n=meta["rs_n"], rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    frames_bits_ref, _ = codec.encode_payload(expected, rung)
    nsym = meta["frame_bits"] // ws.bits_per_sym
    test_audio = np.asarray(ws.modulate(np.zeros(meta["frame_bits"], np.uint8)), np.float32)
    flen = len(test_audio)
    pad = int(0.30 * SR)
    frames_bits = []
    for start in sec["frame_starts"]:
        st = int(start) + align
        lo = max(0, st - pad)
        hi = min(len(audio_nom), st + flen + pad)
        window = np.asarray(audio_nom[lo:hi], np.float32)
        rb = np.asarray(_demod_frame_achievable(ws, eq, window, nsym, "contrast"),
                        np.uint8).ravel()
        frames_bits.append(rb)
    return codec.decode_payload(frames_bits, meta)


def _print_table(recording_path, sync, sounder, align, results):
    print(f"[m8_decode] {recording_path}")
    print(f"  recovered clock: {sync['speed']:.4f}x "
          f"(offset {sync['speed_offset'] * 100:+.2f}%), align {align:+d}")
    if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
        print(f"  sounder: flutter {sounder['flutter_wrms_pct']:.2f}%, "
              f"SNR med {sounder['snr_db_median']:.1f} dB, "
              f"nf {sounder['noise_floor_dbfs']:.1f} dBFS")
    print(f"\n  {'payload':<22} {'phy':<19} {'RS':>9} {'net':>7} {'eff':>7} "
          f"{'cwFail':>8} {'PACK':>5} {'ORIG':>5} {'COMBO':>6}")
    for r in results:
        rs = f"({r['rs_n']},{r['rs_k']})"
        cw = f"{r['rs_codewords_failed']}/{r['n_codewords']}"
        pk = "YES" if r["byte_exact"] else "no"
        og = "YES" if r.get("orig_byte_exact") else "no"
        cb = ""
        c = r.get("combo_decode")
        if c is not None:
            cb = ("YES" if c.get("byte_exact") else "no") if "error" not in c else "ERR"
        print(f"  {r['name']:<22} {r['phy']:<19} {rs:>9} "
              f"{r.get('projected_net_bps') or 0:7.0f} "
              f"{r.get('effective_bps') or 0:7.0f} {cw:>8} {pk:>5} {og:>5} {cb:>6}")
    n_pk = sum(r["byte_exact"] for r in results)
    n_og = sum(bool(r.get("orig_byte_exact")) for r in results)
    print(f"\n  byte-exact (packed): {n_pk}/{len(results)}   "
          f"orig-exact (unpacked): {n_og}/{len(results)}")
    ex = [r for r in results if r.get("orig_byte_exact")]
    if ex:
        best = max(ex, key=lambda r: r.get("effective_bps") or 0)
        print(f"  best orig-exact rung: {best['name']} -> "
              f"net {best.get('projected_net_bps'):.0f} bps, "
              f"eff {best.get('effective_bps'):.0f} bps")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape-playback WAV or master8.wav")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, args.out_tag)
