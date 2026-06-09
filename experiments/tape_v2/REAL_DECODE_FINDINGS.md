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
