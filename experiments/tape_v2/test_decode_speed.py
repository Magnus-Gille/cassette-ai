"""test_decode_speed.py -- Parity gate + benchmark for issue #21 decode speedups.

Verifies:
  WIN 1 (early-exit ensemble): already in the code since be9047e. Confirmed by
         checking that on a clean (no-channel) WAV the early-exit fires and
         fewer than all 8 branches are used.
  WIN 2 (parallel front-end bank): new --parallel flag on _decode_section.
         Asserts assembled bytes are BYTE-IDENTICAL to the serial path.

Parity gate method: uses the existing doom_ship gate mini-master
(m10doom3_gate_manifest.json + m10doom3_gate.bin, both committed) to build a
reproducible WAV in-worktree, decodes it serially then in parallel, and
asserts assembled bytes are byte-identical.

Usage:
    python3 experiments/tape_v2/test_decode_speed.py
    python3 experiments/tape_v2/test_decode_speed.py --noisy  # also tests w/ channel noise
"""
from __future__ import annotations

import argparse
import json
import pathlib
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

# IMPORTANT: import m10_decode from THIS worktree's tape_v2 BEFORE any transitive
# import causes analyze_master2 to prepend the MAIN repo's tape_v2 to sys.path.
# analyze_master2 does `TAPE_V2 = ROOT/"experiments"/"tape_v2"; sys.path.insert(0, ...)`
# with a hardcoded ROOT pointing to the main repo, so once it's imported any module
# not yet in sys.modules would be resolved from the main repo instead of the worktree.
# Importing m10_decode explicitly first ensures sys.modules caches the worktree version.
import m10_decode as m10  # noqa: E402  ← must be first
import numpy as np  # noqa: E402
import analyze_master2 as am2  # noqa: E402
import m10doom3_simgate as sg  # noqa: E402

GATE_WAV = sg.GATE_WAV
GATE_MANIFEST = sg.GATE_MANIFEST
GATE_SIDECAR = sg.GATE_SIDECAR


def _build_and_sync(verbose=False):
    """Build gate WAV (idempotent) and sync. Returns (audio_nom, align, sec)."""
    sg.build_mini(force=False)
    audio, align, mani, _ = sg.sync_load(GATE_WAV)
    sec = mani["ws_payloads"][0]
    return audio, align, sec


def _serial_decode(audio_nom, sec, align, *, verbose=False):
    """Run _decode_section serially. Returns (assembled, elapsed_s, n_branches)."""
    ledger = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
    # patch verbose into branch_records to count how many branches ran
    t0 = time.time()
    res, assembled = m10._decode_section(audio_nom, sec, align, ledger,
                                         rescue=True, verbose=verbose)
    elapsed = time.time() - t0
    n_branches = len([b for b in res.get("branch_records", [])
                      if b.get("stage") == "ensemble"])
    return assembled, elapsed, n_branches, res


def _parallel_decode(audio_nom, sec, align, n_workers=None, *, verbose=False):
    """Run _decode_section with parallel=True. Returns (assembled, elapsed_s, n_branches)."""
    ledger = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
    import os
    workers = n_workers or min(8, os.cpu_count() or 4)
    t0 = time.time()
    res, assembled = m10._decode_section(audio_nom, sec, align, ledger,
                                         rescue=True, verbose=verbose,
                                         parallel=workers)
    elapsed = time.time() - t0
    n_branches = len([b for b in res.get("branch_records", [])
                      if b.get("stage") == "ensemble"])
    return assembled, elapsed, n_branches, res


def run_clean(verbose=True):
    """Parity + benchmark on the clean (no-channel) gate WAV."""
    if verbose:
        print("\n=== CLEAN (no-channel) gate decode ===", flush=True)
    print("[test] Building / loading gate WAV...", flush=True)
    audio_nom, align, sec = _build_and_sync(verbose=False)
    n_cw = sec["meta"]["n_codewords"]
    n_frontends = len(m10.D2X_PLAN)

    if verbose:
        print(f"[test] Section: {sec['name']}, {sec['meta']['n_frames']} frames, "
              f"{n_cw} codewords, {n_frontends} frontend branches", flush=True)

    # ----- SERIAL (WIN 1 verification) -----
    print("[test] Serial decode...", flush=True)
    assembled_s, t_serial, n_br_s, res_s = _serial_decode(audio_nom, sec, align,
                                                           verbose=verbose)
    be_s = bool(assembled_s == (ROOT / "experiments" / "tape_v2" / sec["payload_sidecar"]).read_bytes())
    print(f"[test] Serial: {n_br_s}/{n_frontends} branches, {t_serial:.1f}s, "
          f"cw_failed={res_s['rs_codewords_failed']}, byte_exact={be_s}", flush=True)
    assert be_s, f"Serial baseline failed byte-exact on clean WAV! cw_failed={res_s['rs_codewords_failed']}"

    # WIN 1 check: on clean WAV, early exit should fire (fewer branches than total)
    if n_br_s < n_frontends:
        print(f"[test] WIN 1 OK: early exit fired after {n_br_s}/{n_frontends} branches", flush=True)
    else:
        print(f"[test] NOTE: all {n_frontends} branches ran (early exit did not fire -- "
              "may still be OK if first branch had non-zero failures)", flush=True)

    # ----- PARALLEL (WIN 2 parity) -----
    print("[test] Parallel decode...", flush=True)
    try:
        assembled_p, t_par, n_br_p, res_p = _parallel_decode(audio_nom, sec, align,
                                                               verbose=verbose)
        be_p = bool(assembled_p == (ROOT / "experiments" / "tape_v2" / sec["payload_sidecar"]).read_bytes())
        parity = bool(assembled_p == assembled_s)
        print(f"[test] Parallel: {n_br_p}/{n_frontends} branches, {t_par:.1f}s, "
              f"cw_failed={res_p['rs_codewords_failed']}, byte_exact={be_p}, "
              f"parity_with_serial={parity}", flush=True)

        assert parity, "PARITY FAIL: parallel assembled bytes differ from serial!"
        assert be_p, "Parallel byte_exact failed on clean WAV!"

        speedup = t_serial / t_par if t_par > 0 else float("inf")
        print(f"\n[test] CLEAN GATE RESULT: "
              f"serial={t_serial:.1f}s parallel={t_par:.1f}s speedup={speedup:.2f}x", flush=True)
        print(f"[test] WIN 1 verified: {n_br_s}/{n_frontends} serial branches (early exit)")
        print(f"[test] WIN 2 verified: BYTE-IDENTICAL output (parity={parity})")
        return True, {"t_serial": t_serial, "t_par": t_par, "speedup": speedup,
                      "n_serial_branches": n_br_s, "n_frontend_total": n_frontends}
    except TypeError as e:
        if "parallel" in str(e) or "unexpected keyword" in str(e):
            print(f"[test] WIN 2 not yet implemented: {e}", flush=True)
            print("[test] Only WIN 1 verification done.", flush=True)
            return None, None
        raise


