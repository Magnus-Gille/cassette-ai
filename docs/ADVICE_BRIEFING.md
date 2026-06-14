# Cassette-AI — project briefing & request for advice

*Self-contained summary for a fresh reviewer. I'd like your help deciding how to proceed
(see "What I'm asking you" at the end).*

---

## The goal

Store digital data — ultimately a tiny but **real, runnable LLM** — on an ordinary
audio **cassette tape**, and read it back **acoustically** with no special hardware:
play the tape on a normal deck, let its speaker play into a **phone microphone**, and
decode the audio back to the exact original bytes. The romantic target: a language model
you can literally hold on a cassette and "play."

The hard requirement is **byte-exact** recovery (the model weights must come back
bit-for-bit), through a genuinely bad analog channel.

---

## What we've actually achieved (the milestone)

**24,576 bytes of a real quantized LLM recovered BYTE-EXACT off a physical cassette,
acoustically, through the air.** Recorded our master tape to a real cassette, played it
back (deck speaker → iPhone Voice Memos → iCloud → decode). Raw bit error rate 0.46%,
0 of 222 Reed–Solomon codewords failed (clean, not FEC-rescued). The model is Karpathy's
`stories260K` (260K params, 512-token vocab, int4-quantized → ~150 KB), which still writes
coherent TinyStories after the round trip.

So the end-to-end acoustic loop **works**. We have since **pushed the proven rate to
562 bps** (see "latest real result" below) — the full 150 KB model now fits a 60-minute
cassette. We are pushing further.

---

## The technical stack

**Channel.** Cassette tape (Dolby OFF) → deck speaker → ~1 m of room air → phone mic →
AAC-compressed `.qta` file via Voice Memos → iCloud. On a quiet living room this measures
**~40 dB SNR, ~0.3–0.4% wow/flutter**, with a strong HF rolloff (tones at 9 kHz are ~20×
weaker than at 500 Hz) plus reverb that smears energy across nearby frequency bins
(~25% diffuse, time-varying cross-bin "contamination").

**Modulation (the PHY that won).** `WS_M16_K1_sp3_N256` — "wide-spaced tones." 16 candidate
tones spanning 560 Hz–9 kHz, **spaced 3 FFT bins apart (562 Hz guard)** so the reverb skirt
of one tone doesn't bleed into its neighbor. One tone on per symbol (orthogonal MFSK,
4 bits/symbol), 256 samples/symbol at 48 kHz → **750 gross bps**. Detection is a **contrast
detector** (pick the bin that stands out most after per-tone equalization), which beats the
contamination floor that defeats narrow-spaced or multi-tone (k-of-M) schemes.

**Sync & equalization.** Each tape opens with a wideband **chirp**, a ~45 s **channel
sounder** (known multitone), and closes with another chirp. The decoder uses the two chirps
to recover deck speed and align globally, then reads the sounder to measure the live channel
H(f) and build a **per-tone EQ** that flattens the HF rolloff before detection. (One-shot
pre-computed EQ is useless — the channel is **time-varying** take to take; the sounder must
be read fresh from each recording.)

