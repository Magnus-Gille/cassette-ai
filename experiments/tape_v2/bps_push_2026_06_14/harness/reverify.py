"""reverify.py -- INDEPENDENT re-verification of the surviving gauntlet candidates.

Task 1 of the finalization: re-run build() + the mandatory clean-channel self-check
(BER<1e-3) + score.score_candidate(..., channels=("replay_tape10",), n_seeds=6) for:
  * r8 baseline (the reference; via evaluate.build_dense2x_candidate(22,179))
  * dapsk16-strongmids build('d')   (8-DPSK on 3 CSI-cleanest carriers)
  * extband_dbpsk build(4) and build(6)

Confirms the model_nets reproduce the gauntlet's claims (within noise). Flags any
that DON'T reproduce or DON'T clean-invert.

Writes results/reverify.json.
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

HARNESS = pathlib.Path(__file__).resolve().parent
BP = HARNESS.parent
CAND = BP / "candidates"
RESULTS = BP / "results"
sys.path.insert(0, str(HARNESS))

import evaluate as ev          # noqa: E402
import score as sc             # noqa: E402

FS = 48_000
REF = 5920.588235294118        # r8 worst-capture model_net on replay_tape10 (== the 5921 ref)


def _load(modname, fname):
    spec = importlib.util.spec_from_file_location(modname, CAND / fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def clean_check(fs) -> float:
    """Mandatory RED/GREEN clean-channel self-check. Handles both the bare-scheme
    FuncScheme (dapsk) and the closure-based adapter (extband / r8)."""
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    # adapters that recover nd from a closure need _nbits set before demod
    mr = getattr(fs, "_modulate_ref", None)
    if mr is not None:
        mr._nbits = len(bits)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), FS)
    m = min(len(bits), len(rx))
    ber = float(np.mean(bits[:m] != rx[:m])) + (len(bits) - m) / len(bits)
    return ber


def screen(fs, *, n_seeds=6, payload_bits=6000):
    r = sc.score_candidate(fs, channels=("replay_tape10",), also_simB=True,
                           n_seeds=n_seeds, payload_bits=payload_bits, ref_net=REF)
    rep = r["per_channel"]["replay_tape10"]
    simB = r["per_channel"].get("simB_master3", {})
    return {
        "name": r["name"],
        "gross_bps": r["gross_bps"],
        "replay_ber": rep["ber"],
        "replay_model_net": rep["model_net"],
        "simB_ber": simB.get("ber"),
        "worst_model_net_bps": r["worst_model_net_bps"],
        "verdict": r["verdict"],
        "verdict_reason": r["verdict_reason"],
    }


def main():
    t0 = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = {"ref_net_bps": REF, "n_seeds": 6, "payload_bits": 6000,
           "channel": "replay_tape10", "candidates": {}}

    # claimed model_nets from the gauntlet, for the reproduce check
    claims = {
        "r8_baseline": 5920.6,
        "dapsk16_d": 6774.0,
        "extband_4": 6600.0,
        "extband_6": 6875.0,
    }

    dapsk = _load("dapsk16_strongmids", "dapsk16-strongmids.py")
    extb = _load("extband_dbpsk", "extband_dbpsk.py")

    specs = [
        ("r8_baseline", lambda: ev.build_dense2x_candidate(22, 179, name="r8_reverify")),
        ("dapsk16_d", lambda: dapsk.build("d")),
        ("extband_4", lambda: extb.build(4)),
        ("extband_6", lambda: extb.build(6)),
    ]

    for key, builder in specs:
        print(f"\n=== {key} ===", flush=True)
        fs = builder()
        cb = clean_check(fs)
        clean_ok = cb < 1e-3
        print(f"  clean_ber = {cb:.2e}  ({'PASS' if clean_ok else 'FAIL — DO NOT SHIP'})",
              flush=True)
        s = screen(fs)
        s["clean_ber"] = cb
        s["clean_ok"] = clean_ok
        claimed = claims[key]
        got = s["replay_model_net"]
        # reproduce within noise: model_net is quantized (gross*k_max/255), so allow
        # +-3% OR within one k_max step.
        rel = abs(got - claimed) / max(1.0, claimed)
        s["claimed_model_net"] = claimed
        s["reproduce_rel_err"] = rel
        s["reproduces"] = bool(rel <= 0.03)
        out["candidates"][key] = s
        print(f"  gross={s['gross_bps']:.0f}  replay_ber={s['replay_ber']:.5f}  "
              f"model_net={got:.0f}  (claimed {claimed:.0f}, rel_err {rel*100:.1f}%)  "
              f"verdict={s['verdict']}  reproduces={s['reproduces']}", flush=True)

    out["wall_s"] = round(time.time() - t0, 1)
    (RESULTS / "reverify.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[wrote] {RESULTS / 'reverify.json'}  ({out['wall_s']}s)", flush=True)


if __name__ == "__main__":
    main()
