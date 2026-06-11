# MASTER10 SHIP REPORT

Date: 2026-06-12 · Built/gated/dressed this session
Tape: `experiments/tape_v2/master10.wav` — **362.1 s (6.04 min)**, peak 0.70, SR 48k, master_id=`master10`
Builder: `m10_master.py` (deterministic, LADDER_SEED=20260612) · Manifest: `master10_manifest.json` · Sidecars: `sidecars_m10/`
Decoder: `m10_decode.py` — the COMPOSED SUPERSET pipeline (ensemble union + late-window dc0 + carrier-class erasure ladder + d2x window plan, strictly-additive CRC32-guarded fill-only)
Player: `play_master10.sh`

> **DO NOT PRINT `x10_master10.wav`** (stale REJECTED toneplan-v2 artifact).
> The tape is `master10.wav`. The manifest embeds master_id=`master10` and
> m10_decode refuses the default decode against any other manifest.

Record to beat: **2572 net bps orig-exact** (m9 m8_dense375, tape9_run1).

---

## 1. The ladder (10 sections, robust-early -> stretch-late, tail canary LAST)

| # | rung | phy | RS | net bps | x rec | payload (packed/orig) | frames/cw | tape s | tier |
|---|---|---|---|---|---|---|---|---|---|
| r0 | m10_r0_canary_2572 | DQ_P22_N512_sp4 msp375 | (255,159) | 2572.1 | 1.00 | 7662/8192 @98304 | 25/49 | 34.2 | **canary** |
| r1 | m10_r1_n256_rs179_2632 | DQ_P10_N256_sp4 | (255,179) | 2632.4 | 1.02 | 7753/8192 @43008 | 22/44 | 32.6 | proven |
| r2 | m10_r2_n256_rs191_2809 | DQ_P10_N256_sp4 | (255,191) | 2808.8 | 1.09 | 7741/8192 @18432 | 21/41 | 30.6 | proven |
| r3 | m10_r3_n256_p11_2896 | DQ_P11_N256_sp4 | (255,179) | 2895.6 | 1.13 | 7719/8192 @20480 | 22/44 | 30.5 | proven |
| r4 | m10_r4_n256_p11_2896_twin | DQ_P11_N256_sp4 | (255,179) | 2895.6 | 1.13 | 7730/8192 @51200 | 22/44 | 30.5 | proven |
| r5 | m10_r5_d2x_p18_rs127 | D2X_P18_N256_sp2_drop4 | (255,127) | 3361.8 | 1.31 | 11409/12288 @106496 | 45/90 | 44.6 | frontier |
| r6 | m10_r6_d2x_p21_rs159 | D2X_P21_N256_sp2_drop1 | (255,159) | **4910.3** | **1.91** | 11424/12288 @118784 | 36/72 | 32.7 | frontier (RECORD ATTEMPT) |
| r7 | m10_r7_d2x_p21_rs159_twin | D2X_P21_N256_sp2_drop1 | (255,159) | 4910.3 | 1.91 | 11463/12288 @86016 | 37/73 | 33.4 | frontier |
| r8 | m10_r8_d2x_p22_rs179 | D2X_P22_N256_sp2 | (255,179) | 5791.2 | 2.25 | 11450/12288 @131072 | 32/64 | 28.3 | stretch (predicted FAIL; SER diagnostic) |
| r9 | m10_r9_tail_canary_2572rep | DQ_P22_N512_sp4 msp375 | (255,159) | (0 — forensic) | — | byte-identical r0 | 25/49 | 34.2 | probe (FORENSIC ONLY) |

Lead-in: 1 s silence + 0.2 s chirp + sounder (2x3 s multitone + 12 s 3 kHz
flutter + 3 s noisefloor) ≈ 29 s. Extra ~1.3 s gap before r9; ≥1 s silence
around the end chirp (SOP). Total payload on tape: 92,013 packed / 98,304
original bytes of the real cassette-LLM (`stories260K_int4.cass`).
Total 362.1 s — **5.96 min under the 12-min cap on purpose** (padding adds
capture risk without information; every rung carries a payload sidecar so
failures yield per-carrier SER forensics for free).

Build provenance:
- r0/r5/r6/r8 sections are **byte-identical reuses** of the already
  self-checked x10 dense2x-master sections (packed blobs adopted from
  `sidecars_x10_dense2x/`, asserted at build time — note gzip-mtime trap, gate
  report §5).
