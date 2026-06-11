# X10 Gate Report — master10 campaign (composed-superset receiver + 10-rung ladder)

Date: 2026-06-12 · Session: x10 master10 build/gate/dress
Decoder under test: `experiments/tape_v2/m10_decode.py` (the COMPOSED superset pipeline)
Master under test: `experiments/tape_v2/master10.wav` (master_id=`master10`, built by `m10_master.py`)

> **DO-NOT-PRINT HAZARD (standing):** `x10_master10.wav`, `x10_master10_draft.wav`,
> `x10_master10_manifest.json` are STALE artifacts of the REJECTED toneplan-v2
> candidate (B-aggr-03). The operator must NEVER print `x10_master10.wav`.
> The tape is **`master10.wav`** only.

---

## 1. Per-candidate gate outcomes (survivors AND negatives)

### Survivors — composed into m10_decode / laddered into master10

| candidate | gate evidence | verdict |
|---|---|---|
| **C-redundancy-architecture-1** (frontend ensemble union, pll30 + ema .4/.5/.6/.65/.7/.8) | `x10_ensemble_gate.json`: gate_met=TRUE; banked m9_m5 **2632** + m9_m4 **2338** orig-exact on tape9; 0 regressions across 4 historical captures; 0 miscorrections; CRC trial budget held | **SHIP** → m10_decode pass 1 |
| **B-cons-01** (late-window dc0 at N256) | `x10_late_window_tape9_run1.json`: banked m9_m6 **2809** (0/41) + m9_m7 **2896** (0/43) on tape9; 0 misc; regressions clean. Caveat at adjudication: truth-free argmin rode the +40 grid edge on every section | **SHIP** → m10_decode pass 2, grid WIDENED to [0..80] (see gate G5 below) |
| **A-fec-gmd-erasure** (carrier-class errors-and-erasures retry ladder) | `x10_gmd_erasure_tape9_run1.json`: recovered all 14 residual tape9 codewords on trial 1; 0 misc; ledger 2444 trials (fa ≈ 5.7e-07); unittest + m8/tape7/tape4 regressions clean | **SHIP** → m10_decode pass 3 (fill-only) |
| **B-aggr-05-dense2x** (375 Hz grid @ 187.5 sym/s) | `x10_b_aggr_05_dense2x_probe.json`: STEP-1 real-capture gate **GO** — P18 predicted byte-ER 0.029 vs thr 0.151 (5.2x), P21 0.079 vs 0.113 (1.43x, thin), P22 0.113 > 0.089 (predicted FAIL, diagnostic rung). `x10_b_aggr_05_dense2x_simgate.json`: sim gate **full REJECT** — pre-registered as *prediction-to-test* (the same sim axis falsely rejected the standing 2572 record: m9 sim failed m8_dense375 on 37/49 cells, real tape 0/49). Sections + sidecars built & self-checked orig-exact | **SHIP (frontier/stretch tiers)** → rungs r5/r6/r8 reused verbatim; twin r7 new |

### Negatives — gated OUT, not laddered (kept for the record)

| candidate | gate evidence | verdict |
|---|---|---|
| **B-aggr-03 toneplan-v2** (6 DQM sections) | `x10_b_aggr_03_toneplan_v2_pregate.json`: banker2896 g1=1/8, g5 mean-BER 0.81 vs cap 0.089 | **REJECT**. Its stale `x10_master10*.wav` artifacts are the DO-NOT-PRINT hazard |
| **bitload-N512** | `x10_bitload_census.json` adjudication: per-freq phase-dispersion census fails the pre-registered CP bounds (e.g. 750 Hz p(>15°) CP-upper95 0.091, fail) | **REJECT** — do not ladder |
| **C-margin-erasure** (margin-ranked erasures) | `x10_c_margin_erasure.json`: 0/45 residual codewords recovered — tape9 errors are *confident* errors; margin ranking can't find them | **NEGATIVE** — superseded by the structural carrier-class ladder |
| **freqdiff (m9a)** | m9: 37/37 cw failed on tape9 (per-pair channel-phase tilt 54–76° RMS > 45° QPSK boundary). Reproduced 37/37 by the composed pipeline this session | **DEAD** — omitted from master10 |
| **replay-diversity** | capture-blocked (single capture per tape available) | **OMITTED** — twins r4/r7 provide within-tape realization diversity instead (m4/m4b precedent; banks independently, no cross-section fusion) |

---

## 2. NEW blocking gates this session (m10) — all run BEFORE tape day, zero tape cost

### G1 — Build integrity (byte-identical reuse) — **PASS**
`m10_master.py` asserts at build time:
- r0/r5/r6/r8 packed payloads byte-identical to the already-self-checked
  `sidecars_x10_dense2x/*.bin` blobs (verbatim reuse — required because gzip
  embeds an mtime: a fresh `pack_payload` differs at byte 20; see §5 fixes).
