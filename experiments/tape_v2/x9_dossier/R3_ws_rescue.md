# R3 — WS fixed-grid failure forensics + rescue (m8 real capture)

**Capture:** `experiments/tape_v2/captures/m8_tape_mono_lossless.wav` (660 s, 48 k mono lossless)
**Sync:** deck clock +0.117 %, flutter 0.41 % wrms, SNR median 38.3 dB, noise floor −55.6 dBFS — identical to the official m8 decode.
**Script:** `experiments/tape_v2/x9_ws_forensics.py` (stages: sync → demod → forensics → rescue)
**Artifacts:** `x9_dossier/R3_ws_rescue.json`, `results/x9_ws_forensics.log`

---

## TL;DR

**m8_m16k3_rs159 (1052 net bps) CANNOT be rescued byte-exact on this tape. NO new record.**
The fixed-grid WS failures are a **real, partially-recoverable timing slip** — the per-symbol
timing-trajectory front-end cuts the K=3 lottery rung's raw BER from 0.103 → **0.0587** and its
failed codewords from **37/37 → 7/37** — but the residual floor still exceeds the RS(255,159)
budget by ~6 codewords clustered right at the correction edge. To close it errors-only would need
rs_k ≤ 131 → ~870 net bps, **below the 934 bps DQPSK record**. The 934 DQPSK record stands.

**Harness validated by two positive controls that DO flip byte-exact, CRC-verified:**
- `m8_m32k2_rs159` (748 bps): 5 → **0/36 cw**, raw BER 0.0795 → 0.0518 — reproduces the known m8_decode combo flip.
- `m8_m32k2_rs127` (598 bps): 6 → **0/6 cw**, raw BER 0.187 → 0.131 (freq-trajectory + frac:0.5 erasures) — a NEW clean flip that the official timing-only combo missed. Below 934, not a record.

Every flip has `miscorrected_cw = 0` and full manifest-CRC32 verification (no truth leak into the decoder; truth only for scoring).

---

## 1. Forensics — why the fixed grid fails

Per-section classification (pass-1 greedy demod, instrumented). All six WS sections classify
**TIMING-SLIP (recoverable)**: the symbol grid wanders ≳ 0.7 symbol within a single ~3.4 s frame
and BER climbs as the frame progresses.

| section | net bps | K/N | base BER | drift span | late/early BER | gap sep (corr/wrong) | classification |
|---|---|---|---|---|---|---|---|
| m8_ctrl_m16k1_rs191 | 562 | 1 / 256 | 0.072 | 0.70 sym | 0.10 | — | timing-slip + EQ tell |
| m8_m16k2_rs159 | 701 | 2 / 256 | 0.107 | 0.76 sym | 2.28 | — | timing-slip (late-rising) |
| m8_m16k2_rs191 | 843 | 2 / 256 | 0.105 | 0.81 sym | 2.01 | — | timing-slip (late-rising) |
| **m8_m16k3_rs159** | **1052** | **3 / 256** | **0.103** | **0.75 sym** | **2.62** | **17.8 / 8.6** | **timing-slip (late-rising)** |
| m8_m32k2_rs159 | 748 | 2 / 320 | 0.079 | 0.67 sym | 2.30 | — | timing-slip → flips |
| m8_m32k2_rs127 | 598 | 2 / 320 | 0.187 | 0.83 sym | 1.42 | — | timing-slip → flips |

**m8_m16k3_rs159 within-frame symbol-error rate by quintile** (the smoking gun):

| | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| fixed grid (baseline) | 0.099 | 0.181 | 0.253 | 0.319 | 0.339 |
| trajectory bw 0.08 | 0.109 | 0.123 | 0.146 | 0.158 | 0.189 |

The fixed grid is near-recoverable at the frame start (9.9 % sym-error) and degrades monotonically
to 33.9 % by the frame end as the grid drifts ~193 samples (0.75 of N=256). The trajectory flattens
this profile — late-frame error collapses — confirming the failure is **timing**, not EQ or random
noise. The `gap` contrast separates correct (17.8) from wrong (8.6) symbols by ~2×, so the detector
is informative.

> **Caveat on the control:** `m8_ctrl_m16k1_rs191` has late/early ratio **0.10** (BER higher EARLY)
> and 7 EQ-clipped tones at the 0.05 floor (562 Hz + high-band fades). Its failure is **EQ/fading
> dominated**, not pure timing slip — which is why the trajectory barely moves its BER (0.0722 → 0.0716)
> and it stalls at 1/9 cw. Different physics from the late-rising M16K2/K3 rungs.

---

## 2. Rescue — K=3-generalized timing-trajectory front-end + errors-and-erasures

`WSEngineK3` extends `h5.SectionEngine` to **K=3** (3-tone combinations LUT) so the lottery rung can
run the trajectory front-end for the first time. Pass-1 greedy demod reproduces the official m8 baseline
**bit-exactly for all six sections** (incl. K=3: 0.10302 BER, 37/37 cw) — proving the engine is faithful.

