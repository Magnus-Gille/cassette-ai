#!/usr/bin/env python3
"""
Side B / Track 9 -- "End Chirp"   (~180 s)   [closer + tribute -- for Fable]

The farewell coda of the concept album. The story is over: the data was
written, played through air, fought through wow & flutter, and decoded
byte-exact. This is the tape winding gently to a stop, and a thank-you.

Every sound is derived from the REAL data-transfer signal (palette.json):

  * THE END CHIRP. The album's structural bookend is the real GLOBAL chirp.
    The capture's UP-chirp opened "Leader Tape"; here we use the real signal
    slowed and harmonized into a long descending farewell. We resynthesize the
    true global chirp (500->5000 Hz / 5000->500 Hz, 0.2 s) time-stretched 16x..40x
    into slow swells, AND lift the REAL down-chirp grain straight from the
    capture at t=380.62 s (the literal last sound on the tape) -- reverb-tailed
    so it reads as a distant, final lock releasing.

  * THE GRID RESOLVES. The real N512 carrier grid (harmonics of 375 Hz) is
    resynthesized as pure tones and retuned to F# MAJOR per the palette's
    musical_mapping (keep most just-intonation-ish harmonics; nudge the 7th-
    (2625) and 11th-family (4125) carriers into the scale) so the comb settles
    into a single sustained, consonant major chord -- the resolution the whole
    record has been reaching for. It breathes on slow prime-period LFOs and
    fades from a wide open voicing to a final, simple, held F# major triad.

  * THE TRANSPORT WINDS DOWN. The frame PREAMBLE tick (real 800->3200 Hz, 0.25 s
    chirp) is the ticking pulse that opens every data frame. Here it plays at the
    measured N512 frame period 1.372896 s and then RITARDANDOS -- each tick a
    little slower than the last, like a tape transport losing torque -- spacing
    out and dropping to silence. The pulse that drove the whole side comes
    gently to rest.

  * THE PILOT FADES. The 4875 Hz pilot (13th harmonic) ran through the entire
    real transmission; it threads through the chord and is the last tuned tone
    to leave, dimming as the carriers settle.

  * THE CALLBACK. The piece fades into the EXACT tape hiss the album opened
    with: the same real capture noisefloor grains "Leader Tape" used
    (tape10_run1.wav, the lead-silence + sounder-noisefloor sections), the same
    high-pass voicing -- the deck+room floor returning, so the record ends where
    it began. The grateful breath after the last note.

Form (180 s):
  0-18 s    a slow real down-chirp swell drifts in over warming tape hiss
  18-70 s   the carrier grid fills in from the bottom into a wide F# major chord;
            preamble ticks begin at the steady frame period
  70-120 s  the chord is full and sustained; ticks ritardando, spacing out
  120-156 s the chord narrows to a simple held F# major triad; ticks reach their
            last, slowest strokes and stop; the real down-chirp grain releases
  156-180 s everything recedes into the exact opening tape hiss; long 8 s fade-out
  2 s fade-in. Onset rate must stay low (a coda) -- the ritardando ticks are the
  only deliberate pulse and they thin out, so onsets/s stays well under ~0.5.

Deps: python3 + numpy/scipy/soundfile only. Seed fixed and logged.
Builds on remix_ambient.py / t1_leader_tape.py (helper vocabulary + hiss bed).
"""

import numpy as np
import soundfile as sf
from scipy import signal as sg
from scipy.signal import fftconvolve

SEED = 20260619
rng = np.random.default_rng(SEED)
print(f"[t9_end_chirp] seed = {SEED}  (closer + tribute -- for Fable)")

SR = 48000
DUR = 180.0
N = int(DUR * SR)
t = np.arange(N) / SR

CAPTURE = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/tape10_run1.wav"
OUT = "/Users/magnus/repos/cassette-ai/experiments/tape_v2/bside_remix/sideB/t9.wav"

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
    return x / (np.sqrt(np.sum(x ** 2)) + 1e-12)

