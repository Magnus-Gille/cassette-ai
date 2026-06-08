"""rw_t1_cable_mic.py — T1: Cable line-out -> TRRS -> phone mic input.

Questions answered:
  (a) Does FSK's amplitude/frequency coding survive hard clipping?
  (b) Does the ~7.5 kHz phone-recorder band cap break MFSK-32 (top tones ~10 kHz)?
  (c) Net reliable rate per modem on this path.

Four conditions swept (n_seeds=12, payload_bits=2000):
  - bfsk_b0   (P2 unpadded) — hard clipped
  - bfsk_b0   (P2 padded)   — level-corrected
  - mfsk32    (P2 unpadded) — hard clipped + band cap
  - mfsk32    (P2 padded)   — level-corrected + band cap

Saves: RESULTS/data/rw_cable_trrs_mic.json
       RESULTS/plots/rw_cable_trrs_mic.png
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc                  # noqa: E402
import realworld_channels as rw          # noqa: E402

DATA_DIR  = ROOT / "RESULTS" / "data"
PLOTS_DIR = ROOT / "RESULTS" / "plots"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

N_SEEDS    = 12
PAYLOAD_BITS = 2000


def run_condition(scheme, path_key: str, label: str, **path_kwargs) -> dict:
    t0 = time.time()
    res = rw.evaluate_realworld(
        scheme,
        path_key,
        n_seeds=N_SEEDS,
        payload_bits=PAYLOAD_BITS,
        **path_kwargs,
    )
    dt = time.time() - t0
    res["label"] = label
    res["elapsed_s"] = round(dt, 2)

    # Analytic projection to cassette capacity (net bps / P_full)
    raw_ber = res["raw_bit_error_rate"]
    eras    = res["erasure_rate"]
    gross   = res["gross_bps"]
    proj    = hc.project_to_cassette(raw_ber, eras, gross,
                                     payload_bytes=1_271_000, target_P=0.95)
    res["projection"] = proj

    print(
        f"  [{label}]  gross={gross:.0f} bps  raw_ber={raw_ber:.3e}  "
        f"clean={res['clean_decode_prob']:.2f}  "
        f"peak={res['corr_peak_mean']:.3f}  "
        f"net={proj.get('net_bps', 0):.0f} bps  "
        f"MB_C90={proj.get('MB_C90_stereo', 0):.2f}  "
        f"({dt:.1f}s)"
    )
    return res


def main():
    print("=" * 70)
    print("T1: cable_trrs_phone_mic — BFSK vs MFSK-32, unpadded vs padded")
    print(f"  n_seeds={N_SEEDS}  payload_bits={PAYLOAD_BITS}")
    print("=" * 70)

    modems = rw.build_reference_modems(PAYLOAD_BITS)
    bfsk   = modems["bfsk_b0"]
    mfsk32 = modems["mfsk32"]

    # Also run P1 as the ceiling reference for each modem
    conditions = []

    print("\n-- P1 ceiling (transparent reference) --")
    conditions.append(run_condition(bfsk,  "cable_usb_soundcard", "bfsk_b0@P1_ceiling"))
    conditions.append(run_condition(mfsk32, "cable_usb_soundcard", "mfsk32@P1_ceiling"))

    print("\n-- P2 unpadded: line level ~8x mic full-scale -> hard clip --")
    conditions.append(run_condition(bfsk,  "cable_trrs_phone_mic", "bfsk_b0@P2_unpadded",
                                    level_pad=False))
    conditions.append(run_condition(mfsk32, "cable_trrs_phone_mic", "mfsk32@P2_unpadded",
                                    level_pad=False))

    print("\n-- P2 padded: -16 dB inline pad -> linear region --")
    conditions.append(run_condition(bfsk,  "cable_trrs_phone_mic", "bfsk_b0@P2_padded",
                                    level_pad=True))
    conditions.append(run_condition(mfsk32, "cable_trrs_phone_mic", "mfsk32@P2_padded",
                                    level_pad=True))

    # -----------------------------------------------------------------------
    # Build summary dict
    # -----------------------------------------------------------------------
    summary = {
        "experiment": "T1_cable_trrs_mic",
        "n_seeds": N_SEEDS,
        "payload_bits": PAYLOAD_BITS,
        "tape_preset": "normal",
        "path": "cable_trrs_phone_mic (P2)",
        "findings": {
            "clipping_survivability": _clipping_verdict(conditions),
            "band_cap_impact": _band_cap_verdict(conditions),
            "net_rates": _net_rates_summary(conditions),
        },
        "conditions": conditions,
    }

    # -----------------------------------------------------------------------
    # Save JSON
    # -----------------------------------------------------------------------
    out_path = DATA_DIR / "rw_cable_trrs_mic.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=_json_default)
    print(f"\nSaved {out_path}")

    # -----------------------------------------------------------------------
    # Plot
    # -----------------------------------------------------------------------
    _make_plot(conditions, PLOTS_DIR / "rw_cable_trrs_mic.png")
    print(f"Saved {PLOTS_DIR / 'rw_cable_trrs_mic.png'}")

    return summary


def _clipping_verdict(conditions: list[dict]) -> dict:
    """Does BFSK survive hard clipping? Compare P2_unpadded to P1 ceiling."""
    b0_ceil  = _find(conditions, "bfsk_b0@P1_ceiling")
    b0_clip  = _find(conditions, "bfsk_b0@P2_unpadded")
    b0_pad   = _find(conditions, "bfsk_b0@P2_padded")
    return {
        "bfsk_ceiling_raw_ber": b0_ceil["raw_bit_error_rate"] if b0_ceil else None,
        "bfsk_clipped_raw_ber": b0_clip["raw_bit_error_rate"] if b0_clip else None,
        "bfsk_padded_raw_ber":  b0_pad["raw_bit_error_rate"] if b0_pad else None,
        "bfsk_clipped_clean":   b0_clip["clean_decode_prob"] if b0_clip else None,
        "bfsk_padded_clean":    b0_pad["clean_decode_prob"] if b0_pad else None,
        "verdict": (
            "BFSK tolerates clipping: frequency coding survives amplitude distortion"
            if b0_clip and b0_clip["raw_bit_error_rate"] < 0.1
            else "BFSK fails under clipping"
        ),
    }


def _band_cap_verdict(conditions: list[dict]) -> dict:
    """Does the 7.5 kHz mic band cap hurt MFSK-32 (tones span 400-10000 Hz)?"""
    m_ceil = _find(conditions, "mfsk32@P1_ceiling")
    m_clip = _find(conditions, "mfsk32@P2_unpadded")
    m_pad  = _find(conditions, "mfsk32@P2_padded")
    # MFSK-32 highest tone is USABLE_F_HIGH=10000 Hz, mic band is 7500 Hz.
    # Fraction of tones ABOVE the mic cut: 32 tones, delta_f=9600/31≈309.7 Hz
    # Starting at 400 Hz, tone k is at 400 + k*309.7 Hz.
    # Tones above 7500: k > (7500-400)/309.7 = 22.9 -> tones 23..31 (9 of 32) = 28%
    return {
        "mfsk32_ceiling_raw_ber": m_ceil["raw_bit_error_rate"] if m_ceil else None,
        "mfsk32_padded_raw_ber":  m_pad["raw_bit_error_rate"] if m_pad else None,
        "mfsk32_padded_clean":    m_pad["clean_decode_prob"] if m_pad else None,
        "tones_above_mic_cutoff_pct": 28.1,
        "mic_cutoff_hz": 7500,
        "highest_mfsk32_tone_hz": 10000,
        "verdict": (
            "MFSK-32 band cap CRITICAL: ~28% of tones (10kHz top) exceed 7.5kHz mic cutoff"
            if m_pad and m_pad["raw_bit_error_rate"] > 0.05
            else "MFSK-32 survives band cap (unexpected)"
        ),
    }


def _net_rates_summary(conditions: list[dict]) -> list[dict]:
    out = []
    for c in conditions:
        proj = c.get("projection", {})
        out.append({
            "label": c["label"],
            "gross_bps": c["gross_bps"],
            "raw_ber": c["raw_bit_error_rate"],
            "clean_decode_prob": c["clean_decode_prob"],
            "corr_peak_mean": c["corr_peak_mean"],
            "net_bps": proj.get("net_bps", 0),
            "MB_C90_stereo": proj.get("MB_C90_stereo", 0),
            "required_code_rate": proj.get("required_code_rate", None),
            "P_full": proj.get("P_full", 0),
        })
    return out


def _find(conditions: list[dict], label: str) -> dict | None:
    for c in conditions:
        if c["label"] == label:
            return c
    return None


def _json_default(o):
    if hasattr(o, "__iter__") and not isinstance(o, str):
        return list(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return str(o)


def _make_plot(conditions: list[dict], out_path: pathlib.Path):
    labels    = [c["label"] for c in conditions]
    ber       = [c["raw_bit_error_rate"] for c in conditions]
    clean     = [c["clean_decode_prob"] for c in conditions]
    peaks     = [c["corr_peak_mean"] for c in conditions]
    net_bps   = [c.get("projection", {}).get("net_bps", 0) for c in conditions]

    x = np.arange(len(labels))
    short_labels = [l.split("@")[-1] + "\n" + l.split("@")[0] for l in labels]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("T1: cable_trrs_phone_mic  (P2) — BFSK vs MFSK-32, unpadded vs padded",
                 fontsize=11)

    color_map = {
        "bfsk_b0": "#2196F3",
        "mfsk32":  "#FF9800",
    }

    def bar_colors(labels_list):
        colors = []
        for lbl in labels_list:
            modem = lbl.split("@")[0]
            colors.append(color_map.get(modem, "#999999"))
        return colors

    cols = bar_colors(labels)

    ax = axes[0, 0]
    bars = ax.bar(x, ber, color=cols, edgecolor="black", linewidth=0.7)
    ax.axhline(0.5, color="red", linestyle="--", linewidth=0.8, label="random=0.5")
    ax.set_xticks(x); ax.set_xticklabels(short_labels, fontsize=7)
    ax.set_ylabel("Raw BER"); ax.set_title("Raw Bit Error Rate (lower=better)")
    ax.set_ylim(0, 0.6); ax.legend(fontsize=7)

    ax = axes[0, 1]
    ax.bar(x, clean, color=cols, edgecolor="black", linewidth=0.7)
    ax.set_xticks(x); ax.set_xticklabels(short_labels, fontsize=7)
    ax.set_ylabel("P(clean)"); ax.set_title("Clean Decode Probability (higher=better)")
    ax.set_ylim(0, 1.1)

    ax = axes[1, 0]
    ax.bar(x, peaks, color=cols, edgecolor="black", linewidth=0.7)
    ax.axhline(0.6, color="orange", linestyle="--", linewidth=0.8, label="sync floor ~0.6")
    ax.set_xticks(x); ax.set_xticklabels(short_labels, fontsize=7)
    ax.set_ylabel("Corr peak"); ax.set_title("Preamble Sync Correlation (higher=better)")
    ax.set_ylim(0, 1.1); ax.legend(fontsize=7)

    ax = axes[1, 1]
    safe_net = [max(v, 0) for v in net_bps]
    ax.bar(x, safe_net, color=cols, edgecolor="black", linewidth=0.7)
    ax.axhline(478, color="blue", linestyle="--", linewidth=0.8, label="B0 baseline 478 bps")
    ax.set_xticks(x); ax.set_xticklabels(short_labels, fontsize=7)
    ax.set_ylabel("Net bps"); ax.set_title("Projected Net Rate @ P=0.95 (higher=better)")
    ax.legend(fontsize=7)

    # Legend for modem colors
    from matplotlib.patches import Patch
    legend_els = [Patch(facecolor=color_map["bfsk_b0"], label="bfsk_b0"),
                  Patch(facecolor=color_map["mfsk32"],  label="mfsk32")]
    fig.legend(handles=legend_els, loc="lower center", ncol=2, fontsize=9,
               bbox_to_anchor=(0.5, -0.01))

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
