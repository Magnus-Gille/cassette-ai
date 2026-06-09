"""dd_common.py — shared harness for capacity deep-dive campaign #2.

Builds on the FROZEN harness in src/hyp_common.py. Adds:

  * Dual-channel evaluation: the SIM 'normal' channel (preset 'normal',
    speed_offset 0, capture usb_soundcard) AND a HARSH real-proxy channel
    (preset 'worn' + speed_offset=-0.12, the ~0.88x flutter-heavy acoustic
    loop). Every hypothesis is measured on BOTH and projected to net_bps with
    P_full via the frozen project_to_cassette.

  * A reusable GLOBAL SPEED-CORRECTION front end (estimate_speed / correct_speed)
    derived ONLY from the known chirp preamble — no oracle. This is the first-
    order 'sim->real bridge': it undoes the steady ~12% deck-clock offset so a
    scheme's own per-window tracking only has to handle the residual ~2% flutter.

  * Reference re-measurement of MFSK-32 and C4 on both channels (in-run anchors).

Path note: the frozen harness hardcodes ROOT=/Users/magnus/repos/cassette-ai.
This repo lives at /home/user/cassette-ai; a symlink makes the path resolve.
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc          # noqa: E402
import capture_scenarios as cs   # noqa: E402
from scipy.signal import resample_poly, correlate  # noqa: E402

FS = hc.SAMPLE_RATE

# --- The two evaluation channels -------------------------------------------
SIM = dict(tape_preset="normal", speed_offset=0.0, capture_key="usb_soundcard")
REAL = dict(tape_preset="worn", speed_offset=-0.12, capture_key="usb_soundcard")
CHANNELS = {"sim": SIM, "real": REAL}


# ===========================================================================
# Global speed-correction front end (preamble-derived, no oracle)
# ===========================================================================
def estimate_speed(audio: np.ndarray,
                   ratios: np.ndarray | None = None,
                   seconds: float = hc.PREAMBLE_SECONDS) -> float:
    """Estimate the steady resample ratio r applied to the TX audio, using ONLY
    the known chirp preamble. The channel applies tape_core speed_offset by
    resample_poly(x, num, den) with ratio = 1+offset; the received preamble is a
    chirp stretched by that ratio. We resample the *known* preamble template by a
    grid of candidate ratios and take the one whose cross-correlation peak with
    the received audio is sharpest/largest.

    Returns r_hat such that the received audio is ~ TX resampled by r_hat (so to
    restore nominal timing, resample the received audio by 1/r_hat).
    """
    audio = np.asarray(audio, dtype=np.float64)
    if ratios is None:
        ratios = np.arange(0.84, 1.061, 0.004)
    pre0 = np.asarray(hc.make_preamble(seconds), dtype=np.float64)
    # The preamble lives in the lead-in. Restrict the search to a generous lead
    # window so data tones can't spuriously win the correlation. The preamble at
    # the slowest ratio is ~seconds/0.84 long; allow ~3x that plus slack.
    lead_n = int(min(len(audio), max(0.6, seconds / 0.84 * 3 + 0.3) * FS))
    seg = audio[:lead_n]
    seg_csum = np.cumsum(seg ** 2)
    from fractions import Fraction

    def _score(r):
        frac = Fraction(float(r)).limit_denominator(4000)
        pre_r = resample_poly(pre0, frac.numerator, frac.denominator)
        L = len(pre_r)
        if L >= len(seg):
            return -np.inf
        corr = correlate(seg, pre_r, mode="valid")
        # windowed energy E[i:i+L] from prefix sums of squares
        e_full = seg_csum[L - 1:]
        e_prev = np.concatenate([[0.0], seg_csum[:-L]])[:len(e_full)]
        win_en = np.sqrt(np.maximum(e_full - e_prev, 1e-12))[:len(corr)]
        tmpl_norm = np.sqrt(np.sum(pre_r ** 2))
        ncc = np.abs(corr) / (win_en * tmpl_norm + 1e-12)
        return float(np.max(ncc))

    # Stage 1: coarse grid.
    best_r = max(ratios, key=_score)
    # Stage 2: fine local refinement around the coarse winner.
    fine = np.arange(best_r - 0.006, best_r + 0.0061, 0.0008)
    best_r = max(fine, key=_score)
    # Stage 3: parabolic interpolation on the finest triplet.
    finer = np.arange(best_r - 0.0008, best_r + 0.00081, 0.0002)
    best_r = max(finer, key=_score)
    return float(best_r)


def correct_speed(audio: np.ndarray, r_hat: float) -> np.ndarray:
    """Resample received audio by 1/r_hat to restore nominal symbol timing."""
    if abs(r_hat - 1.0) < 1e-4:
        return np.asarray(audio, dtype=np.float64)
    from fractions import Fraction
    # invert: nominal = received resampled by 1/r_hat
    frac = Fraction(1.0 / float(r_hat)).limit_denominator(2000)
    return resample_poly(np.asarray(audio, dtype=np.float64),
                         frac.numerator, frac.denominator)


def tracked_tone_demod(audio, freqs, N, bps, *, n_bits=4000,
                       preamble_seconds=hc.PREAMBLE_SECONDS,
                       acq=40, track=3, do_speed=True, center_bias=0.03,
                       vel_gain=0.0):
    """Flutter-tracking NON-COHERENT tone demod for an MFSK-style tone bank.

    Pipeline (the 'sim->real bridge'):
      1. GLOBAL speed correction from the chirp preamble (undo the ~12% deck clock).
      2. Coarse chirp sync (find_preamble).
      3. WIDE initial acquisition (+/-acq) to lock symbol 0 after residual offset.
      4. Per-symbol +/-track micro-search on the tone-energy lock score, with the
         offset drift carried forward so slow wow/flutter is followed symbol by
         symbol. Returns (sym_indices, drifts, lock_scores).

    `freqs` are the M tone frequencies (need not be FFT-bin-centred), `N` the
    samples per symbol, `bps` the bits per symbol (log2 M). Pure-energy detection
    -> shrugs off flutter-induced phase, only the timing must be tracked.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if do_speed:
        r = estimate_speed(audio, seconds=preamble_seconds)
        audio = correct_speed(audio, r)
    start = hc.find_preamble(audio, preamble_seconds)
    t = np.arange(N) / FS
    basis = np.exp(-2j * np.pi * np.outer(freqs, t))  # (M, N)

    def sc_off(base):
        if base < 0:
            return -1.0, None
        seg = audio[base:base + N]
        if len(seg) < N:
            if len(seg) < N // 2:   # too little left to be a real symbol
                return -1.0, None
            seg = np.concatenate([seg, np.zeros(N - len(seg))])  # pad final symbol
        # Real captures (resampled in global sync) can carry non-finite samples
        # at resample edges; an inf/nan in seg makes basis @ seg overflow/​NaN and
        # poisons the lock score. Sanitise to finite values before the matmul.
        if not np.all(np.isfinite(seg)):
            seg = np.nan_to_num(seg, nan=0.0, posinf=0.0, neginf=0.0)
        e = np.abs(basis @ seg)
        return float(e.max() / (np.median(e) + 1e-9)), e

    best = None
    for off in range(-acq, acq + 1):
        s, _ = sc_off(start + off)
        if s > 0 and (best is None or s > best[0]):
            best = (s, off)
    drift = float(best[1]) if best else 0.0
    vel = 0.0  # first-order timing predictor (samples/symbol) — tracks fast flutter
    syms, drifts, locks = [], [], []
    pos = start
    while pos + drift + vel + N // 2 <= len(audio):
        predicted = drift + vel               # predict next symbol's offset
        base = int(round(pos + predicted))
        b = None
        for d in range(-track, track + 1):
            s, e = sc_off(base + d)
            if s <= 0:
                continue
            # Center-bias: penalise moving off the PREDICTED boundary so the
            # drift doesn't random-walk on clean signal and doesn't get yanked
            # by a burst. With vel>0 the prediction leads the flutter, so the
            # residual d is small and the center-bias still applies cleanly.
            s_adj = s * (1.0 - center_bias * abs(d))
            if b is None or s_adj > b[0]:
                b = (s_adj, d, e)
        if b is None:
            break
        _, d, e = b
        s, _ = sc_off(base + d)
        new_drift = predicted + d
        increment = new_drift - drift          # realized per-symbol timing increment
        vel = (1.0 - vel_gain) * vel + vel_gain * increment
        drift = new_drift
        syms.append(e)
        drifts.append(drift)
        locks.append(s)
        pos += N
        if len(syms) * bps >= n_bits:
            break
    return syms, np.array(drifts), np.array(locks)


