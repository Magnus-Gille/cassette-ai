"""x9_flutter_inject.py — BUILD + SELF-VALIDATE the HF-flutter injection that the
R6 master9 gate (R6_sim_fidelity.md §4.2) requires but did not yet implement.

The frozen sim's flutter is two pure sinusoids (0.55 Hz wow, 4.8 Hz flutter) +
18% white, rms-normalized.  Measured (x9_sim_probes.json): the sim has ~100-200x
too little timing-jitter energy ABOVE 5 Hz vs the real m8 tape.  That blind spot
let h8 rate every N1024 DQPSK rung as "strict PASS" — all of which then died on
the real tape (35-37/37 RS codewords failed), while the N512 rung the sim rated
equally was the one that actually won (934 bps, 0 cw failed).

This script adds a BROADBAND timing-jitter trajectory tau_hf(t) (filtered white
noise, flat-ish PSD to a corner) on top of sim_v2.channel_v2 by resampling the
channel output, then runs the ACTUAL h4 DQPSK decoder (pilot tracker + RS) over
N512 and N1024 rungs at several injection levels.

THE GATE-VALIDATING QUESTION (pre-registered, must answer YES to trust the gate):
  At an injection level whose 5-200 Hz residual band-RMS matches the measured real
  residual (~35 us, x9_sim_probes Table A), does
      N1024 DQPSK FAIL  AND  N512 DQPSK PASS  (byte-exact),
  reproducing the real m8 tape outcome that the un-augmented sim got backwards?
If YES, the injection is a faithful proxy for the missing impairment and the
master9 HF-flutter gate cell is trustworthy.  If NO, the gate must not rely on it.

Reads only.  Writes results/x9_flutter_inject.json.  Seeds set + logged.
NOTE: resampling-based injection keeps the FROZEN channel untouched (no edits).
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from scipy import signal

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                       # noqa: E402
from m3_codec import Rung                      # noqa: E402
import sim_v2                                  # noqa: E402
import x9_sim_probes as xp                     # noqa: E402
from h4_dqpsk import (                         # noqa: E402
    DQPSKScheme, build_section, nominal_frame_bits, _payload_slice,
    PAD_LO_S, PAD_HI_S, FS,
)

RESULTS = _HERE / "results"
OUT = RESULTS / "x9_flutter_inject.json"

# Measured real residual band-RMS that the injection is calibrated to reproduce.
# x9_sim_probes.json -> real -> jitter_rms_s_by_band, 5-200 Hz sum:
#   5-23.4 Hz 33.9 us + 23.4-46.9 Hz 11.1 us + 46.9-200 Hz 8.9 us (RSS ~37 us).
REAL_HF_BAND_RMS_S = 37.0e-6          # 5-200 Hz RSS, real m8 pilot
HF_CORNER_HZ = 60.0                   # broadband jitter flat to ~60 Hz then rolls off


# ---------------------------------------------------------------------------
# HF-flutter injection: a broadband timing-jitter resample on top of channel_v2
# ---------------------------------------------------------------------------
def make_hf_jitter(n: int, band_rms_s: float, *, seed: int,
                   corner_hz: float = HF_CORNER_HZ, fs: int = FS) -> np.ndarray:
    """Broadband timing-jitter trajectory tau_hf(t) [seconds], length n.

    White noise band-limited to [~3 Hz, corner_hz] (above the wow band the sim
    already models, up to a cassette-plausible flutter ceiling), scaled so its
    RMS over the band equals band_rms_s.  The HIGH-PASS at 3 Hz avoids
    double-counting the 0.55/4.8 Hz components the frozen warp already has.
    """
    if band_rms_s <= 0:
        return np.zeros(n)
    rg = np.random.default_rng(40_000 + seed)
    w = rg.standard_normal(n)
    sos = signal.butter(4, [3.0, corner_hz], btype="band", fs=fs, output="sos")
    tau = signal.sosfiltfilt(sos, w)
    tau = tau / (np.sqrt(np.mean(tau ** 2)) + 1e-18) * band_rms_s
    return tau


def inject_hf_flutter(y: np.ndarray, band_rms_s: float, *, seed: int,
                      fs: int = FS) -> np.ndarray:
    """Resample y onto a time axis perturbed by tau_hf(t): y'(t) = y(t - tau_hf).
    This imposes a frequency-proportional phase error 2*pi*f*tau on every tone,
    exactly the impairment class real flutter produces — but with the broadband
    HF spectrum the frozen 2-sinusoid warp lacks."""
    if band_rms_s <= 0:
        return y
    n = len(y)
    tau = make_hf_jitter(n, band_rms_s, seed=seed, fs=fs)
    t = np.arange(n) / fs
    warped = t - tau
    warped = np.clip(warped, 0.0, t[-1])
    return np.interp(t, warped, y)


def channel_with_hf(section: np.ndarray, *, seed: int, band_rms_s: float,
                    aac: bool = False) -> np.ndarray:
    """sim_v2 channel (aac off by default, lossless era), THEN broadband HF jitter."""
    y = sim_v2.channel_v2(section, profile="tape7", aac=aac, seed_offset=seed)
    y = inject_hf_flutter(np.asarray(y, np.float64), band_rms_s, seed=seed)
    return y.astype(np.float64)


# ---------------------------------------------------------------------------
# Step 1: verify the injection lands the intended residual on the pilot tone
# ---------------------------------------------------------------------------
def verify_injection_residual(levels, seeds=(0, 1, 2), dur_s=16.0):
    """Push a pure 4500 Hz pilot tone through channel_with_hf at each level,
    re-measure the tracker residual the way x9_sim_probes does, and confirm the
    1.0x level reproduces ~the real residual (N512 ~31 us, N1024 ~54 us)."""
    tone = xp.make_tone(xp.PILOT_HZ, dur_s)
    rows = []
    for lvl in levels:
        brms = lvl * REAL_HF_BAND_RMS_S
        r512, r1024, b5_23, b23_47, b47_200 = [], [], [], [], []
        for s in seeds:
            y = channel_with_hf(tone, seed=s, band_rms_s=brms, aac=False)
            y = y[: len(tone)]
            tau = xp.instantaneous_timing_jitter(y, xp.PILOT_HZ)
            f, P = xp.jitter_psd(tau)
            b5_23.append(xp.band_jitter_rms(f, P, 5.0, 23.4))
            b23_47.append(xp.band_jitter_rms(f, P, 23.4, 46.9))
            b47_200.append(xp.band_jitter_rms(f, P, 46.9, 200.0))
            r512.append(xp.pilot_tracker_residual(tau, 512)["resid_rms_ns"])
            r1024.append(xp.pilot_tracker_residual(tau, 1024)["resid_rms_ns"])
        rows.append({
            "level": lvl, "band_rms_target_us": round(brms * 1e6, 2),
            "band5_23_us": round(float(np.mean(b5_23)) * 1e6, 2),
            "band23_47_us": round(float(np.mean(b23_47)) * 1e6, 2),
            "band47_200_us": round(float(np.mean(b47_200)) * 1e6, 2),
            "resid_N512_ns": round(float(np.mean(r512)), 1),
            "resid_N1024_ns": round(float(np.mean(r1024)), 1),
        })
        print(f"  [resid] level {lvl:4.2f} target {brms*1e6:5.1f}us -> "
              f"5-23 {rows[-1]['band5_23_us']:.1f} 23-47 {rows[-1]['band23_47_us']:.1f} "
              f"| residN512 {rows[-1]['resid_N512_ns']:.0f}ns "
              f"residN1024 {rows[-1]['resid_N1024_ns']:.0f}ns", flush=True)
    return rows


# ---------------------------------------------------------------------------
# Step 2: run the ACTUAL h4 DQPSK decoder under HF injection (the gate test)
# ---------------------------------------------------------------------------
# The two rungs whose REAL outcome is known and OPPOSITE: N512 PASSed (934 bps,
# 0 cw failed), N1024 FAILed (37/37). The un-augmented sim got both wrong-way (it
# passed N1024 2/2). A faithful injection must flip N1024 to FAIL while keeping
# N512 PASS at the 1.0x level.
GATE_RUNGS = [
    {"name": "dq_p10n512_rs127",  "P": 10, "N": 512,  "spacing": 8,  "rs_k": 127,
     "offset": 90112, "payload_bytes": 8192, "frame_bytes": 510},   # REAL: PASS
    {"name": "dq_p10n1024_rs159", "P": 10, "N": 1024, "spacing": 16, "rs_k": 159,
     "offset": 49152, "payload_bytes": 8192, "frame_bytes": 510},   # REAL: FAIL
    {"name": "dq_p10n1024_rs223", "P": 10, "N": 1024, "spacing": 16, "rs_k": 223,
     "offset": 65536, "payload_bytes": 8192, "frame_bytes": 510},   # REAL: FAIL
]


def run_rung_hf(spec, seed, band_rms_s, aac=False):
    t0 = time.time()
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name=spec["name"], M=spec["P"], K=1, rs_n=255,
                rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)

    y = channel_with_hf(section, seed=seed, band_rms_s=band_rms_s, aac=aac)

    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    rx_frames = []
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi])
        flen = len(frame_audios[fi])
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(y), st + flen + pad_hi)
        bits, _ = sch.demod(y[w_lo:w_hi], nd)
        rx_frames.append(bits)
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(bits))
        raw_err += int(np.count_nonzero(tb[:m] != bits[:m])) + (len(tb) - m)
        raw_tot += len(tb)
    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == payload
    net = sch.gross_bps * spec["rs_k"] / 255.0
    return {
        "rung": spec["name"], "N": spec["N"], "seed": seed,
        "band_rms_us": round(band_rms_s * 1e6, 2),
        "rs_k": spec["rs_k"], "net_bps": round(net, 1),
        "raw_ber": round(raw_err / max(1, raw_tot), 5),
        "rs_codewords_failed": cw_failed, "n_codewords": meta["n_codewords"],
        "byte_exact": bool(exact), "wall_s": round(time.time() - t0, 1),
    }


def _job(args):
    spec, seed, brms, aac = args
    return run_rung_hf(spec, seed, brms, aac)


def gate_validation(levels, seeds=(0, 1, 2), workers=6):
    """For each injection level, decode the gate rungs and report PASS fraction.
    Level 0.0 must reproduce the un-augmented sim (N1024 PASS). A level near 1.0x
    must flip N1024 -> FAIL while N512 stays PASS (the real-tape truth)."""
    jobs = [(spec, seed, lvl * REAL_HF_BAND_RMS_S, False)
            for lvl in levels for spec in GATE_RUNGS for seed in seeds]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_job, jobs):
            rows.append(r)
            print(f"  [decode {r['rung']:18s} band{r['band_rms_us']:5.1f}us "
                  f"seed{r['seed']}] BER={r['raw_ber']:.4f} "
                  f"cw={r['rs_codewords_failed']}/{r['n_codewords']} "
                  f"exact={r['byte_exact']} ({r['wall_s']}s)", flush=True)
    return rows


def summarize_gate(rows, levels):
    by = {}
    for r in rows:
        by.setdefault((round(r["band_rms_us"] / (REAL_HF_BAND_RMS_S * 1e6), 2),
                       r["rung"]), []).append(r)
    table = []
    for lvl in levels:
        for spec in GATE_RUNGS:
            key = (round(lvl, 2), spec["name"])
            rr = by.get(key, [])
            if not rr:
                continue
            table.append({
                "level": lvl, "rung": spec["name"], "N": spec["N"],
                "n_exact": sum(x["byte_exact"] for x in rr), "n": len(rr),
                "mean_ber": round(float(np.mean([x["raw_ber"] for x in rr])), 5),
                "mean_cw_failed": round(float(np.mean(
                    [x["rs_codewords_failed"] for x in rr])), 1),
            })
    # the validation criterion at the closest-to-1.0x level
    near1 = min(levels, key=lambda L: abs(L - 1.0))
    n512 = next((t for t in table if t["level"] == near1 and t["N"] == 512), None)
    n1024 = [t for t in table if t["level"] == near1 and t["N"] == 1024]
    n512_pass = bool(n512 and n512["n_exact"] == n512["n"])
    n1024_fail = bool(n1024 and all(t["n_exact"] == 0 for t in n1024))
    reproduces_real = n512_pass and n1024_fail
    # also confirm level 0 reproduces the un-augmented sim (N1024 should PASS)
    base = [t for t in table if t["level"] == 0.0]
    base_n1024_pass = all(t["n_exact"] == t["n"] for t in base if t["N"] == 1024) \
        if any(t["N"] == 1024 for t in base) else None
    return {
        "table": table,
        "validation_level": near1,
        "n512_pass_at_1x": n512_pass,
        "n1024_fail_at_1x": n1024_fail,
        "reproduces_real_m8_outcome": reproduces_real,
        "baseline_level0_n1024_pass": base_n1024_pass,
        "verdict": ("INJECTION VALIDATED — reproduces N512-pass / N1024-fail; "
                    "the master9 HF-flutter gate cell is trustworthy"
                    if reproduces_real else
                    "INJECTION NOT VALIDATED at 1.0x — re-scale or re-shape "
                    "before any gate relies on it"),
    }


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    levels = [0.0, 0.5, 1.0, 1.5, 2.0]
    out = {
        "about": "HF-flutter injection build + self-validation for master9 gate",
        "real_hf_band_rms_s": REAL_HF_BAND_RMS_S, "hf_corner_hz": HF_CORNER_HZ,
        "levels_x_real": levels,
    }
    print("== step 1: verify injection lands the intended pilot residual ==",
          flush=True)
    out["residual_calibration"] = verify_injection_residual(levels)
    OUT.write_text(json.dumps(out, indent=2, default=float))

    print("== step 2: gate validation — decode N512 & N1024 under injection ==",
          flush=True)
    rows = gate_validation(levels)
    out["gate_rows"] = rows
    out["gate_summary"] = summarize_gate(rows, levels)
    OUT.write_text(json.dumps(out, indent=2, default=float))
    print("VERDICT:", out["gate_summary"]["verdict"], flush=True)
    print(f"[done] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
