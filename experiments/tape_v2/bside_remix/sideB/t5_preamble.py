#!/usr/bin/env python3
"""
TRACK 5 — "Preamble"  (B-side of the DOOM-on-cassette prize tape)
=================================================================
THE BANGER. Techno/IDM, locked dead to the REAL d2x frame period.

This is the dancefloor peak of the 9-track concept album. The frame
preamble — the 800->3200 Hz tick that opens every data frame on the tape —
becomes the heartbeat: pitched down 8x it is the KICK, at native pitch it
is the hi-tick that announces every drop. Everything you hear is the real
data-transfer signal, retuned and re-rhythmed:

  * TEMPO  : exactly the d2x N256_sp2 frame period (0.983333 s = 2 beats ->
             122.034 BPM). Every bar is two real frames long.
  * KICK   : the REAL frame-preamble chirp (800->3200 Hz, 0.25 s) sampled
             from the capture and pitched DOWN 8x -> 100->400 Hz thump,
             plus its own HF transient click. 4-on-the-floor.
  * HATS   : sliced HF DQPSK phase-hop transients (>6 kHz) from the REAL
             d2x section of the capture. Closed + open + 16th-note rolls.
  * BASS   : the lowest REAL carrier (F#2 = 750/8 = 93.75 Hz) and its grid
             siblings, additive square-ish synth driven by a resonant
             low-pass FILTER SWEEP that opens across each build/drop.
  * RISER  : resynth of the REAL global chirp (500->5000 Hz linear) stretched
             over 2 bars, climbing into every drop; the REAL up-chirp sample
             zaps the downbeat of each drop.
  * CRASH  : the REAL Schroeder multitone sounder (64 tones 300-11000 Hz)
             splashing on the drop.
  * STABS  : DQPSK phase-hop resynthesis on the EXACT carrier grid
             (750/1125/1500/1875/2625 Hz), the buzzy modem chord.
  * BED    : the REAL capture (d2x + N512 data sections) band-passed and
             sidechain-ducked under the kick — literal modem hiss as texture.
  * TICKS  : REAL preamble samples placed on the exact frame grid (every
             2 beats) through the breaks — you are hearing the tape's pulse.
  * CLOSE  : the REAL down-chirp says goodbye on the outro.

FORM (132 bars @ 122.034 BPM ~= 259.6 s + 3 s tail ~= 262 s):
  intro   0..8    ticks + bed, the frame pulse establishes
  build1  8..16   filter opens, kick fades in, riser
  DROP1  16..40   first drop (24 bars) — 4-floor, bass, hats, stabs
  break1 40..52   pad + gated real-data stabs, kick out
  build2 52..60   riser, snare-roll of preamble ticks
  DROP2  60..88   biggest drop (28 bars) — full energy, claps, open hats
  break2 88..98   stripped — bed + ticks + lone bass, breathing room
  build3 98..106  final riser, accelerating preamble ticks
  DROP3 106..126  final peak (20 bars) — everything, then strip to outro
  outro 126..132  ticks resolve, down-chirp farewell

Output: stereo 48 kHz 16-bit, peak <= -1 dBFS, RMS ~= -15 dBFS,
        2 s fade-in / 4 s fade-out.
Seed: 20260615 (logged below).
"""
import numpy as np
import scipy.signal as sig
import soundfile as sf

SEED = 20260615
rng = np.random.default_rng(SEED)
SR = 48000

BASE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2"
CAPTURE = f"{BASE}/captures/tape10_run1.wav"
OUT = f"{BASE}/bside_remix/sideB/t5.wav"

# ----------------------------------------------------------------- timing grid
FRAME_S = 0.983333            # d2x N256_sp2 nominal frame period (palette.json)
BEAT = FRAME_S / 2.0          # -> 122.034 BPM (two beats per real frame)
BAR = 4 * BEAT                # 1.966666 s
STEP = BAR / 16.0             # 16th note
N_BARS = 132
TAIL_S = 3.0
TOTAL_S = N_BARS * BAR + TAIL_S
N = int(TOTAL_S * SR)
BPM = 60.0 / BEAT

