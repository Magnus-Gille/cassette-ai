"""m6_decode.py -- recover master6 WS turbo-geometry ladder payloads.

Mirrors m5_decode.py, but each section can use a different WS geometry.

Usage:
    python3 experiments/tape_v2/m6_decode.py experiments/tape_v2/master6.wav
    python3 experiments/tape_v2/m6_decode.py experiments/tape_v2/captures/tape6_run1.wav
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
import m3_codec as codec  # noqa: E402
from assault_widespace import _demod_frame_achievable, build as ws_build  # noqa: E402
from m3_codec import Rung  # noqa: E402

SR = codec.FS
MANIFEST_PATH = _HERE / "master6_manifest.json"
RESULTS_DIR = _HERE / "results"
WS_WINDOW_PAD = 0.30


def _ws_eq_from_sounder(ws, sounder: dict) -> np.ndarray:
    sf_freqs = np.asarray(sounder.get("sounder_freqs", []), dtype=np.float64)
    H_db = np.asarray(sounder.get("H_db", []), dtype=np.float64)
    if len(sf_freqs) < 2:
        return np.ones(ws.M)
    Hlin = 10.0 ** (np.interp(ws.freqs, sf_freqs, H_db) / 20.0)
    Hlin = Hlin / (Hlin.max() + 1e-12)
    return np.clip(Hlin, 0.05, None)


def _decode_section(audio_nom, sec: dict, align: int, sounder: dict) -> dict:
    phy = sec["phy_params"]
    ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
    assert ws is not None, sec["name"]
    eq = _ws_eq_from_sounder(ws, sounder)

    meta = sec["meta"]
    rung = Rung(
        name=meta["rung"],
        M=meta["M"],
        K=meta["K"],
        rs_n=meta["rs_n"],
        rs_k=meta["rs_k"],
        frame_bytes=meta["frame_bytes"],
    )
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    frames_bits_ref, _ = codec.encode_payload(expected, rung)

    nsym = meta["frame_bits"] // ws.bits_per_sym
    test_audio = np.asarray(ws.modulate(np.zeros(meta["frame_bits"], np.uint8)), np.float32)
    flen = len(test_audio)
    pad = int(WS_WINDOW_PAD * SR)

    raw_err = 0
    raw_tot = 0
    frames_bits: list[np.ndarray] = []

    for fi, start in enumerate(sec["frame_starts"]):
        st = int(start) + align
        lo = max(0, st - pad)
        hi = min(len(audio_nom), st + flen + pad)
        window = np.asarray(audio_nom[lo:hi], dtype=np.float32)
        rb = np.asarray(
            _demod_frame_achievable(ws, eq, window, nsym, "contrast"),
            dtype=np.uint8,
        ).ravel()
        tb = frames_bits_ref[fi].astype(np.uint8)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        frames_bits.append(rb)

    recovered = codec.decode_payload(frames_bits, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    byte_errors = sum(a != b for a, b in zip(recovered, expected)) + abs(
        len(recovered) - len(expected)
    )
    return {
        "name": sec["name"],
        "role": sec.get("role", ""),
        "scheme": "widespace",
        "phy": sec["phy"],
        "llm_offset": sec.get("llm_offset", 0),
        "payload_bytes": len(expected),
        "n_frames": meta["n_frames"],
        "n_codewords": meta["n_codewords"],
        "raw_ber": raw_err / max(1, raw_tot),
        "rs_codewords_failed": cw_failed,
        "byte_errors": byte_errors,
        "byte_exact": recovered == expected,
        "rs_n": meta["rs_n"],
        "rs_k": meta["rs_k"],
        "gross_bps": sec.get("gross_bps"),
        "projected_net_bps": sec.get("projected_net_bps"),
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
    except Exception as exc:
        sounder = {"error": str(exc)}

    results = [_decode_section(audio_nom, sec, align, sounder) for sec in manifest["ws_payloads"]]

    if verbose:
        print(f"[m6_decode] {recording_path}")
        print(
            f"  recovered clock: {sync['speed']:.4f}x "
            f"(offset {sync['speed_offset'] * 100:+.2f}%), align {align:+d}"
        )
        if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
            print(
                f"  sounder: flutter {sounder['flutter_wrms_pct']:.2f}%, "
                f"SNR med {sounder['snr_db_median']:.1f} dB, "
                f"nf {sounder['noise_floor_dbfs']:.1f} dBFS"
            )
        print(
            f"\n  {'payload':<23} {'phy':<19} {'RS':>9} {'net':>7} "
            f"{'rawBER':>8} {'cwFail':>8} {'byteErr':>8} {'EXACT':>6}"
        )
        for r in results:
            rs = f"({r['rs_n']},{r['rs_k']})"
            cw = f"{r['rs_codewords_failed']}/{r['n_codewords']}"
            tag = "YES" if r["byte_exact"] else "no"
            print(
                f"  {r['name']:<23} {r['phy']:<19} {rs:>9} "
                f"{r['projected_net_bps']:7.0f} {r['raw_ber']:8.4f} "
                f"{cw:>8} {r['byte_errors']:8} {tag:>6}"
            )
        exact = [r for r in results if r["byte_exact"]]
        print(f"\n  byte-exact: {len(exact)}/{len(results)}")
        if exact:
            best = max(exact, key=lambda r: r["projected_net_bps"])
            print(
                f"  best exact rung: {best['name']} -> "
                f"{best['projected_net_bps']:.0f} bps"
            )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    out = {
        "recording": str(recording_path),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {
            k: v
            for k, v in (sounder or {}).items()
            if k not in ("H_db", "snr_db_per_tone", "sounder_freqs")
        },
        "payloads": results,
        "n_byte_exact": sum(r["byte_exact"] for r in results),
        "n_payloads": len(results),
    }
    json_path = RESULTS_DIR / f"m6_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m6_decode] wrote {json_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape-playback WAV or master6.wav")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, args.out_tag)
