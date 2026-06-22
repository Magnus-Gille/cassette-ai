#!/usr/bin/env python3
"""Sample-accurate capture from the UCA222 (or any input device) via PortAudio.

WHY NOT ffmpeg: on this machine ffmpeg's avfoundation capture drops ~11.5% of
samples (verified 2026-06-22 -- a 16 s grab yields only ~14.2 s of audio, every
run, tones un-shifted so it's dropped samples not a resample). PortAudio
(sounddevice) respects the device clock and keeps every sample (768000 samples
arrive in 16.26 s wall-clock = true ~48 kHz). Use THIS for all UCA222 line-in
captures, not ffmpeg.

Streams straight to disk (low RAM) so it is safe for a full ~17 min tape side.

Usage:
    python3 capture_uca.py <seconds> <out.wav> [--device "USB Audio CODEC"]
                           [--rate 48000] [--channels 2]
"""
import argparse
import queue
import sys

import numpy as np
import soundfile as sf
import sounddevice as sd


def pick_device(name: str):
    for i, d in enumerate(sd.query_devices()):
        if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
            return i, d
    ins = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
    sys.exit(f"no input device matching {name!r}. available inputs: {ins}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", type=float)
    ap.add_argument("out")
    ap.add_argument("--device", default="USB Audio CODEC")
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--channels", type=int, default=2)
    ap.add_argument("--blocksize", type=int, default=2048)
    a = ap.parse_args()

    dev, info = pick_device(a.device)
    q: "queue.Queue" = queue.Queue()
    xruns = 0

    def cb(indata, frames, time_info, status):
        nonlocal xruns
        if status:
            xruns += 1
            print(f"  PortAudio status: {status}", file=sys.stderr)
        q.put(indata.copy())

    target = int(a.seconds * a.rate)
    got = 0
    peak = 0.0
    print(f"capture {a.seconds:.1f}s @ {a.rate} Hz, {a.channels}ch "
          f"from [{dev}] {info['name']} -> {a.out}", file=sys.stderr)
    with sf.SoundFile(a.out, "w", samplerate=a.rate, channels=a.channels,
                      subtype="FLOAT") as f, \
         sd.InputStream(samplerate=a.rate, channels=a.channels, device=dev,
                        dtype="float32", callback=cb, blocksize=a.blocksize):
        while got < target:
            block = q.get()
            f.write(block)
            got += len(block)
            peak = max(peak, float(np.abs(block).max()))
    print(f"done: {got} samples ({got/a.rate:.3f}s), peak {peak:.3f} "
          f"({20*np.log10(peak + 1e-12):.1f} dBFS), xrun-events {xruns}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
