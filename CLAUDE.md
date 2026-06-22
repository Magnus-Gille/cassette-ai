# Cassette-AI — project instructions

Storing digital data (eventually a tiny LLM) on an ordinary audio cassette. The project
is now firmly in the **physical-loop** phase (record to tape → play back → capture →
decode), which **supersedes the old `agents.md` "don't attempt physical hardware
integration" rule** — that line is stale; ignore it.

## Capturing tape playback — USE VOICE MEMOS → iCloud (the proven path, 2026-06-08)

**Do NOT try to live-capture the iPhone mic on the Mac.** We burned an evening on it:
the iPhone-as-Continuity-mic path is unreliable for data — it pops "the microphone is not
available", and when it *does* open (ffmpeg avfoundation, even `sox -t coreaudio`) the
sample clock is **jittery**, which smears every narrowband tone and makes decode fail at
chance. The MacBook's own mic via ffmpeg has the same clock-jitter problem. Confirm the
clock-jitter tell quickly: `sox`/`ffmpeg` returning ~2.6 s for a `-t 3` request = bad clock.

**The reliable method (no AirDrop, no Continuity):**
1. Record the tape playback **on the iPhone in Voice Memos** (its ADC clock is sample-accurate).
2. It **auto-syncs via iCloud** to the Mac — no AirDrop needed (AirDrop's P2P link is flaky
   on this setup). The file lands at:
   `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<YYYYMMDD HHMMSS>-*.qta`
   (`.qta` = Voice Memos' AAC/QuickTime container; ffmpeg reads it directly).
3. Convert + analyze (the analyzer accepts any sample rate / mono-or-stereo):
   ```
   QTA="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta"
   ffmpeg -hide_banner -loglevel error -y -i "$QTA" -ac 1 -ar 48000 experiments/tape_v2/captures/<name>.wav
   python3 experiments/tape_v2/analyze_master2.py experiments/tape_v2/captures/<name>.wav
   ```
   Trim a long over-run with `-t <sec>` before analysis if Voice Memos kept running.
   Captures are gitignored (`experiments/tape_v2/captures/`) — large, irreplaceable; back up.

**Operator flow:** phone Voice Memos record → wait ~1 s → play tape from the start → let the
FULL master play (don't stop till the end chirp) → stop phone → the file appears in iCloud.
Arbitrary lead-in before the tape is fine — the analyzer's chirp search handles it (fixed
2026-06-08: it now searches a generous lead-in window, not just the first 5 s).

**What we learned about the channel (2026-06-08, first real capture):** on a quiet living-room
acoustic loop the capture is **excellent — 39 dB SNR, 0.44 % flutter**, far better than the
prior worst-case (~12.6 dB / 2.2 %). The acoustic loop is not the enemy when the setup is clean.
Stereo ×2 capacity is still **electrical-only** (one speaker → one mic = one summed channel);
the **electrical line-in** path (USB interface, e.g. Behringer UCA222) remains the unlock for
the high-rate OFDM configs. See `experiments/tape_v2/REAL_DECODE_FINDINGS.md`.

## Capturing via the UCA222 electrical line-in + PortAudio (the WIRED path, 2026-06-22)

A Behringer UCA222 USB interface now gives a clean **electrical** capture — deck line-out
(or, for a no-tape loopback, the deck's **record-pause / "source" monitor**) → UCA222 RCA in
→ USB. Sample-accurate, and it unlocks **true stereo** (independent L/R, not the acoustic
summed-mono).

**THE GOTCHA — do NOT capture with ffmpeg avfoundation.** On this Mac it silently **drops
~11.5 % of samples** every run (a 16 s grab → ~14.2 s of audio; tones un-shifted, so it's
dropped samples, not a resample). The clock gremlin lives in the *capture software*, not the
UCA222 (its ADC reads a true 48 kHz). **Capture with PortAudio instead:**
```
python3 experiments/tape_v2/capture_uca.py <seconds> <out.wav>   # streaming, sample-accurate, 0 xruns
```

**Wiring / stereo tooling (`experiments/tape_v2/`):**
- `loopback_check.sh` — live **no-tape** wiring check (Mac out → deck source monitor → UCA222):
  routing (L/R swap), level/clip, crosstalk (dB), clock — from front 1000/1700 Hz probes.
- `make_stereo_cal_master.py` → `stereo_cal_master.wav` (proven ladder on L+R + crosstalk probes);
  `analyze_stereo_cal.py <capture>` → routing/level/crosstalk/clock + splits L/R for per-channel decode.
- d2x high-bitrate harness: `make_d2x_cal.py` / `decode_d2x_cal.py` (~4910 bps vs a seeded payload),
  `d2x_loopback.sh` (mono), `make_d2x_stereo_cal.py` + `d2x_stereo_loopback.sh` (stereo).
- **Real-tape d2x proof** runbook: `d2x_tape_proof.sh {record|capture}` (record cal_d2x_stereo.wav →
  tape → rewind → play → `capture_uca.py` → decode L+R). Independent-payload variant (rigorous true-2x,
  different data per channel): `make_d2x_stereo_indep_cal.py` + `d2x_tape_proof.sh {record-indep|capture-indep}`.
- **Full-spectrum test tape** (`fullspectrum_master.py` / `fullspectrum_decode.py` / `fullspectrum_proof.sh`):
  ONE master that grades a setup across the whole tier under one sync — ladder 1868→9820 bps (R0 robust mono …
  R3 4910/ch independent-stereo). Phone capture grades the acoustic ceiling; wired reaches 9820. `fullspectrum_manifest.json`
  + `fullspectrum_sidecars/` tracked. (v2 TODO: sub-kbps BFSK floor + eval report-card scoring.)

**Results (2026-06-22):** d2x byte-exact over the electrical loopback (mono ×2 + stereo, ~9820 bps), **and**
the **real-tape d2x STEREO proof PASSED** — recorded to a physical cassette, played back via UCA222, decoded
byte-exact on BOTH channels (0/944 cw each, worst crosstalk −44 dB; `results/d2x_tape_stereo_proof_2026-06-22.json`).
~9820 bps stereo is now TAPE-proven. Still open: the independent-payload true-2x tape pass + the full-spectrum
tape pass (both await the deck). Full arc: `REAL_DECODE_FINDINGS.md`.

**The Magnetic Vault site** (`magnetic-vault/`): rebuilt in the moodboard aesthetic (Bauhaus × cassette j-card)
and **deployed to Cloudflare Pages** (direct upload, NOT the public GitHub repo): https://magnetic-vault.pages.dev
(client-side password gate, `wrangler pages deploy magnetic-vault --project-name=magnetic-vault` to redeploy).
Moodboard photos there are third-party reference-only/temporary — strip before any public push.

## Record/playback level SOP (do not skip)
- **Dolby NR OFF** at both record and playback (companding mangles multitone/QAM).
- **Record level ~7.0**, not 8.5 (8.5 saturates → IMD floor blooms, kills dense carriers).
- **Readback speaker ~55** (rms ~0.04, loud but no clip).
- **~1 s silence** around the start/end chirps — they are the sync anchors; if clipped,
  global alignment fails. Start the phone capture FIRST, then the tape.

## Decoding a capture
```
python3 experiments/tape_v2/analyze_master2.py <recording.wav>
```
Recovers deck speed, re-measures the real channel from the front sounder, scores every
config (pass-rate + raw BER → projected net bps + whole-file recoverability). Results land
in `experiments/tape_v2/results/`.

## Repo orientation
- `src/hyp_common.py` — frozen evaluation harness (channel → BER → net-bps projection). The
  yardstick for every modem. `src/channel.py` — the cassette channel model. `src/cassette_format.py`
  — the shipping BFSK/CAS3 codec.
- `experiments/capacity/` — the 5-hypothesis capacity campaign (C1 Gray, C2 combinatorial
  k-of-M, C3 soft-FEC, C4 bit-loaded OFDM, C5 FTN). Adjudication: `docs/capacity_pushing_results.md`.
- `experiments/tape_v2/` — the physical tape test (master ladder + analyzer). `master2.wav`
  + `_sim_*.wav` are gitignored (regenerable via `make_master2.py`); sidecars are tracked.
- `experiments/dpd/` — prior real-tape channel characterization (`channel_model.json`) + cassette-LLM proof.
- `docs/audio_magic_{deep,overview}.html` — full + plain-language writeups of the DSP.
- `experiments/tape_v2/doom_ship/` — the **DOOM-on-cassette ship pipeline**. `m10doom3_*` = the
  DOOM v3 tape (full Freedoom Episode 1 + WebAudio sound + saves + THE MAGNETIC VAULT custom E1M1),
  encoded at the proven d2x 4910-bps config. **PROVEN: decoded BYTE-EXACT off a real cassette
  (2026-06-13)** — `results/m10doom3_results_doom_tape_readback.json`. Burn: `play_doom_tape_v3.sh`
  (side A) / `play_doom_tape_sideb.sh` (side B = DECODED album + GPL source). Decode: `m10doom3_decode.py`.
  **WEB HOSTING GOTCHA:** `doom_cassette_v3.html` embeds wasm+wad as a raw **windows-1252** byte
  carrier (optimal for the tape's lzma budget) and only works over `file://`. Served over HTTP,
  the `Content-Type: charset=utf-8` overrides `<meta charset>` and corrupts the payload (wasm
  `CompileError`). For web hosting use `build/assemble_html_web.py` → `dist/doom_cassette_web.html`
  (base64 carrier, charset-immune) — that's what GitHub Pages (https://magnus-gille.github.io/cassette-ai/)
  serves. The tape build stays cp1252.
- `experiments/tape_v2/x10_*..x12_*` + `m10_*` — the rate campaigns (record 5791 bps) + the composed
  `m10_decode.py` / `x11_decode.py` superset receiver (resampling-PLL + ensemble-union + carrier-class
  erasure rescue). Dossiers in `experiments/tape_v2/x10_dossier/`.
- `payloads/` — candidate tape payloads (tiny permissive LLMs + DOOM). `README.md` + `fetch_payloads.sh`
  tracked; binaries gitignored. `payloads/doom/` = the WASM build + custom level + reports.
- `experiments/tape_v2/bside_remix/sideB/` — **DECODED**, the 9-track album built from the real data
  signal (B-side art); `LINER_NOTES.md` + `TRACKLIST.txt` + per-track scripts tracked, WAVs gitignored.

## Conventions
- Python 3.11+, numpy/scipy/soundfile/reedsolo; prefer `scipy.signal` over hand-rolled DSP.
- Random seeds always set and logged; the harness is seed-deterministic.
- Big WAVs are gitignored (regenerable from scripts); commit on a feature branch, never push to `master` directly.
- Multi-agent experiment orchestration via the Workflow tool is the established pattern here.
