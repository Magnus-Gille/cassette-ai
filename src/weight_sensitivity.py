from __future__ import annotations

import os
from copy import deepcopy

import matplotlib.pyplot as plt
import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

from common import DATA, PLOTS, ROOT, SEED, ensure_dirs, rng, save_json, write_csv
from model_robustness_real import HOLDOUT, MODEL_ID, perplexity


BIT_BUCKETS = {
    "sign": list(range(31, 32)),
    "exponent": list(range(23, 31)),
    "mantissa_high": list(range(12, 23)),
    "mantissa_low": list(range(0, 12)),
}
LAYER_TYPES = ["embedding", "attention", "mlp", "layernorm"]
TRIALS = 3


def classify(name: str) -> tuple[str, str] | None:
    low = name.lower()
    if "wte" in low or "wpe" in low or "embed" in low:
        return "embedding", "token_or_position"
    if ".attn." in low or "attention" in low:
        role = "projection" if any(x in low for x in ["proj", "c_attn", "q", "k", "v"]) else "other"
        return "attention", role
    if ".mlp." in low or "c_fc" in low or "c_proj" in low:
        return "mlp", "projection"
    if "ln_" in low or "layernorm" in low or "norm" in low:
        return "layernorm", "scale_or_bias"
    return None


def selected_state(model: torch.nn.Module, layer_type: str) -> list[tuple[str, torch.Tensor]]:
    out = []
    for name, p in model.named_parameters():
        c = classify(name)
        if c and c[0] == layer_type and torch.is_floating_point(p.data):
            out.append((name, p.data))
    return out


def flip_bucket(model: torch.nn.Module, layer_type: str, bit_bucket: str, ber: float, trial: int) -> torch.nn.Module:
    m = deepcopy(model)
    g = rng(51000 + trial + int(ber * 1e8) + len(layer_type) * 17 + len(bit_bucket))
    bits = BIT_BUCKETS[bit_bucket]
    with torch.no_grad():
        for _, p in selected_state(m, layer_type):
            arr = p.detach().cpu().float().contiguous().numpy()
            ui = arr.view(np.uint32).reshape(-1)
            n_flips = int(g.poisson(ui.size * len(bits) * ber))
            if n_flips == 0:
                continue
            idx = g.integers(0, ui.size, size=n_flips)
            b = g.choice(bits, size=n_flips)
            for i, bit in zip(idx, b):
                ui[i] ^= np.uint32(1 << int(bit))
            repaired = np.nan_to_num(ui.view(np.float32).reshape(arr.shape), nan=0.0, posinf=1e3, neginf=-1e3)
            repaired = np.clip(repaired, -1e3, 1e3)
            p.copy_(torch.from_numpy(repaired).to(device=p.device, dtype=p.dtype))
    return m


def bit_fraction(model: torch.nn.Module, layer_type: str, bit_bucket: str) -> float:
    total = 0
    selected = 0
    for _, p in model.named_parameters():
        if not torch.is_floating_point(p.data):
            continue
        bits = p.numel() * 32
        total += bits
        c = classify(_)
        if c and c[0] == layer_type:
            selected += p.numel() * len(BIT_BUCKETS[bit_bucket])
    return selected / total if total else 0.0


def run() -> None:
    ensure_dirs()
    os.environ["HF_HOME"] = str(ROOT / "hf_cache")
    set_seed(SEED)
    tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=str(ROOT / "hf_cache"))
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    base = AutoModelForCausalLM.from_pretrained(MODEL_ID, cache_dir=str(ROOT / "hf_cache"))
    base.eval()
    base_ppl = perplexity(base, tok, HOLDOUT)

    rows = []
    for layer_type in LAYER_TYPES:
        roles = sorted({classify(n)[1] for n, _ in base.named_parameters() if classify(n) and classify(n)[0] == layer_type})
        role = "+".join(roles) if roles else "none"
        for bit_bucket in BIT_BUCKETS:
            for ber in [1e-5, 1e-3]:
                ppls = []
                for trial in range(TRIALS):
                    m = flip_bucket(base, layer_type, bit_bucket, ber, trial)
                    m.eval()
                    ppls.append(perplexity(m, tok, HOLDOUT))
                ratio = float(np.median(ppls) / base_ppl)
                rows.append(
                    {
                        "model": MODEL_ID,
                        "layer_type": layer_type,
                        "tensor_role": role,
                        "bit_position_bucket": bit_bucket,
                        "ber": f"{ber:.1e}",
                        "trials": TRIALS,
                        "baseline_perplexity": round(base_ppl, 4),
                        "median_perplexity": round(float(np.median(ppls)), 4),
                        "ppl_ratio_vs_unperturbed": round(ratio, 4),
                        "bit_fraction_of_model": round(bit_fraction(base, layer_type, bit_bucket), 6),
                    }
                )

    by_bucket = {}
    for r in rows:
        key = (r["layer_type"], r["tensor_role"], r["bit_position_bucket"])
        by_bucket.setdefault(key, {})[r["ber"]] = r
    ranked = []
    for key, vals in by_bucket.items():
        r1 = vals["1.0e-05"]
        r2 = vals["1.0e-03"]
        frag = float(r1["ppl_ratio_vs_unperturbed"])
        tol = float(r2["ppl_ratio_vs_unperturbed"])
        cls = "critical" if frag > 2.0 else "tolerant" if tol < 1.1 else "normal"
        ranked.append((frag, key, cls))
        for ber, row in vals.items():
            row["fragility_rank_score"] = round(frag, 4)
            row["uep_class"] = cls
    rows.sort(key=lambda r: float(r["fragility_rank_score"]), reverse=True)
    write_csv(DATA / "weight_sensitivity.csv", rows)

    critical = sum(float(v["1.0e-05"]["bit_fraction_of_model"]) for v in by_bucket.values() if float(v["1.0e-05"]["ppl_ratio_vs_unperturbed"]) > 2.0)
    tolerant = sum(float(v["1.0e-03"]["bit_fraction_of_model"]) for v in by_bucket.values() if float(v["1.0e-03"]["ppl_ratio_vs_unperturbed"]) < 1.1)
    save_json(DATA / "weight_sensitivity_summary.json", {"critical_fraction": critical, "tolerant_fraction": tolerant, "baseline_perplexity": base_ppl})

    mat = np.zeros((len(LAYER_TYPES), len(BIT_BUCKETS)))
    for i, lt in enumerate(LAYER_TYPES):
        for j, bb in enumerate(BIT_BUCKETS):
            vals = [float(r["ppl_ratio_vs_unperturbed"]) for r in rows if r["layer_type"] == lt and r["bit_position_bucket"] == bb and r["ber"] == "1.0e-05"]
            mat[i, j] = vals[0] if vals else np.nan
    fig, ax = plt.subplots(figsize=(8, 4.8))
    im = ax.imshow(np.log10(np.maximum(mat, 1e-3)), cmap="inferno", aspect="auto")
    ax.set_xticks(range(len(BIT_BUCKETS)), list(BIT_BUCKETS.keys()), rotation=30, ha="right")
    ax.set_yticks(range(len(LAYER_TYPES)), LAYER_TYPES)
    ax.set_title("TinyStories-1M sensitivity at BER 1e-5 (log10 perplexity ratio)")
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, f"{mat[i,j]:.1f}x", ha="center", va="center", color="white" if mat[i, j] > 2 else "black", fontsize=8)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(PLOTS / "sensitivity_heatmap.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()

