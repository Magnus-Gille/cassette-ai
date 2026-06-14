# Record this: `master.wav` (13.8 min)

One file, three experiments, all self-locating (two sync chirps bracket everything).

## How to record
1. Play **`experiments/dpd/master.wav`** start-to-finish through the laptop → cassette
   deck (record to tape in one pass).
2. Then play the tape back → speaker → iPhone mic, recording on the phone (same setup
   as the prior `batch_recorded` run — aim for a similar level, e.g. ~speaker 55 / rec 70,
   loud but not clipping).
3. Leave ~1 s of silence before the first chirp and after the last — don't clip the ends
   (the chirps are the sync anchors; if they're cut, alignment fails).
4. Save the phone capture as a WAV/m4a and tell me the path. I run:
   `python3 analyze_master.py <your_recording> ` → full results table.

## What's on it (13.8 min)
| Block | Time | What it tests |
|---|---|---|
| **A. Channel sounder** | ~55 s | sweeps → H(f) magnitude+phase + harmonic distortion; multitone → SNR(f); steady tone → wow/flutter; silence → noise floor |
| **B. PAPR / IMD sweep** | ~55 s | all-carrier multitone at {in-phase / low-PAPR / random} × 4 drive levels → does lower crest factor + lower drive cut the −10.5 dB intermodulation floor? |
| **C. OOK A/B grid** | ~12 min | 6 rates (250–533 gross bps) × {phase-0 (high PAPR) vs low-PAPR phases} × 11 reps = 132 frames → **does low-PAPR rendering raise the reliable bitrate, and what rate passes _nearly always_?** |

## What we'll learn
- **B** isolates the single cheapest lever from the Codex debate: if low-PAPR/low-drive
  drops the IMD floor 3–6 dB, ~⅔–all carriers become 2-bit-capable.
- **C** is the head-to-head with pass-rate statistics — the real customer metric
  ("rate that passes nearly always"), and whether a free TX-side phase change buys it.
- **A** gives the ground-truth channel (magnitude, phase, distortion, wow) to design the
  next waveform against.

Validated end-to-end on the clean file: all 132 frames decode byte-exact, chirp sync
exact, sounder + IMD analyzers run. So any failure after recording is the channel, not
the tooling.
