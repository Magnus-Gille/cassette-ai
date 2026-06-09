# Decoding the first real tape capture — findings

Capture: `captures/voicememo_run1.wav` (iPhone Voice Memos → iCloud → Mac; the
acoustic loop laptop→tape→deck→speaker→phone). 41.5 min recording (operator left
it running); the master content is ~12.8 s → ~1010 s. Source `.qta` is in iCloud
Voice Memos (`20260608 202255-1957CE44.qta`).

## The mystery, solved

The analyzer returned **chance-level BER (~0.5) on every config**, which first looked
like the schemes failing on tape. It was not. Two bugs/gaps, in order of impact:

### 1. Global-sync bug — chirp0 search window too narrow (FIXED, committed)
`global_sync_and_resample` searched only the first ~5 s for the global sync chirp
(it assumed chirp0 ≈ its nominal 1 s position). Real captures have an arbitrary
**lead-in** — here the operator started the recorder ~11 s before the tape, so the
real chirp0 was at **12.79 s**, outside the window. The analyzer locked a spurious
peak at 4.17 s → `align` off by ~8.6 s → every section extracted from the wrong
place → chance BER.

**Fix:** search a generous lead-in window (first ~45 % / ≥60 s) and take the
dominant peak. Result on the real capture:

| metric | before fix | after fix |
|---|---|---|
| recovered clock | 1.0087× (wrong) | **1.0001×** |
| sounder flutter | 75 % (garbage) | **0.44 %** |
| sounder SNR median | — | **39 dB** |
| noise floor | — | **−58 dBFS** |
| per-section BER (robust cfgs) | ~0.5 (chance) | **0.10 – 0.25** |

**The capture is excellent** — 39 dB SNR and 0.44 % flutter on a quiet living-room
acoustic loop, *far* better than the prior worst-case characterization (12.6 dB /
2.2 %). The acoustic loop is not the enemy we feared when the setup is clean.

### 2. Residual error = channel colouration → needs equalization + FEC (NOT yet byte-exact)
After the sync fix, BER is ~0.1–0.25, not 0. Diagnosed (see `debug_timing.py`):
- **Not timing** — a fine symbol-grid offset/rate scan does not move the BER floor.
- **It is tone-detection under channel colouration.** MFSK/combinatorial pick the
  loudest FFT bin(s); the real channel (tape HF rolloff + AAC + reverb leakage
  across 1-bin-spaced tones) biases the argmax. The sim channel had no reverb/
  colour, so this never showed.

**Per-tone equalization** (normalise each tone bin by its across-symbol energy)
confirms the mechanism: mfsk32 **BER 0.25 → 0.096** (2.6×). Combinatorial improves
less with the naive estimate (each tone is ON only K/M of the time, so a blind
mean/median is a poor channel-gain estimate — a sounder-H(f)-based or ON-percentile
estimate is the proper fix).

| config | raw BER | per-tone-EQ BER | CRC passes |
|---|---|---|---|
| mfsk32 | 0.252 | **0.096** | 0 |
| c2_m32_k2 | 0.116 | 0.106 | 0 |
| c2_m32_k4 | 0.401 | 0.306 | 0 |

**No config reaches byte-exact** on an *unprotected* 96-byte frame: a ~10 % residual
symbol-error floor means ~80 bit errors/frame, which CRC cannot pass. Closing the
last 10 % is an **error-correction-coding job**, not a detection-tuning job — exactly
the FEC layer the capacity projection assumes and that deep-dive hypotheses D2
(interleave + LDPC/fountain) and D7 (concatenated soft FEC) build.

## Bottom line
- ✅ The full physical loop works and the analyzer now correctly characterizes a real
  capture (the sync bug is fixed and committed).
- ✅ The real acoustic channel on a good setup is far better than feared (39 dB / 0.44 %).
- ⏳ Byte-exact recovery needs: (a) proper channel equalization for the tone detectors
  (sounder-H(f) or ON-gain based), and (b) the FEC layer. Both are concrete next steps;
  the capture is saved so they can be validated offline without re-recording.

