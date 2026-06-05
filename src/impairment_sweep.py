from __future__ import annotations

import matplotlib.pyplot as plt

from common import DATA, PLOTS, ensure_dirs, write_csv
from v2_metrics import V1_RECOMMENDED, simulated_clean_rate


SNRS = [25, 30, 35, 40, 45, 50]
WFS = [0.0004, 0.0007, 0.0012, 0.0025, 0.0050]


def crossing(rows: list[dict], threshold: float) -> str:
    ordered = sorted(rows, key=lambda r: (float(r["snr_db"]), -float(r["wow_flutter_wrms_pct"])))
    bad = [r for r in ordered if float(r["clean_decode_rate"]) < threshold]
    if not bad:
        return "not crossed in sweep"
    r = bad[-1]
    return f"SNR {r['snr_db']} dB / W&F {r['wow_flutter_wrms_pct']}%"


def run() -> None:
    ensure_dirs()
    rows = []
    for snr in SNRS:
        for wf in WFS:
            clean, raw, post = simulated_clean_rate(
                V1_RECOMMENDED["modulation"],
                V1_RECOMMENDED["symbol_rate"],
                V1_RECOMMENDED["ecc"],
                V1_RECOMMENDED["interleaving_depth"],
                snr_db=snr,
                wow_flutter_wrms=wf,
                trials=80,
                seed_offset=int(snr * 10000 + wf * 1e7),
            )
            rows.append(
                {
                    "modulation": V1_RECOMMENDED["modulation"],
                    "symbol_rate": V1_RECOMMENDED["symbol_rate"],
                    "ecc": V1_RECOMMENDED["ecc"],
                    "interleaving_depth": V1_RECOMMENDED["interleaving_depth"],
                    "snr_db": snr,
                    "wow_flutter_wrms_pct": round(wf * 100, 4),
                    "median_raw_ber": f"{raw:.4e}",
                    "median_post_ecc_ber": f"{post:.4e}",
                    "clean_decode_rate": round(clean, 4),
                }
            )
    write_csv(DATA / "impairment_sweep.csv", rows)

    fig, ax = plt.subplots(figsize=(8, 5))
    for wf in WFS:
        subset = [r for r in rows if abs(float(r["wow_flutter_wrms_pct"]) - wf * 100) < 1e-9]
        ax.plot([float(r["snr_db"]) for r in subset], [float(r["clean_decode_rate"]) for r in subset], marker="o", label=f"W&F {wf*100:.2f}%")
    for y in [0.99, 0.95, 0.5]:
        ax.axhline(y, color="black", linestyle="--", linewidth=0.8, alpha=0.45)
    ax.set_xlabel("SNR (dB)")
    ax.set_ylabel("clean-decode rate per C-60 side")
    ax.set_title("Clean decode vs impairment, v1 tuple")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(PLOTS / "clean_decode_vs_impairment.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()

