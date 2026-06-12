"""x12_m11_dress.py -- master11 dress rehearsal (NOT a gate; m9/m10 pattern).

Pushes the FINAL master11.wav end-to-end through the pre-registered faithful
channel, then decodes with the shipping x12_master11_decode receiver and
rolls up per-rung outcomes.  Cells (the task-frozen plan):

  s0       sim_v2.channel_v2(profile='tape7', aac=False, dg=0.58), seed 0
  s1       same, seed 1
  aac_s0   same + REAL AAC round-trip, seed 0
  clk_s0   same as s0 + constant +0.17% clock offset applied by polyphase
           resample of the whole capture (x11_d2x_erasure._apply_clock,
           frozen import; +0.17% is the mid value of the frozen x11 stock
           clk grid {0, 0.10, 0.17, 0.25}%)

HONESTY CONTEXT (pre-registered, unchanged from m9/m10/x11): the faithful
sim runs 5-8x PESSIMISTIC vs real captures; its diffuse-reverb axis falsely
rejected the standing 2572 record AND the entire d2x family -- which then
landed on real tape (tape10: r5/r6/r7 clean, r8 record via rescue).  N256 /
d2x / dense rungs are EXPECTED to wipe out here.  Report, don't panic: sim
PASS is meaningful; sim REJECT on the timing/density axes is a
prediction-to-test (falsified 3x already).

Dress decodes run --no-x11-rescue (stage A only, the m9/m10 dress
convention): the gated rescue's evidence lives in its own gate
(x11_d2x_gate_report) + the tape10 regression rerun; arming it on sim-dead
sections adds minutes, not information.

Chunked (<8 min per invocation):
    python3 x12_m11_dress.py gen --cell s0          # build captures/m11_dress_<cell>.wav
    python3 x12_master11_decode.py captures/m11_dress_s0.wav --out-tag dress_s0 --no-x11-rescue
    python3 x12_m11_dress.py rollup                 # merge -> results/x12_m11_dress.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import warnings

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sim_v2                                   # noqa: E402
from x11_d2x_erasure import _apply_clock        # noqa: E402 (frozen, read-only)

SR = 48000
WAV = _HERE / "master11.wav"
RESULTS = _HERE / "results"
CAP_DIR = _HERE / "captures"

PROFILE = "tape7"
DIFFUSE_GAIN = 0.58            # m9 dress convention (faithful nominal)
CELLS = {
    "s0": {"seed": 0, "aac": False, "clk_pct": 0.0},
    "s1": {"seed": 1, "aac": False, "clk_pct": 0.0},
    "aac_s0": {"seed": 0, "aac": True, "clk_pct": 0.0},
    "clk_s0": {"seed": 0, "aac": False, "clk_pct": 0.17},
}


def gen(cell: str) -> str:
    c = CELLS[cell]
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    x, sr = sf.read(str(WAV), dtype="float64", always_2d=False)
    assert sr == SR, sr
    if c["clk_pct"]:
        x, ratio = _apply_clock(x, c["clk_pct"])
    np.random.seed(c["seed"])
    y = sim_v2.channel_v2(x, profile=PROFILE, aac=c["aac"],
                          seed_offset=c["seed"],
                          sim_overrides={"diffuse_gain": DIFFUSE_GAIN})
    cap = CAP_DIR / f"m11_dress_{cell}.wav"
    sf.write(str(cap), y.astype(np.float32), SR, subtype="FLOAT")
    print(f"[dress-gen] {cell}: master11.wav ({len(x)/SR:.1f}s) -> {cap.name} "
          f"(aac={c['aac']}, clk={c['clk_pct']:+.2f}%, seed={c['seed']})")
    return str(cap)


def rollup() -> dict:
    per_cell = {}
    for cell in CELLS:
        p = RESULTS / f"x12_m11_results_dress_{cell}.json"
        if not p.exists():
            per_cell[cell] = {"missing": True}
            continue
        res = json.loads(p.read_text())
        rows = []
        for r in res["payloads"]:
            rows.append({
                "name": r["name"], "kind": r.get("kind"), "tier": r.get("tier"),
                "net_bps": r.get("projected_net_bps"),
                "cw_failed": r.get("rs_codewords_failed"),
                "n_codewords": r.get("n_codewords"),
                "byte_exact": bool(r.get("byte_exact")),
                "orig_exact": bool(r.get("orig_byte_exact")),
                "front_end": r.get("front_end_used"),
                "stage": r.get("decoder_stage"),
                "miscorrected_cw": r.get("miscorrected_cw", 0),
            })
        per_cell[cell] = {
            "cell_def": CELLS[cell],
            "clock_meas": res["sync"].get("speed"),
            "n_orig_exact": res["n_orig_exact"],
            "n_payloads": res["n_payloads"],
            "tape_pass_valid": res.get("tape_pass_valid"),
            "fa_bound": res.get("false_accept_bound"),
            "rungs": rows,
        }

    names = [s["name"] for s in json.loads(
        (_HERE / "master11_manifest.json").read_text())["ws_payloads"]]
    rollup_rows = []
    for nm in names:
        per = {}
        for cell, pc in per_cell.items():
            if pc.get("missing"):
                per[cell] = None
                continue
            row = next((r for r in pc["rungs"] if r["name"] == nm), None)
            per[cell] = (f"{'ORIG' if row['orig_exact'] else 'fail'}"
                         f"({row['cw_failed']}/{row['n_codewords']})"
                         if row else None)
        rollup_rows.append({"name": nm, "per_cell": per})

    out = {
        "tape": "master11",
        "what": "DRESS REHEARSAL (not a gate): full master11.wav through the "
                "faithful channel; cells s0/s1/aac_s0/clk_s0; shipping "
                "decoder stage A (--no-x11-rescue, m9/m10 dress convention)",
        "channel": {"fn": "sim_v2.channel_v2", "profile": PROFILE,
                    "diffuse_gain": DIFFUSE_GAIN, "cells": CELLS},
        "sim_pessimism_note": "faithful sim is 5-8x pessimistic vs real "
                              "captures; sim REJECT on N256/d2x/density axes "
                              "is a prediction-to-test (falsified 3x: "
                              "2338/2572, 2896, the d2x family on tape10)",
        "per_cell": per_cell,
        "rollup": rollup_rows,
    }
    out_path = RESULTS / "x12_m11_dress.json"
    out_path.write_text(json.dumps(out, indent=2, default=float))

    print("\n[dress] ===== ROLL-UP (per cell: ORIG/fail + failed cw) =====")
    cells = list(CELLS)
    print(f"  {'rung':<26}" + "".join(f"{c:>16}" for c in cells))
    for r in rollup_rows:
        print(f"  {r['name']:<26}" + "".join(
            f"{str(r['per_cell'].get(c)):>16}" for c in cells))
    print(f"\n[dress] wrote {out_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--cell", required=True, choices=list(CELLS))
    sub.add_parser("rollup")
    args = ap.parse_args()
    if args.cmd == "gen":
        gen(args.cell)
    else:
        rollup()
