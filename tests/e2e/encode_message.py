"""encode_message.py — Encode a small message into a recordable WAV.

Usage:
    python3 tests/e2e/encode_message.py [--text "hello"] [--in PATH] \
        [--out tests/e2e/artifacts/signal.wav] [--lead 0.5] [--tail 0.5]

Payload source (mutually exclusive; at most one):
  --text TEXT   UTF-8 string to encode.
  --in PATH     File whose raw bytes are encoded.
  (neither)     Built-in demo payload.

Outputs:
  <out>              16-bit PCM mono WAV at 48 kHz.
  <out>.payload.bin  Exact original payload bytes (sidecar for decode_recording.py).

Prints: payload length, SHA-256 hex, wav path, wav duration in seconds, sidecar path.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import warnings

# ---------------------------------------------------------------------------
# Path bootstrap — give us both src/ (codec) and tests/e2e/ (cassette_e2e).
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parents[1] / "src"
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_HERE))

import cassette_e2e as ce  # noqa: E402
import soundfile as sf     # noqa: E402  (needed only to query duration)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_PAYLOAD: bytes = (
    b"CASSETTE-AI end-to-end test :: " + bytes(range(32))
)
_DEFAULT_OUT = _HERE / "artifacts" / "signal.wav"
_WARN_BYTES = 512


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Encode a message into a cassette-modem WAV file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--text",
        metavar="TEXT",
        help="UTF-8 string to encode.",
    )
    src.add_argument(
        "--in",
        dest="infile",
        metavar="PATH",
        help="File whose raw bytes are encoded.",
    )
    p.add_argument(
        "--out",
        metavar="PATH",
        default=str(_DEFAULT_OUT),
        help=f"Output WAV path (default: {_DEFAULT_OUT}).",
    )
    p.add_argument(
        "--lead",
        type=float,
        default=0.5,
        metavar="S",
        help="Leading silence in seconds (default: 0.5).",
    )
    p.add_argument(
        "--tail",
        type=float,
        default=0.5,
        metavar="S",
        help="Trailing silence in seconds (default: 0.5).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Resolve payload ---
    if args.text is not None:
        payload = args.text.encode("utf-8")
    elif args.infile is not None:
        inpath = pathlib.Path(args.infile)
        if not inpath.is_file():
            print(f"ERROR: --in path not found: {inpath}", file=sys.stderr)
            return 1
        payload = inpath.read_bytes()
    else:
        payload = _DEFAULT_PAYLOAD

    if len(payload) > _WARN_BYTES:
        warnings.warn(
            f"Payload is {len(payload)} bytes (> {_WARN_BYTES}). "
            "Large payloads reduce decode robustness on real tape.",
            stacklevel=1,
        )

    if len(payload) == 0:
        print("ERROR: payload is empty.", file=sys.stderr)
        return 1

    # --- Output paths ---
    out_path = pathlib.Path(args.out).resolve()
    sidecar_path = out_path.parent / (out_path.name + ".payload.bin")

    # Create artifacts dir if needed.
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Encode ---
    audio = ce.encode_payload_to_audio(payload)

    # --- Write WAV ---
    ce.write_wav(
        out_path,
        audio,
        sample_rate=ce.SAMPLE_RATE,
        peak=0.7,
        lead_silence_s=args.lead,
        tail_silence_s=args.tail,
    )

    # --- Write sidecar ---
    sidecar_path.write_bytes(payload)

    # --- Compute stats ---
    sha = hashlib.sha256(payload).hexdigest()
    info = sf.info(str(out_path))
    duration_s = info.frames / info.samplerate

    # --- Report ---
    print(f"payload_length : {len(payload)} bytes")
    print(f"sha256         : {sha}")
    print(f"wav_path       : {out_path}")
    print(f"wav_duration_s : {duration_s:.3f}")
    print(f"sidecar_path   : {sidecar_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
