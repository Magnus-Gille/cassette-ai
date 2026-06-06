"""rw_t4_bluetooth.py — T4: Bluetooth / narrowband voice path experiment.

Tests whether wideband reference modems (BFSK-B0, MFSK-32) survive the
Bluetooth HFP narrowband path (P5: lowpass 3400 Hz + libopus voip 12k + AGC).
Then tests a purpose-built narrowband BFSK modem (tones within 800-2600 Hz,
600-1200 bit/s) through the same path.

PATHS tested: P5 bluetooth_hfp_narrow
MODEMS tested:
  1. bfsk_b0   — 1200 bps BFSK (tones 1200/2400 Hz) — may survive since its
                 tones are inside 3400 Hz, but codec distortion may kill it.
  2. mfsk32    — 32-FSK band-spanning (400-10000 Hz) — will almost certainly
                 fail; tones above 3400 Hz are destroyed.
  3. nb_bfsk   — narrowband BFSK: tones 1000/2000 Hz @600 bps, well inside HFP.
  4. nb_bfsk_fast — narrowband BFSK: tones 800/1600 Hz @1200 bps (tighter but
                    uses a 2:1 frequency ratio, compatible with costas/PLL FSK
                    detectors).

Results saved to RESULTS/data/rw_bluetooth_narrow.json.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import numpy as np
from scipy import signal as scipy_signal

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
import capture_scenarios as cscn      # noqa: E402
import cassette_e2e as e2e            # noqa: E402
import hyp_common as hc               # noqa: E402
import realworld_channels as rw       # noqa: E402

FS = 48_000
DATA_DIR = ROOT / "RESULTS" / "data"
PLOTS_DIR = ROOT / "RESULTS" / "plots"

# ---------------------------------------------------------------------------
# Narrowband BFSK modem implementation
# ---------------------------------------------------------------------------
# Design rationale:
#   HFP / BT narrowband band: ~300–3400 Hz (standard telephony).
#   Place FSK tones well inside this band with clear spectral separation.
#   Use non-coherent energy-detector: count zero-crossings in a symbol window
#   to disambiguate the two tones (simple, robust to amplitude distortion).
#   Preamble: reuse hc.make_preamble() but shift it down — a 300->1800 Hz
#   chirp that stays inside the HFP band.
#
#   Variants:
#     nb_bfsk_slow: mark=1000 Hz, space=2000 Hz, baud=600 Bd -> 600 bps.
#       Wide frequency separation (1 octave) maximises discrimination under
#       codec distortion. Survives some bass rolloff and narrowband ISI.
#     nb_bfsk_fast: mark=800 Hz, space=1600 Hz, baud=1200 Bd -> 1200 bps.
#       Faster but tighter; 2:1 frequency ratio preserved.

class NarrowbandBFSK:
    """Simple narrowband 2-FSK modem using zero-crossing rate detection.

    Parameters
    ----------
    f_mark, f_space : float
        Tone frequencies (Hz). Must be inside the target channel band.
    baud_rate : int
        Symbols per second (= bits per second for 2-FSK).
    fs : int
        Sample rate (48000).
    """

    def __init__(self, f_mark: float = 1000.0, f_space: float = 2000.0,
                 baud_rate: int = 600, fs: int = FS, name: str = "nb_bfsk"):
        self.f_mark = float(f_mark)
        self.f_space = float(f_space)
        self.baud_rate = int(baud_rate)
        self.fs = int(fs)
        self.name = name
        self._samps_per_sym = int(round(fs / baud_rate))
        # Compute gross_bps from a representative encode.
        sample_bits = np.zeros(200, dtype=np.uint8)
        audio = self.modulate(sample_bits)
        dur = len(audio) / fs
        self.gross_bps = float(len(sample_bits)) / dur if dur > 0 else float(baud_rate)

    # ---- preamble ----------------------------------------------------------
    def _make_narrowband_preamble(self) -> np.ndarray:
        """Linear up-chirp from 300 Hz to 1800 Hz — stays inside HFP band."""
        dur = 0.25
        n = int(dur * self.fs)
        t = np.arange(n, dtype=np.float64) / self.fs
        from scipy.signal import chirp
        sig = chirp(t, f0=300.0, f1=1800.0, t1=dur, method="linear")
        return (0.65 * sig).astype(np.float32)

    def _find_narrowband_preamble(self, audio: np.ndarray) -> int:
        """Cross-correlate the narrowband preamble, return first data sample."""
        audio = np.asarray(audio, dtype=np.float64)
        pre = self._make_narrowband_preamble().astype(np.float64)
        n_pre = len(pre)
        if len(audio) < n_pre:
            return 0
        corr = np.correlate(audio[:min(len(audio), n_pre * 8)],
                            pre, mode="valid")
        if len(corr) == 0:
            return 0
        # Full correlate for better robustness on short audio
        from scipy.signal import correlate as full_corr
        corr = full_corr(audio, pre, mode="valid")
        pre_start = int(np.argmax(np.abs(corr)))
        return pre_start + n_pre

    # ---- modulate ----------------------------------------------------------
    def modulate(self, bits: np.ndarray) -> np.ndarray:
        """Encode bits as 2-FSK tones, prepend narrowband preamble."""
        bits = np.asarray(bits, dtype=np.uint8)
        preamble = self._make_narrowband_preamble()
        sps = self._samps_per_sym

        # Generate FSK symbols
        chunks = []
        phase = 0.0
        dt = 1.0 / self.fs
        for b in bits:
            freq = self.f_mark if b == 1 else self.f_space
            t = np.arange(sps, dtype=np.float64) * dt
            tone = np.sin(2 * np.pi * freq * t + phase)
            # Maintain phase continuity across symbols
            phase = (phase + 2 * np.pi * freq * sps * dt) % (2 * np.pi)
            chunks.append(tone)

        if chunks:
            data_audio = np.concatenate(chunks).astype(np.float32)
        else:
            data_audio = np.array([], dtype=np.float32)

        # Normalise amplitude
        mx = float(np.max(np.abs(data_audio))) if len(data_audio) else 1.0
        if mx > 0:
            data_audio = data_audio / mx * 0.7

        return np.concatenate([preamble, data_audio]).astype(np.float32)

    # ---- demodulate --------------------------------------------------------
    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Decode 2-FSK via energy detection (band-pass filter per tone)."""
        audio = np.asarray(audio, dtype=np.float64)
        sps = int(round(sr / self.baud_rate))
        nyq = sr / 2.0

        # Find sync start
        data_start = self._find_narrowband_preamble(audio)
        data_audio = audio[data_start:]

        if len(data_audio) < sps:
            return np.array([], dtype=np.uint8)

        # Band-pass filter around each tone to get energy envelopes
        bw = min(self.baud_rate * 0.6, 400.0)  # filter width per tone

        def _bp_energy(x: np.ndarray, fc: float, bw: float) -> np.ndarray:
            """Squared magnitude of bandpass-filtered signal -> energy envelope."""
            f_lo = max(fc - bw / 2, 30.0) / nyq
            f_hi = min(fc + bw / 2, nyq * 0.95) / nyq
            if f_hi <= f_lo:
                return np.zeros(len(x))
            sos = scipy_signal.butter(4, [f_lo, f_hi], btype="bandpass", output="sos")
            filt = scipy_signal.sosfiltfilt(sos, x)
            return filt ** 2  # instantaneous power

        e_mark  = _bp_energy(data_audio, self.f_mark,  bw)
        e_space = _bp_energy(data_audio, self.f_space, bw)

        # Segment into symbol windows, sum energy, compare
        n_syms = len(data_audio) // sps
        bits_out = []
        for i in range(n_syms):
            sl = slice(i * sps, (i + 1) * sps)
            em = float(np.sum(e_mark[sl]))
            es = float(np.sum(e_space[sl]))
            bits_out.append(1 if em > es else 0)

        return np.array(bits_out, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Build narrowband schemes
# ---------------------------------------------------------------------------

def build_nb_bfsk_slow() -> NarrowbandBFSK:
    """mark=1000, space=2000, baud=600. Wide 1-octave separation, robust."""
    return NarrowbandBFSK(f_mark=1000.0, f_space=2000.0, baud_rate=600,
                          name="nb_bfsk_slow_1000_2000_600bd")


def build_nb_bfsk_fast() -> NarrowbandBFSK:
    """mark=800, space=1600, baud=1200. Faster, same 2:1 frequency ratio."""
    return NarrowbandBFSK(f_mark=800.0, f_space=1600.0, baud_rate=1200,
                          name="nb_bfsk_fast_800_1600_1200bd")


# ---------------------------------------------------------------------------
# Evaluate all modems through P5
# ---------------------------------------------------------------------------

def run_all(n_seeds: int = 12, payload_bits: int = 2000) -> dict:
    """Evaluate all modems through bluetooth_hfp_narrow (P5) and return results."""
    print(f"T4 bluetooth_narrow: n_seeds={n_seeds}, payload_bits={payload_bits}")
    print("=" * 70)

    results = {}

    # Reference modems
    ref_modems = rw.build_reference_modems(payload_bits)
    nb_slow = build_nb_bfsk_slow()
    nb_fast = build_nb_bfsk_fast()

    schemes = {
        "bfsk_b0":       ref_modems["bfsk_b0"],
        "mfsk32":        ref_modems["mfsk32"],
        "nb_bfsk_slow":  nb_slow,
        "nb_bfsk_fast":  nb_fast,
    }

    for key, scheme in schemes.items():
        t0 = time.time()
        print(f"\n[{key}] gross_bps_declared={getattr(scheme, 'gross_bps', '?'):.0f}")
        res = rw.evaluate_realworld(
            scheme, "bluetooth_hfp_narrow",
            n_seeds=n_seeds, payload_bits=payload_bits,
        )
        dt = time.time() - t0

        # Project to cassette capacity
        proj = hc.project_to_cassette(
            raw_ber=res["raw_bit_error_rate"],
            erasure_rate=res["erasure_rate"],
            gross_bps=res["gross_bps"],
        )
        res["projection"] = proj
        results[key] = res

        print(f"  raw_ber          = {res['raw_bit_error_rate']:.4f}")
        print(f"  erasure_rate     = {res['erasure_rate']:.4f}")
        print(f"  clean_decode_prob= {res['clean_decode_prob']:.3f}")
        print(f"  corr_peak_mean   = {res['corr_peak_mean']:.3f}  "
              f"min={res['corr_peak_min']:.3f}")
        print(f"  net_bps          = {proj['net_bps']:.1f}")
        print(f"  MB/C90-stereo    = {proj['MB_C90_stereo']:.3f}")
        print(f"  P_full           = {proj['P_full']:.2f}")
        print(f"  ({dt:.1f}s)")

    return results


# ---------------------------------------------------------------------------
# Optional plot
# ---------------------------------------------------------------------------

def make_plot(results: dict) -> pathlib.Path | None:
    """Bar chart of net_bps across modems over P5."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available, skipping plot")
        return None

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    out = PLOTS_DIR / "rw_bluetooth_narrow.png"

    names = list(results.keys())
    net_bps  = [results[k]["projection"]["net_bps"] for k in names]
    raw_bers = [results[k]["raw_bit_error_rate"] for k in names]
    cleans   = [results[k]["clean_decode_prob"] for k in names]
    corr_pk  = [results[k]["corr_peak_mean"] for k in names]

    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    fig.suptitle("T4 — Bluetooth HFP Narrowband Path (P5)\n"
                 "lowpass 3400 Hz + libopus voip 12k + AGC", fontsize=12)

    colors = ["#e74c3c" if v < 50 else "#f39c12" if v < 300 else "#2ecc71"
              for v in net_bps]

    ax = axes[0, 0]
    bars = ax.bar(names, net_bps, color=colors, edgecolor="black", linewidth=0.7)
    ax.axhline(478, color="steelblue", linestyle="--", linewidth=1.2,
               label="B0 reference (478 bps)")
    ax.set_ylabel("Net bps (with outer FEC)")
    ax.set_title("Net throughput (projected)")
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", rotation=20)
    for bar, v in zip(bars, net_bps):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 5,
                f"{v:.0f}", ha="center", va="bottom", fontsize=8)

    ax = axes[0, 1]
    ax.bar(names, raw_bers, color=["#c0392b" if v > 0.1 else "#e67e22"
                                    if v > 0.01 else "#27ae60" for v in raw_bers],
           edgecolor="black", linewidth=0.7)
    ax.set_ylabel("Raw BER")
    ax.set_title("Raw bit error rate (pre-FEC)")
    ax.tick_params(axis="x", rotation=20)
    for i, v in enumerate(raw_bers):
        ax.text(i, v + 0.003, f"{v:.3f}", ha="center", fontsize=8)

    ax = axes[1, 0]
    ax.bar(names, cleans, color=["#27ae60" if v > 0.5 else "#e67e22"
                                  if v > 0.1 else "#c0392b" for v in cleans],
           edgecolor="black", linewidth=0.7)
    ax.set_ylabel("Fraction seeds")
    ax.set_title("Clean decode probability (BER=0)")
    ax.set_ylim(0, 1.05)
    ax.tick_params(axis="x", rotation=20)

    ax = axes[1, 1]
    ax.bar(names, corr_pk, color="steelblue", edgecolor="black", linewidth=0.7)
    ax.axhline(0.6, color="red", linestyle="--", linewidth=1.2,
               label="~0.6 recovery floor")
    ax.set_ylabel("Normalised corr. peak")
    ax.set_title("Sync acquisition (corr_peak_mean)")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", rotation=20)

    plt.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {out}")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    N_SEEDS = 12
    PAYLOAD_BITS = 2000

    results = run_all(n_seeds=N_SEEDS, payload_bits=PAYLOAD_BITS)

    # Assemble output JSON
    output = {
        "experiment": "T4_bluetooth_narrow",
        "description": (
            "Tests wideband reference modems (bfsk_b0, mfsk32) and a "
            "purpose-built narrowband BFSK modem through the Bluetooth HFP "
            "narrowband path (P5: lowpass 3400 Hz + libopus voip 12k + AGC)."
        ),
        "path": "bluetooth_hfp_narrow",
        "n_seeds": N_SEEDS,
        "payload_bits": PAYLOAD_BITS,
        "tape_preset": "normal",
        "normal_tape_params": rw.NORMAL_TAPE,
        "results": results,
        "summary": {},
    }

    # Summary comparison
    for key, res in results.items():
        proj = res["projection"]
        output["summary"][key] = {
            "gross_bps": res["gross_bps"],
            "raw_ber": res["raw_bit_error_rate"],
            "clean_decode_prob": res["clean_decode_prob"],
            "corr_peak_mean": res["corr_peak_mean"],
            "net_bps": proj["net_bps"],
            "MB_C90_stereo": proj["MB_C90_stereo"],
            "P_full": proj["P_full"],
        }

    # Save before plot (critical)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "rw_bluetooth_narrow.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2,
                  default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"\nResults saved: {out_path}")

    # Plot (optional)
    make_plot(results)

    # Print final comparison table
    print("\n" + "=" * 70)
    print("FINAL COMPARISON — Bluetooth HFP Narrowband (P5)")
    print(f"{'Modem':<22} {'gross_bps':>9} {'raw_BER':>8} {'clean%':>7} "
          f"{'corr_pk':>8} {'net_bps':>9} {'MB/C90':>7} {'P_full':>7}")
    print("-" * 70)
    for key, s in output["summary"].items():
        print(f"{key:<22} {s['gross_bps']:>9.0f} {s['raw_ber']:>8.4f} "
              f"{s['clean_decode_prob']*100:>6.1f}% {s['corr_peak_mean']:>8.3f} "
              f"{s['net_bps']:>9.1f} {s['MB_C90_stereo']:>7.3f} "
              f"{s['P_full']:>7.2f}")

    return str(out_path)


if __name__ == "__main__":
    main()
