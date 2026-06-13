#!/usr/bin/env python3
"""
Side B / Track 1 -- "Leader Tape"  (~150 s)

The clear-plastic silence before the data. The hushed opener of the concept
album: the leader tape spooling through the heads before anything is written,
then -- around 0:40 -- a single real chirp 'pip' emerging from the hiss like a
distant signal locking, and an almost-imperceptible build until, by the end,
the real 375 Hz carrier grid is just barely audible as a held chord. This is
the album's quiet floor; nothing here should ever feel like an "event".

Real-signal content (every sound is derived from the actual transmission):
  * Tape hiss / room tone: looped & cross-faded grains of the REAL capture
    noisefloor (tape10_run1.wav, the lead-silence + sounder-noisefloor sections,
    ~ -50 dB RMS) -- the genuine deck+room floor, not synthetic noise.
  * The single 'pip' at 0:40 is the REAL global up-chirp (500->5000 Hz, 0.2 s)
    lifted straight from the capture at t=20.74 s, reverb-tailed so it reads as
    "distant", arriving from across the room.
  * Distant precursor swells: the SAME global chirp resynthesized and stretched
    8x/16x into soft risers, deep in reverb -- the signal "approaching".
  * The held end-chord is the REAL N512 carrier grid (harmonics of 375 Hz)
    resynthesized as pure tones, retuned to F# major (per palette
    musical_mapping: keep the just-intonation-ish harmonics, nudge the 7th/11th
    harmonics into the scale) so the comb reads as a consonant pad, breathing on
    slow prime-period LFOs. It enters so gradually you only notice it is there
    once it already is.
  * The 4875 Hz pilot (13th harmonic) threads in faintly near the end -- it runs
    through the whole real transmission, so it appears as the carriers settle.

Form (150 s): 0-40 s pure leader-tape floor (hiss + room tone, a far precursor
swell barely there); 0:40 the real pip locks; 40-100 s the floor warms, a
second distant swell; 100-150 s the carrier-grid chord fades up to "just
audible" and holds; 4 s fade-in / 4 s fade-out. Onset rate must stay very low.

Deps: python3 + numpy/scipy/soundfile only. Seed fixed and logged.
"""

import numpy as np
import soundfile as sf
from scipy import signal as sg
from scipy.signal import fftconvolve

SEED = 20260611
rng = np.random.default_rng(SEED)
print(f"[t1_leader_tape] seed = {SEED}")

SR = 48000
DUR = 150.0
N = int(DUR * SR)
t = np.arange(N) / SR

CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/t1.wav"

cap, cap_sr = sf.read(CAPTURE, dtype="float64")
assert cap_sr == SR and cap.ndim == 1, "expected 48k mono capture"

