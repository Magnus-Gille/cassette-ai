"""x10_forensics_errors.py -- BET B forensics: what kills the 2632-2896 bps band?

Re-decodes the m5/m6/m7 (+ m0 control, m4/m4b twins) sections of the tape9_run1
capture with diagnostic instrumentation. NO proposals -- measurement only.

Per failed RS codeword: byte-error positions, frame/carrier/symbol mapping,
burst-vs-random stats. Per symbol: front-end timing residual (dtau), decision-
directed LS timing residual, pilot SNR vs off-band noise probes, above-band IMD
probes, per-carrier soft phase residuals (genie view vs the manifest sidecar --
scoring only, never fed back into any decision).

Imports m9_decode / x9_resampling_pll / h4_dqpsk internals -- does NOT modify
them. The demod DECISIONS come from the unmodified production front-ends
(ResamplingPLLDemod.demod); the instrumented DFT pass replicates the exact same
loops with extra probe frequencies appended and is VERIFIED against the
production quadrant decisions per frame (q_mismatch must be 0).

Usage (each run < 8 min, checkpoints results/x10_forensics_errors.json):
    python3 x10_forensics_errors.py prepare
    python3 x10_forensics_errors.py section m9_m5_n256_rs179 --winner ema0.6 \
        --repro resampling_pll,ema0.5
    python3 x10_forensics_errors.py summarize

Deterministic (no RNG). Seeds: N/A.
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

import analyze_master2 as am2                       # noqa: E402
import m3_codec as codec                            # noqa: E402
from m3_codec import Rung                           # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S         # noqa: E402
import m9_decode as m9d                             # noqa: E402
from x9_resampling_pll import (ResamplingPLLDemod,  # noqa: E402
                               _pi_loop_gains)
import hyp_common as hc                             # noqa: E402

SR = codec.FS
CAPTURE = _HERE / "captures" / "tape9_run1.wav"
CACHE_NPY = _HERE / "captures" / "x10_audio_nom_tape9_run1.npy"
SYNC_JSON = _HERE / "results" / "x10_forensics_sync.json"
OUT_JSON = _HERE / "results" / "x10_forensics_errors.json"
MANIFEST = json.loads((_HERE / "master9_manifest.json").read_text())

# off-band probes (Hz). All integer multiples of FS/Nw for both N256 (Nw=192,
# 250 Hz grid) and N512 (Nw=384, 125 Hz grid); >= 2 analysis bins from every
# carrier, so Hann-orthogonal to the data tones. NOISE probes sit OFF the
# 750 Hz IMD grid; IMD probes sit ON it (n*750) to catch hysteresis products.
PROBE_NOISE_HZ = (10000.0, 10750.0, 11500.0)
PROBE_IMD_HZ = (9750.0, 10500.0, 11250.0)
N_PROBE = len(PROBE_NOISE_HZ) + len(PROBE_IMD_HZ)


# ===========================================================================
# prepare: one global sync + cached nominal-clock audio
# ===========================================================================
def prepare():
    t0 = time.time()
    audio, sr = sf.read(str(CAPTURE), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert sr == SR, f"capture sr {sr} != {SR}"
    sync = am2.global_sync_and_resample(audio, MANIFEST)
    audio_nom = sync["audio_nominal"]
    np.save(CACHE_NPY, audio_nom.astype(np.float32))
    meta = {k: (float(v) if isinstance(v, (np.floating,)) else int(v))
            for k, v in sync.items() if k != "audio_nominal"}
    meta["align"] = int(sync["chirp0_nominal"]) - int(MANIFEST["tx_chirp0"])
    meta["n_samples_nominal"] = int(len(audio_nom))
    SYNC_JSON.parent.mkdir(exist_ok=True)
    SYNC_JSON.write_text(json.dumps(meta, indent=2, default=float))
    print(f"[prepare] cached {CACHE_NPY.name} ({len(audio_nom)} samples), "
          f"clock {sync['speed']:.6f}, align {meta['align']:+d}, "
          f"{time.time()-t0:.0f}s")


def _load_nominal():
    audio_nom = np.load(CACHE_NPY, mmap_mode="r")
    sync = json.loads(SYNC_JSON.read_text())
    return audio_nom, sync


# ===========================================================================
# instrumented DFT passes -- exact replicas of x9_resampling_pll loops with
# probe frequencies appended (probes never touch the pilot tracking).
# ===========================================================================
def _ema_dft_ext(sch, y, ds, total, ema_alpha, freqs_ext):
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    fpil = sch.freqs[sch.pilot_idx]
    pidx = sch.pilot_idx
    c = np.zeros((total, len(freqs_ext)), np.complex128)
    dtau = np.zeros(total)
    drift = 0.0
    sm = 0.0
    for i in range(total):
        base = ds + i * N + int(round(drift))
        lo = base + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs_ext, tt))
        c[i] = E @ (seg * win)
        if i > 0:
            dp = float(np.angle(c[i, pidx] * np.conj(c[i - 1, pidx])))
            sm = (1 - ema_alpha) * (dp / (2 * np.pi * fpil)) + ema_alpha * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
    return c, dtau


def _plain_dft_ext(sch, y, ds, total, freqs_ext):
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    c = np.zeros((total, len(freqs_ext)), np.complex128)
    for i in range(total):
        lo = ds + i * N + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs_ext, tt))
        c[i] = E @ (seg * win)
    return c


def _pll_dft_ext(pll, y, ds, total, freqs_ext):
    """Replicates ResamplingPLLDemod._demod_pll Pass1+warp+Pass2 with probes."""
    sch = pll.sch
    N = sch.N
    c1, dtau_ema = _ema_dft_ext(sch, y, ds, total, pll.ema_alpha, freqs_ext)
    kp, ki = _pi_loop_gains(pll.pll_bw_hz, pll.t_sym, pll.zeta)
    tau = v = 0.0
    tau_sym = np.zeros(total)
    for i in range(1, total):
        err = dtau_ema[i] - v
        v += ki * err
        tau += v + kp * err
        tau_sym[i] = tau
    sym_centers = ds + (np.arange(total) + 0.5) * N
    body_lo = ds
    body_hi = min(len(y), ds + total * N + N)
    tgrid = np.arange(body_lo, body_hi, dtype=np.float64)
    tau_t = np.interp(tgrid, sym_centers, tau_sym, left=tau_sym[0], right=tau_sym[-1])
    src = np.clip(tgrid - tau_t * FS, 0.0, len(y) - 1.0)
    y2 = y.copy()
    y2[body_lo:body_hi] = np.interp(src, np.arange(len(y)), y)
    c2 = _plain_dft_ext(sch, y2, ds, total, freqs_ext)
    fpil = sch.freqs[sch.pilot_idx]
    dtau_res = np.zeros(total)
    for i in range(1, total):
        dp = float(np.angle(c2[i, sch.pilot_idx] * np.conj(c2[i - 1, sch.pilot_idx])))
        dtau_res[i] = dp / (2 * np.pi * fpil)
    return c2, dtau_res, tau_sym, c1, dtau_ema


def _decide_refine(sch, c_carriers, dtau_total, refine=True):
    """Replica of x9 _decide that also returns soft outputs."""
    fd = sch.freqs[sch.data_idx]
    d = c_carriers[1:, :] * np.conj(c_carriers[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau_total[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    nd = dphi.shape[0]
    dtau_dd = np.zeros(nd)
    if refine:
        res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_dd = num / (2 * np.pi * den)
        dphi = dphi - 2 * np.pi * dtau_dd[:, None] * fd[None, :]
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    res_final = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    return q, dphi, res_final, dtau_dd


# ===========================================================================
# stream/byte mapping helpers
# ===========================================================================
def _rebuild_stream_bytes(frames_bits, meta):
    """Identical reassembly to m9_decode._rs_merge_guarded."""
    fb = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]
    pieces = []
    for fi in range(n_frames):
        nominal = fb if fi < n_frames - 1 else (stream_bits - fb * (n_frames - 1))
        rb = (np.asarray(frames_bits[fi], np.uint8).ravel()
              if fi < len(frames_bits) else np.zeros(nominal, np.uint8))
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    bits = np.concatenate(pieces)[:stream_bits]
    return np.packbits(bits)[: (meta["n_codewords"] * meta["rs_n"])], bits


def _bit_to_carrier_sym(b, nd):
    blk = 2 * nd
    return int(b // blk), int((b % blk) // 2)


def _frame_nom_bits(meta):
    return m9d._nominal_frame_bits(meta)


# ===========================================================================
# per-section forensics
# ===========================================================================
def _get_section(name):
    for sec in MANIFEST["ws_payloads"]:
        if sec["name"] == name:
            return sec
    raise KeyError(name)


def _make_frontend(sch, fe_name):
    if fe_name == "resampling_pll":
        return ResamplingPLLDemod(sch, pll_bw_hz=30.0, front_end="pll")
    if fe_name.startswith("ema"):
        return ResamplingPLLDemod(sch, front_end="ema", ema_alpha=float(fe_name[3:]))
    raise ValueError(fe_name)


def _demod_all_frames(audio_nom, sec, align, sch, dem):
    meta = sec["meta"]
    nom_bits = _frame_nom_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    out = []
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        w_lo = max(0, int(st - pad_lo))
        w_hi = min(len(audio_nom), int(st + flen_full + pad_hi))
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        bits, diag = dem.demod(win, nd)
        out.append({"bits": np.asarray(bits, np.uint8), "diag": diag, "win": win,
                    "nd": nd, "nom_bits": nom_bits[fi], "w_lo": w_lo, "st": st})
    return out


def _rs_level(frames, sec, sch, expected_packed):
    """Authoritative RS merge + structural per-codeword byte-error counts."""
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    rx_frames = [f["bits"] for f in frames]
    out, cwf, misc, _ = m9d._rs_merge_guarded(rx_frames, meta, crc_table,
                                              erase_frac=0.0, rel_cw=None)
    byte_err = sum(a != b for a, b in zip(out, expected_packed)) + abs(
        len(out) - len(expected_packed))
    exact = out == expected_packed

    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _m2 = codec.encode_payload(expected_packed, rung)
    tx_bytes, tx_bits = _rebuild_stream_bytes(tx_frames, meta)
    rx_bytes, rx_bits = _rebuild_stream_bytes(rx_frames, meta)
    n_cw, rs_n = meta["n_codewords"], meta["rs_n"]
    tx_mat = tx_bytes.reshape(rs_n, n_cw).T
    rx_mat = rx_bytes.reshape(rs_n, n_cw).T
    err_mat = tx_mat != rx_mat                      # (n_cw, rs_n)
    return {"rs_out_exact": exact, "cw_failed_rs": int(cwf), "miscorrected": int(misc),
            "byte_errors_payload": int(byte_err), "tx_frames": tx_frames,
            "tx_bits": tx_bits, "rx_bits": rx_bits, "err_mat": err_mat,
            "tx_mat": tx_mat, "rx_mat": rx_mat}


def _mask_carriers_refail(frames, sec, sch, rs, mask_set):
    """Counterfactual: replace rx bits on carriers in mask_set with tx bits,
    recount per-cw byte errors and structural failures."""
    meta = sec["meta"]
    nom_bits = _frame_nom_bits(meta)
    t = (meta["rs_n"] - meta["rs_k"]) // 2
    fb = meta["frame_bits"]
    masked_frames = []
    pos = 0
    for fi, f in enumerate(frames):
        nb = nom_bits[fi]
        nd = f["nd"]
        blk = 2 * nd
        rxb = np.asarray(f["bits"], np.uint8).ravel()[:nb].copy()
        if len(rxb) < nb:
            rxb = np.concatenate([rxb, np.zeros(nb - len(rxb), np.uint8)])
        txb = rs["tx_bits"][pos:pos + nb]
        bidx = np.arange(nb)
        car = bidx // blk
        m = np.isin(car, list(mask_set))
        rxb[m] = txb[m]
        masked_frames.append(rxb)
        pos += nb
    rx_bytes, _ = _rebuild_stream_bytes(masked_frames, meta)
    n_cw, rs_n = meta["n_codewords"], meta["rs_n"]
    rx_mat = rx_bytes.reshape(rs_n, n_cw).T
    errs = (rx_mat != rs["tx_mat"]).sum(axis=1)
    return {"cw_err_counts": [int(e) for e in errs],
            "cw_failed_structural": int((errs > t).sum()),
            "total_byte_errors_stream": int(errs.sum())}


def analyze_section(name, winner_fe, repro_fes):
    t0 = time.time()
    audio_nom, sync = _load_nominal()
    align = int(sync["align"])
    sec = _get_section(name)
    meta = sec["meta"]
    sch = m9d._scheme_from_entry(sec)
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rs_n, rs_k, n_cw = meta["rs_n"], meta["rs_k"], meta["n_codewords"]
    t_cap = (rs_n - rs_k) // 2
    P = sch.P
    freqs_ext = np.concatenate([sch.freqs, PROBE_NOISE_HZ, PROBE_IMD_HZ])
    ncar = len(sch.freqs)
    noise_cols = np.arange(ncar, ncar + 3)
    imd_cols = np.arange(ncar + 3, ncar + 6)
    # probe sanity: integer analysis-grid bins, >=2 bins from every carrier
    grid = FS / sch.Nw
    for pf in PROBE_NOISE_HZ + PROBE_IMD_HZ:
        assert abs(pf / grid - round(pf / grid)) < 1e-9
        assert min(abs(pf - f) for f in sch.freqs) >= 2 * grid - 1e-9

    result = {"section": name, "phy": sec["phy"], "rs": [rs_n, rs_k], "t_rs": t_cap,
              "n_codewords": n_cw, "n_frames": meta["n_frames"],
              "projected_net_bps": sec.get("projected_net_bps"),
              "carrier_freqs_hz": [float(f) for f in sch.freqs],
              "pilot_idx": int(sch.pilot_idx),
              "data_carrier_freqs_hz": [float(f) for f in sch.freqs[sch.data_idx]],
              "winner_front_end": winner_fe, "front_ends": {}}

    # ---------- reproduction-only front-ends (cheap: decisions + RS counts) --
    for fe_name in repro_fes:
        dem = _make_frontend(sch, fe_name)
        frames = _demod_all_frames(audio_nom, sec, align, sch, dem)
        rs = _rs_level(frames, sec, sch, expected_packed)
        ser = m9d._per_carrier_ser([f["bits"] for f in frames], sec, sch, expected_packed)
        errs = rs["err_mat"].sum(axis=1)
        result["front_ends"][fe_name] = {
            "cw_failed_rs": rs["cw_failed_rs"],
            "cw_failed_structural": int((errs > t_cap).sum()),
            "byte_errors_payload": rs["byte_errors_payload"],
            "per_carrier_ser": ser,
            "cw_err_counts": [int(e) for e in errs],
            "frame_dtau_rms_us": [round(float(np.sqrt(np.mean(
                np.square(f["diag"]["dtau"])))) * 1e6, 2) for f in frames],
            "pll_frame_selector": [f["diag"].get("front_end") for f in frames],
        }
        del frames
        print(f"  [{name}] repro {fe_name}: cw_failed={rs['cw_failed_rs']} "
              f"byte_err={rs['byte_errors_payload']} ({time.time()-t0:.0f}s)")

    # ---------- winner front-end: full instrumentation -----------------------
    dem = _make_frontend(sch, winner_fe)
    frames = _demod_all_frames(audio_nom, sec, align, sch, dem)
    rs = _rs_level(frames, sec, sch, expected_packed)
    errs_per_cw = rs["err_mat"].sum(axis=1)

    # genie quadrant maps + instrumented soft metrics, per frame
    nom_bits = _frame_nom_bits(meta)
    pos = 0
    frame_rows = []
    # section accumulators (per data carrier)
    Pd = len(sch.data_idx)
    car_err = np.zeros(Pd, int)
    car_tot = np.zeros(Pd, int)
    car_sig_pow = np.zeros(Pd)
    car_res_sq_ok = np.zeros(Pd)      # final residual^2 on correct cells
    car_res_n_ok = np.zeros(Pd, int)
    car_gerr_sq = np.zeros(Pd)        # genie phase-err^2 all cells
    car_gerr_n = np.zeros(Pd, int)
    qoff_counts = np.zeros((Pd, 3), int)   # (q-tq)%4 in {1,2,3}
    noise_pow_all = []
    imd_pow_all = []
    pilot_pow_all = []
    q_mismatch_total = 0
    # deep-dive carrier traces: keep per-symbol error/softs for chosen carriers
    deep_traces = {}                   # dc_idx -> list per frame of dict arrays
    err_maps = []                      # per frame (nd, Pd) bool

    for fi, f in enumerate(frames):
        nd, nb = f["nd"], f["nom_bits"]
        total = nd + 1
        diag = f["diag"]
        ds = int(diag["preamble_at"])
        y = f["win"]
        used = diag.get("front_end", "ema")
        if winner_fe == "resampling_pll" and used == "pll":
            c_ext, dtau_res, tau_sym, _c1, _de = _pll_dft_ext(dem, y, ds, total, freqs_ext)
            dtau_total = dtau_res
        else:
            alpha = dem.ema_alpha
            c_ext, dtau_total = _ema_dft_ext(sch, y, ds, total, alpha, freqs_ext)
        q, dphi, res_final, dtau_dd = _decide_refine(sch, c_ext[:, :ncar], dtau_total)
        qm = int((q != diag["quadrants"]).sum())
        q_mismatch_total += qm

        # genie
        txb = rs["tx_bits"][pos:pos + nb]
        tq = sch.bits_to_quadrants(txb)             # (nd, P), zero-padded
        blk = 2 * nd
        valid = np.zeros((nd, Pd), bool)
        for dci in range(Pd):
            # data carrier dci occupies bit block dci_carrier_index in 0..P-1?
            # bits_to_quadrants blocks are over ALL P data positions (P = sch.P,
            # carriers excl pilot), block index == data position index.
            nbits_block = max(0, min(blk, nb - dci * blk))
            valid[: nbits_block // 2, dci] = True
        errm = (q[:nd] != tq[:nd]) & valid
        err_maps.append(errm)
        car_err += errm.sum(axis=0)
        car_tot += valid.sum(axis=0)
        # genie phase error (distance from transmitted quadrant center)
        gerr = (dphi[:nd] - tq[:nd] * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        car_gerr_sq += np.where(valid, gerr ** 2, 0.0).sum(axis=0)
        car_gerr_n += valid.sum(axis=0)
        car_res_sq_ok += np.where(valid & ~errm, res_final[:nd] ** 2, 0.0).sum(axis=0)
        car_res_n_ok += (valid & ~errm).sum(axis=0)
        off = (q[:nd] - tq[:nd]) % 4
        for k in (1, 2, 3):
            qoff_counts[:, k - 1] += ((off == k) & valid).sum(axis=0)

        # signal/noise powers (rows 1..total-1 = decision-bearing symbols)
        cs = c_ext[1:, :]
        sig = np.abs(cs[:, sch.data_idx]) ** 2       # (nd, Pd)
        car_sig_pow += np.where(valid, sig[:nd], 0.0).sum(axis=0)
        npow = np.mean(np.abs(cs[:, noise_cols]) ** 2, axis=1)
        ipow = np.mean(np.abs(cs[:, imd_cols]) ** 2, axis=1)
        ppow = np.abs(cs[:, sch.pilot_idx]) ** 2
        noise_pow_all.append(npow)
        imd_pow_all.append(ipow)
        pilot_pow_all.append(ppow)

        frame_rows.append({
            "frame": fi,
            "tape_pos_s": round((int(sec["frame_starts"][fi]) + align) / SR, 2),
            "front_end_used": used,
            "q_mismatch": qm,
            "dtau_fe_rms_us": round(float(np.sqrt(np.mean(np.square(
                dtau_total[1:])))) * 1e6, 2),
            "dtau_dd_rms_us": round(float(np.sqrt(np.mean(dtau_dd ** 2))) * 1e6, 2),
            "pilot_snr_db_med": round(float(10 * np.log10(
                np.median(ppow) / max(np.median(npow), 1e-30))), 2),
            "imd_over_noise_db": round(float(10 * np.log10(
                np.mean(ipow) / max(np.mean(npow), 1e-30))), 2),
            "per_carrier_errs": [int(e) for e in errm.sum(axis=0)],
            "n_sym": int(nd),
        })
        # store per-symbol traces for deep dive later
        deep_traces[fi] = {"errm": errm, "sig": sig[:nd], "npow": npow[:nd],
                           "ppow": ppow[:nd], "dtau_dd": dtau_dd[:nd],
                           "dtau_fe": dtau_total[1:nd + 1], "gerr": gerr,
                           "valid": valid}
        pos += nb

    ser = [float(e) / max(1, t) for e, t in zip(car_err, car_tot)]
    noise_all = np.concatenate(noise_pow_all)
    mean_noise = float(np.mean(noise_all))
    per_carrier = {
        "freqs_hz": [float(f) for f in sch.freqs[sch.data_idx]],
        "ser": [round(s, 5) for s in ser],
        "ser_m9_reference": None,  # filled by summarize
        "snr_db_vs_offband_noise": [round(float(10 * np.log10(
            (sp / max(1, tcnt)) / mean_noise)), 2)
            for sp, tcnt in zip(car_sig_pow, car_tot)],
        "genie_phase_err_rms_deg": [round(float(np.degrees(np.sqrt(
            sq / max(1, n)))), 2) for sq, n in zip(car_gerr_sq, car_gerr_n)],
        "resid_rms_deg_correct_cells": [round(float(np.degrees(np.sqrt(
            sq / max(1, n)))), 2) for sq, n in zip(car_res_sq_ok, car_res_n_ok)],
        "err_qoffset_counts_1_2_3": [[int(x) for x in row] for row in qoff_counts],
    }

    # ---------- deep dive on bad carriers ------------------------------------
    bad_dcis = sorted({0} | {i for i, s in enumerate(ser) if s > 0.10}
                      | {int(np.argmax([s if i != 0 else -1
                                        for i, s in enumerate(ser)]))})
    deep = {}
    for dci in bad_dcis:
        e_all, ok_all = [], []
        sig_err, sig_ok, dd_err, dd_ok, psnr_err, psnr_ok = [], [], [], [], [], []
        run_hist = {}
        adj_num = adj_den = 0
        per_frame_ser = []
        gerr_hist = np.zeros(18, int)
        for fi, tr in deep_traces.items():
            v = tr["valid"][:, dci]
            e = tr["errm"][:, dci][v]
            per_frame_ser.append(round(float(e.mean()) if len(e) else 0.0, 4))
            sig = tr["sig"][:, dci][v]
            dd = np.abs(tr["dtau_dd"][v[:len(tr["dtau_dd"])]]) if len(tr["dtau_dd"]) else np.array([])
            psnr = 10 * np.log10(tr["ppow"][v[:len(tr["ppow"])]] /
                                 np.maximum(tr["npow"][v[:len(tr["npow"])]], 1e-30))
            sig_err.extend(sig[e]); sig_ok.extend(sig[~e])
            if len(dd) == len(e):
                dd_err.extend(dd[e]); dd_ok.extend(dd[~e])
            if len(psnr) == len(e):
                psnr_err.extend(psnr[e]); psnr_ok.extend(psnr[~e])
            ge = tr["gerr"][:, dci][v]
            gerr_hist += np.histogram(np.degrees(ge), bins=18, range=(-180, 180))[0]
            # runs within the frame
            run = 0
            for x in e:
                if x:
                    run += 1
                elif run:
                    run_hist[run] = run_hist.get(run, 0) + 1
                    run = 0
            if run:
                run_hist[run] = run_hist.get(run, 0) + 1
            adj_num += int((e[1:] & e[:-1]).sum())
            adj_den += int(e[:-1].sum())
            e_all.append(e)
        e_cat = np.concatenate(e_all)
        p_err = float(e_cat.mean())
        deep[f"dc{dci}_{int(sch.freqs[sch.data_idx][dci])}Hz"] = {
            "ser": round(p_err, 5),
            "n_err": int(e_cat.sum()), "n_sym": int(len(e_cat)),
            "p_err_given_prev_err": round(adj_num / adj_den, 4) if adj_den else None,
            "clustering_ratio_vs_random": round((adj_num / adj_den) / p_err, 3)
            if adj_den and p_err > 0 else None,
            "run_length_hist": {str(k): v for k, v in sorted(run_hist.items())},
            "mag_db_err_minus_ok": round(float(10 * np.log10(
                np.median(sig_err) / np.median(sig_ok))), 2)
            if sig_err and sig_ok else None,
            "dtau_dd_med_us_err": round(float(np.median(dd_err)) * 1e6, 2) if dd_err else None,
            "dtau_dd_med_us_ok": round(float(np.median(dd_ok)) * 1e6, 2) if dd_ok else None,
            "pilot_snr_db_med_err": round(float(np.median(psnr_err)), 2) if psnr_err else None,
            "pilot_snr_db_med_ok": round(float(np.median(psnr_ok)), 2) if psnr_ok else None,
            "per_frame_ser": per_frame_ser,
            "genie_phase_err_hist_deg_18bins": [int(x) for x in gerr_hist],
        }

    # ---------- failed-codeword forensics ------------------------------------
    failed = [int(i) for i in np.where(errs_per_cw > t_cap)[0]]
    nd_frames = [f["nd"] for f in frames]
    fcw = []
    for i in failed:
        jbad = [int(j) for j in np.where(rs["err_mat"][i])[0]]
        bad = []
        car_attr = {}
        frames_touched = {}
        for j in jbad:
            sb = j * n_cw + i
            fi = sb // meta["frame_bytes"]
            bif = sb % meta["frame_bytes"]
            nd = nd_frames[min(fi, len(nd_frames) - 1)]
            # which bits in this byte actually differ
            cars, syms = set(), []
            for bo in range(8):
                gb = sb * 8 + bo
                fb_off = gb - fi * meta["frame_bits"]
                if rs["tx_bits"][gb] != rs["rx_bits"][gb]:
                    car, sym = _bit_to_carrier_sym(fb_off, nd)
                    cars.add(car)
                    syms.append(sym)
            for car in cars:
                car_attr[car] = car_attr.get(car, 0) + 1
            frames_touched[fi] = frames_touched.get(fi, 0) + 1
            bad.append([j, fi, sorted(cars), [min(syms), max(syms)] if syms else []])
        jarr = np.array(jbad)
        adj = int((np.diff(jarr) == 1).sum()) if len(jarr) > 1 else 0
        fcw.append({
            "cw": i, "n_byte_err": int(errs_per_cw[i]), "t": t_cap,
            "overflow": int(errs_per_cw[i] - t_cap),
            "byte_positions": jbad,
            "adjacent_pos_pairs": adj,
            "expected_adjacent_if_random": round(
                float(len(jarr) * (len(jarr) - 1)) / rs_n, 2),
            "n_frames_touched": len(frames_touched),
            "max_bytes_one_frame": max(frames_touched.values()),
            "carrier_attribution": {str(k): v for k, v in sorted(car_attr.items())},
            "bad_bytes_j_frame_carriers_symrange": bad,
        })

    # ---------- counterfactual carrier masking + RS-margin sweep -------------
    ser_arr = np.array(ser)
    worst_other = int(np.argmax(np.where(np.arange(Pd) == 0, -1, ser_arr)))
    masks = {
        "mask_dc0": {0},
        f"mask_dc{worst_other}": {worst_other},
        f"mask_dc0_dc{worst_other}": {0, worst_other},
        "mask_dc0_and_all_ser_gt_2pct": {0} | {i for i, s in enumerate(ser) if s > 0.02},
    }
    # map data-carrier index (block index in bits) -- blocks are 0..P-1 over
    # data positions, matching bits_to_quadrants carrier-major blocks.
    counterf = {}
    for mname, mset in masks.items():
        counterf[mname] = _mask_carriers_refail(frames, sec, sch, rs, mset)
        counterf[mname]["masked_data_carriers"] = sorted(int(x) for x in mset)
    t_sweep = {str(t): int((errs_per_cw > t).sum()) for t in range(8, 65, 2)}

    result["front_ends"][winner_fe] = {
        "cw_failed_rs": rs["cw_failed_rs"],
        "cw_failed_structural": int((errs_per_cw > t_cap).sum()),
        "byte_errors_payload": rs["byte_errors_payload"],
        "rs_out_exact": bool(rs["rs_out_exact"]),
        "q_mismatch_total": int(q_mismatch_total),
        "per_carrier_ser": [round(s, 5) for s in ser],
    }
    result["per_carrier"] = per_carrier
    result["frames"] = frame_rows
    result["deep_dive"] = deep
    result["codewords"] = {
        "t": t_cap, "err_counts": [int(e) for e in errs_per_cw],
        "mean_err": round(float(errs_per_cw.mean()), 2),
        "std_err": round(float(errs_per_cw.std()), 2),
        "max_err": int(errs_per_cw.max()),
        "margin_to_t_min": int(t_cap - errs_per_cw.max()),
        "dispersion_var_over_mean": round(float(errs_per_cw.var() /
                                                max(errs_per_cw.mean(), 1e-9)), 2),
        "failed": failed,
        "failed_forensics": fcw,
        "cw_failed_vs_t_sweep": t_sweep,
    }
    result["counterfactuals"] = counterf
    result["elapsed_s"] = round(time.time() - t0, 1)

    # checkpoint
    out = json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else {
        "experiment": "x10_forensics_errors", "capture": str(CAPTURE),
        "date": "2026-06-11", "deterministic": True, "sections": {}}
    out["sections"][name] = result
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    print(f"  [{name}] winner {winner_fe}: cw_failed={rs['cw_failed_rs']} "
          f"q_mismatch={q_mismatch_total} elapsed {time.time()-t0:.0f}s -> checkpointed")
    return result


# ===========================================================================
# probe2: physics discriminators for the dc0/N256 failure.
#   (a) window-shift sweep: re-DFT carrier 0 with the analysis window slid
#       within the symbol. Leading-edge ISI (acoustic echo of the PREVIOUS
#       symbol) predicts gerr falls as the window moves late; a static
#       frequency-domain notch/IMD predicts shift-invariance.
#   (b) data-dependence: conditional genie phase error of dc0 by the
#       TRANSMITTED quadrant transition (current and previous). Prev-symbol
#       ISI predicts a quadrature signature: mean gerr ~ -90deg*sign pattern
#       vs q_tx in {1,3}, ~0 for {0,2}, plus mag high@0 / low@2.
#   (c) sounder H(f)/SNR dump 2.5-6.5 kHz (the 4500 Hz hole).
# ===========================================================================
def _ema_dft_shift(sch, y, ds, total, ema_alpha, freqs_ext, shift):
    """_ema_dft_ext with the analysis window slid by `shift` samples inside
    the symbol (same pilot-driven integer-drift tracking, re-run per shift)."""
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    fpil = sch.freqs[sch.pilot_idx]
    pidx = sch.pilot_idx
    c = np.zeros((total, len(freqs_ext)), np.complex128)
    dtau = np.zeros(total)
    drift = 0.0
    sm = 0.0
    for i in range(total):
        base = ds + i * N + int(round(drift))
        lo = base + skip + shift
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs_ext, tt))
        c[i] = E @ (seg * win)
        if i > 0:
            dp = float(np.angle(c[i, pidx] * np.conj(c[i - 1, pidx])))
            sm = (1 - ema_alpha) * (dp / (2 * np.pi * fpil)) + ema_alpha * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
    return c, dtau


def probe2(name, fe_alpha, shifts, deep_dcis):
    t0 = time.time()
    audio_nom, sync = _load_nominal()
    align = int(sync["align"])
    sec = _get_section(name)
    meta = sec["meta"]
    sch = m9d._scheme_from_entry(sec)
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _m2 = codec.encode_payload(expected_packed, rung)
    _txb, tx_bits = _rebuild_stream_bytes(tx_frames, meta)
    nom_bits = _frame_nom_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    freqs_ext = np.asarray(sch.freqs, float)

    shift_table = {dci: {} for dci in deep_dcis}
    cond_table = {dci: None for dci in deep_dcis}
    pos = 0
    # per-shift accumulators: dci -> shift -> [sum_sq, n, errs, mag_pows]
    acc = {dci: {s: [0.0, 0, 0, []] for s in shifts} for dci in deep_dcis}
    # conditional accumulators at shift 0: dci -> lists per current q (0..3)
    cond = {dci: {"cur": {k: [] for k in range(4)}, "prev": {k: [] for k in range(4)},
                  "mag_cur": {k: [] for k in range(4)}} for dci in deep_dcis}

    for fi, st in enumerate(sec["frame_starts"]):
        nb = nom_bits[fi]
        nd = sch.nsym_data(nb)
        total = nd + 1
        st = int(st) + align
        w_lo = max(0, int(st - pad_lo))
        w_hi = min(len(audio_nom), int(st + flen_full + pad_hi))
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
        txb = tx_bits[pos:pos + nb]
        tq = sch.bits_to_quadrants(txb)[:nd]
        blk = 2 * nd
        for s in shifts:
            c, dtau = _ema_dft_shift(sch, y, ds, total, fe_alpha, freqs_ext, s)
            q, dphi, _res, _dd = _decide_refine(sch, c, dtau)
            gerr = (dphi[:nd] - tq * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            sig = np.abs(c[1:, sch.data_idx]) ** 2
            for dci in deep_dcis:
                nv = max(0, min(blk, nb - dci * blk)) // 2
                ge = gerr[:nv, dci]
                a = acc[dci][s]
                a[0] += float((ge ** 2).sum())
                a[1] += int(nv)
                a[2] += int((q[:nv, dci] != tq[:nv, dci]).sum())
                a[3].append(np.median(sig[:nv, dci]))
                if s == 0:
                    tqx = tq[:nv, dci]
                    mag_db = 10 * np.log10(np.maximum(sig[:nv, dci], 1e-30))
                    mag_db = mag_db - np.median(mag_db)
                    for k in range(4):
                        m = tqx == k
                        cond[dci]["cur"][k].extend(np.degrees(ge[m]))
                        cond[dci]["mag_cur"][k].extend(mag_db[m])
                        mp = np.zeros_like(m)
                        mp[1:] = (tqx[:-1] == k)[: len(mp) - 1]
                        cond[dci]["prev"][k].extend(np.degrees(ge[mp]))
        pos += nb

    for dci in deep_dcis:
        for s in shifts:
            sq, n, ne, mags = acc[dci][s]
            shift_table[dci][str(s)] = {
                "gerr_rms_deg": round(float(np.degrees(np.sqrt(sq / max(1, n)))), 2),
                "ser": round(ne / max(1, n), 5),
                "mag_med_db_rel_shift0": round(float(10 * np.log10(
                    np.median(mags) / max(np.median(acc[dci][0][3]), 1e-30))), 2),
            }
        ct = {}
        for key in ("cur", "prev"):
            ct[key] = {str(k): {
                "n": len(v), "mean_deg": round(float(np.mean(v)), 2) if v else None,
                "std_deg": round(float(np.std(v)), 2) if v else None}
                for k, v in cond[dci][key].items()}
        ct["mag_by_cur_q_db"] = {str(k): round(float(np.median(v)), 2) if v else None
                                 for k, v in cond[dci]["mag_cur"].items()}
        cond_table[dci] = ct

    out = json.loads(OUT_JSON.read_text())
    secout = out["sections"].setdefault(name, {})
    secout["probe2"] = {
        "fe_alpha": fe_alpha, "shifts": list(shifts),
        "note": ("window-shift sweep + data-conditioned genie phase error on "
                 "selected data carriers; shift in samples, + = later window"),
        "carriers": {f"dc{d}_{int(sch.freqs[sch.data_idx][d])}Hz":
                     {"shift_sweep": shift_table[d], "conditional": cond_table[d]}
                     for d in deep_dcis},
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    print(f"  [{name}] probe2 done ({time.time()-t0:.0f}s)")
    for d in deep_dcis:
        f0 = shift_table[d]
        print(f"   dc{d}: " + " ".join(f"{s}:{f0[str(s)]['gerr_rms_deg']}d/"
                                       f"{f0[str(s)]['ser']:.3f}" for s in shifts))


def sounder_dump():
    audio_nom, sync = _load_nominal()
    snd = am2.analyze_sounder(np.asarray(audio_nom), MANIFEST, sync)
    out = json.loads(OUT_JSON.read_text())
    keep = {}
    for k, v in snd.items():
        if isinstance(v, (int, float, str, bool)) or v is None:
            keep[k] = v
    fr = np.asarray(snd.get("sounder_freqs", []), float)
    if len(fr):
        for arr_k in ("H_db", "snr_db_per_tone"):
            if arr_k in snd:
                a = np.asarray(snd[arr_k], float)
                keep[arr_k + "_tones"] = {str(int(f)): round(float(x), 2)
                                          for f, x in zip(fr, a)}
    out["sounder"] = keep
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    sel = {k: v for k, v in keep.get("H_db_tones", {}).items()
           if 2000 <= int(k) <= 7000}
    print("  sounder H_db 2-7kHz:", sel)


# ===========================================================================
def summarize():
    out = json.loads(OUT_JSON.read_text())
    m9 = json.loads((_HERE / "results" / "m9_results_tape9_run1.json").read_text())
    m9p = {p["name"]: p for p in m9["payloads"]}
    checks = {}
    for name, secres in out["sections"].items():
        ref = m9p.get(name, {})
        ref_best = {"front_end": ref.get("front_end_used"),
                    "cw_failed": ref.get("rs_codewords_failed"),
                    "byte_errors": ref.get("byte_errors"),
                    "per_carrier_ser": ref.get("per_carrier_ser")}
        w = secres["winner_front_end"]
        mine = secres["front_ends"].get(w, {})
        checks[name] = {
            "m9_reference": ref_best,
            "x10_winner": {"front_end": w, "cw_failed": mine.get("cw_failed_rs"),
                           "byte_errors": mine.get("byte_errors_payload")},
            "match": (mine.get("cw_failed_rs") == ref.get("rs_codewords_failed")
                      and mine.get("byte_errors_payload") == ref.get("byte_errors")),
        }
    out["reproduction_check"] = checks
    out["verdict"] = {
        "question": "WHAT kills the 2632-2896 bps band (m5/m6/m7 on tape9_run1)?",
        "answer_ranked": [
            {"rank": 1, "cause": "previous-symbol ISI (acoustic echo/reverb tail) "
             "destroying data carrier 0 (750 Hz) at N256",
             "share_of_byte_errors": "~62-65% of stream byte errors on m5/m6/m7",
             "evidence": [
                 "dc0 SNR vs off-band noise 33-36 dB yet genie phase error RMS 60-67 deg",
                 "error symbols vs correct: mag -1.5 dB, pilot SNR -0.2 dB, "
                 "dtau_dd 4.05 vs 3.97 us -- NOT fades, NOT capture noise, NOT timing",
                 "window-shift sweep: dc0 gerr falls monotonically as the analysis "
                 "window slides late: 83deg/SER0.58 @-24smp -> 33deg/SER0.13 @+32smp "
                 "(leading-edge contamination)",
                 "data-conditioned signature: mag +2.4 dB when tx dphi quadrant=0 "
                 "(echo in-phase), -5.0..-5.6 dB when quadrant=2 (echo anti-phase), "
                 "mean phase pull -31/+24 deg for q=1/q=2; echo amplitude r~0.31-0.44 "
                 "(I/C -7..-10 dB) at 750 Hz",
                 "m0 control (N512, IDENTICAL 750 Hz tone plan, same capture): "
                 "dc0 SER 0, gerr 8 deg, same shift-trend at ~7x smaller amplitude -- "
                 "N512's 1.33ms guard + 8ms window dilutes the same physical echo"]},
            {"rank": 2, "cause": "static channel notch at 4.4-4.7 kHz hitting m7's "
             "4500 Hz data carrier (21.5% SER)",
             "evidence": [
                 "sounder H_db: -21.6 dB @4407 Hz, -28.1 dB @4666 Hz vs -11.5 @4162",
                 "shift-INVARIANT (38.3 deg gerr at all window placements)",
                 "carrier SNR 20 dB vs 28-35 dB neighbors",
                 "m5/m6 parked the PILOT at 4500 (survives at 24 dB); m7 moved the "
                 "pilot to 5250 (40 dB, strongest bin) and put data on the notch"]},
            {"rank": 3, "cause": "top-band (6750-8250 Hz) timing-sensitive stragglers "
             "2-5% SER -- the only part the front-end sweep actually fixes",
             "evidence": [
                 "ema0.6 vs ema0.5/pll on m5: dc0 unchanged (0.3926 vs 0.39216), "
                 "dc6-dc9 halved (e.g. dc7 0.0593 -> 0.0446, dc9 0.0475 -> 0.0285)",
                 "their errors prefer CENTER window placement (SER blows up at "
                 "+24/+32 shift), opposite of dc0"]},
        ],
        "ruled_out": {
            "timing_transients": "dtau_dd flat 2.5-6.1 us RMS across every frame of "
            "every section; identical on error vs correct symbols",
            "rs_margin_or_interleaving": "per-cw byte-error counts are UNDER-dispersed "
            "(var/mean 0.32-0.46): interleaving is working; failure is the MEAN "
            "sitting at/above the cliff (m5 32.0 vs t=38, m6 34.7 vs t=32, "
            "m7 34.7 vs t=38), not bursts",
            "miscorrections": "0 everywhere (CRC guard)",
        },
        "counterfactual_headline": "masking ONLY data carrier 0 (genie upper bound): "
        "m5 0/44, m6 0/41, m7 0/43 failed codewords -- all three rungs "
        "(2632/2809/2896 bps) byte-exact; post-mask max cw errors 20/22/22 vs "
        "t=38/32/38 (huge margin). Masking dc7 alone on m6 still fails 7.",
        "rs_t_sweep_as_is": {"m5_needs_t": 40, "m6_needs_t": 44, "m7_needs_t": 42,
                             "note": "thinner RS alone cannot rescue m6/m7 with dc0 "
                             "in place without dropping below current record rates"},
        "twins_m4_m4b": "same scheme: m4 mean cw err 40.9 (max 51, t=48, 5 fail), "
        "m4b 33.3 (max 47, 0 fail) -- realization variance near the cliff; both "
        "pass with dc0 masked",
    }
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    for k, v in checks.items():
        print(f"  {k}: match={v['match']} x10={v['x10_winner']} "
              f"ref_cw={v['m9_reference']['cw_failed']}")


# ===========================================================================
if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sp = sub.add_parser("section")
    sp.add_argument("name")
    sp.add_argument("--winner", required=True)
    sp.add_argument("--repro", default="")
    p2 = sub.add_parser("probe2")
    p2.add_argument("name")
    p2.add_argument("--alpha", type=float, default=0.6)
    p2.add_argument("--shifts", default="-24,-16,-8,0,8,16,24,32")
    p2.add_argument("--dcis", default="0")
    sub.add_parser("sounder")
    sub.add_parser("summarize")
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare()
    elif args.cmd == "section":
        repro = [x for x in args.repro.split(",") if x]
        analyze_section(args.name, args.winner, repro)
    elif args.cmd == "probe2":
        probe2(args.name, args.alpha,
               [int(x) for x in args.shifts.split(",")],
               [int(x) for x in args.dcis.split(",")])
    elif args.cmd == "sounder":
        sounder_dump()
    elif args.cmd == "summarize":
        summarize()
