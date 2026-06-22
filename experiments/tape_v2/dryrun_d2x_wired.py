"""dryrun_d2x_wired.py -- push the d2x (Dense2x DQPSK) ladder through the WIRED
(electrical line-in) channel model and report, per rung, whether RS should close
to byte-exact over the wired path. Brackets the cliff above the proven r6 rung.

This mirrors assault_wired.py's eval pattern (sanity -> wired-clean -> wired-worn ->
RS-closure -> net-bps projection) but for the proven d2x DQPSK ladder rather than the
combinatorial / OFDM frontier. It reuses the REAL decode primitives:
  * Dense2xScheme / Dense2xDropScheme (Schroeder-phased TX, drop-null carriers) from
    x10_b_aggr_05_dense2x_master.py -- the exact schemes burned on the tape.
  * DQPSKScheme.demod() -- the achievable per-frame receiver: hc.find_preamble chirp
    sync + Hann-windowed per-carrier complex DFT + pilot-tracked timing drift +
    one-shot decision-directed timing refinement. NO genie / truth used in the loop.
  * wired_channel() + WIRED / WIRED_WORN presets from assault_wired.py (frozen
    cassette_channel at a clean line-in operating point, no acoustic terms).

Sync fidelity note: a real tape decode does ONE global chirp-pair + front-sounder
clock recovery for the whole tape, then per-frame chirp preambles. Here each frame is
modulated stand-alone (its own 0.25 s preamble) and passed through the channel, so the
per-frame demod's hc.find_preamble does the sync -- exactly the per-frame path
run_dqpsk_rung uses in h4_dqpsk.py. We do not model the global resample; the WIRED
preset's flutter is already the POST-sync residual (see assault_wired.py _FLUTTER_RES),
so this is the honest post-sync operating point, not a double-count.

Run:  python3 experiments/tape_v2/dryrun_d2x_wired.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
_HERE = ROOT / "experiments" / "tape_v2"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "deepdive2", _HERE):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)

# --- wired channel + presets (reuse assault_wired.py verbatim) -------------
from assault_wired import wired_channel, WIRED, WIRED_WORN, FS  # noqa: E402
# --- the EXACT tape schemes ------------------------------------------------
from x10_b_aggr_05_dense2x_master import (  # noqa: E402
    Dense2xScheme, Dense2xDropScheme, DROP_P18, DROP_P21, PILOT_HZ,
)
# --- the PRODUCTION receiver (resampling-PLL / EMA front-end) --------------
from x9_resampling_pll import ResamplingPLLDemod  # noqa: E402

np.seterr(all="ignore")

RESULTS = _HERE / "results"
RS_N = 255

# RS(255,k) corrects t = (255-k)//2 byte errors per codeword. A rung "closes"
# (projected byte-exact) if the MEAN per-codeword byte-error fraction sits
# comfortably below that correction fraction. assault_wired.py uses a margin
# threshold (RS_MARGIN=0.20) below the raw ceiling for interleave headroom; we
# do the same -- close if mean byte_er < 0.85 * (t/255) (15 % guard band for
# the variance the mean hides), and call MARGINAL in the 0.85..1.0 band.
RS_GUARD = 0.85


def rs_t_frac(k: int) -> float:
    """Per-codeword byte-correction fraction of RS(255,k)."""
    t = (RS_N - k) // 2
    return t / RS_N


# ---------------------------------------------------------------------------
# The ladder. r5/r6/r8 are the tape rungs; >r8 are hypothetical cliff-brackets.
# (r7 == r6 twin, skipped per spec.) "P" is data-carrier count; net = gross*k/255.
# ---------------------------------------------------------------------------
def make_tx_scheme(spec: dict):
    """TX = production tape geometry (skip=64; sets framing/quadrant mapping)."""
    if spec["kind"] == "drop":
        return Dense2xDropScheme(spec["P"], spec["drop"], pilot_hz=PILOT_HZ, skip=64)
    return Dense2xScheme(spec["P"], skip=64)


def make_rx_demod(spec: dict):
    """RX = the PRODUCTION decode path: hann256_skip0 receiver scheme (the probe
    winner; the base skip=64/Hann128 window is NON-ORTHOGONAL at 2-bin spacing) +
    the proven EMA(0.7) pilot-tracking front-end. This is exactly what
    x10_b_aggr_05_dense2x_decode._frontends_for ranks first."""
    if spec["kind"] == "drop":
        sch_rx = Dense2xDropScheme(spec["P"], spec["drop"], pilot_hz=PILOT_HZ, skip=0)
    else:
        sch_rx = Dense2xScheme(spec["P"], skip=0)
    return ResamplingPLLDemod(sch_rx, front_end="ema", ema_alpha=0.7)


# Grid note: the N256/sp2 comb caps at P23 (top carrier 9375 Hz < 9500 ceiling);
# P24+ overflows the band. So the only way to push ABOVE r8 (P22) is (a) one more
# carrier (P23) and (b) progressively thinner RS on the P22/P23 grid -- which is
# precisely how the realistic frontier cliff is reached.
LADDER = [
    {"id": "r5", "name": "d2x-p18-rs127", "kind": "drop", "P": 18, "drop": DROP_P18,
     "rs_k": 127, "note": "robust bank"},
    {"id": "r6", "name": "d2x-p21-rs159", "kind": "drop", "P": 21, "drop": DROP_P21,
     "rs_k": 159, "note": "PROVEN byte-exact on real cassette"},
    {"id": "r8", "name": "d2x-p22-rs179", "kind": "full", "P": 22,
     "rs_k": 179, "note": "stretch (full grid, keeps 750 Hz)"},
    # ---- cliff-brackets ABOVE r8 (thinner RS / one more carrier) ----
    {"id": "h1", "name": "d2x-p22-rs191", "kind": "full", "P": 22,
     "rs_k": 191, "note": "thinner RS on P22 grid"},
    {"id": "h2", "name": "d2x-p23-rs191", "kind": "full", "P": 23,
     "rs_k": 191, "note": "max carriers (9375 Hz) + thin RS"},
    {"id": "h3", "name": "d2x-p23-rs207", "kind": "full", "P": 23,
     "rs_k": 207, "note": "max carriers + very thin RS (push to cliff)"},
]

REPS = 10
NSYM = 200          # data symbols per rep (one synthetic RS frame's worth)


def byte_errs(tx_bits: np.ndarray, rx_bits: np.ndarray) -> tuple[int, int]:
    """Return (byte_errors, n_bytes) comparing the packed-byte streams that feed RS."""
    n = min(len(tx_bits), len(rx_bits))
    nbytes = n // 8
    tb = np.packbits(tx_bits[:nbytes * 8])
    rb = np.packbits(rx_bits[:nbytes * 8])
    return int(np.count_nonzero(tb != rb)), nbytes


def codeword_byte_er(tx_bits: np.ndarray, rx_bits: np.ndarray, k: int):
    """Per-RS-codeword byte error fraction (over 255-byte codewords laid over the
    byte stream), returns (mean_frac, max_frac, n_cw). This is the quantity RS must
    correct: t/255 per codeword."""
    n = min(len(tx_bits), len(rx_bits))
    nbytes = (n // 8)
    tb = np.packbits(tx_bits[:nbytes * 8])
    rb = np.packbits(rx_bits[:nbytes * 8])
    err = (tb != rb).astype(int)
    fracs = []
    for i in range(0, len(err) - RS_N + 1, RS_N):
        fracs.append(err[i:i + RS_N].sum() / RS_N)
    if not fracs:                                   # short -> single partial cw
        fracs = [err.sum() / max(1, len(err))]
    return float(np.mean(fracs)), float(np.max(fracs)), len(fracs)


def eval_rung(spec: dict) -> dict:
    sch = make_tx_scheme(spec)
    dem = make_rx_demod(spec)
    P = sch.P
    bps = sch.bits_per_sym
    gross = sch.gross_bps
    k = spec["rs_k"]
    rg = np.random.default_rng(1000 + P * 7 + k)

    def _demod(audio):
        rb, _ = dem.demod(np.asarray(audio, np.float64), NSYM, refine=True)
        return np.asarray(rb, np.uint8).ravel()

    # 1) zero-channel sanity -- modulate -> demod must be bit-exact
    sb = rg.integers(0, 2, size=NSYM * bps, dtype=np.uint8)
    rx = _demod(sch.modulate(sb))
    m = min(len(sb), len(rx))
    sanity_ber = (int(np.count_nonzero(sb[:m] != rx[:m])) + abs(len(sb) - m)) / len(sb)

    def run_preset(preset: dict):
        be = bt = 0
        cw_means, cw_maxes = [], []
        for rep in range(REPS):
            bits = rg.integers(0, 2, size=NSYM * bps, dtype=np.uint8)
            a = sch.modulate(bits)
            y = wired_channel(a, preset, seed_offset=rep)
            rb = _demod(y)
            mm = min(len(bits), len(rb))
            if len(rb) < len(bits):
                rb = np.concatenate([rb, np.zeros(len(bits) - len(rb), np.uint8)])
            be += int(np.count_nonzero(bits != rb[:len(bits)]))
            bt += len(bits)
            cwm, cwx, _ = codeword_byte_er(bits, rb, k)
            cw_means.append(cwm)
            cw_maxes.append(cwx)
            beb, nbb = byte_errs(bits, rb)
        ber = be / max(1, bt)
        mean_byte_er = float(np.mean(cw_means))
        # worst-case across reps of the per-codeword max (the codeword that
        # determines whether the whole frame survives)
        worst_cw = float(np.max(cw_maxes))
        return ber, mean_byte_er, worst_cw

    clean_ber, clean_byte_er, clean_worst = run_preset(WIRED)
    worn_ber, worn_byte_er, worn_worst = run_preset(WIRED_WORN)

    tfrac = rs_t_frac(k)
    close_thr = RS_GUARD * tfrac

    def verdict(worst: float) -> str:
        # worst = worst-case per-codeword byte-error fraction observed. RS closes
        # iff every codeword's errors <= t. Use the worst observed codeword vs the
        # exact ceiling, with the guard band for the unseen tail.
        if worst < close_thr:
            return "CLOSES"
        if worst < tfrac:
            return "MARGINAL"
        return "FAILS"

    clean_v = verdict(clean_worst)
    worn_v = verdict(worn_worst)

    net = gross * k / RS_N
    return {
        "id": spec["id"], "name": spec["name"], "P": P, "rs_k": k,
        "gross_bps": gross, "net_bps_mono": net, "net_bps_stereo": net * 2,
        "rs_t_per_cw": (RS_N - k) // 2, "rs_t_frac": tfrac, "close_thr": close_thr,
        "sanity_ber": sanity_ber,
        "clean_ber": clean_ber, "clean_byte_er": clean_byte_er,
        "clean_worst_cw": clean_worst, "clean_verdict": clean_v,
        "worn_ber": worn_ber, "worn_byte_er": worn_byte_er,
        "worn_worst_cw": worn_worst, "worn_verdict": worn_v,
        "note": spec["note"],
    }


def stress_sweep(spec: dict) -> list[dict]:
    """The wired/worn presets leave the whole ladder error-free, so the cliff is
    NOT reached within the geometry. To locate where the d2x PHY actually breaks
    (margin headroom), sweep a degrading channel on the most aggressive rung until
    RS can no longer close. Reported as the operating-point margin, not a tape rung."""
    sch = make_tx_scheme(spec)
    dem = make_rx_demod(spec)
    bps = sch.bits_per_sym
    k = spec["rs_k"]
    tfrac = rs_t_frac(k)
    rg = np.random.default_rng(7777)
    grid = [(50, 0.05), (44, 0.09), (38, 0.20), (32, 0.40), (28, 0.60),
            (24, 0.90), (20, 1.50), (16, 2.50)]
    rows = []
    for snr, flut_pct in grid:
        preset = dict(snr_db=float(snr), bandwidth_hz=11_000.0,
                      wow_flutter_wrms=flut_pct / 100.0)
        worst = 0.0
        be = bt = 0
        for rep in range(8):
            bits = rg.integers(0, 2, size=NSYM * bps, dtype=np.uint8)
            y = wired_channel(sch.modulate(bits), preset, seed_offset=rep)
            rb, _ = dem.demod(np.asarray(y, np.float64), NSYM, refine=True)
            rb = np.asarray(rb, np.uint8).ravel()
            if len(rb) < len(bits):
                rb = np.concatenate([rb, np.zeros(len(bits) - len(rb), np.uint8)])
            be += int(np.count_nonzero(bits != rb[:len(bits)])); bt += len(bits)
            _, cwx, _ = codeword_byte_er(bits, rb, k)
            worst = max(worst, cwx)
        closes = worst < tfrac
        rows.append({"snr_db": snr, "flutter_pct": flut_pct,
                     "ber": be / max(1, bt), "worst_cw": worst,
                     "rs_t_frac": tfrac, "rs_closes": bool(closes)})
        print(f"    stress SNR={snr:>2}dB flut={flut_pct:>4.2f}% : "
              f"BER={be/max(1,bt):.4f} worst_cw={worst:.4f} "
              f"(RS ceil {tfrac:.3f}) -> {'CLOSES' if closes else 'FAILS'}", flush=True)
    return rows


def main():
    t0 = time.time()
    print("=" * 100)
    print("DRY-RUN: d2x DQPSK ladder over the WIRED (electrical line-in) channel")
    print(f"  WIRED      : SNR {WIRED['snr_db']} dB band {WIRED['bandwidth_hz']:.0f} Hz "
          f"flutter {WIRED['wow_flutter_wrms']*100:.3f}%")
    print(f"  WIRED_WORN : SNR {WIRED_WORN['snr_db']} dB band {WIRED_WORN['bandwidth_hz']:.0f} Hz "
          f"flutter {WIRED_WORN['wow_flutter_wrms']*100:.3f}%")
    print(f"  {REPS} reps/rung, {NSYM} sym/rep, RS guard {RS_GUARD}")
    print("=" * 100)

    rows = []
    for spec in LADDER:
        r = eval_rung(spec)
        rows.append(r)
        print(f"[{r['id']:>2}] {r['name']:16s} P{r['P']:>2} RS(255,{r['rs_k']}) "
              f"sanityBER={r['sanity_ber']:.2e} | "
              f"clean byte_er={r['clean_byte_er']:.4f} worst_cw={r['clean_worst_cw']:.4f} "
              f"{r['clean_verdict']:8s} | "
              f"worn byte_er={r['worn_byte_er']:.4f} worst_cw={r['worn_worst_cw']:.4f} "
              f"{r['worn_verdict']:8s} | net {r['net_bps_mono']:.0f}/{r['net_bps_stereo']:.0f}",
              flush=True)

    # The wired/worn presets leave the ladder error-free up to the grid ceiling,
    # so locate the actual breakdown by degrading the channel on the most
    # aggressive rung (h3 = P23/RS207) -- this is the headroom margin.
    print("\n[stress sweep on the most aggressive rung -- find the real cliff]",
          flush=True)
    stress = stress_sweep(LADDER[-1])

    out = {
        "preset_wired": WIRED, "preset_wired_worn": WIRED_WORN,
        "reps": REPS, "nsym": NSYM, "rs_guard": RS_GUARD,
        "fs": FS, "rows": rows,
        "stress_sweep_rung": LADDER[-1]["name"], "stress_sweep": stress,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    outp = RESULTS / "dryrun_d2x_wired.json"
    outp.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[done] {outp}  ({time.time()-t0:.0f}s)")
    return out


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
