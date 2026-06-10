"""m8_master.py -- assemble master8.wav: the overnight-campaign deliverable tape.

ONE physical recording, ONE global sync (chirp pair + front sounder), 9 rungs
spanning three proven/sim-validated PHY families, robust early -> stretch late:

  1. m8_ctrl_m16k1_rs191   WS_M16_K1_sp3_N256  RS(255,191)  -- real-proven control 561.8
  2. m8_m32k2_rs127        WS_M32_K2_sp2_N320  RS(255,127)  -- real-proven 597.6 (combo)
  3. m8_m32k2_rs159        WS_M32_K2_sp2_N320  RS(255,159)  -- real-proven 748.2 (combo)
  4. m8_m16k2_rs159        WS_M16_K2_sp3_N256  RS(255,159)  -- sim 701.5
  5. m8_m16k2_rs191        WS_M16_K2_sp3_N256  RS(255,191)  -- sim 842.6
  6. m8_dq_p10n1024_rs159  DQPSK P10 N1024     RS(255,159)  -- sim 584.6 stress-proof
  7. m8_dq_p10n1024_rs223  DQPSK P10 N1024     RS(255,223)  -- sim 819.9 target
  8. m8_dq_p10n512_rs127   DQPSK P10 N512      RS(255,127)  -- sim 933.8 stretch
  9. m8_m16k3_rs159        WS_M16_K3_sp3_N256  RS(255,159)  -- sim 1052.2 lottery

Architecture follows m7 EXACTLY where possible (proven on real tape7):
  * global chirp0 (up) -> front Schroeder sounder -> sections -> chirp1 (down).
  * each WS section carries its own `phy_params`; m8_decode reuses
    m6_decode._decode_section for the WS-M16 family, and the H6 combo path
    (h5.SectionEngine timing-trajectory bw 0.25 Hz + errors-and-erasures) for
    the WS-M32 sections, exactly as the real-tape wins were obtained.
  * DQPSK sections are structurally identical (a train of per-frame-preamble
    frames); they carry `dqpsk_params` and decode via h4_dqpsk.DQPSKScheme.demod
    (self-referencing pilot; no per-section sounder needed in the merge).

PAYLOAD: every rung carries an H9-PACKED slice of stories260K_int4.cass at a
staggered offset (so rungs decode different parts). pack_payload(algo='auto');
this interpreter LACKS lzma, so gzip is used and recorded in the manifest. The
manifest records orig+packed lengths and sha256 of both. The RS frame format is
UNCHANGED from m6 (zero tape-format risk); the receiver-side miscorrection guard
for the WS-M32 combo decode is a CRC32-per-RS-codeword table in the manifest
(decoder checks decoded codeword messages against it -- receiver-side, no truth).

Run:
    python3 experiments/tape_v2/m8_master.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import zlib

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
from h4_dqpsk import DQPSKScheme  # noqa: E402
from h9_payload_codec import pack_payload, unpack_payload  # noqa: E402
from make_master2 import (  # noqa: E402
    GLOBAL_CHIRP_T,
    _build_sounder,
    _make_global_chirp,
    _silence,
)
from reedsolo import RSCodec  # noqa: E402

SR = codec.FS
CASS = codec.CASS

OUT_DIR = _HERE
SIDECAR_DIR = OUT_DIR / "sidecars_m8"
WAV_PATH = OUT_DIR / "master8.wav"
MANIFEST_PATH = OUT_DIR / "master8_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
RS_N = 255
FRAME_BYTES = 510

_M16K1 = {"M": 16, "K": 1, "spacing": 3, "N": 256}
_M32K2 = {"M": 32, "K": 2, "spacing": 2, "N": 320}
_M16K2 = {"M": 16, "K": 2, "spacing": 3, "N": 256}
_M16K3 = {"M": 16, "K": 3, "spacing": 3, "N": 256}

# 9-rung ladder. `kind` selects build/decode path: "ws" or "dqpsk".
# `combo` flags the WS-M32 sections that ALSO get the H6 combo decode path.
# Payload sizes (orig bytes) are staggered offsets into the cassette-LLM so no
# two rungs carry the same bytes. The H9-PACKED blob (gzip here) is what gets
# RS-encoded + modulated; orig sizes chosen to keep total tape <= ~16 min.
RUNGS = [
    {"name": "m8_ctrl_m16k1_rs191", "kind": "ws", "phy": _M16K1, "rs_k": 191,
     "offset": 0,      "orig_bytes": 6144, "combo": False,
     "role": "control-real-proven-561.8"},
    {"name": "m8_m32k2_rs127", "kind": "ws", "phy": _M32K2, "rs_k": 127,
     "offset": 6144,   "orig_bytes": 4096, "combo": True,
     "role": "turbo-real-proven-597.6-combo"},
    {"name": "m8_m32k2_rs159", "kind": "ws", "phy": _M32K2, "rs_k": 159,
     "offset": 10240,  "orig_bytes": 6144, "combo": True,
     "role": "turbo-real-proven-748.2-combo"},
    {"name": "m8_m16k2_rs159", "kind": "ws", "phy": _M16K2, "rs_k": 159,
     "offset": 16384,  "orig_bytes": 6144, "combo": False,
     "role": "m16k2-sim-701.5"},
    {"name": "m8_m16k2_rs191", "kind": "ws", "phy": _M16K2, "rs_k": 191,
     "offset": 22528,  "orig_bytes": 6144, "combo": False,
     "role": "m16k2-sim-842.6"},
    {"name": "m8_dq_p10n1024_rs159", "kind": "dqpsk",
     "dqpsk": {"P": 10, "N": 1024, "spacing": 16}, "rs_k": 159,
     "offset": 28672,  "orig_bytes": 6144, "combo": False,
     "role": "dqpsk-sim-584.6-stress-proof"},
    {"name": "m8_dq_p10n1024_rs223", "kind": "dqpsk",
     "dqpsk": {"P": 10, "N": 1024, "spacing": 16}, "rs_k": 223,
     "offset": 34816,  "orig_bytes": 8192, "combo": False,
     "role": "dqpsk-sim-819.9-target"},
    {"name": "m8_dq_p10n512_rs127", "kind": "dqpsk",
     "dqpsk": {"P": 10, "N": 512, "spacing": 8}, "rs_k": 127,
     "offset": 43008,  "orig_bytes": 8192, "combo": False,
     "role": "dqpsk-sim-933.8-stretch"},
    {"name": "m8_m16k3_rs159", "kind": "ws", "phy": _M16K3, "rs_k": 159,
     "offset": 51200,  "orig_bytes": 6144, "combo": False,
     "role": "m16k3-sim-1052.2-lottery"},
]


def _codeword_crcs(packed: bytes, rs_k: int) -> list[int]:
    """CRC32 of each RS codeword's MESSAGE bytes (rs_k bytes), in the same
    chunk order codec.encode_payload produces. Receiver-side miscorrection
    guard: the decoder compares each RS-decoded codeword message against this
    list -- no truth leak, the message bytes are recoverable by anyone who
    decodes the tape correctly. The CRC just flags a silent RS miscorrection."""
    pad = (-len(packed)) % rs_k
    padded = packed + bytes(pad)
    return [zlib.crc32(padded[i:i + rs_k]) & 0xFFFFFFFF
            for i in range(0, len(padded), rs_k)]


def _gross_bps_ws(ws) -> float:
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
        "tape": "master8",
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "cass_path": str(CASS),
        "cass_sha256": hashlib.sha256(full).hexdigest(),
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
        orig = full[spec["offset"]: spec["offset"] + spec["orig_bytes"]]
        assert len(orig) == spec["orig_bytes"], spec
        packed, pmeta = pack_payload(orig, algo="auto")
        assert unpack_payload(packed) == orig, f"H9 roundtrip failed for {spec['name']}"

        sidecar = SIDECAR_DIR / f"{spec['name']}.bin"   # PACKED blob (RS-encoded)
        sidecar.write_bytes(packed)
        sidecar_orig = SIDECAR_DIR / f"{spec['name']}.orig.bin"
        sidecar_orig.write_bytes(orig)

        if spec["kind"] == "ws":
            phy = spec["phy"]
            ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
            assert ws is not None, spec
            rung = Rung(name=spec["name"], M=phy["M"], K=phy["K"],
                        rs_n=RS_N, rs_k=spec["rs_k"], frame_bytes=FRAME_BYTES)
            frames_bits, meta = codec.encode_payload(packed, rung)
            frame_starts: list[int] = []
            for fbits in frames_bits:
                audio = np.asarray(ws.modulate(fbits.astype(np.uint8)), dtype=np.float32)
                frame_starts.append(pos)
                add_raw(audio)
                add_raw(_silence(FRAME_GAP_S))
            add_gap()
            gross = _gross_bps_ws(ws)
            phy_name = ws.name
            extra = {"phy_params": phy}
        else:  # dqpsk
            dq = spec["dqpsk"]
            sch = DQPSKScheme(dq["P"], dq["N"], dq["spacing"])
            rung = Rung(name=spec["name"], M=dq["P"], K=1,
                        rs_n=RS_N, rs_k=spec["rs_k"], frame_bytes=FRAME_BYTES)
            frames_bits, meta = codec.encode_payload(packed, rung)
            frame_starts = []
            for fbits in frames_bits:
                audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
                frame_starts.append(pos)
                add_raw(audio)
                add_raw(_silence(FRAME_GAP_S))
            add_gap()
            gross = sch.gross_bps
            phy_name = sch.name
            extra = {"dqpsk_params": dq,
                     "carrier_freqs_hz": [round(float(f), 1) for f in sch.freqs[sch.data_idx]],
                     "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1)}

        net = gross * spec["rs_k"] / RS_N
        eff = net * spec["orig_bytes"] / pmeta["packed_len"]
        entry = {
            "name": spec["name"],
            "kind": spec["kind"],
            "scheme": "widespace" if spec["kind"] == "ws" else "dqpsk",
            "phy": phy_name,
            "role": spec["role"],
            "combo": spec["combo"],
            "gross_bps": gross,
            "projected_net_bps": net,
            "effective_bps": eff,
            "payload_sidecar": str(sidecar.relative_to(OUT_DIR)),       # PACKED
            "payload_orig_sidecar": str(sidecar_orig.relative_to(OUT_DIR)),
            "payload_len": len(packed),                                 # == RS input len
            "llm_offset": spec["offset"],
            "pack": {
                "algo": pmeta["algo"],
                "orig_len": pmeta["orig_len"],
                "packed_len": pmeta["packed_len"],
                "reduction_pct": pmeta["reduction_pct"],
                "sha256_orig": hashlib.sha256(orig).hexdigest(),
                "sha256_packed": hashlib.sha256(packed).hexdigest(),
            },
            "crc32_codewords": _codeword_crcs(packed, spec["rs_k"]),
            "meta": meta,
            "frame_starts": frame_starts,
            **extra,
        }
        manifest["ws_payloads"].append(entry)

        print(
            f"[build] {spec['name']:22s} {phy_name:18s} RS({RS_N},{spec['rs_k']:3d}) "
            f"gross={gross:6.1f} net={net:6.1f} eff={eff:6.1f} "
            f"orig={spec['orig_bytes']} packed={pmeta['packed_len']} "
            f"({pmeta['algo']},-{pmeta['reduction_pct']:.1f}%) "
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

    print(f"[build] master8.wav {dur_s:.1f}s ({dur_s / 60:.2f} min), peak 0.95")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    return (
        f"master8.wav {dur_s:.1f}s ({dur_s / 60:.2f} min), "
        f"{len(manifest['ws_payloads'])} rungs "
        f"({sum(1 for r in RUNGS if r['kind']=='ws')} WS + "
        f"{sum(1 for r in RUNGS if r['kind']=='dqpsk')} DQPSK)"
    )


if __name__ == "__main__":
    print(build())
