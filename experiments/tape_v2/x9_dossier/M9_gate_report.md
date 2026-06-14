# M9 Gate Report — master9 pre-registered SHIP/HOLD/REJECT adjudication

**Date:** 2026-06-10 · **Branch:** deepdive-3-overnight · **Phase:** Gate runner (integration + gates)
**Spec:** `MASTER9_PLAN.md` §4 (FROZEN gates) · **Harness:** `experiments/tape_v2/m9_sim_validate.py`
**Results:** `results/m9_sim_validate_run1.json` (+ `..._partial_run1.json` checkpoint)
**Anchor record:** 934 net bps (DQPSK P10 N512 sp8, RS127, 0/62 cw on the real m8 tape)

---

## 0. Headline

The pre-registered 5-gate matrix (616 cells: 11 rungs × 56 cells, 8 nominal + 8 dg-pessimism
+ 4 HF-flutter + 4 combo + 32 diagnostic seeds) ran clean in 12.4 min through
`sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`. **No gate, threshold, or
rung parameter was tuned.** One harness limitation is documented (the diagnostic clock-offset
cell, §5) — it touches only diagnostic cells, never a SHIP gate.

**Verdict summary (sim-adjudicated against the FROZEN §4.2 rule):**

| rung | net bps | g1 nom | g2 dg65 | g3 hf12µs | g4 combo | g5 byte-floor | **verdict** | plan expected |
|---|---|---|---|---|---|---|---|---|
| **M0** reprove-934 | 934 | 8/8 ✓ | 8/8 ✓ | 4/4 ✓ | 4/4 ✓ | 0.000/0.151 ✓ | **SHIP** | SHIP ✓ |
| M1 thin-159 | 1169 | 7/8 ✓ | **4/8 ✗** | 4/4 ✓ | 4/4 ✓ | 0.007/0.113 ✓ | **HOLD** | SHIP |
| M2 thin-191 | 1404 | **4/8 ✗** | 3/8 ✗ | 2/4 ✗ | 2/4 ✗ | **0.331/0.075 ✗** | **REJECT** | SHIP/cliff |
| **M3** drop-null-9c | 1052 | 8/8 ✓ | 6/8 ✓ | 4/4 ✓ | 4/4 ✓ | 0.000/0.113 ✓ | **SHIP** | SHIP ✓ |
| M4 N256 **CENTERPIECE** | 2338 | **1/8 ✗** | 0/8 ✗ | 0/4 ✗ | 0/4 ✗ | 0.839/0.113 ✗ | **REJECT** | SHIP-iff-12µs |
| M4b N256 variance copy | 2338 | 0/8 ✗ | 0/8 ✗ | 0/4 ✗ | 0/4 ✗ | 0.855/0.113 ✗ | **REJECT** | SHIP-iff-12µs |
| M5 N256 rs179 | 2632 | 0/8 ✗ | 0/8 ✗ | 0/4 ✗ | 0/4 ✗ | 0.909/0.089 ✗ | **REJECT** | SHIP-cand |
| M6 N256 rs191 | 2809 | 0/8 ✗ | 0/8 ✗ | 0/4 ✗ | 0/4 ✗ | 0.964/0.075 ✗ | **REJECT** | HOLD-likely |
| M7 N256 P11-9000 | 2896 | 0/8 ✗ | 0/8 ✗ | 0/4 ✗ | 0/4 ✗ | 0.916/0.089 ✗ | **REJECT** | HOLD |
| M8 dense-375 (code-gated) | 2572 | 5/8 ✗ | 1/8 ✗ | 2/4 ✗ | 2/4 ✗ | 0.118/0.113 ✗ | **REJECT** (HOLD-by-rule) | HOLD-by-rule |
| M9a freq-differential | 1169 | 0/8 ✗ | 0/8 ✗ | 0/4 ✗ | 0/4 ✗ | 0.995/0.113 ✗ | **REJECT** (HOLD-by-rule) | HOLD/lottery |

**Sim-blessed headline: M0 (934, the record, reproven) + M3 (1052 bps, 1.13×).**
M1 (1169) is a *near-miss HOLD* — robust at the nominal dg, it fails only the dg=0.65 pessimism
gate. M2 (1404) sits on the N512 RS cliff in the sim. The N256 centerpiece (M4–M7) is decisively
reverb-ISI-limited **in the sim**; this is a finding, not an embarrassment — and crucially the
sim's N256 reverb-ISI scaling is the one axis with **no real anchor** (see §3). M8/M9a are
HOLD-by-rule (sim cannot bless spacing<750 Hz or a new frequency-differential mapping).

