#!/usr/bin/env python3
"""
B-SIDE track 4 — "Three Seventy-Five"  (the bright heart of the record)

The 375 Hz carrier grid IS the melody. A natural-minor tune at ~109 BPM where the
real cassette-modem signal sings: every carrier of the N512_sp4 grid (375 Hz
harmonics, 750..9000 Hz) is quantized to the nearest A-natural-minor pitch and the
literal retuned grid plays a high 'sparkle' arpeggio; a DQPSK phase-flip on every
melody note keeps the modem character; the real frame-preamble ticks are the
rim-click backbeat; a portamento lead carries the tune. AABA, hopeful, expanded into
a fuller arrangement than remix_melodic.py: a sung counter-melody in the B section
and a key LIFT (Am -> Cm, up a minor third) for the final statement before the outro.

REAL SIGNAL QUOTED (the soul of the record):
  * REAL global chirps sampled from tape10_run1.wav (up @ 20.863 s, down @ 380.624 s)
    as phrase transitions + bookends, plus stretched resynthesized 500->5000 Hz risers.
  * REAL frame-preamble ticks (capture 46.8634 + k*1.372896 s) as rim-click percussion
    AND an authentic frame-rhythm layer ticking at the TRUE measured N512 frame period
    (1.372896 s), locked to the grid (one frame = exactly 2.5 beats -> 109.26 BPM).
  * REAL Schroeder multitone splash (capture 21.98 / 25.99 s) as section crashes.
  * REAL d2x DQPSK texture (capture ~206 s) band-passed as a 'data hiss' bed.
  * The ACTUAL N512 carrier grid retuned to A natural minor: literal carriers form the
    grid-sparkle arp; octave-folded carrier pitches seed the main arp & bass voicings.
    DQPSK-style 90-deg phase hops at the real N512 symbol rate (2048 samples = 42.7 ms)
    buzz the pad; every plucked/chip note starts on a random quadrant phase (DQPSK).

FORM (109.26 BPM, bar = 4 beats = 2.196 s):
  Intro    bars  0-7    (8)  data-hiss + ticks fade in, grid sparkle wakes up
  A1       bars  8-15   (8)  theme, lead enters
  A2       bars 16-23   (8)  theme + grid sparkle, fuller drums
  B        bars 24-31   (8)  lift the harmony, lead + COUNTER-MELODY answer phrases
  A3       bars 32-39   (8)  theme reprise, brightest
  Lift     bars 40-43   (4)  riser / modulation transition (Am -> Cm)
  A4'      bars 44-51   (8)  theme in Cm (key lift, +3 semitones), triumphant
  Outro    bars 52-59   (8)  thinning, down-chirp farewell
  = 60 bars  ~ 131.8 s of music + tail ... too short. Doubled A-sections below to 105 bars.

Output: t4.wav  (stereo 48 kHz 16-bit, peak <= -1 dBFS, RMS ~ -15 dBFS, 2 s fade-in /
4 s fade-out). Self-QA prints peak/RMS/duration, 10-band spectral balance, onset rate;
expect clear melodic mid-band energy and a moderate onset rate (8th/16th arp at 109 BPM).
"""
import numpy as np
import soundfile as sf
from scipy import signal

SEED = 20260614
rng = np.random.default_rng(SEED)
print(f"seed = {SEED}")

SR = 48000
BASE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2"
CAPTURE = f"{BASE}/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/alt/t4.wav"

# ----------------------------------------------------------------- timing grid
FRAME_S = 1.372896                  # measured N512 frame period in the capture
BEAT = FRAME_S / 2.5                # frame = exactly 2.5 beats  -> 109.26 BPM
BPM = 60.0 / BEAT
BAR = 4 * BEAT
TAIL = 4.5
print(f"BPM = {BPM:.3f} (frame {FRAME_S:.6f} s = 2.5 beats), bar = {BAR:.4f} s")

# ---------------------------------------------------------------- song sections
# (start_bar, n_bars, label). A 230 s target -> ~105 bars.
SECTIONS = [
    ("intro", 8),
    ("A1", 8),
    ("A2", 8),
    ("A2b", 8),     # second A statement, fuller
    ("B", 8),       # counter-melody section
    ("A3", 8),
    ("A3b", 8),
    ("B2", 8),      # second B, counter-melody develops
    ("A4", 8),
    ("lift", 4),    # modulation riser
    ("Acm1", 8),    # theme in Cm (key lift +3)
    ("Acm2", 8),    # theme in Cm, brightest
    ("outro", 8),
]
bar_cursor = 0
SEC = {}
for name, nb in SECTIONS:
    SEC[name] = (bar_cursor, nb)
    bar_cursor += nb
