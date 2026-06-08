"""exp_capacity_cliff.py — Experiment C: Reliable-Rate -> MB-per-Cassette.

For each capture scenario (usb_soundcard, phone_custom_pcm, phone_voice_recorder_aac,
phone_voip_opus_narrow) at tape preset "normal":

  1. Sweep candidate gross bit rates using 2-FSK or 4-FSK depending on whether the
     tones fit in the usable bandwidth.
  2. Pass each through full_chain (tape core + capture stage) over N=20 seeds.
  3. Measure raw BER; find the highest gross rate with mean BER <= 1e-3 (and <= 1e-4).
  4. Compute net payload rate = reliable_gross * outer_code_rate(0.8) * 2 (stereo).
  5. Project MB-per-cassette for C60 (3574 s usable) and C90 (5374 s).
  6. Compare to the 1.271 MB TinyStories-1M UEP target.
  7. Also compute the Shannon ceiling from measured SNR and effective bandwidth.

Outputs
-------
RESULTS/data/exp_capacity_cliff.csv
RESULTS/plots/exp_capacity_cliff.png
"""

from __future__ import annotations

import math
import sys
import pathlib

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))

import parametric_modem as pm
from parametric_modem import decode_bits, decode_bits_with_timing, encode_bits, ber as pm_ber
from capture_scenarios import (
    CAPTURE_SCENARIOS,
    TAPE_PRESETS,
    full_chain,
    tape_core,
    capture_usb_soundcard,
    capture_phone_custom_pcm,
    capture_voice_recorder_aac,
    capture_voip_opus_narrow,
)
from common import DATA, PLOTS, ensure_dirs, rng, write_csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TAPE_PRESET       = "normal"
N_SEEDS           = 20           # Monte-Carlo seeds per (scenario, rate) cell
N_BITS            = 3000         # random bits per seed (keep run time tractable)
OUTER_CODE_RATE   = 0.8          # assumed RS/LDPC outer FEC rate
STEREO_FACTOR     = 2            # record on both channels independently
TARGET_MB         = 1.271        # UEP-encoded TinyStories-1M payload (MB)
C60_USABLE_S      = 3_574.0      # usable seconds across 2 sides of a C60
C90_USABLE_S      = 5_374.0      # usable seconds across 2 sides of a C90
BER_THRESH_LOOSE  = 1e-3         # pre-FEC "reliable" threshold (loose)
BER_THRESH_STRICT = 1e-4         # pre-FEC "reliable" threshold (strict)

# Effective bandwidth limits per capture scenario
# (used for tone selection AND Shannon ceiling calculation)
SCENARIO_BW: dict[str, float] = {
    "usb_soundcard":            11_000.0,   # tape normal BW limit (11kHz)
    "phone_custom_pcm":         11_000.0,   # tape normal BW limit (slightly cut at 18kHz ADC, but tape wins)
    "phone_voice_recorder_aac":  7_500.0,   # speech lowpass
    "phone_voip_opus_narrow":    3_800.0,   # narrowband VoIP
}

# Candidate gross bit rates (bps)
CANDIDATE_RATES = [600, 1_200, 2_400, 4_800, 9_600, 19_200]

# SNR from tape "normal" preset (for Shannon ceiling); diagnostics refine this
NORMAL_TAPE_SNR_DB = TAPE_PRESETS["normal"]["snr_db"]  # 42.0 dB


# ---------------------------------------------------------------------------
# Helper: choose modem config for a (scenario, rate) pair
# ---------------------------------------------------------------------------

