"""hyp_h2_mfsk.py — H2: MFSK (Olivia-style) multi-tone modulation hypothesis.

Claim: M-ary orthogonal FSK (M in {4,8,16,32,64}), non-coherent FFT energy
detection, plus an optional Walsh/Hadamard block FEC layer, packed into the
~10.5 kHz usable tape band using band-spanning orthogonal tone grids, delivers
>= 1.5x B0's reliable net throughput (>= 717.1 bps).

Design principle (Olivia MFSK):
  - Space M tones across the usable band so delta_f ~ band / (M-1).
  - Orthogonality condition: T_sym = 1/delta_f, so each tone is an integer
    number of cycles in the symbol window -> coherent FFT integration.
  - At each symbol, emit one tone; detect by peak FFT bin (non-coherent).
  - Each symbol carries log2(M) bits.
  - Gross_bps = log2(M) / T_sym ~ log2(M) * band / (M-1).
  - Sweep M: small M = wide spacing, robust, lower rate;
             large M = narrow spacing, more bits/sym, sensitive to SNR.

Prior art: Olivia MFSK (Pawel Jalocha, 2005); Soviet/ham HF multi-tone telegraphy.

ACCEPT threshold: net_bps >= 717.1 bps  (= 1.5 * 478.05, pre-registered in
  docs/encoding_hypotheses.md)
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import numpy as np

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import cassette_format as cf          # noqa: E402
import channel as ch                  # noqa: E402
import capture_scenarios as cs        # noqa: E402
import cassette_e2e as e2e            # noqa: E402
import hyp_common as hc               # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 48_000
USABLE_F_LOW  = 400.0     # Hz — well above tape rumble / preamble low edge
USABLE_F_HIGH = 10_000.0  # Hz — safe margin below 10.5 kHz HF rolloff
USABLE_BW     = USABLE_F_HIGH - USABLE_F_LOW  # ~ 9600 Hz

# Pre-registered accept threshold
B0_NET_BPS    = 478.05     # from hyp_baseline_B0.json
H2_THRESHOLD  = 717.1      # 1.5 * B0_NET_BPS (pre-registered in encoding_hypotheses.md)

DATA_DIR  = ROOT / "RESULTS" / "data"
PLOTS_DIR = ROOT / "RESULTS" / "plots"


# ---------------------------------------------------------------------------
# Walsh-Hadamard FEC helpers (optional Olivia-style inner code)
# ---------------------------------------------------------------------------

def _hadamard_matrix(n: int) -> np.ndarray:
    """n×n Hadamard matrix (n power of 2), ±1 entries."""
    assert n >= 1 and (n & (n - 1)) == 0
    H = np.array([[1.0]], dtype=np.float32)
    while H.shape[0] < n:
        H = np.block([[H, H], [H, -H]])
    return H


def _walsh_encode(data_bits: np.ndarray, k: int) -> np.ndarray:
    """Encode k-bit symbols to Walsh codewords of length 2^k.

    Each k-bit symbol s -> H[s] row of the 2^k Hadamard matrix (+1/-1 chips).
    Pads data_bits to a multiple of k internally.
    Returns 1-D array of ±1 chips.
    """
    n = 1 << k
    H = _hadamard_matrix(n)
    bits = np.asarray(data_bits, dtype=np.uint8)
    pad = (k - len(bits) % k) % k
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    n_syms = len(bits) // k
    chips = np.empty(n_syms * n, dtype=np.float32)
    for i in range(n_syms):
        sym = int(np.packbits(bits[i * k:(i + 1) * k], bitorder="big")[0]) >> (8 - k)
        chips[i * n:(i + 1) * n] = H[sym]
    return chips  # ±1


def _walsh_decode(chips: np.ndarray, k: int) -> np.ndarray:
    """Decode Walsh chips (soft ±1 values) to bits."""
    n = 1 << k
    H = _hadamard_matrix(n)
    trim = len(chips) - (len(chips) % n)
    chips = chips[:trim]
    n_syms = len(chips) // n
    out = np.empty(n_syms * k, dtype=np.uint8)
    for i in range(n_syms):
        c = chips[i * n:(i + 1) * n]
        corr = H @ c
        best = int(np.argmax(corr))
        bits_sym = np.unpackbits(np.array([best], dtype=np.uint8), bitorder="big")[-k:]
        out[i * k:(i + 1) * k] = bits_sym
    return out


# ---------------------------------------------------------------------------
# MFSK Scheme (band-spanning, Olivia-style orthogonal tone grid)
# ---------------------------------------------------------------------------

class MFSKScheme:
    """MFSK modulator/demodulator using band-spanning orthogonal tone grid.

    Tone grid: M tones at f_low + i * delta_f, i=0..M-1, where
      delta_f = USABLE_BW / (M - 1)   (span the full usable band)
      T_sym   = 1 / delta_f            (orthogonality: N_sym samples = integer)

    This maximises SNR per symbol by using narrow-band integration over exactly
    one tone cycle, while spanning the maximum usable bandwidth.

    Parameters
    ----------
    M          : number of orthogonal tones (4, 8, 16, 32, 64, 128)
    walsh_k    : Walsh FEC parameter k; k=0 = no FEC.
                 Each k data bits encode as a 2^k-chip Walsh codeword before
                 MFSK mapping. Divides gross_bps by 2^k/k (coding overhead).
    bw_low, bw_high : usable band edges (Hz)
    """

    def __init__(
        self,
        M: int = 32,
        walsh_k: int = 0,
        bw_low: float = USABLE_F_LOW,
        bw_high: float = USABLE_F_HIGH,
        preamble_seconds: float = 0.25,
    ):
        assert M >= 2 and (M & (M - 1)) == 0, "M must be a power of 2 >= 2"
        self.M = M
        self.bits_per_sym = int(math.log2(M))
        self.walsh_k = walsh_k
        self.bw_low = bw_low
        self.bw_high = bw_high
        self.preamble_seconds = preamble_seconds

        # Olivia-style band-spanning tone grid
        bw = bw_high - bw_low
        self.delta_f = bw / (M - 1)          # Hz between adjacent tones
        self.T_sym   = 1.0 / self.delta_f    # symbol period (orthogonality)
        self.samples_per_sym = int(round(self.T_sym * SAMPLE_RATE))

        # Exact tone frequencies: multiples of delta_f from bw_low
        self.freqs = np.array([bw_low + i * self.delta_f for i in range(M)])

        # Preamble for coarse sync
        self._preamble = hc.make_preamble(preamble_seconds).astype(np.float32)

        # Required by the hc.evaluate_scheme Scheme protocol
        self.erasure_fn = None

        # Name
        fec_tag = f"_walsh{walsh_k}" if walsh_k > 0 else "_noFEC"
        self.name = f"H2_mfsk{M}{fec_tag}"

    @property
    def gross_bps(self) -> float:
        """Gross information bits per second (data-only, preamble counted as overhead)."""
        # For evaluate_scheme compatibility: gross_bps is declared once and
        # accounts for preamble overhead relative to a representative payload.
        # Here we use 4000 bits as the representative payload (matches n_seeds default).
        return self._compute_gross_bps(4000)

    def _compute_gross_bps(self, n_data_bits: int) -> float:
        """Compute gross_bps for given payload size (preamble overhead included)."""
        if self.walsh_k > 0:
            k = self.walsh_k
            n_chips_per_sym = 1 << k   # 2^k chips per k-bit input symbol
            # chip_bits_total = n_data_bits/k * 2^k = n_data_bits * (2^k/k)
            n_chip_bits = (math.ceil(n_data_bits / k)) * (1 << k)
            n_syms = math.ceil(n_chip_bits / self.bits_per_sym)
        else:
            n_syms = math.ceil(n_data_bits / self.bits_per_sym)

        total_samples = len(self._preamble) + n_syms * self.samples_per_sym
        total_dur = total_samples / SAMPLE_RATE
        return n_data_bits / total_dur if total_dur > 0 else 0.0

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        """bits (uint8) -> float32 audio @48kHz, including chirp preamble."""
        bits = np.asarray(bits, dtype=np.uint8)
        n_data_bits = len(bits)

        # --- Optional Walsh FEC encoding ---
        if self.walsh_k > 0:
            chips = _walsh_encode(bits, self.walsh_k)
            # chips are ±1 floats; convert to 0/1 bit stream for MFSK mapping
            chip_bits = np.clip((chips + 1.0) / 2.0, 0, 1).astype(np.uint8)
        else:
            chip_bits = bits

        # Pad chip_bits to multiple of bits_per_sym
        bps = self.bits_per_sym
        pad = (bps - len(chip_bits) % bps) % bps
        if pad:
            chip_bits = np.concatenate([chip_bits, np.zeros(pad, dtype=np.uint8)])
        n_syms = len(chip_bits) // bps

        # --- MFSK modulation ---
        N = self.samples_per_sym
        t = np.arange(N, dtype=np.float64) / SAMPLE_RATE

        # Precompute all tone waveforms to speed up inner loop
        tone_waves = np.array([
            np.sin(2.0 * math.pi * f * t) for f in self.freqs
        ], dtype=np.float64)  # shape: (M, N)

        audio_body = np.empty(n_syms * N, dtype=np.float64)
        for i in range(n_syms):
            sym_bits = chip_bits[i * bps:(i + 1) * bps]
            sym_idx = int(np.packbits(sym_bits, bitorder="big")[0]) >> (8 - bps)
            sym_idx = min(sym_idx, self.M - 1)
            audio_body[i * N:(i + 1) * N] = tone_waves[sym_idx]

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
        audio = np.asarray(audio, dtype=np.float32)

        # Coarse sync from chirp preamble
        data_start = hc.find_preamble(audio, self.preamble_seconds)

        N = int(round(self.T_sym * sr))
        freqs = self.freqs

        # Vectorised FFT detection over all symbol windows
        data = audio[data_start:]
        n_complete = len(data) // N
        if n_complete == 0:
            return np.zeros(0, dtype=np.uint8)

        # Stack all symbol windows
        mat = data[:n_complete * N].reshape(n_complete, N).astype(np.float64)

        # FFT-based non-coherent energy detection
        # Compute FFT once per window, then read energy at tone bin indices
        fft_mat = np.fft.rfft(mat, n=N, axis=1)  # (n_syms, N//2+1)
        # Compute bin indices for each tone
        bin_indices = np.round(freqs * N / sr).astype(int)
        bin_indices = np.clip(bin_indices, 0, fft_mat.shape[1] - 1)
        energies = np.abs(fft_mat[:, bin_indices]) ** 2  # (n_syms, M)

        best_syms = np.argmax(energies, axis=1)  # (n_syms,)

        # Convert symbol indices to bits
        bps = self.bits_per_sym
        chip_bits = np.empty(n_complete * bps, dtype=np.uint8)
        for i, sym in enumerate(best_syms):
            bits_sym = np.unpackbits(np.array([int(sym)], dtype=np.uint8), bitorder="big")[-bps:]
            chip_bits[i * bps:(i + 1) * bps] = bits_sym

        # --- Walsh FEC decoding ---
        if self.walsh_k > 0:
            chips_soft = chip_bits.astype(np.float32) * 2.0 - 1.0
            data_bits = _walsh_decode(chips_soft, self.walsh_k)
        else:
            data_bits = chip_bits

        return np.asarray(data_bits, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Configurations to sweep
# ---------------------------------------------------------------------------

def _build_configs():
    """Return list of (label, M, walsh_k) to sweep.

    Focus on configs likely to exceed the 717.1 bps threshold.
    Theoretical gross_bps = log2(M) * USABLE_BW / (M-1), so:
      M=32:  5 * 9600/31 ~ 1548 bps -> excellent margin even with outer FEC
      M=64:  6 * 9600/63 ~ 914 bps  -> good margin
      M=128: 7 * 9600/127 ~ 529 bps -> below threshold without FEC
      M=16:  4 * 9600/15  ~ 2560 bps -> very high but tight tone spacing
    """
    configs = []

    # No Walsh FEC — pure MFSK at various M
    for M in [8, 16, 32, 64, 128]:
        configs.append((f"mfsk{M}_noFEC", M, 0))

    # Walsh k=2 (4-chip codeword): coding overhead factor 2^k/k = 4/2=2x -> halves bps
    for M in [16, 32, 64]:
        configs.append((f"mfsk{M}_walsh2", M, 2))

    # Walsh k=3 (8-chip codeword): overhead factor 8/3 ~ 2.7x
    for M in [32, 64]:
        configs.append((f"mfsk{M}_walsh3", M, 3))

    return configs


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate_all(
    tape_preset: str = "normal",
    n_seeds: int = 20,
    payload_bits: int = 4000,
    configs=None,
):
    """Sweep configs, return sorted list of result dicts (best net_bps first)."""
    if configs is None:
        configs = _build_configs()

    results = []
    for label, M, walsh_k in configs:
        scheme = MFSKScheme(M=M, walsh_k=walsh_k)
        print(
            f"  {label:30s}  delta_f={scheme.delta_f:.0f}Hz  "
            f"T_sym={scheme.T_sym*1000:.2f}ms  gross_bps={scheme.gross_bps:.0f}  ...",
            flush=True,
        )
        t0 = time.time()

        eval_res = hc.evaluate_scheme(
            scheme,
            tape_preset=tape_preset,
            n_seeds=n_seeds,
            payload_bits=payload_bits,
        )
        proj = hc.project_to_cassette(
            raw_ber=eval_res["raw_bit_error_rate"],
            erasure_rate=eval_res["erasure_rate"],
            gross_bps=eval_res["gross_bps"],
        )

        row = {
            "label": label,
            "M": M,
            "walsh_k": walsh_k,
            "delta_f_hz": float(scheme.delta_f),
            "T_sym_ms": float(scheme.T_sym * 1000),
            "tape_preset": tape_preset,
            **eval_res,
            **proj,
        }
        results.append(row)
        elapsed = time.time() - t0
        print(
            f"    BER={eval_res['raw_bit_error_rate']:.2e}  "
            f"net_bps={proj['net_bps']:.1f}  P_full={proj['P_full']:.2f}  "
            f"({elapsed:.1f}s)",
            flush=True,
        )

    results.sort(key=lambda r: r["net_bps"], reverse=True)
    return results


def make_plot(results: list[dict]):
    """Save a bar chart of net_bps for each configuration."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels = [r["label"] for r in results]
        net_vals = [r["net_bps"] for r in results]
        gross_vals = [r["gross_bps"] for r in results]

        fig, ax = plt.subplots(figsize=(14, 5))
        x = np.arange(len(labels))
        w = 0.4
        colors_net = ["#2ecc71" if v >= H2_THRESHOLD else "#e74c3c" for v in net_vals]
        ax.bar(x - w / 2, gross_vals, width=w, label="gross_bps", color="#95a5a6", edgecolor="black", linewidth=0.5)
        ax.bar(x + w / 2, net_vals,   width=w, label="net_bps",   color=colors_net, edgecolor="black", linewidth=0.5)
        ax.axhline(H2_THRESHOLD, color="navy",  linestyle="--", linewidth=1.5, label=f"H2 threshold {H2_THRESHOLD:.0f} bps")
        ax.axhline(B0_NET_BPS,   color="gray",  linestyle=":",  linewidth=1.2, label=f"B0 baseline {B0_NET_BPS:.0f} bps")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("bps (projected)")
        ax.set_title("H2 MFSK Olivia sweep — gross vs net bps per configuration")
        ax.legend(fontsize=9)
        fig.tight_layout()

        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        plot_path = PLOTS_DIR / "hyp_mfsk_olivia.png"
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)
        print(f"Plot saved: {plot_path}")
    except Exception as exc:
        print(f"Warning: plot failed ({exc})")


