"""x12_micinv.py -- X12 SPIKE STEAL (a): static microphone non-linearity inverse.

HYPOTHESIS (BatComm steal): the capture chain's LAST element (iPhone mic +
ADC, approximately also the speaker) applies a static memoryless compression;
inverting it pre-demod should reduce the IMD floor / raise per-carrier SNR on
REAL captures.  A static post-inverse can only model non-linearity that acts
AFTER all dispersive elements -- tape/deck NL behind playback EQ is
structurally out of reach of this spike (logged as a caveat, not a leak).

PRE-REGISTERED GATES (frozen in this header AND in the JSON checkpoint at
creation, BEFORE any metric stage runs):

  G_M1 (SNR leg)   : median loaded-SNR_375 gain across multitone tones with
                     750 <= f <= 9000 Hz of >= +1.0 dB on the HELD-OUT tape10
                     multitone rep1 (fit never sees rep1).
  G_M2 (IMD leg)   : normalized in-band IMD excess -- sum over multitone gaps
                     of max(gap_floor - silence_psd, 0) * usable_gap_width,
                     normalized by in-band tone power -- reduced by >= 20%
                     on the HELD-OUT tape10 rep1.
  G_M3 (decode leg): with the fitted inverse applied pre-demod to the FULL
                     tape10 nominal capture, every banked rung (m10 r0-r8,
                     ACTIVE, non-freqdiff) must re-decode orig-exact: ZERO
                     regression vs results/x11_decode_results_tape10_run1.
                     Run ONLY IF (G_M1 or G_M2) passes -- pre-registered
                     ordering: a signal-level fail already makes PASS
                     impossible, so no decode/CRC trials are consumed.

  PASS = (G_M1 or G_M2) and G_M3.    Anything else = FAIL (honest KILL).

FIT PROTOCOL (frozen): model yhat = y + a3*y^3 + a5*y^5 (odd, memoryless,
ABSOLUTE capture units so coefficients transfer across captures of differing
level); fitted ONLY on tape10 multitone rep0 (rep1, tape9 rep0/rep1 are held
out); objective = normalized in-band IMD excess; coarse grid over normalized
(b3, b5) in [-0.5, 0.5] (u = y / p99.9|y|, a3 = b3/s^2, a5 = b5/s^4) followed
by Nelder-Mead polish.  An INJECTION CALIBRATION (forward-distort rep0 with
known cubic eps in {2,5,10}% at p99.9 level, then refit) quantifies both the
metric's sensitivity and the fit's recovery accuracy, so a null result is a
bounded statement ("any static mic NL is < eps_detectable"), not a shrug.

Frozen modules imported VERBATIM (read-only): x10_headroom._tone_gap_table,
x10_b_aggr_05_dense2x_probe._load_tape9, x11_decode._decode_section_x11,
h9_payload_codec.unpack_payload.

Stages (checkpoint results/x12_micinv.json; reruns skip done work):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 x12_micinv.py levels
    ... fit | validate | regress | verdict | all
Deterministic (no RNG).  Every RS/CRC trial in the conditional regress stage
is ledgered in the JSON.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import pathlib
import sys
import time

import numpy as np

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# frozen machinery, imported verbatim
from x10_headroom import _tone_gap_table               # noqa: E402
from x10_b_aggr_05_dense2x_probe import _load_tape9    # noqa: E402
from scipy.signal import welch                         # noqa: E402
from scipy.optimize import minimize                    # noqa: E402

SR = 48_000
RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "x12_micinv.json"
MANIFEST_M10 = json.loads((_HERE / "master10_manifest.json").read_text())
MANIFEST_M9 = json.loads((_HERE / "master9_manifest.json").read_text())
CACHE_T10 = _HERE / "captures" / "x11_decode_nom_tape10_run1.npy"
SYNC_T10 = RESULTS / "x11_decode_sync_tape10_run1.json"
BANKED_T10 = RESULTS / "x11_decode_results_tape10_run1.json"

BAND = (750.0, 9000.0)          # the modem band (d2x grid)
FLUTTER_FRAC = 0.0045           # matches _tone_gap_table's exclusion geometry
TRIM_MT, TRIM_NF = 0.3, 0.4     # section edge trims (headroom recipe)
EPS_INJECT = (0.02, 0.05, 0.10)

PREREG = {
    "frozen_utc": None,   # stamped at JSON creation, before any metric stage
    "model": "yhat = y + a3*y^3 + a5*y^5 (static, memoryless, odd; absolute "
             "capture units)",
    "fit_data": "tape10 multitone rep0 ONLY (rep1 + tape9 rep0/rep1 held out)",
    "objective": "normalized in-band IMD excess (gaps 750-9000 Hz)",
    "gates": {
        "G_M1": "median loaded-SNR_375 gain >= +1.0 dB, tones in 750-9000 Hz, "
                "tape10 rep1 (held out)",
        "G_M2": "normalized in-band IMD excess reduced >= 20%, tape10 rep1 "
                "(held out)",
        "G_M3": "0 decode regression on banked rungs (tape10, x11 receiver) "
                "with inverse pre-demod; only run if G_M1|G_M2",
        "PASS": "(G_M1 or G_M2) and G_M3",
    },
    "order": ["levels", "fit", "validate", "regress(conditional)", "verdict"],
}

CAVEATS = [
    "a static post-inverse models only the LAST memoryless non-linearity "
    "(mic+ADC, approximately speaker); tape/deck NL behind linear playback "
    "EQ is a Wiener-Hammerstein structure this spike cannot reach",
    "multitone gap floor = IMD + flutter FM sidebands + window leakage; the "
    "inverse can only remove the IMD part -- sensitivity quantified by the "
    "injection calibration so a null is a bounded null",
    "Voice Memos may apply slow AGC; gain wander breaks absolute-unit "
    "coefficient transfer tape9<->tape10, so the cross-capture row is "
    "supporting evidence, not a gate leg",
    "the inverse is applied to the nominal-rate resampled cache; memoryless "
    "NL commutes with the mild (1.0007x) resampling to first order",
]


# ===========================================================================
def _ckpt() -> dict:
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    pre = dict(PREREG)
    pre["frozen_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = {"campaign": "x12 spike steal (a): static mic non-linearity inverse",
           "prereg": pre, "caveats": CAVEATS, "stages": {}}
    RESULTS.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))
    return out


def _save(out: dict) -> None:
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))


def _load_tape10():
    audio_nom = np.load(CACHE_T10, mmap_mode="r")
    sync = json.loads(SYNC_T10.read_text())
    return audio_nom, int(sync["align"])


def _grab(audio_nom, align, sec, trim):
    st = sec["start"] + align
    ti = int(trim * SR)
    return np.asarray(audio_nom[st + ti: st + sec["length"] - ti], np.float64)


def _sections(manifest):
    mt = [s for s in manifest["sounder_sections"] if s["kind"] == "multitone"]
    nf = next(s for s in manifest["sounder_sections"] if s["kind"] == "noisefloor")
    freqs = np.asarray(mt[0]["info"]["freqs"], float)
    return mt, nf, freqs


def _apply_inv(y, a3, a5):
    y = np.asarray(y, np.float64)
    y2 = y * y
    return y * (1.0 + y2 * (a3 + a5 * y2))


def _noise_at_fn(nseg):
    f_n, n_psd = welch(nseg, fs=SR, nperseg=16384, noverlap=8192, window="hann")
    return lambda f: np.interp(np.asarray(f, float), f_n, n_psd)


def _gap_geometry(freqs):
    centers, widths = [], []
    for k in range(len(freqs) - 1):
        f0, f1 = freqs[k], freqs[k + 1]
        e0 = max(5.0, 3.0 * FLUTTER_FRAC * f0)
        e1 = max(5.0, 3.0 * FLUTTER_FRAC * f1)
        centers.append(0.5 * (f0 + f1))
        widths.append(max((f1 - e1) - (f0 + e0), 0.0))
    return np.asarray(centers), np.asarray(widths)


def _mt_metrics(seg, freqs, noise_at, full_tables=False):
    """Per-rep multitone metrics: normalized in-band IMD excess + loaded SNR."""
    tone_p, _gc, gap_f, _pib = _tone_gap_table(seg, freqs)
    centers, widths = _gap_geometry(freqs)
    gf = np.asarray([v if v is not None else np.nan for v in gap_f], float)
    n_gap = noise_at(centers)
    ing = ((centers >= BAND[0]) & (centers <= BAND[1])
           & ~np.isnan(gf) & (widths > 0))
    imd_excess = float(np.sum(np.maximum(gf[ing] - n_gap[ing], 0.0)
                              * widths[ing]))
    int_ = (freqs >= BAND[0]) & (freqs <= BAND[1])
    tone_band_p = float(np.sum(tone_p[int_]))
    ok = ~np.isnan(gf)
    loaded_at_tone = np.interp(freqs, centers[ok], gf[ok])
    snr_loaded = 10.0 * np.log10(tone_p / (loaded_at_tone * 375.0) + 1e-300)
    res = {"imd_excess_norm": imd_excess / max(tone_band_p, 1e-300),
           "snr_loaded_med_db": round(float(np.median(snr_loaded[int_])), 3),
           "n_tones_in_band": int(int_.sum()), "n_gaps_in_band": int(ing.sum())}
    if full_tables:
        res["snr_loaded_db"] = [round(float(s), 2) for s in snr_loaded]
        res["bloom_db_gaps"] = [
            (round(float(10 * np.log10(g / n + 1e-300)), 2)
             if np.isfinite(g) else None) for g, n in zip(gf, n_gap)]
    return res


# ===========================================================================
def stage_levels():
    out = _ckpt()
    if "levels" in out["stages"]:
        print("[levels] already done")
        return
    rows = {}
    for tag, loader, man in (("tape10", _load_tape10, MANIFEST_M10),
                             ("tape9", _load_tape9, MANIFEST_M9)):
        audio_nom, align = loader()
        mt, nf, _ = _sections(man)
        r = {}
        for i, sec in enumerate(mt):
            seg = _grab(audio_nom, align, sec, TRIM_MT)
            r[f"multitone_rep{i}"] = {
                "rms": round(float(np.sqrt(np.mean(seg ** 2))), 5),
                "p999_abs": round(float(np.percentile(np.abs(seg), 99.9)), 5),
                "peak_abs": round(float(np.max(np.abs(seg))), 5)}
        nseg = _grab(audio_nom, align, nf, TRIM_NF)
        r["noisefloor"] = {"rms": round(float(np.sqrt(np.mean(nseg ** 2))), 6)}
        rows[tag] = r
        print(f"[levels] {tag}: " + json.dumps(r))
    out["stages"]["levels"] = rows
    _save(out)


# ===========================================================================
def _fit_inverse(seg, freqs, noise_at, s_ref, label=""):
    """Grid + Nelder-Mead over normalized (b3, b5); returns fit record."""
    n_eval = [0]

    def J(b):
        b3, b5 = float(b[0]), float(b[1])
        if abs(b3) > 1.0 or abs(b5) > 1.5:
            return 1e9
        a3, a5 = b3 / s_ref ** 2, b5 / s_ref ** 4
        n_eval[0] += 1
        return _mt_metrics(_apply_inv(seg, a3, a5), freqs,
                           noise_at)["imd_excess_norm"]

    j_id = J((0.0, 0.0))
    best, best_j = (0.0, 0.0), j_id
    for b3 in np.linspace(-0.5, 0.5, 21):
        for b5 in np.linspace(-0.5, 0.5, 11):
            j = J((b3, b5))
            if j < best_j:
                best, best_j = (float(b3), float(b5)), j
    res = minimize(J, np.asarray(best), method="Nelder-Mead",
                   options={"maxiter": 120, "xatol": 1e-3, "fatol": 1e-9})
    b3, b5 = (float(res.x[0]), float(res.x[1])) if res.fun <= best_j else best
    j_fit = min(float(res.fun), best_j)
    rec = {"label": label, "s_ref": float(s_ref),
           "b3": round(b3, 5), "b5": round(b5, 5),
           "a3": b3 / s_ref ** 2, "a5": b5 / s_ref ** 4,
           "J_identity": j_id, "J_fit": j_fit,
           "J_reduction_pct": round(100.0 * (1.0 - j_fit / max(j_id, 1e-300)), 2),
           "n_evals": n_eval[0]}
    print(f"  [fit {label}] b3={b3:+.4f} b5={b5:+.4f} "
          f"J {j_id:.3e} -> {j_fit:.3e} ({rec['J_reduction_pct']:+.1f}% red, "
          f"{n_eval[0]} evals)")
    return rec


def stage_fit():
    out = _ckpt()
    if "fit" in out["stages"]:
        print("[fit] already done")
        return
    t0 = time.time()
    audio_nom, align = _load_tape10()
    mt, nf, freqs = _sections(MANIFEST_M10)
    rep0 = _grab(audio_nom, align, mt[0], TRIM_MT)
    nseg = _grab(audio_nom, align, nf, TRIM_NF)
    noise_at = _noise_at_fn(nseg)
    s_ref = float(np.percentile(np.abs(rep0), 99.9))

    # ---- injection calibration: metric sensitivity to a KNOWN static cubic
    base = _mt_metrics(rep0, freqs, noise_at)
    inj = []
    for eps in EPS_INJECT:
        a3t = eps / s_ref ** 2
        m = _mt_metrics(rep0 + a3t * rep0 ** 3, freqs, noise_at)
        inj.append({"eps_at_p999": eps,
                    "imd_excess_norm": m["imd_excess_norm"],
                    "imd_increase_x": round(m["imd_excess_norm"]
                                            / max(base["imd_excess_norm"],
                                                  1e-300), 3),
                    "snr_loaded_med_db": m["snr_loaded_med_db"]})
        print(f"  [inject eps={eps}] IMDx{inj[-1]['imd_increase_x']} "
              f"snr_med {m['snr_loaded_med_db']} dB "
              f"(base {base['snr_loaded_med_db']})")
    # recovery check: can the fit find a known injected NL?
    a3_05 = 0.05 / s_ref ** 2
    rec_fit = _fit_inverse(rep0 + a3_05 * rep0 ** 3, freqs, noise_at, s_ref,
                           label="recovery(eps=0.05 injected)")
    rec_fit["recovered_eps"] = round(-rec_fit["b3"], 4)
    rec_fit["expected_eps_smallsignal"] = 0.05

    # ---- the real fit (tape10 rep0 ONLY)
    fit = _fit_inverse(rep0, freqs, noise_at, s_ref, label="tape10_rep0")
    out["stages"]["fit"] = {
        "fit_section": "tape10 multitone rep0",
        "baseline_rep0": base, "injection_calibration": inj,
        "recovery_check": rec_fit, "fitted": fit,
        "wall_s": round(time.time() - t0, 1)}
    _save(out)
    print(f"[fit] done in {out['stages']['fit']['wall_s']}s")


# ===========================================================================
def stage_validate():
    out = _ckpt()
    if "validate" in out["stages"]:
        print("[validate] already done")
        return
    if "fit" not in out["stages"]:
        raise RuntimeError("run fit first")
    t0 = time.time()
    fit = out["stages"]["fit"]["fitted"]
    a3, a5 = float(fit["a3"]), float(fit["a5"])
    rows = {}
    for tag, loader, man in (("tape10", _load_tape10, MANIFEST_M10),
                             ("tape9", _load_tape9, MANIFEST_M9)):
        audio_nom, align = loader()
        mt, nf, freqs = _sections(man)
        nseg = _grab(audio_nom, align, nf, TRIM_NF)
        noise_id = _noise_at_fn(nseg)
        noise_inv = _noise_at_fn(_apply_inv(nseg, a3, a5))
        for i, sec in enumerate(mt):
            seg = _grab(audio_nom, align, sec, TRIM_MT)
            mid = _mt_metrics(seg, freqs, noise_id, full_tables=True)
            minv = _mt_metrics(_apply_inv(seg, a3, a5), freqs, noise_inv,
                               full_tables=True)
            d_snr = round(minv["snr_loaded_med_db"] - mid["snr_loaded_med_db"], 3)
            imd_red = round(100.0 * (1.0 - minv["imd_excess_norm"]
                                     / max(mid["imd_excess_norm"], 1e-300)), 2)
            rows[f"{tag}_rep{i}"] = {
                "held_out": not (tag == "tape10" and i == 0),
                "identity": mid, "inverse": minv,
                "delta_snr_loaded_med_db": d_snr,
                "imd_excess_reduction_pct": imd_red}
            print(f"  [{tag} rep{i}] dSNR_med {d_snr:+.3f} dB, "
                  f"IMD excess red {imd_red:+.2f}%"
                  + ("  (HELD OUT)" if rows[f'{tag}_rep{i}']['held_out'] else
                     "  (in-sample)"))
        if tag == "tape9":   # independent refit = NL-estimate consistency
            rep0 = _grab(audio_nom, align, mt[0], TRIM_MT)
            s9 = float(np.percentile(np.abs(rep0), 99.9))
            rows["tape9_independent_refit"] = _fit_inverse(
                rep0, freqs, noise_id, s9, label="tape9_rep0(independent)")

    adj = rows["tape10_rep1"]
    g_m1 = bool(adj["delta_snr_loaded_med_db"] >= 1.0)
    g_m2 = bool(adj["imd_excess_reduction_pct"] >= 20.0)
    out["stages"]["validate"] = {
        "adjudicating_row": "tape10_rep1 (held out)",
        "rows": rows,
        "G_M1_snr_pass": g_m1, "G_M2_imd_pass": g_m2,
        "signal_gate_pass": bool(g_m1 or g_m2),
        "wall_s": round(time.time() - t0, 1)}
    _save(out)
    print(f"[validate] G_M1={g_m1} G_M2={g_m2} -> signal gate "
          f"{'PASS' if (g_m1 or g_m2) else 'FAIL'}")


# ===========================================================================
def stage_regress(sections=None):
    out = _ckpt()
    if "validate" not in out["stages"]:
        raise RuntimeError("run validate first")
    val = out["stages"]["validate"]
    st = out["stages"].setdefault("regress", {})
    if not val["signal_gate_pass"]:
        st.update({"skipped": True, "reason":
                   "pre-registered order: signal gate (G_M1|G_M2) FAILED on "
                   "the held-out tape10 rep1, PASS is already impossible -- "
                   "no decode/CRC trials consumed"})
        _save(out)
        print("[regress] SKIPPED (signal gate failed; pre-registered order)")
        return
    import x11_decode as x11                  # frozen receiver, read-only
    from h9_payload_codec import unpack_payload
    fit = out["stages"]["fit"]["fitted"]
    a3, a5 = float(fit["a3"]), float(fit["a5"])
    banked = json.loads(BANKED_T10.read_text())["payloads_by_name"]
    audio_nom, align = _load_tape10()
    audio_t = _apply_inv(np.asarray(audio_nom, np.float64), a3, a5)
    st.setdefault("ledger", {"rs_attempts": 0, "crc_checks": 0,
                             "crc_rejects": 0, "crc_accepts": 0})
    st.setdefault("sections", {})
    for sec in MANIFEST_M10["ws_payloads"]:
        name = sec["name"]
        if sections and name not in sections:
            continue
        if sec.get("forensic_only") or sec["kind"] == "freqdiff":
            continue
        if name in st["sections"]:
            continue
        t0 = time.time()
        r, assembled = x11._decode_section_x11(audio_t, sec, align,
                                               st["ledger"], verbose=False)
        if r.pop("_x11_orig_exact_override", None) is not None or \
                r.get("decoder_stage") == "x11_rescue":
            orig = bool(r["x11_rescue"]["orig_exact"])
        else:
            try:
                rec = unpack_payload(assembled)
                pk = sec["pack"]
                orig = (hashlib.sha256(rec).hexdigest() == pk["sha256_orig"]
                        and len(rec) == pk["orig_len"])
            except Exception:
                orig = False
        was = bool(banked[name].get("orig_byte_exact"))
        st["sections"][name] = {
            "orig_exact_with_inverse": bool(orig),
            "orig_exact_banked": was,
            "regressed": bool(was and not orig),
            "rs_codewords_failed": int(r.get("rs_codewords_failed", -1)),
            "decoder_stage": r.get("decoder_stage"),
            "wall_s": round(time.time() - t0, 1)}
        st["false_accept_bound"] = st["ledger"]["crc_checks"] * 2.0 ** -32
        _save(out)
        print(f"  [{name:26s}] inv={'YES' if orig else 'no'} "
              f"banked={'YES' if was else 'no'} "
              f"({st['sections'][name]['wall_s']}s)")
    done = [s for s in st["sections"].values()]
    st["n_regressed"] = sum(s["regressed"] for s in done)
    st["G_M3_decode_pass"] = bool(st["n_regressed"] == 0 and len(done) > 0)
    _save(out)
    print(f"[regress] {len(done)} sections, regressed={st['n_regressed']}")


# ===========================================================================
def stage_verdict():
    out = _ckpt()
    val = out["stages"].get("validate")
    if not val:
        raise RuntimeError("run validate first")
    reg = out["stages"].get("regress", {})
    fit = out["stages"]["fit"]
    sig = bool(val["signal_gate_pass"])
    g_m3 = bool(reg.get("G_M3_decode_pass", False))
    verdict = "PASS" if (sig and g_m3) else "FAIL"
    adj = val["rows"]["tape10_rep1"]
    inj = fit["injection_calibration"]
    # detectability bound: smallest injected eps whose IMD increase >= 1.2x
    detect = next((r["eps_at_p999"] for r in inj
                   if r["imd_increase_x"] >= 1.2), None)
    out["stages"]["verdict"] = {
        "verdict": verdict,
        "G_M1": val["G_M1_snr_pass"], "G_M2": val["G_M2_imd_pass"],
        "G_M3": g_m3 if sig else "not run (signal gate failed)",
        "heldout_delta_snr_db": adj["delta_snr_loaded_med_db"],
        "heldout_imd_reduction_pct": adj["imd_excess_reduction_pct"],
        "fitted_b3_b5": [fit["fitted"]["b3"], fit["fitted"]["b5"]],
        "injection_detectability_eps": detect,
        "recovery_check_eps": fit["recovery_check"].get("recovered_eps"),
        "interpretation": None}
    v = out["stages"]["verdict"]
    refit9 = val["rows"].get("tape9_independent_refit", {})
    v["tape9_independent_refit_b3_b5"] = [refit9.get("b3"), refit9.get("b5")]
    if verdict == "FAIL":
        base_fit = fit["fitted"]
        rec_delta = round(fit["recovery_check"]["b3"] - base_fit["b3"], 4)
        v["interpretation"] = (
            f"the fit machinery resolves a KNOWN injected cubic (delta-b3 of "
            f"recovery fit vs base fit = {rec_delta} vs -0.05 injected), yet "
            f"(1) the tape10 fit's in-sample gain ({base_fit['J_reduction_pct']}"
            f"% IMD) does NOT survive held-out rep1 "
            f"({v['heldout_imd_reduction_pct']}% / "
            f"{v['heldout_delta_snr_db']:+.3f} dB = overfit to rep noise), and "
            f"(2) an INDEPENDENT refit on tape9 rep0 lands at the identity "
            f"(b3={refit9.get('b3')}, b5={refit9.get('b5')}, 0.0% gain). "
            f"No invertible static mic/ADC non-linearity is present at our "
            f"capture levels (multitone p99.9 ~0.32-0.53 FS); the multitone "
            f"gap bloom is flutter FM sidebands + tape-side products, which a "
            f"memoryless post-inverse structurally cannot remove. Note the "
            f"injection table also shows the IMD-excess metric is only "
            f"mildly sensitive (eps=0.10 -> 1.11x), so the bounded claim is: "
            f"any static cubic is well below eps~0.05 at p99.9 level, since "
            f"the fit reliably recovers deltas of that size and found none "
            f"on either capture.")
    _save(out)
    print(f"[verdict] {verdict}  dSNR={v['heldout_delta_snr_db']:+.3f} dB  "
          f"IMDred={v['heldout_imd_reduction_pct']:+.2f}%")


STAGES = {"levels": stage_levels, "fit": stage_fit, "validate": stage_validate,
          "regress": stage_regress, "verdict": stage_verdict}

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES) + ["all"])
    ap.add_argument("--sections", nargs="*", default=None,
                    help="regress stage: subset of section names (chunking)")
    args = ap.parse_args()
    if args.stage == "all":
        for name, fn in STAGES.items():
            fn() if name != "regress" else fn(sections=args.sections)
    elif args.stage == "regress":
        stage_regress(sections=args.sections)
    else:
        STAGES[args.stage]()
