"""m5_master.py — assemble master5.wav: a WS rate-ladder calibration tape.

Same PHY as the master4 proven winner (WS_M16_K1_sp3_N256), 4 rungs varying
RS rate only.  master4 measured raw BER 0.46% → RS(255,111) over-coded ~5×.
This ladder locates the actual ceiling:

  Rung  RS(n,k)      t   E[byte-err/cw]   P(byte-exact@0.46%BER)   net bps
  ────  ──────────  ──   ──────────────   ──────────────────────   ───────
  A     RS(255,111)  72   9.2 / 72  = 13%   ≈100%                   ~326
  B     RS(255,159)  48   9.2 / 48  = 19%   ≈100%                   ~434
  C     RS(255,191)  32   9.2 / 32  = 29%   ≈100%                   ~513
  D     RS(255,223)  16   9.2 / 16  = 58%   ~63%  (stretch)         ~594

Each rung carries an 8 KB slice of stories260K_int4.cass at a unique offset
for easy identification.  Total duration: ~11 min.

CSS dropped (failed on real tape in master4; sim→real gap not yet fixed).
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2", ROOT / "experiments" / "capacity",
           _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                       # noqa: E402
from m3_codec import Rung                      # noqa: E402
from assault_widespace import build as ws_build  # noqa: E402
from make_master2 import (                     # noqa: E402
    _make_global_chirp, _build_sounder, _silence, GLOBAL_CHIRP_T,
)

SR = codec.FS
CASS = codec.CASS

OUT_DIR = _HERE
SIDECAR_DIR = OUT_DIR / "sidecars_m5"
WAV_PATH = OUT_DIR / "master5.wav"
MANIFEST_PATH = OUT_DIR / "master5_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
WS_FRAME_GAP_S = 0.12

WS_M, WS_K, WS_SPACING, WS_N = 16, 1, 3, 256

# 4 rungs: same PHY, varying RS rate only
RUNGS = [
    # (name,              rs_k, offset_start, frame_bytes)
    ("ws_rs111_8k",  111, 0,      510),   # anchor  — proven ~326 net bps
    ("ws_rs159_8k",  159, 8192,   510),   # moderate — ~434 net bps
    ("ws_rs191_8k",  191, 16384,  510),   # target   — ~513 net bps
    ("ws_rs223_8k",  223, 24576,  510),   # stretch  — ~594 net bps (~63% success at 0.46% BER)
]
PAYLOAD_BYTES = 8192
RS_N = 255


def build() -> str:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)

    parts: list[np.ndarray] = []
    pos = 0

    def add_raw(sig: np.ndarray):
        nonlocal pos
        sig = np.asarray(sig, dtype=np.float32)
        parts.append(sig)
        pos += len(sig)

    def add_gap(d: float = GAP_S):
        add_raw(_silence(d))

    manifest: dict = {
        "SR": SR,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "ws_phy": {
            "M": WS_M, "K": WS_K, "spacing": WS_SPACING, "N": WS_N,
            "frame_gap_samples": int(WS_FRAME_GAP_S * SR),
        },
        "ws_payloads": [],
    }

    full = CASS.read_bytes()
    assert len(full) == 153823, f"unexpected cassette-LLM size {len(full)}"

    ws = ws_build(WS_M, WS_K, WS_SPACING, WS_N)
    assert ws is not None and ws.name == "WS_M16_K1_sp3_N256", ws

    add_raw(_silence(LEAD))

    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for s in sounder_sections:
        s["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    import dataclasses

    for name, rs_k, offset, frame_bytes in RUNGS:
        payload = full[offset: offset + PAYLOAD_BYTES]
        assert len(payload) == PAYLOAD_BYTES, f"slice out of range at offset {offset}"

        rung = Rung(name=name, M=WS_M, K=WS_K,
                    rs_n=RS_N, rs_k=rs_k, frame_bytes=frame_bytes)
        frames_bits, meta = codec.encode_payload(payload, rung)

        scar = SIDECAR_DIR / f"{name}.bin"
        scar.write_bytes(payload)

        frame_starts: list[int] = []
        for fbits in frames_bits:
            audio = np.asarray(ws.modulate(fbits.astype(np.uint8)), dtype=np.float32)
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(WS_FRAME_GAP_S))

        add_gap()

        manifest["ws_payloads"].append({
            "name": name,
            "scheme": "widespace",
            "phy": ws.name,
            "payload_sidecar": str(scar.relative_to(OUT_DIR)),
            "payload_len": len(payload),
            "llm_offset": offset,
            "meta": meta,
            "frame_starts": frame_starts,
        })

        t = meta["n_codewords"]
        dur_s = sum(
            len(np.asarray(ws.modulate(np.zeros(meta["frame_bits"], np.uint8)), np.float32))
            for _ in range(1)
        ) / SR * meta["n_frames"]  # rough per-frame estimate
        print(f"[build] WS  {name:16s} RS({RS_N},{rs_k:3d}) fb{frame_bytes} "
              f"frames={meta['n_frames']:3d} cw={t:3d} bytes={len(payload)}")

    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()

    add_raw(_silence(TAIL))

    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * 0.95).astype(np.float32)
    dur_s = len(audio_full) / SR

    sf.write(str(WAV_PATH), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"[build] master5.wav {dur_s:.1f}s ({dur_s/60:.2f} min), "
          f"{len(audio_full)} samples, peak 0.95")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    return (f"master5.wav {dur_s:.1f}s ({dur_s/60:.2f} min), "
            f"{len(manifest['ws_payloads'])} WS rungs, "
            f"chirp0={manifest['tx_chirp0']} chirp1={manifest['tx_chirp1']}")


if __name__ == "__main__":
    print(build())
