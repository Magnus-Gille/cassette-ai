#!/usr/bin/env python3
"""
B-side remix — 'melodic' direction (chiptune).

Quotes the real cassette-modem signal:
  * REAL sampled global chirps (up @ 20.863 s, down @ 380.624 s of tape10_run1.wav)
    used as phrase transitions, plus a stretched resynthesized 500->5000 Hz riser.
  * REAL sampled frame-preamble ticks (capture 46.863 s + k*1.372896 s) as rim-click
    percussion; an authentic frame-rhythm layer ticks at the true measured N512
    frame period (1.372896 s) which is locked to the musical grid: BPM is chosen so
    one frame = exactly 2.5 beats  ->  BPM = 60*2.5/1.372896 = 109.26 (~110 as asked).
  * REAL Schroeder multitone splash (capture 21.96/25.97 s) as section crash.
  * REAL d2x DQPSK texture (capture ~206 s) as a band-passed bed.
  * The actual N512 carrier grid (375 Hz harmonics, 750..9000 Hz) retuned: every
    carrier quantized to the nearest A-natural-minor pitch; the literal retuned
    carriers play a high 'grid sparkle' arp; their octave-folded pitches drive the
    main arp/bass/pad. DQPSK-style 90-degree phase hops at the real N512 symbol
    rate (2048 samples = 42.7 ms) buzz the pad; every arp note starts on a random
    quadrant phase (0/90/180/270) like a DQPSK symbol.

Form: Intro(4) A1(8) A2(8) B(8) A3(8) Outro(8) = 44 bars @ 109.26 BPM ~ 96.7 s.
Chords A: Am F C G (2 bars each); B: F G Am G. Melody = one voice w/ portamento.

Output: bside_melodic.wav  (stereo 48 kHz 16-bit, peak <= -1 dBFS, RMS ~ -15 dBFS,
2 s fade-in / 4 s fade-out). Self-QA prints peak/RMS/duration, 10-band spectral
balance, onset rate.
"""
import json
import numpy as np
import soundfile as sf
from scipy import signal

SEED = 20260612
rng = np.random.default_rng(SEED)
print(f"seed = {SEED}")

SR = 48000
BASE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2"
CAPTURE = f"{BASE}/captures/tape10_run1.wav"
OUT = f"{BASE}/bside_remix/bside_melodic.wav"

# ----------------------------------------------------------------- timing grid
FRAME_S = 1.372896                  # measured N512 frame period in the capture
BEAT = FRAME_S / 2.5                # frame = exactly 2.5 beats
BPM = 60.0 / BEAT
BAR = 4 * BEAT
N_BARS = 44
TAIL = 3.0
print(f"BPM = {BPM:.3f} (frame {FRAME_S:.6f} s = 2.5 beats), bar = {BAR:.4f} s")

DUR = N_BARS * BAR + TAIL
N = int(DUR * SR)
mixL = np.zeros(N)
mixR = np.zeros(N)

def add(sig, t_s, amp=1.0, pan=0.0):
    """pan in [-1, 1]"""
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
    e = np.full(n, s)
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
    t *= np.exp(-np.arange(len(t)) / (0.022 * SR))     # snap it into a rim click
    t[: int(0.001 * SR)] *= np.linspace(0, 1, int(0.001 * SR))
    ticks.append(norm(t))

