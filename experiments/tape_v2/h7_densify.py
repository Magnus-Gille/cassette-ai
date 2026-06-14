"""h7_densify.py — H7: PUSH THE TONE-PHY DENSITY FRONTIER past H1's 842.6 net bps.

Three orthogonal densification axes on the proven wide-spaced geometry
(562.5 Hz-class tone pitch, contrast detector, concentration-lock tracker),
evaluated with the H1 harness pattern (machinery imported from h1_m16k2_sp3):

  (a) K=3 on the proven grid: WS_M16_K3_sp3_N256, C(16,3)=560 -> 9 bits/sym,
      gross 1687.5 bps. Band 562.5..9000 Hz (same as proven K1/K2 grid — fits).
      RS127 nets 840.4, RS159 nets 1052.2, RS191 nets 1264.0.
  (b) Faster symbols: N=192 (250 Hz bins, sp3 = 750 Hz pitch).
      BAND-FIT CHECK against the real 400-9500 Hz channel:
        M16 N192: top tone 11750 Hz  -> OVERFLOW (also > builder F_HIGH 11 kHz)
        M16 N224: top tone 10071 Hz  -> > 9500, rejected
        M14 N192: top tone 10250 Hz  -> > 9500, rejected
        M13 N192: top tone  9500 Hz  -> exactly at edge, rejected (rolloff)
        M12 N192: top tone  8750 Hz  -> FITS (500..8750 Hz)
      => WS_M12_K2_sp3_N192, C(12,2)=66 -> 6 bits/sym, gross 1500 bps.
      RS127 nets 747.1, RS159 nets 935.3, RS191 nets 1123.5.
  (c) More tones (contingency, only run if (a) and (b) both fail the gate):
      WS_M20_K2_sp3_N320 (450 Hz pitch, 450..9000 Hz fits), C(20,2)=190 ->
      7 bits/sym, gross 1050 bps. RS159 nets 654.7, RS191 nets 786.5.

Protocol (= H1): 8 KB slices of stories260K_int4.cass (m7 offsets), seeds
{0,1,2}, sim_v2.channel_v2(profile='tape7', aac=True), pilot-measured EQ,
ACHIEVABLE demod (no genie in verdicts), m3_codec RS+interleave, byte-exact
scoring. net = gross * rs_k/255 (anchor 750 gross @ RS191 = 561.8).

MANDATORY CONTROL: ctrl_m16k1_rs191 seeds {0,1} via the identical run path —
must reproduce results/h1_m16k2_results.json (seed0 raw .0105 / 0 cw / exact;
seed1 raw .0563 / 41 cw / fail).

Diagnostics (seed-0 runs, truth-aided, NOT in verdicts): K-generic tone-set
confusion (|detected ∩ true| histogram), per-tone miss/false histograms
(band-rolloff tell: errors concentrated at high tone indices), pilot EQ curve.

PRE-REGISTERED GATE:
  PASS    = some config with net > 842.6 byte-exact >= 2/3 seeds.
  PARTIAL = net in 702..842.6 byte-exact 3/3, or a clear closed-frontier diagnosis.
  FAIL    = otherwise.

Output: results/h7_densify_results.json  (+ results/h7_densify.log).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import real_channel_sim as rcs                # noqa: E402
import sim_v2                                 # noqa: E402
import m3_codec as codec                      # noqa: E402
from m3_codec import Rung                     # noqa: E402
from assault_widespace import build as ws_build, eval_scheme  # noqa: E402

# Reuse the H1 machinery verbatim (build_section/pilot-EQ/achievable demod).
import h1_m16k2_sp3 as h1                     # noqa: E402

FS = h1.FS
PAD_S = h1.PAD_S
RS_N = h1.RS_N
FRAME_BYTES = h1.FRAME_BYTES

RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "h7_densify_results.json"
LOG = RESULTS / "h7_densify.log"

H1_BEST_NET = 842.6
PARTIAL_LO = 702.0
CASS = h1.CASS
OFFSETS = {111: 24576, 127: 0, 159: 8192, 191: 16384}  # m7/h1-style slices

_logf = None


def log(msg):
    print(msg, flush=True)
    if _logf:
        _logf.write(msg + "\n")
        _logf.flush()


# ---------------------------------------------------------------------------
# run one config end-to-end. Copy of h1.run_one with K-GENERIC diagnostics
# (h1's confusion dict assumed K=2); demod decisions are identical (same
# build_section / eq_from_pilot / demod_frame_syms).
# ---------------------------------------------------------------------------
def run_one(ws, rs_k, payload, seed, *, label, diagnostics=False):
    t0 = time.time()
    rung = Rung(name=label, M=ws.M, K=ws.K, rs_n=RS_N, rs_k=rs_k,
                frame_bytes=FRAME_BYTES)
    tx_frames, meta = codec.encode_payload(payload, rung)
    section, starts = h1.build_section(ws, tx_frames)

    y = sim_v2.channel_v2(section.astype(np.float64), profile="tape7",
                          aac=True, seed_offset=int(seed))
    y = y.astype(np.float32)

    pad = int(PAD_S * FS)
    eq = h1.eq_from_pilot(ws, y, pad)   # signal-derived, no truth
    pre = len(ws._preamble)
    N, bps = ws.N, ws.bits_per_sym

    raw_err = raw_tot = 0
    frames_rx = []
    inter_hist = {k: 0 for k in range(ws.K + 1)}  # |detected ∩ true| over sym errors
    n_sym_tot = n_sym_err = 0
    miss_hist = np.zeros(ws.M, int)   # true tone not detected
    false_hist = np.zeros(ws.M, int)  # detected tone not in truth
    for fi, tb in enumerate(tx_frames):
        nbits = len(tb)
        nsym = int(np.ceil(nbits / bps))
        flen = pre + nsym * N
        st = starts[fi]
        w_lo = max(0, st - pad)
        w_hi = min(len(y), st + flen + pad)
        rb, syms = h1.demod_frame_syms(ws, eq, y[w_lo:w_hi], nsym)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        frames_rx.append(rb)
        if diagnostics:
            tbits = tb
            padb = (-len(tbits)) % bps
            if padb:
                tbits = np.concatenate([tbits, np.zeros(padb, np.uint8)])
            for sidx in range(nsym):
                ts = ws._bits_to_sym(tbits[sidx * bps:(sidx + 1) * bps])
                ds_ = syms[sidx]
                n_sym_tot += 1
                if ds_ == ts:
                    continue
                n_sym_err += 1
                tset = set(ws._table[ts].tolist())
                dset = set(ws._table[ds_].tolist())
                inter_hist[len(tset & dset)] += 1
                for tone in tset - dset:
                    miss_hist[tone] += 1
                for tone in dset - tset:
                    false_hist[tone] += 1

    recovered = codec.decode_payload(frames_rx, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == payload
    byte_err = sum(a != b for a, b in zip(recovered, payload)) + abs(
        len(recovered) - len(payload))

    gross = ws.bits_per_sym * FS / ws.N
    net = gross * rs_k / RS_N
    row = {
        "label": label, "phy": ws.name, "rs_k": rs_k, "seed": int(seed),
        "gross_bps": round(gross, 1), "net_bps": round(net, 1),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "raw_ber": round(raw_err / max(1, raw_tot), 5),
        "cw_failed": cw_failed,
        "byte_errors": byte_err,
        "byte_exact": bool(exact),
        "section_seconds": round(len(section) / FS, 1),
        "wall_seconds": round(time.time() - t0, 1),
    }
    if diagnostics:
        row["pilot_eq"] = np.round(eq, 3).tolist()
        row["sym_err_rate"] = round(n_sym_err / max(1, n_sym_tot), 4)
        row["confusion_inter_hist"] = {
            f"shared_{k}_of_{ws.K}": v for k, v in inter_hist.items()}
        row["miss_per_tone"] = miss_hist.tolist()
        row["false_per_tone"] = false_hist.tolist()
    return row


def band_fit_row(M, K, sp, N):
    ws = ws_build(M, K, sp, N)
    if ws is None:
        df = FS / N
        import math
        b0 = math.ceil(400.0 / df)
        top = (b0 + sp * (M - 1)) * df
        return {"name": f"WS_M{M}_K{K}_sp{sp}_N{N}", "builds": False,
                "top_hz": round(top, 1), "fits_9500": False}
    return {"name": ws.name, "builds": True,
            "f_lo_hz": float(ws.freqs[0]), "top_hz": float(ws.freqs[-1]),
            "fits_9500": bool(ws.freqs[-1] <= 9500.0),
            "bits_per_sym": ws.bits_per_sym,
            "gross_bps": round(ws.bits_per_sym * FS / ws.N, 1)}


def run_ladder(out, key, ws, rs_ks, payload_full, seeds=(0, 1, 2)):
    """Run a rung ladder; returns list of rows (also appended to out[key])."""
    for rs_k in rs_ks:
        payload = payload_full[OFFSETS[rs_k]:OFFSETS[rs_k] + 8192]
        assert len(payload) == 8192
        for seed in seeds:
            r = run_one(ws, rs_k, payload, seed,
                        label=f"{key}_{ws.name}_rs{rs_k}",
                        diagnostics=(seed == 0))
            out[key].append(r)
            extra = (f" symErr={r['sym_err_rate']}" if "sym_err_rate" in r else "")
            log(f"[{key}] {ws.name} rs{rs_k} seed{seed}: "
                f"raw_ber={r['raw_ber']:.4f} "
                f"cw_failed={r['cw_failed']}/{r['n_codewords']} "
                f"byte_exact={r['byte_exact']} net={r['net_bps']}bps"
                f"{extra} ({r['wall_seconds']}s)")
            _flush(out)


def _flush(out):
    OUT_JSON.write_text(json.dumps(out, indent=2, default=float))


def gate(rows):
    """Apply the pre-registered gate over all experimental rows."""
    best_pass = None
    best_partial = None
    by_cfg = {}
    for r in rows:
        by_cfg.setdefault((r["phy"], r["rs_k"], r["net_bps"]), []).append(r)
    for (phy, rs_k, net), rs in sorted(by_cfg.items(), key=lambda x: -x[0][2]):
        n_exact = sum(r["byte_exact"] for r in rs)
        n = len(rs)
        if net > H1_BEST_NET and n >= 3 and n_exact >= 2:
            if best_pass is None:
                best_pass = {"phy": phy, "rs_k": rs_k, "net_bps": net,
                             "seeds_exact": n_exact, "n_seeds": n}
        elif PARTIAL_LO <= net <= H1_BEST_NET and n >= 3 and n_exact == 3:
            if best_partial is None:
                best_partial = {"phy": phy, "rs_k": rs_k, "net_bps": net,
                                "seeds_exact": n_exact, "n_seeds": n}
    if best_pass:
        return "PASS", best_pass
    if best_partial:
        return "PARTIAL", best_partial
    return "FAIL", None


def main():
    global _logf
    RESULTS.mkdir(exist_ok=True)
    _logf = open(LOG, "w")
    full = CASS.read_bytes()
    assert len(full) == 153823, len(full)

    out = {"experiment": "h7_densify", "profile": "tape7", "aac": True,
           "h1_best_net_bps": H1_BEST_NET, "frame_bytes": FRAME_BYTES,
           "gap_s": h1.GAP_S, "pad_s": PAD_S, "seeds": [0, 1, 2],
           "band_fit": [], "sanity": {}, "control": [],
           "h7a_k3": [], "h7b_n192": [], "h7c_m20": []}

    # ---- band-fit documentation (axis b candidates + chosen schemes) ----
    for cfg in [(16, 3, 3, 256), (16, 2, 3, 192), (16, 2, 3, 224),
                (14, 2, 3, 192), (13, 2, 3, 192), (12, 2, 3, 192),
                (20, 2, 3, 320)]:
        row = band_fit_row(*cfg)
        out["band_fit"].append(row)
        log(f"[band] {row}")
    _flush(out)

    # ---- build chosen schemes ----
    ws_ctrl = ws_build(16, 1, 3, 256)
    ws_a = ws_build(16, 3, 3, 256)     # axis (a)
    ws_b = ws_build(12, 2, 3, 192)     # axis (b) — documented band fit above
    ws_c = ws_build(20, 2, 3, 320)     # axis (c) contingency
    assert ws_a and ws_a.bits_per_sym == 9, ws_a
    assert ws_b and ws_b.bits_per_sym == 6 and ws_b.freqs[-1] <= 9500
    assert ws_c and ws_c.bits_per_sym == 7 and ws_c.freqs[-1] <= 9500

    # ---- no-channel sanity (demod-bug catch) ----
    params = rcs.load_params()
    for tag, ws in (("ctrl_k1", ws_ctrl), ("a_m16k3", ws_a),
                    ("b_m12k2n192", ws_b), ("c_m20k2n320", ws_c)):
        s = eval_scheme(ws, params, "master3", detector="contrast",
                        reps=2, nsym=48, sanity=True)["sanity_ber"]
        out["sanity"][f"{tag}_nochannel_ber"] = s
        log(f"[sanity] {ws.name}: no-channel BER={s:.2e}")
        assert s < 1e-6, f"demod bug: sanity BER {s} on {ws.name}"
    _flush(out)

    # ---- CONTROL: reproduce h1 control exactly ----
    ctrl_payload = full[16384:16384 + 8192]
    expect = {0: (0.01049, 0, True), 1: (0.05632, 41, False)}
    ctrl_ok = True
    for seed in (0, 1):
        r = run_one(ws_ctrl, 191, ctrl_payload, seed, label="ctrl_m16k1_rs191")
        out["control"].append(r)
        e = expect[seed]
        match = (abs(r["raw_ber"] - e[0]) < 0.005 and r["byte_exact"] == e[2])
        ctrl_ok &= match
        log(f"[ctrl] seed{seed}: raw_ber={r['raw_ber']:.4f} "
            f"cw_failed={r['cw_failed']}/{r['n_codewords']} "
            f"byte_exact={r['byte_exact']} (h1 expected raw~{e[0]} "
            f"cw={e[1]} exact={e[2]}; match={match}) ({r['wall_seconds']}s)")
        _flush(out)
    out["control_reproduces_h1"] = bool(ctrl_ok)
    if not (out["control"][0]["raw_ber"] < 0.10):
        log("[ctrl] HARNESS BROKEN — aborting")
        _flush(out)
        return

    # ---- axis (a): K=3 ladder ----
    log(f"[h7a] {ws_a.name}: 9 b/sym, freqs {ws_a.freqs[0]:.1f}.."
        f"{ws_a.freqs[-1]:.1f} Hz, n_symbols={ws_a.n_symbols}")
    run_ladder(out, "h7a_k3", ws_a, (127, 159, 191), full)

    # ---- axis (b): N=192 ladder ----
    log(f"[h7b] {ws_b.name}: 6 b/sym, freqs {ws_b.freqs[0]:.1f}.."
        f"{ws_b.freqs[-1]:.1f} Hz, n_symbols={ws_b.n_symbols}")
    run_ladder(out, "h7b_n192", ws_b, (127, 159, 191), full)

    # ---- interim gate; axis (c) only if (a) and (b) both fail ----
    verdict, best = gate(out["h7a_k3"] + out["h7b_n192"])
    if verdict == "FAIL":
        log(f"[h7c] axes (a)+(b) gate=FAIL -> running contingency {ws_c.name}: "
            f"7 b/sym, freqs {ws_c.freqs[0]:.1f}..{ws_c.freqs[-1]:.1f} Hz")
        run_ladder(out, "h7c_m20", ws_c, (159, 191), full)
        verdict, best = gate(out["h7a_k3"] + out["h7b_n192"] + out["h7c_m20"])

    out["verdict"] = verdict
    out["best"] = best
    log(f"[h7] VERDICT={verdict} best={best}")
    _flush(out)
    log(f"[h7] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
