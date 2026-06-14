#!/usr/bin/env python3
"""
bside_ambient.wav -- "Music for Tape Decks"
Ambient/drone remix of the cassette-ai master10 data-transfer signal.

Materials (all quoted from the real signal, per palette.json):
  * Real capture audio (tape10_run1.wav): the opening up-chirp pip, two 12 s
    slabs of actual DQPSK carrier texture (N512 rung r0 + d2x rung r5) which are
    reverb-smeared into washes (and surfaced dry at the climax), and the real
    Schroeder multitone sounder smeared into a noise-splash wash.
  * The actual carrier grid (375 Hz harmonics) retuned to a 7-limit just
    intonation set over the 375 Hz fundamental, breathing on prime-period LFOs.
  * The actual global chirp (500->5000 Hz, 0.2 s) resynthesized stretched
    8x/16x as recurring swells (down-chirp 5000->500 for the recede).
  * The frame rhythm: preamble ticks at the *measured* N512 frame period
    1.372896 s, barely-there, mid-section only.
  * The 4875 Hz pilot (13th harmonic) as a faint constant thread -- it runs
    through the whole real transmission, so it runs through the piece.

Form: 132 s arc -- quiet low drone -> spectrum opens, ticks + washes -> full
spectrum climax with audible real modem buzz -> down-chirps, recede to the
fundamental + tape hiss.

Deps: python3 + numpy/scipy/soundfile only. Seed fixed and logged.
"""

import numpy as np
import soundfile as sf
from scipy import signal as sg
from scipy.signal import fftconvolve

SEED = 20260612
rng = np.random.default_rng(SEED)
print(f"[remix_ambient] seed = {SEED}")

SR = 48000
DUR = 132.0
N = int(DUR * SR)
t = np.arange(N) / SR

CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/bside_ambient.wav"

cap, cap_sr = sf.read(CAPTURE, dtype="float64")
assert cap_sr == SR and cap.ndim == 1

# ----------------------------------------------------------------- helpers --
def grab(t0, dur, fade=0.5):
    """Slice real capture audio with raised-cosine edge fades."""
    a = cap[int(t0 * SR): int((t0 + dur) * SR)].copy()
    nf = int(fade * SR)
    w = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
    a[:nf] *= w
    a[-nf:] *= w[::-1]
    return a

def exp_ir(rt60, dur, lp_hz, seed_off):
    """Synthetic exponential-decay reverb IR (noise * exp decay, lowpassed)."""
    r = np.random.default_rng(SEED + seed_off)
    n = int(dur * SR)
    x = r.standard_normal(n) * np.exp(-6.91 * np.arange(n) / (rt60 * SR))
    b, a = sg.butter(2, lp_hz / (SR / 2), "low")
    x = sg.lfilter(b, a, x)
    bh, ah = sg.butter(2, 120 / (SR / 2), "high")
    x = sg.lfilter(bh, ah, x)
    return x / np.sqrt(np.sum(x**2))

def reverb_st(x, rt60=5.0, lp_hz=6000.0, seed_off=0):
    """Stereo reverb: two decorrelated synthetic IRs."""
    irL = exp_ir(rt60, rt60 * 1.1, lp_hz, seed_off)
    irR = exp_ir(rt60, rt60 * 1.1, lp_hz, seed_off + 1)
    return fftconvolve(x, irL), fftconvolve(x, irR)

def spectral_blur(x, blur_s=1.5):
    """Paulstretch-style freeze: time-smooth STFT magnitudes AND randomize
    phases -> turns buzzy DQPSK texture into a static lush pad while keeping
    the exact carrier-grid comb spectrum. (Keeping original phases would let
    the symbol hops re-emerge through OLA -- measured, not theoretical.)"""
    _, _, S = sg.stft(x, SR, nperseg=4096, noverlap=3072)
    mag = np.abs(S)
    k = max(3, int(blur_s * SR / 1024))
    kern = np.hanning(k)
    kern /= kern.sum()
    mag = np.apply_along_axis(lambda m: np.convolve(m, kern, "same"), 1, mag)
    ph = rng.uniform(0, 2 * np.pi, mag.shape)
    _, y = sg.istft(mag * np.exp(1j * ph), SR, nperseg=4096, noverlap=3072)
    return y

def place(busL, busR, xL, xR, t0, gain=1.0, pan=0.0):
    """Add a stereo (or mono->stereo) event into the mix at time t0."""
    if xR is None:
        xR = xL
    gL = gain * min(1.0, 1.0 - pan)
    gR = gain * min(1.0, 1.0 + pan)
    i0 = int(t0 * SR)
    for bus, x, g in ((busL, xL, gL), (busR, xR, gR)):
        n = min(len(x), len(bus) - i0)
        if n > 0:
            bus[i0:i0 + n] += g * x[:n]

