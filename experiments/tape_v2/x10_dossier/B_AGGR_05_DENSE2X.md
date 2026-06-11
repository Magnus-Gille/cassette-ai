# B-aggr-05-dense2x — time-densification 2x: 375 Hz grid at 187.5 sym/s

Candidate slot: the funded frontier (target 4400–5100 net). Status: **STEP-1 GATE = GO**
(real-capture evidence), master10-dense2x built + self-checked, sim gates logged as
pre-registered prediction-to-test (REJECT, the documented m9 false-reject fingerprint).
**Awaiting physical tape pass.**

## 1. Pre-registered gate (frozen in `x10_b_aggr_05_dense2x_probe.py` before any measurement)

- metric: predicted mean byte-ER for P18/RS(255,127) at the dense2x receiver geometry,
  best-18-of-22 carriers by measured SER, `byte_ER = mean_k(1-(1-SER_k)^4)`
- GO = byte_ER ≤ 0.6·(255−127)/(2·255) = **0.15059**; NO-GO = abort, zero tape spent.
- Tape-claim discipline (pre-registered, inherited from the brief): any record/net-bps claim
  requires sha256 orig-exact vs manifest; byte-exact-but-not-orig-exact = geometry validation
  only, NO rate claim. ALL tape outcomes additionally require the anchor rung to reprove
  2572 orig-exact, else the tape pass is void (`tape_pass_valid` in the decoder output).
  miscorrected_cw must be 0 post-hoc; CRC trial ledger false-accept bound < 1e-4.

## 2. STEP-1 probe — how it measures the target geometry on REAL tape

`m9_m8_dense375` on tape9_run1 uses the EXACT dense2x tone plan (23 tones, 750+375k Hz,
pilot 4875) at N512. Re-demodulating that real capture at stride 256 with the dense2x
windows measures per-carrier DQPSK SER at the target geometry with the ~4.8 dB window-energy
loss and echo-tail concentration physically included. Differentials alternate
across-boundary (real phase transition + prev-symbol echo = the dense2x decision case;
n=2279/carrier) and within-symbol (no-ISI baseline). Truth used for scoring only.