N_BARS = bar_cursor
print(f"N_BARS = {N_BARS}  ({SECTIONS})")

DUR = N_BARS * BAR + TAIL
N = int(DUR * SR)
mixL = np.zeros(N)
mixR = np.zeros(N)
print(f"target music length = {N_BARS*BAR:.1f} s (+ {TAIL}s tail) = {DUR:.1f} s")

def add(sig, t_s, amp=1.0, pan=0.0):
    """pan in [-1, 1] (equal-power)."""
    i0 = int(t_s * SR)
    if i0 >= N or i0 + len(sig) <= 0:
        return
    s = sig
    if i0 < 0:
        s = s[-i0:]; i0 = 0
    s = s[: N - i0]
    th = (pan + 1) * np.pi / 4
    mixL[i0:i0 + len(s)] += s * np.cos(th) * amp
    mixR[i0:i0 + len(s)] += s * np.sin(th) * amp

def env_adsr(n, a=0.005, d=0.05, s=0.8, r=0.06):
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    e = np.full(n, float(s))
    na = min(na, n); e[:na] = np.linspace(0, 1, na)
    if na + nd < n:
        e[na:na + nd] = np.linspace(1, s, nd)
    nr = min(nr, n)
    if nr > 0:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e

# ------------------------------------------------- real samples from the capture
cap, _ = sf.read(CAPTURE, dtype="float64")

def grab(t0, dur):
    i = int(t0 * SR)
    return cap[i:i + int(dur * SR)].copy()

def hp(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "high")
    return signal.lfilter(b, a, x)

def bp(x, f1, f2, order=3):
    b, a = signal.butter(order, [f1 / (SR / 2), f2 / (SR / 2)], "band")
    return signal.lfilter(b, a, x)

def norm(x):
    return x / (np.max(np.abs(x)) + 1e-12)

# rim-click ticks: 4 different real preambles (capture 46.8634 + k*1.372896)
ticks = []
for k in range(4):
    t = grab(46.8634 + k * FRAME_S - 0.002, 0.12)
    t = hp(t, 500)
    t *= np.exp(-np.arange(len(t)) / (0.022 * SR))     # snap into a rim click
    t[: int(0.001 * SR)] *= np.linspace(0, 1, int(0.001 * SR))
    ticks.append(norm(t))

# a softer, longer 'shaker' from the same preamble for fills
shaker = grab(46.8634 - 0.002, 0.12)
shaker = hp(shaker, 1500)
shaker *= np.exp(-np.arange(len(shaker)) / (0.040 * SR))
shaker = norm(shaker)

