"""x11_frontier_probe.py -- x11-frontier per-carrier MARGIN measurement + gate.

GOAL (x11-frontier brief): design new rung candidates beyond the master10
ladder strictly from measured evidence.  This probe supplies deliverable (a):
a real-capture-anchored per-carrier margin table in DEGREES at the dense2x
geometry, with a pre-registered >=15 deg rule for every kept carrier.

WHAT IS NEW vs x10_b_aggr_05_dense2x_probe (which is imported, NOT edited):
the x10 probe recorded per-carrier SER and RMS phase error only.  RMS is
tail-dominated for carriers whose errors come in flutter bursts, so it cannot
support a *degree-margin* gate.  This probe re-runs the same stride-256
re-demodulation of the REAL tape9 m9_m8_dense375 section (and the independent
master8 capture) and collects the FULL |dphi error| distribution per carrier
per receiver branch -> empirical quantiles (p50/p90/p99/max).

MARGIN CONVENTION (frozen in PREREG below BEFORE the quantile stages run):
    margin_deg(k) = 45.0 - p90_emp(|dphi_err_k|)   [boundary view, best
                    branch within the SANCTIONED receiver branch set]
45 deg is the DQPSK decision boundary; p90 is the empirical 90th percentile
of |differential phase error| over all boundary symbols (errors included).
The byte-ER tail risk is gated separately (G-C, B-aggr-05 form).  Branch
selection per carrier is design-time evidence: the shipped receiver family
(m10 union + per-carrier late-window placement, G3-validated on tape9)
realizes per-carrier window/alpha/shift choices truth-free at decode time.

DISCLOSED PRIOR KNOWLEDGE (honesty): per-carrier SER and RMS at this geometry
were already published in results/x10_b_aggr_05_dense2x_probe.json before
this file was written.  The QUANTILES (p90/p99) -- the quantities the margin
gate actually adjudicates on -- have never been measured.  Thresholds were
frozen before any quantile was computed.

STAGES (checkpoint results/x11_frontier_margins.json; each stage < 8 min):
    prereg      freeze gates + candidate definitions (refuses if stages ran)
    quantiles   tape9 GOLD m9_m8_dense375 @ stride 256: 27 sanctioned
                branches x 22 data carriers -> empirical quantiles
    secondtape  independent master8 capture (m8_dq_p10n512_rs127, 750-step
                grid subset) -> cross-capture confirmation margins
    extbins     >9 kHz extension bins 9375/9750/10125/10500: PREDICTED p90
                from (i) timing-residual frequency scaling fitted on the
                measured high-band carriers and (ii) the real tape9 sounder
                SNR map (results/x10_headroom.json) -- prediction-class rows
    margins     adjudicate the frozen gates -> per-candidate margin tables
                + KILL/GO verdicts

Usage: OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
           python3 x11_frontier_probe.py <stage>
Deterministic (no RNG).
"""
from __future__ import annotations

import argparse
import datetime
import json
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

import m3_codec as codec                                   # noqa: E402
import m9_decode as m9d                                    # noqa: E402
import hyp_common as hc                                    # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S                # noqa: E402
# frozen x10 probe: imported VERBATIM (sync caches, DFT loop, decision math)
from x10_b_aggr_05_dense2x_probe import (                  # noqa: E402
    WIN_CFGS, _make_win, _load_tape9, _load_m8tape, _get_section, _tx_truth,
    _halfrate_dft, _decide, _expected_transitions, MANIFEST_T9, MANIFEST_M8,
)

SR = codec.FS
OUT_JSON = _HERE / "results" / "x11_frontier_margins.json"
HEADROOM_JSON = _HERE / "results" / "x10_headroom.json"

RECORD_BPS = 2572.06
SYM_RATE = 187.5            # dense2x N256 stride @48k
BITS_PER_CARRIER = 2        # DQPSK

# ---------------------------------------------------------------------------
# SANCTIONED receiver branch set (window x ema-alpha x window shift).  All
# realizable by the shipped m10-family receiver: union over windows/alphas +
# per-carrier late-window placement (truth-free EVM argmin, G3-validated).
# hann256 shifts >0 ingest next-symbol samples -- kept ONLY as the proven dc0
# late-window mechanism (x10: dc0 SER .355->.048 @ +48).
# ---------------------------------------------------------------------------
BRANCHES = (
    [("hann256_skip0", a, s) for a in (0.6, 0.7, 0.8) for s in (0, 48)]
    + [("rect128_skip64", a, s) for a in (0.6, 0.7, 0.8)
       for s in (-32, -16, 0, 16, 32, 48, 64)]
)

