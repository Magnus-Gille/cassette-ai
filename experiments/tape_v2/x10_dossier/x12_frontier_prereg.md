# x12-FRONTIER-REGATE — pre-registration (FROZEN 2026-06-12T15:54Z)

**Campaign:** x12 · **Step:** frontier re-gate vs tape10 evidence · **Status:** FROZEN
before any adjudicating measurement of this step ran. Gates below adjudicate (a) the
killed-design candidate set by deterministic arithmetic on ALREADY-PUBLISHED receipts,
(b) a NEW post-freeze 8-seed sim screen on pre-registered BLOCKING axes only, (c) a NEW
post-freeze no-channel self-check, and (d) a FUTURE real-capture tape pass via the
frozen ship-thresholds. Nothing in (a) is a new measurement; everything in (b)–(d) runs
strictly after this freeze.

## 0. Disclosure (what was known when this froze)

- `results/x11_frontier_margins.json` (tape9 + m8 quantiles, ext-bin model fit, the x11
  kills) and `results/x12_tape10_margins.json` (native-d2x tape10 quantiles, replicate,
  sounder, tape10 ext-bin refit, byte-ER projections) are PUBLISHED inputs. The
  per-carrier margin/SER numbers they contain were known before this freeze. This
  re-gate's carrier arithmetic is therefore a RE-ADJUDICATION of existing receipts under
  rules fixed here, not a blind experiment — disclosed per discipline.
- The 15° DQPSK margin line, the `0.6·(255−k)/510` cap, the `/1.5` margin factor, the
  derate rule, and the blocking-vs-prediction axis split are inherited verbatim from the
  frozen x11 prereg (no threshold was re-tuned against tape10 numbers).
- New thresholds introduced here (30° DBPSK line, SER90 tail rule, mid-8 selection rule,
  rate-selection rule, ship-thresholds) were written down as RULES in this file before
  their numeric outcomes were computed by `x12_frontier_regate.py`.
- Standing record at freeze: **5791.2 net bps byte-exact** (m10_r8 on tape10, x11-rescue
  assisted; receipts `results/x11_decode_results_tape10_run1.json`).

## 1. Frozen evidence columns

| column | source | nature |
|---|---|---|
| t9 | `x11_frontier_margins.json` `stages.quantiles_tape9`, best of 27 sanctioned branches | measured (half-rate N512 emulation of d2x) |
| t10 | `x12_tape10_margins.json` `stages.quantiles_tape10_m10_r8_d2x_p22_rs179`, same 27 branches | measured (NATIVE d2x, primary) |
| t10b | same file, `m10_r6` replicate | measured (consistency check only, never adjudicates) |
| m8 | `x11_frontier_margins.json` `stages.quantiles_m8tape` | measured, ADVISORY ONLY (see G_A2 note) |
| ext9 | `x11_frontier_margins.json` `stages.extbins` | model prediction (tape9 fit) |
| ext10 | `x12_tape10_margins.json` `stages.extbins_tape10` | model prediction (tape10 refit; c1 inflated by the 9000 Hz ref collapse → conservative for ext bins) |

Margin convention (unchanged): `margin = boundary − p90(|dphi err|)`, best sanctioned
branch; DQPSK boundary 45°, DBPSK boundary 90°.

## 2. Frozen gates

- **G_A2 — two-capture per-carrier rule.** Every carrier whose CLEANLINESS a design's
  budget depends on must show margin ≥ 15° (DQPSK) on BOTH t9 and t10. DBPSK carriers
  must show `90° − p90 ≥ 30°` on both columns (equal fractional headroom: 15/45 = 30/90;
  stricter than a flat 15° — frozen before computing any DBPSK margin).
  *m8 demotion (frozen rationale):* x11's G_B used m8 as the only second capture. Tape10
  is now a second NATIVE capture on the current deck/era; m8 (3 burns ago, deck-era
  artifacts, 750-step subset) becomes an advisory column — logged, flagged, never
  binding. The G_B lesson ("a banker may not stand on one tape's good day") is preserved
  by requiring BOTH t9 and t10.
