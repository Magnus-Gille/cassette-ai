"""stack_screen.py -- Tasks 2 & 3 of the finalization.

TASK 2 (stacked flagship screen):
  Screen StackedFlagship at (n8 in {3,7}) x (n_ext in {4,6}) on replay_tape10,
  n_seeds=6, payload 6000.  Report gross_bps + replay_ber + model_net per config.
  Compare to the best SINGLE lever (extband n_ext=6 = 6875; dapsk d = 6774) and to
  the apples-to-apples r8 baseline scored in the SAME run/seeds.

TASK 3 (bulk-frame the stack + 8-DPSK + r8):
  Screen the stacked flagship (n8=3,n_ext=4), dapsk16('d'), and r8 at payload_bits
  in [6000, 20000, 40000, 80000] on replay_tape10, n_seeds=8.  Report whether the
  bulk-framing BER-drop COMPOUNDS with the higher-order modulation (does the stack
  ALSO get lower BER at long frames?).

Writes results/stack_screen.json.
"""
from __future__ import annotations
import importlib.util
import json
import math
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
REF_N4 = 5920.588235294118     # r8 worst-capture model_net on replay_tape10 @ n_seeds=4 (the fixed "5921" ref)


def _load(modname, fname):
    spec = importlib.util.spec_from_file_location(modname, CAND / fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_stack = _load("stacked_flagship", "stacked_flagship.py")
_dapsk = _load("dapsk16_strongmids", "dapsk16-strongmids.py")


def clean_ber(fs) -> float:
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    mr = getattr(fs, "_modulate_ref", None)
    if mr is not None:
        mr._nbits = len(bits)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), FS)
    m = min(len(bits), len(rx))
    return float(np.mean(bits[:m] != rx[:m])) + (len(bits) - m) / len(bits)


def screen(fs, *, n_seeds, payload_bits, also_simB=False):
    r = sc.score_candidate(fs, channels=("replay_tape10",), also_simB=also_simB,
                           n_seeds=n_seeds, payload_bits=payload_bits, ref_net=REF_N4)
    rep = r["per_channel"]["replay_tape10"]
    out = {
        "name": r["name"], "gross_bps": r["gross_bps"],
        "replay_ber": rep["ber"], "model_net": rep["model_net"],
        "verdict": r["verdict"],
    }
    if also_simB:
        out["simB_ber"] = r["per_channel"].get("simB_master3", {}).get("ber")
    return out