---

## 1. Integration (Task 1) — DONE, all 11 rungs byte-exact + orig-exact

The three implementer tracks were reconciled to the plan's interface. **No API mismatch
remained** — the delivered `m9_decode.py` already calls `ResamplingPLLDemod(sch, pll_bw_hz=30,
front_end='pll').demod(win, nd)` and `FreqDiffDQPSKScheme.demod(win, nd, refine, eq_tilt)`,
which is the actual (Track-A) interface, per the plan's "code to the interface, Gate phase
reconciles" instruction. The no-channel self-check is **GREEN**:

```
python3 m9_master.py            # builds master9_draft.wav 482.4s (8.04 min), 11 rungs + P1 + P2
python3 m9_decode.py master9_draft.wav
  -> byte-exact (packed) 11/11   orig-exact (unpacked) 11/11
     every DQPSK rung via resampling_pll, M9a via freqdiff, 0 cw failed
```

All 11 rungs — including M9a (freqdiff) and M8 (dense-375 via `min_spacing_hz=375`) — decode
byte-exact AND orig-exact through the full common receiver chain at high SNR. **No integration
fix was required; the modules were already mutually consistent.** Frozen-file constraints hold:
`real_channel_sim.py` clean, `h4_dqpsk.py` carries ONLY the sanctioned backwards-compatible
`min_spacing_hz` kwarg (default 562.0 reproduces the frozen assert bit-identically), `app/` and
the R*/A/B/C/MASTER9_PLAN dossier files untouched.

---

## 2. Gate harness (Task 2) — `m9_sim_validate.py`, FROZEN protocol

`m9_sim_validate.py` is a literal transcription of `MASTER9_PLAN.md §4.2`. It runs each rung as
a standalone per-section clip (LEAD + front sounder + frames@gaps + TAIL, via
`h4_dqpsk.build_section` — the exact window geometry the proven receiver and the VALIDATED
`x9_flutter_gate` use), pushes it through the channel variant for the cell, and decodes it with
the **full master9 receiver sweep**: resampling-PLL (default) + pilot-EMA α∈{0.4,0.5,0.6}, RS
errors-only + errors-and-erasures @ erase-frac∈{0,0.25,0.5}, **CRC32-per-codeword guard ON**,
keeping the CRC-verified byte-exact winner. The payloads, manifests, and CRC tables are the
actual master9 tape content (`master9_manifest.json` + `sidecars_m9/`), so the gate tests the
exact bytes that would be burned.

### 2.1 Channel config (FROZEN, §4.0)
- **Nominal:** `channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`.
- **dg-pessimism:** `diffuse_gain=0.65`.
- **Seeds:** nominal **8 {0..7}**; each stress axis **4 {0..3}**. All logged.

### 2.2 Stress envelope (FROZEN, §4.1)
- **HF-flutter (the centerpiece):** the VALIDATED `x9_flutter_gate.gate_jitter` 5–23.4 Hz
  band injection (Butterworth band-pass white noise resampled into the audio) at the **12 µs
  SHIP line** + 16 µs / 20 µs headroom diagnostics. This is the only axis that emulates the
  sim's documented 100–200× HF-flutter blind spot; it is independently validated to reproduce
  the real m8 N512-pass / N1024-fail split.
- **Combo:** SNR −2 dB AND flutter_residual_frac 0.30 (gate 4).
- **Diagnostics (reported, NOT SHIP gates):** HF-flutter 16/20 µs, SNR −4 dB, clock ±0.15%,
  reverb-τ ×{0.5,1.5}, tape4 (quieter take).

### 2.3 SHIP / HOLD / REJECT rule (FROZEN, §4.2 — transcribed verbatim)
SHIP iff: (1) ≥7/8 nominal byte-exact, (2) ≥6/8 dg-0.65 byte-exact, (3) ≥3/4 HF-flutter-12µs,
(4) ≥3/4 combo, (5) mean nominal **byte**-error-rate ≤ 0.6·(255−k)/(2·255). HOLD if it passes
1,2,5 but fails timing gate 3 or 4. REJECT if it fails nominal (1) or the byte floor (5). M8
(spacing<750 Hz) and M9a (freqdiff) are **HOLD-by-rule** regardless of sim outcome.

---

## 3. Per-rung adjudication (Task 3) — the honest findings

