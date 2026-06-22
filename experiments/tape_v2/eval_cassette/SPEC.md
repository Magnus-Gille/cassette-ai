# Eval Cassette v1 — product spec + build contract

**Product:** a cassette you insert into ANY deck + speaker + mic setup, play, capture, and decode → it prints a
**report card** telling you (a) the highest **data tier / bitrate** that setup supports, (b) a **channel
characterization**, and (c) **ranked advice** on what to improve. It carries NO useful payload — its job is to
*evaluate the link*. Lower tiers matter: a weak setup should still get a meaningful "you can do Tier 2" result,
not just "fail".

**Architecture = HYBRID predict + confirm:** the front sounder PREDICTS the achievable tier from the measured
channel; the tier ladder CONFIRMS it byte-exact; the report cross-checks the two and explains any gap.

Work in `experiments/tape_v2/eval_cassette/`. Branch `exp/bps-push-2026-06-14`. Reuse proven repo DSP — do not
reinvent modems, sync, or the channel measurement.

---

## 1. The tier ladder (each tier = a known modulation carrying a TINY known payload)

Each tier carries ~256–512 bytes of **seeded-random** payload (byte-exact check = "this tier works on your
deck"). Span robust-floor → cutting-edge. Use reliably-buildable schemes:

| tier | target net bps | scheme (reuse) | enables (real payload at C90 mono) |
|---|---|---|---|
| T0 | ~330 | wide-spaced-tone WS (if locatable in repo; else lowest robust DQPSK) | text / mnist 25 KB |
| T1 | ~540 | BFSK/CAS3 — `cassette_format.encode_audio` (the shipping baseline) | delphi-llama2-100k 147 KB |
| T2 | ~1100 | MFSK-32 (if locatable) or DQPSK P8 N512 | stories260K int4 150 KB |
| T3 | ~2572 | DQPSK P22 N512 sp4 (`m10_master.make_scheme` kind=dqpsk) | stories260K FP32 1.07 MB |
| T4 | ~3360 | d2x P18 drop RS127 (`Dense2xDropScheme`) | DOOM-mini |
| T5 | ~4910 | d2x P21 drop[750] RS159 (DOOM, PROVEN) | DOOM 1.47 MB · chess-gpt borderline |
| T6 | ~5791 | r8 P22 RS179 (`build_dense2x_candidate(22,179)`) — the record | chess-gpt int4 3.2 MB |
| T7 | ~6488 | bulk + 8-DPSK (`bps_push_2026_06_14/candidates/stacked_flagship` or dapsk16 'd') | chess-gpt + headroom |

It is fine to finalize the exact P/N per tier from what builds reliably; keep ~8 tiers spanning ~330→~6500 bps,
each with a KNOWN decode path. If WS / MFSK builders aren't cleanly available, substitute DQPSK-family rungs at
the same bps and note it. Anchor each tier's "enables" label to the real artifacts in `payloads/` (see
`payloads/README.md`): mnist 25 KB, delphi-100k 147 KB, stories260K 150 KB/1.07 MB, DOOM 1.47 MB, chess-gpt
3.2 MB int4. Note in the report that **10 MB+ tiers exist in capacity (electrical/stereo) but have no curated
payload yet** — flag as a gap, don't fake it.

## 2. Characterization sounder (front, ~60 s) — reuse `analyze_master2.py` measurement fns

Reuse the existing sounder + its measurements (H(f), per-tone SNR, flutter from 3 kHz tone, clock from chirp
pair, noise floor from silence). ADD two probes:
- **Two-tone IMD probe** (e.g. 1 kHz + 1.3 kHz equal-amp, ~3 s): measure 3rd-order intermod products → flags
  record-level saturation (the "level 8.5 blooms IMD" failure). Report IMD in dB below carriers.
- **Diffuse-contamination probe** (a 1-bin-spaced multitone, ~3 s): measure off-tone leakage fraction (the
  reverb/room floor that caps acoustic setups) — exactly the `spectral_contamination` measurement.

Output a measured-channel dict: snr_db (median + p10), usable_bw_hz (and HF rolloff dB), flutter_pct, clock,
noise_floor_dbfs, imd_db, diffuse_frac, dropout_rate.

## 3. Tier requirements table (the heart of PREDICT + ADVICE)

