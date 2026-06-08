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

## Conventions
- Python 3.11+, numpy/scipy/soundfile/reedsolo; prefer `scipy.signal` over hand-rolled DSP.
- Random seeds always set and logged; the harness is seed-deterministic.
- Big WAVs are gitignored (regenerable from scripts); commit on a feature branch, never push to `master` directly.
- Multi-agent experiment orchestration via the Workflow tool is the established pattern here.
