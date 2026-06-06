"""Experiment A — Impairment Ladder

Starting from perfect transmission, add tape impairments one at a time to
identify which rung causes the biggest reliability drop.

Rungs (additive, each builds on the previous):
  0  perfect        : encode -> decode, NO channel
  1  +bandlimit     : bandwidth_hz=12000 only
  2  +noise         : add snr_db=42
  3  +flutter       : add wow_flutter_wrms=0.0010
  4  +dropouts      : add burst_rate_per_s=0.3, burst_length_ms=6
  5  +speed_offset  : add steady +1.0% speed offset (requires full speed grid)
  6  realistic_all  : combined normal-deck, cross-deck point (+/-1.5% speed)
  7  worn_deck      : snr=36, bw=9000, wf=0.0025, bursts=1.0/10, +/-1.5% speed

N_SEEDS Monte Carlo seeds per rung, payload = cf.cassette_payload("ladderA", 512).
"""

from __future__ import annotations

import sys
import pathlib
import statistics
import time

import numpy as np
from scipy.signal import resample_poly
from fractions import Fraction

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))

import cassette_format as cf
import cassette_e2e as e2e
import channel as ch
from common import DATA, PLOTS, ensure_dirs, write_csv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
N_SEEDS = 24
PAYLOAD_SIZE = 512
PAYLOAD = cf.cassette_payload("ladderA", PAYLOAD_SIZE)
FS = 48_000

# Speed grids
TRIVIAL_GRID = (1.0, 1.0001, 1.0)   # effectively ratio=1.0 only
FULL_GRID_1   = (0.94, 1.06, 0.005)  # +/-6% for cross-deck 1.5% offset
# A tighter grid used for known +1% offset (saves time vs full +/-6%)
GRID_1PCT     = (0.97, 1.03, 0.003)


def resample_speed(audio: np.ndarray, speed_ratio: float) -> np.ndarray:
    """Simulate tape running faster by speed_ratio: compress the signal in time.
    A ratio of 1.01 means the tape ran 1% fast -> we need to stretch it back,
    i.e. resample by 1/speed_ratio to restore pitch/timing."""
    if abs(speed_ratio - 1.0) < 1e-9:
        return audio
    # speed_ratio > 1 -> signal is compressed in time -> resample_poly by 1/ratio
    ratio = 1.0 / speed_ratio
    frac = Fraction(ratio).limit_denominator(2000)
    up, down = frac.numerator, frac.denominator
    return resample_poly(audio.astype(np.float64), up, down).astype(np.float32)


# ---------------------------------------------------------------------------
# Rung definitions
# ---------------------------------------------------------------------------
# Each rung is a callable: seed_offset -> (audio_post_channel, measured_snr_db, measured_wf_pct)
# We encode once, then apply channel per seed.

def encode_once() -> np.ndarray:
    return cf.encode_audio(PAYLOAD).astype(np.float32)


CLEAN_AUDIO = None  # lazy init once


def get_clean() -> np.ndarray:
    global CLEAN_AUDIO
    if CLEAN_AUDIO is None:
        CLEAN_AUDIO = encode_once()
    return CLEAN_AUDIO


def run_rung_0(seed: int):
    """Perfect: no channel."""
    audio = get_clean().copy()
    return audio, float("nan"), 0.0


def run_rung_1(seed: int):
    """+ bandlimit only: bw=12000, snr=120dB (effectively none), wf=0, no bursts."""
    audio = get_clean()
    y, diag = ch.cassette_channel_diagnostics(
        audio, fs=FS,
        snr_db=120.0,
        wow_flutter_wrms=0.0,
        bandwidth_hz=12_000.0,
        burst_rate_per_s=0.0,
        burst_length_ms=0.0,
        seed_offset=seed,
    )
    return y.astype(np.float32), diag["measured_snr_db"], diag["measured_wow_flutter_wrms_pct"]


def run_rung_2(seed: int):
    """+ noise: bw=12000, snr=42."""
    audio = get_clean()
    y, diag = ch.cassette_channel_diagnostics(
        audio, fs=FS,
        snr_db=42.0,
        wow_flutter_wrms=0.0,
        bandwidth_hz=12_000.0,
        burst_rate_per_s=0.0,
        burst_length_ms=0.0,
        seed_offset=seed,
    )
    return y.astype(np.float32), diag["measured_snr_db"], diag["measured_wow_flutter_wrms_pct"]


def run_rung_3(seed: int):
    """+ flutter: bw=12000, snr=42, wf=0.0010."""
    audio = get_clean()
    y, diag = ch.cassette_channel_diagnostics(
        audio, fs=FS,
        snr_db=42.0,
        wow_flutter_wrms=0.0010,
        bandwidth_hz=12_000.0,
        burst_rate_per_s=0.0,
        burst_length_ms=0.0,
        seed_offset=seed,
    )
    return y.astype(np.float32), diag["measured_snr_db"], diag["measured_wow_flutter_wrms_pct"]


