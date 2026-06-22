"""Screen the three dapsk16-strongmids variants through the trusted filter.

Mandatory clean-channel self-check (BER<1e-3) per variant FIRST, then
score_candidate on replay_tape10 (+ simB_master3 as a known-pessimistic
secondary).  Reports each variant's replay model_net vs the r8 reference (5921).
Writes results/dapsk16-strongmids_screen.json.
"""
from __future__ import annotations
import importlib.util
import json
import pathlib
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")

HERE = pathlib.Path(__file__).resolve().parent
BP = HERE.parent
HARNESS = BP / "harness"
RESULTS = BP / "results"
sys.path.insert(0, str(HARNESS))

# load the candidate module (hyphenated filename -> importlib)
_spec = importlib.util.spec_from_file_location(
    "dapsk16_strongmids", HERE / "dapsk16-strongmids.py")
cand = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cand)

import score as sc   # noqa: E402

FS = 48_000
REF = 5920.588235294118    # r8 worst-capture model_net on replay_tape10


def clean_check(fs) -> float:
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), FS)
    m = min(len(bits), len(rx))
    ber = float(np.mean(bits[:m] != rx[:m])) + (len(bits) - m) / len(bits)
    return ber


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    out = {"candidate": "dapsk16-strongmids", "ref_net_bps": REF, "variants": {}}
    for v in ("a", "b", "c", "d", "e"):
        fs = cand.build(v)
        cb = clean_check(fs)
        print(f"[clean] variant {v} ({fs.name}): gross={fs.gross_bps:.0f} "
              f"clean_ber={cb:.2e}", flush=True)
        assert cb < 1e-3, (f"variant {v} clean-channel BER {cb} >= 1e-3 -- "
                           f"modulate/demodulate not inverse; FIX before screening")
        r = sc.score_candidate(fs, channels=("replay_tape10",), also_simB=True,
                               n_seeds=6, payload_bits=6000, ref_net=REF)
        rep = r["per_channel"]["replay_tape10"]
        simB = r["per_channel"].get("simB_master3", {})
        entry = {
            "name": fs.name,
            "gross_bps": r["gross_bps"],
            "clean_ber": cb,
            "replay_ber": rep["ber"],
            "replay_model_net": rep["model_net"],
            "simB_ber": simB.get("ber"),
            "simB_model_net": simB.get("model_net"),
            "worst_model_net_bps": r["worst_model_net_bps"],
            "beats_5921": bool(r["worst_model_net_bps"] > REF),
            "verdict": r["verdict"],
            "verdict_reason": r["verdict_reason"],
        }
        out["variants"][v] = entry
        print(f"[score] variant {v}: replay_ber={rep['ber']:.4f} "
              f"replay_model_net={rep['model_net']:.0f} "
              f"simB_ber={simB.get('ber')} "
              f"worst_model_net={r['worst_model_net_bps']:.0f} "
              f"beats5921={entry['beats_5921']} verdict={r['verdict']}", flush=True)

    # pick the best variant by replay model_net
    best_v = max(out["variants"], key=lambda v: out["variants"][v]["replay_model_net"])
    out["best_variant"] = best_v
    out["best_replay_model_net"] = out["variants"][best_v]["replay_model_net"]
    out["best_beats_5921"] = out["variants"][best_v]["replay_model_net"] > REF
    out["wall_s"] = round(time.time() - t0, 1)
    (RESULTS / "dapsk16-strongmids_screen.json").write_text(
        json.dumps(out, indent=2, default=float))
    print(f"\n[BEST] variant {best_v} replay_model_net="
          f"{out['best_replay_model_net']:.0f} beats5921={out['best_beats_5921']} "
          f"({out['wall_s']}s)", flush=True)
    print(f"[wrote] {RESULTS / 'dapsk16-strongmids_screen.json'}")


if __name__ == "__main__":
    main()
