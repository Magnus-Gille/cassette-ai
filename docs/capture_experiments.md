# Capture-Path & Channel Experiments: Does the Payload Fit on One Cassette?

*Synthesis of three Monte-Carlo experiments simulating the computer -> tape -> computer chain.
All runs use the CAS3 BFSK codec (48 kHz, 1200 bit/s, tones at 1200/2400 Hz), the realistic
`cassette_channel` simulator, and the robust decoder front-end. No physical tape was used.*

Data: `RESULTS/data/exp_impairment_ladder.csv`, `RESULTS/data/exp_capture_paths.csv`,
`RESULTS/data/exp_capacity_cliff.csv`
Plots: `RESULTS/plots/exp_impairment_ladder.png`, `RESULTS/plots/exp_capture_paths.png`,
`RESULTS/plots/exp_capacity_cliff.png`

---

## 1. Question & Method

**The reliability ladder (Exp A).** Starting from a perfect transmission, we layer one realistic
tape impairment at a time — band-limit, additive noise, wow/flutter, burst dropouts, steady speed
offset, then a fully "realistic normal deck", then a "worn deck" — and measure where clean decoding
first breaks. This isolates *which* physical impairment dominates reliability, rather than lumping
them into a single pessimistic blob. N=24 seeds, 512-byte synthetic payload per cell.

**The capture-path comparison (Exp B).** The tape core (record electronics + tape + playback head)
is common to every capture path. After it, the playback-to-computer ADC stage differs: a transparent
USB soundcard, a purpose-built phone app capturing raw PCM, a standard voice-recorder app (AAC 64k
via real ffmpeg roundtrip), and a VoIP app (Opus 24k narrowband via real ffmpeg roundtrip). We run
each capture path over both a "normal" and a "worn" tape preset to see whether the capture stage or
the tape itself is the bottleneck, and measure each path's effective bandwidth from a chirp sweep.

**The MB-per-cassette projection (Exp C).** We find the highest gross bit rate each capture path can
sustain below a target bit-error-rate (1e-3 and the stricter 1e-4), apply an assumed outer-code rate
of 0.8 and a stereo (2-track) factor, and project payload megabytes onto a C60 and C90 against the
hard target: the UEP-encoded TinyStories-1M payload of **1.271 MB**. This answers "does it fit on one
cassette, and under what capture setup?"

---

## 2. Finding 1 — Burst Dropouts, Not Flutter, Are the First Cliff (Exp A)

The hypothesis going in was that wow/flutter would be the reliability killer. **It is not.** At
"normal" tape levels the codec is completely immune to band-limit, noise, and flutter:

| Rung | Impairment added | P(clean) | mean frame recovery | mean BER |
|------|------------------|---------:|--------------------:|---------:|
| 0 | perfect | 1.000 | 1.000 | 0.0% |
| 1 | + band-limit (12 kHz) | 1.000 | 1.000 | 0.0% |
| 2 | + noise (SNR 42 dB) | 1.000 | 1.000 | 0.0% |
| 3 | + flutter (0.10% wrms) | 1.000 | 1.000 | 0.0% |
| 4 | + dropouts (0.3/s, 6 ms) | **0.958** | 0.979 | 4.2% |
| 5 | + speed offset (+1%) | 0.958 | 0.979 | 4.2% |
| 6 | realistic_all (+/-1.5% cross-deck) | 0.958 | 0.979 | 4.2% |
| 7 | worn_deck (SNR 36, BW 9k, WF 0.25%, burst 1.0/10ms) | **0.667** | 0.854 | 22.9% |

Source: `RESULTS/data/exp_impairment_ladder.csv`, `RESULTS/plots/exp_impairment_ladder.png`.

**The first and only cliff in the normal regime is burst dropouts** (rung 4: 1.000 -> 0.958). Flutter
at 0.10% wrms (rung 3) costs *nothing* — the chirp-sync front-end absorbs the timebase warp. Steady
speed offset, even cross-deck +/-1.5% (rungs 5-6), also costs nothing: the robust decoder's speed
search fully compensates, leaving metrics identical to rung 4. The biggest single drop is the jump to
a worn deck (rung 7: 0.958 -> 0.667, a 29-point fall), driven by the *combination* of heavier
dropouts (1.0/s, 10 ms) and lower SNR (36 dB) plus a coarser flutter — but note even here the worn
deck still recovers 85% of frames on average, a strong partial-credit regime where an LLM-tolerant
encoding or fountain code would salvage most of the payload.

