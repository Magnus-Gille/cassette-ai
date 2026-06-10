# Cassette-AI Companion App — High-Level Design & Architecture

**Status:** Scoping draft (2026-06-10)
**Author:** Design pass (Claude Code)
**Audience:** Magnus + future implementer

> The app *is* the product. A data-cassette without an easy decoder is a dusty
> curio; with a one-tap "watch an AI boot off a cassette" experience, it's a
> magic trick worth €25–60. This doc scopes that app: capture, visualization,
> decode, and a "test my setup" calibration flow that maps a user's room/gear to
> the tape tiers they can actually read.

---

## 1. Goals & Non-Goals

**Goals**
- Replace the brittle Voice Memos → iCloud lab workflow with first-class raw PCM capture.
- Turn decode into a *show*: live spectrogram, sync-lock, SNR/flutter gauges, CRC progress, and a payload "boot" moment.
- Let a buyer self-qualify their setup *before* buying or before blaming the tape ("Robust: YES / Turbo: YES / Moonshot: marginal").
- Serve three users: **the buyer**, **the demo viewer/camera**, and **Magnus in the lab**.

**Non-Goals (for now)**
- Android at launch (audio paths are heterogeneous — see §5).
- On-device decode of the highest tiers at MVP (server does the heavy lift first — see §6).
- Replacing the Python reference stack. Python stays the **source of truth**; the app is a port/client validated against it.

---

## 2. Users & Journeys

### 2a. The Buyer (primary)
1. Buys a tape (or wants to try the included demo). Scans the **QR code on the J-card** → app installs / deep-links to that tape's manifest.
2. App offers **"Test My Setup"** (§7). Gets a tier verdict. Adjusts (phone closer, level down, lossless on).
3. Hits **Record**, presses Play on the deck. Watches the waterfall lock, gauges settle, CRC tick to 100%.
4. **Boot moment:** payload decodes and *runs* — the on-tape LLM starts emitting a story on screen; a chess tape opens a board; a book tape renders text.

### 2b. The Demo Viewer / Camera (marketing)
- Someone is filming the screen for the marketing video. The visualization must look *great on camera*: big waterfall, satisfying lock animation, gauges that move, a climactic boot. This journey shares the decode screen but with a **"Stage" / presentation mode** (hide chrome, enlarge viz, optional auto-narration captions).

### 2c. Magnus in the Lab (dogfood)
- Same capture engine, but with **Pro/Lab mode**: export raw 48 kHz WAV (the exact artifact `analyze_master2.py` consumes), dump the measured sounder metrics as JSON, tag captures, and one-tap share to the Mac. This replaces Voice Memos *and* gives Magnus the cleanest possible captures for the research loop. Lab mode is a hidden toggle, not a separate app.

---

## 3. The Three App Surfaces (feature scope)

### 3.1 Lossless Capture (replaces Voice Memos)
- Raw **48 kHz, mono or stereo, float32** PCM, **no OS voice processing** (AGC / AEC / noise suppression OFF — these would mangle narrowband tones).
- **Pre-capture noise check:** 1–2 s ambient listen → show room noise floor (dBFS) and warn if too loud / too reverberant.
- **Live level guidance:** a headroom meter with a hard "CLIPPING" alarm. Clipping kills the sync chirps — this is non-negotiable UX (already a known failure mode).
- **Lossless storage** (the artifact must be PCM/ALAC-equivalent, never AAC). Default AAC injects masking-skirt noise next to tones and historically forced ~2.5× wider carrier spacing = much lower rates.
- Capture lead-in is free-form: the decoder's chirp search tolerates arbitrary silence before the tape starts. Operator flow: tap Record → press Play → let the full master play to the end chirp → Stop.

