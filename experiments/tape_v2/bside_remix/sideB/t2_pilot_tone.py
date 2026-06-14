#!/usr/bin/env python3
"""
t2.wav -- "Pilot Tone"  (B-side track 2 of 9)

The 4875 Hz pilot -- the single carrier the receiver locks onto, the one tone
that runs through the ENTIRE real transmission -- as a sustained, beating drone.
Underneath it the data carrier grid blooms in 7-limit just intonation over the
375 Hz fundamental, each partial breathing on its own prime-period LFO. The REAL
down-chirp from the capture (5000->500 Hz, the tape signing off) is grabbed from
tape10_run1.wav and stretched ~12x into a slow, dark, recurring swell.

Weightless, Eno-esque. Almost no onsets -- a held field that opens, beats, and
recedes to the pilot alone over tape hiss.

Materials, all quoted from the REAL signal (palette.json):
  * 4875 Hz pilot (13th harmonic of 375 Hz, ~D# -36c) -- the protagonist drone,
    a cluster of micro-detuned oscillators that BEAT against each other (this is
    literally the lock tone the demodulator tracks).
  * The real N512 carrier grid (harmonics 2..24 of 375 Hz) retuned to a 7-limit
    just-intonation set, blooming in and out under the pilot.
  * The REAL capture down-chirp (capture t=380.45 s) phase-vocoder time-stretched
    ~12x into a 2.4 s falling swell, recurring like the signal repeatedly
    saying goodbye.
  * A 12 s slab of the REAL N512 DQPSK carrier texture (capture 50-62 s),
    Paulstretch-frozen into a lush pad so the exact comb spectrum survives while
    the buzz becomes a wash -- the data made weightless.
  * The real up-chirp pip opens it (capture 20.74 s), the tape coming alive.
  * Real tape noisefloor (capture 43.0 s) as the warmth bed.

Form (210 s): pilot fades up alone -> grid blooms in JI, first slow down-chirp
swell -> full beating field, frozen-data pad, recurring swells -> grid recedes,
the pilot is left ringing alone over hiss, last distant down-chirp.

Deps: python3 + numpy/scipy/soundfile only. Seed fixed and logged.
"""

import numpy as np
import soundfile as sf
from scipy import signal as sg
from scipy.signal import fftconvolve

SEED = 20260612
rng = np.random.default_rng(SEED)
print(f"[t2_pilot_tone] seed = {SEED}")

SR = 48000
DUR = 210.0
N = int(DUR * SR)
t = np.arange(N) / SR

CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/t2.wav"

cap, cap_sr = sf.read(CAPTURE, dtype="float64")
assert cap_sr == SR and cap.ndim == 1, "expected mono 48k capture"

PILOT = 4875.0    # 13th harmonic of 375 Hz -- the lock tone
F0 = 375.0        # grid fundamental (F#4 +23c)

# ----------------------------------------------------------------- helpers --
def grab(t0, dur, fade=0.5):
    """Slice real capture audio with raised-cosine edge fades."""
    a = cap[int(t0 * SR): int((t0 + dur) * SR)].copy()
    nf = int(fade * SR)
    if nf > 0 and 2 * nf < len(a):
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

def reverb_st(x, rt60=6.0, lp_hz=6000.0, seed_off=0):
    """Stereo reverb: two decorrelated synthetic IRs."""
    irL = exp_ir(rt60, rt60 * 1.1, lp_hz, seed_off)
    irR = exp_ir(rt60, rt60 * 1.1, lp_hz, seed_off + 1)
    return fftconvolve(x, irL), fftconvolve(x, irR)

def spectral_blur(x, blur_s=1.8):
    """Paulstretch-style freeze: time-smooth STFT magnitudes and randomize
    phases -> buzzy DQPSK texture becomes a static lush pad while the exact
    carrier-grid comb spectrum is preserved."""
    _, _, S = sg.stft(x, SR, nperseg=4096, noverlap=3072)
    mag = np.abs(S)
    k = max(3, int(blur_s * SR / 1024))
    kern = np.hanning(k)
    kern /= kern.sum()
    mag = np.apply_along_axis(lambda m: np.convolve(m, kern, "same"), 1, mag)
    ph = rng.uniform(0, 2 * np.pi, mag.shape)
    _, y = sg.istft(mag * np.exp(1j * ph), SR, nperseg=4096, noverlap=3072)
    return y