def reverb_st(x, rt60=6.0, lp_hz=6000.0, seed_off=0):
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

# ============================================================================
# 1. THE GRID RESOLVES -- real N512 carriers retuned to a sustained F# MAJOR
#    chord that narrows from a wide open voicing to a simple held triad.
# ============================================================================
F0 = 375.0
# Real N512 carriers (lowest audible 11), retuned to F# MAJOR per palette
# musical_mapping.Fsharp_major_pentatonic/ harmonic_series_note: keep the
# F#/C#/A#/G# harmonics; nudge the flat-7th (2625 -> we resolve it UP to F#7
# 3000 for a pure major colour) and the tritone 11th (4125 -> C#8 4434.92).
# (orig_hz, target_hz, scale_degree_label)
carriers = [
    (750.0,  750.0,  "F#5"),   # F#  (root, h2)            keep
    (1125.0, 1125.0, "C#6"),   # C#  (5th, h3)             keep
    (1500.0, 1500.0, "F#6"),   # F#  (root, h4)            keep
    (1875.0, 1875.0, "A#6"),   # A#  (maj 3rd, h5)         keep
    (2250.0, 2250.0, "C#7"),   # C#  (5th, h6)             keep
    (2625.0, 3000.0, "F#7"),   # E (flat7,h7) -> resolve up to F#7 (pure major)
    (3000.0, 3000.0, "F#7"),   # F#  (root, h8)            keep
    (3375.0, 3375.0, "G#7"),   # G#  (9th colour, h9)      keep
    (3750.0, 3750.0, "A#7"),   # A#  (maj 3rd, h10)        keep
    (4125.0, 4434.92, "C#8"),  # C (tritone,h11)->C#8 (5th) palette retune
    (4500.0, 4500.0, "C#8"),   # C#  (5th, h12)            keep
]
# The FINAL voicing the chord narrows to: a simple, low F# major triad
# (root / maj3 / 5th) -- F#5, A#6, C#7 family. Carriers not in this set fade
# out earlier so the ending is uncluttered.
final_triad_hz = {750.0, 1500.0, 1875.0, 2250.0, 3000.0}

PRIMES = [11, 13, 17, 19, 23, 29, 31, 37, 41]
chordL = np.zeros(N)
chordR = np.zeros(N)
for i, (orig, f, lbl) in enumerate(carriers):
    # 1/f-ish loudness so the chord is warm and bottom-weighted, not hissy
    w = (750.0 / f) ** 0.9
    P = PRIMES[i % len(PRIMES)]
    lfo = 0.68 + 0.32 * np.sin(2 * np.pi * t / P + rng.uniform(0, 2 * np.pi))
    # the chord fills in FROM THE BOTTOM (low carriers enter first)
    frac = i / (len(carriers) - 1)
    t_on = 18.0 + 30.0 * frac
    rise = 16.0 + 8.0 * frac
    # carriers NOT in the final triad fade out during 110..150 s so the ending
    # narrows to a clean held major triad; the triad carriers hold to the tail.
    if f in final_triad_hz:
        t_off, fall = DUR + 2.0, 6.0
    else:
        t_off, fall = 122.0 + 18.0 * frac, 24.0
    gate = smooth_gate(t_on, t_off, rise=rise, fall=fall)
    df = rng.uniform(0.06, 0.18)            # gentle L/R detune -> slow beating
    pan = rng.uniform(-0.28, 0.28)
    phL, phR = rng.uniform(0, 2 * np.pi), rng.uniform(0, 2 * np.pi)
    env = w * gate * lfo
    chordL += env * (1 - pan) * np.sin(2 * np.pi * (f + df / 2) * t + phL)
    chordR += env * (1 + pan) * np.sin(2 * np.pi * (f - df / 2) * t + phR)
