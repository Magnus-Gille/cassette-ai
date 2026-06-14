"""x10_b_aggr_05_dense2x_dress.py -- dress rehearsal: the FULL master10-dense2x
wav through the faithful channel (m9_dress_rehearsal pattern:
channel_v2(profile='tape7', aac=True, diffuse_gain=0.58)), then the complete
x10 decoder exactly as it will run on the real capture.

Remember the calibration: this sim is 5-8x PESSIMISTIC vs real captures on the
timing/short-symbol axis (it rejected all m9 N256 rungs; real tape landed
m4b/m8).  The dress rehearsal validates the DECODE CHAIN end-to-end (sync,
manifest, front-end sweep, CRC ledger), not the rate claim.

Usage:  python3 x10_b_aggr_05_dense2x_dress.py [--seeds 0,1]
Writes: results/x10_b_aggr_05_dense2x_dress.json + per-seed decoder results.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sim_v2                                     # noqa: E402
import x10_b_aggr_05_dense2x_decode as x10dec     # noqa: E402

FS = 48_000
MASTER = _HERE / "x10_master_dense2x.wav"
OUT_JSON = _HERE / "results" / "x10_b_aggr_05_dense2x_dress.json"
DIFFUSE_GAIN = 0.58
PROFILE = "tape7"
AAC = True


def main(seeds):
    x, sr = sf.read(str(MASTER), dtype="float64", always_2d=False)
    assert sr == FS
    rows = []
    for seed in seeds:
        t0 = time.time()
        y = sim_v2.channel_v2(x, profile=PROFILE, aac=AAC, seed_offset=seed,
                              sim_overrides={"diffuse_gain": DIFFUSE_GAIN})
        cap = _HERE / f"x10_dense2x_dress_s{seed}.wav"
        sf.write(str(cap), np.asarray(y, np.float32), FS, subtype="FLOAT")
        res = x10dec.decode(str(cap), out_tag=f"dress_s{seed}", verbose=True)
        rows.append({
            "seed": seed,
            "anchor_reproved": res["anchor_reproved"],
            "n_orig_exact": res["n_orig_exact"],
            "per_rung": [{k: r.get(k) for k in
                          ("name", "rs_codewords_failed", "n_codewords",
                           "byte_errors", "byte_exact", "orig_byte_exact",
                           "front_end_used")} for r in res["payloads"]],
            "wall_s": round(time.time() - t0, 1)})
        print(f"[dress seed{seed}] anchor={res['anchor_reproved']} "
              f"orig-exact {res['n_orig_exact']}/4 ({rows[-1]['wall_s']}s)",
              flush=True)
    out = {"channel": {"fn": "sim_v2.channel_v2", "profile": PROFILE,
                       "aac": AAC, "diffuse_gain": DIFFUSE_GAIN},
           "pessimism_note": "sim 5-8x pessimistic on timing/N256 axis "
                             "(pre-registered prediction-to-test)",
           "seeds": list(seeds), "rows": rows}
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    print(f"[dress] -> {OUT_JSON.name}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1")
    args = ap.parse_args()
    main([int(s) for s in args.seeds.split(",")])