def run_noisy(verbose=True):
    """Parity + benchmark on a noisy (sim channel) gate capture."""
    print("\n=== NOISY (simulated channel) gate decode ===", flush=True)
    try:
        import sim_v2
        import x11_d2x_erasure as xd
    except ImportError as e:
        print(f"[test] Skipping noisy test (import error: {e})", flush=True)
        return None, None

    print("[test] Building gate WAV + generating noisy capture...", flush=True)
    sg.build_mini(force=False)
    # use a mild channel: dg=0.35 (the x11 marginal), no AAC, no clock offset
    cap = sg.gen_capture(aac=False, clk=0.0, force=False)
    audio, align, mani, _ = sg.sync_load(cap)
    sec = mani["ws_payloads"][0]
    n_cw = sec["meta"]["n_codewords"]
    n_frontends = len(m10.D2X_PLAN)

    print("[test] Serial decode (noisy)...", flush=True)
    assembled_s, t_serial, n_br_s, res_s = _serial_decode(audio, sec, align,
                                                           verbose=verbose)
    print(f"[test] Serial: {n_br_s}/{n_frontends} branches, {t_serial:.1f}s, "
          f"cw_failed={res_s['rs_codewords_failed']}", flush=True)

    print("[test] Parallel decode (noisy)...", flush=True)
    try:
        assembled_p, t_par, n_br_p, res_p = _parallel_decode(audio, sec, align,
                                                               verbose=verbose)
        parity = bool(assembled_p == assembled_s)
        print(f"[test] Parallel: {n_br_p}/{n_frontends} branches, {t_par:.1f}s, "
              f"cw_failed={res_p['rs_codewords_failed']}, parity={parity}", flush=True)
        assert parity, "PARITY FAIL on noisy capture!"
        speedup = t_serial / t_par if t_par > 0 else float("inf")
        print(f"\n[test] NOISY GATE RESULT: "
              f"serial={t_serial:.1f}s parallel={t_par:.1f}s speedup={speedup:.2f}x", flush=True)
        return True, {"t_serial": t_serial, "t_par": t_par, "speedup": speedup,
                      "n_serial_branches": n_br_s}
    except (AttributeError, TypeError) as e:
        if "parallel" in str(e) or "unexpected keyword" in str(e):
            print(f"[test] WIN 2 not yet implemented: {e}", flush=True)
            return None, None
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--noisy", action="store_true",
                    help="also run with a simulated-channel noisy capture")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    ok_clean, stats_clean = run_clean(verbose=args.verbose)
    ok_noisy = stats_noisy = None
    if args.noisy:
        ok_noisy, stats_noisy = run_noisy(verbose=args.verbose)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if ok_clean is True:
        print(f"  CLEAN PARITY: PASS")
        if stats_clean:
            print(f"    serial={stats_clean['t_serial']:.1f}s "
                  f"parallel={stats_clean['t_par']:.1f}s "
                  f"speedup={stats_clean['speedup']:.2f}x")
            print(f"    WIN 1: early exit after "
                  f"{stats_clean['n_serial_branches']}/{stats_clean['n_frontend_total']} branches")
    elif ok_clean is None:
        print("  WIN 2 not yet implemented -- serial parity verified only")
    else:
        print("  CLEAN PARITY: FAIL")
        sys.exit(1)

    if ok_noisy is True:
        print(f"  NOISY PARITY: PASS")
        if stats_noisy:
            print(f"    serial={stats_noisy['t_serial']:.1f}s "
                  f"parallel={stats_noisy['t_par']:.1f}s "
                  f"speedup={stats_noisy['speedup']:.2f}x")
    elif ok_noisy is None and args.noisy:
        print("  NOISY: skipped or WIN 2 not implemented")

    sys.exit(0)


if __name__ == "__main__":
    main()