- **G_C2 — byte-ER budget.** Predicted byte-ER ≤ `[0.6·(255−k)/510] / 1.5`, where
  byte-ER = mean over used carriers of `1−(1−SER)^(8/bits)` (bits=2 → ^4 DQPSK, bits=1 →
  ^8 DBPSK), with the WORST-of-(t9,t10) per-carrier SER. SER for measured carriers =
  best-branch SER at the 45° (DQPSK) boundary; for DBPSK carriers SER = SER90 from the
  tail rule (§3). The global column-interleave equalizes codewords, so the mean (not
  worst-codeword) is the right granularity — same convention as x11 G_C.
- **G_D2 — rate floor.** A banker claim requires projected net > **5791.2 bps** (the
  standing record; x11 used the then-record 4910 the same way). Probe rungs are exempt
  from the floor but must carry a unique pre-stated evidence purpose.
- **G_E2 — extension bins.** Bins >9 kHz have no real-capture modem evidence; any rung
  using them is PROBE class regardless of margins (x11 G_E precedent). They are gated on
  PREDICTED p90 from BOTH models (ext9 AND ext10) under the G_A2 boundary rule for their
  constellation.
- **Derate rule (unchanged):** a carrier failing G_A2 is dropped and the candidate
  re-derives (P and net shrink; RS k FIXED per candidate for C1/C2/C4 — no post-hoc
  code-rate softening). A banker re-deriving to ≤ 5791.2 is KILLED.
- **Canary rule:** any new ladder MUST carry the 2572 anchor (byte-identical m10_r0
  reuse) and the best-proven d2x banker 4910 (byte-identical m10_r6 reuse). A future
  tape pass is valid only if BOTH canaries decode orig-exact.
- **CRC ledger:** every `_rs_merge_guarded` call logs `n_codewords` CRC32 acceptance
  trials; campaign false-accept budget < 1e-4.

## 3. Frozen SER90 tail rule (DBPSK SER prediction)

For a carrier with measured quantiles on capture c:
`λ = (p99 − p90)/ln 10` (the p90→p99 decade decay), and
`SER90 = 0.5 if p90 ≥ 90° else min(0.5, 0.10 · exp(−(90 − p90)/λ))`.
For ext bins (model p90 only): same formula with `p90 = p90_pred(f)` and λ borrowed from
the **9000 Hz carrier of the same capture** (nearest measured high-band carrier; widest
measured high-band tail). Exponential tail anchored at the empirical p90 is a disclosed
model assumption — heavier than Gaussian, and exactly what the probe exists to test on
real tape.

## 4. Candidate registry (exact configs, frozen)

| id | config | design net | tier | binding gates |
|---|---|---|---|---|
| **C1** `x12_c1_d2x_p16_rs223` | d2x N256 sp2, the x11 "16 clean carriers" = tape9-pass-15° set minus 3750 = {1125,1500,1875,2250,3000,3375,4125,5250,6000,6375,7125,7500,7875,8250,8625,9000}, pilot 4875, RS(255,223) | 5247.1 | banker | G_A2 (all 16), G_C2, G_D2 |
| **C2** `x12_c2_d2x_p22_rs191` | d2x N256 sp2 FULL grid P22 (750–9000, pilot 4875), RS(255,191) | 6179.4 | banker | G_C2 (worst-capture P22 byte-ER vs cap/1.5; published t10 projection 0.1346 already known — disclosed), G_D2; rescue-dependence logged vs the demonstrated tape10 ceiling (22/64 cw rescued at RS179) |
| **C3** `x12_c3_dbpsk_p12_ext` | uniform DBPSK (1 bit/carrier/sym, 90° boundary), N256 sp2 grid 750–10500, P12 = 8 mid-band carriers + 4 ext bins {9375,9750,10125,10500}, pilot 4875. Mid-8 RULE: the 8 largest `min(margin_t9, margin_t10)` DQPSK-measured carriers, ties to lower f. RS k by the rate rule (§5) | 12·187.5·k/255 | **probe** (G_E2) | G_A2-DBPSK (all 12, two columns; ext via ext9+ext10 models), G_C2 (SER90 tail rule), sim blocking screen (§6), self-check |
| **C4** `x12_c4_stable_set_sweep` | "any P23+/denser variant tape10 justifies": (i) the two-capture stable set S* = {f : min(margin_t9,t10) ≥ 15°} at every RS k ∈ {127,159,179,191,223,239}; (ii) DQPSK ext-band re-add check (ext9+ext10 ≥ 15°); (iii) 4500-readd check (G_A2) | derived | banker sweep | G_A2 + G_C2 + G_D2 exhaustively; GO only if some variant clears all three |

