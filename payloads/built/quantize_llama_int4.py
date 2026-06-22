#!/usr/bin/env python3
"""
Tie-aware group-wise int4 quantizer for the delphi-suite / karpathy TinyStories
Llama-2 models, for the cassette-ai tape payload campaign.

Design
------
- 2D weight matrices  -> group-wise asymmetric int4 (group along the input dim).
  Each group of `GROUP` elements gets an fp16 scale + an int8 zero-point; values
  packed 2 nibbles/byte. This is the dominant cost (embeddings + projections).
- 1D weights (RMSNorm gains) -> kept fp16 (negligible, quantizing them hurts).
- Tie-aware: if lm_head.weight == embed_tokens.weight, the embedding is stored
  ONCE and lm_head is reconstructed on load (saves a full vocab x dim table).
- Output bundle (for size measurement / tape) =
      manifest.json (shapes, dtypes, group size, tie flag)
    + packed int4 nibbles + fp16 scales + int8 zeros (one .npz-style blob)
    + tokenizer.model (raw SentencePiece, ~ tiny)
    + config.json
  -> all tarred, then lzma -9e compressed = on_tape bytes.

Round-trip: dequantize back to fp32, reload into the HF model, run a forward
pass, and report max abs error of a couple of weights + that logits are finite.
"""
import sys, os, json, io, tarfile, struct, subprocess, types

# ---------------------------------------------------------------------------
# _lzma stub. The torch-capable interpreter in this env (pyenv 3.10) was built
# without the `_lzma` C extension. transformers 5.8 imports lzma lazily during
# model construction, which otherwise surfaces as a confusing
# "Could not import module 'LlamaConfig'" error. We never use lzma from Python
# (compression shells out to the `xz` CLI), so a no-op stub is safe: it lets the
# import chain resolve; any actual lzma *use* would raise LZMAError.
# ---------------------------------------------------------------------------
if "_lzma" not in sys.modules:
    try:
        import _lzma  # noqa: F401
    except ImportError:
        _stub = types.ModuleType("_lzma")
        class LZMAError(Exception):
            pass
        _stub.LZMAError = LZMAError
        for _n, _v in dict(
            FORMAT_AUTO=0, FORMAT_XZ=1, FORMAT_ALONE=2, FORMAT_RAW=3,
            CHECK_NONE=0, CHECK_CRC32=1, CHECK_CRC64=4, CHECK_SHA256=10,
            CHECK_ID_MAX=15, CHECK_UNKNOWN=16,
            FILTER_LZMA1=0x4000000000000001, FILTER_LZMA2=0x21,
            FILTER_DELTA=0x03, FILTER_X86=0x04, FILTER_POWERPC=0x05,
            FILTER_IA64=0x06, FILTER_ARM=0x07, FILTER_ARMTHUMB=0x08,
            FILTER_SPARC=0x09, MF_HC3=0x03, MF_HC4=0x04, MF_BT2=0x12,
            MF_BT3=0x13, MF_BT4=0x14, MODE_FAST=1, MODE_NORMAL=2,
            PRESET_DEFAULT=6, PRESET_EXTREME=1 << 31,
        ).items():
            setattr(_stub, _n, _v)
        def _unavail(*a, **k):
            raise LZMAError("lzma unavailable in this interpreter (stub)")
        _stub.LZMACompressor = _unavail
        _stub.LZMADecompressor = _unavail
        _stub.is_check_supported = lambda x: False
        _stub._encode_filter_properties = _unavail
        _stub._decode_filter_properties = _unavail
        sys.modules["_lzma"] = _stub

import numpy as np
import torch


def xz_compress(data: bytes) -> bytes:
    """Compress bytes with the `xz -9e` CLI (lzma preset 9 extreme).

    Used instead of the stdlib `lzma` module because the torch-capable
    interpreter in this env (pyenv 3.10) was built without `_lzma`.
    Functionally equivalent to lzma.compress(data, preset=9|EXTREME).
    """
    p = subprocess.run(["xz", "-9", "-e", "-T", "1", "-c"],
                       input=data, stdout=subprocess.PIPE, check=True)
    return p.stdout

GROUP = 64  # group size along the input (last) dim for 2D weights


