"""x10_b_aggr_03_toneplan_v2_pregate.py — PRE-REGISTERED sim pre-gate (B-aggr-03).

Protocol (frozen in PREREG below, written to the results JSON BEFORE any sim
cell runs; the run stage refuses to start without it):

  g1  nominal screen: >=7/8 seeds byte-exact, sim_v2.channel_v2(profile='tape7',
      aac=False, dg=0.58), seeds {0..7}  — identical channel cell to the m9 gate.
  g5  mean byte-error-rate over the g1 seeds <= 0.6*(255-k)/(2*255)
      (k179 -> 0.0894).

AXIS CLASSIFICATION (frozen BEFORE any run; post-hoc reassignment PROHIBITED):
  tape-BLOCKING axes (can cut a rung, with the kill discipline below):
    B1  IMD/dense-packing at the NEW tone placements (9750 / 10500 Hz bins)
    B2  notch-placement sensitivity (pilot-on-notch tracking viability)
    B3  AAC survival of the new >9 kHz bins
  prediction-to-test-ONLY axes (logged, NEVER a cut):
    timing/flutter, N256 symbol length, density.
  m9 calibration (results/m9_sim_validate_run1.json): the SAME sim cell scored
  every N256 rung g1 0-1/8 with mean BER 0.84-0.96, and the real tape then
  landed m4b 0/49 EXACT and put m5 within 2 codewords of 2632. An absolute g1/g5
  failure of an N256 rung in this screen is therefore EXPECTED and is evidence
  on the prediction axes only. What this screen actually decides:
    * the m7-RELATIVE comparison (same N256 family, same channel, same seeds):
      does the channel-mapped plan beat m7's plan (mean BER 0.916, g1 0/8)?
    * the three blocking-axis criteria (B1-B3, numeric definitions in PREREG).

KILL DISCIPLINE: no rung is killed from the 8-seed screen alone. A KILL needs a
16-seed confirmation run where (a) the blocking criterion holds at 16-seed scale
AND (b) g1 < 14/16. Anchor x0 is never sim-gated (spacing<750 is sim-unvalidated
HOLD-by-rule; the rung is the PROVEN record verbatim — sanity cells logged only).

Stages:
  python3 .../x10_b_aggr_03_toneplan_v2_pregate.py --stage prereg
  python3 .../x10_b_aggr_03_toneplan_v2_pregate.py --stage run [--rungs ...] [--workers 4]
  python3 .../x10_b_aggr_03_toneplan_v2_pregate.py --stage confirm --rungs <name>   # 16-seed
  python3 .../x10_b_aggr_03_toneplan_v2_pregate.py --stage adjudicate

Checkpoint/results: results/x10_b_aggr_03_toneplan_v2_pregate.json
(every finished cell is written immediately; reruns skip completed cells).
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                   # noqa: E402
from m3_codec import Rung                                   # noqa: E402
import sim_v2                                               # noqa: E402
from h4_dqpsk import build_section, nominal_frame_bits, PAD_LO_S, PAD_HI_S, FS  # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod            # noqa: E402
from m9_decode import (                                     # noqa: E402
    _rs_merge_guarded, _frame_reliability_to_cw, _per_carrier_ser, _better,
)
from x10_b_aggr_03_toneplan_v2_decode import _scheme_from_entry  # noqa: E402

SR = codec.FS
assert SR == FS == 48_000
MANIFEST_PATH = _HERE / "x10_master10_manifest.json"
RESULTS_DIR = _HERE / "results"
OUT_PATH = RESULTS_DIR / "x10_b_aggr_03_toneplan_v2_pregate.json"

NOMINAL_DG = 0.58
G1_SEEDS = list(range(8))
AAC_SEEDS = list(range(4))
CONFIRM_SEEDS = list(range(16))
PLL_BW_HZ = 30.0
EMA_ALPHAS = (0.5, 0.6, 0.65)
ERASE_FRACS = (0.0,)        # tape9 evidence: erasures monotonically hurt; CRC guard kept
NEW_BIN_FREQS = (9750.0, 10500.0)
ESTABLISHED_BAND = (5250.0, 9000.0)   # m9-proven N256 carriers for the B1/B3 reference

GATED_RUNGS = ["x10_x1a_banker2896", "x10_x1b_banker2896_var", "x10_x2a_stretch3158",
               "x10_x2b_stretch3158_var", "x10_x3_pvar2896"]
ANCHOR_RUNG = "x10_x0_anchor2572"

PREREG = {
    "candidate": "B-aggr-03-toneplan-v2",
    "frozen_utc": None,   # set when written; cells refuse to run without this block
    "channel": "sim_v2.channel_v2(profile='tape7', aac in {False,True}, "
               "sim_overrides={'diffuse_gain': 0.58}), seed_offset=seed",
    "gate": {
        "g1": ">=7/8 seeds byte-exact on the nominal screen (aac=False, dg=0.58, seeds 0-7)",
        "g5": "mean byte-error-rate over g1 seeds <= 0.6*(255-k)/(2*255); k179 cap 0.0894",
    },
    "receiver_sweep": "resampling_pll(bw=30) + ema alphas (0.5,0.6,0.65); erase_frac 0.0 only "
                      "(pre-registered deviation from the m9 gate's (0,0.25,0.5): on tape9 "
                      "erasures never helped and monotonically hurt; CRC32 guard retained)",
    "axis_classification": {
        "tape_blocking": [
            "B1 IMD/dense-packing at the new tone placements (9750/10500 Hz)",
            "B2 notch-placement sensitivity (pilot-on-notch tracking viability)",
            "B3 AAC survival of the new >9 kHz bins",
        ],
        "prediction_to_test_only": ["timing/flutter", "N256 symbol length", "density"],
        "reassignment": "post-hoc reassignment of an axis between classes is PROHIBITED",
    },
    "blocking_criteria": {
        "B1_new_bin_imd": "On the 8-seed nominal screen: median-across-seeds SER of a new "
                          "bin (9750 or 10500) > max(0.10, 3x the median SER of the same "
                          "rung's established 5250-9000 Hz carriers). Sim CAN see this axis "
                          "(IMD/leakage/EQ are modeled; not timing-dominated).",
        "B2_pilot_track": "Whole-rung tracking collapse signature on >=6/8 nominal seeds "
                          "(cw_failed/n_cw > 0.9 AND per-carrier SER ~uniform > 0.4 on ALL "
                          "carriers) while x10_x3_pvar2896 (pilot 6000) does NOT collapse on "
                          "the same seeds. CAVEAT (logged, frozen): the sim H(f) is the "
                          "master3 curve without the tape9 4500 Hz notch, so the sharper "
                          "in-situ test of B2 is the tape9 GOLD evidence that m5/m6's pilot "
                          "at 4500 tracked at 24 dB; sim B2 covers leakage/EQ pathology only.",
        "B3_aac_new_bins": "median SER of a new bin over the 4 aac=True seeds > "
                           "max(0.10, 3x its median SER over the aac=False seeds 0-3) — "
                           "i.e. the AAC round-trip SPECIFICALLY kills the new bins.",
    },
    "kill_discipline": "No KILL from the 8-seed screen. KILL requires a 16-seed confirmation "
                       "(seeds 0-15) where the flagged blocking criterion holds at 16-seed "
                       "scale AND g1 < 14/16.",
    "m9_calibration_baseline": {
        "source": "results/m9_sim_validate_run1.json (same channel cell, m9 gate)",
        "m9_m7_n256_p11_9000": {"g1": "0/8", "mean_ber": 0.916,
                                "real_tape": "5/43 cw failed at 2896 bps on tape9"},
        "m9_m5_n256_rs179": {"g1": "0/8", "mean_ber": 0.909,
                             "real_tape": "2/44 cw failed at 2632 bps on tape9"},
        "m9_m4b_n256_rs159_var": {"g1": "0/8", "mean_ber": 0.855,
                                  "real_tape": "0/49 EXACT at 2338 bps on tape9"},
        "reading": "absolute g1/g5 failure of an N256 rung in this sim is the EXPECTED "
                   "prediction-axis outcome, never a cut; the decision-relevant sim "
                   "quantities are the m7-RELATIVE mean-BER/per-carrier comparison and "
                   "the B1-B3 blocking criteria",
    },
    "anchor_policy": "x10_x0_anchor2572 is never sim-gated (375 Hz spacing is HOLD-by-rule, "
                     "sim-unvalidated <750 Hz; the rung is the PROVEN 2572 record verbatim, "
                     "byte-identical scheme+payload). 8 nominal cells logged as sanity only.",
    "ship_gate_tape": "SHIP = anchor reproves 2572 orig-exact on the new capture (else tape "
                      "pass VOID) AND a banker rung orig-exact >= 2896 net bps under the "
                      "pre-registered sidecar-CRC convention; stretch counted separately; "
                      "miscorrected_cw = 0 verified post-hoc; union-receiver CRC-acceptance "
                      "trials logged within the < 1e-4 campaign false-accept budget.",
    "seeds": {"g1": G1_SEEDS, "aac": AAC_SEEDS, "confirm": CONFIRM_SEEDS},
}


# ===========================================================================
def _load_ckpt() -> dict:
    if OUT_PATH.exists():
        return json.loads(OUT_PATH.read_text())
    return {"prereg": None, "cells": {}, "confirm_cells": {}, "adjudication": None}


def _save_ckpt(ck: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(ck, indent=2, default=float))


# ===========================================================================
# one sim cell: build the rung clip, channel it, decode with the frozen sweep.
# ===========================================================================
def run_cell(sec: dict, seed: int, aac: bool) -> dict:
    t0 = time.time()
    sch = _scheme_from_entry(sec)
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()

    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected_packed, rung)
    frame_audios = [np.asarray(sch.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in tx_frames]
    section, starts, _spans = build_section(frame_audios)

    y = np.asarray(sim_v2.channel_v2(
        section, profile="tape7", aac=aac, seed_offset=int(seed),
        sim_overrides={"diffuse_gain": NOMINAL_DG}), np.float64)

    nom_bits = nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)

    def demod_all(frontend):
        rx, diags = [], []
        for fi, st in enumerate(starts):
            nd = sch.nsym_data(nom_bits[fi])
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(y), st + len(frame_audios[fi]) + pad_hi)
            bits, diag = frontend(y[w_lo:w_hi], nd)
            rx.append(np.asarray(bits, np.uint8))
            diags.append(diag if isinstance(diag, dict) else {})
        return rx, diags

    frontends = [("resampling_pll",
                  lambda w, nd, d=ResamplingPLLDemod(sch, pll_bw_hz=PLL_BW_HZ,
                                                     front_end="pll"): d.demod(w, nd))]
    for a in EMA_ALPHAS:
        frontends.append((f"ema{a}",
                          lambda w, nd, d=ResamplingPLLDemod(sch, front_end="ema",
                                                             ema_alpha=a): d.demod(w, nd)))

    best = None
    for fe_name, fe in frontends:
        rx, diags = demod_all(fe)
        rel_cw = _frame_reliability_to_cw(diags, meta)
        for ef in ERASE_FRACS:
            out, cwf, misc, ne = _rs_merge_guarded(rx, meta, crc_table,
                                                   erase_frac=ef, rel_cw=rel_cw)
            exact = out == expected_packed
            berr = sum(a != b for a, b in zip(out, expected_packed)) + abs(
                len(out) - len(expected_packed))
            att = {"front_end": fe_name, "erase_frac": ef, "byte_exact": exact,
                   "cw_failed": cwf, "miscorrected": misc, "byte_errors": berr,
                   "_rx": rx}
            if best is None or _better(att, best):
                best = att
            if exact:
                break
        if best and best["byte_exact"]:
            break

    pcs = _per_carrier_ser(best["_rx"], sec, sch, expected_packed)
    return {
        "rung": sec["name"], "seed": int(seed), "aac": bool(aac), "dg": NOMINAL_DG,
        "profile": "tape7",
        "byte_exact": bool(best["byte_exact"]), "cw_failed": int(best["cw_failed"]),
        "n_codewords": meta["n_codewords"],
        "byte_error_rate": round(best["byte_errors"] / max(1, len(expected_packed)), 6),
        "miscorrected": int(best["miscorrected"]),
        "front_end": best["front_end"],
        "per_carrier_ser": pcs,
        "carrier_freqs_hz": sec.get("carrier_freqs_hz"),
        "wall_s": round(time.time() - t0, 1),
    }


def _cell_key(rung: str, seed: int, aac: bool) -> str:
    return f"{rung}|{'aac' if aac else 'nom'}|s{seed}"


def _worker(args):
    sec, seed, aac = args
    import warnings
    warnings.filterwarnings("ignore")
    return run_cell(sec, seed, aac)


# ===========================================================================
def stage_prereg() -> None:
    ck = _load_ckpt()
    if ck.get("prereg"):
        print(f"[prereg] already frozen at {ck['prereg']['frozen_utc']} — not rewriting")
        return
    if ck.get("cells"):
        raise RuntimeError("cells exist but no prereg block — protocol violation, aborting")
    pr = dict(PREREG)
    pr["frozen_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ck["prereg"] = pr
    _save_ckpt(ck)
    print(f"[prereg] FROZEN at {pr['frozen_utc']} -> {OUT_PATH}")


def stage_run(rungs: list[str] | None, workers: int, confirm: bool = False) -> None:
    ck = _load_ckpt()
    if not ck.get("prereg"):
        raise RuntimeError("prereg block missing — run --stage prereg FIRST")
    manifest = json.loads(MANIFEST_PATH.read_text())
    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    want = rungs or (GATED_RUNGS + [ANCHOR_RUNG])
    store = "confirm_cells" if confirm else "cells"

    jobs = []
    for rname in want:
        sec = secs[rname]
        if confirm:
            seeds_nom = CONFIRM_SEEDS
            seeds_aac = CONFIRM_SEEDS if rname != ANCHOR_RUNG else []
        else:
            seeds_nom = G1_SEEDS
            seeds_aac = AAC_SEEDS if rname != ANCHOR_RUNG else []
        for s in seeds_nom:
            if _cell_key(rname, s, False) not in ck[store]:
                jobs.append((sec, s, False))
        for s in seeds_aac:
            if _cell_key(rname, s, True) not in ck[store]:
                jobs.append((sec, s, True))

    print(f"[run{'-confirm' if confirm else ''}] {len(jobs)} cells to do "
          f"({len(ck[store])} already done)")
    if not jobs:
        return
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_worker, j): j for j in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            ck[store][_cell_key(r["rung"], r["seed"], r["aac"])] = r
            _save_ckpt(ck)
            print(f"  [{r['rung']:<24} s{r['seed']} {'aac' if r['aac'] else 'nom'}] "
                  f"exact={r['byte_exact']} cw={r['cw_failed']}/{r['n_codewords']} "
                  f"ber={r['byte_error_rate']:.3f} fe={r['front_end']} ({r['wall_s']}s)",
                  flush=True)
    print(f"[run] done in {(time.time() - t0) / 60:.1f} min")


# ===========================================================================
def _median(xs):
    return float(np.median(xs)) if len(xs) else None


def _rung_cells(ck, rname, aac):
    return [c for c in ck["cells"].values()
            if c["rung"] == rname and c["aac"] == aac]


def _new_bin_sers(cells, freqs_key="carrier_freqs_hz"):
    """{new_bin_freq: [per-seed SER]} + per-seed median SER of established carriers."""
    out = {f: [] for f in NEW_BIN_FREQS}
    est = []
    for c in cells:
        freqs = c.get(freqs_key) or []
        sers = c.get("per_carrier_ser") or []
        est_seed = [s for f, s in zip(freqs, sers)
                    if ESTABLISHED_BAND[0] <= f <= ESTABLISHED_BAND[1]]
        if est_seed:
            est.append(float(np.median(est_seed)))
        for f, s in zip(freqs, sers):
            if any(abs(f - nb) < 1.0 for nb in NEW_BIN_FREQS):
                out[[nb for nb in NEW_BIN_FREQS if abs(f - nb) < 1.0][0]].append(float(s))
    return out, est


def stage_adjudicate() -> dict:
    ck = _load_ckpt()
    if not ck.get("prereg"):
        raise RuntimeError("no prereg block")
    adjudication = {"rungs": {}, "ladder": None}
    for rname in GATED_RUNGS + [ANCHOR_RUNG]:
        nom = _rung_cells(ck, rname, False)
        aacc = _rung_cells(ck, rname, True)
        if not nom:
            continue
        rs_k = 159 if rname == ANCHOR_RUNG else 179
        cap = round(0.6 * (255 - rs_k) / (2 * 255), 4)
        g1_ne = sum(1 for c in nom if c["byte_exact"])
        mean_ber = float(np.mean([c["byte_error_rate"] for c in nom]))
        g1_pass = g1_ne >= 7 and len(nom) >= 8
        g5_pass = mean_ber <= cap

        # ---- B1: new-bin IMD/dense-packing (nominal cells) ----
        nb_nom, est_nom = _new_bin_sers(nom)
        b1 = {}
        for f, sers in nb_nom.items():
            if not sers:
                continue
            med = _median(sers)
            ref = max(0.10, 3.0 * (_median(est_nom) or 0.0))
            b1[str(int(f))] = {"median_ser": round(med, 4), "threshold": round(ref, 4),
                               "flag": bool(med > ref)}
        b1_flag = any(v["flag"] for v in b1.values())

        # ---- B2: pilot-track collapse signature (nominal cells) ----
        collapse_seeds = 0
        for c in nom:
            sers = c.get("per_carrier_ser") or []
            if (c["n_codewords"] and c["cw_failed"] / c["n_codewords"] > 0.9
                    and sers and min(sers) > 0.4):
                collapse_seeds += 1
        b2_flag = collapse_seeds >= 6
        # comparator: pvar must NOT collapse for the flag to indict the pilot placement
        if b2_flag and rname != "x10_x3_pvar2896":
            pvar = _rung_cells(ck, "x10_x3_pvar2896", False)
            pvar_collapse = sum(
                1 for c in pvar
                if (c["n_codewords"] and c["cw_failed"] / c["n_codewords"] > 0.9
                    and (c.get("per_carrier_ser") or [1.0])
                    and min(c["per_carrier_ser"]) > 0.4))
            if pvar and pvar_collapse >= 6:
                b2_flag = False   # both pilots collapse -> not a placement effect

        # ---- B3: AAC kills the new bins (aac vs nom on seeds 0-3) ----
        b3 = {}
        nom03 = [c for c in nom if c["seed"] in AAC_SEEDS]
        nb_aac, _ = _new_bin_sers(aacc)
        nb_nom03, _ = _new_bin_sers(nom03)
        for f in NEW_BIN_FREQS:
            sa, sn = nb_aac.get(f, []), nb_nom03.get(f, [])
            if not sa or not sn:
                continue
            med_a, med_n = _median(sa), _median(sn)
            thr = max(0.10, 3.0 * med_n)
            b3[str(int(f))] = {"median_ser_aac": round(med_a, 4),
                               "median_ser_noaac": round(med_n, 4),
                               "threshold": round(thr, 4), "flag": bool(med_a > thr)}
        b3_flag = any(v["flag"] for v in b3.values())

        blocked = (b1_flag or b2_flag or b3_flag)
        if rname == ANCHOR_RUNG:
            verdict = "ANCHOR (never sim-gated; sanity logged)"
        elif g1_pass and g5_pass:
            verdict = "PASS-pregate"
        elif blocked:
            verdict = "BLOCKING-FLAG -> 16-seed confirmation REQUIRED before any KILL"
        else:
            verdict = ("PREDICTION-TO-TEST (absolute g1/g5 fail on the frozen "
                       "prediction-only axes; carried to tape per the m9 calibration)")

        adjudication["rungs"][rname] = {
            "n_nominal_cells": len(nom), "n_aac_cells": len(aacc),
            "g1": f"{g1_ne}/{len(nom)}", "g1_pass": g1_pass,
            "g5_mean_ber": round(mean_ber, 4), "g5_cap": cap, "g5_pass": g5_pass,
            "vs_m9_m7_baseline_mean_ber": 0.916,
            "beats_m7_baseline": bool(mean_ber < 0.916),
            "B1_new_bin_imd": b1, "B1_flag": b1_flag,
            "B2_collapse_seeds": collapse_seeds, "B2_flag": b2_flag,
            "B3_aac_new_bins": b3, "B3_flag": b3_flag,
            "verdict": verdict,
            "front_ends_used": sorted({c["front_end"] for c in nom}),
            "miscorrected_total": sum(c["miscorrected"] for c in nom + aacc),
        }

    n_blocked = sum(1 for v in adjudication["rungs"].values()
                    if v["verdict"].startswith("BLOCKING"))
    n_killed = 0  # kills only possible after a 16-seed confirm; none run unless flagged
    adjudication["ladder"] = {
        "rungs_to_tape": [r for r in [ANCHOR_RUNG] + GATED_RUNGS
                          if not adjudication["rungs"].get(r, {}).get("verdict", "").startswith("KILL")],
        "n_blocking_flags": n_blocked, "n_killed": n_killed,
        "note": "all non-killed rungs are burned to x10_master10; prediction-axis sim "
                "failures ride to tape per the frozen m9 calibration",
    }
    ck["adjudication"] = adjudication
    _save_ckpt(ck)
    print(json.dumps(adjudication, indent=2, default=float))
    return adjudication


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True,
                    choices=["prereg", "run", "confirm", "adjudicate"])
    ap.add_argument("--rungs", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.stage == "prereg":
        stage_prereg()
    elif args.stage == "run":
        stage_run(args.rungs, args.workers)
    elif args.stage == "confirm":
        stage_run(args.rungs, args.workers, confirm=True)
    else:
        stage_adjudicate()