def run_rung_4(seed: int):
    """+ dropouts: bw=12000, snr=42, wf=0.0010, bursts=0.3/6ms."""
    audio = get_clean()
    y, diag = ch.cassette_channel_diagnostics(
        audio, fs=FS,
        snr_db=42.0,
        wow_flutter_wrms=0.0010,
        bandwidth_hz=12_000.0,
        burst_rate_per_s=0.3,
        burst_length_ms=6.0,
        seed_offset=seed,
    )
    return y.astype(np.float32), diag["measured_snr_db"], diag["measured_wow_flutter_wrms_pct"]


def run_rung_5(seed: int):
    """+ speed offset: add steady +1.0% (also rng-signed per seed for variety)."""
    audio = get_clean()
    # Apply tape channel first
    y, diag = ch.cassette_channel_diagnostics(
        audio, fs=FS,
        snr_db=42.0,
        wow_flutter_wrms=0.0010,
        bandwidth_hz=12_000.0,
        burst_rate_per_s=0.3,
        burst_length_ms=6.0,
        seed_offset=seed,
    )
    # Steady speed offset: +1.0% (playback deck faster than record)
    speed_ratio = 1.01
    y_shifted = resample_speed(y.astype(np.float32), speed_ratio)
    return y_shifted, diag["measured_snr_db"], diag["measured_wow_flutter_wrms_pct"]


def run_rung_6(seed: int):
    """realistic_all: normal deck + cross-deck speed (drawn from +/-1.5%)."""
    audio = get_clean()
    rng = np.random.default_rng(42 + seed)
    speed_offset = rng.uniform(-0.015, 0.015)
    speed_ratio = 1.0 + speed_offset
    y, diag = ch.cassette_channel_diagnostics(
        audio, fs=FS,
        snr_db=42.0,
        wow_flutter_wrms=0.0010,
        bandwidth_hz=12_000.0,
        burst_rate_per_s=0.3,
        burst_length_ms=6.0,
        seed_offset=seed,
    )
    y_shifted = resample_speed(y.astype(np.float32), speed_ratio)
    return y_shifted, diag["measured_snr_db"], diag["measured_wow_flutter_wrms_pct"]


def run_rung_7(seed: int):
    """worn_deck: snr=36, bw=9000, wf=0.0025, bursts=1.0/10ms, +/-1.5% speed."""
    audio = get_clean()
    rng = np.random.default_rng(99 + seed)
    speed_offset = rng.uniform(-0.015, 0.015)
    speed_ratio = 1.0 + speed_offset
    y, diag = ch.cassette_channel_diagnostics(
        audio, fs=FS,
        snr_db=36.0,
        wow_flutter_wrms=0.0025,
        bandwidth_hz=9_000.0,
        burst_rate_per_s=1.0,
        burst_length_ms=10.0,
        seed_offset=seed,
    )
    y_shifted = resample_speed(y.astype(np.float32), speed_ratio)
    return y_shifted, diag["measured_snr_db"], diag["measured_wow_flutter_wrms_pct"]


RUNGS = [
    (0, "perfect",        run_rung_0, TRIVIAL_GRID),
    (1, "+bandlimit",     run_rung_1, TRIVIAL_GRID),
    (2, "+noise",         run_rung_2, TRIVIAL_GRID),
    (3, "+flutter",       run_rung_3, TRIVIAL_GRID),
    (4, "+dropouts",      run_rung_4, TRIVIAL_GRID),
    (5, "+speed_offset",  run_rung_5, GRID_1PCT),
    (6, "realistic_all",  run_rung_6, FULL_GRID_1),
    (7, "worn_deck",      run_rung_7, FULL_GRID_1),
]

# Total expected frames in a 512-byte payload
_TOTAL_FRAMES: int | None = None


