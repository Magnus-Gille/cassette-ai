"""anchor_test.py — THE CALIBRATION GATE for the BPS-push harness.

Reproduces the known real-tape outcomes so we know which metric to trust:
  PROVEN  : r8  P22 RS179 = 5791 net (RECORD, byte-exact off tape10)
            r6  P21 drop[750] RS159 = 4910 net (DOOM ship tape, byte-exact)
  KILLED  : 6179 P22 RS191 (x12 two-capture gate)
            5247 P16 RS223  (x12 two-capture gate)

r8 and 6179 share the SAME modulation (P22 DQPSK) -> IDENTICAL per-carrier margin.
So margin alone cannot separate them; the discriminator is FEC closure at the
measured raw BER (RS179 closes, RS191 does not). This script prints both metrics
on every anchor so we can SEE which combination reproduces proven-vs-killed, and
establishes r8's empirical margin as the proven floor for the r8-relative gate.
"""
from __future__ import annotations
import json, pathlib, sys, time, traceback
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev
import replay_channel as rc

CHANNELS = ["simB_master3", "replay_tape10"]
N_SEEDS = 4
PAYLOAD_BITS = 6000

# (label, P, rs_k, drop, truth)  truth in {"PROVEN","KILLED"}
ANCHORS = [
    ("r8_P22_rs179_5791",  22, 179, None,    "PROVEN"),
    ("r6_P21drop750_rs159_4910", 21, 159, [750.0], "PROVEN"),
    ("k_P22_rs191_6179",   22, 191, None,    "KILLED"),
    ("k_P16_rs223_5247",   16, 223, None,    "KILLED"),
]

def main():
    t0 = time.time()
    print(f"[anchor] registering replay channels …", flush=True)
    rc.register_replay_channels(["tape10"])
    print(f"[anchor] channels = {CHANNELS}  n_seeds={N_SEEDS}  payload_bits={PAYLOAD_BITS}", flush=True)

    rows = []
    for (label, P, rs_k, drop, truth) in ANCHORS:
        print(f"\n[anchor] === {label}  (truth={truth}) ===", flush=True)
        try:
            sch = ev.build_dense2x_candidate(P, rs_k, drop_freqs_hz=drop, name=label)
            res = ev.evaluate_candidate(sch, channels=CHANNELS,
                                        n_seeds=N_SEEDS, payload_bits=PAYLOAD_BITS)
            res["truth"] = truth
            rows.append(res)
            print(f"  gross={res['gross_bps']:.0f}  cassette_net={res['cassette_net_bps']:.0f}"
                  f"  simB_net_worst={res['simB_net_bps_worst']:.0f}"
                  f"  worst_min_margin={res['worst_min_margin_deg']}"
                  f"  verdict={res['verdict']}", flush=True)
            for ch in CHANNELS:
                pc = res["per_channel"].get(ch, {})
                mar = pc.get("margin", {})
                print(f"    {ch:16s} raw_ber={pc.get('raw_ber'):.4f}"
                      f"  pooled_min_margin={mar.get('pooled_min_margin_deg')}"
                      f"  min_margin_worst_seed={mar.get('min_margin_deg_worst_seed')}"
                      f"  n<15deg={mar.get('n_carriers_below_15deg_max')}", flush=True)
        except Exception as e:
            print(f"  !! FAILED: {e}", flush=True)
            traceback.print_exc()
            rows.append({"name": label, "truth": truth, "error": str(e)})

    out = HERE.parent / "results" / "anchor_calibration.json"
    out.parent.mkdir(exist_ok=True)
    json.dump(rows, open(out, "w"), indent=1)
    print(f"\n[anchor] saved {out}  ({time.time()-t0:.0f}s)", flush=True)

    # ---- verdict on the harness itself ----
    print("\n[anchor] ===== CALIBRATION SUMMARY =====", flush=True)
    print(f"{'anchor':28s} {'truth':7s} {'cass_net':9s} {'simB_net':9s} "
          f"{'m3_ber':7s} {'tp10_ber':8s} {'m3_marg':8s} {'tp10_marg':9s} {'verdict':6s}", flush=True)
    for r in rows:
        if "error" in r:
            print(f"{r['name']:28s} {r['truth']:7s}  ERROR {r['error'][:40]}", flush=True)
            continue
        pc = r["per_channel"]
        def g(ch, k, sub=None):
            e = pc.get(ch, {})
            if sub: e = e.get("margin", {})
            v = e.get(k)
            return v
        print(f"{r['name']:28s} {r['truth']:7s} "
              f"{r['cassette_net_bps']:9.0f} {r['simB_net_bps_worst']:9.0f} "
              f"{g('simB_master3','raw_ber') or 0:7.4f} {g('replay_tape10','raw_ber') or 0:8.4f} "
              f"{g('simB_master3','pooled_min_margin_deg','m') or 0:8.1f} "
              f"{g('replay_tape10','pooled_min_margin_deg','m') or 0:9.1f} "
              f"{r['verdict']:6s}", flush=True)

if __name__ == "__main__":
    main()
