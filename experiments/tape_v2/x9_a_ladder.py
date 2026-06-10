"""x9_a_ladder.py — DESIGNER A ('proven-PHY scaler') master9 ladder arithmetic.

Computes, REPRODUCIBLY, the exact PHY parameters, net-bps arithmetic, tape
seconds, and measured-margin-anchored bit-loading map for every rung of the
Designer-A master9 ladder. ALL numbers derive from:
  - the FROZEN proven PHY (h4_dqpsk.DQPSKScheme: 2 bits/carrier/symbol DQPSK,
    Hann Nw=3N/4 demod, per-symbol pilot timing correction),
  - the R2 real-capture per-carrier truth margins (the 934 bps record), and
  - the orthogonality constraint spacing_bins * Nw % N == 0 (Nw = 3N/4).

It does NOT modify any shipping file and uses NO genie knowledge. Run:
    python3 experiments/tape_v2/x9_a_ladder.py
Writes experiments/tape_v2/x9_dossier/A_ladder.json.

Seed (for any stochastic check; this module is deterministic): 20260610.
"""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np

SEED = 20260610
FS = 48_000
HERE = pathlib.Path(__file__).resolve().parent
DOSSIER = HERE / "x9_dossier"

# --- R2 MEASURED per-carrier truth margins on the PROVEN 934 bps capture -----
# freq_hz -> (qpsk_raw_SER, frac_below_22.5deg [= D8PSK raw SER proxy],
#             out_SNR_dB, amp_CoV_pct). Source: R2_margins.md sections 0 & 3.
R2_CARRIER = {
    750:  (0.0,     0.00917, 16.2, 11.1),
    1500: (1.58e-4, 0.0508,  13.7, 13.8),
    2250: (1.58e-4, 0.0291,  13.9, 12.6),
    3000: (0.0,     0.0138,  14.6, 9.4),
    3750: (6.34e-2, 0.303,   8.2,  27.0),   # measured room null (carrier 4)
    5250: (1.42e-3, 0.0323,  12.2, 8.9),
    6000: (2.37e-3, 0.0318,  11.8, 6.3),
    6750: (1.98e-2, 0.136,   9.0,  18.1),
    7500: (5.80e-2, 0.167,   7.7,  20.4),
    8250: (3.46e-2, 0.0972,  8.4,  17.5),
}


