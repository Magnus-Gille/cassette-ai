"""m3_master.py — assemble the PHYSICAL master3.wav that carries a REAL payload.

This is the recordable master for the FIRST byte-exact recovery of a real file off
a physical cassette, using the deep-dive #2 breakthrough (flutter-tracked
combinatorial k-of-M index modulation + global RS-interleave whole-file FEC).

It REUSES, without reinventing:
  * make_master2._make_global_chirp / _build_sounder / _silence — the proven
    self-locating layout: lead silence, a wide-band global up-chirp, a ~45 s
    channel sounder, and a global down-chirp. analyze_master2.global_sync_and_resample
    recovers whole-tape speed/anchor from those two chirps (lead-in robust).
  * m3_codec.encode_payload(bytes, rung) -> frames + meta, and the RUNGS ladder.
  * d3d4_combo_tracked.make_tracked_combo(M, K) — each frame is modulated
    independently (its own 0.25 s chirp preamble) so the modem re-syncs per frame.

Layout
------
  1. ~1 s lead silence
  2. GLOBAL up-chirp                       (manifest tx_chirp0)
  3. ~0.4 s gap
  4. ~45 s SOUNDER (multitone + steady + noisefloor)
  5. ~0.4 s gap
  6. LADDER PAYLOADS, each = independently-modulated frames with ~0.2 s gaps
  7. ~0.4 s gap
  8. GLOBAL down-chirp                      (manifest tx_chirp1)
  9. ~1 s tail silence

Mix peak-normalised to 0.95.

PAYLOADS
--------
  - 2 KB random TEST file (fixed seed)        @ robust    — guaranteed-win probe
  - 2 KB random TEST file (fixed seed)        @ frontier  — frontier-rung probe
  - 32 KB slice of stories260K_int4.cass      @ robust    — hedge: real data, robust
  - FULL 153823-byte stories260K_int4.cass    @ frontier  — THE HERO

Each payload's exact known bytes are written to sidecars_m3/<name>.bin for byte
comparison by m3_decode.py.
"""
from __future__ import annotations

import dataclasses
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

import m3_codec as codec                                 # noqa: E402
from d3d4_combo_tracked import make_tracked_combo        # noqa: E402
# Reuse the proven master2 sounder + global-chirp helpers verbatim.
from make_master2 import (                               # noqa: E402
    _make_global_chirp, _build_sounder, _silence,
    GLOBAL_CHIRP_T,
)

SR = codec.FS
CASS = codec.CASS

OUT_DIR = _HERE
SIDECAR_DIR = OUT_DIR / "sidecars_m3"
WAV_PATH = OUT_DIR / "master3.wav"
MANIFEST_PATH = OUT_DIR / "master3_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40            # gap around chirps / sounder / between payloads
FRAME_GAP_S = 0.20      # gap between a payload's frames


# ---------------------------------------------------------------------------
# Payload manifest (name, rung, byte source)
# ---------------------------------------------------------------------------
def _build_payloads() -> list[dict]:
    full = CASS.read_bytes()
    assert len(full) == 153823, f"unexpected cassette-LLM size {len(full)}"
    rng = np.random.default_rng(0xCA55E77E)
    test2k = rng.integers(0, 256, size=2048, dtype=np.uint8).tobytes()
    # NOTE on `frame_bytes` overrides: the global column-interleave's burst
    # protection scales with FRAME COUNT — a single badly-desynced frame corrupts
    # ~1/n_frames of every codeword's bytes. A 2 KB payload at the nominal robust
    # frame_bytes=2000 is only ~3 frames, so one dead frame puts ~1/3 of each
    # codeword wrong, EXCEEDING RS(255,127) — the "guaranteed-win" probe was in
    # fact the FRAGILE rung (verified: it failed on sim seeds 11/23 while the 52-
    # frame 153 KB hero survived). Fix: shrink the probes' frame_bytes so a 2 KB
    # payload still spans many short frames (deep interleave). 255 B/frame -> ~17
    # frames; one dead frame then perturbs only ~15 of 255 bytes/codeword, far
    # within RS correction. This makes the probe genuinely the safe win it claims.
    return [
        {"name": "test2k_robust",   "rung": "robust",   "bytes": test2k,
         "frame_bytes": 255},
        {"name": "test2k_frontier", "rung": "frontier", "bytes": test2k,
         "frame_bytes": 255},
        # THE HERO at the ROBUST rung (best-odds): RS(255,127) rate 0.498 + dense
        # re-sync (frame_bytes 2000 -> ~77 frames) directly attacks the tracker
        # desync that defeated the frontier-rung full LLM. Supersedes the 32 KB
        # slice (same bytes, same rung).
        {"name": "llm_full_robust", "rung": "robust",     "bytes": full},
    ]


def build() -> str:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)

    parts: list[np.ndarray] = []
    pos = 0  # running sample counter

    def add_raw(sig: np.ndarray):
        nonlocal pos
        sig = np.asarray(sig, dtype=np.float32)
        parts.append(sig)
        pos += len(sig)

    def add_gap(d: float = GAP_S):
        add_raw(_silence(d))

    manifest: dict = {
        "SR": SR, "tx_chirp0": None, "tx_chirp1": None,
        "sounder_sections": [], "payloads": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
    }

    # 1. lead
    add_raw(_silence(LEAD))

    # 2. global up-chirp
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

    # 4. ladder payloads
    payloads = _build_payloads()
    print(f"[build] payloads: {[(p['name'], p['rung'], len(p['bytes'])) for p in payloads]}")
    for p in payloads:
        rung = codec.RUNGS_BY_NAME[p["rung"]]
        if p.get("frame_bytes"):  # per-payload deep-interleave override
            rung = dataclasses.replace(rung, frame_bytes=int(p["frame_bytes"]))
        sch = make_tracked_combo(rung.M, rung.K)
        frames_bits, meta = codec.encode_payload(p["bytes"], rung)

        # sidecar: exact known bytes
        scar = SIDECAR_DIR / f"{p['name']}.bin"
        scar.write_bytes(p["bytes"])

        frame_starts: list[int] = []
        for fbits in frames_bits:
            audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(FRAME_GAP_S))
        # one extra gap to separate payloads cleanly
        add_gap()

        sec = {
            "name": p["name"], "rung": rung.name,
            "payload_sidecar": str(scar.relative_to(OUT_DIR)),
            "payload_len": len(p["bytes"]),
            "meta": meta,
            "frame_starts": frame_starts,
            "frame_gap_samples": int(FRAME_GAP_S * SR),
        }
        manifest["payloads"].append(sec)
        print(f"[build]   {p['name']:18s} {rung.name:8s} "
              f"RS({rung.rs_n},{rung.rs_k}) fb{rung.frame_bytes} "
              f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
              f"bytes={len(p['bytes'])}")

    # 5. global down-chirp
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()

    # 6. tail
    add_raw(_silence(TAIL))

    # ------------------------------------------------------------------
    # assemble + peak-normalise to 0.95
    # ------------------------------------------------------------------
    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * 0.95).astype(np.float32)
    dur_s = len(audio_full) / SR

    sf.write(str(WAV_PATH), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print(f"[build] master3.wav {dur_s:.1f}s ({dur_s/60:.2f} min), "
          f"{len(audio_full)} samples, peak 0.95")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    return (f"master3.wav {dur_s:.1f}s ({dur_s/60:.2f} min), "
            f"{len(manifest['payloads'])} payloads, "
            f"chirp0={manifest['tx_chirp0']} chirp1={manifest['tx_chirp1']}")


if __name__ == "__main__":
    print(build())
