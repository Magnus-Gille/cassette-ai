#!/usr/bin/env python3
"""
remix_concrete.py — B-side art: MUSIQUE CONCRETE remix of the real tape10 capture.

Every sound in this piece is the actual cassette playing back master10
(tape10_run1.wav: deck + room + tape warmth, flutter 0.42%). No synthesis.
Techniques:
  * granular resynthesis (40-200 ms Hann grains) of the real DQPSK sections,
    pitch-quantized to an F# drone chord by resampling — the carriers sit on a
    375 Hz (F#4+23c) harmonic grid, so simple ratios {1/8,1/6,1/4,1/3,1/2,2/3,
    3/4,1,3/2,2} land every grain on F# / B / C# chord tones.
  * rhythm by GATING the real d2x signal with patterns derived from the measured
    preamble anatomy (tick 0.25 s + gap 0.12 s, frame period T = 0.984208 s,
    61 BPM). The gate grid is phase-locked to the capture's own preambles.
  * spectral freeze (FFT magnitude hold, random-phase OLA) of the Schroeder
    sounder splash — the frozen 64-tone spectrum is the drone bed.
  * THE REVEAL: 62-70 s the untouched real signal (N512 rung r0, preambles and
    all) surfaces dry in the middle of the piece.
  * the real 500->5000 Hz global chirps (up at capture 20.863 s, down at
    380.624 s) as risers / closing gestures, echoed on the frame grid.

Seed: 20260612 (logged below). Output: bside_concrete.wav, stereo 48k/16bit,
128 s, peak <= -1 dBFS, RMS ~ -15 dBFS, 2 s fade-in / 4 s fade-out.
"""

import numpy as np
import soundfile as sf
from scipy import signal as sig
from scipy.ndimage import median_filter

SEED = 20260612
rng = np.random.default_rng(SEED)
print(f"[seed] {SEED}")

SR = 48000
CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/bside_concrete.wav"

# ---- palette facts (from palette.json, measured on the real capture) --------
T = 0.984208                # measured d2x frame period (s)  -> 60.97 BPM
D2X_PRE0 = 205.3075         # first d2x preamble (capture s)
N512_PRE0 = 46.8634         # first N512 preamble (capture s)
N512_T = 1.372896           # measured N512 frame period (s)
CHIRP_UP_T = 20.8628        # real up-chirp 500->5000 Hz, 0.2 s
CHIRP_DN_T = 380.6237       # real down-chirp
SCHROEDER_T = 21.9636       # Schroeder 64-tone sounder splash (3 s)
N512_R0 = (46.88, 81.22)    # N512 rung r0 (capture s)
N512_R9 = (345.37, 379.71)  # N512 tail canary
D2X_R5 = (205.35, 249.63)   # d2x rung r5

DUR = 128.0
N = int(DUR * SR)
L = np.zeros(N)
R = np.zeros(N)

cap, sr_in = sf.read(CAPTURE, dtype="float64")
assert sr_in == SR and cap.ndim == 1, "expected mono 48k capture"


# ---- helpers -----------------------------------------------------------------
def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-20))


def norm(x, target=0.1):
    return x * (target / rms(x))


def seg(t0, dur):
    a = int(t0 * SR)
    return cap[a:a + int(dur * SR)].copy()


def add(t, x, gain=1.0, pan=0.5):
    """Equal-power pan, pan in [0,1] (0=L)."""
    a = int(t * SR)
    if a >= N:
        return
    b = min(a + len(x), N)
    if a < 0:
        x = x[-a:]
        a = 0
    x = x[: b - a]
    L[a:b] += x * gain * np.cos(pan * np.pi / 2)
    R[a:b] += x * gain * np.sin(pan * np.pi / 2)


def resamp(x, ratio):
    """Playback-rate resample: ratio>1 -> higher pitch, shorter."""
    n_out = int(len(x) / ratio)
    idx = np.arange(n_out) * ratio
    return np.interp(idx, np.arange(len(x)), x)


def env_bp(n, points):
    """Breakpoint envelope: points = [(t_s, value), ...] over n samples."""
    t = np.arange(n) / SR
    ts = np.array([p[0] for p in points])
    vs = np.array([p[1] for p in points])
    return np.interp(t, ts, vs)


