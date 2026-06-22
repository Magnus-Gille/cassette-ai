#!/usr/bin/env python3
"""Build a STEREO calibration master for the UCA222 electrical line-in path.

Context (2026-06-22): we finally have an electrical line-in (Behringer UCA222,
deck line-out RCA L/R -> UCA222 -> USB) instead of the acoustic loop that summed
everything to mono. This is the first true-stereo run. Every existing master is
mono and analyze_master2.py downmixes stereo->mono on read, so a real stereo
calibration needs (a) a stereo master with per-channel-distinct segments and
(b) a split + crosstalk analyzer (see analyze_stereo_cal.py).

Layout (decision: "same ladder on both channels + crosstalk probes"):

  lead-in (stereo, DISTINCT per channel) -- this is what makes separation measurable:
    [1.0 s silence]
    [L-only probe: PROBE_L_HZ on L, silence on R, 1.5 s]   -> measures crosstalk L->R
    [0.5 s silence]
    [R-only probe: PROBE_R_HZ on R, silence on L, 1.5 s]   -> measures crosstalk R->L
    [1.0 s silence]
  body (IDENTICAL content on L and R):
    master2.wav (the proven mono calibration ladder) duplicated to both channels.
    After capture, each channel is split out and decoded INDEPENDENTLY by
    analyze_master2.py -> per-channel pass-rate / BER over the real stereo path.

Two outputs:
  stereo_cal_master.wav       full run (~16.6 min)   <- the real calibration
  stereo_cal_quickcheck.wav   ~20 s                  <- verify wiring/clock/crosstalk FIRST
Sidecar stereo_cal_master.json records probe windows & freqs (tracked; WAVs gitignored).

Distinct, non-harmonic probe freqs (1000 / 1700 Hz) let the analyzer also detect an
accidental L<->R swap in the wiring.

Usage:
    python3 make_stereo_cal_master.py
"""
import json
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48_000
HERE = Path(__file__).resolve().parent
MASTER_MONO = HERE / "master2.wav"          # the proven mono calibration ladder
OUT_FULL = HERE / "stereo_cal_master.wav"
OUT_QUICK = HERE / "stereo_cal_quickcheck.wav"
SIDECAR = HERE / "stereo_cal_master.json"

PROBE_L_HZ = 1000.0    # L-only burst
PROBE_R_HZ = 1700.0    # R-only burst (non-harmonic w.r.t. 1000 -> swap-detectable)
PRE_SIL = 1.0
PROBE_DUR = 1.5
MID_SIL = 0.5
POST_SIL = 1.0
QUICK_BODY_SEC = 8.0   # seconds of the ladder kept in the quick wiring-check clip


def _silence(dur: float) -> np.ndarray:
    return np.zeros(int(round(dur * SR)), dtype=np.float32)


def _tone(freq: float, dur: float, amp: float, fade: float = 0.01) -> np.ndarray:
    n = int(round(dur * SR))
    t = np.arange(n, dtype=np.float64) / SR
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    f = int(round(fade * SR))
    if 0 < f < n // 2:
        env = np.ones(n, dtype=np.float32)
        env[:f] = np.linspace(0.0, 1.0, f, dtype=np.float32)
        env[-f:] = np.linspace(1.0, 0.0, f, dtype=np.float32)
        x *= env
    return x


