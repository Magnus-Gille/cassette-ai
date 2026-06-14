"""x9_ws_forensics.py -- R3: WS fixed-grid failure forensics + timing-trajectory
rescue on the m8 real capture (captures/m8_tape_mono_lossless.wav).

Question: on m8, ALL fixed-grid WS rungs failed (raw BER 0.07-0.19) including the
previously-proven 562 bps control (m8_ctrl_m16k1_rs191, 9/9 cw). Meanwhile the
m8_decode combo path (h5 timing-trajectory front-end bw 0.25 Hz + errors-and-
erasures + manifest-CRC guard) rescued m8_m32k2_rs159 (748 bps) clean, and got
the 562 control to 1/9 cw (almost). The K=3 lottery rung m8_m16k3_rs159
(1052 bps, BER 0.103, 37/37 cw) has NO combo path because h5.SectionEngine only
supports K in {1,2}. If the WS failures are a recoverable front-end/alignment
problem, rescuing m8_m16k3_rs159 = INSTANT NEW RECORD (1052 > 934).

This script:
  STAGE sync   -- global sync + resample of the m8 capture (cached, slow once).
  STAGE demod  -- baseline-faithful pass-1 greedy demod of every WS section,
                  recording per-symbol chosen-offset d, lock, preamble ds,
                  per-tone contrast, two-half-window clock eps. Cached.
  STAGE forensics -- for the control + every M16 rung: per-frame preamble
                  offset spread, per-symbol timing error vs the fixed grid,
                  error bunching vs grid drift, per-tone detection contrast
                  over time. Classifies the failure: timing-slip (recoverable)
                  vs EQ/level vs genuinely random.
  STAGE rescue -- K=1/2/3-capable timing-trajectory front-end (h5 logic
                  generalized to K=3 via a combinations LUT) + errors-and-
                  erasures RS with the manifest CRC32-per-codeword guard.
                  Sweeps: trajectory bandwidth {0.1,0.25,0.5,1.0,2.0},
                  freq-disc vs timing trajectory, 2-pass decision-directed
                  retiming, contrast-gap erasures. The decoder NEVER sees the
                  truth payload; truth bytes are used ONLY for scoring. The CRC
                  table is the receiver-side miscorrection guard.

Outputs:
    x9_dossier/R3_ws_rescue.json
    x9_dossier/R3_ws_rescue.md  (written by a sibling step from the json)
    results/x9_audio_nom_<tag>.npy (gitignored), results/x9_sync_meta_<tag>.json
    results/x9_demod_cache_<tag>.npz

Seed 2025 logged for protocol (pipeline fully deterministic).
"""
from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import sys
import time
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import butter, filtfilt, medfilt, resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

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
from h2_erasure_decode import _stream_bytes_and_rel  # noqa: E402
from reedsolo import RSCodec, ReedSolomonError  # noqa: E402

SR = codec.FS
SEED = 2025
MANIFEST_PATH = _HERE / "master8_manifest.json"
RESULTS_DIR = _HERE / "results"
CAPTURES_DIR = _HERE / "captures"
DOSSIER = _HERE / "x9_dossier"
WS_WINDOW_PAD = 0.30
TRACK = 15
EPS_CLIP = 0.02
MED_KERNEL = 9

LOG_PATH = DOSSIER / "x9_ws_forensics.log"
_log_fh = None


def log(msg: str, echo: bool = True) -> None:
    global _log_fh
    if _log_fh is None:
        DOSSIER.mkdir(parents=True, exist_ok=True)
        _log_fh = open(LOG_PATH, "a")
        _log_fh.write(f"\n===== x9_ws_forensics run {time.strftime('%F %T')} "
                      f"seed={SEED} =====\n")
    _log_fh.write(msg + "\n")
    _log_fh.flush()
    if echo:
        print(msg, flush=True)


