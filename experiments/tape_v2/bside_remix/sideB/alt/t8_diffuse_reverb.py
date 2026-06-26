#!/usr/bin/env python3
"""
t8_diffuse_reverb.py — B-side track 8: "DIFFUSE REVERB"  (~220 s)

The deep, tape-warm comedown after the peak. SPACE — dark ambient. The room
itself. This extends remix_concrete.py: every sound is the REAL tape10 capture
(deck + room + tape warmth, flutter 0.42%) — spectral-frozen, granulated,
reverberated, but never synthesised. The grid is a harmonic series on 375 Hz
(F#4 +23c), so simple resampling ratios land grains on an F# / B / C# low chord.

Form (220 s arc):
  0–18   silence breathing open: frozen Schroeder slab fades up from nothing.
  18–70  the room fills: vast spectral-frozen washes of the Schroeder sounder
         (two octaves down) + a low F#/B/C# drone built from pitched real-signal
         grains. Sub-fundamental 187.5/375 Hz body. Pilot 4875 Hz ghost-thread.
  70–108 swell toward the reveal: drone thickens, a stretched real up-chirp
         rises (×16) as a slow riser, the wash brightens by one octave.
  108–117 THE REVEAL: the untouched real DQPSK modem signal (N512 rung r0,
         preambles and all) surfaces DRY for ~9 s in the middle of the piece —
         the transmission itself, the soul of the record, laid bare.
  117–175 dissolution: the reveal is caught and dragged back under as a chain
         of lowpassed, pitch-dropping echoes on the frame grid; drone darkens.
  175–220 deep comedown: only the lowest frozen wash + sub-drone + a final
         real down-chirp (×16, two octaves down) sinking away into tape hiss.

LOW onset rate by design (dark ambient): no percussion, no gating; everything
is washes, drones, and slow swells. The lone "event" cluster is the reveal.

Deps: python3 + numpy/scipy/soundfile only.  Seed 20260618 (logged).
Output: t8.wav, stereo 48k/16bit, ~220 s, peak <= -1 dBFS, RMS ~ -15 dBFS,
2 s fade-in / 4 s fade-out.
"""

import numpy as np
import soundfile as sf
from scipy import signal as sg
from scipy.signal import fftconvolve
from scipy.ndimage import median_filter

SEED = 20260618
rng = np.random.default_rng(SEED)
print(f"[t8_diffuse_reverb] seed = {SEED}")

SR = 48000
DUR = 220.0
N = int(DUR * SR)
t = np.arange(N) / SR

CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/alt/t8.wav"

cap, cap_sr = sf.read(CAPTURE, dtype="float64")
assert cap_sr == SR and cap.ndim == 1, "expected mono 48k capture"

# ---- palette facts (from palette.json, measured on the real capture) --------
SCHROEDER_T = 21.9636        # Schroeder 64-tone sounder splash start (capture s)
CHIRP_UP_T = 20.8628         # real up-chirp 500->5000 Hz, 0.2 s (capture s)
CHIRP_DN_T = 380.6237        # real down-chirp 5000->500 Hz
N512_PRE0 = 46.8634          # first N512 preamble (capture s)
N512_T = 1.372896            # measured N512 frame period (s)
D2X_R5 = 205.3547            # d2x rung r5 capture start
N512_R0 = 46.8803            # N512 rung r0 capture start
N512_R9 = 345.3741           # N512 tail canary capture start
NOISEFLOOR_T = 43.0          # tape noisefloor region (capture s)
F0 = 375.0                   # grid fundamental (F#4 +23c)


# ---- helpers -----------------------------------------------------------------
def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-20))


def norm(x, target=0.1):
    return x * (target / (rms(x) + 1e-20))


