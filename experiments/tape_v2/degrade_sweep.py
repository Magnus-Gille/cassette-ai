#!/usr/bin/env python3
"""degrade_sweep.py — synthetic channel-degradation sweep against the DIAG-1 tape.

Starting from the CLEAN diag_master.wav (ground truth: byte-exact sidecars,
perfect sync — no burn-time-stall, no deck wear), apply real-world tape-channel
impairments at increasing severity, one axis at a time and then combined, and
re-run the diag decode ladder (mfsk32 / c1_gray_m16 / c4_bpsk / c4_qpsk) at
each step. Reports the per-axis, per-rung failure threshold in the SAME units
the report card (analyze_diag.py) measures on a real capture — so a real
capture's numbers can be directly compared against this map.

Axes modeled (each independently, then combined on one severity knob):
  - noise      broadband AWGN -> target SNR (dB)
  - hum        50 Hz + harmonics ground-loop injection -> measured hum dB
  - lowpass    tape-head / azimuth HF rolloff -> lowpass cutoff (Hz)
  - flutter    wow/flutter time-base jitter -> measured WRMS %
  - clockoff   constant deck-speed error (uniform, NOT the burn-stall) -> %
  - clip       record-level overdrive / saturation -> measured THD %

Usage:
    python3 degrade_sweep.py [--out results/degrade_sweep.json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy import signal as sig

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
TAPE_V2 = ROOT / "experiments" / "tape_v2"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", TAPE_V2):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_diag as ad  # noqa: E402

MASTER_WAV = TAPE_V2 / "diag_master.wav"
MANIFEST = TAPE_V2 / "diag_manifest.json"
CONFIGS = ["mfsk32", "c1_gray_m16", "c4_bpsk", "c4_qpsk"]


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


# ─── Degradation primitives ────────────────────────────────────────────────

def add_noise(y: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    if snr_db is None or snr_db >= 90:
        return y
    g = _rng(1000 + seed)
    sig_rms = float(np.sqrt(np.mean(y ** 2)) + 1e-12)
    noise_rms = sig_rms / (10 ** (snr_db / 20.0))
    return y + g.normal(0.0, noise_rms, size=len(y)).astype(y.dtype)


def add_hum(y: np.ndarray, sr: int, amp: float,
            freqs=(50, 100, 150, 200), decay: float = 0.55) -> np.ndarray:
    if amp <= 0:
        return y
    t = np.arange(len(y)) / sr
    hum = np.zeros_like(y)
    a = amp
    for f in freqs:
        hum += a * np.sin(2 * np.pi * f * t).astype(y.dtype)
        a *= decay
    return y + hum


def lowpass(y: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    if cutoff_hz is None or cutoff_hz >= sr / 2 - 100:
        return y
    sos = sig.butter(5, cutoff_hz, btype="lowpass", fs=sr, output="sos")
    return sig.sosfiltfilt(sos, y).astype(y.dtype)


def add_flutter(y: np.ndarray, sr: int, wrms_pct: float, seed: int = 0) -> np.ndarray:
    if wrms_pct is None or wrms_pct <= 0:
        return y
    g = _rng(2000 + seed)
    t = np.arange(len(y)) / sr
    p1, p2 = g.uniform(0, 2 * np.pi, size=2)
    inst = (1.0 * np.sin(2 * np.pi * 0.55 * t + p1)
            + 0.45 * np.sin(2 * np.pi * 4.8 * t + p2)
            + 0.18 * g.standard_normal(len(t)))
    inst = inst / (np.sqrt(np.mean(inst ** 2)) + 1e-12) * (wrms_pct / 100.0)
    warped_t = np.clip(t + np.cumsum(inst) / sr, 0, t[-1])
    return np.interp(t, warped_t, y).astype(y.dtype)


def clock_offset(y: np.ndarray, sr: int, pct: float) -> np.ndarray:
    if not pct:
        return y
    factor = 1.0 + pct / 100.0
    new_len = max(1, int(round(len(y) / factor)))
    return sig.resample(y, new_len).astype(y.dtype)


def clip(y: np.ndarray, drive_db: float) -> np.ndarray:
    if not drive_db:
        return y
    gain = 10 ** (drive_db / 20.0)
    peak = float(np.max(np.abs(y)) + 1e-12)
    norm = np.tanh(gain * peak) / peak
    return (np.tanh(gain * y) / norm).astype(y.dtype)


# ─── Decode + measure ───────────────────────────────────────────────────────

def decode_rates(mono: np.ndarray, manifest: dict) -> dict:
    res = ad._decode_diag_sections(mono.astype(np.float32), manifest, 48_000)
    if not res:
        return {c: 0.0 for c in CONFIGS}
    return {c: res.get(c, {}).get("passrate", 0.0) for c in CONFIGS}


def measure(mono: np.ndarray, sr: int, manifest: dict) -> dict:
    """Measure the SAME quantities analyze_diag's report card prints, so a
    real capture's numbers can be compared 1:1 against this sweep."""
    hum = ad.check_mains_hum(mono, sr)
    freq = ad.check_frequency_response(mono, sr, diag_tape_mode=True)
    clk = ad.check_clock_flutter(mono, sr, manifest)
    dist = ad.check_distortion(mono, sr, manifest=manifest)
    return {
        "hum_worst_db": hum["worst_hum_db"],
        "hf_rolloff_db": freq.get("hf_rolloff_db"),
        "median_carrier_snr_db": freq.get("median_snr_db"),
        "flutter_wrms_pct": clk.get("flutter_wrms_pct"),
        "speed_offset_pct": clk.get("speed_offset_pct"),
        "thd_pct": dist.get("thd_pct"),
        "imd_dbr": dist.get("imd_dbr"),
    }