# ===========================================================================
# K=1/2/3-capable SectionEngine (generalizes h5.SectionEngine to K=3)
# ===========================================================================
class WSEngineK3:
    """Vectorized faithful WS contrast demod for K in {1,2,3}. K=1/2 paths are
    numerically identical to h5.SectionEngine; K=3 adds a 3-tone combinations
    LUT so the timing-trajectory front-end can run on the lottery rung."""

    def __init__(self, sec: dict, sounder: dict):
        phy = sec["phy_params"]
        self.ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
        assert self.ws is not None, sec["name"]
        ws = self.ws
        self.N, self.M, self.K = ws.N, ws.M, ws.K
        self.bps = ws.bits_per_sym
        self.tone_bins = np.clip(ws._bin_indices, 0, self.N // 2)
        glens = {len(g) for g in ws._guard_bins}
        assert len(glens) == 1, f"non-uniform guard bins in {ws.name}: {glens}"
        self.guard_mat = np.stack(ws._guard_bins)
        self.eq = self._eq_from_sounder(sounder)
        self.sym_cap = ws._sym_cap

        # symbol lookup tables, generalized over K
        if self.K == 1:
            self.pair_lut = None
            self.combo_lut = None
        elif self.K == 2:
            lut = np.full((self.M, self.M), 0, dtype=np.int64)
            for pair, si in ws._rev_table.items():
                lut[pair[0], pair[1]] = si
            self.pair_lut = lut
            self.combo_lut = None
        elif self.K == 3:
            # 3D LUT: combo_lut[a,b,c] (a<b<c) -> symbol index (capped at sym_cap-1)
            lut = np.zeros((self.M, self.M, self.M), dtype=np.int64)
            for trip, si in ws._rev_table.items():
                lut[trip[0], trip[1], trip[2]] = min(si, self.sym_cap - 1)
            self.combo_lut = lut
            self.pair_lut = None
        else:
            raise ValueError(f"K={self.K} not supported")

        half = self.N // 2
        n = np.arange(self.N)
        E = np.exp(-2j * np.pi * ws.freqs[None, :] * n[:, None] / SR)
        self.E1 = E[:half]
        self.E2 = E[half:]
        self.fs_sym = SR / self.N

        meta = sec["meta"]
        self.meta = meta
        rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                    rs_n=meta["rs_n"], rs_k=meta["rs_k"],
                    frame_bytes=meta["frame_bytes"])
        self.expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        self.frames_bits_ref, _ = codec.encode_payload(self.expected, rung)
        self.nsym = meta["frame_bits"] // ws.bits_per_sym
        test_audio = np.asarray(
            ws.modulate(np.zeros(meta["frame_bits"], np.uint8)), np.float32)
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

    def _scores(self, yy, positions):
        """Return contrast scores (P, M) and the zero-padded windows (P, N)."""
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
        return sc, W, valid

    def score_positions(self, yy, positions):
        """Faithful batch decode at candidate positions. Returns
        (si, lock, gap, valid, W, tones). lock is the K-vs-(K+1) normalized
        margin; gap is the unnormalized margin."""
        sc, W, valid = self._scores(yy, positions)
        order = np.argsort(sc, axis=1)
        s1 = np.take_along_axis(sc, order[:, -1:], 1)[:, 0]
        if self.K == 1:
            ti = order[:, -1]
            si = np.minimum(ti, self.sym_cap - 1)
            s2 = np.take_along_axis(sc, order[:, -2:-1], 1)[:, 0]
            gap = s1 - s2
            tones = ti[:, None]
        elif self.K == 2:
            top = order[:, -2:]
            a = top.min(axis=1)
            b = top.max(axis=1)
            si = np.minimum(self.pair_lut[a, b], self.sym_cap - 1)
            sK = np.take_along_axis(sc, order[:, -2:-1], 1)[:, 0]
            sK1 = np.take_along_axis(sc, order[:, -3:-2], 1)[:, 0]
            gap = sK - sK1
            tones = np.stack([a, b], axis=1)
        else:  # K == 3
            top = np.sort(order[:, -3:], axis=1)  # ascending sorted triple
            a, b, c = top[:, 0], top[:, 1], top[:, 2]
            si = self.combo_lut[a, b, c]
            sK = np.take_along_axis(sc, order[:, -3:-2], 1)[:, 0]
            sK1 = np.take_along_axis(sc, order[:, -4:-3], 1)[:, 0]
            gap = sK - sK1
            tones = np.stack([a, b, c], axis=1)
        lock = gap / (np.abs(s1) + 1e-9)
        lock = np.where(valid, lock, -np.inf)
        gap = np.where(valid, gap, -np.inf)
        return si, lock, gap, valid, W, tones

    def demod_frame_pass1(self, yy, ds):
        """Faithful greedy tracker == _demod_frame_achievable. Also returns the
        per-symbol clock eps (two-half-window discriminator on winning tones),
        per-tone contrast scores of the winner, and contrast margin."""
        nsym, N = self.nsym, self.N
        offs = np.arange(-TRACK, TRACK + 1)
        si_out = np.zeros(nsym, np.int64)
        d_out = np.zeros(nsym, np.int64)
        lock_out = np.full(nsym, -np.inf)
        gap_out = np.full(nsym, -np.inf)
        ok_out = np.zeros(nsym, bool)
        segs = np.zeros((nsym, N))
        tones_out = np.zeros((nsym, self.K), np.int64)
        drift = 0.0
        for sidx in range(nsym):
            base = ds + sidx * N + int(round(drift))
            si, lock, gap, valid, W, tones = self.score_positions(yy, base + offs)
            if not valid.any():
                continue
            j = int(np.argmax(lock))
            si_out[sidx] = si[j]
            d_out[sidx] = offs[j]
            lock_out[sidx] = lock[j]
            gap_out[sidx] = gap[j]
            ok_out[sidx] = True
            segs[sidx] = W[j]
            tones_out[sidx] = tones[j]
            drift += offs[j]
        eps = self._clock_from_segs(segs, tones_out, ok_out)
        return si_out, d_out, lock_out, gap_out, ok_out, eps

    def demod_frame_steered_instr(self, yy, ds, tau):
        """Trajectory-steered grid (no greedy accumulation), instrumented with
        per-symbol lock + gap of the chosen decode (H6 style)."""
        nsym, N = self.nsym, self.N
        offs = np.arange(-TRACK, TRACK + 1)
        si_out = np.zeros(nsym, np.int64)
        lock_out = np.full(nsym, -np.inf)
        gap_out = np.full(nsym, -np.inf)
        d_out = np.zeros(nsym, np.int64)
        for sidx in range(nsym):
            base = ds + sidx * N + int(round(tau[sidx]))
            si, lock, gap, valid, _, _ = self.score_positions(yy, base + offs)
            if not valid.any():
                continue
            j = int(np.argmax(lock))
            si_out[sidx] = si[j]
            lock_out[sidx] = lock[j]
            gap_out[sidx] = gap[j]
            d_out[sidx] = offs[j]
        return si_out, lock_out, gap_out, d_out

    def _clock_from_segs(self, segs, tones, ok):
        half = self.N // 2
        Z1 = segs[:, :half] @ self.E1
        Z2 = segs[:, half:] @ self.E2
        dphi = np.angle(Z2 * np.conj(Z1))
        f_err = dphi * SR / (np.pi * self.N)
        eps_tone = f_err / self.ws.freqs[None, :]
        w_tone = np.abs(Z1 + Z2)
        rows = np.arange(len(segs))[:, None]
        e = eps_tone[rows, tones]
        w = w_tone[rows, tones] + 1e-12
        eps = (e * w).sum(axis=1) / w.sum(axis=1)
        eps[~ok] = np.nan
        return eps

    def bits_from_si(self, si):
        shifts = np.arange(self.bps - 1, -1, -1)
        return ((si[:, None] >> shifts[None, :]) & 1).astype(np.uint8).ravel()

    def section_metrics(self, frames_si):
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


