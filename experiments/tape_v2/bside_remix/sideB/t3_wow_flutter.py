#!/usr/bin/env python3
"""
t3.wav -- "Wow & Flutter"  (B-side, track 3 of 9: THE STRUGGLE)

The enemy of the whole project -- timebase wobble -- becomes the instrument.
Everything here is sung through the cassette deck's unsteady hands.

Materials (all derived from / quoting the REAL data-transfer signal, per
palette.json + the actual capture tape10_run1.wav):

  * TONE BED -- the real N512 carrier grid (375 Hz harmonics 2..14) retuned to
    F# NATURAL MINOR (per musical_mapping.scale_quantizations: A# carriers
    1875/3750 pulled down to A/B per the table), played as a slow, sustained
    chord. Dark, unresolved -- the struggling key.
  * WOW & FLUTTER -- the bed is read through a VARYING fractional-delay pointer
    (exactly how a real deck's capstan wobble pitch-shifts the audio): slow wow
    (~0.6 Hz + 1.7 Hz) plus fast flutter (~8.5 Hz + 12.3 Hz), peak depth tuned
    so the instantaneous speed deviation is ~0.42 % RMS -- the MEASURED flutter
    of this very capture. Audibly seasick.
  * REAL DQPSK TEXTURE -- two slabs of actual modem buzz (N512 rung r0 @ cap
    50 s, d2x rung r5 @ cap 210 s), band-passed, micro-smeared, then bent with
    a DEEPER copy of the same flutter so the symbol hops slur and detune.
  * FRAME PULSE that drifts in and out of lock -- the real 800->3200 Hz preamble
    tick, fired at the measured N512 frame period 1.372896 s but with its phase
    slowly wandering (a sine drift) against an implied steady grid: it tightens,
    loosens, and slips, like the decoder hunting for sync.
  * REAL CHIRP -- the actual up-chirp pip (capture ~20.74 s) opens the track,
    its 12x-stretched ghost answering, then wow-bent. Real Schroeder sounder and
    the real tape noisefloor form a warmth bed.
  * The 4875 Hz pilot (13th harmonic) threads through, wobbling with the rest.

Form (~200 s): the bed fades up steady-ish -> the wobble deepens and the
texture/pulse enter -> mid-section the flutter is at its worst and the pulse
slips badly -> it eases but never fully settles -> long recede, the pilot the
last thing wobbling.

Deps: python3 + numpy/scipy/soundfile only. Seed fixed and logged.
"""

import numpy as np
import soundfile as sf
from scipy import signal as sg
from scipy.signal import fftconvolve

SEED = 20260613
rng = np.random.default_rng(SEED)
print(f"[t3_wow_flutter] seed = {SEED}")

SR = 48000
DUR = 200.0
N = int(DUR * SR)
t = np.arange(N) / SR

CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/t3.wav"

cap, cap_sr = sf.read(CAPTURE, dtype="float64")
assert cap_sr == SR and cap.ndim == 1, "expected mono 48k capture"

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
    """Synthetic exponential-decay reverb IR (noise * exp decay, band-limited)."""
    r = np.random.default_rng(SEED + seed_off)
    n = int(dur * SR)
    x = r.standard_normal(n) * np.exp(-6.91 * np.arange(n) / (rt60 * SR))
    b, a = sg.butter(2, lp_hz / (SR / 2), "low")
    x = sg.lfilter(b, a, x)
    bh, ah = sg.butter(2, 120 / (SR / 2), "high")
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
    """Raised-cosine on/off gate envelope across the whole timeline."""
    e = np.clip((t - t_on) / rise, 0, 1)
    e = np.minimum(e, np.clip((t_off - t) / fall, 0, 1))
    return 0.5 - 0.5 * np.cos(np.pi * np.clip(e, 0, 1))


