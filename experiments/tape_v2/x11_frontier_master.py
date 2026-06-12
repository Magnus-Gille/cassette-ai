"""x11_frontier_master.py -- assemble the x11-frontier candidate sections.

Builds x11_master_frontier.wav: ONE global sync (chirp pair + front Schroeder
sounder, m9/m10 architecture) + 4 sections:

  a0  x11_anchor_2572        BYTE-IDENTICAL m10_r0 canary reuse (asserted
                             against master10_manifest.json sha256 + CRC table)
  f1  x11_f1_d2x_p19_rs179   banker candidate  net 5001.5   (margin-gate KILL)
  f2  x11_f2_d2x_p19_rs191   banker candidate  net 5336.8   (margin-gate KILL)
  f3  x11_f3_d2xx_p23_rs127  ext-band probe    net 4296.0   (GO, but derated
                             by the gate to P16/2988 -- dominated by r5)

PRINT AUTHORIZATION: **NOT AUTHORIZED.**  The pre-registered x11 margin gate
(results/x11_frontier_margins.json, frozen before measurement) KILLED both
banker candidates (2625/6750 Hz fail the 15-deg tape9 margin; 3750 Hz fails
cross-capture confirmation at the documented master8 null) and stripped all
four >9 kHz bins from F3 (predicted margins 6.4-10.3 deg < 15).  This wav
exists for the x11 sim pre-gate (AAC + constant-clock-offset axes) and the
mandatory no-channel self-check of the section generators ONLY.  The manifest
embeds print_authorized=false; x11_frontier_decode refuses nothing, but no
tape pass is sanctioned by the x11 campaign.

FRAMING: imports m10_master.make_scheme + _codeword_crcs and the
x10_b_aggr_05_dense2x_master schemes VERBATIM (import, don't copy -- no
frozen file is edited).  Section framing (0.25 s preamble, 0.12 s frame gaps,
RS(255,k) m3_codec frames, h9-packed payloads, CRC32-per-codeword sidecar
tables) is byte-compatible with the m10_master conventions.

Run:  python3 x11_frontier_master.py [--out x11_master_frontier.wav]
Deterministic (LADDER_SEED logged).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                   # noqa: E402
from m3_codec import Rung                                  # noqa: E402
from h9_payload_codec import pack_payload, unpack_payload  # noqa: E402
from make_master2 import (                                 # noqa: E402
    GLOBAL_CHIRP_T, _build_sounder, _make_global_chirp, _silence,
)
# import-don't-copy: the m10 scheme factory + CRC convention, verbatim
from m10_master import (                                   # noqa: E402
    make_scheme, _codeword_crcs, MANIFEST_PATH as M10_MANIFEST_PATH,
    X10_SIDECARS, RS_N, FRAME_BYTES, GAP_S, FRAME_GAP_S, LEAD, TAIL,
)

SR = codec.FS
CASS = codec.CASS

OUT_DIR = _HERE
WAV_PATH = OUT_DIR / "x11_master_frontier.wav"
MANIFEST_PATH = OUT_DIR / "x11_master_frontier_manifest.json"
SIDECAR_DIR = OUT_DIR / "sidecars_x11_frontier"
MARGINS_JSON = _HERE / "results" / "x11_frontier_margins.json"

MASTER_ID = "x11_frontier"
LADDER_SEED = 20260612
RECORD_BPS = 2572.06

# ---------------------------------------------------------------------------
# The x11-frontier ladder.  Geometry/RS frozen in the x11 prereg
# (results/x11_frontier_margins.json); the anchor is the m10_r0 canary
# byte-identical (m10 reuse convention).
# ---------------------------------------------------------------------------
LADDER = [
    {"name": "x11_anchor_2572", "tier": "canary", "kind": "dqpsk",
     "P": 22, "N": 512, "spacing": 4, "min_spacing_hz": 375.0, "rs_k": 159,
     "offset": 98304, "orig_bytes": 8192, "pilot_hz": 4875,
     "reuse_sidecar": "x10_anchor_m8dense375",
     "m10_twin": "m10_r0_canary_2572",
     "role": "canary -- must reprove 2572 orig-exact on any capture"},
    {"name": "x11_f1_d2x_p19_rs179", "tier": "banker-candidate",
     "kind": "dense2x_drop", "P": 19, "N": 256, "spacing": 2, "skip": 64,
     "drop_freqs_hz": [750.0, 4500.0, 5625.0], "rs_k": 179,
     "offset": 59392, "orig_bytes": 12288, "pilot_hz": 4875,
     "role": "x11 banker candidate 5001.5 net -- KILLED by the margin gate "
             "(2625/6750 below 15 deg on tape9; 3750 fails m8 cross-capture)"},
    {"name": "x11_f2_d2x_p19_rs191", "tier": "banker-candidate",
     "kind": "dense2x_drop", "P": 19, "N": 256, "spacing": 2, "skip": 64,
     "drop_freqs_hz": [750.0, 4500.0, 5625.0], "rs_k": 191,
     "offset": 71680, "orig_bytes": 12288, "pilot_hz": 4875,
     "role": "x11 banker candidate 5336.8 net -- KILLED by the margin gate "
             "(same geometry as f1)"},
    {"name": "x11_f3_d2xx_p23_rs127_extband", "tier": "probe",
     "kind": "dense2x_drop", "P": 23, "N": 256, "spacing": 2, "skip": 64,
     "drop_freqs_hz": [750.0, 4500.0, 5625.0], "rs_k": 127,
     "offset": 0, "orig_bytes": 12288, "pilot_hz": 4875,
     "role": "ext-band probe 750..10500 Hz grid, 4296 net as designed -- the "
             "margin gate stripped all 4 new bins (predicted 6.4-10.3 deg); "
             "kept for the sim pre-gate's B1/B3 ext-band evidence only"},
]


def _margin_verdicts() -> dict:
    if not MARGINS_JSON.exists():
        return {}
    adj = json.loads(MARGINS_JSON.read_text()).get("adjudication", {})
    return {k: v.get("verdict") for k, v in
            adj.get("per_candidate", {}).items()}


# ===========================================================================
def build(out_wav: pathlib.Path = WAV_PATH) -> str:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    full = CASS.read_bytes()
    assert len(full) == 153823, f"unexpected cassette-LLM size {len(full)}"
    m10_manifest = json.loads(M10_MANIFEST_PATH.read_text())
    m10_secs = {s["name"]: s for s in m10_manifest["ws_payloads"]}
    verdicts = _margin_verdicts()

    parts: list[np.ndarray] = []
    pos = 0

    def add_raw(sig):
        nonlocal pos
        sig = np.asarray(sig, dtype=np.float32)
        parts.append(sig)
        pos += len(sig)

    def add_gap(d: float = GAP_S):
        add_raw(_silence(d))

    manifest: dict = {
        "SR": SR,
        "tape": MASTER_ID,
        "master_id": MASTER_ID,
        "print_authorized": False,
        "print_block_reason": (
            "x11 margin gate KILLED both banker candidates and stripped the "
            "F3 extension bins; this wav exists for the x11 sim pre-gate and "
            "the no-channel self-check only (results/x11_frontier_margins"
            ".json adjudication)"),
        "tx_chirp0": None, "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "cass_path": str(CASS),
        "cass_sha256": hashlib.sha256(full).hexdigest(),
        "ladder_seed": LADDER_SEED,
        "rx_window_plan": {
            "primary": "hann256_skip0", "alternate": "rect128_skip64",
            "reason": "Hann(Nw=128) non-orthogonal at 1-bin spacing (probe)"},
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

    for rung in LADDER:
        rung_start_pos = pos
        sch = make_scheme(rung)
        orig = full[rung["offset"]: rung["offset"] + rung["orig_bytes"]]
        assert len(orig) == rung["orig_bytes"], rung
        packed, pmeta = pack_payload(orig, algo="auto")
        assert unpack_payload(packed) == orig, f"H9 roundtrip {rung['name']}"

        if rung.get("reuse_sidecar"):
            ref = (X10_SIDECARS / f"{rung['reuse_sidecar']}.bin").read_bytes()
            assert unpack_payload(ref) == orig, rung["name"]
            assert len(ref) == pmeta["packed_len"], rung["name"]
            packed = ref

        sidecar = SIDECAR_DIR / f"{rung['name']}.bin"
        sidecar.write_bytes(packed)
        (SIDECAR_DIR / f"{rung['name']}.orig.bin").write_bytes(orig)

        m_rung = Rung(name=rung["name"], M=rung["P"], K=1,
                      rs_n=RS_N, rs_k=rung["rs_k"], frame_bytes=FRAME_BYTES)
        frames_bits, meta = codec.encode_payload(packed, m_rung)
        frame_starts: list[int] = []
        for fbits in frames_bits:
            audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), np.float32)
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(FRAME_GAP_S))
        add_gap()

        gross = sch.gross_bps
        net = gross * rung["rs_k"] / RS_N
        entry = {
            "name": rung["name"], "kind": rung["kind"], "tier": rung["tier"],
            "scheme": sch.name, "phy": sch.name,
            "role": rung.get("role", ""),
            "margin_gate_verdict": verdicts.get(rung["name"],
                                                "ANCHOR (never gated)"),
            "gross_bps": gross, "projected_net_bps": net,
            "x_record": round(net / RECORD_BPS, 3),
            "payload_sidecar": str(sidecar.relative_to(OUT_DIR)),
            "payload_orig_sidecar": str(
                (SIDECAR_DIR / f"{rung['name']}.orig.bin").relative_to(OUT_DIR)),
            "payload_len": len(packed),
            "llm_offset": rung["offset"],
            "pack": {
                "algo": pmeta["algo"], "orig_len": pmeta["orig_len"],
                "packed_len": pmeta["packed_len"],
                "reduction_pct": pmeta["reduction_pct"],
                "sha256_orig": hashlib.sha256(orig).hexdigest(),
                "sha256_packed": hashlib.sha256(packed).hexdigest(),
            },
            "crc32_codewords": _codeword_crcs(packed, rung["rs_k"]),
            "meta": meta,
            "frame_starts": frame_starts,
            "dqpsk_params": {
                "P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
                "skip": rung.get("skip"),
                "min_spacing_hz": rung.get("min_spacing_hz", 375.0),
                "drop_freqs_hz": [float(f) for f in rung.get("drop_freqs_hz", [])],
                "pilot_hz": rung["pilot_hz"]},
            "carrier_freqs_hz": [round(float(f), 1)
                                 for f in sch.freqs[sch.data_idx]],
            "pilot_hz_actual": round(float(sch.freqs[sch.pilot_idx]), 1),
        }
        manifest["ws_payloads"].append(entry)
        sec_s = (pos - rung_start_pos) / SR
        print(f"[build] {rung['name']:32s} {sch.name:28s} "
              f"RS({RS_N},{rung['rs_k']:3d}) gross={gross:6.1f} "
              f"net={net:7.1f} x{net/RECORD_BPS:4.2f} "
              f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
              f"sec={sec_s:5.1f}s [{rung['tier']}]")

    # ---- anchor byte-identity vs master10 (the m10 reuse convention) -------
    a0 = manifest["ws_payloads"][0]
    r0 = m10_secs["m10_r0_canary_2572"]
    assert a0["pack"]["sha256_packed"] == r0["pack"]["sha256_packed"], \
        "anchor packed payload != m10_r0"
    assert a0["crc32_codewords"] == r0["crc32_codewords"], \
        "anchor CRC table != m10_r0"
    assert a0["pack"]["sha256_orig"] == r0["pack"]["sha256_orig"]

    add_raw(_silence(1.0))
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()
    add_raw(_silence(TAIL))

    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * 0.70).astype(np.float32)
    dur_s = len(audio_full) / SR

    sf.write(str(out_wav), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))
    print(f"\n[build] {out_wav.name} {dur_s:.1f}s ({dur_s/60:.2f} min), peak 0.70")
    print(f"[build] anchor byte-identity vs m10_r0: VERIFIED")
    print(f"[build] PRINT AUTHORIZED: NO (margin-gate kill; sim/self-check only)")
    return (f"{out_wav.name} {dur_s:.1f}s ({dur_s/60:.2f} min), "
            f"{len(manifest['ws_payloads'])} sections")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    print(build(pathlib.Path(args.out)))
