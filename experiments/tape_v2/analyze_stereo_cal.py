#!/usr/bin/env python3
"""Analyze a STEREO capture from the UCA222 line-in path.

Works on BOTH:
  * a LIVE no-tape loopback  (Mac out -> deck record-pause monitor -> UCA222 -> Mac), and
  * a real TAPE capture of stereo_cal_master.wav.

From the front crosstalk-probe section (PROBE_L_HZ on L, PROBE_R_HZ on R) it checks:
  * both channels carrying signal, and neither clipping / too quiet  (level)
  * L/R not swapped                                                  (routing)
  * channel separation / crosstalk in dB, both directions           (separation)
  * sample clock: measured probe spacing vs expected (sidecar)       (clock)
For a long capture (a real tape body) it also splits L/R to mono WAVs and prints the
per-channel analyze_master2.py commands (run with --decode to launch them).

Usage:
    python3 analyze_stereo_cal.py <capture.wav> [--sidecar stereo_cal_master.json]
                                  [--probe-window 90] [--decode]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, hilbert, sosfiltfilt

HERE = Path(__file__).resolve().parent
CLIP = 0.99           # peak >= this -> clipping
LOW = 0.02            # peak <  this -> probably no/weak signal
CLOCK_TOL = 0.005     # 0.5 % spacing error -> clock flag


def _bandpass(x: np.ndarray, f0: float, sr: int, bw: float = 80.0):
    lo = max(20.0, f0 - bw / 2) / (sr / 2)
    hi = min(sr / 2 - 100.0, f0 + bw / 2) / (sr / 2)
    sos = butter(4, [lo, hi], btype="band", output="sos")
    y = sosfiltfilt(sos, x)
    return y, np.abs(hilbert(y))


def _smooth(x: np.ndarray, sr: int, win: float = 0.03) -> np.ndarray:
    k = max(1, int(win * sr))
    return np.convolve(x, np.ones(k) / k, mode="same")


def _detect_probe(capL, capR, f0, sr):
    """Locate the f0 probe via the INTER-CHANNEL differential |envL - envR|.

    The probe is present in ONE channel only, so |envL - envR| peaks there. The
    ladder body is identical on L and R, so it contributes ~0 to the differential
    -- this rejects body energy at the probe frequency (which a plain per-channel
    envelope max does NOT, and which otherwise mis-locates the plateau into the
    body and corrupts the spacing/crosstalk numbers).
    """
    yL, eL = _bandpass(capL, f0, sr)
    yR, eR = _bandpass(capR, f0, sr)
    diff = _smooth(np.abs(eL - eR), sr)
    pk = int(np.argmax(diff))
    if diff[pk] <= 0:
        return None
    thr = 0.5 * diff[pk]                                 # plateau around the peak
    s = pk
    while s > 0 and diff[s - 1] > thr:
        s -= 1
    e = pk
    while e < len(diff) - 1 and diff[e + 1] > thr:
        e += 1
    if (e - s) < int(0.3 * sr):                          # too short to be a 1.5 s probe
        return None
    seg = slice(s, e + 1)
    carrier = 0 if eL[seg].mean() >= eR[seg].mean() else 1
    strong_y = yL if carrier == 0 else yR
    weak_y = yR if carrier == 0 else yL
    rms_s = float(np.sqrt(np.mean(strong_y[seg] ** 2)))
    rms_w = float(np.sqrt(np.mean(weak_y[seg] ** 2)))
    return {
        "carrier": carrier,                              # 0=L, 1=R
        "center_s": 0.5 * (s + e) / sr,
        "dur_s": (e - s) / sr,
        "rms_strong": rms_s,
        "rms_weak": rms_w,
        "xtalk_db": 20.0 * np.log10(rms_w / rms_s + 1e-12),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", help="stereo capture WAV (UCA222 line-in)")
    ap.add_argument("--sidecar", default=str(HERE / "stereo_cal_master.json"))
    ap.add_argument("--probe-window", type=float, default=90.0,
                    help="seconds at the front to search for probes")
    ap.add_argument("--decode", action="store_true",
                    help="also run analyze_master2.py on each split channel")
    args = ap.parse_args()

    side = json.loads(Path(args.sidecar).read_text())
    pl = side["probes"]["L"]
    pr = side["probes"]["R"]
    sr_expect = side["sr"]
    exp_spacing = ((pr["start_frame"] + pr["end_frame"]) / 2
                   - (pl["start_frame"] + pl["end_frame"]) / 2) / sr_expect

    audio, sr = sf.read(args.capture, dtype="float32", always_2d=True)
    n, ch = audio.shape
    print(f"capture: {Path(args.capture).name}  {sr} Hz  {ch} ch  {n/sr:.2f} s")
    if ch < 2:
        print("  FAIL: capture is MONO -- use -ac 2 and the UCA222 input device.")
        sys.exit(2)
    if sr != sr_expect:
        print(f"  note: capture sr {sr} != master sr {sr_expect} "
              "(spacing/clock still valid; tape decode resamples anyway)")
    L, R = audio[:, 0], audio[:, 1]

    # ---- levels (whole file) ----
    print("LEVELS")
    for nm, x in (("L", L), ("R", R)):
        pk, rms = float(np.max(np.abs(x))), float(np.sqrt(np.mean(x ** 2)))
        tag = "CLIP!" if pk >= CLIP else ("quiet?" if pk < LOW else "ok")
        print(f"  {nm}: peak {pk:6.3f}  rms {rms:6.3f}  dBFS {20*np.log10(pk+1e-12):6.1f}  [{tag}]")

    # ---- probes (front window) ----
    w = min(n, int(args.probe_window * sr))
    Lw, Rw = L[:w], R[:w]
    dl = _detect_probe(Lw, Rw, pl["freq_hz"], sr)
    dr = _detect_probe(Lw, Rw, pr["freq_hz"], sr)
    if dl is None or dr is None:
        print("PROBES: NOT FOUND in front window -- is signal getting through? "
              "(try a louder source, longer --probe-window, or check cabling)")
        sys.exit(3)

    ch_name = {0: "L", 1: "R"}
    l_ok = dl["carrier"] == 0
    r_ok = dr["carrier"] == 1
    print("ROUTING")
    print(f"  {pl['freq_hz']:.0f} Hz sent on L -> arrived on {ch_name[dl['carrier']]}  "
          f"[{'ok' if l_ok else 'SWAPPED'}]")
    print(f"  {pr['freq_hz']:.0f} Hz sent on R -> arrived on {ch_name[dr['carrier']]}  "
          f"[{'ok' if r_ok else 'SWAPPED'}]")
    if not l_ok and not r_ok:
        print("  => L and R are SWAPPED end-to-end (cross your RCA or fix in software).")
    elif l_ok and r_ok:
        print("  => routing correct, no swap.")
    else:
        print("  => one channel mis-routed -- check cabling.")

    print("SEPARATION (crosstalk -- more negative = better isolation)")
    print(f"  L->R: {dl['xtalk_db']:6.1f} dB   (R->L: {dr['xtalk_db']:6.1f} dB)")
    worst = max(dl["xtalk_db"], dr["xtalk_db"])
    note = ("excellent (likely noise-limited)" if worst < -45 else
            "good (>=2x stereo realistic)" if worst < -25 else
            "marginal -- independent stereo payloads risky" if worst < -15 else
            "POOR -- channels heavily bleeding")
    print(f"  worst {worst:.1f} dB -> {note}")

    # ---- clock (probe spacing) ----
    meas_spacing = dr["center_s"] - dl["center_s"]
    ratio = meas_spacing / exp_spacing if exp_spacing else float("nan")
    err = abs(ratio - 1.0)
    print("CLOCK")
    print(f"  probe spacing measured {meas_spacing:.4f} s vs expected {exp_spacing:.4f} s"
          f"  (ratio {ratio:.5f}, {err*100:.3f}% off)  "
          f"[{'ok' if err < CLOCK_TOL else 'OFF -- speed/clock drift'}]")

    # ---- verdict ----
    good = l_ok and r_ok and worst < -15 and err < CLOCK_TOL \
        and all(np.max(np.abs(x)) < CLIP and np.max(np.abs(x)) >= LOW for x in (L, R))
    print("VERDICT:", "WIRING OK -- safe to commit to tape." if good
          else "review the flagged item(s) above before recording.")

    # ---- per-channel decode (only meaningful for a full tape body) ----
    is_body = n / sr > 60.0
    if is_body:
        capf = Path(args.capture)
        outL = capf.with_name(capf.stem + "_L.wav")
        outR = capf.with_name(capf.stem + "_R.wav")
        sf.write(str(outL), L, sr, subtype="FLOAT")
        sf.write(str(outR), R, sr, subtype="FLOAT")
        print(f"split -> {outL.name}, {outR.name}")
        cmds = [[sys.executable, str(HERE / "analyze_master2.py"), str(outL),
                 "--out-tag", "stereo_L"],
                [sys.executable, str(HERE / "analyze_master2.py"), str(outR),
                 "--out-tag", "stereo_R"]]
        if args.decode:
            for c in cmds:
                print("RUN:", " ".join(c))
                subprocess.run(c, check=False)
        else:
            print("per-channel decode (run, or pass --decode):")
            for c in cmds:
                print("   ", " ".join(c))
    else:
        print("(short capture -> wiring check only; no per-channel ladder decode)")


if __name__ == "__main__":
    main()
