# MASTER9 — Build Report (IMPL-TAPE deliverable)

**Author:** IMPL-TAPE workflow agent · 2026-06-10 · branch `deepdive-3-overnight`
**Spec:** `experiments/tape_v2/x9_dossier/MASTER9_PLAN.md` (followed exactly)
**Anchor record:** 934 net bps (DQPSK P10 N512 sp8 RS127, 0/62 cw on m8 tape)

This report covers the master9 **tape builder + decoder** (Track B + integration).
The pre-registered SHIP/HOLD gate harness (`m9_sim_validate.py`, MASTER9_PLAN §4)
is the Gate phase's deliverable and is **not** built here; this report flags the
one finding the Gate phase must adjudicate (M4 ISI sensitivity, below).

---

## 1. Deliverables (all green)

| file | what | status |
|---|---|---|
| `experiments/tape_v2/m9_ladder.json` | the exact 11-rung table (M0–M9a incl. M8 HOLD) + the two probes' params | **built** |
| `experiments/tape_v2/h4_dqpsk.py` | +`min_spacing_hz` kwarg (default 562 = old assert; M8 passes 375) | **edited, default bit-identical** |
| `experiments/tape_v2/m9_master.py` | tape builder (m8 structure): global chirp → front sounder → P1 → P2 → 11 rungs → chirp1; CRC32-per-cw manifest guard; h9-packed staggered slices | **built** |
| `experiments/tape_v2/m9_decode.py` | global sync + clock resample → per-section decode via the common chain (PLL **and** EMA front-ends, RS-mode sweep, CRC32 miscorrection guard); M9a via x9_freqdiff | **built** |
| `experiments/tape_v2/master9_draft.wav` + `master9_manifest.json` + `sidecars_m9/` | the draft tape (regenerable; WAV gitignored) | **built** |
| `experiments/tape_v2/results/m9_results_master9_draft.json` | self-check decode result (11/11 byte-exact) | **written** |

Front-end modules `x9_resampling_pll.py` (Track A) and `x9_freqdiff.py` were present;
`m9_decode` imports them to the documented APIs. **One correctness fix landed in
`x9_freqdiff.py`** (see §5) so M9a decodes byte-exact in the self-check.

---

## 2. The frozen-code change (M8 only) — verified bit-identical default

`h4_dqpsk.DQPSKScheme.__init__` gained a backwards-compatible `min_spacing_hz`
kwarg (default **562.0**), replacing the hard `assert spacing*df >= 562.0`. The
orthogonality assert (L115) is untouched.

Verification (P10 N512 sp8, no-channel modulate→demod, before vs after the edit):

```
BEFORE_EDIT: outlen=2000 biterr=0 sha=1b9a9b6047377563
AFTER_EDIT : outlen=2000 biterr=0 sha=1b9a9b6047377563   bit_identical=True
```

The default floor still rejects sp4@N512 (`spacing 375 Hz < 562`); only M8 passes
`min_spacing_hz=375.0` (22 carriers 750–9000 Hz, pilot 4875 Hz, orthogonal at sp4).
**M0–M7 and M9a are untouched** by this change.

---

## 3. The tape: master9_draft.wav

- **Duration: 482.4 s (8.04 min)** — well under the ~10 min budget (≈9.6 min spare
  the plan reserved is partly spent on the M4 second realization + longer M1/M2
  payloads, per C FACT 1 / MASTER9_PLAN §1).
- Layout: 1 s lead → global up-chirp → front Schroeder sounder (m8-identical) →
  **P1** (3× 4 s repeated sounder) → **P2** (8 s 4500 Hz pilot + 8 s 10-carrier
  level-ramp at −12/−9/−6/−3 dBFS) → 11 rungs (each: per-frame 0.25 s chirp
  preamble + DQPSK/F-DQPSK section + 0.12 s frame gaps) → global down-chirp → 1 s tail.
- Peak-normalized **0.70** (record SOP level ~7.0, Dolby OFF). Schroeder phasing
  on every multitone. Probes total **~32 s** (vs planned 28 s — the extra 4 s is
  inter-segment guard silence; immaterial against the spare budget).
- Ordering is robust-early → stretch-late: M0–M3 (N512 near-certain) sit at the
  head; the high-value M4–M7 (N256) sit in the **middle** (best-tracked region);
  M8 (code-gated HOLD) and M9a (lottery) at the tail.

