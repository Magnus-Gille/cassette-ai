"""rw_t2_acoustic_close.py — T2: acoustic close-range sweep (phone mic at speaker).

Experiment: hold the phone right at the laptop/cassette-deck speaker in a quiet
room. We sweep two dimensions:
  1. Playback level / soft-clip drive (how hard the speaker is driven).
  2. Speaker-mic distance (0.05 m, 0.15 m, 0.30 m) via reverb distance + 1/r attenuation.

Both reference modems (bfsk_b0, mfsk32) are tested over every condition.

Key questions:
  - Does over-the-air into a phone mic decode at all at close range?
  - What are clean_decode_prob, corr_peak (sync acquisition under reverb+AGC)?
  - What is the min viable level / max survivable distance?
  - Which modem survives?

Outputs:
  RESULTS/data/rw_acoustic_close.json   — all results (SAVED BEFORE returning)
  RESULTS/plots/rw_acoustic_close.png   — heatmap / bar plots
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

# ---------------------------------------------------------------------------
# Path bootstrap (canonical for this repo)
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import realworld_channels as rw
import hyp_common as hc
import hyp_h2_mfsk as h2
import channel as ch
import capture_scenarios as cscn

from scipy import signal

FS = 48_000
DATA_DIR = ROOT / "RESULTS" / "data"
PLOT_DIR = ROOT / "RESULTS" / "plots"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PLOT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Experiment parameters
# ---------------------------------------------------------------------------
N_SEEDS = 12
PAYLOAD_BITS = 2000

# Soft-clip drive values (k parameter in tanh(k*x)/tanh(k)).
# k=1.2 = mild (normal speaker drive, baseline P3 value)
# k=2.5 = moderate clipping
# k=5.0 = heavy clipping (speaker pushed hard)
DRIVE_LEVELS = [0.8, 1.2, 2.5, 5.0]

# Physical distances [m] — determines reverb direct/reverb ratio and 1/r attenuation.
# 0.05 m = phone literally touching / 5 cm from speaker cone
# 0.15 m = baseline (default P3)
# 0.30 m = 30 cm, still "close" but direct signal weakened
DISTANCES_M = [0.05, 0.15, 0.30]

# RT60 for a small quiet room (fixed across all close conditions).
RT60 = 0.25  # seconds


# ---------------------------------------------------------------------------
# Custom path: acoustic_close_sweep
#   Parameterized by drive and distance (the two sweep dimensions).
#   Everything else identical to rw.acoustic_close_quiet (P3).
# ---------------------------------------------------------------------------

def acoustic_close_sweep(audio48k: np.ndarray, seed: int = 0, *,
                          drive: float = 1.2,
                          distance_m: float = 0.15) -> tuple:
    """Acoustic close path with configurable drive and distance.

    Mirrors rw.acoustic_close_quiet (P3) exactly but exposes drive and
    distance_m as parameters for the sweep.

    Chain: tape_core -> speaker_response -> soft_clip(drive) ->
           room_reverb(RT60, distance_m) -> distance_atten(distance_m) ->
           mic_response(phone_recorder) -> ambient_noise(30dB, pink) -> AGC
    """
    y = rw.tape_core(audio48k, seed)
    y = rw.speaker_response(y, kind="laptop")
    y = rw.soft_clip(y, k=drive)
    y = rw.room_reverb(y, rt60=RT60, distance_m=distance_m, seed=seed)
    y = rw.distance_atten(y, distance_m=distance_m)
    y = rw.mic_response(y, kind="phone_recorder")
    y = rw.ambient_noise(y, snr_db=30.0, kind="pink", seed=seed)
    y = cscn._agc(y, target_rms=0.2, attack=0.005, release=0.20)
    return y.astype(np.float32), FS


def evaluate_sweep(scheme, drive: float, distance_m: float,
                   n_seeds: int = N_SEEDS,
                   payload_bits: int = PAYLOAD_BITS) -> dict:
    """Run a single (modem, drive, distance) condition over n_seeds seeds."""
    bers: list[float] = []
    peaks: list[float] = []
    cleans: list[bool] = []

    for seed in range(n_seeds):
        tx_bits = hc._random_bits(payload_bits, seed)
        audio = np.asarray(scheme.modulate(tx_bits), dtype=np.float32)
        rx_audio, sr = acoustic_close_sweep(
            audio, seed, drive=drive, distance_m=distance_m
        )
        rx_bits = np.asarray(scheme.demodulate(rx_audio, sr), dtype=np.uint8)

        ber = hc._ber(tx_bits, rx_bits)
        bers.append(ber)
        cleans.append(ber == 0.0)
        peaks.append(rw._corr_peak(rx_audio))

    return {
        "modem": getattr(scheme, "name", "scheme"),
        "drive": float(drive),
        "distance_m": float(distance_m),
        "gross_bps": float(scheme.gross_bps),
        "raw_bit_error_rate": float(np.mean(bers)),
        "clean_decode_prob": float(np.mean(cleans)),
        "corr_peak_mean": float(np.mean(peaks)),
        "corr_peak_min": float(np.min(peaks)),
        "corr_peak_std": float(np.std(peaks)),
        "per_seed_ber": [float(x) for x in bers],
        "per_seed_corr_peak": [float(x) for x in peaks],
        "per_seed_clean": [bool(x) for x in cleans],
        "n_seeds": n_seeds,
        "payload_bits": payload_bits,
        "rt60": RT60,
        "snr_db_ambient": 30.0,
        "tape_preset": "normal",
    }


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def run() -> dict:
    t0_total = time.time()
    print("=" * 70)
    print("T2: Acoustic close-range sweep — phone mic at speaker")
    print(f"  Modems:    bfsk_b0, mfsk32")
    print(f"  Drives:    {DRIVE_LEVELS}")
    print(f"  Distances: {DISTANCES_M} m")
    print(f"  Seeds:     {N_SEEDS} per condition")
    print(f"  Payload:   {PAYLOAD_BITS} bits")
    print("=" * 70)

    modems = rw.build_reference_modems(PAYLOAD_BITS)
    sweep_results = []

    total_conditions = len(modems) * len(DRIVE_LEVELS) * len(DISTANCES_M)
    done = 0

    for mname, scheme in modems.items():
        for drive in DRIVE_LEVELS:
            for dist in DISTANCES_M:
                t0 = time.time()
                res = evaluate_sweep(scheme, drive=drive, distance_m=dist)
                dt = time.time() - t0
                sweep_results.append(res)
                done += 1
                print(
                    f"  [{done}/{total_conditions}] {mname:10s} drive={drive:.1f}"
                    f"  dist={dist:.2f}m  "
                    f"ber={res['raw_bit_error_rate']:.3f}  "
                    f"clean={res['clean_decode_prob']:.2f}  "
                    f"peak={res['corr_peak_mean']:.3f}  ({dt:.1f}s)"
                )

    # Also run baseline P3 (default drive=1.2, dist=0.15) for reference.
    print("\n-- P3 baseline reference (default acoustic_close_quiet) --")
    p3_results = {}
    for mname, scheme in modems.items():
        t0 = time.time()
        res = rw.evaluate_realworld(scheme, "acoustic_close_quiet",
                                    n_seeds=N_SEEDS, payload_bits=PAYLOAD_BITS)
        p3_results[mname] = res
        dt = time.time() - t0
        print(
            f"  {mname:10s} P3: ber={res['raw_bit_error_rate']:.3f}  "
            f"clean={res['clean_decode_prob']:.2f}  "
            f"peak={res['corr_peak_mean']:.3f}  ({dt:.1f}s)"
        )

    total_time = time.time() - t0_total
    print(f"\nTotal sweep time: {total_time:.1f}s")

    # -----------------------------------------------------------------------
    # Analysis: find min viable conditions
    # -----------------------------------------------------------------------
    def find_best(modem_name: str) -> dict | None:
        candidates = [r for r in sweep_results
                      if r["modem"] == modem_name and r["clean_decode_prob"] > 0]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["clean_decode_prob"])

    def find_threshold(modem_name: str, metric: str = "clean_decode_prob",
                       threshold: float = 0.5) -> list:
        """Conditions where clean_decode_prob >= threshold."""
        return [r for r in sweep_results
                if r["modem"] == modem_name and r[metric] >= threshold]

    analysis = {}
    for mname in modems:
        best = find_best(mname)
        viable_50 = find_threshold(mname, threshold=0.5)
        viable_any = find_threshold(mname, threshold=0.01)
        corr_peaks = [r["corr_peak_mean"] for r in sweep_results
                      if r["modem"] == mname]
        analysis[mname] = {
            "any_success": bool(find_best(mname) is not None),
            "best_condition": best,
            "n_viable_50pct": len(viable_50),
            "n_viable_any": len(viable_any),
            "corr_peak_range": [
                float(min(corr_peaks)),
                float(max(corr_peaks)),
            ] if corr_peaks else [0.0, 0.0],
        }

    output = {
        "experiment": "rw_t2_acoustic_close",
        "description": (
            "Acoustic close-range sweep: phone mic placed near laptop speaker "
            "in a quiet room. Sweep drive (soft-clip intensity) and distance "
            "(0.05, 0.15, 0.30 m). Both reference modems (bfsk_b0, mfsk32) "
            "evaluated over 12 seeds per condition."
        ),
        "parameters": {
            "n_seeds": N_SEEDS,
            "payload_bits": PAYLOAD_BITS,
            "drive_levels": DRIVE_LEVELS,
            "distances_m": DISTANCES_M,
            "rt60_s": RT60,
            "ambient_snr_db": 30.0,
            "tape_preset": "normal",
        },
        "sweep_results": sweep_results,
        "p3_baseline": p3_results,
        "analysis": analysis,
        "total_time_s": round(total_time, 1),
    }

    # SAVE BEFORE returning — robustness rule.
    out_path = DATA_DIR / "rw_acoustic_close.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2,
                  default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"\nSaved: {out_path}")

    return output


# ---------------------------------------------------------------------------
# Plot (optional, after save)
# ---------------------------------------------------------------------------

def plot(output: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError:
        print("matplotlib not available — skipping plot")
        return

    sweep = output["sweep_results"]
    modems = ["bfsk_b0", "mfsk32"]
    distances = sorted(set(r["distance_m"] for r in sweep))
    drives = sorted(set(r["drive"] for r in sweep))

    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    fig.suptitle(
        "T2: Acoustic Close — Clean Decode Prob & Corr Peak\n"
        "(laptop speaker -> quiet room -> phone MEMS mic, 30 dB pink noise, RT60=0.25s)",
        fontsize=11
    )

    for col, mname in enumerate(modems):
        # Rows: clean_decode_prob heatmap, corr_peak_mean heatmap
        for row, metric in enumerate(["clean_decode_prob", "corr_peak_mean"]):
            ax = axes[row][col]
            grid = np.zeros((len(distances), len(drives)))
            for i, d in enumerate(distances):
                for j, dr in enumerate(drives):
                    match = [r for r in sweep
                             if r["modem"] == mname
                             and abs(r["distance_m"] - d) < 0.001
                             and abs(r["drive"] - dr) < 0.001]
                    grid[i, j] = match[0][metric] if match else 0.0

            im = ax.imshow(
                grid, aspect="auto", origin="lower",
                cmap="RdYlGn" if metric == "clean_decode_prob" else "viridis",
                vmin=0, vmax=1,
            )
            ax.set_xticks(range(len(drives)))
            ax.set_xticklabels([f"{d:.1f}" for d in drives], fontsize=8)
            ax.set_yticks(range(len(distances)))
            ax.set_yticklabels([f"{d:.2f}m" for d in distances], fontsize=8)
            ax.set_xlabel("Soft-clip drive (k)", fontsize=8)
            ax.set_ylabel("Distance [m]", fontsize=8)
            label = "Clean decode prob" if metric == "clean_decode_prob" else "Corr peak mean"
            ax.set_title(f"{mname} — {label}", fontsize=9)
            plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

            # Annotate cells with values.
            for i in range(len(distances)):
                for j in range(len(drives)):
                    ax.text(j, i, f"{grid[i,j]:.2f}", ha="center",
                            va="center", fontsize=7,
                            color="white" if grid[i,j] < 0.5 else "black")

    # Third column: summary bar chart (best clean_decode_prob per modem x distance)
    for col, mname in enumerate(modems):
        ax = axes[0][2] if col == 0 else axes[1][2]
        best_per_dist = []
        for d in distances:
            vals = [r["clean_decode_prob"] for r in sweep
                    if r["modem"] == mname and abs(r["distance_m"] - d) < 0.001]
            best_per_dist.append(max(vals) if vals else 0.0)
        ax.bar([f"{d:.2f}m" for d in distances], best_per_dist,
               color=["#2ca02c" if v >= 0.5 else "#d62728" for v in best_per_dist])
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("Best clean_decode_prob", fontsize=8)
        ax.set_title(f"{mname} — best clean prob by distance", fontsize=9)
        ax.axhline(0.5, ls="--", color="gray", lw=1, label="50% threshold")
        ax.legend(fontsize=7)
        # Annotate
        for i, v in enumerate(best_per_dist):
            ax.text(i, v + 0.02, f"{v:.2f}", ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    out_path = PLOT_DIR / "rw_acoustic_close.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved: {out_path}")
    plt.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = run()
    plot(result)

    # Print summary for human review.
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for mname, info in result["analysis"].items():
        print(f"\n  {mname}:")
        print(f"    any_success:      {info['any_success']}")
        print(f"    n_viable_any:     {info['n_viable_any']}")
        print(f"    n_viable_50pct:   {info['n_viable_50pct']}")
        print(f"    corr_peak_range:  {info['corr_peak_range']}")
        if info["best_condition"]:
            bc = info["best_condition"]
            print(f"    best: drive={bc['drive']:.1f}, dist={bc['distance_m']:.2f}m, "
                  f"clean={bc['clean_decode_prob']:.2f}, ber={bc['raw_bit_error_rate']:.3f}")
