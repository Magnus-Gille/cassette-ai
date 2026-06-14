"""m7_decode.py -- recover the MERGED master7 (m5+m6) ladder from a captured WAV.

master7 carries both challengers' rungs under one global sync, each section
tagged with its own `phy_params`. This decoder reuses the per-rung section
decoder from m6_decode (which already builds the right WS geometry per section),
just pointed at master7_manifest.json, and adds a per-source (m5 / m6) summary.

Usage:
    python3 experiments/tape_v2/m7_decode.py experiments/tape_v2/master7.wav
    python3 experiments/tape_v2/m7_decode.py experiments/tape_v2/captures/tape7_run1.wav
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
from m6_decode import _decode_section  # noqa: E402  (per-rung WS section decoder)

SR = codec.FS
MANIFEST_PATH = _HERE / "master7_manifest.json"
RESULTS_DIR = _HERE / "results"


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
        r = _decode_section(audio_nom, sec, align, sounder)
        r["source"] = sec.get("source", "")
        results.append(r)

    if verbose:
        print(f"[m7_decode] {recording_path}")
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
            f"\n  {'payload':<16} {'src':<3} {'phy':<19} {'RS':>9} {'net':>7} "
            f"{'rawBER':>8} {'cwFail':>9} {'byteErr':>8} {'EXACT':>6}"
        )
        for r in results:
            rs = f"({r['rs_n']},{r['rs_k']})"
            cw = f"{r['rs_codewords_failed']}/{r['n_codewords']}"
            tag = "YES" if r["byte_exact"] else "no"
            print(
                f"  {r['name']:<16} {r['source']:<3} {r['phy']:<19} {rs:>9} "
                f"{r['projected_net_bps']:7.0f} {r['raw_ber']:8.4f} "
                f"{cw:>9} {r['byte_errors']:8} {tag:>6}"
            )
        for src in ("m5", "m6"):
            sub = [r for r in results if r["source"] == src]
            if sub:
                ex = [r for r in sub if r["byte_exact"]]
                line = f"\n  [{src}] byte-exact: {len(ex)}/{len(sub)}"
                if ex:
                    best = max(ex, key=lambda r: r["projected_net_bps"])
                    line += f"  best: {best['name']} -> {best['projected_net_bps']:.0f} bps"
                print(line)
        allex = [r for r in results if r["byte_exact"]]
        print(f"\n  TOTAL byte-exact: {len(allex)}/{len(results)}")
        if allex:
            best = max(allex, key=lambda r: r["projected_net_bps"])
            full_min = 153823 * 8 / best["projected_net_bps"] / 60
            print(
                f"  fastest exact rung: {best['name']} ({best['phy']}) "
                f"-> {best['projected_net_bps']:.0f} bps "
                f"=> full 153 KB LLM in ~{full_min:.1f} min"
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
    json_path = RESULTS_DIR / f"m7_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m7_decode] wrote {json_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape-playback WAV or master7.wav")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, args.out_tag)