def quantize_2d(W: np.ndarray, group: int = GROUP):
    """Asymmetric int4 group-wise quant of a 2D fp32 matrix.
    Returns (packed_uint8, scales_fp16, zeros_int8, padded_cols).
    Groups run along axis=1 (input dim). Pads last group with zeros."""
    rows, cols = W.shape
    pad = (-cols) % group
    if pad:
        W = np.concatenate([W, np.zeros((rows, pad), W.dtype)], axis=1)
    cols_p = W.shape[1]
    ng = cols_p // group
    Wg = W.reshape(rows, ng, group)
    wmin = Wg.min(axis=2)              # (rows, ng)
    wmax = Wg.max(axis=2)
    scale = (wmax - wmin) / 15.0
    scale[scale == 0] = 1.0           # constant group -> avoid div0
    zero = np.round(-wmin / scale)    # so q = round(w/scale)+zero in [0,15]
    zero = np.clip(zero, 0, 15).astype(np.int8)
    q = np.round(Wg / scale[:, :, None]) + zero[:, :, None]
    q = np.clip(q, 0, 15).astype(np.uint8)            # (rows, ng, group)
    q = q.reshape(rows, cols_p)                        # (rows, cols_p)
    # pack 2 nibbles per byte along the column axis
    if cols_p % 2:
        q = np.concatenate([q, np.zeros((rows, 1), np.uint8)], axis=1)
    qf = q.reshape(rows, -1, 2)
    packed = (qf[:, :, 0] | (qf[:, :, 1] << 4)).astype(np.uint8)
    return packed, scale.astype(np.float16), zero, cols_p


