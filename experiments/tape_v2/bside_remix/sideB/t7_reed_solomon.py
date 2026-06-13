#!/usr/bin/env python3
"""
t7_reed_solomon.py — B-side track 7: "Reed-Solomon"  (GLITCH / IDM)

ERROR CORRECTION AS MUSIC. The piece IS a Reed-Solomon codeword being repaired
in real time. Every sound is the REAL tape10 capture (deck + room + tape warmth,
flutter 0.42%) — granulated, gated, stuttered, and slowly re-assembled.

NARRATIVE ARC (the decoder at work):
  0  ..40 s  CORRUPTION   — scattered broken grains, hard dropouts, bit-reversed
                            stutters, pitch glitches. No stable pulse. The codeword
                            is shredded; symbols arrive out of order, many erased.
  40 ..78 s  PARTIAL LOCK — a kick (real preamble chirp, pitched down) finds the
                            122 BPM d2x grid. ~half the steps fire; the rest are
                            erasures (rhythmic gaps). Hats stutter in and out.
  78 ..120 s LOCKING IN   — the groove tightens: erasures get FILLED step by step
                            as "parity" repairs them. A retuned-carrier bass (real
                            375 Hz grid, F# minor) and DQPSK stabs lock to the grid.
  120..165 s CODEWORD OK  — full propulsive 4-on-the-floor + 16th hats + bass +
                            stabs. The repaired codeword: a coherent machine groove.
                            One brief "re-check" stutter fill, then clean to the end.
  165..195 s RESOLVE      — the real down-chirp (tape says CRC-OK) + a tail of clean
                            frame-locked ticks dissolving out. Decode complete.

Techniques (all on REAL audio):
  * granular resynthesis of real DQPSK sections, pitch-quantized by resampling to
    simple ratios -> the 375 Hz (F#4+23c) harmonic grid stays on an F#-minor chord.
  * GATING the real signal with preamble-derived patterns (tick 0.25 s + gap 0.12 s)
    on the 122 BPM grid; "erasures" = closed gate steps that progressively fill.
  * BIT-REVERSED / reversed grains, stutter-repeats (a symbol re-read N times),
    and resample glitches = the visible texture of correction.
  * KICK = real frame-preamble chirp (800->3200 Hz) pitched down 8x. HATS = HF
    phase-hop transients sliced from the real d2x capture. STABS = real-grid DQPSK.
  * the REAL global up/down chirps as the riser into lock and the closing CRC-OK.

Grid: d2x frame period 0.983333 s = 2 beats -> 122.034 BPM (palette.json).
Seed: 20260617 (logged below). Output: t7.wav, stereo 48k/16bit, ~195 s,
peak <= -1 dBFS, RMS ~ -15 dBFS, 2 s fade-in / 4 s fade-out.
"""

import numpy as np
import soundfile as sf
from scipy import signal as sig
from scipy.ndimage import median_filter

SEED = 20260617
rng = np.random.default_rng(SEED)
print(f"[seed] {SEED}")

SR = 48000
CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/t7.wav"

# ---- palette facts (measured on the real capture) ---------------------------
FRAME_S = 0.983333          # d2x N256_sp2 frame period -> 122.034 BPM
BEAT = FRAME_S / 2.0        # 0.4916665 s
BAR = 4 * BEAT              # 1.966666 s
STEP = BAR / 16.0           # 16th note

D2X_PRE0 = 205.3075         # first d2x preamble (capture s)
D2X_T = 0.984208            # measured d2x frame period
N512_PRE0 = 46.8634         # first N512 preamble
N512_T = 1.372896
CHIRP_UP_T = 20.8628        # real up-chirp 500->5000 Hz, 0.2 s
CHIRP_DN_T = 380.6237       # real down-chirp
SCHROEDER_T = 21.9636       # Schroeder sounder splash
N512_R0 = (46.88, 81.22)    # N512 rung r0
D2X_R5 = (205.35, 249.63)   # d2x rung r5
D2X_R6 = (250.03, 282.38)   # d2x rung r6 (21 carriers)
D2X_R8 = (316.17, 344.07)   # d2x rung r8 (22 carriers, full grid)
N512_R9 = (345.37, 379.71)  # tail canary

N_BARS = 99
TAIL_S = 1.0
DUR = N_BARS * BAR + TAIL_S
N = int(DUR * SR)
L = np.zeros(N)
R = np.zeros(N)