# --------------------------------------------------- the FLUTTER signature ---
# A real deck's capstan/pinch-roller imperfections create a SPEED ratio s(time)
# that wobbles around 1.0. We model it as a slow "wow" (sub-few-Hz) plus fast
# "flutter" (several Hz), each from a couple of incommensurate sinusoids so it
# never repeats audibly. The instantaneous fractional speed deviation, RMS, is
# scaled to the MEASURED 0.42 % of this capture.
WOW_HZ = (0.57, 1.73)        # slow drift -> seasick pitch wander
FLUT_HZ = (8.5, 12.3)        # fast flutter -> the warble/grain
MEASURED_FLUTTER_RMS = 0.0042  # 0.42 %


def flutter_speed(scale=1.0, depth_env=None, seed_off=0):
    """Return a speed-ratio array s(t) ~ 1.0 with wow+flutter, RMS-deviation
    scaled to `scale` * 0.42 %. `depth_env` (len N or None) lets the wobble
    deepen/ease across the piece. Each call gets its own random phases."""
    r = np.random.default_rng(SEED + 700 + seed_off)
    dev = np.zeros(N)
    # wow: dominant, ~70 % of the energy
    for f in WOW_HZ:
        dev += 0.85 * np.sin(2 * np.pi * f * t + r.uniform(0, 2 * np.pi))
    # flutter: faster, lower amplitude
    for f in FLUT_HZ:
        dev += 0.45 * np.sin(2 * np.pi * f * t + r.uniform(0, 2 * np.pi))
    # normalise to unit RMS, then to the target fractional deviation
    dev /= np.sqrt(np.mean(dev ** 2))
    dev *= MEASURED_FLUTTER_RMS * scale
    if depth_env is not None:
        dev = dev * depth_env
    return 1.0 + dev


def wow_resample(x, speed):
    """Read signal x through a time-varying speed ratio (a wandering read
    pointer) -> imposes pitch wobble, exactly like a deck. `speed` is sampled
    at output rate; the read position is the running integral of speed."""
    pos = np.cumsum(speed)            # fractional read index per output sample
    pos = pos - pos[0]                # start at sample 0
    src = np.arange(len(x))
    return np.interp(pos, src, x, left=0.0, right=0.0)


L = np.zeros(N)
R = np.zeros(N)

# ------------------------------------------ 1. F# natural-minor tone bed -----
# Real N512 grid harmonics 2..14 of 375 Hz, quantized to F# natural minor per
# palette musical_mapping (A# 1875/3750 pulled to B; everything else kept).
# Build a STEADY stereo bed first, then wobble it through the deck.
F0 = 375.0
# (real_carrier_hz, target_hz)  -- F# natural minor quantization, lowest octaves
BED = [
    (750.0,  750.0),    # F#5  keep
    (1125.0, 1125.0),   # C#6  keep
    (1500.0, 1500.0),   # F#6  keep
    (1875.0, 1975.53),  # A#6 -> B6  (retune, natural minor)
    (2250.0, 2250.0),   # C#7  keep
    (2625.0, 2625.0),   # E7   keep (flat-7 harmonic, lives in minor)
    (3000.0, 3000.0),   # F#7  keep
    (3375.0, 3375.0),   # G#7  keep
    (3750.0, 3951.07),  # A#7 -> B7  (retune)
]
print(f"[bed] {len(BED)} real carriers -> F# natural minor "
      f"(2 retuned: 1875->B6, 3750->B7)")

bedL = np.zeros(N)
bedR = np.zeros(N)
# weight lower partials louder (warmer, less shrill); slow prime LFOs breathe
PRIMES = [7, 11, 13, 17, 19, 23]
for i, (fr, f) in enumerate(BED):
    w = 1.0 / (f / 750.0) ** 0.85
    P = PRIMES[i % len(PRIMES)]
    lfo = 0.62 + 0.38 * np.sin(2 * np.pi * t / P + rng.uniform(0, 2 * np.pi))
    dtune = rng.uniform(0.08, 0.30)              # L/R detune -> slow beating
    phL, phR = rng.uniform(0, 2 * np.pi), rng.uniform(0, 2 * np.pi)
    bedL += w * lfo * np.sin(2 * np.pi * (f + dtune / 2) * t + phL)
    bedR += w * lfo * np.sin(2 * np.pi * (f - dtune / 2) * t + phR)
