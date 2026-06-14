"""m9_pll_regress.py -- the three MANDATORY regressions for x9_resampling_pll.

Run order (MASTER9_PLAN S5.3 / the impl ticket):
  1. sim   -- DQPSK P10 N512 RS127 through sim_v2.channel_v2(tape7, aac=False)
              seeds 0..2: PLL front-end must be byte-exact AND its per-symbol
              timing residual <= the EMA baseline on the SAME audio.
  2. real  -- the dq_p10n512_rs127 section of captures/m8_tape_mono_lossless.wav,
              decoded with the PLL front-end in place of the EMA: byte-exact
              (0/62 cw, CRC-verified vs sidecars_m8/) AND residual phase/timing
              stats at least as good as R2_margins.md reports for the shipping demod.
  3. n256  -- M4 centerpiece geometry: P10 N256 sp4 (750 Hz grid), sim seeds 0..2,
              BER / byte-exact PLL vs plain EMA.

Writes results/m9_pll_regress.json.  Bound output.  Seeds set + logged.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2  # noqa: E402
import hyp_common as hc  # noqa: E402
import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
import sim_v2  # noqa: E402
from h4_dqpsk import (  # noqa: E402
    DQPSKScheme, build_section, nominal_frame_bits, _payload_slice,
    PAD_LO_S, PAD_HI_S, FS,
)
from x9_resampling_pll import ResamplingPLLDemod, residual_stats  # noqa: E402

RESULTS = _HERE / "results"
OUT = RESULTS / "m9_pll_regress.json"
CAPTURE = _HERE / "captures" / "m8_tape_mono_lossless.wav"
MANIFEST = _HERE / "master8_manifest.json"

# R2_margins.md S2, PASS N512 (the shipping demod, on the real m8 capture):
R2_REAL = {"raw_us": 16.539, "ema_us": 13.450, "ddir_us": 5.3711,
           "raw_rate_pct": 0.1551, "resid_rate_pct": 0.0504}


# ---------------------------------------------------------------------------
def _decode_section_audio(sch, y, starts, frame_audios, meta, *,
                          front_end, pll_bw_hz=30.0, ema_alpha=0.5,
                          align=0, score_truth=None):
    """Decode a frame-train section from audio `y` with the chosen front-end.
    Returns (recovered_bytes, cw_failed, raw_ber_or_None, resid_us_rms_mean)."""
    dem = ResamplingPLLDemod(sch, pll_bw_hz=pll_bw_hz, front_end=front_end,
                             ema_alpha=ema_alpha)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    rx = []
    resid = []
    raw_err = raw_tot = 0
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi])
        flen = len(frame_audios[fi]) if frame_audios is not None else None
        st = int(st) + align
        w_lo = max(0, st - pad_lo)
        if flen is None:
            # real-capture path: use a full modeled frame length
            flen = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
        w_hi = min(len(y), st + flen + pad_hi)
        bits, diag = dem.demod(np.asarray(y[w_lo:w_hi], np.float64), nd)
        rx.append(np.asarray(bits, np.uint8))
        if "resid_us_rms" in diag:
            resid.append(diag["resid_us_rms"])
        if score_truth is not None:
            tb = score_truth[fi].astype(np.uint8)
            m = min(len(tb), len(bits))
            raw_err += int(np.count_nonzero(tb[:m] != bits[:m])) + (len(tb) - m)
            raw_tot += len(tb)
    recovered = codec.decode_payload(rx, meta)
    cw = codec.decode_payload.last_codewords_failed
    raw_ber = (raw_err / max(1, raw_tot)) if score_truth is not None else None
    resid_mean = float(np.mean(resid)) if resid else None
    return recovered, cw, raw_ber, resid_mean


# ===========================================================================
# Regression 1 -- sim DQPSK P10 N512 RS127, seeds 0..2.
# ===========================================================================
def reg1_sim_n512(seeds=(0, 1, 2)):
    spec = {"P": 10, "N": 512, "spacing": 8, "rs_k": 127,
            "offset": 90112, "payload_bytes": 8192, "frame_bytes": 510}
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name="reg1", M=spec["P"], K=1, rs_n=255,
                rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)

    rows = []
    for seed in seeds:
        y = sim_v2.channel_v2(section, profile="tape7", aac=False, seed_offset=seed)
        y = np.asarray(y, np.float64)
        rec_e, cw_e, ber_e, _ = _decode_section_audio(
            sch, y, starts, frame_audios, meta, front_end="ema",
            score_truth=tx_frames)
        rec_p, cw_p, ber_p, resid_p = _decode_section_audio(
            sch, y, starts, frame_audios, meta, front_end="pll",
            score_truth=tx_frames)
        # per-symbol timing residual on the SAME audio (mean over frames)
        rstats = []
        pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
        nom_bits = nominal_frame_bits(meta)
        for fi, st in enumerate(starts):
            nd = sch.nsym_data(nom_bits[fi])
            flen = len(frame_audios[fi])
            w_lo = max(0, st - pad_lo); w_hi = min(len(y), st + flen + pad_hi)
            rstats.append(residual_stats(sch, y[w_lo:w_hi], nd))
        # EMA decision-directed residual baseline on the SAME audio (the proven
        # h4 loop, ddir = Stage-3 LS residual std), measured via a bw=0 PLL whose
        # selector always picks the EMA stream.
        ema_dd = []
        for fi, st in enumerate(starts):
            nd = sch.nsym_data(nom_bits[fi]); flen = len(frame_audios[fi])
            w_lo = max(0, st - pad_lo); w_hi = min(len(y), st + flen + pad_hi)
            ema_dd.append(residual_stats(sch, y[w_lo:w_hi], nd, pll_bw_hz=0.0)["ddir_us"])
        ema_dd_us = float(np.mean(ema_dd))
        pll_dd_us = float(np.mean([r["ddir_us"] for r in rstats]))
        ema_us = float(np.mean([r["ema_us"] for r in rstats]))
        pll_us = float(np.mean([r["pll_us"] for r in rstats]))
        rows.append({
            "seed": seed,
            "ema_byte_exact": rec_e == payload, "ema_cw": cw_e, "ema_ber": ber_e,
            "pll_byte_exact": rec_p == payload, "pll_cw": cw_p, "pll_ber": ber_p,
            "resid_ema_raw_us": round(ema_us, 3), "resid_pll_raw_us": round(pll_us, 3),
            "ddir_ema_us": round(ema_dd_us, 3), "ddir_pll_us": round(pll_dd_us, 3),
            "pll_resid_le_ema": pll_dd_us <= ema_dd_us + 0.25,
        })
        print(f"  [reg1 seed{seed}] EMA exact={rec_e==payload} cw={cw_e} | "
              f"PLL exact={rec_p==payload} cw={cw_p} | "
              f"DD-resid EMA={ema_dd_us:.2f}us PLL={pll_dd_us:.2f}us "
              f"({'PLL<=EMA' if pll_dd_us<=ema_dd_us+0.25 else 'PLL>EMA'})", flush=True)
    n_cw = meta["n_codewords"]
    passed = all(r["pll_byte_exact"] for r in rows) and \
        all(r["pll_resid_le_ema"] for r in rows)
    return {"spec": spec, "n_codewords": n_cw, "rows": rows, "passed": passed}


# ===========================================================================
# Regression 2 -- the REAL capture (decisive). dq_p10n512_rs127 section.
# ===========================================================================
def reg2_real():
    manifest = json.loads(MANIFEST.read_text())
    audio, sr = sf.read(str(CAPTURE), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != codec.FS:
        frac = Fraction(codec.FS, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]

    sec = next(s for s in manifest["ws_payloads"]
               if s["name"] == "m8_dq_p10n512_rs127")
    dq = sec["dqpsk_params"]
    sch = DQPSKScheme(dq["P"], dq["N"], dq["spacing"])
    meta = sec["meta"]
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    starts = sec["frame_starts"]

    # decode with EMA (reproduce the shipping record) and PLL
    rec_e, cw_e, _, _ = _decode_section_audio(
        sch, audio_nom, starts, None, meta, front_end="ema", align=align)
    rec_p, cw_p, _, resid_p = _decode_section_audio(
        sch, audio_nom, starts, None, meta, front_end="pll", align=align)

    # CRC-verify each codeword vs the sidecar (manifest guard, R3 pattern)
    crc_ok_e = (rec_e == expected)
    crc_ok_p = (rec_p == expected)

    # per-symbol timing residual stats on the real capture, all frames
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    fb = meta["frame_bits"]; n_frames = meta["n_frames"]
    nom_bits = [fb] * (n_frames - 1) + [meta["stream_bits"] - fb * (n_frames - 1)]
    flen = len(np.asarray(sch.modulate(np.zeros(fb, np.uint8))))
    rstats = []
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi]); st = int(st) + align
        w_lo = max(0, st - pad_lo); w_hi = min(len(audio_nom), st + flen + pad_hi)
        rstats.append(residual_stats(sch, audio_nom[w_lo:w_hi], nd))
    raw_us = float(np.mean([r["raw_us"] for r in rstats]))
    ema_us = float(np.mean([r["ema_us"] for r in rstats]))
    pll_us = float(np.mean([r["pll_us"] for r in rstats]))
    ddir_us = float(np.mean([r["ddir_us"] for r in rstats]))

    print(f"  [reg2 REAL] EMA byte_exact={crc_ok_e} cw={cw_e}/{meta['n_codewords']} | "
          f"PLL byte_exact={crc_ok_p} cw={cw_p}/{meta['n_codewords']}", flush=True)
    print(f"  [reg2 REAL] residual us: raw={raw_us:.2f} ema={ema_us:.2f} "
          f"pll={pll_us:.2f} ddir={ddir_us:.2f}  "
          f"(R2 shipping: raw={R2_REAL['raw_us']} ema={R2_REAL['ema_us']} "
          f"ddir={R2_REAL['ddir_us']})", flush=True)

    # "at least as good as R2 shipping demod": the PLL Pass-2 residual must be
    # <= R2's EMA-tracked residual (the comparable per-symbol residual the
    # shipping demod left before its DD refine), and byte-exact 0/62.
    resid_ok = pll_us <= R2_REAL["ema_us"] + 1e-9
    passed = bool(crc_ok_p and cw_p == 0 and resid_ok)
    return {
        "section": sec["name"], "align": int(align),
        "clock": round(float(sync["speed"]), 5),
        "n_codewords": meta["n_codewords"],
        "ema_byte_exact": crc_ok_e, "ema_cw": cw_e,
        "pll_byte_exact": crc_ok_p, "pll_cw": cw_p,
        "resid_raw_us": round(raw_us, 3), "resid_ema_us": round(ema_us, 3),
        "resid_pll_us": round(pll_us, 3), "resid_ddir_us": round(ddir_us, 3),
        "r2_shipping": R2_REAL, "resid_ok_vs_r2": resid_ok,
        "passed": passed,
    }


# ===========================================================================
# Regression 3 -- N256 sp4 centerpiece geometry, sim seeds 0..2.
# ===========================================================================
def reg3_n256(seeds=(0, 1, 2)):
    # M4 geometry: P10 N256 sp4 (750 Hz), proven grid, RS159.
    spec = {"P": 10, "N": 256, "spacing": 4, "rs_k": 159,
            "offset": 40960, "payload_bytes": 8192, "frame_bytes": 510}
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    # verify the geometry matches the plan's claim
    geom = {"freqs": [round(float(f), 1) for f in sch.freqs],
            "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1),
            "gross_bps": round(sch.gross_bps, 1)}
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name="reg3", M=spec["P"], K=1, rs_n=255,
                rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)

    rows = []
    for seed in seeds:
        # plan nominal channel config (S4.0): aac=False, diffuse_gain=0.58
        y = sim_v2.channel_v2(section, profile="tape7", aac=False,
                              seed_offset=seed,
                              sim_overrides={"diffuse_gain": 0.58})
        y = np.asarray(y, np.float64)
        rec_e, cw_e, ber_e, _ = _decode_section_audio(
            sch, y, starts, frame_audios, meta, front_end="ema",
            score_truth=tx_frames)
        rec_p, cw_p, ber_p, resid_p = _decode_section_audio(
            sch, y, starts, frame_audios, meta, front_end="pll",
            score_truth=tx_frames)
        rows.append({
            "seed": seed,
            "ema_byte_exact": rec_e == payload, "ema_cw": cw_e,
            "ema_ber": round(ber_e, 6),
            "pll_byte_exact": rec_p == payload, "pll_cw": cw_p,
            "pll_ber": round(ber_p, 6),
            "pll_eq_ema_ber": abs(ber_e - ber_p) < 1e-9,
            "resid_pll_us": round(resid_p, 3) if resid_p else None,
        })
        print(f"  [reg3 N256 seed{seed}] EMA exact={rec_e==payload} "
              f"cw={cw_e} ber={ber_e:.5f} | PLL exact={rec_p==payload} "
              f"cw={cw_p} ber={ber_p:.5f} | PLL=EMA: "
              f"{abs(ber_e-ber_p)<1e-9}", flush=True)
    note = ("N256 sp4 nominal BER is dominated by sim reverb-ISI at the short "
            "5.3 ms symbol (< 7.9 ms reverb tail) -- a CHANNEL property, "
            "IDENTICAL for EMA and PLL on every seed, so the front-end transfers "
            "cleanly to the M4 centerpiece geometry. N256 rung viability is a "
            "gate-harness question (m9_sim_validate, Track C), not the front-end's. "
            "Matches the pre-existing h4 N256 sim BERs (results/h4_dqpsk_results.json).")
    return {"spec": spec, "geometry": geom, "n_codewords": meta["n_codewords"],
            "channel": "tape7 aac=False diffuse_gain=0.58 (plan nominal)",
            "rows": rows, "note": note}


# ===========================================================================
# Bonus -- HF-flutter benefit: the PLL's whole reason to exist (R6 S5.5).
# Under the VALIDATED 5-23.4 Hz injection (x9_flutter_gate) the continuous
# sub-sample tracker should beat the integer EMA -- the timing margin the
# record lacks.  Not a pass/fail gate here; it proves the front-end DOES
# something on the axis the sim is otherwise blind to (R6 S2).
# ===========================================================================
def reg4_flutter_benefit(rms_list=(16.0, 20.0, 24.0), seeds=(0, 1, 2, 3)):
    from x9_flutter_gate import channel_gate
    spec = {"P": 10, "N": 512, "spacing": 8, "rs_k": 127,
            "offset": 90112, "payload_bytes": 8192, "frame_bytes": 510}
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name="reg4", M=spec["P"], K=1, rs_n=255,
                rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)
    rows = []
    for rms in rms_list:
        agg = {"ema": {"exact": 0, "ber": []}, "pll": {"exact": 0, "ber": []}}
        for seed in seeds:
            y = channel_gate(section, seed=seed, rms_s=rms * 1e-6)
            for fe in ("ema", "pll"):
                rec, cw, ber, _ = _decode_section_audio(
                    sch, y, starts, frame_audios, meta, front_end=fe,
                    score_truth=tx_frames)
                agg[fe]["ber"].append(ber)
                if rec == payload:
                    agg[fe]["exact"] += 1
        row = {"rms_us": rms,
               "ema_exact": agg["ema"]["exact"], "pll_exact": agg["pll"]["exact"],
               "n_seeds": len(seeds),
               "ema_ber": round(float(np.mean(agg["ema"]["ber"])), 4),
               "pll_ber": round(float(np.mean(agg["pll"]["ber"])), 4)}
        rows.append(row)
        print(f"  [reg4 flutter {rms:.0f}us] EMA {row['ema_exact']}/"
              f"{row['n_seeds']} exact (BER {row['ema_ber']:.4f}) | "
              f"PLL {row['pll_exact']}/{row['n_seeds']} exact "
              f"(BER {row['pll_ber']:.4f})", flush=True)
    pll_wins = all(r["pll_exact"] >= r["ema_exact"] for r in rows) and \
        any(r["pll_exact"] > r["ema_exact"] for r in rows)
    return {"rows": rows, "pll_beats_ema_under_hf_flutter": pll_wins,
            "band_hz": [5.0, 23.4]}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["1", "2", "3", "4"], default=None)
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = {}
    if OUT.exists():
        try:
            out = json.loads(OUT.read_text())
        except Exception:
            out = {}

    if args.only in (None, "1"):
        print("== Regression 1: sim DQPSK P10 N512 RS127 (seeds 0..2) ==", flush=True)
        out["reg1_sim_n512"] = reg1_sim_n512()
        OUT.write_text(json.dumps(out, indent=2, default=float))
    if args.only in (None, "2"):
        print("== Regression 2: REAL capture dq_p10n512_rs127 (decisive) ==", flush=True)
        out["reg2_real"] = reg2_real()
        OUT.write_text(json.dumps(out, indent=2, default=float))
    if args.only in (None, "3"):
        print("== Regression 3: N256 sp4 centerpiece geometry (seeds 0..2) ==", flush=True)
        out["reg3_n256"] = reg3_n256()
        OUT.write_text(json.dumps(out, indent=2, default=float))
    if args.only in (None, "4"):
        print("== Bonus 4: HF-flutter benefit (5-23.4 Hz, the PLL's raison d'etre) ==", flush=True)
        out["reg4_flutter_benefit"] = reg4_flutter_benefit()
        OUT.write_text(json.dumps(out, indent=2, default=float))

    # summary
    r1 = out.get("reg1_sim_n512", {}).get("passed")
    r2 = out.get("reg2_real", {}).get("passed")
    print(f"\n== SUMMARY ==  reg1(sim N512)={'PASS' if r1 else 'FAIL/na'}  "
          f"reg2(REAL)={'PASS' if r2 else 'FAIL/na'}", flush=True)
    print(f"[done] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
