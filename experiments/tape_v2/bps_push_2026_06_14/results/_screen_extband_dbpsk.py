"""Screen driver for candidate extband-dbpsk. Writes results/extband-dbpsk_screen.json."""
from __future__ import annotations
import json, pathlib, sys, time, warnings
import numpy as np

warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parent
HARNESS = HERE.parent / "harness"
CANDS = HERE.parent / "candidates"
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(CANDS))

import score  # noqa: E402
from extband_dbpsk import build  # noqa: E402

REF = 5920.588235294118  # r8 reference model_net (results/r8_reference.json)


def main():
    t0 = time.time()
    # clean-channel self-check on each variant first (re-assert here)
    clean = {}
    for ne in (2, 4, 6):
        fs = build(ne)
        rng = np.random.default_rng(0)
        bits = rng.integers(0, 2, 4000, dtype=np.uint8)
        rx = fs.demodulate(np.asarray(fs.modulate(bits), np.float32), 48000)
        m = min(len(bits), len(rx))
        ber = float(np.mean(bits[:m] != rx[:m]))
        clean[ne] = ber
        assert ber < 1e-3, (ne, ber)

    variants = []
    for ne in (2, 4, 6):
        fs = build(ne)
        r = score.score_candidate(fs, channels=("replay_tape10",),
                                  also_simB=True, n_seeds=6, payload_bits=6000)
        pc = r["per_channel"]
        replay = pc["replay_tape10"]
        simB = pc.get("simB_master3", {})
        row = {
            "n_ext": ne,
            "name": r["name"],
            "gross_bps": r["gross_bps"],
            "clean_ber": clean[ne],
            "replay_ber": replay["ber"],
            "replay_model_net": replay["model_net"],
            "simB_ber": simB.get("ber"),
            "simB_model_net": simB.get("model_net"),
            "worst_model_net_bps": r["worst_model_net_bps"],
            "beats_5921": bool(r["worst_model_net_bps"] > REF),
            "verdict": r["verdict"],
            "verdict_reason": r["verdict_reason"],
        }
        variants.append(row)
        print(f"[screen] n_ext={ne} gross={r['gross_bps']:.0f} "
              f"replay_ber={replay['ber']:.4f} model_net={replay['model_net']:.0f} "
              f"simB_ber={simB.get('ber'):.4f} "
              f"worst={r['worst_model_net_bps']:.0f} "
              f"beats5921={row['beats_5921']} {r['verdict']}", flush=True)

    # pick the best variant by replay model_net (the number that matters)
    best = max(variants, key=lambda v: v["worst_model_net_bps"])
    out = {
        "id": "extband-dbpsk",
        "file": str((CANDS / "extband_dbpsk.py").resolve()),
        "ref_model_net": REF,
        "variants": variants,
        "best_variant": best,
        "n_seeds": 6, "payload_bits": 6000,
        "wall_s": round(time.time() - t0, 1),
    }
    outp = HERE / "extband-dbpsk_screen.json"
    outp.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[screen] best n_ext={best['n_ext']} worst_model_net={best['worst_model_net_bps']:.0f} "
          f"(ref {REF:.0f}, +{best['worst_model_net_bps']-REF:.0f})  {best['verdict']}")
    print(f"[screen] wrote {outp}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