# add a soft sub-fundamental for body (375 + 187.5 Hz)
bedL += 0.9 * np.sin(2 * np.pi * 375.0 * t + 0.3) + 0.6 * np.sin(2 * np.pi * 187.5 * t)
bedR += 0.9 * np.sin(2 * np.pi * 375.0 * t + 1.1) + 0.6 * np.sin(2 * np.pi * 187.5 * t + 0.7)

# wobble the bed: depth ramps up into the worst-flutter mid-section, eases late
depth = ramp_env([0, 18, 60, 110, 150, DUR],
                 [0.45, 0.9, 1.8, 2.4, 1.3, 0.7])
sL = flutter_speed(scale=1.0, depth_env=depth, seed_off=0)
sR = flutter_speed(scale=1.0, depth_env=depth, seed_off=5)   # decorrelated L/R
bedL = wow_resample(bedL, sL)
bedR = wow_resample(bedR, sR)
bpk = max(np.abs(bedL).max(), np.abs(bedR).max())
bed_env = ramp_env([0, 10, 55, 120, 165, DUR - 4, DUR],
                   [0.0, 0.55, 0.9, 1.0, 0.85, 0.55, 0.0])
L += 0.40 * bed_env * bedL / bpk
R += 0.40 * bed_env * bedR / bpk

# wobbling pilot thread (4875 Hz, the 13th-harmonic pilot of the real signal)
pilot = np.sin(2 * np.pi * 4875.0 * t)
pilot = wow_resample(pilot, flutter_speed(0.8, depth_env=depth, seed_off=9))
pgate = smooth_gate(14.0, DUR - 6.0, 16.0, 30.0)   # pilot is the last to leave
L += 0.014 * pgate * pilot
R += 0.014 * pgate * np.roll(pilot, SR // 5)

# ------------------------------ 2. real DQPSK texture, smeared and bent ------
bp_b, bp_a = sg.butter(3, [500 / (SR / 2), 6500 / (SR / 2)], "band")


def wow_texture(t0_cap, dur_cap, depth_scale, soff):
    """Real modem buzz -> band-pass -> micro-smear -> deep wow-bend.
    Returns a stereo pair as long as the bent signal."""
    x = sg.lfilter(bp_b, bp_a, grab(t0_cap, dur_cap, fade=2.0))
    micro = exp_ir(0.30, 0.55, 5000, soff)         # short tail: hops glow
    x = fftconvolve(x, micro)[:len(x)]
    # bend with a DEEPER flutter than the bed (texture is the most warped voice)
    sp = flutter_speed(scale=depth_scale, seed_off=soff + 20)[:len(x)]
    x = wow_resample(x, sp)
    x /= (np.abs(x).max() + 1e-9)
    return x, np.roll(x, 911)                       # tiny decorrelation


texA, texAr = wow_texture(50.0, 14.0, 2.2, soff=30)    # N512 rung r0
texB, texBr = wow_texture(210.0, 14.0, 2.8, soff=40)   # d2x rung r5 (worst-bent)


def edge_fade(x, fade_s):
    nf = int(fade_s * SR)
    w = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
    y = x.copy()
    y[:nf] *= w
    y[-nf:] *= w[::-1]
    return y


texA, texAr = edge_fade(texA, 3.0), edge_fade(texAr, 3.0)
texB, texBr = edge_fade(texB, 3.0), edge_fade(texBr, 3.0)
place(L, R, texA, texAr, 34.0, gain=0.16, pan=-0.15)
place(L, R, texB, texBr, 78.0, gain=0.24, pan=0.10)      # worst-flutter zone
place(L, R, texA, texAr, 124.0, gain=0.18, pan=0.20)
# a quiet near-dry ghost of the d2x buzz surfaces in the recede
ghost = sg.lfilter(bp_b, bp_a, grab(228.0, 12.0, fade=3.0))
ghost = wow_resample(ghost, flutter_speed(1.4, seed_off=55)[:len(ghost)])
ghost /= (np.abs(ghost).max() + 1e-9)
place(L, R, ghost, np.roll(ghost, 733), 162.0, gain=0.12, pan=-0.1)

# ------------------------- 3. frame pulse that drifts in and out of lock -----
# Real preamble tick (800->3200 Hz) at the measured N512 frame period, but its
# firing phase WANDERS against an implied steady grid -> tightens, loosens,
# slips out of lock. The struggle of the decoder hunting for sync.
PERIOD = 1.372896                # measured N512 frame period (palette)
tick_n = int(0.25 * SR)
tt = np.arange(tick_n) / SR
tick = sg.chirp(tt, f0=800, t1=0.25, f1=3200, method="linear")
tick *= np.sin(np.pi * tt / 0.25) ** 2
lp_b, lp_a = sg.butter(4, 2600 / (SR / 2), "low")
tick = sg.lfilter(lp_b, lp_a, tick)
tick /= np.abs(tick).max()
# pulse present mid-piece, swelling around the worst flutter, never on the grid
pulse_env_t = [30.0, 55.0, 95.0, 140.0, 160.0]
pulse_env_v = [0.0,  1.0,  1.0,  0.7,   0.0]
DRIFT_AMP = 0.42                 # +/- seconds of phase wander (huge -> slips)
DRIFT_HZ = 0.045                 # slow wander cycle
k = 0
tk = 30.0
while tk < 160.0:
    # phase drift: where it ACTUALLY fires vs the ideal grid time
    drift = DRIFT_AMP * np.sin(2 * np.pi * DRIFT_HZ * tk + 0.6) \
        + 0.10 * np.sin(2 * np.pi * 0.17 * tk)
    t_fire = tk + drift
    if 0 < t_fire < DUR - 0.3:
        g = np.interp(t_fire, pulse_env_t, pulse_env_v)
        # bend each tick a touch too, and vary level so some ticks "miss"
        miss = 0.55 + 0.45 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.31 * tk + 1.3))
        place(L, R, tick, tick, t_fire, gain=0.05 * g * miss,
              pan=0.30 * (-1) ** k)
    tk += PERIOD
    k += 1
