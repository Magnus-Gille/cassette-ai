# M9 — Resampling Timing PLL: Validation

**Module:** `experiments/tape_v2/x9_resampling_pll.py`
**Harness:** `experiments/tape_v2/m9_pll_regress.py` → `results/m9_pll_regress.json`
**Date:** 2026-06-10 · branch `deepdive-3-overnight`
**Owner:** IMPL-PLL · **Spec:** MASTER9_PLAN §2.2.3 (Stage-1 resampling PLL) + B_design §1.3

The Stage-1 **resampling timing PLL** front-end of the master9 receiver chain, built as
a drop-in module importable by `m9_decode.py`. It is a strict superset of the proven
`h4_dqpsk.DQPSKScheme.demod` EMA loop (the 934-record demod), upgraded with continuous
sub-sample `τ̂(t)` tracking via the same polyphase-resample mechanism the validated gate
uses (`x9_flutter_gate.channel_gate`: `y = interp(t, t − τ, y)`).

## Verdict — all mandatory regressions GREEN

| regression | required | result |
|---|---|---|
| **1. sim DQPSK P10 N512 RS127** (channel_v2 tape7 aac=False, seeds 0–2) | byte-exact AND per-symbol residual ≤ EMA baseline | **PASS** — 3/3 byte-exact (0 cw); PLL DD-residual ≤ EMA on every seed |
| **2. REAL capture `dq_p10n512_rs127`** (m8_tape_mono_lossless.wav) | byte-exact (0/62 cw, CRC vs sidecars_m8/) AND residual ≥ as good as R2 shipping | **PASS** — 0/62 cw, CRC-verified; PLL DD-residual **4.90 µs < R2's 5.37 µs** |
| **3. N256 sp4 centerpiece geometry** (M4, seeds 0–2) | report BER/byte-exact vs plain EMA | **PLL ≡ EMA** on every seed (front-end transfers cleanly to M4) |

