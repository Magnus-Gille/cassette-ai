"""make_master2.py — Build the tape_v2 physical-test master WAV.

Outputs
-------
experiments/tape_v2/master2.wav          float32 @48k, peak ~0.95, 16-18 min
experiments/tape_v2/master2_manifest.json
experiments/tape_v2/sidecars/<config>_rep<r>.bin   exact payload bytes per section

Layout
------
  1. 1 s lead silence
  2. 0.2 s global up-chirp (tx_chirp0)
  3. 0.4 s gap
  4. ~45 s SOUNDER  (multitone + steady tone + silence)
  5. 0.4 s gap
  6. LADDER  (88-89 reps per config, interleaved round-robin robust->aggressive)
  7. 0.4 s gap
  8. 0.2 s global down-chirp (tx_chirp1)
  9. 1 s tail silence

Final mix peak-normalised to 0.95.

Validation gate
---------------
After writing, re-read the WAV and decode EVERY section via its modem.
Asserts 100% byte-exact match to its sidecar. Prints census.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import struct
import zlib
import os
import numpy as np
import soundfile as sf
from scipy.signal import chirp as _scipy_chirp

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

TAPE_V2 = ROOT / "experiments" / "tape_v2"
if str(TAPE_V2) not in sys.path:
    sys.path.insert(0, str(TAPE_V2))

import modems_index   # noqa: E402
import modems_combo   # noqa: E402
import modems_ofdm    # noqa: E402

SR = 48_000

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
OUT_DIR = TAPE_V2
SIDECAR_DIR = OUT_DIR / "sidecars"
WAV_PATH = OUT_DIR / "master2.wav"
MANIFEST_PATH = OUT_DIR / "master2_manifest.json"

SIDECAR_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Config registry — ordered robust -> aggressive, with modem module reference
# ---------------------------------------------------------------------------
CONFIGS_ORDERED = [
    ("mfsk32",       modems_index),
    ("c1_gray_m16",  modems_index),
    ("c2_m32_k2",    modems_combo),
    ("c2_m32_k4",    modems_combo),
    ("c2_m48_k6",    modems_combo),
    ("c4_bpsk",      modems_ofdm),
    ("c4_qpsk",      modems_ofdm),
    ("c4_realmodel", modems_ofdm),
    ("c4_simloaded", modems_ofdm),
]

# ---------------------------------------------------------------------------
# Global chirp anchors (distinct from the 0.25 s per-section preamble chirps)
# These are wider-band, longer, easily locatable in the recording.
# ---------------------------------------------------------------------------
GLOBAL_CHIRP_T  = 0.20    # seconds
GLOBAL_CHIRP_F0 = 500.0   # Hz  — below the 800-3200 Hz modem preamble band
GLOBAL_CHIRP_F1 = 5000.0  # Hz
GLOBAL_CHIRP_AMP = 0.70


def _make_global_chirp(up: bool = True) -> np.ndarray:
    n = int(GLOBAL_CHIRP_T * SR)
    t = np.arange(n, dtype=np.float64) / SR
    f0, f1 = (GLOBAL_CHIRP_F0, GLOBAL_CHIRP_F1) if up else (GLOBAL_CHIRP_F1, GLOBAL_CHIRP_F0)
    sig = _scipy_chirp(t, f0=f0, f1=f1, t1=GLOBAL_CHIRP_T, method="linear")
    fade = int(0.01 * SR)
    sig[:fade]  *= np.linspace(0, 1, fade)
    sig[-fade:] *= np.linspace(1, 0, fade)
    return (GLOBAL_CHIRP_AMP * sig).astype(np.float32)


# ---------------------------------------------------------------------------
# Sounder helpers (~45 s total including gaps between sub-sections)
# ---------------------------------------------------------------------------

def _silence(dur: float) -> np.ndarray:
    return np.zeros(int(dur * SR), dtype=np.float32)


def _schroeder_multitone(freqs: list[int], dur: float, amp: float) -> np.ndarray:
    """Low-PAPR Schroeder multitone over the given frequencies."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    fade = int(0.02 * SR)
    x[:fade]  *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return (amp * x).astype(np.float32)


