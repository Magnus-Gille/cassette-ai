"""server.py — Cassette-AI decode backend (FastAPI, Python 3.10+).

Endpoints
---------
POST /api/captures          multipart WAV upload -> {job_id}
GET  /api/jobs/{job_id}     job status + result
GET  /api/tapes/{tape_id}/manifest  tape registry entry
GET  /api/grading           versioned tier-threshold doc
POST /api/setup-test        calibration WAV -> channel metrics + tier verdicts

Run
---
    uvicorn server:app --port 8765
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent          # cassette-ai/
TAPE_V2 = REPO_ROOT / "experiments" / "tape_v2"
RESULTS_DIR = TAPE_V2 / "results"
MANIFEST_PATH = TAPE_V2 / "master8_manifest.json"
REGISTRY_PATH = HERE / "registry.json"
GRADING_PATH = HERE / "grading.json"
CALIBRATION_DIR = HERE / "calibration"
UPLOADS_DIR = HERE / "_uploads"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory job store  {job_id: {status, stage, progress, result?, error?}}
# ---------------------------------------------------------------------------
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Stage markers we recognise in m8_decode.py stdout
# ---------------------------------------------------------------------------
# m8_decode prints lines like:  "[m8_decode] …"  and  sounder/sync lines.
# We map partial stdout content to (stage, progress).
_STAGE_MAP = [
    ("saving",   0.00),
    ("sync",     0.10),
    ("channel",  0.25),
    ("demod",    0.45),
    ("fec",      0.65),
    ("unpack",   0.80),
    ("done",     1.00),
]


def _progress_from_stdout(lines: list[str]) -> tuple[str, float]:
    """Heuristic: scan stdout lines and advance through stages."""
    stage, progress = "saving", 0.0
    for line in lines:
        l = line.lower()
        if "global sync" in l or "chirp" in l or "recovered clock" in l:
            stage, progress = "sync", 0.10
        elif "sounder" in l or "snr" in l or "flutter" in l:
            stage, progress = "channel", 0.25
        elif "demod" in l or "payload" in l or "phy" in l:
            stage, progress = "demod", 0.45
        elif "rs_codeword" in l or "byte_exact" in l or "fec" in l:
            stage, progress = "fec", 0.65
        elif "unpack" in l or "wrote" in l:
            stage, progress = "unpack", 0.80
    return stage, progress


# ---------------------------------------------------------------------------
# Background decode worker
# ---------------------------------------------------------------------------
def _run_decode(job_id: str, wav_path: pathlib.Path) -> None:
    """Subprocess m8_decode.py, parse its JSON result, update job store."""
    tag = f"job_{job_id}"
    result_file = RESULTS_DIR / f"m8_results_{tag}.json"

    # Patch the sys.path additions m8_decode needs
    cmd = [
        sys.executable, str(TAPE_V2 / "m8_decode.py"),
        str(wav_path), "--out-tag", tag,
    ]

    stdout_lines: list[str] = []
    stage, progress = "sync", 0.10

    with _jobs_lock:
        _jobs[job_id]["stage"] = "sync"
        _jobs[job_id]["progress"] = 0.10

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(REPO_ROOT),
        )
        for line in proc.stdout:
            stdout_lines.append(line)
            stage, progress = _progress_from_stdout(stdout_lines)
            with _jobs_lock:
                _jobs[job_id]["stage"] = stage
                _jobs[job_id]["progress"] = progress

        proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(
                f"m8_decode exited {proc.returncode}:\n" + "".join(stdout_lines[-20:])
            )

        if not result_file.exists():
            raise FileNotFoundError(f"Expected result file not found: {result_file}")

        raw = json.loads(result_file.read_text())
        result = _shape_result(raw)

        with _jobs_lock:
            _jobs[job_id].update({
                "status": "done",
                "stage": "done",
                "progress": 1.0,
                "result": result,
                "log": "".join(stdout_lines[-200:]),
            })

    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id].update({
                "status": "error",
                "stage": "error",
                "progress": 0.0,
                "error": str(exc),
                "log": "".join(stdout_lines[-200:]),
            })
    finally:
        # Clean up the uploaded WAV (large)
        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass


def _shape_result(raw: dict) -> dict:
    """Map m8_decode JSON -> clean API result."""
    sounder = raw.get("sounder") or {}
    sync = raw.get("sync") or {}
    payloads = raw.get("payloads") or []

    channel_metrics = {
        "snr_db_median": sounder.get("snr_db_median"),
        "snr_db_p10": sounder.get("snr_db_p10"),
        "noise_floor_dbfs": sounder.get("noise_floor_dbfs"),
        "flutter_wrms_pct": sounder.get("flutter_wrms_pct"),
        "frac_below_8db": sounder.get("frac_below_8db"),
        "clock_ratio": sync.get("clock_ratio"),
        "speed_offset_pct": (sync.get("speed_offset") or 0.0) * 100.0,
    }

    per_rung = []
    best_bps = 0.0
    for p in payloads:
        net_bps = p.get("projected_net_bps") or 0.0
        byte_exact = bool(p.get("byte_exact_best") or p.get("byte_exact"))
        cw_failed = p.get("rs_codewords_failed") or 0
        per_rung.append({
            "name": p.get("name", ""),
            "phy": p.get("phy", p.get("scheme", "")),
            "net_bps": net_bps,
            "effective_bps": p.get("effective_bps"),
            "byte_exact": byte_exact,
            "cw_failed": cw_failed,
            "n_codewords": p.get("n_codewords"),
            "orig_byte_exact": bool(p.get("orig_byte_exact")),
            "combo": bool(p.get("combo")),
        })
        if byte_exact:
            best_bps = max(best_bps, net_bps)

    # payload_preview: first 120 chars of the decoded sidecar from the best passing rung
    payload_preview = None
    for p in sorted(payloads, key=lambda x: x.get("projected_net_bps") or 0, reverse=True):
        if p.get("byte_exact_best") or p.get("byte_exact"):
            sidecar_rel = p.get("payload_orig_sidecar") or p.get("payload_sidecar")
            if sidecar_rel:
                sidecar = TAPE_V2 / sidecar_rel
                if sidecar.exists():
                    try:
                        raw_bytes = sidecar.read_bytes()
                        payload_preview = raw_bytes[:120].decode("utf-8", errors="replace")
                    except Exception:
                        pass
            break

    return {
        "tape": raw.get("tape", "master8"),
        "channel": channel_metrics,
        "rungs": per_rung,
        "best_rate_bps": best_bps,
        "n_byte_exact": raw.get("n_byte_exact_packed", 0),
        "n_orig_exact": raw.get("n_orig_exact", 0),
        "n_payloads": raw.get("n_payloads", 0),
        "payload_preview": payload_preview,
    }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Cassette-AI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/captures")
async def post_capture(file: UploadFile = File(...)) -> dict:
    """Accept a WAV upload (up to ~600 MB), start async decode, return job_id."""
    job_id = str(uuid.uuid4())
    wav_path = UPLOADS_DIR / f"{job_id}.wav"

    # Stream to disk
    with open(wav_path, "wb") as f:
        chunk_size = 1024 * 1024  # 1 MB
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "stage": "saving",
            "progress": 0.0,
        }

    t = threading.Thread(target=_run_decode, args=(job_id, wav_path), daemon=True)
    t.start()

    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    """Poll job status; result is present when status=done."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "stage": job.get("stage", ""),
        "progress": job.get("progress", 0.0),
        "result": job.get("result"),
        "error": job.get("error"),
    }