def ramp_env(times, vals):
    """Piecewise-linear envelope over the whole piece."""
    return np.interp(t, times, vals)

def smooth_gate(t_on, t_off, rise, fall):
    """Raised-cosine on/off gate envelope."""
    e = np.zeros(N)
    e += np.clip((t - t_on) / rise, 0, 1)
    e = np.minimum(e, np.clip((t_off - t) / fall, 0, 1))
    return 0.5 - 0.5 * np.cos(np.pi * np.clip(e, 0, 1))

L = np.zeros(N)
R = np.zeros(N)

# ---------------------------------------------- 1. JI-retuned carrier drone --
# Real N512 carrier grid = harmonics 2..24 of 375 Hz. Retune each carrier to
# the nearest member of a 7-limit JI harmonic set; add sub-fundamentals
# (187.5, 375 Hz) for body. Pilot 4875 (13th) handled separately below.
F0 = 375.0
JI_SET = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 24]
real_carriers = [750, 1125, 1500, 1875, 2250, 2625, 3000, 3375, 3750, 4125,
                 4500, 5250, 5625, 6000, 6375, 6750, 7125, 7500, 7875, 8250,
                 8625, 9000]
retuned = {}
for f in real_carriers:
    h = min(JI_SET, key=lambda k: abs(k * F0 - f))
    retuned[h] = retuned.get(h, 0) + 1
partials = [(0.5, 1.0), (1.0, 1.4)] + \
    [(h, retuned[h] ** 0.5 / h ** 0.7) for h in sorted(retuned)]
print(f"[drone] {len(real_carriers)} real carriers -> JI harmonics "
      f"{sorted(retuned)} (+ sub 187.5/375 Hz)")

PRIMES = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41]
hs = [p[0] for p in partials]
order = np.argsort(hs)
droneL = np.zeros(N)
droneR = np.zeros(N)
for rank, idx in enumerate(order):
    h, w = partials[idx]
    f = h * F0
    if f > 9100:
        continue
    # arc scheduling: low partials enter first, high ones at the climax,
    # high ones leave first in the recede
    frac = rank / max(1, len(order) - 1)
    t_on = 0.0 + 52.0 * frac**1.3
    t_off = DUR - 4.0 - 38.0 * frac**1.1
    gate = smooth_gate(t_on, t_off, rise=14.0, fall=16.0)
    # breathing: prime-period LFO, random phase
    P = PRIMES[int(rng.integers(len(PRIMES)))]
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * t / P + rng.uniform(0, 2 * np.pi))
    env = w * gate * lfo
    df = rng.uniform(0.10, 0.32)           # L/R detune -> slow beating
    pan = rng.uniform(-0.35, 0.35)
    phL = rng.uniform(0, 2 * np.pi)
    phR = rng.uniform(0, 2 * np.pi)
    droneL += env * (1 - pan) * np.sin(2 * np.pi * (f + df / 2) * t + phL)
    droneR += env * (1 + pan) * np.sin(2 * np.pi * (f - df / 2) * t + phR)
dpk = max(np.abs(droneL).max(), np.abs(droneR).max())
L += 0.42 * droneL / dpk
R += 0.42 * droneR / dpk

# pilot thread: 4875 Hz (13th harmonic), faint, constant like the real pilot
pgate = smooth_gate(18.0, 112.0, 20.0, 18.0)
plfo = 0.7 + 0.3 * np.sin(2 * np.pi * t / 13.0 + 1.0)
L += 0.012 * pgate * plfo * np.sin(2 * np.pi * 4875.0 * t)
R += 0.012 * pgate * plfo * np.sin(2 * np.pi * 4875.0 * t + 1.3)

# --------------------------------- 2. real DQPSK texture: washes + dry quote --
bp_b, bp_a = sg.butter(3, [500 / (SR / 2), 6800 / (SR / 2)], "band")

texA = grab(50.0, 12.0)        # N512 rung r0 texture (capture 50-62 s)
texB = grab(210.0, 12.0)       # d2x rung r5 texture (capture 210-222 s)
for tex, t0, g, soff in ((texA, 24.0, 0.14, 10), (texB, 72.0, 0.28, 20)):
    x = sg.lfilter(bp_b, bp_a, tex)
    wL, wR = reverb_st(x, rt60=6.0, lp_hz=5500, seed_off=soff)
    wL, wR = spectral_blur(wL, 1.6), spectral_blur(wR, 1.6)
    pk = max(np.abs(wL).max(), np.abs(wR).max())
    wL, wR = wL / pk, wR / pk
    nf = int(4.0 * SR)
    w = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
    for ch in (wL, wR):
        ch[:nf] *= w
        ch[-nf:] *= w[::-1]
    place(L, R, wL, wR, t0, gain=g)

