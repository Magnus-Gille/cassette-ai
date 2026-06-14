"""x12_recon_margins.py -- TAPE10 CHANNEL RECONNAISSANCE (x12 campaign, step 0).

Re-measures the per-carrier dense2x phase-error margins from the REAL d2x
sections of tape10_run1 (master10 burn, fresh C90, lower volume, sounder SNR
35.4 dB / flutter 0.42%) with the EXACT quantile methodology of
results/x11_frontier_margins.json:

    margin_deg(k) = 45.0 - p90_emp(|dphi_err_k| deg), best branch within the
    SAME 27-branch sanctioned receiver set (hann256_skip0 x {.6,.7,.8} x
    {0,+48}; rect128_skip64 x {.6,.7,.8} x {-32..+64}).

WHY: the x11-frontier margin gate KILLED both >4910 banker candidates on
tape9/m8-era evidence (2625/6750 Hz < 15 deg on tape9; 3750 Hz m8 cross-
capture fail; all four >9 kHz ext bins timing-dead).  Tape10 then demonstrated
a strictly better channel (10/10 orig-exact incl. the stretch r8 5791 rung).
This file re-measures those margins against tape10 evidence so the x12 design
campaign can pre-register against current reality.

STRICTLY-MORE-REAL NOTE: the tape9 quantiles were a half-rate re-demodulation
of an N512 section (synthetic d2x geometry); the tape10 sections here are
NATIVE d2x (N256, Schroeder-phase TX) -- the tape10 numbers carry no geometry
emulation caveat.  The comparison therefore conflates tape/channel quality
with geometry realism; both deltas push the same direction (more trustworthy).

THIS IS EVIDENCE, NOT A GATE.  The 15-deg G_A line is REFERENCED for
comparison only; the x11 kills stand until a new pre-registered campaign
(frozen BEFORE its measurements) re-adjudicates.  The G_B cross-capture
lesson ("3750 Hz passes tape9 at 29 deg, fails m8 at -3 deg") is structural:
single-tape margins, including these, are necessary-not-sufficient.

Frozen files imported VERBATIM (never edited): x11_frontier_probe
(_section_gerr_samples, BRANCHES, _best_branch_table), x10_b_aggr_05_dense2x_*
(WIN_CFGS, _make_win, Dense2x schemes), x10_headroom (_tone_gap_table).

Stages (checkpoint results/x12_tape10_margins.json; reruns skip done work):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 x12_recon_margins.py quantiles
    ... sounder | extbins | delta | all
Deterministic (no RNG).
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

# frozen machinery, imported verbatim
from x11_frontier_probe import (                       # noqa: E402
    _section_gerr_samples, _best_branch_table, BRANCHES)
from x10_b_aggr_05_dense2x_probe import (              # noqa: E402
    WIN_CFGS, _make_win, _get_section)
from x10_b_aggr_05_dense2x_master import (             # noqa: E402
    Dense2xScheme, Dense2xDropScheme)
from x10_headroom import _tone_gap_table               # noqa: E402
from scipy.signal import welch                         # noqa: E402

SR = 48_000
RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "x12_tape10_margins.json"
T9_MARGINS = RESULTS / "x11_frontier_margins.json"
MANIFEST_M10 = json.loads((_HERE / "master10_manifest.json").read_text())
CACHE_T10 = _HERE / "captures" / "x11_decode_nom_tape10_run1.npy"
SYNC_T10 = RESULTS / "x11_decode_sync_tape10_run1.json"

# native d2x sections on tape10 (real N256 Schroeder-TX evidence)
SECTIONS = ("m10_r8_d2x_p22_rs179",      # P22 full grid -- ALL killed bins live here
            "m10_r6_d2x_p21_rs159")      # P21 (drop 750) same-tape replicate
EXT_BINS = (9375.0, 9750.0, 10125.0, 10500.0)
REF_F = (6375.0, 7125.0, 7500.0, 8250.0, 8625.0, 9000.0)   # frozen extbins refs
KILLED_BINS = (2625.0, 3750.0, 6750.0)
G_A_REF_DEG = 15.0                       # referenced, NOT adjudicated here


def _ckpt() -> dict:
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    return {
        "campaign": "x12-recon (channel evidence only, no gates adjudicated)",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "methodology": "margin_deg(k) = 45.0 - p90_emp(|dphi_err_k| deg), "
                       "boundary view, best branch within the x11 sanctioned "
                       "27-branch set -- identical recipe to "
                       "x11_frontier_margins.json; tape10 sections are NATIVE "
                       "d2x (R=1, N256) vs tape9's half-rate N512 emulation",
        "caveats": [
            "single-tape evidence: the x11 G_B lesson stands (3750 Hz passed "
            "tape9 +29 deg yet failed the m8 capture at -3 deg); any x12 "
            "design gate needs a second-capture column",
            "tape9-vs-tape10 delta conflates channel quality (fresh C90, "
            "lower volume) with geometry realism (native d2x + Schroeder TX "
            "vs emulated); both favor tape10 trustworthiness",
            "ext bins >9 kHz have NO modem evidence on any capture; their "
            "rows remain model predictions (tape10-refit)",
        ],
        "stages": {},
    }


def _save(out: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))


def _load_tape10():
    audio_nom = np.load(CACHE_T10, mmap_mode="r")
    sync = json.loads(SYNC_T10.read_text())
    return audio_nom, int(sync["align"])


def _tx_scheme(sec):
    p = sec["dqpsk_params"]
    if sec["kind"] == "dense2x":
        return Dense2xScheme(p["P"], skip=p.get("skip") or 64)
    assert sec["kind"] == "dense2x_drop", sec["kind"]
    return Dense2xDropScheme(p["P"], p["drop_freqs_hz"],
                             pilot_hz=p["pilot_hz"], skip=p.get("skip") or 64)


# ===========================================================================
def stage_quantiles():
    out = _ckpt()
    audio_nom, align = _load_tape10()
    for sname in SECTIONS:
        key = f"quantiles_tape10_{sname}"
        st = out["stages"].setdefault(key, {
            "capture": "tape10_run1 (GOLD, master10 burn)",
            "section": sname, "native_d2x": True, "R": 1, "stride": 256,
            "branches": {}})
        sec = _get_section(MANIFEST_M10, sname)
        sch = _tx_scheme(sec)
        st["data_freqs_hz"] = [float(f) for f in sch.freqs[sch.data_idx]]
        st["pilot_hz"] = float(sch.freqs[sch.pilot_idx])
        t0 = time.time()
        for cfg_name, alpha, shift in BRANCHES:
            bkey = f"{cfg_name}|a{alpha}|s{shift:+d}"
            if bkey in st["branches"]:
                continue
            cfg = WIN_CFGS[cfg_name]
            if cfg["skip"] + shift < 0:
                continue
            win = _make_win(cfg)
            stats = _section_gerr_samples(audio_nom, align, sec, sch, 1,
                                          cfg["Nw"], cfg["skip"], alpha,
                                          shift, win)
            st["branches"][bkey] = {"config": cfg_name, "alpha": alpha,
                                    "shift": shift, "per_carrier": stats}
            mean_ser = float(np.mean([r["ser"] for r in stats]))
            print(f"  [{sname} {bkey:28s}] meanSER={mean_ser:.4f}", flush=True)
            _save(out)
        print(f"[quantiles] {sname}: {len(st['branches'])} branches "
              f"({time.time()-t0:.0f}s)")
    _save(out)


# ===========================================================================
def stage_sounder():
    """tape10 per-tone SNR_375 table from the master10 multitone sounder --
    same math as x10_headroom.stage_sounder (tone power vs Welch silence
    floor scaled to a 375 Hz band)."""
    out = _ckpt()
    if "sounder_tape10" in out["stages"]:
        print("[sounder] already done")
        return
    audio_nom, align = _load_tape10()
    multitone = [s for s in MANIFEST_M10["sounder_sections"]
                 if s["kind"] == "multitone"]
    noise = next(s for s in MANIFEST_M10["sounder_sections"]
                 if s["kind"] == "noisefloor")
    freqs = np.asarray(multitone[0]["info"]["freqs"], float)

    def grab(sec, trim):
        st = sec["start"] + align
        ti = int(trim * SR)
        return np.asarray(audio_nom[st + ti: st + sec["length"] - ti],
                          np.float64)

    nseg = grab(noise, 0.4)
    f_n, n_psd = welch(nseg, fs=SR, nperseg=16384, noverlap=8192, window="hann")
    tone_acc = np.zeros(len(freqs))
    for mt in multitone:
        tp, _gc, _gf, _pib = _tone_gap_table(grab(mt, 0.3), freqs)
        tone_acc += tp
    tone_p = tone_acc / len(multitone)
    n_at = np.interp(freqs, f_n, n_psd)
    snr_375 = 10 * np.log10(tone_p / (n_at * 375.0))
    out["stages"]["sounder_tape10"] = {
        "n_multitone_reps": len(multitone),
        "noise_floor_dbfs": round(20 * math.log10(
            float(np.sqrt(np.mean(nseg ** 2))) + 1e-30), 2),
        "table": [{"f_hz": float(f), "snr_375_db": round(float(s), 2)}
                  for f, s in zip(freqs, snr_375)],
        "snr_375_median_db": round(float(np.median(snr_375)), 2),
    }
    _save(out)
    hi = [r for r in out["stages"]["sounder_tape10"]["table"]
          if r["f_hz"] >= 8751]
    print(f"[sounder] median SNR375 "
          f"{out['stages']['sounder_tape10']['snr_375_median_db']} dB; "
          f"high band: {hi}")


# ===========================================================================
def stage_extbins():
    """Refit the FROZEN x11 extbins model form on tape10 inputs:
    p90_pred(f) = sqrt((c1*f)^2 + c0^2 + max(0, sn(f)^2 - sn_ref^2)), (c0,c1)
    LS-fitted on the tape10 best-branch p90 of the same six reference
    carriers; sn(f) from the tape10 sounder SNR_375 table."""
    out = _ckpt()
    qkey = f"quantiles_tape10_{SECTIONS[0]}"
    if qkey not in out["stages"] or "sounder_tape10" not in out["stages"]:
        raise RuntimeError("run quantiles + sounder first")
    best = _best_branch_table(out["stages"][qkey])
    ref = [(b["freq_hz"], b["p90_deg"]) for b in best
           if b and b["freq_hz"] in REF_F]
    assert len(ref) == len(REF_F), ref
    F = np.array([r[0] for r in ref])
    P90 = np.array([r[1] for r in ref])
    A = np.stack([np.ones_like(F), F ** 2], axis=1)
    coef, *_ = np.linalg.lstsq(A, P90 ** 2, rcond=None)
    c0sq, c1sq = max(0.0, float(coef[0])), max(0.0, float(coef[1]))

    tab = out["stages"]["sounder_tape10"]["table"]
    f_tab = np.array([r["f_hz"] for r in tab])
    snr_tab = np.array([r["snr_375_db"] for r in tab])
    sn = lambda f: (180.0 / np.pi) / np.sqrt(
        10 ** (float(np.interp(f, f_tab, snr_tab)) / 10.0))
    sn_ref = float(np.median([sn(f) for f in REF_F]))

    rows = []
    for f in EXT_BINS:
        p90_pred = float(np.sqrt(c0sq + c1sq * f * f
                                 + max(0.0, sn(f) ** 2 - sn_ref ** 2)))
        rows.append({"freq_hz": f, "class": "PREDICTED (tape10 refit)",
                     "snr_375_db": round(float(np.interp(f, f_tab, snr_tab)), 2),
                     "sn_noise_deg": round(sn(f), 2),
                     "p90_pred_deg": round(p90_pred, 2),
                     "margin_pred_deg": round(45.0 - p90_pred, 2),
                     "ge_15deg_ref": bool(45.0 - p90_pred >= G_A_REF_DEG)})
        print(f"  [extbin {f:6.0f}] p90_pred={p90_pred:5.1f} "
              f"margin={45-p90_pred:5.1f}")
    out["stages"]["extbins_tape10"] = {
        "fit": {"c0_deg": round(float(np.sqrt(c0sq)), 2),
                "c1_deg_per_hz": float(np.sqrt(c1sq)),
                "ref_points": [{"f": float(a), "p90": float(b)}
                               for a, b in ref],
                "sn_ref_deg": round(sn_ref, 2)},
        "rows": rows}
    _save(out)
    print("[extbins] done")


# ===========================================================================
def stage_delta():
    out = _ckpt()
    t9 = json.loads(T9_MARGINS.read_text())
    best_t9 = {b["freq_hz"]: b for b in
               _best_branch_table(t9["stages"]["quantiles_tape9"]) if b}
    best_m8 = {b["freq_hz"]: b for b in
               _best_branch_table(t9["stages"]["quantiles_m8tape"]) if b}
    qkey = f"quantiles_tape10_{SECTIONS[0]}"
    best_t10 = {b["freq_hz"]: b for b in
                _best_branch_table(out["stages"][qkey]) if b}
    rkey = f"quantiles_tape10_{SECTIONS[1]}"
    best_t10b = ({b["freq_hz"]: b for b in
                  _best_branch_table(out["stages"][rkey]) if b}
                 if rkey in out["stages"] else {})

    # prior verdict per carrier from the x11 adjudication (f1 table covers all)
    prior = {}
    f1 = t9["adjudication"]["per_candidate"]["x11_f1_d2x_p19_rs179"]
    for row in f1["margin_table"]:
        if row.get("class", "").startswith("MEASURED"):
            why = []
            if not row["G_A_pass"]:
                why.append(f"G_A tape9 {row['margin_deg']}<15")
            if not row["G_B_pass"]:
                why.append(f"G_B m8 {row['m8_margin_deg']}<10")
            prior[row["freq_hz"]] = "KILLED: " + ", ".join(why) if why else "kept"
    for f in (750.0, 4500.0, 5625.0):
        prior[f] = "dropped at design time (x10 probe: dc0 echo-ISI / deck notches)"

    table = []
    for f in sorted(best_t10):
        b10, b9 = best_t10[f], best_t9.get(f)
        m8b = best_m8.get(f)
        row = {"freq_hz": f,
               "t9_margin_deg": b9["margin_deg"] if b9 else None,
               "t9_p90_deg": b9["p90_deg"] if b9 else None,
               "m8_margin_deg": m8b["margin_deg"] if m8b else None,
               "t10_margin_deg": b10["margin_deg"],
               "t10_p90_deg": b10["p90_deg"], "t10_ser": b10["ser"],
               "t10_n": b10["n"], "t10_branch": b10["branch"],
               "t10_p21_margin_deg": (best_t10b[f]["margin_deg"]
                                      if f in best_t10b else None),
               "delta_margin_deg": (round(b10["margin_deg"] - b9["margin_deg"], 2)
                                    if b9 else None),
               "t10_ge_15deg_ref": bool(b10["margin_deg"] >= G_A_REF_DEG),
               "prior_x11_status": prior.get(f, "kept"),
               "was_killed_bin": f in KILLED_BINS}
        table.append(row)

    ext10 = out["stages"].get("extbins_tape10", {}).get("rows", [])
    ext9 = {r["freq_hz"]: r for r in t9["stages"]["extbins"]["rows"]}
    ext_table = [{"freq_hz": r["freq_hz"],
                  "t9_margin_pred_deg": ext9[r["freq_hz"]]["margin_pred_deg"],
                  "t10_margin_pred_deg": r["margin_pred_deg"],
                  "delta_pred_deg": round(r["margin_pred_deg"]
                                          - ext9[r["freq_hz"]]["margin_pred_deg"], 2),
                  "t10_ge_15deg_ref": r["ge_15deg_ref"]} for r in ext10]

    out["stages"]["delta"] = {
        "primary_section": SECTIONS[0], "replicate_section": SECTIONS[1],
        "note": "t9 = x11_frontier_margins quantiles_tape9 (half-rate N512 "
                "emulation); t10 = native d2x P22 r8 section; margins are "
                "45 - p90(best sanctioned branch); 15 deg line is the x11 "
                "G_A reference, NOT adjudicated here",
        "table": table, "ext_bins": ext_table,
        "killed_bins_recheck": {str(int(f)): next(
            (r for r in table if r["freq_hz"] == f), None)
            for f in KILLED_BINS},
    }
    _save(out)
    for r in table:
        flag = " <-- was killed" if r["was_killed_bin"] else ""
        print(f"  {r['freq_hz']:7.0f}  t9 {str(r['t9_margin_deg']):>6}  "
              f"t10 {r['t10_margin_deg']:6.2f}  d {str(r['delta_margin_deg']):>6}"
              f"  ser {r['t10_ser']:.4f}{flag}")
    print(f"[delta] -> {OUT_JSON.name}")


STAGES = {"quantiles": stage_quantiles, "sounder": stage_sounder,
          "extbins": stage_extbins, "delta": stage_delta}

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
