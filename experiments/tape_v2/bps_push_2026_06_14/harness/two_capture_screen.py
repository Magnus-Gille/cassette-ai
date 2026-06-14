"""two_capture_screen.py -- HARDEN the ladder against burn-to-burn carrier flips.

The #1 stated weakness of the bps-push result: every rung was screened on ONE
faithful replay channel (replay_tape10). That single channel CANNOT see the
carrier flips that killed the old 6179 config -- those only show up when a SECOND
real burn (different deck-state / azimuth / day) measures a different per-carrier
margin set.

This script registers a SECOND (and a third) faithful replay channel from
GENUINELY DIFFERENT real captures and re-screens all 6 recommended-ladder rungs on
ALL of them, taking the TWO-CAPTURE WORST model_net as the load-bearing number.

Second captures:
  * tape9  = master9_manifest.json + captures/tape9_run1.wav -- a DIFFERENT real
             burn of the DQPSK ladder (different deck-state, genuinely independent
             of the tape10 5791 burn). THE primary second capture.
  * doom   = m10doom3_manifest.json + captures/doom_tape_readback.wav -- the 4910
             DOOM burn. An even-MORE-different burn (different content, lower SNR,
             different day) -- a third stress channel.

The two-capture gate: a rung is robust GO iff its worst model_net across
{tape10, tape9} still beats r8's worst model_net across the SAME captures (the
two-capture r8 reference). doom is reported as an additional stress point.

Run:  python3 two_capture_screen.py
Saves: results/two_capture_screen.json
"""
from __future__ import annotations

import importlib.util
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
BPS = HERE.parent
CAND = BPS / "candidates"
RESULTS = BPS / "results"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CAND))

import evaluate as ev          # noqa: E402
import score as sc             # noqa: E402
import replay_channel as rc    # noqa: E402

N_SEEDS = 8
PAYLOAD_SHORT = 6000
PAYLOAD_BULK = 80000           # bulk-frame rung body (~one long single-preamble frame)

# Capture set: tape10 (the original single channel) + the two NEW second captures.
TWO_CAPTURE = ("replay_tape10", "replay_tape9")    # the two-capture WORST gate set
STRESS = ("replay_doom",)                          # additional, even-more-different burn
ALL_CHANS = TWO_CAPTURE + STRESS


