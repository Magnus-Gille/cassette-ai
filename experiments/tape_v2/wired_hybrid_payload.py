"""Production-style one-side payload tape using the proven hybrid P23 modem.

Default payload: Chess-GPT 4.5M INT4 weights.  The raw 3.55 MB model is wrapped
in the repo's self-verifying H9 container, striped bytewise across independent
left/right channels, and protected by stripe-local in-band CRC + RS(255,155).

Framing is intentionally much tougher than the rate-test ladder:
  * 272 codewords per channel/stripe, 151 user bytes + CRC32 per codeword.
  * 17 independently synchronized PHY frames per stripe.
  * each PHY frame carries 15 complete interleaved RS byte-columns.
  * three completely lost frames per stripe remain errors-only correctable.

Build (never plays audio):
    python3 experiments/tape_v2/wired_hybrid_payload.py --build --quick-selfcheck

Decode a captured side:
    python3 experiments/tape_v2/wired_hybrid_payload.py --decode CAPTURE.wav
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOOM_SHIP = HERE / "doom_ship"
for path in (ROOT / "src", ROOT / "tests" / "e2e",
             ROOT / "experiments" / "capacity",
             ROOT / "experiments" / "deepdive2", HERE, DOOM_SHIP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from analyze_master2 import global_sync_and_resample  # noqa: E402
from exp_wired_hybrid_dpsk import P23HybridDPSK, RANKED_D8_HZ  # noqa: E402
import h9_payload_codec as h9  # noqa: E402
from hyp_common import find_preamble, make_preamble  # noqa: E402
import inband_crc as ib  # noqa: E402
from make_master2 import GLOBAL_CHIRP_T, _make_global_chirp, _silence  # noqa: E402
from m10doom_master import pack_doom as pack_h9_lzma  # noqa: E402
from m10doom_master import unpack_doom as unpack_h9_lzma  # noqa: E402
from rs_backend import RSCodec, ReedSolomonError, BACKEND as RS_BACKEND  # noqa: E402

SR = 48_000
RS_N = 255
RS_K = 155
D8_FREQS = RANKED_D8_HZ[:16]
CODEWORDS_PER_STRIPE = 272
COLUMNS_PER_FRAME = 15
FRAMES_PER_STRIPE = RS_N // COLUMNS_PER_FRAME
FRAME_CODED_BYTES = CODEWORDS_PER_STRIPE * COLUMNS_PER_FRAME
FRAME_CODED_BITS = FRAME_CODED_BYTES * 8
FRAME_GAP_S = 0.12
FRAME_GAP_SAMPLES = int(FRAME_GAP_S * SR)
STRIPE_USER_BYTES = (CODEWORDS_PER_STRIPE * ib.k_data_bytes(RS_K)
                     - ib.HEADER.size)
MASTER_ID = "wired_hybrid_chessgpt_v1"

PAYLOAD_PATH = ROOT / "payloads" / "built" / "chess-gpt-4.5M" / "chess_gpt_int4.bin"
WAV_PATH = HERE / "wired_hybrid_chessgpt_master.wav"
MANIFEST_PATH = HERE / "wired_hybrid_chessgpt_manifest.json"
RESULTS_DIR = HERE / "results"
RECOVERED_DIR = HERE / "recovered"
RECOVERED_PATH = RECOVERED_DIR / "chess_gpt_int4.recovered.bin"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resample_exact(signal: np.ndarray, target_samples: int) -> np.ndarray:
    signal = np.asarray(signal, np.float32)
    if len(signal) == target_samples:
        return signal
    frac = Fraction(target_samples, max(1, len(signal))).limit_denominator(20_000)
    out = np.asarray(resample_poly(signal, frac.numerator, frac.denominator),
                     np.float32)
    if len(out) < target_samples:
        out = np.pad(out, (0, target_samples - len(out)))
    return out[:target_samples]


def _stripe_split(blob: bytes) -> tuple[bytes, bytes]:
    return blob[0::2], blob[1::2]


def _stripe_join(left: bytes, right: bytes, total_bytes: int) -> bytes:
    out = bytearray(total_bytes)
    out[0::2] = left[:(total_bytes + 1) // 2]
    out[1::2] = right[:total_bytes // 2]
    return bytes(out)


def _encode_stripe(user_chunk: bytes) -> list[np.ndarray]:
    """CIB1 messages -> RS codewords -> column interleave -> 17 PHY frames."""
    if len(user_chunk) > STRIPE_USER_BYTES:
        raise ValueError("stripe payload exceeds fixed geometry")
    padded = bytes(user_chunk) + bytes(STRIPE_USER_BYTES - len(user_chunk))
    messages = ib.frame_payload(padded, RS_K)
    assert len(messages) == CODEWORDS_PER_STRIPE
    rsc = RSCodec(RS_N - RS_K)
    codewords = [bytes(rsc.encode(message)) for message in messages]
    matrix = np.frombuffer(b"".join(codewords), np.uint8).reshape(
        CODEWORDS_PER_STRIPE, RS_N)
    stream = matrix.T.reshape(-1)
    frames = [
        np.unpackbits(stream[i:i + FRAME_CODED_BYTES]).astype(np.uint8)
        for i in range(0, len(stream), FRAME_CODED_BYTES)
    ]
    assert len(frames) == FRAMES_PER_STRIPE
    assert all(len(frame) == FRAME_CODED_BITS for frame in frames)
    return frames


def _decode_stripe(rx_frames: list[np.ndarray]) -> tuple[bytes, dict]:
    """Inverse stripe codec, with only in-band CRC as the acceptance channel."""
    pieces = []
    for index in range(FRAMES_PER_STRIPE):
        bits = (np.asarray(rx_frames[index], np.uint8).ravel()
                if index < len(rx_frames) else np.zeros(FRAME_CODED_BITS, np.uint8))
        if len(bits) < FRAME_CODED_BITS:
            bits = np.pad(bits, (0, FRAME_CODED_BITS - len(bits)))
        pieces.append(np.packbits(bits[:FRAME_CODED_BITS]))
    stream = np.concatenate(pieces)
    matrix = stream.reshape(RS_N, CODEWORDS_PER_STRIPE).T
    rsc = RSCodec(RS_N - RS_K)
    accepted: list[bytes | None] = []
    rs_fail = 0
    crc_fail = 0
    for codeword in matrix:
        try:
            message = bytes(rsc.decode(bytes(codeword))[0])
        except (ReedSolomonError, Exception):
            message = None
            rs_fail += 1
        if message is None:
            accepted.append(None)
            continue
        ok, data = ib.accept_message(message)
        if not ok:
            accepted.append(None)
            crc_fail += 1
        else:
            accepted.append(data)
    payload, header = ib.reassemble(accepted, RS_K)
    return (payload or b""), {
        "codewords_total": CODEWORDS_PER_STRIPE,
        "codewords_accepted": sum(part is not None for part in accepted),
        "rs_failures": rs_fail,
        "crc_failures": crc_fail,
        "inband_header": header,
    }


def _pack_payload(payload_path: pathlib.Path) -> tuple[bytes, bytes, dict]:
    raw = payload_path.read_bytes()
    # Use the repo's lzma bridge when this pyenv lacks _lzma; otherwise H9 auto
    # silently falls back to gzip and wastes ~42 KB / one extra stripe.
    packed, pack_meta = pack_h9_lzma(raw)
    if unpack_h9_lzma(packed) != raw:
        raise AssertionError("H9 payload pack/unpack failed")
    return raw, packed, pack_meta


def _codec_selfcheck(packed: bytes) -> dict:
    """Fast all-data check: every stripe through CIB1/RS/interleave and back."""
    stripes = _stripe_split(packed)
    recovered_channels = []
    n_stripes = math.ceil(max(map(len, stripes)) / STRIPE_USER_BYTES)
    for channel_blob in stripes:
        recovered = bytearray()
        for stripe_index in range(n_stripes):
            start = stripe_index * STRIPE_USER_BYTES
            chunk = channel_blob[start:start + STRIPE_USER_BYTES]
            frames = _encode_stripe(chunk)
            decoded, diag = _decode_stripe(frames)
            if diag["codewords_accepted"] != CODEWORDS_PER_STRIPE:
                raise AssertionError(f"codec stripe failed: {diag}")
            recovered += decoded[:len(chunk)]
        recovered_channels.append(bytes(recovered[:len(channel_blob)]))
    joined = _stripe_join(recovered_channels[0], recovered_channels[1], len(packed))
    if joined != packed:
        raise AssertionError("all-data stripe codec self-check failed")
    return {"n_stripes": n_stripes, "packed_sha256": _sha(joined)}


def build(payload_path: pathlib.Path = PAYLOAD_PATH,
          out_wav: pathlib.Path = WAV_PATH) -> dict:
    raw, packed, pack_meta = _pack_payload(payload_path)
    codec_check = _codec_selfcheck(packed)
    channel_blobs = _stripe_split(packed)
    n_stripes = codec_check["n_stripes"]
    scheme = P23HybridDPSK(D8_FREQS)
    expected_symbols = 1 + math.ceil(FRAME_CODED_BITS / scheme.bits_per_sym)
    expected_body_samples = len(make_preamble()) + expected_symbols * scheme.N

    manifest = {
        "master_id": MASTER_ID,
        "SR": SR,
        "channels": ["L", "R"],
        "tx_chirp0": None,
        "tx_chirp1": None,
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "sounder_sections": [],
        "payload": {
            "name": "Chess-GPT 4.5M INT4",
            "source_path": str(payload_path.relative_to(ROOT)),
            "original_bytes": len(raw),
            "original_sha256": _sha(raw),
            "packed_bytes": len(packed),
            "packed_sha256": _sha(packed),
            "pack": pack_meta,
            "stereo_stripe": "even bytes on L, odd bytes on R",
            "channel_bytes": [len(channel_blobs[0]), len(channel_blobs[1])],
        },
        "phy": {
            "name": scheme.name,
            "d8_freqs_hz": [int(freq) for freq in D8_FREQS],
            "bits_per_symbol": scheme.bits_per_sym,
            "gross_bps_per_channel": scheme.gross_bps,
            "rs_n": RS_N,
            "rs_k": RS_K,
            "inband_crc_bytes": ib.CRC_BYTES,
            "codewords_per_stripe": CODEWORDS_PER_STRIPE,
            "columns_per_frame": COLUMNS_PER_FRAME,
            "frames_per_stripe": FRAMES_PER_STRIPE,
            "frame_coded_bits": FRAME_CODED_BITS,
            "frame_body_samples": expected_body_samples,
            "frame_gap_samples": FRAME_GAP_SAMPLES,
            "stripe_user_bytes_per_channel": STRIPE_USER_BYTES,
            "rs_backend": RS_BACKEND,
        },
        "n_stripes": n_stripes,
        "channel_stripes": [[], []],
        "frames": [],
    }
    for channel, blob in enumerate(channel_blobs):
        for stripe_index in range(n_stripes):
            start = stripe_index * STRIPE_USER_BYTES
            valid = len(blob[start:start + STRIPE_USER_BYTES])
            manifest["channel_stripes"][channel].append({
                "stripe_index": stripe_index,
                "channel_offset": start,
                "valid_bytes": valid,
            })

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    pos = 0

    def write_pair(handle, left: np.ndarray, right: np.ndarray | None = None):
        nonlocal pos
        left = np.asarray(left, np.float32)
        right = left if right is None else np.asarray(right, np.float32)
        if len(left) != len(right):
            raise AssertionError("stereo frame lengths diverged")
        handle.write(np.column_stack([left, right]))
        pos += len(left)

    with sf.SoundFile(out_wav, "w", samplerate=SR, channels=2,
                      subtype="FLOAT") as wav:
        write_pair(wav, _silence(1.0))
        manifest["tx_chirp0"] = pos
        write_pair(wav, _make_global_chirp(up=True))
        write_pair(wav, _silence(0.40))

        global_frame = 0
        print(f"[build] {MASTER_ID}: {len(raw):,} B raw -> {len(packed):,} B "
              f"{pack_meta['algo']}; {n_stripes} stripes, "
              f"{n_stripes * FRAMES_PER_STRIPE} frames/channel", flush=True)
        for stripe_index in range(n_stripes):
            encoded = []
            for channel, blob in enumerate(channel_blobs):
                start = stripe_index * STRIPE_USER_BYTES
                chunk = blob[start:start + STRIPE_USER_BYTES]
                encoded.append(_encode_stripe(chunk))
            for frame_in_stripe in range(FRAMES_PER_STRIPE):
                start_sample = pos
                audio_l = scheme.modulate(encoded[0][frame_in_stripe])
                audio_r = scheme.modulate(encoded[1][frame_in_stripe])
                write_pair(wav, audio_l, audio_r)
                body_end = pos
                write_pair(wav, _silence(FRAME_GAP_S))
                manifest["frames"].append({
                    "global_frame": global_frame,
                    "stripe_index": stripe_index,
                    "frame_in_stripe": frame_in_stripe,
                    "start_sample": start_sample,
                    "body_end_sample": body_end,
                    "end_sample": pos,
                    "coded_bits": FRAME_CODED_BITS,
                    "body_samples": expected_body_samples,
                })
                global_frame += 1
            print(f"  stripe {stripe_index + 1:02d}/{n_stripes}  "
                  f"t={pos / SR / 60:.2f} min", flush=True)

        write_pair(wav, _silence(0.80))
        manifest["tx_chirp1"] = pos
        write_pair(wav, _make_global_chirp(up=False))
        write_pair(wav, _silence(1.0))

    manifest["duration_seconds"] = pos / SR
    manifest["duration_minutes"] = pos / SR / 60
    manifest["c90_side_margin_seconds"] = 45 * 60 - pos / SR
    manifest["effective_original_bps"] = len(raw) * 8 / (pos / SR)
    manifest["effective_packed_bps"] = len(packed) * 8 / (pos / SR)
    if manifest["c90_side_margin_seconds"] <= 60:
        raise AssertionError("payload master lacks at least one minute C90-side margin")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"[build] wrote {out_wav} ({manifest['duration_minutes']:.2f} min; "
          f"C90-side margin {manifest['c90_side_margin_seconds'] / 60:.2f} min)")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    return manifest


def _locate_frames(mono: np.ndarray, manifest: dict, sync: dict) -> list[int]:
    """Sequential local-preamble acquisition; nominal positions are hints only."""
    preamble_samples = len(make_preamble())
    search_radius = int(0.80 * SR)
    starts = []
    scale = float(np.clip(sync["speed"], 0.92, 1.08))
    for index, frame in enumerate(manifest["frames"]):
        if index == 0:
            predicted = (int(sync["chirp0_meas"]) + int(frame["start_sample"])
                         - int(manifest["tx_chirp0"]))
            radius = int(1.5 * SR)
        else:
            expected_delta = (int(frame["start_sample"])
                              - int(manifest["frames"][index - 1]["start_sample"]))
            predicted = starts[-1] + int(round(expected_delta * scale))
            radius = search_radius
        lo = max(0, predicted - radius)
        hi = min(len(mono), predicted + radius + preamble_samples)
        after = find_preamble(mono[lo:hi])
        detected = max(0, lo + after - preamble_samples)
        if starts:
            expected_delta = (int(frame["start_sample"])
                              - int(manifest["frames"][index - 1]["start_sample"]))
            measured_delta = detected - starts[-1]
            candidate = measured_delta / max(1, expected_delta)
            if 0.90 <= candidate <= 1.10:
                scale = candidate
        starts.append(int(detected))
    return starts


def decode(wav_path: pathlib.Path, *, quick_selfcheck: bool = False) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20_000)
        audio = np.column_stack([
            resample_poly(audio[:, channel], frac.numerator, frac.denominator)
            for channel in range(audio.shape[1])
        ])
    if audio.shape[1] < 2:
        raise ValueError("payload tape requires a stereo capture")
    mono = audio[:, :2].mean(axis=1)
    sync_full = global_sync_and_resample(mono, manifest)
    sync = {key: value for key, value in sync_full.items()
            if key != "audio_nominal"}
    starts = _locate_frames(mono, manifest, sync)
    scheme = P23HybridDPSK(manifest["phy"]["d8_freqs_hz"])

    if quick_selfcheck:
        # File-level modulation gate without spending ~15 minutes demodulating
        # deterministic clean audio: verify first/middle/last frame on both
        # channels.  _codec_selfcheck already covered every payload bit.
        selected = sorted({0, len(starts) // 2, len(starts) - 1})
    else:
        selected = list(range(len(starts)))

    rx_by_channel: list[list[np.ndarray | None]] = [
        [None] * len(starts), [None] * len(starts)]
    frame_rows = []
    for index in selected:
        frame = manifest["frames"][index]
        if index + 1 < len(starts):
            next_detected = starts[index + 1]
            next_expected = int(manifest["frames"][index + 1]["start_sample"])
        else:
            next_detected = int(sync["chirp1_meas"])
            next_expected = int(manifest["tx_chirp1"])
        expected_interval = next_expected - int(frame["start_sample"])
        local_scale = (next_detected - starts[index]) / max(1, expected_interval)
        if not 0.90 <= local_scale <= 1.10:
            local_scale = 1.0
        raw_samples = int(round(int(frame["body_samples"]) * local_scale))
        row = {"frame": index, "local_clock": local_scale, "channels": []}
        for channel in range(2):
            raw = audio[starts[index]:starts[index] + raw_samples, channel]
            window = _resample_exact(raw, int(frame["body_samples"]))
            bits = np.asarray(scheme.demodulate(window, SR), np.uint8)
            bits = bits[:int(frame["coded_bits"])]
            if len(bits) < int(frame["coded_bits"]):
                bits = np.pad(bits, (0, int(frame["coded_bits"]) - len(bits)))
            rx_by_channel[channel][index] = bits
            row["channels"].append({"bits": len(bits)})
        frame_rows.append(row)
        if not quick_selfcheck and (index + 1) % 25 == 0:
            print(f"[decode] frames {index + 1}/{len(starts)}", flush=True)

    if quick_selfcheck:
        # Recreate the exact selected TX bits and compare clean file audio.
        raw_source = (ROOT / manifest["payload"]["source_path"]).read_bytes()
        packed, _ = pack_h9_lzma(raw_source)
        blobs = _stripe_split(packed)
        for index in selected:
            frame = manifest["frames"][index]
            stripe_index = int(frame["stripe_index"])
            frame_in_stripe = int(frame["frame_in_stripe"])
            for channel in range(2):
                start = stripe_index * STRIPE_USER_BYTES
                tx = _encode_stripe(blobs[channel][start:start + STRIPE_USER_BYTES])[
                    frame_in_stripe]
                if not np.array_equal(tx, rx_by_channel[channel][index]):
                    raise AssertionError(
                        f"clean audio spot-check failed frame {index} channel {channel}")
        result = {
            "mode": "quick_selfcheck",
            "wav": str(wav_path),
            "selected_frames": selected,
            "audio_spotcheck_exact": True,
            "all_data_codec_exact": True,
        }
    else:
        recovered_channels = []
        stripe_diagnostics = [[], []]
        for channel in range(2):
            assembled = bytearray()
            for stripe_index in range(int(manifest["n_stripes"])):
                first = stripe_index * FRAMES_PER_STRIPE
                frames = [
                    (rx_by_channel[channel][first + offset]
                     if rx_by_channel[channel][first + offset] is not None
                     else np.zeros(FRAME_CODED_BITS, np.uint8))
                    for offset in range(FRAMES_PER_STRIPE)
                ]
                stripe, diag = _decode_stripe(frames)
                valid = int(manifest["channel_stripes"][channel][stripe_index]
                            ["valid_bytes"])
                assembled += stripe[:valid]
                stripe_diagnostics[channel].append(diag)
            expected_len = int(manifest["payload"]["channel_bytes"][channel])
            recovered_channels.append(bytes(assembled[:expected_len]))
        packed = _stripe_join(recovered_channels[0], recovered_channels[1],
                              int(manifest["payload"]["packed_bytes"]))
        packed_match = _sha(packed) == manifest["payload"]["packed_sha256"]
        try:
            original = unpack_h9_lzma(packed)
        except Exception as exc:
            original = b""
            unpack_error = repr(exc)
        else:
            unpack_error = None
        original_match = (_sha(original) == manifest["payload"]["original_sha256"]
                          and len(original) == manifest["payload"]["original_bytes"])
        if original_match:
            RECOVERED_DIR.mkdir(parents=True, exist_ok=True)
            RECOVERED_PATH.write_bytes(original)
        result = {
            "mode": "physical_decode",
            "wav": str(wav_path),
            "sync": sync,
            "frames_detected": len(starts),
            "packed_sha256_match": packed_match,
            "original_sha256_match": original_match,
            "byte_exact": original_match,
            "unpack_error": unpack_error,
            "recovered_path": str(RECOVERED_PATH) if original_match else None,
            "stripe_diagnostics": stripe_diagnostics,
            "frame_diagnostics": frame_rows,
        }
        accepted = [sum(d["codewords_accepted"] for d in channel)
                    for channel in stripe_diagnostics]
        total = int(manifest["n_stripes"]) * CODEWORDS_PER_STRIPE
        print(f"[decode] codewords accepted L={accepted[0]}/{total} "
              f"R={accepted[1]}/{total}")
        print(f"[decode] packed hash={'MATCH' if packed_match else 'FAIL'}; "
              f"original Chess-GPT={'BYTE-EXACT' if original_match else 'FAIL'}")
        if original_match:
            print(f"[decode] wrote {RECOVERED_PATH}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = "quick_selfcheck" if quick_selfcheck else wav_path.stem
    out = RESULTS_DIR / f"wired_hybrid_payload_{tag}.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"[decode] wrote {out}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--quick-selfcheck", action="store_true")
    parser.add_argument("--decode", type=pathlib.Path)
    parser.add_argument("--payload", type=pathlib.Path, default=PAYLOAD_PATH)
    parser.add_argument("--out", type=pathlib.Path, default=WAV_PATH)
    args = parser.parse_args()
    if not args.build and args.decode is None:
        parser.error("choose --build or --decode CAPTURE.wav")
    if args.build:
        build(args.payload, args.out)
        if args.quick_selfcheck:
            decode(args.out, quick_selfcheck=True)
    elif args.decode is not None:
        decode(args.decode, quick_selfcheck=args.quick_selfcheck)