## Tools (in this dir)
- `debug_decode.py` — section-localization brute-force scan (found the sync bug).
- `debug_timing.py` — symbol-grid timing/rate scan (ruled out timing).
- `debug_eq_combo.py` — equalized combinatorial demod + CRC pass count.

## master3 codec + robustness ladder (m3_codec.py)
The FEC layer is now built: `m3_codec.py` refactors w4_endtoend.run_global's PROVEN
RS-interleave pipeline into reusable `encode_payload(payload, rung)` /
`decode_payload(frames_bits, meta)`, plus a robust->frontier LADDER of rungs.

Self-test (CHANNELS["real"], 40 KB cass slice, all clean roundtrips on a >=32 KB slice):

| rung     | M,K   | RS(n,k)    | rate  | net bps | rawBER | real byte-exact |
|----------|-------|------------|-------|---------|--------|-----------------|
| robust   | 16,2  | (255,127)  | 0.498 | 1509    | 0.0016 | YES             |
| mid      | 16,2  | (255,159)  | 0.624 | 1890    | 0.0014 | YES             |
| frontier | 16,2  | (255,191)  | 0.749 | 2270    | 0.0013 | YES (= w4)      |

**ARCHITECTURAL FINDING (overturns the brief's "wide spacing = lower M = robust"
heuristic):** for the flutter-TRACKED combinatorial PHY, LOWER M is *worse* on
flutter, not better. Measured survival at 0.44 % flutter: M12 0.75, M16 1.00,
M20 0.88. The dominant failure is the per-symbol energy-lock TIMING tracker losing
lock; lower M -> fewer samples/symbol (M12=58 vs M16=77) -> shorter window the
tracker loses faster. Energy detection already immunises the frequency axis against
flutter phase chaos, so widening tone spacing buys nothing. M8/M10 are non-viable
(M8 fails even with no channel: 39 samples/symbol is too short to sync). Therefore
the ladder keeps the verified M16,K2 PHY on every rung and ladders purely on RS RATE
+ re-sync density (frame_bytes) -- the honest robustness levers for this tracker.

**Interleave-depth caveat:** at the frontier rate (0.749) one fully-desynced frame
must stay within RS's 32-sym correction, which needs >~10 frames of interleave
depth. A 16 KB slice (6 frames) can fail frontier when one frame desyncs (saw
BER 0.52 on one seed); 40 KB (14 frames) and the full 153 KB (~38 frames) have
ample depth -- this shallow-depth failure is exactly why the robust rung exists.

