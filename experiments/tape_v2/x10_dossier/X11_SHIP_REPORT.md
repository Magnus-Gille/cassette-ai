# X11 SHIP REPORT — decoder-only ship (adjudicated Option B)

**Date:** 2026-06-12 · **Campaign:** x11 (post-master10-build hardening)
**Adjudication: Option B — ship decoder upgrades only. NO master10b. NO appended rungs.**
**The tape to burn is the existing blessed `master10.wav` (unchanged, bit-identical, self-check 10/10).**
**Burn script: `play_master10.sh` · Receiver to run on the capture: `x11_decode.py`.**

---

## 1. The adjudication in one paragraph

The x11 frontier campaign's pre-registered margin gate KILLED both >4910 banker candidates
(f1 derated P19→P16 = 4211.8 net, f2 = 4494.1 net — both below the 4910 floor;
`results/x11_frontier_margins.json`), and f3's GO-derated 2988 bps is strictly dominated by
r5's already-printed 3362. `x11_master_frontier.wav` carries `print_authorized=false`.
Toneplan-v2 remains explicitly NOT-burned (REJECTED print). With zero append candidates, a
master10b would be a bit-identical re-print of r0–r9: pure physical-burn risk for zero new
content. All real x11 value ships in the receiver: the d2x rescue path (the previously-fatal
critic gap), the dc0 late-window mechanism, AAC-axis + constant-clock-offset validation, and
0-regression proof across all 4 gold captures.

## 2. What ships (decoder stack)

| component | what it is | evidence |
|---|---|---|
| `m10_decode.py` | FROZEN composed superset pipeline (unchanged blessed burn artifact) | `results/x10_m10_results_composed_regression_tape9_run1.json`, `_m8_tape.json` |
| `x11_d2x_erasure.py` | d2x-aware rescue: shift-window sweep + frozen erasure ladder over enlarged pool | `results/x11_d2x_gate_report.json` — **gate_met=true**; G1 23/23 synthetic marginal d2x sections rescued orig-exact across aac {off,on} × clk {0,+0.10,+0.17,+0.25}%; 0 miscorrections; FA bound 1.03e-5 |
| **`x11_decode.py`** | **THE SHIPPING RECEIVER**: thin superset wrapper; stage A = `m10_decode._decode_section` verbatim; stage B = gated d2x rescue, fired ONLY on d2x sections stage A leaves failing; rescue adopted ONLY if strictly better (never-worse-than-m10 by construction) | `results/x11_decode_selfcheck.json` (pass=true), `results/x11_decode_regression_{tape9,m8,tape7,tape4,summary}.json` (**blocking_gate_pass=true**) |
| `x11_history_rescue.py` | receiver-breadth evidence: 6 previously-failed historical rungs banked orig-exact (4 on tape7, 2 on m8), 0 miscorrections, FA 2.9e-7 | `results/x11_history_rescue_*.json` — decoder-only; all 6 rungs (467.6–819.9 bps) sit far below 2896; bank nothing shippable, prove generality |

### x11_decode.py wrapper selfcheck (`results/x11_decode_selfcheck.json`)

- **Clean synth** (`x11_d2x_synth.wav`, bit-identical master10 r5–r8 slices): 4/4 orig-exact,
  stage A only — the rescue correctly never fires on a healthy capture.
- **Marginal synth cell** (`dg0.35_aac0_clk+0.00_s0`): stage A leaves r7 at 1 and r8 at 8
  failed codewords; the wrapper arms the rescue and lands **4/4 orig-exact**
  (r7: sweep filled 17 + ladder 2; r8: sweep filled 41 + ladder 2), 0 miscorrections —
  reproduces the gated rescue outcomes exactly, end-to-end through the shipping entry point.

### Blocking regression gate (0 regressions, 0 miscorrections — all 4 gold captures)