- r9 ≡ r0: same packed sha256, same CRC32 table, identical first-frame audio
  (generator determinism check). All asserts hold on the final build.
- Every section (including NEW twins r4/r7) ships `crc32_codewords` in
  `master10_manifest.json` — the mandatory acceptance channel (tape7/tape4 precedent).

### G2 — Clean self-check (BLOCKING, deliverable 4) — **PASS**
`m10_decode.py master10.wav` (no channel): **10/10 byte-exact AND orig-exact**,
0 codewords failed on every rung, first-branch early-stop everywhere
(`resampling_pll30` for DQPSK, `hann256_skip0_ema0.7` for dense2x), 0
miscorrections, fa_bound 1.3e-07. → `results/x10_m10_results_selfcheck_nochan.json`

### G3 — Composed-superset regression, tape9_run1 (BLOCKING) — **PASS**
The three rx upgrades had only ever been validated SEPARATELY. The composed
pipeline (ONE run of m10_decode with `--manifest master9_manifest.json`)
re-decoded `captures/tape9_run1.wav`:

| m9 rung | net bps | composed outcome | winning path |
|---|---|---|---|
| m0_reprove934 | 934 | **0/16 ORIG-EXACT** | pass-1 pll30 |
| m1_thin159 | 1169 | **0/38 ORIG-EXACT** | pass-1 pll30 |
| m2_thin191 | 1404 | **0/40 ORIG-EXACT** | pass-1 pll30 |
| m3_dropnull9c | 1052 | **0/37 ORIG-EXACT** | pass-1 pll30 |
| m4_n256_rs159 | 2338 | **0/48 ORIG-EXACT** | pass-1 ema0.65 (single branch!) |
| m4b_n256_rs159_var | 2338 | **0/49 ORIG-EXACT** | pass-1 ema0.6 |
| m5_n256_rs179 | 2632 | **0/44 ORIG-EXACT** | pass-1 ema0.65 (single branch!) |
| m6_n256_rs191 | 2809 | **0/41 ORIG-EXACT** | pass-2 late-window (S32..S80 all 0/41 on ema0.6 base) |
| m7_n256_p11_9000 | 2896 | **0/43 ORIG-EXACT** | pass-2 late-window (ema0.6 S32+ and pll30 S16+ all clean) |
| m8_dense375 (canary config) | 2572 | **0/49 ORIG-EXACT** | pass-1 pll30 |
| m9a_freqdiff | 1169 | 37/37 FAIL | expected documented negative (dead candidate) |

**All 9 banked/rescued m9 outcomes reproduced orig-exact. 0 regressions,
0 miscorrections (truth-audit), 0 CRC rejects in 2196 CRC checks, fa_bound
5.1e-07 < 1e-4.** → `results/x10_m10_results_composed_regression_tape9_run1.json`
Notable: the widened ensemble alone (ema0.65) now single-branch-banks m4 AND m5
— the m9 production decoder (ema≤0.6) needed the union to do this.

### G4 — Composed-superset regression, m8_tape_mono_lossless — **PASS**
`m8_dq_p10n512_rs127`: 0/62, byte+orig-exact via pass-1 pll30, 0 misc.
→ `results/x10_m10_results_composed_regression_m8_tape.json`

### G5 — dc0 grid widening (promoted to BLOCKING) — **PASS, closed via widen-again annex**
Pre-registered widened grid [0,8,16,24,32,40,48,56,64,72,80]; rule: pass =
argmin interior OR edge improvement flattened (<10% relative), else widen
again and re-run.
- Composed tape9 run: truth-free EVM argmin chose **+80 (the new edge)** on
  every base/section. m6: edge EVM gain 9.5% (ema0.6) / 3.5% (pll30) → formal
  PASS by flattening. m7: 14.1% / 14.1% → **formal FAIL → widen-again triggered**.
- **Annex** (`x10_m10_dc0_annex.py` → `results/x10_m10_dc0_annex.json`),
  ema0.6 base, S ∈ {80,88,96,112,128,160,192} on tape9 m6+m7:
  EVM argmin is **INTERIOR at S≈112** (m6: 8.55°, m7: 6.60°, rising after);
  the operative metric **cw_failed is flat at 0 from S32 through S160** on both
  sections (m6 S192: 1 cw — the far tail finally degrades). No decode
  improvement was left at the +80 edge; beyond it the EVM statistic mostly
  tracks ISI-free energy fraction, not decision correctness.
- **Shipped configuration:** grid stays [0..80]; ALL scalar dc0 branches join
  the strictly-additive union, so argmin selection is NOT load-bearing — an
  edge-riding argmin cannot cost a codeword by construction.

