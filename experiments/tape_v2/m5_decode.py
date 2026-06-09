"""m5_decode.py — recover the master5 rate-ladder payloads from a captured WAV.

Mirrors m4_decode.py but with 4 WS rungs (varying RS rates) and no CSS.

Usage
-----
    python3 m5_decode.py <recording.wav> [--out-tag TAG]
    python3 m5_decode.py master5.wav            # self-check (no channel)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2", ROOT / "experiments" / "capacity",
           _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                      # noqa: E402
from m3_codec import Rung                                     # noqa: E402
import analyze_master2 as am2                                 # noqa: E402
from assault_widespace import build as ws_build, _demod_frame_achievable  # noqa: E402

SR = codec.FS
MANIFEST_PATH = _HERE / "master5_manifest.json"
RESULTS_DIR = _HERE / "results"

WS_WINDOW_PAD = 0.30  # seconds of pad around each WS frame window


def _ws_eq_from_sounder(ws, sounder: dict) -> np.ndarray:
    sf_freqs = np.asarray(sounder.get("sounder_freqs", []), dtype=np.float64)
    H_db = np.asarray(sounder.get("H_db", []), dtype=np.float64)
    if len(sf_freqs) < 2:
        return np.ones(ws.M)
    Hlin = 10.0 ** (np.interp(ws.freqs, sf_freqs, H_db) / 20.0)
    Hlin = Hlin / (Hlin.max() + 1e-12)
    return np.clip(Hlin, 0.05, None)


def _decode_ws(audio_nom, sec, align, ws, eq) -> dict:
    meta = sec["meta"]
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                rs_n=meta["rs_n"], rs_k=meta["rs_k"],
                frame_bytes=meta["frame_bytes"])
    frames_bits_ref, _ = codec.encode_payload(
        (_HERE / sec["payload_sidecar"]).read_bytes(), rung
    )
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()

    n_frames = meta["n_frames"]
    nsym = meta["frame_bits"] // ws.bits_per_sym
    frame_gap = meta.get("frame_gap_samples",
                         int(round(0.12 * SR)))

    # Audio for one frame (first frame, to get length)
    test_audio = np.asarray(
        ws.modulate(np.zeros(meta["frame_bits"], np.uint8)), np.float32
    )
    flen = len(test_audio)
    pad = int(WS_WINDOW_PAD * SR)

    raw_err = 0
    raw_tot = 0
    frames_bits: list[np.ndarray] = []

    for fi, st in enumerate(sec["frame_starts"]):
        st_a = int(st) + align
        w_lo = max(0, st_a - pad)
        w_hi = min(len(audio_nom), st_a + flen + pad)
        win = np.asarray(audio_nom[w_lo:w_hi], dtype=np.float32)
        rb = np.asarray(
            _demod_frame_achievable(ws, eq, win, nsym, "contrast"),
            dtype=np.uint8,
        ).ravel()
        tb = frames_bits_ref[fi].astype(np.uint8)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        frames_bits.append(rb)

    recovered = codec.decode_payload(frames_bits, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == expected
    byte_err = sum(a != b for a, b in zip(recovered, expected)) + abs(
        len(recovered) - len(expected)
    )
    return {
        "name": sec["name"],
        "scheme": "widespace",
        "phy": sec["phy"],
        "llm_offset": sec.get("llm_offset", 0),
        "payload_bytes": len(expected),
        "n_frames": n_frames,
        "n_codewords": meta["n_codewords"],
        "raw_ber": raw_err / max(1, raw_tot),
        "rs_codewords_failed": cw_failed,
        "byte_errors": byte_err,
        "byte_exact": bool(exact),
        "rs_n": meta["rs_n"],
        "rs_k": meta["rs_k"],
    }


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
    except Exception as e:
        sounder = {"error": str(e)}

    wphy = manifest["ws_phy"]
    ws = ws_build(wphy["M"], wphy["K"], wphy["spacing"], wphy["N"])
    eq = _ws_eq_from_sounder(ws, sounder)

    results = []
    for sec in manifest["ws_payloads"]:
        results.append(_decode_ws(audio_nom, sec, align, ws, eq))

    if verbose:
        print(f"[m5_decode] {recording_path}")
        print(f"  recovered clock: {sync['speed']:.4f}x "
              f"(offset {sync['speed_offset']*100:+.2f}%), align {align:+d}")
        if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
            print(f"  sounder: flutter {sounder['flutter_wrms_pct']:.2f}%, "
                  f"SNR med {sounder['snr_db_median']:.1f} dB, "
                  f"nf {sounder['noise_floor_dbfs']:.1f} dBFS")
        print(f"\n  {'payload':<16} {'RS':>9} {'frames':>6} {'cw':>5} "
              f"{'rawBER':>8} {'cwFail':>8} {'byteErr':>8} {'EXACT':>6}")
        for r in results:
            rs = f"({r['rs_n']},{r['rs_k']})"
            cw = f"{r['rs_codewords_failed']}/{r['n_codewords']}"
            tag = "YES ✓" if r["byte_exact"] else "no"
            print(f"  {r['name']:<16} {rs:>9} {r['n_frames']:>6} {r['n_codewords']:>5} "
                  f"{r['raw_ber']:>8.4f} {cw:>8} {r['byte_errors']:>8} {tag:>6}")
        n_exact = sum(r["byte_exact"] for r in results)
        print(f"\n  byte-exact: {n_exact}/{len(results)}")
        if n_exact:
            best = max((r for r in results if r["byte_exact"]),
                       key=lambda r: r["rs_k"])
            approx_net = 750.0 * best["rs_k"] / 255
            print(f"  best rate: RS(255,{best['rs_k']}) ~ {approx_net:.0f} net bps "
                  f"→ full 153KB LLM in ~{153823*8/approx_net/60:.1f} min")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    out = {
        "recording": str(recording_path),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {k: v for k, v in (sounder or {}).items()
                    if k not in ("H_db", "snr_db_per_tone", "sounder_freqs")},
        "payloads": results,
        "n_byte_exact": sum(r["byte_exact"] for r in results),
        "n_payloads": len(results),
    }
    json_path = RESULTS_DIR / f"m5_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m5_decode] wrote {json_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape-playback WAV (or master5.wav)")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, args.out_tag)
