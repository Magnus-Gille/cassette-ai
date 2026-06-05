# Cassette-AI End-to-End Runbook

A small digital payload is encoded as BFSK audio (the CAS3 modem in
`src/cassette_format.py`), played out of the laptop onto a real cassette, recorded
back, and decoded. The codec's own demodulator assumes perfect, fixed timing — it
cannot survive a real record/playback loop. So everything here goes through the
**robust front-end** in `tests/e2e/cassette_e2e.py`, which: cross-correlates the
recording against the sync chirp to find the data start (so leading/trailing silence
is irrelevant), resamples any recording rate back to 48 kHz, removes DC and
normalizes gain, and — the key trick — **brute-forces a small tape-speed search**
(≈0.94–1.06×) to undo the constant speed difference between the record deck and the
play deck. Because flutter accumulates within a pass, keep the message **small**
(tens to low-hundreds of bytes).

> **Validate in software first.** Before touching tape, prove the whole chain works:
> ```
> cd /Users/magnus/repos/cassette-ai
> python3 tests/e2e/loopback_selftest.py
> ```
> All six cases (including `speed_fast`, `speed_slow`, `rate_44100`) must print
> `PASS` and the run must end with `ALL PASS`.

---

## PART A — Encode the message

```
cd /Users/magnus/repos/cassette-ai
python3 tests/e2e/encode_message.py \
    --text "hello cassette ai 2026" \
    --out tests/e2e/artifacts/signal.wav
```

This produces two files:

- `tests/e2e/artifacts/signal.wav` — 16-bit PCM mono, 48 kHz, the audio you play to
  the deck. Contains a 2 s leader, a sync chirp, the BFSK data, and a trailer, padded
  with 0.5 s of silence each end.
- `tests/e2e/artifacts/signal.wav.payload.bin` — the exact original bytes, used by the
  decoder to verify a byte-exact match.

Keep messages short. The encoder warns above 512 bytes; for a reliable first physical
run, stay well under that (a short sentence is ideal).

---

## PART B — Physical record / playback

**Gear:** a cassette deck (or portable recorder), a blank cassette, and two audio
cables.

**Cabling:**
- **Cable 1 (record):** laptop **headphone / line OUT** → deck **LINE IN**.
- **Cable 2 (capture):** deck **LINE OUT** → laptop **line / mic IN**.

**Levels (do this before committing a take):**
- Laptop output volume ~**70–80%**. Loud enough to drive the deck, not so loud it
  clips. Clipping flattens the tone peaks and destroys the demod.
- Set the deck's **record level** so its meters peak **near 0 dB without pinning**
  into the red. A quick rehearsal pass while watching the meters is worth it.

**Record (laptop → tape):**
1. Put the deck in record-pause, then start recording.
2. Play the signal on the laptop:
   ```
   afplay tests/e2e/artifacts/signal.wav
   ```
3. Let it finish, then stop the deck. Leave a second or two of silence before and
   after — the decoder finds the chirp by correlation, so exact start/stop timing
   does not matter.

**Capture (tape → laptop):** rewind the cassette to before the recorded section,
then capture the deck's playback into `recorded.wav`.

*ffmpeg (avfoundation) — list input devices first:*
```
ffmpeg -f avfoundation -list_devices true -i ""
```
Note the index of your audio input (the line/mic IN your capture cable is plugged
into), then start the capture, press play on the deck, and stop with `q` when done:
```
ffmpeg -f avfoundation -i ":<device#>" -ac 1 -ar 48000 recorded.wav
```
(`-ac 1` = mono, `-ar 48000` = 48 kHz; any rate is fine — the decoder resamples — but
48 kHz matches the codec and is simplest.)

*GUI fallback — QuickTime Player:* File → **New Audio Recording**, click the chevron
next to the record button to pick the correct input, set the input level, record the
deck's playback, then **File → Export As → Audio Only** to a `.wav` (or `.m4a`; the
decoder reads what `soundfile`/ffmpeg can open).

---

## PART C — Decode and compare

```
cd /Users/magnus/repos/cassette-ai
python3 tests/e2e/decode_recording.py \
    --wav recorded.wav \
    --expect tests/e2e/artifacts/signal.wav.payload.bin
```

Success prints `VERDICT: PASS (exact byte match)` and exits 0. The report also shows
the chosen **speed ratio** (how much speed error it corrected, e.g. 1.01 ≈ +1% fast
deck) and the **chirp correlation peak** (signal-quality proxy; higher is better).

You can also compare against a literal string with `--text "hello cassette ai 2026"`,
or get machine-readable output with `--json`.

---

## PART D — Troubleshooting

- **Low `corr_peak` (e.g. < 0.3) / no chirp found.** Levels too low or a cabling
  problem. Raise the laptop output and/or deck record level, confirm both cables are
  in the right jacks (OUT→IN both directions), and that the capture is actually
  picking up the deck (watch the input meter in QuickTime). Re-record.
- **FAIL with garbled / partial bytes.** Two usual causes:
  - **Speed error beyond the search range.** The default search covers ≈ ±6%
    (`0.94–1.06`). A very off-speed deck needs a wider grid:
    ```
    python3 tests/e2e/decode_recording.py --wav recorded.wav \
        --expect tests/e2e/artifacts/signal.wav.payload.bin \
        --speed-lo 0.90 --speed-hi 1.10 --speed-step 0.005
    ```
  - **Input clipping.** If the deck output or laptop input was driven into the red,
    the tones distort. Lower levels and re-record.
- **Still failing?** Shorten the message and re-run PART A→C. Smaller payloads keep
  wow/flutter drift well under one bit and are the most reliable. And always confirm
  the software chain is healthy first:
  ```
  python3 tests/e2e/loopback_selftest.py
  ```
