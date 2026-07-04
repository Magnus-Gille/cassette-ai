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

AUTO mode (arm on the START chirp, stop on the END chirp -- hands-free):
    python3 capture_uca.py <max_seconds> <out.wav> --auto
  Listens for the global up-chirp (500->5000 Hz, 0.2 s); once heard it starts
  writing (with a short pre-roll so the chirp itself is captured) and keeps
  recording until it hears the global down-chirp (5000->500 Hz), then writes a
  short tail and stops. `<max_seconds>` is a HARD safety cap: if no start chirp
  is ever heard, or the end chirp is missed, it stops at the cap so you are never
  stuck. Detection is a normalized matched filter on the summed-mono downmix
  (level-independent), so it works on either the wired or the acoustic path.
"""
import argparse
import queue
import sys
import time
from collections import deque

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy.signal import correlate, chirp as _scipy_chirp, resample_poly
from fractions import Fraction

# --- global chirp params (MUST match analyze_master2 / fullspectrum_master) ---
CHIRP_T = 0.20
CHIRP_F0 = 500.0
CHIRP_F1 = 5000.0

# Cassette decks run a few % off nominal speed (the "we are rewind" deck measured
# 0.98x). A fixed-speed matched filter smears on a speed-offset chirp: the 0.98x
# tape scored only 0.34 against a 1.00x template but 0.67 against a 0.98x one.
# So detection correlates against a BANK of speed-scaled templates and takes the
# best -- level-independent AND speed-tolerant. Covers +-8% (worn deck margin).
SPEED_GRID = tuple(round(s, 3) for s in np.arange(0.92, 1.081, 0.02))


def _ref_chirp(up: bool, sr: int, speed: float = 1.0) -> np.ndarray:
    """Unit-energy, zero-mean reference chirp resampled to `speed` (matched
    filter template for a deck running at that fractional speed)."""
    n = int(CHIRP_T * sr)
    t = np.arange(n, dtype=np.float64) / sr
    f0, f1 = (CHIRP_F0, CHIRP_F1) if up else (CHIRP_F1, CHIRP_F0)
    r = _scipy_chirp(t, f0=f0, f1=f1, t1=CHIRP_T, method="linear").astype(np.float64)
    if abs(speed - 1.0) > 1e-4:
        fr = Fraction(speed).limit_denominator(2000)
        r = resample_poly(r, fr.numerator, fr.denominator)
    r -= r.mean()
    r /= (np.sqrt((r * r).sum()) + 1e-12)
    return r


def _build_bank(up: bool, sr: int, speeds=SPEED_GRID):
    """List of (speed, template) matched filters over the speed grid."""
    return [(sp, _ref_chirp(up, sr, sp)) for sp in speeds]


def _norm_xcorr(seg: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Sliding normalized cross-correlation of unit-energy zero-mean `ref`
    against `seg`. Result in [0,1]; peak ~ how chirp-like each window is."""
    n = len(ref)
    ones = np.ones(n)
    num = correlate(seg, ref, mode="valid", method="fft")
    s1 = correlate(seg, ones, mode="valid", method="fft")
    s2 = correlate(seg * seg, ones, mode="valid", method="fft")
    var = s2 - s1 * s1 / n            # local energy after mean removal
    denom = np.sqrt(np.maximum(var, 1e-9))
    return np.abs(num) / denom


def _best_match(seg: np.ndarray, bank, K: int):
    """Best (peak_ncc, abs_offset_into_seg, speed) over a template bank.
    abs_offset is the chirp-start index measured from seg[0] (i.e. base - K)."""
    best_pk, best_i, best_sp = -1.0, 0, None
    for sp, ref in bank:
        c = _norm_xcorr(seg, ref)
        i = int(np.argmax(c))
        pk = float(c[i])
        if pk > best_pk:
            best_pk, best_i, best_sp = pk, i, sp
    return best_pk, best_i, best_sp


