#!/usr/bin/env python3
"""Master + sequence the B-side concept album.

Steps:
  1. Verify all 9 tracks exist (stereo 48 kHz). Flag any missing.
  2. Loudness-match each track to RMS -15 dBFS, then re-limit (soft-knee)
     to a peak ceiling of -1 dBFS. Because the limiter pulls RMS down
     slightly, we iterate the make-up gain so the *post-limit* RMS lands
     on -15 dBFS for a consistent, even album level. Re-write each WAV
     in place (PCM_16).
  3. Concatenate t1..t9 in order with 2.5 s of digital silence between
     tracks -> SIDE_B_album.wav (single reel). Report total minutes.

Deterministic, no RNG. python3 + numpy + soundfile only.
"""
import os
import sys

import numpy as np
import soundfile as sf

SR = 48000
TARGET_RMS_DB = -15.0
CEILING_DB = -1.0          # peak ceiling after limiting
KNEE_FRAC = 0.80           # soft knee starts at 80% of ceiling
GAP_S = 2.5                # silence between tracks
BUDGET_MIN = 34.0

DIR = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB"
TRACKS = [
    ("t1.wav", "Leader Tape"),
    ("t2.wav", "Pilot Tone"),
    ("t3.wav", "Wow & Flutter"),
    ("t4.wav", "Three Seventy-Five"),
    ("t5.wav", "Preamble"),
    ("t6.wav", "Byte-Exact"),
    ("t7.wav", "Reed-Solomon"),
    ("t8.wav", "Diffuse Reverb"),
    ("t9.wav", "End Chirp"),
]
ALBUM = os.path.join(DIR, "SIDE_B_album.wav")


def db(x):
    return 20.0 * np.log10(max(float(x), 1e-12))


def rms_lin(x):
    return float(np.sqrt(np.mean(x ** 2)))


def soft_limit(x, ceiling, knee_frac=KNEE_FRAC):
    """Soft-knee limiter: identity below knee, tanh squash asymptotic to ceiling."""
    k = knee_frac * ceiling
    a = np.abs(x)
    over = a > k
    y = x.copy()
    y[over] = np.sign(x[over]) * (k + (ceiling - k) * np.tanh((a[over] - k) / (ceiling - k)))
    return y


def master_track(x, target_lin, ceiling_lin):
    """Make-up gain to target RMS, soft-limit to ceiling, iterate make-up so the
    post-limit RMS lands on target. Returns (y, gain_db_applied)."""
    gain = target_lin / max(rms_lin(x), 1e-12)
    y = soft_limit(x * gain, ceiling_lin)
    # Two correction passes: limiter shaves RMS, nudge gain back up.
    for _ in range(6):
        r = rms_lin(y)
        if abs(db(r) - TARGET_RMS_DB) < 0.05:
            break
        gain *= target_lin / max(r, 1e-12)
        y = soft_limit(x * gain, ceiling_lin)
    return y, db(gain)


def main():
    target_lin = 10 ** (TARGET_RMS_DB / 20.0)
    ceiling_lin = 10 ** (CEILING_DB / 20.0)

    missing = [fn for fn, _ in TRACKS if not os.path.exists(os.path.join(DIR, fn))]
    if missing:
        print("MISSING TRACKS:", missing)
        return 2

    mastered = []
    print("=== PER-TRACK MASTER (RMS -15 dBFS, peak ceiling -1 dBFS) ===")
    for fn, title in TRACKS:
        path = os.path.join(DIR, fn)
        x, sr = sf.read(path, always_2d=True)
        assert sr == SR, f"{fn}: sr {sr} != {SR}"
        assert x.shape[1] == 2, f"{fn}: not stereo"
        assert np.isfinite(x).all(), f"{fn}: non-finite samples"
        peak_in, rms_in = float(np.max(np.abs(x))), rms_lin(x)

        y, gdb = master_track(x, target_lin, ceiling_lin)
        peak_out, rms_out = float(np.max(np.abs(y))), rms_lin(y)
        assert peak_out <= ceiling_lin + 1e-4, f"{fn}: peak {db(peak_out)} over ceiling"

        sf.write(path, y.astype(np.float64), sr, subtype="PCM_16")
        dur = y.shape[0] / sr
        mastered.append((fn, title, y, dur))
        print(f"  {fn:7s} {title:20s} dur={dur:7.2f}s  "
              f"in[peak {db(peak_in):6.2f} rms {db(rms_in):6.2f}]  "
              f"gain {gdb:+5.2f}  out[peak {db(peak_out):6.2f} rms {db(rms_out):6.2f}]")

    # Concatenate with 2.5 s silence between tracks (not before t1 / after t9).
    gap = np.zeros((int(round(GAP_S * SR)), 2), dtype=np.float64)
    parts = []
    for i, (_, _, y, _) in enumerate(mastered):
        if i > 0:
            parts.append(gap)
        parts.append(y)
    album = np.concatenate(parts, axis=0)
    sf.write(ALBUM, album.astype(np.float64), SR, subtype="PCM_16")

    total_s = album.shape[0] / SR
    total_min = total_s / 60.0
    apeak, arms = float(np.max(np.abs(album))), rms_lin(album)
    print("\n=== ALBUM ===")
    print(f"  file        : {ALBUM}")
    print(f"  total       : {total_s:.2f} s = {total_min:.3f} min")
    print(f"  budget       : {BUDGET_MIN} min  -> "
          + ("OK, under budget" if total_min <= BUDGET_MIN
             else f"OVER by {total_min - BUDGET_MIN:.3f} min"))
    print(f"  album peak  : {db(apeak):.2f} dBFS   album rms: {db(arms):.2f} dBFS")
    print(f"  gaps        : 8 x {GAP_S}s silence between tracks")

    # 10-band spectral balance + onset rate of the whole reel (QA).
    spectral_qa(album, SR)
    return 0


def spectral_qa(x, sr):
    mono = x.mean(axis=1)
    # 10 log-spaced bands 30 Hz .. ~20 kHz.
    edges = np.geomspace(30, 20000, 11)
    N = 1 << 16
    win = np.hanning(N)
    # average a few windows across the file
    step = max(1, (len(mono) - N) // 40)
    acc = np.zeros(N // 2 + 1)
    cnt = 0
    for s in range(0, len(mono) - N, step):
        seg = mono[s:s + N] * win
        acc += np.abs(np.fft.rfft(seg)) ** 2
        cnt += 1
    psd = acc / max(cnt, 1)
    freqs = np.fft.rfftfreq(N, 1 / sr)
    print("  10-band spectral balance (relative dB):")
    bands = []
    for i in range(10):
        lo, hi = edges[i], edges[i + 1]
        m = (freqs >= lo) & (freqs < hi)
        e = psd[m].sum() if m.any() else 1e-20
        bands.append(e)
    bdb = 10 * np.log10(np.array(bands) / max(bands) + 1e-12)
    for i in range(10):
        bar = "#" * int(max(0, bdb[i] + 60) / 2)
        print(f"    {edges[i]:7.0f}-{edges[i+1]:7.0f} Hz : {bdb[i]:6.1f} dB {bar}")
    # crude onset rate over the whole reel
    fr = 1024
    env = np.array([np.sqrt(np.mean(mono[i:i + fr] ** 2))
                    for i in range(0, len(mono) - fr, fr)])
    denv = np.diff(env)
    thr = denv.std() * 1.5
    onsets = int(np.sum(denv > thr))
    print(f"  onset rate  : {onsets / (len(mono)/sr):.2f} onsets/s over full reel")


if __name__ == "__main__":
    sys.exit(main())
