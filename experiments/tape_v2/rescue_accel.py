"""rescue_accel.py -- Parallel acceleration of the X11 d2x rescue ladder (issue #21).

Profiling breakdown (gate scenario dg0.35_aac0_clk+0.00, 406 cw, 11 frames):
  r-a (replicate stock 8-frontend union):  37.7s   5%
  r-b (shift-window sweep, 4 geo×base):   177.4s  26%
      demod (scipy, GIL-released): 51.6s
      RS decode (reedsolo, GIL-held): 125.8s
  r-c (erasure ladder, 392 failing cw):   476.0s  69%
      RS only: 21,952 attempts at ~21.7ms each
  Total serial: 691.1s

Bottleneck: reedsolo RS decode is pure Python (GIL-held). Threads cannot
parallelize it. ProcessPoolExecutor gives each worker its own GIL.

Acceleration:
  r-b: 4 workers (one per geo×base pair). Each does full demod+RS. Apply
       branch results in original geo×base×branch order for fill-only union.
       Critical path (rect+pll ≈ 84s) → ~2× speedup on r-b.
  r-c: N workers (default 8). Each handles chunk of ~(n_fail/N) codewords.
       Each worker iterates (set, branch) in the same order as serial, returns
       first success per codeword. Speedup: ~N× on r-c (near-linear).

Parity (provably byte-identical to serial):
  r-b: results collected in original geo×base×branch order; fill-only union
       applied in that order. First source per codeword = same as serial.
  r-c: each codeword processed independently; worker uses same (set, branch)
       iteration order as serial _erasure_ladder; returns first success.
       Codeword results are independent → merge order is irrelevant.
  Verified: test_rescue_accel.py asserts byte-identical assembled payload.

Usage: imported by m10doom3_decode.decode_section_bytes (opt-in via
  x11_rescue_accel=True). Serial fallback: workers=1.
"""
from __future__ import annotations

