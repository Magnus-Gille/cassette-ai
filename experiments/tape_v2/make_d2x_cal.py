"""make_d2x_cal.py -- Encode a seeded random payload using the proven d2x r6 config
(Dense2x DQPSK, P=21, RS(255,159), ~4910 net bps) and write a calibration WAV.

Outputs (in experiments/tape_v2/):
    cal_d2x_mono.wav          mono float32 48kHz calibration tape
    cal_d2x_manifest.json     decode manifest (same schema as DOOM ship manifest)
    cal_d2x_payload.bin       raw payload sidecar (NO lzma -- raw bytes)

Prints: payload bytes, WAV duration (s), net bps.

Run:
    python3 experiments/tape_v2/make_d2x_cal.py
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

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

# Import the proven build_tape assembler from the DOOM ship pipeline
from m10doom3_master import build_tape  # noqa: E402

# ---- output paths (all relative to TAPE_V2 for the manifest sidecar field) --
WAV_PATH = TAPE_V2 / "cal_d2x_mono.wav"
MANIFEST_PATH = TAPE_V2 / "cal_d2x_manifest.json"
SIDECAR_PATH = TAPE_V2 / "cal_d2x_payload.bin"

# payload_sidecar in the manifest must be relative to tape_v2 (that's what
# _decode_section resolves it against: _HERE / sec["payload_sidecar"])
SIDECAR_REL = "cal_d2x_payload.bin"

# ---- calibration payload: 150 000 seeded random bytes -----------------------
PAYLOAD_BYTES = 150_000
SEED = 1234

# FRAME_BYTES: the DOOM v3 ship uses 10200 (for a 1.5 MB payload). For our
# 150 KB calibration payload we use 5100 -- cited in the docstring as feasible
# (4575 bps on packed bytes) and smaller frames give more re-syncs.
FRAME_BYTES = 5100

TAPE_ID = "cal_d2x"
SECTION_NAME = "cal_d2x_r6"


def main():
    import warnings
    warnings.filterwarnings("ignore")

    rng = np.random.default_rng(SEED)
    payload = bytes(rng.integers(0, 256, size=PAYLOAD_BYTES, dtype=np.uint8))
    print(f"[make_d2x_cal] payload  {PAYLOAD_BYTES} raw bytes (seed {SEED})")

    res = build_tape(
        payload,
        out_wav=WAV_PATH,
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        payload_sidecar_rel=SIDECAR_REL,
        section_name=SECTION_NAME,
        frame_bytes=FRAME_BYTES,
        tape_id=TAPE_ID,
        role="calibration-raw-payload",
        verbose=True,
    )

    dur = res["wav_seconds"]
    net = res["net_bps"]
    print(f"[make_d2x_cal] WAV      {WAV_PATH.name}: {dur:.1f} s ({dur / 60:.2f} min)")
    print(f"[make_d2x_cal] net bps  {net:.1f} bps")
    print(f"[make_d2x_cal] manifest {MANIFEST_PATH.name}")
    print(f"[make_d2x_cal] sidecar  {SIDECAR_PATH.name} ({len(payload)} B)")


if __name__ == "__main__":
    main()
