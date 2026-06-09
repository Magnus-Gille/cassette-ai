"""h2_erasure_decode.py -- HYPOTHESIS H2: errors-and-erasures RS decoding.

RS(255,k) corrects t=(255-k)/2 unknown-position byte errors, but e errors +
f erasures whenever 2e+f <= 255-k. The WS contrast detector's per-symbol lock
score (winner-vs-runner-up margin at the chosen timing offset) is a natural
reliability signal: flag the least-reliable symbols' bytes as erasures and
RS can correct codewords that fail plain errors-only decoding.

Two stages (demod once, iterate decode on the cache -- DISCIPLINE rule):

  Stage 1 (slow, once): replicate m7_decode/m6_decode._decode_section demod on
    captures/tape7_run1.wav EXACTLY (same ws_build geometry, same EQ-from-sounder,
    same +/-15-sample concentration-lock tracker, same fixed nsym per frame),
    but additionally record per symbol: lock score, unnormalized score gap,
    chosen timing offset, chosen symbol index. Cache -> results/h2_demod_cache.npz.
    Honesty check: recomputed raw_ber per section must match
    results/m7_results_tape7_run1.json to ~1e-12.

  Stage 2 (fast, cached): map symbol reliabilities through the byte stream /
    global column-interleave to per-(codeword,position) reliabilities, then
    sweep FIXED erasure-flagging policies (same rule for every codeword of
    every rung; the decoder never sees the true payload) and decode with
    reedsolo errors-and-erasures (RSCodec(nsym).decode(..., erase_pos=...)).
    Truth (sidecar payloads) is used ONLY for final scoring + the raw_ber /
    baseline parity sanity checks, never for flagging.

Policies swept (all fixed rules):
  frac:f      per codeword erase the F = round(f * (rs_n-rs_k)) least-reliable
              byte positions, f in {0, .25, .5, .75, 1.0}
  pct:q       global threshold at the q-th percentile of the RUNG's own byte
              reliability distribution (received data only); cap at rs_n-rs_k
              least-reliable per codeword
  x metric in {lock, gap} x byte aggregation over contributing symbols in
  {min, mean} (M32 has 1 symbol/byte so min==mean there).

Usage:
    python3 experiments/tape_v2/h2_erasure_decode.py            # both stages
    python3 experiments/tape_v2/h2_erasure_decode.py --decode-only   # stage 2 from cache

Output: results/h2_erasure_results.json, log results/h2_erasure_decode.log
Seed: none needed (decode path is deterministic); SEED=2026 logged for parity.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2  # noqa: E402
import hyp_common as hc  # noqa: E402
import m3_codec as codec  # noqa: E402
from assault_widespace import _energies_at, _score, _sym_from_score, build as ws_build  # noqa: E402
from m3_codec import Rung  # noqa: E402
from reedsolo import RSCodec, ReedSolomonError  # noqa: E402

SR = codec.FS
SEED = 2026  # logged; the pipeline is deterministic
MANIFEST_PATH = _HERE / "master7_manifest.json"
RESULTS_DIR = _HERE / "results"
CACHE_PATH = RESULTS_DIR / "h2_demod_cache.npz"
LOG_PATH = RESULTS_DIR / "h2_erasure_decode.log"
RESULTS_PATH = RESULTS_DIR / "h2_erasure_results.json"
REF_RESULTS_PATH = RESULTS_DIR / "m7_results_tape7_run1.json"
CAPTURE = ROOT / "experiments" / "tape_v2" / "captures" / "tape7_run1.wav"
WS_WINDOW_PAD = 0.30  # identical to m6_decode

PASSING_RUNGS = ("m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k")
GATE_RUNG = "m16_rs223_8k"

_log_fh = None


def log(msg: str, echo: bool = True):
    global _log_fh
    if _log_fh is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        _log_fh = open(LOG_PATH, "a")
        _log_fh.write(f"\n===== h2_erasure_decode run {time.strftime('%F %T')} =====\n")
    _log_fh.write(msg + "\n")
    _log_fh.flush()
    if echo:
        print(msg)


# ---------------------------------------------------------------------------
# m6_decode parity helpers (copied verbatim semantics; m6_decode is not edited)
# ---------------------------------------------------------------------------
def _ws_eq_from_sounder(ws, sounder: dict) -> np.ndarray:
    sf_freqs = np.asarray(sounder.get("sounder_freqs", []), dtype=np.float64)
    H_db = np.asarray(sounder.get("H_db", []), dtype=np.float64)
    if len(sf_freqs) < 2:
        return np.ones(ws.M)
    Hlin = 10.0 ** (np.interp(ws.freqs, sf_freqs, H_db) / 20.0)
    Hlin = Hlin / (Hlin.max() + 1e-12)
    return np.clip(Hlin, 0.05, None)


def _demod_frame_instrumented(scheme, eq, y_frame, nsym, detector, track=15):
    """assault_widespace._demod_frame_achievable with per-symbol instrumentation.

    Identical numerics / decision path; additionally returns per symbol:
      lock  -- the tracker's concentration-lock score of the CHOSEN decode
               (srt[K-1]-srt[K]) / (|srt[0]| + 1e-9)   (winner-vs-runner-up margin)
      gap   -- unnormalized winner-vs-runner-up margin srt[K-1]-srt[K]
      dsel  -- chosen timing offset, sym -- chosen symbol index
    """
    N = scheme.N
    bps = scheme.bits_per_sym
    tone_bins = np.clip(scheme._bin_indices, 0, N // 2)
    guard_bins = scheme._guard_bins
    ds = hc.find_preamble(y_frame.astype(np.float32), scheme.preamble_seconds)
    yy = y_frame.astype(np.float64)
    drift = 0.0
    out = []
    locks = np.full(nsym, -np.inf)
    gaps = np.full(nsym, -np.inf)
    dsels = np.zeros(nsym, np.int16)
    syms = np.zeros(nsym, np.int32)
    for sidx in range(nsym):
        base = ds + sidx * N + int(round(drift))
        best = None
        for d in range(-track, track + 1):
            et, eg = _energies_at(yy, base + d, N, tone_bins, guard_bins)
            if et is None:
                continue
            sc = _score(et, eg, eq, detector)
            si = _sym_from_score(scheme, sc)
            srt = np.sort(sc)[::-1]
            lock = (srt[scheme.K - 1] - srt[scheme.K]) / (abs(srt[0]) + 1e-9)
            if best is None or lock > best[0]:
                best = (lock, si, d, srt[scheme.K - 1] - srt[scheme.K])
        if best is None:
            out.extend([0] * bps)
            continue
        out.extend(scheme._sym_to_bits(best[1]))
        drift += best[2]
        locks[sidx] = best[0]
        gaps[sidx] = best[3]
        dsels[sidx] = best[2]
        syms[sidx] = best[1]
    return np.array(out, dtype=np.uint8), locks, gaps, dsels, syms


def demod_all(recording_path: pathlib.Path) -> dict:
    """Stage 1: demod every section of every rung ONCE; cache + sanity-check."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    log(f"[demod] loading {recording_path} ...")
    t0 = time.time()
    audio, sr = sf.read(str(recording_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    log(f"[demod] sync clock {sync['speed']:.6f}x align {align:+d} "
        f"flutter {sounder['flutter_wrms_pct']:.2f}% SNRmed {sounder['snr_db_median']:.1f} dB "
        f"({time.time()-t0:.0f}s)")

    cache: dict[str, np.ndarray] = {}
    section_info = []
    for sec in manifest["ws_payloads"]:
        ts = time.time()
        name = sec["name"]
        phy = sec["phy_params"]
        ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
        assert ws is not None, name
        eq = _ws_eq_from_sounder(ws, sounder)
        meta = sec["meta"]
        rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                    rs_n=meta["rs_n"], rs_k=meta["rs_k"],
                    frame_bytes=meta["frame_bytes"])
        expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        frames_bits_ref, _ = codec.encode_payload(expected, rung)

        nsym = meta["frame_bits"] // ws.bits_per_sym  # m6 parity: fixed per section
        test_audio = np.asarray(ws.modulate(np.zeros(meta["frame_bits"], np.uint8)), np.float32)
        flen = len(test_audio)
        pad = int(WS_WINDOW_PAD * SR)

        n_frames = meta["n_frames"]
        bits_mat = np.zeros((n_frames, nsym * ws.bits_per_sym), np.uint8)
        lock_mat = np.zeros((n_frames, nsym), np.float64)
        gap_mat = np.zeros((n_frames, nsym), np.float64)
        dsel_mat = np.zeros((n_frames, nsym), np.int16)
        raw_err = 0
        raw_tot = 0
        for fi, start in enumerate(sec["frame_starts"]):
            st = int(start) + align
            lo = max(0, st - pad)
            hi = min(len(audio_nom), st + flen + pad)
            window = np.asarray(audio_nom[lo:hi], dtype=np.float32)
            rb, locks, gaps, dsels, _syms = _demod_frame_instrumented(
                ws, eq, window, nsym, "contrast")
            tb = frames_bits_ref[fi].astype(np.uint8)
            m = min(len(tb), len(rb))
            raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
            raw_tot += len(tb)
            bits_mat[fi, :len(rb)] = rb
            lock_mat[fi] = locks
            gap_mat[fi] = gaps
            dsel_mat[fi] = dsels
        raw_ber = raw_err / max(1, raw_tot)
        cache[f"{name}__bits"] = bits_mat
        cache[f"{name}__lock"] = lock_mat
        cache[f"{name}__gap"] = gap_mat
        cache[f"{name}__dsel"] = dsel_mat
        cache[f"{name}__raw_ber"] = np.float64(raw_ber)
        section_info.append({"name": name, "raw_ber": raw_ber,
                             "bits_per_sym": ws.bits_per_sym, "nsym": nsym})
        log(f"[demod] {name:<14} {ws.name:<19} frames={n_frames:3d} "
            f"rawBER={raw_ber:.6f}  ({time.time()-ts:.0f}s)")

    np.savez_compressed(CACHE_PATH, **cache)
    log(f"[demod] cache -> {CACHE_PATH} ({CACHE_PATH.stat().st_size/1e6:.1f} MB, "
        f"total {time.time()-t0:.0f}s)")

    # honesty check: recomputed rawBER must match the ground-truth m7 results
    ref = json.loads(REF_RESULTS_PATH.read_text())
    ref_ber = {p["name"]: p["raw_ber"] for p in ref["payloads"]}
    ok = True
    for si in section_info:
        d = abs(si["raw_ber"] - ref_ber[si["name"]])
        tag = "OK" if d < 1e-12 else "MISMATCH"
        if d >= 1e-12:
            ok = False
        log(f"[parity] {si['name']:<14} rawBER recomputed {si['raw_ber']:.8f} "
            f"vs m7 {ref_ber[si['name']]:.8f}  d={d:.2e}  {tag}")
    if not ok:
        log("[parity] WARNING: demod does not reproduce m7_decode exactly!")
    return cache


# ---------------------------------------------------------------------------
# Stage 2: cached decode sweep
# ---------------------------------------------------------------------------
def _stream_bytes_and_rel(bits_mat, rel_mat, meta, bps, agg):
    """Replicate m3_codec.decode_payload stream reassembly, carrying per-byte
    reliability = agg(contributing symbols' reliabilities)."""
    fb_bits = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]
    pieces, rpieces = [], []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else (stream_bits - fb_bits * (n_frames - 1))
        rb = bits_mat[fi].ravel()
        rr = np.repeat(rel_mat[fi], bps)  # per-bit reliability
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
            rr = np.concatenate([rr, np.full(nominal - len(rr), -np.inf)])
        pieces.append(rb[:nominal])
        rpieces.append(rr[:nominal])
    rx_bits = np.concatenate(pieces)[:stream_bits]
    rel_bits = np.concatenate(rpieces)[:stream_bits]
    n_cw, rs_n = meta["n_codewords"], meta["rs_n"]
    rx_bytes = np.packbits(rx_bits)[:n_cw * rs_n]
    rel_by_bit = rel_bits[:n_cw * rs_n * 8].reshape(-1, 8)
    rel_bytes = rel_by_bit.min(axis=1) if agg == "min" else rel_by_bit.mean(axis=1)
    # de-interleave (column-major): stream byte p -> codeword p % n_cw, pos p // n_cw
    rx_mat = rx_bytes.reshape(rs_n, n_cw).T
    rel_mat_cw = rel_bytes.reshape(rs_n, n_cw).T
    return rx_mat, rel_mat_cw


