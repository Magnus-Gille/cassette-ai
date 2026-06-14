"""c0_reference.py — Reference anchor for the capacity campaign.

Measures two baselines:
  1. B0 (BFSK / CAS3 shipping codec) via hc.measure_baseline_B0.
  2. MFSK-32 (no FEC) via hc.evaluate_scheme + hc.project_to_cassette using
     the existing MFSKScheme(M=32, walsh_k=0) from src/hyp_h2_mfsk.py.

Canonical settings: n_seeds=16, payload_bits=4000, tape_preset="normal".
Results are saved to experiments/capacity/results/c0_reference.json.
"""

from __future__ import annotations

import json
import sys
import pathlib

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc                   # noqa: E402
from hyp_h2_mfsk import MFSKScheme        # noqa: E402

RESULTS_DIR = ROOT / "experiments" / "capacity" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

N_SEEDS     = 16
PAYLOAD_BITS = 4_000
TAPE_PRESET  = "normal"


# ---------------------------------------------------------------------------
# Sanity gate: zero-channel loopback BER must be ~0
# ---------------------------------------------------------------------------
def _sanity_check(scheme: MFSKScheme) -> float:
    """Pass modulate output straight to demodulate (NO channel). Returns BER."""
    import numpy as np
    rng = np.random.default_rng(42)
    bits = rng.integers(0, 2, size=PAYLOAD_BITS, dtype=np.uint8)
    audio = scheme.modulate(bits)
    recovered = scheme.demodulate(audio, hc.SAMPLE_RATE)
    n = len(bits)
    m = min(n, len(recovered))
    errs = int(np.count_nonzero(bits[:m] != recovered[:m])) + (n - m)
    return errs / n


def main() -> None:
    # -------------------------------------------------------------------
    # 1. Sanity gate
    # -------------------------------------------------------------------
    scheme_mfsk32 = MFSKScheme(M=32, walsh_k=0)
    loopback_ber = _sanity_check(scheme_mfsk32)
    print(f"[sanity] MFSK-32 zero-channel loopback BER = {loopback_ber:.2e}")
    if loopback_ber > 1e-6:
        raise RuntimeError(
            f"Sanity gate FAILED: loopback BER={loopback_ber:.2e} > 1e-6. "
            "Demodulator has a bug — fix before measuring."
        )
    print("[sanity] PASSED")

    # -------------------------------------------------------------------
    # 2. B0 baseline
    # -------------------------------------------------------------------
    print(f"\nMeasuring B0 (n_seeds={N_SEEDS}, payload_bits={PAYLOAD_BITS}) ...")
    b0 = hc.measure_baseline_B0(
        tape_preset=TAPE_PRESET,
        n_seeds=N_SEEDS,
        payload_bits=PAYLOAD_BITS,
    )
    print(
        f"  B0  gross={b0['gross_bps']:.1f} bps  "
        f"raw_BER={b0['raw_bit_error_rate']:.2e}  "
        f"erasure={b0['erasure_rate']:.3f}  "
        f"net_bps={b0['net_bps']:.1f}  "
        f"P_full={b0['P_full']:.2f}"
    )

    # -------------------------------------------------------------------
    # 3. MFSK-32 (no FEC)
    # -------------------------------------------------------------------
    print(f"\nMeasuring MFSK-32 (n_seeds={N_SEEDS}, payload_bits={PAYLOAD_BITS}) ...")
    mfsk32_eval = hc.evaluate_scheme(
        scheme_mfsk32,
        tape_preset=TAPE_PRESET,
        n_seeds=N_SEEDS,
        payload_bits=PAYLOAD_BITS,
        capture_key="usb_soundcard",
    )
    mfsk32_proj = hc.project_to_cassette(
        raw_ber=mfsk32_eval["raw_bit_error_rate"],
        erasure_rate=mfsk32_eval["erasure_rate"],
        gross_bps=mfsk32_eval["gross_bps"],
    )
    print(
        f"  MFSK-32  gross={mfsk32_eval['gross_bps']:.1f} bps  "
        f"raw_BER={mfsk32_eval['raw_bit_error_rate']:.2e}  "
        f"net_bps={mfsk32_proj['net_bps']:.1f}  "
        f"MB_C90_stereo={mfsk32_proj['MB_C90_stereo']:.3f}  "
        f"P_full={mfsk32_proj['P_full']:.2f}"
    )

    # -------------------------------------------------------------------
    # 4. Save results
    # -------------------------------------------------------------------
    out = {
        "experiment": "c0_reference",
        "n_seeds": N_SEEDS,
        "payload_bits": PAYLOAD_BITS,
        "tape_preset": TAPE_PRESET,
        "capture_key": "usb_soundcard",
        "deterministic_note": (
            "RNG seeded deterministically via hc._random_bits(seed=0..n_seeds-1); "
            "channel is seed-deterministic in cs.full_chain. Re-running gives "
            "identical numbers."
        ),
        "sanity_loopback_ber": loopback_ber,
        "B0": b0,
        "MFSK32": {**mfsk32_eval, **mfsk32_proj},
    }

    out_path = RESULTS_DIR / "c0_reference.json"
    with open(out_path, "w") as f:
        json.dump(
            out, f, indent=2,
            default=lambda o: list(o) if hasattr(o, "__iter__") else str(o),
        )
    print(f"\nResults saved to {out_path}")

    # -------------------------------------------------------------------
    # 5. Summary
    # -------------------------------------------------------------------
    print("\n=== c0_reference SUMMARY ===")
    print(f"  B0  net_bps     = {b0['net_bps']:.2f}")
    print(f"  MFSK-32  gross_bps    = {mfsk32_eval['gross_bps']:.2f}")
    print(f"  MFSK-32  raw_BER      = {mfsk32_eval['raw_bit_error_rate']:.2e}")
    print(f"  MFSK-32  net_bps      = {mfsk32_proj['net_bps']:.2f}")
    print(f"  MFSK-32  MB_C90_stereo = {mfsk32_proj['MB_C90_stereo']:.4f}")
    print(f"  MFSK-32  P_full       = {mfsk32_proj['P_full']:.2f}")
    print("============================")

    return out


if __name__ == "__main__":
    main()
