# RECORD_ME_v4 — recording master4.wav onto a physical cassette

`master4.wav` is a recordable cassette master that carries REAL data via **two
validated audio modulation schemes**, each with its own decoder in
`m4_decode.py`. It is the acoustic-channel integration of the two schemes that
SURVIVED the faithful real-channel sim (see `REAL_DECODE_FINDINGS.md`):

- **Scheme 1 — WIDE-SPACED TONES** (`WS_M16_K1_sp3_N256`): K-of-M tones spaced
  3 FFT bins apart with empty guard bins, so the channel's adjacent-bin smear
  lands in ignored guards, not on data tones. Per-frame modulation; the decoder
  estimates a per-tone EQ from this recording's own sounder. RS rate **(255,111)**.
- **Scheme 2 — CHIRP SPREAD-SPECTRUM (CSS/LoRa-style)** (`sf=6, bw=9000, fc=5000`):
  one **pilot-aided** chirp stream per payload (`pilot_every=2`, Gray-coded). CSS
  spreads each symbol over the whole band; the matched dechirp re-concentrates the
  true symbol while the diffuse contamination averages out (processing gain). RS
  rate **(255,95)**.

Both schemes use `m3_codec.encode_payload/decode_payload` ONLY for the
Reed-Solomon + global byte-interleave framing; the scheme itself does the actual
tone/chirp modulation of the framed bits.

## What is on the tape (~16.8 min, one side)

```
~1 s silence -> GLOBAL up-chirp -> ~0.4 s gap -> ~45 s channel sounder -> ~0.4 s gap
  -> SCHEME-1 (wide-spaced) payloads -> ~0.4 s gap
  -> SCHEME-2 (CSS chirp) payloads   -> ~0.4 s gap
  -> GLOBAL down-chirp -> ~1 s silence
```

The two wide-band chirps let the decoder self-locate and recover deck speed even
with an arbitrary recorder lead-in. The 45 s sounder gives a fresh channel readout
(H(f), SNR, flutter %, noise floor) for THIS recording — the wide-spaced decoder
divides out the measured H(f) to flatten the channel before tone detection.

### Payloads

| Payload | Scheme | RS | What it is |
|---|---|---|---|
| `ws_test2k`  | wide-spaced | (255,111) | 2 KB known random test block (fixed seed) |
| `ws_llm24k`  | wide-spaced | (255,111) | `stories260K_int4.cass[:24576]` (24 KB real data) |
| `css_test2k` | CSS chirp   | (255,95)  | 2 KB known random test block (fixed seed) |
| `css_llm6k`  | CSS chirp   | (255,95)  | `stories260K_int4.cass[:6144]` (6 KB real data) |

The exact known bytes of each payload are in `sidecars_m4/<name>.bin` for byte
comparison after recovery.

## How to record (CRITICAL — follow exactly, per CLAUDE.md)

**Use Voice Memos -> iCloud, NOT Continuity live-capture.** Continuity live-capture
has resampling/dropout artifacts that have broken past decodes. The reliable path is:

1. Copy `master4.wav` to the iPhone (AirDrop or iCloud Drive).
2. Play `master4.wav` from the phone into the cassette deck (LINE IN if available,
   otherwise a clean acoustic/mic path) and record onto a **fresh, recently-used tape**.
3. **Dolby OFF** on both record and playback. Dolby NR mangles the tone spectrum.
4. **Levels:** aim for a healthy VU but DO NOT pin into the red. The master is
   peak-normalised to 0.95; record so peaks sit around 0 VU / -3 dB, not clipping.
5. Record the **full ~16.8 min pass** in one take. Do not pause.
6. Leave **~1 s of clean silence around the chirps** (the master already has lead/tail
   silence; just don't start the tape on top of the up-chirp or cut the down-chirp).
7. **Phone close to the speaker helps** on an acoustic loop: the wide-spaced scheme
   closes at the measured contamination, but a tighter coupling (phone jammed on the
   speaker, or a blanket over both) adds margin — most useful for the CSS payloads on
   the AAC/voice-memo path.

### Playback / capture for decoding

1. Play the recorded tape back into the Mac via a clean line-in / USB soundcard, OR
   record the speaker with Voice Memos on the phone (NOT Continuity live-capture).
2. Save as WAV (or convert). Any sample rate is fine; `m4_decode.py` resamples to
   48 k and the chirps recover the residual deck speed.
3. Decode:

   ```
   python3 experiments/tape_v2/m4_decode.py <capture.wav> --out-tag tapeN
   ```

   The decoder prints a per-payload table (scheme, RS rate, bytes, frames, raw error
   rate, RS codewords failed, byte-exact YES/no) and writes
   `results/m4_results_<tag>.json`. Byte-exact is judged by direct comparison to the
   `sidecars_m4/<name>.bin` known bytes.

## Sim expectation (before you record)

`m4_sim_validate.py` runs master4.wav through the faithful `real_channel_sim` at
`capture=master3` (clean tape) and `capture=master2` (AAC voicememo) and decodes with
the same `m4_decode` pipeline — the honest pre-record expectation for what the real
tape should reproduce.
