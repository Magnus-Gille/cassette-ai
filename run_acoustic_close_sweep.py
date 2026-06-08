"""run_acoustic_close_sweep.py

T2 acoustic_close_quiet sweep experiment.
Sweeps distance (0.03, 0.08, 0.15, 0.30 m) x ambient SNR (35, 30, 25 dB)
for both REFERENCE_MODEMS (bfsk_b0, mfsk32).

Saves full results to RESULTS/data/rw_acoustic_close.json
Generates plot   to RESULTS/plots/rw_acoustic_close.png
"""

import sys
import pathlib
import json
import time

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for p in ["src", "tests/e2e"]:
    sys.path.insert(0, str(ROOT / p))

import numpy as np
import realworld_channels as rw
import hyp_common as hc
import capture_scenarios as cscn

FS = 48_000
N_SEEDS = 12
PAYLOAD_BITS = 2000
DISTANCES = [0.03, 0.08, 0.15, 0.30]
SNRS = [35, 30, 25]


def acoustic_close_custom(audio48k: np.ndarray, seed: int = 0,
                           distance_m: float = 0.15, snr_db: float = 30.0):
    """Custom acoustic_close path with configurable distance and SNR.

    Matches P3's chain exactly: tape_core -> speaker_response -> soft_clip ->
    room_reverb(rt60=0.25, distance) -> distance_atten -> mic_response ->
    ambient_noise(snr_db, pink) -> AGC
    """
    y = rw.tape_core(audio48k, seed)
    y = rw.speaker_response(y, kind="laptop")
    y = rw.soft_clip(y, k=1.2)
    y = rw.room_reverb(y, rt60=0.25, distance_m=distance_m, seed=seed)
    y = rw.distance_atten(y, distance_m=distance_m)
    y = rw.mic_response(y, kind="phone_recorder")
    y = rw.ambient_noise(y, snr_db=snr_db, kind="pink", seed=seed)
    y = cscn._agc(y, target_rms=0.2, attack=0.005, release=0.20)
    return y.astype(np.float32), FS


def run_cell(scheme, modem_name: str, distance_m: float, snr_db: float):
    """Run one (modem, distance, snr) cell — 12 seeds."""
    bers = []
    peaks = []
    cleans = []
    eras = []

    for seed in range(N_SEEDS):
        tx_bits = hc._random_bits(PAYLOAD_BITS, seed)
        audio = np.asarray(scheme.modulate(tx_bits), dtype=np.float32)
        rx_audio, sr = acoustic_close_custom(audio, seed=seed,
                                             distance_m=distance_m,
                                             snr_db=snr_db)
        rx_bits = np.asarray(scheme.demodulate(rx_audio, sr), dtype=np.uint8)

        ber = hc._ber(tx_bits, rx_bits)
        bers.append(float(ber))
        cleans.append(bool(ber == 0.0))
        peaks.append(float(rw._corr_peak(rx_audio)))

        ef = getattr(scheme, "erasure_fn", None)
        if ef is not None:
            eras.append(float(ef(rx_audio, sr, tx_bits)))
        elif hasattr(scheme, "erasure_rate_for"):
            eras.append(float(scheme.erasure_rate_for(0)))
        else:
            eras.append(0.0)

    # content-clean: fraction of seeds with ALL content bits correct (BER==0)
    content_clean = float(np.mean(cleans))

    return {
        "modem": modem_name,
        "distance_m": distance_m,
        "snr_db": snr_db,
        "raw_bit_error_rate": float(np.mean(bers)),
        "clean_decode_prob": content_clean,   # strict BER==0 fraction
        "erasure_rate": float(np.mean(eras)),
        "corr_peak_mean": float(np.mean(peaks)),
        "corr_peak_min": float(np.min(peaks)),
        "corr_peak_std": float(np.std(peaks)),
        "per_seed_ber": bers,
        "per_seed_clean": cleans,
        "per_seed_corr_peak": peaks,
        "n_seeds": N_SEEDS,
        "payload_bits": PAYLOAD_BITS,
    }


def main():
    modems = rw.build_reference_modems(PAYLOAD_BITS)
    results = []
    total = len(DISTANCES) * len(SNRS) * len(modems)
    done = 0

    print(f"Running {total} cells: {len(modems)} modems x "
          f"{len(DISTANCES)} distances x {len(SNRS)} SNRs, "
          f"{N_SEEDS} seeds each\n")
    print(f"{'Modem':<12} {'dist':>6} {'SNR':>5}  "
          f"{'BER':>8}  {'clean':>6}  {'peak_mean':>10}  {'peak_min':>9}")
    print("-" * 65)

    t0 = time.time()
    for mname, scheme in modems.items():
        for dist in DISTANCES:
            for snr in SNRS:
                t_cell = time.time()
                cell = run_cell(scheme, mname, dist, snr)
                results.append(cell)
                done += 1
                elapsed = time.time() - t_cell
                print(f"{mname:<12} {dist:>6.2f} {snr:>5}  "
                      f"{cell['raw_bit_error_rate']:>8.4f}  "
                      f"{cell['clean_decode_prob']:>6.2f}  "
                      f"{cell['corr_peak_mean']:>10.4f}  "
                      f"{cell['corr_peak_min']:>9.4f}  "
                      f"({elapsed:.1f}s)")

    total_time = time.time() - t0
    print(f"\nDone. {total} cells in {total_time:.1f}s")

    # Save results
    data_dir = ROOT / "RESULTS" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "rw_acoustic_close.json"
    payload = {
        "experiment": "T2_acoustic_close_quiet_sweep",
        "n_seeds": N_SEEDS,
        "payload_bits": PAYLOAD_BITS,
        "distances_m": DISTANCES,
        "snrs_db": SNRS,
        "modems": list(modems.keys()),
        "tape_preset": "normal",
        "rt60": 0.25,
        "results": results,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Saved {out_path}")

    # Plot
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm

        plots_dir = ROOT / "RESULTS" / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)

        fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
        fig.suptitle("T2 Acoustic Close: clean_decode_prob vs distance\n"
                     "(strict BER=0, n_seeds=12, rt60=0.25)", fontsize=12)

        snr_colors = {35: "green", 30: "orange", 25: "red"}
        modem_list = list(modems.keys())

        for ax_idx, mname in enumerate(modem_list):
            ax = axes[ax_idx]
            ax.set_title(mname)
            ax.set_xlabel("Distance (m)")
            ax.set_ylabel("Clean decode probability")
            ax.set_ylim(-0.05, 1.05)
            ax.set_xlim(0, 0.35)
            ax.grid(True, alpha=0.3)
            ax.axhline(0.5, color="black", lw=0.8, ls="--", alpha=0.4,
                       label="_50% threshold")

            for snr in SNRS:
                xs = []
                ys = []
                for cell in results:
                    if cell["modem"] == mname and cell["snr_db"] == snr:
                        xs.append(cell["distance_m"])
                        ys.append(cell["clean_decode_prob"])
                # sort by distance
                pairs = sorted(zip(xs, ys))
                xs = [p[0] for p in pairs]
                ys = [p[1] for p in pairs]
                ax.plot(xs, ys, "o-", color=snr_colors[snr],
                        label=f"SNR={snr}dB", lw=2, ms=7)

            ax.legend(fontsize=9)

        plt.tight_layout()
        plot_path = plots_dir / "rw_acoustic_close.png"
        plt.savefig(plot_path, dpi=120, bbox_inches="tight")
        plt.close()
        print(f"Saved {plot_path}")
    except Exception as e:
        print(f"Plot skipped: {e}")

    return results


if __name__ == "__main__":
    main()