# real global chirps
chirp_up = norm(hp(grab(20.8628 - 0.01, 0.24), 300))
chirp_dn = norm(hp(grab(380.6237 - 0.01, 0.24), 300))
for c in (chirp_up, chirp_dn):
    c[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    c[-int(0.02 * SR):] *= np.linspace(1, 0, int(0.02 * SR))

# Schroeder multitone splash -> crash (two reps = decorrelated L/R)
def crash_sample(t0, tau=0.45, length=1.6):
    c = hp(grab(t0, length), 300)
    c *= np.exp(-np.arange(len(c)) / (tau * SR))
    c[: int(0.003 * SR)] *= np.linspace(0, 1, int(0.003 * SR))
    return norm(c)
crashL = crash_sample(21.98)
crashR = crash_sample(25.99)
crash_short_L = crash_sample(21.98, tau=0.22, length=0.9)
crash_short_R = crash_sample(25.99, tau=0.22, length=0.9)

# d2x DQPSK texture bed (band-passed so it reads as 'data hiss' over the harmony)
bed_raw = bp(grab(206.0, 8.0), 3500, 9000)
nx = int(0.25 * SR)                                    # crossfade loop
bed_loop = bed_raw[: len(bed_raw) - nx].copy()
bed_loop[:nx] = bed_loop[:nx] * np.linspace(0, 1, nx) + bed_raw[-nx:] * np.linspace(1, 0, nx)
bed_loop = norm(bed_loop)

# ----------------------------------------------------------- carrier quantization
N512 = [750, 1125, 1500, 1875, 2250, 2625, 3000, 3375, 3750, 4125, 4500,
        5250, 5625, 6000, 6375, 6750, 7125, 7500, 7875, 8250, 8625, 9000]
A_MINOR_PC = {9, 11, 0, 2, 4, 5, 7}                    # A B C D E F G

def quantize_pc(freq, pcset):
    m = 69 + 12 * np.log2(freq / 440.0)
    cands = np.arange(int(m) - 2, int(m) + 3)
    cands = [c for c in cands if c % 12 in pcset]
    best = min(cands, key=lambda c: abs(c - m))
    return best, 440.0 * 2 ** ((best - 69) / 12)

QCAR = [quantize_pc(f, A_MINOR_PC) for f in N512]      # (midi, freq) per carrier, A minor
print("carrier grid -> A natural minor (literal retune of the real 375 Hz harmonics):")
print("  " + ", ".join(f"{f}->{q:.0f}" for f, (m, q) in zip(N512, QCAR)))

def midi_f(m):
    return 440.0 * 2 ** ((m - 69) / 12)

# ------------------------------------------------------------------- oscillators
SYMBOL = 2048 / SR                                     # real N512 sp4 symbol = 42.7 ms

def smooth_steps(steps, n, step_n, ramp_s=0.0018):
    off = np.repeat(steps, step_n)[:n]
    if len(off) < n:
        off = np.pad(off, (0, n - len(off)), mode="edge")
    k = max(3, int(ramp_s * SR))
    return signal.lfilter(np.ones(k) / k, [1.0], off)

def dqpsk_tone(freq, dur, hop_s=SYMBOL):
    """sustained tone whose phase hops 0/90/180/270 every symbol (the modem buzz)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    nsym = int(np.ceil(dur / hop_s)) + 1
    quad = rng.integers(0, 4, nsym) * (np.pi / 2)
    off = smooth_steps(quad, n, int(hop_s * SR))
    return np.sin(2 * np.pi * freq * t + off)

def chip_note(freq, dur, quadrant):
    """band-limited square-ish chip tone, DQPSK quadrant start phase."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * freq * t + quadrant * (np.pi / 2)
    y = np.sin(ph)
    if freq * 3 < 16000: y = y + 0.30 * np.sin(3 * ph)
    if freq * 5 < 16000: y = y + 0.12 * np.sin(5 * ph)
    return y

def pluck(freq, dur, quadrant, tau=0.12):
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * freq * t + quadrant * np.pi / 2)
    e = np.exp(-t / tau)
    e[: int(0.003 * SR)] *= np.linspace(0, 1, int(0.003 * SR))
    return y * e

def resynth_chirp(f0, f1, dur, amp_env=True):
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = signal.chirp(t, f0, dur, f1, method="linear")
    if amp_env:
        y *= signal.windows.tukey(n, 0.15)
    return y

# ------------------------------------------------------------------ harmony map
# Base key A natural minor; lift sections transpose +3 (C minor). Pad/arp/bass
# voicings carry pitch-class sets so the grid-sparkle stays in-chord.
def chord(root, third, fifth, arp, pcs):
    return dict(root=root, pad=[root + 12, third + 12, fifth + 12],
                arp=arp, pcs=set(pcs))

CH = {
    "Am": dict(root=45, pad=[57, 60, 64], arp=[69, 72, 76, 81], pcs={9, 0, 4}),
    "F":  dict(root=41, pad=[53, 57, 60], arp=[65, 69, 72, 77], pcs={5, 9, 0}),
    "C":  dict(root=48, pad=[55, 60, 64], arp=[67, 72, 76, 79], pcs={0, 4, 7}),
    "G":  dict(root=43, pad=[55, 59, 62], arp=[67, 71, 74, 79], pcs={7, 11, 2}),
    "Dm": dict(root=50, pad=[57, 62, 65], arp=[69, 74, 77, 81], pcs={2, 5, 9}),
    "E":  dict(root=52, pad=[56, 59, 64], arp=[68, 71, 76, 80], pcs={4, 8, 11}),
}
# transposed (+3) chords for the Cm lift
def transpose_chord(c, semis):
    return dict(root=c["root"] + semis,
                pad=[m + semis for m in c["pad"]],
                arp=[m + semis for m in c["arp"]],
                pcs={(p + semis) % 12 for p in c["pcs"]})
CH["Cm"] = transpose_chord(CH["Am"], 3)
CH["Ab"] = transpose_chord(CH["F"], 3)
CH["Eb"] = transpose_chord(CH["C"], 3)
CH["Bb"] = transpose_chord(CH["G"], 3)