### G6 — Strictly-additive semantics ENFORCED IN CODE — **PASS (by construction + audit)**
`_union_fill` only fills `None` slots (CRC-failing codewords); pass-2/pass-3
are offered only still-failing codewords; no code path can replace a
CRC-passing message. Truth-audit across every run this session:
**miscorrected_cw = 0 everywhere.**

---

## 3. Dress rehearsal (NOT a gate — m9 convention) — summary

`sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`, seeds 0+1,
full master10.wav end-to-end, full composed decode. Pre-registered context:
the faithful sim is 5–8x PESSIMISTIC vs real captures and fully REJECTS the
dense2x family; N256 rungs expected to look bad here.

Headline (see `results/x10_m10_dress_rehearsal.json` and MASTER10_SHIP_REPORT.md §4):
- **r0 canary LANDS on both seeds** (s0: via widened bank ema0.8 + union/ladder;
  s1: clean pll30) — the 2572 config survives the pessimistic sim under the
  composed receiver (the m9-era receiver had FAILED this config in sim on s0).
- **r9 tail canary LANDS on both seeds** — on s0 the carrier-class ladder
  rescued all 31 residual codewords (a live end-to-end demonstration of pass-3
  at heavy degradation, 0 miscorrections).
- N256 rungs (r1–r4): FAIL both seeds (cw 33–41 of ~44) — matches the m9 dress
  precedent (m9 sims rejected N256; real tape landed them).
- dense2x rungs (r5–r8): FAIL both seeds (all/nearly-all cw) — matches the
  pre-registered sim REJECT (prediction-to-test).
- 0 miscorrections on all seeds; CRC/fa budgets held.

---

## 4. Reproducibility block

```
# build (deterministic; LADDER_SEED=20260612 logged in manifest)
python3 experiments/tape_v2/m10_master.py                  # -> master10.wav + manifest + sidecars_m10/

# blocking self-check (G2)
python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/master10.wav --out-tag selfcheck_nochan

# composed-superset regression (G3, G4) — chunked <8 min/invocation
python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/captures/tape9_run1.wav \
  --manifest master9_manifest.json --out-tag composed_regression_tape9_run1 --sections <chunk>
python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/captures/m8_tape_mono_lossless.wav \
  --manifest master8_manifest.json --out-tag composed_regression_m8_tape --sections m8_dq_p10n512_rs127

# dc0 widen-again annex (G5 closure)
python3 experiments/tape_v2/x10_m10_dc0_annex.py

# dress rehearsal (seeds 0,1; channel = tape7 profile, aac=False, dg=0.58)
python3 experiments/tape_v2/x10_m10_dress.py gen --seed 0   # and --seed 1
python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/captures/m10_dress_s0.wav --out-tag dress_s0 --sections <chunks>
python3 experiments/tape_v2/x10_m10_dress.py rollup
```
All runs `OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2`. The decoder itself is
deterministic (no RNG); the only RNG is the dress channel (seeds 0/1, logged).

---

## 5. Code fixes made during the build (honest log)

1. **gzip mtime non-determinism:** `h9_payload_codec.pack_payload` embeds the
   gzip mtime — a fresh pack of the SAME bytes differs at byte 20 from the x10
   sidecar blobs. Fix: verbatim-reuse sections load the original packed blob
   from `sidecars_x10_dense2x/` (asserted to unpack to the expected cass slice,
   same length). Without this, r0 would NOT have been byte-identical to the
   validated anchor and its CRC table would have silently differed.
2. **Compressible-offset trap:** first-pick fresh offsets (4096/12288) landed in
   a highly-compressible cass region → r1 packed to ~2.7 KB (15 codewords,
   11.6 s) instead of the planned ~7.7 KB. Re-picked fresh offsets in
   incompressible regions (r1=43008, r2=18432, r3=20480, r4=51200) restoring
   the planned section sizes (44/41/44/44 codewords, 32.6/30.6/30.5/30.5 s).

## 6. Known harness limitations

- The faithful sim's diffuse-reverb/N256 axis remains unanchored (5–8x
  pessimism); dress FAILs on N256/d2x are predictions-to-test, not verdicts.
- The truth-free decision-EVM statistic decouples from decode correctness at
  very large window shifts (annex S192: EVM still moderate while cw_failed
  rises) — safe in our architecture only because branch selection is
  non-load-bearing (union of all scalar branches).
- `lw_pll30` scalar branches were ineffective on m6 (41/41 at every shift; the
  PLL-warped stream breaks wholesale on P10 N256 — known m9 behavior, harmless
  under CRC guard; ema base carried the rescue).
- Sounder `snr_db` per-tone fields can be absent on some captures (null in the
  m9 tape9 results); m10_decode tolerates it.
