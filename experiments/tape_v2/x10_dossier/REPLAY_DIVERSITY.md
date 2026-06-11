# X10 Replay Diversity — pre-registration + machinery validation

**Candidate:** C-redundancy-architecture-3-replay-diversity
**Frozen:** 2026-06-12, BEFORE any tape9_run2 capture exists (verified absent from
`captures/` and the Voice Memos iCloud store at freeze time).
**Code:** `experiments/tape_v2/x10_c_redundancy_architecture_3_replay_diversity.py`
**Results:** `results/x10_replay_fusion.json`, `results/x10_replay_cw_<tag>.json`

## Status: CAPTURE PENDING — operator step not yet performed

The tape9_run2 capture does not exist. Everything else is built, validated, and
armed. The run1 side of the fusion is already decoded and cached.

## What this is

Per-codeword CRC32-guarded union across TWO playbacks of the existing master9
tape. Zero new mastering. Targets the residuals that within-capture branch-union
cannot fix on tape9_run1:

| rung | net bps | residual failed cw after within-run1 union (6 branches) |
|---|---|---|
| m9_m6_n256_rs191 | 2809 | **10**: [0, 4, 5, 6, 20, 27, 30, 35, 37, 38] |
| m9_m7_n256_p11_9000 | 2896 | **4**: [20, 23, 25, 26] |

(m4/m5 are already fixed within run1 by the extended-alpha branches — see
`x10_union_probe`; cross-checked bit-exact by this candidate's stage A.)

## PRE-REGISTERED DECISION RULE (frozen — do not soften after capture)

- **Per-capture failed set** F_c = codewords NOT CRC32-recovered by ANY branch
  within capture c. Branch set (FROZEN): `resampling_pll(bw=30)` + `ema` alpha in
  {0.5, 0.6, 0.65, 0.7, 0.8}; erase_frac = 0 only.
  - Amendment log: ema0.8 added 2026-06-12 before any run2 capture, after the
    run1 fidelity check showed unique m6 wins (union 17→10 cw). Run1 is prior
    evidence; the freeze deadline is the run2 capture.
  - Plan deviation: no late-window/gmd/pfft modules had landed as importable
    x10 modules at freeze time → not included. The plan's `x10_ensemble_decode`
    sanity decoder also does not exist; "standalone" is defined as
    within-capture branch union (this file's stage A), a strict superset of the
    production m9_decode sweep at erase 0.
- **Independence statistic:** pooled overlap
  `100 * sum(|F_run1 ∩ F_run2|) / sum(min(|F_run1|, |F_run2|))` over m6 and m7
  (rungs with both failed sets nonempty). Per-rung overlap also reported.
- **Decision:** ≥ 80% → errors RECORDED-IN, redirect campaign spend to TX rungs.
  ≤ 40% → errors PLAYBACK-BORNE, fund replay/multi-pass diversity as a standing
  branch. 40–80% → indeterminate, no spend redirection either way.
- **DIAGNOSTIC PASS sanity arms (all required, each failable):**
  run2 flutter_wrms within 1.5× of run1; run2 noise floor within 1.5× amplitude
  (|Δ dBFS| ≤ 3.52); all 6 m9-landed rungs (m0,m1,m2,m3,m4b,m8) orig-exact on
  run2 standalone; miscorrected_cw == 0 post-hoc vs manifest truth on BOTH
  captures; total CRC-acceptance trials × 2⁻³² < 1e-4 campaign budget.
- **RECORD PASS:** m7 residual cw → 0 across the two-capture union banks
  **2896 net bps as a multi-pass-category record** that does NOT supersede
  single-capture records (sidecar-CRC convention caveat). This categorization
  is part of the threshold, not a footnote.

## Machinery validation (done, 2026-06-12)

1. **Fidelity:** stage A on tape9_run1 reproduces the x10_union_probe per-branch
   failed sets EXACTLY (20/20 branch×section sets bit-identical), and the
   within-capture union matches its grand union (m6: 10, m7: 4; m4/m5/m8 and
   all m9-landed rungs orig-exact). miscorrected = 0, CRC conflicts = 0.
2. **End-to-end cross-capture fusion** on the only existing same-master pair —
   the sim dress pair (`m9_dress_s0/s1.wav`, channel_v2 profile=tape7 aac=False
   dg=0.58, seeds 0/1), rule NOT armed:
   - **m8_dense375 banked exact by the union**: seed0 fails 36/49 cw, seed1
     lands it; cross-capture union → 0 cw failed, orig-exact (sha256 verified).
     The union mechanism demonstrably recovers a rung one capture loses.
   - **Positive control for the RECORDED-IN arm:** pooled m6/m7 overlap = 100%
     (failed sets fully nested). Correct: the sim's N256 failure is structural
     (same reverb IR across seeds; only noise/flutter vary), i.e. "recorded-in"
     in sim terms — the statistic reads it as such.
   - **Sanity arms fire when they should:** the sim pair is flagged
     non-comparable (nf amplitude ratio 1.636 > 1.5) and m4b/m8-on-s0 fail the
     landed-rung regression — demonstrating the gate is failable.
   - Trials 4860 → false-accept bound 1.13e-6 (< 1e-4 budget). miscorrected = 0.

## Operator runbook (the only missing step, ~10 min)

1. Play the existing master9 tape once more (Dolby NR OFF, speaker ~55, start
   Voice Memos FIRST, ≥1 s lead-in, let the END chirp play out).
2. The file lands in `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/`.
   Convert: `ffmpeg -hide_banner -loglevel error -y -i "<file>" -ac 1 -ar 48000
   experiments/tape_v2/captures/tape9_run2.wav`

Then (each < 1 min after sync):

```
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
  experiments/tape_v2/x10_c_redundancy_architecture_3_replay_diversity.py \
  decode --capture experiments/tape_v2/captures/tape9_run2.wav --tag tape9_run2
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
  experiments/tape_v2/x10_c_redundancy_architecture_3_replay_diversity.py \
  fuse --tag-a tape9_run1 --tag-b tape9_run2 --label real_replay_pair --real-pair
```

`--real-pair` arms the decision rule; the fusion entry lands in
`results/x10_replay_fusion.json` under `pairs.real_replay_pair` with the
verdicts, overlap matrix, trial budget, and post-hoc miscorrection audit.

## Interpretation note (from the x10 forensics, for the adjudicator)

The dominant N256 impairment is previous-symbol acoustic echo/reverb ISI on the
750 Hz carrier — a playback-ROOM effect, not a tape-magnetics effect. But the
room, deck, speaker, and mic positions are likely identical across playbacks, so
echo-driven symbol errors may still be common-mode (→ high overlap) even though
they are not literally "recorded-in". If the verdict is RECORDED-IN, the honest
reading is "common-mode under identical playback geometry"; a deliberately
perturbed third playback (mic moved ~20 cm) would split that ambiguity. The
40%-arm (playback-borne) is only reachable by noise/flutter-realization errors,
which is exactly what makes the statistic informative.

Tier-2 coherent DFT averaging across captures: not implemented (pre-registered
as optional, only if the union leaves 1–2 stragglers on the real pair).