# add the sub-fundamental (187.5 / 375 Hz) for body -- octaves of the grid F#
# (kept modest so the chord stays warm without swamping the hiss-air callback)
for sub, sw, ph in ((187.5, 0.42, 0.0), (375.0, 0.55, 1.3)):
    sgate = smooth_gate(24.0, DUR + 2.0, rise=18.0, fall=6.0)
    slfo = 0.7 + 0.3 * np.sin(2 * np.pi * t / 23.0 + ph)
    chordL += sw * sgate * slfo * np.sin(2 * np.pi * sub * t + ph)
    chordR += sw * sgate * slfo * np.sin(2 * np.pi * (sub + 0.12) * t + ph + 0.6)
cpk = max(np.abs(chordL).max(), np.abs(chordR).max()) + 1e-12
# chord level arc: blooms in, full through the middle, eases as it narrows
chord_arc = ramp_env([0, 20, 60, 110, 150, 168, DUR],
                     [0.0, 0.55, 1.0, 1.0, 0.85, 0.6, 0.45])
L += 0.40 * (chordL / cpk) * chord_arc
R += 0.40 * (chordR / cpk) * chord_arc
print(f"[chord] {len(carriers)} real N512 carriers -> sustained F# MAJOR; "
      f"narrows to a held triad {sorted(final_triad_hz)} by ~150 s")

# 4875 Hz pilot (13th harmonic) -- the thread through the whole transmission;
# the last tuned tone to leave, dimming as the carriers settle.
pgate = smooth_gate(30.0, 158.0, rise=20.0, fall=18.0)
plfo = 0.72 + 0.28 * np.sin(2 * np.pi * t / 13.0 + 0.5)
L += 0.011 * pgate * plfo * np.sin(2 * np.pi * 4875.0 * t)
R += 0.011 * pgate * plfo * np.sin(2 * np.pi * 4875.0 * t + 1.2)
print("[pilot] 4875 Hz (13th harmonic) threads the chord, fades by ~158 s")

# ============================================================================
# 2. THE END CHIRP -- the real global chirp, slowed & harmonized into a
#    descending farewell; plus the REAL down-chirp grain (the last sound on
#    the tape) released near the end.
# ============================================================================
def swell(f0, f1, stretch, rt=8.0, lp=5200, soff=30):
    """Resynth the real 0.2 s global chirp, time-stretched into a soft swell,
    deep in reverb. Returns (dry+wet) L/R, peak-normalized."""
    d = 0.2 * stretch
    n = int(d * SR)
    tt = np.arange(n) / SR
    x = sg.chirp(tt, f0=f0, t1=d, f1=f1, method="linear")
    x *= np.sin(np.pi * tt / d) ** 2            # smooth swell envelope
    wL, wR = reverb_st(x, rt60=rt, lp_hz=lp, seed_off=soff)
    m = max(np.abs(wL).max(), np.abs(wR).max()) + 1e-12
    xp = np.pad(x, (0, len(wL) - len(x)))
    # mostly the smeared reverb wash (the dry chirp kept low so the swell reads
    # as a soft distant rise/fall, not a peaky transient)
    return 0.28 * xp + wL * 0.95 / m, 0.28 * xp + wR * 0.95 / m

# slow DESCENDING farewell swells (5000->500), increasingly stretched & distant
dn_open = swell(5000, 500, 32, rt=9.0, soff=30)   # 6.4 s, drifts in at the top
dn_mid  = swell(5000, 500, 24, rt=8.0, soff=32)   # 4.8 s
dn_last = swell(5000, 500, 40, rt=10.0, soff=34)  # 8.0 s, the final long fall
# one gentle ascending answer mid-piece (a small breath up before the last fall)
up_breath = swell(500, 5000, 28, rt=8.0, soff=36) # 5.6 s

place(L, R, *dn_open, 6.0, gain=0.16, pan=-0.18)
place(L, R, *up_breath, 60.0, gain=0.12, pan=0.20)
place(L, R, *dn_mid, 96.0, gain=0.15, pan=0.15)
place(L, R, *dn_last, 132.0, gain=0.18, pan=-0.10)
print("[chirp] slowed real global chirp -> descending farewell swells "
      "(16-40x stretch)")

