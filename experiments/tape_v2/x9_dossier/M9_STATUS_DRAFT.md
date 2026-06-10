<!-- READY-TO-PASTE STATUS.md SECTION (do NOT edit STATUS.md from this workflow).
     Paste this block at the TOP of STATUS.md, above the 934-record section. -->

## 🎬 MASTER9 BUILT & READY TO RECORD — projected 1404→2896 bps (1.5×→3.1×) (2026-06-10)
Branch `deepdive-3-overnight`. `master9.wav` (**482.4 s / 8.04 min**, 11 rungs + 2 diagnostic
probes, peak 0.70) is built and **self-checks byte-exact + orig-exact 11/11 with no channel**
(`m9_decode.py master9.wav` → clock 1.0000×, 0 cw failed every rung). Ready to burn:
`bash experiments/tape_v2/play_master9.sh`. Full plan + adjudicated gates in `x9_dossier/`
(`MASTER9_PLAN.md`, `M9_gate_report.md`, `MASTER9_SHIP_REPORT.md`).

**The ladder (robust-early → stretch-late), with the pre-registered sim gate verdict:**
M0 reprove-934 RS127 **SHIP** · M1 thin-159 1169 **HOLD**(near-miss, dg65 only) · M2 thin-191 1404
**REJECT**(N512 cliff) · M3 drop-null 1052 **SHIP** · M4/M4b N256 RS159 2338 **REJECT**(sim N256
ISI — the CENTERPIECE bet) · M5 2632 / M6 2809 / M7 2896 N256 **REJECT** · M8 dense-375 2572
**HOLD-by-rule**(sim blind <750 Hz) · M9a freq-diff 1169 **HOLD-by-rule**(timing-immune lottery).
Plus **P1** (repeated-sounder stationary-null map) + **P2** (pilot-jitter re-anchor + IMD knee).

**The full ladder is on the tape on purpose.** The KILL/REJECT sim verdicts are *headline-
eligibility*, NOT tape-cut decisions: per `MASTER9_PLAN.md §1.2/§6` and `M9_gate_report.md §6`
("burn the full ladder — the sim's N256 REJECT is a prediction to test, not a reason to cut the
centerpiece"), every un-blessable rung is carried as a **prediction-to-test probe**. The sim's
N256 reverb-ISI scaling is **the one axis with no real anchor** (m8 carried no N256 rung); the
C-design thesis is N256 wins on the *timing axis the sim is blind to* (187.5 Hz pilot rate vs
93.8 Hz), which the nominal-reverb death never lets the rung reach — so only the real tape settles it.

**Dress rehearsal** (merged tape through the faithful `channel_v2(tape7, aac=False, dg=0.58)`,
seeds 0+1, `m9_dress_rehearsal.py`): **M0/M1/M2/M3 orig-exact on BOTH seeds, 0 cw failed** — the
N512 near-certain band survives end-to-end (best both-seed rung M2 = 1404 bps, 1.5×). M4–M7 die on
nominal reverb-ISI exactly as the gate predicted (the unanchored axis); M8 seed-splits ([37, 0]);
M9a fails by rule. *Caveat (honest): M2 lands the 2 dress seeds but the 8-seed gate marked it REJECT
(4/8) on the N512 RS cliff — trust the 8-seed gate, not the 2-seed pass.*

**Sim-blessed headline floor (SHIP all 5 gates): M0 (934, reproven) + M3 (1052, 1.13×).** Honest
expected real record: **M2 at 1404 bps (1.5×)** near-certain floor, with **M4 (2338, 2.5×)** the
expected headline if its HF-flutter gate clears on the real capture, and a real shot at M5/M6
(≈2.6–3.0×). Point estimate ≈ **2000 bps (≈2.1×)**.

**FROZEN constraints held:** `real_channel_sim.py` untouched; `h4_dqpsk.py` carries only the
sanctioned `min_spacing_hz` kwarg (default 562 = bit-identical to the frozen assert; M8 alone passes
375); `app/` + R*/A/B/C/PLAN dossier files untouched.

**NEXT — record the tape (operator SOP):** (1) Dolby OFF, deck record ~7.0, readback speaker ~55.
(2) Phone **Voice Memos LOSSLESS, START THE PHONE RECORDING FIRST**, then deck, then
`play_master9.sh`. (3) Let the FULL tape play to the end chirp (~1 s silence around chirps = sync
anchors). (4) iCloud-synced `.qta` → `ffmpeg -ac 1 -ar 48000 captures/tape9_run1.wav` →
`python3 experiments/tape_v2/m9_decode.py .../tape9_run1.wav`. (5) **FIRST on the real capture:**
re-anchor the HF-flutter gate from **P2(a)** (8 s 4500 Hz pilot → 5–23.4 Hz band-RMS jitter) before
claiming any N256 verdict — m8 anchor was 33.9 µs.