# ---------------------------------------------------------------------------
# Candidate rungs (frozen).  Geometry = the proven Dense2x family
# (DQPSK N256 spacing2 skip64, 375 Hz grid from 750 Hz, pilot 4875).
# net = P * 375 * rs_k / 255 bps.
# ---------------------------------------------------------------------------
CANDIDATES = {
    "x11_f1_d2x_p19_rs179": {
        "tier": "banker", "kind": "dense2x_drop", "P": 19, "rs_k": 179,
        "drop_freqs_hz": [750.0, 4500.0, 5625.0],
        "grid_max_hz": 9000.0, "offset": 59392, "orig_bytes": 12288,
        "net_bps": 19 * 375 * 179 / 255,        # 5001.5
        "rationale": "notch-free P19: drops the three carriers the x10 probe "
                     "measured bad (dc0 750 echo-ISI, 4500/5625 deck notches) "
                     "but keeps 1500/2625/6750/7875/9000 which RS(255,179) "
                     "absorbs; strictly better probe byte-ER margin than the "
                     "r6 banker (pred 0.037 vs 0.079) at HIGHER net "
                     "(5001 vs 4910)."},
    "x11_f2_d2x_p19_rs191": {
        "tier": "banker", "kind": "dense2x_drop", "P": 19, "rs_k": 191,
        "drop_freqs_hz": [750.0, 4500.0, 5625.0],
        "grid_max_hz": 9000.0, "offset": 71680, "orig_bytes": 12288,
        "net_bps": 19 * 375 * 191 / 255,        # 5336.8
        "rationale": "same notch-free geometry at RS(255,191): beats r8's "
                     "code-rate risk profile by dropping the measured-bad "
                     "carriers instead of keeping the full grid."},
    "x11_f3_d2xx_p23_rs127_extband": {
        "tier": "probe", "kind": "dense2x_drop", "P": 23, "rs_k": 127,
        "drop_freqs_hz": [750.0, 4500.0, 5625.0],
        "grid_max_hz": 10500.0, "offset": 0, "orig_bytes": 12288,
        "net_bps": 23 * 375 * 127 / 255,        # 4296.0
        "new_bins_hz": [9375.0, 9750.0, 10125.0, 10500.0],
        "rationale": "band extension past 9 kHz on the same 375 Hz grid "
                     "(toneplan-v2 sim-cleared 9750/10500; headroom map shows "
                     "usable SNR to 11 kHz).  RS127 derate, PROBE class: the "
                     "new bins have no modem evidence on any real capture, so "
                     "no banker claim regardless of margins; lands 4296 if it "
                     "decodes and yields the >9 kHz per-carrier SER map that "
                     "designs master12 either way."},
}

