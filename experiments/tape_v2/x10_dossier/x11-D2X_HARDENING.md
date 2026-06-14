# x11-D2X_HARDENING — hardening the d2x decode path (critic gaps a+b)

**Date:** 2026-06-12 · **Code:** `x11_d2x_erasure.py` · **Gate report:** `results/x11_d2x_gate_report.json`
**Verdict: GATE MET (G1+G2+G3 all pass).** 23/23 synthetic marginal d2x sections rescued to
orig-exact, 0 miscorrections, FA bound 1.03e-5, 0 regressions on the 4-capture suite.

## Why this campaign

x10's critic gaps: (a) the carrier-class errors-and-erasures ladder had NEVER succeeded on a
d2x section (validated only N512/N256) — no proven rescue path if master10's d2x rungs
(r5 3362 / r6+r7 4910 / r8 5791) land marginal on the real tape; (b) the dress rehearsal never
exercised the AAC axis nor a realistic constant clock offset (~0.17%). This campaign closes
both, synthetically, before the burn.

## Pre-registered gate (frozen in the module docstring before any run)

- **G1** Extend the ladder to the d2x layout; on >=20 synthetic marginal d2x sections
  (master10's own r5–r8 waveforms through `sim_v2.channel_v2` variants INCLUDING `aac=True`
  and constant clock offsets {+0.10%, +0.17%, +0.25%}), rescue >=30% of sections the stock
  composed decode (`m10_decode._decode_section`, verbatim) leaves at 1–8 failed codewords;
  0 miscorrections post-hoc; ledger within FA budget.
- **G2** 0 regressions on tape9 / m8 / tape7 / tape4.
- **G3** Window-plan sensitivity table (hann256_skip0, rect128_skip64, + 4 new pre-registered
  variants); identify the best truth-free selection statistic.

## Design (all new code in `x11_d2x_erasure.py`; frozen files imported read-only)

1. **Mini-master** `x11_d2x_synth.wav` (168 s): bit-identical slices of master10.wav (head with
   chirp0+sounder, the r5–r8 block, chirp1 tail); every cut asserted to land in exact silence;
   per-section sha256 recorded; byte identity asserted with `np.array_equal`.
2. **Channel variants**: clock offset by polyphase resample of the whole tape, then
   `channel_v2(profile='tape7', aac, seed, sim_overrides={'diffuse_gain': dg})`. The faithful
   sim (dg≈0.58) kills d2x outright (the known 5–8x-pessimistic axis; dress was 90/90 dead), so
   dg was calibrated by a frozen truth-blind SCREEN rule → dg*=0.35, dg2=0.40.
3. **Stock** = `m10_decode._decode_section` verbatim (ensemble union + its own d2x ladder).
   **Marginal** = stock-final 1–8 failed cw.
4. **x11 rescue** (pre-registered order, CRC32-guarded strictly-additive fill-only):
   r-a replicate stock pass-1 union (fidelity-checked) → r-b **d2x shift-window sweep**
   ({hann256_skip0, rect128_skip64} × {ema0.7, pll30} × global shifts ±16/±32(/±48) + a
   per-carrier decision-EVM-argmin stitched branch — the proven dc0 late-window mechanism
   extended to every d2x carrier) → r-c the **frozen** `m10_decode._erasure_ladder` over the
   enlarged branch pool, pool-ranked by a truth-free consensus-distance statistic.

## Results

### Stock grid → marginal inventory (52 cells, 4 rungs each)

| dg | behaviour of stock composed decode |
|---|---|
| 0.35 (dg*) | mostly clean; seed-0 cells leave r7 at 1 and r8 at 8–17 failed → 6 marginal |
| 0.38 (A1) | the composed-level cliff: r6 1–10, r8 6–12 failed → 9 marginal |
| 0.37 (A1) | r7 6 / r8 2–4 failed → 4 marginal (stopped at inventory >=20 per the A1 stop rule) |
| 0.40 (dg2) | mostly dead (14–64 failed cw); only seed-1 r7 stays in band → 4 marginal |

**Amendment A1** (`results/x11_d2x_amendment_a1.json`): the pre-registered dg*+dg2 grids gave
only 10 marginal sections because the composed pipeline is far stronger than the single-front-end
screen. The inventory was extended at dg 0.38 then 0.37 (the screen rule's own 0.025-step cliff
refinement, 2-decimal cell-id constraint), recorded **before any rescue ran** — selection on
stock outcomes only; G1 thresholds untouched. Final inventory: **23 marginal sections**
(r6×6, r7×9, r8×8) covering aac {off,on} × clk {0, +0.10%, +0.17%, +0.25%} × seeds {0,1}.
r5 (the 4-weak-carrier-dropping banker rung) never went marginal — 0 failed even at dg 0.40.