def main():
    print("=" * 72)
    print("H2 — MFSK Olivia-style band-spanning sweep")
    print(f"Accept threshold: net_bps >= {H2_THRESHOLD:.1f} bps (1.5x B0)")
    print(f"Band: {USABLE_F_LOW:.0f}–{USABLE_F_HIGH:.0f} Hz ({USABLE_BW:.0f} Hz usable)")
    print("=" * 72)

    configs = _build_configs()
    print(f"\nSweeping {len(configs)} configurations on tape='normal' (n_seeds=20) ...")

    results = evaluate_all(
        tape_preset="normal",
        n_seeds=20,
        payload_bits=4000,
        configs=configs,
    )

    best = results[0]
    print(f"\nBest config (normal): {best['label']} -> net_bps={best['net_bps']:.1f}")

    # --- Worn stress test on the best config ---
    print(f"\nRunning 'worn' stress test on best config ({best['label']}) ...")
    worn_scheme = MFSKScheme(M=best["M"], walsh_k=best["walsh_k"])
    worn_eval = hc.evaluate_scheme(
        worn_scheme,
        tape_preset="worn",
        n_seeds=16,
        payload_bits=4000,
    )
    worn_proj = hc.project_to_cassette(
        raw_ber=worn_eval["raw_bit_error_rate"],
        erasure_rate=worn_eval["erasure_rate"],
        gross_bps=worn_eval["gross_bps"],
    )
    worn_res = {**worn_eval, **worn_proj, "label": best["label"] + "_worn"}
    print(
        f"  Worn: BER={worn_eval['raw_bit_error_rate']:.2e}  "
        f"net_bps={worn_proj['net_bps']:.1f}  P_full={worn_proj['P_full']:.2f}"
    )

    # --- Verdict ---
    verdict = "ACCEPT" if best["net_bps"] >= H2_THRESHOLD else "REJECT"

    # --- Compile output metrics ---
    output = {
        "hypothesis": "H2_mfsk_olivia",
        "verdict": verdict,
        "threshold_net_bps": H2_THRESHOLD,
        "B0_net_bps": B0_NET_BPS,
        "ratio_vs_B0": round(best["net_bps"] / B0_NET_BPS, 3),
        "best_config_normal": best,
        "all_configs_normal": results,
        "worn_stress": worn_res,
        "metadata": {
            "usable_band_hz": [USABLE_F_LOW, USABLE_F_HIGH],
            "n_seeds": 20,
            "payload_bits": 4000,
            "tape_preset": "normal",
        },
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = DATA_DIR / "hyp_mfsk_olivia.json"
    with open(metrics_path, "w") as f:
        json.dump(output, f, indent=2, default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"\nMetrics saved: {metrics_path}")

    make_plot(results)

    # --- Summary table ---
    print("\n" + "=" * 72)
    print(f"{'Config':<30}  {'gross':>7}  {'raw_BER':>9}  {'net_bps':>8}  {'P_full':>6}")
    print("-" * 72)
    for r in results[:10]:
        flag = " *BEST*" if r is best else ""
        print(
            f"{r['label']:<30}  {r['gross_bps']:>7.0f}  "
            f"{r['raw_bit_error_rate']:>9.2e}  "
            f"{r['net_bps']:>8.1f}  "
            f"{r['P_full']:>6.2f}{flag}"
        )
    print("=" * 72)
    print(f"\nVERDICT: {verdict}")
    print(f"  Best config : {best['label']}")
    print(f"  gross_bps   = {best['gross_bps']:.1f}")
    print(f"  raw_BER     = {best['raw_bit_error_rate']:.2e}")
    print(f"  net_bps     = {best['net_bps']:.1f}  (threshold {H2_THRESHOLD:.1f})")
    print(f"  P_full      = {best['P_full']:.2f}")
    print(f"  MB_C90_stereo = {best['MB_C90_stereo']:.3f}")
    print(f"  ratio vs B0 = {best['net_bps'] / B0_NET_BPS:.3f}x")
    print("=" * 72)

    return output


if __name__ == "__main__":
    main()