def _modem_config(
    scenario: str,
    gross_bps: int,
) -> tuple[tuple[float, ...], int] | None:
    """Return (tones, M) for the given scenario and gross rate, or None if not feasible.

    Strategy:
    - Try 2-FSK first (tones at f0, f0 + spacing, spacing = gross_bps).
    - If the upper tone exceeds the scenario bandwidth, try 4-FSK (symbol_rate =
      gross_bps/2, spacing = symbol_rate, 4 tones from 600 Hz up).
    - If still not feasible, return None.
    """
    bw = SCENARIO_BW[scenario]
    min_freq = 600.0

    # 2-FSK: spacing = gross_bps (orthogonal for symbol_rate=gross_bps)
    spacing_2fsk = float(gross_bps)
    f0_2fsk = min_freq
    f1_2fsk = f0_2fsk + spacing_2fsk
    if f1_2fsk <= bw * 0.95:
        return (f0_2fsk, f1_2fsk), 2

    # 4-FSK: symbol_rate = gross_bps/2, spacing = symbol_rate
    spacing_4fsk = float(gross_bps // 2)
    tones_4fsk = tuple(min_freq + i * spacing_4fsk for i in range(4))
    if tones_4fsk[-1] <= bw * 0.95:
        return tones_4fsk, 4

    # 8-FSK: symbol_rate = gross_bps/3, spacing = symbol_rate
    spacing_8fsk = float(gross_bps // 3)
    tones_8fsk = tuple(min_freq + i * spacing_8fsk for i in range(8))
    if tones_8fsk[-1] <= bw * 0.95:
        return tones_8fsk, 8

    return None  # rate not feasible in this bandwidth


# ---------------------------------------------------------------------------
# BER measurement for a single (scenario, rate, seed)
# ---------------------------------------------------------------------------

def _measure_ber_one(
    scenario_key: str,
    gross_bps: int,
    tones: tuple[float, ...],
    seed: int,
    *,
    timing_recovery: bool = True,
) -> float:
    """Generate random bits, encode, run through full_chain, decode, return BER.

    Parameters
    ----------
    timing_recovery : bool
        If True, use decode_bits_with_timing (DLL tracker — models hardware modem).
        If False, use decode_bits with fixed timing (worst-case: no tracking).
    """
    g = np.random.default_rng(42_000 + seed * 1000 + gross_bps)
    tx_bits = g.integers(0, 2, size=N_BITS).astype(np.int32)

    # Encode
    audio = pm.encode_bits(tx_bits, bit_rate=gross_bps, tones=tones, fs=48_000)

    # Full chain: tape core + capture stage
    out_audio, _sr, _diag = full_chain(audio, TAPE_PRESET, scenario_key, seed=seed)

    # Normalize output to unit peak before decoding (compensates for AGC gain shifts)
    peak = float(np.max(np.abs(out_audio)))
    if peak > 0.0:
        out_audio = out_audio / peak

    # Decode
    if timing_recovery:
        rx_bits = pm.decode_bits_with_timing(
            out_audio, bit_rate=gross_bps, tones=tones, fs=48_000, n_bits=N_BITS,
        )
    else:
        rx_bits = pm.decode_bits(
            out_audio, bit_rate=gross_bps, tones=tones, fs=48_000, n_bits=N_BITS,
        )

    return pm.ber(tx_bits, rx_bits)


# ---------------------------------------------------------------------------
# Shannon ceiling
# ---------------------------------------------------------------------------

def _shannon_bps(snr_db: float, bw_hz: float) -> float:
    """Shannon-Hartley capacity in bps."""
    snr_linear = 10.0 ** (snr_db / 10.0)
    return bw_hz * math.log2(1.0 + snr_linear)


# ---------------------------------------------------------------------------
# Main experiment loop
# ---------------------------------------------------------------------------

def run() -> list[dict]:
    ensure_dirs()

    print("=" * 72)
    print("Experiment C — Reliable-Rate -> MB-per-Cassette")
    print(f"Tape preset: {TAPE_PRESET}  |  N={N_SEEDS} seeds  |  {N_BITS} bits/seed")
    print("=" * 72)

    # Structure: ber_table[scenario][rate] = list of BER values (over seeds)
    # Two modes: fixed timing (no tracking) and timing recovery (DLL)
    ber_table_fixed:   dict[str, dict[int, list[float]]] = {}
    ber_table_tracked: dict[str, dict[int, list[float]]] = {}

    scenario_keys = list(CAPTURE_SCENARIOS.keys())

    for scenario in scenario_keys:
        ber_table_fixed[scenario]   = {}
        ber_table_tracked[scenario] = {}
        bw = SCENARIO_BW[scenario]
        print(f"\n[{scenario}]  usable BW={bw/1000:.1f} kHz")

        for gross_bps in CANDIDATE_RATES:
            cfg = _modem_config(scenario, gross_bps)
            if cfg is None:
                print(f"  {gross_bps:6d} bps — SKIP (tones exceed BW)")
                ber_table_fixed[scenario][gross_bps]   = [1.0] * N_SEEDS
                ber_table_tracked[scenario][gross_bps] = [1.0] * N_SEEDS
                continue

            tones, M = cfg
            bps_label = f"{gross_bps:6d} bps ({M}-FSK, tones=[{', '.join(f'{f:.0f}' for f in tones)}])"
            bers_fixed   = []
            bers_tracked = []
            for seed in range(N_SEEDS):
                bf = _measure_ber_one(scenario, gross_bps, tones, seed, timing_recovery=False)
                bt = _measure_ber_one(scenario, gross_bps, tones, seed, timing_recovery=True)
                bers_fixed.append(bf)
                bers_tracked.append(bt)
            mean_fixed   = float(np.mean(bers_fixed))
            mean_tracked = float(np.mean(bers_tracked))
            ber_table_fixed[scenario][gross_bps]   = bers_fixed
            ber_table_tracked[scenario][gross_bps] = bers_tracked
            print(
                f"  {bps_label}  "
                f"BER_fixed={mean_fixed:.2e}  BER_tracked={mean_tracked:.2e}"
            )

    # Use timing-tracked BER as primary (models a real hardware modem with DLL)
    ber_table = ber_table_tracked

    # ---------------------------------------------------------------------------
    # Find reliable rates and project capacity
    # ---------------------------------------------------------------------------

    summary_rows = []
    for scenario in scenario_keys:
        bw = SCENARIO_BW[scenario]
        # SNR for Shannon: use tape "normal" SNR (42 dB)
        # (capture stages add very little extra noise for usb/phone_custom, more for lossy)
        # Rough effective SNR: for lossy scenarios degrade by ~6 dB (AAC/Opus artefacts)
        eff_snr = NORMAL_TAPE_SNR_DB
        if scenario == "phone_voice_recorder_aac":
            eff_snr -= 6.0   # codec artefacts lower effective SNR
        elif scenario == "phone_voip_opus_narrow":
            eff_snr -= 12.0  # more destructive codec + narrowband
        shannon = _shannon_bps(eff_snr, bw)

        # Find highest gross rate with mean BER <= threshold
        reliable_loose = 0
        reliable_strict = 0
        for gross_bps in CANDIDATE_RATES:
            mean_ber = float(np.mean(ber_table[scenario][gross_bps]))
            if mean_ber <= BER_THRESH_LOOSE:
                reliable_loose = gross_bps
            if mean_ber <= BER_THRESH_STRICT:
                reliable_strict = gross_bps

        # Net rate = reliable_gross * outer_code_rate * stereo_factor
        def _net(gross):
            return gross * OUTER_CODE_RATE * STEREO_FACTOR

        net_bps_loose  = _net(reliable_loose)
        net_bps_strict = _net(reliable_strict)

        def _mb(net_bps, usable_s):
            return net_bps * usable_s / 8.0 / 1e6

        mb_c60_loose  = _mb(net_bps_loose,  C60_USABLE_S)
        mb_c90_loose  = _mb(net_bps_loose,  C90_USABLE_S)
        mb_c60_strict = _mb(net_bps_strict, C60_USABLE_S)
        mb_c90_strict = _mb(net_bps_strict, C90_USABLE_S)

        pct_c90_loose  = mb_c90_loose  / TARGET_MB * 100.0
        pct_c90_strict = mb_c90_strict / TARGET_MB * 100.0

        summary_rows.append({
            "scenario":               scenario,
            "usable_bw_hz":           bw,
            "reliable_gross_bps_1e3": reliable_loose,
            "reliable_gross_bps_1e4": reliable_strict,
            "net_bps_stereo_1e3":     net_bps_loose,
            "net_bps_stereo_1e4":     net_bps_strict,
            "MB_C60_1e3":             round(mb_c60_loose,  3),
            "MB_C90_1e3":             round(mb_c90_loose,  3),
            "MB_C60_1e4":             round(mb_c60_strict, 3),
            "MB_C90_1e4":             round(mb_c90_strict, 3),
            "pct_target_C90_1e3":     round(pct_c90_loose,  1),
            "pct_target_C90_1e4":     round(pct_c90_strict, 1),
            "shannon_bps":            round(shannon),
        })

    # ---------------------------------------------------------------------------
    # Print table
    # ---------------------------------------------------------------------------

    print("\n")
    print("=" * 72)
    print("SUMMARY TABLE — Reliable rates & MB-per-cassette (outer code rate=0.8, stereo)")
    print("=" * 72)
    hdr = (
        f"{'Scenario':<30} {'Rel@1e-3':>9} {'Rel@1e-4':>9} "
        f"{'Net bps':>9} {'MB/C90':>7} {'%Target':>8} {'Shannon':>10}"
    )
    print(hdr)
    print("-" * 72)
    for r in summary_rows:
        fits = "PASS" if r["pct_target_C90_1e3"] >= 100.0 else "FAIL"
        print(
            f"{r['scenario']:<30} "
            f"{r['reliable_gross_bps_1e3']:>9} "
            f"{r['reliable_gross_bps_1e4']:>9} "
            f"{r['net_bps_stereo_1e3']:>9.0f} "
            f"{r['MB_C90_1e3']:>7.3f} "
            f"{r['pct_target_C90_1e3']:>7.1f}% "
            f"{r['shannon_bps']:>9}  {fits}"
        )
    print("-" * 72)
    print(f"  Target: {TARGET_MB} MB on one C90 cassette")
    print(f"  Outer FEC rate: {OUTER_CODE_RATE}  |  Stereo factor: {STEREO_FACTOR}x")
    print(f"  C90 usable: {C90_USABLE_S:.0f}s  |  C60 usable: {C60_USABLE_S:.0f}s")
    print("=" * 72)

    # ---------------------------------------------------------------------------
    # Write CSV
    # ---------------------------------------------------------------------------

    write_csv(DATA / "exp_capacity_cliff.csv", summary_rows)
    print(f"\nCSV -> {DATA / 'exp_capacity_cliff.csv'}")

    # ---------------------------------------------------------------------------
    # Plot: two-panel figure
    # ---------------------------------------------------------------------------

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # --- Panel 1: BER vs gross bit rate, per scenario ---
    ax1 = axes[0]
    colors = ["tab:blue", "tab:green", "tab:orange", "tab:red"]
    labels = {
        "usb_soundcard":            "USB soundcard",
        "phone_custom_pcm":         "Phone custom PCM",
        "phone_voice_recorder_aac": "Phone voice recorder (AAC 64k)",
        "phone_voip_opus_narrow":   "Phone VoIP Opus (24k)",
    }

    for color, scenario in zip(colors, scenario_keys):
        mean_bers_tracked = [float(np.mean(ber_table_tracked[scenario][r])) for r in CANDIDATE_RATES]
        mean_bers_fixed   = [float(np.mean(ber_table_fixed[scenario][r]))   for r in CANDIDATE_RATES]
        ax1.plot(
            CANDIDATE_RATES, mean_bers_tracked,
            marker="o", color=color, label=f"{labels[scenario]} (DLL)", linewidth=1.8,
        )
        ax1.plot(
            CANDIDATE_RATES, mean_bers_fixed,
            marker="x", color=color, linestyle="--", linewidth=1.0, alpha=0.55,
            label=f"{labels[scenario]} (fixed)",
        )

    ax1.axhline(BER_THRESH_LOOSE,  color="gray", linestyle="--", linewidth=1.2,
                label=f"BER={BER_THRESH_LOOSE:.0e} (loose)")
    ax1.axhline(BER_THRESH_STRICT, color="black", linestyle=":",  linewidth=1.2,
                label=f"BER={BER_THRESH_STRICT:.0e} (strict)")
    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlabel("Gross bit rate (bps)", fontsize=10)
    ax1.set_ylabel("Mean BER", fontsize=10)
    ax1.set_title("BER vs Gross Bit Rate by Capture Path\n(tape='normal', N=20 seeds)", fontsize=10)
    ax1.set_xticks(CANDIDATE_RATES)
    ax1.set_xticklabels([str(r) for r in CANDIDATE_RATES], rotation=45, ha="right", fontsize=8)
    ax1.legend(fontsize=7.5, loc="upper left")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.set_ylim(1e-6, 1.2)

    # --- Panel 2: MB per C90 per scenario (bar chart), with target line ---
    ax2 = axes[1]
    x_pos = np.arange(len(scenario_keys))
    mb_vals_loose  = [r["MB_C90_1e3"] for r in summary_rows]
    mb_vals_strict = [r["MB_C90_1e4"] for r in summary_rows]

    bar_w = 0.35
    bars1 = ax2.bar(x_pos - bar_w/2, mb_vals_loose,  bar_w, label="BER≤1e-3 threshold", color=colors, alpha=0.85)
    bars2 = ax2.bar(x_pos + bar_w/2, mb_vals_strict, bar_w, label="BER≤1e-4 threshold",
                    color=colors, alpha=0.45, hatch="//")

    ax2.axhline(TARGET_MB, color="red", linestyle="-", linewidth=2.0, label=f"Target {TARGET_MB} MB")

    # Annotate bars with MB values
    for bar, val in zip(bars1, mb_vals_loose):
        if val > 0:
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                     f"{val:.2f}", ha="center", va="bottom", fontsize=7)
    for bar, val in zip(bars2, mb_vals_strict):
        if val > 0:
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                     f"{val:.2f}", ha="center", va="bottom", fontsize=7)

    short_labels = ["USB\nsoundcard", "Phone\ncustom PCM", "Phone\nAAC 64k", "Phone\nOpus 24k"]
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(short_labels, fontsize=8)
    ax2.set_ylabel("Payload capacity (MB)", fontsize=10)
    ax2.set_title("MB per C90 Cassette by Capture Path\n(stereo, outer FEC rate=0.8)", fontsize=10)
    ax2.legend(fontsize=8)
    ax2.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    plot_path = PLOTS / "exp_capacity_cliff.png"
    fig.savefig(str(plot_path), dpi=150)
    plt.close(fig)
    print(f"Plot  -> {plot_path}")

    return summary_rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
