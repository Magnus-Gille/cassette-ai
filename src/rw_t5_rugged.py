"""rw_t5_rugged.py — T5: Rugged Acoustic Mode for worst-case phone-mic paths.

Designs and tests a "RUGGED ACOUSTIC MODE" that is specifically tuned for:
  - Narrowband voice-band tones (600-3000 Hz) — stays inside phone telephony band
  - Strong repetition FEC (3x or 5x majority vote) for burst-error resilience
  - Long/repeated chirp preamble (2x 0.5s) for robust sync acquisition
  - Amplitude normalisation in demod front-end (RMS normalization + bandpass)

Tests:
  1. P4 acoustic_far_noisy at SNR~12 dB, dist~1m (hard operating point)
  2. P5 bluetooth_hfp_narrow (3400 Hz lowpass + libopus voip 12k)

Reference baselines: bfsk_b0 and mfsk32 at the same paths.
Goal: clean_decode_prob >= 0.9 on a SMALL payload through paths where
standard modems fail.

SAVE results to RESULTS/data/rw_rugged_mode.json BEFORE returning.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import numpy as np
from scipy import signal

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import cassette_format as cf          # noqa: E402
import channel as ch                  # noqa: E402
import capture_scenarios as cscn      # noqa: E402
import cassette_e2e as e2e            # noqa: E402
import hyp_common as hc               # noqa: E402
import realworld_channels as rw       # noqa: E402

FS = 48_000
DATA_DIR  = ROOT / "RESULTS" / "data"
PLOTS_DIR = ROOT / "RESULTS" / "plots"

# ---------------------------------------------------------------------------
# Rugged mode design constants
# ---------------------------------------------------------------------------
# Tone band: 600–3000 Hz — stays inside phone telephony (300-3400 Hz) AND
# well inside phone recorder (250-7500 Hz). BFSK mark/space frequencies:
RUGGED_F0 = 750.0    # mark (1 bit)  — avoids 600 Hz mic rolloff floor
RUGGED_F1 = 2100.0   # space (0 bit) — well below 3400 Hz telephony cutoff
RUGGED_BAUD = 50     # symbols/second — 20ms symbol >> RT60=500ms reverb tail -> defeats ISI

# FEC: repetition code. Each info bit is sent N times; majority vote at RX.
# 3x → 33% code rate (gross->net factor 1/3)
# 5x → 20% code rate (gross->net factor 1/5)
RUGGED_REP = 3       # repetition factor (3 = majority-of-3)

# Preamble: a LONGER chirp (0.5s) repeated twice for robust correlation peak
# We generate a custom chirp that sits inside our narrower tone band.
RUGGED_PRE_F0   = 600.0
RUGGED_PRE_F1   = 3000.0
RUGGED_PRE_SECS = 1.0   # single long chirp (no ambiguous repetitions; longer = more robust)
RUGGED_PRE_REPS = 1     # no repetition — unique template -> unambiguous timing


# ---------------------------------------------------------------------------
# Preamble helpers (custom narrowband chirp, wider/longer than hc default)
# ---------------------------------------------------------------------------

def _make_rugged_preamble(
    f0: float = RUGGED_PRE_F0,
    f1: float = RUGGED_PRE_F1,
    seconds: float = RUGGED_PRE_SECS,
    reps: int = RUGGED_PRE_REPS,
) -> np.ndarray:
    """Narrowband chirp (f0->f1 Hz) repeated `reps` times. float32 @48k."""
    n = int(seconds * FS)
    t = np.arange(n, dtype=np.float64) / FS
    seg = signal.chirp(t, f0=f0, f1=f1, t1=seconds, method="linear")
    seg = (0.65 * seg).astype(np.float32)
    return np.tile(seg, reps).astype(np.float32)


def _find_rugged_preamble(
    audio: np.ndarray,
    f0: float = RUGGED_PRE_F0,
    f1: float = RUGGED_PRE_F1,
    seconds: float = RUGGED_PRE_SECS,
    reps: int = RUGGED_PRE_REPS,
) -> tuple[int, float]:
    """Find the end of the rugged preamble via cross-correlation.

    Returns (data_start_sample, normalised_corr_peak).

    Strategy: use a SINGLE chirp segment as the template (the repeated
    preamble contains `reps` copies of this segment). The last segment ends
    at the preamble/data boundary, so the correlation peak at position p
    (= start of the matched segment) places the data start at p + seg_len.

    This is more robust than correlating with the full preamble because:
    - Reverb decorrelates the received audio from any deterministic template
      over long durations. A single 0.5s chirp is short enough to survive.
    - Codec algorithmic delays (libopus: ~20-40ms) shift the whole signal
      uniformly; the single-segment finder absorbs this offset correctly.
    - The repeated preamble is still useful acoustically (builds up SNR in
      the receiver ear / AGC), but only one segment is needed for timing.

    When the reverb is so heavy that the correlation peak is very low
    (< ~0.1), the timing may still be within ±1 symbol of correct, which
    the repetition FEC absorbs.
    """
    audio = np.asarray(audio, dtype=np.float64)
    n_seg = int(seconds * FS)
    t = np.arange(n_seg, dtype=np.float64) / FS
    template = signal.chirp(t, f0=f0, f1=f1, t1=seconds, method="linear") * 0.65

    if len(audio) < n_seg:
        return 0, 0.0

    corr = signal.correlate(audio, template, mode="valid")
    denom = (np.linalg.norm(template) * np.sqrt(n_seg)) * (np.std(audio) + 1e-12)
    norm_corr = np.abs(corr) / (denom + 1e-12)

    # Find the best-matching segment anywhere in the audio.
    # peak_idx is the START of the best-matching segment; data starts one
    # segment later (at peak_idx + n_seg), which is the end of that segment.
    peak_idx = int(np.argmax(norm_corr))
    peak_val = float(norm_corr[peak_idx])

    data_start = peak_idx + n_seg
    data_start = min(data_start, len(audio))

    return data_start, peak_val


# ---------------------------------------------------------------------------
# RX front-end normalisation
# ---------------------------------------------------------------------------

def _rx_normalise(audio: np.ndarray, f_low: float = 550.0,
                   f_high: float = 3100.0) -> np.ndarray:
    """Amplitude normalisation + bandpass for rugged demod front-end.

    1. Bandpass to the signal band (removes out-of-band noise + DC).
    2. RMS normalisation to a fixed level (accounts for AGC residual variance).
    3. Soft-limit to [-1, 1] to handle occasional overdriven samples.
    """
    y = np.asarray(audio, dtype=np.float64)
    # Bandpass: keep signal band only
    nyq = FS / 2.0
    f_low_c  = max(f_low,  1.0)
    f_high_c = min(f_high, nyq * 0.999)
    sos = signal.butter(4, [f_low_c / nyq, f_high_c / nyq],
                        btype="bandpass", output="sos")
    y = signal.sosfiltfilt(sos, y)
    # RMS normalisation
    rms = float(np.sqrt(np.mean(y ** 2))) or 1e-9
    y = y / rms * 0.25
    # Soft clip to [-1, 1]
    y = np.clip(y, -1.0, 1.0)
    return y.astype(np.float32)


# ---------------------------------------------------------------------------
# Rugged BFSK Scheme (narrowband tones + repetition FEC + long preamble)
# ---------------------------------------------------------------------------

class RuggedBFSKScheme:
    """Rugged BFSK modem for worst-case phone-mic / acoustic paths.

    Design:
    - Two tones (750 Hz = mark, 2100 Hz = space), both inside 600–3000 Hz,
      which survives both phone recorder and telephony (300–3400 Hz) bands.
    - Wide symbol period (1/200 s = 5 ms) for high per-bit SNR via coherent
      integration. Each symbol integrates 240 samples @48k.
    - Repetition FEC: each info bit transmitted `rep` times; decoded by
      majority vote (handles up to (rep-1)//2 erroneous copies).
    - Long preamble (2 × 0.5 s narrowband chirp) for reliable sync even with
      reverb, babble noise, and codec distortion.
    - RX front-end: bandpass + RMS normalisation before demod.

    Demodulation: non-coherent energy detection — compute energy in a small
    band around each tone frequency per symbol window using the Goertzel
    algorithm (= one DFT bin), pick the higher energy.

    gross_bps accounts for preamble overhead; net_bps after FEC is
    gross_bps / rep.
    """

    def __init__(
        self,
        f_mark: float = RUGGED_F0,
        f_space: float = RUGGED_F1,
        baud: float = RUGGED_BAUD,
        rep: int = RUGGED_REP,
        pre_f0: float = RUGGED_PRE_F0,
        pre_f1: float = RUGGED_PRE_F1,
        pre_secs: float = RUGGED_PRE_SECS,
        pre_reps: int = RUGGED_PRE_REPS,
    ):
        self.f_mark  = f_mark
        self.f_space = f_space
        self.baud    = baud
        self.rep     = rep
        self.pre_f0  = pre_f0
        self.pre_f1  = pre_f1
        self.pre_secs = pre_secs
        self.pre_reps = pre_reps

        self.samples_per_sym = int(round(FS / baud))
        self._preamble = _make_rugged_preamble(pre_f0, pre_f1, pre_secs, pre_reps)
        self.erasure_fn = None
        self.name = (
            f"RuggedBFSK_f{int(f_mark)}-{int(f_space)}Hz"
            f"_{baud:.0f}baud_rep{rep}"
            f"_pre{pre_secs:.1f}sx{pre_reps}"
        )

    @property
    def gross_bps(self) -> float:
        """Gross info bits/s (payload+FEC bits per second of audio, preamble paid)."""
        # Use 2000 bits as representative payload (matches eval default).
        return self._compute_gross_bps(2000)

    def _compute_gross_bps(self, n_info_bits: int) -> float:
        n_tx_bits = n_info_bits * self.rep
        n_syms    = n_tx_bits
        total_samples = len(self._preamble) + n_syms * self.samples_per_sym
        dur = total_samples / FS
        return float(n_info_bits) / dur if dur > 0 else 0.0

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        """bits (uint8) -> float32 audio @48kHz, including rugged preamble."""
        bits = np.asarray(bits, dtype=np.uint8).ravel()
        n_info = len(bits)

        # Repetition encoding: each bit repeated `rep` times
        tx_bits = np.repeat(bits, self.rep).astype(np.uint8)

        N   = self.samples_per_sym
        t   = np.arange(N, dtype=np.float64) / FS
        mark_wave  = np.sin(2.0 * math.pi * self.f_mark  * t)
        space_wave = np.sin(2.0 * math.pi * self.f_space * t)

        n_syms = len(tx_bits)
        body   = np.empty(n_syms * N, dtype=np.float64)
        for i, b in enumerate(tx_bits):
            body[i * N:(i + 1) * N] = mark_wave if b else space_wave

        audio = np.concatenate([
            self._preamble.astype(np.float64),
            body,
        ]).astype(np.float32)

        peak = float(np.max(np.abs(audio))) or 1.0
        return (audio / peak * 0.70).astype(np.float32)

    def _goertzel_energy(self, frame: np.ndarray, freq: float) -> float:
        """Goertzel energy detector for `freq` Hz in `frame` @48k.

        Numerically identical to |DFT[k]|^2 at bin k = freq*N/FS.
        """
        N   = len(frame)
        k   = freq * N / FS
        w   = 2.0 * math.pi * k / N
        coeff = 2.0 * math.cos(w)
        s1 = 0.0
        s2 = 0.0
        for x in frame:
            s0 = float(x) + coeff * s1 - s2
            s2 = s1
            s1 = s0
        return s1 * s1 + s2 * s2 - coeff * s1 * s2

    def _goertzel_block(self, frames: np.ndarray, freq: float) -> np.ndarray:
        """Vectorised Goertzel over rows of `frames` (n_syms x N). Returns (n_syms,)."""
        N     = frames.shape[1]
        k     = freq * N / FS
        w     = 2.0 * math.pi * k / N
        coeff = 2.0 * math.cos(w)
        # Use matrix recurrence — equivalent to row-wise scalar Goertzel
        s1 = np.zeros(frames.shape[0], dtype=np.float64)
        s2 = np.zeros(frames.shape[0], dtype=np.float64)
        for n_idx in range(N):
            s0 = frames[:, n_idx] + coeff * s1 - s2
            s2 = s1
            s1 = s0
        return s1 ** 2 + s2 ** 2 - coeff * s1 * s2

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """audio,sr -> recovered info bits (uint8). Real sync, no oracle."""
        audio = np.asarray(audio, dtype=np.float32)

        # 1. RX front-end: bandpass + RMS normalise
        rx = _rx_normalise(audio, f_low=self.pre_f0 - 100, f_high=self.pre_f1 + 100)

        # 2. Find preamble
        data_start, _ = _find_rugged_preamble(
            rx, self.pre_f0, self.pre_f1, self.pre_secs, self.pre_reps
        )

        N = self.samples_per_sym
        data = rx[data_start:].astype(np.float64)
        n_complete = len(data) // N
        if n_complete == 0:
            return np.zeros(0, dtype=np.uint8)

        # 3. Stack symbol windows
        mat = data[:n_complete * N].reshape(n_complete, N)

        # 4. Non-coherent energy detection via vectorised Goertzel
        e_mark  = self._goertzel_block(mat, self.f_mark)
        e_space = self._goertzel_block(mat, self.f_space)
        rx_bits = (e_mark > e_space).astype(np.uint8)

        # 5. Repetition FEC: majority vote over groups of `rep` bits
        rep = self.rep
        n_groups = len(rx_bits) // rep
        if n_groups == 0:
            return np.zeros(0, dtype=np.uint8)
        votes = rx_bits[:n_groups * rep].reshape(n_groups, rep)
        info_bits = (votes.sum(axis=1) > rep // 2).astype(np.uint8)

        return info_bits


# ---------------------------------------------------------------------------
# Helper: compute corr_peak using rugged preamble
# ---------------------------------------------------------------------------

def _rugged_corr_peak(audio: np.ndarray, scheme: RuggedBFSKScheme) -> float:
    """Normalised peak of the rugged preamble cross-correlation in audio."""
    _, peak = _find_rugged_preamble(
        audio,
        scheme.pre_f0, scheme.pre_f1,
        scheme.pre_secs, scheme.pre_reps,
    )
    return float(peak)


# ---------------------------------------------------------------------------
# Evaluate rugged scheme through a path (mirrors rw.evaluate_realworld)
# but uses rugged_corr_peak for the sync metric
# ---------------------------------------------------------------------------

def evaluate_rugged_realworld(
    scheme: RuggedBFSKScheme,
    path_key: str,
    n_seeds: int = 12,
    payload_bits: int = 2000,
    **path_kwargs,
) -> dict:
    """Monte-Carlo the rugged scheme through a real-world path.

    Returns same metric family as rw.evaluate_realworld, but uses the
    rugged preamble's correlation peak for sync quality.
    """
    if path_key not in rw.PATHS:
        raise ValueError(f"Unknown path '{path_key}'. Choose from: {sorted(rw.PATHS)}")
    path_fn = rw.PATHS[path_key]

    bers:   list[float] = []
    peaks:  list[float] = []
    cleans: list[bool]  = []

    for seed in range(n_seeds):
        tx_bits = hc._random_bits(payload_bits, seed)
        audio   = np.asarray(scheme.modulate(tx_bits), dtype=np.float32)
        rx_audio, _ = path_fn(audio, seed, **path_kwargs)

        rx_bits = np.asarray(scheme.demodulate(rx_audio, 48000), dtype=np.uint8)
        ber     = hc._ber(tx_bits, rx_bits)
        bers.append(ber)
        cleans.append(ber == 0.0)
        peaks.append(_rugged_corr_peak(rx_audio, scheme))

    return {
        "name": scheme.name,
        "path_key": path_key,
        "path_kwargs": {k: (v if isinstance(v, (int, float, str, bool)) else str(v))
                        for k, v in path_kwargs.items()},
        "gross_bps": float(scheme.gross_bps),
        "raw_bit_error_rate": float(np.mean(bers)),
        "erasure_rate": 0.0,
        "clean_decode_prob": float(np.mean(cleans)),
        "corr_peak_mean": float(np.mean(peaks)),
        "corr_peak_min": float(np.min(peaks)),
        "corr_peak_std": float(np.std(peaks)),
        "per_seed_ber": [float(x) for x in bers],
        "per_seed_erasure": [0.0] * n_seeds,
        "per_seed_corr_peak": [float(x) for x in peaks],
        "per_seed_clean": [bool(x) for x in cleans],
        "n_seeds": int(n_seeds),
        "payload_bits": int(payload_bits),
        "tape_preset": "normal",
    }


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------

def run_experiment(n_seeds: int = 12, payload_bits: int = 2000) -> dict:
    """Run the full T5 rugged mode experiment.

    1. Build rugged scheme variants (rep=3 and rep=5, baud=50).
       Design rationale:
       - baud=50 -> 20ms symbols >> RT60=500ms reverb tail (defeats ISI)
       - tones at 750 Hz / 2100 Hz: inside both phone recorder (250-7500 Hz)
         AND BT telephony (300-3400 Hz) bands
       - rep=3 -> majority-of-3 vote, code rate 1/3
       - rep=5 -> majority-of-5 vote, code rate 1/5 (survives higher raw BER)
       - preamble: single unique 1.0s narrowband chirp (600->3000 Hz)
         single rep avoids timing ambiguity; longer = better corr SNR vs reverb
    2. Reference modems (bfsk_b0, mfsk32) on P4/P5 (baseline for comparison).
    3. Rugged schemes on P4 (SNR=12 dB babble, 1m) and P5 (BT HFP).
    4. Project to cassette capacity.
    """
    print("=" * 70)
    print("T5 — Rugged Acoustic Mode Experiment")
    print(f"n_seeds={n_seeds}, payload_bits={payload_bits}")
    print("=" * 70)

    # --- Build schemes ---
    rugged_rep3 = RuggedBFSKScheme(rep=3)
    rugged_rep5 = RuggedBFSKScheme(rep=5)
    ref_modems  = rw.REFERENCE_MODEMS  # bfsk_b0, mfsk32

    # --- Path configs ---
    # P4 at hard operating point: SNR=12 dB, dist=1m, babble noise
    p4_kwargs   = {"snr_db": 12.0, "noise_kind": "babble"}
    # P5: BT HFP narrowband (no extra kwargs)
    p5_kwargs   = {}

    all_results: dict = {
        "metadata": {
            "n_seeds": n_seeds,
            "payload_bits": payload_bits,
            "paths": {
                "P4_acoustic_far_noisy": {
                    "snr_db": 12.0,
                    "noise_kind": "babble",
                    "dist_m": 1.0,
                    "rt60": 0.5,
                    "description": "Speaker 1m away, reverb RT60=0.5s, babble noise SNR=12dB",
                },
                "P5_bluetooth_hfp": {
                    "description": "BT HFP: lowpass 3400Hz + libopus voip 12k roundtrip",
                },
            },
            "rugged_design": {
                "f_mark_hz":  RUGGED_F0,
                "f_space_hz": RUGGED_F1,
                "baud":       RUGGED_BAUD,
                "sym_period_ms": 1000.0 / RUGGED_BAUD,
                "rationale": "20ms symbol >> RT60=500ms reverb, 750/2100Hz inside both phone and BT bands",
                "pre_chirp_hz": [RUGGED_PRE_F0, RUGGED_PRE_F1],
                "pre_secs":   RUGGED_PRE_SECS,
                "pre_reps":   RUGGED_PRE_REPS,
                "pre_note": "single unique chirp (no repeated segments) for unambiguous timing",
            },
        },
        "reference_on_P4": {},
        "reference_on_P5": {},
        "rugged_on_P4":    {},
        "rugged_on_P5":    {},
        "projections":     {},
    }

    # --- Reference modems on P4 and P5 ---
    print("\n[Reference modems — P4 acoustic_far_noisy SNR=12dB]")
    for mname, scheme in ref_modems.items():
        t0 = time.time()
        res = rw.evaluate_realworld(scheme, "P4", n_seeds=n_seeds,
                                    payload_bits=payload_bits, **p4_kwargs)
        dt = time.time() - t0
        all_results["reference_on_P4"][mname] = res
        print(f"  {mname:25s}  gross={res['gross_bps']:.0f}bps  "
              f"BER={res['raw_bit_error_rate']:.3e}  "
              f"clean_P={res['clean_decode_prob']:.2f}  "
              f"corr_peak={res['corr_peak_mean']:.3f}  ({dt:.1f}s)")

    print("\n[Reference modems — P5 bluetooth_hfp_narrow]")
    for mname, scheme in ref_modems.items():
        t0 = time.time()
        res = rw.evaluate_realworld(scheme, "P5", n_seeds=n_seeds,
                                    payload_bits=payload_bits, **p5_kwargs)
        dt = time.time() - t0
        all_results["reference_on_P5"][mname] = res
        print(f"  {mname:25s}  gross={res['gross_bps']:.0f}bps  "
              f"BER={res['raw_bit_error_rate']:.3e}  "
              f"clean_P={res['clean_decode_prob']:.2f}  "
              f"corr_peak={res['corr_peak_mean']:.3f}  ({dt:.1f}s)")

    # --- Rugged schemes on P4 ---
    print("\n[Rugged schemes — P4 acoustic_far_noisy SNR=12dB]")
    for tag, scheme in [("rep3", rugged_rep3), ("rep5", rugged_rep5)]:
        t0 = time.time()
        res = evaluate_rugged_realworld(scheme, "P4", n_seeds=n_seeds,
                                        payload_bits=payload_bits, **p4_kwargs)
        dt = time.time() - t0
        all_results["rugged_on_P4"][tag] = res
        print(f"  {tag:25s}  gross={res['gross_bps']:.0f}bps  "
              f"BER={res['raw_bit_error_rate']:.3e}  "
              f"clean_P={res['clean_decode_prob']:.2f}  "
              f"corr_peak={res['corr_peak_mean']:.3f}  ({dt:.1f}s)")

    # --- Rugged schemes on P5 ---
    print("\n[Rugged schemes — P5 bluetooth_hfp_narrow]")
    for tag, scheme in [("rep3", rugged_rep3), ("rep5", rugged_rep5)]:
        t0 = time.time()
        res = evaluate_rugged_realworld(scheme, "P5", n_seeds=n_seeds,
                                        payload_bits=payload_bits, **p5_kwargs)
        dt = time.time() - t0
        all_results["rugged_on_P5"][tag] = res
        print(f"  {tag:25s}  gross={res['gross_bps']:.0f}bps  "
              f"BER={res['raw_bit_error_rate']:.3e}  "
              f"clean_P={res['clean_decode_prob']:.2f}  "
              f"corr_peak={res['corr_peak_mean']:.3f}  ({dt:.1f}s)")

    # --- Projections to cassette capacity ---
    print("\n[Cassette capacity projections (net_bps after FEC, P_full)]")
    for path_label, results_dict in [
        ("P4", {**all_results["reference_on_P4"], **all_results["rugged_on_P4"]}),
        ("P5", {**all_results["reference_on_P5"], **all_results["rugged_on_P5"]}),
    ]:
        for name, res in results_dict.items():
            proj = hc.project_to_cassette(
                raw_ber=res["raw_bit_error_rate"],
                erasure_rate=res["erasure_rate"],
                gross_bps=res["gross_bps"],
            )
            key = f"{name}@{path_label}"
            all_results["projections"][key] = proj
            print(f"  {key:40s}  net={proj['net_bps']:.1f}bps  "
                  f"P_full={proj['P_full']:.2f}  "
                  f"MB_C90={proj['MB_C90_stereo']:.3f}")

    return all_results


def make_plot(all_results: dict) -> pathlib.Path | None:
    """Bar chart comparing schemes across paths."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        path_pairs = [
            ("P4", "reference_on_P4", "rugged_on_P4", "acoustic_far_noisy (SNR=12dB, 1m)"),
            ("P5", "reference_on_P5", "rugged_on_P5", "bluetooth_hfp_narrow (libopus 12k)"),
        ]

        metrics = ["clean_decode_prob", "corr_peak_mean", "raw_bit_error_rate"]
        colors  = {"bfsk_b0": "#3498db", "mfsk32": "#e67e22",
                   "rep3": "#2ecc71", "rep5": "#27ae60"}

        for ax_i, (path_label, ref_key, rug_key, title) in enumerate(path_pairs):
            ax = axes[ax_i]
            ref_data = all_results.get(ref_key, {})
            rug_data = all_results.get(rug_key, {})
            combined = {**ref_data, **rug_data}

            labels = list(combined.keys())
            clean_probs = [combined[l]["clean_decode_prob"] for l in labels]
            corr_peaks  = [combined[l]["corr_peak_mean"]    for l in labels]

            x = np.arange(len(labels))
            w = 0.35
            c_list = [colors.get(l, "#95a5a6") for l in labels]

            ax.bar(x - w / 2, clean_probs, width=w, label="clean_decode_prob",
                   color=c_list, edgecolor="black", linewidth=0.5)
            ax.bar(x + w / 2, corr_peaks,  width=w, label="corr_peak_mean",
                   color=c_list, edgecolor="black", linewidth=0.5, alpha=0.6, hatch="//")
            ax.axhline(0.9, color="red",   linestyle="--", linewidth=1.5, label="P=0.9 target")
            ax.axhline(0.6, color="orange",linestyle=":",  linewidth=1.2, label="corr_peak floor")

            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=9)
            ax.set_ylim(0, 1.1)
            ax.set_title(title, fontsize=9)
            ax.set_ylabel("Probability / Normalised peak")
            ax.legend(fontsize=8)

        fig.suptitle("T5 Rugged Mode: clean_decode_prob + corr_peak vs reference modems",
                     fontsize=11)
        fig.tight_layout()

        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        plot_path = PLOTS_DIR / "rw_rugged_mode.png"
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)
        print(f"\nPlot saved: {plot_path}")
        return plot_path
    except Exception as exc:
        print(f"Warning: plot failed ({exc})")
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    N_SEEDS      = 12
    PAYLOAD_BITS = 2000

    results = run_experiment(n_seeds=N_SEEDS, payload_bits=PAYLOAD_BITS)

    # SAVE FIRST — ROBUSTNESS RULE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / "rw_rugged_mode.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2,
                  default=lambda o: (list(o) if hasattr(o, "__iter__") else str(o)))
    print(f"\nResults saved: {json_path}")

    # Optional plot
    make_plot(results)

    # --- Summary verdict ---
    print("\n" + "=" * 70)
    print("VERDICT SUMMARY")
    print("=" * 70)

    for path_label in ["P4", "P5"]:
        rug_key = f"rugged_on_{path_label}"
        print(f"\n  Path {path_label}:")
        for tag, res in results.get(rug_key, {}).items():
            proj_key = f"{tag}@{path_label}"
            proj = results["projections"].get(proj_key, {})
            print(f"    rugged-{tag:5s}  "
                  f"gross={res['gross_bps']:.0f}bps  "
                  f"net={proj.get('net_bps',0):.1f}bps  "
                  f"clean_P={res['clean_decode_prob']:.2f}  "
                  f"corr_peak={res['corr_peak_mean']:.3f}  "
                  f"BER={res['raw_bit_error_rate']:.3e}")

    print("\nDone.")
