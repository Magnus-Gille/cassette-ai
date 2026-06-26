#!/usr/bin/env python3
"""
B-SIDE Track 6 — "Byte-Exact"  ALT MIX  (listener-feedback revision)

Changes from original t6_byte_exact.py:
  1. OPENING CHORDS ENRICHED: intro now uses extended voicings (CHORD_INTRO —
     F#maj9, Bmaj9, C#9sus4, D#m(add9)) via lay_intro_pads(), giving colour tones
     (7ths / 9ths) on top of the unchanged grid ring.  Grid ring level slightly
     trimmed (0.10 → 0.08) so the extensions cut through.
  2. SHRILL BACKGROUND TAMED: lay_grid_ring lowpass tightened 11 kHz → 5 kHz
     (Butterworth 4th-order), and the DQPSK bed's upper bandpass edge moved
     9 kHz → 6 kHz.  Presence of the shimmer is preserved but the harshness is gone.
  3. CHORUS-3 HIT SOFTENED (t≈118 s, "1:59"): upchirp 0.30 → 0.22, crash
     0.30 → 0.20.  The transition still lands but no longer jars.
  4. STRONGER ENDING: outro adds a IV (B) → I (F#) final cadence (bars ob0+7
     and ob0+9) with a clear attack on the tonic landing, plus one final
     CRC-pass motif confirming the tonic — track now has a defined close
     instead of drifting away.  Total duration unchanged.

All other parameters (SR, DUR, stereo, subtype, seed, arrangement) are identical
to the original.
"""
import numpy as np
import scipy.signal as sig
import soundfile as sf

SEED = 20260616
rng = np.random.default_rng(SEED)
print(f"seed = {SEED}")

SR = 48000
BASE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2"
CAPTURE = f"{BASE}/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/alt/t6.wav"

# ------------------------------------------------------------------ timing grid
FRAME_S = 0.983333                 # d2x N256_sp2 nominal frame period (palette.json)
BEAT = FRAME_S / 2.0               # -> 122.034 BPM, confident mid-tempo
BPM = 60.0 / BEAT
BAR = 4 * BEAT
N512_FRAME_S = 1.372667            # the "heroic" half-time pulse (N512 frame)
# Arrangement (~210 s @ 1.9667 s/bar -> ~107 bars):
#   intro 8, V1 8, Ch1 12, V2 8, Ch2 16, V3 8, Ch3 16, Ch4(biggest) 20, outro 11 = 107
SEC = [("intro", 8), ("verse1", 8), ("chorus1", 12), ("verse2", 8),
       ("chorus2", 16), ("verse3", 8), ("chorus3", 16), ("chorus4", 20),
       ("outro", 11)]
bar_start = {}
acc = 0
for name, nb in SEC:
    bar_start[name] = acc
    acc += nb
N_BARS = acc
TAIL = 2.5
DUR = N_BARS * BAR + TAIL
N = int(DUR * SR)
print(f"BPM = {BPM:.3f} | bar = {BAR:.4f} s | bars = {N_BARS} | dur = {DUR:.1f} s")
print("sections:", {k: (bar_start[k], n) for (k, n) in SEC})

mix = np.zeros((N, 2))

def t_of(bar, beat=0.0):
    return (bar * 4 + beat) * BEAT

def add(sig_mono, t_s, amp=1.0, pan=0.0):
    """constant-power pan in [-1,1]"""
    i0 = int(round(t_s * SR))
    if i0 >= N or i0 + len(sig_mono) <= 0:
        return
    s = sig_mono
    if i0 < 0:
        s = s[-i0:]; i0 = 0
    s = s[: N - i0]
    th = (pan + 1.0) * np.pi / 4.0
    mix[i0:i0 + len(s), 0] += s * np.cos(th) * amp
    mix[i0:i0 + len(s), 1] += s * np.sin(th) * amp

def add_st(xl, xr, t_s, amp=1.0):
    i0 = int(round(t_s * SR))
    if i0 >= N:
        return
    n = min(len(xl), len(xr), N - i0)
    mix[i0:i0 + n, 0] += xl[:n] * amp
    mix[i0:i0 + n, 1] += xr[:n] * amp

# ----------------------------------------------------------------- DSP helpers
def hp(x, fc, order=4):
    return sig.sosfilt(sig.butter(order, fc, btype="high", fs=SR, output="sos"), x)

def lp(x, fc, order=4):
    return sig.sosfilt(sig.butter(order, fc, btype="low", fs=SR, output="sos"), x)

def bp(x, lo, hi, order=4):
    return sig.sosfilt(sig.butter(order, [lo, hi], btype="band", fs=SR, output="sos"), x)

def norm(x):
    m = np.max(np.abs(x))
    return x / m if m > 0 else x

def fade_edges(x, ms=3.0):
    n = int(SR * ms / 1000)
    if 2 * n < len(x):
        r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
        x[:n] *= r; x[-n:] *= r[::-1]
    return x

def midi_f(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)

