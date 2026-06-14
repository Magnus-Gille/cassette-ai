"""validate_analyzer.py — Task 2 validation gate.

Push master2.wav through the harsh simulated real deck (cs.full_chain) and run
analyze_master2.analyze on the result. Confirms:
  - chirp sync found, global clock recovered within ~1% of the applied speed,
  - robust ladder rungs (mfsk32, c1_gray_m16, c2_m32_k2, c4_bpsk) decode at high
    passrate while aggressive rungs degrade.

Two simulated channels:
  worn  + speed_offset=-0.12  (emulates the ~0.88x harsh acoustic deck)
  normal+ speed_offset= 0.0   (sanity: the clean 42 dB-ish sim regime)
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import soundfile as sf

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    sys.path.insert(0, str(ROOT / _p))
TAPE_V2 = ROOT / "experiments" / "tape_v2"
sys.path.insert(0, str(TAPE_V2))

import capture_scenarios as cs       # noqa: E402
import analyze_master2 as am         # noqa: E402

WAV = TAPE_V2 / "master2.wav"
ROBUST = ["mfsk32", "c1_gray_m16", "c2_m32_k2", "c4_bpsk"]
# When True, reuse on-disk _sim_<tag>.wav fixtures instead of re-running the
# (slow) full_chain. Set via --reuse on the CLI.
REUSE = False


def run_channel(tape_preset: str, speed_offset: float, seed: int, tag: str):
    tmp = TAPE_V2 / f"_sim_{tag}.wav"
    if REUSE and tmp.exists():
        print(f"[{tag}] reusing existing fixture {tmp}")
    else:
        audio, sr = sf.read(str(WAV), dtype="float32", always_2d=False)
        print(f"[{tag}] pushing {len(audio)} samples through "
              f"full_chain('{tape_preset}', speed_offset={speed_offset}, seed={seed}) ...")
        rx, _sr, diag = cs.full_chain(audio, tape_preset, "usb_soundcard",
                                      speed_offset=speed_offset, seed=seed)
        print(f"[{tag}] full_chain diag: {diag}")
        sf.write(str(tmp), np.asarray(rx, dtype=np.float32), 48000, subtype="FLOAT")
    print(f"[{tag}] analyzing simulated recording ...")
    result = am.analyze(str(tmp), out_tag=f"sim_{tag}", verbose=True)
    # tmp kept on disk for reproducibility/debugging (git-ignored artifact).

    # Validation assertions
    speed = result["sync"]["speed"]
    applied_speed = 1.0 + speed_offset
    clock_err = abs(speed - applied_speed) / applied_speed
    print(f"[{tag}] clock recovered {speed:.4f}x vs applied {applied_speed:.4f}x "
          f"=> err {clock_err*100:.2f}%")

    per = result["per_config"]
    robust_rates = {c: per[c]["passrate"] for c in ROBUST}
    print(f"[{tag}] robust passrates: "
          + ", ".join(f"{c}={r:.2f}" for c, r in robust_rates.items()))
    return result


AGGRESSIVE = ["c2_m48_k6", "c4_qpsk", "c4_realmodel", "c4_simloaded"]


def main():
    print("=" * 70)
    print("TASK 2 VALIDATION GATE")
    print("=" * 70)
    r_worn = run_channel("worn", -0.12, seed=7, tag="worn")
    print()
    r_norm = run_channel("normal", 0.0, seed=3, tag="normal")

    # ------------------------------------------------------------------
    # Validation assertions — the analyzer + ladder must behave SENSIBLY:
    #   1. Global clock recovered to within ~1% on BOTH channels.
    #   2. On the clean `normal` channel the robust rungs decode (analyzer
    #      end-to-end correctness check): robust mean passrate high.
    #   3. On the harsh `worn -0.12` channel the ladder DEGRADES from robust
    #      to aggressive: mean robust passrate >> mean aggressive passrate, and
    #      the aggressive QPSK/loaded rungs collapse (~0) on the real null
    #      structure — exactly the expected sim->real transfer failure.
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    def mean_rate(res, cfgs):
        return sum(res["per_config"][c]["passrate"] for c in cfgs) / len(cfgs)

    # 1. clock
    worn_speed = r_worn["sync"]["speed"]
    norm_speed = r_norm["sync"]["speed"]
    worn_err = abs(worn_speed - 0.88) / 0.88
    norm_err = abs(norm_speed - 1.00) / 1.00
    print(f"[clock] worn recovered {worn_speed:.4f}x (applied 0.88, err {worn_err*100:.2f}%)")
    print(f"[clock] normal recovered {norm_speed:.4f}x (applied 1.00, err {norm_err*100:.2f}%)")
    assert worn_err < 0.01, f"worn clock error {worn_err*100:.2f}% > 1%"
    assert norm_err < 0.01, f"normal clock error {norm_err*100:.2f}% > 1%"

    # 2. normal end-to-end correctness: robust rungs decode well
    norm_robust = mean_rate(r_norm, ROBUST)
    print(f"[normal] robust mean passrate = {norm_robust:.2f}")
    assert norm_robust >= 0.8, f"normal robust mean {norm_robust:.2f} < 0.8 (analyzer broken)"

    # 3. worn degradation: robust >> aggressive, aggressive collapses
    worn_robust = mean_rate(r_worn, ROBUST)
    worn_aggr = mean_rate(r_worn, AGGRESSIVE)
    print(f"[worn] robust mean passrate = {worn_robust:.2f}, "
          f"aggressive mean passrate = {worn_aggr:.2f}")
    assert worn_robust > worn_aggr, "ladder did not degrade robust->aggressive on worn"
    assert worn_aggr < 0.2, f"aggressive rungs did not collapse on worn ({worn_aggr:.2f})"

    print("\nPer-config tables:")
    hdr = (f"  {'config':<14} {'gross':>7} {'raw_ber':>8} "
           f"{'passrate':>8} {'net_bps':>8} {'P_full':>7} {'FEC_OK':>7}")
    sep = "  " + "-" * (len(hdr) - 2)

    print("\n  -- worn (speed_offset=-0.12) --")
    print(hdr); print(sep)
    for c in am.CONFIG_ORDER:
        d = r_worn["per_config"][c]
        ber_s = f"{d.get('raw_ber', float('nan')):.4f}"
        fec_s = "YES" if d.get("recoverable_with_FEC") else "no"
        print(f"  {c:<14} {d['gross_bps']:>7.0f} {ber_s:>8} "
              f"{d['passrate']:>8.2f} {d.get('proj_net_bps',0):>8.0f} "
              f"{d.get('proj_P_full',0):>7.2f} {fec_s:>7}")

    print("\n  -- normal (speed_offset=0.0) --")
    print(hdr); print(sep)
    for c in am.CONFIG_ORDER:
        d = r_norm["per_config"][c]
        ber_s = f"{d.get('raw_ber', float('nan')):.4f}"
        fec_s = "YES" if d.get("recoverable_with_FEC") else "no"
        print(f"  {c:<14} {d['gross_bps']:>7.0f} {ber_s:>8} "
              f"{d['passrate']:>8.2f} {d.get('proj_net_bps',0):>8.0f} "
              f"{d.get('proj_P_full',0):>7.2f} {fec_s:>7}")

    print("\nVALIDATION GATE PASSED.")
    return r_worn, r_norm


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true",
                    help="reuse on-disk _sim_*.wav fixtures (skip full_chain)")
    args = ap.parse_args()
    REUSE = args.reuse
    main()
