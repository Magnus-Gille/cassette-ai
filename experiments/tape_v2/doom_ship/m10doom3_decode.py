"""m10doom3_decode.py -- recover the v3 DOOM HTML from a captured (or clean) WAV.

The receive side of the DOOM v3 ship tape (m10doom3_master.py). The section is
a dense2x_drop r6 rung, so the receiver is the X11 SHIPPING RECEIVER path:

  stage A  m10_decode._decode_section VERBATIM (frozen composed pipeline:
           the 8-branch d2x front-end bank {hann256_skip0, rect128_skip64} x
           {ema .5/.6/.7/.8, pll 30/45} ensemble union, CRC32-per-codeword
           guard, carrier-class errors-and-erasures ladder). On tape10 this
           landed r6 at 0/72 failed codewords on the FIRST branch.
  stage B  ONLY IF stage A leaves CRC-failing codewords: the gated x11 d2x
           rescue (shift-window sweep + frozen erasure ladder over the
           enlarged pool). x11_decode.py's wrapper cannot be reused as-is
           because xd.x11_rescue_section assembles bytes internally but
           returns only an audit dict (no payload bytes) -- so this module
           carries a BYTES-RETURNING mirror of that loop, built ONLY from
           read-only imports of the frozen machinery (m10._frontends_for,
           m9d._demod_section_frames, xd._rx_mat, m10._per_cw_decode,
           m10._union_fill, xd._d2x_shift_branches, xd.RESCUE_GEOS/BASES,
           m10._rank_carriers, m10._erasure_ladder, xd._consensus_distance,
           m10.N_LADDER_BRANCHES, m10._assemble). Identical decision rules,
           identical strictly-additive CRC32-guarded fill-only discipline;
           the rescue outcome is adopted ONLY if strictly better than stage A.

Output: doom_ship/doom3_decoded.html + results JSON; the verdict compares
sha256 of the decoded HTML against the manifest html_sha256 AND against
payloads/doom/dist/doom_cassette_v3.html when present on disk.

Usage:
    python3 experiments/tape_v2/doom_ship/m10doom3_decode.py <capture.wav>
        [--out-tag TAG] [--no-cache]
(default recording: the clean v3 master, i.e. the blocking no-channel
self-check -- must land 0 failed codewords and BYTE-EXACT with the rescue
machinery armed.)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2/doom_ship
TAPE_V2 = _HERE.parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    TAPE_V2,
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2  # noqa: E402
import inband_crc as ib  # noqa: E402 (self-describing per-codeword CRC framing)
import m3_codec as codec  # noqa: E402
import m9_decode as m9d  # noqa: E402  (read-only)
import m10_decode as m10  # noqa: E402  (FROZEN, read-only)
import x11_d2x_erasure as xd  # noqa: E402  (gated x11, read-only)
from m10doom3_master import (  # noqa: E402
    unpack_doom, MANIFEST_PATH, WAV_PATH,
)

SR = codec.FS
RESULTS_DIR = _HERE / "results"
CAP_DIR = TAPE_V2 / "captures"            # gitignored; big caches live here
DECODED_PATH = _HERE / "doom3_decoded.html"
D2X_KINDS = ("dense2x", "dense2x_drop")
FA_BUDGET = 1e-4


def _new_ledger():
    return {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}


# ===========================================================================
# capture loading (x11_decode pattern; m10doom3-prefixed caches in captures/)
# ===========================================================================
def _load_capture(recording_path, manifest, tag, use_cache=True):
    nom_cache = CAP_DIR / f"m10doom3_nom_{tag}.npy"
    sync_cache = RESULTS_DIR / f"m10doom3_sync_{tag}.json"
    if use_cache and nom_cache.exists() and sync_cache.exists():
        audio_nom = np.load(nom_cache, mmap_mode="r")
        sync = json.loads(sync_cache.read_text())
        return audio_nom, sync, True
    audio, sr = sf.read(str(recording_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)
    sync_full = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync_full["audio_nominal"]
    sync = {k: (float(v) if isinstance(v, (np.floating, float))
                else int(v) if isinstance(v, (np.integer, int)) else v)
            for k, v in sync_full.items() if k != "audio_nominal"}
    sync["align"] = int(sync_full["chirp0_nominal"]) - int(manifest["tx_chirp0"])
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync_full)
        sync["sounder"] = {k: v for k, v in (sounder or {}).items()
                           if k in ("flutter_wrms_pct", "snr_db_median",
                                    "noise_floor_dbfs", "speed_refine")}
    except Exception as exc:
        sync["sounder"] = {"error": str(exc)}
    if use_cache:
        CAP_DIR.mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        np.save(nom_cache, np.asarray(audio_nom, np.float32))
        sync_cache.write_text(json.dumps(sync, indent=2, default=float))
    return audio_nom, sync, False


# ===========================================================================
# BYTES-RETURNING mirror of xd.x11_rescue_section (frozen machinery, read-only
# imports; same pre-registered order r-a -> r-b -> r-c, same fill-only rules).
# ===========================================================================
def x11_rescue_section_bytes(audio_nom, sec, align, ledger, stock_row,
                             verbose=True):
    t0 = time.time()
    meta = sec["meta"]
    inband = sec.get("crc_mode") == "inband"
    crc = sec.get("crc32_codewords")
    n_cw = meta["n_codewords"]
    expected_packed = (TAPE_V2 / sec["payload_sidecar"]).read_bytes()
    k = meta["rs_k"]
    if inband:
        truth_msgs = ib.frame_payload(expected_packed, k)
    else:
        padded = expected_packed + bytes((-len(expected_packed)) % k)
        truth_msgs = [padded[i * k:(i + 1) * k] for i in range(n_cw)]

    union_msgs: list[bytes | None] = [None] * n_cw
    union_src: list[str | None] = [None] * n_cw
    pool: list[tuple[str, np.ndarray]] = []

    # ---- r-a: replicate the stock pass-1 union ---------------------------
    for label, sch_rx, fe in m10._frontends_for(sec):
        rx, _d = m9d._demod_section_frames(audio_nom, sec, align, sch_rx, fe)
        mat = xd._rx_mat(rx, meta)
        _ok, msgs = m10._per_cw_decode(mat, meta, crc, ledger, inband=inband)
        m10._union_fill(union_msgs, union_src, msgs, label)
        pool.append((label, mat))
    failed_p1 = [i for i in range(n_cw) if union_msgs[i] is None]
    fidelity = (stock_row.get("stock_ladder_targets") is None
                or failed_p1 == stock_row["stock_ladder_targets"])
    if verbose:
        print(f"    [x11b {sec['name']}] pass1 failed={len(failed_p1)} "
              f"fidelity_vs_stock={fidelity}", flush=True)

    # ---- r-b: d2x shift-window sweep (fill-only on failing cw) -----------
    sweep_rec = {}
    for geo in xd.RESCUE_GEOS:
        for base in xd.RESCUE_BASES:
            still = [i for i in range(n_cw) if union_msgs[i] is None]
            if not still:
                break
            branches, brec = xd._d2x_shift_branches(audio_nom, align, sec,
                                                    geo, base)
            sweep_rec[f"{geo}_{base}"] = {"argmin_vec": brec["argmin_vec"]}
            for bn, frames in branches.items():
                still = [i for i in range(n_cw) if union_msgs[i] is None]
                if not still:
                    break
                mat = xd._rx_mat(frames, meta)
                _ok, msgs = m10._per_cw_decode(mat, meta, crc, ledger,
                                               only_cw=still, inband=inband)
                m10._union_fill(union_msgs, union_src, msgs, bn)
                pool.append((bn, mat))
    failed_p2 = [i for i in range(n_cw) if union_msgs[i] is None]
    if verbose:
        print(f"    [x11b {sec['name']}] after sweep failed={len(failed_p2)} "
              f"(sweep filled {len(failed_p1) - len(failed_p2)})", flush=True)

    # ---- r-c: frozen carrier-class erasure ladder over the enlarged pool --
    ladder_rec = None
    rank = disp = None
    if failed_p2:
        rank, disp = m10._rank_carriers(audio_nom, align, sec, verbose=verbose)
        ranked_pool = sorted(
            pool, key=lambda bm: xd._consensus_distance(bm[1], union_msgs, meta))
        branch_mats = [(bn, mat) for bn, mat in
                       ranked_pool[:m10.N_LADDER_BRANCHES]]
        ladder_rec = m10._erasure_ladder(sec, meta, crc, branch_mats,
                                         union_msgs, union_src, rank, ledger,
                                         verbose=verbose, inband=inband)
    failed_final = [i for i in range(n_cw) if union_msgs[i] is None]

    # ---- audit + ASSEMBLED BYTES (the bit x11_decode's wrapper drops) -----
    if inband:
        data_chunks = [None if m is None else m[:-ib.CRC_BYTES]
                       for m in union_msgs]
        body, _hdr = ib.reassemble(data_chunks, k)
        assembled = body if body is not None else b""
    else:
        assembled = m10._assemble(meta, union_msgs)
    byte_exact = assembled == expected_packed
    misc = sum(1 for i in range(n_cw) if union_msgs[i] is not None
               and union_msgs[i] != truth_msgs[i])
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
        "elapsed_s": round(time.time() - t0, 1),
    }
    if verbose:
        print(f"    [x11b {sec['name']}] FINAL failed={len(failed_final)} "
              f"byte_exact={byte_exact} misc={misc} ({rec['elapsed_s']}s)",
              flush=True)
    return rec, assembled


# ===========================================================================
# the per-section v3 path: frozen stage A, gated bytes-returning stage B
# (mirror of x11_decode._decode_section_x11 -- same adoption rule)
# ===========================================================================
def decode_section_bytes(audio_nom, sec, align, ledger, *, rescue=True,
                         x11_rescue=True, verbose=True,
                         accel_workers: int | None = None):
    """Decode one d2x section (stage A + gated x11 rescue).

    accel_workers: if set to an integer >= 2, use the parallel rescue
        (rescue_accel.x11_rescue_section_bytes_accel) instead of the serial
        x11_rescue_section_bytes.  The parallel rescue is byte-identical to
        the serial version (parity proven in test_rescue_accel.py).
        Speedup on large sections (many failing codewords):
          r-b sweep: ~2x (4 geo×base workers in parallel)
          r-c ladder: ~N/2x where N = accel_workers (RS decode in parallel)
        Recommended: accel_workers = os.cpu_count() or 8.
        Default (None): serial path.
    """
    r, assembled = m10._decode_section(audio_nom, sec, align, ledger,
                                       rescue=rescue, verbose=verbose)
    r["x11_rescue"] = None
    r["x11_rescued"] = False
    r["decoder_stage"] = "m10_stock"
    stock_failed = int(r["rs_codewords_failed"])
    if x11_rescue and stock_failed > 0 and sec["kind"] in D2X_KINDS:
        ladder = r.get("ladder") or {}
        targets = ladder.get("target_cws")
        accepted = {a["cw"] for a in (ladder.get("accepted") or [])}
        stock_row = {
            "name": sec["name"],
            "cw_failed": stock_failed,
            "stock_ladder_targets": targets,
            "failed_idx": ([i for i in targets if i not in accepted]
                           if targets is not None else None),
        }
        use_accel = (accel_workers is not None and accel_workers >= 2)
        if verbose:
            mode = (f"parallel (accel_workers={accel_workers})"
                    if use_accel else "serial bytes-returning mirror")
            print(f"    [m10doom3 {sec['name']}] stage A left "
                  f"{stock_failed} failed cw -> arming x11 d2x rescue "
                  f"({mode})", flush=True)
        if use_accel:
            import sys as _sys
            import pathlib as _pathlib
            _here = _pathlib.Path(__file__).resolve().parent.parent
            if str(_here) not in _sys.path:
                _sys.path.insert(0, str(_here))
            import rescue_accel as _ra
            # Sweep uses 4 workers (one per geo×base pair, max useful = 4)
            sweep_w = min(4, accel_workers)
            ladder_w = accel_workers
            rec, assembled_b = _ra.x11_rescue_section_bytes_accel(
                audio_nom, sec, align, ledger, stock_row,
                sweep_workers=sweep_w, ladder_workers=ladder_w,
                verbose=verbose)
        else:
            rec, assembled_b = x11_rescue_section_bytes(audio_nom, sec, align,
                                                        ledger, stock_row,
                                                        verbose=verbose)
        r["x11_rescue"] = rec
        if int(rec["cw_failed_final"]) < stock_failed:
            # strictly better -> adopt (never-worse-than-m10 guarantee)
            r["decoder_stage"] = "x11_rescue"
            r["x11_rescued"] = bool(rec["cw_failed_final"] == 0
                                    and rec["byte_exact"])
            r["rs_codewords_failed"] = int(rec["cw_failed_final"])
            r["byte_exact"] = bool(rec["byte_exact"])
            r["miscorrected_cw"] = int(rec["miscorrected"])
            r["x11_filled_by_sweep"] = len(rec["filled_by_sweep"])
            r["x11_filled_by_ladder"] = len(rec["filled_by_ladder"])
            assembled = assembled_b
    return r, assembled


# ===========================================================================
# capture-level driver for the ship tape
# ===========================================================================
def decode(recording_path: str, out_tag: str | None = None,
           manifest_path: pathlib.Path | str | None = None,
           rescue: bool = True, x11_rescue: bool = True,
           verbose: bool = True, use_cache: bool = True,
           accel_workers: int | None = None) -> dict:
    """Decode the DOOM ship tape.

    accel_workers: pass through to decode_section_bytes → parallel rescue.
        None = serial (default).  Set to os.cpu_count() or 8 to speed up
        hard captures where the x11 rescue takes many minutes.
    """
    mpath = pathlib.Path(manifest_path) if manifest_path else MANIFEST_PATH
    manifest = json.loads(mpath.read_text())
    sec = manifest["ws_payloads"][0]
    tag = out_tag or pathlib.Path(recording_path).stem
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    ledger = _new_ledger()
    audio_nom, sync, cached = _load_capture(recording_path, manifest, tag,
                                            use_cache)
    align = int(sync["align"])
    if verbose:
        print(f"[m10doom3_decode] {recording_path} (manifest={mpath.name}, "
              f"sync_cached={cached})")
        print(f"  clock {sync.get('speed', 0):.5f}x  align {align:+d}  "
              f"sounder {sync.get('sounder')}", flush=True)

    r, assembled = decode_section_bytes(audio_nom, sec, align, ledger,
                                        rescue=rescue, x11_rescue=x11_rescue,
                                        verbose=verbose,
                                        accel_workers=accel_workers)

    # ---- unpack + integrity vs the shipped artifact ----
    pack = sec["pack"]
    unpack_ok = orig_exact = False
    recovered_orig = b""
    try:
        recovered_orig = unpack_doom(assembled)
        unpack_ok = True
        sha_o = hashlib.sha256(recovered_orig).hexdigest()
        orig_exact = (sha_o == pack["sha256_orig"]
                      and len(recovered_orig) == pack["orig_len"]
                      and sha_o == manifest.get("html_sha256"))
    except Exception as exc:
        r["unpack_error"] = str(exc)

    DECODED_PATH.write_bytes(recovered_orig)

    # independent check against the dist artifact, when it exists on disk
    dist = pathlib.Path(manifest.get("html_path", ""))
    dist_match = None
    if dist.exists():
        dist_match = (hashlib.sha256(dist.read_bytes()).hexdigest()
                      == hashlib.sha256(recovered_orig).hexdigest())

    payload_seconds = (sec["section_end"] - sec["section_start"]) / SR
    net_bps = sec["projected_net_bps"]
    eff_bps = pack["orig_len"] * 8 / payload_seconds
    fa_bound = ledger["crc_checks"] * 2.0 ** -32

    r.update({
        "unpack_ok": unpack_ok,
        "orig_byte_exact": bool(orig_exact),
        "dist_file_match": dist_match,
        "pack_algo": pack["algo"],
        "orig_len": pack["orig_len"],
        "packed_len": pack["packed_len"],
        "effective_bps": eff_bps,
    })

    verdict = "BYTE-EXACT" if orig_exact else "FAIL"
    if verbose:
        print(f"  section {sec['phy']} RS({sec['meta']['rs_n']},"
              f"{sec['meta']['rs_k']}) FB={sec['meta']['frame_bytes']}: "
              f"cw failed {r['rs_codewords_failed']}/{r['n_codewords']}, "
              f"stage={r['decoder_stage']}, front-end {r.get('front_end_used')}")
        print(f"  packed byte-exact: {r['byte_exact']}   unpack: {unpack_ok}   "
              f"orig sha256 match: {orig_exact}"
              + (f"   dist file match: {dist_match}"
                 if dist_match is not None else ""))
        print(f"  decoded HTML -> {DECODED_PATH} ({len(recovered_orig)} B)")
        print(f"\n  VERDICT: {verdict}   net {net_bps:.1f} bps (PHY, RS-coded)"
              f"   effective {eff_bps:.1f} bps on the HTML "
              f"({pack['orig_len']} B in {payload_seconds:.1f} s)   "
              f"fa_bound {fa_bound:.2e}")

    out = {
        "recording": str(recording_path),
        "tape": manifest.get("tape", "m10doom3"),
        "decoder": ("m10doom3_decode (m10 stage A + bytes-returning x11 d2x "
                    "rescue, armed)"),
        "verdict": verdict,
        "net_bps": net_bps,
        "effective_bps": eff_bps,
        "payload_seconds": payload_seconds,
        "decoded_html": str(DECODED_PATH),
        "ledger": ledger,
        "false_accept_bound": fa_bound,
        "fa_within_budget": bool(fa_bound < FA_BUDGET),
        "sync": {k: v for k, v in sync.items() if k != "sounder"},
        "sounder": sync.get("sounder"),
        "payload": {k: v for k, v in r.items()
                    if k not in ("branch_records", "per_carrier_ser")}
        | {"branch_records": r.get("branch_records"),
           "per_carrier_ser": r.get("per_carrier_ser")},
    }
    json_path = RESULTS_DIR / f"m10doom3_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=_jsafe))
    if verbose:
        print(f"[m10doom3_decode] wrote {json_path}")
    return out


def _jsafe(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


if __name__ == "__main__":
    import os
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?", default=str(WAV_PATH),
                    help="captured tape-playback WAV (default: the clean v3 "
                         "master = the blocking no-channel self-check)")
    ap.add_argument("--out-tag", default=None)
    ap.add_argument("--manifest", default=None,
                    help="manifest JSON (default: the standard v3 DOOM tape). "
                         "Pass the inband cassette-LLM manifest to decode that tape.")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--accel-workers", type=int, default=None,
                    help="parallel rescue workers (default: serial). "
                         "Set to os.cpu_count() or 8 for hard captures. "
                         "Requires rescue_accel.py in experiments/tape_v2/.")
    args = ap.parse_args()
    res = decode(args.recording, args.out_tag, manifest_path=args.manifest,
                 use_cache=not args.no_cache,
                 accel_workers=args.accel_workers)
    sys.exit(0 if res["verdict"] == "BYTE-EXACT" else 1)