**Verdict on the hypothesis:** flutter is *not* the killer at realistic levels. The reliability
budget is dominated by **burst dropouts**, with SNR as the secondary factor on worn tape. Speed
offset is a solved problem in software.

---

## 3. Finding 2 — Capture Path: Custom App ~= Soundcard; Standard App Caps Your Future (Exp B)

| Tape | Capture path | P(clean) | frame recovery | -3 dB BW | -20 dB BW |
|------|--------------|---------:|---------------:|---------:|----------:|
| normal | USB soundcard | **1.00** | 1.00 | 10.5 kHz | 13.0 kHz |
| normal | phone custom PCM | **1.00** | 1.00 | 10.5 kHz | 13.0 kHz |
| normal | voice recorder AAC 64k | 0.50 | 0.75 | 7.8 kHz | 9.5 kHz |
| normal | VoIP Opus 24k | 0.29 | 0.56 | **3.8 kHz** | 5.1 kHz |
| worn | USB soundcard | 0.54 | 0.75 | 8.8 kHz | 10.6 kHz |
| worn | phone custom PCM | 0.54 | 0.73 | 8.8 kHz | 10.6 kHz |
| worn | voice recorder AAC 64k | 0.08 | 0.27 | 7.6 kHz | 8.9 kHz |
| worn | VoIP Opus 24k | 0.04 | 0.19 | 3.8 kHz | 5.3 kHz |

Source: `RESULTS/data/exp_capture_paths.csv`, `RESULTS/plots/exp_capture_paths.png`.

**USB soundcard vs phone:** A purpose-built phone app capturing raw PCM is **indistinguishable from
a USB soundcard** — identical P(clean) and identical bandwidth on both normal (1.00) and worn (0.54)
tape. The custom app's ~65 dB ADC noise and slight clock offset are swamped by the tape core; the
capture stage adds *zero* overhead when it is built to preserve full bandwidth and disable
processing. On worn tape, the tape itself is the bottleneck and both transparent paths land at 0.54.

**Custom app vs standard app:** This is the decisive contrast.

- The standard **voice-recorder (AAC 64k)** path drops P(clean) from 1.00 to **0.50** on normal tape
  (a 50-point reliability loss) and caps bandwidth at ~7.8 kHz.
- The **VoIP (Opus 24k narrowband)** path is worse: P(clean) 0.29 on normal tape, with a hard **3.8
  kHz** band-limit.

The critical framing is *not* "does it pass today." The slow 1200/2400 Hz BFSK tones *just barely
survive* even the 3.8 kHz VoIP cap — that is why Opus still scrapes a 0.29 pass rate. **But the 3.8
kHz ceiling permanently caps the rate.** Any attempt to scale throughput (higher-rate FSK, QAM, or
tones above ~3 kHz) is *destroyed* by the standard app's band-limit, while a custom/soundcard path
offers ~10.5 kHz of usable bandwidth — roughly 3x the headroom. A standard voice app does not just
add noise; it amputates the spectrum you would need to ever go faster.

**Answer:** Use a transparent capture (USB soundcard or a custom raw-PCM phone app — they are
equivalent). **A standard voice app is a dead end**, not because it fails today, but because its
bandwidth cap forecloses any future rate increase.

---

## 4. Finding 3 — It Does NOT Fit on One Cassette at the Current Rate (Exp C)

| Capture path | reliable gross (BER<1e-3) | net stereo | MB / C60 | MB / C90 | % of 1.271 MB on C90 |
|--------------|--------------------------:|-----------:|---------:|---------:|---------------------:|
| USB soundcard | 600 bps | 960 bps | 0.429 | 0.645 | **50.7% (FAIL)** |
| phone custom PCM | 600 bps | 960 bps | 0.429 | 0.645 | **50.7% (FAIL)** |
| voice recorder AAC 64k | 600 bps (1e-3 only) | 960 bps | 0.429 | 0.645 | 50.7% (FAIL); fails 1e-4 |
| VoIP Opus 24k | **0 bps** | 0 | 0.000 | 0.000 | **0% (FAIL)** |