# section bar-ranges
INTRO  = range(0, 8)
BUILD1 = range(8, 16)
DROP1  = range(16, 40)
BREAK1 = range(40, 52)
BUILD2 = range(52, 60)
DROP2  = range(60, 88)
BREAK2 = range(88, 98)
BUILD3 = range(98, 106)
DROP3  = range(106, 126)
OUTRO  = range(126, 132)
ALL_DROPS = list(DROP1) + list(DROP2) + list(DROP3)

def t_of(bar, step=0.0):
    return bar * BAR + step * STEP

# ----------------------------------------------------------------- DSP helpers
def hp(x, f, order=4):
    return sig.sosfilt(sig.butter(order, f, btype='high', fs=SR, output='sos'), x)

def lp(x, f, order=4):
    return sig.sosfilt(sig.butter(order, f, btype='low', fs=SR, output='sos'), x)

def bp(x, lo, hi, order=4):
    return sig.sosfilt(sig.butter(order, [lo, hi], btype='band', fs=SR, output='sos'), x)

def fade_edges(x, ms=3.0):
    n = int(SR * ms / 1000)
    if 2 * n < len(x):
        r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
        x[:n] *= r
        x[-n:] *= r[::-1]
    return x

def norm_peak(x, p=1.0):
    m = np.max(np.abs(x))
    return x * (p / m) if m > 0 else x

def add_at(buf, t_s, x, pan=0.0, gain=1.0):
    """Mix mono x into stereo buf at t_s with constant-power pan in [-1,1]."""
    i0 = int(round(t_s * SR))
    if i0 >= len(buf) or i0 < 0:
        return
    n = min(len(x), len(buf) - i0)
    th = (pan + 1.0) * np.pi / 4.0
    buf[i0:i0 + n, 0] += x[:n] * gain * np.cos(th)
    buf[i0:i0 + n, 1] += x[:n] * gain * np.sin(th)

def add_st(buf, t_s, xl, xr, gain=1.0):
    i0 = int(round(t_s * SR))
    if i0 >= len(buf) or i0 < 0:
        return
    n = min(len(xl), len(xr), len(buf) - i0)
    buf[i0:i0 + n, 0] += xl[:n] * gain
    buf[i0:i0 + n, 1] += xr[:n] * gain

def tile_xfade(src, n_target, xfade_s=0.3):
    """Loop src to n_target samples with raised-cosine crossfades."""
    nx = max(1, int(xfade_s * SR))
    out = np.zeros(n_target)
    pos = 0
    first = True
    while pos < n_target:
        seg = src.copy()
        if not first:
            r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nx))
            seg[:nx] *= r
            pos = max(0, pos - nx)
        n = min(len(seg), n_target - pos)
        out[pos:pos + n] += seg[:n]
        pos += n
        first = False
    return out

# ----------------------------------------------------------------- load capture
cap, sr_in = sf.read(CAPTURE)
if cap.ndim > 1:
    cap = cap.mean(axis=1)
assert sr_in == SR, f"capture sr {sr_in} != {SR}"
print(f"[load] capture {len(cap)/SR:.1f} s @ {SR} Hz   seed={SEED}   BPM={BPM:.3f}")

def cslice(t0, dur):
    a = int(t0 * SR)
    b = int((t0 + dur) * SR)
    return cap[a:b].copy()

