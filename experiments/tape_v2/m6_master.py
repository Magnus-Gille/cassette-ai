"""m6_master.py -- assemble master6.wav: WS turbo-geometry ladder.

master4 proved the safe acoustic PHY:
    WS_M16_K1_sp3_N256 + RS(255,111) -> real tape byte-exact at ~326 bps.

master5 tests the same PHY with lighter RS rates. That can reclaim FEC overhead,
but it cannot beat the gross PHY rate (750 bps). This master tests a geometry
change intended to beat that class:

    WS_M32_K2_sp2_N320

It carries 8 bits/symbol at 320 samples/symbol -> 1200 gross bps. In the faithful
sim it is not safe at full pessimistic contamination, but it becomes clean once
contamination is 0.8x or lower. tape4's measured real BER was far gentler than the
sim, so this belongs on the next physical cassette as a stretch ladder.

Rungs:
  - one M16 control at RS(255,223), matching master5's fastest current-class rung.
  - M32K2 turbo rungs at RS(255,95/111/127/159/191).

Run:
    python3 experiments/tape_v2/m6_master.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
from assault_widespace import build as ws_build  # noqa: E402
from make_master2 import (  # noqa: E402
    GLOBAL_CHIRP_T,
    _build_sounder,
    _make_global_chirp,
    _silence,
)

SR = codec.FS
CASS = codec.CASS

OUT_DIR = _HERE
SIDECAR_DIR = OUT_DIR / "sidecars_m6"
WAV_PATH = OUT_DIR / "master6.wav"
MANIFEST_PATH = OUT_DIR / "master6_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
FRAME_BYTES = 510
RS_N = 255

RUNGS = [
    {
        "name": "m16_control_rs223_8k",
        "phy": {"M": 16, "K": 1, "spacing": 3, "N": 256},
        "rs_k": 223,
        "offset": 0,
        "payload_bytes": 8192,
        "role": "control-fastest-current-class",
    },
    {
        "name": "m32_turbo_rs95_4k",
        "phy": {"M": 32, "K": 2, "spacing": 2, "N": 320},
        "rs_k": 95,
        "offset": 8192,
        "payload_bytes": 4096,
        "role": "turbo-safe-if-real-channel<=0.8x-sim",
    },
    {
        "name": "m32_turbo_rs111_4k",
        "phy": {"M": 32, "K": 2, "spacing": 2, "N": 320},
        "rs_k": 111,
        "offset": 12288,
        "payload_bytes": 4096,
        "role": "turbo-moderate",
    },
    {
        "name": "m32_turbo_rs127_4k",
        "phy": {"M": 32, "K": 2, "spacing": 2, "N": 320},
        "rs_k": 127,
        "offset": 16384,
        "payload_bytes": 4096,
        "role": "turbo-fast",
    },
    {
        "name": "m32_turbo_rs159_4k",
        "phy": {"M": 32, "K": 2, "spacing": 2, "N": 320},
        "rs_k": 159,
        "offset": 20480,
        "payload_bytes": 4096,
        "role": "turbo-beats-m16-rs223-if-it-passes",
    },
    {
        "name": "m32_turbo_rs191_4k",
        "phy": {"M": 32, "K": 2, "spacing": 2, "N": 320},
        "rs_k": 191,
        "offset": 24576,
        "payload_bytes": 4096,
        "role": "turbo-stretch",
    },
]


def _gross_bps(ws) -> float:
    return ws.bits_per_sym * SR / ws.N


def build() -> str:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    full = CASS.read_bytes()
    assert len(full) == 153823, f"unexpected cassette-LLM size {len(full)}"

    parts: list[np.ndarray] = []
    pos = 0

    def add_raw(sig: np.ndarray) -> None:
        nonlocal pos
        sig = np.asarray(sig, dtype=np.float32)
        parts.append(sig)
        pos += len(sig)

    def add_gap(d: float = GAP_S) -> None:
        add_raw(_silence(d))

    manifest: dict = {
        "SR": SR,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "ws_payloads": [],
    }

    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    for spec in RUNGS:
        phy = spec["phy"]
        ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
        assert ws is not None, spec

        payload = full[spec["offset"] : spec["offset"] + spec["payload_bytes"]]
        assert len(payload) == spec["payload_bytes"], spec
        sidecar = SIDECAR_DIR / f"{spec['name']}.bin"
        sidecar.write_bytes(payload)

        rung = Rung(
            name=spec["name"],
            M=phy["M"],
            K=phy["K"],
            rs_n=RS_N,
            rs_k=spec["rs_k"],
            frame_bytes=FRAME_BYTES,
        )
        frames_bits, meta = codec.encode_payload(payload, rung)

        frame_starts: list[int] = []
        for fbits in frames_bits:
            audio = np.asarray(ws.modulate(fbits.astype(np.uint8)), dtype=np.float32)
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(FRAME_GAP_S))
        add_gap()

        gross = _gross_bps(ws)
        manifest["ws_payloads"].append({
            "name": spec["name"],
            "scheme": "widespace",
            "phy": ws.name,
            "phy_params": phy,
            "role": spec["role"],
            "gross_bps": gross,
            "projected_net_bps": gross * spec["rs_k"] / RS_N,
            "payload_sidecar": str(sidecar.relative_to(OUT_DIR)),
            "payload_len": len(payload),
            "llm_offset": spec["offset"],
            "meta": meta,
            "frame_starts": frame_starts,
        })

        print(
            f"[build] {spec['name']:24s} {ws.name:18s} "
            f"RS({RS_N},{spec['rs_k']:3d}) gross={gross:6.1f} "
            f"net={gross * spec['rs_k'] / RS_N:6.1f} "
            f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d}"
        )

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

    print(f"[build] master6.wav {dur_s:.1f}s ({dur_s / 60:.2f} min), peak 0.95")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    return (
        f"master6.wav {dur_s:.1f}s ({dur_s / 60:.2f} min), "
        f"{len(manifest['ws_payloads'])} WS rungs"
    )


if __name__ == "__main__":
    print(build())
