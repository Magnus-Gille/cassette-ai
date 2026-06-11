"""x10_c_redundancy_architecture_1_frontend_ensemble_union.py

PRODUCTION ensemble-union receiver (bet C, candidate 1): CRC32-guarded
per-codeword UNION across a widened timing-front-end ensemble.

Productionizes the validated prototypes x10_union_probe.py +
x10_union_verify_orig.py into a manifest-driven decoder that follows the
m9_decode.py pattern (am2.global_sync_and_resample -> per-section demod ->
RS + CRC), with ONE architectural change: the per-section winner-take-all of
m9_decode._rs_merge_guarded is replaced by a per-codeword
accept-any-CRC-verified-branch fusion across the front-end bank
(erase_frac = 0 everywhere; on tape9 erasures only ever hurt).

NOTE on the file name: the campaign plan called this file x10_ensemble_decode.py
but the binding x10 rules for this candidate restrict new code to
x10_c_redundancy_architecture_1_frontend_ensemble_union*.py — the rules win.
Result files keep the plan's names: results/x10_ensemble_decode_<capture>.json.

Front-end bank (all drop-in supersets of the proven h4 path, via
x9_resampling_pll.ResamplingPLLDemod):
    resampling PLL @ pll_bw_hz in {15, 30, 45}
    pilot-EMA      @ alpha     in {0.40 .. 0.85 step 0.05}
ordered proven-first so early-stop reproduces the m9 winners cheaply.

Registration hook: external experiment modules (x10_late_window, x10_gmd,
x10_pfft, ...) become additional union branches by exposing
    UNION_ADMITTED = True            # only after passing the full 4-capture
                                     # regression suite (admission requirement)
    provide_union_branches(sch, sec) -> iterable of (name, fe) where
                                     fe(win, nd) -> (bits, diag)
or at runtime via register_branch_provider(fn).  Branches that have not been
admitted are NOT imported into the production bank.

RECORD CONVENTION (declared, not buried): per-codeword CRC32 acceptance uses
the manifest sidecar table (sec["crc32_codewords"]) — truth-derived
receiver-side information; only the whole-payload CRC32 is in-stream.  All
record claims from this receiver inherit that sidecar caveat, the same
convention as the standing 2572 bps record (m9_decode uses the same table).

CAMPAIGN LEDGER: every RS-decode attempt whose output is offered to a CRC32
check is one false-accept trial at p = 2^-32.  This module counts trials per
run, accumulates them across reruns (cumulative_rs_attempts) and across
captures + the prototype runs, against the PRE-REGISTERED campaign budget of
4e5 trials (expected false-accepts < 1e-4).

Captures (regression suite):
    tape9  -> captures/tape9_run1.wav            master9_manifest.json  (union, all 11 sections)
    m8     -> captures/m8_tape_mono_lossless.wav master8_manifest.json  (union, m8_dq_p10n512_rs127)
    tape7  -> captures/tape7_run1.wav            master7_manifest.json  (proven WS path, 3 named rungs)
    tape4  -> captures/tape4_run1.wav            master4_manifest.json  (proven WS path, 2 named rungs)

Usage (one capture per invocation, <8 min each):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
        experiments/tape_v2/x10_c_redundancy_architecture_1_frontend_ensemble_union.py tape9
    ... same for m8 / tape7 / tape4
    [--no-early-stop]  run every bank branch even after the union is complete
    [--sections a,b]   restrict to named sections (default: per-capture spec)

Deterministic: no RNG anywhere (seeds N/A); numpy/scipy versions logged.
Outputs: results/x10_ensemble_decode_<capture-stem>.json (checkpointed per section).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import pathlib
import sys
import time
import zlib
from fractions import Fraction

import numpy as np
import scipy
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                       # noqa: E402
import m3_codec as codec                            # noqa: E402
import m9_decode as md                              # noqa: E402  (read-only import)
from x9_resampling_pll import ResamplingPLLDemod    # noqa: E402
from h9_payload_codec import unpack_payload         # noqa: E402
from reedsolo import RSCodec, ReedSolomonError      # noqa: E402

SR = codec.FS
RESULTS_DIR = _HERE / "results"

# ===========================================================================
# Front-end bank (plan spec: pll_bw {15,30,45} Hz + ema alpha {0.40..0.85/.05})
# ordered proven-first (m9 winners) so early-stop is cheap on EXACT sections.
# ===========================================================================
BANK: tuple[tuple[str, dict], ...] = (
    ("resampling_pll30", dict(front_end="pll", pll_bw_hz=30.0)),
    ("ema0.50", dict(front_end="ema", ema_alpha=0.50)),
    ("ema0.60", dict(front_end="ema", ema_alpha=0.60)),
    ("ema0.65", dict(front_end="ema", ema_alpha=0.65)),
    ("ema0.70", dict(front_end="ema", ema_alpha=0.70)),
    ("ema0.80", dict(front_end="ema", ema_alpha=0.80)),
    ("ema0.40", dict(front_end="ema", ema_alpha=0.40)),
    ("ema0.45", dict(front_end="ema", ema_alpha=0.45)),
    ("ema0.55", dict(front_end="ema", ema_alpha=0.55)),
    ("ema0.75", dict(front_end="ema", ema_alpha=0.75)),
    ("ema0.85", dict(front_end="ema", ema_alpha=0.85)),
    ("resampling_pll15", dict(front_end="pll", pll_bw_hz=15.0)),
    ("resampling_pll45", dict(front_end="pll", pll_bw_hz=45.0)),
)

# Prototype trials already spent (documented, conservative exact counts):
#   x10_union_probe_tape9_run1: 6 FEs x (48+44+41+43)=1056 RS+CRC trials
#                               + frame_select 176 + majority3 176     = 1408
#   x10_union_verify_orig:      4 FEs x 48 (m4) + 4 FEs x 44 (m5)      =  368
PRIOR_TRIALS = {"x10_union_probe_tape9_run1": 1408, "x10_union_verify_orig": 368}
CAMPAIGN_TRIAL_BUDGET = 400_000          # pre-registered; E[false-accept] < 1e-4

# ===========================================================================
# External-branch registration hook (admission-gated).
# ===========================================================================
EXTERNAL_BRANCH_MODULES = ("x10_late_window", "x10_gmd", "x10_pfft")
_BRANCH_PROVIDERS: list = []


def register_branch_provider(fn) -> None:
    """Register fn(sch, sec) -> iterable[(name, fe)] as extra union branches.
    ADMISSION REQUIREMENT (campaign-wide): the providing experiment must first
    pass the full 4-capture regression suite with 0 regressions before being
    registered in any production run."""
    _BRANCH_PROVIDERS.append(fn)


def _external_branches(sch, sec) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for fn in _BRANCH_PROVIDERS:
        out.extend(fn(sch, sec))
    for modname in EXTERNAL_BRANCH_MODULES:
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            continue
        if not getattr(mod, "UNION_ADMITTED", False):
            continue                      # not admitted -> not in the bank
        prov = getattr(mod, "provide_union_branches", None)
        if prov is not None:
            out.extend(prov(sch, sec))
    return out


# ===========================================================================
# Helpers productionized from x10_union_probe (kept inline: no x10_common).
# ===========================================================================
def _rx_mat(rx_frames, meta):
    """Reassemble the de-interleaved codeword matrix (same math as m9_decode)."""
    fb_bits, n_frames = meta["frame_bits"], meta["n_frames"]
    stream_bits = meta["stream_bits"]
    rs_n, n_cw = meta["rs_n"], meta["n_codewords"]
    pieces = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else stream_bits - fb_bits * (n_frames - 1)
        rb = (np.asarray(rx_frames[fi], np.uint8).ravel()
              if fi < len(rx_frames) else np.zeros(nominal, np.uint8))
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    rx_bits = np.concatenate(pieces)[:stream_bits]
    if len(rx_bits) < stream_bits:
        rx_bits = np.concatenate([rx_bits, np.zeros(stream_bits - len(rx_bits), np.uint8)])
    rx_bytes = np.packbits(rx_bits)[:n_cw * rs_n]
    return rx_bytes.reshape(rs_n, n_cw).T


def _per_cw_decode(rx_mat, meta, crc_table):
    """Errors-only RS per codeword + CRC32 guard.
    Returns (ok_mask, msgs, n_rs_attempts, n_crc_checked, n_crc_accepted)."""
    rs_n, rs_k, n_cw = meta["rs_n"], meta["rs_k"], meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    ok = np.zeros(n_cw, bool)
    msgs: list = [None] * n_cw
    n_att = n_chk = n_acc = 0
    for i in range(n_cw):
        n_att += 1
        try:
            msg = bytes(rsc.decode(bytearray(rx_mat[i].tobytes()))[0])
        except (ReedSolomonError, Exception):
            continue
        n_chk += 1
        if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
            continue                      # CRC guard: reject miscorrection
        ok[i] = True
        msgs[i] = msg
        n_acc += 1
    return ok, msgs, n_att, n_chk, n_acc


def _assemble(meta, msgs):
    out = bytearray()
    for i in range(meta["n_codewords"]):
        out += msgs[i] if msgs[i] is not None else bytes(meta["rs_k"])
    return bytes(out)[:meta["payload_len"]]


# ===========================================================================
# Union decode of one DQPSK / drop-null section.
# ===========================================================================
def union_decode_dqpsk_section(audio_nom, sec, align, *, early_stop=True):
    sch = md._scheme_from_entry(sec)
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()    # SCORING ONLY
    n_cw, rs_k = meta["n_codewords"], meta["rs_k"]
    payload_len = meta["payload_len"]

    branches: list[tuple[str, object]] = []
    for bname, kw in BANK:
        dem = ResamplingPLLDemod(sch, **kw)
        branches.append((bname, lambda w, nd, d=dem: d.demod(w, nd)))
    branches.extend(_external_branches(sch, sec))

    union_msgs: list = [None] * n_cw
    accepted_by: list = [None] * n_cw
    per_branch: dict = {}
    led = {"rs_attempts": 0, "crc_checked": 0, "crc_accepted": 0}
    branches_run = 0
    for bname, fe in branches:
        if early_stop and all(m is not None for m in union_msgs):
            break
        ts = time.time()
        rx_frames, _diags = md._demod_section_frames(audio_nom, sec, align, sch, fe)
        ok, msgs, n_att, n_chk, n_acc = _per_cw_decode(_rx_mat(rx_frames, meta),
                                                       meta, crc_table)
        led["rs_attempts"] += n_att
        led["crc_checked"] += n_chk
        led["crc_accepted"] += n_acc
        branches_run += 1
        new = 0
        for i in range(n_cw):
            if union_msgs[i] is None and msgs[i] is not None:
                union_msgs[i] = msgs[i]
                accepted_by[i] = bname
                new += 1
        failed = [int(i) for i in np.flatnonzero(~ok)]
        per_branch[bname] = {"cw_failed": len(failed), "failed_idx": failed,
                             "new_cw_accepted": new,
                             "sec_s": round(time.time() - ts, 2)}
        print(f"    [{sec['name']}] {bname}: {len(failed)}/{n_cw} failed "
              f"(+{new} new) {per_branch[bname]['sec_s']}s", flush=True)

    # ---- post-hoc miscorrection check (truth, SCORING ONLY): any CRC-accepted
    # codeword whose in-payload bytes differ from the sidecar is a false-accept.
    miscorrected = 0
    for i in range(n_cw):
        if union_msgs[i] is None:
            continue
        lo, hi = i * rs_k, min((i + 1) * rs_k, payload_len)
        if union_msgs[i][:hi - lo] != expected[lo:hi]:
            miscorrected += 1

    recovered = _assemble(meta, union_msgs)
    failed_union = [i for i in range(n_cw) if union_msgs[i] is None]
    byte_err = sum(a != b for a, b in zip(recovered, expected)) + abs(
        len(recovered) - len(expected))
    byte_exact = recovered == expected

    # ---- unpack + orig-exact (sha256 vs manifest pack) ----
    pack = sec.get("pack") or {}
    unpack_ok = orig_exact = None
    try:
        orig = unpack_payload(recovered)
        unpack_ok = True
        sha_o = hashlib.sha256(orig).hexdigest()
        orig_exact = (sha_o == pack.get("sha256_orig")
                      and len(orig) == pack.get("orig_len"))
    except Exception as exc:
        unpack_ok = False
        orig_exact = False
        sha_o = f"unpack_error: {exc}"

    acc_hist: dict = {}
    for b in accepted_by:
        if b is not None:
            acc_hist[b] = acc_hist.get(b, 0) + 1

    res = {
        "name": sec["name"], "kind": sec["kind"], "phy": sec["phy"],
        "decoder": "ensemble_union", "erase_frac": 0.0,
        "rs_n": meta["rs_n"], "rs_k": rs_k,
        "n_codewords": n_cw, "n_frames": meta["n_frames"],
        "gross_bps": sec.get("gross_bps"),
        "projected_net_bps": sec.get("projected_net_bps"),
        "effective_bps": sec.get("effective_bps"),
        "rs_codewords_failed": len(failed_union), "failed_idx": failed_union,
        "byte_errors": byte_err, "byte_exact": bool(byte_exact),
        "miscorrected_cw_posthoc": miscorrected,
        "unpack_ok": unpack_ok, "orig_byte_exact": bool(orig_exact),
        "sha256_orig_recovered": sha_o,
        "branches_run": branches_run,
        "branches_skipped": [b for b, _ in branches][branches_run:],
        "accepted_by_branch": acc_hist,
        "per_branch": per_branch,
        "ledger": led,
    }
    return res


# ===========================================================================
# Capture specs.
# ===========================================================================
CAPTURES = {
    "tape9": {
        "wav": _HERE / "captures" / "tape9_run1.wav",
        "manifest": _HERE / "master9_manifest.json",
        "mode": "union_all",            # union for dqpsk; m9 path for freqdiff
        "sections": None,               # all
    },
    "m8": {
        "wav": _HERE / "captures" / "m8_tape_mono_lossless.wav",
        "manifest": _HERE / "master8_manifest.json",
        "mode": "union_named",
        "sections": ["m8_dq_p10n512_rs127"],
    },
    "tape7": {
        "wav": _HERE / "captures" / "tape7_run1.wav",
        "manifest": _HERE / "master7_manifest.json",
        "mode": "ws_m6",                # proven m6/m7 WS section decoder
        "sections": ["m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k"],
    },
    "tape4": {
        "wav": _HERE / "captures" / "tape4_run1.wav",
        "manifest": _HERE / "master4_manifest.json",
        "mode": "ws_m4",                # proven m4 WS decoder
        "sections": ["ws_test2k", "ws_llm24k"],
    },
}

# Named regression rungs per capture: (check_field, [section names]).
NAMED_REGRESSION = {
    "tape9": ("orig_byte_exact", ["m9_m0_reprove934", "m9_m1_thin159",
                                  "m9_m2_thin191", "m9_m3_dropnull9c",
                                  "m9_m4b_n256_rs159_var", "m9_m8_dense375",
                                  "m9_m4_n256_rs159", "m9_m5_n256_rs179"]),
    "m8": ("orig_byte_exact", ["m8_dq_p10n512_rs127"]),
    "tape7": ("byte_exact", ["m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k"]),
    "tape4": ("byte_exact", ["ws_test2k", "ws_llm24k"]),
}


def _load_audio(path: pathlib.Path) -> np.ndarray:
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    return audio


def _cumulative_prev(out_path: pathlib.Path) -> int:
    try:
        prev = json.loads(out_path.read_text())
        return int(prev.get("ledger_totals", {}).get("cumulative_rs_attempts", 0))
    except Exception:
        return 0


def _campaign_ledger(self_path: pathlib.Path, self_cumulative: int) -> dict:
    total = sum(PRIOR_TRIALS.values())
    detail = dict(PRIOR_TRIALS)
    for f in sorted(RESULTS_DIR.glob("x10_ensemble_decode_*.json")):
        if f == self_path:
            detail[f.name] = self_cumulative
            total += self_cumulative
            continue
        try:
            d = json.loads(f.read_text())
            c = int(d.get("ledger_totals", {}).get("cumulative_rs_attempts", 0))
        except Exception:
            c = 0
        detail[f.name] = c
        total += c
    if self_path.name not in detail:
        detail[self_path.name] = self_cumulative
        total += self_cumulative
    return {"budget": CAMPAIGN_TRIAL_BUDGET,
            "total_trials": total,
            "within_budget": total < CAMPAIGN_TRIAL_BUDGET,
            "expected_false_accepts_at_2^-32": total * 2.0 ** -32,
            "detail": detail}


# ===========================================================================
def run_capture(key: str, *, early_stop=True, only_sections=None) -> dict:
    spec = CAPTURES[key]
    manifest = json.loads(spec["manifest"].read_text())
    cap = spec["wav"]
    stem = cap.stem
    out_path = RESULTS_DIR / f"x10_ensemble_decode_{stem}.json"
    prev_cum = _cumulative_prev(out_path)

    t0 = time.time()
    audio = _load_audio(cap)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    print(f"[{key}] sync {time.time()-t0:.1f}s clock={sync.get('clock_ratio')} "
          f"align={align:+d}", flush=True)
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    except Exception as exc:
        sounder = {"error": str(exc)}

    want = set(only_sections or spec["sections"] or
               [s["name"] for s in manifest["ws_payloads"]])
    results: list[dict] = []
    led_tot = {"rs_attempts": 0, "crc_checked": 0, "crc_accepted": 0}

    out = {
        "capture": str(cap), "manifest": str(spec["manifest"]), "mode": spec["mode"],
        "decoder": "x10_c_redundancy_architecture_1_frontend_ensemble_union",
        "bank": [b for b, _ in BANK], "early_stop": bool(early_stop),
        "erase_frac": 0.0,
        "record_convention_caveat": (
            "per-codeword CRC32 acceptance uses the manifest sidecar table "
            "(truth-derived receiver-side information); only the whole-payload "
            "CRC32 is in-stream. Record claims inherit this sidecar caveat, "
            "same convention as the standing 2572 bps record."),
        "versions": {"python": sys.version.split()[0], "numpy": np.__version__,
                     "scipy": scipy.__version__},
        "seeds": "deterministic decode, no RNG",
        "sync": {k: (str(v) if isinstance(v, Fraction) else v)
                 for k, v in sync.items() if k != "audio_nominal"},
        "align": int(align),
        "sections": results,
    }

    def _checkpoint():
        cum = prev_cum + led_tot["rs_attempts"]
        out["ledger_totals"] = {**led_tot, "prev_cumulative_rs_attempts": prev_cum,
                                "cumulative_rs_attempts": cum}
        out["campaign_ledger"] = _campaign_ledger(out_path, cum)
        chk, names = NAMED_REGRESSION[key]
        by_name = {r["name"]: r for r in results}
        out["named_rung_checks"] = {
            "check_field": chk,
            "rungs": {n: bool(by_name.get(n, {}).get(chk)) for n in names},
            "n_pass": sum(bool(by_name.get(n, {}).get(chk)) for n in names),
            "n_named": len(names),
            "regressions": [n for n in names if not by_name.get(n, {}).get(chk)],
        }
        out["miscorrected_total"] = sum(
            int(r.get("miscorrected_cw_posthoc") or r.get("miscorrected_cw") or 0)
            for r in results)
        out["elapsed_s"] = round(time.time() - t0, 1)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, default=str))

    for sec in manifest["ws_payloads"]:
        if sec.get("skipped") or sec["name"] not in want:
            continue
        ts = time.time()
        if spec["mode"] in ("union_all", "union_named") and sec.get("kind") in (
                "dqpsk", "dqpsk_dropnull"):
            r = union_decode_dqpsk_section(audio_nom, sec, align, early_stop=early_stop)
            for k in led_tot:
                led_tot[k] += r["ledger"][k]
        elif spec["mode"] == "union_all" and sec.get("kind") == "freqdiff":
            # proven m9 freqdiff path (not a union member; m9a is not a named rung)
            r, _packed = md._decode_freqdiff_section(audio_nom, sec, align, sounder)
            r["decoder"] = "m9_freqdiff_delegate"
            # conservative ledger: its CRC-guarded merge sweeps 3 erase fracs
            n_tr = 3 * sec["meta"]["n_codewords"]
            led_tot["rs_attempts"] += n_tr
            r["ledger"] = {"rs_attempts": n_tr, "crc_checked": None,
                           "crc_accepted": None}
            # post-hoc truth verdict for freqdiff: byte_errors vs sidecar already
            # computed by the m9 path; miscorrected_cw is its CRC-guard count.
        elif spec["mode"] == "ws_m6":
            from m6_decode import _decode_section as ws_decode_section
            r = ws_decode_section(audio_nom, sec, align, sounder)
            r["decoder"] = "m6_ws_delegate"
            r["miscorrected_cw_posthoc"] = (
                0 if r.get("byte_errors") == 0 else None)  # exact => none possible
        elif spec["mode"] == "ws_m4":
            from m4_decode import _decode_ws, _ws_eq_from_sounder
            from assault_widespace import build as ws_build
            wphy = manifest["ws_phy"]
            ws = ws_build(wphy["M"], wphy["K"], wphy["spacing"], wphy["N"])
            eq = _ws_eq_from_sounder(ws, sounder)
            r = _decode_ws(audio_nom, sec, align, ws, eq)
            r["decoder"] = "m4_ws_delegate"
            r["miscorrected_cw_posthoc"] = (
                0 if r.get("byte_errors") == 0 else None)
        else:
            continue
        r["section_s"] = round(time.time() - ts, 1)
        results.append(r)
        _checkpoint()
        chk = r.get("orig_byte_exact", r.get("byte_exact"))
        print(f"  [{sec['name']}] done in {r['section_s']}s  "
              f"cw_failed={r.get('rs_codewords_failed')}  exact={chk}", flush=True)

    _checkpoint()
    print(f"[{key}] wrote {out_path}  total {time.time()-t0:.1f}s", flush=True)
    nm = out["named_rung_checks"]
    print(f"[{key}] named rungs: {nm['n_pass']}/{nm['n_named']} pass "
          f"({nm['check_field']}); regressions: {nm['regressions']}", flush=True)
    print(f"[{key}] miscorrected_total={out['miscorrected_total']}  "
          f"trials(run)={led_tot['rs_attempts']}  "
          f"campaign={out['campaign_ledger']['total_trials']}/"
          f"{CAMPAIGN_TRIAL_BUDGET}", flush=True)
    return out


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", choices=sorted(CAPTURES.keys()))
    ap.add_argument("--no-early-stop", action="store_true")
    ap.add_argument("--sections", default=None,
                    help="comma-separated section names (overrides default)")
    args = ap.parse_args()
    run_capture(args.capture,
                early_stop=not args.no_early_stop,
                only_sections=args.sections.split(",") if args.sections else None)