**FEC.** Reed–Solomon over the whole payload + **global column-interleave** of the codewords
across modem frames, so one fully-desynced frame corrupts only a few bytes per codeword
(well within RS's correction budget). We ladder the **RS rate** to trade robustness for speed.

**Capture path.** iPhone **Voice Memos → iCloud** (NOT live mic capture — the iPhone-as-mic
and laptop-mic paths have a jittery sample clock that smears every narrowband tone and makes
decode fail at chance). Voice Memos' ADC clock is sample-accurate; that was the unlock.

---

## What we learned along the way (the non-obvious bits)

- **Live mic capture is dead** for data — sample-clock jitter (~2.6 s returned for a 3 s
  request) destroys narrowband tones. The sample-accurate Voice-Memos path fixed it.
- **One-shot EQ / channel pre-inversion is dead** — the channel is time-varying; intelligence
  must live in the receiver, reading a fresh sounder each take.
- **Narrow-spaced and k-of-M (multi-tone) schemes fail** on the diffuse contamination floor.
  **Wide tone spacing + contrast detection** was the creative win that broke through.
- **CSS (LoRa-style chirp spread-spectrum)** looked great in simulation (processing gain,
  ~0 contamination floor) but **failed on the real tape** (raw BER 0.19–0.25) — a real
  sim→real gap (pilot-timing didn't transfer). Wide-spaced tones is the proven PHY; CSS is
  parked.
- We built a **faithful channel simulator** calibrated to our measured tape that correctly
  predicts real failures the naive simulator missed. It runs **~5–8× more pessimistic** than
  our actual best captures, so "passes in the faithful sim" is a strong (conservative) signal.

---

## Current state: the rate-push (a tape is recording right now)

We over-coded the milestone ~5× (0.46% real BER vs RS correcting 28%), so there's lots of
headroom. Three test tapes, all self-checking byte-exact and validated through the faithful
sim:

- **master5** — same proven PHY (M16), **lighter RS rates** ladder: RS(255, 111/159/191/223).
- **master6** — a **geometry change** (a second AI agent's challenger): `WS_M32_K2_sp2_N320`,
  **8 bits/symbol, 1200 gross bps** — RS(255, 95/111/127/159/191).
- **master7** — the two **merged into one 15.6-min tape** (one sync, 9 rungs) so a single
  capture decides the winner. *This is what's recording now.*

**Net payload bitrates (post-FEC, mono — the acoustic loop sums to one channel):**

| Config | Bitrate | Proof status |
|---|---|---|
| M16 RS(255,111) | 326 bps | ✅ proven byte-exact on real tape (first milestone) |
| M16 RS(255,191) | **562 bps** | ✅ **proven byte-exact on real tape (latest, master7)** |
| M16 RS(255,223) | 656 bps | ✗ failed on real tape (9/37 codewords over budget) |
| M32 turbo RS(255,191) | 899 bps | ✗ failed on real tape (raw BER 0.08–0.14; only the heavily-coded M32 RS95/447 bps survived) |
| Wired stereo OFDM (USB line-in) | ~4860 bps | sim only; needs a ~€30 interface; ×2 stereo |

### Latest real result (master7 tape, just decoded)

A single 15.6-min cassette carrying **9 rungs** (the M16 RS-ladder + the M32 turbo ladder)
was recorded and decoded. Channel this take: clock 1.0022×, **flutter 0.37%, SNR 36.4 dB**
(noisier than our 40 dB best — noise floor −48 dBFS vs −53/−58 before). Outcome:

- **M16 RS(255,191) = 562 bps recovered byte-exact** — a new proven rate, ~1.7× the old
  326 bps milestone. M16 RS(255,111) also byte-exact. (M16 RS159 missed by 1 codeword and
  RS223 by 9 — variance/bursts at the margins, expected.)
- **M32 turbo confirmed AAC-fragile in reality, not just in sim:** raw BER 0.08–0.14 on the
  dense rungs; only the most heavily-coded M32 (RS95, 447 bps) survived. The 8-bits/symbol,
  2-bin-spaced geometry does **not** transfer to the compressed acoustic path. This matched
  the faithful sim's prediction exactly.

**Storage capacity** (mono acoustic, total tape = both sides; model = 150 KB):

| Rate | C60 (60 min) | C90 (90 min) | full model in |
|---|---|---|---|
| 326 bps (proven) | 143 KB | 215 KB | 63 min (fits C90) |
| 562 bps | 247 KB | 370 KB | 37 min |
| 899 bps (turbo) | 395 KB | 593 KB | 23 min |
| ~4860 bps (wired) | 2.1 MB | 3.1 MB | 4 min |

**Model tiers we could target** (int4 sizes): current = stories260K **150 KB** (fits C90 today)
and a same-tier MIT llama2-100k **147 KB**; **next tier** = delphi **Mamba-200k 479 KB**
(reachable only if the 899-bps turbo geometry holds on real tape); above that, a **chess-GPT
3.2 MB** that needs the wired path.

---

## The open question (now sharpened by the real result)

We tried to beat the M16 PHY with a denser M32 "turbo" geometry (8 bits/symbol, 2-bin tone
spacing, 899 bps). It is rock-solid on a clean simulated tape but **failed on the real,
AAC-compressed acoustic path** (raw BER 0.08–0.14) — only its most heavily-coded rung
(447 bps) survived, *below* what plain M16 already gives. So **denser tone packing is the
wrong lever** against this channel; the AAC perceptual codec (which discards/quantizes HF)
is the real wall.

Meanwhile M16 with lighter FEC just gave us **562 bps byte-exact on real tape**. So the
proven frontier is ~562 bps (full model in 36.5 min, fits a C60). The question is how — or
whether — to push past it on the no-hardware acoustic path, given AAC is the binding
constraint, versus switching strategy (bigger model at 562 bps, or the wired ~4860 bps lane).

---

## What I'm asking you

I'd value an outside technical read. Specifically:

1. **Denser tone packing (M32 turbo) just failed on real tape** — verdict is in. Given that,
   what modulation would *you* reach for to beat 750 gross bps on a flutter-y, HF-limited,
   **AAC-compressed** acoustic link? Is there any rate headroom left on the no-hardware path,
   or is ~562 bps near the practical ceiling?
2. **AAC is the binding adversary** on the acoustic path (perceptual codec discards
   "inaudible" HF and quantizes spectrally). Are there modulation/coding choices robust to
   psychoacoustic compression specifically — keeping energy where AAC preserves it (mid-band,
   tonal), spreading, pilot design, or shaping to look "loud" to the codec's masking model?
3. **FEC strategy.** We use RS + global interleave. Given a low-rate but *bursty* channel
   (occasional whole-frame desyncs from flutter), would a soft-decision / LDPC / fountain
   approach meaningfully beat RS here, or is RS the right tool at this scale?
4. **Are we missing an obviously better approach** to the core problem (byte-exact digital
   over a flutter-y, HF-limited, AAC-compressed acoustic cassette link)? Any prior art we
   should steal from (acoustic data-over-sound, DTMF-era modems, deep-space coding)?
5. **Where to invest next:** push the acoustic rate further, accept ~562 bps and chase a
   bigger/better-curated model, or commit to the wired (~4860 bps) path for the high-rate
   demo? What would you prioritize and why?

Constraints: must stay **byte-exact**; the headline demo is **no special hardware**
(speaker→mic), with wired as an acknowledged "fast lane." Python/numpy/scipy stack;
Reed–Solomon via `reedsolo`. Happy to provide any specific numbers or code you want to see.
