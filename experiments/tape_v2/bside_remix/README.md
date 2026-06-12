# B-Side Remix — the data-transfer sound, as music

**This is art, not a data format.** Nothing here encodes or decodes anything. These four
pieces are musical remixes of the master10 cassette data-transfer signal — composed so a
listener *recognizes* the modem ("that's the data!") while actually enjoying the track.
Think of it as the B-side of the tape: side A carries the payload, side B plays with it.

All source material is the project's own signal:

- `../captures/tape10_run1.wav` — the real capture of the tape playing (deck + room +
  tape warmth, 0.42 % flutter). Used as a literal sample source.
- `../master10.wav` + `master10_manifest.json` — the clean master: chirp parameters,
  carrier grids (N512 sp4 @ 375 Hz spacing; d2x N256 sp2), sounder positions, and the
  frame rhythm (~0.25 s preambles, frame period 1.372896 s ≈ 44 BPM half-time).

Musical raw facts exploited throughout: the 375 Hz carrier grid is a quasi-harmonic
series (F#4-ish fundamental); DQPSK phase hops give the buzzy modem texture; the global
chirps are natural risers/sweeps; preamble ticks are a ready-made rhythm track; the
Schroeder sounder is a noise splash that works as a crash/impact.

## Tracks

All tracks: stereo 48 kHz 16-bit, loudness-matched to −15 dBFS RMS, peaks ≤ −1 dBFS,
2 s fade-in / 4 s fade-out.

### 1. `bside_ambient.wav` — 132 s — slow-breathing F# drone
A drone piece built from the actual 375 Hz carrier grid retuned to 7-limit just
intonation. Opens with the real tape chirp pip, swells with 8–16× time-stretched
versions of the actual 500–5000 Hz chirp (down-chirps carry the recede). Real capture
audio is woven through: DQPSK textures frozen into reverb washes, the Schroeder sounder
smeared into a noise-splash crash at the 58 s climax, the real noise floor as a tape-hiss
bed. Listen for the plainly audible dry d2x modem-buzz ghost surfacing at 96–108 s as
the piece thins out, with preamble ticks pulsing barely-there at the measured 1.3729 s
frame period. Arc: quiet → full-spectrum plateau (60–84 s) → recede.

### 2. `bside_techno.wav` — 128 s — techno/IDM remix
Four-on-the-floor techno/IDM where every element is derived from the real signal: kicks
and hats carved from preamble transients and the capture's noise floor, bass and stabs
retuned off the 375 Hz carrier grid, chirp sweeps as build-up risers, the Schroeder
splash as crash, and raw DQPSK buzz riding the breakdowns. The tempo grid is locked to
the measured frame period (≈ 1.373 s ⇒ the 88–175 BPM family).

### 3. `bside_melodic.wav` — 100 s — chiptune in A minor
A 109.26 BPM tune (chosen so the real frame period of 1.372896 s lands exactly on
2.5 beats). Square-ish arpeggio cycles Am–F–C–G under a single portamento lead (AABA
form; B lifts to 16th-notes, melody up an octave). Real sampled preamble chirps act as
rim-click backbeat plus an authentic frame-period tick layer panning L/R; real up/down
global chirps and a Schroeder splash mark every section change; band-passed real DQPSK
capture hisses under the intro, B and outro. The modem identity stays audible: pads buzz
with 90° phase hops at the true 42.7 ms symbol rate, every arp note starts on a random
DQPSK quadrant, and a high "sparkle" arp plays the literal 375 Hz carrier grid retuned
to A natural minor in a dotted-8th cross-rhythm.

### 4. `bside_concrete.wav` — 128 s — dark musique concrète
Built *entirely* from the real tape10 capture — no synthesized sounds anywhere. Emerges
from a frozen Schroeder-sounder wash and low F#/B/C# drone grains, builds through a
granular chorale into a preamble-locked gate ritual (the real d2x signal stuttering on
its own 61 BPM frame grid, sampled preamble ticks as percussion), then ducks away as the
untouched N512 modem signal surfaces raw (62–70 s) before re-submerging into a
lowpassed octave-down version and dissolving under down-chirp echoes. Spectrum centred
on the 500–4000 Hz carrier grid with a 13 % sub-500 Hz shelf — dark and tape-warm.

## Regenerating

Scripts are deterministic; **all seeds are fixed at `20260612`** and logged at runtime.
Requires only python3 + numpy/scipy/soundfile (the project's standard stack).

```bash
cd experiments/tape_v2/bside_remix
python3 extract_palette.py      # carve the sample palette from tape10_run1.wav + master10
python3 remix_ambient.py        # -> bside_ambient.wav
python3 remix_techno.py         # -> bside_techno.wav
python3 remix_melodic.py        # -> bside_melodic.wav
python3 remix_concrete.py       # -> bside_concrete.wav
python3 verify_and_match.py     # verify (duration/peak/NaN) + RMS-match to -15 dBFS
```

`extract_palette.py` writes `palette.json` + `ref_snippets.wav` (sample slices used by
the remix scripts). `verify_and_match.py` is the mastering pass: it checks duration
90–150 s / finite samples / peak ceiling, RMS-aligns every track to −15 dBFS, and
re-limits with a soft-knee limiter at −1 dBFS. Each render takes well under 5 minutes.

## Note on the WAVs

**The WAV files in this directory are gitignored** (large, fully regenerable from the
scripts above). Required `.gitignore` line:

```
experiments/tape_v2/bside_remix/*.wav
```

Only the scripts, `palette.json` and this README are meant to be tracked.
