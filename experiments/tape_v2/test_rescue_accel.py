"""test_rescue_accel.py -- Parity gate for the parallel rescue acceleration (issue #21).

FAST TESTS (< 3 min each, run by default):
  T1: _ladder_chunk_worker parity — serial vs parallel on 50 failing codewords
      from the gate rescue scenario.  Both must return identical (recovered set,
      RS attempt counts).  This is the primary parity gate.

  T2: _parallel_sweep parity — full 4-pair sweep, serial vs parallel(4w),
      assembled bytes must be identical.

SLOW TESTS (opt-in, --full, ~15 min total):
  T3: Full rescue parity — x11_rescue_section_bytes vs x11_rescue_section_bytes_accel.
      Byte-identical assembled payload + cw_failed_final must match.

PARITY PROOF (both tests):
  r-c: Each codeword processed independently. Worker iterates (set, branch) in
       same order as serial _erasure_ladder and returns first success.
       codeword results are independent → merge order irrelevant → identical.
  r-b: Branch results collected in original geo×base×branch order; fill-only
       union applied in that order → same first-source per codeword → identical.

Usage:
    python3 experiments/tape_v2/test_rescue_accel.py           # fast tests T1 + T2
    python3 experiments/tape_v2/test_rescue_accel.py --full    # also T3 (~15 min)
    python3 experiments/tape_v2/test_rescue_accel.py --t1only  # just ladder chunk test
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
import warnings

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
_DOOM = _HERE / "doom_ship"
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT/"src", ROOT/"tests"/"e2e", ROOT/"experiments"/"deepdive2",
           ROOT/"experiments"/"capacity", _HERE, _DOOM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np
import m10_decode as m10
import m9_decode as m9d
import m10doom3_simgate as sg
import x11_d2x_erasure as xd
from x10_a_fec_gmd_erasure import _rx_mat, carrier_class_map
import rescue_accel as ra


def _new_led():
    return {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}


def _load_scenario():
    sg.build_mini(force=False)
    cap = sg.gen_capture(aac=False, clk=0.0, force=False)
    audio_nom, align, mani, _ = sg.sync_load(cap)
    sec = mani["ws_payloads"][0]
    print(f"[scenario] {cap.name}  cw={sec['meta']['n_codewords']}  "
          f"frames={sec['meta']['n_frames']}", flush=True)
    return audio_nom, align, sec


def _run_ra_pool(audio_nom, align, sec):
    """Return (union_msgs, union_src, pool, ledger) after r-a only."""
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    n_cw = meta["n_codewords"]
    led = _new_led()
    union_msgs = [None] * n_cw
    union_src = [None] * n_cw
    pool = []
    for label, sch_rx, fe in m10._frontends_for(sec):
        rx, _ = m9d._demod_section_frames(audio_nom, sec, align, sch_rx, fe)
        mat = _rx_mat(rx, meta)
        _ok, msgs = m10._per_cw_decode(mat, meta, crc, led)
        m10._union_fill(union_msgs, union_src, msgs, label)
        pool.append((label, mat))
    failed = [i for i in range(n_cw) if union_msgs[i] is None]
    print(f"  r-a: {len(failed)}/{n_cw} still failing  "
          f"RS={led['rs_attempts']}", flush=True)
    return union_msgs, union_src, pool, led, failed


# ============================================================
# T1: _ladder_chunk_worker parity on 50 failing codewords
# ============================================================
def test_t1_ladder_chunk_parity(audio_nom, align, sec, n_workers=4, chunk_size=50):
    """PRIMARY PARITY GATE for r-c.

    Runs _ladder_chunk_worker on the first `chunk_size` failing codewords
    from the gate scenario, comparing serial (workers=1) vs parallel (workers=N).
    The chunk is small enough to run in ~60–90s total.
    """
    print(f"\n{'='*55}")
    print(f"T1: ladder chunk parity (chunk={chunk_size}, workers={n_workers})")
    print(f"{'='*55}")

    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    n_cw = meta["n_codewords"]

    # Build pool from r-a, compute rank, then prepare branch_mats
    print("[T1] Running r-a (37s)...", flush=True)
    um, src, pool, _, failed = _run_ra_pool(audio_nom, align, sec)
    assert len(failed) > 0, "r-a already solved everything"

    print("[T1] Computing carrier rank (7s)...", flush=True)
    rank, _ = m10._rank_carriers(audio_nom, align, sec, verbose=False)
    ranked = sorted(pool, key=lambda bm: xd._consensus_distance(bm[1], um, meta))
    branch_mats = ranked[:m10.N_LADDER_BRANCHES]

    # Build the args for _parallel_erasure_ladder (which internally calls the chunk workers)
    P = len(m10._tx_scheme(sec).data_idx)
    positions, _ = carrier_class_map(meta, P)
    top = [c for c in rank if c < P][:m10.TOP_RANKED]
    sets = ([(c,) for c in top]
            + [(top[a], top[b]) for a in range(len(top))
               for b in range(a + 1, len(top))]
            + [tuple(top[x] for x in range(len(top)) if x != skip)
               for skip in range(len(top) - 1, -1, -1)])
    sets_ser = [list(s) for s in sets]
    positions_cw = [[list(positions[i][c]) for c in range(P)] for i in range(n_cw)]
    branch_rows = [(bname, [bytes(mat[i]) for i in range(n_cw)])
                   for bname, mat in branch_mats]

    # Take a small chunk of failing codewords
    cw_chunk = failed[:chunk_size]
    print(f"[T1] Testing on chunk {cw_chunk[:5]}...{cw_chunk[-1]} "
          f"({len(cw_chunk)} codewords)", flush=True)

    chunk_args = (cw_chunk, branch_rows, meta["rs_n"], meta["rs_k"],
                  list(crc), positions_cw, sets_ser, m10.MAX_PATTERNS_PER_CW)

    # Serial
    print(f"[T1] Serial (workers=1, expect ~{chunk_size*56*0.022:.0f}s)...", flush=True)
    t0 = time.perf_counter()
    results_s, n_rs_s, n_crc_s, n_rej_s = ra._ladder_chunk_worker(chunk_args)
    t_serial = time.perf_counter() - t0
    print(f"     Done: {len(results_s)} recovered  RS={n_rs_s}  {t_serial:.1f}s",
          flush=True)

    # Parallel (n_workers): split the chunk across workers via _parallel_erasure_ladder
    # We can't call _parallel directly on the same chunk_args without the full API.
    # Instead use _parallel_erasure_ladder with a fresh union state capped to cw_chunk.
    um_par = list(um)
    src_par = list(src)
    led_par = _new_led()
    # Temporarily set all non-chunk codewords as "filled" so ladder only processes chunk
    um_test_s = list(um)
    src_test_s = list(src)
    um_test_p = list(um)
    src_test_p = list(src)
    # Force-fill all codewords not in chunk (so ladder skips them)
    _sentinel = b"\x00" * meta["rs_k"]
    for i in range(n_cw):
        if i not in set(cw_chunk):
            um_test_s[i] = _sentinel
            um_test_p[i] = _sentinel

    led_s = _new_led()
    t0 = time.perf_counter()
    ra._parallel_erasure_ladder(sec, meta, crc, branch_mats,
                                  um_test_s, src_test_s, rank, led_s,
                                  workers=1, verbose=False)
    t_serial2 = time.perf_counter() - t0

    led_p = _new_led()
    t0 = time.perf_counter()
    ra._parallel_erasure_ladder(sec, meta, crc, branch_mats,
                                  um_test_p, src_test_p, rank, led_p,
                                  workers=n_workers, verbose=False)
    t_par = time.perf_counter() - t0

    print(f"[T1] serial({chunk_size}cw): {t_serial2:.1f}s  RS={led_s['rs_attempts']}",
          flush=True)
    print(f"[T1] parallel({n_workers}w, {chunk_size}cw): {t_par:.1f}s  "
          f"RS={led_p['rs_attempts']}", flush=True)
    speedup = t_serial2 / max(0.01, t_par)
    print(f"[T1] Speedup on r-c chunk: {speedup:.2f}x", flush=True)

    # Parity checks
    recovered_s = {i for i in cw_chunk if um_test_s[i] is not None
                   and um_test_s[i] is not _sentinel}
    recovered_p = {i for i in cw_chunk if um_test_p[i] is not None
                   and um_test_p[i] is not _sentinel}

    # Assemble just the chunk portion and compare bytes
    assembled_s = m10._assemble(meta, um_test_s)
    assembled_p = m10._assemble(meta, um_test_p)

    assert recovered_s == recovered_p, \
        f"PARITY FAIL: recovered sets differ: serial={sorted(recovered_s)} par={sorted(recovered_p)}"
    assert assembled_s == assembled_p, "PARITY FAIL: assembled bytes differ!"
    assert led_s["rs_attempts"] == led_p["rs_attempts"], \
        f"RS attempt count: serial={led_s['rs_attempts']} par={led_p['rs_attempts']}"
    assert led_s["crc_accepts"] == led_p["crc_accepts"], \
        f"CRC accept count: serial={led_s['crc_accepts']} par={led_p['crc_accepts']}"

    print(f"[T1] PASS: serial={len(recovered_s)} recovered, "
          f"parallel={len(recovered_p)} recovered, "
          f"byte-identical, RS counts match", flush=True)
    print(f"  r-c speedup on {chunk_size}-codeword chunk: {speedup:.2f}x "
          f"(serial={t_serial2:.1f}s par={t_par:.1f}s {n_workers}w)", flush=True)
    return True, {"t_serial": t_serial2, "t_par": t_par, "speedup": speedup,
                  "recovered": len(recovered_s), "chunk_size": chunk_size}


# ============================================================
# T2: full r-b sweep parity
# ============================================================
def test_t2_sweep_parity(audio_nom, align, sec, sweep_workers=4):
    """Verify _parallel_sweep produces byte-identical results to serial sweep."""
    print(f"\n{'='*55}")
    print(f"T2: r-b sweep parity (workers={sweep_workers})")
    print(f"{'='*55}")

    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    n_cw = meta["n_codewords"]

    # Serial r-a + r-b reference
    print("[T2] r-a + serial r-b...", flush=True)
    um_s, src_s, pool_s, _, _ = _run_ra_pool(audio_nom, align, sec)
    pool_s_full = list(pool_s)
    t0 = time.perf_counter()
    for geo in xd.RESCUE_GEOS:
        for base in xd.RESCUE_BASES:
            branches, _ = xd._d2x_shift_branches(audio_nom, align, sec,
                                                   geo, base, verbose=False)
            for bn, frames in branches.items():
                mat = _rx_mat(frames, meta)
                still = [i for i in range(n_cw) if um_s[i] is None]
                if not still:
                    break
                ld = _new_led()
                _ok, msgs = m10._per_cw_decode(mat, meta, crc, ld, only_cw=still)
                m10._union_fill(um_s, src_s, msgs, bn)
                pool_s_full.append((bn, mat))
    t_serial_rb = time.perf_counter() - t0
    assembled_serial = m10._assemble(meta, um_s)
    failed_serial = [i for i in range(n_cw) if um_s[i] is None]
    print(f"  Serial r-b: {len(failed_serial)}/{n_cw} still failing  "
          f"{t_serial_rb:.1f}s", flush=True)

    # Parallel r-a + parallel r-b
    print(f"[T2] r-a + parallel r-b ({sweep_workers}w)...", flush=True)
    um_p, src_p, pool_p, _, _ = _run_ra_pool(audio_nom, align, sec)
    pool_p_full = list(pool_p)
    led_p = _new_led()
    t0 = time.perf_counter()
    sweep_rec, pool_new = ra._parallel_sweep(
        audio_nom, align, sec, um_p, src_p, pool_p_full, led_p,
        workers=sweep_workers, verbose=False)
    pool_p_full.extend(pool_new)
    t_par_rb = time.perf_counter() - t0
    assembled_par = m10._assemble(meta, um_p)
    failed_par = [i for i in range(n_cw) if um_p[i] is None]
    print(f"  Parallel r-b: {len(failed_par)}/{n_cw} still failing  "
          f"{t_par_rb:.1f}s ({sweep_workers}w)", flush=True)
    speedup = t_serial_rb / max(0.01, t_par_rb)
    print(f"  r-b speedup: {speedup:.2f}x  (serial={t_serial_rb:.1f}s "
          f"par={t_par_rb:.1f}s)", flush=True)

    # Parity
    assert failed_serial == failed_par, \
        (f"PARITY FAIL: still-failing differs\n"
         f"  serial={failed_serial[:5]} par={failed_par[:5]}")
    assert assembled_serial == assembled_par, "PARITY FAIL: assembled bytes differ!"
    # Source labels for filled codewords must match
    for i in range(n_cw):
        if um_s[i] is not None:
            assert src_s[i] == src_p[i], \
                f"PARITY FAIL: cw {i} source {src_s[i]!r} != {src_p[i]!r}"

    print(f"[T2] PASS: byte-identical, same still-failing set, same sources "
          f"(speedup={speedup:.2f}x)", flush=True)
    return True, {"t_serial_rb": t_serial_rb, "t_par_rb": t_par_rb,
                  "speedup": speedup, "failed_after": len(failed_par)}


# ============================================================
# T3: Full rescue parity (slow, opt-in)
# ============================================================
def test_t3_full_rescue_parity(audio_nom, align, sec,
                                sweep_w=4, ladder_w=4):
    """Byte-identical assembled payload: serial vs accelerated full rescue."""
    print(f"\n{'='*55}")
    print(f"T3: Full rescue parity (sw={sweep_w} lw={ladder_w}) [SLOW ~20 min]")
    print(f"{'='*55}")
    import m10doom3_decode as v3d
    meta = sec["meta"]
    n_cw = meta["n_codewords"]

    # Build stock_row via stage-A decode
    led_a = _new_led()
    r_a, assembled_a = m10._decode_section(audio_nom, sec, align, led_a,
                                             rescue=True, verbose=False)
    ladder = r_a.get("ladder") or {}
    targets = ladder.get("target_cws")
    accepted = {a["cw"] for a in (ladder.get("accepted") or [])}
    stock_row = {
        "name": sec["name"],
        "cw_failed": int(r_a["rs_codewords_failed"]),
        "stock_ladder_targets": targets,
        "failed_idx": ([i for i in targets if i not in accepted]
                       if targets is not None else None),
    }
    print(f"  Stage A: {r_a['rs_codewords_failed']}/{n_cw} failed", flush=True)

    # Serial rescue
    print("[T3] Serial rescue (will take ~10 min)...", flush=True)
    led_s = _new_led()
    t0 = time.perf_counter()
    rec_s, asm_s = v3d.x11_rescue_section_bytes(
        audio_nom, sec, align, led_s, stock_row, verbose=False)
    t_serial = time.perf_counter() - t0
    print(f"  Serial: {rec_s['cw_failed_final']}/{n_cw} failed  {t_serial:.1f}s",
          flush=True)

    # Parallel rescue
    print(f"[T3] Parallel rescue (sw={sweep_w} lw={ladder_w})...", flush=True)
    led_p = _new_led()
    t0 = time.perf_counter()
    rec_p, asm_p = ra.x11_rescue_section_bytes_accel(
        audio_nom, sec, align, led_p, stock_row,
        sweep_workers=sweep_w, ladder_workers=ladder_w, verbose=False)
    t_par = time.perf_counter() - t0
    speedup = t_serial / max(0.01, t_par)
    print(f"  Parallel: {rec_p['cw_failed_final']}/{n_cw} failed  {t_par:.1f}s  "
          f"speedup={speedup:.2f}x", flush=True)

    assert asm_s == asm_p, "PARITY FAIL: assembled bytes differ!"
    assert rec_s["cw_failed_final"] == rec_p["cw_failed_final"], \
        (f"cw_failed_final differs: {rec_s['cw_failed_final']} "
         f"vs {rec_p['cw_failed_final']}")
    print(f"[T3] PASS: BYTE-IDENTICAL assembled payload  "
          f"speedup={speedup:.2f}x  (serial={t_serial:.0f}s par={t_par:.0f}s)",
          flush=True)
    return True, {"t_serial": t_serial, "t_par": t_par, "speedup": speedup,
                  "cw_failed": rec_p["cw_failed_final"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="also run T3 (full rescue parity, ~20 min)")
    ap.add_argument("--t1only", action="store_true",
                    help="only run T1 (ladder chunk parity, ~3 min)")
    ap.add_argument("--ladder-workers", type=int, default=4)
    ap.add_argument("--sweep-workers", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=50,
                    help="number of failing codewords to test in T1")
    args = ap.parse_args()

    audio_nom, align, sec = _load_scenario()

    results = {}

    ok1, s1 = test_t1_ladder_chunk_parity(
        audio_nom, align, sec, n_workers=args.ladder_workers, chunk_size=args.chunk)
    results["T1"] = {"pass": ok1, **s1}

    if not args.t1only:
        ok2, s2 = test_t2_sweep_parity(
            audio_nom, align, sec, sweep_workers=args.sweep_workers)
        results["T2"] = {"pass": ok2, **s2}
    else:
        ok2 = True
        results["T2"] = {"skipped": True}

    if args.full and not args.t1only:
        ok3, s3 = test_t3_full_rescue_parity(
            audio_nom, align, sec, sweep_w=args.sweep_workers,
            ladder_w=args.ladder_workers)
        results["T3"] = {"pass": ok3, **s3}
    else:
        ok3 = True
        results["T3"] = {"skipped": True}

    print("\n" + "=" * 55)
    print("PARITY GATE SUMMARY")
    print("=" * 55)
    for name, r in results.items():
        if r.get("skipped"):
            print(f"  {name}: skipped")
        else:
            status = "PASS" if r.get("pass") else "FAIL"
            extras = ""
            if "speedup" in r:
                extras += f" (speedup={r['speedup']:.2f}x)"
            print(f"  {name}: {status}{extras}")
    all_ok = ok1 and ok2 and ok3
    print(f"\n  GATE: {'PASS' if all_ok else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
