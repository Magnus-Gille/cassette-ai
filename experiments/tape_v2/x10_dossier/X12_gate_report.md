# X12 Gate Report — frontier re-gate, bulk framing, spike steals → master11

Date: 2026-06-12 · Session: x12 re-gate campaign + master11 build/gate/dress
Master under test: `experiments/tape_v2/master11.wav` (master_id=`master11`, built by `x12_master11_master.py`)
Decoder under test: `experiments/tape_v2/x12_master11_decode.py` (x11 blessed receiver + frozen x12 DBPSK sweep, strictly additive)
Standing record (NOT challenged by this tape): **5791 net bps byte-exact** (m10_r8, tape10_run1, x11 rescue).

> Print artifact note: `master11.wav` is the gated `x12_master_regate.wav`
> ladder **promoted to the official master11 name** — sample data asserted
> byte-identical at build time (`provenance.audio_byte_identical_to_regate=true`
> in `master11_manifest.json`). Either file prints the same audio; the blessed
> operator path is `play_master11.sh` → `master11.wav`.

---

## 1. Per-candidate gate outcomes (one survivor, four honest kills)

Prereg: `x10_dossier/x12_frontier_prereg.md` (frozen 2026-06-12T15:54Z, before any measurement it adjudicates). Receipts: `results/x12_frontier_regate.json`.

### Survivor — laddered into master11

| candidate | gate evidence | verdict |
|---|---|---|
| **x12_c3_dbpsk_p12_ext** (uniform DBPSK, 90° boundary, 8 rule-picked mid carriers + 4 ext bins 9375/9750/10125/10500 Hz, N256/sp2, pilot 4875, RS k by the frozen rate rule → k\*=191, 1685.3 net bps) | `x12_frontier_regate.json` adjudication: gate_met=true on BOTH captures (tape9 + tape10 native columns); per-carrier DBPSK margins 67–77° at the mids; ext-bin tail rule λ from 9 kHz: t9 10.5° / t10 17.2°; no-channel self-check 3/3; 8-seed blocking sim screen clean | **GO (probe tier)** → master11 c3 |

Why a 1685 bps rung is worth tape: the >9 kHz ext bins have **zero real-capture
modem evidence** — their margins are model predictions (51–55° at the 90° DBPSK
boundary on the tape9 fit) and the SER90 tail rule is an untested assumption.
This rung converts the last open frontier axis from model to measurement.
Pre-registered outcomes: real ext SERs at prediction → RS191-class ext designs
become x13 candidates; 3× over → that lead dies with receipts. **Banks either way.**

### Kills — gated OUT with receipts (kept for the record)

| candidate | gate evidence | verdict |
|---|---|---|
| **x12_c1_d2x_p16_rs223** (~5247) | fails G_D2 outright (the lead predates the 5791 landing); ALSO fails G_A2 — the "16 clean carriers" set is demonstrably non-stationary across burns (x12 recon: 6 per-carrier class flips between consecutive burns on the same deck) and G_C2 — the thin-margin set does not exist as a two-capture object | **KILL** |
| **x12_c2_d2x_p22_rs191** (~6179 family, incl. the ~6186 P22 RS191) | G_C2 fails by >2× at the banker rule and >1.7× at the raw cap; printing a rung whose arithmetic REQUIRES the rescue ceiling from day one banks nothing the proven r8 path doesn't already bank | **KILL** |
| **x12_c4_stable_set_sweep** (14 variants) | worst-capture byte-ER 0.0528; no RS rate turns the two-capture-stable set into a banker above the 5791 floor; no ext bin or dropped carrier re-qualifies at 15° on both captures | **KILL** |
| **Bulk framing** (the ~1.17–1.3× multiplier) | `results/x12_framing_report.json`: G1 mechanics PASS (all 6 sections byte-exact clean, splice lock ds=12000) but **G2/G3 FAIL — K_s=1**: accumulated flutter wander appears as a STATIC window offset on extrapolated frames (the per-frame pilot loop tracks increments, never absolute offset); spliced BER grows with anchor distance (r6: .0178 → .0212 @K2 → .0221 @K4 → .0364 @K8; r0 collapses by K8); recommended_F=1 ⇒ framing efficiency gain 1.0× | **gate_met=FALSE** → ZERO bulk-framed rungs on master11; every rung ships v1 framing (framing-canary-pair rule moot) |
| **Spike steal (a): mic non-linearity inverse** | `results/x12_micinv.json`: machinery proven (recovers a known injected cubic) yet in-sample gain does NOT survive held-out rep1 (−0.148 dB / −0.59% IMD = overfit to rep noise) and an independent tape9 refit lands at identity (b3=−0.00035). No invertible static mic/ADC NL at our capture levels; the gap bloom is flutter FM sidebands + tape-side products a memoryless post-inverse structurally cannot remove | **FAIL — banked null** |
| **Spike steal (b): CP-OFDM (quiet/libquiet-style)** | `results/x12_ofdm_assessment.json`: the banked d2x rect128_skip64 branch is ALREADY de-facto CP-OFDM (CP=128) — design A (coherent, same geometry) is a **SIDEGRADE** (≤1.04° median margin upper bound vs 3–32° carrier non-stationarity between burns); design B (CP64, 1.33×) **killed by echo numbers** (guard-64 tail/direct −5.0 dB, ISI-equiv p90 52.9°); design C (93.75 Hz bins, 1.6×) **killed by flutter ICI** (SIR 14.1 dB at 9 kHz) | **KILL — no modem built, nothing banked** |

