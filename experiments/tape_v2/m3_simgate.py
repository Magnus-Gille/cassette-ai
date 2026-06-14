"""m3_simgate.py — VALIDATION GATE B: push master3.wav through a sim cassette
channel at the clean-real-capture regime (~0.44% flutter + a small speed offset)
and decode, reporting which ladder payloads survive byte-exact.

This mirrors w5_flutter_sweep's channel application (cassette_channel with a
prescribed wow_flutter_wrms and a deck-clock resample) but applies it to the WHOLE
recordable master, then runs the real m3_decode pipeline (chirp sync recovers the
speed offset, per-frame flutter-tracked demod, global RS-interleave decode).
"""
from __future__ import annotations

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

import channel as ch                  # noqa: E402
import m3_decode                      # noqa: E402

SR = 48_000
MASTER = _HERE / "master3.wav"
SIM_WAV = _HERE / "_sim_master3.wav"


def make_sim(flutter=0.0044, speed=0.97, snr=32.0, bw=9000.0,
             burst_rate=0.5, burst_ms=8.0, seed=7) -> str:
    audio, sr = sf.read(str(MASTER), dtype="float32", always_2d=False)
    assert sr == SR
    # Deck-clock speed offset: a deck at `speed` x nominal compresses time.
    fr = Fraction(speed).limit_denominator(4000)
    x = resample_poly(audio.astype(np.float64), fr.numerator, fr.denominator)
    y = ch.cassette_channel(x, fs=SR, snr_db=snr, wow_flutter_wrms=flutter,
                            bandwidth_hz=bw, burst_rate_per_s=burst_rate,
                            burst_length_ms=burst_ms, seed_offset=seed).astype(np.float32)
    pk = float(np.max(np.abs(y)))
    if pk > 1e-9:
        y = (y / pk * 0.95).astype(np.float32)
    sf.write(str(SIM_WAV), y, SR, subtype="FLOAT")
    return str(SIM_WAV)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--flutter", type=float, default=0.0044)
    ap.add_argument("--speed", type=float, default=0.97)
    ap.add_argument("--snr", type=float, default=32.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    print(f"[simgate] flutter={args.flutter*100:.2f}% speed={args.speed}x "
          f"snr={args.snr}dB seed={args.seed}")
    p = make_sim(flutter=args.flutter, speed=args.speed, snr=args.snr, seed=args.seed)
    m3_decode.decode(p, out_tag=f"sim_fl{int(args.flutter*1e4)}_sp{int(args.speed*100)}")