# ===========================================================================
# Trajectory builders (verbatim from h5)
# ===========================================================================
def build_tau_timing(d_row, fs_sym, bw_hz):
    drift = np.concatenate([[0.0], np.cumsum(d_row.astype(np.float64))[:-1]])
    k = min(MED_KERNEL, len(drift) - (1 - len(drift) % 2))
    if k >= 3:
        drift = medfilt(drift, kernel_size=k)
    wn = min(0.99, bw_hz / (fs_sym / 2.0))
    b, a = butter(2, wn)
    if len(drift) > 3 * max(len(a), len(b)):
        drift = filtfilt(b, a, drift)
    return drift


def build_tau_freq(eps, fs_sym, bw_hz, N):
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
    tau = -N * np.concatenate([[0.0], np.cumsum(e)[:-1]])
    return tau


# ===========================================================================
# Stage 1: global sync + resample (cached)
# ===========================================================================
def stage_sync(recording, tag):
    audio_npy = RESULTS_DIR / f"x9_audio_nom_{tag}.npy"
    meta_json = RESULTS_DIR / f"x9_sync_meta_{tag}.json"
    if audio_npy.exists() and meta_json.exists():
        log(f"[sync] cache hit: {audio_npy.name}")
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
    meta = {"sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
            "align": align, "sounder": sounder}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    np.save(audio_npy, audio_nom)
    meta_json.write_text(json.dumps(meta, indent=2, default=float))
    log(f"[sync] done {time.time()-t0:.0f}s: clock {sync['speed']:.6f}x align "
        f"{align:+d} flutter {sounder.get('flutter_wrms_pct', float('nan')):.3f}% "
        f"SNRmed {sounder.get('snr_db_median', float('nan')):.1f}dB")
    return audio_nom, meta


def frame_window(audio_nom, eng, start, align):
    st = int(start) + align
    pad = int(WS_WINDOW_PAD * SR)
    lo = max(0, st - pad)
    hi = min(len(audio_nom), st + eng.flen + pad)
    return np.asarray(audio_nom[lo:hi], dtype=np.float64)


# ===========================================================================
# Stage 2: pass-1 greedy demod, cached (records d, lock, gap, ds, eps, contrast)
# ===========================================================================
WS_SECTIONS = ("m8_ctrl_m16k1_rs191", "m8_m32k2_rs127", "m8_m32k2_rs159",
               "m8_m16k2_rs159", "m8_m16k2_rs191", "m8_m16k3_rs159")