---

## 2. Blocking gates for the master11 artifact — all run BEFORE tape day, zero tape cost

### G1 — Build integrity (byte-identical reuse + gated-blob adoption) — **PASS**
`x12_master11_master.py` asserts at build time (frozen `x12_regate_master.build`
runs verbatim; only output identity repointed):
- c0/c1 packed blobs, CRC32 tables and orig sha256 **byte-identical to master10's
  r0/r6** (the m10 reuse convention, adopted from `sidecars_m10/`).
- c3 packed blob **adopted from the gated `sidecars_x12_regate/`** (the bytes the
  8-seed blocking screen actually adjudicated) — the gzip-mtime trap (m10 ship
  report §5) makes a fresh pack non-reproducible; adoption is asserted via
  unpack-roundtrip + length.
- master11 sample data sha256 == gated `x12_master_regate.wav` sample data sha256
  (whole-file hashes never reproduce: libsndfile's PEAK chunk embeds a write
  timestamp — bytes 60–61).
- Section tables (payload shas, CRC tables, frame starts) identical to the gated
  regate manifest.
- Builder REFUSES to build unless the c3 adjudication verdict is GO.

### G2 — No-channel self-check (BLOCKING) — **PASS 3/3**
`python3 x12_master11_decode.py master11.wav --out-tag selfcheck_nochan` →
`results/x12_m11_results_selfcheck_nochan.json`:

| rung | cw failed | front-end / stage | PACK | ORIG |
|---|---|---|---|---|
| x12_c0_anchor_2572 | 0/49 | m10_stock (resampling_pll30) | YES | YES |
| x12_c1_d2x_4910 | 0/72 | m10_stock (hann256_skip0_ema0.7) | YES | YES |
| x12_c3_dbpsk_p12_ext | 0/10 | x12_dbpsk_sweep | YES | YES |

0 miscorrections; canary pair reproved; FA bound 3.05e-08 ≪ 1e-4.
`print_authorized` was flipped to true ONLY after this check
(`x12_master11_master.py --authorize`, provenance in the manifest).

### G3 — Banked-outcome regression, tape10_run1 (BLOCKING) — **PASS, 0 regressions**
The shipping receiver stack re-decoded the gold capture from scratch
(fresh sync, fresh caches, tag `regress_tape10`) and reproduced the banked
`x11_decode_results_tape10_run1.json` **exactly**: 10/10 orig-exact, r0–r7+r9
clean at stage m10_stock, **r8 (5791 RECORD) again lands via the x11 rescue**,
0 miscorrections, FA bound 2.49e-07 (identical to banked). Receipts:
`results/x12_m11_results_regress_tape10.json` + `results/x12_m11_regression_report.json`.

### G4 — Banked-outcome regression, tape9_run1 (BLOCKING) — **PASS, 0 regressions**
Same drill against `x11_decode_results_regress_tape9.json`: 11/11 sections match —
10 orig-exact (m0 934 … m8 2572 dense375) + the m9a freqdiff **expected negative
reproduced at exactly 37/37 failed cw**. Receipts:
`results/x12_m11_results_regress_tape9.json` + `results/x12_m11_regression_report.json`
(`zero_regressions=true`).