cap, sr_in = sf.read(CAPTURE, dtype="float64")
assert sr_in == SR and cap.ndim == 1, "expected mono 48k capture"
print(f"[load] capture {len(cap)/SR:.1f} s @ {SR} Hz")


# ---- helpers -----------------------------------------------------------------
def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-20))


def norm(x, target=0.1):
    m = rms(x)
    return x * (target / m) if m > 0 else x


def normpk(x, p=1.0):
    m = np.max(np.abs(x))
    return x * (p / m) if m > 0 else x


def seg(t0, dur):
    a = int(t0 * SR)
    return cap[a:a + int(dur * SR)].copy()


def add(t, x, gain=1.0, pan=0.5):
    """Equal-power pan, pan in [0,1] (0=L, 1=R)."""
    a = int(round(t * SR))
    if a >= N:
        return
    if a < 0:
        x = x[-a:]
        a = 0
    b = min(a + len(x), N)
    x = x[: b - a]
    L[a:b] += x * gain * np.cos(pan * np.pi / 2)
    R[a:b] += x * gain * np.sin(pan * np.pi / 2)


def add_st(t, xl, xr, gain=1.0):
    a = int(round(t * SR))
    if a >= N:
        return
    n = min(len(xl), len(xr), N - a)
    L[a:a + n] += xl[:n] * gain
    R[a:a + n] += xr[:n] * gain


def resamp(x, ratio):
    """ratio>1 -> higher pitch, shorter."""
    n_out = max(1, int(len(x) / ratio))
    idx = np.arange(n_out) * ratio
    return np.interp(idx, np.arange(len(x)), x)


def hp(x, f, order=4):
    return sig.sosfilt(sig.butter(order, f, "hp", fs=SR, output="sos"), x)