# ----------------------------------------------------------------- instruments
# KICK: real preamble chirp pitched DOWN 8x -> 100..400 Hz thump.
pre_n512 = cslice(46.8634, 0.25)        # first N512 frame preamble (capture)
pre_d2x = cslice(205.3075, 0.25)        # first d2x frame preamble (capture)
body = sig.resample_poly(pre_n512, 8, 1)[:int(0.40 * SR)]
body = lp(norm_peak(body), 300, 4)
tk = np.arange(len(body)) / SR
kenv = np.exp(-tk / 0.082) * np.minimum(tk / 0.002, 1.0)
kick = np.tanh(3.2 * norm_peak(body) * kenv)
click = hp(pre_n512[:int(0.006 * SR)], 1200, 2) * np.exp(-np.arange(int(0.006 * SR)) / (0.002 * SR))
kick[:len(click)] += 0.7 * norm_peak(click)
kick = fade_edges(norm_peak(kick), 1.5)
print(f"[kick] real preamble pitched 8x down -> {len(kick)/SR*1000:.0f} ms thump")

# HATS: HF transient grains sliced from the real d2x DQPSK section.
hsrc = hp(cslice(208.0, 35.0), 6000, 6)
e = np.convolve(hsrc ** 2, np.ones(256) / 256, mode='same')
pk, _ = sig.find_peaks(e, distance=int(0.045 * SR))
order = np.argsort(e[pk])[::-1][:140]
grain_pos = pk[order]
assert len(grain_pos) >= 48, f"only {len(grain_pos)} hat grains"
print(f"[hats] {len(grain_pos)} HF phase-hop grains sliced from real d2x capture")

def hat(open_=False):
    pos = int(rng.choice(grain_pos))
    dur = 0.17 if open_ else 0.042
    tau = 0.065 if open_ else 0.014
    n = int(dur * SR)
    g = hsrc[pos:pos + n].copy()
    if len(g) < n:
        g = np.pad(g, (0, n - len(g)))
    g = hp(norm_peak(g), 7500, 4)            # lift the air so the hats sparkle on a real rig
    g = norm_peak(g) * np.exp(-np.arange(n) / (tau * SR))
    return fade_edges(g, 1.0)

# CLAP: real Schroeder sounder splash, triple-burst envelope.
csrc = bp(cslice(22.3, 0.5), 700, 4500, 4)
nclap = int(0.30 * SR)
tcl = np.arange(nclap) / SR
cenv = np.zeros(nclap)
for off in (0.0, 0.011, 0.024):
    m = tcl >= off
    cenv[m] += np.exp(-(tcl[m] - off) / 0.013)
cenv += 0.6 * np.exp(-tcl / 0.09)
clap = fade_edges(norm_peak(csrc[:nclap] * cenv), 1.0)

# CRASH: real Schroeder sounder, long decay, stereo via offset slices.
def crash_pair():
    cl = hp(cslice(26.15, 2.4), 1200, 4)
    cr = hp(cslice(26.161, 2.4), 1200, 4)
    n = min(len(cl), len(cr))
    env = np.exp(-np.arange(n) / (0.80 * SR)) * np.minimum(np.arange(n) / (0.004 * SR), 1.0)
    m = max(np.max(np.abs(cl[:n] * env)), np.max(np.abs(cr[:n] * env)))
    return fade_edges(cl[:n] * env / m, 2), fade_edges(cr[:n] * env / m, 2)

crashL, crashR = crash_pair()

# ZAPS: the real global chirps straight off the tape.
zap_up = fade_edges(norm_peak(cslice(20.855, 0.23)), 2.0)
zap_down = fade_edges(norm_peak(cslice(380.615, 0.23)), 2.0)

# TICKS: real preamble samples (N512 & d2x flavours), the literal frame rhythm.
tick_a = fade_edges(norm_peak(pre_n512.copy()), 2.0)
tick_b = fade_edges(norm_peak(pre_d2x.copy()), 2.0)

# BASS: additive square-ish on sub-octaves of the real 375 Hz grid.
#   F#2 = 750/8 = 93.75 Hz (lowest real carrier, octave-folded), siblings:
F2, As2, Cs3, E3 = 750 / 8, 1875 / 16, 1125 / 8, 2625 / 16  # 93.75/117.2/140.6/164.1 Hz