- r9 is asserted byte-identical to r0 (payload sha256, CRC table, frame audio).
- The ONLY new TX sections are the twins **r4** and **r7** (fresh offsets
  51200 / 86016), both shipping mandatory `crc32_codewords` sidecar tables —
  as does every section (the union/rescue machinery's only acceptance channel).
- Deliberate omissions: m4-config 2338 (dominated by r1), freqdiff (dead,
  37/37), toneplan-v2 (REJECT), bitload-N512 (REJECT), replay-diversity
  (capture-blocked; twins replace it).

## 2. The receiver (one pipeline, all rungs)

`m10_decode.py` composes, strictly additively (CRC-passing codewords are
final; rescues only ever FILL CRC-failing ones):
1. **Ensemble union** over self-tracking front-ends: resampling-PLL(30 Hz) +
   EMA α∈{0.5,0.6,0.65,0.7,0.8,0.4}; dense2x sections sweep the manifest
   rx_window_plan (hann256/skip0 primary, rect128/skip64 alternate — the
   literal Hann/Nw=128 receiver is non-orthogonal and never used).
2. **Late-window dc0** (N256 DQPSK): widened pre-registered grid
   [0,8,...,80], OTHER_GRID {-8,0,8}, truth-free decision-EVM argmin, bases
   ema0.6+pll30; ALL scalar branches join the union (argmin not load-bearing).
3. **Carrier-class errors-and-erasures RS ladder**: truth-free
   residual-dispersion ranking, ≤60 patterns/cw, 4 best branches, fill-only.
Per-codeword CRC32 guard everywhere; full trial ledger; erase_frac=0 outside
the structural ladder (pre-registered). Per-rung per-carrier SER logged
regardless of outcome (SHIP-rule forensics).

## 3. Blocking gates — ALL PASSED before tape day (details: `X10_gate_report.md`)

| gate | result |
|---|---|
| Build integrity (byte-identical reuse, r9≡r0, CRC sidecars everywhere) | **PASS** |
| Clean self-check `master10.wav` (deliverable 4, blocking) | **PASS — 10/10 byte-exact AND orig-exact**, 0 cw failed, first-branch early-stop, 0 misc (`results/x10_m10_results_selfcheck_nochan.json`) |
| Composed-superset regression on REAL `tape9_run1.wav` | **PASS — all 9 banked/rescued m9 outcomes orig-exact** (934/1052/1169/1404/2338+2338b/2572/2632/2809/2896); freqdiff 37/37 fail = expected documented negative; 0 regressions, 0 miscorrections, fa 5.1e-07 (`results/x10_m10_results_composed_regression_tape9_run1.json`) |
| Composed-superset regression on REAL `m8_tape_mono_lossless.wav` | **PASS — 0/62, orig-exact** (`results/x10_m10_results_composed_regression_m8_tape.json`) |
| dc0 grid widening (blocking) | **PASS (closed via widen-again annex)** — argmin interior at S≈112 when probed to S192; cw_failed flat at 0 from S32–S160; shipped grid [0..80]+scalar-union is sufficient and safe (`results/x10_m10_dc0_annex.json`) |
| Strictly-additive semantics in code | **PASS** — fill-only enforced; truth-audited misc=0 in every run |

Notable receiver gain surfaced by the composed regression: **ema0.65 alone now
single-branch-banks m9's m4 AND m5** (the m9 production decoder needed
2-of-44-failing at best); late-window banks m6/m7 across the whole S32–S80
scalar range, not just one lucky shift.

## 4. Dress rehearsal (NOT a gate) — honest per-rung outcomes

Channel: `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`,
seeds 0+1, whole tape end-to-end, full composed decode
(`results/x10_m10_dress_rehearsal.json`). **Pre-registered context: the
faithful sim is 5–8x pessimistic vs real captures; it falsely rejected the
standing 2572 record (m9 sim 37/49 cells FAIL → real tape 0/49) and fully
REJECTS the dense2x family. N256/d2x sim failures are predictions-to-test.**

| rung | tier | net | orig-exact seeds | cw failed/seed | rescued cw/seed |
|---|---|---|---|---|---|
| r0 canary | canary | 2572 | **2/2** | [0, 0] | [31, 0] |
| r1 n256_rs179 | proven | 2632 | 0/2 | [37, 44] | [1, 0] |
| r2 n256_rs191 | proven | 2809 | 0/2 | [41, 41] | [0, 0] |
| r3 n256_p11 | proven | 2896 | 0/2 | [35, 44] | [8, 0] |
| r4 n256_p11_twin | proven | 2896 | 0/2 | [38, 44] | [5, 0] |
| r5 d2x_p18 | frontier | 3362 | 0/2 | [90, 90] | [0, 0] |
| r6 d2x_p21 | frontier | 4910 | 0/2 | [72, 72] | [0, 0] |
| r7 d2x_p21_twin | frontier | 4910 | 0/2 | [73, 73] | [0, 0] |
| r8 d2x_p22 | stretch | 5791 | 0/2 | [64, 64] | [0, 0] |
| r9 tail canary | probe | (0) | **2/2** | [0, 0] | [31, 0] |