@app.get("/api/tapes/{tape_id}/manifest")
async def get_tape_manifest(tape_id: str) -> dict:
    """Return distilled tape manifest from the registry."""
    if not REGISTRY_PATH.exists():
        raise HTTPException(status_code=503, detail="Registry not built; run build_registry.py")
    registry = json.loads(REGISTRY_PATH.read_text())
    entry = registry.get(tape_id)
    if entry is None:
        known = list(registry.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Tape '{tape_id}' not found. Known tapes: {known}",
        )
    return entry


@app.get("/api/grading")
async def get_grading() -> dict:
    """Return versioned tier-threshold grading.json."""
    if not GRADING_PATH.exists():
        raise HTTPException(status_code=503, detail="grading.json not found")
    return json.loads(GRADING_PATH.read_text())


@app.get("/api/calibration")
async def get_calibration():
    """Serve the bundled Stage-A calibration WAV (lossless, no streaming codec).

    The iOS app plays this through the user's speaker while listening, to grade
    the speaker+room+mic path before any real tape is read (design doc §3.3/§7).
    """
    wav = CALIBRATION_DIR / "calibration.wav"
    if not wav.exists():
        raise HTTPException(
            status_code=503,
            detail="calibration.wav not found; run calibration/make_calibration.py",
        )
    return FileResponse(
        path=str(wav),
        media_type="audio/wav",
        filename="calibration.wav",
    )