# real global chirps
chirp_up = norm(hp(grab(20.8628 - 0.01, 0.24), 300))
chirp_dn = norm(hp(grab(380.6237 - 0.01, 0.24), 300))
for c in (chirp_up, chirp_dn):
    c[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    c[-int(0.02 * SR):] *= np.linspace(1, 0, int(0.02 * SR))

# Schroeder multitone splash -> crash (two reps = decorrelated L/R)
def crash_sample(t0):
    c = hp(grab(t0, 1.6), 300)
    c *= np.exp(-np.arange(len(c)) / (0.45 * SR))
    c[: int(0.003 * SR)] *= np.linspace(0, 1, int(0.003 * SR))
    return norm(c)
crashL = crash_sample(21.98)
crashR = crash_sample(25.99)

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

def quantize_am(freq):
    m = 69 + 12 * np.log2(freq / 440.0)
    cands = np.arange(int(m) - 2, int(m) + 3)
    cands = [c for c in cands if c % 12 in A_MINOR_PC]
    best = min(cands, key=lambda c: abs(c - m))
    return best, 440.0 * 2 ** ((best - 69) / 12)

QCAR = [quantize_am(f) for f in N512]                  # (midi, freq) per carrier
print("carrier grid -> A natural minor:")
for f, (m, q) in zip(N512, QCAR):
    pass  # table kept in script spirit; printed compactly below
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
    if freq * 3 < 14000: y = y + 0.30 * np.sin(3 * ph)
    if freq * 5 < 14000: y = y + 0.12 * np.sin(5 * ph)
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

# ------------------------------------------------------------------ song layout
# sections (bar index): intro 0-3, A1 4-11, A2 12-19, B 20-27, A3 28-35, outro 36-43
CH = {
    "Am": dict(root=45, pad=[57, 60, 64], arp=[69, 72, 76, 81], pcs={9, 0, 4}),
    "F":  dict(root=41, pad=[53, 57, 60], arp=[65, 69, 72, 77], pcs={5, 9, 0}),
    "C":  dict(root=48, pad=[55, 60, 64], arp=[67, 72, 76, 79], pcs={0, 4, 7}),
    "G":  dict(root=43, pad=[55, 59, 62], arp=[67, 71, 74, 79], pcs={7, 11, 2}),
}
A_PROG = ["Am", "Am", "F", "F", "C", "C", "G", "G"]
B_PROG = ["F", "F", "G", "G", "Am", "Am", "G", "G"]
chord_of_bar = {}
for i, c in enumerate(A_PROG):
    chord_of_bar[4 + i] = c; chord_of_bar[12 + i] = c; chord_of_bar[28 + i] = c
for i, c in enumerate(B_PROG):
    chord_of_bar[20 + i] = c
for b in range(0, 4):
    chord_of_bar[b] = "Am"
for b in range(36, 44):
    chord_of_bar[b] = "Am" if b not in (42, 43) else "Am"

def bar_t(b, beat=0.0):
    return b * BAR + beat * BEAT

# ------------------------------------------------------------------------ drums
kick_w = None
def kick(dur=0.10):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 150 * np.exp(-t / 0.03) + 48
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.045)

KICK = kick()
HAT = resynth_chirp(800, 3200, 0.025) * np.exp(-np.arange(int(0.025 * SR)) / (0.008 * SR))

for b in range(2, 42):
    sec_drums = b >= 4
    for bt in (0, 2):
        add(KICK, bar_t(b, bt), 0.34)
    if sec_drums:
        for bt in (1, 3):                               # backbeat = real preamble rim
            add(ticks[(b + bt) % 4], bar_t(b, bt), 0.16, pan=0.15)
    if 12 <= b < 36:                                    # 8th-note micro-chirp hats
        for e in range(8):
            if e % 2 == 1:
                add(HAT, bar_t(b, e / 2), 0.05, pan=-0.3)

# authentic frame-rhythm layer: real ticks at the TRUE measured frame period,
# which the BPM choice locks to every 2.5 beats of the grid.
t = bar_t(2)
side = 1
while t < bar_t(43):
    add(ticks[int(t / FRAME_S) % 4], t, 0.11, pan=0.5 * side)
    side = -side
    t += FRAME_S

# ------------------------------------------------------------------------- bass
for b in range(2, 42):
    ch = CH[chord_of_bar[b]]
    r = midi_f(ch["root"])
    pat = [(0, 0.72, r), (1.0, 0.45, r), (1.75, 0.2, r), (2.0, 0.72, r),
           (3.0, 0.45, r * 2 if b % 4 == 3 else r), (3.75, 0.2, r)]
    for (bt, dur, f) in pat:
        q = rng.integers(0, 4)
        y = chip_note(f, dur * BEAT, q) * env_adsr(int(dur * BEAT * SR), a=0.004, d=0.05, s=0.7, r=0.05)
        add(y, bar_t(b, bt), 0.20)

# -------------------------------------------------------------------- main arp
# octave-folded carrier pitches; 8ths in A sections, 16ths in B; DQPSK quadrant
arp_updown = [0, 1, 2, 3, 2, 1]
for b in range(4, 40):
    ch = CH[chord_of_bar[b]]
    notes = ch["arp"]
    div = 4 if 20 <= b < 28 else 2                       # 16ths in B
    nstep = 4 * div
    for s_ in range(nstep):
        idx = arp_updown[(b * nstep + s_) % len(arp_updown)]
        f = midi_f(notes[idx])
        q = rng.integers(0, 4)
        dur = BEAT / div * 0.92
        y = chip_note(f, dur, q) * env_adsr(int(dur * SR), a=0.003, d=0.04, s=0.55, r=0.03)
        lvl = 0.105 if div == 2 else 0.085
        add(y, bar_t(b, s_ / div), lvl, pan=0.45 * (1 if s_ % 2 else -1))