### Per-rung table (as built)

| # | rung | phy | RS | net bps | ×rec | frames | cw | tape s | status |
|---|---|---|---|---|---|---|---|---|---|
| M0 | m9_m0_reprove934 | DQ_P10_N512_sp8 | (255,127) | 933.8 | 1.00 | 8 | 16 | 20.9 | ACTIVE |
| M1 | m9_m1_thin159 | DQ_P10_N512_sp8 | (255,159) | 1169.1 | 1.25 | 19 | 38 | 49.0 | ACTIVE |
| M2 | m9_m2_thin191 | DQ_P10_N512_sp8 | (255,191) | 1404.4 | 1.50 | 20 | 40 | 51.5 | ACTIVE |
| M3 | m9_m3_dropnull9c | DQ_P9_N512_sp8_dropnull | (255,159) | 1052.2 | 1.13 | 19 | 37 | 52.4 | ACTIVE |
| M4 | m9_m4_n256_rs159 | DQ_P10_N256_sp4 | (255,159) | 2338.2 | 2.50 | 24 | 48 | 35.5 | ACTIVE |
| M4b | m9_m4b_n256_rs159_var | DQ_P10_N256_sp4 | (255,159) | 2338.2 | 2.50 | 25 | 49 | 36.4 | ACTIVE |
| M5 | m9_m5_n256_rs179 | DQ_P10_N256_sp4 | (255,179) | 2632.4 | 2.82 | 22 | 44 | 32.6 | ACTIVE |
| M6 | m9_m6_n256_rs191 | DQ_P10_N256_sp4 | (255,191) | 2808.8 | 3.01 | 21 | 41 | 30.6 | ACTIVE |
| M7 | m9_m7_n256_p11_9000 | DQ_P11_N256_sp4 | (255,179) | 2895.6 | 3.10 | 22 | 43 | 30.0 | ACTIVE |
| M8 | m9_m8_dense375 | DQ_P22_N512_sp4 | (255,159) | 2572.1 | 2.75 | 25 | 49 | 34.2 | **HOLD** |
| M9a | m9_m9a_freqdiff | FDQ_P11_N512_sp8 | (255,159) | 1169.1 | 1.25 | 19 | 37 | 47.7 | ACTIVE |

Carrier geometries were verified against the actual schemes this session:
M0–M2 = the 934-record plan (750–8250, pilot 4500); M3 drops 3750 Hz (9 data
carriers, pilot 4500); M4–M6 = N256 sp4 750-grid (10 carriers, gross 3750); M7 =
P11 N256 (top 9000, pilot 5250, gross 4125); M8 = 22 carriers 750–9000 sp4
(pilot 4875, gross 4125); M9a = 11 chain carriers + pilot 4500, 10 diff-pairs.

**`--no-m8`** rebuilds the tape without the M8 HOLD rung (7.47 min, 10 rungs) —
the Ship phase's lever for whether the code-gated 375 Hz probe is burned.

---

## 4. Self-check (REQUIRED green) — PASS

`python3 m9_master.py` builds the WAV + manifest; `python3 m9_decode.py
master9_draft.wav` (no channel) decodes **every rung byte-exact + orig-exact**:

```
byte-exact (packed): 11/11   orig-exact (unpacked): 11/11
best orig-exact rung: m9_m7_n256_p11_9000 -> net 2896 bps (x3.1, resampling_pll)
```

Every DQPSK rung (incl. M3 drop-null and the M8 dense-375 via min_spacing_hz=375)
decoded through the resampling-PLL front-end; M9a decoded through x9_freqdiff. The
EMA front-end and the errors-and-erasures sweep are present and CRC-guarded; the
PLL won every section on the clean signal (it is a strict superset, ties on clean).

---

## 5. x9_freqdiff correctness fix (so M9a self-checks)

As delivered, `x9_freqdiff` decoded only 1/10 diff-pairs on a **no-channel** signal
(360/400 raw bit errors). Root cause: the absolute-time DFT references each carrier
to the window-start sample `lo`, so each adjacent-carrier difference acquires a
deterministic rotation `2π·(f_k−f_{k−1})·lo/FS = 2π·SPACING·lo/FS` — identical per
pair but a half-cycle (π) at the fractional offsets `lo` lands on, flipping 9/10
pairs by a quadrant. Two corrections (in `demod`):
1. **Subtract the deterministic band-edge alignment rotation** `R_i =
   2π·SPACING·lo_i/FS` (receiver-side, no truth) before slicing — resolves the
   π-fold ambiguity.
