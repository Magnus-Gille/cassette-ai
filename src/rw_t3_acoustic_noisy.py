"""rw_t3_acoustic_noisy.py — T3: Acoustic far-noisy sweep + repetition coding.

Sweeps ambient SNR and distance through the acoustic_far_noisy path (P4),
evaluating both reference modems (BFSK/B0 and MFSK-32), then tests a simple
3x repetition-coded variant of MFSK to measure how much it extends the viable
envelope.

Key implementation notes:
- BFSK (5.68s audio per trial) is slow; we sample it at a reduced grid since
  it is observed to collapse completely (BER~0.495, corr_peak<0.3) even at
  the best acoustic conditions (0.5m, 30dB SNR). The result is documented.
- MFSK-32 (1.54s audio) is the focus of the sweep.
- 3x repetition adds majority-vote redundancy across 3 consecutive copies.

Saves full results to RESULTS/data/rw_acoustic_far_noisy.json.
Optional plot: RESULTS/plots/rw_acoustic_far_noisy.png.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Any

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import signal as sg

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import realworld_channels as rw   # noqa: E402
import hyp_common as hc           # noqa: E402
import capture_scenarios as cscn  # noqa: E402

DATA_DIR  = ROOT / "RESULTS" / "data"
PLOTS_DIR = ROOT / "RESULTS" / "plots"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

FS = 48_000

# ---------------------------------------------------------------------------
# Repetition-coded scheme wrapper
# ---------------------------------------------------------------------------

class RepetitionScheme:
    """Wraps an existing Scheme with N-way repetition + majority vote.

    Each payload bit is transmitted N times consecutively; decoding takes the
    majority across the N copies. gross_bps is reduced by factor N.
    """

    def __init__(self, inner, reps: int = 3):
        self._inner = inner
        self._reps = reps
        self.name = f"{inner.name}_rep{reps}"
        self.gross_bps = inner.gross_bps / reps

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        """Emit N consecutive copies of the payload bits as one audio stream."""
        bits = np.asarray(bits, dtype=np.uint8)
        repeated = np.tile(bits, self._reps)
        return self._inner.modulate(repeated)

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Demodulate all N copies and majority-vote."""
        raw = np.asarray(self._inner.demodulate(audio, sr), dtype=np.uint8)
        n_bits_per_rep = len(raw) // self._reps
        if n_bits_per_rep == 0:
            return raw
        copies = []
        for r in range(self._reps):
            start = r * n_bits_per_rep
            stop = start + n_bits_per_rep
            copies.append(raw[start:stop])
        stack = np.stack(copies, axis=0)  # (reps, bits)
        votes = np.sum(stack, axis=0)
        return (votes > self._reps / 2).astype(np.uint8)


# ---------------------------------------------------------------------------
# Custom acoustic path with configurable distance and SNR
# ---------------------------------------------------------------------------

def _acoustic_path(audio48k: np.ndarray, seed: int,
                   snr_db: float, distance_m: float) -> tuple[np.ndarray, int]:
    """P4 variant with configurable distance and SNR.

    Based on realworld_channels.acoustic_far_noisy with the key parameters
    exposed. RT60 scales with distance (larger reverberant field at range).
    """
    y = rw.tape_core(audio48k, seed)
    y = rw.speaker_response(y, kind="laptop")
    y = rw.soft_clip(y, k=1.2)
    # RT60 grows with distance: ~0.375s at 0.5m, ~0.4s at 1.0m, ~0.55s at 2.0m
    rt60 = 0.25 + 0.15 * distance_m
    y = rw.room_reverb(y, rt60=rt60, distance_m=distance_m, seed=seed)
    y = rw.distance_atten(y, distance_m=distance_m)
    y = rw.mic_response(y, kind="phone_recorder")
    y = rw.ambient_noise(y, snr_db=snr_db, kind="babble", seed=seed)
    y = cscn._agc(y, target_rms=0.2, attack=0.005, release=0.20)
    return y.astype(np.float32), FS


# ---------------------------------------------------------------------------
# Cell evaluator
# ---------------------------------------------------------------------------

def _evaluate_cell(scheme, snr_db: float, distance_m: float,
                   n_seeds: int, payload_bits: int) -> dict[str, Any]:
    """Evaluate one (scheme, snr, distance) cell."""
    bers, cleans, peaks = [], [], []
    for seed in range(n_seeds):
        tx_bits = hc._random_bits(payload_bits, seed)
        audio = np.asarray(scheme.modulate(tx_bits), dtype=np.float32)
        rx_audio, sr = _acoustic_path(audio, seed, snr_db=snr_db,
                                      distance_m=distance_m)
        rx_bits = np.asarray(scheme.demodulate(rx_audio, sr), dtype=np.uint8)
        ber = hc._ber(tx_bits, rx_bits)
        bers.append(ber)
        cleans.append(ber == 0.0)
        peaks.append(rw._corr_peak(rx_audio))

    return {
        "snr_db": float(snr_db),
        "distance_m": float(distance_m),
        "raw_bit_error_rate": float(np.mean(bers)),
        "clean_decode_prob": float(np.mean(cleans)),
        "corr_peak_mean": float(np.mean(peaks)),
        "corr_peak_min": float(np.min(peaks)),
        "per_seed_ber": [float(x) for x in bers],
        "per_seed_clean": [bool(x) for x in cleans],
        "per_seed_corr_peak": [float(x) for x in peaks],
        "n_seeds": n_seeds,
        "payload_bits": payload_bits,
    }