def main():
    t0 = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = {"channel": "replay_tape10", "ref_n4": REF_N4, "task2": {}, "task3": {}}

    # ----------------------------------------------------------------- TASK 2
    print("\n########## TASK 2: stacked flagship screen (n_seeds=6, pb=6000) ##########",
          flush=True)
    # apples-to-apples r8 + the two single levers at the SAME seeds/pb
    print("-- references @ n_seeds=6 --", flush=True)
    out["task2"]["_references"] = {}
    r8_n6 = screen(ev.build_dense2x_candidate(22, 179, name="r8_ref_n6"),
                   n_seeds=6, payload_bits=6000)
    out["task2"]["_references"]["r8"] = r8_n6
    print(f"  r8         gross={r8_n6['gross_bps']:.0f} ber={r8_n6['replay_ber']:.5f} "
          f"model_net={r8_n6['model_net']:.0f}", flush=True)
    dpd = _dapsk.build("d")
    assert clean_ber(dpd) < 1e-3
    dpd_n6 = screen(dpd, n_seeds=6, payload_bits=6000)
    out["task2"]["_references"]["dapsk_d"] = dpd_n6
    print(f"  dapsk_d    gross={dpd_n6['gross_bps']:.0f} ber={dpd_n6['replay_ber']:.5f} "
          f"model_net={dpd_n6['model_net']:.0f}", flush=True)
    extb = _load("extband_dbpsk", "extband_dbpsk.py")
    e6 = extb.build(6)
    assert clean_ber(e6) < 1e-3
    e6_n6 = screen(e6, n_seeds=6, payload_bits=6000)
    out["task2"]["_references"]["extband_6"] = e6_n6
    print(f"  extband_6  gross={e6_n6['gross_bps']:.0f} ber={e6_n6['replay_ber']:.5f} "
          f"model_net={e6_n6['model_net']:.0f}", flush=True)

    best_single = max(dpd_n6["model_net"], e6_n6["model_net"])
    out["task2"]["best_single_lever_model_net"] = best_single

    print("-- stack configs --", flush=True)
    out["task2"]["stacks"] = {}
    for (n8, ne) in [(3, 4), (3, 6), (7, 4), (7, 6)]:
        fs = _stack.build(n8, ne)
        cb = clean_ber(fs)
        assert cb < 1e-3, f"stack n8={n8} ext={ne} clean BER {cb}"
        s = screen(fs, n_seeds=6, payload_bits=6000, also_simB=True)
        s["clean_ber"] = cb
        s["beats_best_single"] = bool(s["model_net"] > best_single)
        s["delta_vs_r8_n6"] = s["model_net"] - r8_n6["model_net"]
        key = f"n8{n8}_ext{ne}"
        out["task2"]["stacks"][key] = s
        print(f"  {key:10s} gross={s['gross_bps']:7.1f} ber={s['replay_ber']:.5f} "
              f"model_net={s['model_net']:.0f}  simB={s['simB_ber']:.4f}  "
              f"beats_best_single={s['beats_best_single']}  d_vs_r8={s['delta_vs_r8_n6']:+.0f}",
              flush=True)

    # ----------------------------------------------------------------- TASK 3
    print("\n########## TASK 3: bulk-frame sweep (n_seeds=8) ##########", flush=True)
    payloads = [6000, 20000, 40000, 80000]
    out["task3"]["payloads"] = payloads
    out["task3"]["schemes"] = {}

    def bulk_sweep(label, builder, bps_per_sym):
        rows = []
        base_ber = None
        for pb in payloads:
            fs = builder()
            s = screen(fs, n_seeds=8, payload_bits=pb)
            nsym = int(math.ceil(pb / bps_per_sym))
            sec = nsym / 187.5
            if base_ber is None:
                base_ber = s["replay_ber"]
            row = {"payload_bits": pb, "frame_symbols": nsym, "frame_seconds": round(sec, 2),
                   "replay_ber": s["replay_ber"], "model_net": s["model_net"],
                   "ber_ratio_vs_short": (s["replay_ber"] / base_ber) if base_ber else None,
                   "gross_bps": s["gross_bps"]}
            rows.append(row)
            print(f"  [{label}] pb={pb:>6} {nsym:>5}sym {sec:6.2f}s  ber={s['replay_ber']:.5f} "
                  f"model_net={s['model_net']:.0f}  ratio={row['ber_ratio_vs_short']:.3f}",
                  flush=True)
        return rows

    print("-- r8 (8250 gross, 44 bits/sym) --", flush=True)
    out["task3"]["schemes"]["r8"] = bulk_sweep(
        "r8", lambda: ev.build_dense2x_candidate(22, 179), 44)

    print("-- dapsk16 d (8812.5 gross, 51 bits/sym: 3*8dpsk + 19*dqpsk) --", flush=True)
    out["task3"]["schemes"]["dapsk_d"] = bulk_sweep(
        "dapsk_d", lambda: _dapsk.build("d"), 51)

    print("-- stacked flagship n8=3,ext=4 (9562.5 gross, 51 bits/sym) --", flush=True)
    out["task3"]["schemes"]["stack_n8_3_ext4"] = bulk_sweep(
        "stack34", lambda: _stack.build(3, 4),
        _stack.build(3, 4)._scheme.bits_per_sym)

    out["wall_s"] = round(time.time() - t0, 1)
    (RESULTS / "stack_screen.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[wrote] {RESULTS / 'stack_screen.json'}  ({out['wall_s']}s)", flush=True)


if __name__ == "__main__":
    main()