| capture | path | result |
|---|---|---|
| tape9_run1.wav | x11_decode wrapper, master9 manifest, fresh sync | 10/10 banked rungs orig-exact (934…2896), freqdiff 37/37-fail expected negative, misc=0, FA 5.1e-7, stage=m10_stock on every section (wrapper transparently identical to m10 on non-d2x) — `all_match=true` |
| m8_tape_mono_lossless.wav | x11_decode wrapper, master8 manifest | m8_dq_p10n512_rs127 0/62, orig-exact, misc=0 — `all_match=true` |
| tape7_run1.wav | unchanged production m7_decode | m16_rs111_8k / m16_rs191_8k / m32_rs95_4k all byte-exact, match reference — `all_match=true` |
| tape4_run1.wav | unchanged production m4_decode | ws_test2k / ws_llm24k byte-exact, match reference — `all_match=true` |

CRC/trial discipline: per-codeword CRC32 is the ONLY acceptance channel; every RS attempt and
CRC check ledgered; campaign FA bound (d2x campaign total incl. gate runs) 1.03e-5 < 1e-4
budget; truth-audited miscorrected=0 everywhere.

## 3. Evidence tier per master10 rung + honest weakest-link table

| rung | net bps | tier | evidence for it | **weakest link (honest)** |
|---|---|---|---|---|
| r0 canary | 2572 | REAL-banked | orig-exact on tape9 (m9 campaign); the pass-validity anchor | dress seed-0 landed only via the full union→erasure rescue chain — the canary itself may need the whole pipeline |
| r1 n256_rs179 | 2632 | REAL-banked | banked from tape9 by the composed receiver (m5 config) | clean pass-1 on tape9; lowest-risk rung |
| r2 n256_rs191 | 2809 | REAL-banked | banked from tape9 (m6 config) | needed late-window + ladder rescue on tape9 — it was rescued, not clean |
| r3 n256_p11 | 2896 | REAL-banked | banked from tape9 (m7 config); the standing record | same: rescued via lw_ema0.6_S32; dc0 reverb-tail bias is the known root cause, late window is the fix |
| r4 twin of r3 | 2896 | REAL-banked config | twin banks independently | new tape pass = new azimuth/level realization; twins exist precisely for this |
| r5 d2x P18 rs127 | 3362 | frontier derate | real-capture probe gate 5.2× margin (P18 pred byte-ER 0.029 vs 0.151) | **never decoded as a full section from a real tape**; drops {750,4500,5625,6750} so it avoids every measured-bad carrier |
| r6 d2x P21 rs159 | 4910 | frontier banker | per-carrier extrapolation from the m8-era capture; sim deaths are the known prediction-only axis | **keeps 2625/3750/6750 Hz, which the NEW x11 frontier margin table measured at 10.2° / m8 −2.8° / 10.6° — below the 15° rule** (that table killed the f1/f2 candidates for the same reason); also the 4500 Hz deck-notch carrier at 18.8° margin. r6 is a gamble with a now-armed rescue path, not a banked outcome |
| r7 twin of r6 | 4910 | frontier banker | realization insurance | same as r6 |
| r8 d2x P22 rs179 | 5791 | stretch | predicted to FAIL by its own probe (byte-ER 0.11); printed as SER diagnostic + lottery ticket | keeps dc0 @750 Hz (the m5–m7 killer) AND 4500/5625 notches; its only realistic hope is the x11 rescue (which did rescue a synthetic 8-failed r8) |
| r9 tail canary | 0 | FORENSIC_ONLY | head-vs-tail differential | banks nothing by design |

**The d2x rescue caveat, carried forward honestly:** the rescue proof is synthetic
(sim_v2 marginality at the dg 0.35–0.40 cliff). The banked claim is the pre-registered
≥30% gate, NOT the observed 100% (23/23). Real d2x failure modes — static deck notches,
azimuth error, level mis-set — may concentrate errors differently than the diffuse-tail sim;
if a real d2x section lands OUTSIDE the 1–8-failed marginal band, the rescue has no evidence
either way. What is no longer true is "there is no proven rescue path at all".

