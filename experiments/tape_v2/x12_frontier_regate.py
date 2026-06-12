"""x12_frontier_regate.py -- FRONTIER RE-GATE vs tape10 evidence (x12 campaign).

Adjudicates the x11-killed frontier designs against the now-available tape10
native-d2x receipts under the gates FROZEN FIRST in
x10_dossier/x12_frontier_prereg.md (2026-06-12T15:54Z):

  C1  x12_c1_d2x_p16_rs223     the RS223 "16 clean carriers" lead (5247.1)
  C2  x12_c2_d2x_p22_rs191     full-grid RS191 (6179.4)
  C3  x12_c3_dbpsk_p12_ext     DBPSK ext-band probe (8 rule-picked mids + 4 ext bins)
  C4  x12_c4_stable_set_sweep  any P23+/denser variant tape10 justifies (exhaustive)

GATES (frozen, see prereg): G_A2 two-capture (t9 AND t10) per-carrier margin
>= 15 deg DQPSK / >= 30 deg DBPSK (m8 advisory only); G_C2 worst-capture
byte-ER <= [0.6*(255-k)/510]/1.5; G_D2 banker floor > 5791.2 (standing record);
G_E2 ext bins = probe class, two-model predicted-p90 rule; SER90 exponential
tail rule; C3 rate by frozen max-k rule.  The carrier arithmetic re-gates
PUBLISHED receipts (disclosed); the sim screen + self-check run post-freeze.

Stages (checkpoint results/x12_frontier_regate.json; reruns skip done work):
    OPENBLAS_NUM_THREADS=2 python3 x12_frontier_regate.py prereg
    ... adjudicate          (deterministic arithmetic on frozen receipts)
    ... simgate [--workers 4]   (8-seed blocking screen on the built C3 section)
    ... final               (collect selfcheck+simgate, set print authorization)
Frozen files imported verbatim, never edited.  Deterministic except channel_v2
seeds (logged).  Every CRC32 acceptance trial is counted into the ledger.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import sys
import time

import numpy as np

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from x11_frontier_probe import _best_branch_table       # noqa: E402  (frozen)

RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "x12_frontier_regate.json"
T9_JSON = RESULTS / "x11_frontier_margins.json"
T10_JSON = RESULTS / "x12_tape10_margins.json"
T10_DECODE_JSON = RESULTS / "x11_decode_results_tape10_run1.json"
PREREG_MD = _HERE / "x10_dossier" / "x12_frontier_prereg.md"

RECORD_BPS = 5791.1764705882354          # m10_r8, byte-exact on tape10 (standing)
SYM_RATE = 48000.0 / 256.0               # 187.5 sym/s (d2x geometry)
DQPSK_REF_DEG = 15.0
DBPSK_REF_DEG = 30.0                     # equal fractional headroom (15/45 = 30/90)
EXT_BINS = (9375.0, 9750.0, 10125.0, 10500.0)
PILOT_HZ = 4875.0
GRID_FULL = [750.0 + 375.0 * i for i in range(27)]      # 750..10500
C1_MEMBERS = [1125.0, 1500.0, 1875.0, 2250.0, 3000.0, 3375.0, 4125.0, 5250.0,
              6000.0, 6375.0, 7125.0, 7500.0, 7875.0, 8250.0, 8625.0, 9000.0]
C3_P = 12
C3_OFFSET = 16384
C3_ORIG_BYTES = 2048
RATE_KS = (127, 159, 179, 191)
SWEEP_KS = (127, 159, 179, 191, 223, 239)
SEEDS_NOM = list(range(8))
SEEDS_AAC = list(range(4))
NOMINAL_DG = 0.58

FROZEN_UTC = "2026-06-12T15:54:06Z"      # prereg doc freeze (written first)


def cap(k: int) -> float:
    return 0.6 * (255 - k) / 510.0


def _ckpt() -> dict:
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    return {"campaign": "x12-frontier-regate", "stages": {}}


def _save(out: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))


def _byte_er(sers, bits_per_carrier):
    """mean over carriers of 1-(1-SER)^(8/bits): the frozen G_C convention
    (column interleave equalizes codewords -> mean granularity)."""
    return float(np.mean([1.0 - (1.0 - s) ** (8 // b)
                          for s, b in zip(sers, bits_per_carrier)]))


def _ser90(p90: float, lam: float) -> float:
    if p90 >= 90.0:
        return 0.5
    return float(min(0.5, 0.10 * math.exp(-(90.0 - p90) / max(lam, 1e-6))))


# ===========================================================================
def stage_prereg():
    out = _ckpt()
    if "prereg" in out:
        print("[prereg] already frozen")
        return
    assert PREREG_MD.exists(), "prereg doc must exist BEFORE this stage"
    out["prereg"] = {
        "campaign": "x12-frontier-regate",
        "frozen_utc": FROZEN_UTC,
        "stage_recorded_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "doc": str(PREREG_MD.relative_to(_HERE)),
        "doc_sha256": __import__("hashlib").sha256(
            PREREG_MD.read_bytes()).hexdigest(),
        "record_floor_bps": RECORD_BPS,
        "gates": {
            "G_A2": "two-capture per-carrier rule: margin >= 15 deg (DQPSK, "
                    "45-deg boundary) / 90-p90 >= 30 deg (DBPSK, 90-deg "
                    "boundary) on BOTH tape9 AND tape10 best sanctioned "
                    "branch; m8 advisory only (demotion rationale in doc)",
            "G_C2": "worst-of-two-captures byte-ER <= [0.6*(255-k)/510]/1.5; "
                    "byte-ER = mean over used carriers of 1-(1-SER)^(8/bits)",
            "G_D2": "banker floor: projected net > 5791.2 bps (standing "
                    "record); probes exempt with pre-stated evidence purpose",
            "G_E2": ">9 kHz bins: probe class regardless; predicted p90 from "
                    "BOTH ext models (tape9 fit AND tape10 refit) under the "
                    "G_A2 boundary rule",
            "ser90_tail": "SER90 = min(.5, .10*exp(-(90-p90)/lam)), lam = "
                          "(p99-p90)/ln10; ext bins borrow lam from the same "
                          "capture's 9000 Hz carrier",
            "rate_rule_c3": "k* = max{k in 127/159/179/191: byte-ER_worst <= "
                            "cap(k)/1.5}; none -> KILL",
            "derate": "G_A2-failing carriers drop, candidate re-derives, RS k "
                      "fixed (C1/C2/C4); banker re-derived <= 5791.2 -> KILL",
            "sim_blocking": "B1x ext-bin IMD median SER > max(.10, 3x mid-8 "
                            "median); B3x AAC median(aac s0-3) > max(.10, 3x "
                            "nominal s0-3) per ext bin; placement = no-channel "
                            "self-check byte+orig-exact, 0 misc, canary "
                            "byte-identity asserts; prediction-only axes "
                            "(absolute g1/g5, timing, density) NEVER a cut; "
                            "8-seed flag holds print=false pending 16-seed "
                            "confirm",
            "canary_rule": "2572 anchor + 4910 d2x banker byte-identical m10 "
                           "reuse MANDATORY; tape pass valid iff both "
                           "orig-exact",
            "crc_budget": "campaign false-accept budget < 1e-4",
        },
        "candidates": {
            "x12_c1_d2x_p16_rs223": {
                "tier": "banker", "kind": "dense2x_drop", "P": 16, "rs_k": 223,
                "members_hz": C1_MEMBERS,
                "design_net_bps": 16 * 2 * SYM_RATE * 223 / 255,
                "origin": "x11 dossier post-hoc lead (5247, 1.59x paper margin)"},
            "x12_c2_d2x_p22_rs191": {
                "tier": "banker", "kind": "dense2x", "P": 22, "rs_k": 191,
                "design_net_bps": 22 * 2 * SYM_RATE * 191 / 255,
                "origin": "x11 excluded design (kept-bad-carrier arithmetic), "
                          "re-tried because tape10 landed r8 via rescue"},
            "x12_c3_dbpsk_p12_ext": {
                "tier": "probe", "kind": "dbpsk_drop", "P": C3_P,
                "rs_k": "rate rule", "ext_bins_hz": list(EXT_BINS),
                "mid8_rule": "8 largest min(margin_t9, margin_t10) DQPSK "
                             "carriers, ties to lower f",
                "offset": C3_OFFSET, "orig_bytes": C3_ORIG_BYTES,
                "purpose": "bank the >9 kHz DBPSK SER map + same-section "
                           "mid-band DBPSK control (the one open ext-band "
                           "axis after the DQPSK timing-death)"},
            "x12_c4_stable_set_sweep": {
                "tier": "banker-sweep",
                "rule": "S* = {f: min(margin_t9,t10) >= 15}; k in "
                        f"{list(SWEEP_KS)}; GO iff net > floor AND G_C2; plus "
                        "DQPSK ext re-add and 4500 re-add checks"},
        },
        "disclosure": "t9/t10 margin+SER receipts were PUBLISHED before this "
                      "freeze; carrier arithmetic is a re-adjudication of "
                      "existing receipts under rules fixed here. New "
                      "post-freeze measurements: sim screen, self-check, "
                      "future tape pass.",
    }
    _save(out)
    print(f"[prereg] frozen block recorded (doc sha "
          f"{out['prereg']['doc_sha256'][:12]}...)")


# ===========================================================================
def _evidence():
    t9 = json.loads(T9_JSON.read_text())
    t10 = json.loads(T10_JSON.read_text())
    b9 = {b["freq_hz"]: b for b in
          _best_branch_table(t9["stages"]["quantiles_tape9"]) if b}
    bm8 = {b["freq_hz"]: b for b in
           _best_branch_table(t9["stages"]["quantiles_m8tape"]) if b}
    b10 = {b["freq_hz"]: b for b in _best_branch_table(
        t10["stages"]["quantiles_tape10_m10_r8_d2x_p22_rs179"]) if b}
    ext9 = {r["freq_hz"]: r for r in t9["stages"]["extbins"]["rows"]}
    ext10 = {r["freq_hz"]: r for r in t10["stages"]["extbins_tape10"]["rows"]}
    return b9, bm8, b10, ext9, ext10


def stage_adjudicate():
    out = _ckpt()
    assert "prereg" in out, "freeze prereg first"
    b9, bm8, b10, ext9, ext10 = _evidence()

    # ---- two-capture table (all 22 measured d2x carriers) ------------------
    table = []
    for f in sorted(b10):
        r9, r10 = b9.get(f), b10[f]
        row = {"freq_hz": f,
               "t9_margin_deg": r9["margin_deg"] if r9 else None,
               "t10_margin_deg": r10["margin_deg"],
               "min_margin_deg": (round(min(r9["margin_deg"],
                                            r10["margin_deg"]), 2)
                                  if r9 else None),
               "t9_ser": r9["ser"] if r9 else None, "t10_ser": r10["ser"],
               "worst_ser": (max(r9["ser"], r10["ser"]) if r9
                             else r10["ser"]),
               "m8_margin_deg_advisory": (bm8[f]["margin_deg"]
                                          if f in bm8 else None),
               "pass_G_A2_dqpsk": bool(r9 and min(r9["margin_deg"],
                                                  r10["margin_deg"])
                                       >= DQPSK_REF_DEG)}
        table.append(row)
    stable = [r["freq_hz"] for r in table if r["pass_G_A2_dqpsk"]]
    worst_ser = {r["freq_hz"]: r["worst_ser"] for r in table}
    minmarg = {r["freq_hz"]: r["min_margin_deg"] for r in table}

    adj = {"two_capture_table": table,
           "stable_set_S_star": stable,
           "n_stable": len(stable),
           "per_candidate": {}}

    # ---- C1: RS223 on the frozen 16-carrier set ----------------------------
    fails = [f for f in C1_MEMBERS if minmarg.get(f) is None
             or minmarg[f] < DQPSK_REF_DEG]
    sers1 = [worst_ser[f] for f in C1_MEMBERS]
    be1 = _byte_er(sers1, [2] * len(sers1))
    net1 = 16 * 2 * SYM_RATE * 223 / 255
    derP = 16 - len(fails)
    der_net = derP * 2 * SYM_RATE * 223 / 255
    adj["per_candidate"]["x12_c1_d2x_p16_rs223"] = {
        "design_net_bps": round(net1, 1),
        "G_A2": {"pass": not fails, "failing_carriers_hz": fails,
                 "failing_min_margins": [minmarg.get(f) for f in fails]},
        "G_C2": {"byte_er_worst_capture": round(be1, 4),
                 "threshold_cap_over_1p5": round(cap(223) / 1.5, 4),
                 "pass": be1 <= cap(223) / 1.5},
        "G_D2": {"pass": net1 > RECORD_BPS,
                 "note": f"design net {net1:.1f} <= standing record "
                         f"{RECORD_BPS:.1f} -- dead on arrival as a banker"},
        "derate": {"P_after_G_A2": derP, "net_after_derate": round(der_net, 1)},
        "verdict": "KILL",
        "why": "fails G_D2 outright (the lead predates the 5791 landing); "
               "ALSO fails G_A2 (the '16 clean carriers' are not stable on "
               "tape10) and G_C2 -- the thin-margin set does not exist as a "
               "two-capture object",
    }

    # ---- C2: full-grid P22 RS191 -------------------------------------------
    p22 = sorted(b10)
    sers2 = [worst_ser[f] for f in p22]
    be2 = _byte_er(sers2, [2] * len(sers2))
    net2 = 22 * 2 * SYM_RATE * 191 / 255
    t10d = json.loads(T10_DECODE_JSON.read_text())
    r8 = next(r for r in t10d["payloads"] if r["name"] == "m10_r8_d2x_p22_rs179")
    resc = r8["x11_rescue"]
    pub = json.loads(T10_JSON.read_text())["stages"]["delta"][
        "byte_er_projections_tape10"]
    adj["per_candidate"]["x12_c2_d2x_p22_rs191"] = {
        "design_net_bps": round(net2, 1),
        "G_D2": {"pass": net2 > RECORD_BPS},
        "G_C2": {"byte_er_worst_capture": round(be2, 4),
                 "published_t10_projection": pub["P22_full_grid"],
                 "raw_cap": round(cap(191), 4),
                 "threshold_cap_over_1p5": round(cap(191) / 1.5, 4),
                 "pass": be2 <= cap(191) / 1.5},
        "rescue_dependence": {
            "demonstrated_at_rs179_tape10": {
                "n_codewords": 64,
                "pass1_failed": len(resc["pass1_failed_idx"]),
                "filled_by_sweep": len(resc["filled_by_sweep"]),
                "filled_by_erasure_ladder": len(resc["after_sweep_failed_idx"])},
            "note": "RS191 has LESS correction (t=32 vs 38) while the same "
                    "grid's worst-capture byte-ER exceeds even the RAW cap "
                    "(no 1.5 margin); best-19-carrier subset 0.0845 and "
                    "best-16 0.0549 are published -- 0.0845 > cap(191) "
                    f"{cap(191):.4f}; a P19@191 variant fails on tape10 too"},
        "verdict": "KILL",
        "why": "G_C2 fails by >2x at the banker rule and >1.7x at the raw "
               "cap; printing a rung whose arithmetic REQUIRES the rescue "
               "ceiling from day one banks nothing the proven r8 path "
               "doesn't already bank",
    }

    # ---- C3: DBPSK ext-band probe ------------------------------------------
    mids = sorted([f for f in minmarg if minmarg[f] is not None],
                  key=lambda f: (-minmarg[f], f))[:8]
    mids = sorted(mids)
    lam9 = (b9[9000.0]["p99_deg"] - b9[9000.0]["p90_deg"]) / math.log(10)
    lam10 = (b10[9000.0]["p99_deg"] - b10[9000.0]["p90_deg"]) / math.log(10)
    ser_tab, marg_tab = [], []
    for f in mids:
        e = {"freq_hz": f, "class": "mid (measured both captures)"}
        for tag, bb in (("t9", b9), ("t10", b10)):
            p90, p99 = bb[f]["p90_deg"], bb[f]["p99_deg"]
            lam = (p99 - p90) / math.log(10)
            e[f"{tag}_p90_deg"] = p90
            e[f"{tag}_dbpsk_margin_deg"] = round(90.0 - p90, 2)
            e[f"{tag}_ser90"] = _ser90(p90, lam)
        e["m8_dbpsk_margin_advisory"] = (round(90.0 - bm8[f]["p90_deg"], 2)
                                         if f in bm8 else None)
        e["pass_G_A2_dbpsk"] = (e["t9_dbpsk_margin_deg"] >= DBPSK_REF_DEG and
                                e["t10_dbpsk_margin_deg"] >= DBPSK_REF_DEG)
        ser_tab.append(e)
    for f in EXT_BINS:
        p9 = 45.0 - ext9[f]["margin_pred_deg"]
        p10 = ext10[f]["p90_pred_deg"]
        e = {"freq_hz": f, "class": "ext (model-predicted, G_E2 probe)",
             "t9_p90_deg": round(p9, 2), "t10_p90_deg": p10,
             "t9_dbpsk_margin_deg": round(90.0 - p9, 2),
             "t10_dbpsk_margin_deg": round(90.0 - p10, 2),
             "t9_ser90": _ser90(p9, lam9), "t10_ser90": _ser90(p10, lam10),
             "pass_G_A2_dbpsk": (90.0 - p9 >= DBPSK_REF_DEG and
                                 90.0 - p10 >= DBPSK_REF_DEG)}
        ser_tab.append(e)
    used = mids + list(EXT_BINS)
    ga2_fail = [e["freq_hz"] for e in ser_tab if not e["pass_G_A2_dbpsk"]]
    be3 = {tag: _byte_er([e[f"{tag}_ser90"] for e in ser_tab],
                         [1] * len(ser_tab)) for tag in ("t9", "t10")}
    be3_worst = max(be3.values())
    k_star = None
    for k in sorted(RATE_KS, reverse=True):
        if be3_worst <= cap(k) / 1.5:
            k_star = k
            break
    drops = [f for f in GRID_FULL if f != PILOT_HZ and f not in used]
    go3 = (not ga2_fail) and (k_star is not None)
    net3 = (C3_P * SYM_RATE * k_star / 255) if k_star else None
    adj["per_candidate"]["x12_c3_dbpsk_p12_ext"] = {
        "tier": "probe (G_E2: ext bins have no real-capture modem evidence)",
        "mid8_by_frozen_rule": mids,
        "drop_freqs_hz": drops,
        "pilot_hz": PILOT_HZ,
        "lam_tail_deg": {"t9_from_9000": round(lam9, 2),
                         "t10_from_9000": round(lam10, 2)},
        "carrier_table": ser_tab,
        "G_A2_dbpsk": {"pass": not ga2_fail, "failing": ga2_fail,
                       "threshold_deg": DBPSK_REF_DEG},
        "G_C2": {"byte_er_pred": {t: round(v, 4) for t, v in be3.items()},
                 "worst": round(be3_worst, 4),
                 "rate_rule_k_star": k_star,
                 "caps_over_1p5": {k: round(cap(k) / 1.5, 4)
                                   for k in RATE_KS},
                 "pass": k_star is not None},
        "design_net_bps": round(net3, 1) if net3 else None,
        "verdict": "GO (probe)" if go3 else "KILL",
        "why": ("all 12 carriers clear the 30-deg two-column DBPSK rule "
                "(worst ext margin is t10's; the t10 refit is conservative -- "
                "its c1 is inflated by the 9000 Hz ref collapse) and the "
                "SER90 budget clears the frozen rate rule"
                if go3 else "frozen gate failed -- see fields"),
        "pending": "build + no-channel self-check + 8-seed blocking screen "
                   "(B1x/B3x) before print authorization",
    }

    # ---- C4: exhaustive stable-set sweep + re-add checks --------------------
    sweep = []
    sersS = [worst_ser[f] for f in stable]
    beS = _byte_er(sersS, [2] * len(sersS)) if stable else 1.0
    for k in SWEEP_KS:
        net = len(stable) * 2 * SYM_RATE * k / 255
        sweep.append({"rs_k": k, "net_bps": round(net, 1),
                      "byte_er_worst": round(beS, 4),
                      "cap_over_1p5": round(cap(k) / 1.5, 4),
                      "G_C2_pass": beS <= cap(k) / 1.5,
                      "G_D2_pass": net > RECORD_BPS,
                      "GO": beS <= cap(k) / 1.5 and net > RECORD_BPS})
    ext_dqpsk_readd = {f: {"t9_margin_pred": ext9[f]["margin_pred_deg"],
                           "t10_margin_pred": ext10[f]["margin_pred_deg"],
                           "pass_15deg_both": ext9[f]["margin_pred_deg"] >= 15
                           and ext10[f]["margin_pred_deg"] >= 15}
                      for f in EXT_BINS}
    f4500 = next(r for r in table if r["freq_hz"] == 4500.0)
    adj["per_candidate"]["x12_c4_stable_set_sweep"] = {
        "stable_set": stable, "n": len(stable),
        "byte_er_worst_capture": round(beS, 4),
        "sweep": sweep,
        "ext_dqpsk_readd": ext_dqpsk_readd,
        "readd_4500": {"t9_margin": f4500["t9_margin_deg"],
                       "t10_margin": f4500["t10_margin_deg"],
                       "pass_G_A2": f4500["pass_G_A2_dqpsk"],
                       "note": "notch MIGRATED (t10 +19) but t9 kills it -- "
                               "exactly the volatility the two-capture rule "
                               "exists to catch"},
        "any_GO": any(r["GO"] for r in sweep),
        "verdict": "KILL" if not any(r["GO"] for r in sweep) else "GO",
        "why": "no RS rate turns the two-capture-stable set into a banker "
               "above the 5791 floor; no ext bin or dropped carrier "
               "re-qualifies at 15 deg on both captures",
    }

    # ---- x11 trio re-verdict rows (rate floor moved past them) -------------
    adj["x11_reverdicts"] = {
        n: {"design_net_bps": v, "standing": "KILL (x11 margin gate)",
            "additionally": f"net {v} <= new floor {RECORD_BPS:.1f} (G_D2)"}
        for n, v in (("x11_f1_d2x_p19_rs179", 5001.5),
                     ("x11_f2_d2x_p19_rs191", 5336.8),
                     ("x11_f3_d2xx_p23_rs127_extband", 4295.6))}

    out["stages"]["adjudication"] = adj
    _save(out)
    for name, c in adj["per_candidate"].items():
        print(f"  {name:28s} -> {c['verdict']}")
    print(f"[adjudicate] stable set n={len(stable)}; -> {OUT_JSON.name}")


# ===========================================================================
# sim pre-gate (blocking axes only) -- runs on the BUILT C3 section
# ===========================================================================
def _run_sim_cell(args):
    sec_name, seed, aac = args
    import warnings
    warnings.filterwarnings("ignore")
    import m3_codec as codec
    from m3_codec import Rung
    import sim_v2
    from h4_dqpsk import build_section, PAD_LO_S, PAD_HI_S, FS
    from m9_decode import _rs_merge_guarded, _per_carrier_ser, _better, \
        _nominal_frame_bits
    from x12_regate_master import (MANIFEST_PATH, make_scheme_x12,
                                   dbpsk_frontends)

    t0 = time.time()
    manifest = json.loads(MANIFEST_PATH.read_text())
    sec = next(s for s in manifest["ws_payloads"] if s["name"] == sec_name)
    sch_tx = make_scheme_x12({"kind": sec["kind"], **sec["dqpsk_params"]})
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected, rung)
    frame_audios = [np.asarray(sch_tx.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)
    y = np.asarray(sim_v2.channel_v2(section, profile="tape7", aac=bool(aac),
                                     seed_offset=int(seed),
                                     sim_overrides={"diffuse_gain": NOMINAL_DG}),
                   np.float64)
    nom_bits = _nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    crc_trials = 0
    best = None
    for fe_name, fe in dbpsk_frontends(sec):
        rx = []
        for fi, st in enumerate(starts):
            nd = sch_tx.nsym_data(nom_bits[fi])
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(y), st + len(frame_audios[fi]) + pad_hi)
            bits, _diag = fe(y[w_lo:w_hi], nd)
            rx.append(np.asarray(bits, np.uint8))
        outb, cwf, misc, _ = _rs_merge_guarded(rx, meta, crc_table,
                                               erase_frac=0.0, rel_cw=None)
        crc_trials += meta["n_codewords"]
        exact = outb == expected
        berr = sum(a != b for a, b in zip(outb, expected)) + abs(
            len(outb) - len(expected))
        att = {"front_end": fe_name, "byte_exact": exact, "cw_failed": cwf,
               "miscorrected": misc, "byte_errors": berr, "_rx": rx}
        if best is None or _better(att, best):
            best = att
        if exact:
            break
    pcs = _per_carrier_ser(best["_rx"], sec, sch_tx, expected)
    return {"seed": int(seed), "aac": bool(aac),
            "byte_exact": bool(best["byte_exact"]),
            "cw_failed": int(best["cw_failed"]),
            "n_codewords": meta["n_codewords"],
            "miscorrected": int(best["miscorrected"]),
            "byte_error_rate": round(best["byte_errors"] / max(1, len(expected)), 5),
            "front_end": best["front_end"], "crc_trials": int(crc_trials),
            "per_carrier_ser": pcs,
            "carrier_freqs_hz": sec.get("carrier_freqs_hz"),
            "wall_s": round(time.time() - t0, 1)}


def stage_simgate(workers: int = 4):
    out = _ckpt()
    adj = out["stages"].get("adjudication")
    assert adj, "run adjudicate first"
    c3 = adj["per_candidate"]["x12_c3_dbpsk_p12_ext"]
    if not c3["verdict"].startswith("GO"):
        print("[simgate] C3 not GO -- nothing to screen")
        return
    st = out["stages"].setdefault("simgate", {"cells": {}})
    todo = [("x12_c3_dbpsk_p12_ext", s, False) for s in SEEDS_NOM] + \
           [("x12_c3_dbpsk_p12_ext", s, True) for s in SEEDS_AAC]
    todo = [t for t in todo
            if f"{'aac' if t[2] else 'nom'}|s{t[1]}" not in st["cells"]]
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_sim_cell, t): t for t in todo}
        for fu in as_completed(futs):
            r = fu.result()
            key = f"{'aac' if r['aac'] else 'nom'}|s{r['seed']}"
            st["cells"][key] = r
            print(f"  [{key:8s}] exact={r['byte_exact']} cw={r['cw_failed']}/"
                  f"{r['n_codewords']} fe={r['front_end']} "
                  f"({r['wall_s']}s)", flush=True)
            _save(out)

    # ---- blocking adjudication (frozen B1x/B3x) ----------------------------
    freqs = st["cells"]["nom|s0"]["carrier_freqs_hz"]
    mids = adj["per_candidate"]["x12_c3_dbpsk_p12_ext"]["mid8_by_frozen_rule"]
    mid_idx = [i for i, f in enumerate(freqs) if f in mids]
    ext_idx = [i for i, f in enumerate(freqs) if f in EXT_BINS]

    def med_ser(keys, idx):
        return float(np.median([st["cells"][k]["per_carrier_ser"][idx]
                                for k in keys]))

    nom_keys = [f"nom|s{s}" for s in SEEDS_NOM]
    nom03 = [f"nom|s{s}" for s in SEEDS_AAC]
    aac_keys = [f"aac|s{s}" for s in SEEDS_AAC]
    mid_med = float(np.median(
        [np.median([st["cells"][k]["per_carrier_ser"][i] for i in mid_idx])
         for k in nom_keys]))
    b1 = {}
    for i in ext_idx:
        m = med_ser(nom_keys, i)
        thr = max(0.10, 3 * mid_med)
        b1[str(int(freqs[i]))] = {"median_ser_nom": round(m, 4),
                                  "threshold": round(thr, 4),
                                  "flag": m > thr}
    b3 = {}
    for i in ext_idx:
        ma, mn = med_ser(aac_keys, i), med_ser(nom03, i)
        thr = max(0.10, 3 * mn)
        b3[str(int(freqs[i]))] = {"median_ser_aac": round(ma, 4),
                                  "median_ser_nom_s0_3": round(mn, 4),
                                  "threshold": round(thr, 4),
                                  "flag": ma > thr}
    g1 = sum(st["cells"][k]["byte_exact"] for k in nom_keys)
    st["adjudication"] = {
        "B1x_ext_imd": b1, "B3x_aac_delta": b3,
        "mid8_median_ser_nom": round(mid_med, 4),
        "any_blocking_flag": any(v["flag"] for v in b1.values())
        or any(v["flag"] for v in b3.values()),
        "g1_nominal_prediction_only": f"{g1}/8 (logged, never a cut)",
        "crc_trials_total": sum(st["cells"][k]["crc_trials"]
                                for k in st["cells"]),
        "miscorrected_total": sum(st["cells"][k]["miscorrected"]
                                  for k in st["cells"]),
    }
    _save(out)
    print(f"[simgate] blocking flag={st['adjudication']['any_blocking_flag']} "
          f"g1={g1}/8 (prediction-only) -> {OUT_JSON.name}")


# ===========================================================================
def stage_final():
    out = _ckpt()
    adj = out["stages"].get("adjudication")
    sim = out["stages"].get("simgate", {}).get("adjudication")
    sc_path = RESULTS / "x12_regate_results_selfcheck_nochan.json"
    sc = json.loads(sc_path.read_text()) if sc_path.exists() else None
    c3 = adj["per_candidate"]["x12_c3_dbpsk_p12_ext"]
    go3 = c3["verdict"].startswith("GO")
    sc_ok = bool(sc and sc["n_byte_exact_packed"] == sc["n_payloads"]
                 and sc["n_orig_exact"] == sc["n_payloads"]
                 and sc["miscorrected_total"] == 0)
    sim_ok = bool(sim and not sim["any_blocking_flag"])
    print_auth = bool(go3 and sc_ok and sim_ok)

    crc_total = (sim["crc_trials_total"] if sim else 0) + \
        (sc["crc_trial_ledger"]["crc_trials"] if sc else 0)
    fa = crc_total * 2.0 ** -32
    out["stages"]["final"] = {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verdicts": {n: c["verdict"]
                     for n, c in adj["per_candidate"].items()},
        "selfcheck_clean": sc_ok,
        "sim_blocking_clean": sim_ok,
        "print_authorized": print_auth,
        "ship_thresholds": {
            "tape_pass_valid": "anchor 2572 AND d2x 4910 canary orig-exact",
            "c3_success": "byte-exact AND orig-exact at the rate-rule k",
            "c3_partial": "per-carrier DBPSK SER table recovered (banks the "
                          "ext map either way; only byte-exact = "
                          "'DBPSK ext-band demonstrated')",
            "master12_hybrid_probe_eligible": "every ext bin real SER <= 0.0202",
            "master12_hybrid_stretch_eligible": "every ext bin real SER <= "
                                                "0.0117 (-> 6317.6 design net)",
        },
        "campaign_crc_ledger": {"crc_trials": crc_total,
                                "false_accept_bound": fa,
                                "budget": 1e-4,
                                "within_budget": bool(fa < 1e-4)},
    }
    _save(out)

    # patch manifest print flag (the builder wrote pending=false)
    man_path = _HERE / "x12_master_regate_manifest.json"
    if man_path.exists():
        man = json.loads(man_path.read_text())
        man["print_authorized"] = print_auth
        man["print_block_reason"] = (
            None if print_auth else
            "x12 frontier re-gate: gates/self-check/sim screen not all clean "
            "-- see results/x12_frontier_regate.json")
        man_path.write_text(json.dumps(man, indent=2, default=float))
    print(f"[final] verdicts={out['stages']['final']['verdicts']} "
          f"print_authorized={print_auth} fa_bound={fa:.2e}")


STAGES = {"prereg": stage_prereg, "adjudicate": stage_adjudicate,
          "simgate": stage_simgate, "final": stage_final}

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES))
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.stage == "simgate":
        stage_simgate(args.workers)
    else:
        STAGES[args.stage]()
