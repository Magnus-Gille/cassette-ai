"""h5_pll_decode.py -- HYPOTHESIS H5: continuous clock tracking (pilot-PLL style)
vs the single linear chirp-to-chirp clock fit, on the REAL capture tape7_run1.wav.

Method (ONE principled estimator, justified):
  Each detected WS symbol carries K strong tones at KNOWN bin-centre frequencies.
  After the baseline (pass-1) demod decides the symbol, we measure the winning
  tone's instantaneous frequency error with the standard data-aided two-half-
  window phase discriminator:  z1 = <first half, e^{-j2pi f t}>, z2 = <second
  half, e^{-j2pi f t}>, delta_f = angle(z2 z1*) * FS / (pi N).  This estimator is
  unbiased, has variance ~ 1/SNR, is NOT quantized by the FFT bin grid (unlike
  parabolic peak interpolation) and is unambiguous for |delta_f| < FS/N = 187.5 Hz
  (flutter excursions are < ~50 Hz).  delta_f / f_tone = instantaneous clock-rate
  error eps(t).  We clip + median-filter (outlier symbols = wrong decisions) and
  zero-phase low-pass (Butterworth-2, loop bandwidth B, swept) eps into a smooth
  clock trajectory, then integrate it into a per-symbol timing trajectory
  tau_k = -N * sum_{j<k} eps_j  which pre-centres the symbol grid:
  base_k = ds + k*N + round(tau_k).  The downstream pipeline is UNCHANGED:
  the same +/-15 max-lock search, contrast detector, EQ, de-interleave, RS --
  only the greedy drift accumulation (the timing front-end) is replaced.

Pass-1 here is a vectorized but bit-faithful re-implementation of
m6_decode._decode_section / assault_widespace._demod_frame_achievable, verified
against results/m7_results_tape7_run1.json.

DISCIPLINE: the slow demod of the 99 MB capture runs ONCE per pass; pass-1
measurements are cached to results/h5_demod_cache_<tag>.npz, the resampled audio
to captures/h5_audio_nom_<tag>.npy (gitignored).  The PLL stage iterates the
cheap trajectory fit + steered re-demod on top of the cache.

Usage:
    python3 experiments/tape_v2/h5_pll_decode.py [--stage all|sync|demod|pll]
        [--recording captures/tape7_run1.wav] [--bws 0.5,1.0,2.0,3.0]

Outputs:
    results/h5_pll_results.json   (per-rung before/after + chosen loop bandwidth)
    results/h5_pll_decode.log     (verbose)
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
from scipy.signal import butter, filtfilt, medfilt, resample_poly

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
from m3_codec import Rung  # noqa: E402
from assault_widespace import build as ws_build  # noqa: E402

SR = codec.FS
SEED = 2025  # logged for protocol; the pipeline is fully deterministic
MANIFEST_PATH = _HERE / "master7_manifest.json"
RESULTS_DIR = _HERE / "results"
CAPTURES_DIR = _HERE / "captures"
WS_WINDOW_PAD = 0.30
TRACK = 15  # SAME +/-15 search as the baseline tracker
EPS_CLIP = 0.02  # |clock error| sanity clip (2%; real flutter wrms 0.37%)
MED_KERNEL = 9  # median-filter kernel (symbols) for decision-outlier rejection

LOG_PATH = RESULTS_DIR / "h5_pll_decode.log"
_log_fh = None


def log(msg: str, echo: bool = True) -> None:
    global _log_fh
    if _log_fh is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        _log_fh = open(LOG_PATH, "a")
        _log_fh.write(f"\n===== h5_pll_decode run {time.strftime('%F %T')} seed={SEED} =====\n")
    _log_fh.write(msg + "\n")
    _log_fh.flush()
    if echo:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Vectorized faithful re-implementation of the WS contrast demod
# ---------------------------------------------------------------------------
class SectionEngine:
    """Precomputed geometry + vectorized scoring for one WS section."""

    def __init__(self, sec: dict, sounder: dict):
        phy = sec["phy_params"]
        self.ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
        assert self.ws is not None, sec["name"]
        ws = self.ws
        self.N = ws.N
        self.M = ws.M
        self.K = ws.K
        self.bps = ws.bits_per_sym
        self.tone_bins = np.clip(ws._bin_indices, 0, self.N // 2)
        # guard bins: uniform count per tone for both master7 geometries (assert)
        glens = {len(g) for g in ws._guard_bins}
        assert len(glens) == 1, f"non-uniform guard bins in {ws.name}: {glens}"
        self.guard_mat = np.stack(ws._guard_bins)  # (M, G)
        self.eq = self._eq_from_sounder(sounder)
        # symbol lookup
        if self.K == 1:
            # combinations(range(M),1) in order -> symbol index == tone index
            self.pair_lut = None
        else:
            lut = np.zeros((self.M, self.M), dtype=np.int64)
            for pair, si in ws._rev_table.items():
                lut[pair[0], pair[1]] = si
            self.pair_lut = lut
        self.sym_cap = ws._sym_cap
        # frequency-discriminator exponentials (half-window correlators)
        half = self.N // 2
        n = np.arange(self.N)
        E = np.exp(-2j * np.pi * ws.freqs[None, :] * n[:, None] / SR)  # (N, M)
        self.E1 = E[:half]  # (half, M)
        self.E2 = E[half:]
        self.fs_sym = SR / self.N

        # codec side
        meta = sec["meta"]
        self.meta = meta
        rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                    rs_n=meta["rs_n"], rs_k=meta["rs_k"],
                    frame_bytes=meta["frame_bytes"])
        self.expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        self.frames_bits_ref, _ = codec.encode_payload(self.expected, rung)
        self.nsym = meta["frame_bits"] // ws.bits_per_sym  # m6 convention (fixed)
        test_audio = np.asarray(ws.modulate(np.zeros(meta["frame_bits"], np.uint8)),
                                np.float32)
        self.flen = len(test_audio)
        self.sec = sec

    def _eq_from_sounder(self, sounder: dict) -> np.ndarray:
        sf_freqs = np.asarray(sounder.get("sounder_freqs", []), dtype=np.float64)
        H_db = np.asarray(sounder.get("H_db", []), dtype=np.float64)
        if len(sf_freqs) < 2:
            return np.ones(self.ws.M)
        Hlin = 10.0 ** (np.interp(self.ws.freqs, sf_freqs, H_db) / 20.0)
        Hlin = Hlin / (Hlin.max() + 1e-12)
        return np.clip(Hlin, 0.05, None)

    # --- vectorized scoring at a batch of candidate positions ---------------
    def score_positions(self, yy: np.ndarray, positions: np.ndarray):
        """Faithful batch version of _energies_at + _score + _sym_from_score +
        the lock metric. Returns (si, lock, valid) arrays over positions."""
        N = self.N
        n = len(yy)
        pos = positions.astype(np.int64)
        valid = ((n - pos) >= (N // 2)) & (pos >= 0)  # _energies_at None-condition
        idx = pos[:, None] + np.arange(N)[None, :]
        mask = (idx >= 0) & (idx < n)
        W = np.where(mask, yy[np.clip(idx, 0, n - 1)], 0.0)  # zero-pad tail
        sp = np.abs(np.fft.rfft(W, axis=1))
        e_tone = sp[:, self.tone_bins]                      # (P, M)
        e_guard = sp[:, self.guard_mat].mean(axis=2)        # (P, M)
        sc = e_tone / self.eq - e_guard / self.eq           # contrast
        if self.K == 1:
            order = np.argsort(sc, axis=1)
            ti = order[:, -1]
            si = np.minimum(ti, self.sym_cap - 1)
            s1 = np.take_along_axis(sc, order[:, -1:], 1)[:, 0]
            s2 = np.take_along_axis(sc, order[:, -2:-1], 1)[:, 0]
            lock = (s1 - s2) / (np.abs(s1) + 1e-9)
            tones = ti[:, None]                             # (P, 1)
        else:
            order = np.argsort(sc, axis=1)
            top2 = order[:, -2:]                            # unordered pair
            a = top2.min(axis=1)
            b = top2.max(axis=1)
            si = np.minimum(self.pair_lut[a, b], self.sym_cap - 1)
            s1 = np.take_along_axis(sc, order[:, -1:], 1)[:, 0]
            sK = np.take_along_axis(sc, order[:, -self.K:-self.K + 1], 1)[:, 0]
            sK1 = np.take_along_axis(sc, order[:, -self.K - 1:-self.K], 1)[:, 0]
            lock = (sK - sK1) / (np.abs(s1) + 1e-9)
            tones = np.stack([a, b], axis=1)                # (P, 2)
        lock = np.where(valid, lock, -np.inf)
        return si, lock, valid, W, tones

    # --- pass 1: faithful greedy tracker + per-symbol clock measurement -----
    def demod_frame_pass1(self, yy: np.ndarray, ds: int):
        nsym, N = self.nsym, self.N
        offs = np.arange(-TRACK, TRACK + 1)
        si_out = np.zeros(nsym, np.int64)
        d_out = np.zeros(nsym, np.int64)
        lock_out = np.full(nsym, -np.inf)
        ok_out = np.zeros(nsym, bool)
        segs = np.zeros((nsym, N))
        tones_out = np.zeros((nsym, self.K), np.int64)
        drift = 0.0
        for sidx in range(nsym):
            base = ds + sidx * N + int(round(drift))
            si, lock, valid, W, tones = self.score_positions(yy, base + offs)
            if not valid.any():
                continue  # bits stay 0, drift unchanged (baseline behaviour)
            j = int(np.argmax(lock))  # first max == baseline strict-> scan
            si_out[sidx] = si[j]
            d_out[sidx] = offs[j]
            lock_out[sidx] = lock[j]
            ok_out[sidx] = True
            segs[sidx] = W[j]
            tones_out[sidx] = tones[j]
            drift += offs[j]
        eps = self._clock_from_segs(segs, tones_out, ok_out)
        return si_out, d_out, lock_out, ok_out, eps

    # --- pass 2: trajectory-steered grid, NO greedy accumulation ------------
    def demod_frame_steered(self, yy: np.ndarray, ds: int, tau: np.ndarray):
        nsym, N = self.nsym, self.N
        offs = np.arange(-TRACK, TRACK + 1)
        si_out = np.zeros(nsym, np.int64)
        for sidx in range(nsym):
            base = ds + sidx * N + int(round(tau[sidx]))
            si, lock, valid, _, _ = self.score_positions(yy, base + offs)
            if not valid.any():
                continue
            si_out[sidx] = si[int(np.argmax(lock))]
        return si_out

    def _clock_from_segs(self, segs, tones, ok):
        """Two-half-window phase discriminator at the winning tone(s) ->
        per-symbol relative clock error eps (NaN where invalid)."""
        half = self.N // 2
        Z1 = segs[:, :half] @ self.E1  # (nsym, M)
        Z2 = segs[:, half:] @ self.E2
        dphi = np.angle(Z2 * np.conj(Z1))                     # (nsym, M)
        f_err = dphi * SR / (np.pi * self.N)                  # Hz
        eps_tone = f_err / self.ws.freqs[None, :]             # relative
        w_tone = np.abs(Z1 + Z2)                              # full-window DFT mag
        rows = np.arange(len(segs))[:, None]
        e = eps_tone[rows, tones]                             # (nsym, K)
        w = w_tone[rows, tones] + 1e-12
        eps = (e * w).sum(axis=1) / w.sum(axis=1)
        eps[~ok] = np.nan
        return eps

    def bits_from_si(self, si: np.ndarray) -> np.ndarray:
        shifts = np.arange(self.bps - 1, -1, -1)
        return ((si[:, None] >> shifts[None, :]) & 1).astype(np.uint8).ravel()

    def section_metrics(self, frames_si: list[np.ndarray]) -> dict:
        raw_err = raw_tot = 0
        frames_bits = []
        for fi, si in enumerate(frames_si):
            rb = self.bits_from_si(si)
            tb = self.frames_bits_ref[fi].astype(np.uint8)
            m = min(len(tb), len(rb))
            raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
            raw_tot += len(tb)
            frames_bits.append(rb)
        recovered = codec.decode_payload(frames_bits, self.meta)
        cw_failed = codec.decode_payload.last_codewords_failed
        byte_errors = sum(a != b for a, b in zip(recovered, self.expected)) + abs(
            len(recovered) - len(self.expected))
        return {
            "raw_ber": raw_err / max(1, raw_tot),
            "rs_codewords_failed": int(cw_failed),
            "byte_errors": int(byte_errors),
            "byte_exact": recovered == self.expected,
        }


# ---------------------------------------------------------------------------
# Stage 1: global sync + resample (cached)
# ---------------------------------------------------------------------------
def stage_sync(recording: pathlib.Path, tag: str) -> tuple[np.ndarray, dict]:
    audio_npy = CAPTURES_DIR / f"h5_audio_nom_{tag}.npy"
    meta_json = RESULTS_DIR / f"h5_sync_meta_{tag}.json"
    if audio_npy.exists() and meta_json.exists():
        log(f"[sync] cache hit: {audio_npy.name}, {meta_json.name}")
        return np.load(audio_npy), json.loads(meta_json.read_text())

    manifest = json.loads(MANIFEST_PATH.read_text())
    t0 = time.time()
    audio, sr = sf.read(str(recording), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = np.asarray(sync["audio_nominal"], np.float32)
    align = int(sync["chirp0_nominal"] - manifest["tx_chirp0"])
    sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    meta = {
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "align": align,
        "sounder": sounder,
    }
    np.save(audio_npy, audio_nom)
    meta_json.write_text(json.dumps(meta, indent=2, default=float))
    log(f"[sync] done in {time.time() - t0:.0f}s: clock {sync['speed']:.6f}x, "
        f"align {align:+d}, flutter {sounder.get('flutter_wrms_pct', float('nan')):.3f}%")
    return audio_nom, meta


# ---------------------------------------------------------------------------
# Stage 2: pass-1 demod (baseline-faithful) + clock measurement, cached
# ---------------------------------------------------------------------------
def frame_window(audio_nom, eng: SectionEngine, start: int, align: int):
    st = int(start) + align
    pad = int(WS_WINDOW_PAD * SR)
    lo = max(0, st - pad)
    hi = min(len(audio_nom), st + eng.flen + pad)
    return np.asarray(audio_nom[lo:hi], dtype=np.float64)


def stage_demod(audio_nom, meta: dict, tag: str) -> dict:
    cache_npz = RESULTS_DIR / f"h5_demod_cache_{tag}.npz"
    if cache_npz.exists():
        log(f"[demod] cache hit: {cache_npz.name}")
        return dict(np.load(cache_npz, allow_pickle=False))

    manifest = json.loads(MANIFEST_PATH.read_text())
    sounder = meta["sounder"]
    align = meta["align"]
    store: dict[str, np.ndarray] = {}
    t_all = time.time()
    for sec in manifest["ws_payloads"]:
        name = sec["name"]
        eng = SectionEngine(sec, sounder)
        nF = eng.meta["n_frames"]
        ds_arr = np.zeros(nF, np.int64)
        si_arr = np.zeros((nF, eng.nsym), np.int64)
        d_arr = np.zeros((nF, eng.nsym), np.int64)
        lock_arr = np.zeros((nF, eng.nsym), np.float32)
        ok_arr = np.zeros((nF, eng.nsym), bool)
        eps_arr = np.zeros((nF, eng.nsym), np.float64)
        t0 = time.time()
        for fi, start in enumerate(sec["frame_starts"]):
            yy = frame_window(audio_nom, eng, start, align)
            ds = hc.find_preamble(yy.astype(np.float32), eng.ws.preamble_seconds)
            si, d, lock, ok, eps = eng.demod_frame_pass1(yy, ds)
            ds_arr[fi] = ds
            si_arr[fi], d_arr[fi], lock_arr[fi] = si, d, lock
            ok_arr[fi], eps_arr[fi] = ok, eps
        m = eng.section_metrics(list(si_arr))
        log(f"[demod] {name:16s} {eng.ws.name:19s} frames={nF:3d} "
            f"rawBER={m['raw_ber']:.6f} cwFail={m['rs_codewords_failed']}/"
            f"{eng.meta['n_codewords']} exact={m['byte_exact']} "
            f"({time.time() - t0:.0f}s)")
        store[f"{name}/ds"] = ds_arr
        store[f"{name}/si"] = si_arr
        store[f"{name}/d"] = d_arr
        store[f"{name}/lock"] = lock_arr
        store[f"{name}/ok"] = ok_arr
        store[f"{name}/eps"] = eps_arr
        store[f"{name}/baseline"] = np.array(
            [m["raw_ber"], m["rs_codewords_failed"], m["byte_errors"],
             float(m["byte_exact"])])
    np.savez_compressed(cache_npz, **store)
    log(f"[demod] pass-1 cached -> {cache_npz.name} ({time.time() - t_all:.0f}s total)")
    return store


# ---------------------------------------------------------------------------
# Stage 3: PLL trajectory + steered re-demod (loop-bandwidth sweep)
# ---------------------------------------------------------------------------
def build_tau_timing(d_row: np.ndarray, fs_sym: float, bw_hz: float) -> np.ndarray:
    """Timing-based trajectory: the pass-1 greedy tracker's chosen-offset
    sequence IS a per-symbol timing-error measurement (derived from the
    symbol-boundary energy/lock profile).  drift_k = sum_{j<k} d_j is its
    integral; median-filter (single-symbol mis-picks) + zero-phase Butterworth-2
    low-pass (loop bandwidth B) turn it into a smooth clock trajectory."""
    drift = np.concatenate([[0.0], np.cumsum(d_row.astype(np.float64))[:-1]])
    k = min(MED_KERNEL, len(drift) - (1 - len(drift) % 2))
    if k >= 3:
        drift = medfilt(drift, kernel_size=k)
    wn = min(0.99, bw_hz / (fs_sym / 2.0))
    b, a = butter(2, wn)
    if len(drift) > 3 * max(len(a), len(b)):
        drift = filtfilt(b, a, drift)
    return drift


def build_tau(eps: np.ndarray, fs_sym: float, bw_hz: float, N: int) -> np.ndarray:
    """eps (per-symbol relative clock error, NaN where invalid) ->
    smooth timing trajectory tau (samples), tau[0]=0."""
    e = eps.copy()
    bad = ~np.isfinite(e)
    if bad.all():
        return np.zeros(len(e))
    if bad.any():
        idx = np.arange(len(e))
        e[bad] = np.interp(idx[bad], idx[~bad], e[~bad])
    e = np.clip(e, -EPS_CLIP, EPS_CLIP)
    k = min(MED_KERNEL, len(e) - (1 - len(e) % 2))
    if k >= 3:
        e = medfilt(e, kernel_size=k)
    wn = min(0.99, bw_hz / (fs_sym / 2.0))
    b, a = butter(2, wn)
    if len(e) > 3 * max(len(a), len(b)):
        e = filtfilt(b, a, e)
    # local clock fast by (1+eps) -> symbols arrive early -> grid steps shorter
    tau = -N * np.concatenate([[0.0], np.cumsum(e)[:-1]])
    return tau


def stage_pll(audio_nom, meta: dict, cache: dict, tag: str, bws: list[float],
              traj: str = "timing") -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    sounder = meta["sounder"]
    align = meta["align"]
    m7_official = json.loads(
        (RESULTS_DIR / f"m7_results_{tag}.json").read_text())["payloads"]
    official = {p["name"]: p for p in m7_official}

    engines = {}
    for sec in manifest["ws_payloads"]:
        engines[sec["name"]] = (sec, SectionEngine(sec, sounder))

    # diagnostics: trajectory vs pass-1 greedy drift correlation (sign check)
    diag = {}
    for name, (sec, eng) in engines.items():
        eps = cache[f"{name}/eps"]
        d = cache[f"{name}/d"]
        rr = []
        rms = []
        for fi in range(eps.shape[0]):
            tau = build_tau(eps[fi], eng.fs_sym, 1.0, eng.N)
            drift = np.concatenate([[0.0], np.cumsum(d[fi])[:-1]])
            if np.std(tau) > 1e-9 and np.std(drift) > 1e-9:
                rr.append(float(np.corrcoef(tau, drift)[0, 1]))
            rms.append(float(np.sqrt(np.nanmean(
                np.clip(eps[fi], -EPS_CLIP, EPS_CLIP) ** 2))))
        diag[name] = {
            "tau_vs_drift_corr_median": float(np.median(rr)) if rr else None,
            "eps_rms_median": float(np.median(rms)),
        }
        log(f"[pll-diag] {name:16s} corr(tau, greedy-drift) med="
            f"{diag[name]['tau_vs_drift_corr_median']} eps_rms med="
            f"{diag[name]['eps_rms_median']:.5f}")

    sweep: dict[str, dict] = {}
    for bw in bws:
        t0 = time.time()
        per_rung = {}
        for name, (sec, eng) in engines.items():
            eps = cache[f"{name}/eps"]
            dmat = cache[f"{name}/d"]
            ds_arr = cache[f"{name}/ds"]
            frames_si = []
            for fi, start in enumerate(sec["frame_starts"]):
                yy = frame_window(audio_nom, eng, start, align)
                if traj == "freq":
                    tau = build_tau(eps[fi], eng.fs_sym, bw, eng.N)
                else:
                    tau = build_tau_timing(dmat[fi], eng.fs_sym, bw)
                frames_si.append(eng.demod_frame_steered(yy, int(ds_arr[fi]), tau))
            m = eng.section_metrics(frames_si)
            per_rung[name] = m
        # summary line per bw
        m16 = [n for n in per_rung if n.startswith("m16")]
        rels = []
        for n in m16:
            b = cache[f"{n}/baseline"][0]
            rels.append((b - per_rung[n]["raw_ber"]) / max(b, 1e-12))
        med = float(np.median(rels))
        nex = sum(per_rung[n]["byte_exact"] for n in per_rung)
        log(f"[pll] bw={bw:4.2f} Hz: median M16 relBER reduction {med * 100:+.1f}%, "
            f"byte-exact {nex}/9 ({time.time() - t0:.0f}s)")
        for n, m in per_rung.items():
            b = cache[f"{n}/baseline"]
            log(f"        {n:16s} BER {b[0]:.5f} -> {m['raw_ber']:.5f} "
                f"cw {int(b[1])} -> {m['rs_codewords_failed']} "
                f"exact {bool(b[3])} -> {m['byte_exact']}", echo=False)
        sweep[str(bw)] = {"median_m16_rel_reduction": med, "per_rung": per_rung,
                          "n_byte_exact": int(nex)}

    # choose bw by median M16 relative BER reduction (pre-stated selector)
    chosen_bw = max(bws, key=lambda b: sweep[str(b)]["median_m16_rel_reduction"])
    chosen = sweep[str(chosen_bw)]["per_rung"]

    # gate evaluation at chosen bw
    rung_names = list(engines.keys())
    m16 = [n for n in rung_names if n.startswith("m16")]
    rels = []
    worsened = []
    for n in rung_names:
        b = float(cache[f"{n}/baseline"][0])
        a = chosen[n]["raw_ber"]
        if n in m16:
            rels.append((b - a) / max(b, 1e-12))
        if a > b * 1.05:
            worsened.append(n)
    median_m16 = float(np.median(rels))
    prev_pass = [n for n in rung_names if bool(cache[f"{n}/baseline"][3])]
    kept_exact = [n for n in prev_pass if chosen[n]["byte_exact"]]
    flipped = [n for n in rung_names
               if not bool(cache[f"{n}/baseline"][3]) and chosen[n]["byte_exact"]]

    gate_pass = (median_m16 >= 0.20 and not worsened
                 and len(kept_exact) == len(prev_pass))
    gate_partial = (not gate_pass) and (bool(flipped) or 0.10 <= median_m16 < 0.20)
    verdict = "PASS" if gate_pass else ("PARTIAL" if gate_partial else "FAIL")

    method_desc = {
        "freq": ("data-aided two-half-window phase discriminator on winning "
                 "WS tone -> per-symbol relative clock error -> clip(2%) + "
                 f"median({MED_KERNEL}) + Butterworth-2 zero-phase lowpass(B) "
                 "-> tau_k = -N*cumsum(eps) steering the symbol grid; "
                 "same +/-15 max-lock search downstream, greedy drift removed"),
        "timing": ("pass-1 greedy tracker chosen-offset sequence (symbol-"
                   "boundary lock/energy profile) integrated to drift_k, "
                   f"median({MED_KERNEL}) + Butterworth-2 zero-phase lowpass(B) "
                   "-> smooth timing trajectory tau steering the symbol grid; "
                   "same +/-15 max-lock search downstream, greedy accumulation "
                   "removed"),
    }[traj]
    out = {
        "recording": f"captures/{tag}.wav",
        "seed": SEED,
        "trajectory_method": traj,
        "method": method_desc,
        "loop_bandwidth_hz": chosen_bw,
        "bandwidths_swept": bws,
        "diagnostics": diag,
        "per_rung": {
            n: {
                "raw_ber_before": float(cache[f"{n}/baseline"][0]),
                "raw_ber_after": chosen[n]["raw_ber"],
                "cw_failed_before": int(cache[f"{n}/baseline"][1]),
                "cw_failed_after": chosen[n]["rs_codewords_failed"],
                "byte_exact_before": bool(cache[f"{n}/baseline"][3]),
                "byte_exact_after": chosen[n]["byte_exact"],
                "byte_errors_after": chosen[n]["byte_errors"],
                "m7_official_raw_ber": official[n]["raw_ber"],
            }
            for n in rung_names
        },
        "bw_sweep": sweep,
        "gate": {
            "median_m16_rel_ber_reduction": median_m16,
            "worsened_rungs_gt5pct": worsened,
            "previously_passing": prev_pass,
            "still_exact": kept_exact,
            "newly_exact": flipped,
            "verdict": verdict,
        },
    }
    out_path = RESULTS_DIR / f"h5_pll_results_{traj}.json"
    out_path.write_text(json.dumps(out, indent=2, default=float))
    log(f"[pll] chosen bw {chosen_bw} Hz; median M16 relBER reduction "
        f"{median_m16 * 100:+.1f}%; worsened>5%: {worsened or 'none'}; "
        f"kept exact {len(kept_exact)}/{len(prev_pass)}; newly exact: "
        f"{flipped or 'none'} -> VERDICT {verdict}")
    log(f"[pll] wrote {out_path}")
    return out


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recording", default=str(CAPTURES_DIR / "tape7_run1.wav"))
    ap.add_argument("--stage", default="all", choices=["all", "sync", "demod", "pll"])
    ap.add_argument("--bws", default="0.5,1.0,2.0,3.0")
    ap.add_argument("--traj", default="timing", choices=["timing", "freq"])
    args = ap.parse_args()

    rec = pathlib.Path(args.recording)
    tag = rec.stem
    bws = [float(x) for x in args.bws.split(",")]
    log(f"[main] recording={rec} stage={args.stage} bws={bws} traj={args.traj}")

    audio_nom, meta = stage_sync(rec, tag)
    if args.stage == "sync":
        return
    cache = stage_demod(audio_nom, meta, tag)
    if args.stage == "demod":
        return
    stage_pll(audio_nom, meta, cache, tag, bws, traj=args.traj)


if __name__ == "__main__":
    main()
