import sys, pathlib, numpy as np
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for p in ["src","tests/e2e","experiments/tape_v2","experiments/deepdive2","experiments/capacity"]:
    sys.path.insert(0, str(ROOT/p))
import assault_widespace as ws
from real_channel_sim import load_params
params = load_params()
wsc = ws.build(16,1,3,256)
SEEDS=4
def ws_test(cap, rs_k):
    n=0
    for s in range(SEEDS):
        r = ws.rs_closure_test(wsc, params, cap, detector="contrast",
                               rs_n=255, rs_k=rs_k, payload_len=8000, seed=s)
        n += int(bool(r["byte_exact"]))
    return n, SEEDS
print("=== WS (Claude) AAC robustness ===")
for cap in ["master3","master2"]:
    a=ws_test(cap,127); b=ws_test(cap,111)
    print(f"[{cap}] WS(255,127): {a[0]}/{a[1]}   WS(255,111): {b[0]}/{b[1]}")