Re-verdict rows (logged, not re-opened): x11_f1 (5001.5), x11_f2 (5336.8), x11_f3
(4295.6) — all now also fail G_D2 (below the 5791.2 record) independent of their
standing margin kills.

## 5. Frozen rate-selection rule (C3 only)

`k* = max{k ∈ {127,159,179,191} : byte-ER_pred(worst capture) ≤ [0.6·(255−k)/510]/1.5}`.
If no k qualifies → C3 is KILLED. The probe ships at k* — chosen by rule, not tuned.

## 6. Frozen sim pre-gate (8-seed, BLOCKING axes only) — runs only if C3 passes §2–§5

Cell: `sim_v2.channel_v2(profile='tape7', dg=0.58, seed_offset=s)`, identical to the
m9/toneplan-v2/x11 gates. Seeds: nominal s∈{0..7}; AAC s∈{0..3} (aac=True). Receiver:
the frozen x12 DBPSK sweep (hann256_skip0 × ema{0.6,0.7,0.8} + pll30; rect128_skip64 ×
ema0.7), erase_frac 0.0, CRC-guarded RS merge, every trial in the ledger.

- **B1x (IMD/placement at ext bins):** median-across-8-nominal-seeds DBPSK SER of any
  ext bin > max(0.10, 3 × the median across seeds of the section's mid-8 median SER) → flag.
- **B3x (AAC delta):** for any ext bin, median SER over the 4 aac seeds > max(0.10, 3 ×
  its median over nominal seeds 0–3) → flag.
- **Placement/self-check (blocking, deterministic):** the no-channel self-check of the
  built master must be byte-exact AND orig-exact on ALL sections with 0 miscorrections,
  and both canaries must assert byte-identity to their m10 twins at build time.
- **Prediction-only (logged, NEVER a cut):** absolute g1/g5 byte-exactness of any
  N256-family rung in sim; timing/flutter; density. (Calibration: sim REJECTs on these
  axes are 3× falsified — 2338/2572, 2896, the whole d2x family.)
- **Kill discipline:** no KILL from the 8-seed screen alone; a blocking flag holds
  `print_authorized=false` pending a 16-seed confirmation (flag must hold AND g1<14/16
  there). Post-hoc axis reassignment PROHIBITED.

## 7. Frozen ship-thresholds (adjudicate the FUTURE master11 capture)

- Tape pass valid ⇔ both canaries orig-exact (2572 anchor AND 4910 d2x banker).
- **C3 probe SUCCESS:** byte-exact AND orig-exact at RS k*. **C3 PARTIAL** (still banks
  evidence): per-carrier DBPSK SER table recovered from ≥1 locked front-end. Only
  byte-exact counts as "DBPSK ext-band demonstrated".
- **Master12 resurrection thresholds (frozen NOW, before any tape):** measured
  real-capture DBPSK SER per ext bin, every bin:
  ≤ 0.0202 (`1−(1−s)^8 ≤ RS127 cap 0.1506`) → an ext-band hybrid is probe-eligible;
  ≤ 0.0117 (`1−(1−s)^8 ≤ RS179 cap 0.0894`) → hybrid stretch-eligible at design net
  6317.6 bps (d2x P22 DQPSK + 4 ext DBPSK, RS179). The hybrid itself stays KILLED in
  x12 (its base P22 byte-ER 0.1346 > cap already needs the rescue ceiling with zero
  margin; not printable on current evidence).
- A blocking-flag-free sim screen + clean self-check ⇒ the x12 master receives
  `print_authorized=true` as a PROBE tape (canaries + C3). Any other outcome ⇒ false.

## 8. Outcome space (declared)

Each candidate gets exactly one of: GO (all binding gates pass), KILL (any binding gate
fails; honest kills are wins), or DERATED-KILL (re-derived net ≤ 5791.2). Expected
deliverables for every GO: section generator + self-checked waveform + frozen
ship-threshold. KILLs ship receipts only.

Adjudicator: `x12_frontier_regate.py` → `results/x12_frontier_regate.json`.
Builder: `x12_regate_master.py` → `x12_master_regate.wav` (+ manifest + sidecars).
Decoder/self-check: `x12_regate_decode.py` → `results/x12_regate_results_*.json`.
No frozen file is edited; all new files are x12-prefixed.
