# Evaluation Cassette v1 — report

A test tape, **not a data carrier**. You play it into ANY deck + speaker + mic
setup, capture the playback, and decode the capture → a **report card** telling you:

1. the highest **data tier / bitrate** that link supports (byte-exact confirmed),
2. a **channel characterization** (SNR, usable BW / HF rolloff, flutter, clock,
   IMD, diffuse contamination, noise floor), and
3. **ranked advice** on what to improve to reach the next tier.

Architecture = **HYBRID predict + confirm**: the front sounder *predicts* the
achievable tier from the measured channel; the tier ladder *confirms* it
byte-exact; the report cross-checks the two and explains any gap.

---

## How to use it

1. **Burn** `eval_master.wav` to tape (Dolby NR **OFF**, record level **~7.0**,
   ~1 s silence around the start/end chirps — they are the sync anchors).
   Regenerate the WAV any time with:
   ```
   python3 experiments/tape_v2/eval_cassette/eval_master.py
   ```
2. **Play + capture** the tape. Use the proven path: record the playback on the
   **iPhone Voice Memos** (sample-accurate clock), let it iCloud-sync, then
   convert to WAV (any sample rate / mono-or-stereo is fine — the analyzer
   resamples and recovers deck speed from the chirps). See the project
   `CLAUDE.md` capture SOP.
3. **Decode → report card**:
   ```
   python3 experiments/tape_v2/eval_cassette/eval_decode.py <capture.wav>
   ```
   Prints the report card and writes `results/<tag>_eval.json`.