def bass_note(f0, dur, cut_base, cut_env, accent=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    cut = cut_base + cut_env * np.exp(-t / 0.085)   # resonant filter envelope
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

BASS_PAT = [  # (step, freq, accent, dur_s)  rolling 16-step groove
    (2, F2, 1.00, 0.21), (6, F2, 0.90, 0.21), (7, As2, 0.65, 0.11),
    (10, Cs3, 0.95, 0.21), (14, E3, 0.90, 0.17), (15, F2, 0.70, 0.10),
]
BASS_PAT2 = BASS_PAT + [(3, F2, 0.55, 0.10), (11, As2, 0.60, 0.10)]

# STABS / PAD: DQPSK phase-hop resynthesis on the exact carrier grid.
def dqpsk_stab(freqs, amps, dur, sym_s=FRAME_S / 16):
    n = int(dur * SR)
    t = np.arange(n) / SR
    sym = (t / sym_s).astype(int)
    y = np.zeros(n)
    for f, a in zip(freqs, amps):
        ph = rng.integers(0, 4, size=sym[-1] + 1) * (np.pi / 2)   # real DQPSK hops
        y += a * np.cos(2 * np.pi * f * t + ph[sym])
    env = np.minimum(t / 0.003, 1.0) * np.exp(-t / (dur / 2.5))
    return fade_edges(lp(y, 9500, 4) * env, 2.0)

CHORD_A = ([750.0, 1125.0, 1500.0, 2250.0], [1.0, 0.8, 0.55, 0.35])   # F# / C#
CHORD_B = ([750.0, 1125.0, 1875.0, 2625.0], [1.0, 0.8, 0.55, 0.40])   # F#7 (E=7th harm)

def pad_pair(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    freqs = [750.0, 1125.0, 1875.0, 2250.0]
    amps = [1.0, 0.7, 0.5, 0.45]
    yl = np.zeros(n)
    yr = np.zeros(n)
    for f, a in zip(freqs, amps):
        p = rng.uniform(0, 2 * np.pi)
        yl += a * np.sin(2 * np.pi * f * t + p)
        yr += a * np.sin(2 * np.pi * f * 1.0012 * t + p)   # slight detune R
    am = 1.0 + 0.15 * np.sin(2 * np.pi * 0.25 * t)
    env = np.minimum(t / 1.5, 1.0) * np.minimum((dur - t) / 2.0, 1.0)
    yl, yr = yl * env * am, yr * env * am
    m = max(np.max(np.abs(yl)), np.max(np.abs(yr)))
    return yl / m, yr / m

# RISER: resynth of the global chirp (500->5000 Hz linear) over N bars + real noisefloor.
def riser(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 500.0 + (5000.0 - 500.0) * t / dur
    chirp = np.sin(2 * np.pi * np.cumsum(f) / SR)
    nz = hp(tile_xfade(cslice(43.0, 2.9), n, 0.2), 2500, 4)   # real noisefloor grain
    nz = norm_peak(nz)
    y = 0.6 * chirp * (t / dur) ** 2.2 + 0.5 * nz * (t / dur) ** 2.0
    return fade_edges(norm_peak(y), 3.0)

# ----------------------------------------------------------------- track buffers
mix = np.zeros((N, 2))
kick_tr = np.zeros((N, 2))
bass_tr = np.zeros((N, 2))
duck = np.zeros(N)            # sidechain amount 0..1

# ------------------- KICK : 4-on-the-floor across all drops + build tails
kick_bars = list(range(12, 40)) + list(range(56, 88)) + list(range(102, 126))
kick_times = [t_of(b, s) for b in kick_bars for s in (0, 4, 8, 12)]
for tks in kick_times:
    add_at(kick_tr, tks, kick, pan=0.0, gain=0.90)
    i0 = int(tks * SR)
    n = min(int(0.5 * SR), N - i0)
    if n > 0:
        curve = np.exp(-np.arange(n) / (0.15 * SR))
        duck[i0:i0 + n] = np.maximum(duck[i0:i0 + n], curve)
print(f"[kick] {len(kick_times)} hits, 4-on-floor @ {BPM:.2f} BPM")

# ------------------- BASS
def lay_bass(bars, pat, cut_base, cut_env_scale, gain):
    for b in bars:
        for (st, f0, acc, dur) in pat:
            nb = bass_note(f0, dur, cut_base, cut_env_scale * acc, acc)
            add_at(bass_tr, t_of(b, st), nb, 0.0, gain)

# builds: single-note pulse with the FILTER opening as the build progresses
def lay_build_bass(bars, gain=0.34):
    bars = list(bars)
    for i, b in enumerate(bars):
        prog = i / max(1, len(bars) - 1)
        for (st, dur) in [(2, 0.21), (6, 0.21), (10, 0.21), (14, 0.21)]:
            nb = bass_note(F2, dur, 170 + 360 * prog, 520, 1.0)
            add_at(bass_tr, t_of(b, st), nb, 0.0, gain)

lay_build_bass(BUILD1, 0.32)
lay_bass(DROP1, BASS_PAT, 700, 1800, 0.36)
lay_build_bass(BUILD2, 0.34)
lay_bass(DROP2, BASS_PAT2, 800, 2200, 0.38)
# break2: lone sub-bass pulse breathing
for b in BREAK2:
    for st in (2, 10):
        add_at(bass_tr, t_of(b, st), bass_note(F2, 0.30, 320, 700, 0.85), 0.0, 0.26)
lay_build_bass(BUILD3, 0.35)
lay_bass(DROP3, BASS_PAT2, 850, 2400, 0.40)

# ------------------- HATS / CLAPS / TICKS / STABS into mix
for b in range(2, N_BARS):
    in_break = (b in BREAK1) or (b in BREAK2)
    in_drop = b in ALL_DROPS
    in_build = (b in BUILD1) or (b in BUILD2) or (b in BUILD3)
    if in_break:
        steps = [10] if b % 2 else [2, 10]
    elif b in INTRO or (b in OUTRO):
        steps = [2, 10]
    elif in_build:
        steps = [2, 6, 10, 14]
    else:
        steps = [2, 6, 10, 14]
    for st in steps:
        open_ = in_drop and st == 10
        g = hat(open_)
        pan = 0.3 if (st // 4) % 2 else -0.3
        add_at(mix, t_of(b, st), g, pan, 0.20 if open_ else 0.23)
    # 16th-note ticking rolls in the heavier drops
    if (b in DROP2) or (b in DROP3):
        for st in (1, 3, 5, 7, 9, 11, 13, 15):
            add_at(mix, t_of(b, st), hat(False), 0.45 if st % 4 == 1 else -0.45, 0.11)

# claps on the backbeat of every drop
for b in ALL_DROPS:
    for st in (4, 12):
        add_at(mix, t_of(b, st), clap, 0.0, 0.34)

# preamble TICKS = the literal frame pulse, in intro/breaks/outro (every 2 beats)
tick_bars = list(INTRO) + list(BREAK1) + list(BREAK2) + list(OUTRO)
ti = 0
for b in tick_bars:
    for st in (0, 8):                       # every 2 beats == exact d2x frame period
        smp = tick_a if ti % 2 == 0 else tick_b
        add_at(mix, t_of(b, st), smp, 0.25 if ti % 2 else -0.25, 0.20)
        ti += 1

# DQPSK modem-chord stabs through the drops
for b in DROP1:
    ch = CHORD_A if b % 2 == 0 else CHORD_B
    add_at(mix, t_of(b, 11), dqpsk_stab(*ch, 0.33), 0.35 if b % 2 else -0.35, 0.13)
for b in DROP2:
    ch = CHORD_A if b % 2 == 0 else CHORD_B
    add_at(mix, t_of(b, 3), dqpsk_stab(*ch, 0.28), -0.4, 0.12)
    add_at(mix, t_of(b, 11), dqpsk_stab(*ch, 0.33), 0.4, 0.13)
for b in DROP3:
    ch = CHORD_A if b % 2 == 0 else CHORD_B
    add_at(mix, t_of(b, 3), dqpsk_stab(*ch, 0.28), -0.4, 0.13)
    add_at(mix, t_of(b, 11), dqpsk_stab(*ch, 0.33), 0.4, 0.14)

# ------------------- BREAKS : pad + gated REAL-capture data stabs
pl, pr = pad_pair(len(list(BREAK1)) * BAR)
add_st(mix, t_of(BREAK1.start), pl, pr, 0.085)
pl2, pr2 = pad_pair(len(list(BREAK2)) * BAR)
add_st(mix, t_of(BREAK2.start), pl2, pr2, 0.075)

gate_src = bp(cslice(212.0, 28.0), 600, 3000, 4)
gp = 0
for b in list(BREAK1) + list(BREAK2):
    for st in (0, 2, 4, 6, 8, 10, 12, 14):
        n = int(0.105 * SR)
        g = fade_edges(gate_src[gp:gp + n].copy(), 4.0)
        gp += int(0.123 * SR)
        if gp + n >= len(gate_src):
            gp = 0
        add_at(mix, t_of(b, st), norm_peak(g), 0.2, 0.15)

# ------------------- RISERS / ZAPS / CRASHES into each drop
# build1 -> drop1 (2-bar riser), build2 -> drop2, build3 -> drop3
add_at(mix, t_of(14), riser(2 * BAR), 0.0, 0.30)
add_at(mix, t_of(58), riser(2 * BAR), 0.0, 0.32)
add_at(mix, t_of(104), riser(2 * BAR), 0.0, 0.34)
for bar in (DROP1.start, DROP2.start, DROP3.start):
    add_at(mix, t_of(bar), zap_up, 0.0, 0.30)        # real up-chirp zap on the drop
    add_st(mix, t_of(bar), crashL, crashR, 0.32)     # Schroeder sounder crash
# soft crash entering the breaks
add_st(mix, t_of(BREAK1.start), crashL, crashR, 0.18)
add_st(mix, t_of(BREAK2.start), crashL, crashR, 0.16)
# the tape says goodbye on the outro
add_at(mix, t_of(129), zap_down, 0.0, 0.32)

# ------------------- MODEM BED (real capture, band-passed, ducked)
bed = np.zeros(N)
bed_plan = [  # (bar_start, bar_end, capture_src_t, gain)  N512=calm, d2x=drops
    (0, 8,    48.0,  0.40), (8, 16,  206.0, 0.32), (16, 40, 206.0, 0.30),
    (40, 52,  52.0,  0.40), (52, 60, 215.0, 0.32), (60, 88, 215.0, 0.30),
    (88, 98,  60.0,  0.40), (98, 106, 252.0, 0.32), (106, 126, 252.0, 0.30),
    (126, 132.6, 60.0, 0.38),
]
for (b0, b1, src_t, g) in bed_plan:
    i0, i1 = int(t_of(b0) * SR), min(int(b1 * BAR * SR), N)
    avail = max(2.0, min(30.0, 380.0 - src_t))
    seg = tile_xfade(cslice(src_t, avail), i1 - i0, 0.4)
    seg = bp(seg, 2000, 6000, 4)
    bed[i0:i1] += fade_edges(norm_peak(seg) * g, 50.0)
bedL = bed.copy()
bedR = np.concatenate([np.zeros(int(0.009 * SR)), bed])[:N]   # 9 ms Haas width

# ------------------- sidechain ducking + sum
bedL *= (1.0 - 0.80 * duck)
bedR *= (1.0 - 0.80 * duck)
bass_tr *= (1.0 - 0.45 * duck)[:, None]
mix[:, 0] += bedL
mix[:, 1] += bedR
mix += kick_tr + bass_tr

# ----------------------------------------------------------------- master
mix[:, 0] = hp(mix[:, 0], 28, 2)
mix[:, 1] = hp(mix[:, 1], 28, 2)

nfi, nfo = int(2.0 * SR), int(4.0 * SR)
mix[:nfi] *= np.linspace(0, 1, nfi)[:, None]
mix[-nfo:] *= np.linspace(1, 0, nfo)[:, None]

# auto-level: drive into tanh so that (after peak-norm to -1.05 dB) RMS ~= -14.9 dBFS
target_rms_db, peak_lin = -14.9, 10 ** (-1.05 / 20)
lo, hi = 0.2, 12.0
g = 1.0
for _ in range(40):
    g = 0.5 * (lo + hi)
    y = np.tanh(g * mix)
    s = peak_lin / np.max(np.abs(y))
    rms_db = 20 * np.log10(np.sqrt(np.mean((y * s) ** 2)))
    if rms_db < target_rms_db:
        lo = g
    else:
        hi = g
yt = np.tanh(g * mix)
final = yt * (peak_lin / np.max(np.abs(yt)))
assert np.all(np.isfinite(final)), "NaN/Inf in final mix"
sf.write(OUT, final, SR, subtype='PCM_16')

# ----------------------------------------------------------------- self-QA
peak_db = 20 * np.log10(np.max(np.abs(final)))
rms_db = 20 * np.log10(np.sqrt(np.mean(final ** 2)))
dur = len(final) / SR
print(f"\n[QA] {OUT}")
print(f"[QA] duration {dur:.2f} s | peak {peak_db:.2f} dBFS | RMS {rms_db:.2f} dBFS | drive g={g:.3f}")
assert dur >= 245 and dur <= 275, f"duration {dur:.1f} out of range"
assert peak_db <= -1.0, f"peak {peak_db:.2f} > -1 dBFS"
assert -16.5 < rms_db < -13.5, f"RMS {rms_db:.2f} out of range"

mono = final.mean(axis=1)
print("[QA] 10-band spectral balance (dB rel. total RMS):")
total = np.sqrt(np.mean(mono ** 2))
for fc in (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000):
    lo_f, hi_f = fc / np.sqrt(2), min(fc * np.sqrt(2), 23500)
    b = sig.sosfilt(sig.butter(4, [lo_f, hi_f], btype='band', fs=SR, output='sos'), mono)
    print(f"      {fc:7.1f} Hz : {20*np.log10(np.sqrt(np.mean(b**2))/total):+6.1f} dB")

f_, t_, S = sig.stft(mono, SR, nperseg=2048, noverlap=1536)
mag = np.abs(S)
flux = np.sum(np.maximum(np.diff(mag, axis=1), 0), axis=0)
hop_s = t_[1] - t_[0]
op, _ = sig.find_peaks(flux, height=np.median(flux) + 1.0 * np.std(flux),
                       distance=max(1, int(0.09 / hop_s)))
ot = t_[op]
print(f"[QA] onsets: {len(op)} total -> {len(op)/dur:.2f}/s overall")
for name, b0, b1 in (("intro", 0, 8), ("drop1", 16, 40), ("break1", 40, 52),
                     ("drop2", 60, 88), ("break2", 88, 98), ("drop3", 106, 126)):
    m = (ot >= t_of(b0)) & (ot < t_of(b1))
    print(f"      {name:6s} onset rate {m.sum()/((b1-b0)*BAR):.2f}/s")
assert len(op) / dur > 1.0, "onset rate too low for a banger"

print("[QA] per-section RMS (dBFS):")
for name, b0, b1 in (("intro", 0, 8), ("build1", 8, 16), ("drop1", 16, 40),
                     ("break1", 40, 52), ("build2", 52, 60), ("drop2", 60, 88),
                     ("break2", 88, 98), ("build3", 98, 106), ("drop3", 106, 126),
                     ("outro", 126, 132)):
    seg = mono[int(t_of(b0) * SR):int(t_of(b1) * SR)]
    print(f"      {name:6s} {20*np.log10(np.sqrt(np.mean(seg**2)) + 1e-12):+6.1f}")
print(f"[QA] seed={SEED}  bpm={BPM:.3f}  bar={BAR:.4f}s  total_bars={N_BARS}")
