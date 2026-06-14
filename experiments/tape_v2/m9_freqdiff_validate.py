"""m9_freqdiff_validate.py -- validation harness for x9_freqdiff (master9 M9a).

Three tests, exactly as the M9a work spec requires:

  (1) no-channel modulate->demod BER EXACTLY 0 across 3 random payloads.
  (2) sim_v2 channel_v2(profile='tape7', aac=False) seeds 0..2 with RS(255,159)
      framing via m3_codec: report raw BER + byte-exact recovery.
  (3) THE HEADLINE PROPERTY TEST: inject synthetic timing jitter (a ~0.4 %
      flutter-like resample wobble) WITHOUT channel noise, and show frequency-
      differential BER stays ~0 where TIME-differential DQPSK on the SAME audio
      degrades.  Quantitative proof of the timing-immunity claim.

The timing-jitter injection reuses the validated x9_flutter_gate mechanism
(`np.interp(t, t - tau, y)`) -- a resampling trajectory y(t)=x(t-tau(t)), the
correct model of cassette flutter (R6 1a).  Test (3) compares F-DQPSK against the
proven time-differential h4 DQPSKScheme on IDENTICAL jittered audio (matched P10
N512 sp8 grid, matched payload) so the only difference is the data mapping.

Run:  python3 experiments/tape_v2/m9_freqdiff_validate.py
Writes a numeric summary to results/m9_freqdiff_validate.json.
Seeds set + logged.  Reads only.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np
from scipy import signal

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                              # noqa: E402
from m3_codec import Rung                             # noqa: E402
import sim_v2                                         # noqa: E402
from h4_dqpsk import (                                # noqa: E402
    DQPSKScheme, build_section, nominal_frame_bits, _payload_slice,
    PAD_LO_S, PAD_HI_S, FS,
)
from x9_freqdiff import FreqDiffDQPSKScheme           # noqa: E402

RESULTS = _HERE / "results"
OUT = RESULTS / "m9_freqdiff_validate.json"


# ---------------------------------------------------------------------------
# helpers: run a frame-train section through a scheme, score raw BER + byte-exact
# ---------------------------------------------------------------------------
def _score_section(sch, tx_frames, meta, y, starts, frame_audios, payload,
                   want_diag=False):
    """Demod every frame in y, score raw BER (vs tx bits) + RS-decode byte-exact.

    want_diag: also return the per-pair static-tilt magnitude measured on frame 0
    (the diagnostic that explains a freq-diff sim failure: the channel phase tilt
    across the 750 Hz carrier gap).
    """
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    rx_frames = []
    diag0 = None
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi])
        flen = len(frame_audios[fi])
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(y), st + flen + pad_hi)
        bits, diag = sch.demod(y[w_lo:w_hi], nd)
        if fi == 0:
            diag0 = diag
        rx_frames.append(bits)
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(bits))
        raw_err += int(np.count_nonzero(tb[:m] != bits[:m])) + (len(tb) - m)
        raw_tot += len(tb)
    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    out = {
        "raw_ber": raw_err / max(1, raw_tot),
        "rs_codewords_failed": cw_failed,
        "n_codewords": meta["n_codewords"],
        "byte_exact": bool(recovered == payload),
    }
    if want_diag and diag0 is not None and "pair_static_tilt_rad" in diag0:
        beta = np.asarray(diag0["pair_static_tilt_rad"])
        gamma = np.asarray(diag0["common_rot_rad"])
        out["pair_static_tilt_deg"] = [round(float(np.degrees(b)), 1) for b in beta]
        out["pair_static_tilt_rms_deg"] = round(
            float(np.degrees(np.sqrt(np.mean(beta ** 2)))), 1)
        out["common_rot_std_deg"] = round(float(np.degrees(np.std(gamma))), 1)
    return out


def _build_frames(sch, payload, rs_k, frame_bytes=510):
    rung = Rung(name=sch.name, M=getattr(sch, "P", 1), K=1,
                rs_n=255, rs_k=rs_k, frame_bytes=frame_bytes)
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)
    return tx_frames, meta, frame_audios, section, starts


# ---------------------------------------------------------------------------
# timing-jitter injection (the x9_flutter_gate resample-wobble, no channel noise)
# ---------------------------------------------------------------------------
def inject_jitter(y, *, seed, rms_us, band_hz=(5.0, 23.4), fs=FS):
    """Apply a flutter-like resample wobble y(t) -> y(t - tau(t)) WITHOUT any other
    channel impairment.  tau is band-limited white noise (the load-bearing
    5-23.4 Hz symbol-tracking band, identical to x9_flutter_gate) scaled to a
    timing-displacement RMS of rms_us microseconds -- the same resampling-
    trajectory model the validated HF-flutter gate uses, isolated from noise/EQ.

    Returns (jittered_audio, measured_warp_rms_us).
    """
    y = np.asarray(y, np.float64)
    n = len(y)
    if rms_us <= 0:
        return y, 0.0
    rg = np.random.default_rng(70_000 + seed)
    w = rg.standard_normal(n)
    sos = signal.butter(4, list(band_hz), btype="band", fs=fs, output="sos")
    tau = signal.sosfiltfilt(sos, w)
    tau = tau / (np.sqrt(np.mean(tau ** 2)) + 1e-18) * (rms_us * 1e-6)  # seconds
    t = np.arange(n) / fs
    yj = np.interp(t, np.clip(t - tau, 0.0, t[-1]), y)
    return yj.astype(np.float64), float(np.sqrt(np.mean((tau * 1e6) ** 2)))


# ---------------------------------------------------------------------------
# TEST 1 -- no-channel BER exactly 0 across 3 random payloads
# ---------------------------------------------------------------------------
def test1_no_channel():
    sch = FreqDiffDQPSKScheme(11, 512, 8)
    pad_lo = int(PAD_LO_S * FS)
    rows = []
    for seed in (0, 1, 2):
        rng = np.random.default_rng(seed)
        nbits = sch.bits_per_sym * 64
        bits = rng.integers(0, 2, nbits).astype(np.uint8)
        audio = sch.modulate(bits)
        win = np.concatenate([np.zeros(pad_lo, np.float32), audio,
                              np.zeros(int(PAD_HI_S * FS), np.float32)])
        rb, _ = sch.demod(win, sch.nsym_data(nbits))
        m = min(len(bits), len(rb))
        err = int(np.count_nonzero(bits[:m] != rb[:m])) + abs(len(bits) - len(rb))
        rows.append({"seed": seed, "nbits": nbits, "ber": err / nbits,
                     "exact": err == 0})
    ok = all(r["exact"] for r in rows)
    return {"pass": ok, "scheme": sch.name, "rows": rows}


# ---------------------------------------------------------------------------
# TEST 2 -- sim_v2 channel, seeds 0..2, RS(255,159), byte-exact
# ---------------------------------------------------------------------------
def test2_sim_channel(rs_k=159, offset=0, payload_bytes=8192):
    sch = FreqDiffDQPSKScheme(11, 512, 8)
    payload = _payload_slice(offset, payload_bytes)
    tx_frames, meta, frame_audios, section, starts = _build_frames(sch, payload, rs_k)
    rows = []
    for seed in (0, 1, 2):
        t0 = time.time()
        y = sim_v2.channel_v2(section, profile="tape7", aac=False, seed_offset=seed)
        y = np.asarray(y, np.float64)
        r = _score_section(sch, tx_frames, meta, y, starts, frame_audios, payload,
                           want_diag=True)
        r.update({"seed": seed, "wall_s": round(time.time() - t0, 1)})
        rows.append(r)
    return {
        "scheme": sch.name, "rs_k": rs_k,
        "net_bps": round(sch.gross_bps * rs_k / 255.0, 1),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "section_seconds": round(len(section) / FS, 1),
        "rows": rows,
        "n_byte_exact": sum(r["byte_exact"] for r in rows),
        "mean_raw_ber": round(float(np.mean([r["raw_ber"] for r in rows])), 5),
    }


# ---------------------------------------------------------------------------
# TEST 3 -- HEADLINE timing-immunity proof:
#   freq-diff vs time-diff on IDENTICAL jittered audio, no channel noise
# ---------------------------------------------------------------------------
def test3_timing_immunity(rs_k=159, offset=16384, payload_bytes=6144,
                          jitter_us=(0.0, 10.0, 16.0, 24.0, 34.0, 50.0),
                          seeds=(0, 1, 2)):
    """Inject ONLY timing jitter (5-23.4 Hz resample wobble, no channel noise/EQ)
    and compare frequency-differential against the proven time-differential h4
    DQPSK on IDENTICAL audio.  34 us is the real m8 5-23.4 Hz residual band-RMS;
    levels bracket it.  The matched grids carry the SAME payload on the SAME
    750 Hz N512 grid -- the ONLY difference is the data mapping, so any divergence
    is the timing-immunity effect, not a confound."""
    # F-DQPSK P11 (10 data pairs) vs time-diff h4 P10 (10 data carriers): both
    # gross 1875 bps; both byte-exact at 0 jitter (matched starting point).
    fsch = FreqDiffDQPSKScheme(11, 512, 8)
    tsch = DQPSKScheme(10, 512, 8)
    payload = _payload_slice(offset, payload_bytes)

    f_tx, f_meta, f_fa, f_sec, f_st = _build_frames(fsch, payload, rs_k)
    t_tx, t_meta, t_fa, t_sec, t_st = _build_frames(tsch, payload, rs_k)

    rows = []
    for rms in jitter_us:
        for seed in seeds:
            fy, fr_us = inject_jitter(f_sec.astype(np.float64), seed=seed, rms_us=rms)
            ty, _ = inject_jitter(t_sec.astype(np.float64), seed=seed, rms_us=rms)
            fr = _score_section(fsch, f_tx, f_meta, fy, f_st, f_fa, payload)
            tr = _score_section(tsch, t_tx, t_meta, ty, t_st, t_fa, payload)
            rows.append({
                "jitter_us": rms, "seed": seed, "warp_rms_us": round(fr_us, 1),
                "freqdiff_raw_ber": round(fr["raw_ber"], 5),
                "freqdiff_byte_exact": fr["byte_exact"],
                "freqdiff_cw_failed": fr["rs_codewords_failed"],
                "timediff_raw_ber": round(tr["raw_ber"], 5),
                "timediff_byte_exact": tr["byte_exact"],
                "timediff_cw_failed": tr["rs_codewords_failed"],
            })

    table = []
    for rms in jitter_us:
        rr = [r for r in rows if r["jitter_us"] == rms]
        table.append({
            "jitter_us": rms,
            "warp_rms_us": round(float(np.mean([r["warp_rms_us"] for r in rr])), 1),
            "freqdiff_mean_ber": round(float(np.mean([r["freqdiff_raw_ber"] for r in rr])), 5),
            "freqdiff_n_exact": sum(r["freqdiff_byte_exact"] for r in rr),
            "timediff_mean_ber": round(float(np.mean([r["timediff_raw_ber"] for r in rr])), 5),
            "timediff_n_exact": sum(r["timediff_byte_exact"] for r in rr),
            "n_seeds": len(rr),
        })
    # The property is proven iff at the REAL m8 jitter level (34 us) freq-diff stays
    # byte-exact across seeds while time-diff degrades, AND freq-diff BER is far
    # below time-diff BER -- the quantitative timing-immunity claim.
    real = next(t for t in table if abs(t["jitter_us"] - 34.0) < 1e-6)
    immunity_proven = (
        real["freqdiff_n_exact"] >= 2 and real["freqdiff_n_exact"] > real["timediff_n_exact"]
        and real["freqdiff_mean_ber"] < 0.5 * max(real["timediff_mean_ber"], 1e-9)
    )
    return {
        "freqdiff_scheme": fsch.name, "timediff_scheme": tsch.name,
        "rs_k": rs_k, "n_codewords": f_meta["n_codewords"],
        "jitter_levels_us": list(jitter_us),
        "real_m8_residual_us": 34.0, "band_hz": [5.0, 23.4], "seeds": list(seeds),
        "rows": rows, "table": table,
        "immunity_proven": bool(immunity_proven),
    }


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = {"about": "x9_freqdiff (master9 M9a) validation",
           "channel": "sim_v2.channel_v2(profile='tape7', aac=False)"}

    print("== TEST 1: no-channel BER==0 (3 random payloads) ==", flush=True)
    out["test1_no_channel"] = test1_no_channel()
    for r in out["test1_no_channel"]["rows"]:
        print(f"  seed{r['seed']}: BER={r['ber']:.2e} exact={r['exact']}", flush=True)
    print(f"  PASS={out['test1_no_channel']['pass']}", flush=True)

    print("== TEST 2: sim_v2 tape7 aac=False, RS(255,159), seeds 0..2 ==", flush=True)
    out["test2_sim_channel"] = test2_sim_channel()
    t2 = out["test2_sim_channel"]
    for r in t2["rows"]:
        print(f"  seed{r['seed']}: rawBER={r['raw_ber']:.4f} "
              f"cw={r['rs_codewords_failed']}/{r['n_codewords']} "
              f"exact={r['byte_exact']} ({r['wall_s']}s)", flush=True)
    print(f"  net={t2['net_bps']} bps  byte_exact={t2['n_byte_exact']}/3  "
          f"meanBER={t2['mean_raw_ber']}", flush=True)

    print("== TEST 3: TIMING-IMMUNITY (freq-diff vs time-diff, jitter, no noise) ==",
          flush=True)
    out["test3_timing_immunity"] = test3_timing_immunity()
    print(f"  {'jitterus':>8} | {'FD_BER':>8} {'FD_ex':>6} | "
          f"{'TD_BER':>8} {'TD_ex':>6}   (34us = real m8 5-23Hz residual)", flush=True)
    for t in out["test3_timing_immunity"]["table"]:
        mark = "  <-- real" if abs(t["jitter_us"] - 34.0) < 1e-6 else ""
        print(f"  {t['jitter_us']:>8.0f} | "
              f"{t['freqdiff_mean_ber']:>8.4f} {t['freqdiff_n_exact']:>3}/{t['n_seeds']:<2} | "
              f"{t['timediff_mean_ber']:>8.4f} {t['timediff_n_exact']:>3}/{t['n_seeds']:<2}{mark}",
              flush=True)
    print(f"  IMMUNITY PROVEN: {out['test3_timing_immunity']['immunity_proven']}",
          flush=True)

    OUT.write_text(json.dumps(out, indent=2, default=float))
    print(f"[done] wrote {OUT}", flush=True)
    return out


if __name__ == "__main__":
    main()
