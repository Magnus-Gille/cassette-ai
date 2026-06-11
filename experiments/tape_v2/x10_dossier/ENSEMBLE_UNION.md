# ENSEMBLE_UNION — production CRC32-guarded per-codeword union receiver

**Candidate:** C-redundancy-architecture-1-frontend-ensemble-union
**Verdict: GATE MET (5/5).** m5 banked orig-exact at **2632 net bps** (new best,
+60 bps / +2.3% over the standing 2572 record) and m4 orig-exact at 2338, both
in the blind production decoder, with **0 regressions** across the full named
4-capture suite, **0 miscorrections** post-hoc, and 3,736 / 400,000 CRC trials
spent campaign-wide.

Evidence class: REAL captures only (tape9_run1, m8_tape_mono_lossless,
tape7_run1, tape4_run1). No sim anywhere. Deterministic — no RNG.

## What it is

Productionization of the validated prototypes `x10_union_probe.py` +
`x10_union_verify_orig.py` into a manifest-driven decoder following the
m9_decode.py pattern (`am2.global_sync_and_resample` → per-section demod →
RS+CRC), with one architectural change: **the per-section winner-take-all of
`m9_decode._rs_merge_guarded` is replaced by a per-codeword
accept-any-CRC-verified-branch fusion** across a widened timing-front-end bank.
`erase_frac = 0` everywhere (on tape9, erasures only ever hurt).

- Code: `experiments/tape_v2/x10_c_redundancy_architecture_1_frontend_ensemble_union.py`
  (decoder) + `..._union_gate.py` (pre-registered gate evaluator).
  *Naming deviation, stated:* the plan said `x10_ensemble_decode.py`; the
  binding candidate rules restrict new files to
  `x10_c_redundancy_architecture_1_frontend_ensemble_union*.py` — rules win.
  Result files keep the plan's names.
- Results: `results/x10_ensemble_decode_{tape9_run1, m8_tape_mono_lossless,
  tape7_run1, tape4_run1}.json`, `results/x10_ensemble_gate.json`.

## Front-end bank (13 branches, proven-first order for early-stop)

`x9_resampling_pll.ResamplingPLLDemod` with:
pll_bw ∈ {30, 15, 45} Hz; pilot-EMA α ∈ {0.40 … 0.85 step 0.05}.
Order: pll30, ema.50, .60, .65, .70, .80, .40, .45, .55, .75, .85, pll15, pll45.
Early stop: once every codeword of a section is CRC-recovered, remaining
branches are skipped (recorded in `branches_skipped`). `--no-early-stop`
available.

**Registration hook:** external experiments (x10_late_window, x10_gmd,
x10_pfft, …) become union branches via `provide_union_branches(sch, sec)` +
`UNION_ADMITTED = True`, or `register_branch_provider(fn)` at runtime.
**Uniform admission requirement (campaign-wide):** a branch enters the
production bank only after passing this full 4-capture regression suite with 0
regressions and a clean post-hoc miscorrection check.

## Results — tape9_run1 (full re-decode, all 11 sections)

| rung | net bps | union cw_failed | exact (orig) | accepted by |
|---|---|---|---|---|
| m9_m0_reprove934 | 934 | 0/16 | **YES** | pll30 ×16 |
| m9_m1_thin159 | 1169 | 0/38 | **YES** | pll30 ×38 |
| m9_m2_thin191 | 1404 | 0/40 | **YES** | pll30 ×40 |
| m9_m3_dropnull9c | 1052 | 0/37 | **YES** | pll30 ×37 |
| m9_m4_n256_rs159 | 2338 | 0/48 | **YES** (was 5/48 FAIL in m9) | pll30 ×22, ema.60 ×21, ema.65 ×5 |
| m9_m4b_n256_rs159_var | 2338 | 0/49 | **YES** | pll30 ×47, ema.60 ×2 |
| **m9_m5_n256_rs179** | **2632** | **0/44** | **YES** (was 2/44 FAIL in m9) | pll30 ×30, ema.60 ×12, ema.65 ×2 |
| m9_m6_n256_rs191 | 2809 | 10/41 | no | best union so far (was 28 in m9) |
| m9_m7_n256_p11_9000 | 2896 | **3/43** | no | pll30 ×38 + pll15 ×1 + ema.50 ×1 (was 5 in m9, 4 in probe) |
| m9_m8_dense375 | 2572 | 0/49 | **YES** | pll30 ×49 |
| m9_m9a_freqdiff | 1169 | 37/37 | no (expected; m9 delegate path) | — |