### 3.1 M0 reprove-934 → **SHIP** (the abort-check passes)
8/8 nominal, 8/8 dg-0.65, 4/4 HF-flutter-12µs, 4/4 combo, byte-floor 0.000 ≤ 0.151. §4.3 is
explicit: *"M0 reprove — SHIP; if it fails the gate, the gate is mis-scaled — abort & re-anchor
on P2."* It SHIPs cleanly, so **the gate is correctly scaled** and the whole matrix is trustworthy.
M0 even clears the 16 µs AND 20 µs HF-flutter headroom cells (4/4 each) — the resampling-PLL
front-end buys the record genuine flutter headroom beyond the 12 µs line (the EMA-only loop
clears 16 µs only 1/4; the harness keeps the cleaner of PLL/EMA per frame, so it gets the PLL win).

### 3.2 M3 drop-null-9c → **SHIP**
8/8 nominal, 6/8 dg-0.65, 4/4 / 4/4 timing, byte-floor 0.000 ≤ 0.113. Dropping the 3750 Hz deck
null (R2 §0: that one carrier threw 35 % of all raw errors on the real tape) makes M3 strictly
easier than M0 — **0 cw failed on all 8 nominal seeds**. This is a clean, defensible new record
at **1052 bps (1.13×)**, fully sim-blessed.

### 3.3 M1 thin-159 → **HOLD** (near-miss; robust nominal, fails dg-pessimism only)
7/8 nominal (only seed 7 fails, with 2 cw), 4/4 / 4/4 timing, byte-floor 0.007 ≤ 0.113 — but
**4/8 at dg=0.65** (< 6/8). The dg-sensitivity sweep (§3.7) shows M1 is **4/4 at every dg ≤
0.58** and only degrades at 0.62 (3/4) and 0.65 (2/4). So M1's nominal is solid; it is the
dg-0.65 pessimism gate — defending the lossless-recalibration uncertainty — that costs it SHIP.
**Per the §4.2 rule this is HOLD** (passes 1,5 + timing, fails 2). On the real tape M1 is very
likely a clean record (RS159 t=48 has 48 byte-corrections per codeword); the sim withholds the
SHIP stamp only because the dg uncertainty band could, pessimistically, eat the thinner margin.

### 3.4 M2 thin-191 → **REJECT** (the N512 cliff, located)
4/8 nominal, 3/8 dg-0.65, byte-floor **0.331 ≫ 0.075**. This is the cliff-bracket doing its job.
The per-seed cw pattern is decisive:

```
N512 grid, nominal dg=0.58, per-seed cw_failed:
  M0 RS127 (t=64):  0 0 0 0 0 0 0 0        <- huge margin
  M1 RS159 (t=48):  0 0 0 0 0 0 0 2        <- 1 marginal seed
  M2 RS191 (t=32):  0 0 26 4 0 0 38 37     <- t=32 cannot absorb the hard-seed bursts
  M3 RS159 dropnull: 0 0 0 0 0 0 0 0        <- null removed -> clean
```

The sim places the **N512 RS cliff between RS159 (t=48) and RS191 (t=32)**. M2's RS191 byte-margin
floor (cap 0.075) is the tightest of the N512 rungs and the hard seeds (s2/s6/s7) blow past it.
The bracket M1↔M2 has *located the cliff in one shot* — exactly its stated purpose (§4.3).

### 3.5 M4–M7 (N256 short-symbol push) → **REJECT** (reverb-ISI wall in the sim)
All four N256 rungs (incl. the M4b variance copy) fail nominal decisively: M4 1/8, M4b/M5/M6/M7
0/8. Raw byte-error-rate ~0.84–0.96. **This is channel physics, not a decode bug** — proven three
ways:
1. **The receiver is sound.** M4 decodes **byte-exact through the channel at dg=0.30 (0 cw) and
   dg=0.45 (0 cw)**, then collapses at dg≥0.55 (§3.7). A broken decoder cannot decode clean at
   low dg.
2. **N512 control passes.** M1 (RS159, same payload size, N512) passes clean at dg=0.58 while M4
   (RS159, N256) fails — the only difference is the symbol length.
3. **Monotone and steep in dg** (the diffuse-reverb gain): the 63 ms diffuse-reverb tail corrupts
   a *larger fraction* of the shorter N256 window (R6 §1d). The M4b variance copy (different cass
   slice) fails identically → not payload-specific.