### 3.2 Visualization (the demo-magic)
A single decode screen, composited from cheap-to-compute live signals:
- **Waterfall / spectrogram** (FFT of the live capture) — the hero element.
- **Sync-lock indicator** — chirp found → "LOCKED" with deck-speed readout (clock ratio).
- **Gauges:** SNR (median + p10), flutter %, noise floor, clipping. Driven by the sounder section once it plays.
- **Per-carrier health** — constellation cluster *or* a simpler bank of per-carrier SNR bars (constellation is prettier on camera; bars are cheaper and clearer for grading).
- **CRC/codeword progress** — Reed-Solomon codewords passing CRC32, a bar ticking to 100%, with a visible "errors corrected" counter (FEC is doing visible work).
- **Boot moment** — on full decode + payload verify, transition into the payload runtime (LLM text stream / chess board / book reader).

> Note: most of these signals (FFT waterfall, chirp lock, sounder SNR/flutter) are
> **front-end metrics the phone can compute live even if the actual payload decode
> happens server-side** (see hybrid strategy §6). The viz never has to wait on the
> full decode to feel alive.

### 3.3 "Test My Setup" (two-stage calibration — see §7)
- **Stage A (channel-only):** play a published calibration tone, phone listens, grades **speaker + room + mic + capture codec**. Does NOT test the deck/tape (no flutter, no wow).
- **Stage B (full-chain):** every real tape carries a short **calibration leader** (a sounder section) before the payload. Reading that leader grades the *whole* chain including the actual deck's flutter/azimuth. The app already gets this for free from the sounder — Stage B is "your first real capture also calibrates you."

---

## 4. Tier-Grading Spec

### 4.1 Tiers (from business context)
| Tier | Rate | Setup demand |
|------|------|--------------|
| **Robust** | ~560–930 bps | survives mediocre setups + AAC re-encode |
| **Turbo** | ~1.5–2.5 kbps | decent setup + lossless capture |
| **Moonshot** | ~4–5 kbps | good setup, phone close, quiet room |

### 4.2 Measured metrics (these already exist in `analyze_master2.py`'s sounder)
The Python sounder emits exactly the inputs a grader needs. Reuse the same names so the app and the reference agree:
- `snr_db_median`, `snr_db_p10` — broadband and worst-case SNR.
- `frac_below_8db` — fraction of carriers below the usable floor (null/reverb tell).
- `flutter_wrms_pct` — wow/flutter (deck health; **only available in Stage B / real tape**).
- `noise_floor_dbfs` — ambient + electronic noise.
- `clock_ratio` / `recovered_clock_from_tone` — deck speed offset.
- `H(f)` / `snr_db_per_tone` — frequency response shape (room nulls, HF rolloff).
- **Clipping flag** and **capture codec** (lossless vs AAC) — app-side, gate Turbo/Moonshot on lossless.

### 4.3 Verdict logic (skeleton — thresholds TBD from lab data)
```
codec      = capture_format          # lossless | aac
clip       = peak_dbfs > -1.0        # any clip → robust-only at best
snr        = snr_db_median
snr_p10    = snr_db_p10
nulls      = frac_below_8db
flutter    = flutter_wrms_pct        # None in Stage A (no tape)

robust   = (snr   >= T_R_SNR) and (nulls <= T_R_NULLS) and not clip
turbo    = robust and (codec == "lossless") and (snr_p10 >= T_T_SNRP10)
                   and (nulls <= T_T_NULLS)
moonshot = turbo  and (snr    >= T_M_SNR)    and (snr_p10 >= T_M_SNRP10)
                   and (nulls <= T_M_NULLS)  and (flutter in (None, <= T_M_FLUT))

# Each tier returns YES / MARGINAL / NO + the single most actionable fix:
#   "move phone closer" (low snr_p10), "lower record level" (clip),
#   "switch to lossless" (codec), "quieter room" (noise_floor), ...
```
Thresholds (`T_*`) must be **calibrated from lab captures** — run the existing
`analyze_master2.py` across the corpus of good/marginal/bad captures and read off
the metric values where each tier's decode starts failing. Ship them as a
versioned `grading.json` so they can be tuned without an app update.

---