def pick_device(name: str):
    for i, d in enumerate(sd.query_devices()):
        if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
            return i, d
    ins = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
    sys.exit(f"no input device matching {name!r}. available inputs: {ins}")


def _mono(block: np.ndarray) -> np.ndarray:
    return block.mean(axis=1) if block.ndim > 1 else np.asarray(block).ravel()


def capture_fixed(a, dev, info) -> None:
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


def capture_auto(a, dev, info) -> None:
    """Arm on the START chirp, stop on the END chirp (see module docstring)."""
    sr = a.rate
    up_bank = _build_bank(True, sr)        # speed-robust START-chirp matched filters
    dn_bank_full = _build_bank(False, sr)  # END-chirp bank (narrowed once armed)
    dn_bank = dn_bank_full
    # carry must be long enough for the LONGEST (slowest-speed) template
    K = max(len(r) for _, r in up_bank + dn_bank_full) - 1
    thr = a.threshold
    pre = int(a.pre_roll * sr)
    tail = int(a.tail * sr)
    min_gap = int(a.min_gap * sr)
    hard_max = int(a.seconds * sr)

    q: "queue.Queue" = queue.Queue()
    xruns = 0

    def cb(indata, frames, time_info, status):
        nonlocal xruns
        if status:
            xruns += 1
        q.put(indata.copy())

    carry = np.zeros(K)          # last K mono samples (matched-filter continuity)
    n_recv = 0                   # abs samples received so far
    state = "SEARCH"
    pre_blocks: "deque" = deque()  # (abs_start, raw_block) ring for pre-roll
    pre_have = 0
    sf_out = None
    up_idx = None
    stop_at = None
    peak_up = 0.0
    peak_dn = 0.0
    peak = 0.0                   # overall signal peak (clip / level indicator)

    def _dbfs(x):
        return 20 * np.log10(x + 1e-12)

    def _status(msg):
        print("\r\033[K" + msg, end="", file=sys.stderr, flush=True)

    print(f"AUTO capture @ {sr} Hz {a.channels}ch from [{dev}] {info['name']} -> {a.out}",
          file=sys.stderr)
    print("  listening for START chirp (500->5000 Hz)... press PLAY on the deck now.",
          file=sys.stderr)
    last_status = 0.0
    t_armed = None
    try:
        with sd.InputStream(samplerate=sr, channels=a.channels, device=dev,
                            dtype="float32", callback=cb, blocksize=a.blocksize):
            while True:
                block = q.get()
                L = len(block)
                base = n_recv
                blk_peak = float(np.abs(block).max())
                peak = max(peak, blk_peak)
                now = time.monotonic()
                seg = np.concatenate([carry, _mono(block)])

                if state == "SEARCH":
                    pk, i, sp = _best_match(seg, up_bank, K)
                    peak_up = max(peak_up, pk)
                    if now - last_status > 0.5:
                        _status(f"  listening for START chirp...  "
                                f"level {_dbfs(blk_peak):6.1f} dBFS   best-match {pk:.2f}")
                        last_status = now
                    if pk >= thr:
                        idx_up = base - K + i
                        up_idx = max(0, idx_up)
                        t_armed = now
                        # narrow the END-chirp bank to the detected deck speed +-1 grid
                        # step (the end chirp runs at the same speed as the start)
                        dn_bank = [(s, r) for (s, r) in dn_bank_full
                                   if abs(s - sp) <= 0.021] or dn_bank_full
                        sf_out = sf.SoundFile(a.out, "w", samplerate=sr,
                                              channels=a.channels, subtype="FLOAT")
                        start_abs = max(0, idx_up - pre)
                        pre_blocks.append((base, block))
                        for bs, blk in pre_blocks:      # backfill pre-roll -> chirp
                            if bs + len(blk) <= start_abs:
                                continue
                            s0 = max(0, start_abs - bs)
                            sf_out.write(blk[s0:])
                        state = "REC"
                        print(f"\r\033[K  ARMED: start chirp @ {idx_up/sr:.1f}s "
                              f"(ncc={pk:.2f}, deck speed ~{sp:.2f}x) -> recording",
                              file=sys.stderr)
                    else:
                        pre_blocks.append((base, block)); pre_have += L
                        while len(pre_blocks) > 1 and \
                                (pre_have - len(pre_blocks[0][1])) >= pre + 2 * L:
                            _, blk = pre_blocks.popleft(); pre_have -= len(blk)
                        if base + L > hard_max:
                            print("", file=sys.stderr)
                            sys.exit(f"AUTO: no START chirp within {a.seconds:.0f}s "
                                     f"(best ncc={peak_up:.2f}). Check wiring / level / "
                                     f"that PLAY was pressed, then retry.")
                else:  # REC
                    sf_out.write(block)
                    elapsed = base - up_idx
                    scanning = elapsed >= min_gap
                    if stop_at is None and scanning:
                        pk, i, _ = _best_match(seg, dn_bank, K)
                        peak_dn = max(peak_dn, pk)
                        if pk >= thr:
                            idx_dn = base - K + i
                            stop_at = idx_dn + tail
                            print(f"\r\033[K  END chirp @ {idx_dn/sr:.1f}s (ncc={pk:.2f}) "
                                  f"-> writing {a.tail:.1f}s tail then stop",
                                  file=sys.stderr)
                    if stop_at is None and now - last_status > 0.5:
                        phase = "listening for END chirp" if scanning else "recording body"
                        _status(f"  recording +{elapsed/sr:5.1f}s  "
                                f"level {_dbfs(blk_peak):6.1f} dBFS   {phase}...")
                        last_status = now
                    if stop_at is not None and base + L >= stop_at:
                        break
                    if base + L > hard_max:
                        print(f"\r\033[K  AUTO: hard cap {a.seconds:.0f}s reached, END chirp "
                              f"not detected (best ncc={peak_dn:.2f}) -- stopping.",
                              file=sys.stderr)
                        break

                carry = seg[-K:]
                n_recv += L
    except KeyboardInterrupt:
        print("\r\033[K  Ctrl-C -- stopping capture.", file=sys.stderr)
    finally:
        if sf_out is not None:
            sf_out.close()

    if sf_out is None:
        sys.exit("AUTO: stopped before arming -- no start chirp captured (no file written).")
    dur = None
    try:
        dur = sf.info(a.out).duration
    except Exception:
        pass
    pk_db = 20 * np.log10(peak + 1e-12)
    level = ("CLIPPING - lower the level!" if peak >= 0.99 else
             "hot" if pk_db > -3 else
             "good" if pk_db > -20 else
             "LOW - raise the level" if pk_db > -40 else
             "VERY LOW - check wiring/level")
    print(f"\r\033[Kdone: wrote {a.out}" + (f" ({dur:.1f}s)" if dur else "") +
          f", peak {peak:.3f} ({pk_db:.1f} dBFS -> {level}), xrun-events {xruns}",
          file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", type=float,
                    help="fixed mode: capture length; auto mode: HARD safety cap")
    ap.add_argument("out")
    ap.add_argument("--device", default="USB Audio CODEC")
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--channels", type=int, default=2)
    ap.add_argument("--blocksize", type=int, default=2048)
    ap.add_argument("--auto", action="store_true",
                    help="arm on START chirp, stop on END chirp (hands-free)")
    ap.add_argument("--threshold", type=float, default=0.30,
                    help="matched-filter detection threshold (0..1)")
    ap.add_argument("--pre-roll", type=float, default=1.0,
                    help="seconds kept before the START chirp")
    ap.add_argument("--tail", type=float, default=1.5,
                    help="seconds kept after the END chirp")
    ap.add_argument("--min-gap", type=float, default=80.0,
                    help="min seconds after START before scanning for END chirp "
                         "(guards against false end-detection mid-signal)")
    a = ap.parse_args()

    dev, info = pick_device(a.device)
    if a.auto:
        capture_auto(a, dev, info)
    else:
        capture_fixed(a, dev, info)


if __name__ == "__main__":
    main()
