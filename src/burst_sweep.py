from __future__ import annotations

import matplotlib.pyplot as plt

from common import DATA, PLOTS, ensure_dirs, write_csv
from v2_metrics import V1_RECOMMENDED, simulated_clean_rate


BURSTS = [
    (0.1, 10),
    (0.1, 100),
    (0.5, 50),
    (1.0, 100),
    (2.0, 500),
]
INTERLEAVERS = [1, 4, 16, 64]


def run() -> None:
    ensure_dirs()
    rows = []
    for rate, length in BURSTS:
        for inter in INTERLEAVERS:
            clean, raw, post = simulated_clean_rate(
                V1_RECOMMENDED["modulation"],
                V1_RECOMMENDED["symbol_rate"],
                V1_RECOMMENDED["ecc"],
                inter,
                burst_rate_per_s=rate,
                burst_length_ms=length,
                trials=80,
                seed_offset=int(rate * 1000 + length * 10 + inter),
            )
            rows.append(
                {
                    "modulation": V1_RECOMMENDED["modulation"],
                    "symbol_rate": V1_RECOMMENDED["symbol_rate"],
                    "ecc": V1_RECOMMENDED["ecc"],
                    "burst_rate_per_s": rate,
                    "burst_length_ms": length,
                    "interleaving_depth": inter,
                    "median_raw_ber": f"{raw:.4e}",
                    "median_post_ecc_ber": f"{post:.4e}",
                    "clean_decode_rate": round(clean, 4),
                }
            )
    write_csv(DATA / "burst_interleaving.csv", rows)

    fig, ax = plt.subplots(figsize=(8, 5))
    for rate, length in BURSTS:
        subset = [r for r in rows if float(r["burst_rate_per_s"]) == rate and int(r["burst_length_ms"]) == length]
        ax.plot([int(r["interleaving_depth"]) for r in subset], [float(r["clean_decode_rate"]) for r in subset], marker="o", label=f"{rate}/s, {length} ms")
    ax.set_xscale("log", base=4)
    ax.set_xticks(INTERLEAVERS)
    ax.set_xticklabels([str(i) for i in INTERLEAVERS])
    ax.set_xlabel("interleaving depth")
    ax.set_ylabel("clean-decode rate per C-60 side")
    ax.set_title("Interleaving under bursty dropouts")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(PLOTS / "clean_decode_vs_interleaving_under_bursts.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()

