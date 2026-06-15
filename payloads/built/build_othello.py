#!/usr/bin/env python3
"""Build tape-ready bundle for Baidicoot/Othello-GPT-Transformer-Lens (MIT). int4 + int8.

minGPT state dict. attn.mask buffers are constant causal masks -> dropped (runtime regenerates).
Vocab is the 61-token Othello board vocab (no tokenizer file needed; config.json carries dims).
"""
import sys, os, json, subprocess
import numpy as np, torch
sys.path.insert(0, os.path.dirname(__file__))
from quantize_lib import quantize_state_dict, load_bundle

ROOT = os.path.dirname(__file__)
SRC = os.path.join(ROOT, 'othello-gpt', 'src')
OUT = os.path.join(ROOT, 'othello-gpt')

def read_sd():
    # weights_only=True: refuse to unpickle arbitrary code from a 3rd-party .pth
    sd = torch.load(os.path.join(SRC, 'final.pth'), map_location='cpu', weights_only=True)
    if hasattr(sd, 'state_dict'):
        sd = sd.state_dict()
    out = {}
    for k, v in sd.items():
        if k.endswith('attn.mask'):
            continue  # constant causal mask buffer, regenerated at runtime
        out[k] = v.detach().cpu().numpy().astype(np.float32)
    return out

def xz_size(data, path):
    with open(path, 'wb') as fh:
        fh.write(data)
    subprocess.run(['xz', '-9e', '-f', '-k', path], check=True)
    return os.path.getsize(path + '.xz')

def main():
    sd = read_sd()
    aux = {'config.json': open(os.path.join(SRC, 'config.json')).read()}
    aux_bytes = json.dumps(aux).encode()
    results = {}
    for bits in (4, 8):
        group = 64 if bits == 4 else 128
        # pos_emb is (1,59,512) 3D -> squeeze to 2D for quant
        sd2 = {}
        for k, v in sd.items():
            if v.ndim == 3 and v.shape[0] == 1:
                sd2[k] = v.reshape(v.shape[1], v.shape[2])
            else:
                sd2[k] = v
        bundle, header, relerr = quantize_state_dict(sd2, bits, group)
        rt = load_bundle(bundle)
        ok = True
        for name in ['tok_emb.weight', 'blocks.0.attn.key.weight']:
            orig = sd2[name].astype(np.float32); rec = rt[name]
            if rec.shape != orig.shape: ok = False
            err = np.abs(rec - orig).mean() / (np.abs(orig).mean() + 1e-9)
            if err > 0.5: ok = False
        full = bundle + b'\x00AUX\x00' + aux_bytes
        raw_path = os.path.join(OUT, f'othello_int{bits}.bin')
        on_tape = xz_size(full, raw_path)
        results[bits] = {
            'raw_bundle_bytes': len(full),
            'on_tape_bytes': on_tape,
            'on_tape_mb': round(on_tape/1e6, 4),
            'raw_bundle_mb': round(len(full)/1e6, 4),
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
