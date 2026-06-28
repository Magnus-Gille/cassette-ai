"""test_sync_failfast.py -- Red/Green tests for sync confidence gate.

Tests use a synthetic signal: chirp0 (up) and chirp1 (down) placed at known
offsets in a noise bed, with a minimal but realistic spacing. The captures are
gitignored so they can't be in committed tests; only the synthetic path is used
here.

Run:
    python3 experiments/tape_v2/test_sync_failfast.py
"""
from __future__ import annotations

import sys
import pathlib
import numpy as np

# Path bootstrap identical to analyze_master2.py
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
TAPE_V2 = ROOT / "experiments" / "tape_v2"
for _p in [str(ROOT / "src"), str(TAPE_V2)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import analyze_master2 as am2  # noqa: E402

SR = am2.SR
CHIRP_LEN = int(am2.GLOBAL_CHIRP_T * SR)


def _build_synthetic_manifest(spacing_samples: int, c0_offset: int = SR) -> dict:
    """Build a minimal manifest dict consistent with global_sync_and_resample."""
    return {
        "tx_chirp0": c0_offset,
        "tx_chirp1": c0_offset + spacing_samples,
    }


def _build_synthetic_signal(
    spacing_samples: int,
    c0_offset: int = SR,
    snr_db: float = 20.0,
    truncate_after_c1: int | None = None,  # samples after chirp1 start
) -> np.ndarray:
    """Build a signal with up-chirp at c0_offset and down-chirp at c0_offset+spacing.

    If truncate_after_c1 is given (e.g. 0), the signal is cut off right after chirp1
    starts, so the down-chirp is NOT fully present.
    """
    rng = np.random.default_rng(42)
    total_len = c0_offset + spacing_samples + CHIRP_LEN + SR  # 1s tail
    noise_amp = 10 ** (-snr_db / 20.0)

    audio = rng.normal(0, noise_amp, total_len).astype(np.float64)

    up = am2._ref_global_chirp(up=True)
    down = am2._ref_global_chirp(up=False)
    audio[c0_offset: c0_offset + len(up)] += up
    audio[c0_offset + spacing_samples: c0_offset + spacing_samples + len(down)] += down

    if truncate_after_c1 is not None:
        audio = audio[:c0_offset + spacing_samples + truncate_after_c1]

    return audio.astype(np.float32)


def test_confident_full_signal():
    """A signal with both chirps present should be sync_confident=True."""
    spacing = int(4.0 * SR)   # 4 s spacing — small but realistic for a test
    manifest = _build_synthetic_manifest(spacing)
    audio = _build_synthetic_signal(spacing)
    result = am2.global_sync_and_resample(audio, manifest)

    assert result["sync_confident"], (
        f"Expected sync_confident=True for full signal; got False. "
        f"warning={result.get('sync_warning')!r}  "
        f"c0_prom={result.get('chirp0_prominence'):.3f}  "
        f"c1_prom={result.get('chirp1_prominence'):.3f}"
    )
    assert result["chirp0_prominence"] > am2.MIN_CHIRP_PROMINENCE, (
        f"chirp0 prominence {result['chirp0_prominence']:.3f} below threshold "
        f"{am2.MIN_CHIRP_PROMINENCE}"
    )
    assert result["chirp1_prominence"] > am2.MIN_CHIRP_PROMINENCE, (
        f"chirp1 prominence {result['chirp1_prominence']:.3f} below threshold "
        f"{am2.MIN_CHIRP_PROMINENCE}"
    )
    print(
        f"  PASS test_confident_full_signal  "
        f"c0={result['chirp0_prominence']:.3f}  c1={result['chirp1_prominence']:.3f}"
    )


def test_not_confident_truncated_signal():
    """A signal with the down-chirp truncated should be sync_confident=False."""
    spacing = int(4.0 * SR)
    manifest = _build_synthetic_manifest(spacing)
    # Truncate 10 samples after chirp1 starts — almost no down-chirp present
    audio = _build_synthetic_signal(spacing, truncate_after_c1=10)
    result = am2.global_sync_and_resample(audio, manifest)

    assert not result["sync_confident"], (
        f"Expected sync_confident=False for truncated signal; got True. "
        f"c0_prom={result.get('chirp0_prominence'):.3f}  "
        f"c1_prom={result.get('chirp1_prominence'):.3f}"
    )
    assert result["sync_warning"], "Expected non-empty sync_warning for truncated signal"
    print(
        f"  PASS test_not_confident_truncated_signal  "
        f"c0={result.get('chirp0_prominence'):.3f}  "
        f"c1={result.get('chirp1_prominence'):.3f}  "
        f"warning={result['sync_warning']!r}"
    )


def test_not_confident_zeroed_c1():
    """A signal with chirp1 zeroed out (no energy at end) should be sync_confident=False."""
    spacing = int(4.0 * SR)
    manifest = _build_synthetic_manifest(spacing)
    audio = np.array(_build_synthetic_signal(spacing), dtype=np.float64)
    c0 = SR
    # Zero out the last 2s of the signal (where chirp1 would be)
    audio[c0 + spacing - SR:] = 0.0
    result = am2.global_sync_and_resample(audio.astype(np.float32), manifest)

    assert not result["sync_confident"], (
        f"Expected sync_confident=False for zeroed chirp1; got True. "
        f"c0_prom={result.get('chirp0_prominence'):.3f}  "
        f"c1_prom={result.get('chirp1_prominence'):.3f}"
    )
    print(
        f"  PASS test_not_confident_zeroed_c1  "
        f"c0={result.get('chirp0_prominence'):.3f}  "
        f"c1={result.get('chirp1_prominence'):.3f}  "
        f"warning={result['sync_warning']!r}"
    )


def test_new_keys_present():
    """Return dict must always have the new confidence keys, even in degenerate input."""
    spacing = int(4.0 * SR)
    manifest = _build_synthetic_manifest(spacing)
    audio = _build_synthetic_signal(spacing)
    result = am2.global_sync_and_resample(audio, manifest)
    for key in ("chirp0_prominence", "chirp1_prominence", "sync_confident", "sync_warning"):
        assert key in result, f"Missing key {key!r} in sync result"
    print("  PASS test_new_keys_present")


if __name__ == "__main__":
    print("Running sync failfast tests (RED before implementation)...")
    failures = []
    for fn in [
        test_new_keys_present,
        test_confident_full_signal,
        test_not_confident_truncated_signal,
        test_not_confident_zeroed_c1,
    ]:
        try:
            fn()
        except (AssertionError, AttributeError, KeyError, TypeError) as exc:
            print(f"  FAIL {fn.__name__}: {exc}")
            failures.append(fn.__name__)
    if failures:
        print(f"\n{len(failures)} test(s) FAILED (expected in RED phase): {failures}")
        sys.exit(1)
    else:
        print("\nAll tests PASSED.")
        sys.exit(0)