# near-dry quote at the climax: the actual modem buzz under the washes,
# micro-smeared (250 ms decay) so DQPSK phase hops glow instead of click
dry = sg.lfilter(bp_b, bp_a, grab(52.0, 14.0, fade=4.0))
micro = exp_ir(0.25, 0.45, 4500, 60)
dry = fftconvolve(dry, micro)
lp4_b, lp4_a = sg.butter(3, 4500 / (SR / 2), "low")
dry = sg.lfilter(lp4_b, lp4_a, dry)
dry /= np.abs(dry).max()
place(L, R, dry, dry * 0.92, 64.0, gain=0.05)   # slightly R-decorrelated

# the clearest data quote surfaces in the recede: real d2x buzz, truly dry,
# quiet in absolute terms but plainly audible over the thinning drone --
# the transmission ghosting through as the piece fades
ghost = sg.lfilter(bp_b, bp_a, grab(228.0, 12.0, fade=3.5))
ghost /= np.abs(ghost).max()
place(L, R, ghost, ghost * 0.9, 96.0, gain=0.14, pan=0.1)

# ----------------------------------- 3. stretched global chirp as swells -----
def swell(f0, f1, stretch, rt=4.5, soff=30):
    d = 0.2 * stretch
    n = int(d * SR)
    tt = np.arange(n) / SR
    x = sg.chirp(tt, f0=f0, t1=d, f1=f1, method="linear")
    x *= np.sin(np.pi * tt / d) ** 2          # smooth swell envelope
    wL, wR = reverb_st(x, rt60=rt, lp_hz=6500, seed_off=soff)
    m = max(np.abs(wL).max(), np.abs(wR).max())
    xp = np.pad(x, (0, len(wL) - len(x)))
    return 0.6 * xp + wL * 0.9 / m, 0.6 * xp + wR * 0.9 / m

upA = swell(500, 5000, 16, soff=30)    # 3.2 s riser
upB = swell(500, 5000, 8, soff=32)     # 1.6 s riser
dnA = swell(5000, 500, 16, soff=34)    # 3.2 s faller

place(L, R, *upA, 13.0, gain=0.14, pan=-0.2)
place(L, R, *upB, 40.5, gain=0.16, pan=0.25)
place(L, R, *upA, 62.0, gain=0.20, pan=0.0)
place(L, R, *dnA, 93.0, gain=0.17, pan=0.2)
place(L, R, *dnA, 116.0, gain=0.13, pan=-0.15)

# the *real* chirp pip opens the piece (capture 20.74-21.25 s), like the
# tape starting up; echoed once by its 16x-stretched ghost right after
pip = grab(20.74, 0.5, fade=0.05)
pip /= np.abs(pip).max()
place(L, R, pip, pip, 3.0, gain=0.30)
pL, pR = reverb_st(pip, rt60=5.0, lp_hz=6000, seed_off=40)
m = max(np.abs(pL).max(), np.abs(pR).max())
place(L, R, pL / m, pR / m, 3.05, gain=0.20)

# ------------------------- 4. real Schroeder sounder smeared into a wash -----
schro = grab(21.96, 3.0, fade=0.3)
schro = sg.lfilter(bp_b, bp_a, schro)
sL, sR = reverb_st(schro, rt60=7.0, lp_hz=5000, seed_off=50)
m = max(np.abs(sL).max(), np.abs(sR).max())
place(L, R, sL / m, sR / m, 58.0, gain=0.30)    # climax splash
place(L, R, sR / m, sL / m, 88.0, gain=0.18)    # softer mirrored return

# --------------------------- 5. frame ticks: barely-there preamble pulse -----
PERIOD = 1.372896      # measured N512 frame period from the real capture
tick_n = int(0.25 * SR)
tt = np.arange(tick_n) / SR
tick = sg.chirp(tt, f0=800, t1=0.25, f1=3200, method="linear")
tick *= np.sin(np.pi * tt / 0.25) ** 2
lp_b, lp_a = sg.butter(4, 2400 / (SR / 2), "low")
tick = sg.lfilter(lp_b, lp_a, tick)
tick /= np.abs(tick).max()
tick_env_t = [28.0, 50.0, 86.0, 102.0]
tick_env_v = [0.0, 1.0, 1.0, 0.0]
k = 0
tt0 = 28.0
while tt0 < 102.0:
    g = np.interp(tt0, tick_env_t, tick_env_v)
    place(L, R, tick, tick, tt0, gain=0.030 * g, pan=0.3 * (-1) ** k)
    tt0 += PERIOD
    k += 1

