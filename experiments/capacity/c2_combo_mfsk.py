"""c2_combo_mfsk.py — C2: Combinatorial K-of-M multitone FSK.

Instead of lighting ONE of M tones (standard MFSK), we light K of M tones
simultaneously, encoding floor(log2(C(M,K))) bits per symbol. The symbol-to-
subset mapping uses the combinatorial number system (a clean bijection between
integers [0, C(M,K)) and K-subsets of {0..M-1}).

Demodulation: non-coherent FFT magnitude -> pick top-K tone bins.

Key design choice: all M tones are placed at EXACT FFT bin centers so the
FFT magnitude at each bin is a lossless energy measurement (no spectral
leakage into adjacent tone bins). This is the Olivia/MFSK orthogonality
condition, extended to K simultaneous tones.

MFSK-32 reference: gross=1411.8 bps, raw_BER=2.02e-3, net_bps=1075.6
ACCEPT bar: net_bps >= 1.25 * 1075.6 = 1344.5, P_full=1.0
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import time
from itertools import combinations

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc  # noqa: E402

SAMPLE_RATE   = 48_000
USABLE_F_LOW  = 400.0
USABLE_F_HIGH = 10_000.0

RESULTS_DIR = ROOT / "experiments" / "capacity" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MFSK32_NET_BPS   = 1075.6
ACCEPT_THRESHOLD = 1.25 * MFSK32_NET_BPS   # 1344.5


# ---------------------------------------------------------------------------
# Tone grid: snap all tones to exact FFT bin centers (orthogonality)
# ---------------------------------------------------------------------------

def _build_tone_grid(M: int,
                     sr: int   = SAMPLE_RATE,
                     f_low: float = USABLE_F_LOW,
                     f_high: float = USABLE_F_HIGH):
    """Return (N, bin_indices, freqs) for M tones all at exact FFT bin centers.

    We choose N (FFT/symbol size) so that:
      delta_f = sr/N  (bin spacing)
      first tone bin b0 = ceil(f_low / delta_f)
      last  tone bin b1 = b0 + M - 1
      all tones within [f_low, f_high]

    Sweeps N near the Olivia estimate (sr / bw * (M-1)) to find a valid grid.
    """
    bw = f_high - f_low
    delta_f_est = bw / max(M - 1, 1)
    for dN in range(-10, 30):
        N = int(round(sr / delta_f_est)) + dN
        if N <= 0:
            continue
        delta_f = sr / N
        b0 = math.ceil(f_low / delta_f)
        b1 = b0 + M - 1
        fa = b0 * delta_f
        fb = b1 * delta_f
        if fa >= f_low - 1e-3 and fb <= f_high + 1e-3:
            bin_indices = np.arange(b0, b0 + M, dtype=np.int32)
            freqs = (bin_indices * delta_f).astype(np.float64)
            return N, bin_indices, freqs
    raise ValueError(f"Could not find clean integer-bin tone grid for M={M}")


# ---------------------------------------------------------------------------
# Combinatorial (K-of-M) lookup tables
# ---------------------------------------------------------------------------

def _build_comb_tables(M: int, K: int):
    """Return (table, rev_table, n_symbols) for the K-of-M combinatorial bijection.

    table[sym_idx]  -> np.int32 array of K sorted tone indices
    rev_table[tuple(sorted_tones)] -> sym_idx
    n_symbols = C(M, K)
    """
    subsets = list(combinations(range(M), K))  # lex order, tuples already sorted
    n_sym = len(subsets)
    table = [np.array(s, dtype=np.int32) for s in subsets]
    rev_table = {s: i for i, s in enumerate(subsets)}
    return table, rev_table, n_sym


# ---------------------------------------------------------------------------
# ComboMFSKScheme
# ---------------------------------------------------------------------------

class ComboMFSKScheme:
    """Combinatorial K-of-M multitone FSK modem.

    Parameters
    ----------
    M  : total tones in alphabet (band-spanning orthogonal grid)
    K  : tones lit simultaneously per symbol  (1 <= K < M)
    """

    def __init__(self, M: int = 32, K: int = 2, preamble_seconds: float = 0.25,
                 f_low: float = USABLE_F_LOW, f_high: float = USABLE_F_HIGH):
        assert 1 <= K < M, f"Need 1 <= K < M, got K={K}, M={M}"
        self.M = M
        self.K = K
        self.preamble_seconds = preamble_seconds
        self.f_low  = f_low
        self.f_high = f_high

        # Exact-bin orthogonal tone grid
        N, bins, freqs = _build_tone_grid(M, f_low=f_low, f_high=f_high)
        self.samples_per_sym = N
        self._bin_indices    = bins    # int32 array, shape (M,)
        self.freqs           = freqs   # float64 array, shape (M,)
        self.delta_f         = float(SAMPLE_RATE) / N
        self.T_sym           = N / float(SAMPLE_RATE)

        # Combinatorial lookup
        self._table, self._rev_table, self.n_symbols = _build_comb_tables(M, K)

        # bits per symbol: floor(log2(C(M,K)))
        self.bits_per_sym = max(1, int(math.floor(math.log2(self.n_symbols))))
        self._sym_cap     = 1 << self.bits_per_sym   # 2^bits_per_sym <= n_symbols

        self._preamble = hc.make_preamble(preamble_seconds).astype(np.float32)
        self.erasure_fn = None
        self.name = f"C2_combo_M{M}_K{K}"

    @property
    def gross_bps(self) -> float:
        return self._compute_gross_bps(4000)

    def _compute_gross_bps(self, n_data_bits: int) -> float:
        bps = self.bits_per_sym
        n_syms = math.ceil(n_data_bits / bps)
        total_samples = len(self._preamble) + n_syms * self.samples_per_sym
        dur = total_samples / SAMPLE_RATE
        return n_data_bits / dur if dur > 0 else 0.0

    # ------------------------------------------------------------------
    # Bit <-> symbol index helpers (handle bps up to 16 bits cleanly)
    # ------------------------------------------------------------------

    def _sym_to_bits(self, sym_idx: int) -> np.ndarray:
        """Convert symbol index to bit array of length bits_per_sym."""
        bps = self.bits_per_sym
        bits = []
        v = sym_idx
        for _ in range(bps):
            bits.append(v & 1)
            v >>= 1
        return np.array(bits[::-1], dtype=np.uint8)

    def _bits_to_sym(self, sym_bits: np.ndarray) -> int:
        """Convert bit array of length bits_per_sym to symbol index."""
        v = 0
        for b in sym_bits:
            v = (v << 1) | int(b)
        return min(v, self._sym_cap - 1)

    # ------------------------------------------------------------------

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        """bits (uint8) -> float32 audio @48kHz, including chirp preamble."""
        bits = np.asarray(bits, dtype=np.uint8)
        bps  = self.bits_per_sym
        pad  = (bps - len(bits) % bps) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
        n_syms = len(bits) // bps

        N = self.samples_per_sym
        t = np.arange(N, dtype=np.float64) / SAMPLE_RATE

        # Equal-amplitude tones; K simultaneous tones -> amp = 1/K (sum peaks at 1)
        amp = 1.0 / self.K
        tone_waves = (amp * np.sin(
            2.0 * math.pi * self.freqs[:, None] * t[None, :]
        )).astype(np.float64)   # (M, N)

        audio_body = np.zeros(n_syms * N, dtype=np.float64)
        for i in range(n_syms):
            sym_idx = self._bits_to_sym(bits[i * bps:(i + 1) * bps])
            for ti in self._table[sym_idx]:
                audio_body[i * N:(i + 1) * N] += tone_waves[ti]

        audio = np.concatenate([
            self._preamble.astype(np.float64),
            audio_body,
        ]).astype(np.float32)

        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = (audio / peak * 0.70).astype(np.float32)
        return audio

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """audio,sr -> recovered bits (uint8). Sync via preamble cross-correlation."""
        audio      = np.asarray(audio, dtype=np.float32)
        data_start = hc.find_preamble(audio, self.preamble_seconds)
        N          = self.samples_per_sym
        data       = audio[data_start:]
        n_complete = len(data) // N
        if n_complete == 0:
            return np.zeros(0, dtype=np.uint8)

        mat = data[:n_complete * N].reshape(n_complete, N).astype(np.float64)

        # FFT at exact bin positions
        fft_mat = np.fft.rfft(mat, n=N, axis=1)          # (n_syms, N//2+1)
        bins    = np.clip(self._bin_indices, 0, fft_mat.shape[1] - 1)
        energies = np.abs(fft_mat[:, bins])               # (n_syms, M)

        # Top-K tone indices per symbol
        top_k = np.argpartition(energies, -self.K, axis=1)[:, -self.K:]

        bps = self.bits_per_sym
        out_bits = np.empty(n_complete * bps, dtype=np.uint8)

        for i in range(n_complete):
            subset  = tuple(sorted(top_k[i].tolist()))
            sym_idx = self._rev_table.get(subset, 0)
            sym_idx = min(sym_idx, self._sym_cap - 1)
            out_bits[i * bps:(i + 1) * bps] = self._sym_to_bits(sym_idx)

        return out_bits


# ---------------------------------------------------------------------------
# Sanity gate: zero-channel loopback BER
# ---------------------------------------------------------------------------

def sanity_check(scheme: ComboMFSKScheme, n_bits: int = 4000) -> float:
    rng  = np.random.default_rng(42)
    bits = rng.integers(0, 2, size=n_bits, dtype=np.uint8)
    audio     = scheme.modulate(bits)
    recovered = scheme.demodulate(audio, hc.SAMPLE_RATE)
    n = len(bits)
    m = min(n, len(recovered))
    errs = int(np.count_nonzero(bits[:m] != recovered[:m])) + (n - m)
    return errs / n


# ---------------------------------------------------------------------------
# Grid sweep
# ---------------------------------------------------------------------------

def sweep_grid(
    M_list: list,
    K_list: list,
    n_seeds: int   = 8,
    payload_bits: int = 4000,
    tape_preset: str  = "normal",
) -> list:
    results = []
    for M in M_list:
        for K in K_list:
            if K >= M:
                continue
            n_sym = math.comb(M, K)
            bits_per_sym = max(1, int(math.floor(math.log2(n_sym))))
            if bits_per_sym < 2:
                # K=1 (standard MFSK) — not interesting for C2
                continue

            scheme = ComboMFSKScheme(M=M, K=K)

            sc_ber = sanity_check(scheme)
            if sc_ber > 1e-6:
                print(f"  [SKIP] M={M} K={K}: sanity BER={sc_ber:.2e} (demod bug)")
                continue

            print(
                f"  M={M:2d} K={K} bps/sym={bits_per_sym} "
                f"C={n_sym:5d} gross~{scheme.gross_bps:.0f}  ...",
                end="", flush=True,
            )
            t0 = time.time()
            eval_res = hc.evaluate_scheme(
                scheme,
                tape_preset=tape_preset,
                n_seeds=n_seeds,
                payload_bits=payload_bits,
                capture_key="usb_soundcard",
            )
            proj = hc.project_to_cassette(
                raw_ber=eval_res["raw_bit_error_rate"],
                erasure_rate=eval_res["erasure_rate"],
                gross_bps=eval_res["gross_bps"],
            )
            elapsed = time.time() - t0
            print(
                f"  BER={eval_res['raw_bit_error_rate']:.2e} "
                f"net={proj['net_bps']:.1f} P={proj['P_full']:.2f} "
                f"({elapsed:.1f}s)",
                flush=True,
            )
            row = {
                "M": M, "K": K,
                "bits_per_sym": bits_per_sym,
                "n_symbols": n_sym,
                "sanity_ber": sc_ber,
                **eval_res, **proj,
            }
            results.append(row)

    results.sort(key=lambda r: r["net_bps"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("C2: Combinatorial K-of-M Multitone FSK")
    print(f"MFSK-32 reference net_bps = {MFSK32_NET_BPS:.1f}")
    print(f"ACCEPT bar: net_bps >= {ACCEPT_THRESHOLD:.1f} (1.25x reference)")
    print("=" * 70)

    # --- Sanity check K=1 (should match MFSK) ---
    print("\n[sanity] Checking K=1, M=32 (should behave like MFSK-32)...")
    s_k1 = ComboMFSKScheme(M=32, K=1)
    ber_k1 = sanity_check(s_k1)
    print(f"  M=32 K=1 zero-channel BER = {ber_k1:.2e}")
    if ber_k1 > 1e-6:
        print("  WARNING: K=1 sanity FAILED — base implementation may have a bug")
    else:
        print("  [sanity] PASSED")

    # --- Phase 1: coarse grid sweep (n_seeds=8) ---
    M_list = [16, 24, 32, 48]
    K_list = [2, 3, 4, 5, 6]

    print(f"\nPhase 1: coarse grid sweep (n_seeds=8) ...")
    grid_results = sweep_grid(
        M_list=M_list, K_list=K_list,
        n_seeds=8, payload_bits=4000, tape_preset="normal",
    )

    if not grid_results:
        print("No valid configs found. Aborting.")
        return {}

    print(f"\nTop 5 after coarse sweep:")
    for r in grid_results[:5]:
        print(f"  M={r['M']:2d} K={r['K']} bps/sym={r['bits_per_sym']} "
              f"gross={r['gross_bps']:.0f} BER={r['raw_bit_error_rate']:.2e} "
              f"net={r['net_bps']:.1f} P={r['P_full']:.2f}")

    best_coarse = grid_results[0]

    # --- Phase 2: confirm top-5 candidates at canonical settings (n_seeds=16) ---
    # The coarse sweep (n_seeds=8) is noisy; confirm multiple candidates.
    top_candidates = [(r["M"], r["K"]) for r in grid_results[:5]]
    # Always include M=32 K=4 which was independently verified as strong
    for extra in [(32, 4), (32, 3), (48, 4)]:
        if extra not in top_candidates:
            top_candidates.append(extra)

    print(f"\nPhase 2: confirming {len(top_candidates)} candidates at n_seeds=16 ...")
    canon_results = []
    for M_b, K_b in top_candidates:
        sc = ComboMFSKScheme(M=M_b, K=K_b)
        sb = sanity_check(sc)
        if sb > 1e-6:
            print(f"  M={M_b} K={K_b}: sanity FAIL {sb:.2e}")
            continue
        ev = hc.evaluate_scheme(sc, tape_preset="normal", n_seeds=16,
                                payload_bits=4000, capture_key="usb_soundcard")
        pr = hc.project_to_cassette(raw_ber=ev["raw_bit_error_rate"],
                                    erasure_rate=ev["erasure_rate"],
                                    gross_bps=ev["gross_bps"])
        print(f"  M={M_b:2d} K={K_b}: BER={ev['raw_bit_error_rate']:.2e} "
              f"net={pr['net_bps']:.1f} P={pr['P_full']:.2f} "
              f"ratio={pr['net_bps']/MFSK32_NET_BPS:.3f}x")
        canon_results.append({"M": M_b, "K": K_b, "sanity_ber": sb, **ev, **pr})

    canon_results.sort(key=lambda r: r["net_bps"], reverse=True)
    best_canon = canon_results[0]
    M_b, K_b = best_canon["M"], best_canon["K"]
    print(f"\nBest canonical: M={M_b} K={K_b} net={best_canon['net_bps']:.1f}")

    print(f"\nPhase 2 detail: confirming M={M_b} K={K_b} at n_seeds=16 ...")
    # Use the already-computed canonical result for the best config
    sanity_ber     = float(best_canon["sanity_ber"])
    canonical_eval = {k: v for k, v in best_canon.items()
                      if k not in ("M", "K", "sanity_ber")}
    # Re-extract the projection fields
    canonical_proj = hc.project_to_cassette(
        raw_ber=best_canon["raw_bit_error_rate"],
        erasure_rate=best_canon["erasure_rate"],
        gross_bps=best_canon["gross_bps"],
    )
    net_bps_final = canonical_proj["net_bps"]
    p_full_final  = canonical_proj["P_full"]
    ratio         = net_bps_final / MFSK32_NET_BPS
    bug           = sanity_ber > 1e-6

    print(f"  [sanity] zero-channel BER = {sanity_ber:.2e}")
    if bug:
        print("  SANITY GATE FAILED — bug_suspected=True")
        verdict = "INCONCLUSIVE"
    else:
        print("  [sanity] PASSED")
        print(f"\n  Best canonical:")
        print(f"    M={M_b} K={K_b}")
        print(f"    gross_bps = {best_canon['gross_bps']:.1f}")
        print(f"    raw_BER   = {best_canon['raw_bit_error_rate']:.2e}")
        print(f"    net_bps   = {net_bps_final:.1f}")
        print(f"    P_full    = {p_full_final:.2f}")
        print(f"    ratio     = {ratio:.3f}x")

        if net_bps_final >= ACCEPT_THRESHOLD and p_full_final == 1.0 and not bug:
            verdict = "ACCEPT"
        else:
            verdict = "REJECT"

    print(f"\n  VERDICT: {verdict}")

    # --- Save results ---
    out = {
        "hypothesis": "C2_combo_mfsk",
        "mfsk32_reference_net_bps": MFSK32_NET_BPS,
        "accept_threshold": ACCEPT_THRESHOLD,
        "grid_sweep_n_seeds": 8,
        "grid_results": grid_results,
        "best_coarse": best_coarse,
        "canon_sweep": canon_results,
        "best_canon": best_canon,
        "canonical_eval": canonical_eval,
        "canonical_proj": canonical_proj,
        "sanity_ber_noChannel": float(sanity_ber),
        "verdict": verdict,
        "ratio_vs_mfsk32": float(ratio),
        "net_bps_final": float(net_bps_final),
        "p_full_final": float(p_full_final),
        "bug_suspected": bool(bug),
    }

    out_path = RESULTS_DIR / "c2_combo_mfsk.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2,
                  default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"\nResults saved to {out_path}")

    return out


if __name__ == "__main__":
    main()
