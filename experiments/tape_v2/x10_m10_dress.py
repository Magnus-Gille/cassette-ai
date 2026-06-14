"""x10_m10_dress.py -- master10 dress rehearsal (NOT a gate; m9 pattern).

Pushes the FINAL master10.wav through the pre-registered faithful channel
`sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)` end-to-end
(whole tape, one global chirp pair, exactly as a real capture arrives), seeds
0 and 1, then decodes with the composed m10_decode and rolls up per-rung
outcomes.

HONESTY CONTEXT (pre-registered): the faithful sim runs 5-8x PESSIMISTIC vs
real captures; its diffuse-reverb axis falsely rejected the standing 2572
record (m9: sim failed m8_dense375 on 37/49 seed-cells, real tape landed
0/49) and fully REJECTS all dense2x rungs. N256-family rungs are EXPECTED to
look bad here. Report, don't panic; sim SHIP remains meaningful, sim REJECT
on timing/N256/density axes is a prediction-to-test.

Chunked (<8 min per invocation):
    python3 x10_m10_dress.py gen --seed 0        # build captures/m10_dress_s0.wav
    python3 m10_decode.py captures/m10_dress_s0.wav --out-tag dress_s0 --sections ...
    python3 x10_m10_dress.py rollup              # merge per-seed results

Output: results/x10_m10_dress_rehearsal.json + captures/m10_dress_s{0,1}.wav
(gitignored).
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

import sim_v2  # noqa: E402

SR = 48000
WAV = _HERE / "master10.wav"
RESULTS = _HERE / "results"
CAP_DIR = _HERE / "captures"

PROFILE = "tape7"
AAC = False
DIFFUSE_GAIN = 0.58          # m9 dress convention (faithful nominal)
SEEDS = (0, 1)


def gen(seed: int) -> str:
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    x, sr = sf.read(str(WAV), dtype="float64", always_2d=False)
    assert sr == SR, sr
    np.random.seed(seed)
    y = sim_v2.channel_v2(x, profile=PROFILE, aac=AAC, seed_offset=seed,
                          sim_overrides={"diffuse_gain": DIFFUSE_GAIN})
    cap = CAP_DIR / f"m10_dress_s{seed}.wav"
    sf.write(str(cap), y.astype(np.float32), SR, subtype="FLOAT")
    print(f"[dress-gen] seed {seed}: master10.wav ({len(x)/SR:.1f}s) -> {cap}")
    return str(cap)


def rollup() -> dict:
    per_seed = {}
    for seed in SEEDS:
        p = RESULTS / f"x10_m10_results_dress_s{seed}.json"
        res = json.loads(p.read_text())
        rows = []
        for r in res["payloads"]:
            rows.append({
                "name": r["name"], "phy": r.get("phy"), "tier": r.get("tier"),
                "net_bps": r.get("section_net_bps"),
                "x_record": r.get("x_record"),
                "forensic_only": r.get("forensic_only"),
                "rs": f"({r.get('rs_n')},{r.get('rs_k')})",
                "cw_failed": r.get("rs_codewords_failed"),
                "n_codewords": r.get("n_codewords"),
                "byte_exact": bool(r.get("byte_exact")),
                "orig_exact": bool(r.get("orig_byte_exact")),
                "front_end": r.get("front_end_used"),
                "n_rescued_cw": len(r.get("rescued_cw") or []),
                "miscorrected_cw": r.get("miscorrected_cw", 0),
            })
        per_seed[str(seed)] = {
            "clock_offset_pct": (res["sync"].get("speed_offset") or 0.0) * 100,
            "n_byte_exact": res["n_byte_exact_packed"],
            "n_orig_exact": res["n_orig_exact"],
            "false_accept_bound": res.get("false_accept_bound"),
            "rungs": rows,
        }

    names = [r["name"] for r in per_seed[str(SEEDS[0])]["rungs"]]
    rollup_rows = []
    for nm in names:
        rows = [next(r for r in per_seed[str(s)]["rungs"] if r["name"] == nm)
                for s in SEEDS]
        n_orig = sum(1 for r in rows if r["orig_exact"])
        rollup_rows.append({
            "name": nm, "phy": rows[0]["phy"], "tier": rows[0]["tier"],
            "net_bps": rows[0]["net_bps"], "x_record": rows[0]["x_record"],
            "rs": rows[0]["rs"],
            "orig_exact_seeds": f"{n_orig}/{len(SEEDS)}",
            "cw_failed_per_seed": [r["cw_failed"] for r in rows],
            "rescued_cw_per_seed": [r["n_rescued_cw"] for r in rows],
            "lands_both": n_orig == len(SEEDS),
        })

    out = {
        "tape": "master10",
        "what": "DRESS REHEARSAL (not a gate): full master10.wav through the "
                "faithful channel, seeds 0+1, full composed m10_decode",
        "channel": {"fn": "sim_v2.channel_v2", "profile": PROFILE, "aac": AAC,
                    "diffuse_gain": DIFFUSE_GAIN, "seeds": list(SEEDS)},
        "sim_pessimism_note": "faithful sim is 5-8x pessimistic vs real "
                              "captures; sim REJECT on N256/density axes is a "
                              "prediction-to-test (it falsely rejected the "
                              "standing 2572 record)",
        "per_seed": per_seed,
        "rollup": rollup_rows,
    }
    out_path = RESULTS / "x10_m10_dress_rehearsal.json"
    out_path.write_text(json.dumps(out, indent=2, default=float))

    print("\n[dress] ===== ROLL-UP (orig-exact on BOTH seeds) =====")
    print(f"  {'rung':<28}{'tier':<10}{'net':>6}  {'seeds':>6} {'cw/seed':>12} {'rescued':>9}")
    for r in rollup_rows:
        print(f"  {r['name']:<28}{r['tier'] or '':<10}{r['net_bps'] or 0:6.0f}  "
              f"{r['orig_exact_seeds']:>6} {str(r['cw_failed_per_seed']):>12} "
              f"{str(r['rescued_cw_per_seed']):>9}")
    print(f"\n[dress] wrote {out_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--seed", type=int, required=True)
    sub.add_parser("rollup")
    args = ap.parse_args()
    if args.cmd == "gen":
        gen(args.seed)
    else:
        rollup()