def phase_vocoder_stretch(x, factor, nperseg=2048, noverlap=None):
    """Phase-vocoder time-stretch (preserves pitch, lengthens duration).
    Used to slow the REAL down-chirp ~12x into a dark falling swell while
    keeping its 5000->500 Hz sweep intact."""
    if noverlap is None:
        noverlap = nperseg * 3 // 4
    hop = nperseg - noverlap
    f, tt, S = sg.stft(x, SR, nperseg=nperseg, noverlap=noverlap)
    mag = np.abs(S)
    ph = np.angle(S)
    n_in = S.shape[1]
    n_out = int(n_in * factor)
    out = np.zeros((S.shape[0], n_out), dtype=complex)
    phase_acc = ph[:, 0].copy()
    src = np.linspace(0, n_in - 1, n_out)
    expected = 2 * np.pi * hop * np.arange(S.shape[0]) / nperseg
    for i, s in enumerate(src):
        i0 = int(np.floor(s))
        i1 = min(i0 + 1, n_in - 1)
        frac = s - i0
        m = (1 - frac) * mag[:, i0] + frac * mag[:, i1]
        out[:, i] = m * np.exp(1j * phase_acc)
        dphi = ph[:, i1] - ph[:, i0] - expected
        dphi = np.mod(dphi + np.pi, 2 * np.pi) - np.pi
        phase_acc = phase_acc + expected + dphi
    _, y = sg.istft(out, SR, nperseg=nperseg, noverlap=noverlap)
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

# ====================================================================
# 1. THE PILOT -- 4875 Hz as a sustained, BEATING drone (the protagonist)
# ====================================================================
# The demodulator locks to this single carrier. We render it as a small
# cluster of oscillators detuned by a few Hz so they audibly BEAT against
# each other -- a slow shimmering wobble, the sound of a lock being held.
# It is present from very early and is the LAST thing standing at the end.
pilot_gate = smooth_gate(0.0, DUR, rise=10.0, fall=22.0)
# breathing on prime-period LFOs (13 s nods to the 13th harmonic)
pbreath = (0.62
           + 0.22 * np.sin(2 * np.pi * t / 13.0 + 0.4)
           + 0.10 * np.sin(2 * np.pi * t / 29.0 + 1.7)
           + 0.06 * np.sin(2 * np.pi * t / 7.0 + 3.1))
pilotL = np.zeros(N)
pilotR = np.zeros(N)
# detunes chosen so beat periods are slow & musical (sub-Hz to a few Hz)
pilot_offsets = [(-2.7, 0.95, -0.45), (-0.9, 1.00, -0.15),
                 (0.0, 1.00, 0.0), (1.1, 0.90, 0.20),
                 (3.3, 0.78, 0.45), (6.7, 0.55, 0.0)]
for df, w, pan in pilot_offsets:
    phL = rng.uniform(0, 2 * np.pi)
    phR = rng.uniform(0, 2 * np.pi)
    # tiny vibrato so the lock "wanders" like a real PLL tracking flutter
    vib = 1.5 * np.sin(2 * np.pi * t / 11.0 + rng.uniform(0, 6.28))
    inst = PILOT + df + vib
    phase = 2 * np.pi * np.cumsum(inst) / SR
    pilotL += w * (1 - pan) * np.sin(phase + phL)
    pilotR += w * (1 + pan) * np.sin(phase + phR)
ppk = max(np.abs(pilotL).max(), np.abs(pilotR).max())
pilot_amp = 0.30 * pilot_gate * pbreath
L += pilot_amp * pilotL / ppk
R += pilot_amp * pilotR / ppk

# a soft sub-octave of the pilot (2437.5 Hz, the 6.5th... actually pilot/2)
# gives it body without muddying -- gated to the middle of the piece
sub_gate = smooth_gate(30.0, 175.0, 25.0, 25.0)
subb = 0.7 + 0.3 * np.sin(2 * np.pi * t / 19.0 + 0.9)
L += 0.045 * sub_gate * subb * np.sin(2 * np.pi * (PILOT / 2) * t)
R += 0.045 * sub_gate * subb * np.sin(2 * np.pi * (PILOT / 2 + 0.4) * t + 1.1)
print(f"[pilot] {len(pilot_offsets)} beating oscillators around {PILOT:.0f} Hz "
      f"(+ {PILOT/2:.0f} Hz sub)")