def run_axis(name: str, base: np.ndarray, sr: int, manifest: dict,
             knob_values: list, apply_fn) -> list:
    print(f"\n=== axis: {name} ===", flush=True)
    rows = []
    for kv in knob_values:
        y = apply_fn(base.copy(), kv)
        rates = decode_rates(y, manifest)
        m = measure(y, sr, manifest)
        row = {"knob": kv, "rates": rates, "measured": m}
        rows.append(row)
        rr = " ".join(f"{c}:{rates[c]*100:.0f}%" for c in CONFIGS)
        print(f"  knob={kv!r:>8}  {rr}  "
              f"hum={m['hum_worst_db']}dB hf={m['hf_rolloff_db']}dB "
              f"flutter={m['flutter_wrms_pct']}% thd={m['thd_pct']}%", flush=True)
        if all(rates[c] == 0.0 for c in CONFIGS):
            print(f"  -> ALL RUNGS DEAD at knob={kv!r}, stopping axis sweep", flush=True)
            break
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(TAPE_V2 / "results" / "degrade_sweep.json"))
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    audio, sr = sf.read(str(MASTER_WAV), dtype="float32", always_2d=True)
    assert sr == 48_000
    base = audio[:, 0].copy()  # L == R content-identical on diag_master

    # Sanity: clean baseline should be 100% on all rungs.
    clean_rates = decode_rates(base, manifest)
    print(f"[degrade_sweep] clean baseline: {clean_rates}")
    assert all(v == 1.0 for v in clean_rates.values()), (
        f"clean diag_master.wav did not decode 100%% — aborting: {clean_rates}")

    report: dict = {"clean_baseline": clean_rates, "axes": {}}

    report["axes"]["noise"] = run_axis(
        "noise (AWGN, target SNR dB)", base, sr, manifest,
        [40, 30, 25, 20, 17, 15, 13, 11, 9, 7, 5, 3],
        lambda y, kv: add_noise(y, kv))

    report["axes"]["hum"] = run_axis(
        "hum (50Hz+harmonics amplitude)", base, sr, manifest,
        [0.0, 0.001, 0.003, 0.006, 0.01, 0.02, 0.035, 0.06, 0.1, 0.16, 0.25],
        lambda y, kv: add_hum(y, sr, kv))

    report["axes"]["lowpass"] = run_axis(
        "lowpass (HF cutoff Hz)", base, sr, manifest,
        [16000, 12000, 10000, 8000, 7000, 6000, 5000, 4200, 3500, 3000, 2500],
        lambda y, kv: lowpass(y, sr, kv))

    report["axes"]["flutter"] = run_axis(
        "flutter (WRMS %)", base, sr, manifest,
        [0.1, 0.3, 0.5, 0.8, 1.2, 1.8, 2.5, 3.5, 5.0, 7.0, 10.0],
        lambda y, kv: add_flutter(y, sr, kv))

    report["axes"]["clockoff"] = run_axis(
        "clockoff (constant speed error %)", base, sr, manifest,
        [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 18.0, 25.0],
        lambda y, kv: clock_offset(y, sr, kv))

    report["axes"]["clip"] = run_axis(
        "clip (overdrive dB)", base, sr, manifest,
        [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 14.0, 20.0],
        lambda y, kv: clip(y, kv))

    # Combined realistic sweep: ramp all axes together on one severity knob t in [0,1]
    print("\n=== axis: combined (all faults together, knob t in [0,1]) ===", flush=True)
    combined_rows = []
    for t in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        y = base.copy()
        y = clip(y, 0.0 + t * 10.0)
        y = lowpass(y, sr, 16000 - t * 12500)
        y = add_flutter(y, sr, 0.1 + t * 4.5)
        y = add_hum(y, sr, 0.0 + t * 0.12)
        y = add_noise(y, 45 - t * 35)
        rates = decode_rates(y, manifest)
        m = measure(y, sr, manifest)
        row = {"knob": t, "rates": rates, "measured": m}
        combined_rows.append(row)
        rr = " ".join(f"{c}:{rates[c]*100:.0f}%" for c in CONFIGS)
        print(f"  t={t:.1f}  {rr}  "
              f"hum={m['hum_worst_db']}dB hf={m['hf_rolloff_db']}dB "
              f"flutter={m['flutter_wrms_pct']}% thd={m['thd_pct']}%", flush=True)
        if all(rates[c] == 0.0 for c in CONFIGS):
            print(f"  -> ALL RUNGS DEAD at t={t:.1f}, stopping combined sweep", flush=True)
            break
    report["axes"]["combined"] = combined_rows

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\n[degrade_sweep] wrote {out_path}")


if __name__ == "__main__":
    main()
