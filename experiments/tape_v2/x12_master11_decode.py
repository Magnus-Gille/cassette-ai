"""x12_master11_decode.py -- the MASTER11 shipping receiver + regression rig.

STRICTLY-ADDITIVE composition: this is a new x12 file; every imported module
is FROZEN and imported read-only.  Section dispatch by kind:

  dqpsk / dqpsk_dropnull / dense2x / dense2x_drop
      -> x11_decode._decode_section_x11  (the BLESSED x11 receiver verbatim:
         m10 composed stage A -- ensemble union + late-window dc0 +
         carrier-class erasure ladder + d2x rx_window_plan sweep -- plus the
         gated x11 d2x rescue stage B, never-worse-than-m10 by construction)
  dbpsk_drop
      -> x12_regate_decode._decode_section  (the frozen x12 DBPSK sweep:
         ResamplingPLLDemod subclass with the 90-deg decision boundary,
         5 pre-registered front-ends, ERASE_FRACS=(0.0,))
  freqdiff (regression manifests only)
      -> m9_decode._decode_freqdiff_section  (x11 wiring verbatim)

Every CRC32 acceptance is ledgered; cumulative false-accept bound
(crc_checks * 2^-32) must stay < 1e-4.  Tape-pass validity (prereg canary
rule): BOTH canaries -- x12_c0_anchor_2572 AND x12_c1_d2x_4910 -- orig-exact.

Usage (each invocation < 8 min; per-section checkpointing):
    # BLOCKING no-channel self-check of the burn artifact:
    python3 x12_master11_decode.py master11.wav --out-tag selfcheck_nochan
    # a real/sim capture of master11:
    python3 x12_master11_decode.py <capture.wav> [--out-tag t] [--sections a,b]
    # the banked-outcome regression (chunkable), then the comparison report:
    python3 x12_master11_decode.py --regress tape10 [--sections ...]
    python3 x12_master11_decode.py --regress tape9  [--sections ...]
    python3 x12_master11_decode.py --regress compare

Outputs: results/x12_m11_results_<tag>.json (+ _sync_), captures/x12_m11_nom_
<tag>.npy (cache, gitignored), results/x12_m11_regression_report.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                          # noqa: E402
import m3_codec as codec                               # noqa: E402
import m9_decode as m9d                                # noqa: E402 (read-only)
import m10_decode as m10                               # noqa: E402 (FROZEN)
import x11_decode as x11                               # noqa: E402 (BLESSED, read-only)
from x11_decode import _jsafe                          # noqa: E402
from x12_regate_decode import (                        # noqa: E402 (frozen x12 rx)
    _decode_section as _x12_dbpsk_section)
from h9_payload_codec import unpack_payload            # noqa: E402

SR = codec.FS
RESULTS_DIR = _HERE / "results"
CAP_DIR = _HERE / "captures"
DEFAULT_MANIFEST = _HERE / "master11_manifest.json"
MASTER_ID = "master11"
FA_BUDGET = 1e-4
FREQDIFF_KIND = "freqdiff"
DBPSK_KIND = "dbpsk_drop"

COMPOSITION = [
    "dqpsk/dense2x kinds: x11_decode._decode_section_x11 VERBATIM (m10 "
    "composed stage A + gated x11 d2x rescue stage B)",
    "dbpsk_drop kind: x12_regate_decode._decode_section VERBATIM (frozen "
    "90-deg DBPSK sweep, ERASE_FRACS=(0.0,))",
    "freqdiff kind: m9_decode._decode_freqdiff_section (x11 wiring)",
    "merge discipline: strictly-additive CRC32-guarded fill-only throughout",
]

# banked references for the BLOCKING regression (0 regressions required)
REGRESS = {
    "tape10": {"capture": CAP_DIR / "tape10_run1.wav",
               "manifest": "master10_manifest.json",
               "banked": RESULTS_DIR / "x11_decode_results_tape10_run1.json"},
    "tape9": {"capture": CAP_DIR / "tape9_run1.wav",
              "manifest": "master9_manifest.json",
              "banked": RESULTS_DIR / "x11_decode_results_regress_tape9.json"},
}


# ===========================================================================
# capture loading -- x11._load_capture logic with x12-prefixed cache paths
# ===========================================================================
def _load_capture(recording_path, manifest, tag, use_cache=True):
    nom_cache = CAP_DIR / f"x12_m11_nom_{tag}.npy"
    sync_cache = RESULTS_DIR / f"x12_m11_sync_{tag}.json"
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
def decode(recording_path: str, out_tag: str | None = None,
           manifest_path: str | None = None, sections: list[str] | None = None,
           rescue: bool = True, x11_rescue: bool = True, verbose: bool = True,
           use_cache: bool = True) -> dict:
    mpath = _HERE / manifest_path if manifest_path else DEFAULT_MANIFEST
    manifest = json.loads(mpath.read_text())
    if manifest_path is None:
        assert manifest.get("master_id") == MASTER_ID, (
            f"manifest master_id {manifest.get('master_id')!r} != {MASTER_ID!r}"
            " -- refusing to decode against the wrong master")
    tag = out_tag or pathlib.Path(recording_path).stem
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"x12_m11_results_{tag}.json"

    out = (json.loads(json_path.read_text()) if json_path.exists()
           else {"recording": str(recording_path), "tape": manifest.get("tape"),
                 "manifest": str(mpath.name),
                 "decoder": "x12_master11_decode (x11 blessed receiver + "
                            "frozen x12 DBPSK sweep, strictly additive)",
                 "composition": COMPOSITION,
                 "print_authorized": manifest.get("print_authorized"),
                 "ledger": {"rs_attempts": 0, "crc_checks": 0,
                            "crc_rejects": 0, "crc_accepts": 0},
                 "payloads_by_name": {}, "section_order": [
                     s["name"] for s in manifest["ws_payloads"]]})
    ledger = out["ledger"]

    audio_nom, sync, cached = _load_capture(recording_path, manifest, tag,
                                            use_cache)
    out["sync"] = {k: v for k, v in sync.items() if k != "sounder"}
    out["sounder"] = sync.get("sounder")
    align = int(sync["align"])
    if verbose:
        print(f"[x12_m11_decode] {recording_path} (manifest={mpath.name}, "
              f"sync_cached={cached})")
        print(f"  clock {sync.get('speed', 0):.5f}x  align {align:+d}  "
              f"sounder {out['sounder']}", flush=True)

    for sec in manifest["ws_payloads"]:
        if sections and sec["name"] not in sections:
            continue
        if sec.get("skipped"):
            out["payloads_by_name"][sec["name"]] = {
                "name": sec["name"], "kind": sec["kind"], "skipped": True,
                "byte_exact": None}
            continue
        pack = sec["pack"]
        if sec["kind"] == FREQDIFF_KIND:
            sounder_full = None
            try:
                sounder_full = am2.analyze_sounder(audio_nom, manifest, sync)
            except Exception:
                pass
            r, assembled = m9d._decode_freqdiff_section(audio_nom, sec, align,
                                                        sounder_full)
            r["x11_rescue"] = None
            r["x11_rescued"] = False
            r["decoder_stage"] = "freqdiff"
            r.update(_unpack_check(assembled, pack))
        elif sec["kind"] == DBPSK_KIND:
            led2 = {"crc_trials": 0}
            r, recovered_packed = _x12_dbpsk_section(audio_nom, sec, align,
                                                     led2)
            ledger["crc_checks"] += led2["crc_trials"]
            ledger["crc_accepts"] += led2["crc_trials"]   # ledgered as checks
            r["x11_rescue"] = None
            r["x11_rescued"] = False
            r["decoder_stage"] = "x12_dbpsk_sweep"
            r.update(_unpack_check(recovered_packed, pack))
        else:
            r, assembled = x11._decode_section_x11(
                audio_nom, sec, align, ledger, rescue=rescue,
                x11_rescue=x11_rescue, verbose=verbose)
            # ---- unpack + integrity (the x11 wiring VERBATIM) ----
            if r.pop("_x11_orig_exact_override", None) is not None or \
                    r.get("decoder_stage") == "x11_rescue":
                rec = r["x11_rescue"]
                r["unpack_ok"] = bool(rec["orig_exact"])
                r["orig_byte_exact"] = bool(rec["orig_exact"])
                r["crc_check"] = bool(rec["orig_exact"])
            else:
                r.update(_unpack_check(assembled, pack))
        r["effective_bps"] = sec.get("effective_bps")
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        out["payloads_by_name"][sec["name"]] = r
        _checkpoint(out, manifest, ledger, json_path)
        if verbose:
            print(f"  [{r['name']:28s}] cw {r.get('rs_codewords_failed')}/"
                  f"{r.get('n_codewords')} stage={r.get('decoder_stage')} "
                  f"PACK={'YES' if r.get('byte_exact') else 'no'} "
                  f"ORIG={'YES' if r.get('orig_byte_exact') else 'no'} "
                  f"-> checkpointed", flush=True)

    if verbose:
        print(f"[x12_m11_decode] canaries anchor={out.get('anchor_2572_reproved')} "
              f"d2x4910={out.get('d2x_4910_canary_reproved')} "
              f"orig-exact {out['n_orig_exact']}/{out['n_payloads']} "
              f"fa_bound={out['false_accept_bound']:.2e}")
        print(f"[x12_m11_decode] wrote {json_path}")
    return out


def _unpack_check(assembled: bytes, pack: dict) -> dict:
    r = {"unpack_ok": None, "orig_byte_exact": None, "crc_check": None}
    try:
        recovered_orig = unpack_payload(assembled)
        r["unpack_ok"] = True
        sha_o = hashlib.sha256(recovered_orig).hexdigest()
        r["orig_byte_exact"] = (sha_o == pack["sha256_orig"]
                                and len(recovered_orig) == pack["orig_len"])
        r["crc_check"] = r["orig_byte_exact"]
    except Exception as exc:
        r["unpack_ok"] = False
        r["orig_byte_exact"] = False
        r["unpack_error"] = str(exc)
    return r


def _checkpoint(out, manifest, ledger, json_path):
    results = [out["payloads_by_name"][n] for n in out["section_order"]
               if n in out["payloads_by_name"]]
    out["payloads"] = results
    out["n_byte_exact_packed"] = sum(bool(x.get("byte_exact")) for x in results)
    out["n_orig_exact"] = sum(bool(x.get("orig_byte_exact")) for x in results)
    out["n_payloads"] = len(results)
    out["n_x11_rescued"] = sum(bool(x.get("x11_rescued")) for x in results)
    out["miscorrected_total"] = sum(int(x.get("miscorrected_cw") or 0)
                                    for x in results)
    out["false_accept_bound"] = ledger["crc_checks"] * 2.0 ** -32
    out["fa_within_budget"] = bool(out["false_accept_bound"] < FA_BUDGET)
    if manifest.get("master_id") == MASTER_ID:
        def _ok(name):
            r = out["payloads_by_name"].get(name)
            return bool(r and r.get("orig_byte_exact"))
        out["anchor_2572_reproved"] = _ok("x12_c0_anchor_2572")
        out["d2x_4910_canary_reproved"] = _ok("x12_c1_d2x_4910")
        out["tape_pass_valid"] = bool(out["anchor_2572_reproved"]
                                      and out["d2x_4910_canary_reproved"])
    json_path.write_text(json.dumps(out, indent=2, default=_jsafe))


# ===========================================================================
# the BLOCKING no-channel self-check verdict (run on master11.wav itself)
# ===========================================================================
def selfcheck_verdict(res: dict) -> bool:
    ok = (res["n_payloads"] == 3 and res["n_orig_exact"] == 3
          and res["n_byte_exact_packed"] == 3
          and res.get("miscorrected_total", 0) == 0
          and res.get("tape_pass_valid"))
    print(f"[selfcheck_nochan] BLOCKING: orig-exact "
          f"{res['n_orig_exact']}/{res['n_payloads']}, "
          f"misc={res.get('miscorrected_total')}, "
          f"canary_pair={res.get('tape_pass_valid')} -> "
          f"{'PASS' if ok else 'FAIL'}")
    return bool(ok)


# ===========================================================================
# BLOCKING regression: reproduce every banked outcome on tape10_run1 +
# tape9_run1 through THIS receiver stack (0 regressions, 0 miscorrections).
# ===========================================================================
def regress_run(which: str, sections=None) -> dict:
    cfg = REGRESS[which]
    return decode(str(cfg["capture"]), out_tag=f"regress_{which}",
                  manifest_path=cfg["manifest"], sections=sections)


def regress_compare() -> dict:
    report = {"experiment": "x12_master11_decode BLOCKING regression "
                            "(banked outcomes on tape10_run1 + tape9_run1)",
              "decoder": "x12_master11_decode (x11 blessed path for all "
                         "banked kinds; new code touches ONLY dbpsk_drop, "
                         "absent from these manifests)",
              "captures": {}}
    all_ok = True
    for which, cfg in REGRESS.items():
        new_p = RESULTS_DIR / f"x12_m11_results_regress_{which}.json"
        new = json.loads(new_p.read_text())
        ref = json.loads(cfg["banked"].read_text())
        rows, ok_all, n = [], True, 0
        for name in ref["section_order"]:
            rr = ref["payloads_by_name"].get(name)
            r = new["payloads_by_name"].get(name)
            if rr is None:
                continue
            if r is None:
                ok_all = False
                rows.append({"name": name, "missing_in_rerun": True,
                             "matches_banked": False})
                continue
            n += 1
            ok = (bool(r.get("orig_byte_exact")) == bool(rr.get("orig_byte_exact"))
                  and bool(r.get("byte_exact")) == bool(rr.get("byte_exact"))
                  and int(r.get("rs_codewords_failed") or 0)
                  == int(rr.get("rs_codewords_failed") or 0)
                  and int(r.get("miscorrected_cw") or 0)
                  == int(rr.get("miscorrected_cw") or 0))
            ok_all &= ok
            rows.append({"name": name,
                         "banked": {"cw_failed": rr.get("rs_codewords_failed"),
                                    "orig_exact": rr.get("orig_byte_exact"),
                                    "stage": rr.get("decoder_stage")},
                         "rerun": {"cw_failed": r.get("rs_codewords_failed"),
                                   "orig_exact": r.get("orig_byte_exact"),
                                   "stage": r.get("decoder_stage"),
                                   "x11_rescued": r.get("x11_rescued")},
                         "matches_banked": bool(ok)})
        complete = n == len(ref["section_order"])
        report["captures"][which] = {
            "capture": cfg["capture"].name, "banked": cfg["banked"].name,
            "rows": rows, "n_compared": n, "complete": complete,
            "all_match": bool(ok_all and complete),
            "fa_bound_rerun": new.get("false_accept_bound")}
        all_ok &= ok_all and complete
    report["zero_regressions"] = bool(all_ok)
    out_path = RESULTS_DIR / "x12_m11_regression_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=_jsafe))
    print(f"[regress] zero_regressions={report['zero_regressions']} "
          f"-> {out_path.name}")
    for w, c in report["captures"].items():
        print(f"  {w}: all_match={c['all_match']} "
              f"({c['n_compared']} sections, complete={c['complete']})")
    return report


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?")
    ap.add_argument("--out-tag", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--sections", default=None,
                    help="comma-separated section names (chunking)")
    ap.add_argument("--no-x11-rescue", action="store_true",
                    help="stage A only (m9/m10 dress convention)")
    ap.add_argument("--regress", default=None,
                    choices=["tape10", "tape9", "compare"])
    args = ap.parse_args()
    secs = args.sections.split(",") if args.sections else None
    if args.regress == "compare":
        rep = regress_compare()
        sys.exit(0 if rep["zero_regressions"] else 1)
    elif args.regress:
        regress_run(args.regress, sections=secs)
    else:
        assert args.recording, "recording path required"
        res = decode(args.recording, out_tag=args.out_tag,
                     manifest_path=args.manifest, sections=secs,
                     x11_rescue=not args.no_x11_rescue)
        if args.out_tag == "selfcheck_nochan":
            sys.exit(0 if selfcheck_verdict(res) else 1)
