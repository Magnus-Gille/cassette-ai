#!/usr/bin/env python3
"""Shared int4/int8 group-wise symmetric quantizer for the cassette payload campaign.

Tape-ready bundle = packed quantized weights (2 int4/byte or 1 int8/byte) +
per-group fp16 scales + fp16 LayerNorm/bias/small vectors + tokenizer/config JSON.
The bundle is then xz -9e (LZMA2) compressed to get the on-tape size.

Quant scheme (per 2D matrix, row-wise groups of GROUP cols):
  q = round(w / scale) clamped to [-(2^(b-1)-1), 2^(b-1)-1]   (symmetric, no zero-point)
  scale = max|w_group| / (2^(b-1)-1)   per group, stored fp16
Round-trip dequant error is reported so we never ship a corrupt quant.
"""
import json, struct, numpy as np

def _quantize_matrix(w, bits, group):
    # w: (rows, cols) float32. Row-wise groups along cols.
    rows, cols = w.shape
    qmax = (1 << (bits - 1)) - 1   # int4 -> 7, int8 -> 127
    g = group if group and group < cols else cols
    # pad cols to multiple of g
    ng = (cols + g - 1) // g
    scales = np.zeros((rows, ng), dtype=np.float32)
    q = np.zeros((rows, cols), dtype=np.int8)
    for gi in range(ng):
        c0, c1 = gi * g, min((gi + 1) * g, cols)
        blk = w[:, c0:c1]
        amax = np.abs(blk).max(axis=1)
        amax[amax == 0] = 1e-8
        sc = amax / qmax
        scales[:, gi] = sc
        qb = np.round(blk / sc[:, None]).clip(-qmax, qmax).astype(np.int8)
        q[:, c0:c1] = qb
    return q, scales.astype(np.float16), g

def _dequantize_matrix(q, scales, group):
    rows, cols = q.shape
    g = group
    out = np.zeros((rows, cols), dtype=np.float32)
    ng = scales.shape[1]
    sc = scales.astype(np.float32)
    for gi in range(ng):
        c0, c1 = gi * g, min((gi + 1) * g, cols)
        out[:, c0:c1] = q[:, c0:c1].astype(np.float32) * sc[:, gi][:, None]
    return out

def _pack_int4(q):
    # q in [-7,7] -> nibble [0,15] (offset +8). Pack 2/byte, row-major flat.
    flat = (q.astype(np.int16) + 8).astype(np.uint8).reshape(-1)
    if flat.size % 2:
        flat = np.concatenate([flat, np.zeros(1, dtype=np.uint8)])
    hi = flat[0::2]; lo = flat[1::2]
    return ((hi << 4) | lo).astype(np.uint8)

def quantize_state_dict(sd, bits, group, min_quant_numel=4096):
    """sd: dict name->float32 np.array. Returns (bundle_bytes, manifest, roundtrip_max_relerr)."""
    blobs = {}       # name -> bytes
    meta = {}        # name -> dict describing how to reconstruct
    max_relerr = 0.0
    for name, w in sd.items():
        w = np.asarray(w, dtype=np.float32)
        if w.ndim == 2 and w.size >= min_quant_numel:
            q, scales, g = _quantize_matrix(w, bits, group)
            packed = _pack_int4(q) if bits == 4 else q.astype(np.int8)
            blobs[name + '.q'] = packed.tobytes()
            blobs[name + '.s'] = scales.tobytes()
            # round-trip check
            dq = _dequantize_matrix(q, scales, g)
            denom = np.abs(w).mean() + 1e-9
            relerr = float(np.abs(dq - w).mean() / denom)
            max_relerr = max(max_relerr, relerr)
            meta[name] = {'kind': f'int{bits}', 'shape': list(w.shape), 'group': g}
        else:
            # keep small/1D tensors as fp16 (LayerNorm, bias, embeddings tail, etc.)
            blobs[name + '.h'] = w.astype(np.float16).tobytes()
            meta[name] = {'kind': 'fp16', 'shape': list(w.shape)}
    # serialize bundle: simple length-prefixed blob store + json manifest
    order = list(blobs.keys())
    buf = bytearray()
    header = {'order': order, 'meta': meta, 'bits': bits, 'group': group}
    hjson = json.dumps(header).encode()
    buf += struct.pack('<I', len(hjson)); buf += hjson
    for k in order:
        b = blobs[k]
        buf += struct.pack('<I', len(b)); buf += b
    return bytes(buf), header, max_relerr

def load_bundle(buf):
    """Reconstruct fp32 state dict from a bundle (round-trip sanity)."""
    off = 0
    (hlen,) = struct.unpack_from('<I', buf, off); off += 4
    header = json.loads(buf[off:off+hlen]); off += hlen
    blobs = {}
    for k in header['order']:
        (blen,) = struct.unpack_from('<I', buf, off); off += 4
        blobs[k] = buf[off:off+blen]; off += blen
    bits = header['bits']
    sd = {}
    for name, m in header['meta'].items():
        shape = tuple(m['shape'])
        if m['kind'] == 'fp16':
            sd[name] = np.frombuffer(blobs[name + '.h'], dtype=np.float16).astype(np.float32).reshape(shape)
        else:
            rows, cols = shape
            g = m['group']
            ng = (cols + g - 1) // g
            scales = np.frombuffer(blobs[name + '.s'], dtype=np.float16).reshape(rows, ng)
            if bits == 4:
                packed = np.frombuffer(blobs[name + '.q'], dtype=np.uint8)
                nib = np.empty(packed.size * 2, dtype=np.uint8)
                nib[0::2] = packed >> 4
                nib[1::2] = packed & 0x0F
                q = (nib[:rows*cols].astype(np.int16) - 8).astype(np.int8).reshape(rows, cols)
            else:
                q = np.frombuffer(blobs[name + '.q'], dtype=np.int8).reshape(rows, cols)
            sd[name] = _dequantize_matrix(q, scales, g)
    return sd