# ----------------------------------------------------- real samples from capture
cap, sr_in = sf.read(CAPTURE)
assert sr_in == SR and cap.ndim == 1
print(f"[load] real capture {len(cap)/SR:.1f} s @ {SR} Hz")

def cslice(t0, dur):
    return cap[int(t0 * SR): int((t0 + dur) * SR)].copy()

# REAL global up-chirp (500->5000 Hz, 0.2 s) — "decode begins"
PREAMBLE_T0 = 46.8634
CAP_FRAME = 1.372896
upchirp = fade_edges(norm(hp(cslice(20.8628 - 0.012, 0.24), 300)), 4.0)
dnchirp = fade_edges(norm(hp(cslice(380.6237 - 0.012, 0.24), 300)), 4.0)

# REAL preamble ticks -> 4 distinct rim/clap voices (capture 46.8634 + k*frame)
ticks = []
for k in range(4):
    tk = cslice(PREAMBLE_T0 + k * CAP_FRAME - 0.003, 0.13)
    tk = hp(tk, 600)
    tk *= np.exp(-np.arange(len(tk)) / (0.020 * SR))     # snap to a rim click
    ticks.append(fade_edges(norm(tk), 1.0))

# REAL Schroeder multitone sounder -> triumphant crash (two reps for stereo width)
def crash_sample(t0, decay=0.55):
    c = hp(cslice(t0, 2.0), 700, 4)
    c *= np.exp(-np.arange(len(c)) / (decay * SR))
    return fade_edges(norm(c), 3.0)
crashL = crash_sample(21.98)
crashR = crash_sample(25.99)

# REAL d2x DQPSK texture -> faint "data intact" hiss bed (band-passed, looped)
# CHANGE 2: upper edge 9 kHz → 6 kHz to tame shrillness in the background
bed_raw = bp(cslice(206.0, 10.0), 3500, 6000)
nx = int(0.3 * SR)
bed_loop = bed_raw[: len(bed_raw) - nx].copy()
r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nx))
bed_loop[:nx] = bed_loop[:nx] * r + bed_raw[-nx:] * r[::-1]
bed_loop = norm(bed_loop)

# ----------------------------------------------- carrier grid retuned to F# MAJOR
# The native grid is a harmonic series on F# +23c (harmonics of 375 Hz). For the
# CLEAN-DECODE payoff we retune EVERY carrier to the nearest pitch of F# MAJOR in
# clean equal temperament (no microtonal +23c smear, no flutter) and ring them out.
N512 = [750, 1125, 1500, 1875, 2250, 2625, 3000, 3375, 3750, 4125, 4500,
        5250, 5625, 6000, 6375, 6750, 7125, 7500, 7875, 8250, 8625, 9000]
# F# major pitch classes: F#(6) G#(8) A#(10) B(11) C#(1) D#(3) E#/F(5)
FS_MAJOR_PC = {6, 8, 10, 11, 1, 3, 5}

def quantize_fs_major(freq):
    m = 69 + 12 * np.log2(freq / 440.0)
    cands = [c for c in range(int(m) - 2, int(m) + 3) if c % 12 in FS_MAJOR_PC]
    best = min(cands, key=lambda c: abs(c - m))
    return best, midi_f(best)

QCAR = [quantize_fs_major(f) for f in N512]
print("real carrier grid -> CLEAN F# MAJOR (ET, steady, no +23c smear):")
print("  " + ", ".join(f"{f:.0f}->{q:.0f}" for f, (m, q) in zip(N512, QCAR)))

# ------------------------------------------------------------------ oscillators
SYMBOL = 2048 / SR                                       # real N512 sp4 symbol = 42.7 ms

def steady_grid_stack(midis, dur, detune_cents=0.0, bright=1.0):
    """STEADY (no vibrato, no flutter) ringing stack on given pitches.
    Slight inter-voice detune for width only; pitch is locked = the 'clean' point."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    yl = np.zeros(n); yr = np.zeros(n)
    for j, m in enumerate(midis):
        f = midi_f(m)
        d = (detune_cents / 1200.0) * (1 if j % 2 else -1)
        pl = rng.uniform(0, 2 * np.pi); pr = rng.uniform(0, 2 * np.pi)
        # a couple of harmonics for body, rolled off so the high grid stays sweet
        for h, ha in ((1, 1.0), (2, 0.18 * bright), (3, 0.07 * bright)):
            if f * h > 16000:
                break
            yl += ha / h * np.sin(2 * np.pi * f * h * (1 - d) * t + pl)
            yr += ha / h * np.sin(2 * np.pi * f * h * (1 + d) * t + pr)
    return yl, yr

def env_ring(n, a=0.012, r_frac=0.18):
    """soft attack, long ringing release — chords that 'ring out clean'."""
    e = np.ones(n)
    na = min(int(a * SR), n)
    e[:na] = np.linspace(0, 1, na) ** 1.5
    nr = min(int(r_frac * n), n)
    e[-nr:] *= np.linspace(1, 0, nr) ** 1.3
    return e

def pluck(freq, dur, tau=0.10, quad=0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * freq * t + quad * np.pi / 2)
    y += 0.25 * np.sin(2 * np.pi * 2 * freq * t)
    e = np.exp(-t / tau)
    na = int(0.003 * SR)
    e[:na] *= np.linspace(0, 1, na)
    return y * e

def lead_tone(freq, dur, level_env=None):
    """warm, STEADY lead voice (the melody / theme) — no flutter, gentle 5th-harmonic glow."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * freq * t
    y = np.sin(ph) + 0.30 * np.sin(3 * ph) + 0.12 * np.sin(5 * ph) + 0.06 * np.sin(2 * ph)
    e = np.ones(n)
    na, nr = int(0.008 * SR), int(0.08 * SR)
    e[:na] = np.linspace(0, 1, na)
    if nr < n:
        e[-nr:] *= np.linspace(1, 0, nr) ** 1.2
    if level_env is not None:
        e *= level_env
    return y * e

