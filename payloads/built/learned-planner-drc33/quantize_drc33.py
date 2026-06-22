#!/usr/bin/env python3
"""Extract + quantize the DRC(3,3) Sokoban planner to a tape-ready bundle.

Input : drc33/bkynosqi/cp_2002944000/model  (flax msgpack checkpoint, 20.5MB
        incl. Adam optimizer state)
Output: build/ ... tape bundle (int8 + int4 quants of the *policy* params only).

We keep ONLY what is needed to ACT in the environment:
  - network_params  (the recurrent ConvLSTM, 1.28M params)
  - actor_params    (the action head)
We drop:
  - opt_state       (Adam moments — pure training overhead, ~15MB)
  - critic_params   (value head — only used for training the policy, not to act)

Quantization: symmetric per-tensor int8 and group-wise int4 (group=64) on the
float32 weights. Round-trip is checked (dequant max abs error reported).
The runtime is JAX/flax via github.com/AlignmentResearch/learned-planner; the
tape bundle ships the quantized weights + cfg.json (architecture) + a manifest.
"""
import msgpack, numpy as np, json, os, struct, hashlib, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CKPT = os.path.join(HERE, "drc33/bkynosqi/cp_2002944000")
MODEL = os.path.join(CKPT, "model")
CFG = os.path.join(CKPT, "cfg.json")
OUT = os.path.join(HERE, "build")
os.makedirs(OUT, exist_ok=True)


def decode_arr(ext):
    shape, dtype, buf = msgpack.unpackb(ext.data, raw=False, strict_map_key=False)
    return np.frombuffer(buf, dtype=np.dtype(dtype)).reshape(shape).astype(np.float32)


def walk(d, prefix=""):
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out += walk(v, prefix + "/" + k)
        else:
            out.append((prefix + "/" + k, v))
    return out


def quant_int8(a):
    """Symmetric per-tensor int8. Returns (qbytes, scale)."""
    amax = float(np.abs(a).max())
    scale = amax / 127.0 if amax > 0 else 1.0
    q = np.clip(np.round(a / scale), -127, 127).astype(np.int8)
    return q, scale


def quant_int4_group(a, group=64):
    """Group-wise symmetric int4 (range -7..7), packed 2-per-byte. Returns (packed, scales)."""
    flat = a.ravel()
    n = flat.size
    pad = (-n) % group
    if pad:
        flat = np.concatenate([flat, np.zeros(pad, np.float32)])
    g = flat.reshape(-1, group)
    amax = np.abs(g).max(axis=1, keepdims=True)
    scales = np.where(amax > 0, amax / 7.0, 1.0).astype(np.float32)
    q = np.clip(np.round(g / scales), -7, 7).astype(np.int8)  # -7..7
    qu = (q + 8).astype(np.uint8)  # 0..15
    qu = qu.ravel()
    packed = (qu[0::2] | (qu[1::2] << 4)).astype(np.uint8)
    return packed, scales.ravel(), n


