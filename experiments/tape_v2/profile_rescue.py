"""profile_rescue.py -- Profile the X11 rescue ladder to guide issue #21 acceleration.

Uses the m10doom3 gate mini-master with the marginal-channel capture
(dg=0.35, aac=False, clk=+0.00) which leaves 392/406 codewords failing
after the 8-branch ensemble -> rescue fires.

Profiles each rescue phase (r-a, r-b, r-c) independently with timers and
cProfile, printing a breakdown so we know where to focus.

Usage:
    cd /path/to/cassette-ai
    python3 experiments/tape_v2/profile_rescue.py [--cprofile] [--quick]
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import pathlib
import pstats
import sys
import time
import warnings

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
_DOOM = _HERE / "doom_ship"
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    _HERE,
    _DOOM,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np
import m10_decode as m10  # noqa: must be early
import m9_decode as m9d  # noqa
import analyze_master2 as am2  # noqa
import m10doom3_simgate as sg  # noqa
import m10doom3_decode as v3d  # noqa
import x11_d2x_erasure as xd  # noqa
from x10_a_fec_gmd_erasure import _rx_mat  # noqa

SR = 48000


def _new_ledger():
    return {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}


def _load_rescue_scenario(verbose=True):
    """Load the marginal scenario: dg=0.35, aac=False, clk=+0.00.
    Returns (audio_nom, align, sec, ledger, stock_row).
    """
    sg.build_mini(force=False)
    cap = sg.gen_capture(aac=False, clk=0.0, force=False)
    audio_nom, align, mani, sync = sg.sync_load(cap)
    sec = mani["ws_payloads"][0]
    n_cw = sec["meta"]["n_codewords"]
    if verbose:
        print(f"[profile] Loaded: {cap.name}")
        print(f"  frames={sec['meta']['n_frames']} codewords={n_cw} "
              f"RS({sec['meta']['rs_n']},{sec['meta']['rs_k']}) carriers={sec['meta'].get('P') or sec.get('dqpsk_params',{}).get('P')}")
        print(f"  align={align}")
    return audio_nom, align, sec


def profile_rescue_phases(audio_nom, align, sec, *, cprofile=False):
    """Profile each rescue phase (r-a, r-b, r-c) separately with timers."""
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    n_cw = meta["n_codewords"]
    k = meta["rs_k"]

    print(f"\n=== PHASE PROFILING (n_cw={n_cw}) ===")

    # ========== r-a: replicate stock pass-1 union ==========
    print("\n--- r-a: replicate stock pass-1 (8 frontends) ---")
    ledger_a = _new_ledger()
    union_msgs_a: list[bytes | None] = [None] * n_cw
    union_src_a: list[str | None] = [None] * n_cw
    pool_a: list[tuple[str, np.ndarray]] = []

    t0 = time.perf_counter()
    if cprofile:
        pr = cProfile.Profile()
        pr.enable()

    for label, sch_rx, fe in m10._frontends_for(sec):
        t_br = time.perf_counter()
        rx, _d = m9d._demod_section_frames(audio_nom, sec, align, sch_rx, fe)
        t_demod = time.perf_counter()
        mat = _rx_mat(rx, meta)
        _ok, msgs = m10._per_cw_decode(mat, meta, crc, ledger_a)
        t_rs = time.perf_counter()
        m10._union_fill(union_msgs_a, union_src_a, msgs, label)
        pool_a.append((label, mat))
        print(f"  {label}: demod={t_demod-t_br:.2f}s  RS={t_rs-t_demod:.2f}s  "
              f"cw_failed={n_cw - sum(1 for m in msgs if m)}", flush=True)

    if cprofile:
        pr.disable()
        _print_cprofile(pr, "r-a", n=20)

    t_a = time.perf_counter() - t0
    failed_p1 = [i for i in range(n_cw) if union_msgs_a[i] is None]
    print(f"\n  r-a total: {t_a:.1f}s  failed_after_p1={len(failed_p1)}/{n_cw}")
    print(f"  ledger: {ledger_a}")

    # ========== r-b: shift-window sweep ==========
    print(f"\n--- r-b: shift-window sweep (2 geos x 2 bases) ---")
    union_msgs_b = list(union_msgs_a)  # copy
    union_src_b = list(union_src_a)
    pool_b = list(pool_a)
    ledger_b = _new_ledger()

    t0_b = time.perf_counter()
    if cprofile:
        pr = cProfile.Profile()
        pr.enable()

    sweep_rec = {}
    for geo in xd.RESCUE_GEOS:
        for base in xd.RESCUE_BASES:
            still = [i for i in range(n_cw) if union_msgs_b[i] is None]
            if not still:
                break
            t_sw = time.perf_counter()
            branches, brec = xd._d2x_shift_branches(audio_nom, align, sec, geo, base)
            t_sw2 = time.perf_counter()
            n_branches = len(branches)
            sweep_rec[f"{geo}_{base}"] = brec

            branch_rs_total = 0.0
            branch_demod_time = t_sw2 - t_sw
            for bn, frames in branches.items():
                still = [i for i in range(n_cw) if union_msgs_b[i] is None]
                if not still:
                    break
                t_rs0 = time.perf_counter()
                mat = _rx_mat(frames, meta)
                _ok, msgs = m10._per_cw_decode(mat, meta, crc, ledger_b, only_cw=still)
                m10._union_fill(union_msgs_b, union_src_b, msgs, bn)
                pool_b.append((bn, mat))
                branch_rs_total += time.perf_counter() - t_rs0

            print(f"  {geo}+{base}: demod_sweep={branch_demod_time:.2f}s  "
                  f"branch_RS={branch_rs_total:.2f}s  n_branches={n_branches}  "
                  f"still_failing={len([i for i in range(n_cw) if union_msgs_b[i] is None])}",
                  flush=True)

    if cprofile:
        pr.disable()
        _print_cprofile(pr, "r-b", n=20)

    t_b = time.perf_counter() - t0_b
    failed_p2 = [i for i in range(n_cw) if union_msgs_b[i] is None]
    print(f"\n  r-b total: {t_b:.1f}s  failed_after_sweep={len(failed_p2)}/{n_cw}")
    print(f"  ledger_b: {ledger_b}")

    # ========== r-c: erasure ladder ==========
    print(f"\n--- r-c: erasure ladder (pool={len(pool_b)} branches) ---")
    union_msgs_c = list(union_msgs_b)
    union_src_c = list(union_src_b)
    ledger_c = _new_ledger()

    if failed_p2:
        t0_c = time.perf_counter()
        if cprofile:
            pr = cProfile.Profile()
            pr.enable()

        rank, disp = m10._rank_carriers(audio_nom, align, sec, verbose=False)
        t_rank = time.perf_counter()
        ranked_pool = sorted(pool_b,
                             key=lambda bm: xd._consensus_distance(bm[1], union_msgs_b, meta))
        branch_mats = [(bn, mat) for bn, mat in ranked_pool[:m10.N_LADDER_BRANCHES]]
        t_rank2 = time.perf_counter()
        print(f"  carrier_rank={t_rank-t0_c:.2f}s  pool_sort={t_rank2-t_rank:.3f}s")
        print(f"  branches: {[bn for bn,_ in branch_mats]}")

        ladder_rec = m10._erasure_ladder(sec, meta, crc, branch_mats,
                                          union_msgs_c, union_src_c, rank, ledger_c,
                                          verbose=True)

        if cprofile:
            pr.disable()
            _print_cprofile(pr, "r-c", n=20)

        t_c = time.perf_counter() - t0_c
        failed_final = [i for i in range(n_cw) if union_msgs_c[i] is None]
        print(f"\n  r-c total: {t_c:.1f}s  failed_final={len(failed_final)}/{n_cw}")
        print(f"  ladder trials={ladder_rec['trials']}  accepted={len(ladder_rec['accepted'])}")
        print(f"  ledger_c: {ledger_c}")
        print(f"\n  === SUMMARY ===")
        print(f"  r-a: {t_a:.1f}s  r-b: {t_b:.1f}s  r-c: {t_c:.1f}s  total: {t_a+t_b+t_c:.1f}s")
        pct = [100*t/(t_a+t_b+t_c) for t in [t_a, t_b, t_c]]
        print(f"  r-a: {pct[0]:.0f}%  r-b: {pct[1]:.0f}%  r-c: {pct[2]:.0f}%")
        return {
            "t_a": t_a, "t_b": t_b, "t_c": t_c,
            "failed_p1": len(failed_p1), "failed_p2": len(failed_p2),
            "failed_final": len(failed_final),
            "ladder_trials": ladder_rec["trials"],
            "ledger_a": ledger_a, "ledger_b": ledger_b, "ledger_c": ledger_c,
        }
    else:
        print(f"  r-c skipped (all codewords filled after r-b)")
        return {"t_a": t_a, "t_b": t_b, "t_c": 0.0,
                "failed_p1": len(failed_p1), "failed_p2": len(failed_p2)}


def _print_cprofile(pr, label, n=20):
    buf = io.StringIO()
    ps = pstats.Stats(pr, stream=buf)
    ps.sort_stats("cumulative")
    ps.print_stats(n)
    lines = buf.getvalue().split("\n")
    print(f"\n  [cProfile {label} top-{n}]")
    for ln in lines[5:5+n+5]:
        print("  " + ln)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cprofile", action="store_true",
                    help="also run cProfile on each phase")
    ap.add_argument("--quick", action="store_true",
                    help="skip r-c profiling (faster for demod analysis)")
    args = ap.parse_args()

    audio_nom, align, sec = _load_rescue_scenario(verbose=True)
    results = profile_rescue_phases(audio_nom, align, sec,
                                    cprofile=args.cprofile)
    print(f"\n[profile] Done. Results: {results}")


if __name__ == "__main__":
    main()