## master3 real capture — decode diagnosis (2026-06-09)
First master3 recording (`captures/tape3_run1.wav`) captured CLEANLY (sounder 40.6 dB,
0.31% flutter, clock recovered 1.0009x) but decoded 0/3 (chance BER). Diagnosis
(`debug_m3.py`): the SIGNAL IS CLEAN — frame0 symbol 0 decodes byte-exact (FFT at the
tone freqs, top-2 = the exact sent tones [3,10], dominant 1.0/0.18 vs ~0.02 floor). The
failure is the deep-dive `make_tracked_combo` demod on real audio, two compounding causes:
  1. TIMING: symbols are not on a regular grid (real flutter wanders them ~1.2 symbols
     over a frame, per-symbol step up to 36 samples vs the demod's +/-3 search) — the
     matched-filter tracker loses lock immediately (fixed stride: 6/40 early symbols
     correct; no single stride/rate recovers the frame).
  2. DETECTION: short symbols (M16 -> N=77, 623 Hz bins) make top-K fragile to channel
     coloration; many symbols mis-detect even with good timing. (Blind median-EQ is wrong
     for k-of-M: each tone is "on" only K/M of the time, so the median estimates the OFF
     level — needs sounder-H(f) or "on"-percentile per-tone gain.)
FIX PATH: a real-audio-hardened demod = robust per-symbol timing tracker (wider search,
energy-CONCENTRATION lock not max/median) + proper per-tone channel EQ + FFT detection.
Target raw BER ~0.15; the robust rung RS(255,127) corrects ~25% so that closes to
byte-exact. If M16/N=77 stays too fragile, re-tier to the longer-symbol M32,K2 (N=159)
that reached ~0.10 BER on the master2 real capture, and re-record. Tools: debug_m3.py.

## master3 hardened decode — RESULT: M16/N=77 is too fragile, re-record needed (2026-06-09)
Built the hardened decoder `m3_decode_v2.py` exactly as planned: reuses
`global_sync_and_resample` + `find_preamble` + `decode_payload` unchanged, replaces only
the per-frame tone demod with (a) FFT-bin energy detection, (b) PROPER per-tone EQ from
the SOUNDER H(f) (the 26 dB HF rolloff is divided out; high tones are ~20x weaker), with
a 1-pass decision-directed refinement, and (c) a wide-window (+/-15) per-symbol timing
tracker on an energy-CONCENTRATION lock score (gap between the Kth and (K+1)th EQ'd tone).

**Result on `captures/tape3_run1.wav` (sounder 40.6 dB, 0.31% flutter, clock 1.0009x):**

| payload          | rung     | bytes  | frames | raw BER | RS cwFail | byte-exact | GENIE BER | genie cwFail | genie exact |
|------------------|----------|--------|--------|---------|-----------|------------|-----------|--------------|-------------|
| test2k_robust    | robust   | 2048   | 17     | 0.433   | 17/17     | NO         | 0.187     | 17/17        | NO          |
| test2k_frontier  | frontier | 2048   | 11     | 0.426   | 11/11     | NO         | 0.200     | 11/11        | NO          |
| llm_full_robust  | robust   | 153823 | 155    | 0.459   | 1212/1212 | NO         | 0.168     | 1212/1212    | NO          |

**MILESTONE NOT ACHIEVED — and it is a PHY-fundamental floor, not a decoder-tuning gap.**

The EQ is the big lever (it lifts the genie ceiling from ~0.64 to ~0.32 SYMBOL error and
the raw-decoder BER stops being chance), and the sounder-H(f) EQ correctly flattens the
channel. But the decisive number is the **GENIE ceiling**: an oracle that is TOLD the
correct symbol and is allowed to pick the best timing offset (+/-15) per symbol AND apply
EQ still floors at **bit-BER ~0.17-0.20**, and that fails EVERY RS codeword. No real
tracker can beat an oracle, so no amount of timing/EQ tuning closes this.

**Root cause = spectral contamination, NOT timing and NOT noise:**
- Per-tone SNR is excellent: 35-59 dB on every data tone, frac_below_8dB = 0. Noise is
  not the problem.
- Genie timing residual over a whole 340-symbol frame is only **0.70 symbols** (per-symbol
  |step| median 0, p90 5 samples). The global sync already handles the flutter wander; the
  tracker is not the bottleneck.
- On symbols the genie decodes CORRECTLY, the median EQ'd energy OUTSIDE the top-K tones
  is **0.65** (should be ~0 for a clean symbol). 103 of 113 undecodable symbols have a
  spurious strong 3rd tone. With N=77 (623 Hz bins, 1-bin tone spacing) the short FFT
  window's spectral skirts + adjacent-symbol energy contaminate all 16 closely-spaced
  bins; EQ then multiplies the weak-tone bins (and their contamination) by up to 20x. A
  correctly-detected K-of-M pair barely clears the leakage floor. Shorter/Hann windows
  are strictly worse (they widen the bins and destroy the 1-bin orthogonality), so N=77
  full-rectangular is already the best operating point — and it is not good enough.

**RE-TIER DECISION (logged):** keep the FFT-detection + sounder-EQ + concentration-lock
tracker design (it is correct and reusable), but the M16/N=77 symbol is fundamentally too
short for the real channel's frequency selectivity. Re-record master4 with the
longer-symbol **M32,K2 (N=159, ~302 Hz bins)** PHY that reached ~0.10 BER on the master2
real capture: doubling the symbol length halves the bin width (less leakage) and gives the
correctly-detected tones more margin over the contamination floor. The robust rung's
RS(255,127) (~25% byte-correction) should then close ~0.10 raw BER to byte-exact. The
hardened demod in `m3_decode_v2.py` carries straight over to M32 (it is parameterised by
the scheme). Tools: `m3_decode_v2.py` (decoder + genie ceiling), `debug_m3.py` (diagnosis).
