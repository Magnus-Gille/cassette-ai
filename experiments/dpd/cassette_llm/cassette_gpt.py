"""stories260K (Karpathy / TinyStories) -> numpy forward pass + quantization, to test
"an LLM on a cassette". Tied embeddings => 260,032 unique weights. We quantize the
weights, measure the PACKED payload (what goes on tape), and re-run to check the
quantized model still writes coherent stories.
"""
import struct, numpy as np, torch

CFG = dict(dim=64, n_layers=5, n_heads=8, n_kv_heads=4, vocab=512, seq=512, eps=1e-5)


def load_weights(pt="stories260K.pt"):
    sd = torch.load(pt, map_location="cpu", weights_only=True)["model"]
    return {k.replace("_orig_mod.", ""): v.float().numpy() for k, v in sd.items()}


# ---------------- tokenizer (decode only, from llama2.c tok512.bin) ----------------
def load_vocab(path="tok512.bin"):
    with open(path, "rb") as f:
        data = f.read()
    (_maxlen,) = struct.unpack("i", data[:4]); off = 4; vocab = []
    for _ in range(CFG["vocab"]):
        (_score,) = struct.unpack("f", data[off:off + 4]); off += 4
        (ln,) = struct.unpack("i", data[off:off + 4]); off += 4
        vocab.append(data[off:off + ln].decode("utf-8", "replace")); off += ln
    return vocab


def decode(ids, vocab):
    out = []
    for i, t in enumerate(ids):
        s = vocab[t]
        if i == 0 and s.startswith(" "): s = s[1:]
        out.append(s.replace("▁", " "))
    return "".join(out)


# ---------------- forward (fp32 numpy) ----------------
def rmsnorm(x, w, eps):
    return x * w / np.sqrt(np.mean(x ** 2, -1, keepdims=True) + eps)


def softmax(x):
    e = np.exp(x - x.max(-1, keepdims=True)); return e / e.sum(-1, keepdims=True)


def forward(tokens, W, cfg=CFG):
    dim, nh, nkv, eps = cfg["dim"], cfg["n_heads"], cfg["n_kv_heads"], cfg["eps"]
    hd = dim // nh; rep = nh // nkv; T = len(tokens)
    x = W["tok_embeddings.weight"][tokens]                       # (T, dim)
    # RoPE tables
    inv = 1.0 / (10000 ** (np.arange(0, hd, 2) / hd))
    pos = np.arange(T)[:, None] * inv[None, :]
    cos = np.cos(pos); sin = np.sin(pos)                          # (T, hd/2)
    def rope(v):  # v: (T, heads, hd)
        v1, v2 = v[..., 0::2], v[..., 1::2]
        return np.stack([v1 * cos[:, None, :] - v2 * sin[:, None, :],
                         v1 * sin[:, None, :] + v2 * cos[:, None, :]], -1).reshape(v.shape)
    mask = np.triu(np.full((T, T), -1e9), 1)
    for l in range(cfg["n_layers"]):
        p = f"layers.{l}."
        xn = rmsnorm(x, W[p + "attention_norm.weight"], eps)
        q = (xn @ W[p + "attention.wq.weight"].T).reshape(T, nh, hd)
        k = (xn @ W[p + "attention.wk.weight"].T).reshape(T, nkv, hd)
        v = (xn @ W[p + "attention.wv.weight"].T).reshape(T, nkv, hd)
        q = rope(q); k = rope(k)
        k = np.repeat(k, rep, 1); v = np.repeat(v, rep, 1)        # GQA expand
        att = np.einsum("thd,shd->hts", q, k) / np.sqrt(hd) + mask
        out = np.einsum("hts,shd->thd", softmax(att), v).reshape(T, dim)
        x = x + out @ W[p + "attention.wo.weight"].T
        xn = rmsnorm(x, W[p + "ffn_norm.weight"], eps)
        g = xn @ W[p + "feed_forward.w1.weight"].T
        g = g * (1 / (1 + np.exp(-g)))                            # SiLU
        h = (g * (xn @ W[p + "feed_forward.w3.weight"].T)) @ W[p + "feed_forward.w2.weight"].T
        x = x + h
    x = rmsnorm(x, W["norm.weight"], eps)
    return x[-1] @ W["tok_embeddings.weight"].T                   # tied output -> logits (vocab,)


def generate(W, vocab, n=220, temp=0.8, seed=1, cfg=CFG):
    rng = np.random.default_rng(seed); ids = [1]                  # BOS
    for _ in range(n):
        logits = forward(ids[-cfg["seq"]:], W, cfg)
        if temp == 0: nxt = int(logits.argmax())
        else:
            p = softmax(logits / temp); nxt = int(rng.choice(len(p), p=p))
        if nxt == 2: break                                       # EOS
        ids.append(nxt)
    return decode(ids[1:], vocab)


if __name__ == "__main__":
    W = load_weights(); vocab = load_vocab()
    nparams = sum(v.size for k, v in W.items() if k != "output.weight")
    print(f"stories260K: {nparams:,} unique params (tied) = {nparams*4/1024:.0f} KB fp32\n")
    print("--- baseline fp32 story ---")
    print(generate(W, vocab))