def speed_correcting_demod(inner_demod):
    """Wrap a demod(audio, sr)->bits so it first estimates+removes global speed.

    Use this to give any flutter-naive scheme a fair shot on the REAL channel:
    the steady 12% clock is undone here; the inner demod handles the rest.
    """
    def demod(audio, sr):
        r = estimate_speed(audio)
        fixed = correct_speed(audio, r)
        return inner_demod(fixed, sr)
    return demod


# ===========================================================================
# Dual-channel evaluation
# ===========================================================================
@dataclass
class ChannelResult:
    channel: str
    gross_bps: float
    raw_ber: float
    erasure_rate: float
    net_bps: float
    P_full: float
    required_code_rate: float
    MB_C90_stereo: float
    per_seed_ber: list


def eval_on(scheme, channel: str, n_seeds: int = 12,
            payload_bits: int = 4000) -> ChannelResult:
    cfg = CHANNELS[channel]
    ev = hc.evaluate_scheme(
        scheme, tape_preset=cfg["tape_preset"], n_seeds=n_seeds,
        payload_bits=payload_bits, capture_key=cfg["capture_key"],
        speed_offset=cfg["speed_offset"],
    )
    proj = hc.project_to_cassette(ev["raw_bit_error_rate"], ev["erasure_rate"],
                                  ev["gross_bps"])
    return ChannelResult(
        channel=channel, gross_bps=ev["gross_bps"],
        raw_ber=ev["raw_bit_error_rate"], erasure_rate=ev["erasure_rate"],
        net_bps=proj["net_bps"], P_full=proj["P_full"],
        required_code_rate=proj["required_code_rate"],
        MB_C90_stereo=proj["MB_C90_stereo"], per_seed_ber=ev["per_seed_ber"],
    )