def stage_demod(audio_nom, meta, tag):
    cache_npz = RESULTS_DIR / f"x9_demod_cache_{tag}.npz"
    if cache_npz.exists():
        log(f"[demod] cache hit: {cache_npz.name}")
        return dict(np.load(cache_npz, allow_pickle=False))
    manifest = json.loads(MANIFEST_PATH.read_text())
    secmap = {s["name"]: s for s in manifest["ws_payloads"]}
    sounder = meta["sounder"]
    align = meta["align"]
    store = {}
    t_all = time.time()
    for name in WS_SECTIONS:
        sec = secmap[name]
        eng = WSEngineK3(sec, sounder)
        nF = eng.meta["n_frames"]
        ds_arr = np.zeros(nF, np.int64)
        si_arr = np.zeros((nF, eng.nsym), np.int64)
        d_arr = np.zeros((nF, eng.nsym), np.int64)
        lock_arr = np.zeros((nF, eng.nsym), np.float64)
        gap_arr = np.zeros((nF, eng.nsym), np.float64)
        ok_arr = np.zeros((nF, eng.nsym), bool)
        eps_arr = np.zeros((nF, eng.nsym), np.float64)
        t0 = time.time()
        for fi, start in enumerate(sec["frame_starts"]):
            yy = frame_window(audio_nom, eng, start, align)
            ds = hc.find_preamble(yy.astype(np.float32), eng.ws.preamble_seconds)
            si, d, lock, gap, ok, eps = eng.demod_frame_pass1(yy, ds)
            ds_arr[fi] = ds
            si_arr[fi], d_arr[fi], lock_arr[fi] = si, d, lock
            gap_arr[fi], ok_arr[fi], eps_arr[fi] = gap, ok, eps
        m = eng.section_metrics(list(si_arr))
        log(f"[demod] {name:20s} {eng.ws.name:19s} K={eng.K} frames={nF:3d} "
            f"rawBER={m['raw_ber']:.5f} cwFail={m['rs_codewords_failed']}/"
            f"{eng.meta['n_codewords']} exact={m['byte_exact']} ({time.time()-t0:.0f}s)")
        store[f"{name}/ds"] = ds_arr
        store[f"{name}/si"] = si_arr
        store[f"{name}/d"] = d_arr
        store[f"{name}/lock"] = lock_arr
        store[f"{name}/gap"] = gap_arr
        store[f"{name}/ok"] = ok_arr
        store[f"{name}/eps"] = eps_arr
        store[f"{name}/baseline"] = np.array(
            [m["raw_ber"], m["rs_codewords_failed"], m["byte_errors"],
             float(m["byte_exact"])])
    np.savez_compressed(cache_npz, **store)
    log(f"[demod] pass-1 cached -> {cache_npz.name} ({time.time()-t_all:.0f}s)")
    return store


