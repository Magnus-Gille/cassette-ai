"""Build and decode the independent-stereo P23 hybrid-DPSK tape trial.

The master is deliberately a short ladder: a DQPSK control, a five-carrier
8-DPSK banker, the selected 16-carrier candidate, and an 18-carrier stretch.
Left and right carry different deterministic payloads so a successful capture
demonstrates the full stereo rate rather than two copies of one mono stream.

Build (does not play audio):
    python3 experiments/tape_v2/wired_hybrid_physical.py --build --selfcheck

Decode a UCA222 capture:
    python3 experiments/tape_v2/wired_hybrid_physical.py --decode CAPTURE.wav
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import pathlib
import sys
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from reedsolo import RSCodec, ReedSolomonError
from scipy.signal import resample_poly

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BPS_DIR = HERE / "bps_push_2026_06_14"
for path in (ROOT / "src", ROOT / "tests" / "e2e",
             ROOT / "experiments" / "capacity",
             ROOT / "experiments" / "deepdive2", HERE, BPS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from analyze_master2 import global_sync_and_resample  # noqa: E402
from exp_wired_hybrid_dpsk import P23HybridDPSK, RANKED_D8_HZ  # noqa: E402
from hyp_common import find_preamble, make_preamble  # noqa: E402
from make_master2 import GLOBAL_CHIRP_T, _make_global_chirp, _silence  # noqa: E402

SR = 48_000
RS_N = 255
PEAK = 0.70
GAP_S = 0.40
FRAME_GAP_S = 0.12
MASTER_ID = "wired_hybrid_physical_v1"
WAV_PATH = HERE / "wired_hybrid_stereo_master.wav"
MANIFEST_PATH = HERE / "wired_hybrid_stereo_manifest.json"
RESULTS_DIR = HERE / "results"
N_CODEWORDS = 48
SEED_BASE = 2026071000

LADDER = [
    {"name": "p23_dq_rs179_control", "n8": 0, "rs_k": 179,
     "role": "fixed-pilot DQPSK control"},
    {"name": "p23_d8x5_rs179_banker", "n8": 5, "rs_k": 179,
     "role": "conservative hybrid banker"},
    {"name": "p23_d8x16_rs155_candidate", "n8": 16, "rs_k": 155,
     "role": "recommended 14.13 kb/s stereo candidate"},
    {"name": "p23_d8x18_rs151_stretch", "n8": 18, "rs_k": 151,
     "role": "slightly faster physical stretch"},
]


def _seeded_payload(seed: int, size: int) -> bytes:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=size, dtype=np.uint8).tobytes()


def _encode(message: bytes, rs_k: int):
    rsc = RSCodec(RS_N - rs_k)
    n_cw = len(message) // rs_k
    codewords = []
    crcs = []
    for i in range(n_cw):
        chunk = message[i * rs_k:(i + 1) * rs_k]
        codewords.append(bytes(rsc.encode(chunk)))
        crcs.append(zlib.crc32(chunk) & 0xFFFFFFFF)
    matrix = np.frombuffer(b"".join(codewords), np.uint8).reshape(n_cw, RS_N)
    bits = np.unpackbits(matrix.T.reshape(-1)).astype(np.uint8)
    return bits, crcs


def _decode_bits(bits: np.ndarray, rs_k: int, n_cw: int, crcs: list[int]):
    need = n_cw * RS_N * 8
    rx = np.asarray(bits, np.uint8).ravel()
    if len(rx) < need:
        rx = np.pad(rx, (0, need - len(rx)))
    matrix = np.packbits(rx[:need]).reshape(RS_N, n_cw).T
    rsc = RSCodec(RS_N - rs_k)
    recovered = bytearray()
    passed = 0
    for i, codeword in enumerate(matrix):
        message = None
        try:
            candidate = bytes(rsc.decode(bytes(codeword))[0])
            if len(candidate) == rs_k:
                message = candidate
        except (ReedSolomonError, Exception):
            pass
        ok = message is not None and (zlib.crc32(message) & 0xFFFFFFFF) == crcs[i]
        passed += int(ok)
        recovered.extend(message if message is not None else bytes(rs_k))
    return bytes(recovered), passed


def build(out_wav: pathlib.Path = WAV_PATH) -> dict:
    left: list[np.ndarray] = []
    right: list[np.ndarray] = []
    pos = 0

    def add(l: np.ndarray, r: np.ndarray | None = None):
        nonlocal pos
        l = np.asarray(l, np.float32)
        r = l if r is None else np.asarray(r, np.float32)
        assert len(l) == len(r)
        left.append(l)
        right.append(r)
        pos += len(l)

    manifest = {
        "master_id": MASTER_ID,
        "SR": SR,
        "channels": ["L", "R"],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "rungs": [],
    }

    add(_silence(1.0))
    manifest["tx_chirp0"] = pos
    add(_make_global_chirp(up=True))
    add(_silence(GAP_S))

    print(f"[build] {MASTER_ID}: independent L/R, {len(LADDER)} rungs")
    for rung_index, rung in enumerate(LADDER):
        d8 = RANKED_D8_HZ[:rung["n8"]]
        scheme = P23HybridDPSK(d8)
        rs_k = int(rung["rs_k"])
        message_bytes = N_CODEWORDS * rs_k
        seeds = [SEED_BASE + 2 * rung_index, SEED_BASE + 2 * rung_index + 1]
        payloads = [_seeded_payload(seed, message_bytes) for seed in seeds]
        encoded = [_encode(payload, rs_k) for payload in payloads]
        tx_bits_l, crcs_l = encoded[0]
        tx_bits_r, crcs_r = encoded[1]
        assert not np.array_equal(tx_bits_l, tx_bits_r)

        start = pos
        body_l = np.asarray(scheme.modulate(tx_bits_l), np.float32)
        body_r = np.asarray(scheme.modulate(tx_bits_r), np.float32)
        assert len(body_l) == len(body_r)
        add(body_l, body_r)
        body_end = pos
        add(_silence(FRAME_GAP_S))
        segment_end = pos
        add(_silence(GAP_S))

        gross = float(scheme.gross_bps)
        net_mono = gross * rs_k / RS_N
        entry = {
            **rung,
            "d8_freqs_hz": [int(f) for f in d8],
            "bits_per_symbol": int(scheme.bits_per_sym),
            "gross_bps_mono": gross,
            "projected_net_bps_mono": net_mono,
            "projected_net_bps_stereo": 2 * net_mono,
            "n_codewords": N_CODEWORDS,
            "coded_bits": int(len(tx_bits_l)),
            "message_bytes_per_channel": message_bytes,
            "payload_seeds": seeds,
            "payload_sha256": [hashlib.sha256(p).hexdigest() for p in payloads],
            "crc32_codewords": [crcs_l, crcs_r],
            "segment_start_sample": int(start),
            "body_end_sample": int(body_end),
            "segment_end_sample": int(segment_end),
            "body_samples": int(len(body_l)),
        }
        manifest["rungs"].append(entry)
        seconds = len(body_l) / SR
        print(f"  {rung['name']:<31} {seconds:5.1f}s  "
              f"{2 * net_mono:8.1f} net bit/s stereo")

    add(_silence(1.0))
    manifest["tx_chirp1"] = pos
    add(_make_global_chirp(up=False))
    add(_silence(GAP_S + 1.0))

    stereo = np.column_stack([np.concatenate(left), np.concatenate(right)])
    raw_peak = float(np.max(np.abs(stereo)))
    stereo = (stereo / raw_peak * PEAK).astype(np.float32)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, stereo, SR, subtype="FLOAT")
    manifest["duration_seconds"] = len(stereo) / SR
    manifest["peak"] = PEAK
    manifest["wav_path"] = str(out_wav)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"[build] wrote {out_wav} ({manifest['duration_seconds']:.1f}s)")
    print(f"[build] wrote {MANIFEST_PATH}")
    return manifest


def _load_channels(wav_path: pathlib.Path):
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20_000)
        audio = np.column_stack([
            resample_poly(audio[:, ch], frac.numerator, frac.denominator)
            for ch in range(audio.shape[1])
        ])
    if audio.shape[1] < 2:
        raise ValueError("This experiment requires a stereo UCA222 capture")
    return audio[:, :2]


def _resample_exact(signal: np.ndarray, target_samples: int) -> np.ndarray:
    """Resample one locally clocked rung and force its manifest-known length."""
    signal = np.asarray(signal, np.float32)
    if len(signal) == target_samples:
        return signal
    frac = Fraction(target_samples, max(1, len(signal))).limit_denominator(20_000)
    out = np.asarray(resample_poly(signal, frac.numerator, frac.denominator),
                     np.float32)
    if len(out) < target_samples:
        out = np.pad(out, (0, target_samples - len(out)))
    return out[:target_samples]


def decode(wav_path: pathlib.Path, *, selfcheck: bool = False) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    if manifest["master_id"] != MASTER_ID:
        raise ValueError("manifest/master mismatch")
    audio = _load_channels(wav_path)
    channel_results = []
    for channel in range(2):
        # Keep the end-to-end chirp result as a timeline-integrity diagnostic,
        # but do NOT use its affine resampling for payload decode.  A UCA/playback
        # discontinuity can delete samples in one rung; fitting that jump as a
        # uniform clock error stretches every otherwise-good rung.  Each payload
        # already has its own modem preamble, so reacquire it in the raw channel
        # and use the manifest's known symbol count/length.
        sync = global_sync_and_resample(audio[:, channel], manifest)
        sync.pop("audio_nominal")
        chirp0_raw = int(sync["chirp0_meas"])
        preamble_samples = len(make_preamble())
        search_radius = int(3.0 * SR)

        # Locate every rung first.  Consecutive preamble spacings then give a
        # local clock estimate for the preceding rung.  This handles ordinary
        # deck speed (capture 2: smooth ~+0.086%) without smearing discontinuous
        # sample losses across unrelated rungs (capture 1).
        located = []
        for entry in manifest["rungs"]:
            predicted_start = (chirp0_raw + int(entry["segment_start_sample"])
                               - int(manifest["tx_chirp0"]))
            search_lo = max(0, predicted_start - search_radius)
            search_hi = min(len(audio), predicted_start + search_radius
                            + preamble_samples)
            search = audio[search_lo:search_hi, channel]
            body_after_preamble = find_preamble(search)
            detected_start = max(
                0, search_lo + body_after_preamble - preamble_samples)
            located.append({
                "entry": entry,
                "predicted_start": int(predicted_start),
                "detected_start": int(detected_start),
            })

        rows = []
        for rung_index, location in enumerate(located):
            entry = location["entry"]
            rs_k = int(entry["rs_k"])
            seed = int(entry["payload_seeds"][channel])
            payload = _seeded_payload(seed, int(entry["message_bytes_per_channel"]))
            tx_bits, _ = _encode(payload, rs_k)
            assert hashlib.sha256(payload).hexdigest() == entry["payload_sha256"][channel]
            scheme = P23HybridDPSK(entry["d8_freqs_hz"])

            expected_symbols = 1 + int(math.ceil(
                int(entry["coded_bits"]) / int(entry["bits_per_symbol"])))
            expected_body_samples = preamble_samples + expected_symbols * scheme.N
            assert expected_body_samples == int(entry["body_samples"])

            detected_start = int(location["detected_start"])
            predicted_start = int(location["predicted_start"])
            if rung_index + 1 < len(located):
                next_detected = int(located[rung_index + 1]["detected_start"])
                next_expected = int(located[rung_index + 1]["entry"]
                                    ["segment_start_sample"])
            else:
                next_detected = int(sync["chirp1_meas"])
                next_expected = int(manifest["tx_chirp1"])
            expected_interval = next_expected - int(entry["segment_start_sample"])
            measured_interval = next_detected - detected_start
            local_clock_scale = measured_interval / max(1, expected_interval)
            if not 0.90 <= local_clock_scale <= 1.10:
                local_clock_scale = 1.0
            raw_body_samples = int(round(expected_body_samples * local_clock_scale))
            detected_end = detected_start + raw_body_samples
            raw_window = np.asarray(
                audio[detected_start:min(len(audio), detected_end), channel],
                np.float32)
            if len(raw_window) < raw_body_samples:
                raw_window = np.pad(raw_window,
                                    (0, raw_body_samples - len(raw_window)))
            window = _resample_exact(raw_window, expected_body_samples)
            rx_bits = np.asarray(scheme.demodulate(window, SR), np.uint8)
            n = len(tx_bits)
            matched = min(n, len(rx_bits))
            errors = int(np.count_nonzero(tx_bits[:matched] != rx_bits[:matched]))
            errors += n - matched
            recovered, cw_passed = _decode_bits(
                rx_bits, rs_k, int(entry["n_codewords"]),
                entry["crc32_codewords"][channel])
            rows.append({
                "name": entry["name"],
                "raw_ber": errors / n,
                "codewords_passed": cw_passed,
                "n_codewords": int(entry["n_codewords"]),
                "byte_exact": recovered == payload,
                "projected_net_bps_mono": entry["projected_net_bps_mono"],
                "local_preamble_start": int(detected_start),
                "predicted_preamble_start": int(predicted_start),
                "timeline_residual_samples": int(detected_start - predicted_start),
                "local_clock_scale": float(local_clock_scale),
                "raw_body_samples": raw_body_samples,
                "expected_symbols_including_reference": expected_symbols,
            })
        channel_results.append({"channel": "LR"[channel], "sync": sync, "rungs": rows})

    all_exact = all(row["byte_exact"] for ch in channel_results for row in ch["rungs"])
    stereo_exact_profiles = []
    for rung_index, entry in enumerate(manifest["rungs"]):
        if all(ch["rungs"][rung_index]["byte_exact"] for ch in channel_results):
            stereo_exact_profiles.append({
                "name": entry["name"],
                "net_bps_stereo": entry["projected_net_bps_stereo"],
            })
    stereo_grade = (max(stereo_exact_profiles, key=lambda row: row["net_bps_stereo"])
                    if stereo_exact_profiles else None)
    result = {
        "master_id": MASTER_ID,
        "wav": str(wav_path),
        "selfcheck": selfcheck,
        "all_byte_exact": all_exact,
        "stereo_exact_profiles": stereo_exact_profiles,
        "stereo_grade": stereo_grade,
        "channels": channel_results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = "selfcheck" if selfcheck else wav_path.stem
    out = RESULTS_DIR / f"wired_hybrid_physical_{tag}.json"
    out.write_text(json.dumps(result, indent=2))
    for ch in channel_results:
        print(f"[decode] channel {ch['channel']} speed={ch['sync']['speed']:.6f}")
        for row in ch["rungs"]:
            print(f"  {row['name']:<31} BER={row['raw_ber']:.6f}  "
                  f"CW={row['codewords_passed']}/{row['n_codewords']}  "
                  f"exact={'YES' if row['byte_exact'] else 'no'}  "
                  f"timeline={row['timeline_residual_samples']:+d} samp  "
                  f"local_clock={row['local_clock_scale']:.6f}")
    print(f"[decode] all byte-exact: {all_exact}; wrote {out}")
    if stereo_grade:
        grade_label = ("CLEAN SELF-CHECK CEILING" if selfcheck
                       else "PHYSICAL STEREO GRADE")
        print(f"[decode] {grade_label}: {stereo_grade['name']} = "
              f"{stereo_grade['net_bps_stereo']:.2f} net bit/s")
    else:
        print("[decode] PHYSICAL STEREO GRADE: no profile passed both channels")
    if selfcheck and not all_exact:
        raise AssertionError("no-channel master self-check failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--decode", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, default=WAV_PATH)
    args = parser.parse_args()
    if not args.build and args.decode is None:
        parser.error("choose --build or --decode CAPTURE.wav")
    if args.build:
        build(args.out)
        if args.selfcheck:
            decode(args.out, selfcheck=True)
    elif args.decode is not None:
        decode(args.decode, selfcheck=args.selfcheck)