PREREG = {
    "campaign": "x11-frontier",
    "frozen_utc": None,
    "margin_metric": "margin_deg(k) = 45.0 - p90_emp(|dphi_err_k| deg), "
                     "boundary view, best branch within the sanctioned set",
    "sanctioned_branches": [list(map(str, b)) for b in BRANCHES],
    "gates": {
        "G_A_per_carrier": "every carrier KEPT by a candidate must show "
                           "tape9 margin_deg >= 15.0 at its best sanctioned "
                           "branch",
        "G_B_cross_capture": "kept carriers with master8-capture evidence "
                             "(750-step subset) must show m8 margin_deg >= "
                             "10.0 (looser: independent tape, documented "
                             "carrier-quality migration); carriers without "
                             "m8 evidence are tape9-only and logged as such",
        "G_C_byte_er": "rung predicted byte_ER (best-branch per-carrier SERs, "
                       "mean(1-(1-SER)^4)) <= [0.6*(255-k)/510] / 1.5  "
                       "(>=1.5x margin factor -- stricter than the r6 "
                       "banker's 1.43x, which the ship report flags as thin)",
        "G_D_rate": "banker qualification requires projected net > 4910 bps; "
                    "probe rungs qualify at any rate",
        "G_E_new_bins": "extension bins (no modem evidence) use the PREDICTED "
                        "p90 from the frozen extbins model; predicted margin "
                        ">= 15.0 required to keep a new bin in F3, else the "
                        "bin is dropped and F3 re-derives (P and net shrink); "
                        "F3 remains probe-class regardless",
        "derate_rule": "if a kept carrier fails G_A/G_B it is dropped and the "
                       "candidate re-derives (P, net shrink; RS k is FIXED "
                       "per candidate -- no post-hoc code-rate softening); "
                       "a banker whose re-derived net <= 4910 is KILLED",
    },
    "extbins_model": "p90_pred(f) = sqrt( (c1*f)^2 + c0^2 + "
                     "max(0, sn(f)^2 - sn_ref^2) ) with (c0,c1) least-squares "
                     "fitted on the measured best-branch p90 of the clean "
                     "high-band reference carriers f in {6375,7125,7500,8250,"
                     "8625,9000}; sn(f) = (180/pi)/sqrt(SNR375_lin(f)) from "
                     "the tape9 sounder table (dB-interpolated), sn_ref = "
                     "median sn over the reference carriers",
    "disclosure": "per-carrier SER/RMS at this geometry were already "
                  "published (x10 dense2x probe) before this file existed; "
                  "the p90/p99 quantiles adjudicated here are NEW "
                  "measurements; thresholds frozen before any quantile ran",
    "excluded_designs": {
        "d2x_p21_rs191_or_p22_rs191": "keeps measured-bad carriers at lower "
                                      "redundancy: probe byte-ER 0.079 vs "
                                      "RS191 cap 0.0753 -> <1x margin, killed "
                                      "by arithmetic before any new data",
        "d8psk_mixed_constellation": "x10 bitload census KILL stands: 0 "
                                     "carriers passed the frozen 3-bit rule "
                                     "on BOTH captures at N512; d2x geometry "
                                     "is strictly noisier per symbol",
        "d3x_n128": "375 Hz = 1 bin at Nw=128 -> rect-only orthogonality "
                    "with zero guard; the x10 probe measured the no-guard "
                    "window class at 49-63% SER (non-orthogonal hann) and "
                    "the echo tail extends past 1.33 ms; no evidence path",
        "d2p5x": "no integer N gives 375 Hz-grid orthogonality at 2.5x "
                 "(N=204.8); geometry impossible without abandoning the "
                 "proven grid",
    },
    "candidates": None,   # filled from CANDIDATES at freeze time
}

QUANTS = (50, 90, 99)


# ===========================================================================
def _ckpt() -> dict:
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    return {"campaign": "x11-frontier", "prereg": None, "stages": {}}


def _save(out: dict) -> None:
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))


