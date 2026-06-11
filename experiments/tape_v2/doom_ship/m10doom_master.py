"""m10doom_master.py -- assemble the DOOM ship tape: m10doom_master.wav.

ONE physical recording, ONE payload: the self-contained playable-DOOM HTML
artifact (payloads/doom/dist/doom_cassette.html), encoded at EXACTLY the proven
2572-net-bps master9 rung:

    m9_m8_dense375   DQPSK P22 N512 sp4   RS(255,159)   min_spacing_hz=375
                     gross 4125.0 bps -> net 2572.1 bps

Architecture follows m9_master.py EXACTLY, minus the ladder and the P1/P2
diagnostic probes (this is a ship tape, not an experiment):

    lead 1 s -> global up-chirp -> front Schroeder sounder -> ONE continuous
    payload section (per-frame 0.25 s chirp preamble + 0.12 s gap, h9-PACKED
    payload, RS(255,159)-framed via m3_codec, CRC32-per-codeword manifest
    miscorrection guard) -> global down-chirp -> tail 1 s.

The rung parameters are READ from m9_ladder.json (the m9_m8_dense375 entry) and
the scheme is built through m9_master.make_scheme -- bit-identical modem to the
rung that survived the real master9 tape.

Payload packing: h9_payload_codec H9PC container, algo=auto (lzma preferred).
The default pyenv interpreter on this machine lacks _lzma, so this module
carries a tiny SUBPROCESS BRIDGE to any lzma-capable python (/usr/bin/python3)
producing/consuming the exact same H9PC-lzma blob h9_payload_codec would. The
container on tape is 100% h9-compatible either way.

Run:
    python3 experiments/tape_v2/doom_ship/m10doom_master.py
        [--html PATH] [--out PATH]

Outputs (all in doom_ship/):
    m10doom_master.wav        the ship tape (FLOAT, 48 kHz, peak 0.70 -- SOP)
    m10doom_manifest.json     decode manifest (m9 schema, single section)
    m10doom_dense375.bin      the packed payload sidecar (H9PC blob)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import zlib

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2/doom_ship
TAPE_V2 = _HERE.parent                                    # .../tape_v2
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    TAPE_V2,
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
import h9_payload_codec as h9  # noqa: E402
from m9_master import _codeword_crcs, make_scheme  # noqa: E402
from make_master2 import (  # noqa: E402
    GLOBAL_CHIRP_T,
    _build_sounder,
    _make_global_chirp,
    _silence,
)

SR = codec.FS
assert SR == 48_000

HTML_PATH = ROOT / "payloads" / "doom" / "dist" / "doom_cassette.html"
LADDER_PATH = TAPE_V2 / "m9_ladder.json"
RUNG_NAME = "m9_m8_dense375"          # the proven 2572-bps rung we reuse 1:1
SECTION_NAME = "m10doom_dense375"

WAV_PATH = _HERE / "m10doom_master.wav"
MANIFEST_PATH = _HERE / "m10doom_manifest.json"
SIDECAR_PATH = _HERE / f"{SECTION_NAME}.bin"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
RS_N = 255
FRAME_BYTES = 510
C60_SIDE_BUDGET_MIN = 29.0            # C60 side with margin (HARD gate)


# ===========================================================================
# LZMA bridge: the default pyenv 3.10 here lacks _lzma. h9_payload_codec falls
# back to gzip silently; for the ship tape we WANT the lzma blob (smaller =
# shorter tape), so when the running interpreter lacks lzma we round-trip the
# body bytes through any lzma-capable python on the box. The blob layout is
# byte-identical to h9.pack_payload(algo='lzma'): H9PC header + lzma body
# (preset 9|EXTREME) -- so a future lzma-capable interpreter unpacks it with
# stock h9_payload_codec.unpack_payload, no bridge needed.
# ===========================================================================
_BRIDGE_PY: str | None = None
_SNIP_C = ("import sys,lzma;sys.stdout.buffer.write("
           "lzma.compress(sys.stdin.buffer.read(),preset=9|lzma.PRESET_EXTREME))")
_SNIP_D = ("import sys,lzma;sys.stdout.buffer.write("
           "lzma.decompress(sys.stdin.buffer.read()))")


def _lzma_python() -> str | None:
    """First python on the box that can import lzma (cached); None if none."""
    global _BRIDGE_PY
    if _BRIDGE_PY is not None:
        return _BRIDGE_PY or None
    cands = ["/usr/bin/python3", shutil.which("python3.12") or "",
             shutil.which("python3.11") or "", shutil.which("python3") or ""]
    for c in cands:
        if not c or not pathlib.Path(c).exists():
            continue
        try:
            r = subprocess.run([c, "-c", "import lzma"], capture_output=True,
                               timeout=20)
            if r.returncode == 0:
                _BRIDGE_PY = c
                return c
        except Exception:
            continue
    _BRIDGE_PY = ""
    return None


def _bridge(snippet: str, data: bytes) -> bytes:
    py = _lzma_python()
    if py is None:
        raise RuntimeError("no lzma-capable python found for the bridge")
    r = subprocess.run([py, "-c", snippet], input=data, capture_output=True,
                       timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"lzma bridge failed: {r.stderr[:300]!r}")
    return r.stdout


def pack_doom(raw: bytes) -> tuple[bytes, dict]:
    """h9.pack_payload(algo='auto') semantics WITH lzma always in the running.

    In-process when the interpreter has lzma; bridged otherwise. Falls back to
    h9's own auto choice (gzip/stored) only if no lzma python exists at all.
    """
    if h9._HAVE_LZMA:
        return h9.pack_payload(raw, algo="auto")
    blob_g, meta_g = h9.pack_payload(raw, algo="auto")   # best of gzip/stored
    try:
        body_l = _bridge(_SNIP_C, raw)
    except RuntimeError:
        return blob_g, meta_g
    if len(body_l) + h9.HEADER_LEN >= meta_g["packed_len"]:
        return blob_g, meta_g
    header = struct.pack(h9.HEADER_FMT, h9.MAGIC, h9.VERSION, h9.ALGO_LZMA, 0,
                         len(raw), zlib.crc32(raw) & 0xFFFFFFFF)
    blob = header + body_l
    meta = {
        "orig_len": len(raw),
        "packed_len": len(blob),
        "body_len": len(body_l),
        "algo": "lzma",
        "ratio": len(blob) / len(raw) if raw else 1.0,
        "reduction_pct": 100.0 * (1 - len(blob) / len(raw)) if raw else 0.0,
    }
    return blob, meta


def unpack_doom(blob: bytes) -> bytes:
    """h9.unpack_payload with the lzma bridge as fallback (same checks)."""
    try:
        return h9.unpack_payload(blob)
    except RuntimeError:
        # H9PC-lzma blob on an interpreter without _lzma -> bridge the body.
        magic, version, algo_id, _res, orig_len, crc = struct.unpack(
            h9.HEADER_FMT, blob[:h9.HEADER_LEN])
        assert magic == h9.MAGIC and version == h9.VERSION
        assert algo_id == h9.ALGO_LZMA, algo_id
        raw = _bridge(_SNIP_D, blob[h9.HEADER_LEN:])
        if len(raw) != orig_len or (zlib.crc32(raw) & 0xFFFFFFFF) != crc:
            raise ValueError("H9PC-lzma container failed integrity check (bridge)")
        return raw


# ===========================================================================
def load_rung() -> dict:
    """The m9_m8_dense375 rung dict, verbatim from m9_ladder.json (the SAME
    file m9_master built the proven tape from), with hard assertions on the
    parameters that define the 2572-bps record."""
    ladder = json.loads(LADDER_PATH.read_text())
    rung = next(r for r in ladder["rungs"] if r["name"] == RUNG_NAME)
    assert rung["kind"] == "dqpsk", rung
    assert (rung["P"], rung["N"], rung["spacing"]) == (22, 512, 4), rung
    assert rung["min_spacing_hz"] == 375.0, rung
    assert rung["rs_k"] == 159 and rung["pilot_hz"] == 4875, rung
    assert abs(rung["net_bps"] - 2572.1) < 0.1, rung
    return rung


def build(html_path: pathlib.Path = HTML_PATH,
          out_wav: pathlib.Path = WAV_PATH) -> dict:
    rung = load_rung()
    raw = html_path.read_bytes()
    sha_orig = hashlib.sha256(raw).hexdigest()

    # ---- pack (lzma via h9/auto, bridged if needed) + blocking roundtrip ----
    packed, pmeta = pack_doom(raw)
    assert unpack_doom(packed) == raw, "H9 pack/unpack roundtrip failed"
    SIDECAR_PATH.write_bytes(packed)

    # ---- modem: bit-identical scheme factory to the proven rung ----
    sch = make_scheme(rung)
    assert sch.name == "DQ_P22_N512_sp4", sch.name

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
        "tape": "m10doom",
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "html_path": str(html_path),
        "html_sha256": sha_orig,
        "ws_payloads": [],
    }

    # ---- lead + global up-chirp ----
    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (same as m8/m9) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # ---- THE payload section (one continuous run of frames, no ladder) ----
    section_start = pos
    m_rung = Rung(name=SECTION_NAME, M=rung["P"], K=1,
                  rs_n=RS_N, rs_k=rung["rs_k"], frame_bytes=FRAME_BYTES)
    frames_bits, meta = codec.encode_payload(packed, m_rung)
    frame_starts: list[int] = []
    for fbits in frames_bits:
        audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
        frame_starts.append(pos)
        add_raw(audio)
        add_raw(_silence(FRAME_GAP_S))
    section_end = pos
    add_gap()

    gross = sch.gross_bps
    net = gross * rung["rs_k"] / RS_N
    payload_seconds = (section_end - section_start) / SR
    eff = len(raw) * 8 / payload_seconds        # incl. compression + framing

    entry = {
        "name": SECTION_NAME,
        "kind": "dqpsk",
        "scheme": sch.name,
        "phy": sch.name,
        "role": "DOOM-ship-single-payload",
        "status": "SHIP",
        "gross_bps": gross,
        "projected_net_bps": net,
        "x_record": rung.get("x_record"),
        "effective_bps": eff,
        "payload_sidecar": str(SIDECAR_PATH.relative_to(TAPE_V2)),
        "payload_len": len(packed),
        "section_start": section_start,
        "section_end": section_end,
        "pack": {
            "algo": pmeta["algo"],
            "orig_len": pmeta["orig_len"],
            "packed_len": pmeta["packed_len"],
            "reduction_pct": pmeta["reduction_pct"],
            "sha256_orig": sha_orig,
            "sha256_packed": hashlib.sha256(packed).hexdigest(),
        },
        "crc32_codewords": _codeword_crcs(packed, rung["rs_k"]),
        "meta": meta,
        "frame_starts": frame_starts,
        "dqpsk_params": {
            "P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
            "min_spacing_hz": rung["min_spacing_hz"],
            "drop_freqs_hz": [],
            "pilot_hz": rung["pilot_hz"],
        },
        "carrier_freqs_hz": [round(float(f), 1) for f in sch.freqs[sch.data_idx]],
        "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1),
    }
    manifest["ws_payloads"].append(entry)

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
    dur_min = dur_s / 60.0

    sf.write(str(out_wav), audio_full, SR, subtype="FLOAT")
    manifest["wav_seconds"] = dur_s
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"[m10doom] payload  {html_path.name}: {len(raw)} B raw -> "
          f"{pmeta['packed_len']} B packed ({pmeta['algo']}, "
          f"-{pmeta['reduction_pct']:.1f}%) = {pmeta['packed_len']/1024:.1f} KB")
    print(f"[m10doom] modem    {sch.name} RS({RS_N},{rung['rs_k']}) "
          f"min_spacing=375Hz gross={gross:.1f} net={net:.1f} bps")
    print(f"[m10doom] frames   {meta['n_frames']} frames, "
          f"{meta['n_codewords']} codewords, payload section "
          f"{payload_seconds:.1f}s, effective {eff:.1f} bps on the HTML")
    print(f"[m10doom] tape     {out_wav.name}: {dur_s:.1f}s ({dur_min:.2f} min), "
          f"peak 0.70  [budget {C60_SIDE_BUDGET_MIN:.0f} min: "
          f"{'OK' if dur_min <= C60_SIDE_BUDGET_MIN else 'OVER'}]")
    print(f"[m10doom] manifest -> {MANIFEST_PATH}")
    assert dur_min <= C60_SIDE_BUDGET_MIN, (
        f"tape {dur_min:.2f} min exceeds the {C60_SIDE_BUDGET_MIN} min C60-side budget")
    return {"wav_seconds": dur_s, "wav_minutes": dur_min,
            "packed_len": pmeta["packed_len"], "algo": pmeta["algo"],
            "n_frames": meta["n_frames"], "net_bps": net,
            "effective_bps": eff, "sha256_orig": sha_orig}


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=str(HTML_PATH))
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    build(pathlib.Path(args.html), pathlib.Path(args.out))
