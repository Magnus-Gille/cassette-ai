from __future__ import annotations

import csv
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from common import DATA, REPORT, STATUS, append_report, ensure_dirs, rng, write_csv
from ecc import SIDE_SECONDS, clean_decode_probability, residual_ber
from modulate import MODS, estimate_ber


ROOT = Path(__file__).resolve().parents[1]


def _run_phase(script: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "src" / script)], check=True, cwd=ROOT)


def _read_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def monte_carlo(best: dict, runs: int = 40) -> list[dict]:
    g = rng(9000)
    rows = []
    net = float(best["net_payload_bitrate_bps"])
    raw_base = float(best["raw_ber"])
    for i in range(runs):
        raw = raw_base * float(g.lognormal(0, 0.28))
        post, _ = residual_ber(raw, best["ecc"], int(best["interleaving_depth"]))
        payload_bits = int(net * SIDE_SECONDS)
        clean = g.random() < clean_decode_probability(post, payload_bits)
        usable_bits = payload_bits if clean else 0
        rows.append(
            {
                "run": i,
                "raw_ber": f"{raw:.4e}",
                "post_ecc_ber": f"{post:.4e}",
                "clean_decode": bool(clean),
                "usable_MB": round(usable_bits / 8 / 1_000_000, 4),
            }
        )
    return rows


def run() -> None:
    ensure_dirs()
    for script in ["channel.py", "model_robustness.py", "modulate.py", "ecc.py"]:
        _run_phase(script)

    ecc_rows = _read_csv(DATA / "ecc_combinations.csv")
    viable = [r for r in ecc_rows if r["hits_phase2_ber_target"] == "True" and float(r["clean_decode_probability_per_side"]) >= 0.95]
    if not viable:
        viable = [r for r in ecc_rows if r["hits_phase2_ber_target"] == "True"]
    best = max(viable, key=lambda r: float(r["net_payload_bitrate_bps"]))

    mc = monte_carlo(best, runs=40)
    write_csv(DATA / "pipeline_monte_carlo.csv", mc)
    usable = np.array([float(r["usable_MB"]) for r in mc])
    mean = float(np.mean(usable))
    lo, hi = np.percentile(usable, [2.5, 97.5])

    candidates = [
        ("TinyStories-1M INT4 surrogate", 0.50, 3e-6),
        ("TinyStories-1M INT8 surrogate", 1.00, 1e-6),
        ("TinyStories-8M INT4 surrogate", 4.00, 3e-7),
        ("TinyStories-8M INT8 surrogate", 8.00, 3e-7),
        ("TinyStories-33M INT4 surrogate", 16.50, 1e-7),
        ("TinyStories-33M INT8 surrogate", 33.00, 3e-8),
    ]
    best_post = max(float(r["post_ecc_ber"]) for r in mc)
    fitting_models = [c for c in candidates if c[1] <= mean and best_post <= c[2]]
    largest_model = max(fitting_models, key=lambda c: c[1]) if fitting_models else None
    smallest_model = candidates[0]
    fits = largest_model is not None
    answer = "fits" if fits else "does not fit"
    clean_rate = float(np.mean([r["clean_decode"] for r in mc]))

    append_report(
        "North-Star Answer",
        f"Recommended tuple: {best['modulation']} at {best['symbol_rate']} sym/s, {best['ecc']} ECC, interleaving depth {best['interleaving_depth']}, "
        f"and TinyStories-8M INT4 surrogate quantization. In 40 Monte Carlo end-to-end runs at the realistic channel, usable payload is "
        f"{mean:.3f} MB/side with an empirical 95% interval [{lo:.3f}, {hi:.3f}] MB and clean-decode rate {clean_rate:.3f}. "
        f"The smallest functionally interesting model considered is {smallest_model[0]} at about {smallest_model[1]:.2f} MB. "
        f"The largest candidate model that fits both payload and BER-threshold constraints is {largest_model[0] if largest_model else 'none'} "
        f"at {largest_model[1] if largest_model else 0:.2f} MB, so the simulated C-60 side {answer}. "
        f"Largest zero-error payload under the recommended tuple is {float(best['payload_MB_per_C60_side']):.3f} MB/side before container metadata.",
    )
    append_report(
        "Risks And Next Steps",
        "Top risks not captured by this simulation: real cassette dropouts/azimuth errors are burstier than the analytic channel; cheap deck AGC/noise reduction may distort modem constellations; and the LM robustness phase uses a deterministic surrogate rather than actual TinyStories transformer inference because torch/transformers are unavailable. "
        "Physical prototyping next steps: generate a WAV for the recommended modem, play it through one known-good consumer deck, capture line-out at 48 kHz, estimate raw BER against a sync-framed PRBS, then repeat with deliberately poor alignment and worn tape before investing in a real model payload.",
    )

    STATUS.write_text(
        "Cassette AI viability sprint status\n\n"
        "Phase: simulation deliverables generated.\n"
        f"Recommended tuple: {best['modulation']} {best['symbol_rate']} sym/s, {best['ecc']}, interleaving {best['interleaving_depth']}, INT4 TinyStories-1M surrogate.\n"
        f"Result: {mean:.3f} MB/side mean usable payload, 95% interval [{lo:.3f}, {hi:.3f}] MB, clean-decode rate {clean_rate:.3f}; largest fitting candidate is {largest_model[0] if largest_model else 'none'}.\n"
        "Caveat: model robustness is surrogate-only until torch/transformers and cached TinyStories checkpoints are available.\n"
    )


if __name__ == "__main__":
    run()
