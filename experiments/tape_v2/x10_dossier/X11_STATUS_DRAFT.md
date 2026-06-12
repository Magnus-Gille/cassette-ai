# X11 STATUS DRAFT (for STATUS.md / Munin projects/cassette-ai)

**As of 2026-06-12, end of the x11 campaign. Adjudicated Option B: decoder-only ship.**

## State

- **Standing record:** 2896 net bps orig-exact (tape9, receiver-banked; m5=2632 / m6=2809 /
  m7=2896 all banked, 0 miscorrections, 0 regressions).
- **Tape to burn:** `master10.wav` (UNCHANGED blessed artifact, 6.04 min, 10 rungs,
  self-check 10/10). No master10b was built — the x11 frontier margin gate killed both
  >4910 candidates (f1→4211.8, f2→4494.1, both < 4910 floor; f3 derated to 2988 < r5's
  3362), so a re-print would have carried burn risk for zero new content.
  `x11_master_frontier.wav` and `x10_master10*.wav` are DO-NOT-PRINT.
- **Receiver to use on the capture:** `x11_decode.py` — NEW shipping superset wrapper:
  frozen `m10_decode` composed pipeline verbatim (stage A) + the gated x11 d2x rescue
  (stage B, fires only on d2x sections stage A leaves failing; adopted only if strictly
  better — never worse than m10 by construction).

## What x11 delivered

1. **d2x rescue path exists and is gated** (`x11_d2x_erasure.py`,
   `results/x11_d2x_gate_report.json` gate_met=true): 23/23 synthetic marginal d2x sections
   rescued orig-exact across aac {off,on} × clock offset {0,+0.10,+0.17,+0.25}%,
   0 miscorrections, FA bound 1.03e-5. Closes x10 critic gap (a) — there was previously NO
   proven rescue if master10's r5–r8 landed marginal. Caveat: proof is synthetic (sim
   marginality cliff dg 0.35–0.40); banked claim is the ≥30% pre-registered gate, not the
   observed 100%.
2. **Both x10 dress gaps closed**: AAC axis + constant ~0.17% clock offset validated
   end-to-end (d2x G1 grid + frontier pre-gate full-chain cells, exact speed recovery).
3. **x11_decode.py blocking regression gate PASS**
   (`results/x11_decode_regression_summary.json`): tape9 10/10 banked rungs orig-exact +
   freqdiff expected negative, m8 0/62, tape7 3/3, tape4 2/2 — 0 regressions,
   0 miscorrections, all matches_reference=true. Wrapper selfcheck PASS (clean synth 4/4
   stage-A-only; marginal synth cell 4/4 with the rescue firing on r7+r8).
4. **Frontier adjudicated KILL** (`x10_dossier/x11-FRONTIER.md`): new per-carrier margin
   table on tape9+m8 killed 2625 Hz (10.2°), 6750 Hz (10.6°), 3750 Hz (m8 −2.8°), and all
   >9 kHz extension bins (timing-jitter phase error ∝ f). Honest implication: master10's
   r6/r7 (4910) KEEP those three sub-15° carriers — they are gambles with a rescue path,
   not banked outcomes. r8 (5791) additionally keeps dc0 and is predicted to FAIL.
5. **History rescue** (`x11_history_rescue.py`): 6 previously-failed historical rungs banked
   orig-exact on old captures (tape7 ×4 incl. m16_rs159/rs223/m32-turbo, m8 ×2), FA 2.9e-7 —
   receiver-generality evidence only; no shippable rungs (all ≤820 bps).

## Next steps (physical, operator required)

1. `bash experiments/tape_v2/play_master10.sh` — burn SOP in the script + X11_SHIP_REPORT §4
   (Dolby OFF, record ~7.0, Voice Memos LOSSLESS phone-first, play through r9 + end chirp).
2. Capture → `captures/tape10_run1.wav` → decode:
   `python3 experiments/tape_v2/x11_decode.py experiments/tape_v2/captures/tape10_run1.wav`
3. Record rule: r0 must reprove 2572 orig-exact on the same capture or the pass is VOID.
   Expected ladder: r1–r4 should bank (proven configs); r5 3362 likely; r6/r7 4910 is THE
   record attempt (uncertain — see margin caveat); r8 5791 lottery ticket.

## Frozen / conventions unchanged

m10_decode.py, m10_master.py, master10_manifest.json, all m*/x9_*/x10_* files,
real_channel_sim.py, h4_dqpsk.py, src/hyp_common.py. Per-cw CRC32 the only acceptance
channel; FA budget 1e-4 campaign-wide; erase_frac=0 outside the structural ladder; gates
frozen before experiments; sim is 5–8× pessimistic on the reverb/timing axis
(prediction-to-test, never a cut).