For each tier, the minimum channel it needs. Derive from the project's empirical findings + calibrate against
the sim (push the eval master through `src/channel.py` presets pristine/good/normal/worn + `real_channel_sim`
and confirm the predicted tier == the tier that actually closes). Example shape (FILL with calibrated values):

| tier | min SNR | max flutter | min usable BW | max diffuse | notes |
|---|---|---|---|---|---|
| T0 WS | ~12 dB | ~2.5 % | 4 kHz | 0.45 | survives bad acoustic |
| ... | ... | ... | ... | ... | ... |
| T6 r8 | ~30 dB | ~0.45 % | 9 kHz | 0.30 | the record; marginal carriers at 15° |
| T7 bulk+8DPSK | ~32 dB | ~0.40 % | 9.5 kHz | 0.28 | needs cleanest mids |

PREDICT = highest tier whose every requirement the measured channel meets.

## 4. Hybrid decode → report card (`eval_decode.py`)

Input: a capture WAV (or the master itself for self-check). Steps:
1. Global chirp sync + resample (reuse `analyze_master2.global_sync_and_resample`).
2. Characterize (§2) → measured-channel dict.
3. PREDICT tier (§3).
4. CONFIRM: decode every tier's payload; the highest **byte-exact** tier = confirmed tier.
5. Cross-check: if confirmed < predicted → flag (sync/IMD/azimuth issue the metrics missed); if confirmed >
   predicted → the requirements table is conservative (note it).
6. ADVICE: identify the binding bottleneck (the metric that blocks the next tier) and emit ranked actions.

Report card (print + save JSON):
```
=== CASSETTE LINK REPORT CARD ===
Confirmed tier: T5 (~4910 bps)   Predicted: T5   [agree]
Enables: DOOM (1.47 MB) · chess-gpt int4 borderline · all TinyStories
Capacity @ tier: C60 2.2 MB · C90 3.3 MB (mono)
── Channel ─────────────────────────────
 SNR 31 dB (p10 24) · usable BW 9.1 kHz (HF -27 dB) · flutter 0.55%
 clock 0.992x · IMD -33 dB · diffuse 0.31 · noise floor -58 dBFS
── Bottleneck to next tier (T6, 5791) ──
 FLUTTER 0.55% > 0.45% limit
 → #1 service deck: belt/capstan/pinch-roller          (+1 tier)
 → #2 capture with Voice Memos not Continuity-mic       (+1 tier)
 → #3 HF rolloff -27 dB: clean heads / check azimuth     (+0.5)
```

## 5. Advice engine (metric → diagnosis → action)

Map each measured metric, when it's the binding constraint, to ranked actions:
- **SNR low** → level too low / cable / amp / mic quality / quieter room / closer mic.
- **HF rolloff / low BW** → dirty or misaligned heads (clean + azimuth) · worn tape · speaker or mic HF response.
- **flutter high** → deck mechanical service (belt, capstan, pinch roller) · OR capture clock (use Voice Memos,
  not Continuity/live-Mac mic which jitters).
- **clock far from 1.0** → deck speed (decoder handles it, but note belt wear).
- **IMD high** → record level too high (drop to ~7.0) · Dolby must be OFF.
- **dropouts** → clean heads · better tape · check head contact.
- **diffuse high** → acoustic loop reverb: deader/quieter room, closer mic, direct coupling, or **go electrical
  line-in** (the real fix).
Each action tagged with expected tier gain.

## 6. Validation (HARD GATE before declaring done)

- **No-channel self-check:** build the eval master, decode it with no channel → EVERY tier byte-exact AND the
  characterization returns sane values (clean channel → high SNR, ~0 flutter, full BW). Hard gate.
- **Through-sim:** push the master through `src/channel.py` presets (pristine/good/normal/worn) and
  `real_channel_sim` (master3) → confirm the CONFIRMED tier drops as the channel worsens, and that PREDICT
  tracks CONFIRM (calibrate the requirements table until they agree within ±1 tier across presets). Report the
  predict-vs-confirm table per preset.

## 7. Deliverables
`eval_master.py`, `eval_decode.py`, `eval_master.wav` (gitignored) + `eval_manifest.json` (tracked),
`results/eval_selfcheck.json`, `results/eval_sim_validation.json`, and `EVAL_REPORT.md` (how to use it +
the per-preset validation table). Commit scripts + manifest + JSONs on the branch.
