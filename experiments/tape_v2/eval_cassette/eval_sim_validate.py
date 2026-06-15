"""eval_sim_validate.py -- HARD GATE B: push eval_master.wav through the sim
channels and confirm (a) the CONFIRMED tier degrades as the channel worsens, and
(b) PREDICT tracks CONFIRM within ~+-1 tier.

Channels:
  * src/channel.py cassette_channel at the four TAPE_PRESETS (pristine/good/
    normal/worn) -- band-limit + wow/flutter + AWGN + dropouts.
  * real_channel_sim.real_channel(master3) -- the calibrated acoustic loop
    (diffuse reverb + HF rolloff + ISI), the closest model to a real capture.

For each channel: render master -> channel -> WAV -> eval_decode.decode -> record
predicted tier, confirmed tier, the measured channel dict, and the predict-vs-
confirm delta.  Writes results/eval_sim_validation.json.

Run:
    python3 eval_sim_validate.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import warnings

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "tape_v2", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from channel import cassette_channel              # noqa: E402  (FROZEN)
from capture_scenarios import TAPE_PRESETS        # noqa: E402
import real_channel_sim as rcs                    # noqa: E402
import eval_decode as ed                          # noqa: E402

SR = 48_000
WAV = _HERE / "eval_master.wav"
TMP_DIR = _HERE / "results" / "_sim_tmp"
RESULTS = _HERE / "results" / "eval_sim_validation.json"
TIER_ORDER = ed.TIER_ORDER


def _idx(t):
    return TIER_ORDER.index(t) if t in TIER_ORDER else -1


def render_preset(x, preset, seed=7):
    p = TAPE_PRESETS[preset]
    return cassette_channel(
        x, fs=SR, snr_db=p["snr_db"], wow_flutter_wrms=p["wow_flutter_wrms"],
        bandwidth_hz=p["bandwidth_hz"], burst_rate_per_s=p["burst_rate_per_s"],
        burst_length_ms=p["burst_length_ms"], seed_offset=seed)


def render_real(x, capture="master3", seed=7):
    return rcs.real_channel(x, capture=capture, seed_offset=seed)


def render_stress(x, snr, wf, bw, seed=7):
    return cassette_channel(x, fs=SR, snr_db=snr, wow_flutter_wrms=wf,
                            bandwidth_hz=bw, burst_rate_per_s=0.3,
                            burst_length_ms=6.0, seed_offset=seed)


# A STRESS LADDER beyond the named presets: the four TAPE_PRESETS are all clean
# enough that these (very robust) modems confirm T7 on all of them -- a true and
# reportable finding, but it does not by itself demonstrate the eval cassette
# walking a WEAKER link down the tier ladder.  This synthetic ladder progressively
# worsens SNR+flutter+BW (beyond 'worn') so the CONFIRMED tier is forced to drop,
# proving the cassette correctly distinguishes weaker links.  (snr_db, wf, bw_hz)
STRESS_LADDER = [
    ("stress_A", 38.0, 0.0025, 11000.0),
    ("stress_B", 30.0, 0.0045, 9000.0),
    ("stress_C", 24.0, 0.0075, 9000.0),
    ("stress_D", 18.0, 0.0110, 8000.0),
    ("stress_E", 13.0, 0.0150, 7000.0),
    ("stress_F", 9.0,  0.0220, 6000.0),
]


def run():
    x, sr = sf.read(str(WAV), dtype="float32", always_2d=False)
    assert sr == SR
    x = np.asarray(x, np.float64)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    channels = [
        ("pristine", lambda: render_preset(x, "pristine")),
        ("good",     lambda: render_preset(x, "good")),
        ("normal",   lambda: render_preset(x, "normal")),
        ("worn",     lambda: render_preset(x, "worn")),
        ("real_master3", lambda: render_real(x, "master3")),
    ]
    for nm, snr, wf, bw in STRESS_LADDER:
        channels.append((nm, (lambda s=snr, w=wf, b=bw: render_stress(x, s, w, b))))

    table = []
    for name, fn in channels:
        y = np.asarray(fn(), np.float32)
        pk = float(np.max(np.abs(y))) or 1.0
        y = (y / pk * 0.9).astype(np.float32)
        wpath = TMP_DIR / f"eval_{name}.wav"
        sf.write(str(wpath), y, SR, subtype="FLOAT")
        res = ed.decode(str(wpath), out_tag=f"sim_{name}", verbose=False)
        ch = res["channel"]
        pred = res["predict"]["predicted_tier"]
        conf = res["confirmed_tier"]
        delta = (_idx(conf) - _idx(pred))
        row = {
            "channel": name,
            "predicted_tier": pred,
            "confirmed_tier": conf,
            "predict_minus_confirm_tiers": -delta,  # +ve = predict above confirm
            "within_1_tier": bool(abs(delta) <= 1),
            "snr_db_median": ch["snr_db_median"],
            "flutter_pct": ch["flutter_pct"],
            "usable_bw_hz": ch["usable_bw_hz"],
            "imd_db": ch["imd_db"],
            "diffuse_frac": ch["diffuse_frac"],
            "clock": ch["recovered_clock"],
            "byte_exact_tiers": [r["tier"] for r in res["confirm"] if r["byte_exact"]],
        }
        table.append(row)
        print(f"  {name:13s} pred={str(pred):4s} conf={str(conf):4s} "
              f"d={(-delta):+d} SNR={ed._fmt(ch['snr_db_median'])} "
              f"flut={ed._fmt(ch['flutter_pct'],'{:.2f}')}% "
              f"BW={ed._fmt(ch['usable_bw_hz'],'{:.0f}')} "
              f"IMD={ed._fmt(ch['imd_db'],'{:.0f}')} "
              f"diff={ed._fmt(ch['diffuse_frac'],'{:.2f}')}")

    # --- gate checks ---
    # (1) across the named presets the confirmed tier is monotone non-increasing
    #     (it does NOT have to strictly drop -- all four presets are clean enough
    #     for T7 on these robust modems, which is itself a true finding).
    preset_seq = [r for r in table if r["channel"] in
                  ("pristine", "good", "normal", "worn")]
    p_idx = [_idx(r["confirmed_tier"]) for r in preset_seq]
    preset_monotone = all(p_idx[i] >= p_idx[i + 1] for i in range(len(p_idx) - 1))

    # (2) DEGRADATION PROOF: across the stress ladder the confirmed tier must
    #     monotonically DROP (strictly, end-to-end) as the channel worsens.
    stress_seq = [r for r in table if r["channel"].startswith("stress_")]
    s_idx = [_idx(r["confirmed_tier"]) for r in stress_seq]
    stress_monotone = all(s_idx[i] >= s_idx[i + 1] for i in range(len(s_idx) - 1))
    stress_drops = len(s_idx) >= 2 and s_idx[0] > s_idx[-1]

    # (3) predict tracks confirm within +-1 tier on EVERY channel
    track = all(r["within_1_tier"] for r in table)

    summary = {
        "preset_confirmed_monotone_nonincreasing": bool(preset_monotone),
        "preset_confirmed_sequence": [r["confirmed_tier"] for r in preset_seq],
        "stress_confirmed_monotone_nonincreasing": bool(stress_monotone),
        "stress_confirmed_drops_end_to_end": bool(stress_drops),
        "stress_confirmed_sequence": [r["confirmed_tier"] for r in stress_seq],
        "predict_tracks_confirm_within_1_tier_all_channels": bool(track),
        "real_master3_predict_equals_confirm": bool(
            next((r["predicted_tier"] == r["confirmed_tier"]
                  for r in table if r["channel"] == "real_master3"), False)),
        "gate_b_pass": bool(preset_monotone and stress_monotone and stress_drops
                            and track),
    }
    out = {"channels": table, "summary": summary, "tier_order": TIER_ORDER}
    RESULTS.write_text(json.dumps(out, indent=2, default=float))
    print()
    print(f"  presets monotone non-increasing: {preset_monotone} "
          f"({summary['preset_confirmed_sequence']})")
    print(f"  stress ladder confirmed drops: {stress_drops} "
          f"({summary['stress_confirmed_sequence']})")
    print(f"  predict tracks confirm (+-1) ALL channels: {track}")
    print(f"  GATE B PASS: {summary['gate_b_pass']}")
    print(f"  wrote {RESULTS}")
    return out


if __name__ == "__main__":
    run()
