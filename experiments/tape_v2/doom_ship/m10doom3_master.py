"""m10doom3_master.py -- assemble the DOOM v3 (Freedoom E1 + SFX + saves) ship tape.

ONE physical recording, ONE payload: payloads/doom/dist/doom_cassette_v3.html,
encoded at EXACTLY the tape10-proven r6 rung (the standing 4910-net record,
landed 0/72 failed codewords on the FIRST front-end branch TWICE on tape10):

    m10_r6_d2x_p21_rs159   D2X_P21_N256_sp2_drop1   RS(255,159)
    21 carriers x 2 bits x 187.5 sym/s = gross 7875.0 -> net 4910.3 bps
    drop {750 Hz}, pilot 4875 Hz, min_spacing 375 Hz, Schroeder TX,
    0.25 s per-frame chirp preamble, 0.12 s frame gap.

This CANNOT be a thin rebind of m10doom_master (the v1 module hardcodes the
m9_m8_dense375 DQPSK rung via load_rung asserts), so it copies the v1 build
structure and swaps in the r6 dense2x_drop scheme, importing everything else
READ-ONLY: pack_doom/unpack_doom (the H9PC lzma bridge) from m10doom_master,
make_scheme/_codeword_crcs/LADDER from m10_master, and the m9 tape skeleton
from make_master2. The r6 parameters are HARD-ASSERTED against both
m10_master.LADDER and the burned master10_manifest.json r6 entry (scheme name,
carrier grid, pilot, gross/net) -- bit-identical modem to the rung that
survived the real tape10.

FRAME_BYTES re-freeze (v3 PHYSICS DELTA -- sim-gated, see m10doom3_simgate.py):
  As burned on tape10 the r6 rung used frame_bytes=510 (0.78 s frames, 42 %
  per-frame overhead: 12000-sample preamble + 5760-sample gap + 1 ref symbol)
  = 2833 bps on packed bytes -- a 1.5 MB payload would need ~74 min. frame_bytes
  is a native m3_codec knob (the decoder is fully meta-driven via
  meta["frame_bits"]; m3-era rungs shipped FB 2000-4000):
      FB=5100  -> 4575 bps packed -> 45.9 min for THIS payload  (over C90 side)
      FB=10200 -> 4736 bps packed -> 44.8 min for THIS payload  (fits)
  The v3 artifact packs to 1,573,668 B (1.501 MB), so FB=5100 misses the
  45.0-min physical C90 side; v3 ships FB=10200 (10.7 s frames). The long-frame
  physics (PLL/EMA timing hold over 10.7 s vs the proven 0.78 s) is NEW at this
  rung and is gated BEFORE printing by m10doom3_simgate.py: clean synth +
  channel-sim marginal cells (x11 pattern: dg* x aac{off,on} x
  clk{0,+0.10,+0.17,+0.25}%) must all land 0 failed codewords through the v3
  receiver with the x11 rescue machinery armed.
  Burst arithmetic stays excellent: the GLOBAL column-major interleave spreads
  byte j of every codeword across the stream, so one fully lost 10.7 s frame
  costs only ceil(10200/n_cw) ~ 2 bytes per RS(255,159) codeword (48
  correctable). Uniform SER, not dropouts, is the failure mode.

Tape skeleton (m9/m10/m10doom, verbatim):
    lead 1 s -> global up-chirp -> front Schroeder sounder -> ONE continuous
    payload section (frames + 0.12 s gaps) -> global down-chirp -> tail 1 s,
    peak-normalized 0.70 (SOP).

Gates (m10doom2 convention): C60 side 29 min and C90-with-margin 43 min are
MEASURED AND REPORTED; the HARD assert is the physical C90 side (45.0 min).

Run:
    python3 experiments/tape_v2/doom_ship/m10doom3_master.py
        [--html PATH] [--out PATH]

Outputs (all in doom_ship/):
    m10doom3_master.wav       the ship tape (FLOAT, 48 kHz, peak 0.70 -- SOP)
    m10doom3_manifest.json    decode manifest (m9/m10 schema, single section)
    m10doom3_dense375.bin     packed payload sidecar (H9PC lzma blob)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

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
import m10doom_master as v1  # noqa: E402 (blessed v1 module: lzma bridge, read-only)
import m10_master as m10m  # noqa: E402 (FROZEN master10 builder, read-only)
from make_master2 import (  # noqa: E402
    GLOBAL_CHIRP_T,
    _build_sounder,
    _make_global_chirp,
    _silence,
)

SR = codec.FS
assert SR == 48_000

HTML_PATH = ROOT / "payloads" / "doom" / "dist" / "doom_cassette_v3.html"
SECTION_NAME = "m10doom3_dense375"
R6_NAME = "m10_r6_d2x_p21_rs159"

WAV_PATH = _HERE / "m10doom3_master.wav"
MANIFEST_PATH = _HERE / "m10doom3_manifest.json"
SIDECAR_PATH = _HERE / f"{SECTION_NAME}.bin"
MASTER10_MANIFEST = TAPE_V2 / "master10_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
RS_N = 255
FRAME_BYTES = 10_200                  # v3 re-freeze (sim-gated; see docstring)

C60_SIDE_BUDGET_MIN = 29.0            # reported (bonus target)
C90_MARGIN_BUDGET_MIN = 43.0          # reported (C90 side with margin)
C90_SIDE_PHYSICAL_MIN = 45.0          # HARD gate: must fit a physical C90 side

# packed-payload budget (re-frozen 2026-06-12 from measured tape10 physics at
# FB=10200: 4736 bps on packed bytes): reported, never asserted -- the binding
# physical gate is the 45.0-min side.
PACKED_TARGET_MB = 1.45
PACKED_HARD_MB = 1.539                # FB=10200 ceiling in ~2600 payload-s

# re-export the proven H9PC lzma bridge (v1, read-only)
pack_doom = v1.pack_doom
unpack_doom = v1.unpack_doom


# ===========================================================================
def r6_rung() -> dict:
    """The r6 ladder entry, verbatim from the FROZEN m10_master.LADDER, with
    hard assertions on every parameter that defines the 4910-net record."""
    rung = next(r for r in m10m.LADDER if r["name"] == R6_NAME)
    assert rung["kind"] == "dense2x_drop", rung
    assert (rung["P"], rung["N"], rung["spacing"], rung["skip"]) == (21, 256, 2, 64), rung
    assert [float(f) for f in rung["drop_freqs_hz"]] == [750.0], rung
    assert rung["rs_k"] == 159 and rung["pilot_hz"] == 4875, rung
    return rung


def make_r6_scheme():
    """Build the r6 scheme through the FROZEN m10_master.make_scheme factory
    and assert config equality against the burned master10_manifest r6 entry
    (the tape that landed 0/72 failed codewords twice)."""
    rung = r6_rung()
    sch = m10m.make_scheme(rung)
    assert sch.name == "D2X_P21_N256_sp2_drop1", sch.name
    assert abs(sch.gross_bps - 7875.0) < 1e-9, sch.gross_bps
    net = sch.gross_bps * rung["rs_k"] / RS_N
    assert abs(net - 4910.294117647059) < 1e-6, net

    man = json.loads(MASTER10_MANIFEST.read_text())
    ref = next(s for s in man["ws_payloads"] if s["name"] == R6_NAME)
    assert ref["kind"] == "dense2x_drop" and ref["scheme"] == sch.name, ref["scheme"]
    dp = ref["dqpsk_params"]
    assert (int(dp["P"]), int(dp["N"]), int(dp["spacing"]), int(dp["skip"])) \
        == (21, 256, 2, 64), dp
    assert [float(f) for f in dp["drop_freqs_hz"]] == [750.0], dp
    assert float(dp["min_spacing_hz"]) == 375.0 and int(dp["pilot_hz"]) == 4875, dp
    got_freqs = [round(float(f), 1) for f in sch.freqs[sch.data_idx]]
    assert got_freqs == [round(float(f), 1) for f in ref["carrier_freqs_hz"]], \
        "carrier grid != burned master10 r6 grid"
    assert round(float(sch.freqs[sch.pilot_idx]), 1) == float(ref["pilot_hz_actual"]) \
        == 4875.0
    assert abs(float(ref["projected_net_bps"]) - net) < 1e-6
    return sch, rung, ref


# ===========================================================================
# the generic tape assembler (shared by the ship build and the sim gate's
# mini-master so the gate exercises the IDENTICAL transmit path)
# ===========================================================================
def build_tape(packed: bytes, *,
               out_wav: pathlib.Path,
               manifest_path: pathlib.Path,
               sidecar_path: pathlib.Path,
               payload_sidecar_rel: str,
               section_name: str,
               frame_bytes: int = FRAME_BYTES,
               tape_id: str = "m10doom3",
               role: str = "DOOM-v3-ship-single-payload",
               manifest_extra: dict | None = None,
               entry_extra: dict | None = None,
               verbose: bool = True) -> dict:
    sch, rung, _ref = make_r6_scheme()

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_bytes(packed)
    # the decoder (m10_decode / x11 rescue) resolves payload_sidecar relative
    # to tape_v2 -- the manifest path MUST round-trip to the sidecar on disk.
    assert (TAPE_V2 / payload_sidecar_rel).resolve() == sidecar_path.resolve(), \
        (payload_sidecar_rel, str(sidecar_path))

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
        "tape": tape_id,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "rx_window_plan": {
            "primary": "hann256_skip0", "alternate": "rect128_skip64",
            "reason": "Hann(Nw=128) non-orthogonal at 1-bin spacing (probe)"},
        "ws_payloads": [],
    }
    if manifest_extra:
        manifest.update(manifest_extra)

    # ---- lead + global up-chirp ----
    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (same as m8/m9/m10) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # ---- THE payload section (one continuous run of r6 frames) ----
    section_start = pos
    m_rung = Rung(name=section_name, M=rung["P"], K=1,
                  rs_n=RS_N, rs_k=rung["rs_k"], frame_bytes=frame_bytes)
    frames_bits, meta = codec.encode_payload(packed, m_rung)
    frame_starts: list[int] = []
    for fi, fbits in enumerate(frames_bits):
        audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
        frame_starts.append(pos)
        add_raw(audio)
        add_raw(_silence(FRAME_GAP_S))
        if verbose and (fi + 1) % 50 == 0:
            print(f"[{tape_id}] modulated {fi + 1}/{len(frames_bits)} frames",
                  flush=True)
    section_end = pos
    add_gap()

    gross = sch.gross_bps
    net = gross * rung["rs_k"] / RS_N
    payload_seconds = (section_end - section_start) / SR

    entry = {
        "name": section_name,
        "kind": "dense2x_drop",
        "scheme": sch.name,
        "phy": sch.name,
        "role": role,
        "status": "SHIP",
        "gross_bps": gross,
        "projected_net_bps": net,
        "effective_bps": None,                     # set by the ship wrapper
        "payload_sidecar": payload_sidecar_rel,
        "payload_len": len(packed),
        "section_start": section_start,
        "section_end": section_end,
        "pack": None,                              # set by caller (entry_extra)
        "crc32_codewords": m10m._codeword_crcs(packed, rung["rs_k"]),
        "meta": meta,
        "frame_starts": frame_starts,
        "dqpsk_params": {
            "P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
            "skip": rung["skip"],
            "min_spacing_hz": 375.0,
            "drop_freqs_hz": [float(f) for f in rung["drop_freqs_hz"]],
            "pilot_hz": rung["pilot_hz"],
        },
        "carrier_freqs_hz": [round(float(f), 1) for f in sch.freqs[sch.data_idx]],
        "pilot_hz_actual": round(float(sch.freqs[sch.pilot_idx]), 1),
    }
    if entry_extra:
        entry.update(entry_extra)
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

    sf.write(str(out_wav), audio_full, SR, subtype="FLOAT")
    manifest["wav_seconds"] = dur_s
    manifest_path.write_text(json.dumps(manifest, indent=2, default=float))

    if verbose:
        print(f"[{tape_id}] modem    {sch.name} RS({RS_N},{rung['rs_k']}) "
              f"FB={frame_bytes} gross={gross:.1f} net={net:.1f} bps")
        print(f"[{tape_id}] frames   {meta['n_frames']} frames, "
              f"{meta['n_codewords']} codewords, payload section "
              f"{payload_seconds:.1f}s "
              f"({len(packed) * 8 / payload_seconds:.1f} bps on packed bytes)")
        print(f"[{tape_id}] tape     {out_wav.name}: {dur_s:.1f}s "
              f"({dur_s / 60:.2f} min), peak 0.70")
        print(f"[{tape_id}] manifest -> {manifest_path}")
    return {"wav_seconds": dur_s, "wav_minutes": dur_s / 60.0,
            "payload_seconds": payload_seconds,
            "packed_bps": len(packed) * 8 / payload_seconds,
            "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
            "net_bps": net, "meta": meta, "entry": entry}


# ===========================================================================
def build(html_path: pathlib.Path = HTML_PATH,
          out_wav: pathlib.Path = WAV_PATH) -> dict:
    raw = html_path.read_bytes()
    sha_orig = hashlib.sha256(raw).hexdigest()

    # ---- pack (lzma via the v1 h9 bridge) + BLOCKING roundtrip ----
    packed, pmeta = pack_doom(raw)
    assert unpack_doom(packed) == raw, "H9 pack/unpack roundtrip failed"

    packed_mb = pmeta["packed_len"] / (1024 * 1024)
    print(f"[m10doom3] payload  {html_path.name}: {len(raw)} B raw -> "
          f"{pmeta['packed_len']} B packed ({pmeta['algo']}, "
          f"-{pmeta['reduction_pct']:.1f}%) = {pmeta['packed_len'] / 1024:.1f} KB "
          f"= {packed_mb:.3f} MB")
    if packed_mb > PACKED_TARGET_MB:
        print(f"[m10doom3] WARN     packed {packed_mb:.3f} MB exceeds the "
              f"re-frozen {PACKED_TARGET_MB:.2f} MB target "
              f"(FB=10200 ceiling {PACKED_HARD_MB:.3f} MB); the binding gate "
              f"is the {C90_SIDE_PHYSICAL_MIN:.0f}-min physical side below")

    res = build_tape(
        packed,
        out_wav=out_wav,
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        payload_sidecar_rel=str(SIDECAR_PATH.relative_to(TAPE_V2)),
        section_name=SECTION_NAME,
        frame_bytes=FRAME_BYTES,
        tape_id="m10doom3",
        manifest_extra={"html_path": str(html_path), "html_sha256": sha_orig},
        entry_extra={
            "pack": {
                "algo": pmeta["algo"],
                "orig_len": pmeta["orig_len"],
                "packed_len": pmeta["packed_len"],
                "reduction_pct": pmeta["reduction_pct"],
                "sha256_orig": sha_orig,
                "sha256_packed": hashlib.sha256(packed).hexdigest(),
            },
            "effective_bps": None,  # patched below once payload_seconds known
        },
    )

    # effective bps on the HTML (incl. compression + framing) -- m10doom conv.
    eff = len(raw) * 8 / res["payload_seconds"]
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest["ws_payloads"][0]["effective_bps"] = eff
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    m = res["wav_minutes"]
    res.update({
        "packed_len": pmeta["packed_len"], "algo": pmeta["algo"],
        "effective_bps": eff, "sha256_orig": sha_orig,
        "fits_c60_side": m <= C60_SIDE_BUDGET_MIN,
        "fits_c90_margin": m <= C90_MARGIN_BUDGET_MIN,
        "fits_c90_side": m <= C90_SIDE_PHYSICAL_MIN,
    })
    print(f"[m10doom3] eff      {eff:.1f} bps on the HTML "
          f"({len(raw)} B in {res['payload_seconds']:.1f} s of payload audio)")
    print(f"[m10doom3] sides    C90 physical ({C90_SIDE_PHYSICAL_MIN:.0f} min): "
          f"{'OK' if res['fits_c90_side'] else 'OVER'}   "
          f"C90 w/ margin ({C90_MARGIN_BUDGET_MIN:.0f} min): "
          f"{'OK' if res['fits_c90_margin'] else 'OVER'}   "
          f"C60 side ({C60_SIDE_BUDGET_MIN:.0f} min): "
          f"{'OK (bonus)' if res['fits_c60_side'] else 'no'}")
    assert m <= C90_SIDE_PHYSICAL_MIN, (
        f"tape {m:.2f} min exceeds the physical C90 side "
        f"({C90_SIDE_PHYSICAL_MIN} min) -- DO NOT PRINT")
    print("[m10doom3] REMINDER: do not print before m10doom3_simgate.py "
          "reports PASS (FB=10200 long-frame physics gate) and the "
          "m10doom3_decode.py no-channel selfcheck is BYTE-EXACT.")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=str(HTML_PATH))
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    build(pathlib.Path(args.html), pathlib.Path(args.out))
