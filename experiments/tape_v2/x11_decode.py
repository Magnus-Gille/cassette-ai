"""x11_decode.py -- the X11 SHIPPING RECEIVER: a thin superset wrapper around
the FROZEN m10_decode composed pipeline, adding the gated x11 d2x rescue path.

This is the decoder to run on the real master10 tape capture (tape10).
m10_decode.py and master10_manifest.json remain frozen blessed burn artifacts;
this module imports them READ-ONLY and changes NOTHING on tape.

Composition (strictly additive; a CRC32-passing codeword is FINAL, rescue
paths are offered ONLY CRC-failing codewords and can never replace one):

  stage A  m10_decode._decode_section VERBATIM (the frozen composed pipeline:
           ensemble union over the widened timing-front-end bank, late-window
           dc0 at N256, carrier-class errors-and-erasures RS retry ladder,
           d2x rx_window_plan sweep).
  stage B  ONLY IF stage A leaves CRC-failing codewords on a dense2x /
           dense2x_drop section: the gated x11 d2x rescue
           (x11_d2x_erasure.x11_rescue_section, read-only import) --
             r-a replicate the stock pass-1 union (fidelity-checked),
             r-b d2x SHIFT-WINDOW sweep {hann256_skip0, rect128_skip64} x
                 {ema0.7, pll30} x shifts (hann +-16/32; rect +-16/32/48)
                 + per-carrier decision-EVM-argmin stitched branches
                 (the proven dc0 late-window mechanism extended to every d2x
                 carrier -- critical for r8, which keeps dc0 @750 Hz),
             r-c the FROZEN carrier-class erasure ladder over the enlarged
                 branch pool, ranked by truth-free consensus byte distance.
           Gate evidence: results/x11_d2x_gate_report.json (gate_met=true,
           G1 23/23 synthetic marginal d2x sections rescued orig-exact across
           aac {off,on} x clk {0,+0.10,+0.17,+0.25}%, 0 miscorrections,
           FA bound 1.03e-5 < 1e-4).
  merge    the wrapper adopts the rescue outcome ONLY if it is strictly
           better (fewer failed codewords) than stage A -- by construction
           x11_decode can never be worse than m10_decode on any section.

Every RS decode attempt and CRC acceptance is ledgered; the cumulative
false-accept bound (crc_checks * 2^-32) is reported and must stay < 1e-4.
Non-d2x sections take the stage-A path UNCHANGED, so all banked m8/m9
outcomes are structurally preserved (proven by the blocking regression gate
below, results/x11_decode_regression_*.json).

Usage (each invocation < 8 min; results checkpoint after every section):
    # the real tape10 capture (the intended use):
    python3 experiments/tape_v2/x11_decode.py experiments/tape_v2/captures/tape10_run1.wav
    # wrapper selfcheck (clean synth + a marginal synth cell that NEEDS the rescue):
    python3 experiments/tape_v2/x11_decode.py --selfcheck
    # blocking regression gate, one capture per invocation:
    python3 experiments/tape_v2/x11_decode.py --regress tape9   # chunkable via --sections
    python3 experiments/tape_v2/x11_decode.py --regress m8
    python3 experiments/tape_v2/x11_decode.py --regress tape7
    python3 experiments/tape_v2/x11_decode.py --regress tape4
    python3 experiments/tape_v2/x11_decode.py --regress summary

Outputs: results/x11_decode_results_<tag>.json (decodes),
         results/x11_decode_regression_<capture>.json + _summary.json (gate),
         results/x11_decode_selfcheck.json.
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

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                          # noqa: E402
import m3_codec as codec                               # noqa: E402
import m9_decode as m9d                                # noqa: E402 (read-only)
import m10_decode as m10                               # noqa: E402 (FROZEN, read-only)
import x11_d2x_erasure as xd                           # noqa: E402 (gated x11, read-only)
from h9_payload_codec import unpack_payload            # noqa: E402

SR = codec.FS
RESULTS_DIR = _HERE / "results"
CAP_DIR = _HERE / "captures"
DEFAULT_MANIFEST = _HERE / "master10_manifest.json"
MASTER_ID = "master10"
D2X_KINDS = ("dense2x", "dense2x_drop")
FA_BUDGET = 1e-4

COMPOSITION = [
    "stageA: m10_decode._decode_section VERBATIM (frozen composed pipeline)",
    "stageB: x11_d2x_erasure.x11_rescue_section on d2x sections stage A leaves "
    "failing (shift-window sweep + frozen erasure ladder over enlarged pool)",
    "merge: rescue adopted ONLY if strictly better; never-worse-than-m10 by "
    "construction; strictly-additive CRC32-guarded fill-only throughout",
]


# ===========================================================================
# capture loading (x11-prefixed caches; logic mirrors the frozen m10 loader)
# ===========================================================================
def _load_capture(recording_path, manifest, tag, use_cache=True):
    nom_cache = CAP_DIR / f"x11_decode_nom_{tag}.npy"
    sync_cache = RESULTS_DIR / f"x11_decode_sync_{tag}.json"
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
# the superset per-section path: frozen stage A, gated stage B, safe merge
# ===========================================================================
def _decode_section_x11(audio_nom, sec, align, ledger, *, rescue=True,
                        x11_rescue=True, verbose=True):
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
        if verbose:
            print(f"    [x11_decode {sec['name']}] stage A left "
                  f"{stock_failed} failed cw -> arming x11 d2x rescue",
                  flush=True)
        rec = xd.x11_rescue_section(audio_nom, sec, align, ledger, stock_row,
                                    verbose=verbose)
        r["x11_rescue"] = rec
        if int(rec["cw_failed_final"]) < stock_failed:
            # strictly better -> adopt (never-worse-than-m10 guarantee)
            r["decoder_stage"] = "x11_rescue"
            r["x11_rescued"] = bool(rec["rescued"])
            r["rs_codewords_failed"] = int(rec["cw_failed_final"])
            r["byte_exact"] = bool(rec["byte_exact"])
            r["miscorrected_cw"] = int(rec["miscorrected"])
            r["x11_filled_by_sweep"] = len(rec["filled_by_sweep"])
            r["x11_filled_by_ladder"] = len(rec["filled_by_ladder"])
            # the rescue path audits orig-exactness internally (sidecar sha);
            # the wrapper carries those audited flags (no assembled bytes are
            # returned by the gated rescue function, by design)
            r["_x11_orig_exact_override"] = bool(rec["orig_exact"])
    return r, assembled


# ===========================================================================
# capture-level driver (mirrors the frozen m10.decode loop; x11 result files)
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
    json_path = RESULTS_DIR / f"x11_decode_results_{tag}.json"

    out = (json.loads(json_path.read_text()) if json_path.exists()
           else {"recording": str(recording_path), "tape": manifest.get("tape"),
                 "manifest": str(mpath.name),
                 "decoder": "x11_decode (m10 composed superset + gated x11 d2x rescue)",
                 "composition": COMPOSITION,
                 "gate_evidence": "results/x11_d2x_gate_report.json (gate_met)",
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
        print(f"[x11_decode] {recording_path} (manifest={mpath.name}, "
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
        if sec["kind"] == "freqdiff":
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
        else:
            r, assembled = _decode_section_x11(audio_nom, sec, align, ledger,
                                               rescue=rescue,
                                               x11_rescue=x11_rescue,
                                               verbose=verbose)
        # ---- unpack + integrity (m9/m10 pattern) ----
        pack = sec["pack"]
        if r.pop("_x11_orig_exact_override", None) is not None or \
                r.get("decoder_stage") == "x11_rescue":
            # outcome adopted from the gated rescue: carry its audited flags
            rec = r["x11_rescue"]
            r["unpack_ok"] = bool(rec["orig_exact"])
            r["orig_byte_exact"] = bool(rec["orig_exact"])
            r["crc_check"] = bool(rec["orig_exact"])
        else:
            crc_ok = unpack_ok = orig_exact = None
            try:
                recovered_orig = unpack_payload(assembled)
                unpack_ok = True
                sha_o = hashlib.sha256(recovered_orig).hexdigest()
                orig_exact = (sha_o == pack["sha256_orig"]
                              and len(recovered_orig) == pack["orig_len"])
                crc_ok = orig_exact
            except Exception as exc:
                unpack_ok = False
                r["unpack_error"] = str(exc)
            r["unpack_ok"] = unpack_ok
            r["orig_byte_exact"] = orig_exact
            r["crc_check"] = crc_ok
        r["effective_bps"] = sec.get("effective_bps")
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        out["payloads_by_name"][sec["name"]] = r
        # checkpoint after every section
        results = [out["payloads_by_name"][n] for n in out["section_order"]
                   if n in out["payloads_by_name"]]
        out["payloads"] = results
        out["n_byte_exact_packed"] = sum(bool(x.get("byte_exact")) for x in results)
        out["n_orig_exact"] = sum(bool(x.get("orig_byte_exact")) for x in results)
        out["n_payloads"] = len(results)
        out["n_x11_rescued"] = sum(bool(x.get("x11_rescued")) for x in results)
        out["false_accept_bound"] = ledger["crc_checks"] * 2.0 ** -32
        out["fa_within_budget"] = bool(out["false_accept_bound"] < FA_BUDGET)
        json_path.write_text(json.dumps(out, indent=2, default=_jsafe))
        if verbose:
            print(f"  [{r['name']:28s}] cw {r.get('rs_codewords_failed')}/"
                  f"{r.get('n_codewords')} stage={r.get('decoder_stage')} "
                  f"PACK={'YES' if r.get('byte_exact') else 'no'} "
                  f"ORIG={'YES' if r.get('orig_byte_exact') else 'no'} "
                  f"-> checkpointed", flush=True)

    if verbose:
        m10._print_table(recording_path, sync, out)
        print(f"[x11_decode] wrote {json_path}")
    return out


# ===========================================================================
# wrapper selfcheck: clean synth (stage A suffices) + marginal synth cell
# (stage B MUST fire and land 4/4 orig-exact -- exercises the full wiring)
# ===========================================================================
SELFCHECK_MARGINAL_CELL = "dg0.35_aac0_clk+0.00_s0"


def selfcheck():
    res_path = RESULTS_DIR / "x11_decode_selfcheck.json"
    out = {"experiment": "x11_decode wrapper selfcheck",
           "marginal_cell": SELFCHECK_MARGINAL_CELL, "runs": {}}

    def _rows(res):
        return [{"name": r["name"], "cw_failed": r.get("rs_codewords_failed"),
                 "orig_exact": r.get("orig_byte_exact"),
                 "miscorrected": r.get("miscorrected_cw"),
                 "stage": r.get("decoder_stage"),
                 "x11_rescued": r.get("x11_rescued")}
                for r in res.get("payloads", [])]

    # 1) clean synth mini-master: stage A must suffice (rescue never fires)
    res1 = decode(str(_HERE / "x11_d2x_synth.wav"),
                  out_tag="selfcheck_synth_clean",
                  manifest_path="x11_d2x_synth_manifest.json")
    rows1 = _rows(res1)
    out["runs"]["synth_clean"] = {
        "rows": rows1,
        "pass": bool(rows1 and all(r["orig_exact"] and r["cw_failed"] == 0
                                   and r["stage"] == "m10_stock"
                                   and (r["miscorrected"] or 0) == 0
                                   for r in rows1))}

    # 2) marginal synth cell: stage B must fire and rescue to 4/4 orig-exact
    cap = CAP_DIR / f"x11_d2x_{SELFCHECK_MARGINAL_CELL}.wav"
    res2 = decode(str(cap), out_tag="selfcheck_synth_marginal",
                  manifest_path="x11_d2x_synth_manifest.json")
    rows2 = _rows(res2)
    out["runs"]["synth_marginal"] = {
        "capture": cap.name, "rows": rows2,
        "pass": bool(rows2 and all(r["orig_exact"] and r["cw_failed"] == 0
                                   and (r["miscorrected"] or 0) == 0
                                   for r in rows2)
                     and any(r["x11_rescued"] for r in rows2))}
    out["fa_bound_clean"] = res1.get("false_accept_bound")
    out["fa_bound_marginal"] = res2.get("false_accept_bound")
    out["pass"] = bool(out["runs"]["synth_clean"]["pass"]
                       and out["runs"]["synth_marginal"]["pass"])
    res_path.write_text(json.dumps(out, indent=2, default=_jsafe))
    print(f"[selfcheck] clean={out['runs']['synth_clean']['pass']} "
          f"marginal={out['runs']['synth_marginal']['pass']} "
          f"PASS={out['pass']}")
    return out


# ===========================================================================
# BLOCKING regression gate: every banked outcome on all 4 real captures,
# 0 regressions / 0 miscorrections.  tape9 + m8 run THROUGH x11_decode (the
# wrapper must be transparently identical to m10 on non-d2x sections);
# tape7 + tape4 run through the UNCHANGED production decoders (x11_decode
# does not touch those paths; included so the full 4-capture suite is on
# record for the shipped receiver stack).
# ===========================================================================
TAPE9_EXPECT = ["m9_m0_reprove934", "m9_m1_thin159", "m9_m2_thin191",
                "m9_m3_dropnull9c", "m9_m4_n256_rs159", "m9_m4b_n256_rs159_var",
                "m9_m5_n256_rs179", "m9_m6_n256_rs191", "m9_m7_n256_p11_9000",
                "m9_m8_dense375"]


def _write_regression(name, payload):
    path = RESULTS_DIR / f"x11_decode_regression_{name}.json"
    payload["experiment"] = "x11_decode BLOCKING regression gate"
    payload["decoder"] = ("x11_decode wrapper" if name in ("tape9", "m8")
                          else "unchanged production decoder "
                               "(x10_a_fec_gmd_erasure._run_production)")
    path.write_text(json.dumps(payload, indent=2, default=_jsafe))
    print(f"[regress] wrote {path.name}: all_match={payload.get('all_match')}",
          flush=True)


def regress_tape9(sections=None):
    res = decode(str(CAP_DIR / "tape9_run1.wav"), out_tag="regress_tape9",
                 manifest_path="master9_manifest.json", sections=sections)
    ref = json.loads((RESULTS_DIR /
                      "x10_m10_results_composed_regression_tape9_run1.json"
                      ).read_text())
    rows, ok_all = [], True
    names = TAPE9_EXPECT + ["m9_m9a_freqdiff"]
    n_present = 0
    for nm in names:
        r = res["payloads_by_name"].get(nm)
        rr = ref["payloads_by_name"].get(nm)
        if r is None or rr is None:
            continue
        n_present += 1
        if nm == "m9_m9a_freqdiff":
            ok = (r.get("rs_codewords_failed") == rr.get("rs_codewords_failed")
                  == 37)   # the expected negative
        else:
            ok = (bool(r.get("orig_byte_exact"))
                  and r.get("rs_codewords_failed") == 0
                  and (r.get("miscorrected_cw") or 0) == 0
                  and bool(rr.get("orig_byte_exact"))
                  == bool(r.get("orig_byte_exact")))
        ok_all &= ok
        rows.append({"name": nm, "cw_failed": r.get("rs_codewords_failed"),
                     "orig_exact": r.get("orig_byte_exact"),
                     "miscorrected": r.get("miscorrected_cw"),
                     "stage": r.get("decoder_stage"),
                     "x11_rescue_fired": r.get("x11_rescue") is not None,
                     "matches_reference": bool(ok)})
    complete = n_present == len(names)
    _write_regression("tape9", {
        "capture": "tape9_run1.wav", "reference":
            "x10_m10_results_composed_regression_tape9_run1.json",
        "rows": rows, "n_present": n_present, "complete": complete,
        "all_match": bool(ok_all and complete),
        "fa_bound": res.get("false_accept_bound")})
    return ok_all and complete


def regress_m8():
    res = decode(str(CAP_DIR / "m8_tape_mono_lossless.wav"),
                 out_tag="regress_m8", manifest_path="master8_manifest.json",
                 sections=["m8_dq_p10n512_rs127"])
    r = res["payloads_by_name"]["m8_dq_p10n512_rs127"]
    ok = (r.get("rs_codewords_failed") == 0 and bool(r.get("orig_byte_exact"))
          and (r.get("miscorrected_cw") or 0) == 0)
    _write_regression("m8", {
        "capture": "m8_tape_mono_lossless.wav",
        "reference": "x10_m10_results_composed_regression_m8_tape.json (0/62)",
        "rows": [{"name": "m8_dq_p10n512_rs127",
                  "cw_failed": r.get("rs_codewords_failed"),
                  "n_codewords": r.get("n_codewords"),
                  "orig_exact": r.get("orig_byte_exact"),
                  "miscorrected": r.get("miscorrected_cw"),
                  "stage": r.get("decoder_stage"),
                  "matches_reference": bool(ok)}],
        "all_match": bool(ok), "fa_bound": res.get("false_accept_bound")})
    return ok


def _regress_production(name, mod, cap, names):
    from x10_a_fec_gmd_erasure import _run_production
    rows = _run_production(mod, str(CAP_DIR / cap), names)
    ref = json.loads((RESULTS_DIR / "x10_gmd_erasure_regression.json"
                      ).read_text())
    refrows = {r["name"]: r for r in ref[cap.replace(".wav", "")]}
    for r in rows:
        rr = refrows[r["name"]]
        r["matches_reference"] = bool(
            bool(r["byte_exact"]) == bool(rr["byte_exact"])
            and r["rs_codewords_failed"] == rr["rs_codewords_failed"])
    ok_all = (len(rows) == len(names)
              and all(r["matches_reference"] for r in rows))
    _write_regression(name, {
        "capture": cap, "reference": "x10_gmd_erasure_regression.json",
        "rows": rows, "all_match": bool(ok_all)})
    return ok_all


def regress_summary():
    caps = ("tape9", "m8", "tape7", "tape4")
    detail = {}
    for c in caps:
        p = RESULTS_DIR / f"x11_decode_regression_{c}.json"
        detail[c] = (json.loads(p.read_text()).get("all_match")
                     if p.exists() else None)
    out = {"experiment": "x11_decode BLOCKING regression gate -- summary",
           "detail": detail,
           "blocking_gate_pass": bool(all(detail[c] for c in caps))}
    sc = RESULTS_DIR / "x11_decode_selfcheck.json"
    if sc.exists():
        out["wrapper_selfcheck_pass"] = json.loads(sc.read_text()).get("pass")
    (RESULTS_DIR / "x11_decode_regression_summary.json").write_text(
        json.dumps(out, indent=2, default=_jsafe))
    print(json.dumps(out, indent=1))
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


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?", default=None)
    ap.add_argument("--out-tag", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--sections", default="")
    ap.add_argument("--no-rescue", action="store_true",
                    help="stage A pass-1 only (no m10 late-window/ladder)")
    ap.add_argument("--no-x11", action="store_true",
                    help="disable stage B (pure frozen m10 behaviour)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--regress", default=None,
                    choices=["tape9", "m8", "tape7", "tape4", "summary"])
    args = ap.parse_args()
    secs = [s for s in args.sections.split(",") if s] or None
    if args.selfcheck:
        out = selfcheck()
        sys.exit(0 if out["pass"] else 1)
    if args.regress == "tape9":
        sys.exit(0 if regress_tape9(secs) else 1)
    if args.regress == "m8":
        sys.exit(0 if regress_m8() else 1)
    if args.regress == "tape7":
        sys.exit(0 if _regress_production(
            "tape7", "m7_decode", "tape7_run1.wav",
            {"m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k"}) else 1)
    if args.regress == "tape4":
        sys.exit(0 if _regress_production(
            "tape4", "m4_decode", "tape4_run1.wav",
            {"ws_test2k", "ws_llm24k"}) else 1)
    if args.regress == "summary":
        out = regress_summary()
        sys.exit(0 if out["blocking_gate_pass"] else 1)
    if not args.recording:
        ap.error("recording required (or --selfcheck / --regress)")
    decode(args.recording, args.out_tag, manifest_path=args.manifest,
           sections=secs, rescue=not args.no_rescue,
           x11_rescue=not args.no_x11, use_cache=not args.no_cache)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
