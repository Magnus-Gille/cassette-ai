"""x10_b_aggr_05_dense2x_simgate.py -- m9-pattern sim gates g1-g5 for the
dense2x rungs.  PRE-REGISTERED STATUS: prediction-to-test, NOT a kill switch.
The m9 gate REJECTED M2/M4-M7 in sim and the real tape landed M2/M4b/M8; the
faithful sim is 5-8x pessimistic on exactly this timing/N256/short-symbol axis.
A sim REJECT here is recorded as a prediction the tape will adjudicate; the
tape decision was already taken by the real-capture probe (GO).

Gate matrix (m9_sim_validate pattern, frozen before any cell ran):
  g1 nominal   channel_v2(profile='tape7', aac=False, dg=0.58), seeds 0-7,
               PASS >= 7/8 byte-exact
  g2 dg-pess   dg=0.65, seeds 0-7, PASS >= 6/8
  g3 flutter   nominal + 12 us HF jitter (x9_flutter_gate.gate_jitter,
               5-23.4 Hz), seeds 0-3, PASS >= 3/4
  g4 combo     SNR-2dB + flutter_residual_frac 0.30, seeds 0-3, PASS >= 3/4
  g5 byte-ER   mean nominal byte-error-rate <= 0.6*(255-k)/(2*255)

Receiver in sim cells (reduced union, the 3 probe-ranked front-ends):
  hann256_skip0+ema0.7, hann256_skip0+pll30, rect128_skip64+ema0.7,
  errors-only RS + CRC32 guard (erase pre-registered OFF).

Usage (chunked, checkpointing results/x10_b_aggr_05_dense2x_simgate.json):
    python3 x10_b_aggr_05_dense2x_simgate.py g1 x10_d2x_p18_rs127
    python3 x10_b_aggr_05_dense2x_simgate.py verdict
Seeds: seed_offset = seed (logged per cell).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                               # noqa: E402
from m3_codec import Rung                              # noqa: E402
import sim_v2                                          # noqa: E402
from h4_dqpsk import (FS, PAD_LO_S, PAD_HI_S,          # noqa: E402
                      build_section, nominal_frame_bits)
import m9_decode as m9d                                # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod       # noqa: E402
from x9_flutter_gate import gate_jitter                # noqa: E402
from x10_b_aggr_05_dense2x_decode import _rx_scheme, _tx_scheme  # noqa: E402

SR = codec.FS
OUT_JSON = _HERE / "results" / "x10_b_aggr_05_dense2x_simgate.json"
MANIFEST = json.loads((_HERE / "x10_master_dense2x_manifest.json").read_text())

NOMINAL_DG = 0.58
PESSIMIST_DG = 0.65
COMBO_SNR_DELTA = -2.0
COMBO_FLUTTER_FRAC = 0.30
JITTER_RMS_S = 12e-6
SEEDS_MAIN = list(range(8))
SEEDS_STRESS = list(range(4))

D2X_RUNGS = ["x10_d2x_p18_rs127", "x10_d2x_p21_rs159", "x10_d2x_p22_rs179"]


def _get_section(name):
    for sec in MANIFEST["ws_payloads"]:
        if sec["name"] == name:
            return sec
    raise KeyError(name)


def _channel(x, *, seed, dg, snr_delta=0.0, flutter_frac=None, jitter_rms=0.0):
    overrides = {"diffuse_gain": float(dg)}
    if flutter_frac is not None:
        overrides["flutter_residual_frac"] = float(flutter_frac)
    snr_db = None
    if snr_delta:
        snr_db = sim_v2.PROFILES["tape7"]["snr_db"] + float(snr_delta)
    y = sim_v2.channel_v2(np.asarray(x, np.float64), profile="tape7",
                          aac=False, seed_offset=int(seed), snr_db=snr_db,
                          sim_overrides=overrides)
    y = np.asarray(y, np.float64)
    if jitter_rms > 0:
        tau = gate_jitter(len(y), seed, jitter_rms)
        t = np.arange(len(y)) / FS
        y = np.interp(t, np.clip(t - tau, 0.0, t[-1]), y)
    return y


def _run_cell(args):
    name, seed, dg, snr_delta, flutter_frac, jitter_rms = args
    t0 = time.time()
    sec = _get_section(name)
    meta = sec["meta"]
    packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    crc_table = sec["crc32_codewords"]
    sch_tx = _tx_scheme(sec)
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _meta2 = codec.encode_payload(packed, rung)
    frame_audios = [np.asarray(sch_tx.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in tx_frames]
    section, starts, _ = build_section(frame_audios, with_sounder=False)
    y = _channel(section, seed=seed, dg=dg, snr_delta=snr_delta,
                 flutter_frac=flutter_frac, jitter_rms=jitter_rms)

    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    fes = []
    for geo, fe, val in (("hann256_skip0", "ema", 0.7),
                         ("hann256_skip0", "pll", 30.0),
                         ("rect128_skip64", "ema", 0.7)):
        sch_rx = _rx_scheme(sec, geo)
        dem = (ResamplingPLLDemod(sch_rx, front_end="ema", ema_alpha=val)
               if fe == "ema" else
               ResamplingPLLDemod(sch_rx, pll_bw_hz=val, front_end="pll"))
        fes.append((f"{geo}_{fe}{val:g}", dem))

    best = None
    for label, dem in fes:
        rx_frames = []
        for fi, st in enumerate(starts):
            nd = sch_tx.nsym_data(nom_bits[fi])
            flen = len(frame_audios[fi])
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(y), st + flen + pad_hi)
            bits, _diag = dem.demod(y[w_lo:w_hi], nd)
            rx_frames.append(np.asarray(bits, np.uint8))
        out, cwf, misc, _ = m9d._rs_merge_guarded(rx_frames, meta, crc_table,
                                                  erase_frac=0.0, rel_cw=None)
        exact = out == packed
        byte_err = sum(a != b for a, b in zip(out, packed)) + abs(
            len(out) - len(packed))
        att = {"front_end": label, "byte_exact": exact, "cw_failed": cwf,
               "miscorrected": misc, "byte_errors": byte_err}
        if best is None or m9d._better(dict(att), dict(best)):
            best = att
        if exact:
            break
    best.update({"rung": name, "seed": seed, "dg": dg, "snr_delta": snr_delta,
                 "flutter_frac": flutter_frac, "jitter_rms_us": jitter_rms * 1e6,
                 "n_codewords": meta["n_codewords"],
                 "payload_len": len(packed),
                 "wall_s": round(time.time() - t0, 1)})
    return best


GATES = {
    "g1": {"seeds": SEEDS_MAIN, "dg": NOMINAL_DG, "snr_delta": 0.0,
           "flutter_frac": None, "jitter": 0.0, "need": 7},
    "g2": {"seeds": SEEDS_MAIN, "dg": PESSIMIST_DG, "snr_delta": 0.0,
           "flutter_frac": None, "jitter": 0.0, "need": 6},
    "g3": {"seeds": SEEDS_STRESS, "dg": NOMINAL_DG, "snr_delta": 0.0,
           "flutter_frac": None, "jitter": JITTER_RMS_S, "need": 3},
    "g4": {"seeds": SEEDS_STRESS, "dg": NOMINAL_DG,
           "snr_delta": COMBO_SNR_DELTA, "flutter_frac": COMBO_FLUTTER_FRAC,
           "jitter": 0.0, "need": 3},
}


def _ckpt():
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    return {"candidate": "B-aggr-05-dense2x",
            "status": "PREDICTION-TO-TEST (pre-registered): sim REJECT on the "
                      "timing/N256/short-symbol axis is a prediction the tape "
                      "adjudicates, not a rung-cut",
            "gate_matrix_frozen": {g: {k: v for k, v in gspec.items()}
                                   for g, gspec in GATES.items()},
            "cells": {}}


def run_gate(gate, rung, workers=4):
    g = GATES[gate]
    jobs = [(rung, s, g["dg"], g["snr_delta"], g["flutter_frac"], g["jitter"])
            for s in g["seeds"]]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_run_cell, jobs):
            rows.append(r)
            print(f"  [{gate} {rung} seed{r['seed']}] cw={r['cw_failed']}/"
                  f"{r['n_codewords']} exact={r['byte_exact']} "
                  f"fe={r['front_end']} ({r['wall_s']}s)", flush=True)
    out = _ckpt()
    out["cells"][f"{gate}:{rung}"] = rows
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    n_pass = sum(r["byte_exact"] for r in rows)
    print(f"[{gate} {rung}] {n_pass}/{len(rows)} byte-exact (need {g['need']})")


def verdict():
    out = _ckpt()
    table = {}
    for rung in D2X_RUNGS:
        sec = _get_section(rung)
        rs_k = sec["meta"]["rs_k"]
        thr = 0.6 * (255 - rs_k) / (2 * 255)
        row = {}
        for gate, g in GATES.items():
            rows = out["cells"].get(f"{gate}:{rung}")
            if not rows:
                row[gate] = None
                continue
            n_pass = sum(r["byte_exact"] for r in rows)
            row[gate] = {"pass": bool(n_pass >= g["need"]),
                         "exact": f"{n_pass}/{len(rows)}",
                         "cw_failed": [r["cw_failed"] for r in rows]}
        g1rows = out["cells"].get(f"g1:{rung}")
        if g1rows:
            ber = float(np.mean([r["byte_errors"] / r["payload_len"]
                                 for r in g1rows]))
            row["g5"] = {"mean_byte_er": round(ber, 5), "threshold": round(thr, 5),
                         "pass": bool(ber <= thr)}
        passes = [v["pass"] for v in row.values() if isinstance(v, dict)]
        if all(v is not None for v in row.values()) and len(passes) == 5:
            if all(passes):
                v = "SHIP"
            elif row["g1"]["pass"] and row["g2"]["pass"] and row["g5"]["pass"]:
                v = "HOLD"
            else:
                v = "REJECT(prediction-to-test)"
        else:
            v = "INCOMPLETE"
        row["verdict"] = v
        table[rung] = row
    out["verdict"] = table
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(table, indent=2, default=str))


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", choices=list(GATES) + ["verdict"])
    ap.add_argument("rung", nargs="?", default=None)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.gate == "verdict":
        verdict()
    else:
        rungs = [args.rung] if args.rung else D2X_RUNGS
        for r in rungs:
            run_gate(args.gate, r, workers=args.workers)
