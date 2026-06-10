# CassetteAI — companion app

The consumer-facing decoder + capture app for data cassettes, and the lab
replacement for the Voice-Memos→iCloud capture workflow. See the full design in
[`docs/COMPANION_APP_DESIGN.md`](../docs/COMPANION_APP_DESIGN.md).

> The app captures lossless 48 kHz PCM off a tape deck, shows a live decode
> "show" (waterfall, sync-lock, SNR/flutter gauges, CRC progress, payload boot),
> and grades a user's setup against the Robust / Turbo / Moonshot tiers. The
> Python reference stack in `experiments/tape_v2/` stays the source of truth;
> the app is a Phase-1 **hybrid** client (on-device front-end DSP + server decode).

## Architecture

```
  iPhone app (SwiftUI)                          Backend (FastAPI, Python)
  ┌───────────────────────────┐                 ┌────────────────────────────┐
  │ CaptureEngine             │  lossless WAV   │ POST /api/captures         │
  │  AVAudioEngine            │ ──────────────► │   → m8_decode.py (subproc) │
  │  .measurement, 48k float32│                 │   → job_id                 │
  │  voice-proc OFF, lossless │  poll           │ GET  /api/jobs/{id}        │
  │                           │ ◄────────────── │   → stage/progress/result  │
  │ CassetteDSP (Accelerate)  │                 │                            │
  │  WaterfallProcessor (FFT) │  Stage-A WAV    │ POST /api/setup-test       │
  │  LevelMeter (clip/RMS)    │ ──────────────► │   → analyze_calibration.py │
  │  ChirpSync, SounderAnalyzer│                │   → metrics + tier verdicts│
  │  SetupGrader  ◄ grading   │  GET            │ GET  /api/grading          │
  │                           │ ◄────────────── │   → grading.json (versioned)│
  │ BackendClient (async)     │  GET            │ GET  /api/tapes/{id}/manifest│
  └───────────────────────────┘                 │ GET  /api/calibration (WAV)│
                                                 └────────────────────────────┘
```

Three components, each owns its directory:

| Path | What | Build/test |
|------|------|-----------|
| `ios/CassetteDSP/` | Swift Package: live DSP core (FFT waterfall, level/clip meter, chirp sync, sounder metrics, tier grader) + golden-vector XCTests. No third-party deps; Apple frameworks only (Accelerate/vDSP). | `swift test` |
| `ios/CassetteAI/` | SwiftUI app: capture, decode "show", Test-My-Setup, library, settings. Tape-deck-industrial aesthetic. iOS 17, Swift 5 language mode. | xcodegen + xcodebuild |
| `backend/` | FastAPI decode service: wraps `m8_decode.py` / `analyze_calibration.py`, serves `grading.json` + per-tape manifests + the Stage-A calibration WAV. | `pytest` + `uvicorn` |

The **wire contract** is the Python backend's JSON. The Swift `Codable` models in
`ios/CassetteAI/Models/TapeManifest.swift` mirror the backend response shapes
exactly (verified by round-tripping live responses through the decoders).

## Run the backend

```bash
cd app/backend
pip install -r requirements.txt          # fastapi, uvicorn, numpy, scipy, soundfile, reedsolo, torch
python3 build_registry.py                # one-time: derive registry.json from master8_manifest.json
python3 calibration/make_calibration.py  # one-time: generate the Stage-A calibration WAV (seed-logged)
python3 -m uvicorn server:app --host 0.0.0.0 --port 8765
```

Smoke-test the endpoints:

```bash
curl http://localhost:8765/api/grading
curl http://localhost:8765/api/tapes/master8/manifest
curl -o calibration.wav http://localhost:8765/api/calibration
curl -X POST -F "file=@calibration/calibration.wav" http://localhost:8765/api/setup-test
```

Use `--host 0.0.0.0` (not `127.0.0.1`) so a physical iPhone on the same Wi-Fi can
reach it; point the app's Settings → Backend URL at `http://<mac-ip>:8765`. The app
defaults to `http://localhost:8765` (fine for the simulator).