# A-section progression: Am F C G (2 bars each) — hopeful natural-minor loop.
A_PROG = ["Am", "Am", "F", "F", "C", "C", "G", "G"]
# B-section: Dm G C Am ... E (the dominant-of-Am turnaround, the 'question')
B_PROG = ["Dm", "Dm", "G", "G", "C", "Am", "E", "E"]
# lift (4 bars): F G | (V/Cm) -> Bb pivot up to Cm
LIFT_PROG = ["F", "G", "Bb", "Bb"]
# Cm theme: Cm Ab Eb Bb (the A-prog shifted up a minor third)
ACM_PROG = ["Cm", "Cm", "Ab", "Ab", "Eb", "Eb", "Bb", "Bb"]

chord_of_bar = {}
def fill_prog(start, prog):
    for i, c in enumerate(prog):
        chord_of_bar[start + i] = c

for name in ("A1", "A2", "A2b", "A3", "A3b", "A4"):
    fill_prog(SEC[name][0], A_PROG)
for name in ("B", "B2"):
    fill_prog(SEC[name][0], B_PROG)
fill_prog(SEC["lift"][0], LIFT_PROG)
for name in ("Acm1", "Acm2"):
    fill_prog(SEC[name][0], ACM_PROG)
# intro/outro on the tonic
for b in range(*[SEC["intro"][0], SEC["intro"][0] + SEC["intro"][1]]):
    chord_of_bar[b] = "Am"
for b in range(SEC["outro"][0], SEC["outro"][0] + SEC["outro"][1]):
    # outro resolves Cm -> back home: Cm Cm Ab Eb | Am Am Am Am (modal mixture landing home)
    rel = b - SEC["outro"][0]
    chord_of_bar[b] = ["Cm", "Cm", "Ab", "Eb", "Am", "F", "Am", "Am"][rel]

def bar_t(b, beat=0.0):
    return b * BAR + beat * BEAT

def sec_range(name):
    s, n = SEC[name]
    return range(s, s + n)

# ------------------------------------------------------------------------ drums
def kick(dur=0.10):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 150 * np.exp(-t / 0.03) + 48
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.045)
KICK = kick()
HAT = resynth_chirp(800, 3200, 0.025) * np.exp(-np.arange(int(0.025 * SR)) / (0.008 * SR))

DRUM_START = SEC["A1"][0]                # drums enter at A1
DRUM_END = SEC["outro"][0] + 6           # thin out near the very end
for b in range(SEC["intro"][0] + 4, DRUM_END):
    full = b >= DRUM_START
    for bt in (0, 2):
        add(KICK, bar_t(b, bt), 0.34 if full else 0.20)
    if full:
        for bt in (1, 3):                                  # backbeat = real preamble rim
            add(ticks[(b + bt) % 4], bar_t(b, bt), 0.16, pan=0.15)
    # 8th-note micro-chirp hats in the busier sections
    busy = any(b in sec_range(s) for s in ("A2b", "B", "A3", "A3b", "B2", "A4", "Acm1", "Acm2"))
    if busy:
        for e in range(8):
            if e % 2 == 1:
                add(HAT, bar_t(b, e / 2), 0.045, pan=-0.3)
    # offbeat shaker swing in B sections for lift
    if any(b in sec_range(s) for s in ("B", "B2")):
        for e in (1, 3, 5, 7):
            add(shaker, bar_t(b, e / 2), 0.04, pan=0.35 * (1 if e % 4 == 1 else -1))

# authentic frame-rhythm layer: real ticks at the TRUE measured frame period.
t = bar_t(SEC["intro"][0] + 2)
side = 1
while t < bar_t(DRUM_END):
    add(ticks[int(t / FRAME_S) % 4], t, 0.10, pan=0.5 * side)
    side = -side
    t += FRAME_S

# ------------------------------------------------------------------------- bass
for b in range(DRUM_START, DRUM_END):
    ch = CH[chord_of_bar[b]]
    r = midi_f(ch["root"])
    walk = b % 4 == 3
    pat = [(0, 0.72, r), (1.0, 0.45, r), (1.75, 0.2, r), (2.0, 0.72, r),
           (3.0, 0.45, r * 2 if walk else r), (3.75, 0.2, r)]
    for (bt, dur, f) in pat:
        q = rng.integers(0, 4)
        y = chip_note(f, dur * BEAT, q) * env_adsr(int(dur * BEAT * SR), a=0.004, d=0.05, s=0.7, r=0.05)
        add(y, bar_t(b, bt), 0.20)