def dequantize_2d(packed, scale, zero, rows, orig_cols, group=GROUP):
    cols_p = ((orig_cols + group - 1) // group) * group
    cols_pp = cols_p + (cols_p % 2)
    lo = (packed & 0x0F).astype(np.int16)
    hi = (packed >> 4).astype(np.int16)
    q = np.empty((rows, cols_pp), np.int16)
    q[:, 0::2] = lo
    q[:, 1::2] = hi
    q = q[:, :cols_p]
    ng = cols_p // group
    q = q.reshape(rows, ng, group)
    scale = scale.astype(np.float32)
    W = (q - zero[:, :, None].astype(np.float32)) * scale[:, :, None]
    W = W.reshape(rows, cols_p)[:, :orig_cols]
    return W.astype(np.float32)


def quantize_state_dict(sd):
    """Returns (blob_dict, manifest) where blob_dict maps names->np arrays."""
    blob = {}
    manifest = {"group": GROUP, "tensors": {}, "tie": False}
    # tie detection
    if "lm_head.weight" in sd and "model.embed_tokens.weight" in sd:
        if torch.equal(sd["lm_head.weight"], sd["model.embed_tokens.weight"]):
            manifest["tie"] = True
    skip = set()
    if manifest["tie"]:
        skip.add("lm_head.weight")
    for k, v in sd.items():
        if k in skip:
            continue
        arr = v.detach().cpu().float().numpy()
        if arr.ndim == 2:
            packed, scale, zero, cols_p = quantize_2d(arr)
            blob[k + ".q"] = packed
            blob[k + ".s"] = scale
            blob[k + ".z"] = zero
            manifest["tensors"][k] = {"kind": "int4", "shape": list(arr.shape)}
        else:
            blob[k + ".f"] = arr.astype(np.float16)
            manifest["tensors"][k] = {"kind": "fp16", "shape": list(arr.shape)}
    return blob, manifest


def dequantize_state_dict(blob, manifest):
    sd = {}
    for k, meta in manifest["tensors"].items():
        if meta["kind"] == "int4":
            rows, cols = meta["shape"]
            sd[k] = torch.from_numpy(
                dequantize_2d(blob[k + ".q"], blob[k + ".s"], blob[k + ".z"],
                              rows, cols, manifest["group"]))
        else:
            sd[k] = torch.from_numpy(blob[k + ".f"].astype(np.float32))
    if manifest["tie"]:
        sd["lm_head.weight"] = sd["model.embed_tokens.weight"].clone()
    return sd


def npz_bytes(blob):
    bio = io.BytesIO()
    np.savez(bio, **blob)
    return bio.getvalue()


def int8_bundle_size(model_dir, sd, tie):
    """Measure the int8 (per-row asymmetric) bundle size for comparison.
    Embeddings/2D weights -> int8 + per-row fp16 scale/zero. 1D -> fp16.
    Returns compressed bundle bytes (tokenizer + config included)."""
    blob = {}
    skip = {"lm_head.weight"} if tie else set()
    for k, v in sd.items():
        if k in skip:
            continue
        arr = v.detach().cpu().float().numpy()
        if arr.ndim == 2:
            wmin = arr.min(axis=1, keepdims=True)
            wmax = arr.max(axis=1, keepdims=True)
            scale = (wmax - wmin) / 255.0
            scale[scale == 0] = 1.0
            zero = np.round(-wmin / scale)
            q = np.clip(np.round(arr / scale) + zero, 0, 255).astype(np.uint8)
            blob[k + ".q"] = q
            blob[k + ".s"] = scale.astype(np.float16)
            blob[k + ".z"] = zero.astype(np.float16)
        else:
            blob[k + ".f"] = arr.astype(np.float16)
    members = {"weights_int8.npz": npz_bytes(blob)}
    for fn in ("tokenizer.model", "tokenizer.json", "config.json",
               "tokenizer_config.json", "special_tokens_map.json"):
        p = os.path.join(model_dir, fn)
        if os.path.exists(p):
            members[fn] = open(p, "rb").read()
    tbio = io.BytesIO()
    with tarfile.open(fileobj=tbio, mode="w") as tar:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    return len(xz_compress(tbio.getvalue()))


def load_state_dict(model_dir):
    """Load weights from pytorch_model.bin OR model.safetensors."""
    pbin = os.path.join(model_dir, "pytorch_model.bin")
    pst = os.path.join(model_dir, "model.safetensors")
    if os.path.exists(pbin):
        return torch.load(pbin, map_location="cpu", weights_only=True)
    if os.path.exists(pst):
        from safetensors.torch import load_file
        return load_file(pst)
    raise FileNotFoundError(f"no weights in {model_dir}")


def build_bundle(model_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    sd = load_state_dict(model_dir)
    blob, manifest = quantize_state_dict(sd)
    # write loose quant blob + manifest into out_dir (for inspection/round-trip)
    blob_path = os.path.join(out_dir, "weights_int4.npz")
    with open(blob_path, "wb") as f:
        f.write(npz_bytes(blob))
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    # assemble the tape bundle: quant blob + tokenizer + config + manifest
    members = {
        "weights_int4.npz": npz_bytes(blob),
        "manifest.json": json.dumps(manifest).encode(),
    }
    for fn in ("tokenizer.model", "tokenizer.json", "config.json",
               "tokenizer_config.json", "special_tokens_map.json"):
        p = os.path.join(model_dir, fn)
        if os.path.exists(p):
            members[fn] = open(p, "rb").read()
    # tar (uncompressed) then lzma -9e
    tbio = io.BytesIO()
    with tarfile.open(fileobj=tbio, mode="w") as tar:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    raw_tar = tbio.getvalue()
    comp = xz_compress(raw_tar)
    bundle_path = os.path.join(out_dir, "tape_bundle.tar.xz")
    with open(bundle_path, "wb") as f:
        f.write(comp)
    return manifest, blob, sd, {
        "raw_tar_bytes": len(raw_tar),
        "bundle_bytes": len(comp),
        "npz_bytes": len(members["weights_int4.npz"]),
        "tokenizer_bytes": len(members.get("tokenizer.model", b"")),
    }


def roundtrip_check(model_dir, blob, manifest, orig_sd):
    """Dequantize, reload into HF Llama, run a forward, report errors."""
    deq = dequantize_state_dict(blob, manifest)
    # max abs error on the embedding (dominant tensor) and one mlp proj
    errs = {}
    for k in ["model.embed_tokens.weight", "model.layers.0.mlp.gate_proj.weight",
              "model.layers.0.self_attn.q_proj.weight"]:
        if k in orig_sd and k in deq:
            a = orig_sd[k].detach().float()
            b = deq[k].detach().float()
            errs[k] = float((a - b).abs().max())
    finite = True
    try:
        from transformers import LlamaForCausalLM, LlamaConfig
        cfg = LlamaConfig.from_pretrained(model_dir)
        model = LlamaForCausalLM(cfg)
        # load dequantized weights (lm_head reconstructed via tie)
        missing, unexpected = model.load_state_dict(deq, strict=False)
        model.eval()
        with torch.no_grad():
            ids = torch.tensor([[1, 2, 3, 4, 5]])
            out = model(ids).logits
        finite = bool(torch.isfinite(out).all())
        ok_shapes = (out.shape[-1] == cfg.vocab_size)
    except Exception as e:
        return {"errors": errs, "forward_ok": False, "exc": str(e)}
    return {"errors": errs, "forward_ok": finite and ok_shapes,
            "logits_shape": list(out.shape), "missing": len(missing),
            "unexpected": len(unexpected)}


if __name__ == "__main__":
    model_dir = sys.argv[1]
    out_dir = sys.argv[2]
    manifest, blob, sd, sizes = build_bundle(model_dir, out_dir)
    sizes["int8_bundle_bytes"] = int8_bundle_size(model_dir, sd, manifest["tie"])
    rt = roundtrip_check(model_dir, blob, manifest, sd)
    result = {"sizes": sizes, "manifest_tie": manifest["tie"],
              "n_int4": sum(1 for m in manifest["tensors"].values() if m["kind"] == "int4"),
              "roundtrip": rt}
    print(json.dumps(result, indent=2))