# ===========================================================================
# Stage 3: FORENSICS
# ===========================================================================
def stage_forensics(audio_nom, meta, cache, tag):
    manifest = json.loads(MANIFEST_PATH.read_text())
    secmap = {s["name"]: s for s in manifest["ws_payloads"]}
    sounder = meta["sounder"]
    forensics = {}
    log("\n[forensics] per-section failure classification")
    for name in WS_SECTIONS:
        sec = secmap[name]
        eng = WSEngineK3(sec, sounder)
        d = cache[f"{name}/d"]        # (nF, nsym) chosen offset
        lock = cache[f"{name}/lock"]
        gap = cache[f"{name}/gap"]
        ok = cache[f"{name}/ok"]
        si = cache[f"{name}/si"]
        eps = cache[f"{name}/eps"]
        ds = cache[f"{name}/ds"]
        nF, nsym = d.shape

        # --- per-symbol error map (bits): compare decoded vs truth ---
        err_per_sym = np.zeros((nF, nsym), np.int64)
        for fi in range(nF):
            rb = eng.bits_from_si(si[fi]).reshape(nsym, eng.bps)
            tb = np.asarray(eng.frames_bits_ref[fi], np.uint8)
            nb = nsym * eng.bps
            if len(tb) < nb:
                tb = np.concatenate([tb, np.zeros(nb - len(tb), np.uint8)])
            tb = tb[:nb].reshape(nsym, eng.bps)
            err_per_sym[fi] = (rb != tb).sum(axis=1)
        sym_wrong = (err_per_sym > 0)

        # --- timing: cumulative greedy drift per frame, in samples ---
        drift = np.cumsum(d, axis=1)  # (nF, nsym) integrated offset
        # how far the grid wanders within a frame (samples)
        drift_span = drift.max(axis=1) - drift.min(axis=1)
        drift_total = drift[:, -1]   # net pull by end of frame
        # convert to fraction of a symbol N
        drift_span_sym = drift_span / eng.N

        # --- correlation: does error follow grid drift? (timing-slip tell) ---
        # rate of grid offset change |d| -- when the grid is slipping, |d| spikes
        absd = np.abs(d)
        # error rate vs |d|: among symbols where |d|>=2, what's the symbol-error rate?
        slip_mask = absd >= 2
        ber_slip = sym_wrong[slip_mask].mean() if slip_mask.any() else float("nan")
        ber_noslip = sym_wrong[~slip_mask].mean() if (~slip_mask).any() else float("nan")

        # --- error vs intra-frame position (does BER rise late in the frame?) ---
        ber_by_pos = sym_wrong.mean(axis=0)  # (nsym,) avg over frames
        first_third = ber_by_pos[:nsym // 3].mean()
        last_third = ber_by_pos[-nsym // 3:].mean()

        # --- error vs frame index (does BER rise deep into the section?) ---
        ber_by_frame = sym_wrong.mean(axis=1)
        ber_frame_corr = float(np.corrcoef(np.arange(nF), ber_by_frame)[0, 1]) if nF > 2 else float("nan")

        # --- contrast / lock health: is the detector confident but wrong? ---
        lock_ok = lock[ok]
        gap_ok = gap[ok]
        # lock of correct vs wrong symbols
        lock_correct = lock[ok & ~sym_wrong]
        lock_wrong = lock[ok & sym_wrong]

        # --- eps (clock) statistics ---
        eps_rms = float(np.sqrt(np.nanmean(np.clip(eps, -EPS_CLIP, EPS_CLIP) ** 2)))

        # --- preamble offset spread across frames ---
        ds_spread = int(ds.max() - ds.min())

        # --- per-tone contrast over time: redo the demod at the winning grid,
        #     measure mean tone-vs-guard contrast across the band to check EQ.
        #     (cheap: reuse the cached gap; per-tone needs a re-run -> sample 3 frames)
        # error bunching metric: runs of consecutive wrong symbols
        def max_run(row):
            m = 0; c = 0
            for v in row:
                c = c + 1 if v else 0
                m = max(m, c)
            return m
        runs = [max_run(sym_wrong[fi]) for fi in range(nF)]
        mean_max_run = float(np.mean(runs))

        # --- classification logic ---
        # timing-slip signature: errors cluster where |d| spikes / where drift wanders,
        #   AND BER rises late in frame / deep in section.
        # EQ/level signature: certain tones always weak (would show in per-tone, but
        #   here proxied by: high BER uniform across positions + lock_wrong not >> noise).
        # random: BER flat vs drift, flat vs position, lock barely separates.
        slip_ratio = (ber_slip / ber_noslip) if (ber_noslip and ber_noslip > 0) else float("inf")
        late_ratio = (last_third / first_third) if first_third > 0 else float("inf")
        lock_sep = (float(np.mean(lock_correct)) - float(np.mean(lock_wrong))) if (
            len(lock_correct) and len(lock_wrong)) else float("nan")

        classification = _classify(
            ber=cache[f"{name}/baseline"][0], slip_ratio=slip_ratio,
            late_ratio=late_ratio, drift_span_sym=float(np.median(drift_span_sym)),
            ber_frame_corr=ber_frame_corr, lock_sep=lock_sep,
            mean_max_run=mean_max_run, nsym=nsym)

        forensics[name] = {
            "ws": eng.ws.name, "K": eng.K, "n_frames": int(nF), "nsym": int(nsym),
            "baseline_raw_ber": float(cache[f"{name}/baseline"][0]),
            "baseline_cw_failed": int(cache[f"{name}/baseline"][1]),
            "ds_spread_samples": ds_spread,
            "drift_span_sym_median": float(np.median(drift_span_sym)),
            "drift_span_sym_max": float(np.max(drift_span_sym)),
            "drift_total_median_samples": float(np.median(drift_total)),
            "eps_rms": eps_rms,
            "ber_at_slip_d>=2": float(ber_slip),
            "ber_no_slip": float(ber_noslip),
            "slip_ratio_ber": float(slip_ratio),
            "ber_first_third": float(first_third),
            "ber_last_third": float(last_third),
            "late_over_early_ratio": float(late_ratio),
            "ber_vs_frame_corr": ber_frame_corr,
            "lock_mean_correct": float(np.mean(lock_correct)) if len(lock_correct) else None,
            "lock_mean_wrong": float(np.mean(lock_wrong)) if len(lock_wrong) else None,
            "lock_separation": lock_sep,
            "mean_max_error_run": mean_max_run,
            "classification": classification,
        }
        log(f"  {name:20s} BER={forensics[name]['baseline_raw_ber']:.4f} "
            f"driftSpan={forensics[name]['drift_span_sym_median']:.2f}sym "
            f"slipBERratio={slip_ratio:.2f} late/early={late_ratio:.2f} "
            f"lockSep={lock_sep:.3f} maxRun={mean_max_run:.1f} -> {classification}")
    return forensics


def _classify(ber, slip_ratio, late_ratio, drift_span_sym, ber_frame_corr,
              lock_sep, mean_max_run, nsym):
    """Heuristic failure classifier."""
    signs = []
    # timing slip: error rate much higher where grid slips, or grid wanders a lot,
    #   or BER climbs late in frame, or BER climbs across frames
    if slip_ratio > 1.5 and np.isfinite(slip_ratio):
        signs.append("err-follows-slip")
    if drift_span_sym > 0.4:
        signs.append("grid-wanders>0.4sym")
    if late_ratio > 1.5 and np.isfinite(late_ratio):
        signs.append("BER-rises-late-in-frame")
    if np.isfinite(ber_frame_corr) and ber_frame_corr > 0.4:
        signs.append("BER-rises-across-frames")
    timing_signs = len(signs)
    # EQ/random: detector confident-but-wrong (lock barely separates correct/wrong)
    eq_random = (np.isfinite(lock_sep) and lock_sep < 0.05)
    if timing_signs >= 1 and not eq_random:
        return f"TIMING-SLIP (recoverable) [{'|'.join(signs)}]"
    if timing_signs >= 1 and eq_random:
        return f"MIXED timing+confident-error [{'|'.join(signs)}; lockSep={lock_sep:.3f}]"
    if eq_random:
        return f"EQ/RANDOM (detector confident but wrong, lockSep={lock_sep:.3f})"
    return f"INDETERMINATE (BER={ber:.3f}, weak signatures)"


# ===========================================================================
# Stage 4: RESCUE
# ===========================================================================
def _crc_guard_decode(rx_mat, rel_cw, meta, expected, crc_table, erase_fn):
    """Errors-and-erasures RS decode with manifest-CRC32 miscorrection guard.
    Returns recovered packed bytes + stats. Truth (expected) only for scoring;
    crc_table is the receiver-side guard (no truth leak)."""
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    recovered = bytearray()
    cw_failed = 0
    miscorrected = 0
    n_erase = 0
    crc_rejects = 0
    for i in range(n_cw):
        epos = erase_fn(rel_cw[i]) if erase_fn else []
        n_erase += len(epos)
        try:
            if epos:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()), erase_pos=epos)[0]
            else:
                dec = rsc.decode(bytearray(rx_mat[i].tobytes()))[0]
            msg = bytes(dec)
            crc_ok = (i >= len(crc_table)) or ((zlib.crc32(msg) & 0xFFFFFFFF) == crc_table[i])
            if not crc_ok:
                miscorrected += 1
                crc_rejects += 1
            recovered += msg
        except (ReedSolomonError, Exception):
            cw_failed += 1
            recovered += bytes(rs_k)
    out = bytes(recovered)[:meta["payload_len"]]
    byte_err = sum(a != b for a, b in zip(out, expected)) + abs(len(out) - len(expected))
    return {
        "rs_codewords_failed": cw_failed,
        "miscorrected_cw": miscorrected,
        "crc_rejected_cw": crc_rejects,
        "mean_erasures_per_cw": n_erase / max(1, n_cw),
        "byte_errors": int(byte_err),
        "byte_exact": out == expected,
        "recovered_packed": out,
    }