@app.post("/api/setup-test")
async def post_setup_test(file: UploadFile = File(...)) -> dict:
    """Accept a calibration WAV, measure channel metrics, grade against tiers."""
    # Write to a temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = pathlib.Path(tmp.name)
        chunk_size = 1024 * 1024
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            tmp.write(chunk)

    try:
        result = _run_calibration(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return result


def _run_calibration(wav_path: pathlib.Path) -> dict:
    """Run analyze_calibration.py on the uploaded WAV and grade against grading.json."""
    # Import calibration analyser from this package
    analyze_cal = CALIBRATION_DIR / "analyze_calibration.py"
    if not analyze_cal.exists():
        raise HTTPException(status_code=503, detail="analyze_calibration.py not found")

    cmd = [sys.executable, str(analyze_cal), str(wav_path)]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Calibration analysis failed:\n{result.stderr[-500:]}"
        )

    try:
        metrics = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not parse calibration output: {exc}\nstdout={result.stdout[:200]}"
        )

    # Grade against grading.json
    if not GRADING_PATH.exists():
        raise HTTPException(status_code=503, detail="grading.json not found")
    grading = json.loads(GRADING_PATH.read_text())

    verdicts = _compute_verdicts(metrics, grading)
    return {
        "metrics": metrics,
        "verdicts": verdicts,
    }


def _compute_verdicts(metrics: dict, grading: dict) -> list[dict]:
    """Compute per-tier YES/MARGINAL/NO + single most actionable advice."""
    tiers = grading.get("tiers", [])
    verdicts = []
    for tier in tiers:
        reqs = tier.get("requirements", {})
        issues = []
        margin_issues = []

        snr_med = metrics.get("snr_db_median")
        snr_p10 = metrics.get("snr_db_p10")
        noise_nf = metrics.get("noise_floor_dbfs")
        flutter = metrics.get("flutter_wrms_pct")
        frac_below = metrics.get("frac_below_8db")

        snr_min = reqs.get("snr_db_median_min")
        if snr_min is not None and snr_med is not None:
            if snr_med < snr_min:
                issues.append(tier.get("advice_low_snr", "move phone closer to speaker"))
            elif snr_med < snr_min + 3:
                margin_issues.append(tier.get("advice_low_snr", "move phone closer to speaker"))

        snrp10_min = reqs.get("snr_db_p10_min")
        if snrp10_min is not None and snr_p10 is not None:
            if snr_p10 < snrp10_min:
                issues.append(tier.get("advice_low_snr_p10", "reduce room reflections"))
            elif snr_p10 < snrp10_min + 3:
                margin_issues.append(tier.get("advice_low_snr_p10", "reduce room reflections"))

        flutter_max = reqs.get("flutter_wrms_pct_max")
        if flutter_max is not None and flutter is not None:
            if flutter > flutter_max:
                issues.append(tier.get("advice_flutter", "service or replace tape deck"))
            elif flutter > flutter_max * 0.85:
                margin_issues.append(tier.get("advice_flutter", "service or replace tape deck"))

        nf_max = reqs.get("noise_floor_dbfs_max")
        if nf_max is not None and noise_nf is not None:
            if noise_nf > nf_max:
                issues.append(tier.get("advice_noise", "find a quieter room"))
            elif noise_nf > nf_max - 3:
                margin_issues.append(tier.get("advice_noise", "find a quieter room"))

        lossless_req = reqs.get("lossless_required", False)
        lossless = metrics.get("lossless", True)  # setup-test calibration is always lossless
        if lossless_req and not lossless:
            issues.append("switch to lossless capture (WAV, not AAC)")

        if not issues and not margin_issues:
            verdict = "YES"
            advice = tier.get("advice_pass", "Setup looks good for this tier!")
        elif issues:
            verdict = "NO"
            advice = issues[0]
        else:
            verdict = "MARGINAL"
            advice = margin_issues[0]

        verdicts.append({
            "tier_id": tier["id"],
            "tier_name": tier["name"],
            "verdict": verdict,
            "advice": advice,
        })

    return verdicts
