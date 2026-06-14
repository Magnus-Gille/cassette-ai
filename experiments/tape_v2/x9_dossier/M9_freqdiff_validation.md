# M9a — Frequency-Differential DQPSK: implementation + validation

**Date:** 2026-06-10 · **Branch:** deepdive-3-overnight · **Author:** IMPL-FREQDIFF
**Module:** `experiments/tape_v2/x9_freqdiff.py` (`FreqDiffDQPSKScheme`)
**Harness:** `experiments/tape_v2/m9_freqdiff_validate.py` → `results/m9_freqdiff_validate.json`
**Spec:** MASTER9_PLAN §1.3 (M9a) + C_design R-LOT — the master9 lottery rung.

---

## 0. What was built

A drop-in frequency-differential DQPSK scheme for the master9 M9a lottery rung. It
mirrors the `h4_dqpsk.DQPSKScheme` public surface exactly (`modulate(bits)->float32
audio with preamble`, `demod(win_audio, nd, ...)->(bits, diag)`, plus
`bits_to_quadrants / quadrants_to_bits / nsym_data / freqs / data_idx / pilot_idx /
gross_bps / name`), so `m9_master` / `m9_decode` can use it without any caller
changes — verified: **NONE missing for drop-in** (API parity check).

**PHY (matches the plan line for M9a):** P11 N512 sp8 on the proven 750 Hz grid,
carriers `{750,1500,2250,3000,3750,4500,5250,6000,6750,7500,8250,9000}` Hz, pilot
**4500 Hz** (mid-band, unmodulated, window-drift tracking only). Chain = the 11
non-pilot carriers; carrier 0 (750 Hz, band edge) is the per-symbol phase
reference. **10 adjacent-carrier diff-pairs × 2 bits = gross 1875 bps, net 1169 bps
at RS(255,159)** — identical to the plan. The two pairs straddling the 3750 Hz deck
null (pairs 3 and 4) are flagged erasure-eligible and excluded from the common-
rotation estimate.

**The data mapping** encodes 2 bits as the phase difference BETWEEN ADJACENT
CARRIERS within one symbol: `bits[pair j] = quadrant(angle(c[i,k]·conj(c[i,k-1])))`,
vs the proven time-differential record's same-carrier symbol-to-symbol difference.

### Timing-immunity derivation (full statement in the module docstring)
Cassette flutter is a resampling trajectory `y(t)=x(t-τ(t))`, so a tone at f gets a
measured DFT phase `-2π·f·τ_i` for symbol i.
- **Time-differential** (record): `d=angle(c[i,k]·conj(c[i-1,k])) = dphi - 2π·f_k·Δτ`
  — the timing term `-2π·f_k·Δτ` is proportional to the symbol-to-symbol timing
  CHANGE Δτ; it does **not** vanish, and is worse at high f_k. This caps the record.
- **Frequency-differential** (M9a): both carriers share the SAME symbol's τ_i, so
  `d=angle(c[i,k]·conj(c[i,k-1])) = dphi + dθ_chan - 2π·SPACING·τ_i`. Because
  `f_k-f_{k-1}=SPACING` is the **same 750 Hz for every adjacent pair**, the timing
  term `dphi_timing = -2π·SPACING·τ_i` is a **CONSTANT PER ADJACENT PAIR** (depends
  only on SPACING and the common per-symbol τ_i, not on k). Common symbol-timing
  jitter therefore appears as one identical rotation shared by all pairs in a
  symbol, removed by the band-edge reference. The fast per-symbol Δτ wander that
  caps the time-differential record does not map onto the decision.

### Two implementation facts that mattered
1. **Per-pair gap, not a single SPACING.** The chain skips the mid-band pilot, so
   the 3750 Hz→5250 Hz pair spans **1500 Hz (2×SPACING)**, not 750 Hz. The
   deterministic band-edge anchor `R_ij = 2π·pair_gap_j·lo_i/FS` uses the actual
   per-pair gap (computed receiver-side from the preamble + pilot drift; no truth).
   With a single SPACING constant that one pair decoded at chance (BER pinned at
   0.10); with the per-pair gap, no-channel BER is exactly 0.
2. **One known training symbol per frame.** Frequency-differential needs the static
   per-pair channel-phase tilt `β_j = θ_chan(f_hi)-θ_chan(f_lo)`, which over a
   750 Hz step reaches >100° on this channel and cannot be bootstrapped blind from a
   cold start (chicken-and-egg at chance). A single leading symbol with KNOWN q=0
   (no truth — the value is fixed) measures β_j directly. Cost ≈ 0.5 % (1 symbol of
   ~200/frame) — the same +1 overhead symbol/frame the proven h4 scheme already has.

---

## 1. Validation results (frozen seeds, all logged)

### Test 1 — no-channel modulate→demod, 3 random payloads → **PASS (BER exactly 0)**

| seed | BER | byte-exact |
|---|---|---|
| 0 | 0.00e+00 | True |
| 1 | 0.00e+00 | True |
| 2 | 0.00e+00 | True |

The scheme is internally consistent: modulate→demod is lossless on a clean signal.

### Test 2 — sim_v2 `channel_v2(profile='tape7', aac=False)`, seeds 0–2, RS(255,159)

| seed | raw BER | cw failed | static-tilt RMS (deg) | common-rot σ (deg) | byte-exact |
|---|---|---|---|---|---|
| 0 | 0.432 | 52/52 | 76.2 | 20.2 | False |
| 1 | 0.445 | 52/52 | 54.4 | 19.1 | False |
| 2 | 0.547 | 52/52 | 73.3 | 18.0 | False |