def orthogonal_spacings(N: int) -> dict[int, float]:
    """Spacings (in bins) that keep carriers orthogonal over the Nw=3N/4 Hann
    window: spacing_bins * Nw % N == 0. Returns {bins: hz}."""
    Nw = N - 2 * (N // 8)          # = 3N/4
    df = FS / N
    return {sp: sp * df for sp in range(1, 33) if (sp * Nw) % N == 0}


def dense_grid(N: int, spacing_bins: int, f_lo=750.0, f_hi=9000.0) -> np.ndarray:
    """Carrier frequencies on the integer-bin dense grid, f_lo..f_hi inclusive."""
    df = FS / N
    b0 = int(round(f_lo / df))
    bins = []
    i = 0
    while True:
        b = b0 + spacing_bins * i
        if b * df > f_hi + 1e-6:
            break
        bins.append(b)
        i += 1
    return np.array(bins) * df


def bitload_map(freqs: np.ndarray) -> list[dict]:
    """Assign bits/carrier from the MEASURED R2 margins by nearest-known band.
    Rule (anchored to R2 frac<22.5deg = D8PSK raw SER proxy):
      < 0.02  -> D8PSK-safe (3 b) ; 0.02-0.06 -> D8PSK-marginal (3 b under heavy RS) ;
      >= 0.06 -> DQPSK-only (2 b)."""
    kf = np.array(sorted(R2_CARRIER))
    out = []
    for f in freqs:
        nearest = int(kf[np.argmin(np.abs(kf - f))])
        d8 = R2_CARRIER[nearest][1]
        if d8 < 0.02:
            bits, klass = 3, "D8PSK-safe"
        elif d8 < 0.06:
            bits, klass = 3, "D8PSK-marginal"
        else:
            bits, klass = 2, "DQPSK-only"
        out.append({"freq_hz": round(float(f), 1), "ref_carrier_hz": nearest,
                    "d8_frac_lt_22p5": d8, "bits": bits, "class": klass})
    return out


def dqpsk_gross(P: int, N: int) -> float:
    return (2 * P) / (N / FS)


def net_bps(gross: float, rs_k: int, rs_n: int = 255) -> float:
    return gross * rs_k / rs_n


def section_seconds(gross: float, rs_k: int, orig_bytes: int,
                    *, packed_ratio: float = 1.0, frame_bytes: int = 510,
                    preamble_s: float = 0.25, frame_gap_s: float = 0.12,
                    section_gap_s: float = 0.40) -> tuple[float, int]:
    """Tape seconds for a rung carrying `orig_bytes` of LLM (assumed ~incompressible
    int4 -> packed_ratio ~1.0). RS(255,k) expands by 255/k; m3 interleaves
    frame_bytes message bytes/frame; each frame adds a 0.25 s preamble + gap."""
    packed = orig_bytes * packed_ratio
    coded_bytes = packed * 255.0 / rs_k
    body = (coded_bytes * 8) / gross
    nframes = max(1, math.ceil(coded_bytes / frame_bytes))
    overhead = preamble_s * nframes + frame_gap_s * nframes + section_gap_s
    return body + overhead, nframes


# --- THE LADDER -------------------------------------------------------------
# Each rung: name, P, N, spacing_bins, rs_k, orig_bytes, constellation, risk.
# Constellation 'dqpsk' = 2 b/carrier (PROVEN). 'd8psk_bitload' = per-carrier
# 2 or 3 b from the measured map (gross computed from the actual map).
LADDER = [
    dict(name="m9_r0_reprove",     P=10, N=512, sp=8, rs_k=127, orig=4096,
         con="dqpsk",         risk="proven",
         note="Re-prove the 934 record on a fresh tape: identical PHY, half payload."),
    dict(name="m9_r1_rs179",       P=10, N=512, sp=8, rs_k=179, orig=6144,
         con="dqpsk",         risk="proven",
         note="Same proven 10-carrier grid; raise RS k 127->179 (record had 0/62 cwFail)."),
    dict(name="m9_r1b_rs191",      P=10, N=512, sp=8, rs_k=191, orig=6144,
         con="dqpsk",         risk="low",
         note="Push RS rate further to k=191; weakest HF carriers 6750-8250 carry the risk."),
    dict(name="m9_r2_dense_rs159", P=22, N=512, sp=4, rs_k=159, orig=8192,
         con="dqpsk",         risk="low",
         note="375 Hz spacing (AAC floor gone). ~22 carriers 750-8625 Hz, proven DQPSK."),
    dict(name="m9_r2b_dense_rs179",P=22, N=512, sp=4, rs_k=179, orig=8192,
         con="dqpsk",         risk="medium",
         note="Dense grid + lighter FEC; the expected new record."),
    dict(name="m9_r3_dense_rs191", P=23, N=512, sp=4, rs_k=191, orig=8192,
         con="dqpsk",         risk="medium",
         note="Full 23-carrier dense grid to 9000 Hz at k=191. Stretch of the dense rung."),
    dict(name="m9_s1_d8_bitload",  P=22, N=512, sp=4, rs_k=127, orig=8192,
         con="d8psk_bitload", risk="high",
         note="Per-carrier bit-loaded D8/DQPSK from R2 map, heavy RS(255,127) lottery."),
]


def build():
    np.random.seed(SEED)
    out = {"_about": "Designer A proven-PHY-scaler master9 ladder arithmetic",
           "seed": SEED,
           "orthogonal_spacings": {str(N): orthogonal_spacings(N)
                                   for N in (256, 512, 1024)},
           "rungs": []}

    cum_sec = 0.0
    print(f"{'rung':22s} {'P':>3} {'N':>4} {'sp':>3} {'spHz':>6} "
          f"{'k':>4} {'gross':>6} {'net':>6} {'orig':>5} {'sec':>6} {'frm':>4} risk")
    for r in LADDER:
        freqs = dense_grid(r["N"], r["sp"])[: r["P"] + 1]  # +1 for the pilot slot
        # data carriers = P (pilot is the middle one, unmodulated)
        data_freqs = np.delete(freqs, len(freqs) // 2)[: r["P"]]
        if r["con"] == "dqpsk":
            gross = dqpsk_gross(r["P"], r["N"])
            bload = [{"freq_hz": round(float(f), 1), "bits": 2} for f in data_freqs]
        else:  # d8psk_bitload: gross from the measured per-carrier map
            bload = bitload_map(data_freqs)
            total_bits = sum(b["bits"] for b in bload)
            gross = total_bits / (r["N"] / FS)
        net = net_bps(gross, r["rs_k"])
        sec, nframes = section_seconds(gross, r["rs_k"], r["orig"])
        cum_sec += sec
        n_cw = math.ceil(r["orig"] * 255.0 / r["rs_k"] / r["rs_k"])  # approx cw count
        out["rungs"].append({
            "name": r["name"], "P": r["P"], "N": r["N"],
            "spacing_bins": r["sp"], "spacing_hz": round(FS / r["N"] * r["sp"], 2),
            "rs_k": r["rs_k"], "rs_n": 255,
            "constellation": r["con"],
            "gross_bps": round(gross, 1), "net_bps": round(net, 1),
            "orig_bytes": r["orig"], "tape_seconds": round(sec, 1),
            "n_frames": nframes,
            "carrier_freqs_hz": [round(float(f), 1) for f in data_freqs],
            "pilot_hz": round(float(freqs[len(freqs) // 2]), 1),
            "bitload": bload,
            "risk": r["risk"], "note": r["note"],
        })
        print(f"{r['name']:22s} {r['P']:>3} {r['N']:>4} {r['sp']:>3} "
              f"{FS/r['N']*r['sp']:>6.0f} {r['rs_k']:>4} {gross:>6.0f} {net:>6.0f} "
              f"{r['orig']:>5} {sec:>6.1f} {nframes:>4} {r['risk']}")

    out["ladder_body_seconds"] = round(cum_sec, 1)
    # sync overhead: 2 global chirps (~3 s each w/ gaps) + front sounder (2x3s + gaps)
    sync_sec = 2 * (GLOBAL_CHIRP_S + 0.4) + (2 * 3.0 + 4 * 0.5) + 2 * 1.0
    # + two diagnostic probes (see design doc)
    probe_sec = PROBE1_S + PROBE2_S
    total = cum_sec + sync_sec + probe_sec
    out["sync_overhead_seconds"] = round(sync_sec, 1)
    out["diagnostic_probe_seconds"] = round(probe_sec, 1)
    out["total_tape_seconds"] = round(total, 1)
    out["total_tape_minutes"] = round(total / 60.0, 2)
    out["budget_minutes"] = 16.0
    out["within_budget"] = total / 60.0 <= 16.0

    DOSSIER.mkdir(parents=True, exist_ok=True)
    (DOSSIER / "A_ladder.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"\nbody={cum_sec:.1f}s sync={sync_sec:.1f}s probes={probe_sec:.1f}s "
          f"TOTAL={total/60:.2f} min (budget 16) -> "
          f"{'OK' if out['within_budget'] else 'OVER'}")
    print(f"[done] wrote {DOSSIER / 'A_ladder.json'}")
    return out


GLOBAL_CHIRP_S = 3.0
PROBE1_S = 12.0   # per-carrier dense-grid pilot probe (measures flutter PSD + null map)
PROBE2_S = 12.0   # D8PSK constellation probe (measures real phase-jitter headroom)

if __name__ == "__main__":
    build()
