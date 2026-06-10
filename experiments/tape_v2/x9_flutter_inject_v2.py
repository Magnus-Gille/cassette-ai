"""x9_flutter_inject_v2.py — REAL-PSD-SHAPED HF-flutter injection + self-validation.

v1 (x9_flutter_inject.py) used a FLAT-to-60Hz jitter spectrum scaled by total
band-RMS.  Self-validation FAILED: at the 1.0x level it killed N512 (BER 0.22)
as hard as N1024 (BER 0.18) — it did NOT reproduce the real differential
(N512 survives 934 bps, N1024 dies).  Root cause: a flat spectrum over-weights
the 47-200 Hz band where NEITHER tracker helps, washing out N512's tracking
advantage (N512 follows jitter to FS/512/2=47 Hz; N1024 only to 23 Hz, so the
load-bearing differential lives in the 23-47 Hz band).

v2 fix: synthesize tau_hf(t) by filtering white noise with a filter whose
magnitude follows the MEASURED REAL jitter PSD (x9_sim_probes.json -> real ->
psd_trace), restricted to f > 3 Hz (the wow band the frozen warp already models).
A single overall LEVEL multiplier then scales it.  This preserves the real
RED spectral slope, so N512's tracking edge over N1024 is preserved.

Validation criterion (pre-registered, identical to v1):
  At the level whose pilot-tracker residual matches the real (N512 ~31 us /
  N1024 ~54 us), N1024 DQPSK must FAIL and N512 must PASS (byte-exact),
  reproducing the real m8 tape outcome.  If YES -> the master9 HF-flutter gate
  cell is trustworthy.

Reads only.  Writes results/x9_flutter_inject_v2.json.  Seeds set + logged.
"""
from __future__ import annotations

import json
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
OUT = RESULTS / "x9_flutter_inject_v2.json"
PROBES = RESULTS / "x9_sim_probes.json"

# Load the measured REAL jitter PSD trace (the shape target).
_pj = json.loads(PROBES.read_text())
_real = _pj["flutter"]["real"]
REAL_PSD_HZ = np.asarray(_real["psd_trace_hz"], float)
REAL_PSD_S2HZ = np.asarray(_real["psd_trace_s2hz"], float)
REAL_RESID_N512_NS = _real["tracker_resid_N512_rms_ns"]      # ~31350
REAL_RESID_N1024_NS = _real["tracker_resid_N1024_rms_ns"]    # ~54475
HF_LO_HZ = 3.0     # below this the frozen 2-sinusoid warp already supplies wow


def _shaped_white(n: int, seed: int, fs: int = FS) -> np.ndarray:
    """White noise filtered so its PSD follows the measured REAL jitter PSD shape
    for f>HF_LO_HZ (unit-RMS output of the shaped, HF-restricted trajectory)."""
    rg = np.random.default_rng(40_000 + seed)
    w = rg.standard_normal(n)
    W = np.fft.rfft(w)
    fr = np.fft.rfftfreq(n, 1.0 / fs)
    # interpolate sqrt(PSD) (amplitude shaping) in log-log; zero below HF_LO.
    logf = np.log10(np.clip(fr, 1e-6, None))
    amp = np.interp(logf, np.log10(REAL_PSD_HZ), np.sqrt(REAL_PSD_S2HZ),
                    left=0.0, right=np.sqrt(REAL_PSD_S2HZ[-1]))
    amp = np.where(fr >= HF_LO_HZ, amp, 0.0)
    amp = np.where(fr <= REAL_PSD_HZ[-1], amp, 0.0)   # don't extrapolate past 200 Hz
    tau = np.fft.irfft(W * amp, n=n)
    tau = tau / (np.sqrt(np.mean(tau ** 2)) + 1e-18)   # unit RMS; LEVEL scales it
    return tau


def inject_hf_flutter(y: np.ndarray, level: float, *, seed: int,
                      unit_rms_s: float, fs: int = FS) -> np.ndarray:
    """Resample y onto t - tau_hf, where tau_hf has the real PSD SHAPE and total
    RMS = level * unit_rms_s.  unit_rms_s is the RMS of the shaped trajectory at
    level 1.0 calibrated so the pilot residual matches the real (see main)."""
    if level <= 0:
        return y
    n = len(y)
    tau = _shaped_white(n, seed, fs) * (level * unit_rms_s)
    t = np.arange(n) / fs
    warped = np.clip(t - tau, 0.0, t[-1])
    return np.interp(t, warped, y)


def channel_with_hf(section, *, seed, level, unit_rms_s, aac=False):
    y = sim_v2.channel_v2(section, profile="tape7", aac=aac, seed_offset=seed)
    y = inject_hf_flutter(np.asarray(y, np.float64), level, seed=seed,
                          unit_rms_s=unit_rms_s)
    return y.astype(np.float64)