# --------------------------------------------------- grid sparkle (literal carriers)
# the actual retuned carrier grid, dotted-8th cross rhythm, chord-filtered
for b in range(12, 40):
    ch = CH[chord_of_bar[b]]
    cset = [q for (m, q) in QCAR if m % 12 in ch["pcs"] and 2400 < q < 6000]
    if not cset:
        cset = [q for (m, q) in QCAR if 2400 < q < 6000]
    k = 0
    for s_ in range(0, 16, 3):                           # every 3rd 16th
        f = cset[k % len(cset)]; k += 1
        y = pluck(f, 0.18, rng.integers(0, 4), tau=0.07)
        add(y, bar_t(b, s_ / 4), 0.040, pan=0.7 * (1 if k % 2 else -1))

# ---------------------------------------------------------------------- pad
# DQPSK-hopped sustained chord tones at the real N512 symbol rate = modem buzz
for b in range(4, 44, 2):
    ch = CH[chord_of_bar[b]]
    dur = 2 * BAR
    lvl = 0.045 if b < 36 else 0.055
    for j, m in enumerate(ch["pad"]):
        y = dqpsk_tone(midi_f(m), dur) * env_adsr(int(dur * SR), a=0.12, d=0.2, s=0.9, r=0.25)
        add(y, bar_t(b), lvl, pan=(-0.5, 0.0, 0.5)[j % 3])

# -------------------------------------------------------------------- melody
MEL_A = [(0, 1.5, 81), (1.5, 0.5, 83), (2, 1, 84), (3, 1, 83), (4, 2, 81), (6, 1, 76), (7, 1, 79),
         (8, 1.5, 81), (9.5, 0.5, 81), (10, 1, 84), (11, 1, 81), (12, 2, 77), (14, 2, 76),
         (16, 1.5, 76), (17.5, 0.5, 79), (18, 1, 84), (19, 1, 79), (20, 2, 76), (22, 2, 72),
         (24, 1.5, 74), (25.5, 0.5, 71), (26, 1, 74), (27, 1, 79), (28, 3, 81), (31, 1, 79)]
MEL_A3_END = [(24, 1, 79), (25, 1, 76), (26, 1, 74), (27, 1, 71), (28, 4, 69)]
MEL_B = [(0, 3, 84), (3, 1, 86), (4, 2, 88), (6, 2, 86), (8, 3, 84), (11, 1, 81),
         (12, 2, 83), (14, 2, 79), (16, 3, 81), (19, 1, 84), (20, 2, 88), (22, 2, 84),
         (24, 2, 83), (26, 1, 79), (27, 1, 83), (28, 3, 81)]

def render_melody(events, t0_s, level=0.16):
    """one voice, exponential portamento between notes (tau 30 ms)."""
    if not events:
        return
    end_beat = max(s + d for (s, d, _) in events) + 0.5
    n = int(end_beat * BEAT * SR)
    ftgt = np.zeros(n); amp = np.zeros(n)
    cur = midi_f(events[0][2])
    ftgt[:] = cur
    for (s_, d_, m_) in events:
        i0, i1 = int(s_ * BEAT * SR), int((s_ + d_) * BEAT * SR)
        ftgt[i0:] = midi_f(m_)
        a = np.ones(i1 - i0)
        na, nr = int(0.006 * SR), int(0.07 * SR)
        a[:na] *= np.linspace(0.2, 1, na)
        a[-nr:] *= np.linspace(1, 0, nr)
        amp[i0:i1] = np.maximum(amp[i0:i1], a)
    alpha = 1 - np.exp(-1 / (0.030 * SR))
    f = np.empty(n); acc = ftgt[0]
    for i in range(n):                                   # one-pole glide
        acc += (ftgt[i] - acc) * alpha
        f[i] = acc
    ph = 2 * np.pi * np.cumsum(f) / SR
    vib = 0.0035 * np.sin(2 * np.pi * 5.2 * np.arange(n) / SR) * np.linspace(0, 1, n) ** 0.3
    ph = ph * (1 + vib)
    y = (np.sin(ph) + 0.33 * np.sin(3 * ph) + 0.15 * np.sin(5 * ph)) * amp
    add(y, t0_s, level)

