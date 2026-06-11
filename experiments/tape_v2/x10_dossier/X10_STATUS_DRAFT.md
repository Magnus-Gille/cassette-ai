# STATUS.md draft section — x10 / master10 (paste-ready)

## 2026-06-12 — master10 SHIPPED: composed-superset receiver + 10-rung ladder, all blocking gates green

**TL;DR:** `master10.wav` (6.04 min, 10 rungs) is built, self-checked 10/10
orig-exact, and ready to print. The new composed decoder `m10_decode.py`
(ensemble union + late-window dc0 + carrier-class erasure ladder + d2x window
plan, strictly-additive CRC-guarded) re-decoded the REAL tape9 capture as ONE
pipeline and reproduced **all 9 banked/rescued m9 outcomes orig-exact**
(934/1052/1169/1404/2338+2338b/2572/2632/2809/2896, 0 miscorrections,
fa 5e-07). Record attempt on tape: dense2x P21 @ **4910 net bps (1.91x the
2572 record)**, with 2632/2809/2896 proven-tier banks below it and a 5791
stretch diagnostic above.

**Artifacts (new):**
- `experiments/tape_v2/m10_master.py` -> `master10.wav` + `master10_manifest.json` + `sidecars_m10/`
- `experiments/tape_v2/m10_decode.py` (composed superset; also decodes m8/m9 captures via `--manifest`)
- `experiments/tape_v2/play_master10.sh` (SOP embedded)
- `experiments/tape_v2/x10_m10_dress.py`, `x10_m10_dc0_annex.py`
- Dossier: `x10_dossier/X10_gate_report.md`, `x10_dossier/MASTER10_SHIP_REPORT.md`
- Results: `results/x10_m10_results_{selfcheck_nochan,composed_regression_tape9_run1,composed_regression_m8_tape,dress_s0,dress_s1}.json`, `results/x10_m10_dress_rehearsal.json`, `results/x10_m10_dc0_annex.json`

**Ladder (net bps / tier):** r0 2572 canary (MUST reprove or pass VOID) ·
r1 2632 / r2 2809 / r3 2896 / r4 2896-twin proven (all banked/rescued on
tape9 evidence) · r5 3362 / r6 **4910 RECORD ATTEMPT** / r7 4910-twin frontier
(real-probe GO, sim REJECT pre-registered as prediction-to-test) · r8 5791
stretch (predicted FAIL; doubles as full-grid SER diagnostic) · r9 = FORENSIC
tail canary, byte-identical r0 repeat at end of tape (head-vs-tail
flutter/azimuth differential; banks nothing, no abort).

**Gates:** self-check PASS (10/10, 0 cw failed); composed regression on
tape9_run1 PASS (9/9 + canary config; freqdiff 37/37 = expected dead);
m8-lossless PASS (0/62); dc0 grid-widening gate CLOSED via widen-again annex
(EVM argmin interior at S≈112, cw_failed flat 0 from S32–S160; shipped grid
[0..80] + union-of-scalars makes argmin non-load-bearing); strictly-additive
fill-only semantics enforced in code, miscorrections 0 everywhere.

**Dress rehearsal (sim, tape7 profile, dg=0.58, seeds 0+1 — NOT a gate, 5–8x
pessimistic):** both canaries land on both seeds (seed 0 only via the composed
rescue: ema0.8 + ladder rescuing 31 cw — the m9-era receiver failed this
config in sim); N256 + dense2x rungs fail in sim exactly per the m9 precedent
and the pre-registered dense2x sim-REJECT. Predictions-to-test, not verdicts.

**Receiver insight banked:** the widened EMA bank matters — ema0.65 alone now
single-branch-banks m9's m4 (2338) and m5 (2632) on tape9; late-window banks
m6/m7 across the entire S32–S80 shift range.

**Hazards:** NEVER print `x10_master10.wav` / `x10_master10_draft.wav` (stale
REJECTED toneplan-v2 artifacts; master10's manifest embeds
master_id=`master10` and m10_decode refuses default decode against anything
else). `pack_payload` gzip output embeds an mtime — byte-identical section
reuse must load the original sidecar blob, never re-pack.

**Next:** print `master10.wav` to tape (play_master10.sh SOP: Dolby OFF,
record ~7.0, Voice Memos LOSSLESS first, let it run past r9 to the end
chirp), capture tape10_run1, `m10_decode.py captures/tape10_run1.wav`.
Record rule: nothing banks unless r0 reproves 2572 orig-exact on the same
capture. Optional zero-cost: second playback capture (tape10_run2) for
replay-fusion.