# ---------------------------------------------------------------------------
# calibrate unit_rms_s so that level=1.0 reproduces the real pilot residual
# ---------------------------------------------------------------------------
def calibrate_unit_rms(seeds=(0, 1, 2), dur_s=16.0):
    """Find the shaped-trajectory total RMS at which the N1024 pilot-tracker
    residual matches the real (~54 us).  Returns (unit_rms_s, diagnostics)."""
    tone = xp.make_tone(xp.PILOT_HZ, dur_s)
    n = len(tone)
    # measure the residual produced by a UNIT-RMS shaped trajectory of 1 us total,
    # then scale linearly (residual is ~linear in injected RMS for small jitter).
    probe_rms = 30e-6
    r1024s = []
    for s in seeds:
        y = channel_with_hf(tone, seed=s, level=1.0, unit_rms_s=probe_rms)[:n]
        tau = xp.instantaneous_timing_jitter(y, xp.PILOT_HZ)
        r1024s.append(xp.pilot_tracker_residual(tau, 1024)["resid_rms_s"])
    resid_at_probe = float(np.mean(r1024s))
    target = REAL_RESID_N1024_NS * 1e-9
    # residual is dominated by injected HF jitter (sim's own is ~11 us); subtract
    # in quadrature to isolate the injection's contribution, then linear-scale.
    sim_floor = 10.84e-6     # sim N1024 residual w/o injection (x9_sim_probes)
    inj_at_probe = np.sqrt(max(resid_at_probe ** 2 - sim_floor ** 2, 1e-18))
    inj_target = np.sqrt(max(target ** 2 - sim_floor ** 2, 1e-18))
    unit_rms = probe_rms * inj_target / max(inj_at_probe, 1e-18)
    return unit_rms, {"resid_at_probe_us": round(resid_at_probe * 1e6, 2),
                      "probe_rms_us": probe_rms * 1e6,
                      "target_resid_N1024_us": round(target * 1e6, 2),
                      "unit_rms_us": round(unit_rms * 1e6, 2)}


def verify_residual(unit_rms_s, levels, seeds=(0, 1, 2), dur_s=16.0):
    tone = xp.make_tone(xp.PILOT_HZ, dur_s)
    n = len(tone)
    rows = []
    for lvl in levels:
        r512, r1024, b5_23, b23_47, b47_200 = [], [], [], [], []
        for s in seeds:
            y = channel_with_hf(tone, seed=s, level=lvl, unit_rms_s=unit_rms_s)[:n]
            tau = xp.instantaneous_timing_jitter(y, xp.PILOT_HZ)
            f, P = xp.jitter_psd(tau)
            b5_23.append(xp.band_jitter_rms(f, P, 5.0, 23.4))
            b23_47.append(xp.band_jitter_rms(f, P, 23.4, 46.9))
            b47_200.append(xp.band_jitter_rms(f, P, 46.9, 200.0))
            r512.append(xp.pilot_tracker_residual(tau, 512)["resid_rms_ns"])
            r1024.append(xp.pilot_tracker_residual(tau, 1024)["resid_rms_ns"])
        rows.append({"level": lvl,
                     "band5_23_us": round(float(np.mean(b5_23)) * 1e6, 2),
                     "band23_47_us": round(float(np.mean(b23_47)) * 1e6, 2),
                     "band47_200_us": round(float(np.mean(b47_200)) * 1e6, 2),
                     "resid_N512_ns": round(float(np.mean(r512)), 1),
                     "resid_N1024_ns": round(float(np.mean(r1024)), 1)})
        print(f"  [resid] lvl {lvl:4.2f} 5-23 {rows[-1]['band5_23_us']:5.1f} "
              f"23-47 {rows[-1]['band23_47_us']:5.1f} 47-200 {rows[-1]['band47_200_us']:5.1f} "
              f"| residN512 {rows[-1]['resid_N512_ns']:.0f} "
              f"residN1024 {rows[-1]['resid_N1024_ns']:.0f}  "
              f"(real: 31350/54475)", flush=True)
    return rows


# ---------------------------------------------------------------------------
GATE_RUNGS = [
    {"name": "dq_p10n512_rs127",  "P": 10, "N": 512,  "spacing": 8,  "rs_k": 127,
     "offset": 90112, "payload_bytes": 8192, "frame_bytes": 510},   # REAL PASS
    {"name": "dq_p10n1024_rs159", "P": 10, "N": 1024, "spacing": 16, "rs_k": 159,
     "offset": 49152, "payload_bytes": 8192, "frame_bytes": 510},   # REAL FAIL
    {"name": "dq_p10n1024_rs223", "P": 10, "N": 1024, "spacing": 16, "rs_k": 223,
     "offset": 65536, "payload_bytes": 8192, "frame_bytes": 510},   # REAL FAIL
]

_UNIT_RMS = None    # set in main, passed via globals to workers