Structural note: the new decoder routes every banked kind (dqpsk, dqpsk_dropnull,
dense2x, dense2x_drop, freqdiff) through the FROZEN x11/m10/m9 code paths
verbatim — new x12 code touches ONLY the `dbpsk_drop` kind, which does not exist
in any banked manifest. G3/G4 prove the wiring, not just the intent.

### G5 — Strictly-additive semantics — **PASS (by construction + audit)**
`x12_master11_decode.py` is a NEW file; every imported module is frozen and
imported read-only. CRC32-passing codewords are final; rescue paths fill only
CRC-failing ones; the x11 rescue is adopted only if strictly better. All CRC
acceptances ledgered; campaign FA budget < 1e-4 held on every run this session.

---

## 3. Dress rehearsal (NOT a gate; m9/m10 pattern) — honest outcomes

`x12_m11_dress.py`: full master11.wav through `sim_v2.channel_v2(profile='tape7',
dg=0.58)`; cells s0 / s1 / aac_s0 / clk_s0 (+0.17% constant clock, the mid value
of the frozen x11 stock grid); shipping decoder stage A (`--no-x11-rescue`, the
m9/m10 dress convention). Receipts: `results/x12_m11_dress.json`.

| rung | s0 | s1 | aac_s0 | clk_s0 |
|---|---|---|---|---|
| x12_c0_anchor_2572 | ORIG (0/49) | ORIG (0/49) | ORIG (0/49) | ORIG (0/49) |
| x12_c1_d2x_4910 | fail (72/72) | fail (72/72) | fail (72/72) | fail (72/72) |
| x12_c3_dbpsk_p12_ext | fail (10/10) | ORIG (0/10) | fail (10/10) | fail (10/10) |

PRE-REGISTERED HONESTY CONTEXT (unchanged from m9/m10/x11): the faithful sim is
5–8× pessimistic vs real captures; its diffuse-reverb axis falsely rejected the
standing 2572 record AND the entire d2x family — which then landed clean on real
tape (tape10: r5/r6/r7 0-failed FIRST-branch, r8 record via rescue). Honest
read of this table:
- **c0 anchor ORIG on all 4 cells** (incl. AAC and +0.17% clock) — the
  meaningful SHIP signal; the tape-pass validity anchor is sim-robust.
- **c1 d2x 72/72 wipeout on all cells** is the SAME sim prediction already
  falsified 3× on real tape (incl. this exact config landing 0/72 clean
  FIRST-branch on tape10); prediction-to-test, not a rejection.
- **c3 ORIG on 1/4 cells (s1 only)** — the probe is cliff-sitting in the
  faithful sim (seed s0 fails where s1 passes; the N256/sp2 grid it rides is
  the same axis the sim over-punishes). It SHIPS as a probe: per the prereg,
  even a non-byte-exact pass banks the per-carrier DBPSK SER map (only
  byte-exact = "DBPSK ext-band demonstrated"). Note the 8-seed blocking screen
  that print-authorized this rung ran clean at its own pre-registered
  settings; this dress cell-set is the harsher m9-convention dg0.58 axis.
- The aac_s0 failure is an extra operational flag: AAC at ~205 kbps attacks
  exactly the >9 kHz ext band the probe measures — **use a LOSSLESS Voice
  Memos capture on tape day (the standing SOP), or the ext-band evidence
  degrades to the AAC floor.**

---

## 4. Trial ledger / false-accept discipline (campaign)

Every CRC32 acceptance test this session was ledgered: self-check 3.05e-08;
tape10 regression 2.49e-07; tape9 regression 5.11e-07; dress cells ≤4.2e-08
each. All ≪ the 1e-4 campaign budget. 0 miscorrected codewords anywhere.

## 5. What did NOT ride (and why that is the result)

No >5791 attempt is on master11: no banker survived re-gating against the
two-capture evidence, so the standing record stays untouched and its proven
path (full-grid + strong RS + x11 rescue) remains the record route for a future
campaign. The x12 result is the honest narrowing of the frontier: one
measurable unknown left (the >9 kHz ext band), one cheap tape (1.8 min) that
measures it, four leads killed with receipts that nobody has to re-litigate.