print(f"[pulse] {k} frame ticks fired at {PERIOD:.6f}s grid, drifting "
      f"+/-{DRIFT_AMP:.2f}s out of lock")

# --------------------------------- 4. real chirp pip + stretched ghost -------
# The real up-chirp opens the track (the tape rolling up), then a 12x-stretched
# wow-bent ghost answers -- the sweep itself made seasick.
pip = grab(20.74, 0.5, fade=0.05)
pip /= np.abs(pip).max()
place(L, R, pip, pip, 4.0, gain=0.26)
pL, pR = reverb_st(pip, rt60=5.0, lp_hz=6000, seed_off=60)
m = max(np.abs(pL).max(), np.abs(pR).max())
place(L, R, pL / m, pR / m, 4.05, gain=0.18)

# stretched up-chirp swell, bent with wow
d = 0.2 * 12
nsw = int(d * SR)
ts = np.arange(nsw) / SR
sweep = sg.chirp(ts, f0=500, t1=d, f1=5000, method="linear")
sweep *= np.sin(np.pi * ts / d) ** 2
sweep = wow_resample(sweep, flutter_speed(2.5, seed_off=70)[:nsw])
swL, swR = reverb_st(sweep, rt60=4.0, lp_hz=6500, seed_off=72)
m = max(np.abs(swL).max(), np.abs(swR).max())
place(L, R, swL / m, swR / m, 6.0, gain=0.16, pan=-0.2)
# a wow-bent DOWN sweep marks the recede
dn = sg.chirp(ts, f0=5000, t1=d, f1=500, method="linear") * np.sin(np.pi * ts / d) ** 2
dn = wow_resample(dn, flutter_speed(2.0, seed_off=74)[:nsw])
dnL, dnR = reverb_st(dn, rt60=4.5, lp_hz=6000, seed_off=76)
m = max(np.abs(dnL).max(), np.abs(dnR).max())
place(L, R, dnL / m, dnR / m, 150.0, gain=0.15, pan=0.2)

