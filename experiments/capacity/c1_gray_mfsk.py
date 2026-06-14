"""c1_gray_mfsk.py — C1: Gray-coded MFSK with band and symbol-period re-tuning.

Hypothesis C1 (SAFE BET):
  Gray-coded MFSK. Standard MFSK maps symbol index -> bits with plain binary,
  so adjacent-tone slip (the dominant failure mode) flips ~log2(M)/2 bits.
  Gray coding makes every adjacent slip flip exactly 1 bit, cutting raw BER
  ~2-3x. Since the MFSK-32 reference BER (2.02e-3) sits just above the 1e-3
  knee in the code-rate table, dropping below 1e-3 lifts the code rate from
  0.80 -> 0.85, and below 1e-4 -> 0.92.

Additionally re-tunes:
  (a) Band shifted toward higher frequencies (500..10500 Hz) for more headroom.
  (b) M in {16, 32, 64} sweep.
  (c) T_sym multiplier slightly above orthogonal (1.0, 1.25, 1.5) for flutter margin.

ACCEPT bar: net_bps >= 1.10x MFSK-32 reference (1075.6 bps) = 1183.2 bps,
            P_full = 1.0, sanity_ber_noChannel ~0.

Canonical eval: n_seeds=16, payload_bits=4000, tape_preset="normal".
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

import hyp_common as hc  # noqa: E402

SAMPLE_RATE = 48_000

RESULTS_DIR = ROOT / "experiments" / "capacity" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Reference to beat
MFSK32_NET_BPS = 1075.6
ACCEPT_THRESHOLD = MFSK32_NET_BPS * 1.10  # 1183.2 bps


# ---------------------------------------------------------------------------
# Gray code helpers
# ---------------------------------------------------------------------------

def _binary_to_gray(n: int) -> int:
    """Convert binary integer to Gray code integer."""
    return n ^ (n >> 1)


def _gray_to_binary(g: int) -> int:
    """Convert Gray code integer to binary integer."""
    mask = g >> 1
    while mask:
        g ^= mask
        mask >>= 1
    return g


def _build_gray_table(M: int) -> tuple[np.ndarray, np.ndarray]:
    """Build forward (sym_idx -> gray_idx) and inverse (gray_idx -> sym_idx) tables.

    For M tones ordered 0..M-1, we map symbol index i to Gray code g(i).
    Modulate: symbol bits -> gray_sym_idx -> tone.
    Demodulate: tone -> gray_sym_idx -> symbol bits (via inverse table).
    """
    # forward: symbol number -> gray code
    fwd = np.array([_binary_to_gray(i) for i in range(M)], dtype=np.int32)
    # inverse: gray code -> symbol number
    inv = np.zeros(M, dtype=np.int32)
    for i in range(M):
        inv[fwd[i]] = i
    return fwd, inv


# ---------------------------------------------------------------------------
# Gray-coded MFSK Scheme
# ---------------------------------------------------------------------------

class GrayMFSKScheme:
    """MFSK with Gray-coded symbol<->tone mapping.

    The only difference from MFSKScheme is:
      modulate: bits -> binary_sym_idx -> gray_tone_idx -> waveform
      demodulate: peak_tone_idx (= gray_idx) -> binary_sym_idx -> bits

    This means an adjacent-tone detection error flips exactly 1 bit instead of
    the average log2(M)/2 bits that plain binary coding would flip.

    Parameters
    ----------
    M          : tones (must be power-of-2 >= 2)
    bw_low     : low frequency edge (Hz)
    bw_high    : high frequency edge (Hz)
    tsym_mult  : multiply the Olivia-orthogonal T_sym by this factor (>= 1.0).
                 Slightly longer symbol periods provide more flutter margin at
                 the cost of some gross_bps.
    preamble_seconds : preamble duration (s)
    """

    def __init__(
        self,
        M: int = 32,
        bw_low: float = 400.0,
        bw_high: float = 10_000.0,
        tsym_mult: float = 1.0,
        preamble_seconds: float = 0.25,
    ):
        assert M >= 2 and (M & (M - 1)) == 0, "M must be power-of-2 >= 2"
        self.M = M
        self.bits_per_sym = int(math.log2(M))
        self.bw_low = bw_low
        self.bw_high = bw_high
        self.tsym_mult = tsym_mult
        self.preamble_seconds = preamble_seconds

        # Olivia-style band-spanning orthogonal tone grid
        bw = bw_high - bw_low
        delta_f = bw / (M - 1)
        self.delta_f = delta_f
        # Orthogonal symbol period: T_sym = 1/delta_f, then scale by tsym_mult
        T_sym_ortho = 1.0 / delta_f
        self.T_sym = T_sym_ortho * tsym_mult
        self.samples_per_sym = int(round(self.T_sym * SAMPLE_RATE))

        # Tone frequencies
        self.freqs = np.array([bw_low + i * delta_f for i in range(M)], dtype=np.float64)

        # Gray code tables: fwd[sym] = gray_tone_idx, inv[gray_tone_idx] = sym
        self._gray_fwd, self._gray_inv = _build_gray_table(M)

        # Preamble
        self._preamble = hc.make_preamble(preamble_seconds).astype(np.float32)

        # Protocol fields
        self.erasure_fn = None
        self.name = (
            f"C1_gray_mfsk{M}_bw{int(bw_low)}-{int(bw_high)}"
            f"_tm{tsym_mult:.2f}"
        )

    @property
    def gross_bps(self) -> float:
        return self._compute_gross_bps(4000)

    def _compute_gross_bps(self, n_data_bits: int) -> float:
        n_syms = math.ceil(n_data_bits / self.bits_per_sym)
        total_samples = len(self._preamble) + n_syms * self.samples_per_sym
        total_dur = total_samples / SAMPLE_RATE
        return n_data_bits / total_dur if total_dur > 0 else 0.0

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        """bits (uint8) -> float32 audio @48kHz including chirp preamble."""
        bits = np.asarray(bits, dtype=np.uint8)
        bps = self.bits_per_sym

        # Pad to multiple of bps
        pad = (bps - len(bits) % bps) % bps
        if pad:
            bits_padded = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
        else:
            bits_padded = bits
        n_syms = len(bits_padded) // bps

        N = self.samples_per_sym
        t = np.arange(N, dtype=np.float64) / SAMPLE_RATE

        # Precompute all M tone waveforms
        tone_waves = np.array([
            np.sin(2.0 * math.pi * f * t) for f in self.freqs
        ], dtype=np.float64)  # (M, N)

        audio_body = np.empty(n_syms * N, dtype=np.float64)
        for i in range(n_syms):
            sym_bits = bits_padded[i * bps:(i + 1) * bps]
            # Convert bit group to symbol index (binary)
            sym_idx = int(np.packbits(sym_bits, bitorder="big")[0]) >> (8 - bps)
            sym_idx = min(sym_idx, self.M - 1)
            # Map to Gray-coded tone index
            tone_idx = int(self._gray_fwd[sym_idx])
            audio_body[i * N:(i + 1) * N] = tone_waves[tone_idx]

        audio = np.concatenate([
            self._preamble.astype(np.float64),
            audio_body,
        ]).astype(np.float32)

        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = (audio / peak * 0.70).astype(np.float32)
        return audio

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """audio, sr -> recovered uint8 bits. Sync from preamble, no oracle."""
        audio = np.asarray(audio, dtype=np.float32)

        # Coarse sync
        data_start = hc.find_preamble(audio, self.preamble_seconds)

        N = int(round(self.T_sym * sr))
        data = audio[data_start:].astype(np.float64)
        n_complete = len(data) // N
        if n_complete == 0:
            return np.zeros(0, dtype=np.uint8)

        # Vectorised FFT energy detection
        mat = data[:n_complete * N].reshape(n_complete, N)
        fft_mat = np.fft.rfft(mat, n=N, axis=1)  # (n_syms, N//2+1)

        # Tone bin indices
        bin_indices = np.round(self.freqs * N / sr).astype(int)
        bin_indices = np.clip(bin_indices, 0, fft_mat.shape[1] - 1)
        energies = np.abs(fft_mat[:, bin_indices]) ** 2  # (n_syms, M)

        # Peak tone index is the Gray-coded symbol index
        gray_tone_idx = np.argmax(energies, axis=1)  # (n_syms,)

        # Convert Gray tone index -> binary symbol index -> bits
        bps = self.bits_per_sym
        out_bits = np.empty(n_complete * bps, dtype=np.uint8)
        for i, g_idx in enumerate(gray_tone_idx):
            sym_idx = int(self._gray_inv[int(g_idx)])
            sym_bits = np.unpackbits(
                np.array([sym_idx], dtype=np.uint8), bitorder="big"
            )[-bps:]
            out_bits[i * bps:(i + 1) * bps] = sym_bits

        return out_bits


# ---------------------------------------------------------------------------
# Sanity check: zero-channel loopback BER must be ~0
# ---------------------------------------------------------------------------

def sanity_check(scheme: GrayMFSKScheme, payload_bits: int = 4000) -> float:
    """Modulate -> demodulate with NO channel. Returns BER (must be ~0)."""
    rng = np.random.default_rng(42)
    bits = rng.integers(0, 2, size=payload_bits, dtype=np.uint8)
    audio = scheme.modulate(bits)
    recovered = scheme.demodulate(audio, SAMPLE_RATE)
    n = len(bits)
    m = min(n, len(recovered))
    errs = int(np.count_nonzero(bits[:m] != recovered[:m])) + (n - m)
    return errs / n


# ---------------------------------------------------------------------------
# Grid sweep
# ---------------------------------------------------------------------------

def _build_grid():
    """Build (label, M, bw_low, bw_high, tsym_mult) grid to sweep.

    Focus on configurations likely to exceed the 1183.2 bps accept bar.
    Theoretical gross_bps ~= log2(M) * bw / (M-1) / tsym_mult.

    Key insight from experimentation:
      - M=16 with narrower band (400-7000 Hz) gives wider tone spacing (440 Hz
        vs 640 Hz for 400-10000 Hz band), which lowers BER significantly.
      - Strict orthogonal T_sym (tm=1.0) maximizes gross_bps.
      - Gray coding cuts raw BER on M=32 from 2.02e-3 -> 1.58e-3 (same code-rate
        bucket), but M=16 narrow-band achieves a higher gross_bps AND acceptable BER.
    """
    configs = []

    # Primary: M=16 with narrowed upper band (wider tone spacing = lower BER)
    for bw_high in [6000.0, 7000.0, 8000.0]:
        for tm in [1.0, 1.10, 1.20, 1.25]:
            label = f"gray_m16_bw400-{int(bw_high//1000)}k_tm{tm:.2f}"
            configs.append((label, 16, 400.0, bw_high, tm))

    # Original full-band M=16, M=32, M=64 for comparison
    for M in [16, 32, 64]:
        for tm in [1.0, 1.25, 1.5]:
            label = f"gray_m{M}_bw400_10k_tm{tm:.2f}"
            configs.append((label, M, 400.0, 10_000.0, tm))

    # Shifted-up band options
    for M in [16, 32]:
        for tm in [1.0, 1.25]:
            label = f"gray_m{M}_bw500_10k5_tm{tm:.2f}"
            configs.append((label, M, 500.0, 10_500.0, tm))

    return configs


def run_sweep(
    n_seeds: int = 8,
    payload_bits: int = 4000,
    tape_preset: str = "normal",
    configs=None,
) -> list[dict]:
    """Sweep Gray MFSK configs. Returns results sorted by net_bps descending."""
    if configs is None:
        configs = _build_grid()

    results = []
    for label, M, bw_low, bw_high, tm in configs:
        scheme = GrayMFSKScheme(M=M, bw_low=bw_low, bw_high=bw_high, tsym_mult=tm)

        # Quick sanity gate on first run of each M
        s_ber = sanity_check(scheme)
        if s_ber > 1e-6:
            print(f"  [SANITY FAIL] {label}: loopback BER={s_ber:.2e}  SKIP")
            continue

        print(
            f"  {label:45s}  gross={scheme.gross_bps:.0f}  ...",
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
            f"  BER={eval_res['raw_bit_error_rate']:.2e}  "
            f"net={proj['net_bps']:.1f}  P={proj['P_full']:.2f}  "
            f"({elapsed:.1f}s)"
        )
        row = {
            "label": label,
            "M": M,
            "bw_low": bw_low,
            "bw_high": bw_high,
            "tsym_mult": tm,
            "sanity_ber": s_ber,
            **eval_res,
            **proj,
        }
        results.append(row)

    results.sort(key=lambda r: r["net_bps"], reverse=True)
    return results


def confirm_best(
    best_row: dict,
    n_seeds: int = 16,
    payload_bits: int = 4000,
    tape_preset: str = "normal",
) -> dict:
    """Re-run the best config at canonical n_seeds=16 settings."""
    scheme = GrayMFSKScheme(
        M=best_row["M"],
        bw_low=best_row["bw_low"],
        bw_high=best_row["bw_high"],
        tsym_mult=best_row["tsym_mult"],
    )
    s_ber = sanity_check(scheme, payload_bits)
    print(f"  [confirm sanity] loopback BER = {s_ber:.2e}")

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
    return {
        "sanity_ber": s_ber,
        **eval_res,
        **proj,
        "M": best_row["M"],
        "bw_low": best_row["bw_low"],
        "bw_high": best_row["bw_high"],
        "tsym_mult": best_row["tsym_mult"],
        "label": best_row["label"],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 72)
    print("C1 — Gray-coded MFSK with band/symbol-period re-tuning")
    print(f"MFSK-32 reference net_bps = {MFSK32_NET_BPS}")
    print(f"ACCEPT threshold (1.10x)  = {ACCEPT_THRESHOLD:.1f} bps")
    print("=" * 72)

    # -------------------------------------------------------------------
    # 1. Sanity gate on a representative scheme
    # -------------------------------------------------------------------
    print("\n[1] Sanity gate (modulate->demodulate, zero channel) ...")
    for M in [16, 32, 64]:
        s = GrayMFSKScheme(M=M)
        b = sanity_check(s)
        flag = "OK" if b < 1e-6 else "FAIL"
        print(f"     M={M:3d}  loopback BER = {b:.2e}  [{flag}]")
        if b > 1e-6:
            raise RuntimeError(
                f"Sanity FAILED for M={M}: BER={b:.2e}. Fix demod before evaluating."
            )
    print("  [sanity] ALL PASSED")

    # -------------------------------------------------------------------
    # 2. Fast grid sweep (n_seeds=8) for exploration
    # -------------------------------------------------------------------
    print(f"\n[2] Fast grid sweep (n_seeds=8, payload_bits=4000) ...")
    configs = _build_grid()
    print(f"  Sweeping {len(configs)} configs ...")
    sweep_results = run_sweep(n_seeds=8, payload_bits=4000, configs=configs)

    print(f"\n  Top-5 by net_bps (n_seeds=8, exploratory):")
    print(f"  {'Config':<48}  {'gross':>7}  {'raw_BER':>9}  {'net_bps':>8}  {'P_full':>6}")
    print("  " + "-" * 83)
    for r in sweep_results[:5]:
        flag = " <-- sweep best" if r is sweep_results[0] else ""
        print(
            f"  {r['label']:<48}  {r['gross_bps']:>7.0f}  "
            f"{r['raw_bit_error_rate']:>9.2e}  "
            f"{r['net_bps']:>8.1f}  "
            f"{r['P_full']:>6.2f}{flag}"
        )

    # -------------------------------------------------------------------
    # 3. Canonical confirmation of the known-best config (n_seeds=16)
    #    Discovered via detailed sweep: M=16, bw=400-7000 Hz, tm=1.00
    #    This narrower band gives wider tone spacing (440 Hz vs 640 Hz),
    #    lower BER, and higher gross_bps than the full-band M=16 configs.
    # -------------------------------------------------------------------
    print(f"\n[3] Canonical confirmation at n_seeds=16 ...")
    BEST_CONFIG = {
        "label": "gray_m16_bw400-7k_tm1.00",
        "M": 16,
        "bw_low": 400.0,
        "bw_high": 7000.0,
        "tsym_mult": 1.0,
    }
    print(f"  Config: {BEST_CONFIG['label']}  (M=16, bw=400-7000Hz, strict-orthogonal)")
    confirmed = confirm_best(BEST_CONFIG, n_seeds=16, payload_bits=4000)
    print(
        f"  CONFIRMED: gross={confirmed['gross_bps']:.1f}  "
        f"BER={confirmed['raw_bit_error_rate']:.2e}  "
        f"net_bps={confirmed['net_bps']:.1f}  "
        f"P_full={confirmed['P_full']:.2f}"
    )

    # -------------------------------------------------------------------
    # 4. Verdict
    # -------------------------------------------------------------------
    net = confirmed["net_bps"]
    p = confirmed["P_full"]
    sber = confirmed["sanity_ber"]
    verdict = (
        "ACCEPT" if net >= ACCEPT_THRESHOLD and p == 1.0 and sber < 1e-6
        else "REJECT" if sber < 1e-6
        else "INCONCLUSIVE"
    )
    ratio = net / MFSK32_NET_BPS

    print("\n" + "=" * 72)
    print(f"VERDICT: {verdict}")
    print(f"  best_config   = {confirmed['label']}")
    print(f"  gross_bps     = {confirmed['gross_bps']:.1f}")
    print(f"  raw_BER       = {confirmed['raw_bit_error_rate']:.2e}")
    print(f"  erasure_rate  = {confirmed['erasure_rate']:.4f}")
    print(f"  net_bps       = {net:.1f}  (threshold {ACCEPT_THRESHOLD:.1f})")
    print(f"  MB_C90_stereo = {confirmed['MB_C90_stereo']:.3f}")
    print(f"  P_full        = {p:.2f}")
    print(f"  ratio vs MFSK-32 = {ratio:.3f}x")
    print(f"  sanity_ber_noChannel = {sber:.2e}")
    print("=" * 72)

    # -------------------------------------------------------------------
    # 5. Save results
    # -------------------------------------------------------------------
    out = {
        "hypothesis_id": "C1",
        "name": "Gray-coded MFSK",
        "experiment": "c1_gray_mfsk",
        "verdict": verdict,
        "accept_threshold_net_bps": ACCEPT_THRESHOLD,
        "mfsk32_reference_net_bps": MFSK32_NET_BPS,
        "ratio_vs_mfsk32": ratio,
        "best_config": confirmed,
        "sweep_results": sweep_results,
        "metadata": {
            "n_seeds_sweep": 8,
            "n_seeds_confirm": 16,
            "payload_bits": 4000,
            "tape_preset": "normal",
            "capture_key": "usb_soundcard",
        },
    }

    out_path = RESULTS_DIR / "c1_gray_mfsk.json"
    with open(out_path, "w") as f:
        json.dump(
            out, f, indent=2,
            default=lambda o: list(o) if hasattr(o, "__iter__") else str(o),
        )
    print(f"\nResults saved to {out_path}")
    return out


if __name__ == "__main__":
    main()
