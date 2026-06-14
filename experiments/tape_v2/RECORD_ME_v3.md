# RECORD_ME_v3 — recording master3.wav onto a physical cassette

This is the attempt at the **FIRST confirmed byte-exact recovery of a real payload
off a physical cassette.** `master3.wav` carries the real 153,823-byte cassette-LLM
(`stories260K_int4.cass`) plus probe files, protected by the deep-dive #2 stack
(flutter-tracked combinatorial k-of-M index modulation + global RS-interleave FEC).

## What is on the tape (~13.1 min, one side)

```
~1 s silence -> GLOBAL up-chirp -> ~45 s channel sounder -> LADDER PAYLOADS -> GLOBAL down-chirp -> ~1 s silence
```

The two wide-band chirps let the decoder self-locate and recover deck speed even
with an arbitrary recorder lead-in. The 45 s sounder gives a fresh channel readout
(H(f), SNR, flutter %, noise floor) for this exact recording.

### The ladder (robust -> frontier)

Every rung uses the verified **M16,K2** flutter-tracked PHY (survival 1.0 at 0.44%
flutter in sim). The rungs ladder on **RS code rate + frame length**, NOT on M:

| Payload | Rung | RS rate | What it is |
|---|---|---|---|
| `test2k_robust` | robust RS(255,127) | 0.498 | 2 KB random probe — guaranteed-win floor |
| `test2k_frontier` | frontier RS(255,191) | 0.749 | 2 KB random probe at the frontier (rate data point) |
| `llm_full_robust` | robust RS(255,127) | 0.498 | **THE HERO: full 153,823-byte LLM, robustly coded (155 frames)** |

The hero LLM is carried at the **robust** rung (best odds), not the frontier — RS rate
0.498 + dense re-sync (155 frames) directly defeats the tracker-desync that hurt the
aggressive rung. In sim at 0.44% flutter it now recovers byte-exact across every seed.

The exact known bytes of each payload are in `sidecars_m3/<name>.bin` for byte
comparison after recovery.

## How to record (CRITICAL — follow exactly)

**Use Voice Memos -> iCloud, NOT Continuity live-capture.** Continuity live-capture
has resampling/dropout artifacts that have broken past decodes. The reliable path is:

1. Copy `master3.wav` to the iPhone (AirDrop or iCloud Drive).
2. Play `master3.wav` from the phone into the cassette deck's LINE IN (or a clean
   mic-coupled path if no line in), recording onto a **fresh, recently-used tape**.
3. **Dolby OFF** on both record and playback. Dolby NR mangles the tone spectrum.
4. **Levels:** aim for healthy VU but DO NOT pin into the red. The master is
   peak-normalised to 0.95; record so peaks sit around 0 VU / -3 dB, not clipping.
5. Record the **full ~11.1 min pass** in one take. Do not pause.
6. Leave **~1 s of clean silence around the chirps** (the master already has lead/tail
   silence; just don't start the tape on top of the up-chirp or cut the down-chirp).

### Playback / capture for decoding

1. Play the recorded tape back into the Mac via a clean line-in / USB soundcard.
2. Capture with **Voice Memos on the phone or a clean line capture — again NOT
   Continuity live-capture.** Save as WAV (or convert to WAV) at any sample rate;
   `m3_decode.py` resamples to 48 k and the chirps recover the residual deck speed.
3. Decode:

   ```
   python3 experiments/tape_v2/m3_decode.py <capture.wav> --out-tag tapeN
   ```

   It prints a per-payload table (rung, bytes, raw frame BER, RS codewords failed,
   BYTE-EXACT yes/no) and the fresh sounder readout, and writes
   `results/m3_results_tapeN.json`.

## Expected outcomes

Last night's clean capture measured **~0.44% wow/flutter**. The M16,K2 tracker holds
lock to ~0.3% comfortably and degrades past ~0.5%; at 0.44% the sim survival is:

- **`test2k_robust` + both probes: expected byte-exact.** Safe wins — RS(255,127)
  absorbs a large raw BER and re-syncs every 255 bytes.
- **`llm_full_robust` (the full 153 KB LLM): expected byte-exact.** Re-tiered to the
  robust rung specifically to land. In sim at 0.44% flutter it recovered byte-exact on
  **every seed tested** (raw BER ~2.4–3.4%, fully absorbed by RS(255,127) + the 155-frame
  global interleave), even at SNR (30–36 dB) harsher than your real capture's 39 dB. So
  the full model is now the *expectation*, not a stretch — though a genuinely bad pass
  (very heavy flutter, a long lock loss) could still miss; re-capture if so.
- `test2k_frontier` is just a frontier-rate data point — informative, not the goal.

**Bottom line:** this is the attempt at the **first byte-exact recovery of a real file —
the full cassette-LLM — off a physical cassette.** Everything is engineered so the full
model lands on a good pass; the 2 KB probe is the guaranteed floor. If the full LLM comes
back byte-exact, you have literally pulled a working language model off a tape.
