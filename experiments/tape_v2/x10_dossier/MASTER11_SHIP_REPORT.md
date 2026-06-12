# MASTER11 SHIP REPORT

Date: 2026-06-12 · Built/gated/dressed this session
Tape: `experiments/tape_v2/master11.wav` — **107.9 s (1.80 min)**, peak 0.70, SR 48k, master_id=`master11`
Builder: `x12_master11_master.py` (frozen `x12_regate_master` machinery verbatim, output identity repointed; deterministic, LADDER_SEED=20260612) · Manifest: `master11_manifest.json` (**print_authorized=true**) · Sidecars: `sidecars_x12_m11/`
Decoder: `x12_master11_decode.py` — the x11 BLESSED receiver (m10 composed stage A + gated x11 d2x rescue stage B) for the canary kinds + the frozen x12 DBPSK 90°-boundary sweep for the probe kind; strictly additive throughout
Player: `play_master11.sh` (refuses to play unless the manifest is print-authorized)

> **This is a SHORT PROBE TAPE, not a record attempt.** The standing record —
> **5791 net bps byte-exact** (m10_r8, tape10_run1, x11 rescue) — is NOT
> challenged; no rung rides above the proven 4910. master11's job: add the
> third native-capture margin column (the cross-capture gate now requires it)
> and convert the >9 kHz ext band from model prediction to real measurement.
>
> Provenance: master11's sample data is **byte-identical to the gated
> `x12_master_regate.wav`** (asserted at build; whole-file hashes differ only
> in the WAV PEAK-chunk timestamp). One audio, one gate trail, one name to print.

---

## 1. The ladder (3 sections, robust-early → stretch-late, ~106 s of signal)

| # | rung | phy | RS | net bps | payload (packed/orig @offset) | frames/cw | tape s | tier |
|---|---|---|---|---|---|---|---|---|
| c0 | x12_c0_anchor_2572 | DQ_P22_N512_sp4 msp375 (full 375 Hz grid 750–9000, pilot 4875) | (255,159) | 2572.1 | 7662/8192 @98304 | 25/49 | 34.2 | **canary** — byte-identical m10_r0 |
| c1 | x12_c1_d2x_4910 | D2X_P21_N256_sp2 drop{750}, pilot 4875 | (255,159) | 4910.3 | 11424/12288 @118784 | 36/72 | 32.7 | **canary** — byte-identical m10_r6 (best-proven clean FIRST-branch d2x) |
| c3 | x12_c3_dbpsk_p12_ext | DBPSK_P12_N256_sp2_ext, 90° boundary: mids 1875/3375/3750/4125/5250/6000/7125/8625 + ext 9375/9750/10125/10500, 14 weak bins dropped, pilot 4875 | (255,191) | 1685.3 | 1797/2048 @16384 | 5/10 | 11.3 | probe — the only x12 GO |

All rungs ship **v1 framing** (per-frame preambles): the x12 bulk-framing gate
FAILED (G2/G3 K_s=1, `results/x12_framing_report.json` gate_met=false), so per
the pre-registered rule there are ZERO bulk-framed rungs and the
framing-canary-pair requirement is moot.

Lead-in: 1 s silence + 0.2 s chirp + sounder (2×3 s multitone + 12 s 3 kHz
flutter + 3 s noisefloor) ≈ 29 s; ≥1 s silence around the end chirp (SOP).
Mandatory canaries per the x12 prereg: the burn's tape-pass is **valid iff
BOTH c0 (2572) and c1 (4910) decode orig-exact**. They are not dead weight —
x12 recon showed 6 per-carrier class flips between consecutive burns on the
same deck, so this burn supplies the third native-capture column for the
cross-capture margin gate.

Build provenance (asserted at build time, G1 in the gate report):
- c0/c1 packed blobs adopted byte-identical from `sidecars_m10/` (sha256 +
  CRC32 tables + orig sha asserted vs the master10 manifest).
- c3 packed blob adopted byte-identical from the gated `sidecars_x12_regate/`
  (gzip-mtime trap: a fresh pack is NOT byte-stable; the adopted bytes are the
  ones the 8-seed blocking screen adjudicated).
- Builder refuses to build unless the c3 adjudication verdict is GO; refuses
  to authorize unless the blocking self-check is 3/3 clean.

## 2. Gates already passed (zero tape cost) — receipts in `X12_gate_report.md`