# ---- 1. spectral freeze of the Schroeder sounder ------------------------------
def spectral_freeze(src, dur, nfft=8192, ratio=1.0):
    """FFT magnitude hold: average magnitude spectrum of src, resynthesize with
    random phases per hop (OLA). ratio pitches the frozen slab by resampling."""
    win = np.hanning(nfft)
    mags = []
    for i in range(0, len(src) - nfft, nfft // 2):
        mags.append(np.abs(np.fft.rfft(src[i:i + nfft] * win)))
    mag = np.mean(mags, axis=0)
    n_out = int(dur * SR * ratio) + nfft  # render longer if we'll slow it down
    out = np.zeros(n_out + nfft)
    hop = nfft // 4
    for pos in range(0, n_out, hop):
        ph = rng.uniform(0, 2 * np.pi, len(mag))
        out[pos:pos + nfft] += np.fft.irfft(mag * np.exp(1j * ph), nfft) * win
    out = out[:n_out]
    if ratio != 1.0:
        out = resamp(out, ratio)
    return norm(out[: int(dur * SR)], 0.1)


print("[render] spectral freeze beds (Schroeder sounder, FFT magnitude hold)")
schroeder = seg(SCHROEDER_T + 0.2, 2.6)
# decorrelated L/R freeze bed, one octave down (dark wash), whole piece
bedL = spectral_freeze(schroeder, DUR, ratio=0.5)
bedR = spectral_freeze(schroeder, DUR, ratio=0.5)
bed_env = env_bp(N, [(0, 0.0), (3, 0.85), (20, 0.7), (46, 0.5), (61.5, 0.25),
                     (66, 0.15), (70.5, 0.35), (96, 0.8), (114, 1.0),
                     (124, 0.7), (128, 0.0)])
L += bedL * bed_env * 0.085
R += bedR * bed_env * 0.085

# freeze "moments": native-pitch swell early, two-octave-down swell late
mom1 = spectral_freeze(schroeder, 10.0, ratio=1.0)
mom1 *= np.hanning(len(mom1))
add(14.0, mom1, 0.10, 0.42)
mom2 = spectral_freeze(schroeder, 12.0, ratio=0.25)
mom2 *= np.hanning(len(mom2))
add(88.0, mom2, 0.14, 0.58)

# ---- 2. granular clouds: pitch-quantized grains of the real signal -----------
# Sources normalized once; grains inherit. All ratios are simple fractions so
# the 375 Hz carrier grid stays on the F#/B/C# drone chord.
src_d2x = norm(seg(D2X_R5[0] + 0.5, 43.0), 0.1)
src_n512 = norm(seg(N512_R0[0] + 0.5, 33.0), 0.1)
src_tail = norm(seg(N512_R9[0] + 0.5, 33.0), 0.1)


def grain_cloud(t0, t1, src, ratios, weights, dur_rng, dens_bp, gain_bp,
                pan_rng=(0.15, 0.85)):
    """Scatter Hann grains of `src` (real capture audio) between t0..t1.
    Each grain is resampled by a chord ratio = pitch quantization."""
    t = t0
    n_src = len(src)
    while t < t1:
        dens = np.interp(t, [p[0] for p in dens_bp], [p[1] for p in dens_bp])
        gain = np.interp(t, [p[0] for p in gain_bp], [p[1] for p in gain_bp])
        out_dur = rng.uniform(*dur_rng)
        ratio = rng.choice(ratios, p=weights)
        n_out = int(out_dur * SR)
        n_need = int(n_out * ratio) + 2
        if n_need < n_src:
            p0 = int(rng.integers(0, n_src - n_need))
            idx = np.arange(n_out) * ratio
            g = np.interp(idx, np.arange(n_need), src[p0:p0 + n_need])
            g *= np.hanning(n_out)
            add(t, g, gain, rng.uniform(*pan_rng))
        t += rng.exponential(1.0 / dens)


print("[render] granular clouds (pitch-quantized real-signal grains)")
# A: sub-drone emergence (d2x grains 2-3 octaves down -> F#/B/C# low chord)
grain_cloud(0.0, 22.0, src_d2x, [0.125, 1 / 6, 0.25, 1 / 3],
            [0.3, 0.2, 0.3, 0.2], (0.12, 0.20),
            [(0, 3), (22, 9)], [(0, 0.7), (22, 0.55)])
# B: grain chorale (N512 grains around native pitch, chord ratios)
grain_cloud(20.0, 46.5, src_n512, [0.5, 2 / 3, 0.75, 1.0, 1.5],
            [0.3, 0.15, 0.2, 0.25, 0.1], (0.08, 0.18),
            [(20, 4), (46.5, 14)], [(20, 0.4), (34, 0.55), (46.5, 0.55)])
# C: pointillist shards (short grains, wider ratio set, hard pans)
grain_cloud(46.3, 62.0, src_n512, [0.5, 0.75, 1.0, 1.5, 2.0],
            [0.25, 0.2, 0.25, 0.2, 0.1], (0.04, 0.08),
            [(46.3, 16), (62, 16)], [(46.3, 0.45), (62, 0.5)],
            pan_rng=(0.05, 0.95))
# E: re-submersion (darker: everything an octave-plus down)
grain_cloud(70.5, 96.0, src_d2x, [0.25, 1 / 3, 0.5, 2 / 3],
            [0.3, 0.2, 0.3, 0.2], (0.07, 0.15),
            [(70.5, 10), (96, 10)], [(70.5, 0.5), (96, 0.5)])
# F: dissolution (tail-canary grains, long + sparse)
grain_cloud(98.0, 126.0, src_tail, [0.25, 1 / 3, 0.5, 2 / 3],
            [0.35, 0.2, 0.3, 0.15], (0.16, 0.20),
            [(98, 7), (126, 1.0)], [(98, 0.5), (126, 0.45)])

# ---- 3. rhythm: gating the REAL signal with preamble-derived patterns --------
print("[render] preamble-locked gate rhythms")


def gated_stream(out_t0, out_t1, cap_t0, pattern_fn, gain, lp_hz=None):
    """Stream the real capture from cap_t0 at native rate; gate it with
    per-frame open windows derived from the preamble anatomy (0.25 s tick,
    0.12 s gap). cap_t0 sits on a real preamble, and out_t0 sits on the output
    frame grid, so the gates expose the capture's own ticks."""
    k0 = int(np.ceil(out_t0 / T))
    t_start = k0 * T
    n = int((out_t1 - t_start) * SR)
    a = int(cap_t0 * SR)
    stream = cap[a:a + n].copy()
    stream = norm(stream, 0.1)
    gate = np.zeros(n)
    n_frames = int((out_t1 - t_start) / T) + 1
    for j in range(n_frames):
        for (off, dur, g) in pattern_fn(k0 + j):
            ga = int((j * T + off) * SR)
            gb = int((j * T + off + dur) * SR)
            if ga >= n:
                break
            gate[ga:min(gb, n)] = g
    w = np.hanning(int(0.004 * SR))
    gate = sig.fftconvolve(gate, w / w.sum(), mode="same")
    out = stream * gate
    if lp_hz:
        sos = sig.butter(4, lp_hz, "lp", fs=SR, output="sos")
        out = sig.sosfilt(sos, out)
    add(t_start, out, gain, 0.5)


# pattern vocabulary: offsets literally from the preamble anatomy
TICK, GAP = 0.25, 0.12
DATA0 = TICK + GAP  # 0.37 s — where the data burst starts


def pat_B(k):  # sparse: tick + data-head every other frame
    ev = [(0.0, TICK, 1.0)]
    if k % 2 == 0:
        ev.append((DATA0, GAP, 0.8))
    return ev


def pat_C(k):  # dense machine ritual
    ev = [(0.0, TICK, 1.0), (DATA0, GAP, 0.9)]
    if k % 4 in (1, 3):
        ev.append((DATA0 + 0.205, 0.10, 0.8))
    if k % 4 == 2:
        ev.append((0.75 * T, 0.16, 0.85))
    if k % 8 == 7:
        ev.append((0.875 * T, 0.10, 0.9))
    return ev


def pat_E(k):  # dark: ticks + occasional long data slab
    ev = [(0.0, TICK, 1.0)]
    if k % 4 == 0:
        ev.append((DATA0, 0.55, 0.7))
    if k % 2 == 1:
        ev.append((0.5 * T, GAP, 0.6))
    return ev


gated_stream(30.0, 46.26, D2X_PRE0 + 2 * T, pat_B, 0.22)
gated_stream(46.26, 62.0, D2X_PRE0 + 18 * T, pat_C, 0.33)
gated_stream(70.8, 96.0, D2X_PRE0 + 6 * T, pat_E, 0.30, lp_hz=2600)

# sampled real preamble ticks as percussive hits on the frame grid
ticks = []
for m in (0, 4, 9, 16):
    x = seg(D2X_PRE0 + m * T - 0.004, 0.30)
    e = np.ones(len(x))
    e[: int(0.002 * SR)] = np.linspace(0, 1, int(0.002 * SR))
    e[int(0.20 * SR):] = np.linspace(1, 0, len(x) - int(0.20 * SR)) ** 2
    ticks.append(norm(x * e, 0.1))

for k in range(47, 63):  # section C: backbeat doubling, alternating pan
    add(k * T, ticks[k % 4], 0.24, 0.3 if k % 2 else 0.7)
    if k % 2 == 1:
        add(k * T + 0.5 * T, ticks[(k + 1) % 4], 0.16, 0.5)
for k in range(72, 98, 2):  # section E: every other frame
    add(k * T, ticks[k % 4], 0.18, 0.62 if k % 4 else 0.38)

# Schroeder splash as crash at section downbeats
splash = norm(seg(SCHROEDER_T + 0.3, 1.2), 0.1)
splash *= np.exp(-np.arange(len(splash)) / (0.35 * SR))
for t_cr, g in [(31 * T, 0.26), (47 * T, 0.30), (72 * T, 0.30), (98 * T, 0.26)]:
    add(t_cr, splash, g, 0.5)
    add(t_cr + 0.01, resamp(splash, 0.5), g * 0.7, 0.5)

# ---- 4. the real chirps: risers and closing gestures --------------------------
print("[render] real chirp gestures")
chirp_up = norm(seg(CHIRP_UP_T - 0.02, 0.26), 0.1)
chirp_dn = norm(seg(CHIRP_DN_T - 0.02, 0.26), 0.1)
edge = np.hanning(int(0.02 * SR))
for c in (chirp_up, chirp_dn):
    c[: len(edge) // 2] *= edge[: len(edge) // 2]
    c[-(len(edge) // 2):] *= edge[len(edge) // 2:]


def chirp_echo(t, x, gain, n_echo=5, fb=0.55, dt=T, pan0=0.35):
    for i in range(n_echo + 1):
        add(t + i * dt, x, gain * fb ** i, pan0 if i % 2 == 0 else 1 - pan0)


chirp_echo(8.0, resamp(chirp_up, 0.5), 0.20)
chirp_echo(14.5, chirp_up, 0.16, pan0=0.65)
chirp_echo(45.5, chirp_up, 0.22)
# pre-reveal riser: real up-chirp climbing an F# arpeggio into the reveal
for tt, rr, gg in [(60.04, 0.5, 0.16), (60.53, 2 / 3, 0.20),
                   (61.02, 1.0, 0.24), (61.51, 1.5, 0.28)]:
    add(tt, resamp(chirp_up, rr), gg, 0.5)
chirp_echo(106.0, chirp_dn, 0.20)
chirp_echo(112.0, resamp(chirp_dn, 0.5), 0.20, pan0=0.6)
add(118.0, resamp(chirp_dn, 0.25), 0.26, 0.5)  # final 2-octave-down sweep

# ---- 5. THE REVEAL: the untouched real signal surfaces ------------------------
print("[render] the reveal (untouched capture, 62-70 s)")
duck = env_bp(N, [(0, 1), (61.6, 1), (62.2, 0.13), (69.2, 0.13), (70.6, 1),
                  (DUR, 1)])
L *= duck
R *= duck
# N512 r0, starting just before its 12th preamble — level-matched, otherwise raw
rev = norm(seg(N512_PRE0 + 11 * N512_T - 0.10, 8.2), 0.085)
re_env = np.ones(len(rev))
n_fi, n_fo = int(0.5 * SR), int(1.3 * SR)
re_env[:n_fi] = np.linspace(0, 1, n_fi)
re_env[-n_fo:] = np.linspace(1, 0, n_fo)
add(62.0, rev * re_env, 1.0, 0.5)

# ---- 6. master ----------------------------------------------------------------
print("[master] hp, fades, level, soft limit")
mix = np.stack([L, R], axis=1)
sos_hp = sig.butter(2, 25, "hp", fs=SR, output="sos")
mix = sig.sosfiltfilt(sos_hp, mix, axis=0)

fade_in = np.ones(N)
nf = int(2.0 * SR)
fade_in[:nf] = np.sin(np.linspace(0, np.pi / 2, nf)) ** 2
nf = int(4.0 * SR)
fade_in[-nf:] *= np.sin(np.linspace(np.pi / 2, 0, nf)) ** 2
mix *= fade_in[:, None]

TARGET_RMS = 10 ** (-15.0 / 20)
CEIL = 10 ** (-1.05 / 20)
for _ in range(4):
    mix *= TARGET_RMS / rms(mix)
    a = np.abs(mix)
    thr = 0.60
    over = a > thr
    mix[over] = np.sign(mix[over]) * (
        thr + (CEIL - thr) * np.tanh((a[over] - thr) / (CEIL - thr)))
peak = np.max(np.abs(mix))
if peak > CEIL:
    mix *= CEIL / peak

sf.write(OUT, mix, SR, subtype="PCM_16")

# ---- 7. self-QA ----------------------------------------------------------------
x, _ = sf.read(OUT, dtype="float64")
mono = x.mean(axis=1)
dur_s = len(x) / SR
pk_db = 20 * np.log10(np.max(np.abs(x)))
rms_db = 20 * np.log10(rms(x))
print(f"\n[QA] duration {dur_s:.1f} s   peak {pk_db:+.2f} dBFS   RMS {rms_db:+.2f} dBFS")
ok = (90 <= dur_s <= 150) and (pk_db <= -1.0 + 1e-6) and (-16.5 <= rms_db <= -13.5)
print(f"[QA] spec gate: {'PASS' if ok else 'FAIL'}")

# 10-band spectral balance (% of total energy)
spec = np.abs(np.fft.rfft(mono)) ** 2
freqs = np.fft.rfftfreq(len(mono), 1 / SR)
edges = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 24000]
tot = spec.sum()
print("[QA] 10-band balance (% energy):")
for lo, hi in zip(edges[:-1], edges[1:]):
    b = spec[(freqs >= lo) & (freqs < hi)].sum() / tot * 100
    print(f"   {lo:>5}-{hi:<5} Hz : {b:5.1f}  {'#' * int(b)}")

# onset rate via spectral flux (per section)
f, tt, S = sig.stft(mono, SR, nperseg=2048, noverlap=1536)
mag = np.abs(S)
flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
thr = median_filter(flux, 93) * 1.6 + 0.02 * flux.max()
pk_idx, _ = sig.find_peaks(flux, height=thr, distance=6)
on_t = tt[1:][pk_idx]
secs = [("A emerge", 0, 20), ("B chorale", 20, 46), ("C ritual", 46, 62),
        ("D REVEAL", 62, 70), ("E submerge", 70, 96), ("F dissolve", 96, 128)]
print("[QA] onset rate + level per section:")
for nm, a, b in secs:
    r = ((on_t >= a) & (on_t < b)).sum() / (b - a)
    sl = mono[int(a * SR):int(b * SR)]
    print(f"   {nm:<10} {r:4.2f} onsets/s   rms {20*np.log10(rms(sl)):+6.1f} dBFS")
print(f"[QA] total onsets {len(on_t)} over {dur_s:.0f} s")
print(f"\n[done] {OUT}")