# THE REAL DOWN-CHIRP GRAIN -- literally the last sound on the tape
# (palette capture_down_start_s = 380.6238). Lift a short grain around it and
# release it near the end, reverb-tailed so the final lock gently lets go.
dn_grain = grab(380.50, 0.55, fade=0.05)
dn_grain /= np.abs(dn_grain).max() + 1e-12
lp_g_b, lp_g_a = sg.butter(2, 6000 / (SR / 2), "low")
dn_grain = sg.lfilter(lp_g_b, lp_g_a, dn_grain)
dn_grain /= np.abs(dn_grain).max() + 1e-12
gL, gR = reverb_st(dn_grain, rt60=9.0, lp_hz=5200, seed_off=40)
m = max(np.abs(gL).max(), np.abs(gR).max()) + 1e-12
GRAIN_T = 150.0
place(L, R, dn_grain, dn_grain, GRAIN_T, gain=0.10)         # the dry release
place(L, R, gL / m, gR / m, GRAIN_T + 0.01, gain=0.20)      # the long room tail
print(f"[chirp] REAL down-chirp grain (capture t=380.62, the last sound on "
      f"tape) released at t={GRAIN_T:.0f}s")

# ============================================================================
# 3. THE TRANSPORT WINDS DOWN -- real preamble tick at the measured frame
#    period, then RITARDANDO to a stop (decelerating spacing).
# ============================================================================
# Build the tick from the real preamble spec: 800->3200 Hz, 0.25 s chirp.
PERIOD = 1.372896                       # measured N512 frame period (real)
tick_n = int(0.25 * SR)
tt = np.arange(tick_n) / SR
tick = sg.chirp(tt, f0=800, t1=0.25, f1=3200, method="linear")
tick *= np.sin(np.pi * tt / 0.25) ** 2  # soften so it's a pulse, not a click
lp_t_b, lp_t_a = sg.butter(4, 2600 / (SR / 2), "low")
tick = sg.lfilter(lp_t_b, lp_t_a, tick)
tick /= np.abs(tick).max() + 1e-12
# give each tick a short reverb tail so it reads as a soft transport stroke
tkL, tkR = reverb_st(tick, rt60=3.0, lp_hz=4000, seed_off=44)
mtk = max(np.abs(tkL).max(), np.abs(tkR).max()) + 1e-12
tkL, tkR = tkL / mtk, tkR / mtk

# Ritardando schedule: ticks begin at the true frame period, hold steady only
# briefly (so the coda never reads as a metered pulse), then the inter-tick gap
# GROWS geometrically (transport losing torque) until the strokes are seconds
# apart, then stop. Levels taper hard too -> a soft pulse coming to rest. The
# gentle, thinning pulse keeps the perceptual onset rate low (a coda), while the
# real preamble tick stays plainly audible as the transport winding down.
t_tick = 44.0
gap = PERIOD
decel = 1.085            # each gap 8.5% longer than the last -> a strong ritard
k = 0
n_ticks = 0
tick_amp0 = 0.058
while t_tick < 150.0 and n_ticks < 200:
    # amplitude eases down as it slows; nearly gone by the last strokes
    prog = (t_tick - 44.0) / (150.0 - 44.0)
    amp = tick_amp0 * (1.0 - 0.86 * prog)
    pan = 0.30 * (-1) ** k
    place(L, R, tkL, tkR, t_tick, gain=amp, pan=pan)
    t_tick += gap
    if t_tick > 60.0:        # brief steady stretch, then begin the deceleration
        gap *= decel
    k += 1
    n_ticks += 1
print(f"[ticks] {n_ticks} real preamble ticks: steady @ {PERIOD:.3f}s then "
      f"ritardando (x{decel}/tick) to a stop -- the transport winding down")