# ====================================================================
# 2. CARRIER GRID bloom in 7-limit JUST INTONATION under the pilot
# ====================================================================
# The real N512 grid = harmonics 2..24 of 375 Hz. Map each to the nearest
# member of a 7-limit just-intonation ratio lattice built ON the 375 Hz
# fundamental, so the bloom is consonant with the harmonic-series grid yet
# distinctly "tuned". Each partial breathes on its own prime-period LFO.
real_carriers = [750, 1125, 1500, 1875, 2250, 2625, 3000, 3375, 3750, 4125,
                 4500, 5250, 5625, 6000, 6375, 6750, 7125, 7500, 7875, 8250,
                 8625, 9000]
# 7-limit just ratios (octave-reduced), expanded across octaves of F0
JI_RATIOS = [1.0, 9 / 8, 5 / 4, 4 / 3, 3 / 2, 5 / 3, 7 / 4, 2.0]
ji_freqs = []
for octv in range(1, 6):                      # octaves above F0
    for r in JI_RATIOS:
        f = F0 * (2 ** (octv - 1)) * r
        if 600 <= f <= 9100:
            ji_freqs.append(f)
ji_freqs = sorted(set(round(f, 2) for f in ji_freqs))
# map each real carrier to nearest JI freq
mapped = {}
for fc in real_carriers:
    fj = min(ji_freqs, key=lambda x: abs(x - fc))
    mapped[fj] = mapped.get(fj, 0) + 1
ji_partials = sorted(mapped.items())          # (freq, weight_count)
print(f"[grid] {len(real_carriers)} real carriers -> {len(ji_partials)} "
      f"7-limit JI partials over {F0:.0f} Hz")

PRIMES = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]
gridL = np.zeros(N)
gridR = np.zeros(N)
n_p = len(ji_partials)
for rank, (f, cnt) in enumerate(ji_partials):
    # weight: lower & more-populated JI bins louder, rolloff with freq
    w = (cnt ** 0.5) / (f / F0) ** 0.7
    frac = rank / max(1, n_p - 1)             # low->high
    # arc: lows enter first and stay; highs bloom only near the middle
    t_on = 14.0 + 70.0 * frac ** 1.25
    t_off = DUR - 8.0 - 70.0 * frac ** 1.15
    if t_off <= t_on + 6:
        t_off = t_on + 18.0
    gate = smooth_gate(t_on, t_off, rise=18.0, fall=22.0)
    P = PRIMES[int(rng.integers(len(PRIMES)))]
    lfo = 0.55 + 0.45 * np.sin(2 * np.pi * t / P + rng.uniform(0, 6.28))
    env = w * gate * lfo
    df = rng.uniform(0.08, 0.30)              # L/R detune -> slow beating
    pan = rng.uniform(-0.40, 0.40)
    phL = rng.uniform(0, 6.28)
    phR = rng.uniform(0, 6.28)
    gridL += env * (1 - pan) * np.sin(2 * np.pi * (f + df / 2) * t + phL)
    gridR += env * (1 + pan) * np.sin(2 * np.pi * (f - df / 2) * t + phR)
gpk = max(np.abs(gridL).max(), np.abs(gridR).max())
# the grid swells under the pilot then recedes -- it never overwhelms the pilot
grid_arc = ramp_env([0, 14, 60, 105, 150, 195, DUR],
                    [0.0, 0.10, 0.85, 1.0, 0.80, 0.20, 0.0])
L += 0.34 * grid_arc * gridL / gpk
R += 0.34 * grid_arc * gridR / gpk