# ===========================================================================
# quantile collector: same frame loop as the x10 probe's _section_halfrate
# but accumulates the FULL per-carrier |gerr| sample set on boundary windows.
# ===========================================================================
def _section_gerr_samples(audio_nom, align, sec, sch, R, Nw, skip_w, alpha,
                          shift, win):
    meta = sec["meta"]
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    tq_frames = _tx_truth(sec, sch)
    P = sch.P
    gabs = [[] for _ in range(P)]      # per-carrier |gerr| deg, boundary only
    err = np.zeros(P, int)
    tot = 0
    for fi, st in enumerate(sec["frame_starts"]):
        nb = nom_bits[fi]
        nd = sch.nsym_data(nb)
        total = nd + 1
        st = int(st) + align
        w_lo = max(0, int(st - pad_lo))
        w_hi = min(len(audio_nom), int(st + flen_full + pad_hi))
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
        c, dtau, _raw = _halfrate_dft(y, ds, total, sch, R, Nw, skip_w,
                                      alpha, shift, win=win)
        q, dphi, _dd = _decide(sch, c, dtau)
        tq = tq_frames[fi]
        exp_q, is_b = _expected_transitions(tq, R, total)
        gerr = (dphi - exp_q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        e = q != exp_q
        err += e[is_b].sum(axis=0)
        tot += int(is_b.sum())
        gb = np.degrees(np.abs(gerr[is_b]))
        for k in range(P):
            gabs[k].append(gb[:, k])
    stats = []
    for k in range(P):
        a = np.concatenate(gabs[k]) if gabs[k] else np.zeros(0)
        row = {"n": int(a.size),
               "ser": round(float(err[k]) / max(1, tot), 5),
               "rms_deg": round(float(np.sqrt(np.mean(a ** 2))), 2) if a.size else None,
               "max_deg": round(float(a.max()), 2) if a.size else None}
        for qq in QUANTS:
            row[f"p{qq}_deg"] = (round(float(np.percentile(a, qq)), 2)
                                 if a.size else None)
        stats.append(row)
    return stats


def _run_branches(audio_nom, align, sec, sch, branches):
    out = {}
    for cfg_name, alpha, shift in branches:
        cfg = WIN_CFGS[cfg_name]
        if cfg["skip"] + shift < 0:
            continue
        win = _make_win(cfg)
        t0 = time.time()
        stats = _section_gerr_samples(audio_nom, align, sec, sch, 2,
                                      cfg["Nw"], cfg["skip"], alpha, shift, win)
        key = f"{cfg_name}|a{alpha}|s{shift:+d}"
        out[key] = {"config": cfg_name, "alpha": alpha, "shift": shift,
                    "per_carrier": stats}
        mean_ser = float(np.mean([r["ser"] for r in stats]))
        print(f"  [{key:28s}] meanSER={mean_ser:.4f} ({time.time()-t0:.1f}s)",
              flush=True)
    return out


# ===========================================================================
def stage_prereg():
    out = _ckpt()
    if out.get("prereg"):
        print(f"[prereg] already frozen at {out['prereg']['frozen_utc']}")
        return
    if out.get("stages"):
        raise RuntimeError("measurement stages exist without prereg -- abort")
    pr = dict(PREREG)
    pr["frozen_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pr["candidates"] = CANDIDATES
    out["prereg"] = pr
    _save(out)
    print(f"[prereg] FROZEN {pr['frozen_utc']} -> {OUT_JSON.name}")
    for name, c in CANDIDATES.items():
        print(f"  {name:34s} tier={c['tier']:7s} P={c['P']} RS(255,{c['rs_k']})"
              f" net={c['net_bps']:.1f} (x{c['net_bps']/RECORD_BPS:.2f})")


def stage_quantiles():
    out = _ckpt()
    if not out.get("prereg"):
        raise RuntimeError("run prereg first")
    t0 = time.time()
    audio_nom, align = _load_tape9()
    sec = _get_section(MANIFEST_T9, "m9_m8_dense375")
    sch = m9d._scheme_from_entry(sec)
    freqs = [float(f) for f in sch.freqs[sch.data_idx]]
    res = {"capture": "tape9_run1 (GOLD)", "section": "m9_m8_dense375",
           "stride": 256, "data_freqs_hz": freqs,
           "pilot_hz": float(sch.freqs[sch.pilot_idx]),
           "branches": _run_branches(audio_nom, align, sec, sch, BRANCHES)}
    out["stages"]["quantiles_tape9"] = res
    out.setdefault("stage_wall_s", {})["quantiles"] = round(time.time() - t0, 1)
    _save(out)
    print(f"[quantiles] {len(res['branches'])} branches in "
          f"{time.time()-t0:.0f}s -> {OUT_JSON.name}")


def stage_secondtape():
    out = _ckpt()
    if not out.get("prereg"):
        raise RuntimeError("run prereg first")
    t0 = time.time()
    audio_nom, align = _load_m8tape()
    sec = _get_section(MANIFEST_M8, "m8_dq_p10n512_rs127")
    sch = m9d._scheme_from_entry(sec)
    freqs = [float(f) for f in sch.freqs[sch.data_idx]]
    res = {"capture": "m8_tape_mono_lossless (independent)",
           "section": "m8_dq_p10n512_rs127", "stride": 256,
           "data_freqs_hz": freqs,
           "pilot_hz": float(sch.freqs[sch.pilot_idx]),
           "branches": _run_branches(audio_nom, align, sec, sch, BRANCHES)}
    out["stages"]["quantiles_m8tape"] = res
    out.setdefault("stage_wall_s", {})["secondtape"] = round(time.time() - t0, 1)
    _save(out)
    print(f"[secondtape] {len(res['branches'])} branches in "
          f"{time.time()-t0:.0f}s")


# ===========================================================================
def _best_branch_table(stage):
    """Per-carrier best sanctioned branch by max margin (45 - p90)."""
    freqs = stage["data_freqs_hz"]
    best = [None] * len(freqs)
    for key, b in stage["branches"].items():
        for k, row in enumerate(b["per_carrier"]):
            if row["p90_deg"] is None:
                continue
            m = 45.0 - row["p90_deg"]
            if best[k] is None or m > best[k]["margin_deg"]:
                best[k] = {"freq_hz": freqs[k], "branch": key,
                           "margin_deg": round(m, 2), **row}
    return best


def stage_extbins():
    out = _ckpt()
    if not out.get("prereg"):
        raise RuntimeError("run prereg first")
    if "quantiles_tape9" not in out["stages"]:
        raise RuntimeError("run quantiles first")
    hr = json.loads(HEADROOM_JSON.read_text())
    tab = hr["sounder"]["table"]
    f_tab = np.array([r["f_hz"] for r in tab])
    snr_tab = np.array([r["snr_375_db"] for r in tab])

    best = _best_branch_table(out["stages"]["quantiles_tape9"])
    ref_f = [6375.0, 7125.0, 7500.0, 8250.0, 8625.0, 9000.0]
    ref = [(b["freq_hz"], b["p90_deg"]) for b in best
           if b and b["freq_hz"] in ref_f]
    assert len(ref) == len(ref_f), ref
    F = np.array([r[0] for r in ref])
    P90 = np.array([r[1] for r in ref])
    # least squares on p90^2 = c0^2 + c1^2 f^2  (linear in c0^2, c1^2)
    A = np.stack([np.ones_like(F), F ** 2], axis=1)
    coef, *_ = np.linalg.lstsq(A, P90 ** 2, rcond=None)
    c0sq = max(0.0, float(coef[0]))
    c1sq = max(0.0, float(coef[1]))

    def snr_db_at(f):
        return float(np.interp(f, f_tab, snr_tab))

    sn = lambda f: (180.0 / np.pi) / np.sqrt(10 ** (snr_db_at(f) / 10.0))
    sn_ref = float(np.median([sn(f) for f in ref_f]))

    rows = []
    for f in CANDIDATES["x11_f3_d2xx_p23_rs127_extband"]["new_bins_hz"]:
        p90_pred = float(np.sqrt(c0sq + c1sq * f * f
                                 + max(0.0, sn(f) ** 2 - sn_ref ** 2)))
        rows.append({"freq_hz": f, "class": "PREDICTED (sounder-anchored)",
                     "snr_375_db": round(snr_db_at(f), 2),
                     "sn_noise_deg": round(sn(f), 2),
                     "p90_pred_deg": round(p90_pred, 2),
                     "margin_pred_deg": round(45.0 - p90_pred, 2),
                     "pass_15deg": bool(45.0 - p90_pred >= 15.0)})
        print(f"  [extbin {f:6.0f}] SNR375={snr_db_at(f):5.1f} dB "
              f"p90_pred={p90_pred:5.1f} margin={45-p90_pred:5.1f} "
              f"{'PASS' if 45-p90_pred>=15 else 'FAIL'}")
    out["stages"]["extbins"] = {
        "fit": {"c0_deg": round(float(np.sqrt(c0sq)), 2),
                "c1_deg_per_hz": float(np.sqrt(c1sq)),
                "ref_points": [{"f": float(a), "p90": float(b)} for a, b in ref],
                "sn_ref_deg": round(sn_ref, 2)},
        "rows": rows}
    _save(out)
    print("[extbins] done")


# ===========================================================================
def stage_margins():
    out = _ckpt()
    pr = out.get("prereg")
    if not pr:
        raise RuntimeError("no prereg")
    t9 = out["stages"]["quantiles_tape9"]
    m8 = out["stages"].get("quantiles_m8tape")
    ext = out["stages"].get("extbins")
    best_t9 = _best_branch_table(t9)
    by_freq_t9 = {b["freq_hz"]: b for b in best_t9 if b}
    by_freq_m8 = {}
    if m8:
        for b in _best_branch_table(m8):
            if b:
                by_freq_m8[b["freq_hz"]] = b
    ext_rows = {r["freq_hz"]: r for r in (ext["rows"] if ext else [])}

    adjudication = {"per_candidate": {}, "frozen_thresholds": pr["gates"]}
    for name, cand in pr["candidates"].items():
        grid = [750.0 + 375.0 * i
                for i in range(int((cand["grid_max_hz"] - 750.0) / 375.0) + 1)]
        drops = set(cand["drop_freqs_hz"])
        kept = [f for f in grid if f not in drops and f != 4875.0]
        table, kill_carriers = [], []
        for f in kept:
            if f in by_freq_t9:
                b = by_freq_t9[f]
                m8b = by_freq_m8.get(f)
                ga = b["margin_deg"] >= 15.0
                gb = (m8b is None) or (m8b["margin_deg"] >= 10.0)
                row = {"freq_hz": f, "class": "MEASURED (tape9 GOLD)",
                       "branch": b["branch"], "n": b["n"], "ser": b["ser"],
                       "p90_deg": b["p90_deg"], "p99_deg": b["p99_deg"],
                       "margin_deg": b["margin_deg"],
                       "m8_margin_deg": (m8b["margin_deg"] if m8b else None),
                       "m8_evidence": bool(m8b),
                       "G_A_pass": bool(ga), "G_B_pass": bool(gb)}
                if not (ga and gb):
                    kill_carriers.append(f)
            elif f in ext_rows:
                r = ext_rows[f]
                row = {"freq_hz": f, **r,
                       "G_A_pass": bool(r["pass_15deg"]),
                       "G_B_pass": None}
                if not r["pass_15deg"]:
                    kill_carriers.append(f)
            else:
                row = {"freq_hz": f, "class": "NO EVIDENCE", "G_A_pass": False}
                kill_carriers.append(f)
            table.append(row)

        surv = [f for f in kept if f not in kill_carriers]
        P_eff = len(surv)
        net_eff = P_eff * SYM_RATE * BITS_PER_CARRIER * cand["rs_k"] / 255.0
        sers = [by_freq_t9[f]["ser"] for f in surv if f in by_freq_t9]
        # extension bins have no measured SER; byte-ER uses measured carriers
        # only and is therefore a PARTIAL prediction for F3 (logged)
        byte_er = (float(np.mean([1 - (1 - s) ** 4 for s in sers]))
                   if sers else 1.0)
        cap = 0.6 * (255 - cand["rs_k"]) / 510.0
        gc_pass = byte_er <= cap / 1.5
        is_banker = cand["tier"] == "banker"
        gd_pass = (net_eff > 4910.0) if is_banker else True
        derated = len(kill_carriers) > 0
        verdict = ("GO" if (gc_pass and gd_pass and P_eff > 0)
                   else "KILL")
        adjudication["per_candidate"][name] = {
            "tier": cand["tier"], "rs_k": cand["rs_k"],
            "design_P": cand["P"], "effective_P": P_eff,
            "design_net_bps": round(cand["net_bps"], 1),
            "effective_net_bps": round(net_eff, 1),
            "x_record": round(net_eff / RECORD_BPS, 3),
            "carriers_killed_by_margin": kill_carriers,
            "derated": derated,
            "margin_table": table,
            "min_margin_deg_kept": (round(min(
                r["margin_deg"] if "margin_deg" in r else r["margin_pred_deg"]
                for r in table if r["freq_hz"] in surv), 2) if surv else None),
            "G_C_byte_er": {"predicted": round(byte_er, 5),
                            "cap": round(cap, 5),
                            "cap_with_1p5x_margin": round(cap / 1.5, 5),
                            "margin_factor": round(cap / max(byte_er, 1e-9), 2),
                            "pass": bool(gc_pass)},
            "G_D_rate": {"banker_floor": 4910.0, "pass": bool(gd_pass),
                         "applies": is_banker},
            "verdict": verdict,
        }
        print(f"[margins] {name:34s} P{cand['P']}->{P_eff} "
              f"net {cand['net_bps']:.0f}->{net_eff:.0f} "
              f"minMargin={adjudication['per_candidate'][name]['min_margin_deg_kept']} "
              f"byteER {byte_er:.4f}/{cap/1.5:.4f} -> {verdict}")
    out["adjudication"] = adjudication
    _save(out)
    print(f"[margins] -> {OUT_JSON.name}")


STAGES = {"prereg": stage_prereg, "quantiles": stage_quantiles,
          "secondtape": stage_secondtape, "extbins": stage_extbins,
          "margins": stage_margins}

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES) + ["all"])
    args = ap.parse_args()
    if args.stage == "all":
        for fn in STAGES.values():
            fn()
    else:
        STAGES[args.stage]()
