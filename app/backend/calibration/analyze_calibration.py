"""analyze_calibration.py — Analyze a calibration recording.

Uses the same analyze_master2.py sounder functions (chirp sync + sounder metrics)
to measure the channel quality of a calibration capture.

Prints a JSON object to stdout; the server parses it.

Usage:
    python3 app/backend/calibration/analyze_calibration.py <recording.wav>
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from fractions import Fraction

# Bootstrap paths so we can import analyze_master2
HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
TAPE_V2 = REPO_ROOT / "experiments" / "tape_v2"

for _p in [
    str(TAPE_V2),
    str(REPO_ROOT / "src"),
    str(REPO_ROOT / "tests" / "e2e"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import analyze_master2 as am2   # noqa: E402

META_PATH = HERE / "calibration_meta.json"
SR = 48_000


def analyze(wav_path: str) -> dict:
    """Run chirp sync + sounder analysis on a calibration recording.

    Returns a metrics dict that the server grades against grading.json.
    Keys match what analyze_master2.analyze_sounder() emits:
      snr_db_median, snr_db_p10, frac_below_8db, noise_floor_dbfs,
      flutter_wrms_pct (None — no deck flutter in Stage A),
      clock_ratio, lossless.
    """
    meta = json.loads(META_PATH.read_text())

    audio, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator).astype(np.float32)

    # Build a minimal manifest that looks like the master8 manifest
    # so we can reuse global_sync_and_resample + analyze_sounder.
    chirp_info = meta["chirp"]

    # Find chirp sections from meta
    up_sec = next((s for s in meta["sections"] if s["name"] == "global_chirp_up"), None)
    down_sec = next((s for s in meta["sections"] if s["name"] == "global_chirp_down"), None)

    tx_chirp0 = up_sec["start_sample"] if up_sec else int(1.0 * SR)
    tx_chirp1 = down_sec["start_sample"] if down_sec else int((meta["duration_sec"] - 1.2) * SR)

    # Locate sounder repetitions in meta
    sounder_secs = [
        {
            "kind": "multitone",
            "start": s["start_sample"],
            "length": s["length_samples"],
            "info": s["info"],
        }
        for s in meta["sections"]
        if s["name"].startswith("sounder_rep")
    ]

    cal_manifest = {
        "SR": SR,
        "tape": "calibration",
        "tx_chirp0": tx_chirp0,
        "tx_chirp1": tx_chirp1,
        "sounder_sections": sounder_secs,
        "global_chirp": {
            "T": chirp_info["T"],
            "f0": chirp_info["f0"],
            "f1": chirp_info["f1"],
        },
    }

    try:
        sync = am2.global_sync_and_resample(audio, cal_manifest)
    except Exception as exc:
        # If sync fails, return a minimal error result
        return {
            "error": f"Chirp sync failed: {exc}",
            "snr_db_median": None,
            "snr_db_p10": None,
            "frac_below_8db": None,
            "noise_floor_dbfs": None,
            "flutter_wrms_pct": None,
            "clock_ratio": None,
            "lossless": True,
        }

    try:
        sounder = am2.analyze_sounder(sync["audio_nominal"], cal_manifest, sync)
    except Exception as exc:
        sounder = {"error": str(exc)}

    metrics = {
        "snr_db_median": sounder.get("snr_db_median"),
        "snr_db_p10": sounder.get("snr_db_p10"),
        "frac_below_8db": sounder.get("frac_below_8db"),
        "noise_floor_dbfs": sounder.get("noise_floor_dbfs"),
        "flutter_wrms_pct": None,   # Stage A: no tape/deck -> no flutter
        "clock_ratio": sync.get("clock_ratio"),
        "speed_offset_pct": (sync.get("speed_offset") or 0.0) * 100.0,
        "lossless": True,            # the calibration WAV is always lossless
        "sounder_error": sounder.get("error"),
    }
    return metrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: analyze_calibration.py <recording.wav>"}))
        sys.exit(1)
    result = analyze(sys.argv[1])
    print(json.dumps(result))
