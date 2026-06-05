# cassette-ai

Can you store data — eventually an LLM — on a normal audio cassette? This repo is the
viability sprint that answers that, plus a working **end-to-end test** that records a
small digital payload to tape and reads it back.

## TL;DR

- **Codec:** `src/cassette_format.py` — a BFSK modem + framed container (CAS3) at
  48 kHz, 1200 bit/s.
- **Channel model:** `src/channel.py` — a realistic consumer-cassette simulator
  (band-limiting, wow/flutter, AWGN, dropouts) used to evaluate the codec.
- **End-to-end tape test:** `tests/e2e/` — encode a message → play to a deck → record
  back → decode → byte-compare. Built on a **robust front-end** that survives the
  things a real tape does to a signal (silence offsets, gain/DC, resampling, and tape
  speed error).
- **Verdict (digital sprint):** see `STATUS.md` / `REPORT.md`. Storing a full LLM
  payload reliably did **not** clear the bar in corrected-channel simulation; the
  small end-to-end tape test below is the physical-loop proof-of-concept.

## The end-to-end tape test

The codec's own demodulator assumes perfect fixed timing and cannot survive a real
record/playback loop. Everything in `tests/e2e/` goes through the robust front-end in
`tests/e2e/cassette_e2e.py`, which finds the data by cross-correlating against the sync
chirp (leading/trailing silence is irrelevant), resamples any recording rate back to
48 kHz, removes DC / normalizes gain, and **brute-forces a small tape-speed search**
(≈0.94–1.06×) to undo the constant speed difference between the record and play decks.
Keep messages **small** (a short sentence) — flutter accumulates within a pass.

### Validate in software first (no tape needed)

```
python3 tests/e2e/loopback_selftest.py
```

Runs the whole chain through the channel simulator across six impairment cases
(clean, silence-offset, band-limit+noise, speed-fast, speed-slow, 44.1 kHz rate
mismatch). All must print `PASS` / `ALL PASS`.

### Physical run (laptop → tape → laptop)

```
# A. Encode a message to a playable WAV (+ a payload sidecar for verification)
python3 tests/e2e/encode_message.py --text "hello cassette ai 2026" \
    --out tests/e2e/artifacts/signal.wav

# B. Record signal.wav to the deck, then capture the deck's playback to recorded.wav
afplay tests/e2e/artifacts/signal.wav                       # play while deck records
ffmpeg -f avfoundation -list_devices true -i ""             # find your input device #
ffmpeg -f avfoundation -i ":<device#>" -ac 1 -ar 48000 recorded.wav   # capture playback

# C. Decode and byte-compare against the original
python3 tests/e2e/decode_recording.py --wav recorded.wav \
    --expect tests/e2e/artifacts/signal.wav.payload.bin
```

Success prints `VERDICT: PASS (exact byte match)`. **Full cabling, levels, and
troubleshooting: [`tests/e2e/README.md`](tests/e2e/README.md).**

## Setup

```
python3 -m pip install numpy scipy soundfile matplotlib   # core
# ffmpeg required for arbitrary-format capture/convert (brew install ffmpeg)
```

Python 3.10+. The research pipelines additionally use `transformers`, `torch`, and
`reedsolo`; HuggingFace models are cached in `hf_cache/` (gitignored).

## Layout

| Path | What |
|---|---|
| `src/` | codec, channel model, v2/v3 modem pipelines, ECC/UEP experiments |
| `tests/e2e/` | end-to-end tape test (encode/decode CLIs, self-test, runbook) |
| `docs/cassette_format.md` | CAS3 container + physical-layer spec |
| `RESULTS/` | research outputs (CSV/JSON data, PNG plots); large audio cache is gitignored |
| `STATUS.md`, `REPORT*.md`, `agents.md` | sprint status, findings, conventions |