def _decode_with_erasures(rx_mat, rel_cw, meta, expected, erase_fn):
    """Decode all codewords with erase positions from erase_fn(rel_row, meta).
    Returns stats. Truth (`expected`) used ONLY for scoring."""
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    recovered = bytearray()
    cw_failed = 0
    n_erase_tot = 0
    for i in range(n_cw):
        epos = erase_fn(rel_cw[i])
        n_erase_tot += len(epos)
        try:
            if epos:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()), erase_pos=epos)[0]
            else:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()))[0]
            recovered += bytes(dec)
        except (ReedSolomonError, Exception):
            cw_failed += 1
            recovered += bytes(rs_k)
    out = bytes(recovered)[:meta["payload_len"]]
    byte_errors = sum(a != b for a, b in zip(out, expected)) + abs(len(out) - len(expected))
    return {
        "cw_failed": cw_failed,
        "byte_errors": int(byte_errors),
        "byte_exact": out == expected,
        "mean_erasures_per_cw": n_erase_tot / n_cw,
    }


def _selftest_erase_pos():
    """Verify reedsolo errors-and-erasures semantics before relying on it."""
    rsc = RSCodec(64)  # t=32, 2e+f<=64
    rng = np.random.default_rng(SEED)
    msg = bytes(rng.integers(0, 256, 191, dtype=np.uint8))
    cw = bytearray(rsc.encode(msg))
    # 40 erasures (>t) + 10 unknown errors: 2*10+40=60 <= 64 -> must decode
    pos = rng.choice(255, size=50, replace=False)
    epos = sorted(int(p) for p in pos[:40])
    for p in pos:
        cw[int(p)] ^= 0xA5
    dec = rsc.decode(cw, erase_pos=epos)[0]
    assert bytes(dec) == msg, "reedsolo erase_pos self-test FAILED"
    log("[selftest] reedsolo 40 erasures + 10 errors over RS(255,191): OK "
        "(2e+f=60 <= 64 corrected)")


