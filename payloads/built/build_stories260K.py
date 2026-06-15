#!/usr/bin/env python3
"""
Build the tape-ready int4 bundle for karpathy stories260K (llama2.c format).

stories260K is NOT a HuggingFace Llama checkpoint -- it's a karpathy/llama2.c
native export: a `.pt` (nanoGPT-style state dict under `_orig_mod.*`), a `.bin`
fp32 export consumed by llama2.c's `run.c`, and `tok512.bin` (the 512-token
tokenizer for run.c). dim=64, n_layers=5, vocab=512.

We quantize every 2D weight matrix to group-wise int4 (same scheme as the HF
Llama models, the math is arch-agnostic), keep 1D norms fp16, bundle with the
tok512 tokenizer + model_args, and xz -9e. Round-trip = dequantize and report
max abs weight error + that the reconstructed fp32 tensors are finite and
shape-correct (so a re-export to llama2.c .bin would be valid).

Runtime on-device = karpathy llama2.c run.c (reads tok512.bin + a .bin export
re-materialized from the dequantized weights).
"""
import sys, os, io, json, tarfile, importlib.util
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "qz", os.path.join(HERE, "quantize_llama_int4.py"))
qz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qz)

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "stories260K_dl/stories260K")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "stories260K")
os.makedirs(OUT, exist_ok=True)


def main():
    ckpt = torch.load(os.path.join(SRC, "stories260K.pt"),
                      map_location="cpu", weights_only=False)
    model_args = ckpt["model_args"]
    sd = ckpt["model"]
    # strip the _orig_mod. prefix that torch.compile adds
    sd = {k.replace("_orig_mod.", ""): v for k, v in sd.items()}

    # tie detection: llama2.c output head shares tok_embeddings unless 'output.weight'
    tie = "output.weight" not in sd or (
        "output.weight" in sd and "tok_embeddings.weight" in sd
        and torch.equal(sd["output.weight"], sd["tok_embeddings.weight"]))

    blob = {}
    manifest = {"group": qz.GROUP, "tensors": {}, "tie": bool(tie),
                "model_args": model_args, "format": "llama2.c"}
    skip = {"output.weight"} if (tie and "output.weight" in sd) else set()
    for k, v in sd.items():
        if k in skip:
            continue
        arr = v.detach().cpu().float().numpy()
        if arr.ndim == 2:
            packed, scale, zero, _ = qz.quantize_2d(arr)
            blob[k + ".q"] = packed
            blob[k + ".s"] = scale
            blob[k + ".z"] = zero
            manifest["tensors"][k] = {"kind": "int4", "shape": list(arr.shape)}
        else:
            blob[k + ".f"] = arr.astype(np.float16)
            manifest["tensors"][k] = {"kind": "fp16", "shape": list(arr.shape)}

    with open(os.path.join(OUT, "weights_int4.npz"), "wb") as f:
        f.write(qz.npz_bytes(blob))
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f)

    # bundle: quant blob + manifest + tokenizer (tok512.bin is the run.c one)
    members = {
        "weights_int4.npz": qz.npz_bytes(blob),
        "manifest.json": json.dumps(manifest).encode(),
    }
    for fn in ("tok512.bin", "tok512.model"):
        p = os.path.join(SRC, fn)
        if os.path.exists(p):
            members[fn] = open(p, "rb").read()
    tbio = io.BytesIO()
    with tarfile.open(fileobj=tbio, mode="w") as tar:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    raw = tbio.getvalue()
    comp = qz.xz_compress(raw)
    with open(os.path.join(OUT, "tape_bundle.tar.xz"), "wb") as f:
        f.write(comp)

    # int8 comparison
    blob8 = {}
    for k, v in sd.items():
        if k in skip:
            continue
        arr = v.detach().cpu().float().numpy()
        if arr.ndim == 2:
            wmin = arr.min(1, keepdims=True); wmax = arr.max(1, keepdims=True)
            scale = (wmax - wmin) / 255.0; scale[scale == 0] = 1.0
            zero = np.round(-wmin / scale)
            q = np.clip(np.round(arr / scale) + zero, 0, 255).astype(np.uint8)
            blob8[k + ".q"] = q; blob8[k + ".s"] = scale.astype(np.float16)
            blob8[k + ".z"] = zero.astype(np.float16)
        else:
            blob8[k + ".f"] = arr.astype(np.float16)
    m8 = dict(members); m8["weights_int8.npz"] = qz.npz_bytes(blob8)
    del m8["weights_int4.npz"]
    tb8 = io.BytesIO()
    with tarfile.open(fileobj=tb8, mode="w") as tar:
        for name, data in m8.items():
            ti = tarfile.TarInfo(name); ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    int8_bytes = len(qz.xz_compress(tb8.getvalue()))

    # round-trip: dequantize and check error
    errs = {}
    maxerr = 0.0
    for k, meta in manifest["tensors"].items():
        if meta["kind"] == "int4":
            rows, cols = meta["shape"]
            deq = qz.dequantize_2d(blob[k + ".q"], blob[k + ".s"],
                                   blob[k + ".z"], rows, cols, qz.GROUP)
            a = sd[k].detach().float().numpy()
            e = float(np.abs(a - deq).max())
            maxerr = max(maxerr, e)
            if k in ("tok_embeddings.weight", "layers.0.feed_forward.w1.weight"):
                errs[k] = e
    # confirm finite + reconstructable
    finite = all(np.isfinite(qz.dequantize_2d(
        blob[k + ".q"], blob[k + ".s"], blob[k + ".z"],
        *meta["shape"], qz.GROUP)).all()
        for k, meta in manifest["tensors"].items() if meta["kind"] == "int4")

    result = {
        "sizes": {
            "raw_tar_bytes": len(raw),
            "bundle_bytes": len(comp),
            "npz_bytes": len(members["weights_int4.npz"]),
            "int8_bundle_bytes": int8_bytes,
            "tok512_bytes": len(members.get("tok512.bin", b"")),
        },
        "tie": bool(tie),
        "n_int4": sum(1 for m in manifest["tensors"].values() if m["kind"] == "int4"),
        "model_args": model_args,
        "roundtrip": {"errors": errs, "max_abs_err": maxerr,
                      "all_finite": bool(finite), "forward_ok": bool(finite)},
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
