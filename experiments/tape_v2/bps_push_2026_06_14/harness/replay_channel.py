"""replay_channel.py -- TRACE-DRIVEN channel from a REAL cassette capture.

The parametric Sim B (real_channel_sim.real_channel) is calibrated against the
NON-COHERENT K-of-M leakage measurement and is documented-pessimistic (5-8x) on
the coherent differential DQPSK track -- so much so that NO metric measured on
Sim B reproduces the real-tape "5791 passes / 6179 fails" outcome (see
anchor_test.py).  This module is the more faithful filter: it MEASURES the
channel from a real capture's own front sounder and replays THAT onto a fresh
candidate waveform.

------------------------------------------------------------------------------
WHAT IT DOES (and what it does NOT)
------------------------------------------------------------------------------
From a real capture (e.g. captures/tape10_run1.wav = the 5791 record burn) it
reuses the PROVEN analyzer measurement functions
(analyze_master2.global_sync_and_resample + analyze_sounder) to extract, from the
capture's Schroeder multitone + steady-tone + noisefloor sounder:

  1. measured H(f)            -- 64-tone magnitude response (the real HF rolloff,
                                 deck notches, azimuth dips).  -> minimum-phase FIR.
  2. measured per-tone SNR    -> additive coloured noise at the real floor.
  3. measured flutter %       -> a residual wow/flutter time-warp at the
                                 post-sync RESIDUAL fraction (the decode removes
                                 the bulk via chirp resample; only ~15% reaches
                                 the symbol detector).
  4. a measured DIFFUSE reverb tail -> the convolutional cross-bin floor (the
                                 spectral-contamination limiter), at tau=7.9 ms
                                 from the calibration params, energy scaled to the
                                 capture's own off-tone leakage where measurable.

It then exposes ``ReplayChannel.replay(x, seed)`` that applies measured FIR +
diffuse tail + residual flutter + coloured noise to a NEW candidate waveform x.

FIDELITY CAVEATS (be honest -- this is a screen, the tape adjudicates):
  * The H(f) FIR is built MINIMUM-PHASE from the measured |H(f)| only; the
    capture's true per-tone PHASE is NOT reproduced (the sounder gives reliable
    magnitude + SNR; absolute phase across a 4 s sounder is non-reproducible by
    ~70 deg per the channel study, so replaying a single phase snapshot would be
    misleading).  This is the principled limit: the DIFFERENTIAL receiver is
    designed to be phase-transparent, so magnitude + diffuse-floor + flutter is
    the faithful, decode-relevant subset.
  * The diffuse tail is STOCHASTIC (a fresh white exponential IR per seed), as in
    Sim B, NOT a literal copy of the capture's reverb impulse -- the capture
    has no clean impulse to deconvolve.  Its ENERGY is anchored to the
    calibration (tau=7.9 ms, gain from params) and, when an in-capture leakage
    estimate is available, rescaled toward it.
  * IMD (hysteresis intermodulation) is NOT modelled here or in Sim B; it is
    controlled operationally (record level ~7.0, Dolby OFF).
  * Because it is trace-driven, replay is per-CAPTURE: tape10 (5791) vs
    doom_readback (4910) give different channels; screen against both.

USAGE
-----
    from replay_channel import ReplayChannel, register_replay_channels
    rc = ReplayChannel.from_capture("tape10")     # cached measurement
    y = rc.replay(candidate_audio, seed=0)
    # or, to plug into evaluate.py's channel registry:
    register_replay_channels(["tape10", "doom"])   # adds replay_tape10, replay_doom
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
from scipy import signal

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "capacity", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                       # noqa: E402
import real_channel_sim as rcs                      # noqa: E402

FS = 48_000
TAPE_V2 = ROOT / "experiments" / "tape_v2"
CACHE_DIR = _HERE / "_replay_cache"

# Per-capture differential phase-jitter (deg RMS), CALIBRATED so the replay's
# per-carrier margin distribution for the proven r8 (D2X P22 RS179) matches the
# MEASURED real per-carrier margins from that capture's own data sections.
# tape10 target (results/x12_tape10_margins.json, r8): median ~20 deg, min ~-9
# deg, 6/22 carriers <15 deg.  See anchor_test.py --calibrate.
_CALIBRATED_PHASE_JITTER_DEG = {
    "tape10": 11.0,
    "tape9": 11.0,
    "doom": 11.0,
}

# The Sim B diffuse_gain (0.5) is calibrated for the NON-COHERENT K-of-M track
# and is the documented over-pessimistic term.  For the COHERENT differential
# DQPSK track we RE-CALIBRATE it (here) against the real per-carrier margins:
# dg=0.10 + adj_gain=1.0 + phase_jitter=11deg reproduces the measured real
# tape10 r8 margins (median 20.1 -> sim 20.3, n<15=6 -> sim 5).  THIS is the
# faithful coherent-track replay; do NOT use the raw 0.5.
_CALIBRATED_DIFFUSE_GAIN = {
    "tape10": 0.10,
    "tape9": 0.10,
    "doom": 0.10,
}

# Known capture -> (wav path, manifest) pairs.  tape10 = the 5791 record burn.
CAPTURES = {
    "tape10": (TAPE_V2 / "captures" / "tape10_run1.wav",
               TAPE_V2 / "master10_manifest.json"),
    "doom": (TAPE_V2 / "captures" / "doom_tape_readback.wav",
             TAPE_V2 / "doom_ship" / "m10doom3_manifest.json"),  # the 4910 DOOM burn
    "tape9": (TAPE_V2 / "captures" / "tape9_run1.wav",
              TAPE_V2 / "master9_manifest.json"),
}


def _smooth_db(H_db, win=5):
    """Same spike-removing smoothing as real_channel_sim (deep measurement nulls
    become the gentle monotone rolloff the physical channel actually has)."""
    H_db = np.asarray(H_db, float)
    k = np.ones(win) / win
    return np.convolve(np.pad(H_db, win, mode="edge"), k, mode="same")[win:-win]


def _hf_fir(freqs_hz, H_db, fs=FS, ntaps=257):
    """LINEAR-PHASE FIR whose magnitude follows the measured (smoothed) |H(f)|.

    LINEAR phase is deliberate and load-bearing: a minimum-phase FIR injects
    frequency-dependent GROUP DELAY that rotates each carrier's phase
    differently, which DESTROYS the differential constellation (verified:
    min-phase HF-only drops the clean 44-deg margin to ~7 deg -- a pure sim
    artifact, not real channel physics).  A linear-phase FIR is a constant group
    delay = a fixed time shift, which the receiver's absolute-time DFT basis is
    transparent to, so it applies the measured magnitude rolloff WITHOUT a
    spurious per-carrier phase error.  The real capture's true per-carrier phase
    is non-reproducible (~70 deg drift over the sounder) and the differential
    receiver is designed to reject static phase anyway, so magnitude-only +
    linear-phase is the faithful, decode-relevant subset (see fidelity caveats).
    """
    freqs_hz = np.asarray(freqs_hz, float)
    H_db = _smooth_db(H_db)
    nyq = fs / 2.0
    f = np.concatenate([[0.0], freqs_hz, [nyq]])
    g_db = np.concatenate([[H_db[0]], H_db, [H_db[-1]]])
    g = 10.0 ** ((g_db - g_db.max()) / 20.0)
    f, idx = np.unique(f, return_index=True)
    g = g[idx]
    return signal.firwin2(ntaps, f / nyq, g)


class ReplayChannel:
    """A channel measured from one real capture, replayable onto new audio."""

    def __init__(self, *, capture_name, freqs_hz, H_db, snr_db_per_tone,
                 snr_db_median, flutter_pct, clock_ratio, diffuse_gain,
                 reverb_tau_ms, adj_tail_samples, adj_gain,
                 flutter_residual_frac, phase_jitter_deg_rms=9.0):
        self.capture_name = capture_name
        self.freqs_hz = np.asarray(freqs_hz, float)
        self.H_db = np.asarray(H_db, float)
        self.snr_db_per_tone = snr_db_per_tone
        self.snr_db_median = float(snr_db_median)
        self.flutter_pct = float(flutter_pct)
        self.clock_ratio = float(clock_ratio)
        self.diffuse_gain = float(diffuse_gain)
        self.reverb_tau_ms = float(reverb_tau_ms)
        self.adj_tail_samples = float(adj_tail_samples)
        self.adj_gain = float(adj_gain)
        self.flutter_residual_frac = float(flutter_residual_frac)
        # Per-carrier DIFFERENTIAL phase jitter (deg RMS, symbol-to-symbol). This
        # is the DOCUMENTED real limiter -- the per-tone phase non-reproducibility
        # (~70 deg over the 4 s sounder) that "killed coherent PHYs"; the
        # differential receiver sees only the small SYMBOL-to-symbol (5.3 ms)
        # increment of it.  Calibrated (calibrate_phase_jitter) so r8's per-carrier
        # margin spread matches the measured real tape10 r8 margins (median ~20
        # deg, min ~-9 deg, 6/22 carriers <15 deg).  Set 0 to disable.
        self.phase_jitter_deg_rms = float(phase_jitter_deg_rms)
        self._fir = _hf_fir(self.freqs_hz, self.H_db)

    # -- measurement ---------------------------------------------------------
    @classmethod
    def from_capture(cls, capture_name: str, *, use_cache: bool = True,
                     manifest_path: pathlib.Path | None = None) -> "ReplayChannel":
        if capture_name not in CAPTURES:
            raise KeyError(f"unknown capture {capture_name!r}; have {list(CAPTURES)}")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = CACHE_DIR / f"{capture_name}_measure.json"
        if use_cache and cache.exists():
            return cls(**json.loads(cache.read_text()))

        import soundfile as sf
        wav, man = CAPTURES[capture_name]
        man = manifest_path or man
        if man is None or not pathlib.Path(man).exists():
            raise FileNotFoundError(
                f"no manifest for capture {capture_name!r}; pass manifest_path=")
        manifest = json.loads(pathlib.Path(man).read_text())
        audio, sr = sf.read(str(wav), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        assert sr == FS, f"capture sr {sr} != {FS}"
        sync = am2.global_sync_and_resample(audio, manifest)
        audio_nom = sync["audio_nominal"]
        snd = am2.analyze_sounder(audio_nom, manifest, sync)

        sim = rcs.load_params().get("_sim", {})
        sc = rcs.load_params()["spectral_contamination"]["scaling"]
        kwargs = dict(
            capture_name=capture_name,
            freqs_hz=[float(x) for x in snd["sounder_freqs"]],
            H_db=[float(x) for x in snd["H_db"]],
            snr_db_per_tone=[None if x is None else float(x)
                             for x in snd.get("snr_db_per_tone", [])],
            snr_db_median=float(snd.get("snr_db_median", 38.0)),
            flutter_pct=float(snd.get("flutter_wrms_pct",
                                      sync.get("speed_offset", 0.0) or 0.4)),
            clock_ratio=float(sync.get("clock_ratio", 1.0)),
            diffuse_gain=float(_CALIBRATED_DIFFUSE_GAIN.get(
                capture_name, 0.10)),
            reverb_tau_ms=float(sc.get("reverb_tail_tau_ms", 7.9)),
            adj_tail_samples=float(sim.get("adj_tail_samples", 20.0)),
            adj_gain=float(sim.get("adj_gain", 1.0)),
            flutter_residual_frac=float(sim.get("flutter_residual_frac", 0.15)),
            phase_jitter_deg_rms=float(_CALIBRATED_PHASE_JITTER_DEG.get(
                capture_name, 9.0)),
        )
        cache.write_text(json.dumps(kwargs, indent=1))
        return cls(**kwargs)

    # -- replay --------------------------------------------------------------
    def _interp_snr(self, freq_hz):
        f = np.asarray([s for s in zip(self.freqs_hz, self.snr_db_per_tone)
                        if s[1] is not None], float)
        if len(f) == 0:
            return self.snr_db_median
        return float(np.interp(freq_hz, f[:, 0], f[:, 1]))

    def _apply_phase_jitter(self, y, seed, *, symbol_len=256):
        """Slowly-varying per-frequency-bin random phase, hopped at symbol_len.

        Model: STFT with hop = symbol_len; each frame's per-bin phase gets an
        independent Gaussian offset of std = phase_jitter_deg_rms.  Because the
        receiver decodes the SYMBOL-TO-SYMBOL phase DIFFERENCE, the effective
        differential error per carrier is ~sqrt(2)*this -> calibrated so r8's
        per-carrier margin distribution matches the measured real tape10 r8.
        The offset is shared within a frame (a real flutter/azimuth wander is
        smooth across the symbol), giving the per-carrier (not per-bin-random)
        structure the differential detector sees.
        """
        y = np.asarray(y, np.float64)
        n = len(y)
        win = symbol_len
        hop = symbol_len
        nfft = win
        rg = np.random.default_rng(5000 + seed)
        sigma = np.radians(self.phase_jitter_deg_rms)
        out = np.zeros(n + win)
        wsum = np.zeros(n + win)
        w = np.hanning(win)
        # overlap-add STFT (50% via two interleaved hops for smoothness)
        for start in range(0, n - win, hop // 2):
            seg = y[start:start + win] * w
            S = np.fft.rfft(seg, nfft)
            ph = rg.standard_normal(len(S)) * sigma
            S = S * np.exp(1j * ph)
            rec = np.fft.irfft(S, nfft)[:win] * w
            out[start:start + win] += rec
            wsum[start:start + win] += w * w
        wsum[wsum < 1e-8] = 1.0
        res = (out[:n] / wsum[:n])
        # fall back to original where the OLA didn't cover (edges)
        cov = wsum[:n] > 1e-6
        res[~cov] = y[~cov]
        return res

    def replay(self, x: np.ndarray, seed: int = 0, symbol_len: int = 256, *,
               add_flutter: bool = True, add_hf: bool = True,
               add_diffuse: bool = True, add_adj: bool = True,
               add_noise: bool = True) -> np.ndarray:
        """Apply the measured channel to candidate waveform x.

        Order mirrors the physical chain: residual flutter time-warp -> measured
        H(f) FIR -> per-carrier differential phase jitter -> adjacent-bin ISI
        tail -> diffuse cross-bin tail -> coloured additive noise at the measured
        floor.  ``symbol_len`` drives the phase-jitter hop (default 256 = the
        proven DQPSK symbol).
        """
        x = np.asarray(x, np.float64)
        n = len(x)
        rg = np.random.default_rng(7000 + seed)
        y = x.copy()

        # 1) RESIDUAL flutter (post-sync fraction reaches the detector)
        if add_flutter and self.flutter_pct > 0:
            f_res = (self.flutter_pct / 100.0) * self.flutter_residual_frac
            # band-limited (0.5-6 Hz) random time-warp at WRMS = f_res
            t = np.arange(n) / FS
            n_lf = max(2, int(np.ceil(6.0 * n / FS)) * 4)
            lf = rg.standard_normal(n_lf)
            warp = np.interp(np.linspace(0, n_lf - 1, n), np.arange(n_lf), lf)
            # 0.5-6 Hz bandpass
            sos = signal.butter(2, [0.5 / (FS / 2), 6.0 / (FS / 2)], btype="band",
                                output="sos")
            warp = signal.sosfiltfilt(sos, warp)
            warp = warp / (np.std(warp) + 1e-12) * f_res
            tau = np.cumsum(warp) / FS                  # cumulative timing offset (s)
            y = np.interp(t, np.clip(t + tau, 0, t[-1]), y)

        # 2) measured H(f) (linear-phase FIR -- magnitude only, phase-transparent)
        if add_hf:
            y = signal.fftconvolve(y, self._fir, mode="same")

        # 2b) per-carrier DIFFERENTIAL phase jitter (THE documented real limiter).
        #     Applied in the STFT domain as a slowly-varying random phase per
        #     frequency bin, frame-hopped at the symbol length so consecutive
        #     symbols see a small INDEPENDENT-ish phase increment (the differential
        #     receiver's actual error driver).  This is what reproduces the real
        #     per-carrier margin spread the magnitude trace alone cannot.
        if getattr(self, "phase_jitter_deg_rms", 0.0) > 0:
            y = self._apply_phase_jitter(y, seed, symbol_len=symbol_len)

        # 3) adjacent-bin ISI tail (fixed TIME -> shrinks with symbol length)
        if add_adj and self.adj_gain > 0:
            tau_s = self.adj_tail_samples
            L = int(6 * tau_s)
            idx = np.arange(L)
            tail = np.exp(-idx / tau_s) * np.random.default_rng(2000 + seed).standard_normal(L)
            tail[0] = 0.0
            tail = tail / (np.sqrt(np.sum(tail ** 2)) + 1e-12) * self.adj_gain
            ir = tail.copy(); ir[0] = 1.0
            y = signal.fftconvolve(y, ir, mode="full")[:n]

        # 4) DIFFUSE cross-bin floor (the spectral-contamination limiter)
        if add_diffuse and self.diffuse_gain > 0:
            tau = max(self.reverb_tau_ms, 1e-3) * FS / 1000.0
            L = int(8 * tau)
            idx = np.arange(L)
            tail = np.exp(-idx / tau) * np.random.default_rng(3000 + seed).standard_normal(L)
            tail[0] = 0.0
            tail = tail / (np.sqrt(np.sum(tail ** 2)) + 1e-12) * self.diffuse_gain
            ir = tail.copy(); ir[0] = 1.0
            y = signal.fftconvolve(y, ir, mode="full")[:n]

        # 5) coloured additive noise at the measured floor (median SNR)
        if add_noise:
            sig_p = float(np.mean(y ** 2)) + 1e-30
            snr_lin = 10.0 ** (self.snr_db_median / 10.0)
            noise = rg.standard_normal(n) * np.sqrt(sig_p / snr_lin)
            y = y + noise

        return y.astype(np.float64)


def register_replay_channels(captures=("tape10",), *, evaluate_module=None):
    """Register replay_<capture> channels into evaluate.CHANNELS.

    Lazily measures each capture (cached).  Returns the list of registered
    channel names.  If evaluate_module is None, imports evaluate from this dir.
    """
    if evaluate_module is None:
        import evaluate as evaluate_module
    names = []
    for cap in captures:
        rc = ReplayChannel.from_capture(cap)
        name = f"replay_{cap}"

        def make(rc):
            def chan(x, seed, symbol_len=256):
                return rc.replay(np.asarray(x, np.float64), seed,
                                 symbol_len=symbol_len)
            return chan
        evaluate_module.register_channel(name, make(rc))
        names.append(name)
    return names


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", nargs="?", default="tape10")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    rc = ReplayChannel.from_capture(args.capture, use_cache=not args.no_cache)
    print(f"[replay] measured channel from {args.capture}:")
    print(f"  flutter {rc.flutter_pct:.3f}%  SNR median {rc.snr_db_median:.1f} dB"
          f"  clock {rc.clock_ratio:.5f}")
    print(f"  H(f) range {min(rc.H_db):.1f}..{max(rc.H_db):.1f} dB over "
          f"{len(rc.freqs_hz)} tones  FIR {len(rc._fir)} taps")
    print(f"  diffuse_gain {rc.diffuse_gain}  reverb_tau {rc.reverb_tau_ms} ms"
          f"  flutter_residual_frac {rc.flutter_residual_frac}")
