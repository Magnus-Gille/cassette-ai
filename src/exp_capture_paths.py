"""exp_capture_paths.py — Experiment B: Capture-Path Comparison.

Question: USB soundcard vs phone (custom PCM app vs standard voice/VoIP app) —
how much does the CAPTURE stage cost, and is a custom app worth building?

Design:
  - Tape presets:  "normal", "worn"
  - Capture stages: usb_soundcard, phone_custom_pcm,
                    phone_voice_recorder_aac, phone_voip_opus_narrow
  - Monte Carlo:   N=24 seeds per cell
  - Payload:       cf.cassette_payload("captureB", 512) — 512 bytes, fixed
  - Speed grid:    trivial (no steady speed offset injected)
  - Bandwidth estimate via wideband chirp spectrum measurement

Outputs:
  RESULTS/data/exp_capture_paths.csv
  RESULTS/plots/exp_capture_paths.png
"""

from __future__ import annotations

import sys
import pathlib
import time

import numpy as np
from scipy import signal
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))

import cassette_format as cf
import cassette_e2e as e2e
from capture_scenarios import (
    TAPE_PRESETS,
    CAPTURE_SCENARIOS,
    full_chain,
    _lowpass,
    _agc,
    _spectral_gate,
    _ffmpeg_roundtrip,
)
from common import DATA, PLOTS, ensure_dirs, write_csv

FS = 48_000
N_SEEDS = 24
PAYLOAD_SIZE = 512
PAYLOAD = cf.cassette_payload("captureB", PAYLOAD_SIZE)
TAPE_PRESETS_TO_TEST = ["normal", "worn"]

# Scenario display labels
SCENARIO_LABELS = {
    "usb_soundcard":            "USB soundcard",
    "phone_custom_pcm":         "Phone custom PCM",
    "phone_voice_recorder_aac": "Phone voice rec (AAC)",
    "phone_voip_opus_narrow":   "Phone VoIP (Opus)",
}

# Scenario effective bandwidth (measured via chirp sweep below)
# Keys match CAPTURE_SCENARIOS
SCENARIO_EFFECTIVE_BW: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Bandwidth estimation
# ---------------------------------------------------------------------------

def measure_effective_bandwidth(capture_key: str, tape_preset: str) -> dict[str, float]:
    """Estimate effective bandwidth of a capture path using a wideband chirp.

    Generates a 0-to-20kHz linear chirp, runs it through the capture stage
    (after a tape_core pass with the given preset at seed=0), computes the
    power spectrum, and finds the -3dB and -20dB cutoff frequencies.

    Returns dict with bw_3db_hz and bw_20db_hz.
    """
    from capture_scenarios import tape_core

    # 1-second linear chirp spanning 20 Hz -> 20 kHz
    duration = 1.0
    t = np.linspace(0.0, duration, int(FS * duration), endpoint=False)
    chirp = signal.chirp(t, f0=20.0, f1=20_000.0, t1=duration, method="linear").astype(np.float32)
    # Normalize to 0.5 peak
    chirp = (chirp / float(np.max(np.abs(chirp)))) * 0.5

    # Pass through tape core (to include tape bandwidth limits)
    tape_out, _ = tape_core(chirp, preset=tape_preset, seed=0)

    # Pass through capture stage
    capture_fn = CAPTURE_SCENARIOS[capture_key]
    captured = capture_fn(tape_out, seed=0)

    # Compute power spectrum via Welch
    f, Pxx = signal.welch(captured.astype(np.float64), fs=FS, nperseg=4096)

    # Smooth: rolling average over ~50 Hz bins
    kernel = np.ones(25) / 25.0
    Pxx_smooth = np.convolve(Pxx, kernel, mode="same")

    # Reference power = max in 100-500 Hz range (avoid DC and chirp start ramp)
    ref_mask = (f >= 100) & (f <= 500)
    P_ref = float(np.max(Pxx_smooth[ref_mask]))
    if P_ref <= 0:
        P_ref = float(np.max(Pxx_smooth)) + 1e-30

    Pxx_dB = 10.0 * np.log10(Pxx_smooth / P_ref + 1e-30)

    def find_cutoff(threshold_db: float) -> float:
        """Find highest frequency where power is still above threshold_db."""
        mask = Pxx_dB >= threshold_db
        # We want the last freq where it crosses the threshold
        indices = np.where(mask)[0]
        if len(indices) == 0:
            return float(f[0])
        return float(f[indices[-1]])

    bw_3db = find_cutoff(-3.0)
    bw_20db = find_cutoff(-20.0)

    return {"bw_3db_hz": round(bw_3db, 0), "bw_20db_hz": round(bw_20db, 0)}