net = 1169.1 bps · 52 codewords · mean BER 0.475 · **0/3 byte-exact**.

**This is the honest, dossier-predicted result, not a decoder bug.** The measured
**per-pair static channel-phase tilt over the 750 Hz gap has RMS 54–76°** (individual
pairs up to 175° — diagnostic captured in the JSON), far past the QPSK 45° decision
boundary. This is exactly the failure mode C_design R-LOT and R6 §2 predict:
*"frequency-differential trades timing-immunity for sensitivity to the frequency-
selective channel tilt between adjacent carriers 750 Hz apart"* and *"the sim cannot
faithfully vet a new constellation mapping."* The scheme is provably correct (Test 1
BER 0; within-frame genie-β decode reaches BER 0.047), but the channel's frequency-
selective tilt — dominated by the reverb-FIR comb and slow wow, and varying
frame-to-frame — exceeds the QPSK margin on the sim. **This is the information the
M9a lottery ticket buys** (plan §6: *"if it fails, we learn: channel tilt over
750 Hz exceeds QPSK margin, quantifying coherence bandwidth"*). Per the plan, M9a is
a HOLD/lottery rung that the sim cannot bless — a sim failure is expected and does
not disqualify it for a real-tape probe, where the true 750 Hz coherence-phase is
unknown (P1 stationary-null map is designed to measure it).

### Test 3 — THE HEADLINE timing-immunity proof (jitter only, no channel noise/EQ)

Inject ONLY a 5–23.4 Hz resample wobble (the validated `x9_flutter_gate` band) at a
range of timing-RMS levels, with **no other impairment**, and compare F-DQPSK
against the proven time-differential h4 DQPSK on **identical audio** (matched 750 Hz
N512 grid, matched payload, both gross 1875 bps — the only difference is the data
mapping). **34 µs is the measured real m8 5–23.4 Hz residual band-RMS** (R6 Table A).

| jitter RMS (µs) | **F-DQPSK** BER | **F-DQPSK** byte-exact | time-diff BER | time-diff byte-exact |
|---|---|---|---|---|
| 0  | 0.0000 | 3/3 | 0.0000 | 3/3 |
| 10 | 0.0000 | 3/3 | 0.00004 | 3/3 |
| 16 | 0.0000 | 3/3 | 0.0034 | 3/3 |
| 24 | 0.00005 | 3/3 | 0.0232 | 2/3 |
| **34 (real m8)** | **0.0038** | **3/3** | **0.0598** | **0/3** |
| 50 | 0.1019 | 1/3 | 0.1214 | 0/3 |

**IMMUNITY PROVEN = True.** At the real m8 residual jitter level (34 µs),
frequency-differential stays **3/3 byte-exact at BER 0.0038**, while
time-differential collapses to **0/3 byte-exact at BER 0.0598 — a 16× higher raw BER
and a total RS-decode failure**. The divergence is monotone and clean: F-DQPSK BER is
≥6× lower than time-diff at every level ≥16 µs, and only breaks down at 50 µs (well
past the real residual). Because the two schemes ran on byte-identical audio differing
only in the data mapping, this isolates the timing-immunity effect as the cause — the
quantitative proof of the M9a claim: **common per-symbol timing jitter cancels in the
adjacent-carrier difference.**

---

## 2. Interpretation for master9 / master10

- **M9a is correctly a lottery rung.** It is immune to the exact impairment that caps
  the 934 bps record (Test 3), but it is gated on a *different* channel property —
  the 750 Hz coherence-phase tilt — that the sim renders catastrophic (Test 2) and
  that only a real tape (or the P1 stationary-null probe) can measure. This matches
  the plan's HOLD-by-rule grading and P≈0.30 estimate exactly.
- **If M9a lands on real tape, the master10 architecture pivots** away from
  time-differential and timing jitter stops mattering (the paradigm result). If it
  fails, the per-pair static-tilt RMS (54–76° in sim; to be re-measured on the real
  capture) directly quantifies the 750 Hz coherence bandwidth for master10 carrier
  placement — the failure-information the ticket is bought for.
- **What would make M9a real-viable** (master10 follow-ups, not in scope here):
  a measured per-capture H(f)-phase de-rotation (P1 sounder probe gives this), or a
  tighter carrier spacing so the per-pair tilt shrinks below the QPSK margin (the
  R2 caveat that ~150–200 Hz spacing is now supportable on lossless captures), or a
  per-frame pilot/training de-rotation richer than the single reference symbol used
  here.

---

## 3. Reproduce

```
python3 experiments/tape_v2/x9_freqdiff.py          # self-describe + PHY check
python3 experiments/tape_v2/m9_freqdiff_validate.py # all 3 tests -> results JSON
```

- Module: `experiments/tape_v2/x9_freqdiff.py`
- Harness: `experiments/tape_v2/m9_freqdiff_validate.py`
- Results: `experiments/tape_v2/results/m9_freqdiff_validate.json`
- Seeds: Test 1 {0,1,2}; Test 2 {0,1,2}; Test 3 {0,1,2} × jitter {0,10,16,24,34,50} µs.
  Jitter band 5–23.4 Hz (matches `x9_flutter_gate`); all seeds set + logged.
- `src/real_channel_sim.py` untouched (FROZEN). `h4_dqpsk.py` untouched.