import pathlib
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Path helper (called from worker subprocesses via spawn)
# ---------------------------------------------------------------------------
def _ensure_path():
    _HERE = pathlib.Path(__file__).resolve().parent
    ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
    for p in (ROOT / "src",
              ROOT / "tests" / "e2e",
              ROOT / "experiments" / "deepdive2",
              ROOT / "experiments" / "capacity",
              _HERE,
              _HERE / "doom_ship"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    # Force THIS tree's tape_v2 (and doom_ship) to the very front so spawned
    # workers import the worktree's m10_decode / inband_crc, not a main-repo
    # copy that analyze_master2 may have promoted ahead of us.
    for p in (_HERE, _HERE / "doom_ship"):
        s = str(p)
        if s in sys.path:
            sys.path.remove(s)
        sys.path.insert(0, s)


# ===========================================================================
# r-c worker: RS-decode one chunk of failing codewords
# ===========================================================================

def _ladder_chunk_worker(args):
    """Standalone worker for _parallel_erasure_ladder (r-c phase).

    Processes a contiguous chunk of failing codeword indices.  For each
    codeword i in the chunk, tries (set, branch) combinations in the same
    order as the serial _erasure_ladder loop, returning the first
    CRC32-passing decoding.

    Arguments (all pickle-safe):
        cw_chunk      list[int]  — codeword indices to process
        branch_rows   list[(name:str, rows:list[bytes])]
                      rows[i] is the rs_n-byte row for codeword i
        rs_n, rs_k    int — RS code parameters
        crc_table     list[int] — per-codeword CRC32 targets
        positions_cw  list[list[list[int]]] — positions_cw[i][c] = byte
                      positions in codeword i that belong to carrier c
                      (only the entries for i in cw_chunk are used)
        sets_ser      list[list[int]] — carrier sets to try, in order
        max_per_cw    int — per-codeword trial cap

    Returns:
        results       dict[int, tuple] — cw_idx → (msg, bname, carriers,
                      n_erased, n_trials)
        n_rs          int — RS decode attempts made
        n_crc         int — CRC checks performed
        n_rej         int — CRC rejections
    """
    _ensure_path()
    try:
        from rs_backend import RSCodec, ReedSolomonError
    except ImportError:
        import importlib
        importlib.invalidate_caches()
        from rs_backend import RSCodec, ReedSolomonError  # type: ignore
    import inband_crc as ib

    # Backward-compatible unpack: callers built before the inband-CRC stack
    # pass an 8-tuple (external crc_table only); the inband flag defaults to
    # False so the non-inband acceptance path is byte-identical.
    (cw_chunk, branch_rows, rs_n, rs_k,
     crc_table, positions_cw, sets_ser, max_per_cw) = args[:8]
    inband = args[8] if len(args) > 8 else False

    nk = rs_n - rs_k
    rsc = RSCodec(nk)
    results: dict[int, Any] = {}
    n_rs = n_crc = n_rej = 0

    for i in cw_chunk:
        pos_i = positions_cw[i]  # list of P sub-lists
        n_tr = 0
        recovered = False

        for s in sets_ser:
            if recovered:
                break
            # Union byte positions for carriers in set s
            epos_set: set[int] = set()
            for c in s:
                epos_set.update(pos_i[c])
            epos = sorted(epos_set)
            if len(epos) > nk:
                continue  # infeasible: skip, same as serial

            for bname, rows_list in branch_rows:
                if n_tr >= max_per_cw:
                    break
                n_tr += 1
                n_rs += 1
                row = bytearray(rows_list[i])
                try:
                    dec = (rsc.decode(row, erase_pos=epos)[0] if epos
                           else rsc.decode(row)[0])
                    msg = bytes(dec)
                except Exception:
                    continue
                n_crc += 1
                if inband:
                    # self-describing per-codeword CRC: verify the in-band CRC
                    # (no external crc_table for inband manifests).
                    if not ib.accept_message(msg)[0]:
                        n_rej += 1
                        continue
                elif i < len(crc_table) and (
                        zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
                    n_rej += 1
                    continue
                results[i] = (msg, bname, list(s), len(epos), n_tr)
                recovered = True
                break

    return results, n_rs, n_crc, n_rej


# ===========================================================================
# r-b worker: demod + RS for one (geo, base) sweep pair
# ===========================================================================

def _sweep_pair_worker(args):
    """Standalone worker for _parallel_sweep (r-b phase).

    Runs _d2x_shift_branches for one (geo, base) pair and RS-decodes
    all resulting branches against `still_failing` codeword indices.

    Returns:
        branch_results  list[(bn, msgs, mat_bytes)]
            bn         branch name
            msgs       list[bytes|None] length n_cw
            mat_bytes  bytes: (n_cw, rs_n) uint8 matrix serialised
        brec            dict from _d2x_shift_branches
        ld              ledger-delta dict {rs_attempts, crc_checks, …}
    """
    (audio_bytes, audio_shape, audio_dtype_str,
     align, sec, geo, base, still_failing, meta, crc_table) = args

    _ensure_path()
    import numpy as _np
    import m10_decode as _m10
    import x11_d2x_erasure as _xd
    from x10_a_fec_gmd_erasure import _rx_mat

    audio_nom = _np.frombuffer(audio_bytes, dtype=_np.dtype(audio_dtype_str)
                                ).reshape(audio_shape)

    inband = sec.get("crc_mode") == "inband"
    branches, brec = _xd._d2x_shift_branches(audio_nom, align, sec,
                                              geo, base, verbose=False)
    ld = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
    branch_results = []

    for bn, frames in branches.items():
        mat = _rx_mat(frames, meta)
        local_ld = {"rs_attempts": 0, "crc_checks": 0,
                    "crc_rejects": 0, "crc_accepts": 0}
        _ok, msgs = _m10._per_cw_decode(mat, meta, crc_table, local_ld,
                                         only_cw=still_failing, inband=inband)
        for k in ld:
            ld[k] += local_ld[k]
        branch_results.append((bn, msgs, bytes(mat)))

    return branch_results, brec, ld


# ===========================================================================
# parallel r-c: erasure ladder
# ===========================================================================

def _parallel_erasure_ladder(sec, meta, crc, branch_mats, union_msgs,
                              union_src, rank, ledger, *,
                              workers: int = 8, verbose: bool = True,
                              inband: bool = False):
    """Parallel drop-in for m10._erasure_ladder (fill-only, byte-identical).

    Splits failing codewords across `workers` processes.  Each worker finds
    the first (set, branch) success per codeword (same iteration order as
    serial).  Results merged by codeword index (order irrelevant: independent).

    Parity proof:
      Serial: for each codeword i, returns the first (s, bname) s.t.
              RS+CRC passes, in the pre-registered (sets, branch_mats) order.
      Parallel: each worker gets a slice of failing codewords and runs the
              identical (sets, branch_mats) loop for each codeword in its
              slice → same first-success per codeword.
    """
    _ensure_path()
    import m10_decode as _m10
    from x10_a_fec_gmd_erasure import carrier_class_map

    n_cw = meta["n_codewords"]
    nk = meta["rs_n"] - meta["rs_k"]
    failed = [i for i in range(n_cw) if union_msgs[i] is None]
    rec = {"target_cws": list(failed), "accepted": [], "trials": 0,
           "skipped_sets_infeasible": 0,
           "branches": [m[0] for m in branch_mats]}
    if not failed:
        return rec

    P = len(_m10._tx_scheme(sec).data_idx)
    positions, _ = carrier_class_map(meta, P)
    top = [c for c in rank if c < P][:_m10.TOP_RANKED]
    sets = ([(c,) for c in top]
            + [(top[a], top[b]) for a in range(len(top))
               for b in range(a + 1, len(top))]
            + [tuple(top[x] for x in range(len(top)) if x != skip)
               for skip in range(len(top) - 1, -1, -1)])
    sets_ser = [list(s) for s in sets]

    # Serialise positions as a list indexed by codeword then carrier.
    # positions[i][c] = list of byte positions in codeword i for carrier c.
    positions_cw = [[list(positions[i][c]) for c in range(P)]
                    for i in range(n_cw)]

    # Serialise branch matrices as list of per-codeword bytes rows.
    branch_rows = [(bname, [bytes(mat[i]) for i in range(n_cw)])
                   for bname, mat in branch_mats]

    t0 = time.perf_counter()
    n_w = 1 if workers <= 1 else min(workers, len(failed))
    chunk_size = max(1, (len(failed) + n_w - 1) // n_w)
    chunks = [failed[i:i + chunk_size]
              for i in range(0, len(failed), chunk_size)]

    all_results: dict[int, Any] = {}

    # inband manifests have no external crc table (crc is None); pass None.
    crc_for_worker = None if (inband or crc is None) else list(crc)
    chunk_args_list = [
        (chunk, branch_rows, meta["rs_n"], meta["rs_k"],
         crc_for_worker, positions_cw, sets_ser, _m10.MAX_PATTERNS_PER_CW,
         inband)
        for chunk in chunks
    ]

    if n_w <= 1:
        for ca in chunk_args_list:
            cr, nr, nc, nrj = _ladder_chunk_worker(ca)
            all_results.update(cr)
            ledger["rs_attempts"] += nr
            ledger["crc_checks"] += nc
            ledger["crc_rejects"] += nrj
            ledger["crc_accepts"] += len(cr)
    else:
        with ProcessPoolExecutor(max_workers=n_w) as executor:
            futures = [executor.submit(_ladder_chunk_worker, ca)
                       for ca in chunk_args_list]
            for fut in futures:
                cr, nr, nc, nrj = fut.result()
                all_results.update(cr)
                ledger["rs_attempts"] += nr
                ledger["crc_checks"] += nc
                ledger["crc_rejects"] += nrj
                ledger["crc_accepts"] += len(cr)

    # Apply results fill-only (codeword order irrelevant — all independent)
    for i in sorted(all_results):       # deterministic order for audit
        if union_msgs[i] is None:       # still unfilled (should always be true)
            msg, bname, carriers, n_erased, n_tr = all_results[i]
            union_msgs[i] = msg
            union_src[i] = (f"ladder:{bname}:erase{carriers}"
                            f"(e={n_erased})")
            rec["accepted"].append({
                "cw": int(i), "branch": bname,
                "erased_carriers": carriers,
                "n_erased": n_erased,
                "trials_used": n_tr,
            })

    rec["trials"] = ledger["rs_attempts"]   # cumulative (caller can diff)
    elapsed = time.perf_counter() - t0
    if verbose:
        print(f"    [ladder_accel {sec['name']}] recovered "
              f"{len(rec['accepted'])}/{len(failed)} "
              f"({ledger['rs_attempts']} RS attempts, {elapsed:.1f}s, "
              f"{n_w}w)", flush=True)
    return rec


# ===========================================================================
# parallel r-b: shift-window sweep
# ===========================================================================

def _parallel_sweep(audio_nom, align, sec, union_msgs, union_src, pool,
                    ledger, *, workers: int = 4, verbose: bool = True):
    """Parallel shift-window sweep (r-b phase).

    Runs all 4 (geo, base) pairs concurrently.  Branch results are applied
    in original geo×base×branch order for deterministic fill-only union.

    Returns (sweep_rec, pool_additions) — new (bn, mat) tuples to add to pool.

    Parity proof:
      For each (geo, base) pair, the worker returns branches in the same
      insertion order as _d2x_shift_branches (Python dict, insertion-ordered).
      We apply branches across pairs in the original RESCUE_GEOS × RESCUE_BASES
      order.  Fill-only union with the same application order = same first-
      source-per-codeword as serial.
    """
    _ensure_path()
    import x11_d2x_erasure as _xd
    import m10_decode as _m10

    meta = sec["meta"]
    inband = sec.get("crc_mode") == "inband"
    crc = sec.get("crc32_codewords")
    n_cw = meta["n_codewords"]

    still = [i for i in range(n_cw) if union_msgs[i] is None]
    if not still:
        return {}, []

    audio_bytes = audio_nom.tobytes()       # raw bytes of float32 samples
    audio_shape = audio_nom.shape
    audio_dtype_str = audio_nom.dtype.str

    crc_for_worker = None if (inband or crc is None) else list(crc)
    tasks = [(geo, base) for geo in _xd.RESCUE_GEOS for base in _xd.RESCUE_BASES]
    worker_args = [
        (audio_bytes, audio_shape, audio_dtype_str,
         align, sec, geo, base, still, meta, crc_for_worker)
        for geo, base in tasks
    ]

    t0 = time.perf_counter()
    n_w = 1 if workers <= 1 else min(workers, len(tasks))

    if n_w <= 1:
        ordered = [_sweep_pair_worker(wa) for wa in worker_args]
    else:
        with ProcessPoolExecutor(max_workers=n_w) as executor:
            futs = [executor.submit(_sweep_pair_worker, wa) for wa in worker_args]
            ordered = [f.result() for f in futs]

    sweep_rec = {}
    pool_new = []
    rs_n = meta["rs_n"]

    for (geo, base), (branch_results, brec, ld) in zip(tasks, ordered):
        for k in ledger:
            ledger[k] += ld.get(k, 0)
        sweep_rec[f"{geo}_{base}"] = {"argmin_vec": brec["argmin_vec"]}

        for bn, msgs, mat_bytes in branch_results:
            # fill-only union in branch order
            _m10._union_fill(union_msgs, union_src, msgs, bn)
            mat = np.frombuffer(mat_bytes, dtype=np.uint8).reshape(n_cw, rs_n).copy()
            pool_new.append((bn, mat))

    elapsed = time.perf_counter() - t0
    still_now = sum(1 for m in union_msgs if m is None)
    if verbose:
        print(f"    [sweep_accel] r-b {elapsed:.1f}s ({n_w}w) "
              f"still_failing={still_now}/{n_cw}", flush=True)
    return sweep_rec, pool_new


# ===========================================================================
# Full parallel rescue (bytes-returning drop-in for x11_rescue_section_bytes)
# ===========================================================================

def x11_rescue_section_bytes_accel(
        audio_nom, sec, align, ledger, stock_row, *,
        sweep_workers: int = 4,
        ladder_workers: int = 8,
        verbose: bool = True):
    """Parallel drop-in for m10doom3_decode.x11_rescue_section_bytes.

    Same r-a → r-b → r-c structure, same fill-only CRC32-guarded semantics.
    Returns (rec_dict, assembled_bytes) — identical interface and parity.

    sweep_workers: processes for r-b (one per geo×base pair; max useful=4).
    ladder_workers: processes for r-c (chunks of failing codewords; max ~16).
    """
    _ensure_path()
    import m10_decode as _m10
    import m9_decode as _m9d
    import x11_d2x_erasure as _xd
    import inband_crc as ib
    from x10_a_fec_gmd_erasure import _rx_mat

    t0 = time.perf_counter()
    meta = sec["meta"]
    inband = sec.get("crc_mode") == "inband"
    crc = sec.get("crc32_codewords")
    n_cw = meta["n_codewords"]

    _TAPE_V2 = pathlib.Path(__file__).resolve().parent
    expected_packed = (_TAPE_V2 / sec["payload_sidecar"]).read_bytes()
    k_rs = meta["rs_k"]
    if inband:
        truth_msgs = ib.frame_payload(expected_packed, k_rs)
    else:
        padded = expected_packed + bytes((-len(expected_packed)) % k_rs)
        truth_msgs = [padded[i * k_rs:(i + 1) * k_rs] for i in range(n_cw)]

    union_msgs: list[bytes | None] = [None] * n_cw
    union_src: list[str | None] = [None] * n_cw
    pool: list[tuple[str, np.ndarray]] = []

    # ---- r-a: replicate stock pass-1 union (serial — same as x11_rescue) ---
    for label, sch_rx, fe in _m10._frontends_for(sec):
        rx, _d = _m9d._demod_section_frames(audio_nom, sec, align, sch_rx, fe)
        mat = _rx_mat(rx, meta)
        _ok, msgs = _m10._per_cw_decode(mat, meta, crc, ledger, inband=inband)
        _m10._union_fill(union_msgs, union_src, msgs, label)
        pool.append((label, mat))
    failed_p1 = [i for i in range(n_cw) if union_msgs[i] is None]
    fidelity = (stock_row.get("stock_ladder_targets") is None
                or failed_p1 == stock_row["stock_ladder_targets"])
    if verbose:
        print(f"    [x11_accel {sec['name']}] pass1 failed={len(failed_p1)} "
              f"fidelity={fidelity}", flush=True)

    # ---- r-b: parallel shift-window sweep ----------------------------------
    sweep_rec, pool_new = _parallel_sweep(
        audio_nom, align, sec, union_msgs, union_src, pool, ledger,
        workers=sweep_workers, verbose=verbose)
    pool.extend(pool_new)
    failed_p2 = [i for i in range(n_cw) if union_msgs[i] is None]
    if verbose:
        print(f"    [x11_accel {sec['name']}] after sweep failed={len(failed_p2)} "
              f"(sweep filled {len(failed_p1) - len(failed_p2)})", flush=True)

    # ---- r-c: parallel erasure ladder --------------------------------------
    ladder_rec = None
    rank = disp = None
    if failed_p2:
        rank, disp = _m10._rank_carriers(audio_nom, align, sec, verbose=verbose)
        ranked_pool = sorted(
            pool, key=lambda bm: _xd._consensus_distance(bm[1], union_msgs, meta))
        branch_mats = [(bn, mat) for bn, mat in ranked_pool[:_m10.N_LADDER_BRANCHES]]
        ladder_rec = _parallel_erasure_ladder(
            sec, meta, crc, branch_mats, union_msgs, union_src, rank, ledger,
            workers=ladder_workers, verbose=verbose, inband=inband)
    failed_final = [i for i in range(n_cw) if union_msgs[i] is None]

    # ---- audit (same as x11_rescue_section_bytes) --------------------------
    if inband:
        # strip each codeword's in-band CRC then reassemble via the in-band
        # header -- the result IS the original payload bytes (self-described).
        data_chunks = [None if m is None else m[:-ib.CRC_BYTES]
                       for m in union_msgs]
        body, _hdr = ib.reassemble(data_chunks, k_rs)
        assembled = body if body is not None else b""
    else:
        assembled = _m10._assemble(meta, union_msgs)
    byte_exact = assembled == expected_packed
    misc = sum(1 for i in range(n_cw)
               if union_msgs[i] is not None and union_msgs[i] != truth_msgs[i])

    rec = {
        "name": sec["name"],
        "stock_failed_idx": stock_row.get("failed_idx"),
        "stock_cw_failed": stock_row["cw_failed"],
        "pass1_failed_idx": failed_p1,
        "pass1_fidelity_vs_stock_targets": bool(fidelity),
        "after_sweep_failed_idx": failed_p2,
        "final_failed_idx": failed_final,
        "cw_failed_final": len(failed_final),
        "byte_exact": bool(byte_exact),
        "miscorrected": int(misc),
        "rescued": bool(not failed_final and byte_exact),
        "filled_by_sweep": [
            {"cw": i, "source": union_src[i]} for i in range(n_cw)
            if union_src[i] and union_src[i].startswith("d2xsw_")],
        "filled_by_ladder": [
            {"cw": i, "source": union_src[i]} for i in range(n_cw)
            if union_src[i] and union_src[i].startswith("ladder:")],
        "ladder": ladder_rec,
        "carrier_rank_worst_first": rank,
        "carrier_dispersion_deg": disp,
        "sweep_argmin": sweep_rec,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "accel": {"sweep_workers": sweep_workers, "ladder_workers": ladder_workers},
    }
    if verbose:
        print(f"    [x11_accel {sec['name']}] FINAL failed={len(failed_final)} "
              f"byte_exact={byte_exact} misc={misc} ({rec['elapsed_s']}s)",
              flush=True)
    return rec, assembled
