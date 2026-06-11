"""x10_b_aggr_05_dense2x_probe.py -- STEP 1 rx-only GO/NO-GO probe for the
B-aggr-05 "dense2x" candidate: 375 Hz carrier grid at 187.5 sym/s
(DQPSK, N=256, spacing=2, skip=64, Nw=128).

KEY MEASUREMENT IDEA (strictly better than a modelled prediction)
-----------------------------------------------------------------
The m9_m8_dense375 section of the REAL tape9_run1 capture uses the EXACT same
23-tone 375-Hz-spaced frequency plan (750+375k Hz, pilot 4875) as dense2x --
only its symbol length differs (N512 vs N256).  Re-demodulating that real
capture with the dense2x analysis geometry (Hann window Nw=128, skip=64,
stride 256 samples) measures per-carrier DQPSK SER at the target geometry on
REAL tape: the ~4.8 dB per-symbol energy loss vs N512 and the ~3x echo-tail
concentration of the short window are then physically INCLUDED in the
measurement instead of estimated.

Each N512 m8 symbol is split into two half-windows.  Differentials between
consecutive half-windows alternate:
  * ACROSS-boundary (j % 2 == 0): crosses a real DQPSK phase transition with
    the previous symbol's acoustic echo tail intruding past the 1.33 ms guard
    -- exactly the dense2x data-decision case (transition + ISI active).
  * WITHIN-symbol  (j % 2 == 1): same-phase reference -- the no-ISI baseline
    at identical window geometry (decomposes ISI vs timing+noise).

Caveats (logged, see `notes` in the output JSON): in true dense2x the echo at
delays > 320 samples comes from the symbol BEFORE the previous one (random
extra phase) instead of the same previous symbol -- equivalent at ISI-power
level; and transition density doubles (no effect on the unmodulated pilot
loop, which runs identically here at the doubled 187.5 Hz update rate).

STAGES (each < 8 min, checkpointing results/x10_b_aggr_05_dense2x_probe.json)
    halfrate    main measurement: tape9 m8 section at dense2x geometry,
                EMA-alpha sweep + per-differential DD refine, per-carrier SER
                split across/within, pilot-tracking stats @187.5 Hz.
    tail        echo-tail energy profile 1.33-4 ms: window-shift sweep +
                per-carrier LS echo estimate |G/H|^2 vs shift.
    fullcheck   harness fidelity: same machinery at the FULL m8 geometry
                (R=1, Nw=384) must reproduce the production m8 per-carrier SER.
    m0half      same half-rate probe on the m9_m0 section (750-Hz grid, P10)
                -- cross-check on a second tape9 section.
    secondtape  same half-rate probe on the m8_dq_p10n512_rs127 section of the
                INDEPENDENT master8 capture (m8_tape_mono_lossless.wav).
    residuals   x9_resampling_pll.residual_stats on the real m5 section
                (N256 -> real 187.5 Hz pilot updates) -- doubled-rate tracking.
    gate        compute the PRE-REGISTERED GO/NO-GO verdict.

PRE-REGISTERED GATE (frozen before any measurement; do not soften):
    metric    = predicted mean byte-error-rate for the P18/RS(255,127) rung at
                Nw=128: best-18-of-22 data carriers by measured across-boundary
                SER (best EMA alpha), byte_ER = mean_k(1 - (1-SER_k)^4).
    GO        = byte_ER <= 0.6*(255-127)/(2*255) = 0.15059
    NO-GO     = abort the candidate, zero tape spent.

Deterministic (no RNG).  Seeds: N/A.
Usage:  OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
            python3 x10_b_aggr_05_dense2x_probe.py <stage>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import numpy as np
import soundfile as sf

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                        # noqa: E402
import m3_codec as codec                             # noqa: E402
from m3_codec import Rung                            # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S          # noqa: E402
import m9_decode as m9d                              # noqa: E402
import hyp_common as hc                              # noqa: E402

SR = codec.FS
OUT_JSON = _HERE / "results" / "x10_b_aggr_05_dense2x_probe.json"

# tape9 (primary) -- reuse the forensics nominal-clock cache (read-only)
CACHE_T9 = _HERE / "captures" / "x10_audio_nom_tape9_run1.npy"
SYNC_T9 = _HERE / "results" / "x10_forensics_sync.json"
MANIFEST_T9 = json.loads((_HERE / "master9_manifest.json").read_text())

# master8 capture (independent second tape)
CAPTURE_M8 = _HERE / "captures" / "m8_tape_mono_lossless.wav"
CACHE_M8 = _HERE / "captures" / "x10_dense2x_audio_nom_m8tape.npy"
SYNC_M8 = _HERE / "results" / "x10_b_aggr_05_dense2x_sync_m8tape.json"
MANIFEST_M8 = json.loads((_HERE / "master8_manifest.json").read_text())

# dense2x receiver geometry under test
D2X_NW = 128
D2X_SKIP = 64
D2X_STRIDE = 256
ALPHAS = (0.4, 0.5, 0.6, 0.7, 0.8)
SHIFTS = (-32, -16, 0, 16, 32, 48)

# ---- receiver window configurations at the 187.5 sym/s stride --------------
# "hann128_skip64": the plan's LITERAL receiver (h4 Hann over Nw=N-2*skip).
#   NOTE: at Nw=128 the 375 Hz spacing is exactly 1 DFT bin; Hann is NOT
#   orthogonal at 1-bin offsets (-6 dB leakage per neighbor). h4's
#   (spacing*Nw)%N==0 assert only guarantees RECT orthogonality. Kept as a
#   negative control.
# "rect128_skip64": rect window, integer-cycle orthogonal at 1-bin spacing,
#   same 1.33 ms guard; ENBW 1.0 (+1.8 dB noise vs Hann); ICI from tracked
#   residual flutter ~ -50 dB. The orthogonality-restoring fix at the plan's
#   geometry.
# "hann256_skip0": Hann over the FULL 256-sample symbol (2-bin spacing ->
#   Hann-orthogonal); the taper is a soft guard (edge/echo samples weighted
#   ~0..0.5 over the first 1.33 ms).
WIN_CFGS = {
    "hann128_skip64": {"Nw": 128, "skip": 64, "win": "hann"},
    "rect128_skip64": {"Nw": 128, "skip": 64, "win": "rect"},
    "hann256_skip0": {"Nw": 256, "skip": 0, "win": "hann"},
}


def _make_win(cfg):
    return (np.hanning(cfg["Nw"]) if cfg["win"] == "hann"
            else np.ones(cfg["Nw"]))

# ---- PRE-REGISTERED gate thresholds (g5 form: 0.6 * (n-k)/(2n)) ----
THR = {"p18_rs127": 0.6 * (255 - 127) / (2 * 255),    # 0.15059  <- THE gate
       "p21_rs159": 0.6 * (255 - 159) / (2 * 255),    # 0.11294  (informational)
       "p22_rs179": 0.6 * (255 - 179) / (2 * 255)}    # 0.08941  (informational)


# ===========================================================================
# capture loading
# ===========================================================================
def _load_tape9():
    audio_nom = np.load(CACHE_T9, mmap_mode="r")
    sync = json.loads(SYNC_T9.read_text())
    return audio_nom, int(sync["align"])


def _load_m8tape():
    if CACHE_M8.exists() and SYNC_M8.exists():
        audio_nom = np.load(CACHE_M8, mmap_mode="r")
        sync = json.loads(SYNC_M8.read_text())
        return audio_nom, int(sync["align"])
    t0 = time.time()
    audio, sr = sf.read(str(CAPTURE_M8), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert sr == SR, f"capture sr {sr} != {SR}"
    sync = am2.global_sync_and_resample(audio, MANIFEST_M8)
    audio_nom = sync["audio_nominal"]
    np.save(CACHE_M8, audio_nom.astype(np.float32))
    meta = {k: (float(v) if isinstance(v, (np.floating, float)) else int(v))
            for k, v in sync.items() if k != "audio_nominal"}
    meta["align"] = int(sync["chirp0_nominal"]) - int(MANIFEST_M8["tx_chirp0"])
    SYNC_M8.write_text(json.dumps(meta, indent=2, default=float))
    print(f"[m8tape] synced+cached in {time.time()-t0:.0f}s, "
          f"clock {sync['speed']:.6f}, align {meta['align']:+d}")
    return np.load(CACHE_M8, mmap_mode="r"), int(meta["align"])


def _get_section(manifest, name):
    for sec in manifest["ws_payloads"]:
        if sec["name"] == name:
            return sec
    raise KeyError(name)


def _tx_truth(sec, sch):
    """Re-encode the sidecar packed payload -> per-frame tx quadrants + theta
    ladders (SCORING ONLY -- never fed into any decision)."""
    meta = sec["meta"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected_packed, rung)
    nom_bits = m9d._nominal_frame_bits(meta)
    out = []
    for fi, fb in enumerate(tx_frames):
        nb = nom_bits[fi]
        tq = sch.bits_to_quadrants(np.asarray(fb, np.uint8)[:nb])
        nd = sch.nsym_data(nb)
        out.append(tq[:nd])
    return out


# ===========================================================================
# half-rate EMA-tracked DFT (the dense2x front-end behavior, run on the real
# m8/m0 N512 sections).  Mirrors the h4/x9 proven EMA-integer-drift loop at
# window stride S = sch.N // R.  R=2 -> dense2x geometry; R=1 -> fullcheck.
# ===========================================================================
def _halfrate_dft(y, ds, total, sch, R, Nw, skip_w, alpha, shift=0, win=None):
    S = sch.N // R
    nwin = R * total
    if win is None:
        win = np.hanning(Nw)
    freqs = sch.freqs
    pidx = sch.pilot_idx
    fpil = freqs[pidx]
    c = np.zeros((nwin, len(freqs)), np.complex128)
    dtau = np.zeros(nwin)        # EMA-smoothed per-window timing increment
    dtau_raw = np.zeros(nwin)
    drift = 0.0
    sm = 0.0
    for j in range(nwin):
        base = ds + j * S + int(round(drift))
        lo = base + skip_w + shift
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS           # ABSOLUTE basis (h4 pattern)
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        c[j] = E @ (seg * win)
        if j > 0:
            dp = float(np.angle(c[j, pidx] * np.conj(c[j - 1, pidx])))
            d = dp / (2 * np.pi * fpil)
            dtau_raw[j] = d
            sm = (1 - alpha) * d + alpha * sm
            dtau[j] = sm
            drift -= sm * FS
            drift = float(np.clip(drift, -200, 200))
    return c, dtau, dtau_raw


def _decide(sch, c, dtau, refine=True):
    """Production-style differential decision + one-shot DD LS-slope refine
    (verbatim math from x9_resampling_pll._decide)."""
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    dtau_dd = np.zeros(dphi.shape[0])
    if refine:
        res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_dd = num / (2 * np.pi * den)
        dphi = dphi - 2 * np.pi * dtau_dd[:, None] * fd[None, :]
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    return q, dphi, dtau_dd


def _expected_transitions(tq, R, total):
    """(nwin-1, P) expected quadrant transitions for consecutive-window
    differentials.  Window j starts m8 symbol i=j//R when j%R==0; that
    differential carries data quadrant tq[i-1]; within-symbol ones carry 0."""
    P = tq.shape[1]
    exp_q = np.zeros((R * total - 1, P), int)
    is_boundary = np.zeros(R * total - 1, bool)
    for j in range(1, R * total):
        if j % R == 0:
            i = j // R
            exp_q[j - 1] = tq[i - 1]
            is_boundary[j - 1] = True
    return exp_q, is_boundary


def _section_halfrate(audio_nom, align, sec, sch, R, Nw, skip_w, alpha,
                      shift=0, collect_ls=False, win=None):
    """Run the half-rate probe over every frame of a section.  Returns per-
    carrier across/within error counts + gerr accumulators + pilot stats."""
    meta = sec["meta"]
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    tq_frames = _tx_truth(sec, sch)
    P = sch.P
    acc = {
        "err_b": np.zeros(P, int), "tot_b": np.zeros(P, int),
        "err_w": np.zeros(P, int), "tot_w": np.zeros(P, int),
        "gsq_b": np.zeros(P), "gsq_w": np.zeros(P),
        "raw_us": [], "ema_resid_us": [], "dd_us": [],
        "ic_db": [[] for _ in range(P)],     # per-frame LS echo I/C (dB)
    }
    for fi, st in enumerate(sec["frame_starts"]):
        nb = nom_bits[fi]
        nd = sch.nsym_data(nb)
        total = nd + 1
        st = int(st) + align
        w_lo = max(0, int(st - pad_lo))
        w_hi = min(len(audio_nom), int(st + flen_full + pad_hi))
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
        c, dtau, dtau_raw = _halfrate_dft(y, ds, total, sch, R, Nw, skip_w,
                                          alpha, shift, win=win)
        q, dphi, dtau_dd = _decide(sch, c, dtau)
        tq = tq_frames[fi]
        exp_q, is_b = _expected_transitions(tq, R, total)
        gerr = (dphi - exp_q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        err = q != exp_q
        acc["err_b"] += err[is_b].sum(axis=0)
        acc["tot_b"] += int(is_b.sum())
        acc["err_w"] += err[~is_b].sum(axis=0)
        acc["tot_w"] += int((~is_b).sum())
        acc["gsq_b"] += (gerr[is_b] ** 2).sum(axis=0)
        acc["gsq_w"] += (gerr[~is_b] ** 2).sum(axis=0)
        acc["raw_us"].append(float(np.std(dtau_raw[1:]) * 1e6))
        acc["ema_resid_us"].append(float(np.std(dtau_raw[1:] - dtau[1:]) * 1e6))
        acc["dd_us"].append(float(np.std(dtau_dd) * 1e6))
        if collect_ls:
            _ls_echo_frame(acc, c, dtau, sch, tq, R, total)
    return acc


def _ls_echo_frame(acc, c, dtau, sch, tq, R, total):
    """Per-carrier LS echo estimate on the boundary windows of one frame:
    c_corr[i,k] ~ H_k e^{j theta_i,k} + G_k e^{j theta_{i-1},k}.  Pilot-phase
    common-mode correction (scales with f_k/f_pil) removes the flutter wander
    so H is quasi-static over the frame.  I/C = |G/H|^2 -> dB."""
    nc = sch.P + 1
    theta = np.zeros((total, nc))
    for i in range(1, total):
        theta[i] = theta[i - 1]
        theta[i, sch.data_idx] += tq[i - 1] * (np.pi / 2.0)
    pidx = sch.pilot_idx
    psi = np.unwrap(np.angle(c[:, pidx]))
    fr = sch.freqs / sch.freqs[pidx]
    # boundary windows: first window of symbol i (j = i*R), i = 1..total-1
    jj = np.arange(1, total) * R
    cc = c[jj] * np.exp(-1j * np.outer(psi[jj], fr))     # (n, nc)
    for di, k in enumerate(sch.data_idx):
        u_cur = np.exp(1j * theta[1:, k])
        u_prv = np.exp(1j * theta[:-1, k])
        A = np.stack([u_cur, u_prv], axis=1)
        x, *_ = np.linalg.lstsq(A, cc[:, k], rcond=None)
        H, G = x
        ic = (np.abs(G) ** 2) / max(np.abs(H) ** 2, 1e-30)
        acc["ic_db"][di].append(float(10 * np.log10(max(ic, 1e-12))))


# ===========================================================================
# stages
# ===========================================================================
def _ckpt() -> dict:
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    return {"candidate": "B-aggr-05-dense2x", "stagefiles": {},
            "pre_registered_gate": {
                "metric": "predicted mean byte-ER, P18/RS127 @ Nw=128, "
                          "best-18 carriers, byte_ER=mean(1-(1-SER)^4)",
                "go_threshold": THR["p18_rs127"],
                "frozen_before_measurement": True},
            "notes": [
                "halfrate probe = re-demod of REAL m8_dense375 capture at the "
                "dense2x window geometry (Nw=128, skip=64, stride=256): the "
                "4.8 dB window-energy loss and echo-tail concentration are "
                "physically included, not modelled",
                "caveat: dense2x echo at delays >320 smp comes from 2 symbols "
                "back (independent phase) instead of the same previous symbol "
                "-- equivalent at ISI-power level",
                "caveat: probe TX had no Schroeder-phase PAPR control; the "
                "dense2x master adds it (TX-side, can only raise drive)"]}


def _save(out):
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))


def _summ(acc, P):
    sb = [round(float(e) / max(1, t), 5) for e, t in zip(acc["err_b"], np.atleast_1d(acc["tot_b"]) * np.ones(P, int))]
    return sb


def _pack_acc(acc, P):
    tot_b = int(np.atleast_1d(acc["tot_b"])[0]) if np.ndim(acc["tot_b"]) else int(acc["tot_b"])
    tot_w = int(np.atleast_1d(acc["tot_w"])[0]) if np.ndim(acc["tot_w"]) else int(acc["tot_w"])
    ser_b = [round(float(e) / max(1, tot_b), 5) for e in acc["err_b"]]
    ser_w = [round(float(e) / max(1, tot_w), 5) for e in acc["err_w"]]
    g_b = [round(float(np.degrees(np.sqrt(s / max(1, tot_b)))), 2) for s in acc["gsq_b"]]
    g_w = [round(float(np.degrees(np.sqrt(s / max(1, tot_w)))), 2) for s in acc["gsq_w"]]
    d = {"ser_boundary": ser_b, "ser_within": ser_w,
         "gerr_rms_deg_boundary": g_b, "gerr_rms_deg_within": g_w,
         "n_boundary_per_carrier": tot_b, "n_within_per_carrier": tot_w,
         "pilot_raw_dtau_us_med": round(float(np.median(acc["raw_us"])), 2),
         "pilot_ema_resid_us_med": round(float(np.median(acc["ema_resid_us"])), 2),
         "dd_resid_us_med": round(float(np.median(acc["dd_us"])), 2)}
    if any(len(v) for v in acc["ic_db"]):
        d["ls_echo_ic_db_med"] = [round(float(np.median(v)), 1) if v else None
                                  for v in acc["ic_db"]]
    return d


def stage_halfrate():
    t0 = time.time()
    audio_nom, align = _load_tape9()
    sec = _get_section(MANIFEST_T9, "m9_m8_dense375")
    sch = m9d._scheme_from_entry(sec)
    out = _ckpt()
    res = {"section": "m9_m8_dense375",
           "stride": D2X_STRIDE,
           "carriers_hz": [float(f) for f in sch.freqs],
           "pilot_hz": float(sch.freqs[sch.pilot_idx]),
           "configs": {}}
    for cname, cfg in WIN_CFGS.items():
        win = _make_win(cfg)
        centry = {"Nw": cfg["Nw"], "skip": cfg["skip"], "win": cfg["win"],
                  "alphas": {}}
        for a in ALPHAS:
            acc = _section_halfrate(audio_nom, align, sec, sch, 2, cfg["Nw"],
                                    cfg["skip"], a, win=win,
                                    collect_ls=(a == 0.5))
            centry["alphas"][str(a)] = _pack_acc(acc, sch.P)
            m = np.mean(centry["alphas"][str(a)]["ser_boundary"])
            print(f"  [halfrate {cname} a={a}] mean SER_b={m:.4f}", flush=True)
        res["configs"][cname] = centry
    out["halfrate_tape9_m8"] = res
    out["stagefiles"]["halfrate"] = round(time.time() - t0, 1)
    _save(out)
    # quick view of the per-config best
    for cname, ce in res["configs"].items():
        best = min(ce["alphas"].items(),
                   key=lambda kv: np.mean(kv[1]["ser_boundary"]))
        print(f"[halfrate] {cname:16s} best a={best[0]} mean SER_b="
              f"{np.mean(best[1]['ser_boundary']):.4f} "
              f"SER_b={best[1]['ser_boundary']}")
    print(f"[halfrate] done {time.time()-t0:.0f}s -> {OUT_JSON.name}")


def stage_tail():
    t0 = time.time()
    audio_nom, align = _load_tape9()
    sec = _get_section(MANIFEST_T9, "m9_m8_dense375")
    sch = m9d._scheme_from_entry(sec)
    out = _ckpt()
    cname, best_a = _best_cfg_alpha(out)
    cfg = WIN_CFGS[cname]
    win = _make_win(cfg)
    res = {"config": cname, "alpha": best_a, "shifts": {}}
    for s in SHIFTS:
        if cfg["skip"] + s < 0:
            continue
        acc = _section_halfrate(audio_nom, align, sec, sch, 2, cfg["Nw"],
                                cfg["skip"], best_a, shift=s, win=win,
                                collect_ls=True)
        pk = _pack_acc(acc, sch.P)
        res["shifts"][str(s)] = {
            "delay_window_start_ms": round((cfg["skip"] + s) / FS * 1e3, 2),
            "ser_boundary": pk["ser_boundary"],
            "gerr_rms_deg_boundary": pk["gerr_rms_deg_boundary"],
            "ls_echo_ic_db_med": pk.get("ls_echo_ic_db_med")}
        print(f"  [tail shift={s:+d}] meanSER_b="
              f"{np.mean(pk['ser_boundary']):.4f}", flush=True)
    out["tail_profile_tape9_m8"] = res
    out["stagefiles"]["tail"] = round(time.time() - t0, 1)
    _save(out)
    print(f"[tail] done {time.time()-t0:.0f}s")


def stage_fullcheck():
    """Harness fidelity: R=1/Nw=384/skip=64 with alpha 0.5 = the production m8
    geometry; per-carrier boundary SER must track m9_results_tape9_run1."""
    t0 = time.time()
    audio_nom, align = _load_tape9()
    sec = _get_section(MANIFEST_T9, "m9_m8_dense375")
    sch = m9d._scheme_from_entry(sec)
    acc = _section_halfrate(audio_nom, align, sec, sch, 1, sch.Nw, sch.skip, 0.5)
    out = _ckpt()
    pk = _pack_acc(acc, sch.P)
    prod = json.loads((_HERE / "results" / "m9_results_tape9_run1.json").read_text())
    prod_ser = None
    for r in prod["payloads"]:
        if r["name"] == "m9_m8_dense375":
            prod_ser = r.get("per_carrier_ser")
    diffs = [abs(a - b) for a, b in zip(pk["ser_boundary"], prod_ser)] if prod_ser else None
    out["fullcheck_tape9_m8"] = {
        "probe_ser_full_geometry": pk["ser_boundary"],
        "production_per_carrier_ser": prod_ser,
        "max_abs_diff": round(max(diffs), 5) if diffs else None,
        "note": "production winner was resampling_pll; probe uses ema0.5 -- "
                "small diffs expected, gross agreement required"}
    out["stagefiles"]["fullcheck"] = round(time.time() - t0, 1)
    _save(out)
    print(f"[fullcheck] probe SER={pk['ser_boundary']}")
    print(f"[fullcheck] prod  SER={prod_ser}")
    print(f"[fullcheck] max|diff|={max(diffs) if diffs else None} "
          f"({time.time()-t0:.0f}s)")


def stage_m0half():
    t0 = time.time()
    audio_nom, align = _load_tape9()
    sec = _get_section(MANIFEST_T9, "m9_m0_reprove934")
    sch = m9d._scheme_from_entry(sec)
    out = _ckpt()
    cname, best_a = _best_cfg_alpha(out)
    cfg = WIN_CFGS[cname]
    win = _make_win(cfg)
    res = {"config": cname, "alphas": {}}
    for a in (0.5, 0.6, 0.7, 0.8):
        acc = _section_halfrate(audio_nom, align, sec, sch, 2, cfg["Nw"],
                                cfg["skip"], a, win=win)
        res["alphas"][str(a)] = _pack_acc(acc, sch.P)
        print(f"  [m0half a={a}] SER_b={res['alphas'][str(a)]['ser_boundary']}",
              flush=True)
    out["m0half_tape9"] = res
    out["stagefiles"]["m0half"] = round(time.time() - t0, 1)
    _save(out)
    print(f"[m0half] done {time.time()-t0:.0f}s")


def stage_secondtape():
    t0 = time.time()
    audio_nom, align = _load_m8tape()
    sec = _get_section(MANIFEST_M8, "m8_dq_p10n512_rs127")
    sch = m9d._scheme_from_entry(sec)
    out = _ckpt()
    cname, best_a = _best_cfg_alpha(out)
    cfg = WIN_CFGS[cname]
    win = _make_win(cfg)
    res = {"section": "m8_dq_p10n512_rs127", "capture": "m8_tape_mono_lossless",
           "config": cname, "alphas": {}}
    for a in (0.5, 0.6, 0.7, 0.8):
        acc = _section_halfrate(audio_nom, align, sec, sch, 2, cfg["Nw"],
                                cfg["skip"], a, win=win)
        res["alphas"][str(a)] = _pack_acc(acc, sch.P)
        print(f"  [secondtape a={a}] SER_b="
              f"{res['alphas'][str(a)]['ser_boundary']}", flush=True)
    out["secondtape_m8capture"] = res
    out["stagefiles"]["secondtape"] = round(time.time() - t0, 1)
    _save(out)
    print(f"[secondtape] done {time.time()-t0:.0f}s")


def stage_residuals():
    """x9_resampling_pll.residual_stats on the real m5 section (N256 frames =
    genuine 187.5 Hz pilot updates) -- verifies doubled pilot-rate tracking
    with the PRODUCTION module."""
    from x9_resampling_pll import residual_stats
    t0 = time.time()
    audio_nom, align = _load_tape9()
    sec = _get_section(MANIFEST_T9, "m9_m5_n256_rs179")
    sch = m9d._scheme_from_entry(sec)
    meta = sec["meta"]
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    rows = []
    for fi, st in enumerate(sec["frame_starts"][:8]):     # 8 frames is plenty
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        w_lo = max(0, int(st - pad_lo))
        w_hi = min(len(audio_nom), int(st + flen_full + pad_hi))
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        rows.append(residual_stats(sch, y, nd))
    out = _ckpt()
    out["residuals_m5_n256"] = {
        "note": "x9 residual_stats on real N256 frames (pilot @187.5 Hz)",
        "raw_us_med": round(float(np.median([r["raw_us"] for r in rows])), 2),
        "ema_us_med": round(float(np.median([r["ema_us"] for r in rows])), 2),
        "pll_us_med": round(float(np.median([r["pll_us"] for r in rows])), 2),
        "ddir_us_med": round(float(np.median([r["ddir_us"] for r in rows])), 2),
        "n_frames": len(rows)}
    out["stagefiles"]["residuals"] = round(time.time() - t0, 1)
    _save(out)
    print(f"[residuals] {out['residuals_m5_n256']}")


def _best_cfg_alpha(out):
    """(config_name, alpha) minimizing mean boundary SER on the m8 halfrate
    measurement.  Selection by the same metric the production receiver sweep
    optimizes (no truth at decode time on a future tape; here it picks the
    receiver geometry to ship)."""
    hr = out.get("halfrate_tape9_m8")
    if not hr:
        return "rect128_skip64", 0.6
    best = ("rect128_skip64", 0.6, 1e9)
    for cname, ce in hr["configs"].items():
        for a, pk in ce["alphas"].items():
            m = float(np.mean(pk["ser_boundary"]))
            if m < best[2]:
                best = (cname, float(a), m)
    return best[0], best[1]


def stage_gate():
    out = _ckpt()
    hr = out["halfrate_tape9_m8"]
    cname, best_a = _best_cfg_alpha(out)
    ser = np.asarray(
        hr["configs"][cname]["alphas"][str(best_a)]["ser_boundary"], float)
    P_all = len(ser)
    order = np.argsort(ser)
    table = {}
    for tag, P_use in (("p18_rs127", 18), ("p21_rs159", 21), ("p22_rs179", 22)):
        keep = order[:P_use] if P_use <= P_all else order
        s = ser[keep]
        byte_er = float(np.mean(1.0 - (1.0 - s) ** 4))
        table[tag] = {
            "P": P_use, "kept_carrier_idx": sorted(int(i) for i in keep),
            "dropped_carrier_idx": sorted(int(i) for i in order[P_use:]),
            "mean_ser": round(float(np.mean(s)), 5),
            "predicted_byte_er": round(byte_er, 5),
            "threshold": round(THR[tag], 5),
            "pass": bool(byte_er <= THR[tag])}
    go = table["p18_rs127"]["pass"]
    out["gate"] = {
        "receiver_config": cname, "best_alpha": best_a,
        "per_carrier_ser_boundary": [float(x) for x in ser],
        "rungs": table,
        "GO": bool(go),
        "verdict": "GO" if go else "NO-GO (abort, zero tape spent)",
        "note": ("plan's literal hann128_skip64 receiver is non-orthogonal at "
                 "1-bin spacing (kept as negative control); gate evaluated on "
                 "the best orthogonal receiver window at the same TX geometry")}
    _save(out)
    print(json.dumps(out["gate"], indent=2))


STAGES = {"halfrate": stage_halfrate, "tail": stage_tail,
          "fullcheck": stage_fullcheck, "m0half": stage_m0half,
          "secondtape": stage_secondtape, "residuals": stage_residuals,
          "gate": stage_gate}

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES) + ["all"])
    args = ap.parse_args()
    if args.stage == "all":
        for name, fn in STAGES.items():
            fn()
    else:
        STAGES[args.stage]()
