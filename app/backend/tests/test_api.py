"""test_api.py — pytest test suite for the Cassette-AI backend.

Tests:
  1. Upload a tiny synthetic WAV -> job lifecycle reaches done or error (no crash).
  2. GET /api/grading validates against schema.
  3. POST /api/setup-test with the calibration.wav -> top-tier verdicts.
  4. GET /api/tapes/master8/manifest -> returns expected fields.

Run:
    cd app/backend && pytest tests/test_api.py -v
"""
from __future__ import annotations

import io
import json
import pathlib
import struct
import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

# The tests import server from the backend directory
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import server   # noqa: E402

client = TestClient(server.app)

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parent
CAL_WAV = BACKEND / "calibration" / "calibration.wav"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_synthetic_wav(duration_s: float = 2.0, sr: int = 48_000) -> bytes:
    """Create a minimal valid 48 kHz mono float32 WAV (sine burst) in memory."""
    t = np.arange(int(duration_s * sr)) / sr
    # A short chirp-like sweep so the sync code has something to latch onto
    f = np.linspace(500, 5000, len(t))
    sig = (0.5 * np.sin(2 * np.pi * f * t)).astype(np.float32)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)           # 16-bit (WAV doesn't support float32 natively here)
        w.setframerate(sr)
        # Convert float32 -> int16 for standard WAV compatibility
        pcm = (sig * 32767).clip(-32768, 32767).astype(np.int16)
        w.writeframes(pcm.tobytes())
    buf.seek(0)
    return buf.read()


def _wait_for_job(job_id: str, timeout: float = 60.0, poll: float = 0.5) -> dict:
    """Poll GET /api/jobs/{job_id} until status is done or error."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, r.text
        data = r.json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(poll)
    # If we timed out, return whatever state we have
    r = client.get(f"/api/jobs/{job_id}")
    return r.json()


# ---------------------------------------------------------------------------
# Test 1: job lifecycle
# ---------------------------------------------------------------------------

def test_capture_job_lifecycle():
    """Upload a tiny synthetic WAV; job must reach done/error without crashing."""
    wav_bytes = _make_synthetic_wav(2.0)

    response = client.post(
        "/api/captures",
        files={"file": ("test.wav", wav_bytes, "audio/wav")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "job_id" in body
    job_id = body["job_id"]

    job = _wait_for_job(job_id, timeout=90.0)
    # The decode will likely error (synthetic 2s WAV has no real tape content)
    # but the server must not crash — status must be done or error, not stuck.
    assert job["status"] in ("done", "error"), f"Unexpected status: {job}"
    assert "stage" in job
    assert "progress" in job


def test_job_not_found():
    """Unknown job ID returns 404."""
    r = client.get("/api/jobs/nonexistent-job-id-12345")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Test 2: /api/grading schema validation
# ---------------------------------------------------------------------------

def test_grading_schema():
    """GET /api/grading returns a valid grading document."""
    r = client.get("/api/grading")
    assert r.status_code == 200, r.text
    data = r.json()

    # Top-level keys
    assert "version" in data, "grading.json must have 'version'"
    assert "tiers" in data, "grading.json must have 'tiers'"
    assert isinstance(data["tiers"], list)
    assert len(data["tiers"]) >= 1

    for tier in data["tiers"]:
        assert "id" in tier
        assert "name" in tier
        assert "requirements" in tier
        reqs = tier["requirements"]
        # Required fields
        assert "snr_db_median_min" in reqs
        assert "flutter_wrms_pct_max" in reqs
        assert "noise_floor_dbfs_max" in reqs
        assert "lossless_required" in reqs
        # Types
        assert isinstance(reqs["snr_db_median_min"], (int, float))
        assert isinstance(reqs["flutter_wrms_pct_max"], (int, float))
        assert isinstance(reqs["lossless_required"], bool)


# ---------------------------------------------------------------------------
# Test 3: /api/setup-test with calibration.wav
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not CAL_WAV.exists(),
    reason="calibration.wav not found — run make_calibration.py first",
)
def test_setup_test_calibration_wav():
    """Upload calibration.wav; expect top-tier (Robust) verdict = YES."""
    with open(CAL_WAV, "rb") as f:
        wav_bytes = f.read()

    response = client.post(
        "/api/setup-test",
        files={"file": ("calibration.wav", wav_bytes, "audio/wav")},
        timeout=120.0,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert "metrics" in body
    assert "verdicts" in body

    metrics = body["metrics"]
    # The calibration WAV is a clean synthetic signal — expect high SNR
    if metrics.get("snr_db_median") is not None:
        # Synthetic signal through no channel should have excellent SNR
        assert metrics["snr_db_median"] > 20.0, (
            f"Expected high SNR for synthetic calibration WAV, got {metrics['snr_db_median']}"
        )

    verdicts = body["verdicts"]
    assert isinstance(verdicts, list)
    assert len(verdicts) >= 1

    # Find the robust verdict
    robust = next((v for v in verdicts if v.get("tier_id") == "robust"), None)
    assert robust is not None, "No 'robust' tier verdict"
    # The calibration WAV (loopback, no real acoustic channel) should pass Robust
    assert robust["verdict"] in ("YES", "MARGINAL"), (
        f"Expected YES/MARGINAL for Robust tier with calibration WAV, got: {robust}"
    )


# ---------------------------------------------------------------------------
# Test 4: tape manifest
# ---------------------------------------------------------------------------

def test_tape_manifest():
    """GET /api/tapes/master8/manifest returns expected structure."""
    r = client.get("/api/tapes/master8/manifest")
    if r.status_code == 503:
        pytest.skip("Registry not built (run build_registry.py)")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tape_id"] == "master8"
    assert "rungs" in data
    assert len(data["rungs"]) > 0
    rung = data["rungs"][0]
    assert "name" in rung
    assert "projected_net_bps" in rung


def test_tape_manifest_not_found():
    """Unknown tape ID returns 404."""
    r = client.get("/api/tapes/nonexistent_tape_xyz")
    if r.status_code == 503:
        pytest.skip("Registry not built")
    assert r.status_code == 404
