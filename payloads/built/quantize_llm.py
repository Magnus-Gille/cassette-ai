#!/usr/bin/env python3
"""
Tape-payload quantizer for tiny Llama-family models (SmolLM2-135M, TinyCode-python).

Produces the bytes that would be encoded on tape:
  quantized weights (int8 / int4 group-wise / int3 group-wise)
  + tokenizer (tokenizer.json) + config + a runtime note,
then lzma-compresses the bundle and reports the on-tape size.

Quant scheme: symmetric, per-output-channel group-wise (group=GROUP cols).
  int8:  one int8 per weight + fp16 scale per group.
  int4:  two weights per byte (nibble pack) + fp16 scale per group.
  int3:  packed 8 weights per 3 bytes + fp16 scale per group (aggressive).
Embeddings dominate tiny models, so we quantize *every* 2-D tensor including
embed_tokens / lm_head; 1-D tensors (norms) stay fp16.

Sanity: dequantize back, check shapes + report mean abs relative error.
"""
import sys, os, json, struct, io, tarfile, subprocess, shutil
import numpy as np
from safetensors.numpy import load_file

GROUP = 64  # group size along the input dimension


def _bf16_to_f32(raw_u16: np.ndarray) -> np.ndarray:
    # bfloat16 stored as uint16 -> float32
    u32 = raw_u16.astype(np.uint32) << 16
    return u32.view(np.float32)


def load_tensors(path):
    """Load a safetensors file as float32 numpy arrays, handling bf16."""
    import safetensors
    out = {}
    with safetensors.safe_open(path, framework="numpy") as f:
        for k in f.keys():
            try:
                t = f.get_tensor(k)
                out[k] = t.astype(np.float32)
            except Exception:
                out[k] = None  # bf16 fallback handled below
    # Some safetensors numpy backends can't read bf16; fall back to torch.
    if any(v is None for v in out.values()):
        import torch
        from safetensors.torch import load_file as tload
        td = tload(path)
        out = {k: v.float().cpu().numpy() for k, v in td.items()}
    return out


def quant_group(w: np.ndarray, bits: int, group: int = GROUP):
    """Symmetric group-wise quant of a 2-D weight [out, in].
    Returns (q_int (int8, signed), scales (fp16), shape). q values in [-2^(b-1)+1, 2^(b-1)-1]."""
    assert w.ndim == 2
    out, inn = w.shape
    qmax = (1 << (bits - 1)) - 1  # e.g. int4 -> 7, int8 -> 127, int3 -> 3
    # pad input dim to multiple of group
    pad = (-inn) % group
    if pad:
        w = np.concatenate([w, np.zeros((out, pad), np.float32)], axis=1)
    inn_p = w.shape[1]
    ng = inn_p // group
    wg = w.reshape(out, ng, group)
    amax = np.max(np.abs(wg), axis=2, keepdims=True)  # [out, ng, 1]
    scales = (amax / qmax).astype(np.float32)
    scales[scales == 0] = 1.0
    q = np.round(wg / scales).astype(np.int32)
    q = np.clip(q, -qmax, qmax).astype(np.int8)
    return q.reshape(out, inn_p), scales.astype(np.float16).reshape(out, ng), (out, inn)


def dequant_group(q: np.ndarray, scales: np.ndarray, shape, group: int = GROUP):
    out, inn = shape
    inn_p = q.shape[1]
    ng = inn_p // group
    wg = q.reshape(out, ng, group).astype(np.float32)
    w = (wg * scales.astype(np.float32).reshape(out, ng, 1)).reshape(out, inn_p)
    return w[:, :inn]


def pack_int4(q: np.ndarray) -> bytes:
    # q signed int8 in [-7,7]; shift to [0,15] nibble, pack 2/byte
    flat = (q.astype(np.int16) + 8).astype(np.uint8).reshape(-1)
    if flat.size % 2:
        flat = np.concatenate([flat, np.zeros(1, np.uint8)])
    hi = flat[0::2] << 4
    lo = flat[1::2] & 0x0F
    return (hi | lo).astype(np.uint8).tobytes()


def pack_int3(q: np.ndarray) -> bytes:
    # q signed int8 in [-3,3]; shift to [0,7] (3 bits), pack into a contiguous bitstream.
    # Vectorized: expand each value to its 3 low bits, concat, then packbits.
    vals = (q.astype(np.int16) + 4).astype(np.uint8).reshape(-1)  # [-3,3] -> [1,7], fits 3 bits
    n = vals.size
    pad = (-n) % 8
    if pad:
        vals = np.concatenate([vals, np.zeros(pad, np.uint8)])
    # unpackbits gives 8 bits MSB-first per byte; take the low 3 (cols 5,6,7)
    bits8 = np.unpackbits(vals[:, None], axis=1)          # [N,8]
    bits3 = bits8[:, 5:8].reshape(-1)                      # [N*3] big-endian 3-bit stream
    return np.packbits(bits3).tobytes()


