"""d1_preemphasis.py — Hypothesis D1: Channel-matched pre-emphasis / spectral shaping.

Shape the TX spectrum so that post-channel SNR(f) is flatter, pushing more OFDM
subcarriers above higher-QAM thresholds.

The cassette channel (src/channel.py: 5th-order Butterworth lowpass + AWGN) rolls
off the high frequencies. Pre-emphasizing the highs (boosting TX amplitude on high
subcarriers, within a fixed total power budget) equalizes received SNR(f), letting
the bit-loader assign more bits to more carriers -> higher gross & net.

Sweep: flat / +3dB/oct / +6dB/oct / channel-inverse (Butterworth shape) / dpd model.
For each curve: channel-probe with pre-emphasis in place -> new SNR -> new bit-loading
-> evaluate_dual.

Accept bars (pre-registered):
  SIM: net >= 4400 bps (>=1.11x C4 sim net of ~3968)
  REAL: >=256 net bps OR raised real survival vs C4 (real net ~233, survival 0)
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
from scipy.signal import butter, sosfreqz

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

sys.path.insert(0, str(ROOT / "experiments" / "deepdive2"))

import hyp_common as hc          # noqa: E402
import capture_scenarios as cs   # noqa: E402
import dd_common as dd            # noqa: E402

FS = 48_000

# ---------------------------------------------------------------------------
# OFDM framing (identical to C4)
# ---------------------------------------------------------------------------
N_FFT = 256
N_CP = 32
N_SYM = N_FFT + N_CP

F_LOW = 500.0
F_HIGH = 10_300.0
SC_LOW = int(np.ceil(F_LOW * N_FFT / FS))
SC_HIGH = int(np.floor(F_HIGH * N_FFT / FS))
ALL_SC = np.arange(SC_LOW, SC_HIGH + 1)

PILOT_SPACING = 4
PILOT_INDICES = np.array([sc for sc in ALL_SC if (sc - SC_LOW) % PILOT_SPACING == 2])
DATA_INDICES = np.array([sc for sc in ALL_SC if sc not in set(PILOT_INDICES)])
PILOT_AMP = 1.5

N_REF_SYMS = 4
ACQ_SEARCH = 50
TIMING_SEARCH = 4
_K = np.arange(N_FFT)

GAP_DB = 9.0
MAX_BPS = 4


# ---------------------------------------------------------------------------
# Gray QAM constellations (identical to C4)
# ---------------------------------------------------------------------------
def _gray_qam(bps: int) -> np.ndarray:
    if bps == 1:
        return np.array([-1.0 + 0j, 1.0 + 0j])
    if bps == 2:
        return np.array([-1 - 1j, -1 + 1j, 1 - 1j, 1 + 1j]) / np.sqrt(2)
    side = int(round(np.sqrt(2 ** bps)))
    half = bps // 2
    gray = [i ^ (i >> 1) for i in range(side)]
    levels = np.arange(-(side - 1), side, 2, dtype=float)
    pos_for_gray = {g: levels[k] for k, g in enumerate(gray)}
    pts = np.zeros(2 ** bps, dtype=complex)
    for sym in range(2 ** bps):
        gi = sym >> half
        gq = sym & ((1 << half) - 1)
        pts[sym] = pos_for_gray[gi] + 1j * pos_for_gray[gq]
    return pts / np.sqrt(np.mean(np.abs(pts) ** 2))


CONST = {b: _gray_qam(b) for b in (1, 2, 4, 6)}
BITPAT = {
    b: np.array([[(idx >> (b - 1 - j)) & 1 for j in range(b)] for idx in range(2 ** b)],
                dtype=np.uint8)
    for b in (1, 2, 4, 6)
}


def _osym(fd: np.ndarray) -> np.ndarray:
    x = np.fft.ifft(fd, n=N_FFT)
    return np.concatenate([x[-N_CP:], x]).real.astype(np.float64)


_rng_ref = np.random.default_rng(777)
REF_SYM = (2 * _rng_ref.integers(0, 2, size=len(ALL_SC)) - 1).astype(float)
PILOT_PATTERN = np.ones(len(PILOT_INDICES))


def _ref_fd() -> np.ndarray:
    fd = np.zeros(N_FFT, dtype=complex)
    fd[ALL_SC] = REF_SYM * PILOT_AMP
    return fd


def _normalize(audio: np.ndarray, target_rms: float = 0.30) -> np.ndarray:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms > 1e-9:
        audio = audio * (target_rms / rms)
    return audio.astype(np.float32)


# ---------------------------------------------------------------------------
# Tracking demod (identical to C4)
# ---------------------------------------------------------------------------
def _lock_score(fd_rx: np.ndarray):
    Hp = fd_rx[PILOT_INDICES] / (PILOT_PATTERN * PILOT_AMP)
    ph = np.unwrap(np.angle(Hp))
    slope = np.polyfit(PILOT_INDICES, ph, 1)[0]
    res = np.std(ph - (slope * PILOT_INDICES + np.mean(ph - slope * PILOT_INDICES)))
    score = float(np.sum(np.abs(Hp))) / (1.0 + 5.0 * res)
    return score, slope


def _track_demod(rx: np.ndarray, n_syms: int | None = None):
    pos0 = N_REF_SYMS * N_SYM
    best = None
    for off in range(-ACQ_SEARCH, ACQ_SEARCH + 1):
        seg = rx[pos0 + off:pos0 + off + N_SYM]
        if len(seg) < N_SYM:
            continue
        fd_rx = np.fft.fft(seg[N_CP:N_CP + N_FFT])
        score, _ = _lock_score(fd_rx)
        if best is None or score > best[0]:
            best = (score, off)
    drift = float(best[1]) if best is not None else 0.0

    out = []
    pos = pos0
    idx = 0
    pmag_ref = None
    while pos + drift + N_SYM <= len(rx):
        base = int(round(pos + drift))
        best = None
        for d in range(-TIMING_SEARCH, TIMING_SEARCH + 1):
            seg = rx[base + d:base + d + N_SYM]
            if len(seg) < N_SYM:
                break
            fd_rx = np.fft.fft(seg[N_CP:N_CP + N_FFT])
            score, slope = _lock_score(fd_rx)
            if best is None or score > best[0]:
                best = (score, d, fd_rx, slope)
        if best is None:
            break
        _, d, fd_rx, slope = best
        fd_rx = fd_rx * np.exp(-1j * slope * _K)
        Hp = fd_rx[PILOT_INDICES] / (PILOT_PATTERN * PILOT_AMP)
        H = (np.interp(DATA_INDICES, PILOT_INDICES, Hp.real)
             + 1j * np.interp(DATA_INDICES, PILOT_INDICES, Hp.imag))
        H = np.where(np.abs(H) > 1e-6, H, 1e-6)
        eq = fd_rx[DATA_INDICES] / H
        pmag = np.abs(Hp)
        med = float(np.median(pmag))
        if pmag_ref is None:
            pmag_ref = med
        ph = np.unwrap(np.angle(Hp))
        sl = np.polyfit(PILOT_INDICES, ph, 1)[0]
        ph_res = float(np.std(ph - (sl * PILOT_INDICES
                                    + np.mean(ph - sl * PILOT_INDICES))))
        good = (med > 0.45 * pmag_ref) and (ph_res < 0.55)
        if good:
            pmag_ref = 0.9 * pmag_ref + 0.1 * med
        out.append((eq, good))
        drift += d
        pos += N_SYM
        idx += 1
        if n_syms is not None and idx >= n_syms:
            break
    return out


# ---------------------------------------------------------------------------
# Pre-emphasis gain curves
# ---------------------------------------------------------------------------
# All gains are in dB, indexed over DATA_INDICES subcarriers.
# The gain is applied to TX amplitudes; renormalization keeps total power constant.

def _sc_freqs(indices: np.ndarray) -> np.ndarray:
    """Convert subcarrier indices to frequencies in Hz."""
    return indices * (FS / N_FFT)


def _gain_flat(indices: np.ndarray) -> np.ndarray:
    """No pre-emphasis: uniform gain (0 dB)."""
    return np.zeros(len(indices))


def _gain_slope(indices: np.ndarray, db_per_oct: float) -> np.ndarray:
    """Linear slope in dB/octave relative to F_LOW."""
    freqs = _sc_freqs(indices)
    f_ref = F_LOW
    # log2(f/f_ref) octaves -> db_per_oct * log2(f/f_ref) dB
    with np.errstate(divide="ignore"):
        gain = db_per_oct * np.log2(np.maximum(freqs, f_ref) / f_ref)
    return gain


def _gain_butterworth_inverse(indices: np.ndarray, bw_hz: float = 12_000.0) -> np.ndarray:
    """Inverse of the 5th-order Butterworth LPF response (pre-emphasis that inverts the channel)."""
    sos = butter(5, bw_hz, btype="lowpass", fs=FS, output="sos")
    freqs = _sc_freqs(indices)
    _, h = sosfreqz(sos, worN=freqs, fs=FS)
    mag_db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-10))
    # Pre-emphasis = -H_channel (inverse): boost highs that are attenuated
    preemph = -mag_db
    # Clip to reasonable range: don't boost more than +18 dB to avoid clipping
    # (after renorm the relative differences matter, not absolute levels)
    preemph = np.clip(preemph, -18.0, 18.0)
    return preemph


def _gain_from_dpd_model(indices: np.ndarray) -> np.ndarray:
    """Pre-emphasis from the measured experiments/dpd/channel_model.json preemph_db table."""
    model_path = ROOT / "experiments" / "dpd" / "channel_model.json"
    with open(model_path) as f:
        mdl = json.load(f)
    model_freqs = np.array(mdl["H_freq"])
    model_preemph = np.array(mdl["preemph_db"])
    sc_freqs = _sc_freqs(indices)
    gain = np.interp(sc_freqs, model_freqs, model_preemph)
    # Clip to +/-12 dB
    gain = np.clip(gain, -12.0, 12.0)
    return gain


# ---------------------------------------------------------------------------
# Channel probe with pre-emphasis: get per-SC SNR after boosting TX
# ---------------------------------------------------------------------------
def _probe_snr_with_preemph(preemph_gain_db: np.ndarray,
                             cal_seeds=range(40, 52),
                             n_probe_syms: int = 60) -> np.ndarray:
    """
    Probe the channel SNR on DATA_INDICES with a given per-subcarrier pre-emphasis gain.
    preemph_gain_db: array of shape (len(DATA_INDICES),) in dB.

    The probe transmits QPSK on all data subcarriers, but scales each SC by
    the pre-emphasis gain (in amplitude). Renormalizes the full frame to the
    same RMS as the baseline (constant total TX power).

    The demod equalizes out the channel H (which includes the pre-emphasis),
    so the SNR we measure is the post-equalization SNR, which equals:
        SNR_probed(k) = SNR_baseline(k) * (preemph_lin(k))^2 * P_budget
    where P_budget < 1 for the renormalization factor.

    Actually: we measure it empirically by comparing equalized values to known TX.
    """
    # Convert dB gain to linear amplitude scale per subcarrier
    preemph_lin = 10.0 ** (preemph_gain_db / 20.0)  # amplitude scale

    rng = np.random.default_rng(12345)
    qpsk = CONST[2]
    known_idx = rng.integers(0, 4, size=(n_probe_syms, len(DATA_INDICES)))
    tx_data = qpsk[known_idx]

    pre = hc.make_preamble(0.25)
    ref_td = [_osym(_ref_fd()) for _ in range(N_REF_SYMS)]

    data_td = []
    for s in range(n_probe_syms):
        fd = np.zeros(N_FFT, dtype=complex)
        # Apply pre-emphasis: scale each data SC by preemph_lin
        fd[DATA_INDICES] = tx_data[s] * preemph_lin
        fd[PILOT_INDICES] = PILOT_PATTERN * PILOT_AMP
        data_td.append(_osym(fd))

    audio = _normalize(np.concatenate(
        [pre, np.concatenate(ref_td), np.concatenate(data_td), np.zeros(int(0.05 * FS))]))

    err = np.zeros(len(DATA_INDICES))
    sig = np.zeros(len(DATA_INDICES))
    for seed in cal_seeds:
        rx_audio, sr, _ = cs.full_chain(audio, "normal", "usb_soundcard", seed=seed)
        start = hc.find_preamble(rx_audio, 0.25)
        rx = np.asarray(rx_audio, dtype=np.float64)[start:]
        syms = _track_demod(rx, n_syms=n_probe_syms)
        for s_idx, (eq, good) in enumerate(syms):
            if not good:
                continue
            # eq is after channel equalization; tx_data[s_idx] was the original QPSK
            # but the channel + equalizer sees preemph_lin*qpsk as the "true" TX signal
            # After equalization by the channel H, we recover ~ preemph_lin * qpsk + noise
            # To get back to unit-power QPSK, divide by preemph_lin:
            ref0 = tx_data[s_idx]   # unit QPSK
            eq_normalized = eq / preemph_lin  # undo the pre-emphasis to compare to ref0
            alpha = np.vdot(ref0, eq_normalized) / np.vdot(ref0, ref0)
            if abs(alpha) < 1e-6:
                continue
            eq2 = eq_normalized / alpha
            err += np.abs(eq2 - ref0) ** 2
            sig += np.abs(ref0) ** 2

    snr_lin = sig / np.maximum(err, 1e-12)
    return 10.0 * np.log10(np.maximum(snr_lin, 1e-9))


def _bit_loading_from_snr(snr_db: np.ndarray, gap_db: float = 9.0,
                           max_bps: int = 4) -> np.ndarray:
    gamma = 10 ** (gap_db / 10.0)
    snr_lin = 10 ** (snr_db / 10.0)
    b = np.log2(1.0 + snr_lin / gamma)
    out = np.zeros(len(b), dtype=int)
    out[b >= 1.0] = 1
    out[b >= 2.3] = 2
    out[b >= 4.3] = 4
    out[b >= 6.3] = 6
    return np.minimum(out, max_bps)


# ---------------------------------------------------------------------------
# Build a scheme for a given pre-emphasis curve
# ---------------------------------------------------------------------------
class PreemphScheme:
    """OFDM scheme with per-subcarrier pre-emphasis pre-computed at init."""

    def __init__(self, name: str, preemph_gain_db: np.ndarray,
                 snr_db: np.ndarray, gap_db: float = 9.0, max_bps: int = 4):
        self.name = name
        self._preemph_db = preemph_gain_db
        self._preemph_lin = 10.0 ** (preemph_gain_db / 20.0)  # amplitude
        self._snr_db = snr_db

        self._bit_loading = _bit_loading_from_snr(snr_db, gap_db=gap_db, max_bps=max_bps)
        self._active = self._bit_loading > 0
        self._active_data_sc = DATA_INDICES[self._active]
        self._active_bps = self._bit_loading[self._active]
        self._active_mask = self._active
        self._active_preemph = self._preemph_lin[self._active]
        self._bits_per_sym = int(np.sum(self._active_bps))

        if self._bits_per_sym == 0:
            self.gross_bps = 0.0
        else:
            # Estimate gross_bps from a dummy modulate
            dummy = self.modulate(np.zeros(4000, dtype=np.uint8))
            self.gross_bps = float(4000) / (len(dummy) / FS)

        self.erasure_fn = None

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        bits = np.asarray(bits, dtype=np.uint8)
        total = len(bits)
        if self._bits_per_sym == 0:
            # Degenerate: no active carriers, send silence
            n_syms = 1
        else:
            n_syms = max(1, int(np.ceil(total / self._bits_per_sym)))

        pre = hc.make_preamble(0.25)
        ref_td = [_osym(_ref_fd()) for _ in range(N_REF_SYMS)]

        data_td = []
        bi = 0
        for _ in range(n_syms):
            fd = np.zeros(N_FFT, dtype=complex)
            for sc, bps, amp in zip(self._active_data_sc, self._active_bps, self._active_preemph):
                idx = 0
                for _k in range(bps):
                    bit = int(bits[bi]) if bi < total else 0
                    bi += 1
                    idx = (idx << 1) | bit
                fd[sc] = CONST[bps][idx] * amp  # pre-emphasis applied here
            fd[PILOT_INDICES] = PILOT_PATTERN * PILOT_AMP
            data_td.append(_osym(fd))

        audio = np.concatenate([pre, np.concatenate(ref_td), np.concatenate(data_td),
                                 np.zeros(int(0.05 * FS))])
        return _normalize(audio)

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float64)
        start = hc.find_preamble(audio, 0.25)
        if start >= len(audio) - (N_REF_SYMS + 1) * N_SYM:
            return np.zeros(0, dtype=np.uint8)
        rx = audio[start:]
        syms = _track_demod(rx)

        out_bits = []
        for eq, good in syms:
            eq_active = eq[self._active_mask]
            for k, (bps, amp) in enumerate(zip(self._active_bps, self._active_preemph)):
                # Channel equalizer has divided by the channel H; the pre-emphasis
                # was part of the transmitted signal, so the equalized value is
                # amp * CONST[bps][true_idx] + noise/H.
                # Undo pre-emphasis before nearest-neighbor decode:
                eq_k = eq_active[k] / amp if amp > 1e-6 else eq_active[k]
                const = CONST[bps]
                idx = int(np.argmin(np.abs(eq_k - const) ** 2))
                out_bits.append(BITPAT[bps][idx])
        if not out_bits:
            return np.zeros(0, dtype=np.uint8)
        return np.concatenate(out_bits).astype(np.uint8)


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------
CURVES = [
    ("flat",            lambda idx: _gain_flat(idx)),
    ("slope_3dBperoct", lambda idx: _gain_slope(idx, 3.0)),
    ("slope_6dBperoct", lambda idx: _gain_slope(idx, 6.0)),
    ("butter_inverse",  lambda idx: _gain_butterworth_inverse(idx)),
    ("dpd_model",       lambda idx: _gain_from_dpd_model(idx)),
]


def run_sweep(n_seeds_sweep: int = 8, n_seeds_final: int = 12):
    """Run the full D1 pre-emphasis sweep and return a results dict."""
    results = {}
    sweep_results = []

    print("=== D1 Pre-emphasis Sweep ===")
    print(f"Subcarriers: {len(DATA_INDICES)} data, {len(PILOT_INDICES)} pilots")
    print(f"SC range: {SC_LOW}..{SC_HIGH}  ({SC_LOW*FS/N_FFT:.0f}..{SC_HIGH*FS/N_FFT:.0f} Hz)")

    # ---- First probe SNR for each curve (once, expensive) ----
    probed = {}
    for curve_name, gain_fn in CURVES:
        gain_db = gain_fn(DATA_INDICES)
        print(f"\n[probe] {curve_name}: gain range [{gain_db.min():.1f}, {gain_db.max():.1f}] dB")
        snr_db = _probe_snr_with_preemph(gain_db)
        bl = _bit_loading_from_snr(snr_db, gap_db=GAP_DB, max_bps=MAX_BPS)
        hist = {b: int(np.sum(bl == b)) for b in (0, 1, 2, 4, 6)}
        bits_per_sym = int(np.sum(bl))
        print(f"         SNR med={np.median(snr_db):.1f} dB  bits/sym={bits_per_sym}  hist={hist}")
        probed[curve_name] = (gain_db, snr_db, bl, bits_per_sym)

    # ---- Sweep eval (n_seeds_sweep) ----
    print("\n--- Sweep evaluation ---")
    sweep_data = []
    for curve_name, gain_fn in CURVES:
        gain_db, snr_db, bl, bits_per_sym = probed[curve_name]
        if bits_per_sym == 0:
            print(f"[skip] {curve_name}: no active carriers")
            continue

        scheme = PreemphScheme(curve_name, gain_db, snr_db, gap_db=GAP_DB, max_bps=MAX_BPS)

        # Sanity gate
        sanity = dd.sanity_no_channel(scheme)
        print(f"[sanity] {curve_name}: BER={sanity:.2e}", end="")
        if sanity > 5e-3:
            print("  FAIL — skipping this curve")
            sweep_data.append({
                "curve": curve_name, "sanity_ber": sanity, "status": "sanity_fail"
            })
            continue
        print("  OK")

        out = dd.evaluate_dual(scheme, n_seeds=n_seeds_sweep, do_sanity=False)
        out["sanity_ber"] = sanity
        out["bits_per_sym"] = bits_per_sym
        out["gain_db_min"] = float(gain_db.min())
        out["gain_db_max"] = float(gain_db.max())
        out["snr_db_median"] = float(np.median(snr_db))
        out["bit_loading_hist"] = {b: int(np.sum(bl == b)) for b in (0, 1, 2, 4, 6)}
        print(dd.fmt(out))
        sweep_data.append(out)

    # ---- Pick best curve by sim net_bps ----
    valid = [d for d in sweep_data if "sim" in d and d["sim"]["net_bps"] > 0]
    if not valid:
        print("\nERROR: No valid curves found!")
        best_curve_name = "flat"
    else:
        best = max(valid, key=lambda d: d["sim"]["net_bps"])
        best_curve_name = best["name"]
        print(f"\nBest curve by sim net_bps: {best_curve_name}")

    # ---- Final eval on best curve (n_seeds_final) ----
    print(f"\n--- Final eval: {best_curve_name} (n_seeds={n_seeds_final}) ---")
    gain_fn_map = dict(CURVES)
    gain_db_final = gain_fn_map[best_curve_name](DATA_INDICES)
    _, snr_db_final, _, _ = probed[best_curve_name]
    final_scheme = PreemphScheme(best_curve_name + "_final", gain_db_final,
                                  snr_db_final, gap_db=GAP_DB, max_bps=MAX_BPS)

    sanity_final = dd.sanity_no_channel(final_scheme)
    print(f"[sanity] final: BER={sanity_final:.2e}", end="")
    if sanity_final > 5e-3:
        print("  FAIL")
    else:
        print("  OK")

    final_out = dd.evaluate_dual(final_scheme, n_seeds=n_seeds_final, do_sanity=False)
    final_out["sanity_ber"] = sanity_final
    bl_final = _bit_loading_from_snr(snr_db_final, gap_db=GAP_DB, max_bps=MAX_BPS)
    final_out["bits_per_sym"] = int(np.sum(bl_final))
    final_out["gain_db_min"] = float(gain_db_final.min())
    final_out["gain_db_max"] = float(gain_db_final.max())
    final_out["snr_db_median"] = float(np.median(snr_db_final))
    final_out["bit_loading_hist"] = {b: int(np.sum(bl_final == b)) for b in (0, 1, 2, 4, 6)}
    print(dd.fmt(final_out))

    # ---- Baseline reference from C4 (via saved references) ----
    # C4 reference values (from the task spec)
    c4_sim_net = 3968.0
    c4_real_net = 233.0
    c4_real_survival = 0.0  # P_full=0

    # Accept bar check
    sim_net = final_out["sim"]["net_bps"]
    real_net = final_out["real"]["net_bps"]
    real_survival = final_out["real"]["P_full"]

    sim_bar_met = sim_net >= 4400.0
    real_bar_met = real_net >= 256.0 or real_survival > c4_real_survival

    print(f"\n=== VERDICT ===")
    print(f"C4 baseline: sim={c4_sim_net:.0f} bps, real={c4_real_net:.0f} bps, survival={c4_real_survival:.1f}")
    print(f"D1 final:    sim={sim_net:.0f} bps, real={real_net:.0f} bps, survival={real_survival:.2f}")
    print(f"SIM bar (>=4400): {'PASS' if sim_bar_met else 'FAIL'}  ({sim_net:.0f} vs 4400)")
    print(f"REAL bar (>=256 or survival>0): {'PASS' if real_bar_met else 'FAIL'}  ({real_net:.0f} vs 256, surv={real_survival:.2f})")

    if sim_bar_met and real_bar_met:
        verdict = "ACCEPT"
    elif sim_bar_met or real_bar_met:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "REJECT"
    print(f"OVERALL: {verdict}")

    # ---- Assemble final results dict ----
    results = {
        "experiment": "d1_preemphasis",
        "hypothesis": "D1: Channel-matched pre-emphasis / spectral shaping",
        "curves_tried": sweep_data,
        "best_curve": best_curve_name,
        "final_eval": final_out,
        "c4_reference": {
            "sim_net_bps": c4_sim_net,
            "real_net_bps": c4_real_net,
            "real_p_full": c4_real_survival,
        },
        "accept_bars": {
            "sim_net_bps_threshold": 4400.0,
            "real_net_bps_threshold": 256.0,
            "real_survival_threshold": ">0",
        },
        "bars_met": {
            "sim": sim_bar_met,
            "real": real_bar_met,
        },
        "verdict": verdict,
        "verdict_explanation": (
            "Pre-emphasis boosts high-frequency subcarriers to flatten post-channel SNR. "
            "The channel probe is re-run with the pre-emphasis in the TX path, giving a "
            "new per-SC SNR estimate that the bit-loader uses to assign bits. "
            "Total TX power is held constant by RMS normalization after pre-emphasis."
        ),
    }
    return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds_sweep", type=int, default=8)
    ap.add_argument("--seeds_final", type=int, default=12)
    args = ap.parse_args()

    results = run_sweep(n_seeds_sweep=args.seeds_sweep, n_seeds_final=args.seeds_final)

    out_dir = ROOT / "experiments" / "deepdive2" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "d1.json"

    # Make JSON serializable
    def _make_serializable(obj):
        if isinstance(obj, dict):
            return {k: _make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_make_serializable(v) for v in obj]
        elif isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return [_make_serializable(v) for v in obj.tolist()]
        return obj

    results_serial = _make_serializable(results)
    with open(out_path, "w") as f:
        json.dump(results_serial, f, indent=2)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