def resynth_chirp(f0, f1, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    return sig.chirp(t, f0, dur, f1, method="linear") * sig.windows.tukey(n, 0.2)

def kick(dur=0.13):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 130 * np.exp(-t / 0.028) + 50
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.tanh(1.4 * np.sin(ph)) * np.exp(-t / 0.060)
KICK = kick()

def bass_note(f0, dur, accent=1.0):
    """round, confident sub-bass on the retuned grid roots — steady."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for h, ha in ((1, 1.0), (2, 0.45), (3, 0.22), (4, 0.10)):
        y += ha * np.sin(2 * np.pi * f0 * h * t)
    env = np.minimum(t / 0.006, 1.0) * np.exp(-t / (dur * 0.85))
    nr = int(0.02 * SR)
    env[-nr:] *= np.linspace(1, 0, nr)
    return np.tanh(1.5 * y) * env * accent

# ====================================================================== HARMONY
# 'Three Seventy-Five' theme resolved to F# MAJOR. Diatonic chords in F# major.
# Roman: I=F#  IV=B  V=C#  vi=D#m  ii=G#m  iii=A#m
# Triumphant lift progression: F# - D#m - B - C#  (I - vi - IV - V), with the
# final chorus landing I - IV - I (plagal "amen"/clean-decode resolution).
ROOT = {"F#": 66, "B": 71, "C#": 73, "D#m": 75, "G#m": 68, "A#m": 70}  # midi of root
CHORD = {  # mid-register voicing (the ringing stack core), F#3-ish base
    "F#":  [66, 70, 73, 78, 85],          # F# A# C# F# C#
    "B":   [71, 75, 78, 83, 87],          # B D# F# B D#
    "C#":  [73, 77, 80, 85, 89],          # C# E# G# C# F (E#)
    "D#m": [75, 78, 82, 87, 90],          # D# F# A# D# F#
    "G#m": [68, 71, 75, 80, 87],          # G# B D# G# B
    "A#m": [70, 73, 77, 82, 89],          # A# C# F A# C#
}

# CHANGE 1: extended voicings for the intro only — 7ths/9ths add colour and
# harmonic surprise while the progression identity (I vi IV V) is preserved.
# F# major MIDI map: F#=66 G#=68 A#=70 B=71 C#=73 D#=75 E#(F)=77 F#(oct)=78
CHORD_INTRO = {
    "F#":  [66, 70, 73, 77, 80, 85],  # F#maj9: plain triad + E#(77=maj7) + G#(80=9th)
    "B":   [71, 75, 78, 80, 82, 87],  # Bmaj9:  plain triad + G#(80=9th) + A#(82=maj7)
    "C#":  [73, 75, 78, 80, 85, 89],  # C#9sus4: D#(75) replaces E# (suspension), + G#(80)
    "D#m": [75, 78, 82, 77, 85, 90],  # D#m(add9): plain m-triad + E#(77=add9) + C#(85=m7)
}

# the grid stack: of the retuned carrier pitches, pick those in the current chord's
# pitch classes (so the LITERAL retuned carrier grid rings the chord, in clean ET).
def grid_for_chord(chord_midis, lo=2400, hi=8800):
    pcs = {m % 12 for m in chord_midis}
    out = [q_m for (q_m, q) in QCAR if q_m % 12 in pcs and lo < midi_f(q_m) < hi]
    if not out:
        out = [q_m for (q_m, q) in QCAR if lo < midi_f(q_m) < hi]
    return sorted(set(out))

PROG_VERSE = ["F#", "D#m", "B", "C#"]            # I vi IV V (2 bars each in 8-bar)
PROG_CHORUS = ["F#", "B", "C#", "D#m"]           # I IV V vi
PROG_FINAL = ["F#", "B", "F#", "C#", "F#", "B", "F#", "F#"]  # plagal amen lift

def chords_for(section, nb):
    if section.startswith("verse") or section == "bridge":
        base = PROG_VERSE
    elif section == "chorus4":
        seq = (PROG_FINAL + PROG_FINAL)[: nb // 2]   # plagal amen lift, the resolution
        return seq
    else:
        base = PROG_CHORUS
    # 2 bars per chord, repeat to fill
    seq = []
    while len(seq) < nb // 2:
        seq += base
    return seq[: nb // 2]

# ============================================================== ARRANGEMENT
def section_bars(name):
    b0 = bar_start[name]
    nb = dict(SEC)[name]
    return b0, nb

# ---- pad / ringing chord stacks: STEADY (no flutter) — the centerpiece ----
def lay_pads(name, level, bright=1.0, detune=4.0):
    b0, nb = section_bars(name)
    seq = chords_for(name, nb)
    for i, ch in enumerate(seq):
        bar = b0 + i * 2
        dur = 2 * BAR
        yl, yr = steady_grid_stack(CHORD[ch], dur, detune_cents=detune, bright=bright)
        e = env_ring(len(yl), a=0.05, r_frac=0.14)
        yl *= e; yr *= e
        m = max(np.max(np.abs(yl)), np.max(np.abs(yr))) + 1e-9
        add_st(yl / m, yr / m, t_of(bar), level)

# CHANGE 1: intro-specific pad layer using CHORD_INTRO extended voicings
def lay_intro_pads(level, detune=5.5, bright=0.92):
    """Richer harmonic opening: 7ths / 9ths / suspensions on the intro chords."""
    b0, nb = section_bars("intro")
    seq = chords_for("intro", nb)
    for i, ch in enumerate(seq):
        bar = b0 + i * 2
        dur = 2 * BAR
        yl, yr = steady_grid_stack(CHORD_INTRO[ch], dur, detune_cents=detune, bright=bright)
        e = env_ring(len(yl), a=0.07, r_frac=0.15)
        yl *= e; yr *= e
        m = max(np.max(np.abs(yl)), np.max(np.abs(yr))) + 1e-9
        add_st(yl / m, yr / m, t_of(bar), level)

# ---- the literal retuned CARRIER GRID ringing the chord (high shimmer) ----
# CHANGE 2: lowpass tightened from 11 kHz → 5 kHz to tame shrillness
def lay_grid_ring(name, level):
    b0, nb = section_bars(name)
    seq = chords_for(name, nb)
    for i, ch in enumerate(seq):
        bar = b0 + i * 2
        gmidis = grid_for_chord(CHORD[ch])
        # sustained, steady ring of the actual carrier pitches
        yl, yr = steady_grid_stack(gmidis, 2 * BAR, detune_cents=2.5, bright=0.5)
        e = env_ring(len(yl), a=0.10, r_frac=0.20)
        yl *= e; yr *= e
        m = max(np.max(np.abs(yl)), np.max(np.abs(yr))) + 1e-9
        add_st(lp(yl / m, 5000), lp(yr / m, 5000), t_of(bar), level)

# ---- bass on the chord roots (sub-octave of the grid where possible) ----
def lay_bass(name, level, pat="walk"):
    b0, nb = section_bars(name)
    seq = chords_for(name, nb)
    for i, ch in enumerate(seq):
        bar0 = b0 + i * 2
        rootf = midi_f(ROOT[ch] - 24)        # 2 octaves down = warm sub
        for bb in range(2):
            bar = bar0 + bb
            if pat == "walk":
                steps = [(0, 0.9, 1.0), (1.5, 0.5, 0.7), (2, 0.9, 0.95),
                         (3, 0.5, 0.7), (3.5, 0.4, 0.6)]
            else:  # driving
                steps = [(0, 0.55, 1.0), (1, 0.55, 0.8), (2, 0.55, 0.95),
                         (3, 0.55, 0.85)]
            for (bt, dur, acc) in steps:
                y = bass_note(rootf, dur * BEAT, acc)
                add(y, t_of(bar, bt), level)

# ---- the 'CRC-PASSES' motif: rising, affirmative 3-note all-clear figure ----
# scale-degree 5 -> 7 -> 8 (lands clean on tonic octave). In F#: C# -> F(E#) -> F#.
def crc_motif(root_midi, t0, level=0.20, pan=0.0, octave=0):
    deg = [root_midi + 7 + 12 * octave,    # 5th
           root_midi + 11 + 12 * octave,   # maj7 (leading tone)
           root_midi + 12 + 12 * octave]   # tonic octave — the "pass"
    durs = [0.5, 0.5, 1.2]
    t = t0
    for j, (m, d) in enumerate(zip(deg, durs)):
        dur = d * BEAT
        lvl_env = None
        y = lead_tone(midi_f(m), dur)
        add(y, t, level * (1.0 if j < 2 else 1.15), pan)
        t += dur

# ---- main melodic theme (the 'Three Seventy-Five' theme, in F# major) ----
# scale degrees over the chorus (clear, singable, lands on tonic). Degrees relative
# to F# major: 1=F#(66) 2=G# 3=A# 4=B 5=C# 6=D# 7=E#(F). We write absolute midis.
THEME = [  # (beat_in_8bar, dur_beats, midi)  -- 8-bar phrase
    (0, 1.5, 73), (1.5, 0.5, 75), (2, 1.0, 78), (3, 1.0, 75),   # C# D# F# D#
    (4, 2.0, 73), (6, 1.0, 71), (7, 1.0, 73),                   # C#  B  C#
    (8, 1.5, 78), (9.5, 0.5, 80), (10, 1.0, 82), (11, 1.0, 78), # F# G# A# F#
    (12, 2.0, 80), (14, 2.0, 78),                               # G#  F#
    (16, 1.5, 78), (17.5, 0.5, 82), (18, 1.0, 85), (19, 1.0, 82),
    (20, 2.0, 80), (22, 2.0, 73),
    (24, 1.0, 75), (25, 1.0, 78), (26, 1.0, 80), (27, 1.0, 82),
    (28, 3.0, 78), (31, 1.0, 73),                               # land on F#, pickup
]

def lay_theme(name, level=0.20, pan=0.0, octave=0):
    b0, nb = section_bars(name)
    for (bt, dur, m) in THEME:
        if bt >= nb * 4:
            break
        bar = b0 + int(bt // 4)
        beat = bt % 4
        y = lead_tone(midi_f(m + 12 * octave), dur * BEAT)
        # tiny stereo doubling for warmth
        add(y, t_of(bar, beat), level, pan)

# ---- shimmer arp on the retuned grid (clean, steady 16ths/8ths) ----
def lay_grid_arp(name, level, div=2):
    b0, nb = section_bars(name)
    seq = chords_for(name, nb)
    pattern = [0, 1, 2, 3, 2, 1]
    k = 0
    for i, ch in enumerate(seq):
        gset = [m for m in grid_for_chord(CHORD[ch], 2400, 6500)]
        if not gset:
            continue
        for bb in range(2):
            bar = b0 + i * 2 + bb
            for s_ in range(4 * div):
                m = gset[pattern[k % len(pattern)] % len(gset)]
                k += 1
                dur = BEAT / div * 0.9
                y = pluck(midi_f(m), dur, tau=0.06, quad=int(rng.integers(0, 4)))
                pan = 0.55 * (1 if s_ % 2 else -1)
                add(y, t_of(bar, s_ / div), level, pan)

# ---- groove: kick + real-tick rim + half-time heroic clap ----
def lay_groove(name, kick_on=True, four_floor=True, rim=True, heroic_clap=False):
    b0, nb = section_bars(name)
    for b in range(b0, b0 + nb):
        if kick_on:
            beats = (0, 1, 2, 3) if four_floor else (0, 2)
            for bt in beats:
                add(KICK, t_of(b, bt), 0.42)
        if rim:                              # real preamble tick on backbeats 2 & 4
            for bt in (1, 3):
                add(ticks[(b + bt) % 4], t_of(b, bt), 0.20, pan=0.18 * (1 if bt == 1 else -1))
        if heroic_clap:                      # half-time: big crash-tick on beat 3
            add(ticks[(b) % 4], t_of(b, 2), 0.16, pan=0.0)

# real frame-rhythm layer: ticks placed at the TRUE measured d2x frame period.
def lay_frame_rhythm(b0_bar, b1_bar, level=0.10):
    t = t_of(b0_bar)
    tend = t_of(b1_bar)
    s = 1
    i = 0
    while t < tend:
        add(ticks[i % 4], t, level, pan=0.5 * s)
        s = -s; i += 1
        t += FRAME_S

# real DQPSK 'data intact' hiss bed
def lay_bed(b0_bar, b1_bar, level):
    t0 = t_of(b0_bar); t1 = t_of(b1_bar)
    t = t0
    while t < t1:
        seg = bed_loop[: int(min(len(bed_loop), (t1 - t) * SR))]
        add(seg, t, level, pan=(0.0 if (int(t) % 2) else 0.0))
        # tiny Haas widen on R
        i0 = int(round(t * SR)) + int(0.008 * SR)
        if i0 < N:
            n = min(len(seg), N - i0)
            mix[i0:i0 + n, 1] += seg[:n] * level * 0.5
        t += len(bed_loop) / SR

# ====================================================================== BUILD IT
print("[build] laying sections ...")

def sb(name):
    return bar_start[name], dict(SEC)[name]

# INTRO (8): real up-chirp (decode begins) + grid ring swelling in + bed
# CHANGE 1: lay_intro_pads() adds extended voicings (7ths/9ths); grid ring level
# trimmed 0.10 → 0.08 so the colour tones cut through.
add(upchirp, t_of(0) + 0.15, 0.34, pan=-0.15)
add(resynth_chirp(500, 5000, 3 * BEAT) * np.linspace(0.1, 1, int(3 * BEAT * SR)) ** 2,
    t_of(1), 0.16)
b0, nb = sb("intro")
lay_bed(b0, b0 + nb, 0.06)
lay_grid_ring("intro", 0.08)      # slightly trimmed to make room for extended pads
lay_intro_pads(0.09)              # NEW: richer F#maj9 / Bmaj9 / C#9sus4 / D#m(add9)
# distant CRC-pass motifs preview the payoff
crc_motif(66, t_of(b0 + 2, 2), level=0.12, pan=0.2, octave=0)
crc_motif(66, t_of(b0 + 4, 2), level=0.14, pan=-0.2, octave=0)
add_st(crashL, crashR, t_of(b0 + 2), 0.10)   # soft swell

# VERSE 1 (8): steady pads + warm bass + sparse grid arp + groove (half-time)
b0, nb = sb("verse1")
lay_pads("verse1", 0.11, bright=0.8, detune=4.0)
lay_bass("verse1", 0.20, pat="walk")
lay_groove("verse1", kick_on=True, four_floor=False, rim=True)
lay_frame_rhythm(b0, b0 + nb, 0.08)
lay_bed(b0, b0 + nb, 0.035)
crc_motif(66, t_of(b0 + nb - 2, 2), level=0.16, pan=-0.2)

# CHORUS 1 (12): full 4-on-floor groove, theme enters, grid ring + arp, crash
b0, nb = sb("chorus1")
add(upchirp, t_of(b0) - 0.2, 0.26, pan=0.0)
add_st(crashL, crashR, t_of(b0), 0.24)
lay_pads("chorus1", 0.12, bright=1.0, detune=4.5)
lay_grid_ring("chorus1", 0.085)
lay_bass("chorus1", 0.22, pat="drive")
lay_groove("chorus1", kick_on=True, four_floor=True, rim=True, heroic_clap=True)
lay_grid_arp("chorus1", 0.045, div=2)
lay_theme("chorus1", level=0.21, pan=0.0)
for k in range((nb - 4) // 4):
    crc_motif(66, t_of(b0 + 3 + k * 4, 2.5), level=0.19,
              pan=0.18 * (1 if k % 2 else -1), octave=1)

# VERSE 2 (8): fuller than V1, theme an octave down hummed quietly
b0, nb = sb("verse2")
lay_pads("verse2", 0.115, bright=0.85, detune=4.0)
lay_bass("verse2", 0.21, pat="walk")
lay_groove("verse2", kick_on=True, four_floor=True, rim=True)
lay_grid_arp("verse2", 0.038, div=2)
lay_frame_rhythm(b0, b0 + nb, 0.07)
lay_theme("verse2", level=0.13, pan=-0.1, octave=-1)
lay_bed(b0, b0 + nb, 0.030)
crc_motif(71, t_of(b0 + nb - 2, 2), level=0.15, pan=0.25)  # over IV

# CHORUS 2 (16, big): everything, theme up top, grid arp 16ths, double crash
b0, nb = sb("chorus2")
add(upchirp, t_of(b0) - 0.2, 0.28)
add_st(crashL, crashR, t_of(b0), 0.26)
lay_pads("chorus2", 0.125, bright=1.05, detune=5.0)
lay_grid_ring("chorus2", 0.09)
lay_bass("chorus2", 0.23, pat="drive")
lay_groove("chorus2", kick_on=True, four_floor=True, rim=True, heroic_clap=True)
lay_grid_arp("chorus2", 0.05, div=4)
lay_theme("chorus2", level=0.22, pan=0.0)
lay_theme("chorus2", level=0.07, pan=0.4, octave=1)     # octave shimmer double
for k in range((nb - 4) // 4):
    crc_motif(66, t_of(b0 + 3 + k * 4, 2.5), level=0.18,
              pan=0.2 * (1 if k % 2 else -1), octave=1)

# VERSE 3 (8): brief lift-prep before the final double-chorus
b0, nb = sb("verse3")
lay_pads("verse3", 0.12, bright=0.78, detune=3.5)
lay_bass("verse3", 0.19, pat="walk")
lay_groove("verse3", kick_on=True, four_floor=True, rim=True)
lay_grid_arp("verse3", 0.036, div=2)
lay_frame_rhythm(b0, b0 + nb, 0.08)
lay_theme("verse3", level=0.17, pan=0.0)
lay_bed(b0, b0 + nb, 0.030)
crc_motif(73, t_of(b0 + nb - 2, 2), level=0.16, pan=-0.25, octave=0)  # over V
# build riser into chorus 3
add(resynth_chirp(500, 5000, 4 * BEAT) * np.linspace(0.1, 1, int(4 * BEAT * SR)) ** 2.2,
    t_of(b0 + nb - 2), 0.20)

# CHORUS 3 (16): biggest "normal" chorus, full grid stacks, theme + octave double
# CHANGE 3: upchirp 0.30→0.22, crash 0.30→0.20 — softens the jarring hit at t≈118 s
b0, nb = sb("chorus3")
add(upchirp, t_of(b0) - 0.2, 0.22)            # was 0.30
add_st(crashL, crashR, t_of(b0), 0.20)         # was 0.30
lay_pads("chorus3", 0.13, bright=1.1, detune=5.5)
lay_grid_ring("chorus3", 0.10)
lay_bass("chorus3", 0.24, pat="drive")
lay_groove("chorus3", kick_on=True, four_floor=True, rim=True, heroic_clap=True)
lay_grid_arp("chorus3", 0.052, div=4)
lay_theme("chorus3", level=0.23, pan=0.0)
lay_theme("chorus3", level=0.08, pan=-0.4, octave=1)
for k in range((nb - 4) // 4):
    crc_motif(66, t_of(b0 + 3 + k * 4, 2.5), level=0.20,
              pan=0.25 * (1 if k % 2 else -1), octave=1)

# CHORUS 4 (20, BIGGEST): plagal amen lift (I-IV-I), full grid stacks ringing clean
# and PERFECTLY STEADY, theme + octave double, CRC-pass resolving to tonic again
# and again. This is the emotional summit: 0 codewords failed.
b0, nb = sb("chorus4")
add(upchirp, t_of(b0) - 0.2, 0.32)
add_st(crashL, crashR, t_of(b0), 0.32)
add_st(crashL, crashR, t_of(b0 + 8), 0.26)
lay_pads("chorus4", 0.135, bright=1.12, detune=5.5)
lay_grid_ring("chorus4", 0.105)
lay_bass("chorus4", 0.25, pat="drive")
lay_groove("chorus4", kick_on=True, four_floor=True, rim=True, heroic_clap=True)
lay_grid_arp("chorus4", 0.053, div=4)
lay_theme("chorus4", level=0.24, pan=0.0)
lay_theme("chorus4", level=0.085, pan=-0.4, octave=1)
for k in range((nb - 4) // 4):
    crc_motif(66, t_of(b0 + 3 + k * 4, 2.5), level=0.21,
              pan=0.25 * (1 if k % 2 else -1), octave=1)
# high tonic affirmation near the end
crc_motif(78, t_of(b0 + nb - 3, 2), level=0.16, pan=0.0, octave=0)

# OUTRO: chord stacks ring out clean and STEADY, thinning groove, final tonic, no
# down-chirp (this is triumph, not farewell — the goodbye is the coda track 8/9),
# but one calm grid ring on F# fading. A last faint up-chirp echoes "byte-exact".
ob0, on = sb("outro")
yl, yr = steady_grid_stack(CHORD["F#"] + [90], on * BAR, detune_cents=4.0, bright=0.9)
e = env_ring(len(yl), a=0.06, r_frac=0.45)
yl *= e; yr *= e
m = max(np.max(np.abs(yl)), np.max(np.abs(yr))) + 1e-9
add_st(yl / m, yr / m, t_of(ob0), 0.12)
# thinning groove: first 4 bars keep the kick, then only frame ticks ring away
for b in range(ob0, ob0 + 4):
    for bt in (0, 1, 2, 3):
        add(KICK, t_of(b, bt), 0.40)
    for bt in (1, 3):
        add(ticks[(b + bt) % 4], t_of(b, bt), 0.18, pan=0.18 * (1 if bt == 1 else -1))
lay_frame_rhythm(ob0, ob0 + on, 0.08)
lay_bed(ob0, ob0 + on, 0.04)
# final ringing CRC-pass that lands and holds the tonic
crc_motif(66, t_of(ob0 + 1, 0), level=0.20, pan=0.0, octave=1)
# last quiet up-chirp = the data, recovered, intact
add(upchirp, t_of(ob0 + on - 3), 0.16, pan=0.0)
# hold a clean F# major triad tail through the fade-out
yl2, yr2 = steady_grid_stack([66, 70, 73, 78, 85], 6 * BAR, detune_cents=3.0, bright=0.7)
e2 = env_ring(len(yl2), a=0.1, r_frac=0.55)
add_st(yl2 / (np.max(np.abs(yl2)) + 1e-9) * e2,
       yr2 / (np.max(np.abs(yr2)) + 1e-9) * e2, t_of(ob0 + 4), 0.11)

# CHANGE 4: stronger ending — IV (B) → I (F#) final cadence gives a defined close
# instead of just drifting away.  Both chords land within the existing outro duration.
# Bar ob0+7 (≈202.6 s): B major (subdominant IV) rings in, building pre-cadential tension
yl_iv, yr_iv = steady_grid_stack(CHORD["B"] + [87], 2 * BAR, detune_cents=3.0, bright=1.0)
e_iv = env_ring(len(yl_iv), a=0.025, r_frac=0.25)
yl_iv *= e_iv; yr_iv *= e_iv
m_iv = max(np.max(np.abs(yl_iv)), np.max(np.abs(yr_iv))) + 1e-9
add_st(yl_iv / m_iv, yr_iv / m_iv, t_of(ob0 + 7), 0.18)
# Bar ob0+9 (≈206.5 s): F# tonic final landing — sharp attack, defined close
yl_fn, yr_fn = steady_grid_stack(CHORD["F#"] + [90], 2 * BAR, detune_cents=2.0, bright=1.1)
e_fn = env_ring(len(yl_fn), a=0.012, r_frac=0.60)
yl_fn *= e_fn; yr_fn *= e_fn
m_fn = max(np.max(np.abs(yl_fn)), np.max(np.abs(yr_fn))) + 1e-9
add_st(yl_fn / m_fn, yr_fn / m_fn, t_of(ob0 + 9), 0.17)
# Final CRC-pass motif on the tonic landing — one last "byte-exact" affirmation
crc_motif(66, t_of(ob0 + 9, 2), level=0.19, pan=0.0, octave=1)

# ---------------------------------------------------- gentle stereo delay glue
d = int(0.75 * BEAT * SR)                                # dotted-8th cross echo
echo = np.zeros_like(mix)
echo[d:, 0] = 0.16 * mix[:-d, 1]
echo[d:, 1] = 0.16 * mix[:-d, 0]
mix += echo

# ============================================================= MASTER / LEVELS
mix[:, 0] = hp(mix[:, 0], 28, 2)
mix[:, 1] = hp(mix[:, 1], 28, 2)

# fades
nfi, nfo = int(2.0 * SR), int(4.0 * SR)
mix[:nfi] *= np.linspace(0, 1, nfi)[:, None] ** 1.4
mix[-nfo:] *= np.linspace(1, 0, nfo)[:, None] ** 1.4

# auto-level: drive into soft tanh, peak-norm to -1.05 dB, RMS ~ -14.9 dBFS
target_rms_db, peak_lin = -14.9, 10 ** (-1.05 / 20)
lo, hi = 0.2, 12.0
g = 1.0
for _ in range(42):
    g = 0.5 * (lo + hi)
    y = np.tanh(g * mix)
    s = peak_lin / (np.max(np.abs(y)) + 1e-12)
    rms_db = 20 * np.log10(np.sqrt(np.mean((y * s) ** 2)) + 1e-12)
    if rms_db < target_rms_db:
        lo = g
    else:
        hi = g
yt = np.tanh(g * mix)
final = yt * (peak_lin / (np.max(np.abs(yt)) + 1e-12))
assert np.isfinite(final).all(), "non-finite samples!"
sf.write(OUT, final.astype(np.float32), SR, subtype="PCM_16")

# ======================================================================= SELF-QA
peak_db = 20 * np.log10(np.max(np.abs(final)))
rms_db = 20 * np.log10(np.sqrt(np.mean(final ** 2)))
dur = len(final) / SR
print(f"\n[QA] {OUT}")
print(f"[QA] duration = {dur:.2f} s | peak = {peak_db:+.2f} dBFS | "
      f"RMS = {rms_db:+.2f} dBFS | drive g = {g:.3f}")
assert peak_db <= -1.0 + 0.05, "peak ceiling violated"
assert 195 <= dur <= 225, f"duration {dur:.1f} out of ~210+-15 range"

mono = final.mean(axis=1)
print("[QA] 10-band spectral balance (dB rel total RMS):")
total = np.sqrt(np.mean(mono ** 2)) + 1e-12
band_db = {}
for fc in (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000):
    lof, hif = fc / np.sqrt(2), min(fc * np.sqrt(2), 23500)
    bb = sig.sosfilt(sig.butter(4, [lof, hif], btype="band", fs=SR, output="sos"), mono)
    d_ = 20 * np.log10(np.sqrt(np.mean(bb ** 2)) / total + 1e-12)
    band_db[fc] = d_
    print(f"      {fc:7.1f} Hz : {d_:+6.1f} dB")

# onset rate
f_, t_, S = sig.stft(mono, SR, nperseg=2048, noverlap=1536)
mag = np.abs(S)
flux = np.sum(np.maximum(np.diff(mag, axis=1), 0), axis=0)
hop_s = t_[1] - t_[0]
op, _ = sig.find_peaks(flux, height=np.median(flux) + 1.0 * np.std(flux),
                       distance=max(1, int(0.10 / hop_s)))
onset_rate = len(op) / dur
print(f"[QA] onset rate = {onset_rate:.2f} onsets/s ({len(op)} onsets)")

# intent sanity checks
mid_energy = band_db[1000] + band_db[2000]
print(f"[QA intent] mid-band (1k+2k) sum = {mid_energy:+.1f} dB")
print(f"[QA intent] onset {onset_rate:.2f}/s -> expect steady mid-tempo groove "
      f"(~3-7/s; not sparse like an ambient track, not a frantic wall)")
print(f"[QA intent] groove: 4-on-floor @ {BPM:.1f} BPM from d2x frame; "
      f"heroic half-time pulse at N512 frame {N512_FRAME_S:.3f}s")
print(f"\n[QA] seed = {SEED}  bars = {N_BARS}  bpm = {BPM:.3f}")
print(f"wrote {OUT}")