The widened bank's new members earned their seats: ema0.65 contributed the
last 5 (m4) / 2 (m5) codewords no proven front-end could decode, and pll15
recovered one m7 codeword beyond every other branch. m7 is now **3 codewords
from 2896 bps** (failed idx 23, 25, 26) — the structurally-different branches
(late-window, GMD, pFFT) are the designed next union members for its
common-mode floor; m6's 10-cw floor (idx 0,4,5,6,20,27,30,35,37,38) is
dc0-dominated per the forensics and likely needs the dc0 fix, not more
timing diversity.

## Regression suite (0 regressions)

| capture | named rungs | check | result |
|---|---|---|---|
| tape9_run1 | m0/m1/m2/m3/m4b/m8 + union-banked m4/m5 | orig_exact | **8/8 PASS** |
| m8_tape_mono_lossless | m8_dq_p10n512_rs127 | orig_exact | **1/1 PASS** (0/62 cw, first branch) |
| tape7_run1 | m16_rs111_8k, m16_rs191_8k, m32_rs95_4k | byte_exact | **3/3 PASS** (proven m6 WS delegate) |
| tape4_run1 | ws_test2k, ws_llm24k | byte_exact | **2/2 PASS** (proven m4 WS delegate) |

## Miscorrection / false-accept audit

Post-hoc truth check (sidecar bytes, scoring only): **0 miscorrections** on all
4 captures. Additionally `crc_checked == crc_accepted` (1050/1050 on tape9):
no RS output that reached the CRC was ever rejected — the guard never had to
fire on this data, and no false-accept occurred.

**Campaign CRC-trial ledger** (each RS-decode attempt offered to a CRC check =
one 2^-32 false-accept trial): probe 1408 + verify 368 (prototypes, documented
constants) + tape9 1898 + m8 62 + tape7/tape4 0 (no CRC tables; proven non-CRC
paths) = **3,736 of the pre-registered 400,000 budget**; expected false-accepts
≈ 8.7e-7. Reruns accumulate via `cumulative_rs_attempts` in each results file.

## Record convention (declared, per pre-registration)

Per-codeword CRC32 acceptance uses the manifest sidecar table
(`sec["crc32_codewords"]`) — truth-derived receiver-side information; only the
whole-payload CRC32 is in-stream. All record claims from this receiver inherit
that sidecar caveat — the **same convention as the standing 2572 bps record**
(m9_decode used the same table). Under that convention: **new best
byte-exact/orig-exact rate = 2632 net bps (m9_m5_n256_rs179, tape9_run1).**

## Honest caveats

- The 2632 claim is receiver-side recovery of an already-recorded tape; the
  sidecar-CRC convention above applies (identical to the 2572 record's claim).
- Per-frame-select and majority-vote fusions from the probe were NOT
  productionized (probe showed union dominates them); the hook covers future
  structurally-different branches instead.
- m6 (2809) and m7 (2896) remain unrecovered: timing-front-end diversity alone
  saturates at 10 and 3 failed cw respectively — consistent with the forensics
  finding that dc0 ISI is common-mode across timing front-ends.
- tape7/tape4 regressions run the proven WS decoders (no CRC tables exist in
  those manifests); their miscorrection check is implied by byte-exactness.
- The freqdiff section is delegated to the m9 path unchanged (37/37 failed, as
  in m9); its ledger contribution is counted conservatively (3 erase fracs).

## Reproducibility

```
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
  experiments/tape_v2/x10_c_redundancy_architecture_1_frontend_ensemble_union.py tape9   # 25 s
  ... m8    # 5 s
  ... tape7 # 88 s
  ... tape4 # 123 s
python3 experiments/tape_v2/x10_c_redundancy_architecture_1_frontend_ensemble_union_gate.py
```
Deterministic (no RNG). python 3.10.13, numpy 2.2.6, scipy 1.15.3 (as logged).
Sync: tape9 clock 1.0017003 (matches m9_results_tape9_run1.json exactly).
