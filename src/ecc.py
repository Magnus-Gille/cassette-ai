from __future__ import annotations

import math

import matplotlib.pyplot as plt

from common import DATA, PLOTS, append_report, ensure_dirs, write_csv
from modulate import MODS, RATES, estimate_ber


PHASE2_TARGET_BER = 3e-6
SIDE_SECONDS = 30 * 60


def residual_ber(raw: float, ecc: str, interleaving: int) -> tuple[float, float]:
    if ecc == "none":
        rate = 1.0
        resid = raw
    elif ecc == "rep3":
        rate = 1 / 3
        resid = 3 * raw**2 * (1 - raw) + raw**3
    elif ecc == "rep5":
        rate = 1 / 5
        resid = 10 * raw**3 * (1 - raw) ** 2 + 5 * raw**4 * (1 - raw) + raw**5
    elif ecc == "hamming74":
        rate = 4 / 7
        resid = 1 - ((1 - raw) ** 7 + 7 * raw * (1 - raw) ** 6)
        resid = min(1.0, resid / 4.0)
    else:
        raise ValueError(ecc)
    burst_relief = max(1.0, math.sqrt(interleaving) / 1.8)
    return resid / burst_relief, rate


def clean_decode_probability(post_ber: float, payload_bits: int) -> float:
    return math.exp(-post_ber * payload_bits)


def run() -> None:
    ensure_dirs()
    eccs = ["none", "hamming74", "rep3", "rep5"]
    interleavers = [1, 16, 64]
    rows = []
    for mod in MODS:
        for sym in RATES:
            raw = estimate_ber(mod, sym, seed_offset=88)
            for ecc in eccs:
                for inter in interleavers:
                    post, code_rate = residual_ber(raw, ecc, inter)
                    net = sym * MODS[mod] * code_rate
                    payload_bits = int(net * SIDE_SECONDS)
                    prob = clean_decode_probability(post, payload_bits)
                    rows.append(
                        {
                            "modulation": mod,
                            "symbol_rate": sym,
                            "ecc": ecc,
                            "interleaving_depth": inter,
                            "raw_ber": f"{raw:.4e}",
                            "post_ecc_ber": f"{post:.4e}",
                            "net_payload_bitrate_bps": round(net, 2),
                            "payload_MB_per_C60_side": round(net * SIDE_SECONDS / 8 / 1_000_000, 3),
                            "clean_decode_probability_per_side": round(prob, 6),
                            "hits_phase2_ber_target": post <= PHASE2_TARGET_BER,
                        }
                    )
    write_csv(DATA / "ecc_combinations.csv", rows)

    fig, ax = plt.subplots(figsize=(8, 5))
    for ecc in eccs:
        subset = [r for r in rows if r["ecc"] == ecc and r["interleaving_depth"] == 64]
        ax.scatter([r["net_payload_bitrate_bps"] for r in subset], [float(r["post_ecc_ber"]) for r in subset], label=f"{ecc}, I=64", s=28)
    ax.axhline(PHASE2_TARGET_BER, color="black", linestyle="--", linewidth=1, label="Phase 2 BER target")
    ax.set_yscale("log")
    ax.set_xlabel("net payload bitrate (bit/s)")
    ax.set_ylabel("post-ECC BER")
    ax.set_title("ECC combinations")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(PLOTS / "ecc_combinations.png", dpi=160)
    plt.close(fig)

    viable = [r for r in rows if r["hits_phase2_ber_target"]]
    best = max(viable, key=lambda r: r["net_payload_bitrate_bps"]) if viable else None
    if best:
        msg = (
            f"The strongest simulated combinations meet the TinyStories-1M-INT4 Phase 2 BER target of {PHASE2_TARGET_BER:.1e}. "
            f"The highest-net-rate flagged tuple is {best['modulation']} at {best['symbol_rate']} sym/s with {best['ecc']} and "
            f"interleaving {best['interleaving_depth']}, yielding {best['net_payload_bitrate_bps']} bit/s and "
            f"{best['payload_MB_per_C60_side']} MB per C-60 side before packet/file overhead. The flag is a functional-BER screen; "
            f"the final pipeline additionally requires high clean-decode probability for a full side."
        )
    else:
        msg = f"No simulated ECC tuple reached the Phase 2 BER target of {PHASE2_TARGET_BER:.1e}; this would trigger the early-exit negative answer."
    append_report("Phase 4 - ECC", msg)


if __name__ == "__main__":
    run()
