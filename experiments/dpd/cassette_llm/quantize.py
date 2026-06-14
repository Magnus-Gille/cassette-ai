"""Quantize stories260K, measure the PACKED cassette payload (weights + scales + norms
+ tokenizer + header), and re-generate to check coherence survives. Compares against the
measured cassette byte-exact budget (~20 B/s reliable).
"""
import numpy as np, warnings
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
import cassette_gpt as G

TOK_BYTES = 6227          # tok512.bin (must ship to decode)
HEADER = 64               # config header
NORM_KEYS = lambda W: [k for k in W if k.endswith("norm.weight")]
BIG_KEYS = lambda W: [k for k in W if k.endswith(".weight") and not k.endswith("norm.weight")
                      and k != "output.weight"]   # output is tied -> not stored


def q_int8(w):
    s = np.abs(w).max(1, keepdims=True) / 127 + 1e-12
    q = np.round(w / s).clip(-127, 127)
    bytes_ = w.size * 1 + w.shape[0] * 2          # int8 + fp16 row scales
    return q * s, bytes_


def q_int4(w, group=32):
    flat = w.reshape(-1); n = flat.size; pad = (-n) % group
    f = np.concatenate([flat, np.zeros(pad)]).reshape(-1, group)
    s = np.abs(f).max(1, keepdims=True) / 7 + 1e-12
    q = np.round(f / s).clip(-7, 7)
    deq = (q * s).reshape(-1)[:n].reshape(w.shape)
    bytes_ = int(np.ceil(n * 0.5)) + f.shape[0] * 2   # 4-bit packed + fp16 group scales
    return deq, bytes_


def q_ternary(w):
    s = np.abs(w).mean(1, keepdims=True) + 1e-12      # BitNet b1.58 absmean scale
    q = np.round(w / s).clip(-1, 1)
    bytes_ = int(np.ceil(w.size * np.log2(3) / 8)) + w.shape[0] * 2  # ~1.58 bit + fp16 scales
    return q * s, bytes_


SCHEMES = {"int8": q_int8, "int4(g32)": q_int4, "ternary(1.58b)": q_ternary}


def build(W, qfn):
    Wq = {}; total = HEADER + TOK_BYTES
    for k in NORM_KEYS(W):                      # norms: keep fp16 (tiny)
        Wq[k] = W[k].astype(np.float16).astype(np.float32); total += W[k].size * 2
    for k in BIG_KEYS(W):
        Wq[k], b = qfn(W[k]); total += b
    Wq["output.weight"] = Wq["tok_embeddings.weight"]   # tied
    return Wq, total


def cassette_time(nbytes, Bps=20.0):
    return nbytes / Bps / 60                    # minutes of tape at the reliable rate


if __name__ == "__main__":
    W = G.load_weights(); vocab = G.load_vocab()
    fp32 = sum(W[k].size for k in BIG_KEYS(W)) * 4 + TOK_BYTES + HEADER
    print(f"{'scheme':<16}{'payload':>10}{'tape@20B/s':>12}   fits?")
    print(f"{'fp32':<16}{fp32/1024:>8.0f}KB{cassette_time(fp32):>10.0f}min   (reference)")
    samples = {}
    for name, qfn in SCHEMES.items():
        Wq, total = build(W, qfn)
        story = G.generate(Wq, vocab, n=110, temp=0.0)
        samples[name] = story
        tapes = []
        for tape, mins in [("C60", 60), ("C90", 90), ("C120", 120)]:
            if cassette_time(total) <= mins: tapes.append(tape)
        fit = tapes[0] if tapes else "no (needs headroom/bigger tape)"
        print(f"{name:<16}{total/1024:>8.1f}KB{cassette_time(total):>10.1f}min   {fit}")
    print()
    for name, story in samples.items():
        print(f"--- {name} (greedy) ---\n{story.replace(chr(60)+'0x0A'+chr(62), chr(10))[:300]}\n")
