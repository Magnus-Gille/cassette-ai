"""x9_resampling_pll.py -- ladder-wide self-tracking receiver front-end (master9).

The Stage-1 "resampling timing PLL" of MASTER9_PLAN.md S2.2.3 / B_design.md S1.3,
as a drop-in front-end module importable by m9_decode.py.

WHAT IT REPLACES
----------------
h4_dqpsk.DQPSKScheme.demod tracks flutter with a per-symbol pilot EMA(alpha=0.5)
that snaps the analysis window to an INTEGER sample offset (`drift` clamp,
h4 lines 197-214).  R2 S2 measured that loop:
    raw per-symbol dtau std 16.5 us -> EMA 13.5 us -> decision-directed 5.4 us.
R6 S5.5 says beating the record by more than thin RS needs a "structurally better
timing front-end": continuous sub-sample tau-hat(t) tracking instead of an
integer snap.

THE UPGRADE (this module)
-------------------------
A two-pass resampling loop, the canonical UWA Stojanovic/Freitag two-stage move
(R5 S2.2), built on the SAME polyphase-resample mechanism the validated gate uses
(`x9_flutter_gate.channel_gate`: y = interp(t, t - tau, y)):

  Pass 1 -- pilot timing trajectory.  Run the proven h4 per-symbol complex DFT
    (exponent on the ABSOLUTE sample index, so window re-centering is phase-
    transparent) to read the unmodulated mid-band pilot's symbol-to-symbol
    differential phase dp.  Convert to per-symbol timing dtau = dp/(2*pi*f_pilot)
    and feed a SECOND-ORDER (PI) timing loop, loop BW = 30 Hz (R2 f90 = 28.6 Hz).
    The loop integrates dtau into an absolute, continuous tau-hat(t) at every
    sample, with a velocity (rate) state so it follows the 5-23.4 Hz residual
    flutter band a per-symbol EMA under-tracks.

  Resample.  Resample the frame audio onto t - tau-hat(t) with a polyphase /
    linear interpolator (np.interp, identical to channel_gate) BEFORE the final
    FFT.  Wideband flutter (every tone scaled by the same tau-dot) becomes a small
    residual CFO the differential decision and Stage-3 DD refine away.

  Pass 2 -- final per-symbol DFT on the resampled stream, differential decision,
    then h4's PROVEN one-shot decision-directed LS-slope refinement (Stage-3,
    kept verbatim).

STRICT SUPERSET GUARANTEE
-------------------------
With pll_bw_hz=0 (or a clean/zero-flutter input) the PLL contributes no timing
correction beyond the proven pilot loop, so the module reproduces the h4 EMA
result byte-for-byte (the M0 regression anchor).  The default front-end is the
resampling PLL; `front_end='ema'` falls back to the exact h4 loop for the
per-rung receiver sweep (MASTER9_PLAN S2.4).

API (honored by m9_decode.py)
-----------------------------
    pll = ResamplingPLLDemod(sch, pll_bw_hz=30.0, front_end='pll')
    bits, diag = pll.demod(win_audio, nd, refine=True)

`sch` is an h4_dqpsk.DQPSKScheme (any rung geometry: N256/N512, P, spacing).
`demod` has the SAME signature/return contract as DQPSKScheme.demod:
    returns (bits: np.ndarray[uint8-ish int], diag: dict) where diag carries
    'quadrants' (nd, P), 'dtau' (per-symbol residual, seconds), 'preamble_at',
    plus PLL diagnostics ('tau_hat_sym', 'resid_us_rms', 'rate_ppm').

Reads only.  No truth used inside demod.  Seeds N/A (deterministic).
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc  # noqa: E402
from h4_dqpsk import DQPSKScheme, FS  # noqa: E402


# ===========================================================================
# Second-order (PI) timing loop coefficients from a target loop bandwidth.
# ===========================================================================
def _pi_loop_gains(bw_hz: float, t_sym: float, zeta: float = 0.707):
    """Proportional/integral gains for a 2nd-order timing loop updated once per
    symbol (period t_sym).  Standard Gardner/Mengali normalized-BW design:
    theta = Bn*T/(zeta + 1/(4 zeta)); kp, ki from theta and damping zeta.
    Returns (kp, ki).  bw_hz<=0 -> (0,0): the loop contributes nothing (the EMA
    output already carries the timing), preserving the h4 superset property.
    """
    if bw_hz <= 0.0:
        return 0.0, 0.0
    bnt = bw_hz * t_sym                       # normalized loop BW (cycles/symbol)
    denom = zeta + 1.0 / (4.0 * zeta)
    theta = bnt / denom
    d = 1.0 + 2.0 * zeta * theta + theta * theta
    kp = (4.0 * zeta * theta) / d
    ki = (4.0 * theta * theta) / d
    return kp, ki


# ===========================================================================
# Resampling timing PLL demodulator -- strict superset of h4's EMA loop.
# ===========================================================================
class ResamplingPLLDemod:
    """Drop-in front-end wrapping an h4 DQPSKScheme.

    front_end:
      'pll'  (default) -- pilot-driven 2nd-order timing loop -> continuous
                          tau-hat(t) -> resample frame audio -> final DFT.
      'ema'             -- the exact proven h4 integer-drift EMA loop (fallback
                          for the per-rung receiver sweep, S2.4).
    """

    def __init__(self, sch: DQPSKScheme, *, pll_bw_hz: float = 30.0,
                 front_end: str = "pll", ema_alpha: float = 0.5,
                 zeta: float = 0.707):
        self.sch = sch
        self.pll_bw_hz = float(pll_bw_hz)
        self.front_end = front_end
        self.ema_alpha = float(ema_alpha)
        self.zeta = float(zeta)
        self.t_sym = sch.N / FS

    # -- name passthrough for logging --------------------------------------
    @property
    def name(self) -> str:
        return f"PLL({self.front_end},bw{self.pll_bw_hz:g})/{self.sch.name}"

    # ------------------------------------------------------------------
    # Per-symbol complex DFT on an ABSOLUTE sample basis (h4-identical).
    # `y` already aligned so symbol i starts at sample ds + i*N (+ optional
    # per-symbol integer offset `off[i]`).  Returns c[i, k] (total, nc).
    # ------------------------------------------------------------------
    def _dft_symbols(self, y, ds, total, off=None):
        sch = self.sch
        N, skip, Nw = sch.N, sch.skip, sch.Nw
        win = sch._win
        freqs = sch.freqs
        nc = sch.P + 1
        c = np.zeros((total, nc), np.complex128)
        for i in range(total):
            base = ds + i * N + (0 if off is None else int(off[i]))
            lo = base + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS         # ABSOLUTE: shifts transparent
            E = np.exp(-2j * np.pi * np.outer(freqs, tt))
            c[i] = E @ (seg * win)
        return c

    # ------------------------------------------------------------------
    # Stage-3 differential decision + proven one-shot DD refinement
    # (verbatim from h4_dqpsk.DQPSKScheme.demod).  dtau is the per-symbol
    # common-timing term to subtract (seconds, length total).
    # ------------------------------------------------------------------
    def _decide(self, c, dtau, refine: bool, *, return_quality: bool = False):
        sch = self.sch
        fd = sch.freqs[sch.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])               # (nd, nc)
        dphi = np.angle(d[:, sch.data_idx])             # (nd, P)
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
        if refine:
            res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            num = (res * fd[None, :]).sum(axis=1)
            den = (fd ** 2).sum()
            dtau_res = num / (2 * np.pi * den)
            dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
            q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
            dphi = dphi2
        if return_quality:
            # no-truth reliability: RMS angular distance from the decided
            # quadrant centers (smaller = cleaner constellation).  The
            # per-rung sweep selector (S2.4) uses this to pick a front-end.
            resd = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            quality = float(np.sqrt(np.mean(resd ** 2)))
            return q, quality
        return q

    # ==================================================================
    # The EMA fallback -- byte-identical to h4_dqpsk.DQPSKScheme.demod.
    # ==================================================================
    def _demod_ema(self, win_audio, nd, refine):
        sch = self.sch
        y = np.asarray(win_audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
        total = nd + 1
        nc = sch.P + 1
        N, skip, Nw = sch.N, sch.skip, sch.Nw
        fpil = sch.freqs[sch.pilot_idx]
        c = np.zeros((total, nc), np.complex128)
        dtau = np.zeros(total)
        drift = 0.0
        ema = self.ema_alpha
        sm = 0.0
        win = sch._win
        freqs = sch.freqs
        for i in range(total):
            base = ds + i * N + int(round(drift))
            lo = base + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS
            E = np.exp(-2j * np.pi * np.outer(freqs, tt))
            c[i] = E @ (seg * win)
            if i > 0:
                dp = float(np.angle(c[i, sch.pilot_idx] *
                                    np.conj(c[i - 1, sch.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
        q = self._decide(c, dtau, refine)
        return (sch.quadrants_to_bits(q),
                {"quadrants": q, "dtau": dtau[1:], "preamble_at": int(ds),
                 "front_end": "ema"})

    # ==================================================================
    # The resampling PLL front-end.
    #
    # DESIGNED AS A STRICT SUPERSET OF THE EMA LOOP: Pass 1 runs the EXACT
    # proven h4 integer-drift EMA loop to fix the per-symbol window placement
    # (the same `drift` clamp that won the record) AND read its per-symbol
    # `dtau` trajectory.  Pass 2 then drives a 2nd-order PI loop from that same
    # pilot trajectory and resamples the body onto t - tau-hat(t) to warp out
    # the SUB-SAMPLE residual the integer snap leaves.  Because the warp is
    # anchored to EMA's own integer-drift removal, on a clean/well-tracked seed
    # the residual warp is sub-sample-tiny and the decision matches EMA; on a
    # flutter-stressed seed the continuous tau-hat(t) follows the 5-23.4 Hz band
    # the integer EMA under-tracks (the whole point, R6 S5.5).
    # ==================================================================
    def _demod_pll(self, win_audio, nd, refine):
        sch = self.sch
        y = np.asarray(win_audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
        total = nd + 1
        N, skip, Nw = sch.N, sch.skip, sch.Nw
        fpil = sch.freqs[sch.pilot_idx]
        freqs = sch.freqs
        win = sch._win

        # ---- Pass 1: the PROVEN h4 integer-drift EMA loop ------------------
        # Identical to _demod_ema: gives the per-symbol window offset off[i]
        # (integer `drift`) and the EMA-smoothed per-symbol pilot dtau.  This is
        # the trajectory that won the 934 record; we anchor the resample to it.
        c1 = np.zeros((total, sch.P + 1), np.complex128)
        off = np.zeros(total)                      # integer window offset/symbol
        dtau_ema = np.zeros(total)                 # EMA-smoothed pilot dtau
        drift = 0.0
        ema = self.ema_alpha
        sm = 0.0
        for i in range(total):
            base = ds + i * N + int(round(drift))
            off[i] = int(round(drift))
            lo = base + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS
            E = np.exp(-2j * np.pi * np.outer(freqs, tt))
            c1[i] = E @ (seg * win)
            if i > 0:
                dp = float(np.angle(c1[i, sch.pilot_idx] *
                                    np.conj(c1[i - 1, sch.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau_ema[i] = sm
                drift -= dtau_ema[i] * FS
                drift = float(np.clip(drift, -200, 200))

        if self.pll_bw_hz <= 0.0 or total <= 1:
            # bw 0 -> pure EMA path (provable superset: identical to _demod_ema)
            q = self._decide(c1, dtau_ema, refine)
            resid = float(np.sqrt(np.mean((dtau_ema[1:] * 1e6) ** 2)))
            return (sch.quadrants_to_bits(q),
                    {"quadrants": q, "dtau": dtau_ema[1:], "preamble_at": int(ds),
                     "front_end": "pll", "tau_hat_sym": np.cumsum(dtau_ema)[1:],
                     "resid_us_rms": resid, "rate_ppm": 0.0})

        # ---- Pass 2: 2nd-order PI loop -> continuous tau-hat(t) -> resample -
        # The PI loop refines the EMA trajectory: its absolute timing state
        # `tau` integrates the EMA-smoothed increments with a rate state `v`,
        # giving a SMOOTH sub-sample trajectory between symbols that the integer
        # `drift` can only step in whole samples.  The resample warp is the
        # RESIDUAL between this smooth tau-hat and the integer window offset
        # Pass 1 already applied -- so we never re-apply the bulk timing, only
        # the fractional remainder, keeping the EMA superset property.
        kp, ki = _pi_loop_gains(self.pll_bw_hz, self.t_sym, self.zeta)
        tau = 0.0
        v = 0.0
        tau_sym = np.zeros(total)                  # absolute tau-hat (s) per sym
        for i in range(1, total):
            err = dtau_ema[i] - v
            v += ki * err
            tau += v + kp * err
            tau_sym[i] = tau

        # Warp the body onto the nominal grid: the signal at symbol i is delayed
        # by the absolute channel timing tau-hat[i] (= PI-smoothed cumulative
        # pilot dtau).  Pull it forward by sampling y at t + tau-hat(t), so after
        # the warp every symbol sits at the nominal ds + i*N and Pass-2 DFTs at
        # off=None.  This REPLACES Pass-1's integer drift snap with a continuous
        # sub-sample trajectory -- the resampling-PLL upgrade (R5 S2.2).
        sym_centers = ds + (np.arange(total) + 0.5) * N
        body_lo = ds
        body_hi = min(len(y), ds + total * N + N)
        tgrid = np.arange(body_lo, body_hi, dtype=np.float64)
        tau_t = np.interp(tgrid, sym_centers, tau_sym,
                          left=tau_sym[0], right=tau_sym[-1])
        src = np.clip(tgrid - tau_t * FS, 0.0, len(y) - 1.0)
        y2 = y.copy()
        y2[body_lo:body_hi] = np.interp(src, np.arange(len(y)), y)

        # Pass-2 DFT on the de-fluttered stream WITHOUT the integer drift (the
        # warp already placed the signal on the nominal grid).  Residual pilot
        # dtau is read again (small) for the differential decision + DD refine.
        c2 = self._dft_symbols(y2, ds, total, off=None)
        dtau_res = np.zeros(total)
        for i in range(1, total):
            dp = float(np.angle(c2[i, sch.pilot_idx] *
                                np.conj(c2[i - 1, sch.pilot_idx])))
            dtau_res[i] = dp / (2 * np.pi * fpil)
        q_pll, qual_pll = self._decide(c2, dtau_res, refine, return_quality=True)

        # ---- STRICT-SUPERSET SELECTOR (no truth) --------------------------
        # The resample is a strict win only when there is flutter to remove; in
        # a near-zero-flutter window (e.g. the timing-blind sim, R6 S2) the warp
        # adds a hair of interpolation noise.  Decide BOTH ways and keep the
        # cleaner constellation by the no-truth post-decision residual metric
        # (smaller RMS angular distance from quadrant centers = fewer marginal
        # symbols).  This guarantees the PLL front-end is NEVER worse than the
        # proven EMA loop on the metric it can see -- the explicit fallback of
        # MASTER9_PLAN S2.2.3, applied per-frame instead of globally.
        q_ema, qual_ema = self._decide(c1, dtau_ema, refine, return_quality=True)
        if qual_pll <= qual_ema:
            q, used, dtau_out = q_pll, "pll", dtau_res
        else:
            q, used, dtau_out = q_ema, "ema", dtau_ema

        resid_us_rms = float(np.sqrt(np.mean((dtau_out[1:] * 1e6) ** 2)))
        rate_ppm = float(np.median(np.diff(tau_sym[1:])) / self.t_sym * 1e6) \
            if total > 2 else 0.0
        return (sch.quadrants_to_bits(q),
                {"quadrants": q, "dtau": dtau_out[1:], "preamble_at": int(ds),
                 "front_end": used, "selector": {"q_ema": qual_ema,
                                                  "q_pll": qual_pll},
                 "tau_hat_sym": tau_sym[1:],
                 "resid_us_rms": resid_us_rms, "rate_ppm": rate_ppm})

    # ==================================================================
    def demod(self, win_audio, nd, refine: bool = True):
        if self.front_end == "ema":
            return self._demod_ema(win_audio, nd, refine)
        return self._demod_pll(win_audio, nd, refine)


# ===========================================================================
# Convenience: timing-residual stats for a section (for the M9 report).
# Re-derives the per-symbol pilot dtau std (raw), EMA-tracked, and PLL-residual
# the same way R2 S2 / h4 measure them, so the report numbers are apples-to-
# apples against R2_margins.md.
# ===========================================================================
def residual_stats(sch: DQPSKScheme, win_audio, nd, *, pll_bw_hz: float = 30.0):
    """Returns dict with raw/ema/pll per-symbol timing residual std (us) and
    the decision-directed residual, all measured on the SAME audio window.
    Mirrors R2 S2's definitions:
      raw  = std of the per-symbol pilot dtau (no smoothing)
      ema  = std after the proven EMA(alpha) smoother (h4)
      pll  = std of the PLL Pass-2 residual common-timing dtau
      ddir = std of the post-decision LS-slope residual dtau_res (Stage-3)
    """
    y = np.asarray(win_audio, np.float64)
    ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
    total = nd + 1
    fpil = sch.freqs[sch.pilot_idx]

    pll = ResamplingPLLDemod(sch, pll_bw_hz=pll_bw_hz, front_end="pll")
    c1 = pll._dft_symbols(y, ds, total, off=None)
    dpil = np.zeros(total)
    for i in range(1, total):
        dp = float(np.angle(c1[i, sch.pilot_idx] * np.conj(c1[i - 1, sch.pilot_idx])))
        dpil[i] = dp / (2 * np.pi * fpil)
    raw_us = float(np.std(dpil[1:]) * 1e6)

    # EMA-tracked residual (what h4 actually leaves before DD)
    ema = 0.5
    sm = 0.0
    ema_trace = np.zeros(total)
    for i in range(1, total):
        sm = (1 - ema) * dpil[i] + ema * sm
        ema_trace[i] = dpil[i] - sm        # residual after EMA prediction
    ema_us = float(np.std(ema_trace[1:]) * 1e6)

    # Run the actual PLL demod (with the strict-superset selector) and report
    # the per-symbol common-timing residual it leaves on the SELECTED stream.
    _bits, diag = pll.demod(y, nd, refine=True)
    pll_us = diag["resid_us_rms"]
    used = diag.get("front_end", "pll")

    # Decision-directed residual: the Stage-3 LS-slope residual the proven
    # refinement removes -- the quantity directly comparable to R2 S2's
    # "decision-directed 5.4 us".  Re-derive on the selected front-end's
    # constellation (q = decided quadrants, dtau = selected common-timing).
    fd = sch.freqs[sch.data_idx]
    if used == "pll":
        c2 = _pll_resampled_dft(pll, y, ds, total)
    else:
        c2 = _ema_dft(pll, y, ds, total)
    d = c2[1:, :] * np.conj(c2[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(diag["dtau"], fd)
    q = diag["quadrants"]
    res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    num = (res * fd[None, :]).sum(axis=1)
    den = (fd ** 2).sum()
    dtau_dd = num / (2 * np.pi * den)
    ddir_us = float(np.std(dtau_dd) * 1e6)

    return {"raw_us": raw_us, "ema_us": ema_us, "pll_us": pll_us,
            "ddir_us": ddir_us, "front_end": used, "n_sym": total - 1}


def _ema_dft(pll, y, ds, total):
    """Reproduce the EMA-loop's per-symbol c matrix (for residual_stats)."""
    sch = pll.sch
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    freqs = sch.freqs
    fpil = sch.freqs[sch.pilot_idx]
    c = np.zeros((total, sch.P + 1), np.complex128)
    drift = 0.0
    sm = 0.0
    ema = pll.ema_alpha
    for i in range(total):
        base = ds + i * N + int(round(drift))
        lo = base + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        c[i] = E @ (seg * win)
        if i > 0:
            dp = float(np.angle(c[i, sch.pilot_idx] * np.conj(c[i - 1, sch.pilot_idx])))
            sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
            drift -= sm * FS
            drift = float(np.clip(drift, -200, 200))
    return c