# ============================================================================
# 4. THE CALLBACK -- the EXACT opening tape hiss returns and the piece recedes
#    into it. Same real noisefloor grains + voicing as "Leader Tape" (t1).
# ============================================================================
# Use the LONG real quiet regions of the capture directly so the bed needs no
# tight looping: the 19 s lead-in floor (0.5..19.5 s) is the same deck+room hiss
# "Leader Tape" opened with; we also pool the sounder-noisefloor and the
# post-end tape floor. These are stitched with LONG (1.5 s) equal-power
# crossfades into a single ~26 s seamless bed, then tiled with the same long
# crossfade. Long crossfades mean any loop seam is a gradual amplitude move, not
# a transient -> no periodic false-onset train on otherwise stationary hiss.
def stitch(segs, xf_s=1.5):
    xf = int(xf_s * SR)
    fin = 0.5 - 0.5 * np.cos(np.pi * np.arange(xf) / xf)
    fout = fin[::-1]
    out = segs[0].copy()
    for s in segs[1:]:
        a = out.copy()
        a[-xf:] *= fout
        b = s.copy()
        head = b[:xf] * fin
        joined = np.zeros(len(a) + len(b) - xf)
        joined[:len(a)] += a
        joined[len(a) - xf:len(a) - xf + len(b)] += np.concatenate([head, b[xf:]])
        out = joined
    return out

def hiss_bed(seed_segs, roll, xf_s=1.5):
    """Build a long seamless hiss bed from real capture floor regions, then
    loop it with a long equal-power crossfade so there is no periodic seam."""
    body = stitch([s.copy() for s in seed_segs], xf_s)
    body /= np.abs(body).max() + 1e-12
    xf = int(xf_s * SR)
    fin = 0.5 - 0.5 * np.cos(np.pi * np.arange(xf) / xf)
    hop = len(body) - xf               # advance per loop, minus the crossfade
    reps = int(np.ceil((N + len(body)) / hop)) + 2
    out = np.zeros(reps * hop + len(body))
    for kk in range(reps):
        i0 = kk * hop
        b = body.copy()
        b[:xf] *= fin                  # fade IN over the previous tail
        b[-xf:] *= fin[::-1]           # fade OUT into the next head
        out[i0:i0 + len(body)] += b
    out = out[:N]
    # normalize the bed to unit RMS; callers scale it to the desired floor level
    out /= np.sqrt(np.mean(out ** 2)) + 1e-12
    return np.roll(out, roll)

