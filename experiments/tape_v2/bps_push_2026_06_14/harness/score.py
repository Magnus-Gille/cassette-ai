"""score.py — the CORRECTED campaign filter (2026-06-15).

The first-pass harness (evaluate.py) chose per-carrier margin + Sim B net as the
filter; the anchor test PROVED that fails — it marks the proven r8 (5791) and r6
(4910) as NO, identical to the killed configs (margin can't separate two configs
with the same modulation; Sim B net is uniformly crushed by the documented DQPSK
pessimism).

The metric that DOES reproduce the real-tape outcomes is RS-CLOSURE on the
trace-driven replay BER (the faithful channel measured from the 5791 burn):

    PROVEN r8  P22 RS179 : replay_tape10 ber 0.0186 -> ~35 byte-errs -> RS179
                           corrects 38 -> CLOSES.
    KILLED 6179 P22 RS191: same ber -> RS191 corrects 32 -> FAILS.
    PROVEN r6  P21 RS159 : ber 0.0189 -> ~35 -> RS159 corrects 48 -> CLOSES.
    KILLED 5247 P16 RS223: ber 0.0233 -> ~44 -> RS223 corrects 16 -> FAILS.

So the campaign yardstick is the model-CLOSEABLE net bps on the faithful channel:

    E(ber)   = 255 * (1 - (1-ber)^8)            # expected RS byte-errors / codeword
    k_max    = floor(255 - 2*E)                 # largest k (least FEC) that still
                                                # corrects E errors with NO erasure
    model_net(gross, ber) = gross * max(0,k_max) / 255

Computed IDENTICALLY for every candidate and for r8, the absolute calibration
offset cancels: a candidate beats the record iff its worst-capture model_net
exceeds r8's worst-capture model_net (the reference, ~5950).  This is a CONSERVATIVE
floor: the real receiver also runs a carrier-class erasure rescue + multi-front-end
union (each erasure costs 1, not 2), so true closeable net is >= model_net.  Used
relatively, the floor is the right yardstick.

Two-capture stability: score on BOTH replay_tape10 AND replay_doom and take the
worst; that catches carriers that flip between burns (the failure that the x12
two-capture gate guards against).  Margin (from evaluate.py) is kept as secondary
diagnostic only.
"""
from __future__ import annotations
import json, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev
import replay_channel as rc

FAITHFUL_CHANNELS = ("replay_tape10", "replay_doom")   # two real burns
REF_PATH = HERE.parent / "results" / "r8_reference.json"


def expected_byte_errors(ber: float, n: int = 255) -> float:
    ber = max(0.0, min(1.0, float(ber)))
    return n * (1.0 - (1.0 - ber) ** 8)


def model_net_bps(gross: float, ber: float) -> float:
    """Closeable net bps: highest RS rate whose (no-erasure) correction capacity
    covers the expected byte errors at this raw BER."""
    E = expected_byte_errors(ber)
    k_max = int(np.floor(255.0 - 2.0 * E))
    k_max = max(0, min(254, k_max))
    return float(gross) * k_max / 255.0


def _ensure_channels(channels):
    have = set(ev.CHANNELS)
    want_replay = [c.replace("replay_", "") for c in channels if c.startswith("replay_")]
    missing = [c for c in want_replay if f"replay_{c}" not in have]
    if missing:
        rc.register_replay_channels(missing)


def score_candidate(scheme, *, channels=FAITHFUL_CHANNELS, also_simB=True,
                    n_seeds=4, payload_bits=6000, ref_net=None):
    """Run a FuncScheme through the faithful replay channels and return the
    corrected verdict based on model-closeable net bps.

    Returns a flat dict with: gross, requested cassette_net (gross*rs_k/255 if rs_k
    set), per-channel {ber, model_net}, worst_model_net, beats_ref, verdict.
    """
    chans = list(channels) + (["simB_master3"] if also_simB else [])
    _ensure_channels(chans)
    res = ev.evaluate_candidate(scheme, channels=chans, n_seeds=n_seeds,
                                payload_bits=payload_bits)
    gross = res["gross_bps"]
    rs_k = res.get("rs_k")
    cassette_net = (gross * rs_k / 255.0) if rs_k else None

    per = {}
    model_nets_faithful = []
    for ch in chans:
        ber = res["per_channel"][ch]["raw_ber"]
        mn = model_net_bps(gross, ber)
        mar = res["per_channel"][ch].get("margin", {})
        per[ch] = {"ber": ber, "model_net": mn,
                   "pooled_min_margin_deg": mar.get("pooled_min_margin_deg")}
        if ch in channels:                      # faithful captures only
            model_nets_faithful.append(mn)

    worst_model_net = min(model_nets_faithful) if model_nets_faithful else 0.0
    best_model_net = max(model_nets_faithful) if model_nets_faithful else 0.0

    if ref_net is None:
        ref_net = _load_ref()
    beats = worst_model_net > ref_net if ref_net else None

    # verdict: GO if worst (two-capture) model_net beats the r8 reference;
    # HEDGE if only the best capture beats it (one-capture win, tape adjudicates);
    # NO otherwise.
    if ref_net is None:
        verdict, reason = "REF", "this run defines the reference"
    elif worst_model_net > ref_net:
        verdict = "GO"
        reason = (f"two-capture model_net {worst_model_net:.0f} > r8 ref {ref_net:.0f} "
                  f"(+{worst_model_net-ref_net:.0f})")
    elif best_model_net > ref_net:
        verdict = "HEDGE"
        reason = (f"one-capture model_net {best_model_net:.0f} > ref {ref_net:.0f} but "
                  f"worst {worst_model_net:.0f} <= ref — tape adjudicates")
    else:
        verdict = "NO"
        reason = (f"worst {worst_model_net:.0f} and best {best_model_net:.0f} both "
                  f"<= r8 ref {ref_net:.0f}")

    return {
        "name": res["name"], "gross_bps": gross, "rs_k": rs_k,
        "requested_cassette_net": cassette_net,
        "per_channel": per,
        "worst_model_net_bps": worst_model_net,
        "best_model_net_bps": best_model_net,
        "ref_net_bps": ref_net,
        "beats_ref": beats,
        "verdict": verdict, "verdict_reason": reason,
        "_raw_eval": res,
    }


def _load_ref():
    if REF_PATH.exists():
        return json.load(open(REF_PATH))["r8_worst_model_net_bps"]
    return None


def save_ref(r8_score: dict):
    REF_PATH.parent.mkdir(exist_ok=True)
    json.dump({"r8_worst_model_net_bps": r8_score["worst_model_net_bps"],
               "r8_best_model_net_bps": r8_score["best_model_net_bps"],
               "per_channel": {k: v["ber"] for k, v in r8_score["per_channel"].items()}},
              open(REF_PATH, "w"), indent=1)
    return REF_PATH
