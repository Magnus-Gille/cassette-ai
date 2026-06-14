# Cassette-AI Backend

FastAPI decode service for the Cassette-AI companion app.

## Requirements

Python 3.10+, all in `requirements.txt`:

```
pip install -r requirements.txt
```

The backend calls into the existing Python research stack (`experiments/tape_v2/m8_decode.py`,
`analyze_master2.py`) — no modifications to those files.

## First-time setup

```bash
# 1. Generate the calibration WAV (run once)
python3 app/backend/calibration/make_calibration.py

# 2. Build the tape registry (run once, and again when master8_manifest.json changes)
python3 app/backend/build_registry.py
```

## Run the server

```bash
uvicorn server:app --port 8765 --app-dir app/backend
```

Or from the backend directory:

```bash
cd app/backend
uvicorn server:app --port 8765
```

API available at: `http://localhost:8765`

Interactive docs: `http://localhost:8765/docs`

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/captures` | Upload a WAV; returns `{job_id}`. Decode runs async. |
| `GET` | `/api/jobs/{job_id}` | Poll job status. Stages: saving → sync → channel → demod → fec → unpack → done. |
| `GET` | `/api/tapes/{tape_id}/manifest` | Distilled tape manifest (rungs, rates, sha256). |
| `GET` | `/api/grading` | Versioned tier-threshold document. |
| `POST` | `/api/setup-test` | Upload a calibration WAV; returns channel metrics + tier verdicts. |

## Tier grading

`grading.json` holds the tier thresholds. Edit it to tune thresholds without
changing server code. The version field is returned in the API response.

Tiers:
- **Robust** (560–930 bps): survives mediocre setups and AAC re-encode.
- **Turbo** (1.5–2.5 kbps): decent setup + lossless capture.
- **Moonshot** (4–5 kbps): quiet room, phone close, lossless, low flutter.

## Tests

```bash
cd app/backend
pytest tests/test_api.py -v
```

## Story generation

`story.py` wraps the on-tape LLM (stories260K, 260k-param TinyStories model,
int4-quantized to ~150 KB). Used for the "boot moment" payload display.

```python
from story import generate_story
text = generate_story(seed=42, n_tokens=200, temp=0.8)
```

## Directory layout

```
app/backend/
  server.py                 Main FastAPI app
  grading.json              Versioned tier thresholds
  registry.json             Built tape registry (git-ignored)
  build_registry.py         Script to build registry.json
  story.py                  LLM story generator (boot-moment payload)
  requirements.txt
  README.md
  calibration/
    make_calibration.py     Generate calibration.wav + calibration_meta.json
    calibration.wav         25s synthetic sounder (git-tracked, ~5 MB)
    calibration_meta.json   Exact layout offsets
    analyze_calibration.py  Channel analysis for setup-test endpoint
  tests/
    test_api.py             pytest test suite
  _uploads/                 Transient WAV uploads (gitignored)
```