# ====================================================================
# 3. REAL down-chirp stretched ~12x -> slow recurring falling swell
# ====================================================================
# Grab the actual capture down-chirp (5000->500 Hz at capture t=380.62 s) and
# phase-vocoder stretch it ~12x. 0.2 s * 12 = ~2.4 s of slow descent: the tape
# signing off, recurring across the piece like the transmission repeatedly
# bidding farewell. Bandlimited + reverbed into a dark swell.
dnraw = grab(380.45, 0.62, fade=0.04)         # real down-chirp + a little air
dnraw /= (np.abs(dnraw).max() + 1e-12)
dn_st = phase_vocoder_stretch(dnraw, 12.0)
# emphasize the descent: gentle bandpass + smooth swell envelope
bp_b, bp_a = sg.butter(3, [350 / (SR / 2), 6500 / (SR / 2)], "band")
dn_st = sg.lfilter(bp_b, bp_a, dn_st)
ndn = len(dn_st)
swell_env = np.sin(np.pi * np.arange(ndn) / ndn) ** 1.5
dn_st *= swell_env
dnL, dnR = reverb_st(dn_st, rt60=7.0, lp_hz=5500, seed_off=30)
dm = max(np.abs(dnL).max(), np.abs(dnR).max())
# blend a touch of the dry stretched chirp so the descent reads clearly
dnpad = np.pad(dn_st, (0, len(dnL) - len(dn_st)))
dnpad /= (np.abs(dnpad).max() + 1e-12)
downA_L = 0.55 * dnpad + 0.9 * dnL / dm
downA_R = 0.55 * dnpad + 0.9 * dnR / dm
print(f"[downchirp] real down-chirp stretched 12x -> {ndn/SR:.2f} s swell")

# recurring placements, panning side to side, fainter as the piece thins
place(L, R, downA_L, downA_R, 44.0, gain=0.16, pan=-0.25)
place(L, R, downA_R, downA_L, 92.0, gain=0.19, pan=0.20)
place(L, R, downA_L, downA_R, 138.0, gain=0.15, pan=-0.15)
place(L, R, downA_R, downA_L, 186.0, gain=0.12, pan=0.30)   # last, distant

# ====================================================================
# 4. FROZEN REAL DATA -- N512 DQPSK texture Paulstretched into a pad
# ====================================================================
# 12 s of the actual modem buzz (capture 50-62 s) frozen so its exact carrier
# comb survives as a lush wash -- the data made weightless under the pilot.
tex = grab(50.0, 12.0)
texbp = sg.lfilter(bp_b, bp_a, tex)
wL, wR = reverb_st(texbp, rt60=6.5, lp_hz=5500, seed_off=10)
wL, wR = spectral_blur(wL, 1.8), spectral_blur(wR, 1.8)
wpk = max(np.abs(wL).max(), np.abs(wR).max())
wL, wR = wL / wpk, wR / wpk
nf = int(5.0 * SR)
wfade = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
for ch in (wL, wR):
    ch[:nf] *= wfade
    ch[-nf:] *= wfade[::-1]
place(L, R, wL, wR, 70.0, gain=0.16)          # blooms with the grid climax
place(L, R, wR * 0.8, wL * 0.8, 120.0, gain=0.11)   # mirrored softer return

# a near-dry ghost of the real buzz, micro-smeared, surfaces faintly mid-piece
# so the listener catches the actual transmission glowing through the field
dry = sg.lfilter(bp_b, bp_a, grab(52.0, 10.0, fade=4.0))
micro = exp_ir(0.30, 0.5, 4500, 60)
dry = fftconvolve(dry, micro)
lp4_b, lp4_a = sg.butter(3, 4400 / (SR / 2), "low")
dry = sg.lfilter(lp4_b, lp4_a, dry)
dry /= (np.abs(dry).max() + 1e-12)
place(L, R, dry, dry * 0.9, 100.0, gain=0.035, pan=0.1)

# ====================================================================
# 5. the real up-chirp PIP opens it (tape coming alive), then its ghost
# ====================================================================
pip = grab(20.74, 0.5, fade=0.05)
pip /= (np.abs(pip).max() + 1e-12)
place(L, R, pip, pip, 2.5, gain=0.20)
pL, pR = reverb_st(pip, rt60=6.0, lp_hz=6000, seed_off=40)
pm = max(np.abs(pL).max(), np.abs(pR).max())
place(L, R, pL / pm, pR / pm, 2.55, gain=0.16)