# ------------------------ 5. real Schroeder sounder smeared into a wash ------
schro = grab(21.96, 3.0, fade=0.3)
schro = sg.lfilter(bp_b, bp_a, schro)
schro = wow_resample(schro, flutter_speed(1.8, seed_off=80)[:len(schro)])
sLs, sRs = reverb_st(schro, rt60=6.5, lp_hz=5000, seed_off=82)
m = max(np.abs(sLs).max(), np.abs(sRs).max())
place(L, R, sLs / m, sRs / m, 70.0, gain=0.22)            # rises into the worst zone
place(L, R, sRs / m, sLs / m, 112.0, gain=0.14)

# ------------------------------------------ 6. real tape noisefloor warmth ---
nfb = grab(43.0, 2.5, fade=0.4)
nfb /= np.abs(nfb).max()
bedn = np.tile(nfb, int(np.ceil(N / len(nfb))))[:N]
hiss_env = ramp_env([0, 10, 100, 175, DUR], [0.4, 1.0, 1.2, 1.0, 1.4])
L += 0.016 * bedn * hiss_env
R += 0.016 * np.roll(bedn, SR // 3) * hiss_env

# ------------------------------------------------------- fades + mastering ---
nin, nout = int(2.0 * SR), int(4.0 * SR)
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
    mix = 0.875 * np.tanh(mix / 0.875)          # gentle soft limiter
    print(f"[master] soft limiter engaged (pre-peak {20*np.log10(pk):.2f} dBFS)")

sf.write(OUT, mix, SR, subtype="PCM_16")

# ------------------------------------------------------------------- QA ------
peak_db = 20 * np.log10(np.abs(mix).max())
rms_db = 20 * np.log10(np.sqrt(np.mean(mix ** 2)))
print(f"\n[QA] {OUT}")
print(f"[QA] duration  {len(mix)/SR:.2f} s   peak {peak_db:+.2f} dBFS   "
      f"rms {rms_db:+.2f} dBFS")

mono = mix.mean(axis=1)
spec = np.abs(np.fft.rfft(mono)) ** 2
freqs = np.fft.rfftfreq(len(mono), 1 / SR)
edges = [22, 44, 88, 177, 354, 707, 1414, 2828, 5657, 11314, 22627]
tot = spec.sum()
print("[QA] 10-band spectral balance (% of energy):")
for lo, hi in zip(edges[:-1], edges[1:]):
    m_ = (freqs >= lo) & (freqs < hi)
    print(f"      {lo:>5d}-{hi:<5d} Hz : {100*spec[m_].sum()/tot:5.1f} %")

# onset-event rate (loudness-weighted spectral flux, mean+2.5std, 0.3 s re-arm)
f_, tt_, S = sg.stft(mono, SR, nperseg=2048, noverlap=1536)
flux = np.maximum(np.diff(np.abs(S), axis=1), 0).sum(axis=0)
thr = flux.mean() + 2.5 * flux.std()
hop_s = 512 / SR
rearm = int(0.3 / hop_s)
onsets, last = 0, -10 ** 9
for i, v in enumerate(flux):
    if v > thr and i - last > rearm:
        onsets += 1
        last = i
    elif v > thr:
        last = i
print(f"[QA] onset events: {onsets} total = {onsets/DUR:.2f}/s "
      f"(woozy/struggle target: low, well under ~0.7/s)")

# flutter readout: measure the actual instantaneous-pitch wobble we imposed on
# the bed by tracking a strong carrier (1500 Hz F#6) band's phase derivative
ff, ttf, Sx = sg.stft(mono, SR, nperseg=4096, noverlap=3072)
band = (ff > 1400) & (ff < 1600)
if band.any():
    inst = np.abs(Sx[band]).sum(axis=0)
    inst = inst / (inst.max() + 1e-12)
    print(f"[QA] 1500 Hz F#6 band energy wobble: std/mean = "
          f"{inst.std()/(inst.mean()+1e-12):.3f} (audible flutter -> > ~0.15)")

print("[QA] energy arc (RMS dBFS per 20 s window):")
for w0 in range(0, int(DUR), 20):
    seg = mono[w0 * SR:(w0 + 20) * SR]
    print(f"      {w0:>3d}-{w0+20:<3d} s : "
          f"{20*np.log10(np.sqrt(np.mean(seg**2))+1e-12):6.1f} dB")
