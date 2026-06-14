"""m4_master.py — assemble master4.wav: a recordable cassette master that carries
REAL data via TWO validated audio modulation schemes, each with its own decoder.

This is INTEGRATION of existing, validated code (see REAL_DECODE_FINDINGS.md). It
reuses, without retuning:
  * make_master2._make_global_chirp / _build_sounder / _silence — the proven
    self-locating layout (lead silence, wide-band up-chirp, ~45 s channel sounder,
    down-chirp). analyze_master2.global_sync_and_resample recovers whole-tape
    speed/anchor from the two chirps; analyze_master2.analyze_sounder reads the
    fresh channel H(f) used to build the per-tone EQ for the wide-spaced demod.
  * m3_codec.encode_payload / decode_payload — RS(n,k) + GLOBAL byte-interleave
    framing ONLY. The M/K fields of the Rung are placeholders for these schemes;
    the scheme itself does the actual tone/chirp modulation of the framed bits.

SCHEME 1 — WIDE-SPACED TONES (assault_widespace.build(16,1,3,256), WS_M16_K1_sp3_N256)
  Each data frame's bits are modulated with scheme.modulate(frame_bits). Paired
  with Reed-Solomon rate (255,111) (the margin rung, per the WS adjudication).
  Payloads: a 2 KB known random test block (fixed seed) + a 24 KB slice of the
  cassette-LLM file (stories260K_int4.cass[:24576]).

SCHEME 2 — CHIRP SPREAD-SPECTRUM (assault_css.CSSScheme(sf=6, bw=9000, fc=5000))
  The WHOLE payload's framed bits are modulated as ONE piloted stream via
  scheme.modulate_piloted(syms, pilot_every=2) and read back via demod_piloted.
  Paired with Reed-Solomon rate (255,95). Payloads: a 2 KB known test block +
  a 6 KB slice (stories260K_int4.cass[:6144]).

Layout
------
  1. ~1 s lead silence
  2. GLOBAL up-chirp                       (manifest tx_chirp0)
  3. ~0.4 s gap
  4. ~45 s SOUNDER (multitone + steady + noisefloor)
  5. ~0.4 s gap
  6. SCHEME-1 PAYLOADS: per-frame WS-modulated audio with small inter-frame gaps
  7. ~0.4 s gap
  8. SCHEME-2 PAYLOADS: each one piloted CSS stream
  9. ~0.4 s gap
 10. GLOBAL down-chirp                      (manifest tx_chirp1)
 11. ~1 s tail silence

Each payload's exact bytes are written to sidecars_m4/<name>.bin for byte-exact
comparison by m4_decode.py. master4.wav is gitignored (large float WAV).
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf

# --- path bootstrap --------------------------------------------------------
_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2", ROOT / "experiments" / "capacity",
           _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                  # noqa: E402
from m3_codec import Rung                                 # noqa: E402
from assault_widespace import build as ws_build           # noqa: E402
from assault_css import CSSScheme                          # noqa: E402
from make_master2 import (                                # noqa: E402
    _make_global_chirp, _build_sounder, _silence, GLOBAL_CHIRP_T,
)

SR = codec.FS
CASS = codec.CASS

OUT_DIR = _HERE
SIDECAR_DIR = OUT_DIR / "sidecars_m4"
WAV_PATH = OUT_DIR / "master4.wav"
MANIFEST_PATH = OUT_DIR / "master4_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40            # gap around chirps / sounder / between schemes
WS_FRAME_GAP_S = 0.12   # gap between a wide-spaced payload's frames

# Scheme-1 (wide-spaced) PHY + FEC. RS(255,111) = the margin rung (WS adjudication).
WS_M, WS_K, WS_SPACING, WS_N = 16, 1, 3, 256
WS_RS_N, WS_RS_K = 255, 111
WS_FRAME_BYTES = 1020   # deep interleave (24 KB -> ~56 frames) + keeps duration sane

# Scheme-2 (CSS chirp) PHY + FEC. RS(255,95). One piloted stream per payload.
CSS_SF, CSS_BW, CSS_FC = 6, 9000.0, 5000.0
CSS_RS_N, CSS_RS_K = 255, 95
CSS_FRAME_BYTES = 4000
CSS_PILOT_EVERY = 2
CSS_GRAY = True


def _build_payloads() -> dict:
    full = CASS.read_bytes()
    assert len(full) == 153823, f"unexpected cassette-LLM size {len(full)}"
    rng = np.random.default_rng(0xCA55E77E)
    ws_test = rng.integers(0, 256, size=2048, dtype=np.uint8).tobytes()
    css_test = rng.integers(0, 256, size=2048, dtype=np.uint8).tobytes()
    return {
        # frame_bytes per WS payload: the GLOBAL interleave's burst protection
        # scales with FRAME COUNT (one dead frame perturbs ~1/n_frames of every
        # codeword). A 2 KB block at fb1020 is only ~2 data frames -> a single
        # desync exceeds RS, so the test block uses a small frame_bytes for deep
        # interleave (many short frames); the 24 KB slice has ample frames at 1020.
        "ws": [
            {"name": "ws_test2k",  "bytes": ws_test,       "frame_bytes": 255},
            {"name": "ws_llm24k",  "bytes": full[:24576]},
        ],
        "css": [
            {"name": "css_test2k", "bytes": css_test},
            {"name": "css_llm6k",  "bytes": full[:6144]},
        ],
    }


def _ws_rung() -> Rung:
    return Rung(name="ws", M=WS_M, K=WS_K, rs_n=WS_RS_N, rs_k=WS_RS_K,
                frame_bytes=WS_FRAME_BYTES)


def _css_rung() -> Rung:
    # M/K here are placeholders for the framing codec; CSS does the modulation.
    return Rung(name="css", M=1 << CSS_SF, K=1, rs_n=CSS_RS_N, rs_k=CSS_RS_K,
                frame_bytes=CSS_FRAME_BYTES)


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
        "SR": SR, "tx_chirp0": None, "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "ws_payloads": [], "css_payloads": [],
        "ws_phy": {"M": WS_M, "K": WS_K, "spacing": WS_SPACING, "N": WS_N,
                   "rs_n": WS_RS_N, "rs_k": WS_RS_K, "frame_bytes": WS_FRAME_BYTES,
                   "frame_gap_samples": int(WS_FRAME_GAP_S * SR)},
        "css_phy": {"sf": CSS_SF, "bw": CSS_BW, "fc": CSS_FC,
                    "rs_n": CSS_RS_N, "rs_k": CSS_RS_K, "frame_bytes": CSS_FRAME_BYTES,
                    "pilot_every": CSS_PILOT_EVERY, "gray": CSS_GRAY},
    }

    # 1. lead
    add_raw(_silence(LEAD))

    # 2. up-chirp
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # 3. sounder
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for s in sounder_sections:
        s["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    payloads = _build_payloads()

    # 4. SCHEME 1 — wide-spaced tones, per-frame modulation
    ws = ws_build(WS_M, WS_K, WS_SPACING, WS_N)
    assert ws is not None and ws.name == "WS_M16_K1_sp3_N256", ws
    import dataclasses
    for p in payloads["ws"]:
        ws_rung = _ws_rung()
        if p.get("frame_bytes"):
            ws_rung = dataclasses.replace(ws_rung, frame_bytes=int(p["frame_bytes"]))
        frames_bits, meta = codec.encode_payload(p["bytes"], ws_rung)
        scar = SIDECAR_DIR / f"{p['name']}.bin"
        scar.write_bytes(p["bytes"])
        frame_starts: list[int] = []
        for fbits in frames_bits:
            audio = np.asarray(ws.modulate(fbits.astype(np.uint8)), dtype=np.float32)
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(WS_FRAME_GAP_S))
        add_gap()
        manifest["ws_payloads"].append({
            "name": p["name"], "scheme": "widespace", "phy": ws.name,
            "payload_sidecar": str(scar.relative_to(OUT_DIR)),
            "payload_len": len(p["bytes"]), "meta": meta,
            "frame_starts": frame_starts,
        })
        print(f"[build] WS  {p['name']:12s} RS({WS_RS_N},{WS_RS_K}) fb{ws_rung.frame_bytes} "
              f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
              f"bytes={len(p['bytes'])}")

    # 5. SCHEME 2 — CSS chirp, one piloted stream per payload
    css = CSSScheme(sf=CSS_SF, bw=CSS_BW, fc=CSS_FC)
    css_rung = _css_rung()
    for p in payloads["css"]:
        frames_bits, meta = codec.encode_payload(p["bytes"], css_rung)
        scar = SIDECAR_DIR / f"{p['name']}.bin"
        scar.write_bytes(p["bytes"])
        # concat all frame bits into one stream, pad to whole CSS symbols, gray-map
        all_bits = np.concatenate([np.asarray(f, np.uint8) for f in frames_bits]).astype(np.uint8)
        pad = (-len(all_bits)) % css.bits_per_sym
        if pad:
            all_bits = np.concatenate([all_bits, np.zeros(pad, np.uint8)])
        data_vals = css._bits_to_syms(all_bits)
        tx_syms = [css._gray(int(v)) for v in data_vals] if CSS_GRAY else list(data_vals)
        audio = np.asarray(css.modulate_piloted(tx_syms, CSS_PILOT_EVERY), dtype=np.float32)
        stream_start = pos
        add_raw(audio)
        add_gap()
        manifest["css_payloads"].append({
            "name": p["name"], "scheme": "css", "phy": css.name,
            "payload_sidecar": str(scar.relative_to(OUT_DIR)),
            "payload_len": len(p["bytes"]), "meta": meta,
            "stream_start": stream_start,
            "n_data_syms": len(tx_syms),
            "stream_pad_bits": int(pad),
        })
        print(f"[build] CSS {p['name']:12s} RS({CSS_RS_N},{CSS_RS_K}) fb{CSS_FRAME_BYTES} "
              f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
              f"syms={len(tx_syms)} bytes={len(p['bytes'])}")

    # 6. down-chirp
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()

    # 7. tail
    add_raw(_silence(TAIL))

    # assemble + peak-normalise to 0.95
    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * 0.95).astype(np.float32)
    dur_s = len(audio_full) / SR

    sf.write(str(WAV_PATH), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"[build] master4.wav {dur_s:.1f}s ({dur_s/60:.2f} min), "
          f"{len(audio_full)} samples, peak 0.95")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    return (f"master4.wav {dur_s:.1f}s ({dur_s/60:.2f} min), "
            f"{len(manifest['ws_payloads'])} WS + {len(manifest['css_payloads'])} CSS "
            f"payloads, chirp0={manifest['tx_chirp0']} chirp1={manifest['tx_chirp1']}")


if __name__ == "__main__":
    print(build())
