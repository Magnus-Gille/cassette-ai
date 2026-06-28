"""Regression tests for the per-frame timing DRIFT TRACKER (issue #26).

The tracker fixes long-tape decode: global sync fits ONE constant clock ratio
(endpoint average), so a tape whose true speed wanders leaves a residual timing
BOW that, mid-tape, exceeds the per-frame preamble search slack -> spurious
preamble locks -> dead frames -> total RS wipeout. The tracker forward-predicts
each frame's start, measures where the preamble actually landed, and (only on a
confident lock, beyond a deadband) nudges the prediction to follow the bow.

CRITICAL PROPERTY (parity gate): the tracker is a strict NO-OP on a well-tracked
capture -- residual ~0 stays inside the deadband, so drift_pred never moves and
the frozen byte-exact pipeline is untouched. These tests pin that property plus
the confidence gate and the clamp.
"""
import sys
import pathlib

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import hyp_common as hc  # noqa: E402
import m9_decode as m9d  # noqa: E402

PRE_S = 0.25


def _win(chirp_pos, length=40000, noise=0.02, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.standard_normal(length) * noise
    pre = hc.make_preamble(PRE_S).astype(np.float64)
    y[chirp_pos:chirp_pos + len(pre)] += pre
    return y


def test_prominence_separates_lock_from_noise():
    lock = m9d._preamble_prominence(_win(14400, seed=1), PRE_S)
    noise = m9d._preamble_prominence(
        np.random.default_rng(2).standard_normal(40000) * 0.02, PRE_S)
    assert lock > m9d.DRIFT_CONF_MIN, lock
    assert noise < m9d.DRIFT_CONF_MIN, noise
    # margin both sides of the threshold (empirical: noise<=~9, lock>=~75)
    assert lock > 2 * m9d.DRIFT_CONF_MIN
    assert noise < 0.6 * m9d.DRIFT_CONF_MIN


def test_noop_on_zero_and_small_residual():
    w = _win(14400, seed=3)
    assert m9d._drift_update(0, 0, w, PRE_S) == 0
    assert m9d._drift_update(0, m9d.DRIFT_DEADBAND - 1, w, PRE_S) == 0
    assert m9d._drift_update(0, -(m9d.DRIFT_DEADBAND - 1), w, PRE_S) == 0
    # a carried drift with zero residual is preserved (not reset)
    assert m9d._drift_update(-5000, 0, w, PRE_S) == -5000


def test_confident_tracking_and_clamp():
    w = _win(14400, seed=4)
    assert m9d._drift_update(0, 3000, w, PRE_S) == 3000          # within STEP
    assert m9d._drift_update(0, 9000, w, PRE_S) == m9d.DRIFT_STEP  # clamped
    assert m9d._drift_update(0, -9000, w, PRE_S) == -m9d.DRIFT_STEP


def test_unconfident_large_residual_ignored():
    noise = np.random.default_rng(5).standard_normal(40000) * 0.02
    assert m9d._drift_update(0, 9000, noise, PRE_S) == 0


def test_tracks_synthetic_bow_within_pad():
    """A smooth -27000-sample bow over 237 frames stays well inside PAD_LO."""
    pad_lo = int(m9d.PAD_LO_S * hc.SAMPLE_RATE)
    drift, max_resid = 0, 0
    for fi in range(237):
        true_off = int(-27000 * np.sin(np.pi * fi / 237))
        residual = true_off - drift
        # window with the chirp at its measured position so prominence passes
        cp = pad_lo + int(np.clip(residual, -pad_lo + 1000, pad_lo - 1000))
        w = _win(cp, noise=0.02, seed=fi)
        drift = m9d._drift_update(drift, residual, w, PRE_S)
        max_resid = max(max_resid, abs(residual))
    assert max_resid < pad_lo - 2000, max_resid


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL DRIFT TRACKER TESTS PASS")