**Self-check** (the build's HARD GATE — decode the master itself, no channel):
```
python3 experiments/tape_v2/eval_cassette/eval_decode.py \
    experiments/tape_v2/eval_cassette/eval_master.wav --selfcheck
```

---

## The tier ladder shipped (8 tiers, ~329 → ~6488 net bps)

Each tier carries ~256–512 bytes of **seeded-random** payload, RS(255,k) +
CRC32-per-codeword + column-interleave framed (identical framing to the proven
`bps_push` / `m10` pipeline). A byte-exact tier decode means "this link supports
this tier".

| tier | net bps | scheme (reuse) | enables (real payload at C90 mono) |
|---|---|---|---|
| **T0** | ~329 | DQPSK P2 N512 sp4 RS224 *(substitute for WS)* | text / mnist 25 KB |
| **T1** | ~540 | DQPSK P3 N512 sp4 RS245 *(substitute for BFSK/CAS3)* | delphi-llama2-100k 147 KB |
| **T2** | ~1100 | DQPSK P8 N512 sp4 RS187 *(substitute for MFSK-32)* | stories260K int4 150 KB |
| **T3** | ~2572 | DQPSK P22 N512 sp4 RS159 (the standing 2572 DQPSK record) | stories260K FP32 1.07 MB |
| **T4** | ~3362 | D2X P18 drop RS127 (`Dense2xDropScheme`, m10 r5) | DOOM-mini |
| **T5** | ~4910 | D2X P21 drop RS159 (the DOOM tape, **PROVEN** byte-exact) | DOOM 1.47 MB · chess-gpt int4 borderline · all TinyStories |
| **T6** | ~5791 | r8 D2X P22 RS179 (`build_dense2x_candidate`, the record) | chess-gpt int4 3.2 MB |
| **T7** | ~6488 | 8-DPSK csi7 RS173 (`dapsk16` variant e; bulk + higher-order) | chess-gpt int4 3.2 MB + headroom |

**Substitutions (noted per SPEC):** T0/T1/T2 use DQPSK-family rungs at the same
net bps as the ideal WS / BFSK / MFSK-32 schemes, because those builders are not
cleanly available with an RS(255,k)+CRC32 frame API in this DSP set. Each carries
a **known decode path** (`eval_decode` rebuilds the exact scheme from the
manifest) and self-decodes byte-exact. No tier was dropped — the ladder spans the
full ~330 → ~6500 bps range with 8 rungs.

**Capacity gap (flagged, not faked):** 10 MB+ tiers exist in the capacity campaign
(electrical line-in / stereo ×2) but have **no curated payload yet** — the report
card prints this as a gap rather than inventing a tier.

---

## The characterization sounder

Reuses the proven `analyze_master2` sounder + measurement functions (H(f),
per-tone SNR, flutter from the 3 kHz tone, clock from the chirp pair, noise floor
from silence), and **adds two probes** per SPEC §2:

- **Two-tone IMD probe** (1000 + 1300 Hz equal-amp, 3 s): measures the 3rd-order
  intermod products (700 / 1600 Hz) below the carriers → flags record-level
  saturation (the "level 8.5 blooms IMD" failure). Reported in dB below carriers.
- **Diffuse-contamination probe** (24-tone, 1-FFT-bin-spaced at N=512, 3 s):
  measures off-tone leakage fraction → the reverb/room floor that caps acoustic
  setups (the `spectral_contamination` measurement).

Measured-channel dict: `snr_db_median` / `snr_db_p10`, `usable_bw_hz` (+ HF
rolloff at 9 kHz), `flutter_pct`, `recovered_clock`, `noise_floor_dbfs`,
`imd_db`, `diffuse_frac`.

---

## Report-card format (real example: the `real_master3` capture)

This is the closest-to-real sim channel (the calibrated acoustic-loop replay,
master3). Predict == Confirm == T4:

```
=== CASSETTE LINK REPORT CARD ===
Confirmed tier: T4 (~3362 bps)   Predicted: T4   [agree]
Enables: DOOM-mini
-- Channel ------------------------------
 SNR 61.1 dB (p10 53.1) | usable BW 6575 Hz (HF -35 dB) | flutter 0.06%
 clock 1.000x | IMD -75 dB | diffuse 0.01 | noise floor -64 dBFS
-- Tiers --------------------------------
 tier    net  exact    cw_ok   raw_ber  enables
 T0      329     no   0/2     0.09828  text / mnist 25 KB (sub)
 T1      540     no   0/2     0.09975  delphi-llama2-100k 147 KB (sub)
 T2     1100     no   0/2     0.05343  stories260K int4 150 KB (sub)
 T3     2572    YES   2/2     0.02745  stories260K FP32 1.07 MB
 T4     3362    YES   3/3     0.04199  DOOM-mini
 T5     4910     no   0/3     0.04820  DOOM 1.47 MB | chess-gpt int4 borderline
 T6     5791     no   0/2     0.05000  chess-gpt int4 3.2 MB
 T7     6488     no   0/2     0.09289  chess-gpt int4 3.2 MB + headroom
-- Bottleneck to next tier (T5, ~4910 bps) ------
 usable BW 6575 Hz < 8000
 HF rolloff -35 dB < -32 dB at 9k
   -> #1 clean the heads and check azimuth alignment   (+1 tier)
   -> #2 use fresher tape (worn tape rolls off HF)   (+0.5 tier)
   -> #3 a speaker/mic with flatter HF response   (+0.5 tier)
 Note: 10 MB+ capacity tiers (electrical/stereo) exist but have no curated payload yet -- gap, not shipped.
```

The bottleneck engine correctly fingers the master3 channel's **severe HF
rolloff** (−35 dB at 9 kHz) as what blocks T5, and prescribes head-cleaning /
azimuth / fresher tape — exactly the right fix. (When the binding metric is SNR
the advice shifts to level/cabling/mic/room; when flutter, to deck service or
using Voice Memos over the jittery Continuity mic; when IMD, to dropping the
record level and confirming Dolby is OFF; when diffuse, to a deader room or going
electrical line-in.)

A non-`[agree]` card (e.g. `stress_C`: confirmed **T6** > predicted **T5**) prints
the cross-check note — here "the requirements table is conservative; the link beat
its predicted tier" — so the gap is always explained.

---

## Validation (both HARD GATES pass)

### Gate A — no-channel self-check

`eval_decode.py eval_master.wav --selfcheck` → **every tier byte-exact** (T0…T7,
raw BER 0.0) AND the characterization returns sane clean-channel values: SNR
126.6 dB, flutter 0.00 %, usable BW 11000 Hz, IMD −167 dB, diffuse 0.01, clock
1.000×. PREDICT == CONFIRM == T7. (`results/eval_selfcheck.json`)

### Gate B — through-sim (predict-vs-confirm table)

Master pushed through `src/channel.py` (the four `TAPE_PRESETS`) +
`real_channel_sim(master3)` + a synthetic stress ladder (beyond `worn`, to force
the confirmed tier to walk down). `dT = predicted − confirmed` (−1 = predict one
tier below confirm = conservative). Full data in
`results/eval_sim_validation.json`.

| channel | meas SNR (dB) | flutter % | usable BW (Hz) | IMD (dB) | predicted | confirmed | dT |
|---|---|---|---|---|---|---|---|
| pristine | 69.1 | 0.06 | 11000 | −85 | T7 | T7 | +0 |
| good | 65.3 | 0.28 | 11000 | −81 | T7 | T7 | +0 |
| normal | 42.0 | 0.34 | 11000 | −74 | T6 | T7 | −1 |
| worn | 33.9 | 0.86 | 10389 | −51 | T6 | T7 | −1 |
| **real_master3** | 61.1 | 0.06 | 6575 | −75 | **T4** | **T4** | **+0** |
| stress_A | 37.3 | 0.44 | 11000 | −68 | T6 | T7 | −1 |
| stress_B | 32.6 | 0.63 | 10389 | −57 | T6 | T6 | +0 |
| stress_C | 23.0 | 1.00 | 10389 | −50 | T5 | T6 | −1 |
| stress_D | 14.9 | 1.44 | 11000 | −43 | T0 | T0 | +0 |
| stress_E | 11.2 | 3.68 | 11000 | −36 | — | — | +0 |
| stress_F | 8.4 | 2.99 | 11000 | −30 | — | — | +0 |

**Gate-B results:**
- **Confirmed tier degrades as the channel worsens** — across the stress ladder
  the confirmed tier walks down monotonically `T7 → T6 → T6 → T0 → none → none`.
- **PREDICT tracks CONFIRM within ±1 tier on every channel** (worst |dT| = 1).
- **`real_master3` predicts and confirms the same tier exactly** (T4).
- The four named presets are all clean enough that these (very robust) modems
  confirm **T7** on all of them — a true and reportable finding; the stress
  ladder is what demonstrates the cassette correctly distinguishing weaker links.

### Re-running validation

```
python3 experiments/tape_v2/eval_cassette/eval_sim_validate.py
```
Writes `results/eval_sim_validation.json` and prints the gate summary.

---

## Files

- `eval_master.py` — builds `eval_master.wav` + `eval_manifest.json`. Sounder
  (reused) + IMD probe + diffuse probe + the 8-tier RS-framed ladder.
- `eval_decode.py` — the hybrid decoder + report card. CLI:
  `eval_decode.py <wav> [--selfcheck] [--out-tag TAG]`. Holds the calibrated
  tier-requirements table.
- `eval_sim_validate.py` — Gate-B harness (presets + real_channel_sim + stress
  ladder).
- `eval_manifest.json` — per-tier scheme spec, frame bounds, crc32 codewords,
  payload seed, enables-label (tracked).
- `results/eval_selfcheck.json`, `results/eval_sim_validation.json` (tracked).
- `eval_master.wav` — gitignored (regenerable from `eval_master.py`).
```