# ====================================================================
# 6. master arc + real tape-hiss warmth bed
# ====================================================================
arc = ramp_env([0, 10, 70, 110, 160, DUR - 4, DUR],
               [0.45, 0.70, 1.0, 1.0, 0.85, 0.55, 0.40])
L *= arc
R *= arc

# real noisefloor (capture 43.0-45.5 s) looped softly = tape warmth
nfb = grab(43.0, 2.5, fade=0.4)
nfb /= (np.abs(nfb).max() + 1e-12)
bed = np.tile(nfb, int(np.ceil(N / len(nfb))))[:N]
bed_env = ramp_env([0, 12, 180, DUR], [0.5, 1.0, 1.0, 1.7])
L += 0.014 * bed * bed_env
R += 0.014 * np.roll(bed, SR // 3) * bed_env

# ====================================================================
# 7. fades + mastering (2 s in / 4 s out)
# ====================================================================
nin, nout = int(2.0 * SR), int(4.0 * SR)
fi = 0.5 - 0.5 * np.cos(np.pi * np.arange(nin) / nin)
fo = 0.5 + 0.5 * np.cos(np.pi * np.arange(nout) / nout)
for ch in (L, R):
    ch[:nin] *= fi
    ch[-nout:] *= fo

mix = np.stack([L, R], axis=1)
assert np.isfinite(mix).all(), "NaN/Inf in mix!"
rms = np.sqrt(np.mean(mix**2))
mix *= 10 ** (-15.0 / 20) / rms               # RMS -> -15 dBFS
pk = np.abs(mix).max()
if pk > 10 ** (-1.0 / 20):
    drive = 0.84
    mix = drive * np.tanh(mix / drive)        # gentle soft limiter
    print(f"[master] soft limiter engaged (pre-peak {20*np.log10(pk):.2f} dBFS)")
    # re-target RMS after limiting, then guarantee peak <= -1 dBFS
    rms = np.sqrt(np.mean(mix**2))
    mix *= 10 ** (-15.0 / 20) / rms
    pk2 = np.abs(mix).max()
    ceil = 10 ** (-1.0 / 20)
    if pk2 > ceil:
        mix *= ceil / pk2

sf.write(OUT, mix, SR, subtype="PCM_16")

# ====================================================================
# QA
# ====================================================================
peak_db = 20 * np.log10(np.abs(mix).max() + 1e-12)
rms_db = 20 * np.log10(np.sqrt(np.mean(mix**2)) + 1e-12)
print(f"\n[QA] {OUT}")
print(f"[QA] duration  {len(mix)/SR:.2f} s   peak {peak_db:+.2f} dBFS   "
      f"rms {rms_db:+.2f} dBFS")
assert np.isfinite(mix).all(), "NaN in output!"

mono = mix.mean(axis=1)
spec = np.abs(np.fft.rfft(mono))**2
freqs = np.fft.rfftfreq(len(mono), 1 / SR)
edges = [22, 44, 88, 177, 354, 707, 1414, 2828, 5657, 11314, 22627]
tot = spec.sum()
print("[QA] 10-band spectral balance (% of energy):")
for lo, hi in zip(edges[:-1], edges[1:]):
    m_ = (freqs >= lo) & (freqs < hi)
    print(f"      {lo:>5d}-{hi:<5d} Hz : {100*spec[m_].sum()/tot:5.1f} %")

# pilot presence check: energy in a narrow band around 4875 Hz
pm_ = (freqs >= 4800) & (freqs <= 4950)
print(f"[QA] pilot band 4800-4950 Hz: {100*spec[pm_].sum()/tot:5.2f} % of energy")

# onset-event rate: loudness-weighted spectral flux, mean+2.5std, 0.3 s re-arm
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
        last = i
print(f"[QA] onset events: {onsets} total = {onsets/DUR:.3f}/s "
      f"(ambient target: well under 0.5/s)")

print("[QA] energy arc (RMS dBFS per 15 s window):")
for w0 in range(0, int(DUR), 15):
    seg = mono[w0 * SR:(w0 + 15) * SR]
    print(f"      {w0:>3d}-{w0+15:<3d} s : "
          f"{20*np.log10(np.sqrt(np.mean(seg**2))+1e-12):6.1f} dB")
