"""d3d4_combo_tracked.py — D3 (flutter tracker) x D4 (combinatorial index-mod PHY).

The breakthrough of deep-dive #2: a NON-COHERENT combinatorial k-of-M tone PHY
(C2 family) decoded with the dd_common flutter tracker (global speed correction +
per-symbol energy-lock micro-tracking) is the FIRST scheme to reach P_full=1.0 on
the harsh real channel (worn + 0.88x clock + 2.5% flutter + heavy bursts).

Why it works where coherent C4-OFDM fails:
  * magnitude (energy) detection is immune to the flutter-induced phase chaos that
    wrecks coherent pilot-slope tracking;
  * top-K over a wide tone grid keeps the lit tones dominant even when a burst
    attenuates them (the prior "non-coherent shrugs off bursts" lesson);
  * the per-symbol timing tracker (center-biased, drift-carrying) follows the
    residual wow/flutter that a fixed-window reshape cannot.

D4 (index modulation) is realised intrinsically: the information is carried by
WHICH K of M tones are lit (combinatorial index), i.e. index modulation across the
tone bank — on a real flutter channel this beats QAM-on-subcarriers.

Sweep (M,K) to map the real-survival frontier: wider tone spacing (lower M) buys
flutter robustness at the cost of gross rate.
"""
from __future__ import annotations
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "capacity"))
import numpy as np
import dd_common as dd
import c2_combo_mfsk as c2mod

RESULTS = pathlib.Path(__file__).parent / "results"
SURVIVE_BER = 3e-2


def make_tracked_combo(M, K, track=3, center_bias=0.03, vel_gain=0.0):
    sch = c2mod.ComboMFSKScheme(M=M, K=K)
    N = sch.samples_per_sym
    freqs = sch.freqs
    bps = sch.bits_per_sym
    rev = sch._rev_table
    cap = sch._sym_cap

    def demod(audio, sr):
        syms, dr, lk = dd.tracked_tone_demod(
            audio, freqs, N, bps, n_bits=1 << 20,
            preamble_seconds=sch.preamble_seconds,
            track=track, center_bias=center_bias, vel_gain=vel_gain)
        out = []
        for e in syms:
            topk = tuple(sorted(np.argpartition(e, -K)[-K:].tolist()))
            sidx = min(rev.get(topk, 0), cap - 1)
            out.extend([(sidx >> (bps - 1 - j)) & 1 for j in range(bps)])
        return np.array(out, dtype=np.uint8)

    sch.demodulate = demod
    sch.name = f"D4combo_M{M}K{K}_tracked"
    sch.erasure_fn = None
    return sch


def survival(per_seed_ber, thresh=SURVIVE_BER):
    a = np.asarray(per_seed_ber, dtype=float)
    return float(np.mean(a <= thresh)) if len(a) else 0.0


def run_sweep(grid, n_seeds=12):
    rows = []
    for (M, K) in grid:
        sch = make_tracked_combo(M, K)
        out = dd.evaluate_dual(sch, n_seeds=n_seeds)
        row = {"M": M, "K": K, "bps_sym": sch.bits_per_sym,
               "sanity": out["sanity_ber"]}
        for ch in ("sim", "real"):
            d = out[ch]
            row[f"{ch}_net"] = d["net_bps"]
            row[f"{ch}_ber"] = d["raw_ber"]
            row[f"{ch}_surv"] = survival(d["per_seed_ber"])
            row[f"{ch}_gross"] = d["gross_bps"]
        rows.append(row)
        print(f"M{M:2d}K{K} bps{sch.bits_per_sym:2d} sanity{out['sanity_ber']:.0e} "
              f"| sim net{row['sim_net']:5.0f} surv{row['sim_surv']:.2f} "
              f"| real net{row['real_net']:5.0f} surv{row['real_surv']:.2f} "
              f"ber{row['real_ber']:.3f}")
    return rows


if __name__ == "__main__":
    grid = [(16, 2), (16, 3), (20, 2), (20, 3), (24, 2), (24, 3),
            (28, 3), (28, 4), (32, 3), (32, 4), (40, 4), (48, 6)]
    rows = run_sweep(grid, n_seeds=12)
    # best real net at survival >= 0.9
    surv_ok = [r for r in rows if r["real_surv"] >= 0.9]
    best_real = max(surv_ok, key=lambda r: r["real_net"]) if surv_ok else None
    best_sim = max(rows, key=lambda r: r["sim_net"])
    out = {"grid": rows,
           "best_real_at_surv0.9": best_real,
           "best_sim": best_sim}
    with open(RESULTS / "d3d4.json", "w") as f:
        json.dump(out, f, indent=2, default=float)
    print("\nBEST real@surv>=0.9:", best_real)
    print("BEST sim:", {k: best_sim[k] for k in ("M", "K", "sim_net", "real_surv")})
    print(f"[saved] {RESULTS/'d3d4.json'}")