**Dress-gap closure:** both x10 gaps are closed — the AAC axis and constant clock offsets
(0.10/0.17/0.25%) are exercised end-to-end (full-chain sync recovery + decode) in the d2x G1
grid and the frontier pre-gate full-chain cells (`fc_aac_clean`/`fc_clk_clean`/`fc_clkaac_clean`
PASS, exact speed recovery 1.00170 for +0.17%).

## 4. Burn SOP (tape10)

**Script: `bash experiments/tape_v2/play_master10.sh`** (prints the ladder + live progress).
Do NOT print `x10_master10.wav` / `x10_master10_draft.wav` (stale REJECTED toneplan-v2 artifacts).

1. Dolby NR **OFF** (record and playback). Deck record level **~7.0** (not 8.5).
2. Phone Voice Memos, quality **LOSSLESS**; start the PHONE first, then the deck recording,
   then the script (3 s lead-in built in). ~1 s silence around chirps.
3. Let the FULL 6.04 min play, **through r9 and the end chirp** — r9 is the head-vs-tail
   forensic differential; the chirp pair is the global sync anchor.
4. Readback: speaker ~55; Voice Memos auto-syncs via iCloud.
5. Convert and decode with the **x11 receiver** (supersedes the m10_decode line printed by
   the play script — m10_decode.py is frozen and could not be edited):
   ```
   QTA="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta"
   ffmpeg -hide_banner -loglevel error -y -i "$QTA" -ac 1 -ar 48000 \
       experiments/tape_v2/captures/tape10_run1.wav
   OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
       python3 experiments/tape_v2/x11_decode.py experiments/tape_v2/captures/tape10_run1.wav
   ```
   (x11_decode = m10 composed pipeline verbatim + the gated d2x rescue armed as stage B;
   chunk with `--sections` if any single invocation approaches 8 min.)
6. **RECORD RULE:** nothing is a record unless r0 reproves 2572 orig-exact on the SAME
   capture (`tape_pass_valid`); twins bank independently; no cross-section fusion; per-cw
   CRC32 + full trial ledger mandatory; sha256 orig-exact is the only definition of success.
7. Optional zero-tape-cost: capture a second playback (tape10_run2) for replay-diversity
   fusion (separate category, not a rung).

## 5. What was explicitly NOT shipped

- **No new rungs / no master10b** — frontier f1 KILL, f2 KILL, f3 GO-derated-but-dominated
  (`results/x11_frontier_margins.json`, `x11_frontier_pregate.json`, both
  `print_authorized=false`); toneplan-v2 stays unburned (ladder-slot budget rejection stands).
- **History-rescue rungs** (m16_rs159 819.9 bps etc.) — banked as receiver-breadth evidence
  on OLD captures only; they change nothing on tape and sit far below the 2896 record.

## 6. Files (x11 ship set)

- Receiver: `experiments/tape_v2/x11_decode.py` (new), `x11_d2x_erasure.py`,
  `x11_history_rescue.py` (read-only imports of frozen m10/m9/x10 modules).
- Gate evidence: `results/x11_d2x_gate_report.json`, `x11_d2x_rescue.json`,
  `x11_d2x_windows.json`, `x11_d2x_ledger.json`, `x11_d2x_regression.json`.
- Shipping-receiver evidence (this report's new artifacts):
  `results/x11_decode_selfcheck.json`,
  `results/x11_decode_regression_tape9.json`, `_m8.json`, `_tape7.json`, `_tape4.json`,
  `_summary.json` (blocking_gate_pass=true),
  decode transcripts `results/x11_decode_results_*.json`.
- Frontier KILL record: `results/x11_frontier_margins.json`, `x11_frontier_pregate.json`,
  `x10_dossier/x11-FRONTIER.md`.
- d2x hardening dossier: `x10_dossier/x11-D2X_HARDENING.md`.
- No new WAVs from this ship step (synth/frontier WAVs were produced by their own tracks and
  are gitignore-class: `x11_d2x_synth.wav`, `x11_master_frontier.wav`,
  `captures/x11_d2x_*.wav`, caches `captures/x11_decode_nom_*.npy`).
