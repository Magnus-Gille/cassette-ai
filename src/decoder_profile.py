from __future__ import annotations

import time

from cassette_format import decode_audio, encode_audio, tape_seconds_for_payload, cassette_payload
from common import DATA, ensure_dirs, write_csv


PROFILE_SIZES = [4_096, 16_384, 65_536]
ROUNDS = 5
PI5_SLOWDOWN_FACTOR = 2.75


def profile() -> list[dict]:
    rows = []
    for size in PROFILE_SIZES:
        payload = cassette_payload("decoder-profile-v3", size)
        audio = encode_audio(payload)
        tape_seconds = len(audio) / 48_000

        result = decode_audio(audio)
        if not result.complete or result.payload != payload:
            raise RuntimeError(f"clean roundtrip failed for {size} bytes: {result.errors}")

        timings = []
        for _ in range(ROUNDS):
            start = time.perf_counter()
            result = decode_audio(audio)
            elapsed = time.perf_counter() - start
            if result.payload != payload:
                raise RuntimeError(f"profile decode mismatch for {size} bytes")
            timings.append(elapsed)

        best = min(timings)
        median = sorted(timings)[len(timings) // 2]
        laptop_sec_per_tape_sec = median / tape_seconds
        rows.append(
            {
                "payload_bytes": size,
                "tape_audio_seconds": f"{tape_seconds:.3f}",
                "format_estimated_tape_seconds": f"{tape_seconds_for_payload(size):.3f}",
                "decode_rounds": ROUNDS,
                "laptop_best_decode_seconds": f"{best:.6f}",
                "laptop_median_decode_seconds": f"{median:.6f}",
                "laptop_seconds_per_second_audio": f"{laptop_sec_per_tape_sec:.6f}",
                "pi5_class_seconds_per_second_audio": f"{laptop_sec_per_tape_sec * PI5_SLOWDOWN_FACTOR:.6f}",
                "pi5_slowdown_factor": PI5_SLOWDOWN_FACTOR,
                "clean_roundtrip_bit_identical": True,
            }
        )
    return rows


def run() -> None:
    ensure_dirs()
    write_csv(DATA / "decoder_profile.csv", profile())


if __name__ == "__main__":
    run()
