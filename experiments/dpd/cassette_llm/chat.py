"""Interactive playground for stories260K — the cassette-sized LLM.

NOTE: this is a TinyStories *completion* model, not an instruct/chat model. You give it
the start of a story (or any text) and it continues it. Type a line and watch it write.

Commands:
  /fp32        use full-precision weights (best quality)   [default]
  /int4        use the int4 cassette-quantized weights (the 150 KB tape version)
  /temp 0.8    set sampling temperature (0 = greedy/deterministic)
  /len 200     set max new tokens
  /reset       forget the running story
  /quit
"""
import sys, numpy as np, warnings
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
import sentencepiece as spm
import cassette_gpt as G
import quantize as Q

sp = spm.SentencePieceProcessor(model_file="tok512.model")
Wfp = G.load_weights()
Wi4, i4_bytes = Q.build(Wfp, Q.q_int4)
MODELS = {"fp32": Wfp, "int4": Wi4}


def gen_stream(W, ids, n, temp, rng):
    for _ in range(n):
        logits = G.forward(ids[-G.CFG["seq"]:], W)
        if temp == 0: nxt = int(logits.argmax())
        else:
            p = G.softmax(logits / temp); nxt = int(rng.choice(len(p), p=p))
        if nxt == sp.eos_id(): break
        ids.append(nxt); yield nxt


def main():
    mode = "fp32"; temp = 0.8; maxlen = 200; rng = np.random.default_rng()
    ids = [sp.bos_id()]
    print(f"\n  stories260K playground — {len(Wfp['tok_embeddings.weight'])*0+260032:,}-param TinyStories model")
    print(f"  int4 cassette payload = {i4_bytes/1024:.0f} KB. It CONTINUES text — give it a story opening.")
    print("  commands: /int4 /fp32 /temp N /len N /reset /quit\n")
    while True:
        try: line = input(f"[{mode} t={temp}] you> ").strip()
        except (EOFError, KeyboardInterrupt): print(); break
        if not line: continue
        if line.startswith("/"):
            c = line.split(); cmd = c[0]
            if cmd == "/quit": break
            elif cmd in ("/fp32", "/int4"): mode = cmd[1:]; print(f"  -> {mode} weights")
            elif cmd == "/temp" and len(c) > 1: temp = float(c[1])
            elif cmd == "/len" and len(c) > 1: maxlen = int(c[1])
            elif cmd == "/reset": ids = [sp.bos_id()]; print("  -> story reset")
            else: print("  ? unknown/!args")
            continue
        # append the user's text to the running story, then continue it
        ids += sp.encode(" " + line if len(ids) > 1 else line)
        sys.stdout.write("  model> "); sys.stdout.flush()
        prev = sp.decode(ids)
        for _ in gen_stream(MODELS[mode], ids, maxlen, temp, rng):
            full = sp.decode(ids); sys.stdout.write(full[len(prev):]); sys.stdout.flush(); prev = full
        print("\n")


if __name__ == "__main__":
    main()