# ---------------------------------------------------------------------------
# Cliff detection
# ---------------------------------------------------------------------------

def find_cliff(scheme_results: list[dict], threshold: float = 0.5) -> dict:
    """Find the minimum viable SNR per distance (clean_decode_prob >= threshold)."""
    by_dist: dict[float, list[dict]] = {}
    for r in scheme_results:
        by_dist.setdefault(r["distance_m"], []).append(r)
    cliffs = {}
    for dist, rows in sorted(by_dist.items()):
        viable = [r for r in rows if r["clean_decode_prob"] >= threshold]
        if viable:
            min_snr = min(r["snr_db"] for r in viable)
            cliffs[f"{dist:.1f}m"] = {"min_viable_snr_db": min_snr,
                                       "viable_cells": len(viable)}
        else:
            cliffs[f"{dist:.1f}m"] = {"min_viable_snr_db": None,
                                       "viable_cells": 0,
                                       "note": "FAILS everywhere"}
    return cliffs


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def make_plot(all_results: dict[str, list[dict]], out_path: pathlib.Path):
    """clean_decode_prob vs ambient SNR, faceted by distance."""
    dist_vals = sorted({r["distance_m"] for rows in all_results.values()
                        for r in rows})
    fig, axes = plt.subplots(1, len(dist_vals), figsize=(14, 4.5), sharey=True)
    if len(dist_vals) == 1:
        axes = [axes]

    colors = {
        "bfsk_b0":       "#1f77b4",
        "mfsk32":        "#d62728",
        "bfsk_b0_rep3":  "#aec7e8",
        "mfsk32_rep3":   "#ff9f00",
    }
    markers = {
        "bfsk_b0":       "o",
        "mfsk32":        "s",
        "bfsk_b0_rep3":  "o",
        "mfsk32_rep3":   "s",
    }
    linestyles = {
        "bfsk_b0":       "-",
        "mfsk32":        "-",
        "bfsk_b0_rep3":  "--",
        "mfsk32_rep3":   "--",
    }

    for ax_idx, dist in enumerate(dist_vals):
        ax = axes[ax_idx]
        ax.set_title(f"Distance = {dist} m", fontsize=10)
        ax.set_xlabel("Ambient SNR (dB)", fontsize=9)
        ax.set_ylim(-0.05, 1.05)
        ax.axhline(0.5, color="gray", linestyle=":", linewidth=0.8)
        ax.grid(True, alpha=0.3)
        ax.set_xticks(sorted({r["snr_db"] for rows in all_results.values()
                              for r in rows if r["distance_m"] == dist}))

        for sname, scheme_results in all_results.items():
            rows = sorted(
                [r for r in scheme_results if r["distance_m"] == dist],
                key=lambda x: x["snr_db"]
            )
            if not rows:
                continue
            snr_vals = [r["snr_db"] for r in rows]
            prob_vals = [r["clean_decode_prob"] for r in rows]
            ax.plot(snr_vals, prob_vals,
                    linestyles.get(sname, "-") + markers.get(sname, "o"),
                    color=colors.get(sname, "gray"),
                    label=sname, linewidth=1.8, markersize=5)

        if ax_idx == 0:
            ax.set_ylabel("clean_decode_prob", fontsize=9)
        ax.legend(fontsize=7, loc="upper left")

    fig.suptitle(
        "T3: Acoustic Far-Noisy — clean_decode_prob vs Ambient SNR\n"
        "(babble noise, phone recorder mic 250–7500 Hz, 3× rep-coding variants)",
        fontsize=10
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> dict[str, Any]:
    # ---- sweep grid ----
    # BFSK is 5.68s/trial so we sample it at one representative point only
    # (already known to collapse completely; full grid would take ~2 hours).
    # MFSK is 1.54s/trial and gets the full grid.
    MFSK_SNR    = [30, 22, 15, 10, 5]   # dB
    MFSK_DIST   = [0.5, 1.0, 2.0]       # m
    BFSK_SNR    = [30, 15, 5]            # dB (sampled — all expected to fail)
    BFSK_DIST   = [0.5, 1.0, 2.0]       # m
    N_SEEDS     = 12
    PAYLOAD_BITS = 2000

    print("=" * 70)
    print("T3: acoustic_far_noisy sweep")
    print(f"  MFSK grid : {MFSK_SNR} dB x {MFSK_DIST} m")
    print(f"  BFSK grid : {BFSK_SNR} dB x {BFSK_DIST} m (sampled)")
    print(f"  n_seeds={N_SEEDS}  payload_bits={PAYLOAD_BITS}")
    print("=" * 70)

    base_modems = rw.build_reference_modems(PAYLOAD_BITS)
    bfsk = base_modems["bfsk_b0"]
    mfsk = base_modems["mfsk32"]
    mfsk_rep3 = RepetitionScheme(mfsk, reps=3)
    bfsk_rep3 = RepetitionScheme(bfsk, reps=3)

    all_results: dict[str, list[dict]] = {}
    t_total = time.time()

    # ---- MFSK-32 sweep ----
    for sname, scheme, snr_grid, dist_grid in [
        ("mfsk32",      mfsk,      MFSK_SNR, MFSK_DIST),
        ("mfsk32_rep3", mfsk_rep3, MFSK_SNR, MFSK_DIST),
        ("bfsk_b0",     bfsk,      BFSK_SNR, BFSK_DIST),
        ("bfsk_b0_rep3",bfsk_rep3, BFSK_SNR, BFSK_DIST),
    ]:
        print(f"\n--- Scheme: {sname}  gross_bps={scheme.gross_bps:.0f} ---")
        rows = []
        for dist in dist_grid:
            for snr in snr_grid:
                t0 = time.time()
                res = _evaluate_cell(scheme, snr_db=snr,
                                     distance_m=dist,
                                     n_seeds=N_SEEDS,
                                     payload_bits=PAYLOAD_BITS)
                res["scheme"] = sname
                rows.append(res)
                print(
                    f"  dist={dist:.1f}m snr={snr:2d}dB  "
                    f"raw_ber={res['raw_bit_error_rate']:.3f}  "
                    f"clean_P={res['clean_decode_prob']:.2f}  "
                    f"corr={res['corr_peak_mean']:.3f}  ({time.time()-t0:.1f}s)"
                )
        all_results[sname] = rows

    print(f"\nTotal time: {time.time()-t_total:.1f}s")
    return all_results, N_SEEDS, PAYLOAD_BITS


if __name__ == "__main__":
    all_results, N_SEEDS, PAYLOAD_BITS = run()

    # Breakdown cliffs
    cliffs: dict[str, Any] = {}
    for sname, rows in all_results.items():
        cliffs[sname] = find_cliff(rows, threshold=0.5)

    print("\n=== BREAKDOWN CLIFF (clean_decode_prob >= 0.5) ===")
    for sname, cliff in cliffs.items():
        print(f"  {sname}:")
        for dist_key, info in cliff.items():
            mvs = info.get("min_viable_snr_db")
            if mvs is not None:
                print(f"    {dist_key}: min viable SNR = {mvs} dB")
            else:
                print(f"    {dist_key}: FAILS everywhere")

    # Projections for viable cells
    gross_map = {
        "mfsk32":       rw.REFERENCE_MODEMS["mfsk32"].gross_bps,
        "mfsk32_rep3":  rw.REFERENCE_MODEMS["mfsk32"].gross_bps / 3,
        "bfsk_b0":      rw.REFERENCE_MODEMS["bfsk_b0"].gross_bps,
        "bfsk_b0_rep3": rw.REFERENCE_MODEMS["bfsk_b0"].gross_bps / 3,
    }
    projections: dict[str, list[dict]] = {}
    for sname, rows in all_results.items():
        proj_rows = []
        for r in rows:
            try:
                p = hc.project_to_cassette(
                    raw_ber=r["raw_bit_error_rate"],
                    erasure_rate=0.0,
                    gross_bps=gross_map[sname],
                    payload_bytes=int(1.271e6),
                    target_P=0.95,
                )
                proj_rows.append({
                    "snr_db": r["snr_db"],
                    "distance_m": r["distance_m"],
                    "net_bps": p.get("net_bps"),
                    "MB_C90_stereo": p.get("MB_C90_stereo"),
                    "P_full": p.get("P_full"),
                })
            except Exception:
                proj_rows.append({
                    "snr_db": r["snr_db"],
                    "distance_m": r["distance_m"],
                    "net_bps": None,
                    "MB_C90_stereo": None,
                    "P_full": None,
                })
        projections[sname] = proj_rows

    # Save
    out = {
        "experiment": "T3_acoustic_far_noisy",
        "n_seeds": N_SEEDS,
        "payload_bits": PAYLOAD_BITS,
        "noise_kind": "babble",
        "tape_preset": "normal",
        "per_scheme": all_results,
        "breakdown_cliffs": cliffs,
        "projections": projections,
        "meta": {
            "bfsk_grid_note": (
                "BFSK sampled at 3 SNR levels x 3 distances (vs 5x3 for MFSK) "
                "because BFSK collapses completely (BER~0.495, corr_peak~0.28) "
                "even at best acoustic conditions (0.5m, 30dB). Confirmed by "
                "early partial run showing flat BER across all SNR levels."
            )
        },
    }

    out_path = DATA_DIR / "rw_acoustic_far_noisy.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    make_plot(all_results, PLOTS_DIR / "rw_acoustic_far_noisy.png")
    print("Done.")