def _pll_resampled_dft(pll, y, ds, total):
    """Reproduce the PLL Pass-2 resampled c matrix (for residual_stats)."""
    sch = pll.sch
    N = sch.N
    c1 = _ema_dft(pll, y, ds, total)
    fpil = sch.freqs[sch.pilot_idx]
    dtau_ema = np.zeros(total)
    sm = 0.0
    ema = pll.ema_alpha
    for i in range(1, total):
        dp = float(np.angle(c1[i, sch.pilot_idx] * np.conj(c1[i - 1, sch.pilot_idx])))
        sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
        dtau_ema[i] = sm
    kp, ki = _pi_loop_gains(pll.pll_bw_hz, pll.t_sym, pll.zeta)
    tau = v = 0.0
    tau_sym = np.zeros(total)
    for i in range(1, total):
        err = dtau_ema[i] - v
        v += ki * err
        tau += v + kp * err
        tau_sym[i] = tau
    if pll.pll_bw_hz <= 0.0 or total <= 1:
        return c1
    sym_centers = ds + (np.arange(total) + 0.5) * N
    body_lo = ds
    body_hi = min(len(y), ds + total * N + N)
    tgrid = np.arange(body_lo, body_hi, dtype=np.float64)
    tau_t = np.interp(tgrid, sym_centers, tau_sym, left=tau_sym[0], right=tau_sym[-1])
    src = np.clip(tgrid - tau_t * FS, 0.0, len(y) - 1.0)
    y2 = y.copy()
    y2[body_lo:body_hi] = np.interp(src, np.arange(len(y)), y)
    return pll._dft_symbols(y2, ds, total, off=None)


if __name__ == "__main__":
    # Smoke test: clean no-channel decode of a tiny DQPSK section must be
    # byte-exact through BOTH front-ends (superset sanity).
    import m3_codec as codec
    from m3_codec import Rung
    from h4_dqpsk import build_section, nominal_frame_bits, _payload_slice, \
        PAD_LO_S, PAD_HI_S

    sch = DQPSKScheme(10, 512, 8)
    payload = _payload_slice(90112, 2040)
    rung = Rung(name="smoke", M=10, K=1, rs_n=255, rs_k=127, frame_bytes=510)
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)
    y = section.astype(np.float64)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    for fe in ("ema", "pll"):
        dem = ResamplingPLLDemod(sch, front_end=fe)
        rx = []
        for fi, st in enumerate(starts):
            nd = sch.nsym_data(nom_bits[fi])
            flen = len(frame_audios[fi])
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(y), st + flen + pad_hi)
            bits, _ = dem.demod(y[w_lo:w_hi], nd)
            rx.append(bits)
        rec = codec.decode_payload(rx, meta)
        print(f"  [{dem.name:28s}] no-channel byte_exact={rec == payload} "
              f"cw_failed={codec.decode_payload.last_codewords_failed}")