def _make_frac_erase(frac, meta):
    twot = meta["rs_n"] - meta["rs_k"]
    F = int(round(frac * twot))
    if F == 0:
        return None
    return lambda rel: sorted(int(i) for i in np.argsort(rel)[:F])


def _steered_demod_section(audio_nom, sec, eng, cache, sounder, align, bw, traj,
                           two_pass=False):
    """Run the trajectory-steered demod over all frames; return bits_mat,
    lock_mat, gap_mat. traj in {'timing','freq'}. two_pass: use pass-1 d for the
    first trajectory, then re-derive d from the steered decode and refit."""
    name = sec["name"]
    dmat = cache[f"{name}/d"]
    eps_mat = cache[f"{name}/eps"]
    ds_arr = cache[f"{name}/ds"]
    nF = eng.meta["n_frames"]
    si_mat = np.zeros((nF, eng.nsym), np.int64)
    lock_mat = np.zeros((nF, eng.nsym), np.float64)
    gap_mat = np.zeros((nF, eng.nsym), np.float64)
    for fi, start in enumerate(sec["frame_starts"]):
        yy = frame_window(audio_nom, eng, start, align)
        if traj == "freq":
            tau = build_tau_freq(eps_mat[fi], eng.fs_sym, bw, eng.N)
        else:
            tau = build_tau_timing(dmat[fi], eng.fs_sym, bw)
        si, lock, gap, dsteer = eng.demod_frame_steered_instr(yy, int(ds_arr[fi]), tau)
        if two_pass:
            # refine: the steered grid's own residual offsets dsteer -> new traj
            d_eff = dmat[fi] + dsteer  # combine first-pass and residual
            tau2 = build_tau_timing(d_eff, eng.fs_sym, bw)
            si, lock, gap, _ = eng.demod_frame_steered_instr(yy, int(ds_arr[fi]), tau2)
        si_mat[fi] = si
        lock_mat[fi] = lock
        gap_mat[fi] = gap
    bits_mat = np.stack([eng.bits_from_si(si_mat[fi]) for fi in range(nF)])
    return bits_mat, lock_mat, gap_mat, si_mat