def build(master_mono: np.ndarray, probe_amp: float):
    """Return (stereo_full, stereo_quick, manifest)."""
    pre = _silence(PRE_SIL)
    mid = _silence(MID_SIL)
    post = _silence(POST_SIL)
    probe_dur_n = int(round(PROBE_DUR * SR))

    tone_L = _tone(PROBE_L_HZ, PROBE_DUR, probe_amp)
    tone_R = _tone(PROBE_R_HZ, PROBE_DUR, probe_amp)
    sil_probe = _silence(PROBE_DUR)

    # L channel of the lead-in: L probe present, R-probe slot silent.
    lead_L = np.concatenate([pre, tone_L, mid, sil_probe, post])
    # R channel of the lead-in: L-probe slot silent, R probe present.
    lead_R = np.concatenate([pre, sil_probe, mid, tone_R, post])
    assert lead_L.shape == lead_R.shape

    # Probe windows (samples, relative to file start) for the analyzer.
    pre_n = len(pre)
    l_start = pre_n
    l_end = pre_n + probe_dur_n
    r_start = pre_n + probe_dur_n + len(mid)
    r_end = r_start + probe_dur_n
    lead_n = len(lead_L)

    full_L = np.concatenate([lead_L, master_mono])
    full_R = np.concatenate([lead_R, master_mono])
    stereo_full = np.column_stack([full_L, full_R])

    qbody = master_mono[: int(round(QUICK_BODY_SEC * SR))]
    quick_L = np.concatenate([lead_L, qbody])
    quick_R = np.concatenate([lead_R, qbody])
    stereo_quick = np.column_stack([quick_L, quick_R])

    manifest = {
        "sr": SR,
        "channels": ["L", "R"],
        "body_source": MASTER_MONO.name,
        "body_frames": int(len(master_mono)),
        "body_seconds": round(len(master_mono) / SR, 3),
        "leadin_frames": int(lead_n),
        "leadin_seconds": round(lead_n / SR, 3),
        "probe_amp": round(float(probe_amp), 4),
        "probes": {
            "L": {"freq_hz": PROBE_L_HZ, "channel": "L",
                  "start_frame": int(l_start), "end_frame": int(l_end)},
            "R": {"freq_hz": PROBE_R_HZ, "channel": "R",
                  "start_frame": int(r_start), "end_frame": int(r_end)},
        },
        "note": ("Probe windows are relative to file start; a real capture has an "
                 "arbitrary lead-in, so analyze_stereo_cal.py detects the probe "
                 "tones directly rather than trusting these absolute offsets."),
    }
    return stereo_full, stereo_quick, manifest


def main() -> None:
    if not MASTER_MONO.exists():
        raise SystemExit(f"missing {MASTER_MONO} (regenerate via make_master2.py)")
    m, sr = sf.read(str(MASTER_MONO), dtype="float32", always_2d=False)
    if sr != SR:
        raise SystemExit(f"master sr {sr} != {SR}")
    if m.ndim > 1:
        m = m[:, 0]
    body_peak = float(np.max(np.abs(m))) if m.size else 0.7
    # Keep probes from out-shouting the ladder on tape (level ~7 SOP): cap at the
    # body's own peak, and never above 0.7 absolute.
    probe_amp = min(0.7, max(0.3, 0.9 * body_peak))

    stereo_full, stereo_quick, manifest = build(m, probe_amp)

    sf.write(str(OUT_FULL), stereo_full, SR, subtype="FLOAT")
    sf.write(str(OUT_QUICK), stereo_quick, SR, subtype="FLOAT")
    SIDECAR.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"body peak={body_peak:.3f}  probe_amp={probe_amp:.3f}")
    print(f"wrote {OUT_FULL.name}  {stereo_full.shape[0]/SR:.2f}s  "
          f"{stereo_full.nbytes/1e6:.0f} MB  (L/R)")
    print(f"wrote {OUT_QUICK.name}  {stereo_quick.shape[0]/SR:.2f}s  (wiring check)")
    print(f"wrote {SIDECAR.name}")
    print(f"probe L {PROBE_L_HZ:.0f}Hz @ "
          f"{manifest['probes']['L']['start_frame']/SR:.2f}-"
          f"{manifest['probes']['L']['end_frame']/SR:.2f}s  |  "
          f"probe R {PROBE_R_HZ:.0f}Hz @ "
          f"{manifest['probes']['R']['start_frame']/SR:.2f}-"
          f"{manifest['probes']['R']['end_frame']/SR:.2f}s")


if __name__ == "__main__":
    main()