Reading (don't panic — report):
- **Both canaries land on BOTH seeds.** Seed 1 is clean (pll30, 0/49 first
  branch). Seed 0 is harsh and the 2572 config lands ONLY through the composed
  machinery (widened-bank ema0.8 + union + the erasure ladder rescuing 31
  residual codewords, 0 miscorrections) — the m9-era receiver FAILED this
  exact config on the comparable d2x-dress seed (33/49). The composed receiver
  adds real margin, demonstrated end-to-end.
- N256 rungs fail both seeds — **exactly the m9 dress precedent** (m9's dress
  also failed all N256 rungs; the real tape then landed/rescued every one of
  them). The sim's reverb-ISI axis is its one unanchored dimension.
- dense2x rungs fail wholesale — matches the pre-registered sim REJECT
  (prediction-to-test). The real-capture probe evidence (P18 5.2x margin) is
  the GO that funds these rungs, not the sim.
- 0 miscorrections anywhere; CRC false-accept bound ≤ 1.6e-07 per run.

## 5. Expected real-tape outcomes (honest tiers, from the adjudicated plan)

- **Conservative:** r0 reproves 2572; r1 (2632) and/or r2 (2809) bank → record 2809.
- **Base:** r3/r4 (2896) bank → fresh-capture record **+12.6%**.
- **Upside:** P18 lands 3362 and P21 lands **4910 (+91%)**; r8 (5791) is NOT
  expected to land — on failure its sidecar yields the full-grid per-carrier
  SER map that designs master11 (diagnostic for free).
- **r9 contributes forensics only** (head-vs-tail flutter/azimuth
  differential), banks nothing, triggers no abort — pre-registered.

## 6. Record conventions & abort rules (pre-registered, unchanged)

1. All net-bps claims inherit the m9 **sidecar-CRC convention** (per-codeword
   CRC32 table lives in the manifest, only the whole-payload CRC32 is
   in-stream) — same convention as the standing 2572 record.
2. **Nothing is a record** until sha256 orig-exact on the new physical capture
   **WITH r0 reproving 2572 orig-exact** on that same capture (no canary → tape
   pass VOID; m10_decode prints this verdict).
3. SHIP per rung = orig-exact under composed m10_decode with 0 miscorrections
   (CRC-audited, fill-only rescues); per-rung per-carrier SER logged regardless.
4. Twins bank independently (m4/m4b precedent); no cross-section fusion —
   single-capture record semantics stay clean.
5. Optional zero-tape-cost: a second playback capture (tape10_run2) feeds the
   replay-fusion machinery as a separate multi-pass category (not a rung).

## 7. Operator quick sheet

```
bash experiments/tape_v2/play_master10.sh        # SOP embedded (Dolby OFF, rec ~7.0,
                                                 # Voice Memos LOSSLESS first, play past r9)
# capture lands via iCloud; then:
ffmpeg -hide_banner -loglevel error -y -i "$QTA" -ac 1 -ar 48000 \
    experiments/tape_v2/captures/tape10_run1.wav
python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/captures/tape10_run1.wav
# chunk if needed: --sections m10_r0_canary_2572,...   (merges into one results JSON)
```

## 8. Honest caveats

- The dense2x P21 record attempt's probe margin is **1.43x — thin** — and it
  keeps 4500 Hz (the deck-notch carrier, 18.8% SER on the probe). It is the
  riskiest funded element; r7 is its hedge, r5 the derate bank.
- Sim REJECT vs real-probe GO on dense2x is an open contradiction by design;
  the tape adjudicates it.
- The dress rehearsal exercised the composed rescue machinery end-to-end on
  the canary config only; on real-capture N256 evidence the machinery is
  validated via tape9 (G3), not via the sim.
- The EVM argmin statistic decouples from decode correctness at extreme window
  shifts (annex); safe here only because branch selection is non-load-bearing.
- `lw_pll30` scalar branches break wholesale on P10-N256 (known m9 PLL
  behavior) — harmless under CRC guard; ema base carries the late-window rescue.
- Decoder filename: the plan text pinned `x10_m10_decode.py`; the orchestrator
  deliverable pinned `m10_decode.py` (m9 file-pattern). Built as
  **`m10_decode.py`** (+ `m10_master.py`, both NEW files — no frozen file was
  edited; the frozen-list files and all existing m*/x9_*/x10_* files are
  untouched). Helper x10 files added: `x10_m10_dress.py`, `x10_m10_dc0_annex.py`.
