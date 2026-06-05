from __future__ import annotations

import math

import numpy as np

from common import rng
from ecc import SIDE_SECONDS, clean_decode_probability, residual_ber
from modulate import MODS, estimate_ber_conditions


V1_RECOMMENDED = {
    "modulation": "16QAM",
    "symbol_rate": 9600,
    "ecc": "hamming74",
    "interleaving_depth": 1,
}


def effective_post_ber(
    modulation: str,
    symbol_rate: int,
    ecc: str,
    interleaving_depth: int,
    snr_db: float = 40.0,
    wow_flutter_wrms: float = 0.0007,
    burst_rate_per_s: float = 0.0,
    burst_length_ms: float = 0.0,
    seed_offset: int = 0,
) -> tuple[float, float, float]:
    raw_random = estimate_ber_conditions(
        modulation,
        symbol_rate,
        snr_db=snr_db,
        wow_flutter_wrms=wow_flutter_wrms,
        seed_offset=seed_offset,
    )
    post_random, _ = residual_ber(raw_random, ecc, interleaving_depth)
    if burst_rate_per_s <= 0 or burst_length_ms <= 0:
        return raw_random, post_random, post_random

    vulnerable = {"none": 1.0, "hamming74": 0.34, "rep3": 0.22, "rep5": 0.13}[ecc]
    mod_sensitivity = {"BPSK": 0.35, "QPSK": 0.55, "8PSK": 0.95, "16QAM": 1.25}[modulation]
    burst_fraction = burst_rate_per_s * (burst_length_ms / 1000.0)
    burst_post = 1.6e-5 * burst_fraction * mod_sensitivity * vulnerable / (interleaving_depth ** 0.9)
    return raw_random + burst_fraction * mod_sensitivity * 0.02, post_random, post_random + burst_post


def net_payload_bitrate(modulation: str, symbol_rate: int, ecc: str) -> float:
    _, code_rate = residual_ber(1e-12, ecc, 1)
    return symbol_rate * MODS[modulation] * code_rate


def payload_bits(modulation: str, symbol_rate: int, ecc: str) -> int:
    return int(net_payload_bitrate(modulation, symbol_rate, ecc) * SIDE_SECONDS)


def simulated_clean_rate(
    modulation: str,
    symbol_rate: int,
    ecc: str,
    interleaving_depth: int,
    snr_db: float = 40.0,
    wow_flutter_wrms: float = 0.0007,
    burst_rate_per_s: float = 0.0,
    burst_length_ms: float = 0.0,
    trials: int = 80,
    seed_offset: int = 0,
) -> tuple[float, float, float]:
    bits = payload_bits(modulation, symbol_rate, ecc)
    g = rng(12000 + seed_offset)
    clean = 0
    posts = []
    raws = []
    for i in range(trials):
        raw, _, post = effective_post_ber(
            modulation,
            symbol_rate,
            ecc,
            interleaving_depth,
            snr_db,
            wow_flutter_wrms,
            burst_rate_per_s,
            burst_length_ms,
            seed_offset + i,
        )
        raw *= float(g.lognormal(0, 0.22))
        post *= float(g.lognormal(0, 0.28))
        p = clean_decode_probability(post, bits)
        clean += int(g.random() < p)
        posts.append(post)
        raws.append(raw)
    return clean / trials, float(np.median(raws)), float(np.median(posts))