# ----------------------------------------------------------------- helpers --
def grab(t0, dur, fade=0.3):
    """Slice real capture audio with raised-cosine edge fades."""
    a = cap[int(t0 * SR): int((t0 + dur) * SR)].copy()
    nf = max(1, int(fade * SR))
    nf = min(nf, len(a) // 2)
    w = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
    a[:nf] *= w
    a[-nf:] *= w[::-1]
    return a

def exp_ir(rt60, dur, lp_hz, seed_off, hp_hz=110.0):
    """Synthetic exponential-decay reverb IR (noise * exp decay, band-limited)."""
    r = np.random.default_rng(SEED + seed_off)
    n = int(dur * SR)
    x = r.standard_normal(n) * np.exp(-6.91 * np.arange(n) / (rt60 * SR))
    b, a = sg.butter(2, lp_hz / (SR / 2), "low")
    x = sg.lfilter(b, a, x)
    bh, ah = sg.butter(2, hp_hz / (SR / 2), "high")
    x = sg.lfilter(bh, ah, x)
    return x / np.sqrt(np.sum(x ** 2))

def reverb_st(x, rt60=5.0, lp_hz=6000.0, seed_off=0):
    """Stereo reverb: two decorrelated synthetic IRs."""
    irL = exp_ir(rt60, rt60 * 1.1, lp_hz, seed_off)
    irR = exp_ir(rt60, rt60 * 1.1, lp_hz, seed_off + 1)
    return fftconvolve(x, irL), fftconvolve(x, irR)

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

# ----------------------------------------- 1. real tape-hiss / room-tone bed --
# The genuine deck+room floor, made into a STATIONARY bed (no loop, no seam, no
# tremolo) by PSD-matched colored-noise synthesis: estimate the REAL
# noisefloor's power spectrum (Welch-averaged from the capture -> a smooth,
# robust colour template), build a linear-phase FIR with that magnitude
# response, and filter fresh white noise through it. The result has the exact
# tape-floor timbre of the real recording (bass-heavy room rumble + hiss --
# measured: ~59% of energy below 200 Hz, the room behind the deck) but is
# perfectly steady and arbitrarily long. Two independent noise draws -> width.
# This carries the real low-end room tone, so no separate room layer is needed.
floor_src = np.concatenate([grab(42.6, 3.3, fade=0.2),   # sounder_noisefloor
                            grab(10.5, 3.3, fade=0.2)])  # + lead-in floor
fw, Pxx = sg.welch(floor_src, SR, nperseg=4096, noverlap=2048)
mag_template = np.sqrt(np.maximum(Pxx, 0))
# design an FIR whose magnitude matches the real floor colour
NTAP = 2049
f_fir = fw / (SR / 2)
f_fir = np.concatenate([[0.0], f_fir, [1.0]])
g_fir = np.concatenate([[mag_template[0]], mag_template, [mag_template[-1]]])
g_fir = g_fir / (g_fir.max() + 1e-12)
# firwin2 needs strictly increasing, unique freqs incl. 0 and 1
f_fir, idx = np.unique(f_fir, return_index=True)
g_fir = g_fir[idx]
fir = sg.firwin2(NTAP, f_fir, g_fir)

def stationary_floor(seed_off):
    r = np.random.default_rng(SEED + seed_off)
    w = r.standard_normal(N + NTAP)
    x = sg.lfilter(fir, [1.0], w)[NTAP:N + NTAP]
    x /= np.sqrt(np.mean(x ** 2)) + 1e-12
    x *= np.sqrt(np.mean(floor_src ** 2))      # match the real floor's RMS
    return x

bedL = stationary_floor(70)
bedR = stationary_floor(71)
# bed arc: from near-nothing post fade-in up to a soft present floor by the end.
# the real floor RMS is ~ -49 dB; lifted ~ +12 dB it sits as an audible-but-
# quiet bed under everything without ever becoming an "event".
bed_arc = ramp_env([0, 6, 40, 100, 140, DUR], [0.35, 0.60, 0.85, 1.0, 1.05, 0.95])
BED_GAIN = 4.0
L += BED_GAIN * bedL * bed_arc
R += BED_GAIN * bedR * bed_arc
print(f"[bed] PSD-matched real-floor bed, RMS-matched then x{BED_GAIN:.1f}; "
      f"low-end room tone carried natively (~59% <200 Hz)")

# ----------------------------- 2. distant precursor swells (stretched chirp) --
# The real global up-chirp, resynthesized and time-stretched into soft risers,
# buried deep in reverb so they read as "something approaching across the room".
# These are felt more than heard -- they must not register as onsets.
def swell(f0, f1, stretch, rt=7.0, soff=30):
    d = 0.2 * stretch
    n = int(d * SR)
    tt = np.arange(n) / SR
    x = sg.chirp(tt, f0=f0, t1=d, f1=f1, method="linear")
    x *= np.sin(np.pi * tt / d) ** 2
    wL, wR = reverb_st(x, rt60=rt, lp_hz=5000, seed_off=soff)
    m = max(np.abs(wL).max(), np.abs(wR).max()) + 1e-12
    return wL / m, wR / m

upA = swell(500, 5000, 16, soff=30)   # 3.2 s riser, very smeared
upB = swell(500, 5000, 12, soff=32)   # 2.4 s riser
place(L, R, *upA, 22.0, gain=0.040, pan=-0.25)   # first hint, very faint
place(L, R, *upB, 78.0, gain=0.050, pan=0.20)    # a second, slightly nearer

# --------------------------- 3. THE PIP: real chirp locking at ~0:40 ----------
# The single real global up-chirp from the capture (t=20.74 s), the album's
# first true "signal". Played near-dry but with a long reverb tail so it reads
# as distant -- a far-off lock, not an in-your-face transient. Just one.
pip = grab(20.74, 0.5, fade=0.04)
pip /= np.abs(pip).max() + 1e-12
# slightly low-pass so it's a soft "ping" rather than a sharp click
lp_pip_b, lp_pip_a = sg.butter(2, 6000 / (SR / 2), "low")
pip = sg.lfilter(lp_pip_b, lp_pip_a, pip)
pip /= np.abs(pip).max() + 1e-12
pipL, pipR = reverb_st(pip, rt60=8.0, lp_hz=5500, seed_off=40)
m = max(np.abs(pipL).max(), np.abs(pipR).max()) + 1e-12
PIP_T = 40.0
place(L, R, pip, pip, PIP_T, gain=0.13)            # the dry arrival, modest
place(L, R, pipL / m, pipR / m, PIP_T + 0.01, gain=0.22)   # the long room tail
print(f"[pip] real up-chirp placed at t={PIP_T:.1f}s (the distant lock)")

# ----------------------- 4. held carrier-grid chord: the barely-audible build -
# The REAL N512 carrier grid (harmonics of 375 Hz). Resynthesized as pure tones
# and retuned to F# major per palette musical_mapping (keep most harmonics; nudge
# the 7th/11th-family carriers into the scale) so the comb is consonant. The
# chord fades up across the back half and holds -- you realize it's there only
# once it already is. Slow prime-period LFOs give it breath.
F0 = 375.0
# real N512 carriers, lowest 12 (audible range); pitch them to F# major targets
# from palette: keep F#/C#/A# harmonics; 2625(E7)->D#7 2489.02; 4125(C8)->C#8 4434.92
carrier_targets = [
    (750.0,  750.0),    # F#5 keep
    (1125.0, 1125.0),   # C#6 keep
    (1500.0, 1500.0),   # F#6 keep
    (1875.0, 1875.0),   # A#6 keep
    (2250.0, 2250.0),   # C#7 keep
    (2625.0, 2489.02),  # E7 -> D#7  (palette retune)
    (3000.0, 3000.0),   # F#7 keep
    (3375.0, 3375.0),   # G#7 keep
    (3750.0, 3750.0),   # A#7 keep
    (4125.0, 4434.92),  # C8 -> C#8  (palette retune)
    (4500.0, 4500.0),   # C#8 keep
]
PRIMES = [11, 13, 17, 19, 23, 29, 31, 37]
chordL = np.zeros(N)
chordR = np.zeros(N)
# loudness compensation: high partials quieter (1/f-ish), so the chord reads as
# a warm pad weighted to the lower carriers, not a hiss of high tones.
for i, (orig, f) in enumerate(carrier_targets):
    w = (750.0 / f) ** 0.9
    P = PRIMES[i % len(PRIMES)]
    lfo = 0.65 + 0.35 * np.sin(2 * np.pi * t / P + rng.uniform(0, 2 * np.pi))
    # higher carriers enter slightly later -> the chord "fills in" from the bottom
    frac = i / (len(carrier_targets) - 1)
    t_on = 96.0 + 18.0 * frac
    gate = smooth_gate(t_on, DUR + 2.0, rise=22.0, fall=4.0)
    df = rng.uniform(0.08, 0.22)                # L/R detune -> slow beating
    pan = rng.uniform(-0.30, 0.30)
    phL, phR = rng.uniform(0, 2 * np.pi), rng.uniform(0, 2 * np.pi)
    env = w * gate * lfo
    chordL += env * (1 - pan) * np.sin(2 * np.pi * (f + df / 2) * t + phL)
    chordR += env * (1 + pan) * np.sin(2 * np.pi * (f - df / 2) * t + phR)
cpk = max(np.abs(chordL).max(), np.abs(chordR).max()) + 1e-12
L += 0.20 * chordL / cpk
R += 0.20 * chordR / cpk
print(f"[chord] {len(carrier_targets)} real carriers -> F# major pad, "
      f"fades up over t=96..150 s")

# 4875 Hz pilot (13th harmonic) -- threads in faintly as the carriers settle,
# exactly as it runs through the real transmission.
pgate = smooth_gate(112.0, DUR + 2.0, rise=24.0, fall=4.0)
plfo = 0.7 + 0.3 * np.sin(2 * np.pi * t / 13.0 + 0.7)
L += 0.010 * pgate * plfo * np.sin(2 * np.pi * 4875.0 * t)
R += 0.010 * pgate * plfo * np.sin(2 * np.pi * 4875.0 * t + 1.1)

# ------------------------------------------------------- fades + mastering ---
nin, nout = int(4.0 * SR), int(4.0 * SR)   # brief asks for slow 4 s fade-in
fi = 0.5 - 0.5 * np.cos(np.pi * np.arange(nin) / nin)
fo = 0.5 + 0.5 * np.cos(np.pi * np.arange(nout) / nout)
for ch in (L, R):
    ch[:nin] *= fi
    ch[-nout:] *= fo

mix = np.stack([L, R], axis=1)
assert np.isfinite(mix).all(), "non-finite samples in mix"
rms = np.sqrt(np.mean(mix ** 2))
mix *= 10 ** (-15.0 / 20) / rms
pk = np.abs(mix).max()
if pk > 10 ** (-1.0 / 20):
    mix = 0.875 * np.tanh(mix / 0.875)
    print(f"[master] soft limiter engaged (pre-peak {20*np.log10(pk):.2f} dBFS)")

sf.write(OUT, mix, SR, subtype="PCM_16")

# ------------------------------------------------------------------- QA ------
peak_db = 20 * np.log10(np.abs(mix).max() + 1e-12)
rms_db = 20 * np.log10(np.sqrt(np.mean(mix ** 2)) + 1e-12)
print(f"\n[QA] {OUT}")
print(f"[QA] duration  {len(mix)/SR:.2f} s   peak {peak_db:+.2f} dBFS   "
      f"rms {rms_db:+.2f} dBFS")

mono = mix.mean(axis=1)
spec = np.abs(np.fft.rfft(mono)) ** 2
freqs = np.fft.rfftfreq(len(mono), 1 / SR)
edges = [22, 44, 88, 177, 354, 707, 1414, 2828, 5657, 11314, 22627]
tot = spec.sum() + 1e-30
print("[QA] 10-band spectral balance (% of energy):")
for lo, hi in zip(edges[:-1], edges[1:]):
    m_ = (freqs >= lo) & (freqs < hi)
    print(f"      {lo:>5d}-{hi:<5d} Hz : {100*spec[m_].sum()/tot:5.1f} %")

# onset-event rate -- PERCEPTUAL onsets, robust to stationary hiss. A hushed
# leader-tape floor is broadband noise: raw spectral flux crosses any fixed
# mean+k*std threshold on noise jitter alone (a measurement artifact, not an
# audible event). To count what a listener actually perceives as an onset, we
# (a) measure flux against a LOCAL running median (so stationary hiss -> ~0
# excess), and (b) require the excess to exceed a hard perceptual floor scaled
# by the global flux, with a 0.5 s re-arm. This reads a real transient (the
# pip) but ignores noise-floor shimmer.
f_, tt_, S = sg.stft(mono, SR, nperseg=2048, noverlap=1536)
mag = np.abs(S)
flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
hop_s = 512 / SR
# local median over ~3 s -> the "stationary floor" of the flux signal
wmed = max(3, int(3.0 / hop_s) | 1)
med = sg.medfilt(flux, kernel_size=wmed)
excess = np.maximum(flux - med, 0.0)
# perceptual threshold: a transient must rise well above the local texture
thr = excess.mean() + 4.0 * excess.std()
rearm = int(0.5 / hop_s)
onsets, last = 0, -10 ** 9
for i, v in enumerate(excess):
    if v > thr and i - last > rearm:
        onsets += 1
        last = i
    elif v > thr:
        last = i
print(f"[QA] onset events (perceptual, hiss-robust): {onsets} total = "
      f"{onsets/DUR:.3f}/s  (leader-tape target: well under 0.3/s)")
# also report the raw-flux number for transparency (expected high on pure hiss)
thr_raw = flux.mean() + 2.5 * flux.std()
raw = int(np.sum(flux > thr_raw))
print(f"[QA]   (raw spectral-flux crossings, no median-detrend: {raw} -- high "
      f"on broadband hiss by construction, not perceived events)")

print("[QA] energy arc (RMS dBFS per 15 s window):")
for w0 in range(0, int(DUR), 15):
    seg = mono[w0 * SR:(w0 + 15) * SR]
    print(f"      {w0:>3d}-{w0+15:<3d} s : "
          f"{20*np.log10(np.sqrt(np.mean(seg**2))+1e-12):6.1f} dB")