def _load_hyphen(modname: str, filename: str):
    spec = importlib.util.spec_from_file_location(modname, CAND / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _set_rs_k(fs, rs_k):
    fs.rs_k = rs_k
    return fs


def _build_rungs():
    """Build the 6 recommended-ladder rungs EXACTLY per recommended_ladder.json,
    reusing the candidate modules. Returns list of (rung_name, fs, payload_bits)."""
    dapsk = _load_hyphen("dapsk16_strongmids", "dapsk16-strongmids.py")
    stack = _load_hyphen("stacked_flagship", "stacked_flagship.py")

    rungs = []
    # 1) anchor_r8_proven : build_dense2x_candidate(22, 179)
    rungs.append(("anchor_r8", ev.build_dense2x_candidate(22, 179,
                                                          name="anchor_r8_proven"),
                  PAYLOAD_SHORT))
    # 2) r8_bulkframe_safe : SAME r8 PHY, rs_k=191, long single-preamble body
    rungs.append(("r8_bulkframe", ev.build_dense2x_candidate(22, 191,
                                                             name="r8_bulkframe_safe"),
                  PAYLOAD_BULK))
    # 3) dapsk_8dpsk3 : dapsk16-strongmids variant 'd', rs_k=184
    rungs.append(("dapsk_8dpsk3", _set_rs_k(dapsk.build("d"), 184), PAYLOAD_SHORT))
    # 4) stack_8dpsk3_ext4 : stacked_flagship(n8=3, n_ext=4), rs_k=173
    rungs.append(("stack_8dpsk3_ext4", _set_rs_k(stack.build(n8=3, n_ext=4), 173),
                  PAYLOAD_SHORT))
    # 5) stack_bulkframe_TOP : stacked_flagship(n8=3, n_ext=6) + bulk frame, rs_k=191
    rungs.append(("stack_bulkframe_TOP", _set_rs_k(stack.build(n8=3, n_ext=6), 191),
                  PAYLOAD_BULK))
    # 6) robustness_hedge_dapsk7 : dapsk16-strongmids variant 'e', rs_k=173
    rungs.append(("robustness_hedge_dapsk7", _set_rs_k(dapsk.build("e"), 173),
                  PAYLOAD_SHORT))
    return rungs


def _score_on(fs, payload_bits):
    """Score one rung on ALL channels (tape10, tape9, doom) at N_SEEDS.

    Returns {chan: {ber, model_net}} for every channel + the rung meta."""
    rc.register_replay_channels(["tape10", "tape9", "doom"])
    res = ev.evaluate_candidate(fs, channels=list(ALL_CHANS), n_seeds=N_SEEDS,
                                payload_bits=payload_bits)
    gross = res["gross_bps"]
    per = {}
    for ch in ALL_CHANS:
        ber = res["per_channel"][ch]["raw_ber"]
        per[ch] = {"ber": ber, "model_net": sc.model_net_bps(gross, ber)}
    return gross, res.get("rs_k"), per


def main():
    rungs = _build_rungs()

    # --- the r8 two-capture reference: r8's worst model_net across {tape10, tape9}
    out = {
        "meta": {
            "n_seeds": N_SEEDS,
            "two_capture_gate_channels": list(TWO_CAPTURE),
            "stress_channel": list(STRESS),
            "payload_short": PAYLOAD_SHORT,
            "payload_bulk": PAYLOAD_BULK,
            "second_captures": {
                "tape9": "master9_manifest.json + captures/tape9_run1.wav "
                         "(different real burn of the DQPSK ladder)",
                "doom": "m10doom3_manifest.json + captures/doom_tape_readback.wav "
                        "(the 4910 DOOM burn, even-more-different)",
            },
            "note": ("model_net is the rs_k-independent yardstick compared vs r8; "
                     "cassette_net_at_rs_k uses the ladder-prescribed rs_k. The "
                     "TWO-CAPTURE WORST model_net (min over tape10+tape9) is the "
                     "load-bearing number; doom is an additional stress point."),
        },
        "measured_channels": {},
        "rungs": {},
    }

    # record the measured channel params for each capture
    for cap in ("tape10", "tape9", "doom"):
        ch = rc.ReplayChannel.from_capture(cap)
        out["measured_channels"][cap] = {
            "flutter_pct": ch.flutter_pct,
            "snr_db_median": ch.snr_db_median,
            "clock_ratio": ch.clock_ratio,
            "Hf_db_min": float(min(ch.H_db)),
            "Hf_db_max": float(max(ch.H_db)),
            "phase_jitter_deg_rms": ch.phase_jitter_deg_rms,
            "diffuse_gain": ch.diffuse_gain,
        }

    # score every rung
    rung_records = {}
    for rung_name, fs, pb in rungs:
        gross, rs_k, per = _score_on(fs, pb)
        two_cap = [per[c]["model_net"] for c in TWO_CAPTURE]
        worst_two = min(two_cap)
        best_two = max(two_cap)
        doom_mn = per["replay_doom"]["model_net"]
        cassette_net = (gross * rs_k / 255.0) if rs_k else None
        rec = {
            "phy_name": fs.name,
            "gross_bps": gross,
            "rs_k": rs_k,
            "cassette_net_at_rs_k": cassette_net,
            "payload_bits": pb,
            "per_capture": {c: per[c] for c in ALL_CHANS},
            "two_capture_worst_model_net": worst_two,
            "two_capture_best_model_net": best_two,
            "doom_stress_model_net": doom_mn,
            "all3_worst_model_net": min(worst_two, doom_mn),
        }
        rung_records[rung_name] = rec
        print(f"[{rung_name:24s}] gross={gross:7.1f}  "
              f"tape10 ber={per['replay_tape10']['ber']:.4f} mn={per['replay_tape10']['model_net']:.0f}  "
              f"tape9 ber={per['replay_tape9']['ber']:.4f} mn={per['replay_tape9']['model_net']:.0f}  "
              f"doom ber={per['replay_doom']['ber']:.4f} mn={per['replay_doom']['model_net']:.0f}  "
              f"|  2cap-worst={worst_two:.0f}", flush=True)

    # --- references from the anchor rung ---
    r8 = rung_records["anchor_r8"]
    r8_two_worst = r8["two_capture_worst_model_net"]
    r8_all3_worst = r8["all3_worst_model_net"]
    out["meta"]["r8_two_capture_worst_model_net"] = r8_two_worst
    out["meta"]["r8_all3_worst_model_net"] = r8_all3_worst

    # --- verdict per rung vs the r8 two-capture reference ---
    for rung_name, rec in rung_records.items():
        wt = rec["two_capture_worst_model_net"]
        bt = rec["two_capture_best_model_net"]
        dm = rec["doom_stress_model_net"]
        if rung_name == "anchor_r8":
            verdict = "REF"
            reason = (f"the two-capture reference: worst(tape10,tape9)={wt:.0f}, "
                      f"doom={dm:.0f}")
        elif wt > r8_two_worst and dm > r8_two_worst:
            verdict = "GO"
            reason = (f"two-capture worst {wt:.0f} > r8 2cap-ref {r8_two_worst:.0f} "
                      f"(+{wt-r8_two_worst:.0f}) AND doom {dm:.0f} > ref -- robust on "
                      f"BOTH burns + the doom stress")
        elif wt > r8_two_worst:
            verdict = "GO_soft"
            reason = (f"two-capture worst {wt:.0f} > r8 2cap-ref {r8_two_worst:.0f} "
                      f"(+{wt-r8_two_worst:.0f}) but doom stress {dm:.0f} "
                      f"<= ref {r8_two_worst:.0f} -- robust on the DQPSK-ladder burns, "
                      f"softens on the lower-SNR doom burn")
        elif bt > r8_two_worst:
            verdict = "HEDGE"
            reason = (f"one-capture best {bt:.0f} > ref {r8_two_worst:.0f} but "
                      f"two-capture WORST {wt:.0f} <= ref -- DEGRADES on the second "
                      f"capture; demote to hedge / reorder below the robust rungs")
        else:
            verdict = "CUT"
            reason = (f"two-capture worst {wt:.0f} AND best {bt:.0f} both "
                      f"<= r8 2cap-ref {r8_two_worst:.0f} -- flips below the record "
                      f"on the second burn; CUT or hold as anchor-only")
        rec["verdict"] = verdict
        rec["verdict_reason"] = reason

    out["rungs"] = rung_records

    out_path = RESULTS / "two_capture_screen.json"
    out_path.write_text(json.dumps(out, indent=1))
    print(f"\n[saved] {out_path}")

    # compact table
    print("\n=== TWO-CAPTURE SCREEN (n_seeds=%d) ===" % N_SEEDS)
    print(f"r8 two-capture reference (worst of tape10,tape9): {r8_two_worst:.0f}")
    hdr = ("rung", "gross", "t10 ber", "t10 mn", "t9 ber", "t9 mn",
           "doom mn", "2cap worst", "verdict")
    print("%-24s %7s %8s %7s %8s %7s %8s %10s  %s" % hdr)
    for rung_name, rec in rung_records.items():
        p = rec["per_capture"]
        print("%-24s %7.0f %8.4f %7.0f %8.4f %7.0f %8.0f %10.0f  %s" % (
            rung_name, rec["gross_bps"],
            p["replay_tape10"]["ber"], p["replay_tape10"]["model_net"],
            p["replay_tape9"]["ber"], p["replay_tape9"]["model_net"],
            rec["doom_stress_model_net"],
            rec["two_capture_worst_model_net"], rec["verdict"]))
    return out


if __name__ == "__main__":
    main()
