"""h6_combo_decode.py -- HYPOTHESIS H6: stack the two real-capture wins.

H5's timing-trajectory front-end (loop bw 0.25 Hz, traj=timing -- improves the
demod margins on every rung of captures/tape7_run1.wav) feeding H2's
errors-and-erasures RS decoding (contrast-margin reliability -> half-price
corrections). Each alone got m16_rs223 from 9 failed codewords down to 5 (H5)
or 6 (H2); together the better margins should ALSO make the reliability signal
cleaner, so the combo may rescue rungs neither could alone.

Method (all cached inputs come from the already-validated H5 run):
  1. Load H5's stage-1 sync cache (audio_nominal + sounder) and stage-2 pass-1
     demod cache (per-frame greedy-tracker offset sequences d, preamble ds).
     Both were produced by h5_pll_decode.py whose pass-1 demod reproduced the
     m7 ground truth (results/m7_results_tape7_run1.json) bit-exactly.
  2. Steered re-demod: tau = build_tau_timing(d_row, fs_sym, BW=0.25) exactly
     as H5's winning configuration, same +/-15 max-lock search -- but
     instrumented to ALSO record per symbol the H2-style reliability signals:
       lock = (srt[K-1]-srt[K]) / (|srt[0]|+1e-9)   (normalized contrast margin)
       gap  =  srt[K-1]-srt[K]                      (unnormalized margin)
     Cached -> results/h6_demod_cache_<tag>.npz.
  3. CONTROL (harness sanity rule): errors-only decode of the steered bits via
     the H2 decode path must reproduce H5's published per-rung numbers
     (results/h5_pll_results_timing.json, *_after) exactly.
  4. Policy sweep: the SAME fixed-policy grid as H2 (frac:{.25,.5,.75,1} +
     pct:{2,5,10,15,20,25,30}, metric {lock,gap} x byte-agg {min,mean}; 44
     policies), errors-and-erasures decode with reedsolo erase_pos. The
     decoder never sees the truth; truth is used only for scoring.
  5. MISCORRECTION GUARD (H2's silent-miscorrection finding): every codeword
     that decodes WITHOUT raising is compared against the true codeword
     message; wrong bytes => counted as a silent miscorrection and reported
     per rung. byte_exact is always judged against the full true payload.

Policy selection (same pre-stated rule as H2): baseline-passing rungs intact
first, then most byte-exact rungs, then fewest failed codewords, then fewest
byte errors.

PRE-REGISTERED GATE:
  PASS    = m16_rs223_8k byte-exact under the one chosen fixed policy with all
            baseline-passing rungs (m16_rs111, m16_rs191, m32_rs95) intact.
  PARTIAL = m32_rs111_4k or m32_rs159_4k flips (new rungs beyond H5's
            m32_rs127), or total cwFail drops >= 70% vs baseline (74 -> <=22).
  FAIL    = otherwise.

Usage:
    python3 experiments/tape_v2/h6_combo_decode.py [--decode-only]

Outputs:
    results/h6_combo_results.json
    results/h6_combo_decode.log
Seed: pipeline fully deterministic; SEED=2027 logged for protocol parity.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import numpy as np

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

import h5_pll_decode as h5  # noqa: E402  (reuse machinery; module has main guard)
import m3_codec as codec  # noqa: E402
from h2_erasure_decode import _stream_bytes_and_rel  # noqa: E402
from reedsolo import RSCodec, ReedSolomonError  # noqa: E402

SR = codec.FS
SEED = 2027  # logged; deterministic pipeline
TAG = "tape7_run1"
BW_HZ = 0.25  # H5's winning loop bandwidth (timing trajectory) -- FIXED, not swept

RESULTS_DIR = _HERE / "results"
CAPTURES_DIR = _HERE / "captures"
MANIFEST_PATH = _HERE / "master7_manifest.json"
LOG_PATH = RESULTS_DIR / "h6_combo_decode.log"
RESULTS_PATH = RESULTS_DIR / "h6_combo_results.json"
H6_CACHE_PATH = RESULTS_DIR / f"h6_demod_cache_{TAG}.npz"

H5_AUDIO_NPY = CAPTURES_DIR / f"h5_audio_nom_{TAG}.npy"
H5_SYNC_META = RESULTS_DIR / f"h5_sync_meta_{TAG}.json"
H5_DEMOD_CACHE = RESULTS_DIR / f"h5_demod_cache_{TAG}.npz"
H5_RESULTS = RESULTS_DIR / "h5_pll_results_timing.json"
H2_RESULTS = RESULTS_DIR / "h2_erasure_results.json"
M7_RESULTS = RESULTS_DIR / f"m7_results_{TAG}.json"

PASSING_RUNGS = ("m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k")
GATE_RUNG = "m16_rs223_8k"
PARTIAL_RUNGS = ("m32_rs111_4k", "m32_rs159_4k")

_log_fh = None


def log(msg: str, echo: bool = True) -> None:
    global _log_fh
    if _log_fh is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        _log_fh = open(LOG_PATH, "a")
        _log_fh.write(f"\n===== h6_combo_decode run {time.strftime('%F %T')} "
                      f"seed={SEED} bw={BW_HZ} =====\n")
    _log_fh.write(msg + "\n")
    _log_fh.flush()
    if echo:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Instrumented steered demod: H5's demod_frame_steered + H2's lock/gap signals
# ---------------------------------------------------------------------------
class ComboEngine(h5.SectionEngine):
    def score_positions_g(self, yy: np.ndarray, positions: np.ndarray):
        """Identical numerics to SectionEngine.score_positions, additionally
        returning the unnormalized winner-vs-runner-up margin (H2's `gap`)."""
        N = self.N
        n = len(yy)
        pos = positions.astype(np.int64)
        valid = ((n - pos) >= (N // 2)) & (pos >= 0)
        idx = pos[:, None] + np.arange(N)[None, :]
        mask = (idx >= 0) & (idx < n)
        W = np.where(mask, yy[np.clip(idx, 0, n - 1)], 0.0)
        sp = np.abs(np.fft.rfft(W, axis=1))
        e_tone = sp[:, self.tone_bins]
        e_guard = sp[:, self.guard_mat].mean(axis=2)
        sc = e_tone / self.eq - e_guard / self.eq
        order = np.argsort(sc, axis=1)
        s1 = np.take_along_axis(sc, order[:, -1:], 1)[:, 0]
        if self.K == 1:
            ti = order[:, -1]
            si = np.minimum(ti, self.sym_cap - 1)
            s2 = np.take_along_axis(sc, order[:, -2:-1], 1)[:, 0]
            gap = s1 - s2
        else:
            top2 = order[:, -2:]
            a = top2.min(axis=1)
            b = top2.max(axis=1)
            si = np.minimum(self.pair_lut[a, b], self.sym_cap - 1)
            sK = np.take_along_axis(sc, order[:, -self.K:-self.K + 1], 1)[:, 0]
            sK1 = np.take_along_axis(sc, order[:, -self.K - 1:-self.K], 1)[:, 0]
            gap = sK - sK1
        lock = gap / (np.abs(s1) + 1e-9)
        lock = np.where(valid, lock, -np.inf)
        gap = np.where(valid, gap, -np.inf)
        return si, lock, gap, valid

    def demod_frame_steered_instr(self, yy: np.ndarray, ds: int, tau: np.ndarray):
        """H5's demod_frame_steered decision path (same argmax-lock pick),
        instrumented with per-symbol lock + gap of the chosen decode."""
        nsym, N = self.nsym, self.N
        offs = np.arange(-h5.TRACK, h5.TRACK + 1)
        si_out = np.zeros(nsym, np.int64)
        lock_out = np.full(nsym, -np.inf)
        gap_out = np.full(nsym, -np.inf)
        for sidx in range(nsym):
            base = ds + sidx * N + int(round(tau[sidx]))
            si, lock, gap, valid = self.score_positions_g(yy, base + offs)
            if not valid.any():
                continue  # bits stay 0, reliability stays -inf
            j = int(np.argmax(lock))
            si_out[sidx] = si[j]
            lock_out[sidx] = lock[j]
            gap_out[sidx] = gap[j]
        return si_out, lock_out, gap_out


# ---------------------------------------------------------------------------
# Stage A: steered instrumented demod (cached)
# ---------------------------------------------------------------------------
def stage_demod_combo() -> dict:
    if H6_CACHE_PATH.exists():
        log(f"[demod] cache hit: {H6_CACHE_PATH.name}")
        return dict(np.load(H6_CACHE_PATH, allow_pickle=False))

    for p in (H5_AUDIO_NPY, H5_SYNC_META, H5_DEMOD_CACHE):
        if not p.exists():
            raise SystemExit(f"missing H5 cache {p}; run h5_pll_decode.py first")

    t0 = time.time()
    audio_nom = np.load(H5_AUDIO_NPY)
    meta = json.loads(H5_SYNC_META.read_text())
    h5cache = dict(np.load(H5_DEMOD_CACHE, allow_pickle=False))
    manifest = json.loads(MANIFEST_PATH.read_text())
    sounder = meta["sounder"]
    align = meta["align"]
    log(f"[demod] H5 caches loaded ({time.time() - t0:.0f}s); steered "
        f"instrumented re-demod at bw={BW_HZ} Hz (traj=timing)")

    store: dict[str, np.ndarray] = {}
    for sec in manifest["ws_payloads"]:
        name = sec["name"]
        eng = ComboEngine(sec, sounder)
        nF = eng.meta["n_frames"]
        dmat = h5cache[f"{name}/d"]
        ds_arr = h5cache[f"{name}/ds"]
        si_arr = np.zeros((nF, eng.nsym), np.int64)
        lock_arr = np.zeros((nF, eng.nsym), np.float64)
        gap_arr = np.zeros((nF, eng.nsym), np.float64)
        ts = time.time()
        for fi, start in enumerate(sec["frame_starts"]):
            yy = h5.frame_window(audio_nom, eng, start, align)
            tau = h5.build_tau_timing(dmat[fi], eng.fs_sym, BW_HZ)
            si, lock, gap = eng.demod_frame_steered_instr(yy, int(ds_arr[fi]), tau)
            si_arr[fi], lock_arr[fi], gap_arr[fi] = si, lock, gap
        m = eng.section_metrics(list(si_arr))
        log(f"[demod] {name:16s} {eng.ws.name:19s} frames={nF:3d} "
            f"rawBER={m['raw_ber']:.6f} cwFail={m['rs_codewords_failed']}/"
            f"{eng.meta['n_codewords']} exact={m['byte_exact']} "
            f"({time.time() - ts:.0f}s)")
        store[f"{name}/si"] = si_arr
        store[f"{name}/lock"] = lock_arr
        store[f"{name}/gap"] = gap_arr
        store[f"{name}/metrics"] = np.array(
            [m["raw_ber"], m["rs_codewords_failed"], m["byte_errors"],
             float(m["byte_exact"])])
    np.savez_compressed(H6_CACHE_PATH, **store)
    log(f"[demod] cached -> {H6_CACHE_PATH.name} ({time.time() - t0:.0f}s total)")
    return store


# ---------------------------------------------------------------------------
# Errors-and-erasures decode with miscorrection guard
# ---------------------------------------------------------------------------
def _selftest_erase_pos() -> None:
    rsc = RSCodec(64)  # t=32, 2e+f<=64
    rng = np.random.default_rng(SEED)
    msg = bytes(rng.integers(0, 256, 191, dtype=np.uint8))
    cw = bytearray(rsc.encode(msg))
    pos = rng.choice(255, size=50, replace=False)
    epos = sorted(int(p) for p in pos[:40])
    for p in pos:
        cw[int(p)] ^= 0xA5
    dec = rsc.decode(cw, erase_pos=epos)[0]
    assert bytes(dec) == msg, "reedsolo erase_pos self-test FAILED"
    log("[selftest] reedsolo 40 erasures + 10 errors over RS(255,191): OK")


def _decode_guarded(rx_mat, rel_cw, meta, expected, erase_fn, truth_msgs):
    """H2's _decode_with_erasures + miscorrection guard: any codeword that
    decodes without raising but yields wrong message bytes is counted as a
    silent miscorrection. Truth used ONLY for scoring/guarding."""
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    recovered = bytearray()
    cw_failed = 0
    miscorrected = 0
    n_erase_tot = 0
    for i in range(n_cw):
        epos = erase_fn(rel_cw[i])
        n_erase_tot += len(epos)
        try:
            if epos:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()), erase_pos=epos)[0]
            else:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()))[0]
            if bytes(dec) != truth_msgs[i]:
                miscorrected += 1
            recovered += bytes(dec)
        except (ReedSolomonError, Exception):
            cw_failed += 1
            recovered += bytes(rs_k)
    out = bytes(recovered)[:meta["payload_len"]]
    byte_errors = sum(a != b for a, b in zip(out, expected)) + abs(
        len(out) - len(expected))
    return {
        "cw_failed": cw_failed,
        "miscorrected": miscorrected,
        "byte_errors": int(byte_errors),
        "byte_exact": out == expected,
        "mean_erasures_per_cw": n_erase_tot / n_cw,
    }


