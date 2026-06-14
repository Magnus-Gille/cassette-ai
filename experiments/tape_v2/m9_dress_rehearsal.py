"""m9_dress_rehearsal.py -- merged-tape sim spot-check (Ship phase, task 2).

NOT a gate. Pushes the FINAL master9.wav through the plan's pre-registered
FAITHFUL channel `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`
end-to-end (the whole tape, one global chirp pair, exactly as a real capture
arrives), seeds 0 and 1, then runs the full m9_decode and reports per-rung
outcomes. This is the dress rehearsal: it tells us what the merged tape does
through the faithful sim, with the documented R6 pessimism caveats noted in the
ship report (the sim's N256 reverb-ISI scaling is the one axis with no real
anchor; spacing<750 Hz / freqdiff are sim-blind by rule).

Seeds set + logged. Output: results/m9_dress_rehearsal.json + temp WAVs (gitignored).

Run:
    python3 experiments/tape_v2/m9_dress_rehearsal.py
"""
from __future__ import annotations

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
import m9_decode  # noqa: E402

SR = 48000
WAV = _HERE / "master9.wav"
RESULTS = _HERE / "results"
CAP_DIR = _HERE / "captures"

PROFILE = "tape7"
AAC = False
DIFFUSE_GAIN = 0.58          # plan §4.0 faithful nominal (R6 §3 lossless branch)
SEEDS = [0, 1]


def main() -> dict:
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    x, sr = sf.read(str(WAV), dtype="float64", always_2d=False)
    assert sr == SR, sr
    print(f"[dress] master9.wav {len(x)/SR:.1f}s through "
          f"channel_v2(profile={PROFILE!r}, aac={AAC}, diffuse_gain={DIFFUSE_GAIN}) "
          f"seeds {SEEDS}")

    per_seed = {}
    for seed in SEEDS:
        np.random.seed(seed)
        y = sim_v2.channel_v2(x, profile=PROFILE, aac=AAC, seed_offset=seed,
                              sim_overrides={"diffuse_gain": DIFFUSE_GAIN})
        cap = CAP_DIR / f"m9_dress_s{seed}.wav"
        sf.write(str(cap), y.astype(np.float32), SR, subtype="FLOAT")
        print(f"\n[dress] === seed {seed} -> {cap.name} ===")
        res = m9_decode.decode(str(cap), out_tag=f"dress_s{seed}", verbose=True)
        rung_rows = []
        for r in res["payloads"]:
            rung_rows.append({
                "name": r["name"],
                "phy": r.get("phy"),
                "net_bps": r.get("projected_net_bps"),
                "x_record": r.get("x_record"),
                "status": r.get("status"),
                "rs": f"({r.get('rs_n')},{r.get('rs_k')})",
                "cw_failed": r.get("rs_codewords_failed"),
                "n_codewords": r.get("n_codewords"),
                "byte_exact": bool(r.get("byte_exact")),
                "orig_exact": bool(r.get("orig_byte_exact")),
                "front_end": r.get("front_end_used"),
                "miscorrected_cw": r.get("miscorrected_cw", 0),
            })
        per_seed[str(seed)] = {
            "clock_offset_pct": res["sync"].get("speed_offset", 0.0) * 100,
            "n_byte_exact": res["n_byte_exact_packed"],
            "n_orig_exact": res["n_orig_exact"],
            "rungs": rung_rows,
        }

    # cross-seed roll-up: a rung "lands" in the dress rehearsal if orig-exact on
    # BOTH seeds (the most-likely-real signal; sim pessimism noted in the report).
    names = [r["name"] for r in per_seed[str(SEEDS[0])]["rungs"]]
    rollup = []
    for nm in names:
        rows = [next(r for r in per_seed[str(s)]["rungs"] if r["name"] == nm)
                for s in SEEDS]
        n_orig = sum(1 for r in rows if r["orig_exact"])
        rollup.append({
            "name": nm, "phy": rows[0]["phy"], "net_bps": rows[0]["net_bps"],
            "x_record": rows[0]["x_record"], "status": rows[0]["status"],
            "rs": rows[0]["rs"], "orig_exact_seeds": f"{n_orig}/{len(SEEDS)}",
            "cw_failed_per_seed": [r["cw_failed"] for r in rows],
            "lands_both": n_orig == len(SEEDS),
        })

    out = {
        "tape": "master9",
        "what": "DRESS REHEARSAL (not a gate): full merged master9.wav through the "
                "plan's faithful channel, seeds 0+1, full m9_decode",
        "channel": {"fn": "sim_v2.channel_v2", "profile": PROFILE, "aac": AAC,
                    "diffuse_gain": DIFFUSE_GAIN, "seeds": SEEDS},
        "per_seed": per_seed,
        "rollup": rollup,
    }
    out_path = RESULTS / "m9_dress_rehearsal.json"
    out_path.write_text(json.dumps(out, indent=2, default=float))

    print("\n[dress] ===== ROLL-UP (orig-exact on BOTH seeds) =====")
    print(f"  {'rung':<24}{'phy':<24}{'net':>6}{'x':>6}  {'seeds':>6} {'cw/seed':>14}  status")
    for r in rollup:
        print(f"  {r['name']:<24}{r['phy']:<24}{(r['net_bps'] or 0):6.0f}"
              f"{(r['x_record'] or 0):6.2f}  {r['orig_exact_seeds']:>6} "
              f"{str(r['cw_failed_per_seed']):>14}  {r['status']}")
    landed = [r for r in rollup if r["lands_both"]]
    if landed:
        best = max(landed, key=lambda r: r["net_bps"] or 0)
        print(f"\n[dress] best rung landing BOTH seeds: {best['name']} -> "
              f"{best['net_bps']:.0f} bps (x{best['x_record']})")
    else:
        print("\n[dress] no rung landed both seeds")
    print(f"[dress] wrote {out_path}")
    return out


if __name__ == "__main__":
    main()
