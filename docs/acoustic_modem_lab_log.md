# Acoustic modem lab log

Running log of the acoustic data-over-sound experiments (laptop speaker → quiet
room ~0.3 m → iPhone Continuity mic). Newest entries at the bottom. Tools live in
`scripts/`; raw data in `RESULTS/`.

**Target:** decode a real payload **byte-exact** over the acoustic path (then through
the cassette), at the highest reliable throughput, with modulation matched to the
channel. Measured by SER/BER→0, byte-exact pass/fail, net bits/s.

**Channel facts established (see `acoustic_speaker_iphone.md`):**
- Frequency response flat-ish ~400 Hz–10 kHz (bandwidth-rich).
- 2-FSK reliable to ~50 baud, hard cliff ~60–67 baud (time-poor / reverb ISI).
- iPhone capture clock ≈ **0.88×** (a sent symbol of length T appears as ~0.88·T) —
  must be corrected; codec's ±6% search is too narrow.

---

## A — Multi-tone capacity probe ✅

Chords of N equal-energy log-spaced tones (500–8000 Hz), measure weakest tone vs
the intermod "floor" between tones.

| N | weakest tone / floor | verdict |
|---|---|---|
| 2 | 51 dB | clean |
| 4 | 40 dB | clean |
| 8 | 36 dB | clean |
| 16 | 15 dB | clean |
| 32 | 14 dB | clean |

**Result:** speaker→phone stays linear enough that **32 simultaneous carriers** are
all cleanly resolvable. → OFDM-style parallel carriers are very viable. 32 carriers
× ~20 baud ≈ **640 bps** ceiling estimate, vs 50 bps for single 2-FSK.
Tool: `scripts/acoustic_multitone_probe.py`. Data: `RESULTS/data/acoustic_speaker_iphone.json`.

---

## B — MFSK (M=16) over the air ✅

One of 16 log-spaced tones (500–8000 Hz) per symbol = 4 bits/sym. Self-clocking
decoder (searches clock≈0.85–0.90 + phase, argmax tone). 40 sym/segment.

| rate | baud | SER | net bits/s |
|------|------|-----|-----------|
| 80 ms | 12.5 | 5% | 48 |
| 40 ms | 25 | 5% | **95** |
| 25 ms | 40 | 55% | broken |

**Result:** ~95 bps usable at 25 baud (5% SER → needs FEC). Breaks at 40 baud
because short symbols can't resolve closely-spaced low tones (15 ms window ≈ 67 Hz
res, but low carriers ~60 Hz apart). **Lesson:** MFSK trades freq-resolution for
speed; OFDM avoids this (long symbols = fine resolution AND many carriers at once).
Tool: `scripts/acoustic_mfsk_probe.py`.


## C — OFDM end-to-end, BYTE-EXACT over the air ✅ 🎉

K=16 parallel OOK subcarriers, 1500–7000 Hz (the strong/flat band), 100 ms symbols.
Frame brackets data with two **all-ON marker symbols**; decoder finds them by
per-carrier "on-count", takes cluster centroids, and distributes data symbols
**evenly between both markers** (anchors both ends → no clock drift). Per-carrier
on-gain from P0; OOK threshold = 0.5×gain.

**Result:** `"hello cassette ai 2026"` (22 B) decoded **byte-exact, BER 0.000, sha match**
over the laptop-speaker→iPhone acoustic path. Gross rate 160 bps @ 100 ms/16-carrier.

**Debug journey (all measured, not guessed):**
1. clean-signal decode passed → codec logic correct.
2. first air try: `...assette ai 202...` with errors → P0 truncated (ffmpeg ~2.8 s
   startup ate the 2.5 s lead). Added startup-transient guard + 4 s lead.
3. block-length→clock was fragile (variable startup + quiet-edge trimming) →
   switched to all-ON **marker** detection for timing.
4. low carriers (700–900 Hz, −17 dB) too weak to mark reliably → moved carrier band
   to 1500–7000 Hz (maxon 14→16).