def stage_rescue(audio_nom, meta, cache, tag):
    manifest = json.loads(MANIFEST_PATH.read_text())
    secmap = {s["name"]: s for s in manifest["ws_payloads"]}
    sounder = meta["sounder"]
    align = meta["align"]

    # Sweep configurations. The PROVEN combo policy (m8_decode) is
    # bw=0.25, traj=timing, frac:0.25|gap|mean. We sweep around it.
    BWS = [0.1, 0.25, 0.5, 1.0, 2.0]
    TRAJS = ["timing", "freq"]
    ERASE_FRACS = [0.0, 0.25, 0.5]   # 0.0 = errors-only
    METRICS = ["gap", "lock"]
    AGGS = ["mean", "min"]
    TWO_PASS = [False, True]

    # target rungs (M16 K1/K2/K3 -- the fixed-grid failures); also re-verify M32
    TARGETS = ["m8_ctrl_m16k1_rs191", "m8_m16k2_rs159", "m8_m16k2_rs191",
               "m8_m16k3_rs159", "m8_m32k2_rs159", "m8_m32k2_rs127"]

    rescue = {}
    for name in TARGETS:
        sec = secmap[name]
        eng = WSEngineK3(sec, sounder)
        meta_sec = sec["meta"]
        crc_table = sec.get("crc32_codewords", [])
        expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        baseline = cache[f"{name}/baseline"]
        log(f"\n[rescue] {name} ({eng.ws.name}, K={eng.K}) baseline BER "
            f"{baseline[0]:.4f} cwFail {int(baseline[1])}/{meta_sec['n_codewords']}")

        best = None
        trials = []
        # cache steered demods per (bw, traj, two_pass) to avoid recompute over erase params
        for traj in TRAJS:
            for bw in BWS:
                for tp in TWO_PASS:
                    bits_mat, lock_mat, gap_mat, si_mat = _steered_demod_section(
                        audio_nom, sec, eng, cache, sounder, align, bw, traj, two_pass=tp)
                    # raw BER of the steered decode
                    m_raw = eng.section_metrics(list(si_mat))
                    for metric in METRICS:
                        rel = gap_mat if metric == "gap" else lock_mat
                        for agg in AGGS:
                            rx_mat, rel_cw = _stream_bytes_and_rel(
                                bits_mat, rel, meta_sec, eng.bps, agg)
                            for ef in ERASE_FRACS:
                                erase_fn = _make_frac_erase(ef, meta_sec) if ef > 0 else None
                                res = _crc_guard_decode(
                                    rx_mat, rel_cw, meta_sec, expected, crc_table, erase_fn)
                                cfg = (f"traj={traj}|bw={bw}|2pass={tp}|"
                                       f"frac={ef}|{metric}|{agg}")
                                row = {
                                    "cfg": cfg, "traj": traj, "bw": bw, "two_pass": tp,
                                    "erase_frac": ef, "metric": metric, "agg": agg,
                                    "steered_raw_ber": m_raw["raw_ber"],
                                    "rs_codewords_failed": res["rs_codewords_failed"],
                                    "miscorrected_cw": res["miscorrected_cw"],
                                    "crc_rejected_cw": res["crc_rejected_cw"],
                                    "mean_erasures_per_cw": res["mean_erasures_per_cw"],
                                    "byte_errors": res["byte_errors"],
                                    "byte_exact": res["byte_exact"],
                                }
                                trials.append(row)
                                # selection: prefer byte_exact, then fewest cw failed,
                                # then fewest byte errors; CRC-clean required for a flip
                                key = (not res["byte_exact"], res["rs_codewords_failed"],
                                       res["byte_errors"], res["miscorrected_cw"])
                                if best is None or key < best[0]:
                                    best = (key, row, res["recovered_packed"])
        best_row = best[1]
        best_packed = best[2]
        # CRC-verify the headline result explicitly
        crc_verified = _crc_verify_full(best_packed, meta_sec, crc_table)
        rescue[name] = {
            "ws": eng.ws.name, "K": eng.K,
            "n_codewords": meta_sec["n_codewords"],
            "projected_net_bps": sec.get("projected_net_bps"),
            "baseline_raw_ber": float(baseline[0]),
            "baseline_cw_failed": int(baseline[1]),
            "best_cfg": best_row["cfg"],
            "best_steered_raw_ber": best_row["steered_raw_ber"],
            "best_cw_failed": best_row["rs_codewords_failed"],
            "best_byte_errors": best_row["byte_errors"],
            "best_byte_exact": best_row["byte_exact"],
            "best_miscorrected_cw": best_row["miscorrected_cw"],
            "best_crc_rejected_cw": best_row["crc_rejected_cw"],
            "best_mean_erasures_per_cw": best_row["mean_erasures_per_cw"],
            "crc_verified_all_codewords": crc_verified,
            "n_trials": len(trials),
            # keep a compact slice of the trial grid (best 12 by cw_failed)
            "top_trials": sorted(
                trials, key=lambda r: (not r["byte_exact"], r["rs_codewords_failed"],
                                       r["byte_errors"]))[:12],
        }
        flip = "*** BYTE-EXACT FLIP ***" if best_row["byte_exact"] else "still failed"
        log(f"  BEST: {best_row['cfg']} -> rawBER {best_row['steered_raw_ber']:.4f} "
            f"cwFail {best_row['rs_codewords_failed']}/{meta_sec['n_codewords']} "
            f"byteErr {best_row['byte_errors']} exact={best_row['byte_exact']} "
            f"crcVerified={crc_verified}  {flip}")
    return rescue


