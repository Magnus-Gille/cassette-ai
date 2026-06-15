#!/usr/bin/env python3
"""Build tape-ready bundle for derickio/chess-gpt-4.5M (MIT). int4 + int8."""
import sys, os, json, subprocess, tempfile
import numpy as np
from safetensors import safe_open
sys.path.insert(0, os.path.dirname(__file__))
from quantize_lib import quantize_state_dict, load_bundle

ROOT = os.path.dirname(__file__)
SRC = os.path.join(ROOT, 'chess-gpt-4.5M', 'src')
OUT = os.path.join(ROOT, 'chess-gpt-4.5M')

def read_sd():
    f = safe_open(os.path.join(SRC, 'model.safetensors'), 'np')
    return {k: f.get_tensor(k) for k in f.keys()}

def xz_size(data, path):
    with open(path, 'wb') as fh:
        fh.write(data)
    subprocess.run(['xz', '-9e', '-f', '-k', path], check=True)
    return os.path.getsize(path + '.xz')

def main():
    sd = read_sd()
    # tokenizer + config as a small JSON blob (part of the on-tape bundle)
    aux = {}
    for fn in ['config.json', 'vocab.json', 'generation_config.json']:
        p = os.path.join(SRC, fn)
        if os.path.exists(p):
            aux[fn] = open(p).read()
    aux_bytes = json.dumps(aux).encode()

    results = {}
    for bits in (4, 8):
        group = 64 if bits == 4 else 128
        bundle, header, relerr = quantize_state_dict(sd, bits, group)
        # round-trip sanity: reconstruct and compare a couple tensors
        rt = load_bundle(bundle)
        ok = True
        for name in ['transformer.wte.weight', 'transformer.h.0.mlp.c_fc.weight']:
            orig = sd[name].astype(np.float32)
            rec = rt[name]
            if rec.shape != orig.shape:
                ok = False
            # mean abs err relative to scale
            err = np.abs(rec - orig).mean() / (np.abs(orig).mean() + 1e-9)
            if err > 0.5:
                ok = False
        full = bundle + b'\x00AUX\x00' + aux_bytes
        raw_path = os.path.join(OUT, f'chess_gpt_int{bits}.bin')
        with open(raw_path, 'wb') as fh:
            fh.write(full)
        on_tape = xz_size(full, raw_path)
        results[bits] = {
            'raw_bundle_bytes': len(full),
            'on_tape_bytes': on_tape,
            'on_tape_mb': round(on_tape / 1e6, 4),
            'raw_bundle_mb': round(len(full) / 1e6, 4),
            'max_relerr': round(relerr, 5),
            'roundtrip_ok': bool(ok),
            'group': group,
        }
        print(f'int{bits}: raw {len(full)/1e6:.3f}MB -> on-tape {on_tape/1e6:.4f}MB | relerr {relerr:.4f} | rt_ok {ok}')
    print(json.dumps(results))
    with open(os.path.join(OUT, '_build_results.json'), 'w') as fh:
        json.dump(results, fh, indent=2)

if __name__ == '__main__':
    main()
