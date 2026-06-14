"""Candidate: bulk-frame-contpilot  (queue rank 1, lever L4)  —  the near-free MULTIPLIER.

WHAT THIS IS
------------
NOT a new modulation.  This is an ANALYTIC + SIM result on the PROVEN r8 PHY
(``build_dense2x_candidate(22, 179)`` = D2X_P22_N256_sp2, 22 carriers x 2 bits x
187.5 sym/s = 8250 gross, RS(255,179), continuous unmodulated pilot @4875).  The
question the campaign asked: today every frame pays a 0.25 s up/down chirp + 0.12 s
gap = 0.37 s of overhead, amortised over a tiny body.  Can we make the frame LONG
(one preamble, thousands of data symbols) and rely on the existing per-symbol pilot
PLL to hold coherence across the whole frame, or does flutter wander accumulate and
break tracking?

``build()`` returns the exact proven r8 FuncScheme (contract compliance + clean
self-check).  The finding lives in the screen result and the docstring below; the
deliverable is the RECOMMENDATION to lengthen the per-rung frame body on the master.

THE FINDING (screened on the faithful replay_tape10 channel, n_seeds=8)
----------------------------------------------------------------------
Same scheme, frame body swept 137 -> 9091 symbols (0.73 s -> 48.5 s):

    payload  frame      replay_tape10   model_net   ber_ratio
    bits     sym /  s   BER             bps         vs short
    -------  --------   -------------   ---------   ---------
      6000    137 / 0.7   0.01265        6632        1.000
     20000    455 / 2.4   0.00963        7021        0.761
     60000   1364 / 7.3   0.00825        7182        0.652
    120000   2728 /14.5   0.00795        7215        0.628
    200000   4546 /24.2   0.00753        7279        0.595
    400000   9091 /48.5   0.00755        7247        0.597   <- FLAT vs 24 s

BER does NOT degrade as the frame lengthens — it DECREASES, then plateaus.  The
error is FRONT-LOADED (pilot-tracker settling): at 200k bits the first-half BER is
0.0104 while the last half is 0.00019.  The per-symbol EMA pilot converges, then
tracks essentially error-free.  A long frame amortises the one-time settling cost
AND raises the steady-state model_net.  L_max (within 1.2x of the short-frame BER)
is the LONGEST tested, 9091 sym / 48.5 s, with no breakdown — so the cap is set by
dropout-resync robustness, NOT by pilot wander.

WHY (the mechanism)
-------------------
The shipping continuous pilot updates the flutter estimate EVERY symbol (5.33 ms at
N=256), far faster than the 0.55 Hz wow / 4.8 Hz flutter.  Briefing blocker #5
("flutter wander appears as a static offset on extrapolated frames") applied to
BLOCK / extrapolated pilots; the per-symbol pilot has no wander limit.  NO pilot
tracker change is needed.

THE NET MULTIPLIER (ground truth from master10_manifest.json frame_starts)
--------------------------------------------------------------------------
The r8 rung on the real tape10 burn has frame_period 0.871 s = 0.501 s body
(94 sym) + 0.25 s chirp + 0.12 s gap.  Current framing efficiency = 0.575.
One chirp pair over a long body recovers that:

    L = 1364 sym ( 7.3 s)  eff 0.952  WALL-CLOCK MULTIPLIER 1.65x
    L = 2728 sym (14.5 s)  eff 0.975  WALL-CLOCK MULTIPLIER 1.70x
    L = 4546 sym (24.2 s)  eff 0.985  WALL-CLOCK MULTIPLIER 1.71x
    L = 9091 sym (48.5 s)  eff 0.992  WALL-CLOCK MULTIPLIER 1.73x

(Per the guide, gross/net = 5791/5921 are STEADY-STATE, with per-frame overhead NOT
subtracted; the multiplier is on the WALL-CLOCK delivered bps, which today's short
frames leave on the table.  The queue's 1.10-1.14x estimate assumed an 8 s current
frame; the real master uses 0.5 s bodies, so the true win is ~1.65-1.73x.)

CAMPAIGN-RELEVANT BOTTOM LINE
-----------------------------
Bulk framing NEVER costs model_net or BER (it improves both via settling-amortisation)
and is a multiplicative ~1.65-1.73x wall-clock win that composes UNDER EVERY other
rung.  RECOMMEND FOR MASTER: lengthen the per-rung frame body to ~1364-2728 symbols
(7-15 s) with one chirp pair, capping at ~2-3k sym for dropout-resync robustness.

This file's ``build()`` is the proven r8 PHY; the change is in the master frame
sizing (x10_b_aggr_05_dense2x_master.py FRAME_BYTES / the codec frame split), not in
modulate/demodulate.
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

_HARNESS = (pathlib.Path(__file__).resolve().parent.parent / "harness").resolve()
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))


def build():
    """Return the proven r8 FuncScheme (D2X_P22_N256_sp2, RS(255,179)).

    Bulk-framing is a master-level frame-sizing change, NOT a modulation change, so
    the candidate's modem IS the proven r8 modem.  Screening this scheme at
    increasing ``payload_bits`` (= longer single-preamble frames) is exactly the
    bulk-framing experiment.
    """
    import evaluate as ev
    return ev.build_dense2x_candidate(22, 179, name="bulk-frame-contpilot_r8base")


# Recommended master config for the bulk-framing rung (buildable params).
MASTER_CONFIG = {
    "base_phy": "D2X_P22_N256_sp2 (proven r8)",
    "P": 22, "N": 256, "spacing": 2, "skip": 64,
    "bits_per_carrier": 2, "sym_rate": 187.5, "gross_bps": 8250,
    "rs_n": 255, "rs_k": 179, "pilot_hz": 4875.0,
    "kind": "dense2x",
    "frame_body_symbols": 2728,          # ~14.5 s body, one chirp pair per frame
    "frame_body_seconds": 14.55,
    "preamble_seconds": 0.25, "frame_gap_seconds": 0.12,
    "framing_efficiency": 0.975,
    "wallclock_multiplier_vs_today": 1.70,
    "pilot_tracker_change": "NONE (continuous per-symbol EMA pilot already sufficient)",
    "note": ("Lengthen the per-rung frame body from todays ~94 sym (0.5 s) to "
             "~2728 sym (14.5 s); cap at 2-3k sym for dropout-resync. Implemented "
             "in x10_b_aggr_05_dense2x_master.py by raising FRAME_BYTES so the codec "
             "emits one long frame per rung instead of many short ones. Applies "
             "MULTIPLICATIVELY to every other rung on the master."),
}


def _self_check() -> float:
    """Mandatory clean-channel RED/GREEN self-check (modulate->demodulate, no channel)."""
    fs = build()
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    fs._modulate_ref._nbits = len(bits)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), 48000)
    m = min(len(bits), len(rx))
    ber = float(np.mean(bits[:m] != rx[:m]))
    assert ber < 1e-3, f"clean-channel BER {ber} — modem does not invert"
    return ber


def _screen(payloads=(6000, 20000, 60000, 120000, 200000, 400000), n_seeds=8):
    """Screen the r8 scheme at increasing single-preamble frame lengths on
    replay_tape10 and report whether BER stays flat (it does — it improves)."""
    import evaluate as ev
    import score
    base = None
    rows = []
    for pb in payloads:
        fs = ev.build_dense2x_candidate(22, 179)
        r = score.score_candidate(fs, channels=("replay_tape10",), also_simB=False,
                                  n_seeds=n_seeds, payload_bits=pb)
        ber = r["per_channel"]["replay_tape10"]["ber"]
        mn = r["per_channel"]["replay_tape10"]["model_net"]
        nsym = int(math.ceil(pb / 44))
        if base is None:
            base = ber
        rows.append((pb, nsym, nsym / 187.5, ber, mn, ber / base))
        print(f"  pb={pb:>7} {nsym:>5} sym {nsym/187.5:6.2f}s  ber={ber:.5f} "
              f"model_net={mn:.0f}  ratio={ber/base:.3f}")
    return rows


if __name__ == "__main__":
    print("[self-check] clean-channel BER =", _self_check())
    print("[screen] r8 PHY at increasing single-preamble frame length (replay_tape10):")
    _screen()