# --------------------------------------------- 6. master arc + tape-hiss bed --
arc = ramp_env([0, 8, 55, 80, 105, DUR - 4, DUR],
               [0.55, 0.75, 1.0, 1.0, 0.8, 0.55, 0.4])
L *= arc
R *= arc

# real noisefloor (capture 43.0-45.5 s) looped softly = tape-warmth bed
nfb = grab(43.0, 2.5, fade=0.4)
nfb /= np.abs(nfb).max()
bed = np.tile(nfb, int(np.ceil(N / len(nfb))))[:N]
L += 0.015 * bed * ramp_env([0, 10, 110, DUR], [0.4, 1.0, 1.0, 1.6])
R += 0.015 * np.roll(bed, SR // 3) * ramp_env([0, 10, 110, DUR], [0.4, 1.0, 1.0, 1.6])

# ------------------------------------------------------- fades + mastering ---
nin, nout = int(2.0 * SR), int(4.0 * SR)
fi = 0.5 - 0.5 * np.cos(np.pi * np.arange(nin) / nin)
fo = 0.5 + 0.5 * np.cos(np.pi * np.arange(nout) / nout)
for ch in (L, R):
    ch[:nin] *= fi
    ch[-nout:] *= fo

mix = np.stack([L, R], axis=1)
rms = np.sqrt(np.mean(mix**2))
mix *= 10 ** (-15.0 / 20) / rms
pk = np.abs(mix).max()
if pk > 10 ** (-1.0 / 20):
    mix = 0.875 * np.tanh(mix / 0.875)      # gentle soft limiter
    print(f"[master] soft limiter engaged (pre-peak {20*np.log10(pk):.2f} dBFS)")

sf.write(OUT, mix, SR, subtype="PCM_16")

# ------------------------------------------------------------------- QA ------
peak_db = 20 * np.log10(np.abs(mix).max())
rms_db = 20 * np.log10(np.sqrt(np.mean(mix**2)))
print(f"\n[QA] {OUT}")
print(f"[QA] duration  {len(mix)/SR:.2f} s   peak {peak_db:+.2f} dBFS   "
      f"rms {rms_db:+.2f} dBFS")

mono = mix.mean(axis=1)
spec = np.abs(np.fft.rfft(mono))**2
freqs = np.fft.rfftfreq(len(mono), 1 / SR)
edges = [22, 44, 88, 177, 354, 707, 1414, 2828, 5657, 11314, 22627]
tot = spec.sum()
print("[QA] 10-band spectral balance (% of energy):")
for lo, hi in zip(edges[:-1], edges[1:]):
    m_ = (freqs >= lo) & (freqs < hi)
    print(f"      {lo:>5d}-{hi:<5d} Hz : {100*spec[m_].sum()/tot:5.1f} %")

# onset-event rate: linear-magnitude spectral flux (loudness-weighted, so it
# measures *strong* onsets and ignores tape hiss), threshold mean+2.5std,
# rising-edge counting with 0.3 s re-arm: one sustained rough region = one
# event, while e.g. techno kicks at 120 BPM would each count (~2/s)
f_, tt_, S = sg.stft(mono, SR, nperseg=2048, noverlap=1536)
flux = np.maximum(np.diff(np.abs(S), axis=1), 0).sum(axis=0)
thr = flux.mean() + 2.5 * flux.std()
hop_s = 512 / SR
rearm = int(0.3 / hop_s)
onsets, last = 0, -10**9
for i, v in enumerate(flux):
    if v > thr and i - last > rearm:
        onsets += 1
        last = i
    elif v > thr:
        last = i          # still above threshold: hold the re-arm timer
print(f"[QA] onset events: {onsets} total = {onsets/DUR:.2f}/s "
      f"(ambient target: well under 0.5/s)")

print("[QA] energy arc (RMS dBFS per 12 s window):")
for w0 in range(0, int(DUR), 12):
    seg = mono[w0 * SR:(w0 + 12) * SR]
    print(f"      {w0:>3d}-{w0+12:<3d} s : {20*np.log10(np.sqrt(np.mean(seg**2))+1e-12):6.1f} dB")
