"""x9_sim_probes.py — empirical fidelity probes for the master9 sim-gate audit (R6).

Goal: answer, with numbers, three fidelity questions the DQPSK N1024 sim->real
catastrophe forced open:

  P1  FLUTTER SPECTRUM.  The sim warps time with two pure sinusoids (0.55 Hz wow,
      4.8 Hz flutter) + a little white.  Does the resulting *timing-jitter PSD*
      match the REAL tape's?  Specifically: how much jitter energy sits ABOVE the
      symbol-rate-tracking Nyquist of N1024 (~23.4 Hz) vs N512 (~46.9 Hz)?  If the
      sim's high-freq jitter is far below reality, the pilot tracker looks like it
      keeps up at N1024 in sim while it cannot on tape -> exactly the observed
      failure.

  P2  PILOT-DRIVEN TRACKER RESIDUAL.  Run the *actual* DQPSK pilot tracker over a
      pure tone pushed through (a) the sim channel and (b) the real capture's
      steady sounder tone.  Report the residual timing-jitter the tracker leaves
      at N512 vs N1024.  This is the load-bearing quantity: residual phase noise
      on the data carriers = 2*pi*f*dtau_resid.

  P3  ICI / off-bin leakage vs carrier spacing.  Inject a single pure tone, push
      through the sim, measure energy that lands in neighbouring FFT bins at dense
      spacings (93/187/375 Hz).  Tells whether the sim produces honest flutter-ICI
      for a dense-OFDM master9 grid, or whether it is blind to it (no sidebands).

Writes results/x9_sim_probes.json.  Reads the REAL capture
captures/m8_tape_mono_lossless.wav (present, gitignored) for the ground-truth
comparison; degrades gracefully (sim-only) if it is absent.

Seeds: all RNG seeded + logged.  No file is modified; this only reads.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy import signal

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sim_v2  # noqa: E402
import real_channel_sim as rcs  # noqa: E402

FS = 48_000
PILOT_HZ = 4500.0          # DQPSK pilot carrier (mid-band) in both N512 & N1024
RESULTS = _HERE / "results"
CAPTURE = _HERE / "captures" / "m8_tape_mono_lossless.wav"
OUT = RESULTS / "x9_sim_probes.json"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def instantaneous_timing_jitter(y: np.ndarray, f0: float, fs: int = FS) -> np.ndarray:
    """Heterodyne a near-pure tone at f0 to baseband, lowpass, and return the
    instantaneous TIMING deviation dtau(t) [seconds] = -unwrap(phase)/(2*pi*f0).

    A pure carrier x(t)=sin(2*pi*f0*(t - tau(t))) has baseband phase
    -2*pi*f0*tau(t); recovering phase recovers tau(t) up to a constant.
    """
    y = np.asarray(y, dtype=np.float64)
    n = np.arange(len(y))
    bb = y * np.exp(-2j * np.pi * f0 * n / fs)
    # lowpass to +/-150 Hz around the carrier (keeps wow+flutter, drops the
    # image at 2*f0 and out-of-band noise)
    sos = signal.butter(6, 150.0, btype="low", fs=fs, output="sos")
    bbf = signal.sosfiltfilt(sos, bb)
    ph = np.unwrap(np.angle(bbf))
    # remove any residual carrier-frequency offset (linear phase trend).
    # Use a CENTERED, normalized time basis [-1, 1] so the lstsq design matrix is
    # well-conditioned even for long (minute-scale) real segments (a raw-seconds
    # basis overflows float64 in A@coef on a 600 s capture).
    u = np.linspace(-1.0, 1.0, len(y))
    A = np.vstack([u, np.ones_like(u)]).T
    coef, *_ = np.linalg.lstsq(A, ph, rcond=None)
    ph_detrend = ph - A @ coef
    tau = -ph_detrend / (2 * np.pi * f0)
    return tau  # seconds


def jitter_psd(tau: np.ndarray, fs: int = FS):
    """Welch PSD of the timing-jitter signal tau(t). Returns (f, Pxx) with Pxx
    in s^2/Hz. Long segments -> fine low-freq resolution."""
    nper = min(len(tau), 1 << 18)
    f, Pxx = signal.welch(tau, fs=fs, nperseg=nper, noverlap=nper // 2,
                          detrend="linear", scaling="density")
    return f, Pxx


def band_jitter_rms(f, Pxx, f_lo, f_hi):
    """RMS timing jitter [seconds] in the band [f_lo, f_hi] from the PSD."""
    m = (f >= f_lo) & (f < f_hi)
    if not np.any(m):
        return 0.0
    # trapezoid integrate PSD -> variance
    var = np.trapezoid(Pxx[m], f[m])
    return float(np.sqrt(max(var, 0.0)))


def make_tone(f0: float, dur_s: float, fs: int = FS, amp: float = 0.6) -> np.ndarray:
    n = int(dur_s * fs)
    t = np.arange(n) / fs
    return (amp * np.sin(2 * np.pi * f0 * t)).astype(np.float64)


# ---------------------------------------------------------------------------
# P1/P2 : flutter spectrum, sim vs real, and tracker residual at N512/N1024
# ---------------------------------------------------------------------------
def pilot_tracker_residual(tau_true: np.ndarray, N: int, fs: int = FS):
    """Emulate the h4_dqpsk pilot tracker on a known timing trajectory tau_true(t).

    The tracker observes dtau per symbol = tau(t_i) - tau(t_{i-1}) (the pilot
    differential), EMA-smooths with alpha=0.5, and steers the window.  The data
    carriers see the residual = tau_true - tau_tracked at the symbol instants.
    We report the residual timing-jitter RMS [s] (-> phase noise = 2*pi*f*resid).
    """
    ema = 0.5
    nsym = len(tau_true) // N
    if nsym < 4:
        return {"n_sym": nsym, "resid_rms_s": float("nan")}
    # sample the true trajectory at symbol centers
    centers = (np.arange(nsym) * N + N // 2).astype(int)
    tau_sym = tau_true[centers]
    # pilot measures the per-symbol DIFFERENCE (differential phase), EMA-smoothed,
    # then the tracker's accumulated estimate is the cumulative sum of smoothed
    # diffs (mirrors drift -= dtau accumulation in demod()).
    sm = 0.0
    est = np.zeros(nsym)
    acc = tau_sym[0]
    est[0] = acc
    for i in range(1, nsym):
        dtau = tau_sym[i] - tau_sym[i - 1]
        sm = (1 - ema) * dtau + ema * sm
        acc += sm
        est[i] = acc
    resid = tau_sym - est
    # drop warm-up
    resid = resid[2:]
    return {
        "n_sym": int(nsym),
        "resid_rms_s": float(np.sqrt(np.mean(resid ** 2))),
        "resid_rms_ns": float(np.sqrt(np.mean(resid ** 2)) * 1e9),
        # phase noise this residual imposes on the TOP data carrier (~7.5 kHz) and
        # the worst dense-grid case; rms phase in degrees
        "phase_noise_deg_at_7500": float(
            np.degrees(2 * np.pi * 7500.0 * np.sqrt(np.mean(resid ** 2)))),
        "phase_noise_deg_at_4500": float(
            np.degrees(2 * np.pi * 4500.0 * np.sqrt(np.mean(resid ** 2)))),
    }


def probe_flutter(seeds=(0, 1, 2), dur_s=20.0):
    """P1+P2. Sim flutter PSD (aac on & off) and tracker residual vs N; plus the
    REAL capture's sounder-tone flutter PSD + residual if the capture is present."""
    out = {"pilot_hz": PILOT_HZ, "dur_s": dur_s, "seeds": list(seeds)}

    tone = make_tone(PILOT_HZ, dur_s)

    # ---- SIM, aac off (pure tape+room physics) and aac on (full v2) ----
    for aac in (False, True):
        rms_band = {"0_1Hz": [], "1_5Hz": [], "5_23.4Hz": [], "23.4_46.9Hz": [],
                    "46.9_200Hz": [], "total": []}
        resid512, resid1024 = [], []
        psd_keep = None
        for s in seeds:
            y = sim_v2.channel_v2(tone, profile="tape7", aac=aac, seed_offset=s)
            y = y[:len(tone)]
            tau = instantaneous_timing_jitter(y, PILOT_HZ)
            f, P = jitter_psd(tau)
            if psd_keep is None:
                psd_keep = (f, P)
            rms_band["0_1Hz"].append(band_jitter_rms(f, P, 0.05, 1.0))
            rms_band["1_5Hz"].append(band_jitter_rms(f, P, 1.0, 5.0))
            rms_band["5_23.4Hz"].append(band_jitter_rms(f, P, 5.0, 23.4))
            rms_band["23.4_46.9Hz"].append(band_jitter_rms(f, P, 23.4, 46.9))
            rms_band["46.9_200Hz"].append(band_jitter_rms(f, P, 46.9, 200.0))
            rms_band["total"].append(band_jitter_rms(f, P, 0.05, 200.0))
            resid512.append(pilot_tracker_residual(tau, 512))
            resid1024.append(pilot_tracker_residual(tau, 1024))
        key = "sim_aac_on" if aac else "sim_aac_off"
        out[key] = {
            "jitter_rms_s_by_band": {k: float(np.mean(v)) for k, v in rms_band.items()},
            "tracker_resid_N512_rms_ns": float(np.mean([r["resid_rms_ns"] for r in resid512])),
            "tracker_resid_N1024_rms_ns": float(np.mean([r["resid_rms_ns"] for r in resid1024])),
            "phase_noise_deg_N512_at7500": float(np.mean([r["phase_noise_deg_at_7500"] for r in resid512])),
            "phase_noise_deg_N1024_at7500": float(np.mean([r["phase_noise_deg_at_7500"] for r in resid1024])),
        }
        # keep a coarse PSD trace (log-spaced) for the report
        f, P = psd_keep
        sel = (f > 0.05) & (f < 200)
        ff, PP = f[sel], P[sel]
        idx = np.unique(np.geomspace(1, len(ff) - 1, 40).astype(int))
        out[key]["psd_trace_hz"] = [float(x) for x in ff[idx]]
        out[key]["psd_trace_s2hz"] = [float(x) for x in PP[idx]]

    # ---- REAL capture sounder tone (ground truth) ----
    if CAPTURE.exists():
        out["real"] = probe_real_flutter()
    else:
        out["real"] = {"available": False}
    return out


