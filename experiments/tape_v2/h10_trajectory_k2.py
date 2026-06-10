"""h10_trajectory_k2.py — H10: STABILIZE THE 842.6 HERO RUNG WITH
TRAJECTORY-AIDED TIMING (sim).

H1's WS_M16_K2_sp3_N256 @ RS(255,191) (842.6 net bps) failed seed1 — the harsh
sim realization — via margin variance (17 cw).  H5 showed on the REAL capture
that replacing the greedy per-symbol drift accumulation with a smoothed timing
TRAJECTORY (median-filter + Butterworth-2 zero-phase lowpass of the pass-1
tracker's chosen-offset sequence, loop bandwidth 0.25 Hz) reduces BER on all 9
rungs.  This experiment ports that front-end into the H1 K2 sim harness.

Pipeline per run (all achievable, no genie):
  payload 8KB slice -> m3_codec.encode_payload -> WS section + pilot sounder
    -> sim_v2.channel_v2(profile='tape7', aac=True, seed_offset=s)
    -> EQ measured from received pilot (identical to h1)
    -> PASS 1: h1's exact greedy contrast demod (decision-faithful re-impl that
       ALSO records the chosen per-symbol offsets d_k)  == the H1 baseline
    -> trajectory: drift_k = cumsum(d), medfilt(9), butter(2, bw) filtfilt
       (h5_pll_decode.build_tau_timing, verbatim port)
    -> PASS 2: steered re-demod, base_k = ds + k*N + round(tau_k), same +/-15
       max-lock search, NO greedy accumulation
    -> m3_codec.decode_payload, byte-exact vs truth (truth only for scoring).

Loop bandwidth: PRIMARY bw = 0.25 Hz (carried over from H5's real-capture
selection — pre-registered, no per-run tuning).  bw = 1.0 Hz is also evaluated
as a diagnostic only (never enters the verdict).

Runs:
  CONTROL  : pass-1 metrics of rs191 seeds {0,1,2} must reproduce
             results/h1_m16k2_results.json (same decisions => same numbers).
  RS191    : seed_offsets {0,1,2} + extra harsh-check realizations {11,21,31}
             (6 realizations total).
  RS207    : seed_offsets {0,1,2}   (~913 net bps if it opens up)
  RS159    : seed_offsets {0,1,2}   (robustness reference, 701.5 net)

PRE-REGISTERED GATE (bw=0.25 only):
  PASS    = RS191 byte-exact (steered) on >=5/6 realizations.
  PARTIAL = RS191 4/6, OR median relative raw-BER reduction >=15% on the harsh
            realizations (pass-1 not byte-exact) without flipping the rung.
  FAIL    = no improvement.

Output: results/h10_trajectory_k2.json + results/h10_trajectory_k2.log
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np
from scipy.signal import butter, filtfilt, medfilt

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                          # noqa: E402
import sim_v2                                    # noqa: E402
import m3_codec as codec                         # noqa: E402
from m3_codec import Rung                        # noqa: E402
from assault_widespace import (                  # noqa: E402
    build as ws_build, _energies_at, _score, _sym_from_score,
)
# reuse H1's exact section/pilot/EQ machinery (no re-implementation drift)
from h1_m16k2_sp3 import (                       # noqa: E402
    FS, GAP_S, PAD_S, RS_N, FRAME_BYTES, TRACK, CASS,
    build_section, eq_from_pilot,
)

RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "h10_trajectory_k2.json"
LOG_PATH = RESULTS / "h10_trajectory_k2.log"

SEED_NOTE = "channel seeds = seed_offset arg; pipeline otherwise deterministic"
BW_PRIMARY = 0.25          # Hz — H5's real-capture choice, pre-registered
BW_DIAG = 1.0              # Hz — diagnostic only
MED_KERNEL = 9             # symbols (h5 verbatim)
BASELINE_NET_BPS = 561.8

_log_fh = None


def log(msg: str) -> None:
    global _log_fh
    if _log_fh is None:
        RESULTS.mkdir(exist_ok=True)
        _log_fh = open(LOG_PATH, "a")
        _log_fh.write(f"\n===== h10_trajectory_k2 run {time.strftime('%F %T')} =====\n")
    _log_fh.write(msg + "\n")
    _log_fh.flush()
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# pass-1: h1's demod_frame_syms, decision-identical, ALSO returns offsets d_k
# ---------------------------------------------------------------------------
def demod_pass1(ws, eq, y_frame, nsym, detector="contrast", track=TRACK):
    N, bps = ws.N, ws.bits_per_sym
    tone_bins = np.clip(ws._bin_indices, 0, N // 2)
    guard_bins = ws._guard_bins
    ds = hc.find_preamble(y_frame.astype(np.float32), ws.preamble_seconds)
    yy = y_frame.astype(np.float64)
    drift = 0.0
    bits_out, syms_out = [], []
    d_out = np.zeros(nsym, np.int64)
    ok_out = np.zeros(nsym, bool)
    for sidx in range(nsym):
        base = ds + sidx * N + int(round(drift))
        best = None
        for d in range(-track, track + 1):
            et, eg = _energies_at(yy, base + d, N, tone_bins, guard_bins)
            if et is None:
                continue
            sc = _score(et, eg, eq, detector)
            si = _sym_from_score(ws, sc)
            srt = np.sort(sc)[::-1]
            lock = (srt[ws.K - 1] - srt[ws.K]) / (abs(srt[0]) + 1e-9)
            if best is None or lock > best[0]:
                best = (lock, si, d)
        if best is None:
            bits_out.extend([0] * bps)
            syms_out.append(0)
            continue
        bits_out.extend(ws._sym_to_bits(best[1]))
        syms_out.append(best[1])
        d_out[sidx] = best[2]
        ok_out[sidx] = True
        drift += best[2]
    return np.array(bits_out, np.uint8), ds, d_out, ok_out


# ---------------------------------------------------------------------------
# trajectory (h5_pll_decode.build_tau_timing, verbatim port)
# ---------------------------------------------------------------------------
def build_tau_timing(d_row: np.ndarray, fs_sym: float, bw_hz: float) -> np.ndarray:
    drift = np.concatenate([[0.0], np.cumsum(d_row.astype(np.float64))[:-1]])
    k = min(MED_KERNEL, len(drift) - (1 - len(drift) % 2))
    if k >= 3:
        drift = medfilt(drift, kernel_size=k)
    wn = min(0.99, bw_hz / (fs_sym / 2.0))
    b, a = butter(2, wn)
    if len(drift) > 3 * max(len(a), len(b)):
        drift = filtfilt(b, a, drift)
    return drift


# ---------------------------------------------------------------------------
# pass-2: steered grid, same +/-15 max-lock search, no greedy accumulation
# ---------------------------------------------------------------------------
def demod_steered(ws, eq, y_frame, nsym, ds, tau, detector="contrast",
                  track=TRACK):
    N, bps = ws.N, ws.bits_per_sym
    tone_bins = np.clip(ws._bin_indices, 0, N // 2)
    guard_bins = ws._guard_bins
    yy = y_frame.astype(np.float64)
    bits_out = []
    for sidx in range(nsym):
        base = ds + sidx * N + int(round(tau[sidx]))
        best = None
        for d in range(-track, track + 1):
            et, eg = _energies_at(yy, base + d, N, tone_bins, guard_bins)
            if et is None:
                continue
            sc = _score(et, eg, eq, detector)
            si = _sym_from_score(ws, sc)
            srt = np.sort(sc)[::-1]
            lock = (srt[ws.K - 1] - srt[ws.K]) / (abs(srt[0]) + 1e-9)
            if best is None or lock > best[0]:
                best = (lock, si, d)
        if best is None:
            bits_out.extend([0] * bps)
            continue
        bits_out.extend(ws._sym_to_bits(best[1]))
    return np.array(bits_out, np.uint8)


# ---------------------------------------------------------------------------
def metrics(frames_rx, tx_frames, meta, payload):
    raw_err = raw_tot = 0
    for tb, rb in zip(tx_frames, frames_rx):
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
    recovered = codec.decode_payload(frames_rx, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    byte_err = sum(a != b for a, b in zip(recovered, payload)) + abs(
        len(recovered) - len(payload))
    return {
        "raw_ber": round(raw_err / max(1, raw_tot), 5),
        "cw_failed": int(cw_failed),
        "byte_errors": int(byte_err),
        "byte_exact": bool(recovered == payload),
    }


def run_one(ws, rs_k, payload, seed, bws, *, label):
    t0 = time.time()
    rung = Rung(name=label, M=ws.M, K=ws.K, rs_n=RS_N, rs_k=rs_k,
                frame_bytes=FRAME_BYTES)
    tx_frames, meta = codec.encode_payload(payload, rung)
    section, starts = build_section(ws, tx_frames)

    y = sim_v2.channel_v2(section.astype(np.float64), profile="tape7",
                          aac=True, seed_offset=int(seed))
    y = y.astype(np.float32)

    pad = int(PAD_S * FS)
    eq = eq_from_pilot(ws, y, pad)
    pre = len(ws._preamble)
    N, bps = ws.N, ws.bits_per_sym
    fs_sym = FS / N

    # pass 1 (== H1 baseline) + record offsets
    p1_frames, frame_geo = [], []
    for fi, tb in enumerate(tx_frames):
        nsym = int(np.ceil(len(tb) / bps))
        flen = pre + nsym * N
        st = starts[fi]
        w_lo = max(0, st - pad)
        w_hi = min(len(y), st + flen + pad)
        yf = y[w_lo:w_hi]
        rb, ds, d_row, ok = demod_pass1(ws, eq, yf, nsym)
        p1_frames.append(rb)
        frame_geo.append((yf, ds, d_row, nsym))
    m_p1 = metrics(p1_frames, tx_frames, meta, payload)

    # pass 2 per bandwidth (steered)
    per_bw = {}
    for bw in bws:
        p2_frames = []
        for fi, tb in enumerate(tx_frames):
            yf, ds, d_row, nsym = frame_geo[fi]
            tau = build_tau_timing(d_row, fs_sym, bw)
            p2_frames.append(demod_steered(ws, eq, yf, nsym, ds, tau))
        per_bw[str(bw)] = metrics(p2_frames, tx_frames, meta, payload)

    gross = bps * FS / N
    net = gross * rs_k / RS_N
    prim = per_bw[str(BW_PRIMARY)]
    rel = ((m_p1["raw_ber"] - prim["raw_ber"]) / max(m_p1["raw_ber"], 1e-12))
    row = {
        "label": label, "phy": ws.name, "rs_k": rs_k, "seed": int(seed),
        "gross_bps": round(gross, 1), "net_bps": round(net, 1),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "baseline_pass1": m_p1,
        "steered": {bw: per_bw[bw] for bw in map(str, bws)},
        "primary_bw_hz": BW_PRIMARY,
        "rel_ber_reduction_primary": round(rel, 4),
        "wall_seconds": round(time.time() - t0, 1),
    }
    p = prim
    log(f"[h10] {label} seed{seed}: p1 ber={m_p1['raw_ber']:.4f} "
        f"cw={m_p1['cw_failed']} exact={m_p1['byte_exact']} | "
        f"traj(bw{BW_PRIMARY}) ber={p['raw_ber']:.4f} cw={p['cw_failed']} "
        f"exact={p['byte_exact']} relRed={rel * 100:+.1f}% "
        f"net={net:.1f}bps ({row['wall_seconds']}s)")
    return row


def main():
    RESULTS.mkdir(exist_ok=True)
    full = CASS.read_bytes()
    assert len(full) == 153823, len(full)

    bws = [BW_PRIMARY, BW_DIAG]
    out = {
        "experiment": "h10_trajectory_k2", "profile": "tape7", "aac": True,
        "seed_note": SEED_NOTE,
        "primary_bw_hz": BW_PRIMARY, "diag_bw_hz": BW_DIAG,
        "med_kernel": MED_KERNEL, "baseline_net_bps": BASELINE_NET_BPS,
        "control_ref": "results/h1_m16k2_results.json (rs191 seeds 0,1,2)",
        "control_check": {}, "runs": [],
    }

    def flush():
        OUT_JSON.write_text(json.dumps(out, indent=2, default=float))

    ws_k2 = ws_build(16, 2, 3, 256)
    assert ws_k2 is not None and ws_k2.name == "WS_M16_K2_sp3_N256"
    log(f"[h10] scheme {ws_k2.name} bits/sym={ws_k2.bits_per_sym} "
        f"bws={bws} (primary {BW_PRIMARY})")

    # H1 reference numbers for the control check (rs191 seeds 0,1,2)
    h1_ref = {}
    h1_json = RESULTS / "h1_m16k2_results.json"
    if h1_json.exists():
        h1 = json.loads(h1_json.read_text())
        for r in h1["h1"]:
            if r["rs_k"] == 191:
                h1_ref[r["seed"]] = {"raw_ber": r["raw_ber"],
                                     "cw_failed": r["cw_failed"],
                                     "byte_exact": r["byte_exact"]}

    offsets = {159: 8192, 191: 16384, 207: 24576}
    plan = [
        (191, [0, 1, 2, 11, 21, 31]),
        (207, [0, 1, 2]),
        (159, [0, 1, 2]),
    ]
    for rs_k, seeds in plan:
        payload = full[offsets[rs_k]:offsets[rs_k] + 8192]
        assert len(payload) == 8192
        for seed in seeds:
            r = run_one(ws_k2, rs_k, payload, seed, bws,
                        label=f"h10_m16k2_rs{rs_k}")
            out["runs"].append(r)
            # control check: pass-1 must reproduce H1 (same decisions)
            if rs_k == 191 and seed in h1_ref:
                ref = h1_ref[seed]
                got = r["baseline_pass1"]
                match = (abs(got["raw_ber"] - ref["raw_ber"]) < 5e-4
                         and got["cw_failed"] == ref["cw_failed"]
                         and got["byte_exact"] == ref["byte_exact"])
                out["control_check"][f"rs191_seed{seed}"] = {
                    "h1_ref": ref, "h10_pass1": got, "match": bool(match)}
                log(f"[ctrl] rs191 seed{seed}: H1 ref ber={ref['raw_ber']} "
                    f"cw={ref['cw_failed']} vs pass-1 ber={got['raw_ber']} "
                    f"cw={got['cw_failed']} -> match={match}")
            flush()

    # ---- gate (bw = BW_PRIMARY only) ----
    r191 = [r for r in out["runs"] if r["rs_k"] == 191]
    n_exact = sum(r["steered"][str(BW_PRIMARY)]["byte_exact"] for r in r191)
    n_real = len(r191)
    harsh = [r for r in r191 if not r["baseline_pass1"]["byte_exact"]]
    harsh_red = [r["rel_ber_reduction_primary"] for r in harsh]
    med_harsh = float(np.median(harsh_red)) if harsh_red else None
    all_red = [r["rel_ber_reduction_primary"] for r in r191]
    n_exact_p1 = sum(r["baseline_pass1"]["byte_exact"] for r in r191)

    if n_exact >= 5:
        verdict = "PASS"
    elif n_exact == 4 or (med_harsh is not None and med_harsh >= 0.15):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    r207 = [r for r in out["runs"] if r["rs_k"] == 207]
    r159 = [r for r in out["runs"] if r["rs_k"] == 159]
    out["gate"] = {
        "rs191_realizations": n_real,
        "rs191_steered_exact": int(n_exact),
        "rs191_pass1_exact": int(n_exact_p1),
        "harsh_realizations": [r["seed"] for r in harsh],
        "median_rel_ber_reduction_harsh": med_harsh,
        "median_rel_ber_reduction_all": float(np.median(all_red)),
        "rs207_steered_exact": int(sum(
            r["steered"][str(BW_PRIMARY)]["byte_exact"] for r in r207)),
        "rs159_steered_exact": int(sum(
            r["steered"][str(BW_PRIMARY)]["byte_exact"] for r in r159)),
        "control_all_match": bool(all(
            v["match"] for v in out["control_check"].values())) if
            out["control_check"] else None,
        "verdict": verdict,
    }
    out["verdict"] = verdict
    log(f"[h10] GATE: rs191 steered exact {n_exact}/{n_real} "
        f"(pass-1 {n_exact_p1}/{n_real}); harsh seeds "
        f"{[r['seed'] for r in harsh]} median relRed="
        f"{(med_harsh if med_harsh is not None else float('nan')) * 100:.1f}%; "
        f"rs207 {out['gate']['rs207_steered_exact']}/3, "
        f"rs159 {out['gate']['rs159_steered_exact']}/3 -> VERDICT {verdict}")
    flush()
    log(f"[h10] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
