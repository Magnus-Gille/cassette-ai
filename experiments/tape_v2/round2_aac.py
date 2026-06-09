"""Round 2: CSS (Codex) vs WS (Claude) on the master2/AAC faithful profile."""
import sys, pathlib, numpy as np
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for p in ["src","tests/e2e","experiments/tape_v2","experiments/deepdive2","experiments/capacity"]:
    sys.path.insert(0, str(ROOT/p))
import assault_css as css
import assault_widespace as ws
from real_channel_sim import load_params
from m3_codec import Rung
import m3_codec as codec

params = load_params()
rng = np.random.default_rng(7)
payload = bytes(rng.integers(0,256,size=8000,dtype=np.uint8))
SEEDS = 6

# CSS: register a CSS-SAFE rung (RS 255,95) + use robust (255,127)=CSS-FAST
codec.RUNGS_BY_NAME["css_safe"] = Rung(name="css_safe", M=16, K=2, rs_n=255, rs_k=95, frame_bytes=2000)
css.RUNGS_BY_NAME = codec.RUNGS_BY_NAME
sc = css.CSSScheme(sf=6, bw=9000.0, fc=5000.0)
def css_test(cap, rung_name):
    oks=[]
    for s in range(SEEDS):
        ok,_ = css.rs_roundtrip(sc, params, payload, capture=cap, pilot_every=2,
                                rung_name=rung_name, seed_offset=s)
        oks.append(bool(ok))
    return sum(oks), len(oks)

# WS winner: M16,K1,sp3,N256
wsc = ws.build(16,1,3,256)
def ws_test(cap, rs_k):
    oks=[]
    for s in range(SEEDS):
        r = ws.rs_closure_test(wsc, params, cap, detector="contrast",
                               rs_n=255, rs_k=rs_k, payload_len=8000, seed=s)
        oks.append(bool(r[0]))
    return sum(oks), len(oks)

print("=== ROUND 2: AAC robustness (master2) vs clean (master3) ===")
for cap in ["master3","master2"]:
    cf = css_test(cap, "robust")      # CSS-FAST 255,127
    cs = css_test(cap, "css_safe")    # CSS-SAFE 255,95
    print(f"[{cap}] CSS-FAST(255,127): {cf[0]}/{cf[1]}   CSS-SAFE(255,95): {cs[0]}/{cs[1]}")
for cap in ["master3","master2"]:
    w1 = ws_test(cap, 127)
    w2 = ws_test(cap, 111)
    print(f"[{cap}] WS(255,127): {w1[0]}/{w1[1]}   WS(255,111): {w2[0]}/{w2[1]}")