def _crc_verify_full(packed, meta, crc_table):
    """Independent CRC check: re-encode the recovered packed bytes into codeword
    messages exactly as the manifest expects, verify each message CRC32 against
    the table. Returns True only if ALL codewords match (full integrity)."""
    if not crc_table:
        return None
    rs_k = meta["rs_k"]
    n_cw = meta["n_codewords"]
    # The manifest CRC is zlib.crc32(padded[i*rs_k:(i+1)*rs_k]) where
    # padded = packed + zero-pad to a multiple of rs_k (see m8_master
    # _codeword_crcs). The recovered packed bytes ARE the concatenation of the
    # n_cw RS messages in order, so message i = padded[i*rs_k:(i+1)*rs_k].
    buf = bytearray(packed)
    pad = (-len(buf)) % rs_k
    buf += bytes(pad)
    ok = 0
    for i in range(n_cw):
        msg = bytes(buf[i * rs_k:(i + 1) * rs_k])
        if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) == crc_table[i]:
            ok += 1
    return ok == min(n_cw, len(crc_table))


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recording", default=str(CAPTURES_DIR / "m8_tape_mono_lossless.wav"))
    ap.add_argument("--stage", default="all",
                    choices=["all", "sync", "demod", "forensics", "rescue"])
    args = ap.parse_args()
    rec = pathlib.Path(args.recording)
    tag = rec.stem
    log(f"[main] recording={rec} stage={args.stage} seed={SEED}")

    audio_nom, meta = stage_sync(rec, tag)
    if args.stage == "sync":
        return
    cache = stage_demod(audio_nom, meta, tag)
    if args.stage == "demod":
        return

    out = {"recording": str(rec), "tag": tag, "seed": SEED,
           "sync": meta["sync"],
           "sounder": {k: v for k, v in meta["sounder"].items()
                       if k not in ("H_db", "snr_db_per_tone", "sounder_freqs")}}

    forensics = stage_forensics(audio_nom, meta, cache, tag)
    out["forensics"] = forensics
    if args.stage == "forensics":
        (DOSSIER / "R3_ws_rescue.json").write_text(json.dumps(out, indent=2, default=float))
        return

    rescue = stage_rescue(audio_nom, meta, cache, tag)
    out["rescue"] = rescue

    # headline: did we flip m8_m16k3_rs159 (1052 bps)?
    k3 = rescue.get("m8_m16k3_rs159", {})
    out["headline"] = {
        "m8_m16k3_rs159_byte_exact": bool(k3.get("best_byte_exact")),
        "m8_m16k3_rs159_crc_verified": k3.get("crc_verified_all_codewords"),
        "m8_m16k3_rs159_net_bps": k3.get("projected_net_bps"),
        "new_record_if_flipped": 1052.2,
        "prior_record_bps": 933.8,
        "any_ws_flip": sorted([n for n, r in rescue.items() if r.get("best_byte_exact")]),
    }
    DOSSIER.mkdir(parents=True, exist_ok=True)
    (DOSSIER / "R3_ws_rescue.json").write_text(json.dumps(out, indent=2, default=float))
    log(f"\n[done] wrote {DOSSIER / 'R3_ws_rescue.json'}")
    log(f"[HEADLINE] m8_m16k3_rs159 byte-exact={out['headline']['m8_m16k3_rs159_byte_exact']} "
        f"crc_verified={out['headline']['m8_m16k3_rs159_crc_verified']} | "
        f"any WS flip: {out['headline']['any_ws_flip'] or 'none'}")


if __name__ == "__main__":
    main()