5. errors grew toward the end → anchored grid on **both** markers (no drift):
   `hgnlo kassgtte qi 2026`.
6. remaining errors all 0→1 flips (leakage raising off-carriers) → raised OOK
   threshold 0.32→0.5 → **BER 0.000, PASS.**

Tool: `scripts/acoustic_ofdm_modem.py`  (gen / decode / sim).
Recording: `RESULTS/ofdm_pass_recording.wav`.


## D — Throughput + FEC + robustness ✅

Pushed the OFDM modem to a longer 97-byte message and a **noisier room** (lawnmower
running outside — capture clock drifted to 0.78–0.88, raw bit-BER ~3–4%). Built up
the full stack, each layer fixing a measured failure:

1. **K=24/60 ms, no FEC** → ~9–22 byte errors, readable but wrong.
2. **Pilot tone @7800 Hz** (only in marker symbols) replaced all-ON marker detection —
   data can no longer fake a marker (`clock=0.27` bug fixed).
3. **Clock drift *within* a recording** (Continuity Camera drops samples mid-stream)
   caused middle-garbage / good-ends → **periodic re-sync markers every 8 symbols**
   with piecewise-linear timing.
4. A single **missed marker** cascaded → **snap-to-grid** marker handling (pad to full
   chunks, predict marker slots, interpolate missing ones).
5. **Hann window** in the demodulator cut sidelobe leakage → raw BER 0.089 → 0.012.
6. **Reed-Solomon (RS-48)** parity — but scattered single-bit errors made byte-oriented
   RS inefficient (4% bit-BER → 26% byte-BER).
7. **Carrier-major interleaving** (each carrier owns a contiguous byte-run, so a bad
   carrier = a byte *burst* not scattered errors) → RS corrects efficiently.

**Result (lawnmower running, raw BER ~3–4%):**
`97-byte message, K=20 carriers, 80 ms symbols, RS-48, byte-exact PASS over the air.`
250 bps gross, ~112 bps net. Markers 9/9, RS=corrected, sha match.

The full stack: **OFDM (K parallel OOK carriers, 1500–7000 Hz) + pilot-tone framing +
periodic re-sync (drift) + Hann demod + carrier-major interleave + Reed-Solomon.**
Tool: `scripts/acoustic_ofdm_modem.py`.


### D — throughput frontier (lawnmower-noise conditions)

| config | gross | net | result (noisy room) |
|--------|-------|-----|---------------------|
| K=20 / 80 ms / RS-48 | 250 bps | ~112 bps | **byte-exact PASS** |
| K=24 / 60 ms / RS-48 | 400 bps | ~180 bps | FAIL — mid-stream transient burst |

**Insight:** carrier-major interleaving fixes *frequency*-selective errors (bad carriers)
but a *time* transient (mower/car) corrupts all carriers at one instant → scattered byte
errors again. A **2D (time×freq) interleaver** would handle both. K=20/80 ms is the robust
ceiling under active lawnmower noise; expect higher in a quiet room (where 1200-baud-equiv
single carrier already failed but parallel carriers thrive). Next: 2D interleave, then push
again in quiet; then cassette-in-the-loop (needs re-cabling — deferred while away).

### D — measured clock drift (why re-sync markers matter)

Inter-marker spacing in the K=20 PASS recording implies the iPhone capture clock
**swings 0.74–0.80 within a single 6 s recording (7.8%), non-monotonically** (seg5
dipped to 0.74) — discrete sample-drop events, not smooth drift. A single global
clock would accumulate ~0.28 symbol of misalignment per chunk by the end. Re-syncing
every 8 symbols holds each chunk's error small → this is the mechanism that made the
byte-exact decode possible. Smaller CHUNK = more robust, more overhead (8 was enough).

### D — tighter re-sync unlocks higher throughput

