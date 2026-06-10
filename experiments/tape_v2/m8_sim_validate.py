"""m8_sim_validate.py -- validate master8.wav through the CALIBRATED faithful sim.

Runs the FULL master8.wav through sim_v2.channel_v2(profile='tape7', aac=True)
for seeds {0,1}, then decodes the result with m8_decode (every section via its
proper path; WS-M32 sections also via the H6 combo path). Writes a per-rung /
per-seed honest summary to results/m8_sim_validate_summary.json.

EXPECTATION (pre-stated; do NOT fudge):
  rungs 1-4, 6, 7 byte-exact on >=1 seed (rungs 2-3 may need the combo path);
  rungs 5, 8 byte-exact on >=1 seed; rung 9 (m16k3 lottery) may fail. Reported
  honestly per rung/seed -- both the plain RS decode and (for M32) the combo.

Usage:
    python3 experiments/tape_v2/m8_sim_validate.py [--seeds 0 1]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import time

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sim_v2  # noqa: E402
import m8_decode  # noqa: E402

SR = 48_000
RESULTS_DIR = _HERE / "results"
MASTER = str(_HERE / "master8.wav")


def _section_exact(r: dict) -> dict:
    """Per-rung outcome: plain orig-exact, plain packed-exact, and (if combo)
    the combo packed-exact. byte_exact at orig level is the headline."""
    out = {
        "packed_exact": bool(r["byte_exact"]),
        "orig_exact": bool(r.get("orig_byte_exact")),
        "cw_failed": r["rs_codewords_failed"],
        "n_codewords": r["n_codewords"],
        "net_bps": r.get("projected_net_bps"),
        "effective_bps": r.get("effective_bps"),
        "unpack_ok": r.get("unpack_ok"),
        "crc_check": r.get("crc_check"),
    }
    if r.get("combo"):
        c = r.get("combo_decode", {})
        out["combo_packed_exact"] = bool(c.get("byte_exact")) if "error" not in c else None
        out["combo_cw_failed"] = c.get("rs_codewords_failed")
        out["combo_miscorrected"] = c.get("miscorrected_cw")
    return out


def run(seeds: list[int]) -> dict:
    audio, sr = sf.read(MASTER, dtype="float32", always_2d=False)
    assert sr == SR, sr
    audio = audio.astype(np.float64)

    by_seed: dict[int, dict] = {}
    for seed in seeds:
        t0 = time.time()
        print(f"\n=== sim_v2 channel_v2(tape7, aac=True) seed={seed} ===", flush=True)
        y = sim_v2.channel_v2(audio, profile="tape7", aac=True, seed_offset=int(seed))
        pk = float(np.max(np.abs(y))) + 1e-12
        y = (y / pk * 0.95).astype(np.float32)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp = tf.name
        sf.write(tmp, y, SR, subtype="FLOAT")
        print(f"  channel pass {time.time() - t0:.0f}s; decoding...", flush=True)
        out = m8_decode.decode(tmp, out_tag=f"sim_tape7_seed{seed}", verbose=True)
        pathlib.Path(tmp).unlink(missing_ok=True)
        by_seed[seed] = {r["name"]: _section_exact(r) for r in out["payloads"]}
    return by_seed


def summarize(by_seed: dict) -> dict:
    names = list(next(iter(by_seed.values())).keys())
    per_rung = {}
    for name in names:
        seeds_orig = {s: by_seed[s][name]["orig_exact"] for s in by_seed}
        seeds_combo = {s: by_seed[s][name].get("combo_packed_exact") for s in by_seed}
        # a rung "passes" if orig-exact on >=1 seed by ANY available path
        any_pass = any(seeds_orig.values())
        per_rung[name] = {
            "orig_exact_per_seed": seeds_orig,
            "combo_packed_exact_per_seed": seeds_combo,
            "net_bps": next(iter(by_seed.values()))[name]["net_bps"],
            "effective_bps": next(iter(by_seed.values()))[name]["effective_bps"],
            "n_seeds_orig_exact": sum(bool(v) for v in seeds_orig.values()),
            "pass_ge1_seed": any_pass,
        }
    return per_rung


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1])
    args = ap.parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    by_seed = run(args.seeds)
    per_rung = summarize(by_seed)

    # pre-stated expectation matrix (which rungs SHOULD pass on >=1 seed)
    expect_pass = {
        "m8_ctrl_m16k1_rs191": True,
        "m8_m32k2_rs127": True,
        "m8_m32k2_rs159": True,
        "m8_m16k2_rs159": True,
        "m8_m16k2_rs191": True,
        "m8_dq_p10n1024_rs159": True,
        "m8_dq_p10n1024_rs223": True,
        "m8_dq_p10n512_rs127": True,
        "m8_m16k3_rs159": False,  # lottery: may fail
    }
    honest = {}
    for name, exp in expect_pass.items():
        got = per_rung[name]["pass_ge1_seed"]
        honest[name] = {"expected_pass": exp, "got_pass": got,
                        "met": (got or not exp)}

    summary = {
        "tape": "master8",
        "channel": "sim_v2.channel_v2(profile='tape7', aac=True)",
        "seeds": args.seeds,
        "per_rung": per_rung,
        "expectation_check": honest,
        "n_rungs_passing": sum(v["pass_ge1_seed"] for v in per_rung.values()),
        "n_rungs": len(per_rung),
    }
    out_path = RESULTS_DIR / "m8_sim_validate_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=float))

    print("\n==== m8 sim-validate summary (orig-exact on >=1 seed) ====")
    for name, pr in per_rung.items():
        seeds_str = " ".join(f"s{s}:{'Y' if v else 'n'}"
                             for s, v in pr["orig_exact_per_seed"].items())
        combo_str = ""
        cps = pr["combo_packed_exact_per_seed"]
        if any(v is not None for v in cps.values()):
            combo_str = "  combo[" + " ".join(
                f"s{s}:{'Y' if v else ('n' if v is not None else '-')}"
                for s, v in cps.items()) + "]"
        exp = expect_pass[name]
        flag = "OK" if (pr["pass_ge1_seed"] or not exp) else "MISS"
        print(f"  {name:<22} net={pr['net_bps'] or 0:6.0f} eff={pr['effective_bps'] or 0:6.0f} "
              f"{seeds_str}{combo_str}  [{flag}]")
    print(f"\n  passing >=1 seed: {summary['n_rungs_passing']}/{summary['n_rungs']}")
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