def run_rung_hf(spec, seed, level, unit_rms_s, aac=False):
    t0 = time.time()
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name=spec["name"], M=spec["P"], K=1, rs_n=255,
                rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)
    y = channel_with_hf(section, seed=seed, level=level, unit_rms_s=unit_rms_s, aac=aac)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    rx_frames = []
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi])
        flen = len(frame_audios[fi])
        w_lo = max(0, st - pad_lo); w_hi = min(len(y), st + flen + pad_hi)
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
    return {"rung": spec["name"], "N": spec["N"], "seed": seed, "level": level,
            "rs_k": spec["rs_k"], "net_bps": round(net, 1),
            "raw_ber": round(raw_err / max(1, raw_tot), 5),
            "rs_codewords_failed": cw_failed, "n_codewords": meta["n_codewords"],
            "byte_exact": bool(exact), "wall_s": round(time.time() - t0, 1)}


def _job(args):
    spec, seed, level, unit_rms_s = args
    return run_rung_hf(spec, seed, level, unit_rms_s)


def gate_validation(levels, unit_rms_s, seeds=(0, 1, 2), workers=6):
    jobs = [(spec, seed, lvl, unit_rms_s)
            for lvl in levels for spec in GATE_RUNGS for seed in seeds]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_job, jobs):
            rows.append(r)
            print(f"  [decode {r['rung']:18s} lvl{r['level']:4.2f} seed{r['seed']}] "
                  f"BER={r['raw_ber']:.4f} cw={r['rs_codewords_failed']}"
                  f"/{r['n_codewords']} exact={r['byte_exact']} ({r['wall_s']}s)",
                  flush=True)
    return rows


def summarize(rows, levels):
    by = {}
    for r in rows:
        by.setdefault((r["level"], r["rung"]), []).append(r)
    table = []
    for lvl in levels:
        for spec in GATE_RUNGS:
            rr = by.get((lvl, spec["name"]), [])
            if not rr:
                continue
            table.append({"level": lvl, "rung": spec["name"], "N": spec["N"],
                          "n_exact": sum(x["byte_exact"] for x in rr), "n": len(rr),
                          "mean_ber": round(float(np.mean([x["raw_ber"] for x in rr])), 5)})
    near1 = min(levels, key=lambda L: abs(L - 1.0))
    n512 = next((t for t in table if t["level"] == near1 and t["N"] == 512), None)
    n1024 = [t for t in table if t["level"] == near1 and t["N"] == 1024]
    n512_pass = bool(n512 and n512["n_exact"] == n512["n"])
    n1024_fail = bool(n1024 and all(t["n_exact"] == 0 for t in n1024))
    repro = n512_pass and n1024_fail
    # also report the WIDEST level window where the differential holds
    windows = []
    for lvl in levels:
        n5 = next((t for t in table if t["level"] == lvl and t["N"] == 512), None)
        n10 = [t for t in table if t["level"] == lvl and t["N"] == 1024]
        if n5 and n10:
            windows.append({"level": lvl,
                            "n512_pass": n5["n_exact"] == n5["n"],
                            "n1024_fail": all(t["n_exact"] == 0 for t in n10),
                            "differential": (n5["n_exact"] == n5["n"]) and
                                            all(t["n_exact"] == 0 for t in n10)})
    return {"table": table, "validation_level": near1,
            "n512_pass_at_1x": n512_pass, "n1024_fail_at_1x": n1024_fail,
            "reproduces_real_m8_outcome": repro,
            "differential_windows": windows,
            "verdict": ("INJECTION VALIDATED — reproduces N512-pass / N1024-fail; "
                        "master9 HF-flutter gate cell is trustworthy"
                        if repro else
                        "INJECTION NOT VALIDATED at 1.0x — see differential_windows "
                        "for any level where the real differential is reproduced")}


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    levels = [0.0, 0.5, 0.75, 1.0, 1.25, 1.5]
    print("== calibrate unit_rms so level 1.0 matches real N1024 residual ==",
          flush=True)
    unit_rms, cal = calibrate_unit_rms()
    print("  calibration:", cal, flush=True)
    out = {"about": "REAL-PSD-shaped HF-flutter injection (v2) self-validation",
           "real_resid_N512_ns": REAL_RESID_N512_NS,
           "real_resid_N1024_ns": REAL_RESID_N1024_NS,
           "hf_lo_hz": HF_LO_HZ, "unit_rms_us": cal["unit_rms_us"],
           "calibration": cal, "levels": levels}
    print("== verify residual vs level ==", flush=True)
    out["residual_calibration"] = verify_residual(unit_rms, levels)
    OUT.write_text(json.dumps(out, indent=2, default=float))
    print("== gate validation: decode N512 & N1024 under shaped injection ==",
          flush=True)
    rows = gate_validation(levels, unit_rms)
    out["gate_rows"] = rows
    out["gate_summary"] = summarize(rows, levels)
    OUT.write_text(json.dumps(out, indent=2, default=float))
    print("VERDICT:", out["gate_summary"]["verdict"], flush=True)
    print("differential windows:",
          json.dumps(out["gate_summary"]["differential_windows"]), flush=True)
    print(f"[done] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
