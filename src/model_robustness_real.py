from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch
import matplotlib.pyplot as plt
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

from common import DATA, PLOTS, ROOT, SEED, ensure_dirs, rng, save_json, write_csv


MODEL_ID = "roneneldan/TinyStories-1M"
BERS = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2]
QUANTS = ["INT8", "INT4"]
TRIALS = 5
PROMPTS = [
    "Once upon a time, Mia found a red ball",
    "The puppy wanted to help Sam clean the room",
    "Lina heard a tiny bell near the tree",
]
HOLDOUT = (
    "Once there was a little girl named Anna who liked to make small boats from paper. "
    "One rainy day she put a blue boat in a puddle and watched it sail. Her brother Ben "
    "wanted to splash, but Anna asked him to be gentle. The boat floated under a leaf and "
    "came back again. Anna smiled because Ben used a stick to save it. They took the boat "
    "inside, dried it near the window, and made two more boats so they could both play. "
    "At bedtime Anna told Mom that the rain had made a river just for them. Mom laughed "
    "and said that tomorrow they could build a bridge from blocks."
)


def _quantize_and_flip_tensor(t: torch.Tensor, bits: int, ber: float, g: np.random.Generator) -> torch.Tensor:
    if not torch.is_floating_point(t) or t.numel() == 0:
        return t.clone()
    device = t.device
    src = t.detach().cpu().float()
    max_abs = float(src.abs().max())
    if max_abs == 0.0:
        return t.clone()
    qmax = (2 ** (bits - 1)) - 1
    scale = max_abs / qmax
    q = torch.clamp(torch.round(src / scale), -qmax - 1, qmax).to(torch.int16)
    n_bits = q.numel() * bits
    n_flips = int(g.poisson(n_bits * ber))
    if n_flips > 0:
        flat = q.view(-1).numpy()
        idx = g.integers(0, flat.size, size=n_flips)
        bit = g.integers(0, bits, size=n_flips)
        for i, b in zip(idx, bit):
            flat[i] = np.int16(int(flat[i]) ^ (1 << int(b)))
        q = torch.from_numpy(flat.reshape(tuple(q.shape))).to(torch.int16)
    return (q.float() * scale).to(device=device, dtype=t.dtype)


def quantized_perturbed_model(base: torch.nn.Module, bits: int, ber: float, trial: int) -> torch.nn.Module:
    model = deepcopy(base)
    g = rng(22000 + bits * 100 + trial + int(ber * 1e9))
    with torch.no_grad():
        for _, p in model.named_parameters():
            p.copy_(_quantize_and_flip_tensor(p.data, bits, ber, g))
    return model


def perplexity(model: torch.nn.Module, tok, text: str) -> float:
    enc = tok(text, return_tensors="pt")
    with torch.no_grad():
        out = model(**enc, labels=enc["input_ids"])
    return float(torch.exp(out.loss).detach().cpu())


def generate_samples(model: torch.nn.Module, tok) -> list[str]:
    samples = []
    for prompt in PROMPTS:
        enc = tok(prompt, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(
                **enc,
                max_new_tokens=24,
                do_sample=True,
                temperature=0.8,
                top_k=40,
                pad_token_id=tok.eos_token_id,
            )
        samples.append(tok.decode(out[0], skip_special_tokens=True).replace("\n", " "))
    return samples


def run() -> None:
    ensure_dirs()
    os.environ["HF_HOME"] = str(ROOT / "hf_cache")
    os.environ["TRANSFORMERS_CACHE"] = str(ROOT / "hf_cache")
    set_seed(SEED)
    tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=str(ROOT / "hf_cache"))
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    base = AutoModelForCausalLM.from_pretrained(MODEL_ID, cache_dir=str(ROOT / "hf_cache"))
    base.eval()
    base_ppl = perplexity(base, tok, HOLDOUT)

    rows = []
    thresholds = {}
    for quant in QUANTS:
        bits = 8 if quant == "INT8" else 4
        medians = {}
        for ber in BERS:
            ppls = []
            for trial in range(TRIALS):
                set_seed(SEED + trial)
                model = quantized_perturbed_model(base, bits, ber, trial)
                model.eval()
                ppl = perplexity(model, tok, HOLDOUT)
                ppls.append(ppl)
                samples = generate_samples(model, tok)
                rows.append(
                    {
                        "model": MODEL_ID,
                        "quantization": quant,
                        "ber": f"{ber:.1e}",
                        "trial": trial,
                        "baseline_perplexity": round(base_ppl, 4),
                        "perplexity": round(ppl, 4),
                        "ppl_ratio_vs_unperturbed": round(ppl / base_ppl, 4),
                        "sample_1": samples[0],
                        "sample_2": samples[1],
                        "sample_3": samples[2],
                    }
                )
            medians[ber] = float(np.median(ppls)) / base_ppl
        ok = [ber for ber, ratio in medians.items() if ratio <= 2.0]
        thresholds[quant] = max(ok) if ok else None

    write_csv(DATA / "model_ber_threshold_real.csv", rows)
    save_json(DATA / "model_ber_threshold_real_summary.json", {"baseline_perplexity": base_ppl, "thresholds": thresholds})

    fig, ax = plt.subplots(figsize=(8, 5))
    for quant in QUANTS:
        xs, ys = [], []
        for ber in BERS:
            vals = [float(r["ppl_ratio_vs_unperturbed"]) for r in rows if r["quantization"] == quant and r["ber"] == f"{ber:.1e}"]
            xs.append(ber)
            ys.append(float(np.median(vals)))
        ax.plot(xs, ys, marker="o", label=quant)
    ax.axhline(2.0, color="black", linestyle="--", linewidth=1, label="2x perplexity")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("BER injected into quantized weights")
    ax.set_ylabel("perplexity ratio vs unperturbed")
    ax.set_title("Real TinyStories-1M BER tolerance")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "ber_threshold_real.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()