def _steady_tone(f0: float, dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = amp * np.sin(2 * np.pi * f0 * t)
    fade = int(0.02 * SR)
    x[:fade]  *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x.astype(np.float32)


def _build_sounder() -> tuple[np.ndarray, list[dict]]:
    """Build ~45s channel sounder.  Returns (audio, sounder_sections)."""
    # 300-11000 Hz, 64 log-spaced carriers (mirrors make_sounder.py S2)
    freqs = np.round(np.geomspace(300, 11000, 64)).astype(int).tolist()
    parts: list[np.ndarray] = []
    sections: list[dict] = []
    pos = 0

    def add(sig: np.ndarray, kind: str, info: dict):
        nonlocal pos
        parts.append(sig)
        sections.append(dict(kind=kind, start=int(pos), length=int(len(sig)), info=info))
        pos += len(sig)

    def gap(d: float = 0.5):
        nonlocal pos
        g = _silence(d)
        parts.append(g)
        pos += len(g)

    # Sub-section 1: two repetitions of the 64-tone Schroeder probe (3s each) for averaging
    for rep in range(2):
        gap(0.5)
        add(_schroeder_multitone(freqs, 3.0, 0.60), "multitone", {"rep": rep, "freqs": freqs})
        gap(0.5)

    # Sub-section 2: steady 3 kHz tone for wow/flutter measurement (~12 s — enough to estimate)
    gap(0.5)
    add(_steady_tone(3000.0, 12.0, 0.50), "steady", {"f0": 3000.0})
    gap(0.5)

    # Sub-section 3: silence for noise-floor measurement (3 s)
    gap(0.5)
    add(_silence(3.0), "noisefloor", {})
    gap(0.5)

    return np.concatenate(parts).astype(np.float32), sections


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------
# Per-section payload: printable ASCII, ~96 bytes, encodes config+rep identity.
_QUOTE = "The quick cassette plays on. "  # 29 chars (29 * k fills to ~96)
_PAD_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def _make_payload(config: str, rep: int) -> bytes:
    prefix = f"CASSETTE-AI v2 | {config} rep{rep:03d} | "
    # fill to exactly 96 bytes (pad with cycling _PAD_CHARS)
    target = 96
    filler = (_QUOTE + _PAD_CHARS) * 4
    raw = (prefix + filler)[:target]
    # Force exactly target bytes (pad with spaces if short)
    raw = raw.ljust(target)[:target]
    return raw.encode("ascii")


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build() -> str:
    """Assemble master2.wav + manifest + sidecars.  Returns summary string."""

    # ------------------------------------------------------------------
    # 1. Decide rep counts to hit 16-18 min
    # ------------------------------------------------------------------
    GAP_S = 0.40
    SOUNDER_APPROX_S = 45.0   # approximate; actual may vary a few seconds
    CHIRP_T = GLOBAL_CHIRP_T
    LEAD = 1.0
    TAIL = 1.0

    # Compute per-section duration for each config with a 96-byte payload
    payload_sample = b"x" * 96
    section_dur: dict[str, float] = {}
    for name, mod in CONFIGS_ORDERED:
        a = mod.modulate(payload_sample, name)
        section_dur[name] = len(a) / SR

    # per-config cost per rep
    per_rep_cost = {name: section_dur[name] + GAP_S for name, _ in CONFIGS_ORDERED}
    total_per_round = sum(per_rep_cost.values())

    # fixed overhead: lead + chirp0 + gap + sounder + gap + gap + chirp1 + gap + tail
    fixed = LEAD + CHIRP_T + GAP_S + SOUNDER_APPROX_S + GAP_S + GAP_S + CHIRP_T + GAP_S + TAIL

    TARGET_MID = 17.0 * 60.0
    budget = TARGET_MID - fixed
    base_reps = max(1, int(budget / total_per_round))

    # Distribute leftover seconds to the most robust (slowest) configs first
    leftover = budget - base_reps * total_per_round
    reps: dict[str, int] = {name: base_reps for name, _ in CONFIGS_ORDERED}
    for name, _ in sorted(CONFIGS_ORDERED, key=lambda nc: section_dur[nc[0]], reverse=True):
        if leftover >= per_rep_cost[name]:
            reps[name] += 1
            leftover -= per_rep_cost[name]

    print(f"[build] Base reps: {base_reps}, total_per_round={total_per_round:.3f}s")
    print(f"[build] Reps per config: {reps}")

    # ------------------------------------------------------------------
    # 2. Build audio + manifest
    # ------------------------------------------------------------------
    parts: list[np.ndarray] = []
    pos = 0  # running sample counter
    manifest: dict = {
        "SR": SR,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "sections": [],
    }

    def add_raw(sig: np.ndarray):
        nonlocal pos
        parts.append(np.asarray(sig, dtype=np.float32))
        pos += len(sig)

    def add_gap(d: float = GAP_S):
        add_raw(_silence(d))

    # 1. Lead silence
    add_raw(_silence(LEAD))

    # 2. Up-chirp
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # 3. Sounder
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for s in sounder_sections:
        s["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # 4. Ladder — interleaved round-robin
    # Build all (config, rep) pairs in interleaved order.
    # Round-robin: round 0: (c0,0),(c1,0),...,(c8,0); round 1: (c0,1),...; etc.
    max_reps = max(reps.values())
    section_order: list[tuple[str, int]] = []
    for r in range(max_reps):
        for name, _ in CONFIGS_ORDERED:
            if r < reps[name]:
                section_order.append((name, r))

    print(f"[build] Total sections: {len(section_order)}")

    sidecars_written: set[str] = set()
    for name, r in section_order:
        mod = dict(CONFIGS_ORDERED)[name]
        payload = _make_payload(name, r)
        # Save sidecar (write once per (name, r) pair)
        scar_name = f"{name}_rep{r:03d}.bin"
        scar_path = SIDECAR_DIR / scar_name
        if scar_name not in sidecars_written:
            scar_path.write_bytes(payload)
            sidecars_written.add(scar_name)

        # Modulate
        audio_sec = mod.modulate(payload, name)
        sec_start = pos

        manifest["sections"].append({
            "kind": "data",
            "config": name,
            "rep": r,
            "start_sample": int(sec_start),
            "length": int(len(audio_sec)),
            "payload_sidecar": str(scar_path.relative_to(OUT_DIR)),
        })
        add_raw(audio_sec)
        add_gap()

    # 5. Down-chirp
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()

    # 6. Tail silence
    add_raw(_silence(TAIL))

    # ------------------------------------------------------------------
    # 3. Assemble + peak-normalise
    # ------------------------------------------------------------------
    print("[build] Concatenating audio...")
    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    print(f"[build] Pre-norm peak: {peak:.4f}, samples: {len(audio_full)}, duration: {len(audio_full)/SR:.1f}s")
    if peak > 1e-9:
        audio_full = (audio_full / peak * 0.95).astype(np.float32)

    # ------------------------------------------------------------------
    # 4. Write WAV + manifest
    # ------------------------------------------------------------------
    print(f"[build] Writing {WAV_PATH} ...")
    sf.write(str(WAV_PATH), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"[build] Manifest: {MANIFEST_PATH}")

    # ------------------------------------------------------------------
    # 5. VALIDATION GATE: decode every section and assert byte-exact
    # ------------------------------------------------------------------
    print("[validate] Loading WAV for decode verification...")
    rx_audio, rx_sr = sf.read(str(WAV_PATH), dtype="float32", always_2d=False)
    assert rx_sr == SR, f"SR mismatch: {rx_sr} vs {SR}"

    _MOD_MAP = {name: mod for name, mod in CONFIGS_ORDERED}
    n_total = len(manifest["sections"])
    n_pass = 0
    n_fail = 0
    fail_list: list[str] = []
    gross_bytes_per_cfg: dict[str, int] = {}
    n_sections_per_cfg: dict[str, int] = {}

    for sec in manifest["sections"]:
        name = sec["config"]
        r    = sec["rep"]
        start = sec["start_sample"]
        length = sec["length"]
        mod = _MOD_MAP[name]

        # Slice the section audio (include preamble which is inside length)
        audio_sec = rx_audio[start : start + length]

        # Decode directly (no channel)
        rx_payload = mod.demodulate(audio_sec, name)

        # Load expected sidecar
        scar_path = OUT_DIR / sec["payload_sidecar"]
        expected = scar_path.read_bytes()

        if rx_payload == expected:
            n_pass += 1
        else:
            n_fail += 1
            fail_list.append(f"{name} rep{r}")

        gross_bytes_per_cfg[name] = gross_bytes_per_cfg.get(name, 0) + len(expected)
        n_sections_per_cfg[name] = n_sections_per_cfg.get(name, 0) + 1

    total_payload_bytes = sum(gross_bytes_per_cfg.values())
    dur_s = len(audio_full) / SR
    dur_min = dur_s / 60.0

    # ------------------------------------------------------------------
    # 6. Census
    # ------------------------------------------------------------------
    print()
    print("=" * 65)
    print(f"master2.wav  duration={dur_s:.1f}s ({dur_min:.2f} min)")
    print(f"Sections: {n_total} total, {n_pass} PASS, {n_fail} FAIL")
    print()
    print(f"{'Config':<16} {'N_secs':>7} {'Payload_B':>10} {'Gross_bps':>10}")
    print("-" * 47)
    for name, _ in CONFIGS_ORDERED:
        n = n_sections_per_cfg.get(name, 0)
        pb = gross_bytes_per_cfg.get(name, 0)
        # Compute gross bps from section durations
        audio_sample = rx_audio[
            manifest["sections"][0]["start_sample"]:
            manifest["sections"][0]["start_sample"] + manifest["sections"][0]["length"]
        ]
        # Use section_dur computed earlier
        dur_sec = section_dur.get(name, 1.0)
        gbps = (96 + 8) * 8 / dur_sec  # frame = payload+8 overhead bytes
        print(f"  {name:<14} {n:>7} {pb:>10} {gbps:>10.0f}")
    print("-" * 47)
    print(f"  {'TOTAL':<14} {n_total:>7} {total_payload_bytes:>10}")
    print("=" * 65)

    if n_fail > 0:
        print(f"\n[VALIDATION FAILED] {n_fail} sections failed: {fail_list[:10]}")
        raise AssertionError(
            f"Validation gate failed: {n_fail}/{n_total} sections did not decode byte-exact."
        )
    else:
        print("[VALIDATION PASSED] All sections decode byte-exact.")

    summary = (
        f"master2.wav: {dur_s:.1f}s ({dur_min:.2f} min), "
        f"{n_total} sections ({n_sections_per_cfg}), "
        f"{total_payload_bytes} total payload bytes, "
        f"clean decode 100% byte-exact ({n_pass}/{n_total} pass)."
    )
    print(f"\n{summary}")
    return summary


if __name__ == "__main__":
    result = build()
    print(f"\nDone: {result}")
