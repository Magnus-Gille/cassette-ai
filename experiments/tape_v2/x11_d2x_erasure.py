"""x11_d2x_erasure.py -- X11: harden the d2x decode path (critic gaps a+b).

PRE-REGISTERED GATE (frozen 2026-06-12, BEFORE any experiment ran):
  G1  Extend the carrier-class errors-and-erasures ladder to the d2x section
      layout and demonstrate on >=20 SYNTHETIC marginal d2x sections
      (master10's own r5-r8 waveforms through sim_v2.channel_v2 variants
      INCLUDING aac=True and constant clock offsets {+0.10%,+0.17%,+0.25%})
      that the ladder rescues >=30% of sections that the STOCK composed decode
      (m10_decode._decode_section, verbatim) leaves at 1-8 failed codewords;
      0 miscorrections post-hoc vs ground truth; trial ledger within budget
      (crc_checks * 2^-32 < 1e-4 campaign-wide).
  G2  0 regressions on the standard 4-capture suite (tape9 composed 9-banked +
      freqdiff negative; m8 0/62; tape7/tape4 named rungs via the UNCHANGED
      production decoders).
  G3  d2x window-plan sensitivity table: hann256_skip0 vs rect128_skip64 vs
      >=2 NEW pre-registered variants; identify the best truth-free selection
      statistic (candidates pre-registered below).
  Honest negative allowed: if the ladder structurally cannot rescue d2x,
  prove WHY with the error anatomy and report gate_met=false.

WHAT IS NEW (x11; everything frozen is imported read-only)
----------------------------------------------------------
1. x11 mini-master `x11_d2x_synth.wav`: BIT-IDENTICAL slices of master10.wav
   (head incl. chirp0+sounder, the r5-r8 block, the chirp1 tail), so the
   synthetic sections are master10's own waveforms. All cuts land in exact
   silence (asserted). Manifest entries copied verbatim, frame_starts shifted.
2. Channel variants: y = channel_v2(resample(x, 1+clk), profile='tape7',
   aac=aac, seed_offset=seed, sim_overrides={'diffuse_gain': dg}).
   clk axis = constant clock offset applied by polyphase resample of the WHOLE
   mini tape (deck speed error; the global chirp sync must recover it) -- the
   two dress gaps (AAC + constant clock offset) are exercised together.
   dg is calibrated by a cheap pre-registered SCREEN (rule frozen below)
   because the faithful sim at dg>=0.58 kills d2x outright (dress: 90/90) --
   marginality requires softening; the softening rule is chosen truth-blind
   from single-front-end fail fractions, never from rescue outcomes.
3. STOCK = m10_decode._decode_section verbatim (ensemble union + its existing
   d2x ladder). MARGINAL = stock-final 1..8 failed codewords.
4. X11 RESCUE (pre-registered order, strictly-additive CRC32-guarded
   fill-only; a CRC-passing codeword is FINAL):
     r-a  replicate stock pass-1 union (fidelity-checked vs the stock record);
     r-b  d2x SHIFT-WINDOW sweep: geometries {hann256_skip0, rect128_skip64}
          x bases {ema0.7, pll30} x global window shifts
          (hann: -32,-16,+16,+32; rect: -48,-32,-16,+16,+32,+48)
          + one per-carrier decision-EVM-argmin stitched branch per
          (geometry, base) -- the proven late-window dc0 mechanism extended
          to every d2x carrier; new branches are offered ONLY the CRC-failing
          codewords (fill-only);
     r-c  carrier-class errors-and-erasures ladder = m10_decode._erasure_ladder
          UNCHANGED (frozen bounds: truth-free residual-dispersion ranking,
          14 sets from the 4 worst carriers, 4 branches, <=60 patterns/cw)
          over the ENLARGED branch pool; pool ranked by the pre-registered
          truth-free statistic "mean byte distance to CRC-accepted consensus
          on passing codewords" (consensus bytes are CRC-verified, no truth).
   RESCUED = section reaches 0 failed cw + byte_exact + orig_exact.
5. G3 window plans (pre-registered): W1 hann256_skip0(S0), W2 rect128_skip64
   (S0), NEW: W3 rect128_skip32 (=rect,S-32), W4 rect128_skip96 (=rect,S+32),
   W5 rect128_skip112 (=rect,S+48), W6 hann256_skip0_S+32. Base ema0.7.
   Truth-free selection statistics evaluated: (a) mean decision-EVM deg,
   (b) RMS decision residual deg, (c) CRC-pass count. Truth metric = raw BER
   vs the TX frame bits (scoring only).

SCREEN RULE (frozen): screen grid dg in {0.35,0.40,0.45,0.50,0.55} x aac
{False,True} x clk {0} x seed {0}, single front-end hann256_skip0_ema0.7.
dg* = the dg whose MEDIAN single-front-end cw-fail fraction across the 8
(rung x aac) runs is closest to 0.10; dg2 = next-closest (extension reserve,
used only if the dg* stock grid yields <20 marginal sections). If no dg in
the screen yields any run with fail fraction in (0, 0.5), refine with steps
of 0.025 around the cliff (same rule).

STOCK GRID (frozen): dg* x aac {False,True} x clk {0.0,0.10,0.17,0.25} x
seeds {0,1} = 16 cells x 4 rungs (r5,r6,r7,r8) = 64 section-instances.
Extension (only if <20 marginal): same grid at dg2.

LEDGER: every RS decode attempt and CRC acceptance test (screen, stock,
rescue, windows, regression) is counted in results/x11_d2x_ledger.json;
hard abort if campaign crc_checks > 3e5 (bound 4.29e5 = 1e-4 budget).
Post-hoc truth audit on every accepted codeword; miscorrected must be 0.

FROZEN FILES are imported READ-ONLY: m10_decode, m10_master (not imported --
the mini tape slices master10.wav directly and asserts byte identity),
x10_a_fec_gmd_erasure, x10_b_cons_01_late_window_dc0, m9_decode,
analyze_master2, sim_v2, h4_dqpsk, x9_resampling_pll, m3_codec.

Usage (every invocation < 8 min; all stages checkpoint + resume):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 x11_d2x_erasure.py <stage>
    stages:
      build                       -- mini-master + manifest + byte-identity
      selfcheck                   -- clean + clk-only decodes (must be exact)
      screen [--part a|b]         -- dg calibration screen (rule above)
      stock --cell <id> [...]     -- stock composed decode of grid cell(s)
      rescue --cell <id> [...]    -- x11 rescue on that cell's marginal secs
      windows --cell <id> [...]   -- G3 sensitivity rows for marginal secs
      regress9|regressm8|regress7|regress4  -- G2 four-capture suite
      report                      -- gate rollup -> x11_d2x_gate_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sys
import time
import zlib
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

import analyze_master2 as am2                          # noqa: E402
import m3_codec as codec                               # noqa: E402
from m3_codec import Rung                              # noqa: E402
import m9_decode as m9d                                # noqa: E402 (read-only)
import m10_decode as m10                               # noqa: E402 (read-only)
import sim_v2                                          # noqa: E402 (read-only)
from h4_dqpsk import PAD_LO_S, PAD_HI_S                # noqa: E402
from h9_payload_codec import unpack_payload            # noqa: E402
from x10_a_fec_gmd_erasure import _rx_mat, _run_production  # noqa: E402
from x10_b_cons_01_late_window_dc0 import (            # noqa: E402
    _shift_pass_ema, _pll_warp, _shift_pass_pll, _decide_refine,
)
import hyp_common as hc                                # noqa: E402

SR = codec.FS
RESULTS = _HERE / "results"
CAP_DIR = _HERE / "captures"
MINI_WAV = _HERE / "x11_d2x_synth.wav"
MINI_MANIFEST = _HERE / "x11_d2x_synth_manifest.json"
MASTER10_WAV = _HERE / "master10.wav"
MASTER10_MANIFEST = _HERE / "master10_manifest.json"

D2X_SECTIONS = ("m10_r5_d2x_p18_rs127", "m10_r6_d2x_p21_rs159",
                "m10_r7_d2x_p21_rs159_twin", "m10_r8_d2x_p22_rs179")

# ---- pre-registered constants (FROZEN; see module docstring) ---------------
SCREEN_DGS = (0.35, 0.40, 0.45, 0.50, 0.55)
SCREEN_TARGET_FRAC = 0.10
MARGINAL_LO, MARGINAL_HI = 1, 8
STOCK_AAC = (False, True)
STOCK_CLK = (0.0, 0.10, 0.17, 0.25)
STOCK_SEEDS = (0, 1)
RESCUE_BASES = ("ema0.7", "pll30")
RESCUE_GEOS = ("hann256_skip0", "rect128_skip64")
HANN_SHIFTS = (-32, -16, 0, 16, 32)        # 0 kept for argmin reference only
RECT_SHIFTS = (-48, -32, -16, 0, 16, 32, 48)
WINDOW_PLANS = (("hann256_skip0", 0), ("rect128_skip64", 0),
                ("rect128_skip64", -32), ("rect128_skip64", 32),
                ("rect128_skip64", 48), ("hann256_skip0", 32))
WINDOW_PLAN_LABELS = ("hann256_skip0", "rect128_skip64", "rect128_skip32",
                      "rect128_skip96", "rect128_skip112", "hann256_skip0_S32")
LEDGER_HARD_CAP = 300_000          # crc_checks; budget 4.29e5 == 1e-4
FA_BUDGET = 1e-4

LEDGER_PATH = RESULTS / "x11_d2x_ledger.json"


# ===========================================================================
# campaign ledger (file-merged across invocations)
# ===========================================================================
def _new_ledger():
    return {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}


def _merge_ledger(stage: str, led: dict):
    data = (json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists()
            else {"campaign": "x11_d2x_erasure", "total": _new_ledger(),
                  "stages": {}})
    st = data["stages"].setdefault(stage, _new_ledger())
    for k in _new_ledger():
        st[k] += led[k]
        data["total"][k] += led[k]
    data["false_accept_bound"] = data["total"]["crc_checks"] * 2.0 ** -32
    data["fa_within_budget"] = bool(data["false_accept_bound"] < FA_BUDGET)
    LEDGER_PATH.write_text(json.dumps(data, indent=2))
    if data["total"]["crc_checks"] > LEDGER_HARD_CAP:
        raise SystemExit(f"LEDGER HARD CAP exceeded: {data['total']['crc_checks']} "
                         f"crc_checks > {LEDGER_HARD_CAP} -- campaign aborted")
    return data


# ===========================================================================
# stage: build -- the x11 mini-master sliced bit-identically from master10
# ===========================================================================
def _frame_stride(sec):
    fs = sec["frame_starts"]
    return fs[1] - fs[0]


def stage_build():
    audio, sr = sf.read(str(MASTER10_WAV), dtype="float32", always_2d=False)
    assert sr == SR and audio.ndim == 1
    man = json.loads(MASTER10_MANIFEST.read_text())
    secs = {s["name"]: s for s in man["ws_payloads"]}
    r0 = secs["m10_r0_canary_2572"]
    r5, r8 = secs[D2X_SECTIONS[0]], secs[D2X_SECTIONS[-1]]

    head_end = int(r0["frame_starts"][0]) - int(0.10 * SR)
    d2x_lo = int(r5["frame_starts"][0]) - int(0.30 * SR)
    d2x_hi = int(r8["frame_starts"][-1]) + _frame_stride(r8)   # lands in gap
    tail_lo = int(man["tx_chirp1"]) - SR

    # every cut must land in exact silence (the build concatenated _silence)
    for name, idx in (("head_end", head_end), ("d2x_lo", d2x_lo),
                      ("d2x_hi", d2x_hi), ("tail_lo", tail_lo)):
        w = audio[max(0, idx - 480): idx + 480]
        assert float(np.max(np.abs(w))) == 0.0, \
            f"cut {name}@{idx} not in silence (max {np.max(np.abs(w))})"

    head = audio[:head_end]
    d2x = audio[d2x_lo:d2x_hi]
    tail = audio[tail_lo:]
    mini = np.concatenate([head, d2x, tail])

    delta = head_end - d2x_lo            # add to old positions inside d2x block
    mani = {k: man[k] for k in ("SR", "global_chirp", "frame_gap_samples",
                                "cass_path", "cass_sha256", "rx_window_plan")}
    mani["tape"] = "x11_d2x_synth"
    mani["master_id"] = "x11_d2x_synth"
    mani["source"] = ("BIT-IDENTICAL slices of master10.wav (head w/ chirp0+"
                      "sounder, r5-r8 block, chirp1 tail); cuts in exact silence")
    mani["tx_chirp0"] = man["tx_chirp0"]
    mani["tx_chirp1"] = int(man["tx_chirp1"]) - tail_lo + head_end + len(d2x)
    mani["sounder_sections"] = man["sounder_sections"]
    mani["cuts"] = {"head_end": head_end, "d2x_lo": d2x_lo, "d2x_hi": d2x_hi,
                    "tail_lo": tail_lo, "delta": delta}
    mani["ws_payloads"] = []
    sha_rec = {}
    for nm in D2X_SECTIONS:
        e = json.loads(json.dumps(secs[nm]))     # deep copy
        e["frame_starts"] = [int(s) + delta for s in e["frame_starts"]]
        mani["ws_payloads"].append(e)
        lo_old, hi_old = int(secs[nm]["frame_starts"][0]), \
            int(secs[nm]["frame_starts"][-1]) + _frame_stride(secs[nm])
        seg_old = audio[lo_old:hi_old]
        seg_new = mini[lo_old + delta: hi_old + delta]
        assert np.array_equal(seg_old, seg_new), f"{nm} slice not bit-identical"
        sha_rec[nm] = hashlib.sha256(seg_old.tobytes()).hexdigest()

    sf.write(str(MINI_WAV), mini, SR, subtype="FLOAT")
    MINI_MANIFEST.write_text(json.dumps(mani, indent=2, default=float))
    out = {"experiment": "x11_d2x_erasure build",
           "mini_wav": MINI_WAV.name, "dur_s": round(len(mini) / SR, 2),
           "cuts": mani["cuts"],
           "byte_identity": "asserted np.array_equal on every section slice",
           "section_sha256_float32": sha_rec,
           "tx_chirp0": mani["tx_chirp0"], "tx_chirp1": mani["tx_chirp1"]}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "x11_d2x_build.json").write_text(json.dumps(out, indent=2))
    print(f"[build] {MINI_WAV.name} {out['dur_s']}s; sections bit-identical to "
          f"master10.wav; manifest -> {MINI_MANIFEST.name}")
    return out


# ===========================================================================
# capture generation (channel variants) + sync loading
# ===========================================================================
def cell_id(dg, aac, clk, seed):
    return f"dg{dg:.2f}_aac{int(bool(aac))}_clk{clk:+.2f}_s{seed}"


def _apply_clock(x: np.ndarray, clk_pct: float):
    """Constant playback-speed offset: deck runs at (1+clk) -> the capture is
    the tape audio time-compressed by 1/(1+clk). Polyphase resample."""
    if clk_pct == 0.0:
        return x, 1.0
    ratio = 1.0 / (1.0 + clk_pct / 100.0)
    frac = Fraction(ratio).limit_denominator(1000)
    y = resample_poly(x, frac.numerator, frac.denominator)
    return y, float(frac.numerator / frac.denominator)


def gen_capture(dg, aac, clk, seed, *, channel=True, force=False) -> pathlib.Path:
    cid = cell_id(dg, aac, clk, seed) if channel else f"clkonly_clk{clk:+.2f}"
    cap = CAP_DIR / f"x11_d2x_{cid}.wav"
    if cap.exists() and not force:
        return cap
    x, sr = sf.read(str(MINI_WAV), dtype="float64", always_2d=False)
    assert sr == SR
    y, ratio = _apply_clock(x, clk)
    if channel:
        y = sim_v2.channel_v2(y, profile="tape7", aac=bool(aac),
                              seed_offset=int(seed),
                              sim_overrides={"diffuse_gain": float(dg)})
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(str(cap), y.astype(np.float32), SR, subtype="FLOAT")
    print(f"[gen] {cap.name} ({len(y)/SR:.1f}s, ratio={ratio:.6f})", flush=True)
    return cap


def sync_load(cap: pathlib.Path):
    audio, sr = sf.read(str(cap), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)
    mani = json.loads(MINI_MANIFEST.read_text())
    sync = am2.global_sync_and_resample(audio, mani)
    align = int(sync["chirp0_nominal"]) - int(mani["tx_chirp0"])
    return sync["audio_nominal"], align, mani, {
        k: (float(v) if np.isscalar(v) else None)
        for k, v in sync.items() if k != "audio_nominal" and np.isscalar(v)}


# ===========================================================================
# stage: selfcheck -- clean + clk-only decodes (must be exact before any cell)
# ===========================================================================
def _screen_decode_section(audio_nom, sec, align, ledger):
    """Single pre-registered front-end (hann256_skip0 + ema0.7): the d2x
    primary. Returns (n_failed, n_cw)."""
    from x9_resampling_pll import ResamplingPLLDemod
    sch = m10._d2x_rx_scheme(sec, "hann256_skip0")
    dem = ResamplingPLLDemod(sch, front_end="ema", ema_alpha=0.7)
    rx, _ = m9d._demod_section_frames(audio_nom, sec, align, sch,
                                      lambda w, nd, d=dem: d.demod(w, nd))
    ok, _msgs = m10._per_cw_decode(_rx_mat(rx, sec["meta"]), sec["meta"],
                                   sec["crc32_codewords"], ledger)
    return int(np.sum(~ok)), len(ok)


def stage_selfcheck():
    led = _new_ledger()
    out = {"experiment": "x11_d2x_erasure selfcheck", "runs": []}
    # 1) clean mini tape through the FULL stock pipeline
    audio_nom, align, mani, sync = sync_load(MINI_WAV)
    run = {"capture": "clean (no channel)", "align": align, "sync": sync,
           "sections": []}
    for sec in mani["ws_payloads"]:
        res, assembled = m10._decode_section(audio_nom, sec, align, led,
                                             rescue=True, verbose=False)
        orig_ok = _orig_audit(sec, assembled)
        run["sections"].append({"name": sec["name"],
                                "cw_failed": res["rs_codewords_failed"],
                                "byte_exact": res["byte_exact"],
                                "orig_exact": orig_ok,
                                "miscorrected": res["miscorrected_cw"]})
        print(f"[selfcheck clean] {sec['name']}: cw {res['rs_codewords_failed']}"
              f"/{res['n_codewords']} byte={res['byte_exact']} orig={orig_ok}",
              flush=True)
    out["runs"].append(run)
    # 2) clk-only captures (no channel): the clock axis must decode exactly
    for clk in STOCK_CLK[1:]:
        cap = gen_capture(0, False, clk, 0, channel=False)
        audio_nom, align, mani, sync = sync_load(cap)
        run = {"capture": cap.name, "clk_pct": clk, "align": align,
               "sync_speed": sync.get("clock_ratio") or sync.get("speed"),
               "sections": []}
        for sec in mani["ws_payloads"]:
            nf, ncw = _screen_decode_section(audio_nom, sec, align, led)
            run["sections"].append({"name": sec["name"], "cw_failed": nf,
                                    "n_cw": ncw})
            print(f"[selfcheck clk{clk:+.2f}] {sec['name']}: {nf}/{ncw}",
                  flush=True)
        out["runs"].append(run)
    out["all_exact"] = all(
        all((s.get("cw_failed") == 0) for s in r["sections"]) for r in out["runs"])
    out["ledger"] = led
    (RESULTS / "x11_d2x_selfcheck.json").write_text(
        json.dumps(out, indent=2, default=_jsafe))
    _merge_ledger("selfcheck", led)
    print(f"[selfcheck] ALL EXACT: {out['all_exact']}")
    return out


def _orig_audit(sec, assembled: bytes):
    try:
        orig = unpack_payload(assembled)
        sha = hashlib.sha256(orig).hexdigest()
        return bool(sha == sec["pack"]["sha256_orig"]
                    and len(orig) == sec["pack"]["orig_len"])
    except Exception:
        return False


# ===========================================================================
# stage: screen -- dg calibration (rule frozen in module docstring)
# ===========================================================================
def stage_screen(part: str | None):
    led = _new_ledger()
    path = RESULTS / "x11_d2x_screen.json"
    out = (json.loads(path.read_text()) if path.exists()
           else {"experiment": "x11_d2x_erasure screen",
                 "rule": "dg* = dg with median single-FE fail frac across "
                         "(rung x aac) runs closest to 0.10; dg2 next-closest",
                 "frontend": "hann256_skip0_ema0.7", "runs": {}})
    aacs = {"a": (False,), "b": (True,)}.get(part or "", STOCK_AAC)
    for aac in aacs:
        for dg in SCREEN_DGS:
            key = cell_id(dg, aac, 0.0, 0)
            if key in out["runs"]:
                continue
            t0 = time.time()
            cap = gen_capture(dg, aac, 0.0, 0)
            audio_nom, align, mani, sync = sync_load(cap)
            rows = []
            for sec in mani["ws_payloads"]:
                nf, ncw = _screen_decode_section(audio_nom, sec, align, led)
                rows.append({"name": sec["name"], "cw_failed": nf, "n_cw": ncw,
                             "fail_frac": round(nf / ncw, 4)})
                print(f"[screen {key}] {sec['name']}: {nf}/{ncw}", flush=True)
            out["runs"][key] = {"dg": dg, "aac": aac, "rows": rows,
                                "elapsed_s": round(time.time() - t0, 1)}
            path.write_text(json.dumps(out, indent=2, default=_jsafe))
    # selection rule (recomputed every invocation; harmless)
    med = {}
    for dg in SCREEN_DGS:
        fr = [r["fail_frac"] for aac in STOCK_AAC
              for r in out["runs"].get(cell_id(dg, aac, 0.0, 0), {}).get("rows", [])]
        if fr:
            med[f"{dg:.2f}"] = float(np.median(fr))
    if len(med) == len(SCREEN_DGS) * 0 + len([d for d in SCREEN_DGS
                                              if f"{d:.2f}" in med]):
        ranked = sorted(med, key=lambda k: abs(med[k] - SCREEN_TARGET_FRAC))
        out["median_fail_frac"] = med
        if len(ranked) >= 2:
            out["dg_star"], out["dg2"] = float(ranked[0]), float(ranked[1])
    path.write_text(json.dumps(out, indent=2, default=_jsafe))
    _merge_ledger("screen", led)
    print(f"[screen] medians={out.get('median_fail_frac')} "
          f"dg*={out.get('dg_star')} dg2={out.get('dg2')}")
    return out


# ===========================================================================
# stage: stock -- the frozen composed decode on a grid cell
# ===========================================================================
def stock_cells(dg_star: float):
    return [(dg_star, aac, clk, seed) for aac in STOCK_AAC
            for clk in STOCK_CLK for seed in STOCK_SEEDS]


def stage_stock(cells: list[str]):
    led = _new_ledger()
    path = RESULTS / "x11_d2x_stock.json"
    out = (json.loads(path.read_text()) if path.exists()
           else {"experiment": "x11_d2x_erasure stock",
                 "decoder": "m10_decode._decode_section verbatim (rescue=True)",
                 "marginal_band": [MARGINAL_LO, MARGINAL_HI], "cells": {}})
    for cid in cells:
        if cid in out["cells"]:
            print(f"[stock] {cid} already done, skip")
            continue
        dg, aac, clk, seed = _parse_cell(cid)
        t0 = time.time()
        cap = gen_capture(dg, aac, clk, seed)
        audio_nom, align, mani, sync = sync_load(cap)
        rows = []
        for sec in mani["ws_payloads"]:
            res, assembled = m10._decode_section(audio_nom, sec, align, led,
                                                 rescue=True, verbose=False)
            orig_ok = _orig_audit(sec, assembled)
            nf = res["rs_codewords_failed"]
            ladder = res.get("ladder") or {}
            rows.append({
                "name": sec["name"], "cw_failed": nf,
                "n_codewords": res["n_codewords"],
                "byte_exact": res["byte_exact"], "orig_exact": orig_ok,
                "miscorrected": res["miscorrected_cw"],
                "marginal": bool(MARGINAL_LO <= nf <= MARGINAL_HI),
                "stock_ladder_targets": ladder.get("target_cws"),
                "stock_ladder_accepted": len(ladder.get("accepted") or []),
                "failed_idx": (ladder.get("target_cws") and
                               [i for i in ladder["target_cws"]
                                if not any(a["cw"] == i
                                           for a in ladder.get("accepted", []))]),
                "best_single_branch": res.get("best_single_branch"),
                "carrier_rank_worst_first": res.get("carrier_rank_worst_first"),
                "carrier_dispersion_deg": res.get("carrier_dispersion_deg"),
                "elapsed_s": res["elapsed_s"]})
            print(f"[stock {cid}] {sec['name']}: {nf}/{res['n_codewords']} "
                  f"marginal={rows[-1]['marginal']} misc={res['miscorrected_cw']}",
                  flush=True)
        out["cells"][cid] = {"dg": dg, "aac": aac, "clk_pct": clk, "seed": seed,
                             "sync_speed": sync.get("clock_ratio") or sync.get("speed"),
                             "align": align, "rows": rows,
                             "elapsed_s": round(time.time() - t0, 1)}
        path.write_text(json.dumps(out, indent=2, default=_jsafe))
        print(f"[stock] checkpoint {cid} ({out['cells'][cid]['elapsed_s']}s)",
              flush=True)
    _merge_ledger("stock", led)
    return out


def _parse_cell(cid: str):
    # dg0.45_aac1_clk+0.17_s0
    parts = cid.split("_")
    dg = float(parts[0][2:])
    aac = bool(int(parts[1][3:]))
    clk = float(parts[2][3:])
    seed = int(parts[3][1:])
    return dg, aac, clk, seed


# ===========================================================================
# x11 rescue: d2x shift-window sweep + frozen erasure ladder, fill-only
# ===========================================================================
def _d2x_shift_branches(audio_nom, align, sec, geo, base, verbose=False):
    """Shift-window sweep for one (geometry, base). Returns
    (branches: label -> frames, evm_deg: {shift: per-carrier mean |res| deg})."""
    sch = m10._d2x_rx_scheme(sec, geo)
    shifts = HANN_SHIFTS if geo == "hann256_skip0" else RECT_SHIFTS
    meta = sec["meta"]
    nom_bits = m10._nominal_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"],
                                                     np.uint8))))
    P = len(sch.data_idx)
    n_pre = m9d._preamble_n(sch.preamble_seconds)
    q_by_shift = {s: [] for s in shifts}
    evm_sum = np.zeros((P, len(shifts)))
    evm_n = np.zeros((P, len(shifts)))
    drift_pred = 0   # per-frame timing drift tracker (issue #26)
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        total = nd + 1
        st_i = int(st) + align + drift_pred
        w_lo = max(0, st_i - pad_lo)
        w_hi = min(len(audio_nom), st_i + flen_full + pad_hi)
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
        drift_pred = m9d._drift_update(
            drift_pred, (w_lo + ds - n_pre) - st_i, y, sch.preamble_seconds)
        y2 = _pll_warp(sch, y, ds, total, alpha=0.7, bw=30.0) \
            if base == "pll30" else None
        for si, s in enumerate(shifts):
            if base == "pll30":
                c, dtau = _shift_pass_pll(sch, y2, ds, total, s)
            else:
                c, dtau = _shift_pass_ema(sch, y, ds, total, 0.7, s)
            q, res = _decide_refine(sch, c, dtau)
            q_by_shift[s].append(q.astype(np.int8))
            evm_sum[:, si] += np.abs(res).sum(axis=0)
            evm_n[:, si] += res.shape[0]
    evm = evm_sum / np.maximum(evm_n, 1)

    def stitch(vec):
        frames = []
        for fi in range(len(q_by_shift[shifts[0]])):
            qs = q_by_shift[vec[0]][fi].copy()
            for j in range(P):
                qs[:, j] = q_by_shift[int(vec[j])][fi][:, j]
            frames.append(np.asarray(sch.quadrants_to_bits(qs.astype(int)),
                                     np.uint8))
        return frames

    branches = {}
    for s in shifts:
        if s == 0:
            continue                       # S0 == a stock-pass geometry
        branches[f"d2xsw_{geo}_{base}_S{s:+d}"] = stitch([s] * P)
    argvec = [shifts[int(np.argmin(evm[j]))] for j in range(P)]
    branches[f"d2xsw_{geo}_{base}_argmin"] = stitch(argvec)
    evm_deg = {str(s): [round(float(np.degrees(evm[j, si])), 2)
                        for j in range(P)]
               for si, s in enumerate(shifts)}
    return branches, {"shifts": list(shifts), "argmin_vec": argvec,
                      "evm_deg_per_carrier": evm_deg}


def _consensus_distance(mat, union_msgs, meta):
    """Truth-free branch quality: mean byte distance of the branch's rows to
    the CRC-accepted consensus messages on PASSING codewords (message bytes
    only -- parity not compared)."""
    k = meta["rs_k"]
    d, n = 0, 0
    for i, msg in enumerate(union_msgs):
        if msg is None:
            continue
        row = mat[i][:k].tobytes()
        d += sum(a != b for a, b in zip(row, msg))
        n += k
    return d / max(1, n)


def x11_rescue_section(audio_nom, sec, align, ledger, stock_row, verbose=True):
    t0 = time.time()
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    n_cw = meta["n_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    k = meta["rs_k"]
    padded = expected_packed + bytes((-len(expected_packed)) % k)
    truth_msgs = [padded[i * k:(i + 1) * k] for i in range(n_cw)]

    union_msgs: list[bytes | None] = [None] * n_cw
    union_src: list[str | None] = [None] * n_cw
    pool: list[tuple[str, np.ndarray]] = []

    # ---- r-a: replicate the stock pass-1 union ---------------------------
    for label, sch_rx, fe in m10._frontends_for(sec):
        rx, _d = m9d._demod_section_frames(audio_nom, sec, align, sch_rx, fe)
        mat = _rx_mat(rx, meta)
        _ok, msgs = m10._per_cw_decode(mat, meta, crc, ledger)
        m10._union_fill(union_msgs, union_src, msgs, label)
        pool.append((label, mat))
    failed_p1 = [i for i in range(n_cw) if union_msgs[i] is None]
    fidelity = (stock_row.get("stock_ladder_targets") is None
                or failed_p1 == stock_row["stock_ladder_targets"])
    if verbose:
        print(f"    [x11 {sec['name']}] pass1 failed={failed_p1} "
              f"fidelity_vs_stock={fidelity}", flush=True)

    # ---- r-b: d2x shift-window sweep (fill-only on failing cw) -----------
    sweep_rec = {}
    rescued_by_sweep = []
    for geo in RESCUE_GEOS:
        for base in RESCUE_BASES:
            still = [i for i in range(n_cw) if union_msgs[i] is None]
            if not still:
                break
            branches, brec = _d2x_shift_branches(audio_nom, align, sec, geo,
                                                 base)
            sweep_rec[f"{geo}_{base}"] = {"argmin_vec": brec["argmin_vec"]}
            for bn, frames in branches.items():
                still = [i for i in range(n_cw) if union_msgs[i] is None]
                if not still:
                    break
                mat = _rx_mat(frames, meta)
                _ok, msgs = m10._per_cw_decode(mat, meta, crc, ledger,
                                               only_cw=still)
                new = m10._union_fill(union_msgs, union_src, msgs, bn)
                if new:
                    rescued_by_sweep += [i for i in still
                                         if union_msgs[i] is not None
                                         and union_src[i] == bn]
                pool.append((bn, mat))
    failed_p2 = [i for i in range(n_cw) if union_msgs[i] is None]
    if verbose:
        print(f"    [x11 {sec['name']}] after sweep failed={failed_p2} "
              f"(sweep filled {len(failed_p1) - len(failed_p2)})", flush=True)

    # ---- r-c: frozen carrier-class erasure ladder over the enlarged pool --
    ladder_rec = None
    rank = disp = None
    if failed_p2:
        rank, disp = m10._rank_carriers(audio_nom, align, sec, verbose=verbose)
        ranked_pool = sorted(
            pool, key=lambda bm: _consensus_distance(bm[1], union_msgs, meta))
        branch_mats = [(bn, mat) for bn, mat in
                       ranked_pool[:m10.N_LADDER_BRANCHES]]
        ladder_rec = m10._erasure_ladder(sec, meta, crc, branch_mats,
                                         union_msgs, union_src, rank, ledger,
                                         verbose=verbose)
    failed_final = [i for i in range(n_cw) if union_msgs[i] is None]

    # ---- audit -------------------------------------------------------------
    assembled = m10._assemble(meta, union_msgs)
    byte_exact = assembled == expected_packed
    misc = sum(1 for i in range(n_cw) if union_msgs[i] is not None
               and union_msgs[i] != truth_msgs[i])
    orig_ok = _orig_audit(sec, assembled)
    rescued = bool(not failed_final and byte_exact and orig_ok)
    rec = {
        "name": sec["name"],
        "stock_failed_idx": stock_row.get("failed_idx"),
        "stock_cw_failed": stock_row["cw_failed"],
        "pass1_failed_idx": failed_p1,
        "pass1_fidelity_vs_stock_targets": bool(fidelity),
        "after_sweep_failed_idx": failed_p2,
        "final_failed_idx": failed_final,
        "cw_failed_final": len(failed_final),
        "byte_exact": bool(byte_exact),
        "orig_exact": bool(orig_ok),
        "miscorrected": int(misc),
        "rescued": rescued,
        "filled_by_sweep": [
            {"cw": i, "source": union_src[i]} for i in range(n_cw)
            if union_src[i] and union_src[i].startswith("d2xsw_")],
        "filled_by_ladder": [
            {"cw": i, "source": union_src[i]} for i in range(n_cw)
            if union_src[i] and union_src[i].startswith("ladder:")],
        "ladder": ladder_rec,
        "carrier_rank_worst_first": rank,
        "carrier_dispersion_deg": disp,
        "sweep_argmin": sweep_rec,
        "elapsed_s": round(time.time() - t0, 1),
    }
    if verbose:
        print(f"    [x11 {sec['name']}] FINAL failed={failed_final} "
              f"rescued={rescued} misc={misc} ({rec['elapsed_s']}s)", flush=True)
    return rec


def stage_rescue(cells: list[str]):
    led = _new_ledger()
    stock = json.loads((RESULTS / "x11_d2x_stock.json").read_text())
    path = RESULTS / "x11_d2x_rescue.json"
    out = (json.loads(path.read_text()) if path.exists()
           else {"experiment": "x11_d2x_erasure rescue",
                 "preregistration": "module docstring item 4 (frozen)",
                 "cells": {}})
    for cid in cells:
        if cid in out["cells"]:
            print(f"[rescue] {cid} already done, skip")
            continue
        cell = stock["cells"].get(cid)
        if cell is None:
            print(f"[rescue] {cid} has no stock record -- run stock first")
            continue
        marg = [r for r in cell["rows"] if r["marginal"]]
        if not marg:
            out["cells"][cid] = {"marginal_sections": 0, "rows": []}
            path.write_text(json.dumps(out, indent=2, default=_jsafe))
            continue
        dg, aac, clk, seed = _parse_cell(cid)
        cap = gen_capture(dg, aac, clk, seed)
        audio_nom, align, mani, _sync = sync_load(cap)
        secs = {s["name"]: s for s in mani["ws_payloads"]}
        rows = []
        for r in marg:
            rec = x11_rescue_section(audio_nom, secs[r["name"]], align, led, r)
            rows.append(rec)
        out["cells"][cid] = {"marginal_sections": len(marg), "rows": rows}
        path.write_text(json.dumps(out, indent=2, default=_jsafe))
        print(f"[rescue] checkpoint {cid}: "
              f"{sum(r['rescued'] for r in rows)}/{len(rows)} rescued", flush=True)
    _merge_ledger("rescue", led)
    return out


# ===========================================================================
# stage: windows -- G3 sensitivity table on marginal sections
# ===========================================================================
def _truth_frames(sec):
    meta = sec["meta"]
    packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                rs_n=meta["rs_n"], rs_k=meta["rs_k"],
                frame_bytes=meta["frame_bytes"])
    tx_frames, meta2 = codec.encode_payload(packed, rung)
    assert meta2["stream_bits"] == meta["stream_bits"]
    return tx_frames


def stage_windows(cells: list[str]):
    led = _new_ledger()
    stock = json.loads((RESULTS / "x11_d2x_stock.json").read_text())
    path = RESULTS / "x11_d2x_windows.json"
    out = (json.loads(path.read_text()) if path.exists()
           else {"experiment": "x11_d2x_erasure windows (G3)",
                 "plans": list(WINDOW_PLAN_LABELS), "base": "ema0.7",
                 "stats": ["evm_mean_deg", "evm_rms_deg", "crc_pass_count"],
                 "truth_metric": "raw BER vs TX frame bits (scoring only)",
                 "cells": {}})
    for cid in cells:
        if cid in out["cells"]:
            continue
        cell = stock["cells"].get(cid)
        if cell is None:
            continue
        marg = [r for r in cell["rows"] if r["marginal"]]
        if not marg:
            out["cells"][cid] = {"rows": []}
            path.write_text(json.dumps(out, indent=2, default=_jsafe))
            continue
        dg, aac, clk, seed = _parse_cell(cid)
        cap = gen_capture(dg, aac, clk, seed)
        audio_nom, align, mani, _sync = sync_load(cap)
        secs = {s["name"]: s for s in mani["ws_payloads"]}
        rows = []
        for r in marg:
            sec = secs[r["name"]]
            meta = sec["meta"]
            tx_frames = _truth_frames(sec)
            nom_bits = m10._nominal_bits(meta)
            pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
            srow = {"name": sec["name"], "plans": {}}
            for (geo, shift), label in zip(WINDOW_PLANS, WINDOW_PLAN_LABELS):
                sch = m10._d2x_rx_scheme(sec, geo)
                flen_full = len(np.asarray(
                    sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
                frames, abssum, absq, nres, nbits_err, nbits = [], 0.0, 0.0, 0, 0, 0
                n_pre = m9d._preamble_n(sch.preamble_seconds)
                drift_pred = 0   # per-frame timing drift tracker (issue #26)
                for fi, st in enumerate(sec["frame_starts"]):
                    nd = sch.nsym_data(nom_bits[fi])
                    st_i = int(st) + align + drift_pred
                    w_lo = max(0, st_i - pad_lo)
                    w_hi = min(len(audio_nom), st_i + flen_full + pad_hi)
                    y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
                    ds = int(hc.find_preamble(y.astype(np.float32),
                                              sch.preamble_seconds))
                    drift_pred = m9d._drift_update(
                        drift_pred, (w_lo + ds - n_pre) - st_i, y,
                        sch.preamble_seconds)
                    c, dtau = _shift_pass_ema(sch, y, ds, nd + 1, 0.7, shift)
                    q, res = _decide_refine(sch, c, dtau)
                    bits = np.asarray(sch.quadrants_to_bits(q), np.uint8)
                    nb = nom_bits[fi]
                    frames.append(bits[:nb])
                    tb = np.asarray(tx_frames[fi], np.uint8)[:nb]
                    nbits_err += int(np.sum(bits[:nb] != tb))
                    nbits += nb
                    abssum += float(np.abs(res).sum())
                    absq += float((res ** 2).sum())
                    nres += res.size
                ok, _msgs = m10._per_cw_decode(_rx_mat(frames, meta), meta,
                                               sec["crc32_codewords"], led)
                srow["plans"][label] = {
                    "ber": round(nbits_err / max(1, nbits), 5),
                    "crc_pass_count": int(np.sum(ok)),
                    "cw_failed": int(np.sum(~ok)),
                    "evm_mean_deg": round(math.degrees(abssum / max(1, nres)), 3),
                    "evm_rms_deg": round(math.degrees(
                        math.sqrt(absq / max(1, nres))), 3)}
            rows.append(srow)
            print(f"[windows {cid}] {sec['name']}: " + " ".join(
                f"{lb}={srow['plans'][lb]['ber']:.4f}/{srow['plans'][lb]['cw_failed']}f"
                for lb in WINDOW_PLAN_LABELS), flush=True)
        out["cells"][cid] = {"rows": rows}
        path.write_text(json.dumps(out, indent=2, default=_jsafe))
    _merge_ledger("windows", led)
    return out


# ===========================================================================
# stage: regress* -- G2 four-capture suite
# ===========================================================================
TAPE9_EXPECT = ["m9_m0_reprove934", "m9_m1_thin159", "m9_m2_thin191",
                "m9_m3_dropnull9c", "m9_m4_n256_rs159", "m9_m4b_n256_rs159_var",
                "m9_m5_n256_rs179", "m9_m6_n256_rs191", "m9_m7_n256_p11_9000",
                "m9_m8_dense375"]


def _merge_regression(key, payload):
    path = RESULTS / "x11_d2x_regression.json"
    data = (json.loads(path.read_text()) if path.exists()
            else {"experiment": "x11_d2x_erasure regression (G2)",
                  "note": "tape9/m8 through the UNCHANGED m10_decode composed "
                          "pipeline (fresh out-tags, fresh sync); tape7/tape4 "
                          "through the UNCHANGED production decoders "
                          "(x10_a_fec_gmd_erasure._run_production)."})
    data[key] = payload
    path.write_text(json.dumps(data, indent=2, default=_jsafe))
    print(f"[regress] wrote {key}", flush=True)


def stage_regress9(sections=None):
    res = m10.decode(str(CAP_DIR / "tape9_run1.wav"),
                     out_tag="x11_regress_tape9",
                     manifest_path="master9_manifest.json",
                     sections=sections, verbose=True)
    ref = json.loads((RESULTS /
                      "x10_m10_results_composed_regression_tape9_run1.json").read_text())
    rows, ok_all = [], True
    for nm in TAPE9_EXPECT + ["m9_m9a_freqdiff"]:
        r = res["payloads_by_name"].get(nm)
        rr = ref["payloads_by_name"].get(nm)
        if r is None or rr is None:
            continue
        if nm == "m9_m9a_freqdiff":
            ok = (r.get("rs_codewords_failed") == rr.get("rs_codewords_failed")
                  == 37)
        else:
            ok = (bool(r.get("orig_byte_exact")) and r.get("rs_codewords_failed") == 0
                  and r.get("miscorrected_cw", 0) == 0
                  and bool(rr.get("orig_byte_exact")) == bool(r.get("orig_byte_exact")))
        ok_all &= ok
        rows.append({"name": nm, "cw_failed": r.get("rs_codewords_failed"),
                     "orig_exact": r.get("orig_byte_exact"),
                     "miscorrected": r.get("miscorrected_cw"),
                     "matches_reference": bool(ok)})
    _merge_regression("tape9_run1", {"rows": rows, "all_match": bool(ok_all),
                                     "fa_bound": res.get("false_accept_bound")})
    return ok_all


def stage_regressm8():
    res = m10.decode(str(CAP_DIR / "m8_tape_mono_lossless.wav"),
                     out_tag="x11_regress_m8",
                     manifest_path="master8_manifest.json",
                     sections=["m8_dq_p10n512_rs127"], verbose=True)
    r = res["payloads_by_name"]["m8_dq_p10n512_rs127"]
    ok = (r.get("rs_codewords_failed") == 0 and bool(r.get("orig_byte_exact"))
          and r.get("miscorrected_cw", 0) == 0)
    _merge_regression("m8_tape_mono_lossless",
                      {"rows": [{"name": "m8_dq_p10n512_rs127",
                                 "cw_failed": r.get("rs_codewords_failed"),
                                 "orig_exact": r.get("orig_byte_exact"),
                                 "miscorrected": r.get("miscorrected_cw"),
                                 "matches_reference": bool(ok)}],
                       "all_match": bool(ok)})
    return ok


def stage_regress7():
    rows = _run_production("m7_decode", str(CAP_DIR / "tape7_run1.wav"),
                           {"m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k"})
    ref = json.loads((RESULTS / "x10_gmd_erasure_regression.json").read_text())
    refrows = {r["name"]: r for r in ref["tape7_run1"]}
    ok_all = all(bool(r["byte_exact"]) == bool(refrows[r["name"]]["byte_exact"])
                 and r["rs_codewords_failed"] == refrows[r["name"]]["rs_codewords_failed"]
                 for r in rows)
    _merge_regression("tape7_run1", {"rows": rows, "all_match": bool(ok_all)})
    return ok_all


def stage_regress4():
    rows = _run_production("m4_decode", str(CAP_DIR / "tape4_run1.wav"),
                           {"ws_test2k", "ws_llm24k"})
    ref = json.loads((RESULTS / "x10_gmd_erasure_regression.json").read_text())
    refrows = {r["name"]: r for r in ref["tape4_run1"]}
    ok_all = all(bool(r["byte_exact"]) == bool(refrows[r["name"]]["byte_exact"])
                 and r["rs_codewords_failed"] == refrows[r["name"]]["rs_codewords_failed"]
                 for r in rows)
    _merge_regression("tape4_run1", {"rows": rows, "all_match": bool(ok_all)})
    return ok_all


# ===========================================================================
# stage: report -- the gate rollup
# ===========================================================================
def stage_report():
    out = {"experiment": "x11_d2x_erasure GATE REPORT",
           "amendments": ["results/x11_d2x_amendment_a1.json -- marginal-"
                          "inventory extension (dg 0.38/0.37 cliff refinement),"
                          " recorded truth-blind BEFORE any rescue ran; G1 "
                          "thresholds unchanged"],
           "gate": {"G1": None, "G2": None, "G3": None}}
    stock = json.loads((RESULTS / "x11_d2x_stock.json").read_text())
    resc = json.loads((RESULTS / "x11_d2x_rescue.json").read_text())
    # ---- G1 ----
    marg, resc_rows = [], []
    axes = {"aac": set(), "clk": set()}
    for cid, cell in stock["cells"].items():
        for r in cell["rows"]:
            if r["marginal"]:
                marg.append((cid, r["name"], r["cw_failed"]))
                axes["aac"].add(cell["aac"])
                axes["clk"].add(cell["clk_pct"])
    for cid, cell in resc["cells"].items():
        for r in cell.get("rows", []):
            resc_rows.append((cid, r["name"], r["rescued"], r["miscorrected"],
                              len(r["filled_by_sweep"]),
                              len(r["filled_by_ladder"]),
                              r["stock_cw_failed"], r["cw_failed_final"]))
    n_marg = len(marg)
    n_resc = sum(1 for x in resc_rows if x[2])
    misc_total = sum(x[3] for x in resc_rows)
    stock_misc = sum(r["miscorrected"] for c in stock["cells"].values()
                     for r in c["rows"])
    led = json.loads(LEDGER_PATH.read_text())
    g1 = {"n_marginal_sections": n_marg,
          "n_rescue_attempted": len(resc_rows),
          "n_rescued_full": n_resc,
          "rescue_rate": round(n_resc / max(1, len(resc_rows)), 3),
          "marginal_axes_covered": {"aac": sorted(axes["aac"]),
                                    "clk_pct": sorted(axes["clk"])},
          "miscorrected_total": misc_total + stock_misc,
          "ledger": led["total"],
          "false_accept_bound": led["false_accept_bound"],
          "fa_within_budget": led["fa_within_budget"],
          "pass": bool(n_marg >= 20 and len(resc_rows) >= n_marg
                       and n_resc / max(1, len(resc_rows)) >= 0.30
                       and misc_total + stock_misc == 0
                       and led["fa_within_budget"])}
    out["gate"]["G1"] = g1
    out["g1_marginal_sections"] = [
        {"cell": c, "section": s, "stock_cw_failed": f} for c, s, f in marg]
    out["g1_rescue_rows"] = [
        {"cell": c, "section": s, "rescued": rr, "misc": m,
         "filled_sweep": fs, "filled_ladder": fl, "stock_failed": sf,
         "final_failed": ff}
        for c, s, rr, m, fs, fl, sf, ff in resc_rows]
    # ---- G2 ----
    try:
        reg = json.loads((RESULTS / "x11_d2x_regression.json").read_text())
        g2_ok = all(reg.get(k, {}).get("all_match") for k in
                    ("tape9_run1", "m8_tape_mono_lossless", "tape7_run1",
                     "tape4_run1"))
        out["gate"]["G2"] = {"pass": bool(g2_ok),
                             "detail": {k: reg.get(k, {}).get("all_match")
                                        for k in ("tape9_run1",
                                                  "m8_tape_mono_lossless",
                                                  "tape7_run1", "tape4_run1")}}
    except FileNotFoundError:
        out["gate"]["G2"] = {"pass": False, "detail": "regression not run"}
    # ---- G3 ----
    try:
        win = json.loads((RESULTS / "x11_d2x_windows.json").read_text())
        rows = [r for c in win["cells"].values() for r in c.get("rows", [])]
        stats = ("evm_mean_deg", "evm_rms_deg", "crc_pass_count")
        agree = {s: 0 for s in stats}
        spear = {s: [] for s in stats}
        for r in rows:
            plans = r["plans"]
            bers = np.array([plans[lb]["ber"] for lb in WINDOW_PLAN_LABELS])
            best_true = int(np.argmin(bers))
            for s in stats:
                v = np.array([plans[lb][s] for lb in WINDOW_PLAN_LABELS],
                             float)
                pick = int(np.argmax(v)) if s == "crc_pass_count" \
                    else int(np.argmin(v))
                agree[s] += int(pick == best_true)
                sgn = -1.0 if s == "crc_pass_count" else 1.0
                a = np.argsort(np.argsort(bers))
                b = np.argsort(np.argsort(sgn * v))
                n = len(a)
                rho = 1 - 6 * float(np.sum((a - b) ** 2)) / (n * (n * n - 1))
                spear[s].append(rho)
        nrows = max(1, len(rows))
        g3 = {"n_sections": len(rows),
              "top1_agreement": {s: round(agree[s] / nrows, 3) for s in stats},
              "spearman_vs_ber_mean": {s: round(float(np.mean(spear[s])), 3)
                                       for s in stats if spear[s]},
              "plan_mean_ber": {
                  lb: round(float(np.mean([r["plans"][lb]["ber"]
                                           for r in rows])), 5)
                  for lb in WINDOW_PLAN_LABELS} if rows else {},
              "plan_mean_cw_failed": {
                  lb: round(float(np.mean([r["plans"][lb]["cw_failed"]
                                           for r in rows])), 2)
                  for lb in WINDOW_PLAN_LABELS} if rows else {}}
        if rows:
            g3["best_stat_by_top1"] = max(stats, key=lambda s: agree[s])
        g3["pass"] = bool(len(rows) >= 10)
        out["gate"]["G3"] = g3
    except FileNotFoundError:
        out["gate"]["G3"] = {"pass": False, "detail": "windows not run"}
    out["gate_met"] = bool(all(out["gate"][g] and out["gate"][g].get("pass")
                               for g in ("G1", "G2", "G3")))
    (RESULTS / "x11_d2x_gate_report.json").write_text(
        json.dumps(out, indent=2, default=_jsafe))
    print(json.dumps({"G1": out['gate']['G1'].get('pass'),
                      "G1_rescue_rate": out['gate']['G1'].get('rescue_rate'),
                      "G1_n_marginal": out['gate']['G1'].get('n_marginal_sections'),
                      "G2": out['gate']['G2'].get('pass'),
                      "G3": out['gate']['G3'].get('pass'),
                      "gate_met": out["gate_met"]}, indent=1))
    return out


def _jsafe(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    ap.add_argument("--cell", action="append", default=[])
    ap.add_argument("--part", default=None)
    ap.add_argument("--sections", default="")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.stage == "build":
        stage_build()
    elif args.stage == "selfcheck":
        stage_selfcheck()
    elif args.stage == "screen":
        stage_screen(args.part)
    elif args.stage == "stock":
        stage_stock(args.cell)
    elif args.stage == "rescue":
        stage_rescue(args.cell)
    elif args.stage == "windows":
        stage_windows(args.cell)
    elif args.stage == "regress9":
        stage_regress9([s for s in args.sections.split(",") if s] or None)
    elif args.stage == "regressm8":
        stage_regressm8()
    elif args.stage == "regress7":
        stage_regress7()
    elif args.stage == "regress4":
        stage_regress4()
    elif args.stage == "report":
        stage_report()
    elif args.stage == "cells":
        screen = json.loads((RESULTS / "x11_d2x_screen.json").read_text())
        for c in stock_cells(screen["dg_star"]):
            print(cell_id(*c))
    else:
        raise SystemExit(f"unknown stage {args.stage}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