floor_lead = grab(0.6, 18.6, fade=0.4)     # 18.6 s real lead-in deck+room floor
floor_nf   = grab(42.95, 2.95, fade=0.4)   # sounder_noisefloor section
floor_end  = grab(381.2, 4.6, fade=0.4)    # post-end tape floor (after the data)
bedL = hiss_bed([floor_lead, floor_nf, floor_end], 0)
bedR = hiss_bed([floor_end, floor_lead, floor_nf], SR // 3)
hp_b, hp_a = sg.butter(2, 180 / (SR / 2), "high")   # same airy voicing as t1
bedL = sg.lfilter(hp_b, hp_a, bedL)
bedR = sg.lfilter(hp_b, hp_a, bedR)
# Bed is present (warm) at the top as a callback cue, recedes under the full
# chord, then SWELLS UP as everything else fades -> the record ends in the
# exact hiss it opened with.
# bed is now unit-RMS; scale to a quiet floor (~ -28 dB RMS in the steady mid,
# swelling up under the fade-out as the coda recedes into the hiss).
bed_arc = ramp_env([0, 6, 30, 110, 150, 168, 176, DUR],
                   [0.55, 0.80, 0.62, 0.62, 0.85, 1.15, 1.30, 1.20])
L += 0.040 * bedL * bed_arc
R += 0.040 * bedR * bed_arc
# far low room tone, almost subliminal (as in t1): low-pass a copy of the bed
room = hiss_bed([floor_lead, floor_end, floor_nf], SR // 7)
lp_room_b, lp_room_a = sg.butter(2, 220 / (SR / 2), "low")
room = sg.lfilter(lp_room_b, lp_room_a, room)
room_arc = ramp_env([0, 10, 150, DUR], [0.6, 1.0, 1.0, 1.25])
L += 0.013 * room * room_arc
R += 0.013 * np.roll(room, SR // 5) * room_arc
print("[hiss] callback to 'Leader Tape': exact opening noisefloor grains, "
      "swelling up as the coda recedes into them")

# ------------------------------------------------------- fades + mastering ---
nin, nout = int(2.0 * SR), int(8.0 * SR)    # 2 s in; long 8 s farewell out
fi = 0.5 - 0.5 * np.cos(np.pi * np.arange(nin) / nin)
fo = 0.5 + 0.5 * np.cos(np.pi * np.arange(nout) / nout)
for ch in (L, R):
    ch[:nin] *= fi
    ch[-nout:] *= fo

mix = np.stack([L, R], axis=1)
assert np.isfinite(mix).all(), "non-finite samples in mix"

# This coda is intentionally dynamic (quiet hiss floor at the ends, full chord
# in the middle), so a flat RMS-normalize would push the loud middle's chirp-
# swell peaks far above 0 dBFS and a hard limiter would audibly crush them.
# Instead: (1) tame just the sparse transient overshoots with a soft knee placed
# at ~3x the body RMS (only the chirp/grain peaks see it -> the sustained chord
# and hiss stay perfectly linear), then (2) normalize to -15 dB RMS, then (3) a
# final safety trim to <= -1 dBFS. The knee touches < 0.5% of samples.
body_rms = np.sqrt(np.mean(mix ** 2))
knee = 2.5 * body_rms                         # asymptote ~2x knee = 5x RMS (~+14 dB
                                              # crest) -> lands near -1 dBFS at -15 RMS
over = np.abs(mix) > knee
n_eased = int(over.sum())
soft = np.sign(mix) * (knee + (1.0 - np.exp(-(np.abs(mix) - knee) / knee)) * knee)
mix = np.where(over, soft, mix)               # asymptotes to 2*knee, no hard clip
print(f"[master] soft-knee on transients: eased {n_eased} samples "
      f"({100*n_eased/mix.size:.3f}%) above {20*np.log10(knee):.1f} dBFS")

rms = np.sqrt(np.mean(mix ** 2))
mix *= 10 ** (-15.0 / 20) / rms               # aim -15 dB RMS (Master re-aligns)
pk = np.abs(mix).max()
ceil = 10 ** (-1.0 / 20)
if pk > ceil:
    mix *= ceil / pk                          # linear safety trim -> peak = -1 dBFS
    print(f"[master] safety trim {20*np.log10(ceil/pk):+.2f} dB "
          f"(pre-trim peak {20*np.log10(pk):.2f} dBFS)")

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

# onset-event rate -- perceptual, hiss-robust (same method as t1_leader_tape):
# local-median-detrended spectral flux with a hard perceptual floor + re-arm,
# so stationary hiss doesn't count and the (sparse, slowing) ticks read as the
# only real onsets. A coda must stay well under ~0.5/s.
f_, tt_, S = sg.stft(mono, SR, nperseg=2048, noverlap=1536)
mag = np.abs(S)
flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
hop_s = 512 / SR
wmed = max(3, int(3.0 / hop_s) | 1)
med = sg.medfilt(flux, kernel_size=wmed)
excess = np.maximum(flux - med, 0.0)
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
      f"{onsets/DUR:.3f}/s  (coda target: well under 0.5/s)")

print("[QA] energy arc (RMS dBFS per 18 s window):")
for w0 in range(0, int(DUR), 18):
    seg = mono[w0 * SR:(w0 + 18) * SR]
    print(f"      {w0:>3d}-{w0+18:<3d} s : "
          f"{20*np.log10(np.sqrt(np.mean(seg**2))+1e-12):6.1f} dB")
