"""x10_b_aggr_03_toneplan_v2_master.py — assemble x10_master10.wav (B-aggr-03).

m9_master.py pattern, byte-for-byte where possible: ONE physical recording, ONE
global sync (chirp pair + front Schroeder sounder), then the 6-rung x10 ladder
(x10_b_aggr_03_toneplan_v2_scheme.X10_LADDER), robust-early -> stretch-late:

  x0  anchor  m8_dense375 VERBATIM  (must reprove 2572 or the tape pass is void)
  x1a banker  channel-mapped P11 N256, pilot on the 4500 Hz notch        2895.6
  x1b banker  second payload realization                                  2895.6
  x2a stretch P12 N256 to 10500 Hz                                        3158.8
  x2b stretch second payload realization                                  3158.8
  x3  pvar    pilot at 6000 Hz (notch-migration insurance)                2895.6

RECORD CONVENTION (pre-registered BEFORE mastering, x10 pregate JSON s\"prereg\"):
manifest-sidecar per-codeword CRC32 — the same convention the standing 2572
record was set under; net-bps figures stay comparable and every ship-gate record
claim inherits the sidecar caveat (no in-stream per-cw CRC, no rate charge).

Each rung: h9-PACKED slice of stories260K_int4.cass at a staggered offset,
RS(255,k) m3_codec framing, 0.25 s chirp preamble + 0.12 s gap per frame,
CRC32-per-codeword table in the manifest (miscorrection guard).

No P1/P2 probes this time (tape9 already gathered the null-map / jitter / IMD
ramps; the front sounder alone carries the decode-time notch re-derivation).

Run:
    python3 experiments/tape_v2/x10_b_aggr_03_toneplan_v2_master.py \
        [--out x10_master10_draft.wav]

Outputs: x10_master10[_draft].wav, x10_master10_manifest.json, x10_sidecars/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import zlib

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
import h9_payload_codec as h9  # noqa: E402
from h9_payload_codec import unpack_payload  # noqa: E402
from make_master2 import (  # noqa: E402
    GLOBAL_CHIRP_T, _build_sounder, _make_global_chirp, _silence,
)
from x10_b_aggr_03_toneplan_v2_scheme import (  # noqa: E402
    X10_LADDER, LADDER_SEED, make_scheme_x10,
)

SR = codec.FS
assert SR == 48_000
CASS = codec.CASS

OUT_DIR = _HERE
SIDECAR_DIR = OUT_DIR / "x10_sidecars"
WAV_PATH = OUT_DIR / "x10_master10.wav"
MANIFEST_PATH = OUT_DIR / "x10_master10_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
RS_N = 255
FRAME_BYTES = 510


def pack_payload_deterministic(raw: bytes) -> tuple[bytes, dict]:
    """h9-container gzip pack with mtime=0 — BIT-DETERMINISTIC across builds.

    h9_payload_codec.pack_payload uses gzip.compress, which embeds the wall
    clock in the gzip header: two builds of the same master produce different
    packed bytes -> different tape audio + manifest CRCs. A rebuilt WAV would
    then silently mismatch an already-recorded tape. This wrapper produces the
    SAME H9PC container (unpack_payload round-trips it, asserted at every call
    site) from a deterministic gzip stream (mtime=0). Stored fallback if gzip
    does not help, mirroring h9 'auto'.
    """
    import gzip
    import io
    import struct

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as g:
        g.write(raw)
    body = buf.getvalue()
    algo_id = h9.ALGO_GZIP
    if len(body) >= len(raw):
        body, algo_id = raw, h9.ALGO_STORED
    header = struct.pack(h9.HEADER_FMT, h9.MAGIC, h9.VERSION, algo_id, 0,
                         len(raw), zlib.crc32(raw) & 0xFFFFFFFF)
    blob = header + body
    meta = {
        "orig_len": len(raw),
        "packed_len": len(blob),
        "body_len": len(body),
        "algo": h9.ALGO_NAMES[algo_id],
        "ratio": len(blob) / len(raw) if raw else 1.0,
        "reduction_pct": 100.0 * (1 - len(blob) / len(raw)) if raw else 0.0,
    }
    return blob, meta


def _codeword_crcs(packed: bytes, rs_k: int) -> list[int]:
    """CRC32 of each RS codeword's MESSAGE bytes (m8/m9 pattern)."""
    pad = (-len(packed)) % rs_k
    padded = packed + bytes(pad)
    return [zlib.crc32(padded[i:i + rs_k]) & 0xFFFFFFFF
            for i in range(0, len(padded), rs_k)]