render_melody(MEL_A, bar_t(12))
render_melody(MEL_B, bar_t(20), level=0.17)
render_melody([e for e in MEL_A if e[0] < 24] + MEL_A3_END, bar_t(28))

# --------------------------------------------------------- chirp transitions
add(chirp_up, bar_t(4) - 0.22, 0.30, pan=-0.2)           # into A1
add(chirp_up, bar_t(12) - 0.22, 0.30, pan=0.2)           # into A2
add(resynth_chirp(500, 5000, 4 * BEAT) * np.linspace(0.15, 1, int(4 * BEAT * SR)) ** 2,
    bar_t(19), 0.16)                                     # stretched riser into B
add(chirp_up, bar_t(20) - 0.22, 0.34, pan=-0.2)
add(crashL, bar_t(20), 0.26, pan=-0.7)                   # real Schroeder splash
add(crashR, bar_t(20), 0.26, pan=0.7)
add(chirp_up, bar_t(28) - 0.22, 0.30, pan=0.2)           # into A3
add(chirp_dn, bar_t(36) - 0.22, 0.30)                    # into outro
add(crashL, bar_t(36), 0.18, pan=-0.5)
add(chirp_dn, bar_t(42), 0.30)                           # final down-chirp
add(resynth_chirp(5000, 500, 2.5) * np.exp(-np.arange(int(2.5 * SR)) / (1.0 * SR)),
    bar_t(42) + 0.25, 0.12)

# ------------------------------------------------------------------ d2x bed
def add_bed(t0, dur, lvl):
    t = t0
    while t < t0 + dur:
        seg = bed_loop[: int(min(len(bed_loop), (t0 + dur - t) * SR))]
        add(seg, t, lvl, pan=0.0)
        t += len(bed_loop) / SR
add_bed(bar_t(0), bar_t(4) - bar_t(0), 0.050)            # intro: data hiss fades in w/ master fade
add_bed(bar_t(20), bar_t(28) - bar_t(20), 0.035)         # B section
add_bed(bar_t(36), bar_t(44) - bar_t(36), 0.045)         # outro

# outro thinning arp (quarters on Am)
for b in range(40, 43):
    ch = CH["Am"]
    for bt in range(4):
        f = midi_f(ch["arp"][arp_updown[(b * 4 + bt) % 6]])
        y = pluck(f, 0.5, rng.integers(0, 4), tau=0.22)
        add(y, bar_t(b, bt), 0.07, pan=0.3 * (1 if bt % 2 else -1))

# --------------------------------------------------------------- stereo delay
d = int(0.75 * BEAT * SR)                                # dotted-8th cross-feed echo
mixL[d:] += 0.22 * mixR[:-d].copy()
mixR[d:] += 0.22 * mixL[:-d].copy()

# -------------------------------------------------------------------- master
mix = np.stack([mixL, mixR], axis=1)
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
assert 90 <= dur <= 150, "duration out of range"

mono = mix.mean(axis=1)
print("10-band spectral balance (dB rel total):")
edges = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 24000]
fr, Pxx = signal.welch(mono, SR, nperseg=8192)
tot = np.trapezoid(Pxx, fr)
for i in range(10):
    m = (fr >= edges[i]) & (fr < edges[i + 1])
    p = np.trapezoid(Pxx[m], fr[m]) / tot
    print(f"  {edges[i]:>5}-{edges[i+1]:>5} Hz: {10*np.log10(p+1e-12):+6.1f} dB")

f_, t_, S = signal.stft(mono, SR, nperseg=1024, noverlap=512)
mag = np.abs(S)
flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
flux = flux / (flux.max() + 1e-12)
thr = np.median(flux) * 1.6
pk, _ = signal.find_peaks(flux, height=thr, distance=int(0.09 / (t_[1] - t_[0])))
print(f"onset rate = {len(pk)/dur:.2f} onsets/s ({len(pk)} onsets) — "
      f"expect ~3-6/s for an 8th/16th-note chiptune arp at {BPM:.0f} BPM")
print(f"\nwrote {OUT}")