Sweep per rung: trajectory ∈ {timing, freq} × bandwidth × 2-pass DD retiming × erasure metric {gap, lock}
× byte-agg {mean, min} × erase-frac {0, 0.25, 0.5}. Receiver-side guard = manifest CRC32-per-codeword
(verified semantics: message *i* = `(packed‖zero-pad)[i·rs_k:(i+1)·rs_k]`, validated 36/36 against the
known-good m32k2_rs159 sidecar).

### Best result per rung

| rung | net bps | base BER → best BER | cw failed before → after | byte-exact | CRC-verified | best config |
|---|---|---|---|---|---|---|
| m8_ctrl_m16k1_rs191 | 562 | 0.072 → 0.072 | 9 → **1** | no | — | timing bw0.1 frac0.25 gap/mean |
| m8_m16k2_rs159 | 701 | 0.107 → 0.076 | 36 → **22** | no | — | timing bw0.1 errors-only |
| m8_m16k2_rs191 | 843 | 0.105 → 0.089 | 31 → **31** | no | — | timing bw0.1 errors-only |
| **m8_m16k3_rs159** | **1052** | **0.103 → 0.059** | **37 → 7** (focused) | **NO** | no | **timing bw0.08 errors-only** |
| m8_m32k2_rs159 | 748 | 0.079 → 0.052 | 5 → **0** | **YES** | **YES** | timing bw0.1 errors-only |
| m8_m32k2_rs127 | 598 | 0.187 → 0.131 | 6 → **0** | **YES** | **YES** | freq bw0.1 frac0.5 gap/mean |

(The headline grid in the JSON stops at bw 0.1 → m16k3 = 10 cw; the **focused fine-bandwidth attack**
found bw 0.08 → **7 cw**, the true best.)

### Focused attack on m8_m16k3_rs159 (the 1052-bps headline)

Finer bandwidths + 2-pass DD + freq/timing × gap/lock × mean/min × frac{0,0.15,0.25}, all CRC-guarded:

| bw | raw BER | errors-only cw failed |
|---|---|---|
| 0.03 | 0.0750 | 30 |
| 0.05 | 0.0657 | 16 |
| **0.08** | **0.0587** | **7** ← best |
| 0.10 | 0.0592 | 10 |
| 0.12 | 0.0629 | 14 |
| 0.25 | 0.0739 | 22 |
| 0.50 | 0.0801 | 29 |

- Finer = better tracking, down to **bw 0.08** (0.05 under-tracks residual flutter, 0.03 fits noise).
- **Erasures do not help**: frac:0.25 (gap/mean) raises cw_failed 7 → 10. At BER 0.06 the `gap`
  reliability mislocalizes; the over-budget codewords have too many errors to flag cleanly.
- 2-pass DD retiming, freq-trajectory, and min-aggregation: none beat 7 cw. **miscorrected = 0** throughout.

**Why it misses (per-codeword byte-error distribution at bw 0.08):** median **42.6**, max **62**, against
RS(255,159) budget **t = 48**. **6 codewords sit over budget** (43–62 errors), clustered right at the
correction edge. The column interleave (37 cw) spreads the worst late-frame symbols across every codeword,
so the failures are uniform and near-threshold — exactly the regime erasures cannot save.

To close errors-only would require t ≥ 62 → **rs_k ≤ 131 → ~870 net bps < 934**. No path to a record here.

---

## 3. Conclusions for master9

1. **The 934 bps DQPSK record stands.** WS K=3 N256 cannot be rescued on this tape; its residual
   timing floor (0.059 raw BER) after the best trajectory exceeds RS even with the lottery RS(255,159).

2. **Self-tracking is mandatory and a post-hoc trajectory is a weak substitute for a pilot.** The
   trajectory recovers most of the slip (37→7 cw on the K=3 rung; 5→0 and 6→0 on the M32 rungs) but
   the data-derived greedy-offset estimate is noisy at high BER. DQPSK N512 wins because its
   **unmodulated mid-band pilot drives a per-symbol closed-loop timing correction** — fundamentally
   tighter than reconstructing timing from the data symbols. **Put a pilot in every master9 rung.**

3. **Short symbols beat long ones for this flutter channel** — already the m8 lesson (DQPSK N512 ≫
   N1024). The within-frame drift is ~0.75 symbol at N=256 over 3.4 s; halving N halves the per-symbol
   drift the front-end must absorb, and doubles the pilot update rate.

4. **K=3 tone density is a trap at this SNR.** 3 simultaneous tones shrink the inter-tone contrast
   margin; combined with high-band fading (7 EQ-clipped tones ≥ a deck null) the per-symbol error floor
   is irreducibly ~0.06. Prefer K≤2, or fewer wider-spaced tones, over chasing bits/symbol with K=3.

5. **Free wins available now without re-recording:** m8_m32k2_rs127 (598 bps) flips clean with the
   **freq-trajectory** (not the timing-trajectory the official combo used) + frac:0.5 erasures. master9
   decoders should sweep both trajectory kinds, not fix on `timing`.

6. **The CRC32-per-codeword guard works** — 0 silent miscorrections across the entire aggressive sweep,
   enabling miscorrection-safe erasure search. Keep per-codeword CRC tables in the master9 manifest.
