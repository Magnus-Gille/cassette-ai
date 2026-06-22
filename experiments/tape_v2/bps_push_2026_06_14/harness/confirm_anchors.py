"""confirm_anchors.py — prove the CORRECTED filter (score.py) reproduces reality.

Separation criterion: a config's CLAIM is backed iff its achievable worst-capture
model_net >= its claimed cassette_net (gross*rs_k/255).
  PROVEN (r8 5791, r6 4910) -> backed.   KILLED (6179, 5247) -> not backed.
Also establishes r8's achievable model_net as the campaign reference (the number
a new candidate must EXCEED to be a real record).
"""
from __future__ import annotations
import json, sys, pathlib, time, traceback
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev, score as sc, replay_channel as rc

# try both real burns; fall back gracefully if doom can't be measured
CAPS = []
for cap in ("tape10", "doom"):
    try:
        rc.register_replay_channels([cap]); CAPS.append(f"replay_{cap}")
        print(f"[ok] registered replay_{cap}", flush=True)
    except Exception as e:
        print(f"[warn] could not register replay_{cap}: {e}", flush=True)
FAITHFUL = tuple(CAPS)

ANCHORS = [
    ("r8_P22_rs179",  22, 179, None,    5791.2, "PROVEN"),
    ("r6_P21drop_rs159", 21, 159, [750.0], 4910.3, "PROVEN"),
    ("k_P22_rs191",   22, 191, None,    6179.4, "KILLED"),
    ("k_P16_rs223",   16, 223, None,    5247.1, "KILLED"),
]

def run():
    t0 = time.time()
    scores = {}
    # score r8 first WITHOUT a ref, to define it
    for (label, P, rs_k, drop, claim, truth) in ANCHORS:
        try:
            sch = ev.build_dense2x_candidate(P, rs_k, drop_freqs_hz=drop, name=label)
            s = sc.score_candidate(sch, channels=FAITHFUL, also_simB=True,
                                   n_seeds=4, payload_bits=6000, ref_net=0.0)
            s["claim"] = claim; s["truth"] = truth
            scores[label] = s
            print(f"[done] {label}: gross={s['gross_bps']:.0f} worst_model_net="
                  f"{s['worst_model_net_bps']:.0f} best={s['best_model_net_bps']:.0f}", flush=True)
        except Exception as e:
            print(f"[FAIL] {label}: {e}", flush=True); traceback.print_exc()
    # r8 reference
    if "r8_P22_rs179" in scores:
        sc.save_ref(scores["r8_P22_rs179"])
        ref = scores["r8_P22_rs179"]["worst_model_net_bps"]
    else:
        ref = None
    print(f"\n[REFERENCE] r8 worst-capture model_net = {ref}", flush=True)

    print("\n===== ANCHOR SEPARATION (does achievable >= claim?) =====", flush=True)
    print(f"{'anchor':20s} {'truth':7s} {'claim':7s} {'achiev_worst':12s} "
          f"{'achiev_best':11s} {'backed?':8s} {'beats_r8?':9s}", flush=True)
    ok = True
    for label, *_ in [(a[0],) for a in ANCHORS]:
        s = scores.get(label)
        if not s:
            print(f"{label:20s}  MISSING"); ok=False; continue
        backed = s["worst_model_net_bps"] >= s["claim"]
        beats = (ref is not None) and s["worst_model_net_bps"] > ref
        exp_backed = (s["truth"] == "PROVEN")
        flag = "" if backed == exp_backed else "  <-- MISCALIBRATED!"
        if backed != exp_backed: ok = False
        print(f"{label:20s} {s['truth']:7s} {s['claim']:7.0f} "
              f"{s['worst_model_net_bps']:12.0f} {s['best_model_net_bps']:11.0f} "
              f"{str(backed):8s} {str(beats):9s}{flag}", flush=True)
        # per-capture bers
        for ch, d in s["per_channel"].items():
            print(f"     {ch:16s} ber={d['ber']:.4f} model_net={d['model_net']:.0f} "
                  f"margin={d['pooled_min_margin_deg']}", flush=True)

    print(f"\n[CALIBRATION {'PASS' if ok else 'FAIL'}] "
          f"PROVEN backed & KILLED unbacked: {ok}   ({time.time()-t0:.0f}s)", flush=True)
    json.dump({k: {kk: vv for kk, vv in v.items() if kk != '_raw_eval'}
               for k, v in scores.items()},
              open(HERE.parent / "results" / "anchor_confirm.json", "w"), indent=1)

if __name__ == "__main__":
    run()