### G1 — rescue: 23/23 (100%, gate needed >=30%)

Every marginal section reached 0 failed cw + byte-exact + **orig-exact (sha256)**; pass-1 union
replication matched the stock ladder targets on all 23 (fidelity check). Attribution:

- **shift-window sweep filled 591 cw (91%)** — the dc0 late-window mechanism generalizes to the
  whole d2x carrier set; late hann (+32) and the per-carrier argmin-stitched branches do most of it;
- **frozen carrier-class erasure ladder finished 59 cw in 14/23 sections** — the ladder's
  first-ever d2x successes (critic gap (a) closed in both directions: the ladder DOES work on
  d2x, and a stronger new path now sits in front of it). The stock pipeline's own ladder had
  also already accepted 2378 cw across the stock runs (559 on marginal sections), so the d2x
  ladder path is now exercised end-to-end at three depths.
- 0 miscorrections post-hoc vs ground truth across all accepted codewords.

### G2 — regressions: 4/4 clean

tape9 composed (9 banked rungs + freqdiff 37/37-fail negative, fresh sync): all match.
m8 0/62 orig-exact. tape7 (m16_rs111_8k, m16_rs191_8k, m32_rs95_4k) and tape4 (ws_test2k,
ws_llm24k) through the unchanged production decoders: byte-exact/cw-failed identical to the
x10 reference (`results/x11_d2x_regression.json`).

### G3 — window-plan sensitivity (23 marginal sections, ema0.7 base)

| plan | mean BER | mean cw failed |
|---|---|---|
| **hann256_skip0** (primary) | **0.0334** | **30.4** |
| hann256_skip0_S+32 | 0.0357 | 36.0 |
| rect128_skip96 (rect, +32 late) | 0.0462 | 62.5 |
| rect128_skip112 | 0.0581 | 68.7 |
| rect128_skip64 (manifest alternate) | 0.0625 | 66.2 |
| rect128_skip32 | 0.0838 | 69.6 |

The soft Hann window dominates on marginal d2x channels; the manifest's rect128_skip64
alternate is near-useless there (it only earns its keep on clean tapes). Best truth-free
selection statistic: **crc_pass_count** (top-1 agreement with lowest-BER plan 91.3%,
Spearman 0.80). The EVM statistics rank-correlate better (rms 0.86) but lose top-1 (26%)
because hann vs hann_S+32 are nearly tied — use crc_pass_count to pick plans, EVM only to
order shift candidates within a plan (which is exactly how the sweep already uses it).

### Ledger / FA accounting

258,339 RS attempts, 44,225 CRC checks, 0 CRC rejects, 44,225 accepts across selfcheck /
screen / stock / rescue / windows. FA bound = 44,225 × 2⁻³² = **1.03e-5 < 1e-4** budget.
Truth-audited miscorrections: 0 (stock and rescue).

## What this changes for the master10 burn

- A proven d2x rescue path now exists: if r5–r8 land at 1–8 failed cw on the real capture, the
  x11 sweep + ladder chain converted 23/23 such sections synthetically — including under AAC
  and constant clock offsets up to +0.25%.
- The two unexercised dress axes (AAC, constant clock) are now exercised: clk-only selfcheck
  decodes exactly at all three offsets (global chirp sync absorbs it); aac=True changes
  marginality only mildly.
- r5 (3362 net) looks unusually robust — it survived every cell including dg 0.40 where r6–r8 died.

## Honest caveats

1. **Entirely synthetic.** The channel is sim_v2 on master10's own waveforms; the sim is
   known 5–8x pessimistic on the reverb/timing axis and its failure mechanism (diffuse reverb)
   may differ from a real capture's (deck notches, azimuth, dropouts). 100% rescue at this
   synthetic cliff is an upper bound, not a real-tape promise; the >=30% gate is what's banked.
2. **Amendment A1 was required** — the pre-registered inventory protocol under-produced
   (10 < 20). It was recorded truth-blind before any rescue ran and gate thresholds were not
   touched, but it is a protocol deviation and is flagged as such.
3. The marginal band is razor thin (dg 0.35 clean → 0.40 dead), i.e. d2x failure on tape is
   likely binary-ish; the rescue path matters exactly in the narrow in-between regime, which is
   also where master9's real rungs historically landed (the 2338→2896 rescues).
4. r5 never went marginal, so rescue is validated on r6/r7/r8 layouts only (P21/P22; P18
   untested in-rescue — it is also the most protected rung).
5. `crc_rejects=0` campaign-wide: every successful RS decode also passed CRC, so the FA bound
   (counted on CRC checks) is conservative; no near-miss miscorrection was ever observed.