def make_erase_fn(kind, param, meta, rel_all=None):
    """Same fixed policies as H2 (verbatim semantics)."""
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


# ---------------------------------------------------------------------------
def decode_sweep(cache: dict) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    sounder = json.loads(H5_SYNC_META.read_text())["sounder"]
    m7 = {p["name"]: p for p in json.loads(M7_RESULTS.read_text())["payloads"]}
    h5res = json.loads(H5_RESULTS.read_text())["per_rung"]
    h2res = json.loads(H2_RESULTS.read_text())["per_rung"]
    _selftest_erase_pos()

    rungs = []
    control_ok = True
    log("\n[control] errors-only decode of steered bits vs published H5 numbers")
    for sec in manifest["ws_payloads"]:
        name = sec["name"]
        meta = sec["meta"]
        eng = ComboEngine(sec, sounder)
        expected = eng.expected
        bps = eng.bps

        # steered bits matrix (n_frames, nsym*bps)
        si_arr = cache[f"{name}/si"]
        bits_mat = np.stack([eng.bits_from_si(si) for si in si_arr])

        # truth codeword matrix -> per-codeword true message (for the guard)
        tb_mat = np.zeros_like(bits_mat)
        for fi, tb in enumerate(eng.frames_bits_ref):
            tb = np.asarray(tb, np.uint8)
            m = min(len(tb), tb_mat.shape[1])
            tb_mat[fi, :m] = tb[:m]
        dummy_rel = np.zeros((bits_mat.shape[0], eng.nsym))
        truth_mat, _ = _stream_bytes_and_rel(tb_mat, dummy_rel, meta, bps, "min")
        truth_msgs = [truth_mat[i, :meta["rs_k"]].tobytes()
                      for i in range(meta["n_codewords"])]
        joined = b"".join(truth_msgs)[:meta["payload_len"]]
        assert joined == expected, f"truth codeword layout broken for {name}"

        inputs = {}
        for metric in ("lock", "gap"):
            rel = cache[f"{name}/{metric}"]
            for agg in ("min", "mean"):
                rx_mat, rel_cw = _stream_bytes_and_rel(bits_mat, rel, meta, bps, agg)
                inputs[(metric, agg)] = (rx_mat, rel_cw)

        # control: errors-only through the H6 path == published H5-only numbers
        rx_mat, _ = inputs[("lock", "min")]
        st = _decode_guarded(rx_mat, np.zeros_like(rx_mat, float), meta,
                             expected, lambda rel: [], truth_msgs)
        ref_cw = int(h5res[name]["cw_failed_after"])
        ref_ex = bool(h5res[name]["byte_exact_after"])
        match = (st["cw_failed"] == ref_cw and st["byte_exact"] == ref_ex)
        control_ok &= match
        log(f"  {name:16s} cwFail {st['cw_failed']:>2} (H5 ref {ref_cw:>2}) "
            f"exact {st['byte_exact']!s:5s} (H5 ref {ref_ex!s:5s}) "
            f"misco {st['miscorrected']}  {'OK' if match else 'MISMATCH'}")
        rungs.append({"name": name, "meta": meta, "expected": expected,
                      "inputs": inputs, "truth_msgs": truth_msgs,
                      "errors_only": st})
    if not control_ok:
        log("[control] WARNING: steered errors-only decode does NOT reproduce "
            "the published H5 numbers!")

    # ---- the policy sweep (same fixed grid as H2) ----
    policies = []
    for metric in ("lock", "gap"):
        for agg in ("min", "mean"):
            for f in (0.25, 0.5, 0.75, 1.0):
                policies.append({"kind": "frac", "param": f,
                                 "metric": metric, "agg": agg})
            for q in (2, 5, 10, 15, 20, 25, 30):
                policies.append({"kind": "pct", "param": q,
                                 "metric": metric, "agg": agg})

    log(f"\n[sweep] {len(policies)} fixed policies x {len(rungs)} rungs "
        f"(combo = H5 bw{BW_HZ} front-end + erasures)")
    sweep_rows = []
    for pol in policies:
        per_rung = {}
        for r in rungs:
            name = r["name"]
            meta = r["meta"]
            rx_mat, rel_cw = r["inputs"][(pol["metric"], pol["agg"])]
            efn = make_erase_fn(pol["kind"], pol["param"], meta, rel_cw.ravel())
            per_rung[name] = _decode_guarded(rx_mat, rel_cw, meta,
                                             r["expected"], efn, r["truth_msgs"])
        passing_intact = all(per_rung[n]["byte_exact"] for n in PASSING_RUNGS)
        n_exact = sum(per_rung[n]["byte_exact"] for n in per_rung)
        tot_fail = sum(per_rung[n]["cw_failed"] for n in per_rung)
        tot_misco = sum(per_rung[n]["miscorrected"] for n in per_rung)
        tot_byte_err = sum(per_rung[n]["byte_errors"] for n in per_rung)
        pol_id = f"{pol['kind']}:{pol['param']}|{pol['metric']}|{pol['agg']}"
        sweep_rows.append({"policy": pol_id, **pol, "per_rung": per_rung,
                           "passing_intact": passing_intact, "n_exact": n_exact,
                           "total_cw_failed": tot_fail,
                           "total_miscorrected": tot_misco,
                           "total_byte_errors": tot_byte_err,
                           "gate_rung_exact": per_rung[GATE_RUNG]["byte_exact"]})
        marks = " ".join(
            f"{n.split('_')[0][1:]}r{n.split('rs')[1].split('_')[0]}:"
            f"{per_rung[n]['cw_failed']}"
            f"{'!' * (per_rung[n]['miscorrected'] > 0)}"
            f"{'*' if per_rung[n]['byte_exact'] else ''}"
            for n in per_rung)
        log(f"  {pol_id:<24} exact={n_exact}/9 cwFail={tot_fail:>3} "
            f"misco={tot_misco:>2} passOK={'Y' if passing_intact else 'n'} | {marks}",
            echo=False)

    # pick the single best FIXED policy: same pre-stated rule as H2
    sweep_rows.sort(key=lambda r: (not r["passing_intact"], -r["n_exact"],
                                   r["total_cw_failed"], r["total_byte_errors"]))
    best = sweep_rows[0]
    log(f"\n[best fixed policy] {best['policy']}  (exact {best['n_exact']}/9, "
        f"total cwFail {best['total_cw_failed']}, miscorrected "
        f"{best['total_miscorrected']}, passing intact: {best['passing_intact']})")

    # ---- assemble 4-way per-rung table: baseline / H5-only / H2-only / combo ----
    per_rung_out = {}
    log(f"\n  {'rung':<14} {'cwFail b/H5/H2/combo':>22} "
        f"{'exact b/H5/H2/combo':>26} {'misco':>5} {'eras/cw':>8}")
    for r in rungs:
        name = r["name"]
        st = best["per_rung"][name]
        cw4 = {
            "baseline": int(m7[name]["rs_codewords_failed"]),
            "h5_only": int(h5res[name]["cw_failed_after"]),
            "h2_only": int(h2res[name]["cw_failed_after"]),
            "combo": st["cw_failed"],
        }
        ex4 = {
            "baseline": bool(m7[name]["byte_exact"]),
            "h5_only": bool(h5res[name]["byte_exact_after"]),
            "h2_only": bool(h2res[name]["byte_exact_after"]),
            "combo": st["byte_exact"],
        }
        per_rung_out[name] = {
            "cw_failed": cw4,
            "byte_exact": ex4,
            "byte_errors_combo": st["byte_errors"],
            "miscorrected_cw_combo": st["miscorrected"],
            "mean_erasures_per_cw": st["mean_erasures_per_cw"],
            "n_codewords": r["meta"]["n_codewords"],
            "projected_net_bps": m7[name]["projected_net_bps"],
            "policy": best["policy"],
        }
        log(f"  {name:<14} {cw4['baseline']:>4}/{cw4['h5_only']:>3}/"
            f"{cw4['h2_only']:>3}/{cw4['combo']:>3} "
            f"{ex4['baseline']!s:>6}/{ex4['h5_only']!s:>5}/"
            f"{ex4['h2_only']!s:>5}/{ex4['combo']!s:>5} "
            f"{st['miscorrected']:>5} {st['mean_erasures_per_cw']:>8.1f}")

    # miscorrection guard report for every flipped rung
    flipped = [n for n in per_rung_out
               if not per_rung_out[n]["byte_exact"]["baseline"]
               and per_rung_out[n]["byte_exact"]["combo"]]
    guard = {}
    for n in flipped:
        st = best["per_rung"][n]
        guard[n] = {"miscorrected_cw": st["miscorrected"],
                    "silent_miscorrection": st["miscorrected"] > 0,
                    "note": ("byte_exact==True implies any miscorrection was "
                             "self-cancelling; count must be 0 for a clean flip")}
        log(f"[guard] flipped rung {n}: miscorrected_cw={st['miscorrected']} "
            f"({'CLEAN' if st['miscorrected'] == 0 else 'SILENT MISCORRECTION'})")

    # ---- pre-registered gate ----
    cw_baseline = sum(per_rung_out[n]["cw_failed"]["baseline"] for n in per_rung_out)
    cw_combo = sum(per_rung_out[n]["cw_failed"]["combo"] for n in per_rung_out)
    drop = (cw_baseline - cw_combo) / max(1, cw_baseline)
    passing_intact = all(per_rung_out[n]["byte_exact"]["combo"]
                         for n in PASSING_RUNGS)
    gate_exact = per_rung_out[GATE_RUNG]["byte_exact"]["combo"]
    partial_flips = [n for n in PARTIAL_RUNGS
                     if per_rung_out[n]["byte_exact"]["combo"]
                     and not per_rung_out[n]["byte_exact"]["baseline"]]
    if gate_exact and passing_intact:
        verdict = "PASS"
    elif partial_flips or drop >= 0.70:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    log(f"\n[gate] m16_rs223 exact (combo): {gate_exact}; baseline-passing "
        f"intact: {passing_intact}; partial-rung flips: {partial_flips or 'none'}; "
        f"all flips: {flipped or 'none'}; total cwFail {cw_baseline} -> "
        f"{cw_combo} ({drop * 100:.0f}% drop)")
    log(f"[gate] VERDICT: {verdict}")

    out = {
        "hypothesis": ("H6 combo: H5 timing-trajectory front-end (bw 0.25 Hz, "
                       "traj=timing) + H2 errors-and-erasures RS decoding"),
        "recording": f"captures/{TAG}.wav",
        "seed": SEED,
        "loop_bandwidth_hz": BW_HZ,
        "control_errors_only_matches_h5": bool(control_ok),
        "best_fixed_policy": best["policy"],
        "per_rung": per_rung_out,
        "miscorrection_guard_flipped_rungs": guard,
        "gate": {
            "m16_rs223_exact_combo": bool(gate_exact),
            "passing_rungs_intact": bool(passing_intact),
            "flipped_rungs": flipped,
            "partial_rung_flips": partial_flips,
            "total_cw_failed_baseline": cw_baseline,
            "total_cw_failed_combo": cw_combo,
            "cw_drop_fraction": drop,
            "verdict": verdict,
        },
        "n_policies_swept": len(policies),
        "all_policies_summary": [
            {k: row[k] for k in ("policy", "n_exact", "total_cw_failed",
                                 "total_miscorrected", "passing_intact",
                                 "gate_rung_exact")}
            for row in sweep_rows
        ],
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, default=float))
    log(f"\n[done] wrote {RESULTS_PATH}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decode-only", action="store_true",
                    help="skip steered demod, use cached h6 demod npz")
    args = ap.parse_args()
    log(f"[h6] seed={SEED} bw={BW_HZ} decode_only={args.decode_only}")
    if args.decode_only and H6_CACHE_PATH.exists():
        cache = dict(np.load(H6_CACHE_PATH, allow_pickle=False))
        log(f"[h6] loaded cache {H6_CACHE_PATH.name}")
    else:
        cache = stage_demod_combo()
    decode_sweep(cache)


if __name__ == "__main__":
    main()