def build_bundle(src_dir, out_dir, bits, name):
    st = os.path.join(src_dir, "model.safetensors")
    tensors = load_tensors(st)
    blobs = {}  # tensor name -> packed bytes
    meta = {}   # tensor name -> {shape, scales offset etc}
    scale_blob = io.BytesIO()
    weight_blob = io.BytesIO()
    rel_errs = []
    n_quant = 0
    n_fp16 = 0
    for k, w in sorted(tensors.items()):
        if w.ndim == 2 and min(w.shape) >= GROUP // 2:
            q, scales, shape = quant_group(w, bits)
            if bits == 8:
                packed = q.astype(np.int8).tobytes()
            elif bits == 4:
                packed = pack_int4(q)
            elif bits == 3:
                packed = pack_int3(q)
            else:
                raise ValueError(bits)
            woff = weight_blob.tell(); weight_blob.write(packed)
            soff = scale_blob.tell(); scale_blob.write(scales.tobytes())
            meta[k] = dict(kind="q%d" % bits, shape=list(shape),
                           woff=woff, wlen=len(packed),
                           soff=soff, slen=scales.size * 2, ng=scales.shape[1])
            # roundtrip rel err
            dq = dequant_group(q, scales, shape)
            denom = np.mean(np.abs(w)) + 1e-9
            rel_errs.append(float(np.mean(np.abs(dq - w)) / denom))
            n_quant += 1
        else:
            # keep fp16
            h = w.astype(np.float16).tobytes()
            woff = weight_blob.tell(); weight_blob.write(h)
            meta[k] = dict(kind="f16", shape=list(w.shape), woff=woff, wlen=len(h))
            n_fp16 += 1

    os.makedirs(out_dir, exist_ok=True)
    # assemble a tar of: meta.json, weights.bin, scales.bin, tokenizer.json, config.json, runtime.txt
    manifest = dict(format="cassette-quant-v1", bits=bits, group=GROUP, tensors=meta)
    runtime_note = (
        "RUNTIME: llama.cpp / llama2.c-style int%d dequant on load, or transformers.js q%df16 in browser (WASM).\n"
        "Llama arch: load weights.bin via tensors[].woff/wlen, scales.bin via soff/slen, "
        "dequantize group-wise (group=%d, symmetric per-group fp16 scale), run standard Llama forward.\n"
        % (bits, bits, GROUP)
    )
    tarpath = os.path.join(out_dir, "bundle_int%d.tar" % bits)
    with tarfile.open(tarpath, "w") as tf:
        def add_bytes(arcname, data):
            ti = tarfile.TarInfo(arcname); ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        add_bytes("manifest.json", json.dumps(manifest).encode())
        add_bytes("weights.bin", weight_blob.getvalue())
        add_bytes("scales.bin", scale_blob.getvalue())
        add_bytes("runtime.txt", runtime_note.encode())
        for fn in ("tokenizer.json", "config.json", "generation_config.json",
                   "special_tokens_map.json", "tokenizer_config.json"):
            p = os.path.join(src_dir, fn)
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    add_bytes(fn, fh.read())
    raw_tar = os.path.getsize(tarpath)
    # lzma compress via xz CLI (python _lzma unavailable in this pyenv)
    xzpath = tarpath + ".xz"
    if os.path.exists(xzpath):
        os.remove(xzpath)
    subprocess.run(["xz", "-9", "-e", "-k", "-f", tarpath], check=True)
    on_tape = os.path.getsize(xzpath)
    mean_rel = float(np.mean(rel_errs)) if rel_errs else 0.0
    return dict(bits=bits, raw_tar_bytes=raw_tar, on_tape_bytes=on_tape,
                on_tape_mb=round(on_tape / 1e6, 3),
                n_quant=n_quant, n_fp16=n_fp16,
                mean_rel_err=round(mean_rel, 5),
                roundtrip_ok=bool(mean_rel < 0.5 and n_quant > 0),
                xz_path=xzpath)


def main():
    src_dir = sys.argv[1]
    out_dir = sys.argv[2]
    name = sys.argv[3]
    bitlist = [int(b) for b in sys.argv[4].split(",")]
    results = {}
    for bits in bitlist:
        r = build_bundle(src_dir, out_dir, bits, name)
        results["int%d" % bits] = r
        print("int%d: on_tape=%.3f MB  rawtar=%.3f MB  rel_err=%.4f  roundtrip=%s  (q=%d f16=%d)" % (
            bits, r["on_tape_mb"], r["raw_tar_bytes"]/1e6, r["mean_rel_err"], r["roundtrip_ok"],
            r["n_quant"], r["n_fp16"]))
    with open(os.path.join(out_dir, "quant_results.json"), "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
