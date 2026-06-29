# CASSETTE-AI DIAG-1 — Setup Validation Tape (RC v1)

The DIAG-1 tape is a short (~1.8 min) calibration cassette that validates your
recording setup in minutes rather than committing to a 45+ min data tape run.

It is **complementary** to the full-spectrum evaluation tape (`fullspectrum_master.py`):
- **DIAG-1**: fast setup check — run FIRST; catches the faults that would make a
  full tape useless (anti-phase, hum, notch, distortion, clock drift).
- **Fullspectrum**: endurance grade — run AFTER your setup is clean; proves the
  achievable bitrate across the R−1 → R3 rung ladder.

---

## Quick start

```bash
# 1. Build the tape master (once; sidecars are tracked)
python3 experiments/tape_v2/make_diag_master.py

# 2. Record to tape (see "Recording SOP" below)
# 3. Play back and capture with PortAudio (UCA222 wired path):
python3 experiments/tape_v2/capture_uca.py 130 my_diag_capture.wav
# Or via Voice Memos (acoustic path, see CLAUDE.md)

# 4. Analyze — get the report card
python3 experiments/tape_v2/analyze_diag.py my_diag_capture.wav \
    --manifest experiments/tape_v2/diag_manifest.json

# 5. Generic-mode (no diag tape needed — works on any WAV):
python3 experiments/tape_v2/analyze_diag.py any_capture.wav
```

---

## Tape layout (1.77 min stereo, 48 kHz, float32)

```
1.0 s  lead silence
0.2 s  up-chirp (500→5000 Hz)            global sync anchor
0.4 s  gap
0.5 s  DC/noise probe (silence)           DC offset + short noise floor
0.4 s  gap
1.5 s  L-only @ 1000 Hz / R silent        routing + crosstalk L→R
0.4 s  gap
1.5 s  silence / R-only @ 1700 Hz         routing + crosstalk R→L
0.4 s  gap
5.0 s  silence                            mains hum probe (50/60 Hz)
0.4 s  gap
10.0 s 3000 Hz steady tone               flutter/wow + deck clock
0.4 s  gap
10.0 s Schroeder comb ×2 (400–10 kHz)    H(f) per-carrier, notch, HF rolloff
0.4 s  gap
2.0 s  IMD probe (1000+1500+2500 Hz)     THD / intermodulation
0.4 s  gap
~68 s  Data sections (55 sections)        mfsk32 × 20 + gray_m16 × 15
                                          + c4_bpsk × 10 + c4_qpsk × 10
0.4 s  gap
0.2 s  down-chirp (5000→500 Hz)          global sync anchor
1.0 s  tail silence
```

---

## Report card dimensions

| Dimension | Check | Threshold |
|---|---|---|
| Levels / clipping | peak per channel | ≥ 0.99 FS → FAIL |
| DC offset | |mean| per channel | > 0.03 → FAIL, > 0.01 → WARN |
| L/R relationship | Pearson corr + polarity | < −0.15 → anti-phase FAIL |
| L/R SNR comparison | SNR(L), (R), (L+R), (L−R) | best combo recommended |
| Mains hum | 50/60 Hz + harmonics | > +18 dB above band → FAIL, > +8 dB → WARN |
| Frequency response | per-carrier / 1/3-octave SNR | rel < −14 dB → FAIL notch, < −7 dB → WARN |
| HF rolloff | hi-band vs lo-band amplitude | < −16 dB → FAIL, < −8 dB → WARN |
| Deck speed | chirp-pair spacing (diag-tape mode) | > ±3% → FAIL |
| Flutter | complex demod at 3 kHz (diag-tape) | > 2% WRMS → FAIL, > 0.8% → WARN |
| Distortion | THD + IMD at probe tones (diag-tape) | THD > 10% → FAIL |
| Decodability | byte-exact decode per section | pass-rate < 50% → FAIL |

---

## Recording SOP

- **Dolby NR: OFF** (companding mangles multitone)
- **Record level: ~7.0** (not 8.5 — saturation causes IMD bloom)
- **~1 s silence** before you start the tape (let the deck settle)
- **Full play** — don't stop until the end chirp plays

For the wired UCA222 path: `python3 experiments/tape_v2/capture_uca.py 130 capture.wav`  
For acoustic (Voice Memos): record on iPhone → iCloud sync → convert with ffmpeg (see CLAUDE.md)

---

## Mode: generic capture (any WAV)

The analyzer works on **any** stereo or mono WAV — you don't need the diag tape.
Run it on any existing capture to check L/R wiring, hum, and spectrum. The four
faults that originally cost hours to find are all caught automatically:

| Fault | How detected |
|---|---|
| L/R anti-phase (corr ≈ −0.26) | Pearson correlation + SNR(L−R) vs SNR(L+R) |
| Ground-loop hum (+20 dB at 50 Hz) | FFT peak at 50/100/150 Hz vs band noise |
| Mid-band notch (~4.3–4.5 kHz) | 1/3-octave relative amplitude dip > −14 dB |
| Clock / flutter | Complex demod at steady tone (diag tape) / SKIP on data tapes |

**Limitations of generic mode** (no manifest):
- Flutter and distortion require dedicated probe sections → shown as SKIP
- Spectrum analysis uses 1/3-octave bands; DQPSK carrier gaps can show as
  weak bands (not real notches). Use the diag tape + `--manifest` for precise
  notch detection.
- Deck speed requires chirp pair from the tape → SKIP without manifest

---

## Files

| File | Status | Purpose |
|---|---|---|
| `make_diag_master.py` | tracked | builds `diag_master.wav` + manifest + sidecars |
| `analyze_diag.py` | tracked | report card; works on any WAV or diag tape |
| `test_diag.py` | tracked | 14 unit tests (TDD); run with pytest |
| `diag_manifest.json` | tracked | probe windows + section offsets (generated) |
| `diag_sidecars/` | tracked | payload binaries for byte-exact check (generated) |
| `diag_master.wav` | gitignored | the tape WAV (regenerate with `make_diag_master.py`) |

---

## Validation results

### `inband_doom_tape.wav` (stereo electrical — known-bad, UCA222 anti-phase)
- OVERALL: **FAIL**
- L/R correlation: −0.286 → **ANTI-PHASE** → recommend L−R [FAIL]
- Mains hum: 50 Hz at +20 dB → ground loop [FAIL]
- Spectrum: 5 kHz dip (−11.7 dB rel) → notch near 4.3–4.5 kHz [WARN]

### `doom_tape_readback.wav` (mono acoustic — byte-exact decode)
- OVERALL: **WARN** (no critical faults)
- L/R: N/A (mono capture)
- Hum: +11.5 dB (acoustic room noise, below fail threshold) [WARN]
- Spectrum: PASS
