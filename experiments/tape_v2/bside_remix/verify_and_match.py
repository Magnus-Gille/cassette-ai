#!/usr/bin/env python3
"""Verify + loudness-match the B-side remix WAVs.

Checks per track: duration 90-150 s, no NaN/Inf, peak <= -1 dBFS.
Then RMS-aligns every track to -15 dBFS and re-limits with a soft-knee
limiter (ceiling -1 dBFS) so the loudness match cannot push peaks over.
Re-writes the WAVs in place (stereo 48 kHz 16-bit). Deterministic, no RNG.
"""
import json
import sys

import numpy as np
import soundfile as sf

FILES = [
    "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/bside_ambient.wav",
    "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/bside_techno.wav",
    "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/bside_melodic.wav",
    "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/bside_concrete.wav",
]
TARGET_RMS_DB = -15.0
CEILING_DB = -1.0      # peak ceiling after limiting
KNEE_FRAC = 0.70       # soft knee starts at 70% of ceiling


def db(x):
    return 20.0 * np.log10(max(x, 1e-12))


def soft_limit(x, ceiling, knee_frac=KNEE_FRAC):
    """Soft-knee limiter: identity below knee, tanh squash up to < ceiling."""
    k = knee_frac * ceiling
    a = np.abs(x)
    over = a > k
    y = x.copy()
    y[over] = np.sign(x[over]) * (k + (ceiling - k) * np.tanh((a[over] - k) / (ceiling - k)))
    return y


def main():
    target_lin = 10 ** (TARGET_RMS_DB / 20.0)
    ceiling_lin = 10 ** (CEILING_DB / 20.0)
    report = []
    ok = True
    for path in FILES:
        x, sr = sf.read(path, always_2d=True)
        name = path.split("/")[-1]
        dur = x.shape[0] / sr
        checks = {}
        checks["sr_48k"] = (sr == 48000)
        checks["stereo"] = (x.shape[1] == 2)
        checks["finite"] = bool(np.isfinite(x).all())
        checks["duration_90_150"] = (90.0 <= dur <= 150.0)
        peak_in = float(np.max(np.abs(x)))
        rms_in = float(np.sqrt(np.mean(x ** 2)))
        checks["peak_le_-1dBFS_in"] = (peak_in <= ceiling_lin + 1e-4)

        # RMS align to -15 dBFS, then soft-limit to the -1 dBFS ceiling.
        gain = target_lin / max(rms_in, 1e-12)
        y = x * gain
        y = soft_limit(y, ceiling_lin)
        peak_out = float(np.max(np.abs(y)))
        rms_out = float(np.sqrt(np.mean(y ** 2)))
        checks["peak_le_-1dBFS_out"] = (peak_out <= ceiling_lin + 1e-4)

        sf.write(path, y.astype(np.float64), sr, subtype="PCM_16")
        row = {
            "file": name,
            "seconds": round(dur, 3),
            "sr": sr,
            "peak_in_dB": round(db(peak_in), 2),
            "rms_in_dB": round(db(rms_in), 2),
            "gain_dB": round(db(gain), 2),
            "peak_out_dB": round(db(peak_out), 2),
            "rms_out_dB": round(db(rms_out), 2),
            "checks": checks,
        }
        ok &= all(checks.values())
        report.append(row)
        print(json.dumps(row))
    print("ALL_OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
