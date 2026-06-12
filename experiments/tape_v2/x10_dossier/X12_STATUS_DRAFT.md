# X12 STATUS DRAFT (for STATUS.md / Munin projects/cassette-ai)

**As of 2026-06-12, end of the x12 campaign. Adjudicated: BUILD — a short probe tape (master11), not a record attempt.**

## State

- **Standing record (UNTOUCHED):** 5791 net bps byte-exact (m10_r8, tape10_run1,
  fresh C90 at LOWER volume, sounder 35.4 dB / 0.42% flutter; r8 landed via the
  x11 rescue — sweep 19 cw + erasure 3 cw, 0 misc). No x12 candidate survived
  re-gating above it, so the record path (full-grid + strong RS + x11 rescue)
  stays the route for a future campaign.
- **Tape to burn:** `master11.wav` — **1.8 min, 3 rungs, print_authorized=true**
  (`x12_master11_master.py`; audio byte-identical to the gated
  `x12_master_regate.wav`, asserted at build). Ladder: c0 anchor-2572 +
  c1 d2x-4910 (both byte-identical m10 canaries, MANDATORY — pass valid iff
  both orig-exact) + c3 DBPSK ext-band probe 1685.3 (the only x12 GO; 8 mids +
  4 ext bins 9375–10500 Hz, 90° boundary, RS(255,191)).
- **Receiver for the capture:** `x12_master11_decode.py` — x11 blessed path
  (m10 composed + gated d2x rescue) for canary kinds + frozen x12 DBPSK sweep
  for the probe kind; strictly additive; refuses non-master11 manifests by
  default. Operator: `play_master11.sh` (checks print authorization).

## What x12 delivered

1. **One survivor, gated:** the DBPSK ext-band probe (x12-frontier-regate
   gate_met=true, self-check 3/3, 8-seed sim screen clean). The >9 kHz bins
   currently have ZERO real-capture modem evidence; this rung measures them.
   Pre-registered: byte-exact = "DBPSK ext-band demonstrated"; even a fail
   banks the per-carrier SER map. Eligibility ladders for master12 hybrids are
   frozen (ext SER ≤0.0202 probe / ≤0.0117 stretch → 6317.6 design net).
2. **Four honest kills with receipts:** RS223 ~5247 (clean-carrier set
   non-stationary across burns), RS191 ~6186 family (G_C2 fails >2× — needs the
   rescue ceiling from day one), stable-set sweep (no banker above 5791), and
   both spike steals — mic-NL inverse (null held out: no invertible static NL
   at our levels; gap bloom is flutter FM + tape-side products) and CP-OFDM
   (rect128 branch is already de-facto CP-OFDM; alternatives killed by echo /
   flutter-ICI numbers). Nothing re-litigatable.
3. **Bulk framing gate FAILED honestly** (`x12_framing_report.json`
   gate_met=false): nominal-stride extrapolation cannot replace per-frame
   preambles (K_s=1 — flutter wander = static offset on extrapolated windows;
   the pilot loop tracks increments, never absolute offset). The ~1.17–1.3×
   multiplier idea is DEAD in this form; any revival needs a new absolute-
   timing mechanism, pre-registered. ZERO bulk rungs on master11.
4. **master11 artifact fully gated at zero tape cost:** blocking no-channel
   self-check 3/3 orig-exact; blocking banked-outcome regression **zero
   regressions** on tape10_run1 (10/10, r8 record re-lands via rescue) AND
   tape9_run1 (11/11 incl. freqdiff 37/37 expected negative)
   (`results/x12_m11_regression_report.json`); dress (NOT a gate): c0 anchor
   ORIG 4/4 cells (incl. AAC + 0.17% clock), c1 the thrice-falsified sim
   wipeout, c3 1/4 (cliff-sitting; probe ships regardless — SER map banks
   either way) (`results/x12_m11_dress.json`).

## Next actions (tape day, ~10 min total)

1. Burn master11 to tape (`play_master11.sh`; Dolby OFF, record ~7.0, phone
   Voice Memos **LOSSLESS** — the dress AAC cell failed exactly on the ext
   band this tape measures).
2. Capture → `captures/tape11_run1.wav` → `python3 experiments/tape_v2/x12_master11_decode.py captures/tape11_run1.wav`.
3. Adjudicate against the frozen thresholds; bank the ext-band SER map; update
   the cross-capture margin table with the third native column.
4. x13 candidates (pre-register BEFORE looking at tape11 ext SERs): RS191-class
   ext designs if SERs land at prediction; the killed leads stay killed.

## Discipline notes (unchanged)

Frozen: all committed m10_*/x10_*/x11_*/x12_* files; new work = x13 prefix
after this burn. Pre-registered gates before experiments; per-codeword CRC32;
FA budget <1e-4 held everywhere this session (worst 5.11e-07); real-capture
evidence outranks sim; honest KILLs are wins. Big WAVs gitignored
(`x12_*.wav`, `master11*.wav` appended this session); captures are
irreplaceable — back up externally.