def lp(x, f, order=4):
    return sig.sosfilt(sig.butter(order, f, "lp", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=4):
    return sig.sosfilt(sig.butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def fade_edges(x, ms=2.0):
    n = int(SR * ms / 1000)
    if 2 * n < len(x) and n > 1:
        r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
        x = x.copy()
        x[:n] *= r
        x[-n:] *= r[::-1]
    return x


def t_of(bar, step=0.0):
    return bar * BAR + step * STEP


# ---- instrument kit (all sampled from the real capture) ----------------------
# KICK: real preamble chirp pitched down 8x -> 100->400 Hz thump + HF click.
pre_n512 = seg(N512_PRE0, 0.25)
pre_d2x = seg(D2X_PRE0, 0.25)
body = sig.resample_poly(pre_n512, 7, 1)[:int(0.20 * SR)]   # 7x -> knock ~110 Hz
body = bp(normpk(body), 55, 200, 4)
tk = np.arange(len(body)) / SR
kenv = np.exp(-tk / 0.028) * np.minimum(tk / 0.0015, 1.0)   # very short = dry knock, low ring
kick = np.tanh(2.2 * normpk(body) * kenv)
click = hp(pre_n512[:int(0.006 * SR)], 1200, 2) * np.exp(
    -np.arange(int(0.006 * SR)) / (0.0018 * SR))
kick[:len(click)] += 0.85 * normpk(click)   # punchier click = more presence, less sub
kick = fade_edges(normpk(kick), 1.2)

# HATS: HF phase-hop transients sliced from the real d2x section.
hsrc = hp(seg(208.0, 34.0), 6000, 6)
he = np.convolve(hsrc ** 2, np.ones(256) / 256, mode="same")
hpk, _ = sig.find_peaks(he, distance=int(0.045 * SR))
order = np.argsort(he[hpk])[::-1][:120]
grain_pos = hpk[order]
print(f"[kit] {len(grain_pos)} HF transient grains")


def hat(open_=False):
    pos = int(rng.choice(grain_pos))
    dur = 0.15 if open_ else 0.040
    tau = 0.055 if open_ else 0.014
    n = int(dur * SR)
    g = hsrc[pos:pos + n].copy()
    if len(g) < n:
        g = np.pad(g, (0, n - len(g)))
    g = normpk(g) * np.exp(-np.arange(n) / (tau * SR))
    return fade_edges(g, 0.8)


# CLAP / snare: real Schroeder splash, triple-burst.
csrc = bp(seg(SCHROEDER_T + 0.34, 0.5), 700, 4500, 4)
nclap = int(0.26 * SR)
tcl = np.arange(nclap) / SR
cenv = np.zeros(nclap)
for off in (0.0, 0.010, 0.022):
    m = tcl >= off
    cenv[m] += np.exp(-(tcl[m] - off) / 0.012)
cenv += 0.55 * np.exp(-tcl / 0.075)
clap = fade_edges(normpk(csrc[:nclap] * cenv), 0.8)

# real chirps straight off the tape
edge = np.hanning(int(0.02 * SR))
chirp_up = seg(CHIRP_UP_T - 0.02, 0.26)
chirp_dn = seg(CHIRP_DN_T - 0.02, 0.26)
for c in (chirp_up, chirp_dn):
    c[: len(edge) // 2] *= edge[: len(edge) // 2]
    c[-(len(edge) // 2):] *= edge[len(edge) // 2:]
chirp_up = normpk(chirp_up)
chirp_dn = normpk(chirp_dn)

# BASS: retuned real-grid sub-octaves. F#-minor low chord: F#2, A2(B-1 from A#), C#3, E3.
# 375 grid harmonics -> divide down. F#2=750/8=93.75, C#3=1125/8=140.6, E3=2625/16=164.1.
# For minor flavour pull A#(1875) family to A: A2 ~= 110 -> use 1875/16=117.2 then *0.94.
F2, As2, Cs3, E3 = 750 / 8, 1875 / 16, 1125 / 8, 2625 / 16


def bass_note(f0, dur, cut_base, cut_env, accent=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    cut = cut_base + cut_env * np.exp(-t / 0.085)
    y = np.zeros(n)
    for h in (1, 3, 5, 7, 9, 11):
        fh = f0 * h
        if fh > 18000:
            break
        y += (1.0 / h) / np.sqrt(1.0 + (fh / cut) ** 8) * np.sin(2 * np.pi * fh * t)
    env = np.minimum(t / 0.004, 1.0) * np.exp(-t / (dur * 0.9))
    nr = int(0.015 * SR)
    env[-nr:] *= np.linspace(1, 0, nr)
    return np.tanh(1.8 * y) * env * accent


# STABS: DQPSK phase-hop resynth on the exact carrier grid (F#-minor selection).
def dqpsk_stab(freqs, amps, dur, sym_s=FRAME_S / 16):
    n = int(dur * SR)
    t = np.arange(n) / SR
    nsym = int(t[-1] / sym_s) + 1
    y = np.zeros(n)
    symidx = np.minimum((t / sym_s).astype(int), nsym - 1)
    for f, a in zip(freqs, amps):
        ph = rng.integers(0, 4, size=nsym) * (np.pi / 2)
        y += a * np.cos(2 * np.pi * f * t + ph[symidx])
    env = np.minimum(t / 0.003, 1.0) * np.exp(-t / (dur / 2.5))
    return fade_edges(lp(y, 9500, 4) * env, 1.5)


# F# minor selection of the real grid: F#(750/1500) C#(1125/2250) A(1875->retune) E(2625)
CHORD_MIN = ([750.0, 1125.0, 1875.0 * 0.9438, 2625.0],
             [1.0, 0.75, 0.55, 0.42])           # F# A C# E  (A from A# pulled -100c)
CHORD_MIN2 = ([1125.0, 1500.0, 2250.0, 2625.0],
              [1.0, 0.7, 0.5, 0.4])              # C# F# C# E

# normalized granular sources
src_d2x = norm(seg(D2X_R5[0] + 0.5, 43.0), 0.1)
src_d2x6 = norm(seg(D2X_R6[0] + 0.5, 31.0), 0.1)
src_n512 = norm(seg(N512_R0[0] + 0.5, 33.0), 0.1)
src_full = norm(seg(D2X_R8[0] + 0.5, 27.0), 0.1)


# ============================================================================
# SECTION 1 (0..40 s): CORRUPTION — scattered broken grains, glitches, dropouts
# ============================================================================
print("[render] sec1 CORRUPTION — scattered broken grains")
# F#-minor chord ratios for pitch quantization (keeps grains on F#/A/C#/E)
MIN_RATIOS = np.array([0.25, 1 / 3, 0.5, 2 / 3, 0.75, 1.0, 1.5])
MIN_W = np.array([0.18, 0.14, 0.2, 0.12, 0.12, 0.14, 0.10])
MIN_W = MIN_W / MIN_W.sum()


def glitch_grain(src, out_dur, ratio, reverse=False):
    n_out = int(out_dur * SR)
    n_need = int(n_out * ratio) + 2
    if n_need >= len(src):
        n_need = len(src) - 2
        n_out = int(n_need / ratio)
    p0 = int(rng.integers(0, len(src) - n_need))
    idx = np.arange(n_out) * ratio
    g = np.interp(idx, np.arange(n_need), src[p0:p0 + n_need])
    if reverse:
        g = g[::-1]
    return g * np.hanning(len(g))


def stutter(src, unit_dur, n_rep, ratio, decay=0.85):
    """A symbol re-read n_rep times — bit-reversed correction texture."""
    n_unit = int(unit_dur * SR)
    n_need = int(n_unit * ratio) + 2
    if n_need >= len(src):
        n_need = len(src) - 2
    p0 = int(rng.integers(0, max(1, len(src) - n_need)))
    idx = np.arange(int(n_need / ratio)) * ratio
    unit = np.interp(idx, np.arange(n_need), src[p0:p0 + n_need])
    unit = fade_edges(unit, 1.0)
    out = []
    for k in range(n_rep):
        u = unit.copy() * (decay ** k)
        if k % 2 == 1:
            u = u[::-1]          # alternate forward / bit-reversed read
        out.append(u)
    return np.concatenate(out)


# scattered grains across sec1 with increasing density toward the lock point
t = 0.5
while t < 39.0:
    prog = t / 40.0
    dens = 2.0 + 7.0 * prog                  # grains/s, ramps up
    dur = rng.uniform(0.03, 0.13)
    ratio = float(rng.choice(MIN_RATIOS, p=MIN_W))
    rev = rng.random() < 0.35
    src = [src_d2x, src_d2x6, src_full][rng.choice(3, p=[0.4, 0.3, 0.3])]
    g = glitch_grain(src, dur, ratio, reverse=rev)
    gain = rng.uniform(0.18, 0.40) * (0.6 + 0.4 * prog)
    pan = rng.uniform(0.05, 0.95)            # scattered hard pans = symbols out of order
    add(t, g, gain, pan)
    # occasional stutter burst (a symbol re-read) — more frequent later
    if rng.random() < 0.10 + 0.18 * prog:
        st = stutter(src, rng.uniform(0.03, 0.06), int(rng.integers(3, 7)),
                     float(rng.choice([0.5, 1.0, 1.5])))
        add(t, normpk(st) * 0.30 * (0.5 + 0.5 * prog), pan)
    t += rng.exponential(1.0 / dens)

# hard dropouts already implied by sparse scatter; add a few erasure "tells":
# bursts of the real signal that get abruptly cut (gate slam) — corruption noise.
for k in range(7):
    tt = rng.uniform(2.0, 36.0)
    burst = norm(seg(D2X_R5[0] + rng.uniform(1, 30), rng.uniform(0.4, 1.1)), 0.1)
    g = np.ones(len(burst))
    g[: int(0.005 * SR)] = np.linspace(0, 1, int(0.005 * SR))
    g[-int(0.003 * SR):] = np.linspace(1, 0, int(0.003 * SR))  # slam shut = erasure
    add(tt, bp(burst, 1000, 5000) * g, 0.22, rng.uniform(0.2, 0.8))

# a low spectral-freeze wash so it isn't pure pointillism (the noisy channel bed)
def spectral_freeze(src, dur, nfft=8192, ratio=1.0):
    win = np.hanning(nfft)
    mags = []
    for i in range(0, len(src) - nfft, nfft // 2):
        mags.append(np.abs(np.fft.rfft(src[i:i + nfft] * win)))
    mag = np.mean(mags, axis=0)
    n_out = int(dur * SR * ratio) + nfft
    out = np.zeros(n_out + nfft)
    hop = nfft // 4
    for pos in range(0, n_out, hop):
        ph = rng.uniform(0, 2 * np.pi, len(mag))
        out[pos:pos + nfft] += np.fft.irfft(mag * np.exp(1j * ph), nfft) * win
    out = out[:n_out]
    if ratio != 1.0:
        out = resamp(out, ratio)
    return norm(out[: int(dur * SR)], 0.1)


schro = seg(SCHROEDER_T + 0.2, 2.6)
washL = spectral_freeze(schro, 44.0, ratio=0.5)
washR = spectral_freeze(schro, 44.0, ratio=0.5)
t_arr = np.arange(len(washL)) / SR
wash_env = np.clip(0.5 - 0.3 * (t_arr / 44.0), 0, 1) * np.minimum(t_arr / 3.0, 1.0)
add(0.0, washL * wash_env, 0.055, 0.3)
add(0.0, washR * wash_env, 0.055, 0.7)


# ============================================================================
# Rhythmic engine (sec2..4): kick / hats / bass / stabs on the 122 BPM grid,
# with an "erasure mask" that progressively FILLS (the codeword being repaired).
# ============================================================================
print("[render] sec2-4 LOCK / FILL / CODEWORD — repair on the 122 BPM grid")

# Per-bar "fill probability": how many scheduled events actually fire (rest = erasure).
# Ramps from ~0.45 at first lock to 1.0 once the codeword is repaired.
def fill_prob(bar):
    # sec2 ~ bars 20..39, sec3 ~ 40..60, sec4 ~ 61..84
    if bar < 20:
        return 0.0
    if bar < 40:
        return 0.45 + 0.20 * (bar - 20) / 20.0     # 0.45 -> 0.65
    if bar < 61:
        return 0.66 + 0.30 * (bar - 40) / 21.0     # 0.66 -> 0.96
    return 1.0                                       # codeword OK


def fires(bar, slot):
    """Deterministic-ish erasure: parity repairs lower-index slots first."""
    p = fill_prob(bar)
    # bias: kick downbeats (slot 0) repair earliest; off-positions last
    bias = 1.0 - 0.12 * (slot % 4)
    return rng.random() < min(1.0, p * bias)


# --- KICK: 4-on-floor, erasures fill in ---
kick_bars = range(20, 97)
for b in kick_bars:
    for s in (0, 4, 8, 12):
        # downbeat (s==0) locks first; later beats fill in
        slotrank = {0: 0, 8: 1, 4: 2, 12: 3}[s]
        if b < 40 and slotrank > (0 if b < 30 else 1) and not fires(b, slotrank):
            continue
        if 40 <= b < 61 and not fires(b, slotrank):
            continue
        add(t_of(b, s), kick, 0.62, 0.5)

# --- HATS ---
for b in range(20, 97):
    base_steps = [2, 6, 10, 14]
    for s in base_steps:
        if b < 61 and not fires(b, 1):
            continue
        op = (b >= 61) and s == 10 and (b % 2 == 0)
        g = hat(op)
        pan = 0.35 if (s // 4) % 2 else 0.65
        add(t_of(b, s), g, 0.20 if op else 0.22, pan)
    # 16th ticking once codeword is OK (sec4)
    if b >= 61:
        for s in (1, 3, 5, 7, 9, 11, 13, 15):
            add(t_of(b, s), hat(False), 0.10, 0.30 if s % 4 == 1 else 0.70)
    elif b >= 45:  # partial 16ths creeping in during fill
        for s in (3, 7, 11, 15):
            if fires(b, 2):
                add(t_of(b, s), hat(False), 0.09, 0.30 if s % 2 else 0.70)

# --- CLAP/snare on the backbeat (beats 2 & 4 -> steps 4,12) ---
for b in range(40, 97):
    for s in (4, 12):
        if b < 61 and not fires(b, 1):
            continue
        add(t_of(b, s), clap, 0.30, 0.5)

# --- BASS: F#-minor 16-step pattern, enters at fill, full by codeword ---
BASS_PAT = [(2, F2, 1.0, 0.21), (6, F2, 0.9, 0.21), (7, As2 * 0.9438, 0.6, 0.10),
            (10, Cs3, 0.95, 0.21), (14, E3, 0.9, 0.17), (15, F2, 0.7, 0.10)]
for b in range(34, 97):
    cutb = 350 if b < 50 else (650 if b < 61 else 800)
    cute = 900 if b < 61 else 2000
    for (s, f0, acc, dur) in BASS_PAT:
        if b < 61 and not fires(b, 2):
            continue
        nb = bass_note(f0, dur, cutb, cute * acc, acc)
        add(t_of(b, s), nb, 0.34, 0.5)

# --- STABS: DQPSK on the real grid, F# minor ---
for b in range(46, 97):
    if b < 61 and not fires(b, 3):
        continue
    ch = CHORD_MIN if b % 2 == 0 else CHORD_MIN2
    st = dqpsk_stab(*ch, 0.32)
    add(t_of(b, 11), st, 0.18, 0.35 if b % 2 else 0.65)
    if b >= 61 and b % 4 == 2:
        st2 = dqpsk_stab(*CHORD_MIN, 0.26)
        add(t_of(b, 3), st2, 0.15, 0.6)

# --- GATED real-signal bed: preamble-locked, ducked. Carries the "data" voice. ---
def gated_stream(out_b0, out_b1, cap_t0, pattern_fn, gain, lp_hz=None, pan=0.5):
    out_t0, out_t1 = t_of(out_b0), t_of(out_b1)
    n = int((out_t1 - out_t0) * SR)
    a = int(cap_t0 * SR)
    stream = norm(cap[a:a + n].copy(), 0.1)
    if len(stream) < n:
        stream = np.pad(stream, (0, n - len(stream)))
    gate = np.zeros(n)
    n_frames = int((out_t1 - out_t0) / FRAME_S) + 1
    for j in range(n_frames):
        for (off, dur, g) in pattern_fn(j):
            ga = int((j * FRAME_S + off) * SR)
            gb = int((j * FRAME_S + off + dur) * SR)
            if ga >= n:
                break
            gate[ga:min(gb, n)] = g
    w = np.hanning(int(0.004 * SR))
    gate = sig.fftconvolve(gate, w / w.sum(), mode="same")
    out = stream * gate
    if lp_hz:
        out = lp(out, lp_hz, 4)
    add(out_t0, bp(out, 600, 6000, 4), gain, pan)


TICK, GAP = 0.25, 0.12
DATA0 = TICK + GAP


def pat_lock(j):       # sparse data voice during partial lock
    ev = [(0.0, TICK, 0.9)]
    if j % 2 == 0:
        ev.append((DATA0, GAP, 0.7))
    return ev


def pat_full(j):       # dense data voice once locked
    ev = [(0.0, TICK, 1.0), (DATA0, GAP, 0.85)]
    if j % 2 == 1:
        ev.append((DATA0 + 0.205, 0.10, 0.75))
    if j % 4 == 2:
        ev.append((0.75 * FRAME_S, 0.14, 0.8))
    return ev


gated_stream(40, 61, D2X_PRE0 + 2 * D2X_T, pat_lock, 0.24, lp_hz=4500, pan=0.42)
gated_stream(61, 85, D2X_PRE0 + 18 * D2X_T, pat_full, 0.30, pan=0.5)

# --- sampled real preamble TICKS as percussion on the frame grid (every 2 beats) ---
ticks = []
for m in (0, 4, 9, 16):
    x = seg(D2X_PRE0 + m * D2X_T - 0.004, 0.30)
    e = np.ones(len(x))
    e[: int(0.002 * SR)] = np.linspace(0, 1, int(0.002 * SR))
    e[int(0.20 * SR):] = np.linspace(1, 0, len(x) - int(0.20 * SR)) ** 2
    ticks.append(norm(x * e, 0.1))
for b in range(61, 97, 1):
    if b % 2 == 0:
        add(t_of(b, 0), ticks[b % 4], 0.16, 0.32)
        add(t_of(b, 8), ticks[(b + 1) % 4], 0.12, 0.68)


# ============================================================================
# Build / transition gestures: real chirps + Schroeder crashes
# ============================================================================
print("[render] risers / crashes / re-check fill")
# riser into partial lock (bar 20) and into codeword-OK (bar 61)
def riser(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 500.0 + 4500.0 * t / dur
    chirp = np.sin(2 * np.pi * np.cumsum(f) / SR)
    nz = normpk(hp(seg(43.0, dur + 0.5)[:n], 2500, 4))
    y = 0.6 * chirp * (t / dur) ** 2.2 + 0.5 * nz * (t / dur) ** 2.0
    return fade_edges(normpk(y), 3.0)


add(t_of(18), riser(2 * BAR), 0.26, 0.5)
add(t_of(59), riser(2 * BAR), 0.28, 0.5)

# Schroeder crash on the two big downbeats
def crash_pair():
    cl = hp(seg(SCHROEDER_T + 4.2, 2.0), 1200, 4)
    cr = hp(seg(SCHROEDER_T + 4.211, 2.0), 1200, 4)
    n = min(len(cl), len(cr))
    env = np.exp(-np.arange(n) / (0.7 * SR)) * np.minimum(np.arange(n) / (0.004 * SR), 1.0)
    m = max(np.max(np.abs(cl[:n] * env)), np.max(np.abs(cr[:n] * env)))
    return fade_edges(cl[:n] * env / m, 2), fade_edges(cr[:n] * env / m, 2)


crashL, crashR = crash_pair()
add_st(t_of(20), crashL, crashR, 0.30)
add(t_of(20), chirp_up, 0.26, 0.5)
add_st(t_of(61), crashL, crashR, 0.32)
add(t_of(61), chirp_up, 0.28, 0.5)

# the real up-chirp zaps at fill milestones
for b in (40, 50):
    add(t_of(b), resamp(chirp_up, 0.5), 0.18, 0.5)

# ONE "re-check" stutter fill late in the codeword section (bar 80): a final
# correction sweep — a burst of stuttered grains, then clean.
for k in range(10):
    tt = t_of(80) + k * STEP * 0.5
    rr = float(rng.choice([0.5, 1.0, 1.5]))
    st = stutter(src_full, 0.035, int(rng.integers(2, 4)), rr)
    add(tt, normpk(st) * 0.20, 0.2 + 0.6 * (k % 2))


# ============================================================================
# SECTION 5 (165..195 s): RESOLVE — down-chirp CRC-OK + dissolving clean ticks
# ============================================================================
print("[render] sec5 RESOLVE — down-chirp + dissolving ticks")
RES_B0 = 85   # ~167 s
# stop the dense engine; let ticks + a pad-like freeze carry the outro.
# A clean F#-minor freeze pad (native pitch) as the resolved tone.
padL = spectral_freeze(seg(N512_R0[0] + 1.0, 2.6), 30.0, ratio=1.0)
padR = spectral_freeze(seg(N512_R0[0] + 1.0, 2.6), 30.0, ratio=1.0)
pt = np.arange(len(padL)) / SR
pad_env = np.minimum(pt / 2.0, 1.0) * np.clip(1.0 - (pt - 18) / 12.0, 0, 1)
add(t_of(RES_B0), lp(padL, 5000) * pad_env, 0.07, 0.35)
add(t_of(RES_B0), lp(padR, 5000) * pad_env, 0.07, 0.65)

# the tape says CRC-OK: real down-chirp, echoed down the frame grid
def chirp_echo(t0, x, gain, n_echo=5, fb=0.6, dt=FRAME_S, pan0=0.4):
    for i in range(n_echo + 1):
        add(t0 + i * dt, x, gain * fb ** i, pan0 if i % 2 == 0 else 1 - pan0)


chirp_echo(t_of(RES_B0), chirp_dn, 0.26, n_echo=4, pan0=0.4)
add(t_of(RES_B0 + 6), resamp(chirp_dn, 0.5), 0.22, 0.5)
add(t_of(RES_B0 + 10), resamp(chirp_dn, 0.25), 0.24, 0.5)  # 2-oct down sweep

# dissolving clean frame-locked ticks (decode complete, fading)
for b in range(RES_B0, N_BARS):
    g = 0.16 * np.clip(1.0 - (b - RES_B0) / (N_BARS - RES_B0), 0, 1)
    if g <= 0.01:
        break
    add(t_of(b, 0), ticks[b % 4], g, 0.5)
    if b % 2 == 0:
        add(t_of(b, 8), ticks[(b + 1) % 4], g * 0.7, 0.3 if b % 4 else 0.7)


# ============================================================================
# MASTER: hp, fades, level, soft limit
# ============================================================================
print("[master] hp, fades, level, soft limit")
mix = np.stack([L, R], axis=1)
sos_hp = sig.butter(2, 30, "hp", fs=SR, output="sos")
mix = sig.sosfiltfilt(sos_hp, mix, axis=0)

# Tilt EQ: tame the kick/bass low bloom, lift the modem-carrier band (the soul).
# 1) gentle low shelf cut below ~140 Hz; 2) presence lift 2.5-9 kHz via parallel HP add.
sos_lowcut = sig.butter(2, 110, "hp", fs=SR, output="sos")  # extra low trim (one-pass)
low = sig.sosfilt(sos_lowcut, mix, axis=0)
mix = 0.32 * mix + 0.68 * low                                # blend: ~-5 dB sub, keep punch
modem = sig.sosfilt(sig.butter(4, [2200, 9500], "band", fs=SR, output="sos"), mix, axis=0)
mix = mix + 1.1 * modem                                       # lift carrier-grid presence
air = sig.sosfilt(sig.butter(2, 9000, "hp", fs=SR, output="sos"), mix, axis=0)
mix = mix + 0.5 * air                                         # a little air / hat sparkle

fade = np.ones(N)
nf = int(2.0 * SR)
fade[:nf] = np.sin(np.linspace(0, np.pi / 2, nf)) ** 2
nf = int(4.0 * SR)
fade[-nf:] *= np.sin(np.linspace(np.pi / 2, 0, nf)) ** 2
mix *= fade[:, None]

TARGET_RMS = 10 ** (-15.0 / 20)
CEIL = 10 ** (-1.05 / 20)
for _ in range(5):
    mix *= TARGET_RMS / rms(mix)
    a = np.abs(mix)
    thr = 0.55
    over = a > thr
    mix[over] = np.sign(mix[over]) * (
        thr + (CEIL - thr) * np.tanh((a[over] - thr) / (CEIL - thr)))
peak = np.max(np.abs(mix))
if peak > CEIL:
    mix *= CEIL / peak

assert np.all(np.isfinite(mix)), "NaN/Inf in mix"
sf.write(OUT, mix, SR, subtype="PCM_16")

# ============================================================================
# SELF-QA
# ============================================================================
x, _ = sf.read(OUT, dtype="float64")
mono = x.mean(axis=1)
dur_s = len(x) / SR
pk_db = 20 * np.log10(np.max(np.abs(x)) + 1e-20)
rms_db = 20 * np.log10(rms(x))
print(f"\n[QA] duration {dur_s:.1f} s   peak {pk_db:+.2f} dBFS   RMS {rms_db:+.2f} dBFS")
spec_ok = (180 <= dur_s <= 210) and (pk_db <= -1.0 + 1e-6) and (-16.5 <= rms_db <= -13.5)
print(f"[QA] spec gate: {'PASS' if spec_ok else 'FAIL'}")

# 10-band spectral balance (% of total energy)
spec = np.abs(np.fft.rfft(mono)) ** 2
freqs = np.fft.rfftfreq(len(mono), 1 / SR)
edges = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 24000]
tot = spec.sum()
print("[QA] 10-band balance (% energy):")
for lo_, hi_ in zip(edges[:-1], edges[1:]):
    b = spec[(freqs >= lo_) & (freqs < hi_)].sum() / tot * 100
    print(f"   {lo_:>5}-{hi_:<5} Hz : {b:5.1f}  {'#' * int(b)}")

# onset rate via spectral flux, per narrative section
f_, tt_, S = sig.stft(mono, SR, nperseg=2048, noverlap=1536)
mag = np.abs(S)
flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
thr = median_filter(flux, 93) * 1.5 + 0.02 * flux.max()
pk_idx, _ = sig.find_peaks(flux, height=thr, distance=5)
on_t = tt_[1:][pk_idx]
secs = [("CORRUPT", 0, 40), ("PART-LOCK", 40, 78), ("LOCKING", 78, 120),
        ("CODEWORD", 120, 165), ("RESOLVE", 165, dur_s)]
print("[QA] onset rate + level per section:")
for nm, a, b in secs:
    r = ((on_t >= a) & (on_t < b)).sum() / max(1e-9, (b - a))
    sl = mono[int(a * SR):int(b * SR)]
    print(f"   {nm:<10} {r:5.2f} onsets/s   rms {20*np.log10(rms(sl)):+6.1f} dBFS")
print(f"[QA] total onsets {len(on_t)} -> {len(on_t)/dur_s:.2f}/s overall")

# intent check: codeword section should have MUCH higher onset rate than corruption
r_corr = ((on_t >= 0) & (on_t < 40)).sum() / 40.0
r_code = ((on_t >= 120) & (on_t < 165)).sum() / 45.0
print(f"[QA] intent: CODEWORD/CORRUPT onset ratio = {r_code / max(1e-9, r_corr):.2f} "
      f"(want >1.4 — groove locks in)")
print(f"[QA] BPM {60/BEAT:.3f}  bar {BAR:.4f}s  bars {N_BARS}  seed {SEED}")
print(f"\n[done] {OUT}")
