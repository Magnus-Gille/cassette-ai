"""x11_frontier_pregate.py -- PRE-REGISTERED sim pre-gate for the x11-frontier ladder.

Deliverable (b) of the x11-frontier brief: an 8-seed sim_v2 screen with the
FROZEN blocking-vs-prediction axis split from toneplan-v2 (g1>=7/8 applies on
blocking axes only; absolute g1/g5 failure of an N256/d2x rung is the
documented prediction-axis outcome, never a cut).  This screen ALSO closes the
two known x10 dress gaps: the AAC axis and a realistic constant clock offset
(~0.17%), both exercised through the FULL decode chain (global chirp sync +
union receiver), which no previous dress rehearsal did.

CONTEXT (honest framing, frozen): the x11 margin gate
(results/x11_frontier_margins.json, adjudicated BEFORE this file ran) already
KILLED both banker candidates (2625/6750 Hz < 15 deg on tape9; 3750 Hz fails
the m8 cross-capture at its documented null) and stripped all four >9 kHz bins
from F3.  Nothing in this pre-gate can resurrect them -- a margin-gate KILL
stands regardless of sim outcomes.  What this screen still decides/banks:
  * B1/B3 ext-band evidence at 9375/9750/10125/10500 Hz on the d2x geometry
    (master12 design evidence either way),
  * B4: does the production chain absorb a constant 0.17% clock offset and an
    AAC round-trip on a CLEAN wav?  (dress-gap closure; a failure here is a
    receiver-chain finding that would also threaten master10's pending rungs),
  * the m7-relative calibration comparison for the d2x family.

AXIS CLASSIFICATION (frozen BEFORE any run; post-hoc reassignment PROHIBITED):
  tape-BLOCKING axes (sim CAN see them; numeric criteria in PREREG):
    B1  IMD/dense-packing at the F3 extension bins (9375/9750/10125/10500 Hz)
    B3  AAC survival: (a) section-level new-bin delta, (b) full-chain CLEAN
        AAC round-trip byte-exactness
    B4  constant-clock-offset survival: (a) full-chain CLEAN 1.0017x resample
        (and clk+aac combo) byte-exactness, (b) noisy anchor delta
  prediction-to-test-ONLY axes (logged, NEVER a cut):
    timing/flutter, N256 symbol length, d2x density, absolute g1/g5 of any
    N256/d2x rung (m9 calibration: same cell scored every N256 rung g1 0-1/8
    with mean BER 0.84-0.96 and the real tape landed 2338/2632/2896; the
    dense2x simgate showed the same pattern before the 5.2x real-probe clear).

KILL DISCIPLINE (toneplan-v2, frozen): no rung is killed from the 8-seed
screen alone; a sim KILL needs a 16-seed confirmation where the blocking
criterion holds AND g1 < 14/16.  (Moot for f1/f2 here -- already margin-killed.)
The anchor is never sim-gated (375 Hz spacing is sim-unvalidated HOLD-by-rule;
nominal cells are sanity only).  B4a/B3b gate the RECEIVER CHAIN, not a rung.

Stages (checkpoint results/x11_frontier_pregate.json; reruns skip done cells):
    python3 x11_frontier_pregate.py --stage prereg
    python3 x11_frontier_pregate.py --stage run [--workers 4] [--rungs ...]
    python3 x11_frontier_pregate.py --stage fullchain [--cells ...]
    python3 x11_frontier_pregate.py --stage adjudicate
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

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                    # noqa: E402
from m3_codec import Rung                                   # noqa: E402
import sim_v2                                               # noqa: E402
from h4_dqpsk import (build_section, nominal_frame_bits,    # noqa: E402
                      PAD_LO_S, PAD_HI_S, FS)
from m9_decode import (                                     # noqa: E402
    _rs_merge_guarded, _frame_reliability_to_cw, _per_carrier_ser, _better,
)
# x11 (non-frozen) receiver: production-faithful sweep + section decode
from x11_frontier_decode import (                           # noqa: E402
    MANIFEST_PATH, _tx_scheme, _frontends_for, _decode_section,
)

SR = codec.FS
assert SR == FS == 48_000
RESULTS_DIR = _HERE / "results"
OUT_PATH = RESULTS_DIR / "x11_frontier_pregate.json"
WAV_PATH = _HERE / "x11_master_frontier.wav"

NOMINAL_DG = 0.58
G1_SEEDS = list(range(8))
AAC_SEEDS = list(range(4))
NOISE_CLK_SEEDS = list(range(2))
ERASE_FRACS = (0.0,)            # pre-registered (tape9: erasures monotonically hurt)
CLK_OFFSET = (10017, 10000)     # constant +0.17% clock offset (resample_poly p, q)
NEW_BIN_FREQS = (9375.0, 9750.0, 10125.0, 10500.0)
ESTABLISHED_BAND = (5250.0, 9000.0)

GATED_RUNGS = ["x11_f1_d2x_p19_rs179", "x11_f2_d2x_p19_rs191",
               "x11_f3_d2xx_p23_rs127_extband"]
ANCHOR_RUNG = "x11_anchor_2572"

FULLCHAIN_CELLS = (
    # label, transform spec  (clean = no channel_v2 noise)
    ("fc_clk_clean", {"clk": True, "aac": False, "noise_seed": None}),
    ("fc_aac_clean", {"clk": False, "aac": True, "noise_seed": None}),
    ("fc_clkaac_clean", {"clk": True, "aac": True, "noise_seed": None}),
    # noisy anchor-only delta pairs (B4b)
    ("fc_noise_s0", {"clk": False, "aac": False, "noise_seed": 0}),
    ("fc_noise_clk_s0", {"clk": True, "aac": False, "noise_seed": 0}),
    ("fc_noise_s1", {"clk": False, "aac": False, "noise_seed": 1}),
    ("fc_noise_clk_s1", {"clk": True, "aac": False, "noise_seed": 1}),
)

PREREG = {
    "campaign": "x11-frontier",
    "stage": "sim pre-gate (deliverable b) + dress-gap closure (AAC, clock offset)",
    "frozen_utc": None,
    "channel": "sim_v2.channel_v2(profile='tape7', aac in {False,True}, "
               "sim_overrides={'diffuse_gain': 0.58}), seed_offset=seed -- "
               "identical cell to the m9/toneplan-v2 gates",
    "receiver_sweep": "x11_frontier_decode._frontends_for: anchor = production "
                      "m9 chain (pll30 + ema .4/.5/.6); d2x = manifest "
                      "rx_window_plan sweep (hann256_skip0 x ema .5-.8 + pll "
                      "30/45, rect128_skip64 x ema .7 + pll 30); erase_frac "
                      "0.0 only (pre-registered)",
    "gate": {
        "g1": ">=7/8 seeds byte-exact on the nominal screen (BLOCKING axes "
              "only; absolute d2x failure is the documented prediction-axis "
              "outcome per the frozen m9 + dense2x-simgate calibration)",
        "g5": "mean byte-error-rate over g1 seeds <= 0.6*(255-k)/(2*255): "
              "k179 cap 0.0894, k191 cap 0.0753, k127 cap 0.1506",
    },
    "axis_classification": {
        "tape_blocking": [
            "B1 IMD/dense-packing at the F3 extension bins (9375/9750/10125/10500 Hz)",
            "B3 AAC survival (section-level new-bin delta + full-chain clean round-trip)",
            "B4 constant 0.17% clock-offset survival through the full chain",
        ],
        "prediction_to_test_only": [
            "timing/flutter", "N256 symbol length", "d2x density",
            "absolute g1/g5 of any N256/d2x rung",
        ],
        "reassignment": "post-hoc reassignment of an axis between classes is PROHIBITED",
    },
    "blocking_criteria": {
        "B1_ext_bin_imd": "8-seed nominal screen, F3: median-across-seeds SER "
                          "of an extension bin > max(0.10, 3x the median SER "
                          "of F3's established 5250-9000 Hz carriers)",
        "B3a_aac_ext_bins": "median SER of an F3 extension bin over the 4 "
                            "aac=True seeds > max(0.10, 3x its median over "
                            "the aac=False seeds 0-3)",
        "B3b_aac_full_chain_clean": "any section non-byte-exact when the CLEAN "
                                    "wav is AAC-round-tripped (sim_v2.aac_"
                                    "roundtrip, 205 kbps) and decoded through "
                                    "the full chain (global sync + union)",
        "B4a_clk_full_chain_clean": "any section non-byte-exact when the CLEAN "
                                    "wav is resampled by 10017/10000 (+0.17%) "
                                    "-- alone or combined with AAC -- and "
                                    "decoded through the full chain",
        "B4b_clk_noisy_anchor_delta": "over noise seeds {0,1}: median of "
                                      "[cw_failed_frac(clk) - cw_failed_frac"
                                      "(no clk)] on the ANCHOR section > 0.15 "
                                      "OR median delta of mean per-carrier "
                                      "SER > 0.10. CAVEAT (frozen): if the "
                                      "no-offset anchor baseline is itself "
                                      "saturated (cw_failed_frac > 0.9, "
                                      "plausible: dense375 spacing is sim-"
                                      "unvalidated), the axis is logged "
                                      "axis_saturated=true and B4 rests on "
                                      "B4a alone",
        "transform_order": "deck-speed offset is applied to the wav BEFORE "
                           "AAC (deck upstream of phone); for noisy cells the "
                           "resample is applied to the channel_v2 output "
                           "(aac=False), logged as an approximation",
    },
    "kill_discipline": "no KILL from the 8-seed screen alone (16-seed confirm "
                       "+ criterion holding required); f1/f2/f3 are ALREADY "
                       "killed/derated by the x11 margin gate -- this screen "
                       "cannot resurrect them; B3b/B4a flags indict the "
                       "receiver chain / print-worthiness of the geometry, "
                       "and would also threaten master10's pending d2x rungs",
    "m9_calibration_baseline": {
        "m9_m7_n256_p11_9000": {"g1": "0/8", "mean_ber": 0.916,
                                "real_tape": "2896 banked on tape9"},
        "dense2x_simgate": "d2x rungs die in this sim; the real-capture probe "
                           "then cleared the geometry at 5.2x margin "
                           "(B-aggr-05); absolute d2x sim failure here is "
                           "EXPECTED",
    },
    "anchor_policy": "x11_anchor_2572 never sim-gated (sanity cells logged); "
                     "it participates in full-chain cells as the chain-health "
                     "indicator",
    "crc_ledger": "every _rs_merge_guarded call counts meta[n_codewords] CRC32 "
                  "acceptance trials; campaign false-accept budget < 1e-4",
    "seeds": {"g1": G1_SEEDS, "aac": AAC_SEEDS, "noise_clk": NOISE_CLK_SEEDS},
    "clk_offset": {"p": CLK_OFFSET[0], "q": CLK_OFFSET[1],
                   "ppm": (CLK_OFFSET[0] / CLK_OFFSET[1] - 1) * 1e6},
}


# ===========================================================================
def _load_ckpt() -> dict:
    if OUT_PATH.exists():
        return json.loads(OUT_PATH.read_text())
    return {"prereg": None, "cells": {}, "fullchain_cells": {},
            "adjudication": None}


def _save_ckpt(ck: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(ck, indent=1, default=float))


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


# ===========================================================================
# one section-level sim cell (toneplan-v2 run_cell, x11 receiver sweep)
# ===========================================================================
def run_cell(sec: dict, seed: int, aac: bool) -> dict:
    t0 = time.time()
    sch_tx = _tx_scheme(sec)
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()

    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected_packed, rung)
    frame_audios = [np.asarray(sch_tx.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in tx_frames]
    section, starts, _spans = build_section(frame_audios)

    y = np.asarray(sim_v2.channel_v2(
        section, profile="tape7", aac=aac, seed_offset=int(seed),
        sim_overrides={"diffuse_gain": NOMINAL_DG}), np.float64)

    nom_bits = nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)

    crc_trials = 0
    best = None
    for fe_name, _sch_rx, fe in _frontends_for(sec):
        rx, diags = [], []
        for fi, st in enumerate(starts):
            nd = sch_tx.nsym_data(nom_bits[fi])
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(y), st + len(frame_audios[fi]) + pad_hi)
            bits, diag = fe(y[w_lo:w_hi], nd)
            rx.append(np.asarray(bits, np.uint8))
            diags.append(diag if isinstance(diag, dict) else {})
        rel_cw = _frame_reliability_to_cw(diags, meta)
        for ef in ERASE_FRACS:
            out, cwf, misc, _ne = _rs_merge_guarded(rx, meta, crc_table,
                                                    erase_frac=ef, rel_cw=rel_cw)
            crc_trials += meta["n_codewords"]
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

    pcs = _per_carrier_ser(best["_rx"], sec, sch_tx, expected_packed)
    return {
        "rung": sec["name"], "seed": int(seed), "aac": bool(aac),
        "dg": NOMINAL_DG, "profile": "tape7",
        "byte_exact": bool(best["byte_exact"]),
        "cw_failed": int(best["cw_failed"]),
        "n_codewords": meta["n_codewords"],
        "byte_error_rate": round(best["byte_errors"] / max(1, len(expected_packed)), 6),
        "miscorrected": int(best["miscorrected"]),
        "front_end": best["front_end"],
        "crc_trials": int(crc_trials),
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
# full-chain cells: transform the WHOLE master wav, then global sync + decode
# ===========================================================================
def run_fullchain_cell(label: str, spec: dict, manifest: dict) -> dict:
    import soundfile as sf
    from scipy.signal import resample_poly
    import analyze_master2 as am2

    t0 = time.time()
    audio, sr = sf.read(str(WAV_PATH), dtype="float32", always_2d=False)
    assert sr == SR
    y = np.asarray(audio, np.float64)

    chain = []
    if spec["noise_seed"] is not None:
        y = np.asarray(sim_v2.channel_v2(
            y, profile="tape7", aac=False, seed_offset=int(spec["noise_seed"]),
            sim_overrides={"diffuse_gain": NOMINAL_DG}), np.float64)
        chain.append(f"channel_v2(tape7,dg={NOMINAL_DG},seed={spec['noise_seed']})")
    if spec["clk"]:
        y = resample_poly(y, CLK_OFFSET[0], CLK_OFFSET[1])
        chain.append(f"resample {CLK_OFFSET[0]}/{CLK_OFFSET[1]} (+0.17%)")
    if spec["aac"]:
        y = np.asarray(sim_v2.aac_roundtrip(y.astype(np.float32), fs=SR),
                       np.float64)
        chain.append("aac_roundtrip(205k)")

    sync = am2.global_sync_and_resample(y.astype(np.float32), manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]

    sections = manifest["ws_payloads"]
    if spec["noise_seed"] is not None:        # noisy cells: anchor only (B4b)
        sections = [s for s in sections if s["name"] == ANCHOR_RUNG]

    ledger = {"crc_trials": 0}
    per_section = []
    for sec in sections:
        r, _packed = _decode_section(audio_nom, sec, align, ledger)
        r.pop("sweep_attempts", None)
        n_cw = max(1, r["n_codewords"])
        r["cw_failed_frac"] = round(r["rs_codewords_failed"] / n_cw, 4)
        pcs = r.get("per_carrier_ser") or []
        r["mean_carrier_ser"] = (round(float(np.mean(pcs)), 5) if pcs else None)
        per_section.append(r)
        print(f"    [{label}] {sec['name']:32s} cw {r['rs_codewords_failed']}/"
              f"{r['n_codewords']} exact={r['byte_exact']}", flush=True)

    return {
        "label": label, "spec": spec, "chain": chain,
        "speed_recovered": {k: v for k, v in sync.items()
                            if k != "audio_nominal" and np.isscalar(v)},
        "sections": per_section,
        "all_byte_exact": bool(all(s["byte_exact"] for s in per_section)),
        "miscorrected_total": int(sum(s["miscorrected_cw"] for s in per_section)),
        "crc_trials": int(ledger["crc_trials"]),
        "wall_s": round(time.time() - t0, 1),
    }


# ===========================================================================
def stage_prereg() -> None:
    ck = _load_ckpt()
    if ck.get("prereg"):
        print(f"[prereg] already frozen at {ck['prereg']['frozen_utc']} -- not rewriting")
        return
    if ck.get("cells") or ck.get("fullchain_cells"):
        raise RuntimeError("cells exist but no prereg block -- protocol violation")
    pr = dict(PREREG)
    pr["frozen_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ck["prereg"] = pr
    _save_ckpt(ck)
    print(f"[prereg] FROZEN at {pr['frozen_utc']} -> {OUT_PATH.name}")


def stage_run(rungs: list[str] | None, workers: int) -> None:
    ck = _load_ckpt()
    if not ck.get("prereg"):
        raise RuntimeError("prereg block missing -- run --stage prereg FIRST")
    manifest = _manifest()
    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    want = rungs or (GATED_RUNGS + [ANCHOR_RUNG])

    jobs = []
    for rname in want:
        sec = secs[rname]
        seeds_aac = AAC_SEEDS if rname != ANCHOR_RUNG else []
        for s in G1_SEEDS:
            if _cell_key(rname, s, False) not in ck["cells"]:
                jobs.append((sec, s, False))
        for s in seeds_aac:
            if _cell_key(rname, s, True) not in ck["cells"]:
                jobs.append((sec, s, True))

    print(f"[run] {len(jobs)} cells to do ({len(ck['cells'])} already done)")
    if not jobs:
        return
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_worker, j): j for j in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            ck["cells"][_cell_key(r["rung"], r["seed"], r["aac"])] = r
            _save_ckpt(ck)
            print(f"  [{r['rung']:<30} s{r['seed']} {'aac' if r['aac'] else 'nom'}] "
                  f"exact={r['byte_exact']} cw={r['cw_failed']}/{r['n_codewords']} "
                  f"ber={r['byte_error_rate']:.3f} fe={r['front_end']} "
                  f"({r['wall_s']}s)", flush=True)
    print(f"[run] done in {(time.time() - t0) / 60:.1f} min")


def stage_fullchain(cells: list[str] | None) -> None:
    ck = _load_ckpt()
    if not ck.get("prereg"):
        raise RuntimeError("prereg block missing -- run --stage prereg FIRST")
    manifest = _manifest()
    want = cells or [c[0] for c in FULLCHAIN_CELLS]
    todo = [(lab, spec) for lab, spec in FULLCHAIN_CELLS
            if lab in want and lab not in ck["fullchain_cells"]]
    print(f"[fullchain] {len(todo)} cells to do "
          f"({len(ck['fullchain_cells'])} already done)")
    for lab, spec in todo:
        r = run_fullchain_cell(lab, spec, manifest)
        ck["fullchain_cells"][lab] = r
        _save_ckpt(ck)
        print(f"  [{lab:18s}] all_exact={r['all_byte_exact']} "
              f"misc={r['miscorrected_total']} ({r['wall_s']}s)", flush=True)


# ===========================================================================
def _median(xs):
    return float(np.median(xs)) if len(xs) else None


def _rung_cells(ck, rname, aac):
    return [c for c in ck["cells"].values()
            if c["rung"] == rname and c["aac"] == aac]


def _ext_bin_sers(cells):
    out = {f: [] for f in NEW_BIN_FREQS}
    est = []
    for c in cells:
        freqs = c.get("carrier_freqs_hz") or []
        sers = c.get("per_carrier_ser") or []
        est_seed = [s for f, s in zip(freqs, sers)
                    if ESTABLISHED_BAND[0] <= f <= ESTABLISHED_BAND[1]]
        if est_seed:
            est.append(float(np.median(est_seed)))
        for f, s in zip(freqs, sers):
            for nb in NEW_BIN_FREQS:
                if abs(f - nb) < 1.0:
                    out[nb].append(float(s))
    return out, est


def stage_adjudicate() -> dict:
    ck = _load_ckpt()
    if not ck.get("prereg"):
        raise RuntimeError("no prereg block")
    rs_k_by_rung = {"x11_f1_d2x_p19_rs179": 179, "x11_f2_d2x_p19_rs191": 191,
                    "x11_f3_d2xx_p23_rs127_extband": 127, ANCHOR_RUNG: 159}
    adjudication = {"rungs": {}, "blocking_axes": {}, "ladder": None}
    total_crc = 0

    for rname in GATED_RUNGS + [ANCHOR_RUNG]:
        nom = _rung_cells(ck, rname, False)
        aacc = _rung_cells(ck, rname, True)
        if not nom:
            continue
        total_crc += sum(c.get("crc_trials", 0) for c in nom + aacc)
        rs_k = rs_k_by_rung[rname]
        cap = round(0.6 * (255 - rs_k) / (2 * 255), 4)
        g1_ne = sum(1 for c in nom if c["byte_exact"])
        mean_ber = float(np.mean([c["byte_error_rate"] for c in nom]))
        g1_pass = g1_ne >= 7 and len(nom) >= 8
        g5_pass = mean_ber <= cap

        entry = {
            "n_nominal_cells": len(nom), "n_aac_cells": len(aacc),
            "g1": f"{g1_ne}/{len(nom)}", "g1_pass": bool(g1_pass),
            "g5_mean_ber": round(mean_ber, 4), "g5_cap": cap,
            "g5_pass": bool(g5_pass),
            "vs_m9_m7_baseline_mean_ber": 0.916,
            "beats_m7_baseline": bool(mean_ber < 0.916),
            "front_ends_used": sorted({c["front_end"] for c in nom}),
            "miscorrected_total": int(sum(c["miscorrected"]
                                          for c in nom + aacc)),
        }

        if rname == "x11_f3_d2xx_p23_rs127_extband":
            nb_nom, est_nom = _ext_bin_sers(nom)
            b1 = {}
            for f, sers in nb_nom.items():
                if not sers:
                    continue
                med = _median(sers)
                ref = max(0.10, 3.0 * (_median(est_nom) or 0.0))
                b1[str(int(f))] = {"median_ser": round(med, 4),
                                   "threshold": round(ref, 4),
                                   "flag": bool(med > ref)}
            entry["B1_ext_bin_imd"] = b1
            entry["B1_flag"] = any(v["flag"] for v in b1.values())

            nom03 = [c for c in nom if c["seed"] in AAC_SEEDS]
            nb_aac, _ = _ext_bin_sers(aacc)
            nb_nom03, _ = _ext_bin_sers(nom03)
            b3a = {}
            for f in NEW_BIN_FREQS:
                sa, sn = nb_aac.get(f, []), nb_nom03.get(f, [])
                if not sa or not sn:
                    continue
                med_a, med_n = _median(sa), _median(sn)
                thr = max(0.10, 3.0 * med_n)
                b3a[str(int(f))] = {"median_ser_aac": round(med_a, 4),
                                    "median_ser_noaac": round(med_n, 4),
                                    "threshold": round(thr, 4),
                                    "flag": bool(med_a > thr)}
            entry["B3a_aac_ext_bins"] = b3a
            entry["B3a_flag"] = any(v["flag"] for v in b3a.values())

        if rname == ANCHOR_RUNG:
            entry["verdict"] = "ANCHOR (never sim-gated; sanity logged)"
        elif g1_pass and g5_pass:
            entry["verdict"] = "PASS-pregate (margin-gate verdict still stands)"
        else:
            entry["verdict"] = (
                "PREDICTION-TO-TEST (absolute g1/g5 fail on the frozen "
                "prediction-only axes, expected for d2x per calibration); "
                "margin-gate verdict stands regardless")
        adjudication["rungs"][rname] = entry

    # ---- full-chain blocking axes -----------------------------------------
    fc = ck.get("fullchain_cells", {})
    total_crc += sum(c.get("crc_trials", 0) for c in fc.values())

    def _fc(lab):
        return fc.get(lab)

    b3b_cells = {lab: _fc(lab)["all_byte_exact"]
                 for lab in ("fc_aac_clean",) if _fc(lab)}
    b4a_cells = {lab: _fc(lab)["all_byte_exact"]
                 for lab in ("fc_clk_clean", "fc_clkaac_clean") if _fc(lab)}
    b3b_flag = any(not ok for ok in b3b_cells.values()) if b3b_cells else None
    b4a_flag = any(not ok for ok in b4a_cells.values()) if b4a_cells else None

    b4b = None
    pairs = []
    for s in NOISE_CLK_SEEDS:
        base, clk = _fc(f"fc_noise_s{s}"), _fc(f"fc_noise_clk_s{s}")
        if not base or not clk:
            continue
        bs = base["sections"][0]
        cs = clk["sections"][0]
        pairs.append({
            "seed": s,
            "cw_frac_base": bs["cw_failed_frac"], "cw_frac_clk": cs["cw_failed_frac"],
            "d_cw_frac": round(cs["cw_failed_frac"] - bs["cw_failed_frac"], 4),
            "ser_base": bs["mean_carrier_ser"], "ser_clk": cs["mean_carrier_ser"],
            "d_ser": (round(cs["mean_carrier_ser"] - bs["mean_carrier_ser"], 5)
                      if None not in (cs["mean_carrier_ser"], bs["mean_carrier_ser"])
                      else None),
        })
    if pairs:
        med_dcw = _median([p["d_cw_frac"] for p in pairs])
        d_sers = [p["d_ser"] for p in pairs if p["d_ser"] is not None]
        med_dser = _median(d_sers) if d_sers else None
        saturated = all(p["cw_frac_base"] > 0.9 for p in pairs)
        b4b = {"pairs": pairs, "median_d_cw_frac": med_dcw,
               "median_d_mean_ser": med_dser,
               "axis_saturated": bool(saturated),
               "flag": bool((med_dcw is not None and med_dcw > 0.15)
                            or (med_dser is not None and med_dser > 0.10))}

    adjudication["blocking_axes"] = {
        "B3b_aac_full_chain_clean": {"cells": b3b_cells, "flag": b3b_flag},
        "B4a_clk_full_chain_clean": {"cells": b4a_cells, "flag": b4a_flag},
        "B4b_clk_noisy_anchor_delta": b4b,
        "speed_recovery_logged": {lab: c.get("speed_recovered")
                                  for lab, c in fc.items()},
    }

    n_flags = sum(bool(adjudication["rungs"].get(r, {}).get(k))
                  for r in adjudication["rungs"]
                  for k in ("B1_flag", "B3a_flag"))
    n_flags += sum(bool(v) for v in (b3b_flag, b4a_flag,
                                     b4b["flag"] if b4b else False))
    fa_bound = total_crc * 2.0 ** -32
    adjudication["ladder"] = {
        "margin_gate_verdicts_stand": "f1 KILL, f2 KILL, f3 GO-derated "
                                      "(results/x11_frontier_margins.json); "
                                      "no sim outcome resurrects a margin kill",
        "n_blocking_flags": int(n_flags),
        "dress_gaps_closed": {
            "aac_axis": b3b_flag is not None,
            "constant_clock_offset_0p17pct": b4a_flag is not None,
        },
        "crc_trial_ledger": {"crc_trials": int(total_crc),
                             "false_accept_bound": fa_bound,
                             "budget": 1e-4,
                             "within_budget": bool(fa_bound < 1e-4)},
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
                    choices=["prereg", "run", "fullchain", "adjudicate"])
    ap.add_argument("--rungs", nargs="*", default=None)
    ap.add_argument("--cells", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.stage == "prereg":
        stage_prereg()
    elif args.stage == "run":
        stage_run(args.rungs, args.workers)
    elif args.stage == "fullchain":
        stage_fullchain(args.cells)
    else:
        stage_adjudicate()