Source: `RESULTS/data/exp_capacity_cliff.csv`, `RESULTS/plots/exp_capacity_cliff.png`.
(C60/C90 MB are equal across the 1e-3 column because all viable paths cap at the same 600 bps reliable
rate; the C90's longer runtime is the only difference, captured in the per-tape-length projection.)

**No configuration clears the bar.** The best transparent paths (soundcard / custom PCM) reach 0.645
MB on a C90 — exactly **50.7%** of the 1.271 MB TinyStories-1M target. The AAC path matches at the
loose 1e-3 threshold but fails the strict 1e-4 (codec noise floor). The VoIP Opus path delivers **0
reliable bits** — its mean BER at 600 bps (1.27e-3) already exceeds the threshold.

**Root cause of the 600 bps ceiling:** wow/flutter at 0.10% wrms produces up to ~14 samples of
cumulative timing drift. At the codec's native 1200 bps (40 samples/bit) this collapses BER from 0
to ~42%. A simple DLL timing recovery only gets 1200 bps down to ~9% BER — still far above any
FEC-cleanable level. The fix is a closed-loop hardware-style PLL tracking the slow ~0.55 Hz flutter,
which is not in the current software modem. The Shannon ceiling of the tape core (SNR 42 dB, 11 kHz)
is ~153 kbps, so 600 bps is **<0.4% of capacity** — the headroom is enormous; the binding constraint
is the timing loop, not bandwidth or noise.

**To fit 1.271 MB on a C90 in stereo** you need net >= ~1893 bps -> gross >= ~2366 bps -> a reliable
**2400 bps**, which is 4x the current ceiling and blocked entirely on wow/flutter timing recovery.

---

## 5. Recommendation

**Recommended capture setup: USB soundcard.** It is the transparent ceiling path (P(clean)=1.00 on
normal tape, full ~10.5 kHz bandwidth) and requires zero development. A custom raw-PCM phone app is
*equivalent in measured performance* — so the decision to build one is purely about field
convenience, not data quality.

**Should we build a custom phone app? Only if mobile capture is a hard requirement.** The quantified
reason: a custom app buys **+0.50 P(clean) over the AAC voice recorder and +0.71 over VoIP Opus** on
normal tape, and — more importantly — it preserves ~10.5 kHz of bandwidth versus 3.8 kHz for the
standard app, the ~3x headroom you must have to ever scale past 600 bps. But it buys *nothing* over a
USB soundcard. **Build the custom app only to enable phone-based capture; for the bench, use the
soundcard.** Never rely on a standard/off-the-shelf voice app — it both halves reliability today and
caps your future rate.

**Top channel assumptions needing real-hardware confirmation tomorrow:**

1. **Measured wow/flutter spectrum and magnitude.** The 600 bps ceiling — and the entire fit/no-fit
   verdict — hinges on flutter-induced timing drift. The simulator uses two sinusoids (0.55 Hz, 4.8
   Hz); a real deck has a continuous 1/f spectrum plus reel-motor instability. Measure the actual
   flutter PSD; it decides whether a PLL can recover 1200-2400 bps.
2. **True effective bandwidth of the actual deck/tape.** We assume ~11 kHz usable on a normal deck.
   The capacity headroom (and any high-rate ambition) depends on this; confirm the real -3 dB point
   with a chirp sweep through the physical record/playback chain.
3. **Same-deck vs cross-deck steady speed offset and burst-dropout statistics.** Speed offset was
   shown to be software-solvable, but the *dropout rate and burst length* are the dominant reliability
   driver (Finding 1) and the existing REPORT.md notes real captures show much longer low-energy
   segments than the 6 ms simulator bursts. Measure real dropout length distribution on the target
   tape stock — it is the single biggest uncertainty in the reliability budget.

---

## 6. Caveats

- **Raw-BER proxy.** Exp C measures raw bit-error-rate without CAS3 framing, so it does not capture
  header/tail-hash effects or frame-level burst clustering. Actual packet loss under bursts may differ
  from the BER projection.
- **Assumed outer-code rate 0.8, flat.** A real RS/LDPC code's effective rate depends on burst length
  versus interleaver depth; this is not modeled. The MB projections scale linearly with this
  assumption.
- **Stereo = 2x independent channels.** Real cassettes have ~30-35 dB L/R crosstalk; treating the two
  tracks as fully independent is optimistic at high rates and would degrade a stereo-encoded scheme.
- **Simulation-only.** No physical tape was used. The channel model omits AGC pumping detail, lossy-
  codec frequency-specific distortion at the FSK tones, and continuous-spectrum flutter. Shannon
  ceilings use rough effective-SNR offsets for the codec paths (-6 dB AAC, -12 dB Opus), not measured.
- **Confidence intervals.** N=24 seeds gives roughly +/-10 percentage points on P(clean) for the
  stochastic lossy paths (AAC/Opus). Order-of-magnitude conclusions hold; exact pass rates would
  tighten with N=48.