# -------------------------------------------------------------------- main arp
arp_updown = [0, 1, 2, 3, 2, 1]
ARP_SECTIONS = ("A1", "A2", "A2b", "B", "A3", "A3b", "B2", "A4", "Acm1", "Acm2")
for name in ARP_SECTIONS:
    for b in sec_range(name):
        ch = CH[chord_of_bar[b]]
        notes = ch["arp"]
        div = 4 if name in ("B", "B2") else 2             # 16ths in B, 8ths elsewhere
        nstep = 4 * div
        for s_ in range(nstep):
            idx = arp_updown[(b * nstep + s_) % len(arp_updown)]
            f = midi_f(notes[idx])
            q = rng.integers(0, 4)
            dur = BEAT / div * 0.92
            y = chip_note(f, dur, q) * env_adsr(int(dur * SR), a=0.003, d=0.04, s=0.55, r=0.03)
            lvl = 0.100 if div == 2 else 0.080
            add(y, bar_t(b, s_ / div), lvl, pan=0.45 * (1 if s_ % 2 else -1))

# --------------------------------------------------- grid sparkle (literal carriers)
# THE real retuned carrier grid plays a high sparkle: octave of the literal harmonics.
# Use the A-minor table in the Am-based sections; transpose +3 in the Cm sections.
def grid_freqs_for_section(name):
    if name in ("Acm1", "Acm2"):
        return [(m + 3, q * 2 ** (3 / 12)) for (m, q) in QCAR]
    return [(m, q) for (m, q) in QCAR]

SPARKLE_SECTIONS = ("A2", "A2b", "B", "A3", "A3b", "B2", "A4", "Acm1", "Acm2")
for name in SPARKLE_SECTIONS:
    gset_all = grid_freqs_for_section(name)
    for b in sec_range(name):
        ch = CH[chord_of_bar[b]]
        cset = [q for (m, q) in gset_all if (m % 12) in ch["pcs"] and 2400 < q < 6500]
        if not cset:
            cset = [q for (m, q) in gset_all if 2400 < q < 6500]
        k = 0
        for s_ in range(0, 16, 3):                         # dotted cross-rhythm
            f = cset[k % len(cset)]; k += 1
            y = pluck(f, 0.18, rng.integers(0, 4), tau=0.07)
            add(y, bar_t(b, s_ / 4), 0.040, pan=0.7 * (1 if k % 2 else -1))

# ---------------------------------------------------------------------- pad
# DQPSK-hopped sustained chord tones at the real N512 symbol rate = modem buzz.
PAD_SECTIONS = ("A1", "A2", "A2b", "B", "A3", "A3b", "B2", "A4", "lift",
                "Acm1", "Acm2", "outro")
for name in PAD_SECTIONS:
    s, n = SEC[name]
    for b in range(s, s + n, 2):
        ch = CH[chord_of_bar[b]]
        dur = min(2 * BAR, (s + n - b) * BAR)
        lvl = 0.045 if name not in ("Acm1", "Acm2", "A4") else 0.058
        for j, m in enumerate(ch["pad"]):
            y = dqpsk_tone(midi_f(m), dur) * env_adsr(int(dur * SR), a=0.12, d=0.2, s=0.9, r=0.25)
            add(y, bar_t(b), lvl, pan=(-0.5, 0.0, 0.5)[j % 3])

# -------------------------------------------------------------------- melody
# AABA hopeful theme, in MIDI relative to A minor; portamento lead. 32-beat (8-bar)
# phrases. The lead is a single voice with exponential glide + light vibrato.
MEL_A = [(0, 1.5, 81), (1.5, 0.5, 83), (2, 1, 84), (3, 1, 83), (4, 2, 81), (6, 1, 76), (7, 1, 79),
         (8, 1.5, 81), (9.5, 0.5, 81), (10, 1, 84), (11, 1, 81), (12, 2, 77), (14, 2, 76),
         (16, 1.5, 76), (17.5, 0.5, 79), (18, 1, 84), (19, 1, 79), (20, 2, 76), (22, 2, 72),
         (24, 1.5, 74), (25.5, 0.5, 71), (26, 1, 74), (27, 1, 79), (28, 3, 81), (31, 1, 79)]