def probe_real_flutter():
    """Extract a steady tone from the real m8 capture and measure its flutter PSD
    + the pilot-tracker residual at N512/N1024. We look for the longest stretch
    of strong, near-pure tone in the mid-band (the front sounder holds steady
    tones; failing that, the DQPSK pilot at 4500 Hz is a constant carrier through
    every DQPSK frame)."""
    y, sr = sf.read(CAPTURE, dtype="float64", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    info = {"available": True, "sr": int(sr), "len_s": round(len(y) / sr, 1)}
    if sr != FS:
        g = np.gcd(int(sr), FS)
        y = signal.resample_poly(y, FS // g, sr // g)
        sr = FS
        info["resampled_to"] = FS

    # The DQPSK pilot at 4500 Hz (unmodulated mid-band carrier) is present
    # CONTINUOUSLY through the whole DQPSK block (~298-540 s in this capture;
    # payloads 5-7).  This is the exact region whose N1024 tracker failed, so it
    # is the right ground truth.  Within it, pick the steadiest contiguous
    # ~8 s sub-window (max band power, max tonality) and measure jitter there.
    # data carriers sit at +/-750 Hz (N512) — well outside the +/-150 Hz
    # bandpass — so the pilot is cleanly isolated.
    f0 = PILOT_HZ
    sos_bp = signal.butter(6, [f0 - 150, f0 + 150], btype="band", fs=sr, output="sos")
    yb = signal.sosfiltfilt(sos_bp, y)
    region = (int(300 * sr), int(540 * sr))            # DQPSK block (found empirically)
    region = (region[0], min(region[1], len(y)))
    win = int(8.0 * sr)
    hop = int(2.0 * sr)
    best = None
    for st in range(region[0], region[1] - win, hop):
        seg = yb[st:st + win]
        Y = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        fr = np.fft.rfftfreq(len(seg), 1 / sr)
        narrow = Y[(fr > f0 - 30) & (fr < f0 + 30)].sum()
        wide = Y[(fr > f0 - 150) & (fr < f0 + 150)].sum() + 1e-12
        tonality = narrow / wide
        power = float(np.mean(seg ** 2))
        score = tonality * power           # steady AND strong
        if power > 1e-7 and (best is None or score > best[2]):
            best = (st, st + win, score, tonality, power)
    if best is None:
        info["found_tone"] = False
        return info
    st, en, score, ton, pwr = best
    info.update({"found_tone": True, "window_s": [round(st / sr, 1), round(en / sr, 1)],
                 "region_s": [round(region[0] / sr, 1), round(region[1] / sr, 1)],
                 "tonality": round(ton, 3), "power": pwr})
    seg = y[st:en]
    tau = instantaneous_timing_jitter(seg, f0, fs=sr)
    if not np.all(np.isfinite(tau)):
        info["found_tone"] = False
        info["error"] = "non-finite tau"
        return info
    f, P = jitter_psd(tau, fs=sr)
    info["jitter_rms_s_by_band"] = {
        "0_1Hz": band_jitter_rms(f, P, 0.05, 1.0),
        "1_5Hz": band_jitter_rms(f, P, 1.0, 5.0),
        "5_23.4Hz": band_jitter_rms(f, P, 5.0, 23.4),
        "23.4_46.9Hz": band_jitter_rms(f, P, 23.4, 46.9),
        "46.9_200Hz": band_jitter_rms(f, P, 46.9, 200.0),
        "total": band_jitter_rms(f, P, 0.05, 200.0),
    }
    r512 = pilot_tracker_residual(tau, 512, fs=sr)
    r1024 = pilot_tracker_residual(tau, 1024, fs=sr)
    info["tracker_resid_N512_rms_ns"] = r512["resid_rms_ns"]
    info["tracker_resid_N1024_rms_ns"] = r1024["resid_rms_ns"]
    info["phase_noise_deg_N512_at7500"] = r512["phase_noise_deg_at_7500"]
    info["phase_noise_deg_N1024_at7500"] = r1024["phase_noise_deg_at_7500"]
    sel = (f > 0.05) & (f < 200)
    ff, PP = f[sel], P[sel]
    if len(ff) > 5:
        idx = np.unique(np.geomspace(1, len(ff) - 1, 40).astype(int))
        info["psd_trace_hz"] = [float(x) for x in ff[idx]]
        info["psd_trace_s2hz"] = [float(x) for x in PP[idx]]
    return info


# ---------------------------------------------------------------------------
# P3 : ICI / off-bin leakage vs carrier spacing (sim only)
# ---------------------------------------------------------------------------
def probe_ici(N_list=(256, 512, 1024), seeds=(0, 1, 2)):
    """Inject a single pure tone on an integer bin; push through the sim; measure
    the fraction of energy that leaks into the +/-1..+/-4 neighbouring bins (the
    flutter-ICI skirt).  No window -> rectangular -> only the channel produces
    off-bin energy, isolating flutter/reverb ICI from analysis-window leakage."""
    out = {}
    for N in N_list:
        df = FS / N
        b0 = int(round(4500.0 / df))           # mid-band tone on an exact bin
        f0 = b0 * df
        results = {"df_hz": round(df, 1), "tone_hz": round(f0, 1)}
        for aac in (False, True):
            adj1, adj2, dist = [], [], []
            for s in seeds:
                # 64 symbols' worth of tone so we average flutter realizations
                tone = make_tone(f0, 64 * N / FS)
                y = sim_v2.channel_v2(tone, profile="tape7", aac=aac, seed_offset=s)
                y = y[:len(tone)]
                # block-DFT exactly on the symbol grid (no window)
                nb = len(y) // N
                Y = np.fft.rfft(y[:nb * N].reshape(nb, N), axis=1)
                mag = np.abs(Y).mean(axis=0)    # average spectrum
                tot = mag.sum() + 1e-12
                e0 = mag[b0]
                e1 = mag[b0 - 1] + mag[b0 + 1]
                e2 = mag[b0 - 2] + mag[b0 + 2]
                # distant: everything outside +/-4 bins, in-band only
                lo = max(0, b0 - 80); hi = min(len(mag), b0 + 80)
                band = mag[lo:hi].copy()
                c = b0 - lo
                band[max(0, c - 4):c + 5] = 0.0
                edist = band.sum()
                adj1.append(e1 / (e0 + 1e-12))
                adj2.append(e2 / (e0 + 1e-12))
                dist.append(edist / (e0 + 1e-12))
            key = "aac_on" if aac else "aac_off"
            results[key] = {
                "adj1_over_main": float(np.mean(adj1)),   # +/-1 bin leak / main
                "adj2_over_main": float(np.mean(adj2)),   # +/-2 bin leak / main
                "distant_over_main": float(np.mean(dist)),
            }
        out[f"N{N}"] = results
    return out


# ---------------------------------------------------------------------------
def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    print("== P1/P2: flutter spectrum + tracker residual ==", flush=True)
    flut = probe_flutter()
    print("  sim aac_off bands:", json.dumps(
        flut["sim_aac_off"]["jitter_rms_s_by_band"], indent=0)[:200], flush=True)
    print("  sim aac_off resid N512/N1024 ns:",
          round(flut["sim_aac_off"]["tracker_resid_N512_rms_ns"], 1),
          round(flut["sim_aac_off"]["tracker_resid_N1024_rms_ns"], 1), flush=True)
    if flut["real"].get("found_tone"):
        print("  REAL resid N512/N1024 ns:",
              round(flut["real"]["tracker_resid_N512_rms_ns"], 1),
              round(flut["real"]["tracker_resid_N1024_rms_ns"], 1), flush=True)
        print("  REAL phase-noise deg @7500 N512/N1024:",
              round(flut["real"]["phase_noise_deg_N512_at7500"], 1),
              round(flut["real"]["phase_noise_deg_N1024_at7500"], 1), flush=True)

    print("== P3: ICI / off-bin leakage vs spacing ==", flush=True)
    ici = probe_ici()
    for k, v in ici.items():
        print(f"  {k} (df={v['df_hz']}Hz): aac_off adj1={v['aac_off']['adj1_over_main']:.4f} "
              f"dist={v['aac_off']['distant_over_main']:.4f} | "
              f"aac_on adj1={v['aac_on']['adj1_over_main']:.4f}", flush=True)

    payload = {"probe": "x9 sim fidelity probes (R6)",
               "flutter": flut, "ici": ici,
               "notes": {
                   "N512_track_nyquist_hz": FS / 512 / 2,
                   "N1024_track_nyquist_hz": FS / 1024 / 2,
                   "pilot_hz": PILOT_HZ,
               }}
    OUT.write_text(json.dumps(payload, indent=2, default=float))
    print(f"[done] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