def main():
    raw = open(MODEL, "rb").read()
    obj = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    params = obj["params"]["params"]
    leaves = walk(params)

    # keep network_params + actor_params, drop critic
    keep = [(n, e) for n, e in leaves if not n.startswith("/critic")]
    arrays = {n: decode_arr(e) for n, e in keep}
    n_params = sum(a.size for a in arrays.values())
    fp32_bytes = sum(a.nbytes for a in arrays.values())

    # ---- int8 bundle ----
    i8_blob = {"meta": {}, "scales": {}}
    i8_raw = bytearray()
    layout8 = {}
    roundtrip_err8 = 0.0
    for n, a in arrays.items():
        q, s = quant_int8(a)
        deq = q.astype(np.float32) * s
        roundtrip_err8 = max(roundtrip_err8, float(np.abs(deq - a).max()))
        off = len(i8_raw)
        i8_raw += q.tobytes()
        layout8[n] = {"shape": list(a.shape), "offset": off, "nbytes": q.nbytes, "scale": s}
    i8_manifest = json.dumps(layout8).encode()
    i8_bundle = struct.pack("<I", len(i8_manifest)) + i8_manifest + bytes(i8_raw)

    # ---- int4 bundle ----
    i4_raw = bytearray()
    layout4 = {}
    roundtrip_err4 = 0.0
    for n, a in arrays.items():
        packed, scales, n_orig = quant_int4_group(a)
        # dequant to check
        qu = np.empty(((len(packed) * 2)), np.uint8)
        qu[0::2] = packed & 0x0F
        qu[1::2] = packed >> 4
        q = qu.astype(np.int8) - 8
        sc = np.repeat(scales, 64)[: q.size]
        deq = (q.astype(np.float32) * sc)[:n_orig].reshape(a.shape)
        roundtrip_err4 = max(roundtrip_err4, float(np.abs(deq - a).max()))
        off = len(i4_raw)
        i4_raw += scales.astype(np.float32).tobytes() + packed.tobytes()
        layout4[n] = {"shape": list(a.shape), "n": n_orig,
                      "scales_off": off, "n_scales": len(scales),
                      "packed_off": off + scales.nbytes, "n_packed": len(packed)}
    i4_manifest = json.dumps(layout4).encode()
    i4_bundle = struct.pack("<I", len(i4_manifest)) + i4_manifest + bytes(i4_raw)

    # cfg (architecture) — strip to the net config to keep it small
    cfg = json.load(open(CFG))
    net_cfg = {"net": cfg["cfg"]["net"], "params": n_params,
               "model": "DRC(3,3)", "task": "Sokoban (Boxoban)"}
    cfg_blob = json.dumps(net_cfg).encode()

    # write raw quants
    open(os.path.join(OUT, "drc33_int8.bin"), "wb").write(i8_bundle)
    open(os.path.join(OUT, "drc33_int4.bin"), "wb").write(i4_bundle)
    open(os.path.join(OUT, "drc33_net_cfg.json"), "wb").write(cfg_blob)

    # ---- tape bundle = int4 weights + cfg + runtime manifest, lzma -9e ----
    runtime_manifest = json.dumps({
        "model": "learned-planner DRC(3,3) Sokoban",
        "license": "Apache-2.0",
        "params": n_params,
        "quant": "int4 group=64 symmetric (policy params only; opt_state+critic dropped)",
        "runtime": "JAX/flax via github.com/AlignmentResearch/learned-planner (cleanba.convlstm ConvLSTM)",
        "note": "A cassette that plans: recurrent ConvLSTM that solves Sokoban by internal iterative planning.",
    }).encode()

    def xz_compress(b):
        """Compress bytes with `xz -9e` (CLI; python lzma unavailable in this build)."""
        return subprocess.run(["xz", "-9e", "-c", "-T", "1"], input=b,
                              stdout=subprocess.PIPE, check=True).stdout

    def lzma_sz(b):
        return len(xz_compress(b))

    # int8 tape size
    tape_i8 = i8_bundle + b"\x00CFG\x00" + cfg_blob + b"\x00RT\x00" + runtime_manifest
    tape_i4 = i4_bundle + b"\x00CFG\x00" + cfg_blob + b"\x00RT\x00" + runtime_manifest
    on_tape_i8 = lzma_sz(tape_i8)
    on_tape_i4 = lzma_sz(tape_i4)

    # write the chosen (int4) tape bundle to disk
    open(os.path.join(OUT, "drc33_tape_int4.xz"), "wb").write(xz_compress(tape_i4))
    open(os.path.join(OUT, "drc33_tape_int8.xz"), "wb").write(xz_compress(tape_i8))

    result = {
        "n_params": n_params,
        "fp32_mb": round(fp32_bytes / 1e6, 3),
        "int8_bundle_mb": round(len(i8_bundle) / 1e6, 3),
        "int4_bundle_mb": round(len(i4_bundle) / 1e6, 3),
        "on_tape_int8_mb": round(on_tape_i8 / 1e6, 4),
        "on_tape_int4_mb": round(on_tape_i4 / 1e6, 4),
        "roundtrip_err_int8": roundtrip_err8,
        "roundtrip_err_int4": roundtrip_err4,
    }
    print(json.dumps(result, indent=2))
    json.dump(result, open(os.path.join(OUT, "quant_report.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
