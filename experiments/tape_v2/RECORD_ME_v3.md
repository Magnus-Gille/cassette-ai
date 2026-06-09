# RECORD_ME_v3 — recording master3.wav onto a physical cassette

This is the attempt at the **FIRST confirmed byte-exact recovery of a real payload
off a physical cassette.** `master3.wav` carries the real 153,823-byte cassette-LLM
(`stories260K_int4.cass`) plus probe files, protected by the deep-dive #2 stack
(flutter-tracked combinatorial k-of-M index modulation + global RS-interleave FEC).

## What is on the tape (~11.1 min, one side)

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
| `test2k_robust` | robust RS(255,127) | 0.498 | 2 KB random probe — guaranteed-win |
| `test2k_frontier` | frontier RS(255,191) | 0.749 | 2 KB random probe at the frontier |
| `llm32k_robust` | robust RS(255,127) | 0.498 | 32 KB of the LLM, robustly coded (hedge) |
| `llm_full_frontier` | frontier RS(255,191) | 0.749 | **THE HERO: full 153,823-byte LLM** |

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

- **robust rung + both 2 KB probes: expected byte-exact.** These are the safe wins —
  RS(255,127) absorbs a large raw BER and the robust rung re-syncs every 2000 bytes.
- **`llm32k_robust`: expected byte-exact** (robust rate over real data).
- **`llm_full_frontier` (153 KB): the STRETCH.** In sim at 0.44% flutter it recovers
  byte-exact (raw BER ~4.5% fully absorbed by the global RS interleave), but the
  frontier rate 0.749 has less margin, so on real tape survival is ~0.8 — it may or
  may not land on the first pass. If a frame loses lock badly the interleave still
  protects the rest, but a cluster of desynced frames at the frontier rate can exceed
  RS. Re-record / re-capture if the hero misses; the robust rungs landing byte-exact
  already proves the FIRST real-payload recovery off cassette.

**Bottom line:** if ANY payload comes back byte-exact, this is the first confirmed
byte-exact recovery of a real file off a physical cassette. The robust rung and the
2 KB probes are engineered to make that near-certain; the full 153 KB LLM at the
frontier is the headline stretch.