## 5. Platform Recommendation

**Recommendation: native iOS (Swift / AVAudioEngine), iPhone-only at launch.**
The whole project already depends on the iPhone's sample-accurate ADC clock
(Mac mics / Continuity mic are clock-jittery and fatal). The app must guarantee:
raw 48 kHz float PCM, **no AGC/AEC/noise-suppression**, lossless storage. Only
native iOS gives that guarantee cleanly.

### Why not the alternatives

**Web app (getUserMedia on iOS Safari) — rejected for capture.**
iOS Safari/WebKit does **not** reliably deliver raw, unprocessed, fixed-48 kHz PCM:
`echoCancellation` is on by default and historically ignored the constraint;
`noiseSuppression` / `autoGainControl` / `channelCount` are not supported in WebKit;
sample rate is not reliably settable (macOS Safari pins 44.1 kHz). For a narrowband
multitone modem that *requires* AGC/AEC off and a known clock, this is a
non-starter for the capture path.
([webkit bug 179411](https://bugs.webkit.org/show_bug.cgi?id=179411),
[getUserMedia constraints](https://blog.addpipe.com/getusermedia-audio-constraints/))
A web app remains viable only as a *no-capture* companion (manifest browser,
marketing, "how it works") — not the decoder.

**Flutter / React Native — viable but risky for the capture core.**
Packages like `record`, `flutter_sound`, `mic_stream` expose PCM streams, but the
high-fidelity, voice-processing-OFF, measurement-mode path still requires dropping
to native (platform channels) — so you write the hard part in Swift anyway and
inherit a plugin's abstraction as a liability.
([record](https://pub.dev/packages/record),
[flutter_sound](https://pub.dev/packages/flutter_sound)).
Reasonable for the *UI shell* later if Android matters; not worth it for v1.

**Android — later, explicitly.** Android's audio stack is heterogeneous across OEMs
(AudioRecord `UNPROCESSED`/`VOICE_RECOGNITION` source support, sample-rate
resampling, and per-device DSP all vary). It can work, but it needs a per-device
qualification effort that dwarfs the iOS path. Defer until the iOS product is proven.

### The iOS capture facts (verified)
- **Measurement mode** (`AVAudioSession.Mode.measurement`) is the documented way to
  minimize system-supplied input processing (AGC/AEC/etc.) for measurement-style
  capture.
  ([measurement mode](https://developer.apple.com/documentation/avfaudio/avaudiosession/mode-swift.struct/measurement))
- Set the category to `.record` (or `.playAndRecord` for Stage A, which plays the
  test tone while listening), mode `.measurement`, then
  `setPreferredSampleRate(48000)` **after activation** and read back the granted
  `sampleRate`.
  ([setPreferredSampleRate](https://developer.apple.com/documentation/avfaudio/avaudiosession/1616523-setpreferredsamplerate))
- Voice processing is **off by default** on the input node; explicitly do **not**
  call `setVoiceProcessingEnabled(true)`. (And note the documented gotcha: enabling
  voice processing can leave the engine not running.)
  ([AVAudioEngine notes](https://snakamura.github.io/log/2024/11/audio_engine.html))
- iOS caps to 48 kHz for many paths anyway, which is exactly the target rate.
  ([iOS 48 kHz cap](https://benefic.com/blog/why-ios-caps-usb-dacs-at-48khz))

> **Open verification item:** confirm on-device that `.measurement` + 48 kHz yields
> a clean, AGC-free narrowband tone (no pumping, flat noise floor) by capturing the
> existing master and decoding it with the Python stack. This is a half-day spike
> and de-risks the whole platform choice.

---

## 6. DSP / Decode Engine Strategy

The Python stack (chirp sync → sounder → DQPSK/combo demod → RS+CRC → gzip unpack)
is the reference. Re-implementing all of it natively up front is the slow path and
risks subtle divergence. Phased plan:

### Phase 1 (MVP) — Hybrid: on-device front-end + server decode
- **On device (Swift + Accelerate/vDSP):** the *cheap, live* parts — FFT waterfall,
  chirp matched-filter sync + clock ratio, and the sounder metrics (SNR/flutter/
  noise floor). These power the live viz **and** the tier grader, and they're small,
  well-bounded DSP.
- **Server (the existing Python, unchanged):** the *hard* part — full DQPSK/combo
  demod + RS errors-and-erasures + CRC + unpack. App uploads the captured **lossless
  WAV** (or a losslessly-compressed FLAC) + tape ID; server returns the decoded
  payload + per-codeword CRC trace for the progress animation.
- **Why:** ships fastest, keeps Python as the single source of truth, makes new
  tape formats a server-side change (no app release). Cost: needs connectivity for
  the payload, and a backend.

### Phase 2 — On-device decode for the Robust tier
- Port the Robust-tier demod path to Swift/Accelerate (or a shared **Rust/C++ core**
  compiled for iOS, which keeps one codebase and is FFI-friendly to a future
  Android port). Robust tier is the most-shipped, most-latency-sensitive (offline,
  instant boot). Higher tiers can stay server-assisted longer.

### Phase 3 — Full on-device, offline
- Port the remaining tiers. The app decodes everything locally; server becomes
  optional (analytics, format updates).

### Golden-test discipline (all phases)
- Freeze a set of **golden vectors**: input WAV → expected sounder metrics →
  expected demod symbols → expected payload bytes/sha256, generated by the Python
  stack. The native port must reproduce them bit-exactly (or within a stated
  tolerance for the float metrics). This is the contract that prevents drift, and
  it's cheap to maintain since Python already produces these artifacts
  (`m8_decode.py` verifies against manifest sha256 today).

> **Compute reality check:** the current Python decode of a full master is seconds,
> not real-time, on a laptop. On-device, the FFT/sync/sounder front-end is easily
> real-time; the RS+combo decode is the unknown — measure it before committing to
> Phase 2/3 timelines. Hybrid sidesteps this risk for MVP.

---

## 7. Test-Signal Distribution Analysis

**The core wrinkle:** YouTube and Spotify re-encode all audio lossily — YouTube to
**AAC ~128 kbps or Opus ~165 kbps**, Spotify to **Ogg Vorbis up to 320 kbps**,
Apple Music to **AAC 256 kbps**. A test signal *streamed* from these services tests
a **harsher** channel than a real cassette read with lossless capture. Also, a
streamed tone tests **speaker + room + mic** but **not the deck/tape** (no flutter).
([Spotify/Apple codecs](https://hifiwalker.com/blogs/dap-guides-tips/apple-music-vs-spotify-a-comparison-of-audio-quality),
[YouTube audio encoding](https://support.google.com/youtube/answer/4603579))

### Two-stage test story (the resolution)

**Stage A — Channel test (codec-aware), streamed or bundled.**
Grade speaker+room+mic. Two ways to host, both useful:
1. **App-bundled lossless WAV played through the phone, or AirPlay/cast to the
   user's speaker.** This is the *clean* channel test — no streaming codec in the
   path. Recommended default. (Plays from the same device that captures, so the
   phone's own speaker→room→mic loop is what's graded; AirPlay/cast lets the user
   grade their *good* speaker.)
2. **A real "calibration track" distributed via DistroKid to Spotify/YouTube/Apple.**
   Genuinely fun and on-brand (a track literally named "Cassette-AI Calibration
   Tone"), and it doubles as marketing. But it goes through the streaming codec, so
   it must be **codec-robust by design** — built from the proven wide-spaced robust
   configs that already survive AAC. Use it to grade the *worst-case streamed*
   channel; treat a pass here as conservative ("if you pass the streamed test,
   you'll do better off a real tape"). Don't use it to grade Turbo/Moonshot.

**Stage B — Full-chain test (the real unlock).**
Every shipped tape carries a **calibration leader**: a sounder section before the
payload. The first real capture *is* the full-chain calibration — it measures
flutter, deck speed, azimuth-induced HF loss, and real SNR, all of which Stage A
cannot. The app already extracts these from the sounder. So the honest tier verdict
is: **Stage A pre-qualifies (channel only); Stage B confirms (whole chain) on first
play.**

### Recommendation
- **MVP:** app-bundled lossless calibration WAV for Stage A (no streaming-codec
  confound, no distribution dependency) + sounder-leader for Stage B.
- **Marketing add-on:** distribute a codec-robust "Calibration Tone" single via
  DistroKid for reach and fun; surface it in the app as an *optional* "test with
  your hi-fi" path, clearly labelled as the conservative streamed test.

---

## 8. System Architecture

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │                         iPhone App (Swift / SwiftUI)                   │
 │                                                                        │
 │  Capture Engine            Live DSP Front-End        Payload Runtime   │
 │  ───────────────           ──────────────────        ───────────────   │
 │  AVAudioEngine             vDSP/Accelerate:           LLM text stream / │
 │   .measurement, 48k,        FFT waterfall             chess board /     │
 │   voice-proc OFF,           chirp sync + clock        book reader       │
 │   float32, lossless         sounder metrics           (the "boot")      │
 │       │                       │  (SNR/flutter/nf)        ▲              │
 │       │                       ▼                          │              │
 │       │                  Tier Grader  ◄── grading.json   │              │
 │       │                  (verdict + advice)              │              │
 │       ▼                                                  │              │
 │  Lossless WAV/FLAC ─────────────► (Phase 1) ─────────────┘              │
 │       │                            decode request                      │
 └───────┼────────────────────────────┼──────────────────────────────────┘
         │ Lab export                  │
         ▼                             ▼
   Mac / research loop          ┌──────────────────────┐
   (analyze_master2.py)         │  Decode Backend       │
                                │  (existing Python:    │
                                │   DQPSK/combo + RS +  │
                                │   CRC + gzip unpack)  │
                                │   = source of truth   │
                                └──────────┬───────────┘
                                           │ payload + CRC trace
                                           ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  Content / Manifest Service (static, CDN-able)                         │
 │   • per-tape manifest (section map, RS params, CRC32 tables, sha256)   │
 │   • grading.json (tier thresholds, versioned)                          │
 │   • calibration WAV (Stage A)                                          │
 │   • format/codec registry (new tape formats → no app release)          │
 └──────────────────────────────────────────────────────────────────────┘
         ▲
         │ tape ID
   ┌─────┴─────┐
   │ QR on     │   J-card QR encodes tape-ID URL →
   │ J-card    │   app deep-links, fetches that tape's manifest.
   └───────────┘
```

**Key architectural choices**
- **Manifests are per-tape, static, CDN-hosted, content-addressed.** A tape's QR
  encodes a tape-ID URL; the app fetches manifest + CRC tables + sha256 guards. New
  formats ship as new manifests — no app update needed for new tapes.
- **`grading.json` is versioned and remote** — tune tier thresholds from lab data
  without shipping a build.
- **The Python decode service is the contract.** Native ports validate against its
  golden vectors. Until ports exist, it *is* the decoder (Phase 1 hybrid).
- **Lab export is a first-class path**, not an afterthought — it's how Magnus's
  research loop keeps feeding the modem work.

---

## 9. MVP → v2 → v3 Roadmap

### MVP (target: a few weeks, solo + AI)
**In:**
- Native iOS capture: `.measurement`, 48 kHz, float32, voice-proc off, lossless export.
- Clipping/level meter + ambient pre-check.
- Live FFT waterfall + chirp-lock indicator + SNR/flutter/noise gauges (on-device front-end).
- **Phase-1 hybrid decode:** upload lossless capture → existing Python backend → payload back.
- Boot moment for **one** payload type (the LLM story — the headline demo).
- Stage A test with an **app-bundled** calibration WAV; tier badges with the verdict skeleton.
- QR → manifest fetch for one tape.
- Lab export (raw WAV + metrics JSON) to satisfy Magnus's workflow.

**Explicitly CUT from MVP:**
- On-device payload decode (server does it).
- Android.
- Web companion.
- DistroKid streamed calibration track (use bundled WAV).
- Per-carrier constellation (ship the cheaper SNR-bar version).
- Multiple payload runtimes (just the LLM story; chess/book later).
- Presentation/Stage mode polish (basic screen is fine for the first marketing cut).

### v2
- On-device **Robust-tier** decode (Swift/Accelerate or Rust core) → offline, instant boot for the most-sold tier.
- Stage/presentation mode for marketing; richer viz (constellation, FEC-correction counter).
- Additional payload runtimes (chess board, book reader).
- DistroKid streamed calibration single + in-app "test with your hi-fi".
- Per-tape onboarding polish, store integration (deep-link from e-store purchase).

### v3
- Full on-device decode (all tiers), offline-first; server optional.
- Android (after per-device audio qualification).
- Shared Rust/C++ DSP core across iOS+Android, golden-vector-gated.
- Analytics on real-world tier pass-rates → feed threshold tuning + product copy.

---

## 10. Risks & Open Questions

**Capture fidelity (highest risk).**
- *Does `.measurement` + 48 kHz truly disable AGC and give a clean tone on real
  hardware?* Verify with a device spike (capture the master, decode in Python)
  **before** building UI. This is the load-bearing assumption.
- Lossless storage path must never silently fall back to AAC. Assert format on write.

**iOS audio session gotchas.**
- Sample rate must be read back after activation (preferred ≠ granted).
- Stage A plays audio *while* recording → needs `.playAndRecord`; ensure the
  played calibration tone isn't suppressed by any residual echo handling and
  doesn't get AGC'd. May prefer AirPlay-out + mic-in to fully decouple.
- Interruructions (calls, other audio) mid-capture must abort cleanly, not corrupt.

**App Store review.**
- Mic permission needs a crisp `NSMicrophoneUsageDescription` ("to decode audio
  from your cassette"). Low risk but get the copy right.
- A novelty "decode audio into an AI" app is benign for review; the on-device LLM
  payload is just bundled/decoded data + a tiny runtime — no special entitlements.
  Confirm no issue with executing decoded model weights (it's data, not code).

**On-device compute (defers, doesn't block).**
- RS + combo decode time on-device is unmeasured. Hybrid avoids it for MVP; measure
  before committing to v2 on-device timelines.

**Backend dependency (MVP).**
- Phase-1 needs connectivity for the payload. Acceptable for a "watch it boot" demo;
  call it out in UX (and it's the reason v2 brings Robust-tier decode on-device).

**Tier thresholds are unknown until calibrated.**
- The grader is only as good as `grading.json`, which needs a lab-capture corpus
  spanning good/marginal/bad setups. Generate it from `analyze_master2.py` runs
  before promising verdicts in marketing.

**Test-signal honesty.**
- Stage A (channel-only) can't see flutter; never let the UI imply a full-chain
  pass from Stage A alone. The "first real capture confirms" framing must be in the
  copy so a buyer isn't surprised when a flutter-heavy deck underperforms its Stage-A
  grade.

---

## Appendix — Reference files (source of truth)
- `experiments/tape_v2/m8_decode.py` — manifest-driven full decode (sync → sections → RS/CRC → unpack).
- `experiments/tape_v2/h4_dqpsk.py` — DQPSK multi-carrier demod (self-referencing pilot).
- `experiments/tape_v2/analyze_master2.py` — sounder + per-config grading; **emits the exact metrics the tier grader needs**.
- `experiments/tape_v2/sim_v2.py` — channel/sim harness.
- `experiments/tape_v2/REAL_DECODE_FINDINGS.md` — real-channel capture lessons.
- `CLAUDE.md` (project) — capture SOP, level discipline, the Voice-Memos-lossless path this app replaces.
