"""m10_master.py -- assemble master10.wav: the master10 deliverable tape.

ONE physical recording, ONE global sync (chirp pair + front sounder), then the
10-rung master10 ladder (x10_dossier adjudicated plan), robust-early ->
stretch-late, with a FORENSIC tail canary at the very end:

  r0  canary-2572      DQPSK P22 N512 sp4  RS159 msp375  standing record    2572.1
  r1  n256-rs179       DQPSK P10 N256 sp4  RS179  proven (x10 rescue)       2632.4
  r2  n256-rs191       DQPSK P10 N256 sp4  RS191  proven (x10 rescue)       2808.8
  r3  n256-p11         DQPSK P11 N256 sp4  RS179  proven (x10 rescue)       2895.6
  r4  n256-p11-twin    DQPSK P11 N256 sp4  RS179  realization insurance     2895.6
  r5  d2x-p18-rs127    D2X  P18 N256 sp2  RS127  drop{750,4500,5625,6750}   3361.8
  r6  d2x-p21-rs159    D2X  P21 N256 sp2  RS159  drop{750}  RECORD ATTEMPT  4910.3
  r7  d2x-p21-twin     D2X  P21 N256 sp2  RS159  realization insurance      4910.3
  r8  d2x-p22-rs179    D2X  P22 N256 sp2  RS179  full grid (stretch/diag)   5791.2
  r9  tail-canary      BYTE-IDENTICAL repeat of r0 at end of tape  FORENSIC ONLY

Architecture follows m9_master.py EXACTLY where possible:
  * global chirp0 (up) -> front Schroeder sounder (multitone x2 + 12 s flutter
    + 3 s noisefloor) -> rungs -> chirp1 (down).  NO P1/P2 probe sections: every
    rung carries a payload sidecar, so failures yield per-carrier SER forensics.
  * each section carries an h9-PACKED slice of stories260K_int4.cass, RS(255,k)
    m3_codec frames, 0.25 s chirp preamble + 0.12 s gap, and a MANDATORY
    CRC32-per-codeword manifest sidecar table (the only acceptance channel for
    the entire union/rescue machinery -- tape7/tape4 precedent).
  * r0/r9 reuse the x10_anchor_m8dense375 section generator BYTE-IDENTICALLY
    (asserted against sidecars_x10_dense2x/x10_anchor_m8dense375.bin).
  * r5/r6/r8 reuse the x10_b_aggr_05_dense2x_master section generators with the
    SAME payload offsets (asserted byte-identical against their sidecars).
  * r1-r4 use the m9_master N256 generators (plain DQPSKScheme) at FRESH
    payload offsets; r4/r7 are the two NEW twin sections (m4/m4b convention).
  * r9 is placed at the very END (after r8, before the end chirp) and is
    pre-registered FORENSIC ONLY: head-vs-tail differential (outer-wrap
    flutter / azimuth drift attribution), banks nothing, triggers no abort.

DO-NOT-PRINT HAZARD: experiments/tape_v2/x10_master10.wav + x10_master10_draft.wav
+ x10_master10_manifest.json are STALE artifacts of the REJECTED toneplan-v2
candidate. The operator must NEVER print x10_master10.wav. THIS builder writes
master10.wav + master10_manifest.json (master_id='master10'); m10_decode.py
refuses any manifest whose master_id mismatches.

Run:
    python3 experiments/tape_v2/m10_master.py [--out master10_draft.wav]
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

import m3_codec as codec                                  # noqa: E402
from m3_codec import Rung                                 # noqa: E402
from h4_dqpsk import DQPSKScheme, FS as DQ_FS             # noqa: E402
from h9_payload_codec import pack_payload, unpack_payload  # noqa: E402
from make_master2 import (                                # noqa: E402
    GLOBAL_CHIRP_T, _build_sounder, _make_global_chirp, _silence,
)
from x10_b_aggr_05_dense2x_master import (                # noqa: E402
    Dense2xScheme, Dense2xDropScheme, DROP_P18, DROP_P21, PILOT_HZ as D2X_PILOT,
)

SR = codec.FS
assert SR == DQ_FS == 48_000
CASS = codec.CASS

OUT_DIR = _HERE
SIDECAR_DIR = OUT_DIR / "sidecars_m10"
WAV_PATH = OUT_DIR / "master10.wav"
MANIFEST_PATH = OUT_DIR / "master10_manifest.json"
X10_SIDECARS = OUT_DIR / "sidecars_x10_dense2x"   # verbatim-reuse cross-check

MASTER_ID = "master10"
LADDER_SEED = 20260612          # deterministic build; logged per convention

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
GAP_BEFORE_TAIL_CANARY_S = 1.30   # pre-registered: ~1.3 s gap before r9
FRAME_GAP_S = 0.12
RS_N = 255
FRAME_BYTES = 510
RECORD_BPS = 2572.06            # the standing m8_dense375 real-tape record

# ===========================================================================
# The adjudicated master10 ladder (x10_dossier plan, frozen 2026-06-12).
# Offsets: r0/r5/r6/r8 reuse the dense2x-master offsets VERBATIM (byte-identical
# sections); r1-r4/r7 are FRESH offsets unused by any prior tape (m9 used
# 0..82240; dense2x used 98304..131072).  r9 repeats r0's payload bytes.
# ===========================================================================
LADDER = [
    {"name": "m10_r0_canary_2572", "tier": "canary", "kind": "dqpsk",
     "P": 22, "N": 512, "spacing": 4, "min_spacing_hz": 375.0, "rs_k": 159,
     "offset": 98304, "orig_bytes": 8192, "pilot_hz": 4875,
     "reuse_sidecar": "x10_anchor_m8dense375",
     "role": "canary -- MUST reprove 2572 orig-exact or the tape pass is VOID"},
    {"name": "m10_r1_n256_rs179_2632", "tier": "proven", "kind": "dqpsk",
     "P": 10, "N": 256, "spacing": 4, "rs_k": 179,
     "offset": 43008, "orig_bytes": 8192, "pilot_hz": 4500,
     "role": "proven -- m9 m5 config, banked on tape9 by ensemble union"},
    {"name": "m10_r2_n256_rs191_2809", "tier": "proven", "kind": "dqpsk",
     "P": 10, "N": 256, "spacing": 4, "rs_k": 191,
     "offset": 18432, "orig_bytes": 8192, "pilot_hz": 4500,
     "role": "proven -- m9 m6 config, rescued on tape9 by late-window + erasure ladder"},
    {"name": "m10_r3_n256_p11_2896", "tier": "proven", "kind": "dqpsk",
     "P": 11, "N": 256, "spacing": 4, "rs_k": 179,
     "offset": 20480, "orig_bytes": 8192, "pilot_hz": 5250,
     "role": "proven -- m9 m7 config, rescued on tape9; fresh-capture fallback record"},
    {"name": "m10_r4_n256_p11_2896_twin", "tier": "proven", "kind": "dqpsk",
     "P": 11, "N": 256, "spacing": 4, "rs_k": 179,
     "offset": 51200, "orig_bytes": 8192, "pilot_hz": 5250,
     "role": "twin of r3 (m4/m4b convention) -- banks independently, never fused"},
    {"name": "m10_r5_d2x_p18_rs127", "tier": "frontier", "kind": "dense2x_drop",
     "P": 18, "N": 256, "spacing": 2, "skip": 64, "drop_freqs_hz": DROP_P18,
     "rs_k": 127, "offset": 106496, "orig_bytes": 12288, "pilot_hz": 4875,
     "reuse_sidecar": "x10_d2x_p18_rs127",
     "role": "frontier derate -- probe margin 5.2x; sim REJECT pre-registered as prediction-to-test"},
    {"name": "m10_r6_d2x_p21_rs159", "tier": "frontier", "kind": "dense2x_drop",
     "P": 21, "N": 256, "spacing": 2, "skip": 64, "drop_freqs_hz": DROP_P21,
     "rs_k": 159, "offset": 118784, "orig_bytes": 12288, "pilot_hz": 4875,
     "reuse_sidecar": "x10_d2x_p21_rs159",
     "role": "frontier banker -- THE record attempt; probe margin 1.43x (thin), keeps 4500 Hz"},
    {"name": "m10_r7_d2x_p21_rs159_twin", "tier": "frontier", "kind": "dense2x_drop",
     "P": 21, "N": 256, "spacing": 2, "skip": 64, "drop_freqs_hz": DROP_P21,
     "rs_k": 159, "offset": 86016, "orig_bytes": 12288, "pilot_hz": 4875,
     "role": "twin of r6 -- realization insurance on the thinnest-margin attempt"},
    {"name": "m10_r8_d2x_p22_rs179", "tier": "stretch", "kind": "dense2x",
     "P": 22, "N": 256, "spacing": 2, "skip": 64,
     "rs_k": 179, "offset": 131072, "orig_bytes": 12288, "pilot_hz": 4875,
     "reuse_sidecar": "x10_d2x_p22_rs179",
     "role": "stretch -- predicted to FAIL (probe 0.113 > thr 0.089); doubles as full-grid SER diagnostic"},
    {"name": "m10_r9_tail_canary_2572rep", "tier": "probe", "kind": "dqpsk",
     "P": 22, "N": 512, "spacing": 4, "min_spacing_hz": 375.0, "rs_k": 159,
     "offset": 98304, "orig_bytes": 8192, "pilot_hz": 4875,
     "reuse_sidecar": "x10_anchor_m8dense375", "forensic_only": True,
     "role": "FORENSIC ONLY tail canary -- byte-identical r0 repeat at end of tape; "
             "banks NOTHING, triggers NO abort; head-vs-tail differential"},
]


def make_scheme(rung: dict):
    kind = rung["kind"]
    if kind == "dqpsk":
        return DQPSKScheme(rung["P"], rung["N"], rung["spacing"],
                           min_spacing_hz=rung.get("min_spacing_hz", 562.0))
    if kind == "dense2x":
        return Dense2xScheme(rung["P"], skip=rung.get("skip", 64))
    if kind == "dense2x_drop":
        return Dense2xDropScheme(rung["P"], rung["drop_freqs_hz"],
                                 pilot_hz=rung.get("pilot_hz", D2X_PILOT),
                                 skip=rung.get("skip", 64))
    raise ValueError(f"unknown rung kind {kind!r}")


def _codeword_crcs(packed: bytes, rs_k: int) -> list[int]:
    """CRC32 of each RS codeword's MESSAGE bytes (m8/m9 convention). The
    receiver-side miscorrection guard AND the union/rescue acceptance channel."""
    pad = (-len(packed)) % rs_k
    padded = packed + bytes(pad)
    return [zlib.crc32(padded[i:i + rs_k]) & 0xFFFFFFFF
            for i in range(0, len(padded), rs_k)]


# ===========================================================================
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
        "tape": MASTER_ID,
        "master_id": MASTER_ID,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "cass_path": str(CASS),
        "cass_sha256": hashlib.sha256(full).hexdigest(),
        "ladder_seed": LADDER_SEED,
        "rx_window_plan": {
            "primary": "hann256_skip0", "alternate": "rect128_skip64",
            "reason": "Hann(Nw=128) non-orthogonal at 1-bin spacing (probe)"},
        "do_not_print_note": (
            "x10_master10.wav / x10_master10_draft.wav are STALE artifacts of "
            "the REJECTED toneplan-v2 candidate -- DO NOT PRINT. The master10 "
            "tape is THIS file's output: master10.wav."),
        "ws_payloads": [],
    }

    # ---- lead + global up-chirp ----
    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (multitone x2 + 12 s flutter + noisefloor) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # ---- rungs ----
    by_name: dict[str, dict] = {}
    first_frame_audio: dict[str, np.ndarray] = {}
    for rung in LADDER:
        if rung.get("forensic_only"):
            add_raw(_silence(GAP_BEFORE_TAIL_CANARY_S - GAP_S))  # extra pre-r9 gap
        rung_start_pos = pos
        sch = make_scheme(rung)
        orig = full[rung["offset"]: rung["offset"] + rung["orig_bytes"]]
        assert len(orig) == rung["orig_bytes"], rung
        packed, pmeta = pack_payload(orig, algo="auto")
        assert unpack_payload(packed) == orig, f"H9 roundtrip failed for {rung['name']}"

        # ---- verbatim reuse: adopt the already-self-checked x10 section's
        # PACKED bytes (gzip embeds an mtime, so a fresh pack differs at byte
        # 20; byte-identical sections require the original blob) ------------
        if rung.get("reuse_sidecar"):
            ref = (X10_SIDECARS / f"{rung['reuse_sidecar']}.bin").read_bytes()
            assert unpack_payload(ref) == orig, (
                f"{rung['name']}: x10 sidecar {rung['reuse_sidecar']} does not "
                f"unpack to the expected cass slice")
            assert len(ref) == pmeta["packed_len"], (rung["name"], len(ref),
                                                     pmeta["packed_len"])
            packed = ref

        sidecar = SIDECAR_DIR / f"{rung['name']}.bin"
        sidecar.write_bytes(packed)
        sidecar_orig = SIDECAR_DIR / f"{rung['name']}.orig.bin"
        sidecar_orig.write_bytes(orig)

        m_rung = Rung(name=rung["name"], M=rung["P"], K=1,
                      rs_n=RS_N, rs_k=rung["rs_k"], frame_bytes=FRAME_BYTES)
        frames_bits, meta = codec.encode_payload(packed, m_rung)
        frame_starts: list[int] = []
        for fi, fbits in enumerate(frames_bits):
            audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
            if fi == 0:
                first_frame_audio[rung["name"]] = audio
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(FRAME_GAP_S))
        add_gap()

        gross = sch.gross_bps
        net = gross * rung["rs_k"] / RS_N
        eff = net * rung["orig_bytes"] / pmeta["packed_len"]

        entry = {
            "name": rung["name"],
            "kind": rung["kind"],
            "tier": rung["tier"],
            "scheme": sch.name,
            "phy": sch.name,
            "role": rung.get("role", ""),
            "status": "FORENSIC_ONLY" if rung.get("forensic_only") else "ACTIVE",
            "forensic_only": bool(rung.get("forensic_only")),
            "gross_bps": gross,
            "projected_net_bps": 0.0 if rung.get("forensic_only") else net,
            "section_net_bps": net,
            "x_record": 0.0 if rung.get("forensic_only") else round(net / RECORD_BPS, 3),
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
            "dqpsk_params": {
                "P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
                "skip": rung.get("skip"),
                "min_spacing_hz": rung.get("min_spacing_hz",
                                           375.0 if "d2x" in rung["name"] else 562.0),
                "drop_freqs_hz": [float(f) for f in rung.get("drop_freqs_hz", [])],
                "pilot_hz": rung["pilot_hz"]},
            "carrier_freqs_hz": [round(float(f), 1) for f in sch.freqs[sch.data_idx]],
            "pilot_hz_actual": round(float(sch.freqs[sch.pilot_idx]), 1),
        }
        manifest["ws_payloads"].append(entry)
        by_name[rung["name"]] = entry
        sec_s = (pos - rung_start_pos) / SR
        print(f"[build] {rung['name']:28s} {sch.name:26s} RS({RS_N},{rung['rs_k']:3d}) "
              f"gross={gross:6.1f} net={net:7.1f} x{net/RECORD_BPS:4.2f} "
              f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
              f"sec={sec_s:5.1f}s [{rung['tier']}]")

    # ---- r9 byte-identity asserts (forensic differential needs ZERO ambiguity) --
    r0, r9 = by_name["m10_r0_canary_2572"], by_name["m10_r9_tail_canary_2572rep"]
    assert r0["pack"]["sha256_packed"] == r9["pack"]["sha256_packed"], "r9 != r0 payload"
    assert r0["crc32_codewords"] == r9["crc32_codewords"], "r9 != r0 crc table"
    assert np.array_equal(first_frame_audio["m10_r0_canary_2572"],
                          first_frame_audio["m10_r9_tail_canary_2572rep"]), \
        "r9 first-frame audio != r0 (generator non-determinism!)"

    # ---- global down-chirp + tail (>=1 s silence around end chirp per SOP) ----
    add_raw(_silence(1.0))
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()
    add_raw(_silence(TAIL))

    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * 0.70).astype(np.float32)   # SOP peak 0.70
    dur_s = len(audio_full) / SR

    sf.write(str(out_wav), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"\n[build] {out_wav.name} {dur_s:.1f}s ({dur_s / 60:.2f} min), peak 0.70")
    print(f"[build] manifest -> {MANIFEST_PATH} (master_id={MASTER_ID})")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    print("[build] r9 tail canary byte-identity vs r0: VERIFIED")
    print("[build] DO NOT PRINT x10_master10.wav (stale toneplan-v2 reject)")
    return (f"{out_wav.name} {dur_s:.1f}s ({dur_s / 60:.2f} min), "
            f"{len(manifest['ws_payloads'])} rungs")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    print(build(pathlib.Path(args.out)))
