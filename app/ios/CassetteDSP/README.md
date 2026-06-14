# CassetteDSP

Swift Package: DSP front-end for the Cassette-AI companion app.

**Platforms:** iOS 17+, macOS 14+ (tests run on macOS via `swift test`).  
**Dependencies:** Apple frameworks only — Accelerate/vDSP, AVFoundation, Foundation.

## Modules

| File | Public API | Purpose |
|---|---|---|
| `LevelMeter.swift` | `LevelMeter` | Streaming RMS / peak / clip-fraction over float PCM buffers. |
| `WaterfallProcessor.swift` | `WaterfallProcessor` | Streaming 1024-pt STFT; emits magnitude-dB rows normalised 0–1 for display. |
| `ChirpSync.swift` | `ChirpSync`, `ChirpResult` | Matched-filter detector for the 500→5000 Hz global sync chirp. |
| `SounderAnalyzer.swift` | `SounderAnalyzer`, `SounderMetrics` | Schroeder sounder SNR/noise-floor analysis (exact port of `analyze_master2.py`). |
| `SetupGrader.swift` | `SetupGrader`, `GradingConfig`, `GradeResult` | Pure-function tier grader (Robust / Turbo / Moonshot) driven by `grading.json`. |

## Build and test

```bash
cd app/ios/CassetteDSP
swift build
swift test
```

Tests run in under 1 second on Apple Silicon.

## Generating golden fixtures

Fixtures live in `Tests/fixtures/`. Regenerate with:

```bash
python3 Tests/fixtures/make_fixtures.py
```

Requires: `numpy scipy soundfile` (`pip install numpy scipy soundfile`).  
Produces: `chirp_fixture.wav`, `sounder_fixture.wav`, `clip_fixture.wav`, `expected.json`.  
Total fixture size: ~1 MB (well within the 5 MB limit).

## Chirp parameters (must not drift)

Matches `experiments/tape_v2/make_master2.py` exactly:
- f0 = 500 Hz, f1 = 5000 Hz, duration = 0.20 s, sample rate = 48 000 Hz
- Method: linear frequency sweep (`scipy.signal.chirp` equivalent)
- Amplitude: 0.70 (with 10 ms fade in/out — not replicated in the reference template, which is pure sine for matched-filter correlation)

## Test tolerances

| Test | Metric | Tolerance |
|---|---|---|
| ChirpSync | offset | ±64 samples |
| SounderAnalyzer | snr_db_median, snr_db_p10 | ±2 dB |
| SounderAnalyzer | noise_floor_dbfs | ±2 dB |
| LevelMeter | clip_fraction | ±10% relative |
