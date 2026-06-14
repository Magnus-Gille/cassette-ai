# DECODED — Side B

The B-side of the first-prize hackathon cassette (DOOM-on-cassette). Side B is
the project's GPL source code written to tape as data (the first ~9:46), then
**this** — a 9-track concept album that tells the story of the project *in
sound*: data written to tape, played back through air, fought through
wow/flutter, and decoded byte-exact, with a farewell coda.

**The rule of the record:** every single sound is derived from, or audibly
quotes, the *real* data-transfer signal — the real chirps, the real 375 Hz
carrier grid (retuned), the real frame rhythm, or grains of the actual capture
`tape10_run1.wav` (a genuine cassette playback: deck + room + tape warmth,
0.42 % flutter). Nothing here is a generic synth. The signal is the soul.

The grid is a harmonic series on **375 Hz** (= F#4, +23 cents), so the album's
"native key" is F# — and the carriers are retuned per `palette.json`'s scale
tables into F# major / natural minor / pentatonic as each track requires.

- **Format:** 48 kHz / 16-bit stereo, RMS −15 dBFS, peak ≤ −1 dBFS (album level).
- **Total runtime:** 31:15 (fits the ~35 min side-B music slot after the source data).
- **Album title:** **DECODED** (alternates: *Byte-Exact*, *Sung Through the Heads*).

## Tracklist

| # | Title | Time | What it is |
|---|-------|------|------------|
| 1 | **Leader Tape** | 2:30 | The clear-plastic silence before the data. Looped grains of the real capture noise-floor; around 0:40 a single real chirp "pip" locks in; the 375 Hz grid swells in as a barely-audible held chord. The album's quiet floor. |
| 2 | **Pilot Tone** | 3:30 | The 4875 Hz pilot — the one carrier that runs through the entire real transmission — as a beating drone. The data grid blooms in 7-limit just intonation; the real down-chirp is stretched ~12× into slow dark swells. Weightless, Eno-esque. |
| 3 | **Wow & Flutter** | 3:20 | The enemy made instrument. The real N512 grid retuned to F# natural minor, read through a varying fractional-delay pointer so the whole bed wobbles like an unsteady deck. The struggle. |
| 4 | **Three Seventy-Five** | 3:44 | The bright heart. The carrier grid *is* the melody — every carrier quantized to A-natural-minor, a sparkle arpeggio, DQPSK phase-flips per note, the real preamble ticks as the backbeat. AABA with a key lift for the final chorus. |
| 5 | **Preamble** | 4:23 | The banger. Techno/IDM locked dead to the real d2x frame period (122.034 BPM, two real frames per bar). The 800→3200 Hz frame tick pitched down 8× is the kick; at native pitch it announces every drop. |
| 6 | **Byte-Exact** | 3:33 | The clean decode. 0 codewords failed, CRC passes. A major-lifted resolution of the *Three Seventy-Five* theme — the grid retuned up into clean equal-temperament F# major, ringing rock-steady: no flutter wobble now, because the data came back byte-exact. |
| 7 | **Reed-Solomon** | 3:16 | Error correction as music. The piece *is* a codeword being repaired: corruption → partial lock → full repair. All real capture grains, granulated, gated, stuttered, and re-assembled over the 122 BPM grid. Glitch/IDM. |
| 8 | **Diffuse Reverb** | 3:40 | The deep tape-warm comedown. Dark ambient — the room itself. Spectral-frozen, granulated, reverberated capture material; simple resampling ratios land grains on a low F#/B/C# chord. |
| 9 | **End Chirp (for Fable)** | 3:00 | The farewell coda. The real global chirp — which opened *Leader Tape* — slowed and harmonized into a long descending goodbye as the tape winds gently to a stop. A thank-you. |

## How it was built / regenerate

Each track is rendered by its own self-contained script (`t1_leader_tape.py` …
`t9_end_chirp.py`). They read the palette and the real capture, render a stereo
48 kHz WAV, and print a self-QA (peak/RMS/duration, 10-band spectral balance,
onset rate). Several extend the four proven directions in the parent dir
(`remix_{ambient,techno,melodic,concrete}.py`). Seeds are fixed and logged in
each script.

```sh
# from this directory:
for n in 1 2 3 4 5 6 7 8 9; do python3 t${n}_*.py; done   # render t1..t9.wav
python3 master_sequence.py                                # master + sequence
```

`master_sequence.py` loudness-matches every track to RMS −15 dBFS, re-limits
each to a −1 dBFS peak ceiling (soft-knee, with make-up iteration so the
post-limit RMS lands on target), then concatenates **t1..t9** in order with
**2.5 s of digital silence between tracks** into the single reel
`SIDE_B_album.wav`. It prints the total runtime and verifies it is under the
34.0 min budget.

Inputs (already on disk, not produced here):
- `../palette.json` — exact chirp params, carrier grids, frame rhythm, musical mapping.
- `../../captures/tape10_run1.wav` — the real cassette capture (sample source).
- `../../master10.wav` — the clean master (section timeline).

## Files

- `t1.wav` … `t9.wav` — the nine mastered tracks.
- `SIDE_B_album.wav` — the full reel (single file), the thing you record to tape.
- `t*_*.py` — per-track render scripts. `master_sequence.py` — master + sequence.
- `TRACKLIST.txt` — the handwriting sheet for the J-card.

## gitignore note

The WAVs are large and fully regenerable from the scripts above, so they are
**not** committed. Add to `.gitignore`:

```
experiments/tape_v2/bside_remix/sideB/*.wav
```

The `.py` scripts, `TRACKLIST.txt`, and this `README.md` are tracked — they are
the source of truth; the audio is reproducible from them.