The M4 failure even survives reverb-τ ×0.5 (45–48/48 cw): halving the modeled tail still leaves
N256 dead at dg=0.58. So **within the entire defensible lossless-branch dg band (0.55–0.62) and
the ±50% reverb-τ stress, the sim says N256 is reverb-ISI-limited.**

> **The load-bearing caveat (R6 §2 / §4.0 / §5.3-step5):** the sim's N256 reverb-ISI scaling is
> the *one axis with no real anchor.* The real m8 tape carried **no N256 DQPSK rung** — only the
> N512 record (which the sim reproduces 4/4 at dg=0.58, real 0/62 cw). R6's own verdict table
> rates reverb-ISI *"honest-ish — geometry right, may be slightly short — treat τ as a point
> estimate."* And the C_design thesis for the N256 bet is that it wins on the **timing axis**
> (half the symbol period → 187.5 Hz pilot update vs 93.8 Hz → tracks flutter *better*), which is
> the axis the sim is *blind* to and which the HF-flutter gate tests — but the rung never reaches
> the HF-flutter gate because it dies on nominal reverb-ISI first. **The sim's N256 verdict is a
> sim-prediction the real tape must settle.** The N256 ISI mechanism is real (it is the FROZEN
> channel's measured diffuse tail), so the prediction is not baseless — but its *magnitude* at the
> short window is uncalibrated, and could be pessimistic.

### 3.6 M8 dense-375 → **REJECT in sim, HOLD-by-rule**; M9a freq-diff → **REJECT in sim, HOLD-by-rule**
- **M8** (P22 @ 375 Hz, the one frozen-code-gated rung): 5/8 nominal, 1/8 dg-0.65 — borderline,
  and some cells nearly decode (1/49 cw at clock −0.0015; 4/4 at reverb-τ×0.5). But spacing
  375 Hz < 750 Hz is **HOLD-by-rule** (R6 §5.4: sim is blind to flutter-ICI <750 Hz, so it
  cannot bless this rung; carried only to gather real-tape flutter-ICI data for master10).
- **M9a** (frequency-differential): 0/8 — fails at chance, exactly the dossier-predicted outcome
  (per-pair static channel-phase tilt over the 750 Hz gap has RMS 54–76°, far past the QPSK 45°
  boundary; the sim cannot vet this mapping). **HOLD/lottery by rule** — its value is the
  *timing-immunity paradigm* (proven on a jitter-only channel: at 34 µs it stays byte-exact while
  time-differential collapses), which only a real tape can claim. The sim failure does NOT
  disqualify it for a real-tape probe.

### 3.7 dg-sensitivity sweep (the mandated re-anchor diagnostic, §5.3-step5)
4 seeds {0..3}, nominal channel (no stress), across the defensible dg band:

```
M1 RS159:  dg .50→4/4  .55→4/4  .58→4/4  .62→3/4  .65→2/4   (robust to 0.58; pessimism bites)
M2 RS191:  dg .50→4/4  .55→2/4  .58→2/4  .62→1/4  .65→1/4   (on the cliff across the band)
M4 N256:   dg .50→1/4  .55→0/4  .58→0/4  .62→0/4  .65→0/4   (dead across the whole defensible band)
```

The dg anchor is correctly placed: **M0 (= the real N512 record) reproduces the real 0/62-cw PASS
at dg=0.58 (and 0.65), 4/4** — the one anchorable real point. M1/M2's degradation is honest RS-cliff
physics. M4's death is the unanchored N256 reverb-ISI prediction (recoverable only at dg≤0.45, well
below the lossless-branch anchor).

---

## 4. Code fixes made during the gate phase (logged per the mandate)

The integration self-check and the gate matrix ran without revealing a genuine receiver/decode
bug — the implementer tracks were already mutually consistent and the no-channel self-check was
green on first run. **No gate, threshold, or rung parameter was tuned to pass** (the gates are a
verbatim transcription of §4.2). The harness itself required two construction fixes while it was
being written (before any gate run), both internal to `m9_sim_validate.py`:

1. **reverb-τ stress cell wiring.** First draft passed `reverb_tau_scale=` through
   `sim_v2.channel_v2(**kw)` → `real_channel`, which does **not** accept that kwarg (the
   `reverb_tail_tau_ms` knob lives in `params['spectral_contamination']['scaling']`, unreachable
   via `sim_overrides`). Fixed by a dedicated `_channel_reverb_tau` path that deep-copies the
   FROZEN params, scales `reverb_tail_tau_ms`, and reproduces the exact `aac=False` nominal path
   (`real_channel_sim` only read + copied, never edited). Affects diagnostic cells only.
