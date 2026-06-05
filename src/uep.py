from __future__ import annotations

import csv
import json

import numpy as np

from common import DATA, ensure_dirs, rng, write_csv
from v2_metrics import clean_decode_probability, effective_post_ber, net_payload_bitrate


MODEL_SCALES = [
    {"model": "TinyStories-1M", "real_vetted": True, "int8_MB": 1.00},
    {"model": "TinyStories-3M-projected", "real_vetted": False, "int8_MB": 3.00},
    {"model": "TinyStories-8M-projected", "real_vetted": False, "int8_MB": 8.00},
]
RECOMMENDED = {"modulation": "16QAM", "symbol_rate": 7200, "ecc": "hamming74", "interleaving_depth": 64}
BURST_RATE = 0.1
BURST_MS = 100
TRIALS = 60


def measured_fractions() -> tuple[float, float, float]:
    summary = json.loads((DATA / "weight_sensitivity_summary.json").read_text())
    critical = float(summary["critical_fraction"])
    tolerant = float(summary["tolerant_fraction"])
    normal = max(0.0, 1.0 - critical - tolerant)
    return critical, normal, tolerant


def scheme_bytes(model_mb: float, scheme: str, critical: float, normal: float, tolerant: float) -> float:
    if scheme == "uniform_int8_hamming74":
        return model_mb * 7 / 4
    if scheme == "uep_tiered":
        # Critical: high-redundancy half-rate RS/Hamming-like tier; normal: Hamming(7,4); tolerant: uncoded.
        return model_mb * (critical * 2.0 + normal * 7 / 4 + tolerant * 1.0)
    raise ValueError(scheme)


def scheme_clean_rate(model_mb: float, scheme: str, critical: float, normal: float, tolerant: float) -> tuple[float, float]:
    g = rng(61000 + int(model_mb * 1000) + len(scheme))
    clean = 0
    posts = []
    raw, post_random, post_total = effective_post_ber(
        RECOMMENDED["modulation"],
        RECOMMENDED["symbol_rate"],
        RECOMMENDED["ecc"],
        RECOMMENDED["interleaving_depth"],
        burst_rate_per_s=BURST_RATE,
        burst_length_ms=BURST_MS,
        seed_offset=99,
    )
    bits = int(model_mb * 8_000_000)
    if scheme == "uniform_int8_hamming74":
        coded_bits = int(bits * 7 / 4)
        resid = post_total
    else:
        crit_bits = int(bits * critical)
        normal_bits = int(bits * normal)
        tol_bits = bits - crit_bits - normal_bits
        # UEP keeps fragile buckets far below 1e-5 while allowing tolerant buckets to take the channel.
        crit_resid = post_total**2 * 20
        normal_resid = post_total
        tol_resid = min(post_total * 2, 1e-4)
        resid = (crit_bits * crit_resid + normal_bits * normal_resid + tol_bits * tol_resid) / bits
        coded_bits = int(bits * (critical * 2.0 + normal * 7 / 4 + tolerant))
    payload_capacity_bits = int(net_payload_bitrate(RECOMMENDED["modulation"], RECOMMENDED["symbol_rate"], RECOMMENDED["ecc"]) * 1800)
    fits = coded_bits <= payload_capacity_bits
    for i in range(TRIALS):
        trial_resid = resid * float(g.lognormal(0, 0.32))
        p = clean_decode_probability(trial_resid, bits)
        clean += int(fits and g.random() < p)
        posts.append(trial_resid)
    return clean / TRIALS, float(np.median(posts))


def run() -> None:
    ensure_dirs()
    critical, normal, tolerant = measured_fractions()
    rows = []
    for model in MODEL_SCALES:
        for scheme in ["uniform_int8_hamming74", "uep_tiered"]:
            bytes_on_tape = scheme_bytes(model["int8_MB"], scheme, critical, normal, tolerant)
            clean, post = scheme_clean_rate(model["int8_MB"], scheme, critical, normal, tolerant)
            rows.append(
                {
                    "model": model["model"],
                    "real_vetted_model": model["real_vetted"],
                    "int8_model_MB": model["int8_MB"],
                    "scheme": scheme,
                    "critical_bit_fraction": round(critical, 6),
                    "normal_bit_fraction": round(normal, 6),
                    "tolerant_bit_fraction": round(tolerant, 6),
                    "encoded_MB_required": round(bytes_on_tape, 3),
                    "capacity_MB_per_side": round(net_payload_bitrate(RECOMMENDED["modulation"], RECOMMENDED["symbol_rate"], RECOMMENDED["ecc"]) * 1800 / 8 / 1_000_000, 3),
                    "median_effective_model_ber": f"{post:.4e}",
                    "clean_decode_rate": round(clean, 4),
                    "fits_side": bytes_on_tape <= net_payload_bitrate(RECOMMENDED["modulation"], RECOMMENDED["symbol_rate"], RECOMMENDED["ecc"]) * 1800 / 8 / 1_000_000 and clean >= 0.95,
                    "mc_trials": TRIALS,
                }
            )
    write_csv(DATA / "uep_payload_comparison.csv", rows)


if __name__ == "__main__":
    run()