K=24/60 ms failed even in a quiet room with CHUNK=8: **mid-chunk sample-drop events**
(the iPhone clock steps *within* a chunk; piecewise-linear can't follow a step) corrupt
up to 8 symbols ≈ 24 bytes, right at RS-48's limit. **CHUNK=4** (re-sync every 4 symbols)
caps damage at ≤4 symbols → **K=24/60 ms byte-exact PASS, 400 bps gross, ~160 bps net.**
Confirms the **iPhone Continuity clock instability — not the acoustic channel — is the
throughput bottleneck**; a USB line-in would remove it. K=32/50 ms still fails (carrier
resolution: 32 closely-spaced carriers in a ~37 ms window).

### D — final throughput results (quiet room, full stack, CHUNK=4)

| config | gross | net (byte-exact) | result |
|--------|-------|------------------|--------|
| K=20 / 80 ms | 250 bps | ~112 bps | PASS (also passed under lawnmower) |
| K=24 / 60 ms | 400 bps | ~160 bps | PASS |
| K=28 / 60 ms | 467 bps | ~175 bps | **PASS (current best)** |
| K=32 / 50 ms | 640 bps | — | FAIL (carrier resolution at short window) |

**Bottleneck identified:** the iPhone Continuity capture clock (0.74–0.88×, drifts
~8% non-monotonically with discrete sample drops) — *not* the acoustic channel. A USB
line-in interface would remove it and likely push well past 640 bps.

### Status / next (paused — phone needed elsewhere)
- DONE: full acoustic data-over-sound modem, byte-exact to ~467 bps gross over the air.
- DEFERRED (needs phone + re-cabling): **cassette-in-the-loop** (record signal→tape→
  play tape→speaker→phone→decode) — the headline test for the project.
- TODO when back: 2D (time×freq) interleaver, DBPSK carriers, cyclic prefix; push K=32+;
  retry with a USB audio interface to kill the clock-drift ceiling.
- Research agent surveying ggwave / Kansas City Standard / acoustic OFDM was running at pause.

## Research survey complete (background agent)

Full survey in `docs/acoustic_modem_research.md`. Headline: our OOK amplitude threshold
is the main weakness. Two changes predicted to drop BER <0.5% and remove the iPhone-clock
ceiling: **(1) DBPSK per carrier** (Goertzel phase is already computed, just discarded —
no threshold needed) and **(2) a 2D time×freq block interleaver** (burst + fade). Nice
historical tie-in: **Kansas City Standard (1976)** used our exact 1200/2400 Hz tones, and
the **C64 Datasette (1977)** already solved clock drift by measuring period during a leader.
Next-session action table is in the research doc.

## 🎉 CASSETTE-IN-THE-LOOP — BYTE-EXACT (the headline result)

The full physical loop, no line-in hardware: **computer → deck LINE IN → TAPE →
deck LINE OUT → speaker → air → iPhone mic → decode.**

- Signal: `"hello cassette ai 2026"` (22 B), K=16 / 100 ms / CHUNK=4 / RS-48.
- Result: **byte-exact PASS, sha match, RS corrected.** 10/10 markers, clock 0.889,
  data block located at 5.92–9.92 s.
- The tape even had leftover music on it — the 7800 Hz pilot finder isolated our data
  and ignored the music entirely.

This stacks BOTH hard channels (tape wow/flutter + hiss + band-limiting, AND the
acoustic speaker→phone hop with its drifting Continuity clock) and still round-trips
perfectly — the periodic re-sync markers + carrier-major interleave + Reed-Solomon
stack absorbed it all. **Digital data demonstrably survives a real audio cassette.**

Artifacts: `RESULTS/tape_test/signal.wav` (sent), `RESULTS/tape_test/recorded_PASS.wav`
(the actual tape playback that decoded byte-exact).

### Tape-loop physical settings (smoke-test tuning session)
- Dolby NR: **OFF** on both record & playback (matched-ON still corrupted HF carriers
  — companding tracks signal envelope, doesn't cancel for multi-tone data).
- Deck record level: tried **8.5** (over-driven → peak 0.63, intermod false-ons on
  specific carriers, ~3% BER) → backed off to **7.5**.
- Loudspeaker volume (readback): **70** (corrected).
- Target capture level: **rms ≈ 0.04, peak < 0.6** (the known-good single-PASS zone;
  the failing batch take was rms 0.02 = half).

### Readback speaker-volume sweep (rec 7.5, Dolby OFF) -- finding the level sweet spot
| speaker vol | capture rms | peak | result |
|-------------|-------------|------|--------|
| (lower, earlier) | 0.021 | 0.63 | too quiet -> all fail |
| **70** | **0.118** | **0.93** | too loud, mic near clipping -> only K16/100ms passed |
| target | ~0.04 | <0.4 | known-good zone |

K16/100ms passed byte-exact at BOTH extremes (huge margin); denser configs need the
clean mid-level. Next: drop speaker ~half, live-check to rms~0.04, then re-decode.

### ⚠️ PRE-FLIGHT LEVEL CHECKLIST (Claude: ALWAYS prompt this before any take)
Before **RECORD** (computer → deck → tape):
  1. Confirm **deck RECORD level** (target ~7.0; peaks should *not* sit at +4 — that's
     tape saturation → intermod distortion on data carriers).
  2. Confirm **Dolby NR = OFF** (both record & playback).
  3. Confirm laptop output ~75% and routed to the 3.5 mm jack (External Headphones).
Before **PLAYBACK / READBACK** (tape → speaker → phone):
  4. Confirm **loudspeaker volume** for target capture **rms ≈ 0.04, peak < 0.5**
     (≈ speaker 50–55 in this room; 70 clips, 45 is a touch low).
  5. Phone unlocked, Continuity mic connected, positioned by the speaker.

ROOT CAUSE NOTE: record level was stuck at **8.5** through all early smoke tests
(believed to be 7.5) — persistent over-drive = the specific-carrier intermod false-ons
that capped decoding at K16/100ms. Lower to ~7.0 and re-verify for the real run.

## Tape BATCH run — banked (acoustic-readback ceiling characterized)

Ran the 71-experiment batch master to tape and back (laptop→tape→speaker→iPhone),
decoded with the index-aligned batch decoder. Final clean settings: **Dolby OFF,
rec 7.0, speaker 55** (auto-detected the first 3 frames were missed → offset 3, labels
corrected automatically).

**Result: 7/50 byte-exact; reliable frontier ≈ 250–333 bps** (K20/80 and K20/60 passed
repeatedly; P:22B and P:97B passed). Most other configs sat at **~3–5% byte error — just
past Reed-Solomon**, flipping pass/fail run-to-run.

**Root-cause findings (the tuning saga, for the record):**
- **Record level was stuck at 8.5** through early takes (believed 7.5) → tape saturation
  → intermod false-ons on specific carriers. Fixed at 7.0.
- **Dolby NR ON (even matched)** corrupted HF carriers (envelope companding doesn't
  cancel for multi-tone data). Must be OFF both ends.
- **Acoustic readback is SNR-limited at ~rms 0.03**: speaker quieter → noise-limited;
  speaker louder (65+) → mic clipping (peak →1.0). The clean window is narrow.
- Two coupled knobs: lower rec level → weaker tape → need higher speaker (→ clips).

**Conclusion:** the cassette demonstrably stores digital data (robust configs round-trip
byte-exact through real tape), and the **acoustic-readback path tops out ~250 bps reliable**.
Pushing the full throughput frontier requires removing the acoustic hop + iPhone-clock
drift → **electrical line-in (Behringer UCA222)**. The entire stack (modem, FEC, interleave,
batch harness, index-align) carries straight over.

**New SOP added:** pre-flight level checklist (Claude always prompts record/playback levels).
Data: `RESULTS/tape_test/batch_results_speaker55_rec70.json`.