2. **per-rung clip plumbing.** First draft had a dead `if False` branch and a confused
   `_clip`/`_build_clip` return contract. Rewritten so `run_cell` builds one standalone section
   via `build_section` and decodes it at the local frame starts (no global chirp / `align`),
   matching `x9_flutter_gate.run_cell`'s proven geometry.

Both were caught by the pre-flight smoke tests (single-cell M0 nominal + all channel variants)
before the full matrix launched; neither touches the gate definitions or any rung parameter.

---

## 5. Known harness limitation (honest)

The **diagnostic clock-offset cell** (`d_clock_±0.0015`) is a *proxy*: a per-rung clip has no
global chirp pair, so the harness models the ±0.15% static deck-clock by `resample_poly` before
the channel and `resample` back to nominal length after (a stand-in for the decoder's real
chirp-resync, §2.1). This proxy injects a little interpolation noise the real chirp-resync would
not, so a few clock-offset diagnostic cells show small cw failures on otherwise-clean N512 rungs
(e.g. M2 9/40 at +0.0015). **It affects ONLY diagnostic cells — none of the 5 SHIP gates use a
clock offset** — so it does not move any verdict. The full-tape `m9_decode.py` removes static
clock correctly via the global chirp (verified: the no-channel self-check is byte-exact and the
real m8 decode recovered clock 1.00117× exactly). Flagged so master10 does not over-read the
clock-offset diagnostic column.

---

## 6. What ships, what holds, what the tape still buys

**Sim-blessed master9 headline (rungs that SHIP all five gates): M0 (934, reproven) + M3
(1052 bps, 1.13×).** Banked floor if the deck/levels behave.

**Real-tape upside the sim withholds but does not refute:**
- **M1 (1169, 1.25×)** — HOLD only on the dg-0.65 pessimism gate; robust at nominal dg and almost
  certainly a clean real record. The single most-likely *actual* new record.
- **M2 (1404, 1.50×)** — on the N512 RS cliff in the sim; the real tape decides whether RS191's
  t=32 margin survives the real (vs dg=0.58-pessimistic) channel.
- **M4–M7 (2338–2896, 2.5–3.1×)** — REJECT in the sim's *unanchored* N256 reverb-ISI prediction.
  These are the centerpiece bet, and the sim cannot honestly grade them: it has no N256 anchor,
  and the C_design rationale (N256 wins on the timing axis the sim is blind to) is untested by a
  rung that dies on nominal reverb-ISI first. **Keep them on the tape** — they are exactly the
  question master9 exists to answer, and the two probes (P1 null map, P2 re-anchored 5–23.4 Hz
  jitter + IMD knee) hand master10 the numbers to size N/RS correctly next time.

**HOLD-by-rule (information, never headline):** M8 (dense-375 flutter-ICI datum), M9a
(frequency-differential paradigm probe).

**Recommendation for the burn.** The tape is built and self-checks byte-exact end to end. The
gate's sim-blessed floor is modest (M0+M3), but the **honest expected real record is M1 at
1169 bps (1.25×)** with genuine N512 upside to M2 (1404) and an open-but-uncalibrated N256 shot
(M4, 2338). Burn the full ladder per the plan — the sim's N256 REJECT is a *prediction to test*,
not a reason to cut the centerpiece, and §5.3-step5 mandates re-anchoring the HF-flutter gate
against P2(a) on the real capture before claiming any N256 verdict either way.

---

## 7. Reproducibility

```
# full pre-registered matrix (616 cells, 4 workers, ~12 min)
python3 experiments/tape_v2/m9_sim_validate.py --workers 4 --tag run1 --profile tape7

# results
results/m9_sim_validate_run1.json            # final verdicts + diagnostics
results/m9_sim_validate_partial_run1.json     # per-cell checkpoint (resumable)
```

Seeds: nominal {0..7}, stress {0..3}, all logged in every cell record. Channel:
`sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)` nominal, dg=0.65 pessimism.
HF-flutter: `x9_flutter_gate.gate_jitter` 5–23.4 Hz, 12 µs SHIP line. Receiver: resampling-PLL +
EMA-α sweep + errors-and-erasures, CRC32-per-codeword guard ON. FROZEN files verified clean
(`real_channel_sim.py`, R*/A/B/C/MASTER9_PLAN dossier, `app/`); `h4_dqpsk.py` carries only the
sanctioned `min_spacing_hz` kwarg.