# a brighter close for the final A statements: rise to the upper tonic
MEL_A_HIGH_END = [(24, 1, 79), (25, 1, 81), (26, 1, 84), (27, 1, 86), (28, 4, 88)]
# B-section lead: longer arcs that pose the 'question'
MEL_B = [(0, 3, 84), (3, 1, 86), (4, 2, 88), (6, 2, 86), (8, 3, 84), (11, 1, 81),
         (12, 2, 83), (14, 2, 79), (16, 3, 81), (19, 1, 84), (20, 2, 88), (22, 2, 84),
         (24, 2, 83), (26, 1, 79), (27, 1, 83), (28, 3, 84), (31, 1, 88)]
# B-section COUNTER-MELODY: an answering voice, lower register, fills the rests
MEL_B_COUNTER = [(2, 1, 69), (3, 1, 72), (6, 1.5, 74), (10, 1, 67), (11, 1, 71),
                 (14, 2, 72), (18, 1, 69), (19, 1, 76), (22, 1.5, 74),
                 (26, 1, 71), (27, 1, 74), (29, 2, 76)]

def render_voice(events, t0_s, level=0.16, transpose=0, glide_tau=0.030,
                 vib_hz=5.2, vib_depth=0.0018, timbre=(1.0, 0.33, 0.15)):
    """one monophonic voice w/ exponential portamento + light vibrato."""
    if not events:
        return
    end_beat = max(s + d for (s, d, _) in events) + 0.5
    n = int(end_beat * BEAT * SR)
    if n <= 0:
        return
    ftgt = np.zeros(n); amp = np.zeros(n)
    cur = midi_f(events[0][2] + transpose)
    ftgt[:] = cur
    for (s_, d_, m_) in events:
        i0, i1 = int(s_ * BEAT * SR), int((s_ + d_) * BEAT * SR)
        i1 = min(i1, n)
        if i1 <= i0:
            continue
        ftgt[i0:] = midi_f(m_ + transpose)
        a = np.ones(i1 - i0)
        na, nr = int(0.006 * SR), min(int(0.07 * SR), (i1 - i0) // 2 + 1)
        na = min(na, len(a))
        a[:na] *= np.linspace(0.2, 1, na)
        if nr > 0:
            a[-nr:] *= np.linspace(1, 0, nr)
        amp[i0:i1] = np.maximum(amp[i0:i1], a)
    alpha = 1 - np.exp(-1 / (glide_tau * SR))
    # vectorized one-pole glide via lfilter
    f = signal.lfilter([alpha], [1, -(1 - alpha)], ftgt)
    f[0] = ftgt[0]
    ph = 2 * np.pi * np.cumsum(f) / SR
    vib = vib_depth * np.sin(2 * np.pi * vib_hz * np.arange(n) / SR) * np.linspace(0, 1, n) ** 1.5
    ph = ph * (1 + vib)
    h1, h3, h5 = timbre
    y = (h1 * np.sin(ph) + h3 * np.sin(3 * ph) + h5 * np.sin(5 * ph)) * amp
    add(y, t0_s, level)

# A statements: A1 (theme, mid), A2/A2b (theme), A3/A3b (theme), A4 (high end),
# Acm1/Acm2 (theme transposed +3 = key lift).
render_voice(MEL_A, bar_t(SEC["A1"][0]), level=0.155)
render_voice(MEL_A, bar_t(SEC["A2"][0]), level=0.160)
render_voice([e for e in MEL_A if e[0] < 24] + MEL_A_HIGH_END, bar_t(SEC["A2b"][0]), level=0.165)
render_voice(MEL_B, bar_t(SEC["B"][0]), level=0.170)
render_voice(MEL_B_COUNTER, bar_t(SEC["B"][0]), level=0.105,
             glide_tau=0.018, timbre=(1.0, 0.20, 0.08))      # counter-melody, softer reedier
render_voice(MEL_A, bar_t(SEC["A3"][0]), level=0.165)
render_voice([e for e in MEL_A if e[0] < 24] + MEL_A_HIGH_END, bar_t(SEC["A3b"][0]), level=0.168)
render_voice(MEL_B, bar_t(SEC["B2"][0]), level=0.172)
render_voice([(s, d, m + 5) for (s, d, m) in MEL_B_COUNTER], bar_t(SEC["B2"][0]),  # counter rises
             level=0.110, glide_tau=0.018, timbre=(1.0, 0.20, 0.08))
render_voice([e for e in MEL_A if e[0] < 24] + MEL_A_HIGH_END, bar_t(SEC["A4"][0]), level=0.170)
# KEY LIFT: theme +3 semitones (Cm) for the two climactic statements
render_voice(MEL_A, bar_t(SEC["Acm1"][0]), level=0.175, transpose=3)
render_voice([e for e in MEL_A if e[0] < 24] + MEL_A_HIGH_END, bar_t(SEC["Acm2"][0]),
             level=0.178, transpose=3)

# --------------------------------------------------------- chirp transitions
def into(name, amp=0.30, pan=0.0, down=False):
    c = chirp_dn if down else chirp_up
    add(c, bar_t(SEC[name][0]) - 0.22, amp, pan=pan)

into("A1", 0.30, -0.2)
into("A2", 0.30, 0.2)
into("A2b", 0.28, -0.2)
into("B", 0.34, -0.2)
add(crash_short_L, bar_t(SEC["B"][0]), 0.22, pan=-0.7)
add(crash_short_R, bar_t(SEC["B"][0]), 0.22, pan=0.7)
into("A3", 0.30, 0.2)
into("A3b", 0.28, 0.2)
into("B2", 0.32, -0.2)
add(crash_short_L, bar_t(SEC["B2"][0]), 0.20, pan=-0.6)
add(crash_short_R, bar_t(SEC["B2"][0]), 0.20, pan=0.6)
into("A4", 0.30, 0.0)

# the LIFT: stretched 500->5000 resynth riser builds across the 4 lift bars, then
# the real up-chirp + Schroeder splash detonates the key change into Cm.
lift_dur = 4 * BAR
riser = resynth_chirp(500, 5000, lift_dur)
riser *= np.linspace(0.10, 1.0, len(riser)) ** 2
add(riser, bar_t(SEC["lift"][0]), 0.16)
# accelerating preamble ticks during the lift (tension)
tk = bar_t(SEC["lift"][0])
gap = 0.55 * BEAT
i = 0
while tk < bar_t(SEC["Acm1"][0]) - 0.05:
    add(ticks[i % 4], tk, 0.10 + 0.06 * (i / 12.0), pan=0.4 * (1 if i % 2 else -1))
    gap *= 0.90
    tk += max(gap, 0.06)
    i += 1
add(chirp_up, bar_t(SEC["Acm1"][0]) - 0.20, 0.42, pan=0.0)        # the key-change hit
add(crashL, bar_t(SEC["Acm1"][0]), 0.30, pan=-0.7)
add(crashR, bar_t(SEC["Acm1"][0]), 0.30, pan=0.7)
into("Acm2", 0.28, 0.0)

# outro: down-chirp farewell + Schroeder swell, resolves home to Am
add(chirp_dn, bar_t(SEC["outro"][0]) - 0.22, 0.32)
add(crash_short_L, bar_t(SEC["outro"][0]), 0.16, pan=-0.5)
add(crash_short_R, bar_t(SEC["outro"][0]), 0.16, pan=0.5)
# the homecoming: as the harmony returns Cm->Am, a final down-chirp signs off
home_bar = SEC["outro"][0] + 4
add(chirp_dn, bar_t(home_bar) - 0.20, 0.26, pan=0.0)
add(chirp_dn, bar_t(N_BARS - 2), 0.30)
add(resynth_chirp(5000, 500, 2.5) * np.exp(-np.arange(int(2.5 * SR)) / (1.0 * SR)),
    bar_t(N_BARS - 2) + 0.25, 0.12)

# ------------------------------------------------------------------ d2x bed
def add_bed(t0, dur, lvl):
    t = t0
    while t < t0 + dur:
        seg = bed_loop[: int(min(len(bed_loop), (t0 + dur - t) * SR))]
        add(seg, t, lvl, pan=0.0)
        t += len(bed_loop) / SR
add_bed(bar_t(SEC["intro"][0]), SEC["intro"][1] * BAR, 0.050)         # intro data hiss
add_bed(bar_t(SEC["B"][0]), SEC["B"][1] * BAR, 0.032)                 # under B
add_bed(bar_t(SEC["B2"][0]), SEC["B2"][1] * BAR, 0.032)
add_bed(bar_t(SEC["lift"][0]), SEC["lift"][1] * BAR, 0.045)           # lift tension
add_bed(bar_t(SEC["outro"][0]), SEC["outro"][1] * BAR, 0.045)        # outro

# intro grid-sparkle 'waking up' — sparse, getting denser, on Am
for b in sec_range("intro"):
    if b < SEC["intro"][0] + 2:
        continue
    ch = CH["Am"]
    cset = [q for (m, q) in QCAR if (m % 12) in ch["pcs"] and 2400 < q < 6500]
    density = (b - (SEC["intro"][0] + 2)) + 1
    for k in range(density):
        s_ = (k * 5) % 16
        f = cset[k % len(cset)]
        y = pluck(f, 0.22, rng.integers(0, 4), tau=0.10)
        add(y, bar_t(b, s_ / 4), 0.045, pan=0.7 * (1 if k % 2 else -1))

# outro thinning arp (quarters, Am, fading)
for b in range(SEC["outro"][0] + 4, N_BARS - 1):
    ch = CH[chord_of_bar[b]]
    for bt in range(4):
        f = midi_f(ch["arp"][arp_updown[(b * 4 + bt) % 6]])
        y = pluck(f, 0.5, rng.integers(0, 4), tau=0.22)
        add(y, bar_t(b, bt), 0.07, pan=0.3 * (1 if bt % 2 else -1))

# --------------------------------------------------------------- stereo delay
d = int(0.75 * BEAT * SR)                                # dotted-8th cross-feed echo
echoL = np.zeros(N); echoR = np.zeros(N)
echoL[d:] = 0.22 * mixR[:-d]
echoR[d:] = 0.22 * mixL[:-d]
mixL += echoL
mixR += echoR

# -------------------------------------------------------------------- master
mix = np.stack([mixL, mixR], axis=1)
assert np.all(np.isfinite(mix)), "non-finite samples in mix"
TARGET_RMS_DB = -14.8
PEAK_LIM = 10 ** (-1.05 / 20)                            # ~0.886
for _ in range(3):
    rms = np.sqrt(np.mean(mix ** 2))
    mix *= 10 ** (TARGET_RMS_DB / 20) / (rms + 1e-12)
    mix = np.tanh(mix / PEAK_LIM) * PEAK_LIM             # soft limit, peak < -1 dBFS

nfi, nfo = int(2.0 * SR), int(4.0 * SR)
mix[:nfi] *= np.linspace(0, 1, nfi)[:, None] ** 1.5
mix[-nfo:] *= np.linspace(1, 0, nfo)[:, None] ** 1.5

sf.write(OUT, mix.astype(np.float32), SR, subtype="PCM_16")

# ------------------------------------------------------------------------ QA
peak = np.max(np.abs(mix))
rms = np.sqrt(np.mean(mix ** 2))
dur = len(mix) / SR
print(f"\nQA: duration = {dur:.2f} s | peak = {20*np.log10(peak):+.2f} dBFS | "
      f"RMS = {20*np.log10(rms):+.2f} dBFS")
assert peak <= 10 ** (-1.0 / 20) + 1e-4, "clipping margin violated"
assert 215 <= dur <= 245, f"duration {dur:.1f} out of range"

mono = mix.mean(axis=1)
print("10-band spectral balance (dB rel total):")
edges = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 24000]
fr, Pxx = signal.welch(mono, SR, nperseg=8192)
tot = np.trapezoid(Pxx, fr)
band_db = []
for i in range(10):
    m = (fr >= edges[i]) & (fr < edges[i + 1])
    p = np.trapezoid(Pxx[m], fr[m]) / tot
    band_db.append(10 * np.log10(p + 1e-12))
    print(f"  {edges[i]:>5}-{edges[i+1]:>5} Hz: {band_db[-1]:+6.1f} dB")

f_, t_, S = signal.stft(mono, SR, nperseg=1024, noverlap=512)
mag = np.abs(S)
flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
flux = flux / (flux.max() + 1e-12)
thr = np.median(flux) * 1.6
pk, _ = signal.find_peaks(flux, height=thr, distance=int(0.09 / (t_[1] - t_[0])))
onset_rate = len(pk) / dur
print(f"onset rate = {onset_rate:.2f} onsets/s ({len(pk)} onsets) — "
      f"expect ~3-7/s for an 8th/16th arp + melody at {BPM:.0f} BPM")

# intent checks: clear melodic MID-band energy (250 Hz - 4 kHz dominant), moderate onsets
mid = band_db[4] + band_db[5] + band_db[6] + band_db[7]   # 500..8000 group incl mids
low = band_db[0] + band_db[1] + band_db[2]
print(f"mid-band (500-8k) group = {mid:+.1f} dB | low (<250) group = {low:+.1f} dB")
print(f"INTENT CHECK: melodic mid-band present = {band_db[5] > -18 and band_db[6] > -20} ; "
      f"moderate onset rate (2-9/s) = {2 <= onset_rate <= 9}")
print(f"\nwrote {OUT}")
