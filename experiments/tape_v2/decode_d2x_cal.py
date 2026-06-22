"""decode_d2x_cal.py -- Decode a d2x calibration WAV and verify byte-exact recovery.

Usage:
    python3 experiments/tape_v2/decode_d2x_cal.py <capture.wav> \
        [--manifest cal_d2x_manifest.json] [--channel 0]

The <capture.wav> is typically the clean cal_d2x_mono.wav (self-verify) or a
real electrical loopback recording. Stereo inputs are split to the chosen channel.

For a raw (non-lzma) calibration payload, the manifest's sec["pack"] is None, so
we call _decode_section() directly rather than the DOOM decode() wrapper (which
tries to access pack["sha256_orig"] and crashes on a raw payload).

Exits 0 iff byte_exact is True.

Prints: byte_exact, rs_codewords_failed, BER, n_byte_errors.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
TAPE_V2 = ROOT / "experiments" / "tape_v2"
DOOM_SHIP = TAPE_V2 / "doom_ship"

for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity",
           TAPE_V2, DOOM_SHIP):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)

import analyze_master2 as am2  # noqa: E402
import m10_decode as m10       # noqa: E402

SR = 48_000
DEFAULT_MANIFEST = TAPE_V2 / "cal_d2x_manifest.json"


def decode_cal(recording_path: str,
               manifest_path: str | None = None,
               channel: int = 0) -> dict:
    mpath = pathlib.Path(manifest_path) if manifest_path else DEFAULT_MANIFEST
    if not mpath.is_absolute():
        mpath = TAPE_V2 / mpath
    manifest = json.loads(mpath.read_text())

    # ---- load + channel select + resample -----------------------------------
    audio, sr = sf.read(str(recording_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        n_ch = audio.shape[1]
        if channel >= n_ch:
            raise ValueError(f"--channel {channel} but file has only {n_ch} channel(s)")
        audio = audio[:, channel]
        print(f"[decode_d2x_cal] stereo→channel {channel}")
    else:
        if channel != 0:
            print(f"[decode_d2x_cal] WARN: mono file but --channel {channel}; ignoring")

    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64),
                              frac.numerator, frac.denominator).astype(np.float32)
        print(f"[decode_d2x_cal] resampled {sr}→{SR} Hz "
              f"({frac.numerator}/{frac.denominator})")

    # ---- global sync (chirp-pair clock recovery + nominal resample) ---------
    print("[decode_d2x_cal] running global sync...", flush=True)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])
    print(f"[decode_d2x_cal] sync: speed={sync['speed']:.5f}x  align={align:+d}  "
          f"resampled {sync['resample_num']}/{sync['resample_den']}", flush=True)

    # ---- per-section decode (composed superset: pass1 ensemble + rescue) ----
    ledger = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}

    sec = manifest["ws_payloads"][0]
    print(f"[decode_d2x_cal] decoding section '{sec['name']}' "
          f"({sec['meta']['n_frames']} frames, "
          f"{sec['meta']['n_codewords']} codewords)...", flush=True)

    r, assembled = m10._decode_section(audio_nom, sec, align, ledger, rescue=True)

    # ---- compare to known payload (the sidecar written by make_d2x_cal.py) --
    # _decode_section already reads the sidecar and computes byte_exact internally;
    # we also load it explicitly for BER/byte-error reporting.
    sidecar_path = TAPE_V2 / sec["payload_sidecar"]
    known = sidecar_path.read_bytes()
    payload_len = sec["meta"]["payload_len"]

    byte_exact = r["byte_exact"]
    n_byte_errors = r["byte_errors"]
    rs_codewords_failed = r["rs_codewords_failed"]

    # Bit-error rate over the payload window
    a_arr = np.frombuffer(assembled[:payload_len], dtype=np.uint8)
    k_arr = np.frombuffer(known[:payload_len], dtype=np.uint8)
    n_bytes = min(len(a_arr), len(k_arr))
    if n_bytes > 0:
        xor = np.bitwise_xor(a_arr[:n_bytes], k_arr[:n_bytes])
        bit_errors = int(np.unpackbits(xor).sum())
        ber = bit_errors / (n_bytes * 8)
    else:
        bit_errors = 0
        ber = 0.0

    print()
    print("=" * 60)
    print(f"  byte_exact          : {byte_exact}")
    print(f"  rs_codewords_failed : {rs_codewords_failed} / {sec['meta']['n_codewords']}")
    print(f"  n_byte_errors       : {n_byte_errors}")
    print(f"  BER                 : {ber:.3e}  ({bit_errors} / {n_bytes * 8} bits)")
    print(f"  front_end_used      : {r.get('front_end_used')}")
    print(f"  elapsed             : {r.get('elapsed_s')}s")
    print("=" * 60)

    return {
        "byte_exact": byte_exact,
        "rs_codewords_failed": rs_codewords_failed,
        "n_byte_errors": n_byte_errors,
        "ber": ber,
        "front_end_used": r.get("front_end_used"),
    }


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    ap = argparse.ArgumentParser(
        description="Decode a d2x calibration WAV and verify byte-exact recovery.")
    ap.add_argument("capture_wav", help="path to the WAV to decode")
    ap.add_argument("--manifest", default=None,
                    help="manifest JSON (default: cal_d2x_manifest.json)")
    ap.add_argument("--channel", type=int, default=0,
                    help="channel to use for stereo input (default: 0)")
    args = ap.parse_args()

    result = decode_cal(args.capture_wav, args.manifest, args.channel)
    sys.exit(0 if result["byte_exact"] else 1)
