#!/usr/bin/env python3
"""Quantize 1aurent/ddpm-mnist (UNet2D DDPM, ~1.07M params) to a tape-ready bundle.

Input : diffusion_pytorch_model.safetensors (fp32, 4.26MB)
Output: build/ ... int8 + int4 quants + the diffusion runtime config, xz-compressed.

Quantization: symmetric per-tensor int8 and group-wise int4 (group=64).
Norm/bias params (1-D, tiny) are kept at int8 in the int4 path too (they're cheap
and quantizing them coarsely hurts the denoiser). Round-trip max-abs error reported.

Runtime: diffusers `DDPMPipeline` (UNet2D denoiser + DDPM scheduler). The tape
bundle ships quantized weights + config.json (UNet arch) + scheduler_config.json.
"""
import json, os, struct, subprocess
import numpy as np
from safetensors import safe_open

HERE = os.path.dirname(os.path.abspath(__file__))
ST = os.path.join(HERE, "diffusion_pytorch_model.safetensors")
OUT = os.path.join(HERE, "build")
os.makedirs(OUT, exist_ok=True)


def xz_compress(b):
    return subprocess.run(["xz", "-9e", "-c", "-T", "1"], input=b,
                          stdout=subprocess.PIPE, check=True).stdout


def quant_int8(a):
    amax = float(np.abs(a).max())
    s = amax / 127.0 if amax > 0 else 1.0
    q = np.clip(np.round(a / s), -127, 127).astype(np.int8)
    return q, s


def quant_int4_group(a, group=64):
    flat = a.ravel().astype(np.float32)
    n = flat.size
    pad = (-n) % group
    if pad:
        flat = np.concatenate([flat, np.zeros(pad, np.float32)])
    g = flat.reshape(-1, group)
    amax = np.abs(g).max(axis=1, keepdims=True)
    scales = np.where(amax > 0, amax / 7.0, 1.0).astype(np.float32)
    q = np.clip(np.round(g / scales), -7, 7).astype(np.int8)
    qu = (q + 8).astype(np.uint8).ravel()
    packed = (qu[0::2] | (qu[1::2] << 4)).astype(np.uint8)
    return packed, scales.ravel(), n


def main():
    tensors = {}
    with safe_open(ST, framework="numpy") as f:
        for k in f.keys():
            tensors[k] = f.get_tensor(k).astype(np.float32)

    n_params = sum(t.size for t in tensors.values())
    fp32_bytes = sum(t.nbytes for t in tensors.values())

    # ---- int8 ----
    i8_raw = bytearray()
    layout8 = {}
    err8 = 0.0
    for k, a in tensors.items():
        q, s = quant_int8(a)
        deq = q.astype(np.float32) * s
        err8 = max(err8, float(np.abs(deq - a).max()))
        layout8[k] = {"shape": list(a.shape), "offset": len(i8_raw),
                      "nbytes": q.nbytes, "scale": s}
        i8_raw += q.tobytes()
    m8 = json.dumps(layout8).encode()
    i8_bundle = struct.pack("<I", len(m8)) + m8 + bytes(i8_raw)

    # ---- int4 (1-D params stay int8 — they're tiny and matter to the denoiser) ----
    i4_raw = bytearray()
    layout4 = {}
    err4 = 0.0
    for k, a in tensors.items():
        if a.ndim <= 1:  # bias / norm -> int8
            q, s = quant_int8(a)
            deq = q.astype(np.float32) * s
            err4 = max(err4, float(np.abs(deq - a).max()))
            layout4[k] = {"mode": "int8", "shape": list(a.shape),
                          "offset": len(i4_raw), "nbytes": q.nbytes, "scale": s}
            i4_raw += q.tobytes()
        else:
            packed, scales, n_orig = quant_int4_group(a)
            qu = np.empty(len(packed) * 2, np.uint8)
            qu[0::2] = packed & 0x0F
            qu[1::2] = packed >> 4
            q = qu.astype(np.int8) - 8
            sc = np.repeat(scales, 64)[: q.size]
            deq = (q.astype(np.float32) * sc)[:n_orig].reshape(a.shape)
            err4 = max(err4, float(np.abs(deq - a).max()))
            off = len(i4_raw)
            layout4[k] = {"mode": "int4", "shape": list(a.shape), "n": n_orig,
                          "scales_off": off, "n_scales": len(scales),
                          "packed_off": off + scales.astype(np.float32).nbytes,
                          "n_packed": len(packed)}
            i4_raw += scales.astype(np.float32).tobytes() + packed.tobytes()
    m4 = json.dumps(layout4).encode()
    i4_bundle = struct.pack("<I", len(m4)) + m4 + bytes(i4_raw)

    # runtime config (UNet arch + scheduler) — needed to actually denoise
    unet_cfg = open(os.path.join(HERE, "config.json"), "rb").read()
    sched_cfg = open(os.path.join(HERE, "scheduler_config.json"), "rb").read()
    rt = json.dumps({
        "model": "1aurent/ddpm-mnist UNet2D DDPM",
        "license": "MIT",
        "params": n_params,
        "runtime": "diffusers DDPMPipeline (UNet2D denoiser + DDPM scheduler)",
        "note": "Paints digits: unconditional MNIST-style digit generation.",
    }).encode()

    open(os.path.join(OUT, "ddpm_int8.bin"), "wb").write(i8_bundle)
    open(os.path.join(OUT, "ddpm_int4.bin"), "wb").write(i4_bundle)

    sep = b"\x00CFG\x00"
    tape_i8 = i8_bundle + sep + unet_cfg + sep + sched_cfg + sep + rt
    tape_i4 = i4_bundle + sep + unet_cfg + sep + sched_cfg + sep + rt
    xz8 = xz_compress(tape_i8)
    xz4 = xz_compress(tape_i4)
    open(os.path.join(OUT, "ddpm_tape_int8.xz"), "wb").write(xz8)
    open(os.path.join(OUT, "ddpm_tape_int4.xz"), "wb").write(xz4)

    res = {
        "n_params": n_params,
        "fp32_mb": round(fp32_bytes / 1e6, 3),
        "int8_bundle_mb": round(len(i8_bundle) / 1e6, 3),
        "int4_bundle_mb": round(len(i4_bundle) / 1e6, 3),
        "on_tape_int8_mb": round(len(xz8) / 1e6, 4),
        "on_tape_int4_mb": round(len(xz4) / 1e6, 4),
        "roundtrip_err_int8": err8,
        "roundtrip_err_int4": err4,
    }
    print(json.dumps(res, indent=2))
    json.dump(res, open(os.path.join(OUT, "quant_report.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