def grab(t0, dur, fade=0.3):
    """Slice real capture audio with raised-cosine edge fades."""
    a = cap[int(t0 * SR): int((t0 + dur) * SR)].copy()
    nf = max(1, int(fade * SR))
    nf = min(nf, len(a) // 2)
    w = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
    a[:nf] *= w
    a[-nf:] *= w[::-1]
    return a


def resamp(x, ratio):
    """Playback-rate resample: ratio>1 -> higher pitch & shorter."""
    n_out = max(1, int(len(x) / ratio))
    idx = np.arange(n_out) * ratio
    return np.interp(idx, np.arange(len(x)), x)


def env_bp(n, points):
    """Breakpoint envelope over n samples; points = [(t_s, value), ...]."""
    tt = np.arange(n) / SR
    ts = np.array([p[0] for p in points])
    vs = np.array([p[1] for p in points])
    return np.interp(tt, ts, vs)


def place(xL, xR, t0, gain=1.0, pan=0.0):
    """Add a stereo event into the mix at time t0; pan in [-1,1] (0=center)."""
    if xR is None:
        xR = xL
    gL = gain * min(1.0, 1.0 - pan)
    gR = gain * min(1.0, 1.0 + pan)
    i0 = int(t0 * SR)
    if i0 < 0:
        xL, xR = xL[-i0:], xR[-i0:]
        i0 = 0
    for bus, x, g in ((L, xL, gL), (R, xR, gR)):
        nn = min(len(x), len(bus) - i0)
        if nn > 0:
            bus[i0:i0 + nn] += g * x[:nn]


# ---- reverb (synthetic exponential-decay IR, like remix_ambient) -------------
def exp_ir(rt60, dur, lp_hz, seed_off):
    r = np.random.default_rng(SEED + seed_off)
    n = int(dur * SR)
    x = r.standard_normal(n) * np.exp(-6.91 * np.arange(n) / (rt60 * SR))
    b, a = sg.butter(2, lp_hz / (SR / 2), "low")
    x = sg.lfilter(b, a, x)
    bh, ah = sg.butter(2, 110 / (SR / 2), "high")
    x = sg.lfilter(bh, ah, x)
    return x / (np.sqrt(np.sum(x ** 2)) + 1e-12)


def reverb_st(x, rt60=6.0, lp_hz=5500.0, seed_off=0):
    irL = exp_ir(rt60, rt60 * 1.05, lp_hz, seed_off)
    irR = exp_ir(rt60, rt60 * 1.05, lp_hz, seed_off + 1)
    return fftconvolve(x, irL), fftconvolve(x, irR)


def spectral_blur(x, blur_s=2.0, nfft=4096):
    """Paulstretch-style freeze: time-smooth STFT magnitudes AND randomise
    phases -> turns buzzy/transient DQPSK grain texture into a static lush
    drone while keeping the exact carrier-grid comb spectrum. This is what
    removes the per-grain ONSETS so a granular bus reads as one continuous
    diffuse wash, not pointillism. (Borrowed from remix_ambient.spectral_blur.)"""
    nov = nfft - nfft // 4
    _, _, S = sg.stft(x, SR, nperseg=nfft, noverlap=nov)
    mag = np.abs(S)
    k = max(3, int(blur_s * SR / (nfft // 4)))
    kern = np.hanning(k)
    kern /= kern.sum()
    mag = np.apply_along_axis(lambda m: np.convolve(m, kern, "same"), 1, mag)
    ph = rng.uniform(0, 2 * np.pi, mag.shape)
    _, y = sg.istft(mag * np.exp(1j * ph), SR, nperseg=nfft, noverlap=nov)
    return y


# ---- spectral freeze: FFT magnitude hold, random-phase OLA -------------------
def spectral_freeze(src, dur, nfft=8192, ratio=1.0):
    """Average magnitude spectrum of src, resynthesised with random phases per
    hop (OLA). ratio pitches the frozen slab by resampling. Turns the buzzy /
    splashy real material into a static, vast wash while keeping its exact
    spectral colour."""
    win = np.hanning(nfft)
    mags = []
    step = nfft // 2
    for i in range(0, max(1, len(src) - nfft), step):
        mags.append(np.abs(np.fft.rfft(src[i:i + nfft] * win)))
    if not mags:
        mags = [np.abs(np.fft.rfft(np.pad(src, (0, nfft - len(src))) * win))]
    mag = np.mean(mags, axis=0)
    n_out = int(dur * SR * max(ratio, 1.0)) + nfft
    out = np.zeros(n_out + nfft)
    hop = nfft // 4
    for pos in range(0, n_out, hop):
        ph = rng.uniform(0, 2 * np.pi, len(mag))
        out[pos:pos + nfft] += np.fft.irfft(mag * np.exp(1j * ph), nfft) * win
    out = out[:n_out]
    if ratio != 1.0:
        out = resamp(out, ratio)
    return norm(out[: int(dur * SR)], 0.1)


L = np.zeros(N)
R = np.zeros(N)

# =============================================================================
# 1. THE ROOM ITSELF — Schroeder sounder spectral-frozen into vast washes
# =============================================================================
print("[render] spectral-frozen Schroeder washes (the room)")
schroeder = grab(SCHROEDER_T + 0.2, 3.4, fade=0.25)

# (a) deepest bed: two octaves down, decorrelated L/R, runs the whole piece.
bedL = spectral_freeze(schroeder, DUR, ratio=0.25)
bedR = spectral_freeze(schroeder, DUR, ratio=0.25)
bed_env = env_bp(N, [(0, 0.0), (18, 0.85), (40, 0.9), (70, 0.8),
                     (105, 0.55), (108, 0.30), (117, 0.30), (140, 0.7),
                     (175, 0.85), (200, 0.7), (220, 0.0)])
L += bedL * bed_env * 0.085
R += bedR * bed_env * 0.085

# (b) one-octave-down wash: brighter, swells in toward the reveal then recedes.
washL = spectral_freeze(schroeder, DUR, ratio=0.5)
washR = spectral_freeze(schroeder, DUR, ratio=0.5)
# gentle band-limit so it sits as a mid wash, not hiss
sos_w = sg.butter(4, [180, 4200], "band", fs=SR, output="sos")
washL = sg.sosfilt(sos_w, washL)
washR = sg.sosfilt(sos_w, washR)
wash_env = env_bp(N, [(0, 0.0), (30, 0.2), (60, 0.45), (95, 0.75),
                      (106, 0.85), (108, 0.0), (117, 0.0), (135, 0.5),
                      (165, 0.35), (185, 0.15), (220, 0.0)])
L += norm(washL, 0.1) * wash_env * 0.16
R += norm(washR, 0.1) * wash_env * 0.16

# (c) native-pitch frozen swells: discrete "breaths" of the room, reverbed —
# each a full-Hann slow swell so it reads as a wave of the room, not an attack.
for (dur, ratio, t0, gain, pan, soff) in [
        (12.0, 1.0, 34.0, 0.10, -0.35, 11),
        (14.0, 0.5, 78.0, 0.13, 0.40, 13),
        (16.0, 0.25, 150.0, 0.12, -0.25, 15),
        (18.0, 0.25, 188.0, 0.11, 0.20, 17)]:
    mom = spectral_freeze(schroeder, dur, ratio=ratio)
    mom *= np.hanning(len(mom))
    sL, sR = reverb_st(mom, rt60=8.0, lp_hz=4800, seed_off=soff)
    m = max(np.abs(sL).max(), np.abs(sR).max(), 1e-9)
    place(sL / m, sR / m, t0, gain, pan)

# =============================================================================
# 2. LOW F#/B/C# DRONE from PITCHED real-signal grains
#    Real DQPSK carrier audio, granulated and resampled by chord ratios. The
#    375 Hz harmonic grid means ratios {1/8,1/6,1/5,1/4,1/3,1/2} drop carriers
#    onto F#/B/C#/A# low chord tones. This is the "real-capture grains pitched
#    into a low drone" called for in the brief.
# =============================================================================
print("[render] low F#/B/C# drone (pitched real-signal grains, spectrally smeared)")
src_n512 = norm(grab(N512_R0 + 1.0, 32.0, fade=1.0), 0.1)
src_d2x = norm(grab(D2X_R5 + 1.0, 42.0, fade=1.0), 0.1)
src_tail = norm(grab(N512_R9 + 1.0, 32.0, fade=1.0), 0.1)

# The drone is rendered into its OWN buffer, then run through spectral_blur so
# the per-grain attacks vanish into one continuous diffuse wash (low onset
# rate) — exactly the "real-capture grains pitched into a low drone" intent.
droneL = np.zeros(N)
droneR = np.zeros(N)


def grain_into(buf_l, buf_r, t0, t1, src, ratios, weights, dur_rng, dens_bp,
               pan_rng=(-0.5, 0.5), lp_hz=None):
    """Overlap-add long Hann grains of real capture audio into a buffer, each
    resampled by a chord ratio so it lands on an F#/B/C# chord tone. Output is
    spectrally smeared afterward, so dense overlap here just thickens the drone."""
    tcur = t0
    n_src = len(src)
    while tcur < t1:
        dens = np.interp(tcur, [p[0] for p in dens_bp], [p[1] for p in dens_bp])
        out_dur = rng.uniform(*dur_rng)
        ratio = rng.choice(ratios, p=weights)
        n_out = int(out_dur * SR)
        n_need = int(n_out * ratio) + 2
        if n_need < n_src:
            p0 = int(rng.integers(0, n_src - n_need))
            idx = np.arange(n_out) * ratio
            g = np.interp(idx, np.arange(n_need), src[p0:p0 + n_need])
            if lp_hz:
                sos = sg.butter(3, lp_hz, "lp", fs=SR, output="sos")
                g = sg.sosfilt(sos, g)
            g *= np.hanning(n_out)
            pan = rng.uniform(*pan_rng)
            i0 = int(tcur * SR)
            for buf, gp in ((buf_l, 1 - pan), (buf_r, 1 + pan)):
                nn = min(len(g), len(buf) - i0)
                if i0 >= 0 and nn > 0:
                    buf[i0:i0 + nn] += g[:nn] * min(1.0, gp)
        tcur += rng.exponential(1.0 / dens)


# A: sub-drone emergence (deep — 3 octaves down lands on low F#/B/C#)
grain_into(droneL, droneR, 12.0, 74.0, src_d2x,
           [0.125, 1 / 6, 0.2, 0.25, 1 / 3],
           [0.30, 0.18, 0.12, 0.25, 0.15], (1.2, 2.4),
           [(12, 2.0), (74, 2.4)], lp_hz=2200)
# B: thickening chorale toward the reveal (slightly higher, still chordal)
grain_into(droneL, droneR, 58.0, 110.0, src_n512,
           [0.25, 1 / 3, 0.5, 2 / 3],
           [0.30, 0.20, 0.32, 0.18], (1.0, 2.0),
           [(58, 2.2), (110, 2.8)], lp_hz=3000)
# C: dissolution drone (tail-canary grains, darker, longer, octave+ down)
grain_into(droneL, droneR, 117.0, 202.0, src_tail,
           [0.125, 1 / 6, 0.25, 1 / 3, 0.5],
           [0.28, 0.18, 0.26, 0.16, 0.12], (1.6, 3.0),
           [(117, 2.2), (202, 1.2)], lp_hz=1800)

# Smear the whole drone bus -> continuous diffuse wash (kills per-grain onsets).
print("[render]   spectral-blur of drone bus")
droneL = spectral_blur(droneL, blur_s=2.2)
droneR = spectral_blur(droneR, blur_s=2.2)
nd = min(len(droneL), N)
drone_env = env_bp(N, [(0, 0), (14, 0.0), (30, 0.55), (74, 0.62), (95, 0.66),
                       (108, 0.55), (117, 0.55), (140, 0.6), (175, 0.5),
                       (200, 0.32), (220, 0)])
droneL = norm(droneL[:nd], 0.1)
droneR = norm(droneR[:nd], 0.1)
L[:nd] += droneL * drone_env[:nd] * 0.30
R[:nd] += droneR * drone_env[:nd] * 0.30

# Sub-fundamental body: real grains dropped a full 3 octaves (1/8) give 375/187.5
# Hz weight; LP-shelved so it's pure room body, no transient.
sub_env = env_bp(N, [(0, 0), (20, 0.4), (45, 0.8), (90, 0.9), (108, 0.5),
                     (117, 0.5), (140, 0.8), (185, 0.6), (220, 0)])
sub_grains = norm(grab(D2X_R5 + 5.0, 30.0, fade=1.0), 0.1)
sub_slab = resamp(np.tile(sub_grains, 3), 0.125)  # 3 octaves down, long
sos_sub = sg.butter(4, 320, "lp", fs=SR, output="sos")
sub_slab = sg.sosfilt(sos_sub, sub_slab)
sub_slab = norm(sub_slab, 0.1)
nsub = min(len(sub_slab), N)
L[:nsub] += sub_slab[:nsub] * sub_env[:nsub] * 0.05
R[:nsub] += np.roll(sub_slab, SR // 5)[:nsub] * sub_env[:nsub] * 0.05

# =============================================================================
# 3. PILOT GHOST-THREAD — derived from the real pilot region (4875 Hz, 13th
#    harmonic), pulled as a thin band-passed slab of the actual capture so even
#    the high thread is REAL signal, not a synth tone.
# =============================================================================
print("[render] pilot ghost-thread (real 4875 Hz band)")
pilot_src = grab(N512_R0 + 4.0, 24.0, fade=0.5)
sos_pilot = sg.butter(6, [4700, 5050], "band", fs=SR, output="sos")
pilot_band = sg.sosfilt(sos_pilot, pilot_src)
pilot_band = norm(pilot_band, 0.1)
pilot_loop = np.tile(pilot_band, int(np.ceil(N / len(pilot_band))))[:N]
pilot_env = env_bp(N, [(0, 0), (25, 0.6), (70, 0.9), (106, 1.0), (108, 0.0),
                       (117, 0.0), (130, 0.5), (170, 0.3), (200, 0.0),
                       (220, 0)])
L += pilot_loop * pilot_env * 0.018
R += np.roll(pilot_loop, SR // 3) * pilot_env * 0.018

# =============================================================================
# 4. STRETCHED REAL CHIRPS — risers / fallers (the tape spooling)
# =============================================================================
print("[render] stretched real chirp swells")
chirp_up = norm(grab(CHIRP_UP_T - 0.02, 0.26, fade=0.02), 0.1)
chirp_dn = norm(grab(CHIRP_DN_T - 0.02, 0.26, fade=0.02), 0.1)


def chirp_swell(real_chirp, ratio, t0, gain, pan, rt=6.0, lp=6000, soff=30):
    """Slow the real chirp down by `ratio` (<1 = slower & lower) into a swell,
    smooth-enveloped and reverbed."""
    x = resamp(real_chirp, ratio)
    x *= np.sin(np.pi * np.arange(len(x)) / len(x)) ** 2
    wL, wR = reverb_st(x, rt60=rt, lp_hz=lp, seed_off=soff)
    xp = np.pad(x, (0, len(wL) - len(x)))
    m = max(np.abs(wL).max(), np.abs(wR).max(), 1e-9)
    place(0.55 * xp + 0.9 * wL / m, 0.55 * xp + 0.9 * wR / m, t0, gain, pan)


# slow riser climbing toward the reveal (×16 stretch -> ~3.2 s sweep)
chirp_swell(chirp_up, 1 / 16, 92.0, 0.16, -0.2, soff=30)
chirp_swell(chirp_up, 1 / 8, 102.0, 0.14, 0.25, soff=32)
# the dissolution fallers (down-chirp), pitch-dropping deeper each time;
# in the comedown they recede (lower gain, longer reverb, darker) so the
# deepest section stays the calmest part of the piece.
chirp_swell(chirp_dn, 1 / 16, 150.0, 0.13, 0.2, rt=7.0, lp=4500, soff=34)
chirp_swell(chirp_dn, 1 / 16, 180.0, 0.10, -0.15, rt=8.0, lp=3800, soff=36)
# final 2-octave-down sinking sweep into the fade
chirp_swell(chirp_dn, 1 / 32, 202.0, 0.12, 0.0, rt=9.0, lp=3200, soff=38)

# =============================================================================
# 5. THE REVEAL — the untouched real modem signal surfaces DRY (~9 s)
#    N512 rung r0, starting just before a preamble; level-matched, otherwise raw.
#    Everything else ducks so the transmission is laid bare.
# =============================================================================
print("[render] THE REVEAL (untouched real signal, 108-117 s)")
duck = env_bp(N, [(0, 1), (105.0, 1), (109.5, 0.22), (115.5, 0.22),
                  (117.5, 1.0), (DUR, 1)])
L *= duck
R *= duck

rev = norm(grab(N512_PRE0 + 9 * N512_T - 0.10, 9.0, fade=0.05), 0.085)
re_env = np.ones(len(rev))
n_fi, n_fo = int(2.5 * SR), int(1.6 * SR)
re_env[:n_fi] = np.sin(np.linspace(0, np.pi / 2, n_fi)) ** 2
re_env[-n_fo:] = np.sin(np.linspace(np.pi / 2, 0, n_fo)) ** 2
# tiny stereo width via a few-ms decorrelation, keeps it "in the room"
place(rev * re_env, np.roll(rev, 31) * re_env, 108.0, 0.75, 0.0)

# =============================================================================
# 6. DISSOLUTION — the reveal caught and dragged under as lowpassed,
#    pitch-dropping echoes on the frame grid (T = N512 frame period). This is
#    the "then dissolving into lowpassed echoes" of the brief. Sparse & smeared
#    => keeps onset rate low while telling the story.
# =============================================================================
print("[render] dissolving lowpassed echoes on the frame grid")
echo_src = norm(grab(N512_PRE0 + 11 * N512_T, 2.6, fade=0.05), 0.1)
techo = 116.8
ratio = 1.0
g = 0.5
for i in range(9):
    lp = 2600 * (0.78 ** i) + 320
    sos = sg.butter(4, max(lp, 380), "lp", fs=SR, output="sos")
    e = sg.sosfilt(sos, resamp(echo_src, ratio))
    e *= np.hanning(len(e))
    wL, wR = reverb_st(e, rt60=5.0 + i * 0.6, lp_hz=max(lp, 800), seed_off=50 + i)
    m = max(np.abs(wL).max(), np.abs(wR).max(), 1e-9)
    pan = 0.4 if i % 2 == 0 else -0.4
    place(0.5 * np.pad(e, (0, len(wL) - len(e))) + 0.85 * wL / m,
          0.5 * np.pad(e, (0, len(wR) - len(e))) + 0.85 * wR / m,
          techo, g, pan)
    techo += N512_T * (1.0 + 0.12 * i)   # echoes spread apart as they sink
    ratio *= 0.85                         # each echo drops ~a major-ish step
    g *= 0.74

# =============================================================================
# 7. TAPE-WARMTH BED — real noisefloor (deck + room hiss), the ground the whole
#    piece rests on. Quiet, swelling slightly into the fade.
# =============================================================================
print("[render] real tape-noisefloor bed")
nfb = norm(grab(NOISEFLOOR_T, 2.5, fade=0.4), 0.1)
bed = np.tile(nfb, int(np.ceil(N / len(nfb))))[:N]
bed_warm = env_bp(N, [(0, 0.3), (12, 0.8), (110, 0.8), (175, 1.0), (220, 1.3)])
L += 0.014 * bed * bed_warm
R += 0.014 * np.roll(bed, SR // 3) * bed_warm

# =============================================================================
# 8. MASTER — hp, fades, level to -15 dBFS RMS, soft limit to <= -1 dBFS peak
# =============================================================================
print("[master] hp, fades, level, soft limit")
mix = np.stack([L, R], axis=1)
sos_hp = sg.butter(2, 24, "hp", fs=SR, output="sos")
mix = sg.sosfiltfilt(sos_hp, mix, axis=0)

fade = np.ones(N)
nin = int(2.0 * SR)
fade[:nin] = np.sin(np.linspace(0, np.pi / 2, nin)) ** 2
nout = int(4.0 * SR)
fade[-nout:] *= np.sin(np.linspace(np.pi / 2, 0, nout)) ** 2
mix *= fade[:, None]

TARGET_RMS = 10 ** (-15.0 / 20)
CEIL = 10 ** (-1.05 / 20)
for _ in range(4):
    mix *= TARGET_RMS / rms(mix)
    a = np.abs(mix)
    thr = 0.55
    over = a > thr
    mix[over] = np.sign(mix[over]) * (
        thr + (CEIL - thr) * np.tanh((a[over] - thr) / (CEIL - thr)))
peak = np.max(np.abs(mix))
if peak > CEIL:
    mix *= CEIL / peak

sf.write(OUT, mix, SR, subtype="PCM_16")

# =============================================================================
# 9. SELF-QA
# =============================================================================
x, _ = sf.read(OUT, dtype="float64")
mono = x.mean(axis=1)
dur_s = len(x) / SR
pk_db = 20 * np.log10(np.max(np.abs(x)) + 1e-20)
rms_db = 20 * np.log10(rms(x))
print(f"\n[QA] duration {dur_s:.1f} s   peak {pk_db:+.2f} dBFS   RMS {rms_db:+.2f} dBFS")
assert not np.any(np.isnan(x)), "NaN in output!"
ok = (205 <= dur_s <= 235) and (pk_db <= -1.0 + 1e-6) and (-16.5 <= rms_db <= -13.5)
print(f"[QA] spec gate (dur 205-235 / peak<=-1 / RMS -16.5..-13.5): {'PASS' if ok else 'FAIL'}")

# 10-band spectral balance (% of total energy)
spec = np.abs(np.fft.rfft(mono)) ** 2
freqs = np.fft.rfftfreq(len(mono), 1 / SR)
edges = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 24000]
tot = spec.sum()
print("[QA] 10-band balance (% energy):")
for lo, hi in zip(edges[:-1], edges[1:]):
    b = spec[(freqs >= lo) & (freqs < hi)].sum() / tot * 100
    print(f"   {lo:>5}-{hi:<5} Hz : {b:5.1f}  {'#' * int(b)}")

# onset rate via spectral flux (loudness-weighted, re-arm) — should be LOW
f_, tt_, S = sg.stft(mono, SR, nperseg=2048, noverlap=1536)
flux = np.maximum(np.diff(np.abs(S), axis=1), 0).sum(axis=0)
thr = median_filter(flux, 93) * 1.6 + 0.02 * flux.max()
pk_idx, _ = sg.find_peaks(flux, height=thr, distance=12)
on_t = tt_[1:][pk_idx]
secs = [("open", 0, 18), ("room fills", 18, 70), ("swell", 70, 108),
        ("REVEAL", 108, 117), ("dissolve", 117, 175), ("comedown", 175, 220)]
print("[QA] onset rate + level per section:")
for nm, a, b in secs:
    r = ((on_t >= a) & (on_t < b)).sum() / (b - a)
    sl = mono[int(a * SR):int(b * SR)]
    print(f"   {nm:<11} {r:4.2f} onsets/s   rms {20*np.log10(rms(sl)):+6.1f} dBFS")
overall = len(on_t) / dur_s
print(f"[QA] total onsets {len(on_t)} over {dur_s:.0f} s = {overall:.2f}/s "
      f"(dark-ambient target: well under 0.5/s)")
low_onset_ok = overall < 0.5
print(f"[QA] LOW-onset intent: {'PASS' if low_onset_ok else 'CHECK'}")
print(f"\n[done] {OUT}")