2. Replaced the broken published-H(f)-tilt subtraction (which corrupts a clean
   decode, since `modulate` adds no tilt) with a **self-calibrating per-pair (β_j)
   + per-symbol (γ_i) decision-directed de-rotation** that is a no-op on a clean
   signal and subsumes any real static channel tilt without a genie curve. A
   measured sounder phase tilt may still be passed via `eq_tilt` (optional seed).

After the fix, M9a is **byte-exact** on the no-channel section. This is a self-check
fix only; the Gate phase still grades M9a HOLD/lottery by rule (the sim cannot
faithfully vet a novel constellation mapping — MASTER9_PLAN §4.3).

---

## 6. ⚠ FINDING FOR THE GATE PHASE — M4 (N256) is diffuse-reverb-ISI-limited

A smoke run of the full tape through `sim_v2.channel_v2(profile='tape7', aac=False)`
at the **gate's nominal `diffuse_gain=0.58`** shows a sharp N512/N256 split:

| rung | N | raw BER @ dg=0.58 (seed 0) | packed byte-exact |
|---|---|---|---|
| M0/M1/M2/M3 | 512 | ~0 (worst carrier 7.4 %) | **YES** |
| **M4** | 256 | **5.36 %** (per-carrier SER 9–20 %, uniform) | **no (47/48 cw failed)** |

This is **channel physics, not a decode bug** — M4's raw BER scales steeply with
the diffuse-reverb gain (the 63 ms reverb tail corrupts a larger *fraction* of the
shorter N256 window, exactly R6 §1d):

```
M4 raw BER:  dg=0.30 → 0.0008   dg=0.45 → 0.0167   dg=0.58 → 0.0536
```

Implications the Gate phase must adjudicate (per MASTER9_PLAN §4):
- **M4's verdict hinges on the `diffuse_gain` calibration.** R6 §4 mandates dg be
  re-validated against the m8 per-rung BER before trusting any rung; if the
  lossless-branch dg is nearer 0.45 than 0.58, M4 clears nominal comfortably. At
  the frozen nominal dg=0.58, M4 **fails gate 1** (≥7/8 byte-exact) on seed 0 —
  i.e. it would land **REJECT/HOLD in sim**, not the headline 2.5× the plan hopes.
- The N512 rungs (M0–M3) are robust at dg=0.58 → the near-certain ≥1404 bps floor
  (M2) stands regardless. The Gate phase should run the full 8-seed nominal +
  dg-pessimism (0.65) + HF-flutter (12 µs) matrix on M4–M7 to place the verdict,
  and **re-anchor dg against m8 first** (this is the single most decision-relevant
  knob for the N256 centerpiece).
- M0–M3 N512 decode cleanly through the channel in the smoke test (byte-exact +
  orig-exact), so the receiver chain itself is sound; the N256 result is the
  honest channel telling us short-symbol ISI is the binding risk — which is
  precisely the question the master9 N256 bet exists to answer on real tape.

The two probes (P1 stationary-null map, P2a re-anchored 5–23.4 Hz jitter, P2b IMD
saturation knee) are in the tape to hand master10 its three missing numbers; they
are decode-only and cost nothing if a rung fails.

---

## 7. How to run

```bash
# build the tape (full 11-rung) or without the M8 HOLD probe:
python3 experiments/tape_v2/m9_master.py
python3 experiments/tape_v2/m9_master.py --no-m8

# self-check (no channel) — must be 11/11 byte-exact + orig-exact:
python3 experiments/tape_v2/m9_decode.py experiments/tape_v2/master9_draft.wav

# decode a real capture (Voice Memos → iCloud → wav, project SOP):
python3 experiments/tape_v2/m9_decode.py experiments/tape_v2/captures/<name>.wav
```

Results land in `experiments/tape_v2/results/m9_results_<capture>.json` (m8 schema
+ per-rung `front_end_used` / `erase_frac_used` / per-carrier SER + sweep attempts).

**Next (Gate phase):** wire `m9_sim_validate.py` against this manifest + the
front-ends, run the §4 5-gate matrix (re-anchoring dg first), log SHIP/HOLD/REJECT.
**No tape is burnt until the gate matrix is logged** (MASTER9_PLAN §5.3 step 2).
