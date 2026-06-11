"""x10_c_vv_coherent.py -- BET C candidate 1 validation: RX-only coherent-
reference (Viterbi&Viterbi x4) detection on REAL capture tape9_run1.wav.

Premise (measured by x10_c_evm_probe on tape9_run1): per-carrier truth-referenced
differential phase error has lag-1 autocorrelation ~ -0.5 on every carrier of
every section => the underlying per-symbol complex noise is WHITE => differential
detection doubles the noise variance vs coherent. A decision-free smoothed phase
reference (V&V: strip QPSK with z^4, smooth, de-rotate, absolute-decide, then
reconstruct the differential data) should recover up to 3 dB.

Pipeline per frame (tracking truth-free, identical EMA front-end as the m9
winner; truth used ONLY for scoring + the sanctioned CRC-guarded RS verdict):
  1. h4 EMA-integer-drift loop -> c[i,k], dtau[i]            (proven front-end)
  2. cumulative pilot timing de-rotation: c~ = c * exp(-j2pi f cumsum(dtau))
  3. per-symbol common-mode DD refine on absolute phases (mirror of _decide)
  4. V&V per carrier: u = (c~/|c~|)^4 -> centered moving average (2W+1)
     -> theta_ref = unwrap(angle)/4 -> absolute quadrant decisions
  5. differential data quadrants = diff(q_abs) mod 4 -> bits
  6. _rs_merge_guarded (CRC32-per-codeword guard) -> byte-exact verdict
Sweep W in {2,4,8,16}; also keep the plain differential decision as fallback
(strict-superset selector, same pattern as m9's front-end sweep: CRC-verified
byte-exact winner is kept).

Output: results/x10_c_vv_coherent.json
Usage:
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
        experiments/tape_v2/x10_c_vv_coherent.py [capture.wav]
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import m9_decode as m9d                      # noqa: E402
import m3_codec as codec                     # noqa: E402
from m3_codec import Rung                    # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S  # noqa: E402
import hyp_common as hc                      # noqa: E402

am2 = m9d.am2
SR = codec.FS

# section -> EMA alphas to try (winner first); m8 included as regression
TARGETS = {
    "m9_m4_n256_rs159": (0.6, 0.5),
    "m9_m5_n256_rs179": (0.6, 0.5),
    "m9_m6_n256_rs191": (0.6, 0.5),
    "m9_m7_n256_p11_9000": (0.5, 0.6),
    "m9_m8_dense375": (0.5,),
}
WINDOWS = (2,)            # V&V half-window W (absolute-domain arm, kept for record)
DFDD_GAMMAS = (0.5, 0.75, 0.875)   # decision-feedback differential memory


def _ema_demod_soft(sch, y, nd, alpha):
    """h4 EMA-integer-drift loop (mirrors x9 _demod_ema), returns c and dtau."""
    y = np.asarray(y, np.float64)
    ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
    total = nd + 1
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    fpil = sch.freqs[sch.pilot_idx]
    freqs = sch.freqs
    win = sch._win
    c = np.zeros((total, sch.P + 1), np.complex128)
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
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        c[i] = E @ (seg * win)
        if i > 0:
            dp = float(np.angle(c[i, sch.pilot_idx] * np.conj(c[i - 1, sch.pilot_idx])))
            sm = (1 - alpha) * (dp / (2 * np.pi * fpil)) + alpha * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
    return c, dtau


def _wrap(x):
    return (x + np.pi) % (2 * np.pi) - np.pi


def _vv_bits(sch, c, dtau, W):
    """Steps 2-5 of the pipeline; returns data bits (nd*2P,)."""
    fd = sch.freqs[sch.data_idx]
    total = c.shape[0]
    # 2. cumulative pilot-timing de-rotation (absolute domain)
    taucum = np.cumsum(dtau)
    cd = c[:, sch.data_idx] * np.exp(-2j * np.pi * np.outer(taucum, fd))
    # 3. per-symbol common-mode DD refine on absolute phases (one shot,
    #    residual-to-nearest-quadrant weighted by f -- mirror of _decide refine)
    phi = np.angle(cd)
    res = _wrap(phi - np.round(phi / (np.pi / 2)) * (np.pi / 2))
    dtau_res = (res * fd[None, :]).sum(axis=1) / (2 * np.pi * (fd ** 2).sum())
    cd = cd * np.exp(-2j * np.pi * dtau_res[:, None] * fd[None, :])
    # 4. V&V per carrier
    u = (cd / np.maximum(np.abs(cd), 1e-12)) ** 4
    k = 2 * W + 1
    ker = np.ones(k) / k
    q_abs = np.zeros(cd.shape, int)
    for j in range(cd.shape[1]):
        w = np.convolve(u[:, j], ker, mode="same")
        # guard the edges (partial windows): renormalize by actual kernel mass
        norm = np.convolve(np.ones(total), ker, mode="same")
        w = w / np.maximum(norm, 1e-12)
        th_ref = np.unwrap(np.angle(w)) / 4.0
        phi_c = _wrap(np.angle(cd[:, j]) - th_ref)
        q_abs[:, j] = np.round(phi_c / (np.pi / 2)).astype(int) % 4
    # 5. differential reconstruction
    q = (q_abs[1:, :] - q_abs[:-1, :]) % 4
    return sch.quadrants_to_bits(q)


def _dfdd_bits(sch, c, dtau, gamma):
    """Decision-feedback differential detection (DFDD), per carrier.

    Reference R is the recent past of the SAME carrier, rotated forward at each
    step by the decided data increment plus the pilot-tracked timing step --
    nothing global ever accumulates (the V&V absolute-domain failure mode).
    gamma=0 reduces to plain differential; effective averaging window is
    1/(1-gamma) symbols, cutting the white reference-noise variance by up to
    (1-gamma)/(1+gamma) (the measured lag-1 rho ~ -0.5 says the per-symbol
    noise IS white, so averaging is the right move).
    First pass decides per carrier; a one-shot common-mode refine across
    carriers (mirror of _decide's DD refine) then corrects per-symbol common
    timing residual and re-decides.
    """
    fd = sch.freqs[sch.data_idx]
    cd = c[:, sch.data_idx]
    total = cd.shape[0]
    P = cd.shape[1]
    dphi = np.zeros((total - 1, P))
    for j in range(P):
        rot_t = np.exp(2j * np.pi * fd[j] * dtau)      # timing step rotations
        R = cd[0, j]
        for i in range(1, total):
            Rp = R * rot_t[i]
            dp = float(np.angle(cd[i, j] * np.conj(Rp)))
            q = int(np.round(dp / (np.pi / 2.0))) % 4
            dphi[i - 1, j] = dp
            R = (1.0 - gamma) * cd[i, j] + gamma * Rp * np.exp(1j * q * np.pi / 2.0)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    # one-shot common-mode refine (same math as _decide refine)
    res = _wrap(dphi - q * (np.pi / 2.0))
    dtau_res = (res * fd[None, :]).sum(axis=1) / (2 * np.pi * (fd ** 2).sum())
    dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
    q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
    return sch.quadrants_to_bits(q)


def _diff_bits(sch, c, dtau, refine=True):
    """Plain differential decision (mirror of _decide) as the fallback arm."""
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    if refine:
        res = _wrap(dphi - q * (np.pi / 2.0))
        dtau_res = (res * fd[None, :]).sum(axis=1) / (2 * np.pi * (fd ** 2).sum())
        dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
        q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
    return sch.quadrants_to_bits(q)


def run_section(audio_nom, sec, align, alphas):
    sch = m9d._scheme_from_entry(sec)
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))

    out_arms = []
    best = None
    done = False
    for alpha in alphas:
        if done:
            break
        # demod every frame ONCE per alpha (heavy), post-process per arm (cheap)
        soft = []
        for fi, st in enumerate(sec["frame_starts"]):
            nd = sch.nsym_data(nom_bits[fi])
            st = int(st) + align
            y = np.asarray(audio_nom[max(0, st - pad_lo):
                                     min(len(audio_nom), st + flen_full + pad_hi)],
                           np.float64)
            soft.append(_ema_demod_soft(sch, y, nd, alpha))

        arms = ([("diff", "diff", None)]
                + [(f"dfdd_g{g}", "dfdd", g) for g in DFDD_GAMMAS]
                + [(f"vv_W{W}", "vv", W) for W in WINDOWS])
        for name, kind, par in arms:
            rx_frames = []
            for (c, dtau) in soft:
                if kind == "diff":
                    bits = _diff_bits(sch, c, dtau)
                elif kind == "dfdd":
                    bits = _dfdd_bits(sch, c, dtau, par)
                else:
                    bits = _vv_bits(sch, c, dtau, par)
                rx_frames.append(np.asarray(bits, np.uint8))
            rec, cwf, misc, _ = m9d._rs_merge_guarded(rx_frames, meta, crc_table,
                                                      erase_frac=0.0)
            exact = rec == expected_packed
            byte_err = sum(a != b for a, b in zip(rec, expected_packed)) + abs(
                len(rec) - len(expected_packed))
            ser = m9d._per_carrier_ser(rx_frames, sec, sch, expected_packed)
            row = {"arm": f"a{alpha}_{name}", "byte_exact": bool(exact),
                   "cw_failed": int(cwf), "miscorrected": int(misc),
                   "byte_errors": int(byte_err), "per_carrier_ser": ser}
            out_arms.append(row)
            if best is None or (row["byte_exact"], -row["cw_failed"],
                                -row["byte_errors"]) > \
                    (best["byte_exact"], -best["cw_failed"], -best["byte_errors"]):
                best = row
            print(f"  {sec['name']:22s} {row['arm']:18s} exact={exact} cwf={cwf} "
                  f"be={byte_err} ser0={ser[0] if ser else None}")
            if exact and kind != "diff":
                done = True
                break
    return {"section": sec["name"], "phy": sec["phy"], "alphas": list(alphas),
            "net_bps": sec.get("projected_net_bps"),
            "arms": out_arms, "best_arm": best["arm"],
            "best_exact": best["byte_exact"], "best_cwf": best["cw_failed"]}


def main():
    cap = sys.argv[1] if len(sys.argv) > 1 else str(
        _HERE / "captures" / "tape9_run1.wav")
    manifest = json.loads(m9d.MANIFEST_PATH.read_text())
    audio, sr = sf.read(cap, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]

    out = {"capture": cap, "windows": list(WINDOWS), "sections": []}
    for sec in manifest["ws_payloads"]:
        if sec["name"] in TARGETS and not sec.get("skipped"):
            out["sections"].append(
                run_section(audio_nom, sec, align, TARGETS[sec["name"]]))

    rp = _HERE / "results" / "x10_c_vv_coherent.json"
    rp.write_text(json.dumps(out, indent=2, default=float))
    print(f"[x10_c_vv_coherent] wrote {rp}")


if __name__ == "__main__":
    main()
