"""d5_dd_bitload.py — D5: live decision-directed per-carrier bit-loading + null erasure.

C4's bit-loading is frozen from a SIM-channel probe; on the real (worn, 9 kHz BW)
channel the carriers above ~9 kHz are dead nulls yet C4 still loads them. D5 tests
RECEIVER-side channel-matched loading: probe per-SC SNR on the ACTUAL channel type
(disjoint seeds, legitimate channel-type training), erase nulls (carriers below an
SNR floor → 0 bits), and re-measure with the dd speed-correction front end.

Honest expectation: re-loading + null erasure repairs the WASTED carriers but
cannot fix C4's coherent per-symbol pilot-slope tracker, which is the real killer
(3/12 catastrophic seeds). So D5 is expected to give a modest real gain over
frozen-loaded C4 but stay far below the non-coherent combinatorial champion. A
fair, data-backed result either way.
"""
from __future__ import annotations
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "capacity"))
import numpy as np
import dd_common as dd
import capture_scenarios as cs
import hyp_common as hc
import c4_ofdm_bitload as c4

RESULTS = pathlib.Path(__file__).parent / "results"


def probe_snr_on(channel, cal_seeds=range(40, 50), n_probe_syms=60):
    """Re-probe C4's per-SC SNR on a given channel (sim or real), via dd speed
    correction so the worn 0.88x clock doesn't wreck the probe."""
    cfg = dd.CHANNELS[channel]
    rng = np.random.default_rng(12345)
    qpsk = c4.CONST[2]
    known_idx = rng.integers(0, 4, size=(n_probe_syms, len(c4.DATA_INDICES)))
    tx_data = qpsk[known_idx]
    pre = hc.make_preamble(0.25)
    ref_td = [c4._osym(c4._ref_fd()) for _ in range(c4.N_REF_SYMS)]
    data_td = []
    for s in range(n_probe_syms):
        fd = np.zeros(c4.N_FFT, dtype=complex)
        fd[c4.DATA_INDICES] = tx_data[s]
        fd[c4.PILOT_INDICES] = c4.PILOT_PATTERN * c4.PILOT_AMP
        data_td.append(c4._osym(fd))
    audio = c4._normalize(np.concatenate(
        [pre, np.concatenate(ref_td), np.concatenate(data_td), np.zeros(int(0.05 * c4.FS))]))
    err = np.zeros(len(c4.DATA_INDICES)); sig = np.zeros(len(c4.DATA_INDICES))
    for seed in cal_seeds:
        rx_audio, sr, _ = cs.full_chain(audio, cfg["tape_preset"], cfg["capture_key"],
                                        speed_offset=cfg["speed_offset"], seed=seed)
        r = dd.estimate_speed(rx_audio)
        if abs(r - 1.0) > 0.01:   # only resample for a genuine clock offset
            rx_audio = dd.correct_speed(rx_audio, r)
        start = hc.find_preamble(rx_audio, 0.25)
        rx = np.asarray(rx_audio, dtype=np.float64)[start:]
        syms = c4._track_demod(rx, n_syms=n_probe_syms)
        for s, (eq, good) in enumerate(syms):
            if not good:
                continue
            ref0 = tx_data[s]
            alpha = np.vdot(ref0, eq) / np.vdot(ref0, ref0)
            eq2 = eq / alpha
            err += np.abs(eq2 - ref0) ** 2
            sig += np.abs(ref0) ** 2
    snr_lin = sig / np.maximum(err, 1e-12)
    return 10.0 * np.log10(np.maximum(snr_lin, 1e-9))


if __name__ == "__main__":
    out = {}
    print("=== D5: channel-matched bit-loading + null erasure (C4) ===")
    for channel in ("sim", "real"):
        snr = probe_snr_on(channel)
        # null erasure: carriers below 3 dB measured SNR -> 0 bits
        loading = c4._bit_loading_from_snr(snr, gap_db=9.0, max_bps=4)
        loading[snr < 3.0] = 0
        n_null = int(np.sum(snr < 3.0))
        # Apply loading directly (avoid c4._refreeze which recomputes from _SNR_DB).
        c4.BIT_LOADING = loading
        c4.ACTIVE = loading > 0
        c4.ACTIVE_MASK = c4.ACTIVE
        c4.ACTIVE_DATA_SC = c4.DATA_INDICES[c4.ACTIVE]
        c4.ACTIVE_BPS = loading[c4.ACTIVE]
        c4.BITS_PER_OFDM_SYM = int(np.sum(c4.ACTIVE_BPS))
        if c4.BITS_PER_OFDM_SYM == 0:
            # The coherent probe measured EVERY carrier as dead — C4's coherent
            # tracker can't even sound the real channel. Report and skip.
            out[channel] = {"snr_med": float(np.median(snr)), "n_null_erased": n_null,
                            "bits_per_sym": 0, "net": 0.0, "survival": 0.0,
                            "note": "coherent probe found NO usable carrier -> C4 unusable"}
            print(f"[{channel}] snr_med={np.median(snr):.1f} nulls={n_null}/{len(snr)} "
                  f"-> ALL carriers dead; C4 coherent probe fails on this channel")
            continue
        c4.GROSS_BPS = c4._gross_bps(4000)
        sch = hc.FuncScheme(name=f"D5_C4_ddload_{channel}", gross_bps=c4.GROSS_BPS,
                            modulate=c4.modulate, demodulate=c4.demodulate, erasure_fn=None)
        schx = dd.speed_correcting_demod(sch.demodulate)
        sch.demodulate = schx
        res = dd.eval_on(sch, channel, n_seeds=12)
        surv = float(np.mean(np.array(res.per_seed_ber) <= 3e-2))
        cat = float(np.mean(np.array(res.per_seed_ber) > 0.15))
        out[channel] = {"snr_med": float(np.median(snr)), "snr_min": float(snr.min()),
                        "snr_max": float(snr.max()), "n_null_erased": n_null,
                        "bits_per_sym": c4.BITS_PER_OFDM_SYM, "gross": res.gross_bps,
                        "net": res.net_bps, "ber": res.raw_ber, "survival": surv,
                        "catastrophic": cat}
        print(f"[{channel}] snr_med={np.median(snr):.1f} nulls={n_null} "
              f"bits/sym={c4.BITS_PER_OFDM_SYM} gross={res.gross_bps:.0f} "
              f"net={res.net_bps:.0f} ber={res.raw_ber:.3e} surv={surv:.2f} cat={cat:.2f}")
    out["verdict"] = ("Channel-matched DD loading + null erasure on C4: see numbers. "
                      "Compare real net vs frozen-C4 real (233) and vs combinatorial "
                      "champion (2525). C4 coherent tracking remains the real bottleneck.")
    json.dump(out, open(RESULTS / "d5.json", "w"), indent=2, default=float)
    print("[saved] d5.json")
