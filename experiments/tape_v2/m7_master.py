"""m7_master.py -- assemble master7.wav: the MERGED master5 + master6 ladder.

One physical recording, one global sync (chirps + sounder), all rungs from both
challengers so a SINGLE tape capture decodes everything at once:

  * master5 class -- WS_M16_K1_sp3_N256 RS-rate ladder (the proven safe PHY,
    lighter RS to reclaim FEC overhead): RS(255,111/159/191/223).
  * master6 class -- WS_M32_K2_sp2_N320 turbo-geometry ladder (8 bits/sym,
    1200 gross bps) + the M16 RS(255,223) control: RS(255,95/111/127/159/191).

Every section carries its own `phy_params` (the master6 manifest convention), so
the per-rung decoder (m7_decode, which reuses m6_decode._decode_section) builds
the right WS geometry for each rung. Reuses make_master2's chirp/sounder layout
and m3_codec's RS + global-interleave framing, identical to m5/m6.

Run:
    python3 experiments/tape_v2/m7_master.py
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
SIDECAR_DIR = OUT_DIR / "sidecars_m7"
WAV_PATH = OUT_DIR / "master7.wav"
MANIFEST_PATH = OUT_DIR / "master7_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
RS_N = 255

_M16 = {"M": 16, "K": 1, "spacing": 3, "N": 256}   # proven safe PHY (master4/5)
_M32 = {"M": 32, "K": 2, "spacing": 2, "N": 320}   # turbo geometry (master6)

# Merged ladder. `source` tags which challenger a rung comes from. Payload offsets
# pull distinct slices of the real cassette-LLM so no two rungs carry identical
# bytes (keeps each rung an independent byte-exact test).
RUNGS = [
    # --- master5 class: WS_M16, RS-rate ladder (8 KB each, frame_bytes 510) ---
    {"name": "m16_rs111_8k", "phy": _M16, "rs_k": 111, "offset": 0,     "payload_bytes": 8192, "frame_bytes": 510, "source": "m5", "role": "m16-anchor"},
    {"name": "m16_rs159_8k", "phy": _M16, "rs_k": 159, "offset": 8192,  "payload_bytes": 8192, "frame_bytes": 510, "source": "m5", "role": "m16-moderate"},
    {"name": "m16_rs191_8k", "phy": _M16, "rs_k": 191, "offset": 16384, "payload_bytes": 8192, "frame_bytes": 510, "source": "m5", "role": "m16-target"},
    {"name": "m16_rs223_8k", "phy": _M16, "rs_k": 223, "offset": 24576, "payload_bytes": 8192, "frame_bytes": 510, "source": "m5", "role": "m16-stretch"},
    # --- master6 class: WS_M32 turbo geometry (4 KB each, frame_bytes 510) ---
    {"name": "m32_rs95_4k",  "phy": _M32, "rs_k": 95,  "offset": 32768, "payload_bytes": 4096, "frame_bytes": 510, "source": "m6", "role": "turbo-safe"},
    {"name": "m32_rs111_4k", "phy": _M32, "rs_k": 111, "offset": 36864, "payload_bytes": 4096, "frame_bytes": 510, "source": "m6", "role": "turbo-moderate"},
    {"name": "m32_rs127_4k", "phy": _M32, "rs_k": 127, "offset": 40960, "payload_bytes": 4096, "frame_bytes": 510, "source": "m6", "role": "turbo-fast"},
    {"name": "m32_rs159_4k", "phy": _M32, "rs_k": 159, "offset": 45056, "payload_bytes": 4096, "frame_bytes": 510, "source": "m6", "role": "turbo-beats-m16-rs223"},
    {"name": "m32_rs191_4k", "phy": _M32, "rs_k": 191, "offset": 49152, "payload_bytes": 4096, "frame_bytes": 510, "source": "m6", "role": "turbo-hero-stretch"},
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

        payload = full[spec["offset"]: spec["offset"] + spec["payload_bytes"]]
        assert len(payload) == spec["payload_bytes"], spec
        sidecar = SIDECAR_DIR / f"{spec['name']}.bin"
        sidecar.write_bytes(payload)

        rung = Rung(
            name=spec["name"],
            M=phy["M"],
            K=phy["K"],
            rs_n=RS_N,
            rs_k=spec["rs_k"],
            frame_bytes=spec["frame_bytes"],
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
            "source": spec["source"],
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
            f"[build] {spec['name']:16s} {ws.name:18s} "
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

    print(f"[build] master7.wav {dur_s:.1f}s ({dur_s / 60:.2f} min), peak 0.95")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    return (
        f"master7.wav {dur_s:.1f}s ({dur_s / 60:.2f} min), "
        f"{len(manifest['ws_payloads'])} rungs "
        f"({sum(1 for r in RUNGS if r['source']=='m5')} M16 + "
        f"{sum(1 for r in RUNGS if r['source']=='m6')} M32)"
    )


if __name__ == "__main__":
    print(build())