# ---------------------------------------------------------------------------
# Monte Carlo run
# ---------------------------------------------------------------------------

def run_cell(tape_preset: str, capture_key: str) -> dict:
    """Run N_SEEDS Monte Carlo trials for one (tape_preset, capture_key) cell.

    Returns a dict with aggregated metrics.
    """
    audio = e2e.encode_payload_to_audio(PAYLOAD)

    completes = []
    frame_recoveries = []
    byte_error_rates = []
    snr_measurements = []

    total_frames_ref = None

    for seed in range(N_SEEDS):
        try:
            captured, sr, diag = full_chain(
                audio,
                tape_preset=tape_preset,
                capture_key=capture_key,
                seed=seed,
            )
        except Exception as exc:
            # ffmpeg or other failure — count as failed decode
            completes.append(False)
            frame_recoveries.append(0.0)
            byte_error_rates.append(1.0)
            snr_measurements.append(float("nan"))
            continue

        # Trivial speed grid: no steady speed offset
        rr = e2e.robust_decode(
            captured, sr,
            speed_search=(1.0, 1.0001, 1.0),
            verbose=False,
        )
        cmp = e2e.compare_payload(PAYLOAD, rr.result)

        completes.append(bool(rr.result.complete))
        frame_recoveries.append(float(cmp["recovered_fraction"]))
        byte_error_rates.append(float(cmp["byte_error_rate"]))
        snr_measurements.append(float(diag.get("measured_snr_db", float("nan"))))

        if total_frames_ref is None and rr.result.recovered_frames is not None:
            # Infer total frames from first successful result
            # recovered_frames + missing_frames + bad_frames = total
            total_frames_ref = (
                rr.result.recovered_frames
                + len(rr.result.missing_frames)
                + rr.result.bad_frames
            )

    clean_decode_prob = float(np.mean(completes))
    mean_frame_recovery = float(np.mean(frame_recoveries))
    mean_byte_error_rate = float(np.nanmean(byte_error_rates))
    mean_snr_db = float(np.nanmean(snr_measurements))

    return {
        "tape_preset": tape_preset,
        "capture_scenario": capture_key,
        "clean_decode_prob": round(clean_decode_prob, 4),
        "mean_frame_recovery": round(mean_frame_recovery, 4),
        "mean_byte_error_rate": round(mean_byte_error_rate, 4),
        "mean_snr_db": round(mean_snr_db, 2),
        "n_seeds": N_SEEDS,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> None:
    ensure_dirs()

    t_start = time.time()

    print("=" * 72)
    print("Experiment B: Capture-Path Comparison")
    print(f"  Tape presets:    {TAPE_PRESETS_TO_TEST}")
    print(f"  Capture paths:   {list(CAPTURE_SCENARIOS.keys())}")
    print(f"  Monte Carlo:     N={N_SEEDS} seeds, {PAYLOAD_SIZE}-byte payload")
    print("=" * 72)

    # Step 1: Measure effective bandwidths per (capture_key, tape_preset)
    print("\n[1/3] Measuring effective bandwidth via chirp...")
    bw_rows = []
    for tape_preset in TAPE_PRESETS_TO_TEST:
        for capture_key in CAPTURE_SCENARIOS:
            bw = measure_effective_bandwidth(capture_key, tape_preset)
            bw_rows.append({
                "tape_preset": tape_preset,
                "capture_scenario": capture_key,
                **bw,
            })
            label = SCENARIO_LABELS[capture_key]
            print(f"  [{tape_preset:6s}] {label:30s}  -3dB={bw['bw_3db_hz']:6.0f} Hz  "
                  f"-20dB={bw['bw_20db_hz']:6.0f} Hz")

    # Build lookup: (tape_preset, capture_key) -> bw dict
    bw_lookup: dict[tuple, dict] = {
        (r["tape_preset"], r["capture_scenario"]): r
        for r in bw_rows
    }

    # Step 2: Monte Carlo per cell
    print(f"\n[2/3] Monte Carlo ({N_SEEDS} seeds x {len(TAPE_PRESETS_TO_TEST)} presets "
          f"x {len(CAPTURE_SCENARIOS)} scenarios) ...")
    mc_rows = []
    for tape_preset in TAPE_PRESETS_TO_TEST:
        for capture_key in CAPTURE_SCENARIOS:
            label = SCENARIO_LABELS[capture_key]
            print(f"  [{tape_preset:6s}] {label:30s} ... ", end="", flush=True)
            t0 = time.time()
            row = run_cell(tape_preset, capture_key)
            elapsed = time.time() - t0
            bw = bw_lookup[(tape_preset, capture_key)]
            row["bw_3db_hz"] = bw["bw_3db_hz"]
            row["bw_20db_hz"] = bw["bw_20db_hz"]
            mc_rows.append(row)
            print(
                f"clean={row['clean_decode_prob']:.2f}  "
                f"frec={row['mean_frame_recovery']:.3f}  "
                f"ber={row['mean_byte_error_rate']:.4f}  "
                f"snr={row['mean_snr_db']:.1f}dB  "
                f"bw3dB={row['bw_3db_hz']:.0f}Hz  "
                f"({elapsed:.1f}s)"
            )

    # Step 3: Save CSV
    write_csv(DATA / "exp_capture_paths.csv", mc_rows)
    print(f"\n  Saved: {DATA / 'exp_capture_paths.csv'}")

    # Step 4: Print table
    print("\n" + "=" * 72)
    print("RESULTS TABLE")
    print("=" * 72)
    hdr = (
        f"{'Preset':6s}  {'Scenario':30s}  {'P(clean)':8s}  "
        f"{'FrameRec':8s}  {'BER':8s}  {'SNR(dB)':7s}  "
        f"{'BW-3dB':7s}  {'BW-20dB':7s}"
    )
    print(hdr)
    print("-" * 72)
    for row in mc_rows:
        print(
            f"{row['tape_preset']:6s}  "
            f"{SCENARIO_LABELS[row['capture_scenario']]:30s}  "
            f"{row['clean_decode_prob']:8.3f}  "
            f"{row['mean_frame_recovery']:8.3f}  "
            f"{row['mean_byte_error_rate']:8.4f}  "
            f"{row['mean_snr_db']:7.1f}  "
            f"{row['bw_3db_hz']:7.0f}  "
            f"{row['bw_20db_hz']:7.0f}"
        )

    # Compute and print the custom-app vs standard-app deltas
    print("\n" + "=" * 72)
    print("DELTA: custom app vs standard app (phone_custom_pcm vs phone_voice_recorder_aac / phone_voip_opus_narrow)")
    print("=" * 72)
    for tape_preset in TAPE_PRESETS_TO_TEST:
        subset = {r["capture_scenario"]: r for r in mc_rows if r["tape_preset"] == tape_preset}
        custom = subset.get("phone_custom_pcm")
        aac = subset.get("phone_voice_recorder_aac")
        opus = subset.get("phone_voip_opus_narrow")
        if custom and aac:
            delta_aac = custom["clean_decode_prob"] - aac["clean_decode_prob"]
            print(f"  [{tape_preset}] custom_pcm vs voice_rec_aac:  "
                  f"P(clean) delta = {delta_aac:+.3f}  "
                  f"(custom={custom['clean_decode_prob']:.3f}, aac={aac['clean_decode_prob']:.3f})")
        if custom and opus:
            delta_opus = custom["clean_decode_prob"] - opus["clean_decode_prob"]
            print(f"  [{tape_preset}] custom_pcm vs voip_opus:      "
                  f"P(clean) delta = {delta_opus:+.3f}  "
                  f"(custom={custom['clean_decode_prob']:.3f}, opus={opus['clean_decode_prob']:.3f})")

    # Step 5: Plots
    print("\n[3/3] Generating plot...")
    _make_plot(mc_rows)
    print(f"  Saved: {PLOTS / 'exp_capture_paths.png'}")

    elapsed_total = time.time() - t_start
    print(f"\nTotal runtime: {elapsed_total:.1f}s")
    print("=" * 72)


def _make_plot(mc_rows: list[dict]) -> None:
    """Grouped-bar plot: P(clean decode) per scenario, one group per tape preset.

    Bars annotated with effective bandwidth (-3dB).
    """
    scenarios = list(CAPTURE_SCENARIOS.keys())
    n_scenarios = len(scenarios)
    n_presets = len(TAPE_PRESETS_TO_TEST)

    # Colors per tape preset
    preset_colors = {
        "normal": "#4878CF",
        "worn":   "#D65F5F",
    }

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=False)

    for ax_idx, tape_preset in enumerate(TAPE_PRESETS_TO_TEST):
        ax = axes[ax_idx]
        subset = {r["capture_scenario"]: r for r in mc_rows if r["tape_preset"] == tape_preset}

        x = np.arange(n_scenarios)
        bar_w = 0.55
        color = preset_colors[tape_preset]

        probs = [subset[s]["clean_decode_prob"] for s in scenarios]
        bw3dbs = [subset[s]["bw_3db_hz"] for s in scenarios]
        bw20dbs = [subset[s]["bw_20db_hz"] for s in scenarios]
        mean_frecs = [subset[s]["mean_frame_recovery"] for s in scenarios]
        bers = [subset[s]["mean_byte_error_rate"] for s in scenarios]

        bars = ax.bar(x, probs, bar_w, color=color, alpha=0.8, edgecolor="black", linewidth=0.8)

        # Annotate each bar with:
        #   P(clean) value on bar top
        #   BW-3dB and BW-20dB below the bar
        for i, (bar, p, bw3, bw20, frec, ber) in enumerate(
            zip(bars, probs, bw3dbs, bw20dbs, mean_frecs, bers)
        ):
            bar_top = bar.get_height()
            # P(clean) inside or just above bar
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                min(bar_top + 0.02, 0.97),
                f"{p:.2f}",
                ha="center", va="bottom",
                fontsize=9, fontweight="bold",
            )
            # BW annotation below x-axis
            bw_label = f"-3dB: {bw3/1000:.1f}k\n-20dB: {bw20/1000:.1f}k"
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                -0.16,
                bw_label,
                ha="center", va="top",
                fontsize=7.5, color="dimgray",
                transform=ax.get_xaxis_transform(),
            )

        # Reference lines
        for y_ref, ls in [(1.0, "--"), (0.95, ":"), (0.5, ":")]:
            ax.axhline(y_ref, color="gray", linestyle=ls, linewidth=0.8, alpha=0.5)

        ax.set_xticks(x)
        ax.set_xticklabels(
            [SCENARIO_LABELS[s].replace(" ", "\n") for s in scenarios],
            fontsize=8.5,
        )
        ax.set_ylim(0.0, 1.15)
        ax.set_ylabel("P(clean decode)", fontsize=10)
        ax.set_title(f'Tape preset: "{tape_preset}"', fontsize=11, fontweight="bold")
        ax.grid(axis="y", alpha=0.3)

    # Add a secondary inset: frame recovery (partial credit) as thin overlay lines
    for ax_idx, tape_preset in enumerate(TAPE_PRESETS_TO_TEST):
        ax = axes[ax_idx]
        subset = {r["capture_scenario"]: r for r in mc_rows if r["tape_preset"] == tape_preset}
        x = np.arange(n_scenarios)
        frecs = [subset[s]["mean_frame_recovery"] for s in scenarios]
        ax2 = ax.twinx()
        ax2.plot(x, frecs, "o--", color="darkorange", linewidth=1.3, markersize=5, alpha=0.8)
        ax2.set_ylim(0.0, 1.15)
        ax2.set_ylabel("mean frame recovery", fontsize=9, color="darkorange")
        ax2.tick_params(axis="y", labelcolor="darkorange", labelsize=8)

    fig.suptitle(
        f"Capture-Path Comparison (N={N_SEEDS} seeds, {PAYLOAD_SIZE}-byte payload)\n"
        "Bars = P(clean decode) | Orange line = mean frame recovery | Grey text = effective bandwidth",
        fontsize=10,
    )
    fig.tight_layout(rect=[0.0, 0.05, 1.0, 1.0])
    fig.savefig(PLOTS / "exp_capture_paths.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run()
