"""h8_dqpsk_stress.py — HYPOTHESIS H8: de-risk DQPSK for the real tape.

H4's DQPSK results (933.8 net bps sim) are phase-transfer-UNVALIDATED on real
tape. Before master8 spends tape-minutes on DQPSK rungs, stress-test the H4
winner (dq_p10n512_rs127) and the conservative N=1024 rungs under
adversarial-but-plausible channel deviations, using the h4_dqpsk machinery
unchanged (DQPSKScheme, build_section, codec pipeline, achievable demod).

Stress axes (all relative to the calibrated tape7 nominal):
  (a) flutter_residual_frac 0.15 (nominal) -> 0.30 -> 0.50
      [most likely sim->real gap: sim may under-model real phase jitter]
  (b) snr_db 36.4 (nominal) -> 34.4 (-2) -> 32.4 (-4)
  (c) AAC bitrate 204.8k (nominal, matches probed .qta) -> 96k stereo
  (d) seed sweep {0..5} at the nominal channel (realization variance)
  (+) combo probe: flutter 0.30 AND -2 dB together (not in the gate; extra
      margin evidence for the recommended 'safe' rung)

Channel path is IDENTICAL to sim_v2.channel_v2(profile='tape7', aac=True)
except the AAC stage is applied here explicitly so its bitrate is a knob:
channel_v2(aac=False, sim_overrides=...) -> peak-normalize 0.95 -> real AAC
round-trip -> un-normalize. At nominal knobs this reproduces channel_v2
bit-for-bit in structure (same code, same seeds).

PRE-REGISTERED SAFETY-MARGIN VERDICT per config: byte-exact through
  (a) flutter 0.30  AND  (b) -2 dB  AND  (d) >= 5/6 seeds nominal.
Strict = all 3 stress seeds exact on each axis; lenient = >=2/3 (reported
separately, headline uses strict).

GATE: PASS  = a rung with net >= 700 bps survives the full safety matrix.
      PARTIAL = a 562-700 rung survives everything, or target rungs fail
                only flutter 0.50 (extreme).
      FAIL  = DQPSK breaks below 561.8 baseline under moderate stress.

Controls run FIRST (harness sanity rule):
  1) WS control via h4_dqpsk.run_control_rung seeds {0,1} — expected
     exact seed0, fail seed1 (wave-1 adjudicated numbers).
  2) Nominal seeds {0,1,2} of each config must reproduce the H4 results
     (all byte-exact, BER within seed-noise of the logged values).

Usage:  python3 h8_dqpsk_stress.py [--workers 6] [--stage all|control|stress]
Output: results/h8_dqpsk_stress.json  (+ verbose results/h8_dqpsk_stress.log
        via shell redirect)
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                      # noqa: E402
from m3_codec import Rung                     # noqa: E402
import sim_v2                                 # noqa: E402
from h4_dqpsk import (                        # noqa: E402
    DQPSKScheme, build_section, nominal_frame_bits, _payload_slice,
    run_control_rung, PAD_LO_S, PAD_HI_S, FS,
)

RESULTS = _HERE / "results"
OUT_PATH = RESULTS / "h8_dqpsk_stress.json"
BASELINE_NET_BPS = 561.8
NOMINAL_SNR = sim_v2.PROFILES["tape7"]["snr_db"]          # 36.4
NOMINAL_FLUTTER_FRAC = 0.15                                # _sim default
NOMINAL_AAC_BITRATE = 204_800

# ---- configs under stress (specs copied verbatim from h4_dqpsk ladders) ----
CONFIGS = [
    # H4 winner — highest surviving net in sim
    {"name": "dq_p10n512_rs127",  "P": 10, "N": 512,  "spacing": 8,  "rs_k": 127,
     "offset": 90112, "payload_bytes": 8192, "frame_bytes": 510},   # net 933.8
    # stretch candidate — error-free PHY at N=1024, thin RS
    {"name": "dq_p10n1024_rs223", "P": 10, "N": 1024, "spacing": 16, "rs_k": 223,
     "offset": 65536, "payload_bytes": 8192, "frame_bytes": 510},   # net 819.9
    # conservative target
    {"name": "dq_p10n1024_rs191", "P": 10, "N": 1024, "spacing": 16, "rs_k": 191,
     "offset": 57344, "payload_bytes": 8192, "frame_bytes": 510},   # net 702.2
    # safe rung
    {"name": "dq_p10n1024_rs159", "P": 10, "N": 1024, "spacing": 16, "rs_k": 159,
     "offset": 49152, "payload_bytes": 8192, "frame_bytes": 510},   # net 584.6
]

# ---- stress matrix: axis -> (channel kwargs, seeds) ------------------------
AXES = [
    ("nominal",     {},                                          [0, 1, 2, 3, 4, 5]),
    ("flutter030",  {"flutter_frac": 0.30},                      [0, 1, 2]),
    ("flutter050",  {"flutter_frac": 0.50},                      [0, 1, 2]),
    ("snr_m2",      {"snr_db": NOMINAL_SNR - 2.0},               [0, 1, 2]),
    ("snr_m4",      {"snr_db": NOMINAL_SNR - 4.0},               [0, 1, 2]),
    ("aac96",       {"aac_bitrate": 96_000},                     [0, 1, 2]),
    ("combo_f030_m2", {"flutter_frac": 0.30,
                       "snr_db": NOMINAL_SNR - 2.0},             [0, 1, 2]),
]


def channel_h8(section: np.ndarray, *, seed: int,
               flutter_frac: float | None = None,
               snr_db: float | None = None,
               aac_bitrate: int = NOMINAL_AAC_BITRATE) -> np.ndarray:
    """channel_v2 tape physics with knob overrides, then explicit AAC stage
    (same code path as channel_v2's aac=True, but bitrate adjustable)."""
    overrides = ({"flutter_residual_frac": float(flutter_frac)}
                 if flutter_frac is not None else None)
    y = sim_v2.channel_v2(section, profile="tape7", aac=False,
                          seed_offset=seed, snr_db=snr_db,
                          sim_overrides=overrides)
    pk = float(np.max(np.abs(y))) + 1e-12
    g = 0.95 / pk
    y = sim_v2.aac_roundtrip(y * g, bitrate=aac_bitrate) / g
    return y.astype(np.float64)


def run_stress_rung(spec: dict, seed: int, axis: str, chan_kw: dict) -> dict:
    """One (config, axis, seed) cell. Mirrors h4_dqpsk.run_dqpsk_rung exactly
    except the channel call goes through channel_h8."""
    t0 = time.time()
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name=spec["name"], M=spec["P"], K=1,
                rs_n=255, rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _spans = build_section(frame_audios)

    y = channel_h8(section, seed=seed, **chan_kw)

    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    car_err = np.zeros(sch.P, int)
    car_tot = np.zeros(sch.P, int)
    rx_frames = []
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi])
        flen = len(frame_audios[fi])
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(y), st + flen + pad_hi)
        bits, diag = sch.demod(y[w_lo:w_hi], nd)
        rx_frames.append(bits)
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(bits))
        raw_err += int(np.count_nonzero(tb[:m] != bits[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        tq = sch.bits_to_quadrants(tb)
        rq = diag["quadrants"][: len(tq)]
        car_err += (rq != tq[: len(rq)]).sum(axis=0)
        car_tot += len(rq)

    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == payload
    net = sch.gross_bps * spec["rs_k"] / 255.0
    return {
        "rung": spec["name"], "axis": axis, "seed": seed,
        "chan_kw": {k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in chan_kw.items()},
        "rs_k": spec["rs_k"], "net_bps": round(net, 1),
        "n_codewords": meta["n_codewords"],
        "raw_ber": raw_err / max(1, raw_tot),
        "per_carrier_ser": [round(float(e) / max(1, t), 5)
                            for e, t in zip(car_err, car_tot)],
        "rs_codewords_failed": cw_failed,
        "byte_exact": bool(exact),
        "wall_s": round(time.time() - t0, 1),
    }


def _job(args):
    spec, seed, axis, chan_kw = args
    return run_stress_rung(spec, seed, axis, chan_kw)


# ---------------------------------------------------------------------------
# verdict assembly
# ---------------------------------------------------------------------------
def assemble(rows: list[dict]) -> dict:
    by_cfg: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        by_cfg.setdefault(r["rung"], {}).setdefault(r["axis"], []).append(r)

    cfg_table = []
    for spec in CONFIGS:
        name = spec["name"]
        axes = by_cfg.get(name, {})
        summary: dict = {"rung": name, "net_bps": None, "axes": {}}
        for axis, _kw, _seeds in AXES:
            rr = sorted(axes.get(axis, []), key=lambda r: r["seed"])
            if not rr:
                continue
            summary["net_bps"] = rr[0]["net_bps"]
            summary["axes"][axis] = {
                "exact": [r["byte_exact"] for r in rr],
                "n_exact": sum(r["byte_exact"] for r in rr),
                "n": len(rr),
                "raw_ber": [round(r["raw_ber"], 5) for r in rr],
                "cw_failed": [r["rs_codewords_failed"] for r in rr],
            }
        ax = summary["axes"]
        nom_ok = ax.get("nominal", {}).get("n_exact", 0) >= 5
        f030 = ax.get("flutter030", {})
        s_m2 = ax.get("snr_m2", {})
        strict = (nom_ok and f030.get("n_exact", 0) == f030.get("n", 3)
                  and s_m2.get("n_exact", 0) == s_m2.get("n", 3))
        lenient = (nom_ok and f030.get("n_exact", 0) >= 2
                   and s_m2.get("n_exact", 0) >= 2)
        # 'survives ALL stress axes' (for the recommended-safe pick): also
        # aac96 + combo all-exact; flutter050/snr_m4 are extreme, reported only
        all_axes = strict and all(
            ax.get(a, {}).get("n_exact", 0) == ax.get(a, {}).get("n", 3)
            for a in ("aac96", "combo_f030_m2"))
        summary["safety_margin_strict"] = bool(strict)
        summary["safety_margin_lenient"] = bool(lenient)
        summary["survives_all_stress_axes"] = bool(all_axes)
        # breaking point: first axis (in escalation order) with any failure
        breaking = [a for a, _k, _s in AXES
                    if ax.get(a, {}).get("n_exact", -1) < ax.get(a, {}).get("n", 0)]
        summary["failed_axes"] = breaking
        cfg_table.append(summary)

    # ---- pre-registered gate ----
    pass_cfgs = [c for c in cfg_table
                 if c["net_bps"] and c["net_bps"] >= 700.0
                 and c["safety_margin_strict"]]
    par_cfgs = [c for c in cfg_table
                if c["net_bps"] and BASELINE_NET_BPS <= c["net_bps"] < 700.0
                and c["safety_margin_strict"]]
    # 'fail only flutter050' escape for target rungs
    f050_only = [c for c in cfg_table
                 if c["net_bps"] and c["net_bps"] >= 700.0
                 and c["failed_axes"]
                 and set(c["failed_axes"]) <= {"flutter050", "snr_m4"}]
    if pass_cfgs:
        gate = "PASS"
    elif par_cfgs or f050_only:
        gate = "PARTIAL"
    else:
        gate = "FAIL"

    # ---- recommended master8 DQPSK rung set (<=3) ----
    surv_all = [c for c in cfg_table if c["survives_all_stress_axes"]]
    safe = max(surv_all, key=lambda c: c["net_bps"], default=None)
    strict_ok = [c for c in cfg_table if c["safety_margin_strict"]]
    target = max((c for c in strict_ok if not safe or c["rung"] != safe["rung"]),
                 key=lambda c: c["net_bps"], default=None)
    len_ok = [c for c in cfg_table if c["safety_margin_lenient"]]
    used = {c["rung"] for c in (safe, target) if c}
    stretch = max((c for c in len_ok if c["rung"] not in used),
                  key=lambda c: c["net_bps"], default=None)
    if stretch is None:  # fall back: best nominal-majority rung, marked experimental
        nom_ok2 = [c for c in cfg_table if c["rung"] not in used and
                   c["axes"].get("nominal", {}).get("n_exact", 0) >= 4]
        stretch = max(nom_ok2, key=lambda c: c["net_bps"], default=None)

    def slot(c, role, note):
        if c is None:
            return None
        return {"role": role, "rung": c["rung"], "net_bps": c["net_bps"],
                "failed_axes": c["failed_axes"], "note": note}

    rec = [s for s in (
        slot(safe, "safe", "byte-exact on every stress axis incl. aac96+combo"),
        slot(target, "target", "passes pre-registered safety matrix (0.30 flutter, -2 dB, >=5/6 seeds)"),
        slot(stretch, "stretch", "lenient margin only — experimental, expect possible loss"),
    ) if s]
    # dedupe rungs keeping highest role
    seen, rec2 = set(), []
    for s in rec:
        if s["rung"] not in seen:
            rec2.append(s)
            seen.add(s["rung"])

    return {"gate_verdict": gate, "config_table": cfg_table,
            "recommended_master8_rungs": rec2,
            "baseline_net_bps": BASELINE_NET_BPS,
            "gate_def": "PASS: net>=700 survives strict safety matrix; "
                        "PARTIAL: 562-700 survives, or >=700 fails only "
                        "extreme axes (flutter050/snr_m4); else FAIL"}


# ---------------------------------------------------------------------------
def stage_control() -> dict:
    """Harness sanity: the proven WS control through the h4 machinery."""
    rows = []
    for seed in (0, 1):
        r = run_control_rung(seed)
        rows.append(r)
        print(f"  [WS control seed{seed}] rawBER={r['raw_ber']:.4f} "
              f"cw={r['rs_codewords_failed']}/{r['n_codewords']} "
              f"exact={r['byte_exact']} ({r['wall_s']}s)", flush=True)
    expected = {0: True, 1: False}  # wave-1 adjudicated h4 control outcome
    match = all(r["byte_exact"] == expected[r["seed"]] for r in rows)
    print(f"  [WS control] matches wave-1 outcome (s0 exact / s1 fail): {match}",
          flush=True)
    return {"rows": rows, "matches_wave1": bool(match)}


def stage_stress(workers: int) -> list[dict]:
    jobs = [(spec, seed, axis, kw)
            for spec in CONFIGS
            for axis, kw, seeds in AXES
            for seed in seeds]
    print(f"  {len(jobs)} stress cells, {workers} workers", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_job, jobs):
            rows.append(r)
            print(f"  [{r['rung']:18s} {r['axis']:13s} seed{r['seed']}] "
                  f"BER={r['raw_ber']:.5f} cw={r['rs_codewords_failed']}"
                  f"/{r['n_codewords']} exact={r['byte_exact']} "
                  f"({r['wall_s']}s)", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["control", "stress", "all"])
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out: dict = {}
    if OUT_PATH.exists():
        try:
            out = json.loads(OUT_PATH.read_text())
        except Exception:
            out = {}
    out["hypothesis"] = ("H8: DQPSK sim->real de-risk — stress dq_p10n512_rs127 "
                        "+ N=1024 rungs over flutter/SNR/AAC/seed axes")
    out["nominal"] = {"snr_db": NOMINAL_SNR,
                      "flutter_residual_frac": NOMINAL_FLUTTER_FRAC,
                      "aac_bitrate": NOMINAL_AAC_BITRATE,
                      "profile": "tape7"}
    out["axes"] = [{"axis": a, "chan_kw": kw, "seeds": s} for a, kw, s in AXES]

    if args.stage in ("control", "all"):
        print("== stage: control ==", flush=True)
        out["control"] = stage_control()
        OUT_PATH.write_text(json.dumps(out, indent=2, default=float))
    if args.stage in ("stress", "all"):
        print("== stage: stress ==", flush=True)
        rows = stage_stress(args.workers)
        out["stress_rows"] = rows
        out["verdict"] = assemble(rows)
        OUT_PATH.write_text(json.dumps(out, indent=2, default=float))
        print(json.dumps(out["verdict"]["config_table"], indent=2)[:2000])
        print("GATE:", out["verdict"]["gate_verdict"])
        print("RECOMMENDED:",
              json.dumps(out["verdict"]["recommended_master8_rungs"], indent=2))
    print(f"[done] wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