def total_frames() -> int:
    global _TOTAL_FRAMES
    if _TOTAL_FRAMES is None:
        r = e2e.robust_decode(get_clean(), FS, speed_search=TRIVIAL_GRID)
        if r.result.header is not None:
            _TOTAL_FRAMES = r.result.header.frame_count
        else:
            _TOTAL_FRAMES = max(1, (PAYLOAD_SIZE + 255) // 256)
    return _TOTAL_FRAMES


# ---------------------------------------------------------------------------
# Monte Carlo runner
# ---------------------------------------------------------------------------

def run_mc(rung_fn, speed_grid, n_seeds=N_SEEDS):
    complete_list = []
    frame_recovery_list = []
    ber_list = []
    snr_list = []
    wf_list = []

    tf = total_frames()

    for seed in range(n_seeds):
        audio, msnr, mwf = rung_fn(seed)
        rr = e2e.robust_decode(audio, FS, speed_search=speed_grid)
        cmp = e2e.compare_payload(PAYLOAD, rr.result)

        complete_list.append(1 if cmp["complete"] else 0)
        frame_recovery_list.append(rr.result.recovered_frames / tf if tf > 0 else 0.0)
        ber_list.append(cmp["byte_error_rate"])
        if not np.isnan(msnr):
            snr_list.append(msnr)
        wf_list.append(mwf)

    return {
        "clean_decode_prob": statistics.mean(complete_list),
        "mean_frame_recovery": statistics.mean(frame_recovery_list),
        "mean_byte_error_rate": statistics.mean(ber_list),
        "measured_snr_db": statistics.mean(snr_list) if snr_list else float("nan"),
        "measured_wf_pct": statistics.mean(wf_list),
    }


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def make_plot(rows: list[dict]) -> pathlib.Path:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    names = [r["rung_name"] for r in rows]
    cdp   = [r["clean_decode_prob"] for r in rows]
    mfr   = [r["mean_frame_recovery"] for r in rows]
    xs    = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(10, 5))
    width = 0.35
    b1 = ax.bar([x - width/2 for x in xs], cdp, width, label="clean_decode_prob", color="#2196F3", alpha=0.85)
    b2 = ax.bar([x + width/2 for x in xs], mfr, width, label="mean_frame_recovery", color="#FF9800", alpha=0.85)

    # Annotate bars
    for rect, val in zip(b1, cdp):
        ax.text(rect.get_x() + rect.get_width()/2, rect.get_height() + 0.01,
                f"{val:.2f}", ha="center", va="bottom", fontsize=7, color="#1565C0")
    for rect, val in zip(b2, mfr):
        ax.text(rect.get_x() + rect.get_width()/2, rect.get_height() + 0.01,
                f"{val:.2f}", ha="center", va="bottom", fontsize=7, color="#E65100")

    ax.set_xticks(xs)
    ax.set_xticklabels([f"R{r['rung_id']}\n{r['rung_name']}" for r in rows], fontsize=8)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Probability / Fraction")
    ax.set_title(f"Experiment A — Impairment Ladder (N={N_SEEDS} seeds, {PAYLOAD_SIZE}B payload)")
    ax.legend(loc="upper right", fontsize=9)
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1))
    ax.grid(axis="y", alpha=0.3)

    out = PLOTS / "exp_impairment_ladder.png"
    fig.tight_layout()
    fig.savefig(str(out), dpi=150)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ensure_dirs()
    # Warm up the lazy globals
    _ = get_clean()
    _ = total_frames()

    rows = []
    t0 = time.time()

    print(f"\nExperiment A — Impairment Ladder  (N={N_SEEDS} seeds, payload={PAYLOAD_SIZE}B)")
    print(f"{'Rung':<4} {'Name':<18} {'CleanDec':>9} {'FrameRec':>9} {'BER':>9} "
          f"{'SNR(dB)':>8} {'WF(%)':>7}  {'Time':>6}")
    print("-" * 80)

    for rung_id, rung_name, rung_fn, speed_grid in RUNGS:
        t1 = time.time()
        stats = run_mc(rung_fn, speed_grid, n_seeds=N_SEEDS)
        elapsed = time.time() - t1
        row = {
            "rung_id": rung_id,
            "rung_name": rung_name,
            "clean_decode_prob": round(stats["clean_decode_prob"], 4),
            "mean_frame_recovery": round(stats["mean_frame_recovery"], 4),
            "mean_byte_error_rate": round(stats["mean_byte_error_rate"], 6),
            "measured_snr_db": round(stats["measured_snr_db"], 2) if not np.isnan(stats["measured_snr_db"]) else float("nan"),
            "measured_wf_pct": round(stats["measured_wf_pct"], 4),
            "n_seeds": N_SEEDS,
        }
        rows.append(row)
        snr_str = f"{stats['measured_snr_db']:.1f}" if not np.isnan(stats["measured_snr_db"]) else "  N/A"
        print(f"  {rung_id:<2}  {rung_name:<18} {stats['clean_decode_prob']:>8.3f}"
              f"  {stats['mean_frame_recovery']:>8.3f}  {stats['mean_byte_error_rate']:>8.5f}"
              f"  {snr_str:>7}  {stats['measured_wf_pct']:>6.4f}  {elapsed:>5.1f}s")

    total_time = time.time() - t0
    print("-" * 80)
    print(f"Total elapsed: {total_time:.1f}s\n")

    # Identify biggest drop
    probs = [r["clean_decode_prob"] for r in rows]
    drops = [probs[i-1] - probs[i] for i in range(1, len(probs))]
    max_drop_idx = int(np.argmax(drops))  # index into drops (= rung i+1)
    max_drop_rung = rows[max_drop_idx + 1]
    print(f"Biggest single drop: rung {max_drop_rung['rung_id']} "
          f"({max_drop_rung['rung_name']}) "
          f"by {drops[max_drop_idx]:.3f} "
          f"(from {probs[max_drop_idx]:.3f} to {probs[max_drop_idx+1]:.3f})\n")

    # CSV
    csv_path = DATA / "exp_impairment_ladder.csv"
    write_csv(csv_path, rows)
    print(f"CSV: {csv_path}")

    # Plot
    plot_path = make_plot(rows)
    print(f"Plot: {plot_path}\n")

    return rows


if __name__ == "__main__":
    main()