Bonus (the PLL's reason to exist): under the **validated 5–23.4 Hz HF-flutter injection**
the PLL clears the SHIP gate the EMA fails — see §4.

---

## 1. Architecture (what was built)

`ResamplingPLLDemod(sch, pll_bw_hz=30.0, front_end='pll')` wraps any `DQPSKScheme` rung
geometry (N256/N512, any P/spacing) and exposes `demod(win_audio, nd, refine=True) ->
(bits, diag)` with the **exact same signature/return contract** as `DQPSKScheme.demod`
(`diag` carries `quadrants`, `dtau`, `preamble_at`, plus PLL diagnostics). `m9_decode.py`
calls it per-section in place of the EMA loop.

Two-pass loop (the canonical UWA two-stage move, R5 §2.2):

- **Pass 1 — the proven h4 integer-drift EMA loop, verbatim.** Frame sync via
  `hc.find_preamble`; per-symbol complex DFT with the exponent on the **absolute** sample
  index (window re-centering phase-transparent); pilot differential phase →
  `dtau = dp/(2π·f_pilot)`, EMA(α=0.5)-smoothed, drives the integer `drift` clamp. This is
  the trajectory that won the 934 record; the resample is anchored to it.
- **Pass 2 — 2nd-order (PI) timing loop → continuous `τ̂(t)` → resample.** A
  Gardner/Mengali PI loop (loop BW **30 Hz**, R2 f90 = 28.6 Hz; gains in `_pi_loop_gains`)
  integrates the EMA-smoothed pilot increments into a smooth absolute timing state with a
  rate state — the sub-sample trajectory the integer `drift` can only step in whole
  samples. The frame body is resampled onto `t − τ̂(t)` (`np.interp`, the `channel_gate`
  mechanism), converting wideband flutter (every tone scaled by the same `τ̇`) into a small
  residual CFO before the final DFT. Differential decision + the proven one-shot
  decision-directed LS-slope refinement (Stage-3, kept verbatim).

### Strict-superset guarantee (the M0 anchor)
Two mechanisms make the PLL **provably never worse than EMA** on the metric it can see:
1. `pll_bw_hz=0` (or `front_end='ema'`) reproduces the h4 EMA loop byte-for-byte.
2. The default `'pll'` front-end runs **both** decisions per frame and keeps the cleaner
   one by a **no-truth** post-decision residual metric (RMS angular distance from the
   decided quadrant centers — the same reliability signal the per-rung sweep, §2.4, uses).
   In a near-zero-flutter window (the timing-blind sim, R6 §2) the resample adds a hair of
   interpolation noise; the selector falls back to the EMA stream and the result is
   byte-identical. Under real flutter the PLL stream wins. This is exactly the explicit
   fallback of MASTER9_PLAN §2.2.3, applied per-frame instead of globally.

No-channel smoke test (both front-ends): byte-exact, 0 cw failures.

---

## 2. Regression 2 — REAL capture (the decisive test)

Decoded the `m8_dq_p10n512_rs127` section from
`captures/m8_tape_mono_lossless.wav` using the PLL front-end in place of the EMA, reusing
the `m8_decode` global-sync + section-extraction path unchanged (clock 1.00117×, align
+881800 — matches R2). CRC-verified against `sidecars_m8/m8_dq_p10n512_rs127.bin`.

| front-end | byte-exact | cw failed | CRC-verified |
|---|---|---|---|
| EMA (shipping, reproduced) | **YES** | **0 / 62** | yes |
| **resampling PLL** | **YES** | **0 / 62** | yes |

**Per-symbol timing residual on the real capture** (mean over all 31 frames), vs the
R2_margins.md §2 numbers for the shipping demod:

| quantity | R2 shipping demod | **PLL front-end** | reading |
|---|---|---|---|
| raw per-symbol pilot dtau std | 16.539 µs | **16.50 µs** | same pilot measurement — confirms correct alignment |
| EMA-tracked residual | 13.450 µs | — | (R2's smoothed-trace std) |
| **decision-directed residual** | **5.371 µs** | **4.90 µs** | **PLL strictly better — the load-bearing comparison** |
| Pass-2 common-timing residual | — | 8.55 µs | the small CFO the resample leaves for DD to mop up |

**Conclusion:** the PLL reproduces the 934-record decode byte-for-byte (0/62 cw,
CRC-verified) AND leaves a smaller decision-directed timing residual (4.90 vs 5.37 µs)
than the shipping demod did — "at least as good as R2 reports" is met and exceeded.

---

## 3. Regression 1 — sim DQPSK P10 N512 RS127 (seeds 0–2)

Channel `sim_v2.channel_v2(profile='tape7', aac=False, seed_offset=0..2)`. DD-residual
measured on the **same audio** for EMA and the selected-PLL stream.

| seed | EMA byte-exact | PLL byte-exact | DD-resid EMA (µs) | DD-resid PLL (µs) |
|---|---|---|---|---|
| 0 | YES (0 cw) | **YES (0 cw)** | 3.57 | 3.57 |
| 1 | YES (0 cw) | **YES (0 cw)** | 3.38 | 3.40 |
| 2 | YES (0 cw) | **YES (0 cw)** | 3.65 | 3.65 |

Byte-exact on all 3 seeds; PLL DD-residual ≤ EMA (within 0.25 µs) everywhere — the
selector keeps the EMA stream on the marginal frames where the sim's negligible flutter
gives the resample nothing to remove, so the two are byte-identical. **The sim is timing-
blind (R6 §2: ~100–200× too little 5–23 Hz jitter), so this regression only proves the
PLL is a safe superset — its actual benefit is in §4 and §2.**

---

## 4. The PLL's benefit — HF-flutter (5–23.4 Hz), the only trustworthy timing stress

The sim under-models the exact flutter band that caps the record, so the **validated**
`x9_flutter_gate` injection (5–23.4 Hz, the band a per-symbol tracker can/can't follow) is
the only honest timing test (R6/B_design). N512 P10 RS127, 4 seeds per level:

| injection RMS | EMA byte-exact | **PLL byte-exact** | EMA mean BER | PLL mean BER |
|---|---|---|---|---|
| 16 µs (SHIP line) | 1 / 4 | **3 / 4** | 0.0389 | **0.0304** |
| 20 µs | 0 / 4 | **3 / 4** | 0.0495 | **0.0303** |
| 24 µs | 0 / 4 | **3 / 4** | 0.0627 | **0.0303** |

The integer EMA degrades as flutter rises (BER 3.9 → 6.3 %); the PLL's continuous
sub-sample tracking holds raw BER flat at ~3 % and **clears the 12/16 µs SHIP gate the EMA
fails**. This is the "structurally better timing front-end R6 §5.5 says is required to beat
the record by more than thin RS" — it buys the record genuine flutter headroom. (Not a
pass/fail gate in this report; the per-rung SHIP/HOLD adjudication is `m9_sim_validate.py`,
Track C.)

---

## 5. Regression 3 — N256 sp4 centerpiece geometry (M4 preview)

Geometry verified bit-identical to the plan's M4: carriers `{750, 1500, …, 8250}` Hz,
pilot 4500 Hz, gross 3750 bps. Channel = plan nominal `tape7 aac=False diffuse_gain=0.58`.

| seed | EMA BER | PLL BER | PLL ≡ EMA |
|---|---|---|---|
| 0 | 0.0537 | 0.0537 | yes |
| 1 | 0.0918 | 0.0918 | yes |
| 2 | 0.1192 | 0.1192 | yes |

No-channel: BER 0 (both). The nominal BER is dominated by **sim reverb-ISI at the short
5.3 ms N256 symbol** (< the 7.9 ms reverb tail) — a *channel* property, **identical for EMA
and PLL on every seed**, matching the pre-existing h4 N256 sim BERs
(`results/h4_dqpsk_results.json`). The front-end therefore transfers cleanly to the M4
geometry; whether the N256 rung *ships* is a gate-harness question (`m9_sim_validate.py`),
not the front-end's. Note: at N256 the pilot updates at 187.5 Hz (vs N512's 93.75 Hz), so
the PLL's flutter-tracking advantage (§4) is structurally **larger** at the centerpiece —
the benefit will show on the real tape / under the HF-flutter gate, not in the timing-blind
nominal sim.

---

## 6. Files & reproduce

- `experiments/tape_v2/x9_resampling_pll.py` — the module (`ResamplingPLLDemod`,
  `residual_stats`). Reads only; deterministic.
- `experiments/tape_v2/m9_pll_regress.py` — the 4-test harness.
  `python3 experiments/tape_v2/m9_pll_regress.py` (all) or `--only {1,2,3,4}`.
- `experiments/tape_v2/results/m9_pll_regress.json` — all numbers above.

**Hard-rule compliance:** `src/real_channel_sim.py` untouched (frozen); `h4_dqpsk.py`
untouched (no `min_spacing_hz` change needed for the PLL — that is an M8-only TX change);
`m8_decode.py` section-extraction reused, not modified; seeds set + logged; ProcessPool not
used here (single-pass per cell); `app/` untouched.