def decode_sweep(cache) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    ref = json.loads(REF_RESULTS_PATH.read_text())
    ref_by_name = {p["name"]: p for p in ref["payloads"]}
    _selftest_erase_pos()

    # build per-rung decode inputs for each (metric, agg)
    rungs = []
    for sec in manifest["ws_payloads"]:
        name = sec["name"]
        meta = sec["meta"]
        phy = sec["phy_params"]
        bps = {16: 4, 32: 8}[phy["M"]] if phy["K"] in (1, 2) else None
        ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
        bps = ws.bits_per_sym
        expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        bits_mat = cache[f"{name}__bits"]
        inputs = {}
        for metric in ("lock", "gap"):
            rel = cache[f"{name}__{metric}"]
            for agg in ("min", "mean"):
                rx_mat, rel_cw = _stream_bytes_and_rel(bits_mat, rel, meta, bps, agg)
                inputs[(metric, agg)] = (rx_mat, rel_cw)
        rungs.append({"sec": sec, "meta": meta, "expected": expected, "inputs": inputs})

    # baseline parity: errors-only decode must reproduce m7 results exactly
    log("\n[baseline] errors-only decode parity vs m7_results_tape7_run1.json")
    baseline = {}
    parity_ok = True
    for r in rungs:
        name = r["sec"]["name"]
        rx_mat, _ = r["inputs"][("lock", "min")]
        st = _decode_with_erasures(rx_mat, np.zeros_like(rx_mat, float), r["meta"],
                                   r["expected"], lambda rel: [])
        refp = ref_by_name[name]
        match = (st["cw_failed"] == refp["rs_codewords_failed"]
                 and st["byte_errors"] == refp["byte_errors"]
                 and st["byte_exact"] == refp["byte_exact"])
        parity_ok &= match
        baseline[name] = st
        log(f"  {name:<14} cwFail {st['cw_failed']:>2}/{r['meta']['n_codewords']:<3} "
            f"byteErr {st['byte_errors']:>5} exact={st['byte_exact']!s:<5} "
            f"{'OK' if match else 'MISMATCH vs ref ' + str((refp['rs_codewords_failed'], refp['byte_errors']))}")
    if not parity_ok:
        log("[baseline] WARNING: baseline does not reproduce m7 ground truth!")

    # ---- the policy sweep (fixed rules only) ----
    def make_erase_fn(kind, param, meta, rel_all=None):
        twot = meta["rs_n"] - meta["rs_k"]
        if kind == "frac":
            F = int(round(param * twot))
            if F == 0:
                return lambda rel: []
            return lambda rel: sorted(int(i) for i in np.argsort(rel)[:F])
        if kind == "pct":
            tau = np.percentile(rel_all, param)
            def fn(rel, tau=tau, twot=twot):
                idx = np.where(rel < tau)[0]
                if len(idx) > twot:
                    idx = idx[np.argsort(rel[idx])][:twot]
                return sorted(int(i) for i in idx)
            return fn
        raise ValueError(kind)

    policies = []
    for metric in ("lock", "gap"):
        for agg in ("min", "mean"):
            for f in (0.25, 0.5, 0.75, 1.0):
                policies.append({"kind": "frac", "param": f, "metric": metric, "agg": agg})
            for q in (2, 5, 10, 15, 20, 25, 30):
                policies.append({"kind": "pct", "param": q, "metric": metric, "agg": agg})

    log(f"\n[sweep] {len(policies)} fixed policies x {len(rungs)} rungs")
    sweep_rows = []
    for pol in policies:
        per_rung = {}
        for r in rungs:
            name = r["sec"]["name"]
            meta = r["meta"]
            rx_mat, rel_cw = r["inputs"][(pol["metric"], pol["agg"])]
            rel_all = rel_cw.ravel()
            efn = make_erase_fn(pol["kind"], pol["param"], meta, rel_all)
            st = _decode_with_erasures(rx_mat, rel_cw, meta, r["expected"], efn)
            per_rung[name] = st
        passing_intact = all(per_rung[n]["byte_exact"] for n in PASSING_RUNGS)
        n_exact = sum(per_rung[n]["byte_exact"] for n in per_rung)
        tot_fail = sum(per_rung[n]["cw_failed"] for n in per_rung)
        tot_byte_err = sum(per_rung[n]["byte_errors"] for n in per_rung)
        pol_id = f"{pol['kind']}:{pol['param']}|{pol['metric']}|{pol['agg']}"
        sweep_rows.append({"policy": pol_id, **pol, "per_rung": per_rung,
                           "passing_intact": passing_intact, "n_exact": n_exact,
                           "total_cw_failed": tot_fail, "total_byte_errors": tot_byte_err,
                           "gate_rung_exact": per_rung[GATE_RUNG]["byte_exact"]})
        marks = " ".join(
            f"{n.split('_')[0][1:]}r{n.split('rs')[1].split('_')[0]}:"
            f"{per_rung[n]['cw_failed']}{'*' if per_rung[n]['byte_exact'] else ''}"
            for n in per_rung)
        log(f"  {pol_id:<24} exact={n_exact}/9 cwFail={tot_fail:>3} "
            f"passOK={'Y' if passing_intact else 'n'} | {marks}", echo=False)

    # pick the single best FIXED policy: passing rungs intact first, then most
    # byte-exact rungs, then fewest failed codewords, then fewest byte errors.
    sweep_rows.sort(key=lambda r: (not r["passing_intact"], -r["n_exact"],
                                   r["total_cw_failed"], r["total_byte_errors"]))
    best = sweep_rows[0]
    log(f"\n[best fixed policy] {best['policy']}  "
        f"(exact {best['n_exact']}/9, total cwFail {best['total_cw_failed']}, "
        f"passing intact: {best['passing_intact']})")
    log(f"  {'rung':<14} {'cwFail before':>13} {'after':>6} {'byteErr before':>15} "
        f"{'after':>6} {'exact before':>13} {'after':>6} {'mean erasures':>14}")
    per_rung_out = {}
    for r in rungs:
        name = r["sec"]["name"]
        refp = ref_by_name[name]
        st = best["per_rung"][name]
        per_rung_out[name] = {
            "cw_failed_before": refp["rs_codewords_failed"],
            "cw_failed_after": st["cw_failed"],
            "byte_errors_before": refp["byte_errors"],
            "byte_errors_after": st["byte_errors"],
            "byte_exact_before": refp["byte_exact"],
            "byte_exact_after": st["byte_exact"],
            "mean_erasures_per_cw": st["mean_erasures_per_cw"],
            "n_codewords": r["meta"]["n_codewords"],
            "raw_ber": refp["raw_ber"],
            "projected_net_bps": refp["projected_net_bps"],
            "policy": best["policy"],
        }
        o = per_rung_out[name]
        log(f"  {name:<14} {o['cw_failed_before']:>13} {o['cw_failed_after']:>6} "
            f"{o['byte_errors_before']:>15} {o['byte_errors_after']:>6} "
            f"{o['byte_exact_before']!s:>13} {o['byte_exact_after']!s:>6} "
            f"{o['mean_erasures_per_cw']:>14.1f}")

    # gate evaluation (pre-registered)
    failed_rungs = [n for n in per_rung_out if not per_rung_out[n]["byte_exact_before"]]
    flips = [n for n in failed_rungs if per_rung_out[n]["byte_exact_after"]]
    cw_before = sum(per_rung_out[n]["cw_failed_before"] for n in per_rung_out)
    cw_after = sum(per_rung_out[n]["cw_failed_after"] for n in per_rung_out)
    passing_intact = all(per_rung_out[n]["byte_exact_after"] for n in PASSING_RUNGS)
    gate_exact = per_rung_out[GATE_RUNG]["byte_exact_after"]
    if gate_exact and passing_intact:
        verdict = "PASS"
    elif passing_intact and (flips or (cw_before and (cw_before - cw_after) / cw_before >= 0.5)):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    log(f"\n[gate] m16_rs223 exact after: {gate_exact}; passing intact: {passing_intact}; "
        f"flipped rungs: {flips or 'none'}; total cwFail {cw_before} -> {cw_after} "
        f"({(cw_before-cw_after)/max(1,cw_before)*100:.0f}% drop)")
    log(f"[gate] VERDICT: {verdict}")

    # also report best-per-rung among passing-intact policies (diagnostic, NOT the
    # headline -- the headline is the single fixed policy above)
    diag = {}
    for r in rungs:
        name = r["sec"]["name"]
        cand = min((row for row in sweep_rows if row["passing_intact"]),
                   key=lambda row: (not row["per_rung"][name]["byte_exact"],
                                    row["per_rung"][name]["cw_failed"],
                                    row["per_rung"][name]["byte_errors"]))
        diag[name] = {"policy": cand["policy"],
                      "cw_failed": cand["per_rung"][name]["cw_failed"],
                      "byte_exact": cand["per_rung"][name]["byte_exact"],
                      "byte_errors": cand["per_rung"][name]["byte_errors"]}
    log("\n[diagnostic] best passing-intact policy per rung (not the headline):")
    for n, d in diag.items():
        log(f"  {n:<14} {d['policy']:<24} cwFail {d['cw_failed']:>2} "
            f"exact={d['byte_exact']}")

    out = {
        "hypothesis": "H2 errors-and-erasures RS decoding",
        "recording": str(CAPTURE),
        "seed": SEED,
        "reference_results": str(REF_RESULTS_PATH),
        "baseline_parity_ok": bool(parity_ok),
        "best_fixed_policy": best["policy"],
        "per_rung": per_rung_out,
        "gate": {
            "m16_rs223_exact_after": bool(gate_exact),
            "passing_rungs_intact": bool(passing_intact),
            "flipped_rungs": flips,
            "total_cw_failed_before": cw_before,
            "total_cw_failed_after": cw_after,
            "verdict": verdict,
        },
        "diagnostic_best_per_rung": diag,
        "n_policies_swept": len(policies),
        "all_policies_summary": [
            {k: row[k] for k in ("policy", "n_exact", "total_cw_failed",
                                 "passing_intact", "gate_rung_exact")}
            for row in sweep_rows
        ],
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, default=float))
    log(f"\n[done] wrote {RESULTS_PATH}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decode-only", action="store_true",
                    help="skip demod, use results/h2_demod_cache.npz")
    ap.add_argument("--recording", default=str(CAPTURE))
    args = ap.parse_args()
    log(f"[h2] seed={SEED} recording={args.recording} decode_only={args.decode_only}")
    if args.decode_only and CACHE_PATH.exists():
        cache = dict(np.load(CACHE_PATH))
        log(f"[h2] loaded cache {CACHE_PATH}")
    else:
        cache = demod_all(pathlib.Path(args.recording))
    decode_sweep(cache)


if __name__ == "__main__":
    main()