def sanity_no_channel(scheme, payload_bits: int = 4000) -> float:
    """MANDATORY gate: modulate->demodulate with NO channel must give BER ~0."""
    rng = np.random.default_rng(42)
    bits = rng.integers(0, 2, size=payload_bits, dtype=np.uint8)
    audio = np.asarray(scheme.modulate(bits), dtype=np.float32)
    rec = np.asarray(scheme.demodulate(audio, FS), dtype=np.uint8)
    n = len(bits)
    m = min(n, len(rec))
    return (int(np.count_nonzero(bits[:m] != rec[:m])) + (n - m)) / n


def evaluate_dual(scheme, n_seeds: int = 12, payload_bits: int = 4000,
                  do_sanity: bool = True) -> dict:
    out = {"name": getattr(scheme, "name", "?")}
    if do_sanity:
        out["sanity_ber"] = sanity_no_channel(scheme, payload_bits)
    for ch in ("sim", "real"):
        r = eval_on(scheme, ch, n_seeds=n_seeds, payload_bits=payload_bits)
        out[ch] = r.__dict__
    return out


def fmt(out: dict) -> str:
    s = [f"{out['name']}  sanity={out.get('sanity_ber', float('nan')):.1e}"]
    for ch in ("sim", "real"):
        r = out[ch]
        s.append(f"  [{ch:4}] gross={r['gross_bps']:.0f} BER={r['raw_ber']:.2e} "
                 f"era={r['erasure_rate']:.3f} net={r['net_bps']:.0f} "
                 f"P={r['P_full']:.2f} rate={r['required_code_rate']:.3f}")
    return "\n".join(s)


# ===========================================================================
# References (in-run anchors)
# ===========================================================================
def mfsk32_scheme():
    from hyp_h2_mfsk import MFSKScheme
    return MFSKScheme(M=32, walsh_k=0)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--speedtest", action="store_true")
    args = ap.parse_args()

    if args.speedtest:
        # Verify the speed estimator recovers -0.12 on the REAL channel.
        sch = mfsk32_scheme()
        rng = np.random.default_rng(1)
        bits = rng.integers(0, 2, size=4000, dtype=np.uint8)
        audio = np.asarray(sch.modulate(bits), dtype=np.float32)
        rx, sr, diag = cs.full_chain(audio, "worn", "usb_soundcard",
                                     speed_offset=-0.12, seed=0)
        r = estimate_speed(rx)
        print(f"[speedtest] true ratio=0.88  estimated r_hat={r:.4f}  "
              f"err={r-0.88:+.4f}")
        sys.exit(0)

    print("=== MFSK-32 reference, dual channel ===")
    out = evaluate_dual(mfsk32_scheme(), n_seeds=args.seeds)
    print(fmt(out))
