from __future__ import annotations

import math

import matplotlib.pyplot as plt

from common import DATA, PLOTS, append_report, ensure_dirs, rng, write_csv


MODS = {
    "BPSK": 1,
    "QPSK": 2,
    "8PSK": 3,
    "16QAM": 4,
}
RATES = [1200, 2400, 4800, 7200, 9600, 12_000]
BANDWIDTH = 12_000
SNR_DB = 40.0
WOW_FLUTTER_WRMS = 0.0007


def qfunc(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2))


def estimate_ber_conditions(
    mod: str,
    symbol_rate: int,
    snr_db: float = SNR_DB,
    wow_flutter_wrms: float = WOW_FLUTTER_WRMS,
    burst_rate_per_s: float = 0.0,
    burst_length_ms: float = 0.0,
    seed_offset: int = 0,
) -> float:
    bits = MODS[mod]
    occupied = symbol_rate * (1.25 if mod in ("BPSK", "QPSK") else 1.45)
    bandwidth_penalty_db = max(0.0, 18.0 * math.log10(max(occupied / BANDWIDTH, 1.0)))
    timing_penalty_db = 0.7 + 16.0 * (wow_flutter_wrms * symbol_rate / 10.0) ** 1.35
    m_penalty_db = {"BPSK": 0.0, "QPSK": 0.6, "8PSK": 4.8, "16QAM": 7.2}[mod]
    ebn0_db = snr_db - 10 * math.log10(symbol_rate * bits / BANDWIDTH) - bandwidth_penalty_db - timing_penalty_db - m_penalty_db
    ebn0 = 10 ** (ebn0_db / 10)
    base = {"BPSK": qfunc(math.sqrt(2 * ebn0)), "QPSK": qfunc(math.sqrt(2 * ebn0)), "8PSK": 2 * qfunc(math.sqrt(2 * ebn0) * math.sin(math.pi / 8)) / 3, "16QAM": 0.75 * qfunc(math.sqrt(0.8 * ebn0))}[mod]
    g = rng(4000 + seed_offset + symbol_rate + bits)
    flutter_scale = (wow_flutter_wrms / WOW_FLUTTER_WRMS) ** 2.4 if wow_flutter_wrms > 0 else 0.0
    flutter_floor = flutter_scale * (symbol_rate / 12_000) ** 3.1 * {"BPSK": 1.5e-8, "QPSK": 4e-8, "8PSK": 2.5e-6, "16QAM": 8e-6}[mod]
    burst_floor = burst_rate_per_s * (burst_length_ms / 1000.0) * {"BPSK": 0.02, "QPSK": 0.035, "8PSK": 0.07, "16QAM": 0.11}[mod]
    return float(max(base + flutter_floor + burst_floor, 1e-12) * g.lognormal(0, 0.08))


def estimate_ber(mod: str, symbol_rate: int, seed_offset: int = 0) -> float:
    return estimate_ber_conditions(mod, symbol_rate, seed_offset=seed_offset)


def run() -> None:
    ensure_dirs()
    rows = []
    for mod in MODS:
        for rate in RATES:
            ber = estimate_ber(mod, rate)
            rows.append(
                {
                    "modulation": mod,
                    "symbol_rate": rate,
                    "bits_per_symbol": MODS[mod],
                    "raw_bitrate_bps": rate * MODS[mod],
                    "raw_ber": f"{ber:.4e}",
                }
            )

    for row in rows:
        better = [
            r for r in rows
            if float(r["raw_ber"]) <= float(row["raw_ber"]) and r["raw_bitrate_bps"] >= row["raw_bitrate_bps"]
            and (float(r["raw_ber"]) < float(row["raw_ber"]) or r["raw_bitrate_bps"] > row["raw_bitrate_bps"])
        ]
        row["pareto_frontier"] = len(better) == 0
    write_csv(DATA / "modulation_pareto.csv", rows)

    fig, ax = plt.subplots(figsize=(8, 5))
    for mod in MODS:
        xs = [r["raw_bitrate_bps"] for r in rows if r["modulation"] == mod]
        ys = [float(r["raw_ber"]) for r in rows if r["modulation"] == mod]
        ax.plot(xs, ys, marker="o", label=mod)
    front = sorted([r for r in rows if r["pareto_frontier"]], key=lambda r: r["raw_bitrate_bps"])
    ax.plot([r["raw_bitrate_bps"] for r in front], [float(r["raw_ber"]) for r in front], color="black", linewidth=2, label="Pareto frontier")
    ax.set_yscale("log")
    ax.set_xlabel("raw bitrate (bit/s)")
    ax.set_ylabel("raw BER through realistic cassette channel")
    ax.set_title("Modulation/rate Pareto sweep")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "modulation_pareto.png", dpi=160)
    plt.close(fig)

    append_report(
        "Phase 3 - Modulation",
        "The modulation sweep compares BPSK, QPSK, 8PSK, and 16QAM from 1.2 to 12 ksym/s through the realistic cassette channel approximation. "
        "RESULTS/data/modulation_pareto.csv flags non-dominated bitrate/BER points; low-rate PSK dominates reliability while higher-order schemes buy bitrate at a steep BER cost.",
    )


if __name__ == "__main__":
    run()
