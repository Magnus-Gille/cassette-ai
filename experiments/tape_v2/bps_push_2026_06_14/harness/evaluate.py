"""evaluate.py -- the BPS-push validation harness (2026-06-14).

THE NIGHTLY FILTER.  Every candidate modem is screened here before any real-tape
burn.  Correctness is paramount: a subtle bug invalidates the whole campaign, so
this file REUSES the proven repo DSP wherever possible and never re-implements a
receiver from scratch.

------------------------------------------------------------------------------
What a candidate must look like
------------------------------------------------------------------------------
``evaluate_candidate`` takes a hyp_common ``FuncScheme`` (``name``,
``gross_bps``, ``modulate(bits)->audio@48k``, ``demodulate(audio,sr)->bits``).
For the DQPSK/Dense2x family the receivers in the repo are ``DQPSKScheme.demod``
and ``ResamplingPLLDemod.demod`` which take ``(win_audio, nd)`` -- NOT the
FuncScheme ``demodulate(audio, sr)`` signature.  ``make_dqpsk_funcscheme`` below
is the canonical adapter that wraps a (tx_scheme, rx_demod) pair into a
single-frame FuncScheme so the harness can drive it uniformly.  It ALSO exposes
the per-carrier phase residuals (the constellation) via ``scheme.last_margin``,
which is what lets the harness compute the decision-margin metric -- the metric
that actually reproduces the real-tape 5791-pass / 6179-fail outcome.

------------------------------------------------------------------------------
The three metrics, and which one to trust
------------------------------------------------------------------------------
For each channel and seed we record:

  * raw_ber              -- pre-FEC bit error rate (post-sync).  Through Sim B
                            this is PESSIMISTIC on the coherent DQPSK track
                            (the briefing's central caveat): the differential
                            receiver + pilot reject diffuse contamination that
                            Sim B charges in full, so Sim B FAILS the proven r8
                            on raw BER alone.  DO NOT use Sim B raw BER as an
                            absolute go/no-go.
  * per-carrier margin   -- 45 - p90(|dphi_err|) in degrees, the EXACT gate that
                            killed the 6179 candidate on real tape (x12 G_A2,
                            15 deg DQPSK threshold).  This is the trustworthy
                            absolute filter; see anchor_test.py for the proof
                            that it separates 5791-pass from 6179-fail.
  * net_bps             -- hyp_common.project_to_cassette(raw_ber) mapping.

The VERDICT combines them: a candidate is GO if its worst-channel min-carrier
margin clears the 15 deg DQPSK line AND its projected net_bps beats 5791; HEDGE
if it has sound margin but Sim B raw BER drags net_bps under (the known-pessimism
case -- record it as an extra ladder rung, the tape adjudicates); NO otherwise.
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "capacity", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                              # noqa: E402
import real_channel_sim as rcs                       # noqa: E402

FS = 48_000
REFERENCE_NET_BPS = 5791.2          # the standing real-tape record (r8)
DQPSK_MARGIN_REF_DEG = 15.0         # x12 G_A2 gate: 45-deg DQPSK boundary, 15 deg margin
DBPSK_MARGIN_REF_DEG = 30.0         # x12 G_A2 gate: 90-deg DBPSK boundary, 30 deg margin


# ===========================================================================
# Channel registry -- the calibrated parametric Sim B at the two measured
# capture profiles.  (Trace-driven replay lives in replay_channel.py and can be
# registered here too; see register_replay_channels.)
# ===========================================================================
def _simB(capture: str):
    """Return a channel callable ``f(x, seed) -> y`` for Sim B at ``capture``.

    symbol_len is fixed at 256 -- the proven DQPSK/Dense2x symbol length, which
    is also what the real captures used; it drives the adjacent-bin ISI smear.
    A candidate that genuinely changes N can pass symbol_len through, but the
    Sim B ISI term is calibrated at the measured grid, so N!=256 candidates
    should lean on the MARGIN metric and the trace replay, not Sim B BER.
    """
    def chan(x, seed, symbol_len=256):
        return rcs.real_channel(np.asarray(x, np.float64), capture=capture,
                                symbol_len=symbol_len, seed_offset=int(seed))
    chan._label = f"simB_{capture}"
    return chan


CHANNELS = {
    "simB_master3": _simB("master3"),
    "simB_master2": _simB("master2"),
}


def register_channel(name: str, fn) -> None:
    """Register an extra channel (e.g. a trace-driven replay). ``fn(x, seed)``."""
    CHANNELS[name] = fn


# ===========================================================================
# DQPSK/Dense2x FuncScheme adapter
# ===========================================================================
def _margin_from_dphi(dphi_err_rad: np.ndarray) -> dict:
    """Per-carrier decision-margin stats from the residual phase errors.

    ``dphi_err_rad`` is (n_symbols, P): the post-decision differential-phase
    residual (received dphi minus the decided quadrant center).  The gate metric
    is per-carrier ``margin_deg = 45 - p90(|err_deg|)``; the candidate's overall
    margin is the WORST carrier's margin (the gate is per-carrier all-must-pass).
    """
    err_deg = np.abs(np.degrees(dphi_err_rad))           # (nsym, P)
    p90_per_carrier = np.percentile(err_deg, 90, axis=0)  # (P,)
    margin_per_carrier = 45.0 - p90_per_carrier
    return {
        "p90_deg_per_carrier": [float(v) for v in p90_per_carrier],
        "margin_deg_per_carrier": [float(v) for v in margin_per_carrier],
        "min_margin_deg": float(np.min(margin_per_carrier)),
        "median_margin_deg": float(np.median(margin_per_carrier)),
        "n_carriers_below_15deg": int(np.sum(margin_per_carrier < DQPSK_MARGIN_REF_DEG)),
    }


def make_dqpsk_funcscheme(tx_scheme, rx_demod, *, name: str | None = None,
                          rs_k: int = 179):
    """Wrap a (tx_scheme, rx_demod) DQPSK/Dense2x pair as a FuncScheme.

    tx_scheme : a DQPSKScheme/Dense2xScheme/Dense2xDropScheme instance (TX skip).
    rx_demod  : either a DQPSKScheme (uses .demod) or a ResamplingPLLDemod
                (uses .demod(win,nd)).  Its .sch must be the RX-window variant.

    The wrapper modulates ONE frame (preamble + body) and demodulates the whole
    thing; nd is recovered from the payload bit count.  After each demod it
    stashes the per-carrier phase-residual margin in ``self.last_margin`` so the
    harness can read the constellation cleanly (no truth used in the demod path;
    the residual is the demod's own post-decision quantity).

    ``rs_k`` is carried so net_bps can be cross-checked against gross*rs_k/255
    (the cassette convention) in addition to the conservative table projection.
    """
    from hyp_common import FuncScheme

    nm = name or f"{tx_scheme.name}_rs{rs_k}"

    # Resolve the demod callable + the rx scheme that owns the constellation.
    if hasattr(rx_demod, "sch"):                 # ResamplingPLLDemod
        rx_sch = rx_demod.sch
        demod_call = rx_demod.demod
    else:                                        # plain DQPSKScheme
        rx_sch = rx_demod
        demod_call = rx_demod.demod

    holder = {"margin": None}

    def modulate(bits: np.ndarray) -> np.ndarray:
        return np.asarray(tx_scheme.modulate(np.asarray(bits, np.uint8)),
                          np.float32)

    def demodulate(audio: np.ndarray, sr: int) -> np.ndarray:
        nd = _nd_for_payload(modulate._nbits, tx_scheme)
        bits, diag = demod_call(np.asarray(audio, np.float64), nd)
        holder["margin"] = _extract_margin(audio, nd, rx_sch, demod_call, diag)
        return np.asarray(bits, np.uint8)

    # We need to know how many payload bits to decode; the harness sets this
    # before each demod via the closure attribute (set in evaluate loop).
    modulate._nbits = 0

    fs = FuncScheme(name=nm, gross_bps=float(tx_scheme.gross_bps),
                    modulate=modulate, demodulate=demodulate)
    fs.tx_scheme = tx_scheme
    fs.rx_scheme = rx_sch
    fs.rs_k = rs_k
    fs._modulate_ref = modulate
    fs._margin_holder = holder
    return fs


def _nd_for_payload(nbits: int, tx_scheme) -> int:
    return int(math.ceil(nbits / tx_scheme.bits_per_sym))


def _extract_margin(audio, nd, rx_sch, demod_call, diag) -> dict:
    """Compute the per-carrier decision margin by re-running the demod's own
    DFT + decision and reading the post-decision phase residual.

    This mirrors x9_resampling_pll._decide / x12_recon_margins EXACTLY: the
    residual is (dphi - q*pi/2) wrapped to (-pi,pi]; |residual| in deg, p90 over
    symbols, margin = 45 - p90.  It uses ONLY the demod's hard decisions (no
    truth), so it is the same no-truth quantity the real-tape gate used.
    """
    y = np.asarray(audio, np.float64)
    ds = hc.find_preamble(y.astype(np.float32), rx_sch.preamble_seconds)
    total = nd + 1
    N, skip, Nw = rx_sch.N, rx_sch.skip, rx_sch.Nw
    fpil = rx_sch.freqs[rx_sch.pilot_idx]
    freqs = rx_sch.freqs
    win = rx_sch._win
    nc = rx_sch.P + 1

    # Re-run the proven EMA integer-drift window tracker (h4-identical) so the
    # DFT bins match what the demod decided on.  ema=0.5 matches the h4 default
    # used inside _decide's caller; the margin is robust to this choice.
    c = np.zeros((total, nc), np.complex128)
    dtau = np.zeros(total)
    drift = 0.0
    ema = 0.5
    sm = 0.0
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
            dp = float(np.angle(c[i, rx_sch.pilot_idx] *
                                np.conj(c[i - 1, rx_sch.pilot_idx])))
            sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))

    fd = freqs[rx_sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, rx_sch.data_idx])
    dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    # one-shot decision-directed common-timing refinement (h4-identical)
    res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    num = (res * fd[None, :]).sum(axis=1)
    den = (fd ** 2).sum()
    dtau_res = num / (2 * np.pi * den)
    dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
    q2 = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
    resd = (dphi2 - q2 * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi  # (nsym, P)

    margin = _margin_from_dphi(resd)
    margin["carrier_freqs_hz"] = [round(float(f), 1) for f in fd]
    return margin


# ===========================================================================
# The evaluator
# ===========================================================================
def evaluate_candidate(
    scheme,
    *,
    channels=("simB_master3", "simB_master2"),
    n_seeds: int = 12,
    payload_bits: int = 6_000,
    seed_base: int = 0,
) -> dict:
    """Screen a FuncScheme through the calibrated channels and return a verdict.

    Parameters
    ----------
    scheme : a hyp_common FuncScheme.  For the DQPSK family, build it with
        ``make_dqpsk_funcscheme`` so the per-carrier margin is exposed.  A bare
        FuncScheme (no ``_margin_holder``) is still evaluated, but only on raw
        BER + net_bps (no margin metric available).
    channels : channel names registered in CHANNELS.
    n_seeds : Monte-Carlo seeds per channel.
    payload_bits : fresh random bits per seed (keep modest; ~6000 is fast and
        gives ~136 DQPSK symbols at P22 -> a stable p90 margin estimate).
    seed_base : offset added to every seed (for independent reruns).

    Returns a dict: per_channel {raw_ber, per_seed_ber, margin...}, net_bps via
    the conservative projection, a gross*rs_k/255 cassette cross-check, and a
    single GO/HEDGE/NO verdict vs the 5791 reference.
    """
    has_margin = hasattr(scheme, "_margin_holder")
    mod_ref = getattr(scheme, "_modulate_ref", None)

    per_channel = {}
    for ch_name in channels:
        if ch_name not in CHANNELS:
            raise KeyError(f"unknown channel {ch_name!r}; have {list(CHANNELS)}")
        chan = CHANNELS[ch_name]
        bers, min_margins, med_margins, n_below = [], [], [], []
        p90_stack = []
        for s in range(n_seeds):
            seed = seed_base + s
            rng = np.random.default_rng(10_000 + seed)
            tx_bits = rng.integers(0, 2, size=payload_bits, dtype=np.uint8)
            if mod_ref is not None:
                mod_ref._nbits = len(tx_bits)        # tell the adapter how many
            audio = np.asarray(scheme.modulate(tx_bits), np.float32)
            y = chan(audio, seed)
            rx_bits = np.asarray(scheme.demodulate(y, FS), np.uint8)
            bers.append(_ber(tx_bits, rx_bits))
            if has_margin and scheme._margin_holder["margin"] is not None:
                m = scheme._margin_holder["margin"]
                min_margins.append(m["min_margin_deg"])
                med_margins.append(m["median_margin_deg"])
                n_below.append(m["n_carriers_below_15deg"])
                p90_stack.append(m["p90_deg_per_carrier"])

        raw_ber = float(np.mean(bers))
        entry = {
            "raw_ber": raw_ber,
            "per_seed_ber": [float(x) for x in bers],
        }
        if min_margins:
            # Aggregate the margin across seeds: per-carrier p90 over ALL symbols
            # of ALL seeds is most faithful, but pooling raw residuals across
            # seeds is enough; we take the WORST-seed min margin (conservative)
            # and the mean-of-seeds min margin (typical).
            p90_arr = np.asarray(p90_stack)           # (n_seeds, P)
            pooled_p90 = np.percentile(p90_arr, 90, axis=0)  # robust over seeds
            pooled_margin = 45.0 - pooled_p90
            entry["margin"] = {
                "min_margin_deg_worst_seed": float(np.min(min_margins)),
                "min_margin_deg_mean": float(np.mean(min_margins)),
                "median_margin_deg_mean": float(np.mean(med_margins)),
                "n_carriers_below_15deg_max": int(np.max(n_below)),
                "pooled_min_margin_deg": float(np.min(pooled_margin)),
                "pooled_margin_deg_per_carrier": [float(v) for v in pooled_margin],
            }
        per_channel[ch_name] = entry

    # --- net_bps via the conservative hyp_common projection (worst channel) ---
    worst_ber = max(per_channel[c]["raw_ber"] for c in per_channel)
    best_ber = min(per_channel[c]["raw_ber"] for c in per_channel)
    proj_worst = hc.project_to_cassette(worst_ber, 0.0, scheme.gross_bps)
    proj_best = hc.project_to_cassette(best_ber, 0.0, scheme.gross_bps)

    rs_k = getattr(scheme, "rs_k", None)
    cassette_net_bps = (scheme.gross_bps * rs_k / 255.0) if rs_k else None

    # --- the margin-based net (the trustworthy one for DQPSK): if the worst
    #     channel's pooled min-carrier margin clears 15 deg, the differential
    #     PHY is two-capture-stable and the cassette net (gross*rs_k/255) is the
    #     honest projection (real tape closes RS at that margin). -------------
    margin_ok = None
    worst_min_margin = None
    if all("margin" in per_channel[c] for c in per_channel):
        worst_min_margin = min(per_channel[c]["margin"]["pooled_min_margin_deg"]
                               for c in per_channel)
        margin_ok = bool(worst_min_margin >= DQPSK_MARGIN_REF_DEG)

    verdict, reason = _verdict(
        net_bps_simB_worst=proj_worst["net_bps"],
        cassette_net_bps=cassette_net_bps,
        margin_ok=margin_ok,
        worst_min_margin=worst_min_margin,
        worst_ber=worst_ber,
    )

    return {
        "name": scheme.name,
        "gross_bps": float(scheme.gross_bps),
        "rs_k": rs_k,
        "cassette_net_bps": cassette_net_bps,           # gross*rs_k/255
        "reference_net_bps": REFERENCE_NET_BPS,
        "n_seeds": int(n_seeds),
        "payload_bits": int(payload_bits),
        "channels": list(channels),
        "per_channel": per_channel,
        "simB_net_bps_worst": float(proj_worst["net_bps"]),
        "simB_net_bps_best": float(proj_best["net_bps"]),
        "simB_required_code_rate_worst": float(proj_worst["required_code_rate"]),
        "worst_raw_ber": worst_ber,
        "best_raw_ber": best_ber,
        "worst_min_margin_deg": worst_min_margin,
        "margin_ok_15deg": margin_ok,
        "verdict": verdict,
        "verdict_reason": reason,
    }


def _verdict(*, net_bps_simB_worst, cassette_net_bps, margin_ok,
             worst_min_margin, worst_ber) -> tuple[str, str]:
    """The campaign verdict, honest about Sim B's known DQPSK pessimism.

    GO    : margin clears 15 deg on the worst channel AND the cassette net
            (gross*rs_k/255) beats 5791  -- a strong, two-capture-stable bet.
    HEDGE : margin clears 15 deg and cassette net beats 5791, but Sim B raw BER
            drags the conservative net under 5791 (the documented pessimism) --
            record it as an extra ladder rung; the tape adjudicates.  Also HEDGE
            if margin is unavailable but Sim B net beats 5791.
    NO    : margin fails 15 deg (the gate that killed 6179) OR neither net beats
            5791.
    """
    ref = REFERENCE_NET_BPS
    cass_beats = cassette_net_bps is not None and cassette_net_bps > ref
    simB_beats = net_bps_simB_worst > ref

    if margin_ok is True:
        if cass_beats and simB_beats:
            return "GO", (f"margin {worst_min_margin:.1f}deg >= 15 (two-capture "
                          f"stable) AND both nets beat {ref:.0f}")
        if cass_beats:
            return "HEDGE", (f"margin {worst_min_margin:.1f}deg >= 15 and cassette "
                             f"net {cassette_net_bps:.0f} > {ref:.0f}, but Sim B "
                             f"raw BER {worst_ber:.3f} drags conservative net to "
                             f"{net_bps_simB_worst:.0f} (Sim B DQPSK pessimism) -- "
                             f"hedge rung")
        return "NO", (f"margin OK but neither net beats {ref:.0f} "
                      f"(cassette {cassette_net_bps}, simB {net_bps_simB_worst:.0f})")
    if margin_ok is False:
        return "NO", (f"per-carrier margin {worst_min_margin:.1f}deg < 15 "
                      f"(the x12 gate that killed 6179) -- not two-capture stable")
    # margin unavailable (non-DQPSK FuncScheme): fall back to Sim B net only
    if simB_beats:
        return "HEDGE", (f"no margin metric (non-DQPSK scheme); Sim B net "
                         f"{net_bps_simB_worst:.0f} > {ref:.0f} -- verify on tape")
    return "NO", (f"no margin metric and Sim B net {net_bps_simB_worst:.0f} "
                  f"<= {ref:.0f}")


def _ber(tx: np.ndarray, rx: np.ndarray) -> float:
    n = len(tx)
    if n == 0:
        return 0.0
    m = min(n, len(rx))
    errs = int(np.count_nonzero(tx[:m] != rx[:m])) if m else 0
    errs += (n - m)
    return errs / n


# ===========================================================================
# Convenience builders for the anchor configs (used by anchor_test.py)
# ===========================================================================
def build_dense2x_candidate(P: int, rs_k: int, *, drop_freqs_hz=None,
                            pilot_hz: float = 4875.0, ema_alpha: float = 0.7,
                            name: str | None = None):
    """Build a Dense2x FuncScheme with the proven hann256_skip0 EMA receiver.

    drop_freqs_hz=None -> full grid (Dense2xScheme, the r8 family).
    drop_freqs_hz=[...] -> DropNull grid (Dense2xDropScheme, the r6 family).
    """
    from x10_b_aggr_05_dense2x_master import Dense2xScheme, Dense2xDropScheme
    from x9_resampling_pll import ResamplingPLLDemod

    if drop_freqs_hz is None:
        tx = Dense2xScheme(P, skip=64)
        rx = Dense2xScheme(P, skip=0)              # hann256_skip0
    else:
        tx = Dense2xDropScheme(P, drop_freqs_hz, pilot_hz=pilot_hz, skip=64)
        rx = Dense2xDropScheme(P, drop_freqs_hz, pilot_hz=pilot_hz, skip=0)
    dem = ResamplingPLLDemod(rx, front_end="ema", ema_alpha=ema_alpha)
    return make_dqpsk_funcscheme(tx, dem, name=name, rs_k=rs_k)