def build(out_wav: pathlib.Path = WAV_PATH) -> str:
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
        "tape": "x10_master10",
        "candidate": "B-aggr-03-toneplan-v2",
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "cass_path": str(CASS),
        "cass_sha256": hashlib.sha256(full).hexdigest(),
        "ladder_seed": LADDER_SEED,
        "record_convention": ("manifest-sidecar per-codeword CRC32 (m8/m9 convention; "
                              "record claims inherit the sidecar caveat)"),
        "ws_payloads": [],
    }

    # ---- lead + global up-chirp ----
    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (decode-time notch re-derivation anchor) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # ---- rungs ----
    for rung in X10_LADDER:
        rung_start_pos = pos
        sch = make_scheme_x10(rung)
        orig = full[rung["offset"]: rung["offset"] + rung["orig_bytes"]]
        assert len(orig) == rung["orig_bytes"], rung
        packed, pmeta = pack_payload_deterministic(orig)
        assert unpack_payload(packed) == orig, f"H9 roundtrip failed for {rung['name']}"

        sidecar = SIDECAR_DIR / f"{rung['name']}.bin"
        sidecar.write_bytes(packed)
        sidecar_orig = SIDECAR_DIR / f"{rung['name']}.orig.bin"
        sidecar_orig.write_bytes(orig)

        m_rung = Rung(name=rung["name"], M=rung["P"], K=1,
                      rs_n=RS_N, rs_k=rung["rs_k"], frame_bytes=FRAME_BYTES)
        frames_bits, meta = codec.encode_payload(packed, m_rung)
        frame_starts: list[int] = []
        for fbits in frames_bits:
            audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(FRAME_GAP_S))
        add_gap()

        gross = sch.gross_bps
        net = gross * rung["rs_k"] / RS_N
        eff = net * rung["orig_bytes"] / pmeta["packed_len"]

        if rung["kind"] == "dqpsk_mapped":
            dq_params = {"P": rung["P"], "N": rung["N"],
                         "data_bins": rung["data_bins"], "pilot_bin": rung["pilot_bin"]}
        else:
            dq_params = {"P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
                         "min_spacing_hz": rung.get("min_spacing_hz", 562.0),
                         "drop_freqs_hz": [], "pilot_hz": rung["pilot_hz"]}

        entry = {
            "name": rung["name"],
            "kind": rung["kind"],
            "scheme": sch.name,
            "phy": sch.name,
            "role": rung.get("role", ""),
            "status": rung.get("status", "ACTIVE"),
            "risk": rung.get("risk", ""),
            "gross_bps": gross,
            "projected_net_bps": net,
            "x_record": rung.get("x_record"),
            "effective_bps": eff,
            "payload_sidecar": str(sidecar.relative_to(OUT_DIR)),
            "payload_orig_sidecar": str(sidecar_orig.relative_to(OUT_DIR)),
            "payload_len": len(packed),
            "llm_offset": rung["offset"],
            "pack": {
                "algo": pmeta["algo"],
                "orig_len": pmeta["orig_len"],
                "packed_len": pmeta["packed_len"],
                "reduction_pct": pmeta["reduction_pct"],
                "sha256_orig": hashlib.sha256(orig).hexdigest(),
                "sha256_packed": hashlib.sha256(packed).hexdigest(),
            },
            "crc32_codewords": _codeword_crcs(packed, rung["rs_k"]),
            "meta": meta,
            "frame_starts": frame_starts,
            "dqpsk_params": dq_params,
            "carrier_freqs_hz": [round(float(f), 1) for f in sch.freqs[sch.data_idx]],
            "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1),
        }
        manifest["ws_payloads"].append(entry)
        sec_s = (pos - rung_start_pos) / SR

        print(f"[build] {rung['name']:<24} {sch.name:<18} RS({RS_N},{rung['rs_k']:3d}) "
              f"gross={gross:6.1f} net={net:6.1f} "
              f"packed={pmeta['packed_len']} ({pmeta['algo']},-{pmeta['reduction_pct']:.1f}%) "
              f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
              f"sec={sec_s:5.1f}s [{rung.get('status', 'ACTIVE')}]")

    # ---- global down-chirp + tail ----
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()
    add_raw(_silence(TAIL))

    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * 0.70).astype(np.float32)  # SOP peak 0.70
    dur_s = len(audio_full) / SR

    sf.write(str(out_wav), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"\n[build] {out_wav.name} {dur_s:.1f}s ({dur_s / 60:.2f} min), peak 0.70")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    return f"{out_wav.name} {dur_s:.1f}s ({dur_s / 60:.2f} min), {len(manifest['ws_payloads'])} rungs"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    print(build(pathlib.Path(args.out)))
