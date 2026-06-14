"""c5_ftn.py — Hypothesis C5 (moonshot): Faster-than-Nyquist tone packing.

Lever (a): place an MFSK tone grid and SHORTEN the symbol hop below the
orthogonality period T_orth = 1/delta_f, accepting controlled inter-symbol /
inter-tone interference, then recover the per-symbol tone with a coherent
matched-filter bank that knows the fixed tone set.

Packing knobs:
  - alpha_t : time-compression. We emit one orthogonal-length hanning-tapered
              tone burst per symbol but ADVANCE by hop = alpha_t * N_burst.
              alpha_t = 1.0 == orthogonal MFSK baseline; alpha_t < 1.0 == FTN
              (more symbols/sec, more ICI, more bits/band-second).
  - M, band : the orthogonal tone grid (same rule as the MFSK reference).

This file:
  1. SANITY GATE: modulate->demodulate with NO channel, BER must be ~0.
  2. grid sweep over (M, alpha_t) at n_seeds=8.
  3. confirm best at canonical n_seeds=16, payload_bits=4000.

Reference to beat: MFSK-32 net_bps=1075.6. ACCEPT bar net_bps>=1614, P_full=1.0.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc  # noqa: E402

SAMPLE_RATE = 48_000
RESULTS_DIR = ROOT / "experiments" / "capacity" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MFSK32_NET_BPS = 1075.6
ACCEPT_NET_BPS = 1.5 * MFSK32_NET_BPS  # 1613.4


class FTNScheme:
    """MFSK on an orthogonal tone grid, symbol hop compressed by alpha_t."""

    def __init__(
        self,
        M: int = 32,
        alpha_t: float = 1.0,
        bw_low: float = 400.0,
        bw_high: float = 10_500.0,
        preamble_seconds: float = 0.25,
        amp: float = 0.70,
        taper: bool = True,
    ):
        assert M >= 2 and (M & (M - 1)) == 0
        self.M = M
        self.bits_per_sym = int(math.log2(M))
        self.bw_low = bw_low
        self.bw_high = bw_high
        self.alpha_t = float(alpha_t)
        self.preamble_seconds = preamble_seconds
        self.amp = amp
        self.taper = taper

        bw = bw_high - bw_low
        self.delta_f = bw / (M - 1)
        self.T_orth = 1.0 / self.delta_f
        self.T_sym = self.alpha_t * self.T_orth

        self.N_burst = int(round(self.T_orth * SAMPLE_RATE))
        self.hop = max(1, int(round(self.alpha_t * self.N_burst)))

        self.freqs = np.array(
            [bw_low + i * self.delta_f for i in range(M)], dtype=np.float64
        )

        t = np.arange(self.N_burst, dtype=np.float64) / SAMPLE_RATE
        self._win = np.hanning(self.N_burst) if (taper and self.N_burst > 1) else np.ones(self.N_burst)
        self._tone_bursts = np.stack(
            [np.sin(2.0 * math.pi * f * t) * self._win for f in self.freqs]
        )

        self._preamble = hc.make_preamble(preamble_seconds).astype(np.float32)
        self.erasure_fn = None
        self.name = f"C5_ftn_M{M}_a{alpha_t:.2f}"

    def _n_syms_for(self, n_data_bits: int) -> int:
        return math.ceil(n_data_bits / self.bits_per_sym)

    def _total_samples_for(self, n_syms: int) -> int:
        body = (n_syms - 1) * self.hop + self.N_burst if n_syms else 0
        return len(self._preamble) + body

    @property
    def gross_bps(self) -> float:
        n_syms = self._n_syms_for(4000)
        dur = self._total_samples_for(n_syms) / SAMPLE_RATE
        return 4000.0 / dur if dur > 0 else 0.0

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        bits = np.asarray(bits, dtype=np.uint8)
        bps = self.bits_per_sym
        pad = (bps - len(bits) % bps) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
        n_syms = len(bits) // bps

        body_len = (n_syms - 1) * self.hop + self.N_burst if n_syms else 0
        body = np.zeros(body_len, dtype=np.float64)
        for i in range(n_syms):
            sym_bits = bits[i * bps:(i + 1) * bps]
            sym_idx = int(np.packbits(sym_bits, bitorder="big")[0]) >> (8 - bps)
            sym_idx = min(sym_idx, self.M - 1)
            s = i * self.hop
            body[s:s + self.N_burst] += self._tone_bursts[sym_idx]

        audio = np.concatenate([self._preamble.astype(np.float64), body])
        peak = np.max(np.abs(audio)) if len(audio) else 1.0
        if peak > 0:
            audio = audio / peak * self.amp
        return audio.astype(np.float32)

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float64)
        data_start = hc.find_preamble(audio, self.preamble_seconds)
        data = audio[data_start:]

        N = self.N_burst
        hop = self.hop
        if len(data) < N:
            return np.zeros(0, dtype=np.uint8)
        n_syms = (len(data) - N) // hop + 1
        if n_syms <= 0:
            return np.zeros(0, dtype=np.uint8)

        t = np.arange(N, dtype=np.float64) / sr
        win = self._win
        cos_bank = np.stack([np.cos(2 * math.pi * f * t) * win for f in self.freqs])
        sin_bank = np.stack([np.sin(2 * math.pi * f * t) * win for f in self.freqs])

        bps = self.bits_per_sym
        out = np.empty(n_syms * bps, dtype=np.uint8)
        starts = np.arange(n_syms) * hop
        idx = starts[:, None] + np.arange(N)[None, :]
        idx = np.clip(idx, 0, len(data) - 1)
        W = data[idx]

        c = W @ cos_bank.T
        s = W @ sin_bank.T
        energy = c * c + s * s
        best = np.argmax(energy, axis=1)

        for i, sym in enumerate(best):
            bits_sym = np.unpackbits(np.array([int(sym)], dtype=np.uint8), bitorder="big")[-bps:]
            out[i * bps:(i + 1) * bps] = bits_sym
        return out


def sanity_ber(scheme: FTNScheme, payload_bits: int = 4000) -> float:
    rng = np.random.default_rng(42)
    bits = rng.integers(0, 2, size=payload_bits, dtype=np.uint8)
    audio = scheme.modulate(bits)
    rec = scheme.demodulate(audio, SAMPLE_RATE)
    n = len(bits)
    m = min(n, len(rec))
    errs = int(np.count_nonzero(bits[:m] != rec[:m])) + (n - m)
    return errs / n


def eval_one(scheme: FTNScheme, n_seeds: int, payload_bits: int) -> dict:
    ev = hc.evaluate_scheme(
        scheme, tape_preset="normal", n_seeds=n_seeds,
        payload_bits=payload_bits, capture_key="usb_soundcard",
    )
    proj = hc.project_to_cassette(
        raw_ber=ev["raw_bit_error_rate"],
        erasure_rate=ev["erasure_rate"],
        gross_bps=ev["gross_bps"],
    )
    return {**ev, **proj}


def main():
    print("=" * 70)
    print("C5 — Faster-than-Nyquist tone packing (moonshot)")
    print(f"ACCEPT bar: net_bps >= {ACCEPT_NET_BPS:.1f} (1.5x MFSK-32={MFSK32_NET_BPS})")
    print("=" * 70)

    s_orth = FTNScheme(M=32, alpha_t=1.0)
    sb_orth = sanity_ber(s_orth)
    print(f"[sanity] M32 alpha=1.00 no-channel BER = {sb_orth:.2e}  gross={s_orth.gross_bps:.0f}")

    grid = []
    for M in [32, 16]:
        for alpha in [1.00, 0.90, 0.80, 0.70, 0.60, 0.50]:
            grid.append((M, alpha))

    print(f"\nSweeping {len(grid)} configs at n_seeds=8 ...")
    sweep = []
    for M, alpha in grid:
        sc = FTNScheme(M=M, alpha_t=alpha)
        sbn = sanity_ber(sc)
        t0 = time.time()
        r = eval_one(sc, n_seeds=8, payload_bits=4000)
        row = {
            "M": M, "alpha_t": alpha, "name": sc.name,
            "gross_bps": r["gross_bps"], "raw_ber": r["raw_bit_error_rate"],
            "erasure_rate": r["erasure_rate"], "net_bps": r["net_bps"],
            "P_full": r["P_full"], "MB_C90_stereo": r["MB_C90_stereo"],
            "sanity_ber": sbn,
        }
        sweep.append(row)
        print(
            f"  M={M:2d} a={alpha:.2f}  gross={r['gross_bps']:6.0f}  "
            f"sanity={sbn:.1e}  BER={r['raw_bit_error_rate']:.2e}  "
            f"net={r['net_bps']:7.1f}  P={r['P_full']:.2f}  ({time.time()-t0:.0f}s)"
        )

    valid = [r for r in sweep if r["P_full"] >= 1.0 and r["sanity_ber"] <= 1e-3]
    valid.sort(key=lambda r: r["net_bps"], reverse=True)
    best = valid[0] if valid else max(sweep, key=lambda r: r["net_bps"])
    print(f"\nBest @n8: {best['name']}  net={best['net_bps']:.1f}  P={best['P_full']:.2f}")

    print("\nConfirming best at canonical n_seeds=16, payload_bits=4000 ...")
    sc_best = FTNScheme(M=best["M"], alpha_t=best["alpha_t"])
    sb_best = sanity_ber(sc_best)
    conf = eval_one(sc_best, n_seeds=16, payload_bits=4000)
    print(
        f"  {sc_best.name}: sanity={sb_best:.2e}  gross={conf['gross_bps']:.1f}  "
        f"BER={conf['raw_bit_error_rate']:.2e}  net={conf['net_bps']:.1f}  "
        f"P_full={conf['P_full']:.2f}  MB_C90={conf['MB_C90_stereo']:.3f}"
    )

    ratio = conf["net_bps"] / MFSK32_NET_BPS
    verdict = (
        "ACCEPT" if (conf["net_bps"] >= ACCEPT_NET_BPS and conf["P_full"] >= 1.0
                     and sb_best <= 1e-6) else "REJECT"
    )

    out = {
        "experiment": "c5_ftn",
        "accept_net_bps": ACCEPT_NET_BPS,
        "mfsk32_net_bps": MFSK32_NET_BPS,
        "sanity_ber_orth": sb_orth,
        "sweep_n8": sweep,
        "best_config": best,
        "confirm_n16": {**{k: conf[k] for k in (
            "gross_bps", "raw_bit_error_rate", "erasure_rate", "net_bps",
            "P_full", "MB_C90_stereo")}, "sanity_ber": sb_best,
            "name": sc_best.name},
        "ratio_vs_mfsk32": ratio,
        "verdict": verdict,
    }
    out_path = RESULTS_DIR / "c5_ftn.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2,
                  default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"\nSaved {out_path}")
    print(f"VERDICT: {verdict}  ratio={ratio:.3f}x")
    return out


if __name__ == "__main__":
    main()