## Open / build / run the app

```bash
cd app/ios
xcodegen generate                  # writes CassetteAI.xcodeproj (gitignored — regenerate any time)
open CassetteAI.xcodeproj
```

In Xcode:
1. Select the **CassetteAI** scheme.
2. Set **Signing → Team** (the generated project has an empty `DEVELOPMENT_TEAM`;
   pick your Personal Team). Bundle id is `se.gille.cassetteai`.
3. Pick a destination and **Run** (⌘R).

> **On-device is required for real capture.** The whole project depends on the
> iPhone's sample-accurate ADC clock; the simulator has no usable mic for tape
> audio. Use the simulator only for UI work; capture/decode must run on a device.

### Microphone permission
The `Info.plist` carries `NSMicrophoneUsageDescription` ("CassetteAI listens to
your cassette deck to decode the data on the tape"). iOS prompts on first capture.

## Lab workflow (replaces Voice Memos)

The app is Magnus's clean-capture tool. Per the project capture SOP
(`CLAUDE.md`): Dolby **OFF**, record level **~7.0**, readback speaker **~55**,
**~1 s silence** around the start/end chirps.

1. In-app: tap **Record** → press **Play** on the deck → let the full master
   play to the end chirp → **Stop**. (Capture is 48 kHz mono float32 WAV,
   `.measurement` mode, voice-processing OFF, lossless — the exact artifact
   `analyze_master2.py` consumes.)
2. Either:
   - **Decode in-app** — the capture uploads to the backend (`/api/captures`),
     which runs `m8_decode.py`; the app polls `/api/jobs/{id}` and shows the boot
     moment, **or**
   - **Export the raw WAV to the Mac** (share sheet / Files) and run the Python
     stack directly:
     ```bash
     python3 experiments/tape_v2/analyze_master2.py <capture.wav>
     ```

## Current limitations

DSP / app:
- **Decode is server-side (Phase 1 hybrid).** No on-device payload decode yet;
  the app needs the backend reachable to produce a payload. On-device Robust-tier
  decode is v2 (design doc §6).
- **The `.cass` on-tape packed-int4 loader is a stub** on the backend — story
  generation falls back to the bundled weights; a true `.cass` reconstructor must
  invert `quantize.py`'s packing.
- **QR / J-card scanning is a stub** (info sheet only); live `DataScannerViewController`
  scanning is deferred.
- **Capture-clock fidelity (`.measurement` + 48 kHz AGC-free) is unverified on a
  real device** — the load-bearing assumption (design doc §10). Capture the master
  in-app and decode in Python to confirm before trusting any tier verdict.

Grading:
- **Tier thresholds in `backend/grading.json` and `CassetteDSP`
  `GradingConfig.defaults` are provisional** (from the design doc, not yet
  calibrated). Calibrate from a real corpus of good/marginal/bad captures via
  `analyze_master2.py` before putting verdicts in marketing copy. Keep the two
  threshold sources in sync.
- **Stage A (channel-only) cannot see flutter** — the UI must say a full pass is
  confirmed only on the first real tape (Stage B sounder leader).

Build environment:
- The app **compiles cleanly for the iOS Simulator SDK** (verified via direct
  `swiftc` whole-module codegen against `iphonesimulator26.5`, Swift 5 mode, zero
  errors — see the integration notes). A full `xcodebuild -scheme … -destination
  'iOS Simulator'` run is **blocked on this machine** because Xcode 26.5 ships the
  26.5 iOS SDK but only the **iOS 26.2 simulator runtime** is installed and the
  iOS 26.5 device platform is not installed, so xcodebuild's destination matcher
  finds no eligible iOS destination. Install a matching iOS 26.5 simulator runtime
  (Xcode → Settings → Components) — or build/run on a device — to get a normal
  `xcodebuild` / Run flow.
```