### Finding 0 (design-breaking, caught pre-tape): the plan's literal receiver is non-orthogonal
At Nw=128 the 375 Hz spacing is exactly **1 DFT bin**; the proven Hann window leaks −6 dB
per neighbor (h4's `(spacing·Nw)%N==0` assert only guarantees *rect* orthogonality).
Measured: 49–63 % SER (kept as negative control). **TX is unaffected.** Fix = receiver
window only, both validated on the real capture:

| rx window | guard | mean SER (best α) | per-carrier character |
|---|---|---|---|
| hann128_skip64 (plan-literal) | 1.33 ms | 0.487 @ α0.8 | broken (ICI) — negative control |
| **hann256_skip0 (primary)** | soft (Hann taper) | **0.0385 @ α0.7** | mids 0–1 %, dc0 35.5 %, 4500 Hz 18.8 %, 5625 Hz 12.4 % |
| rect128_skip64 (alternate) | 1.33 ms hard | 0.0582 @ α0.7 | same structure |

### Key measurements (hann256_skip0, α=0.7, tape9 GOLD)
- per-carrier SER (data idx 0..21 = 750..9000 Hz, pilot 4875 excluded):
  `[.355, .000, .014, .001, .001, .033, .009, 0, 0, .000, .188, 0, .124, .002, 0, .045, .001, .007, .032, .003, .007, .022]`
- Bad carriers are the KNOWN ones: 750 Hz (prev-symbol echo ISI: LS echo I/C −3.2 dB at the
  symbol-leading window, monotone to −13.1 dB sliding +48 smp late, SER .355→.048 — the
  m4–m7 dc0 mechanism), 4500 Hz + 5625 Hz (static deck notches, shift-worsening not
  shift-improving), 6750 Hz (4.5 %).
- within-symbol baseline mean SER 0.032 (dc0 dominates it too — the 750 Hz room tail is
  multi-ms); mids are clean in BOTH views → the geometry works wherever dc0/notches are avoided.
- pilot tracking @ doubled rate (187.5 Hz updates): raw 10.0 µs → EMA 7.3 µs → DD 3.6 µs
  (probe loop); production `x9 residual_stats` on real N256 frames: raw 21.6 → EMA 13.4 →
  PLL 10.7 → DD 6.9 µs. Doubled-rate tracking verified.
- harness fidelity: same machinery at the full m8 geometry reproduces the production
  per-carrier SER (max |Δ| 0.019, on the top carriers where the production PLL beats ema0.5).
- second tape (master8 capture, independent session, `m8_dq_p10n512_rs127` at half-rate):
  same structure — dc0 ≈ 32 %, the known 3750 Hz master8 null at 11 %, mids clean.

### Gate result (pre-registered metric)
| rung | carriers dropped (measured) | mean SER | predicted byte-ER | threshold | pass |
|---|---|---|---|---|---|
| P18/RS127 derate | 750, 4500, 5625, 6750 Hz | 0.0074 | **0.0288** | 0.1506 | **GO (5.2x margin)** |
| P21/RS159 banker | 750 Hz | 0.0234 | 0.0792 | 0.1129 | pass (info) |
| P22/RS179 stretch | none | 0.0385 | 0.1132 | 0.0894 | fail (info — keeps dc0, on tape as stretch) |

## 3. STEP-2 deliverables (built on GO)

`x10_master_dense2x.wav` — 168.5 s (2.81 min), 4 rungs, m9 architecture (global chirp pair +
front Schroeder sounder), manifest `x10_master_dense2x_manifest.json` + sidecars
`sidecars_x10_dense2x/` with per-codeword CRC32 + sha256(orig/packed):

| rung | PHY | RS | gross | net bps | ×record | frames/cw | sec |
|---|---|---|---|---|---|---|---|
| x10_anchor_m8dense375 | DQ_P22_N512_sp4 | 159 | 4125 | 2572.1 | 1.00 | 25/49 | 34.2 |
| x10_d2x_p18_rs127 | D2X_P18_N256_sp2_drop4 | 127 | 6750 | 3361.8 | 1.31 | 45/90 | 44.6 |
| x10_d2x_p21_rs159 | D2X_P21_N256_sp2_drop1 | 159 | 7875 | 4910.3 | 1.91 | 36/72 | 32.7 |
| x10_d2x_p22_rs179 | D2X_P22_N256_sp2 | 179 | 8250 | 5791.2 | 2.25 | 32/64 | 28.3 |

TX adds Schroeder-phased initial symbols (φ0_k = −πk²/nc; differential-RX invariant):
body crest factor 10.8–11.8 dB vs 13.5 dB un-phased — ~2.4 dB more average drive at the
same peak (the headroom dossier's PAPR point). No TX clipping (channel is hysteresis-IMD
dominated; stated deviation from "light PAPR normalization").

Decoder `x10_b_aggr_05_dense2x_decode.py`: union receiver sweeps both rx windows ×
(PLL bw30/45 + EMA α 0.5–0.8), probe-ranked with early-stop; ERASE_FRACS=(0.0,)
pre-registered (erasures monotonically hurt on tape9); CRC32-per-codeword guard;
trial ledger reported (`false_accept_bound` ≈ 4.7e-7 « 1e-4 budget).

- self-check (clean wav): **4/4 orig-exact**, 0 cw failed, first-attempt front-ends.
- dress rehearsal (channel_v2 tape7, aac=True, dg=0.58, seeds 0/1): chain runs end-to-end;
  anchor 33/49 cw (s0) and 1/49 (s1), d2x rungs collapse — see §4.

## 4. Sim gates g1–g5: REJECT, pre-registered prediction-to-test

All cells logged in `results/x10_b_aggr_05_dense2x_simgate.json`: g1 0/8, g2 0/8, g3 0/4,
g4 0/4 per rung, g5 byte-ER 0.94–1.0. Attribution diagnostic (same file): with dg=0 the sim
is CLEAN (SER ≤0.001) → the collapse is 100 % the sim's diffuse-reverb tail, the one
unanchored axis. Calibration precedent: the m9 dress rehearsal failed m8_dense375 37/49
(seed0) and m4/m5 totally — the real tape landed m8 **0/49 EXACT (the current record)**
and m4b 0/49. The real-capture probe (gold evidence) already measured the actual room tail
at this geometry: mean SER 0.0385. Sim REJECT recorded as the prediction the tape adjudicates.

## 5. Tape-operator runbook

1. Record `experiments/tape_v2/x10_master_dense2x.wav` to tape (SOP: Dolby OFF, record ~7.0,
   ~1 s silence margins). Regenerate wav if missing: `python3 x10_b_aggr_05_dense2x_master.py`.
2. Playback capture per CLAUDE.md (Voice Memos → iCloud → ffmpeg to 48 kHz mono wav in
   `captures/tape10_run1.wav`).
3. `OPENBLAS_NUM_THREADS=2 python3 experiments/tape_v2/x10_b_aggr_05_dense2x_decode.py captures/tape10_run1.wav`
4. Read `results/x10_dense2x_results_tape10_run1.json`: `tape_pass_valid` (anchor reproved)
   must be true; SUCCESS = p18 orig-exact (banks 3362 under sidecar-CRC convention);
   RECORD = p21 orig-exact ≥ 4400 net (sidecar caveat inherited); verify miscorrected_cw=0
   and the CRC ledger.

## 6. Honest caveats

- The probe inherits one structural difference: in true dense2x, echo at delays >320 smp
  comes from two symbols back (independent phase) instead of the same previous symbol —
  equivalent at ISI-power level, slightly different phase statistics.
- Probe TX had no Schroeder phasing (the master adds it; TX-side, raises drive only).
- The pre-registered P18 threshold formula was applied at the probe's measured SER through
  an EMA front-end; the shipped receiver is a strict superset (adds PLL + both windows).
- P21 keeps 4500 Hz (18.8 % SER) — its byte-ER margin (0.079 vs 0.113) is the banker's
  main risk; P18 is the safety rung.
- Sim g1–g5 = REJECT on the axis where sim is documented-wrong; this is logged, not hidden.
- No new physical capture exists yet: the 3362/4910 net figures are projections conditional
  on the tape pass; nothing is claimed as a record until sha256 orig-exact on a real capture.

## 7. Reproducibility

Deterministic (no RNG in probe/master; sim seeds 0–7 logged per cell; ladder_seed 20260612).
Commands: probe stages `halfrate tail fullcheck m0half secondtape residuals gate`;
`x10_b_aggr_05_dense2x_master.py`; `_decode.py <wav>`; `_simgate.py g1|g2|g3|g4 [rung]`,
`_simgate.py verdict`; `_dress.py --seeds 0,1`. All under
`OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2`, each < 8 min.