| gate | result |
|---|---|
| G1 build integrity (byte-identical reuse + gated-blob adoption + audio identity vs gated regate wav) | **PASS** |
| G2 no-channel self-check (BLOCKING) | **PASS 3/3 orig-exact**, 0 misc, FA 3.05e-08 (`results/x12_m11_results_selfcheck_nochan.json`) |
| G3 banked regression tape10_run1 (BLOCKING) | **PASS 10/10**, r8 5791 re-lands via x11 rescue, 0 misc, FA identical to banked (`results/x12_m11_results_regress_tape10.json`) |
| G4 banked regression tape9_run1 (BLOCKING) | **PASS 11/11** incl. freqdiff expected-negative 37/37 (`results/x12_m11_results_regress_tape9.json`) |
| regression roll-up | `results/x12_m11_regression_report.json` — **zero_regressions=true** |
| dress rehearsal (NOT a gate) | c0 ORIG 4/4 cells; c1 72/72 all cells (the thrice-falsified sim axis); c3 ORIG 1/4 (cliff-sitting in sim; ships as probe — SER map banks either way) (`results/x12_m11_dress.json`) |

## 3. Operator SOP (tape day)

1. **Dolby NR OFF** (record AND playback). Record level **~7.0** (tape10 proved
   the better channel arrived at LOWER volume — do not chase level).
2. Phone Voice Memos **LOSSLESS** (Settings → Voice Memos → Audio Quality).
   The dress AAC cell failed exactly on the ext band this tape measures — a
   lossy capture degrades the probe's whole purpose.
3. START PHONE FIRST → start deck recording → `bash experiments/tape_v2/play_master11.sh`.
4. Let the FULL tape play past the end chirp (+~1 s); it is only 1.8 min.
5. Readback: speaker ~55, Voice Memos auto-syncs via iCloud:
   ```
   QTA="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta"
   ffmpeg -hide_banner -loglevel error -y -i "$QTA" -ac 1 -ar 48000 experiments/tape_v2/captures/tape11_run1.wav
   python3 experiments/tape_v2/x12_master11_decode.py experiments/tape_v2/captures/tape11_run1.wav
   ```

## 4. Pre-registered outcome thresholds (frozen BEFORE the burn, regate final)

| outcome | rule |
|---|---|
| tape pass VALID | c0 2572 **AND** c1 4910 orig-exact on the capture |
| c3 SUCCESS | byte-exact AND orig-exact at the rate-rule k (=191) → "DBPSK ext-band demonstrated" |
| c3 PARTIAL | per-carrier DBPSK SER table recovered — banks the >9 kHz ext map either way |
| master12 hybrid probe eligible | every ext bin real SER ≤ 0.0202 |
| master12 hybrid stretch eligible | every ext bin real SER ≤ 0.0117 (→ 6317.6 design net) |

Either c3 outcome is bankable: SERs at prediction open RS191-class ext designs
for x13; SERs 3× over kill the ext-band lead with receipts.

## 5. Deliverables manifest (this session)

| artifact | what |
|---|---|
| `x12_master11_master.py` | builder (+ `--authorize` step, gated on the blocking self-check) |
| `master11.wav` (gitignored, regenerable byte-identical) + `master11_manifest.json` + `sidecars_x12_m11/` | the burn artifact; per-codeword CRC32 tables in the manifest |
| `x12_master11_decode.py` | shipping receiver + `--regress tape10|tape9|compare` rig |
| `x12_m11_dress.py` | dress-rehearsal lane (gen per cell + rollup) |
| `play_master11.sh` | operator player (print-authorization check + SOP + progress bar) |
| `results/x12_m11_results_selfcheck_nochan.json` | blocking self-check receipts |
| `results/x12_m11_results_regress_{tape10,tape9}.json` + `results/x12_m11_regression_report.json` | zero-regression receipts |
| `results/x12_m11_results_dress_{s0,s1,aac_s0,clk_s0}.json` + `results/x12_m11_dress.json` | dress receipts |
| `x10_dossier/X12_gate_report.md` | the full gate trail |

New `.gitignore` lines (appended this session):
```
experiments/tape_v2/x12_*.wav
experiments/tape_v2/master11*.wav
```
(captures/, including the dress WAVs and the future tape11 capture, were
already ignored; sidecars + manifests + results JSONs are tracked.)
