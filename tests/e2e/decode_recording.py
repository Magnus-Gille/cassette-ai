"""decode_recording.py — Robust cassette WAV decoder CLI.

Decodes a recorded WAV file (any sample rate, mono or stereo) using the
robust front-end from cassette_e2e.py and prints a human-readable report.
Optionally compares the recovered payload against an expected value.

Usage:
    python3 tests/e2e/decode_recording.py --wav RECORDED.wav
    python3 tests/e2e/decode_recording.py --wav RECORDED.wav --expect payload.bin
    python3 tests/e2e/decode_recording.py --wav RECORDED.wav --text "hello"
    python3 tests/e2e/decode_recording.py --wav RECORDED.wav --expect payload.bin --json
    python3 tests/e2e/decode_recording.py --wav RECORDED.wav --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

# ---------------------------------------------------------------------------
# Path bootstrap — add the sibling directory (tests/e2e/) so cassette_e2e can
# be imported, and let cassette_e2e itself add src/ to sys.path.
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cassette_e2e as _lib  # noqa: E402 (after path bootstrap)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _preview(data: bytes, n: int = 64) -> str:
    """Return up to n bytes as printable ASCII + hex side-car."""
    chunk = data[:n]
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    hex_str = chunk.hex()
    tail = f" … (+{len(data) - n} more bytes)" if len(data) > n else ""
    return f"{printable!r}  [{hex_str}]{tail}"


# ---------------------------------------------------------------------------
# Core decode + report
# ---------------------------------------------------------------------------

def run(
    wav_path: str,
    *,
    expect_path: str | None = None,
    text: str | None = None,
    as_json: bool = False,
    verbose: bool = False,
    speed_lo: float = 0.94,
    speed_hi: float = 1.06,
    speed_step: float = 0.005,
) -> int:
    """Decode *wav_path* and print results.  Returns 0 on PASS, 1 on FAIL."""
    # --- load wav -----------------------------------------------------------
    wav_path_obj = pathlib.Path(wav_path)
    if not wav_path_obj.exists():
        _die(f"WAV file not found: {wav_path}")

    audio, sample_rate = _lib.read_wav_any(wav_path_obj)

    # --- expected payload (optional) ----------------------------------------
    expected: bytes | None = None
    if expect_path is not None and text is not None:
        _die("Specify at most one of --expect and --text.")
    if expect_path is not None:
        ep = pathlib.Path(expect_path)
        if not ep.exists():
            _die(f"Expect file not found: {expect_path}")
        expected = ep.read_bytes()
    elif text is not None:
        expected = text.encode()

    # --- robust decode -------------------------------------------------------
    rr = _lib.robust_decode(
        audio,
        sample_rate,
        speed_search=(speed_lo, speed_hi, speed_step),
        verbose=verbose,
    )
    dr = rr.result
    payload = dr.payload or b""

    # --- comparison ----------------------------------------------------------
    cmp: dict | None = None
    if expected is not None:
        cmp = _lib.compare_payload(expected, dr)

    # --- build diagnostics dict ---------------------------------------------
    diag: dict = {
        "wav": str(wav_path),
        "detected_sample_rate": rr.from_sample_rate,
        "speed_ratio": rr.speed_ratio,
        "corr_peak": round(rr.corr_peak, 6),
        "start_sample": rr.start_sample,
        "est_snr_db": round(rr.est_snr_db, 2) if rr.est_snr_db == rr.est_snr_db else None,  # NaN -> None
        "recovered_frames": dr.recovered_frames,
        "bad_frames": dr.bad_frames,
        "missing_frames": list(dr.missing_frames) if dr.missing_frames else [],
        "complete": bool(dr.complete),
        "tail_hash_ok": bool(dr.tail_hash_ok),
        "recovered_payload_bytes": len(payload),
        "recovered_payload_sha256": _sha256_hex(payload) if payload else None,
        "errors": list(dr.errors) if dr.errors else [],
    }
    if cmp is not None:
        diag["compare"] = cmp

    # Determine pass/fail.
    if cmp is not None:
        passed = bool(cmp["byte_exact"])
    else:
        # No expectation: PASS if we got a valid header + some payload.
        passed = dr.header is not None and len(payload) > 0

    # --- output --------------------------------------------------------------
    if as_json:
        diag["verdict"] = "PASS" if passed else "FAIL"
        print(json.dumps(diag, indent=2))
    else:
        _print_report(diag, payload, cmp, passed)

    return 0 if passed else 1


def _print_report(
    diag: dict,
    payload: bytes,
    cmp: dict | None,
    passed: bool,
) -> None:
    """Pretty-print the human-readable report to stdout."""
    sep = "-" * 60
    print(sep)
    print("  Cassette Recording Decode Report")
    print(sep)
    print(f"  WAV file           : {diag['wav']}")
    print(f"  Detected sample rate: {diag['detected_sample_rate']} Hz")
    print(f"  Speed ratio chosen : {diag['speed_ratio']:.4f}")
    print(f"  Chirp corr. peak   : {diag['corr_peak']:.4f}")
    print(f"  Data start sample  : {diag['start_sample']}")
    snr = diag["est_snr_db"]
    print(f"  Est. SNR           : {snr:.1f} dB" if snr is not None else "  Est. SNR           : N/A")
    print(sep)
    print(f"  Recovered frames   : {diag['recovered_frames']}")
    print(f"  Bad frames         : {diag['bad_frames']}")
    missing = diag["missing_frames"]
    print(f"  Missing frames     : {missing if missing else 'none'}")
    print(f"  Tail hash OK       : {diag['tail_hash_ok']}")
    print(f"  Complete           : {diag['complete']}")
    print(sep)
    print(f"  Payload length     : {diag['recovered_payload_bytes']} bytes")
    sha = diag["recovered_payload_sha256"]
    print(f"  Payload SHA-256    : {sha if sha else '(empty)'}")
    if payload:
        print(f"  Payload preview    : {_preview(payload)}")
    else:
        print("  Payload preview    : (no payload recovered)")
    if diag["errors"]:
        print(f"  Codec errors       : {diag['errors']}")
    print(sep)

    if cmp is not None:
        print("  Comparison:")
        print(f"    Expected bytes   : {cmp['expected_bytes']}")
        print(f"    Recovered bytes  : {cmp['recovered_bytes']}")
        print(f"    Recovered frac.  : {cmp['recovered_fraction']:.4f}")
        print(f"    Byte error rate  : {cmp['byte_error_rate']:.4f}")
        print(sep)
        verdict = "PASS (exact byte match)" if passed else (
            f"FAIL -- byte_error_rate={cmp['byte_error_rate']:.4f}, "
            f"recovered_fraction={cmp['recovered_fraction']:.4f}"
        )
        print(f"  VERDICT: {verdict}")
    else:
        verdict = "PASS (valid header + payload recovered)" if passed else "FAIL (no valid payload)"
        print(f"  VERDICT: {verdict}")
    print(sep)


def _die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="decode_recording.py",
        description=(
            "Decode a cassette-modem recording (WAV, any sample rate / channel count) "
            "and optionally compare the recovered payload against an expected value."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Decode only — print report
  python3 tests/e2e/decode_recording.py --wav recording.wav

  # Decode and compare against a saved payload file
  python3 tests/e2e/decode_recording.py --wav recording.wav --expect payload.bin

  # Decode and compare against a known text string
  python3 tests/e2e/decode_recording.py --wav recording.wav --text "hello cassette"

  # JSON output (machine-readable, includes all diagnostics)
  python3 tests/e2e/decode_recording.py --wav recording.wav --expect payload.bin --json

  # Verbose: show speed-search progress
  python3 tests/e2e/decode_recording.py --wav recording.wav --verbose

Exit codes:
  0  PASS (exact match if --expect/--text given; valid header+payload otherwise)
  1  FAIL
  2  Usage / file-not-found error
""",
    )
    p.add_argument("--wav", required=True, metavar="PATH",
                   help="Path to the recorded WAV file to decode.")
    expect_grp = p.add_mutually_exclusive_group()
    expect_grp.add_argument("--expect", metavar="PATH",
                             help="Path to a binary file containing the expected payload.")
    expect_grp.add_argument("--text", metavar="STRING",
                             help="Expected payload as a UTF-8 text string.")
    p.add_argument("--json", action="store_true",
                   help="Print results as a JSON object instead of the human report.")
    p.add_argument("--verbose", action="store_true",
                   help="Print speed-search progress lines during decode.")
    p.add_argument("--speed-lo", type=float, default=0.94, metavar="RATIO",
                   help="Lower bound of tape-speed search grid (default: 0.94).")
    p.add_argument("--speed-hi", type=float, default=1.06, metavar="RATIO",
                   help="Upper bound of tape-speed search grid (default: 1.06).")
    p.add_argument("--speed-step", type=float, default=0.005, metavar="STEP",
                   help="Step size for tape-speed search grid (default: 0.005).")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run(
        args.wav,
        expect_path=args.expect,
        text=args.text,
        as_json=args.json,
        verbose=args.verbose,
        speed_lo=args.speed_lo,
        speed_hi=args.speed_hi,
        speed_step=args.speed_step,
    )


if __name__ == "__main__":
    raise SystemExit(main())
