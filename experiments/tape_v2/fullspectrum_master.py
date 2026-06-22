"""fullspectrum_master.py -- build the FULL-SPECTRUM evaluation tape.

ONE stereo master that characterizes a setup across the whole d2x/m10 capability
tier in a SINGLE tape pass:

  * an acoustic / phone capture (summed mono, L=R averaged) recovers the robust
    LOW/MID rungs and reveals the acoustic ceiling;
  * a wired UCA222 (true-stereo, independent L/R) capture recovers all the way up
    to the proven ~9820 bps d2x stereo top.

ARCHITECTURE (lowest-risk: PROVEN d2x/m10 DQPSK family + the proven chirp/sounder
front; ONE global chirp, ONE sync). This is the m10_master.build() multi-section
ladder pattern -- ONE global up-chirp -> front Schroeder sounder -> a LADDER of
d2x-family rung sections (each one a `ws_payloads` entry under the ONE sync) ->
global down-chirp. Decoded by fullspectrum_decode.py via the PROVEN
analyze_master2.global_sync_and_resample + m10_decode._decode_section.

MASTER LAYOUT (stereo, 48 kHz, float):
  [lead 1 s]
  global up-chirp (tx_chirp0)                     <- BOTH channels (per-channel sync)
  0.40 s gap
  front Schroeder sounder (~45 s)                 <- BOTH channels (eval sounder reused)
  0.40 s gap
  L-only crosstalk probe (1000 Hz) / R silent     <- routing + crosstalk (make_d2x_stereo_cal probes)
  0.40 s gap
  R-only crosstalk probe (1700 Hz) / L silent
  0.40 s gap
  LADDER (robust -> aggressive), each rung a d2x-family RS-framed section:
    R0 robust  DQPSK P10 N256 sp4 RS(255,127) ~1868 net   MONO  (same payload L=R)
    R1 mid     DQPSK P10 N256 sp4 RS(255,191) ~2809 net   MONO  (same payload L=R)
    R2 mid-hi  D2X   P18 drop     RS(255,127) ~3362 net   MONO  (same payload L=R)
    R3 top     D2X   P21 drop     RS(255,159) ~4910/ch    STEREO (INDEPENDENT L/R payloads) -> ~9820 stereo
  global down-chirp (tx_chirp1)
  [tail 1 s]
  -> peak-normalize 0.70 (SOP).

The MONO rungs (R0-R2) carry the SAME audio on L and R, so a summed-mono acoustic
capture still recovers them. The TOP rung (R3) carries DIFFERENT seeded payloads on
L vs R: decoding ch0 vs the L payload AND ch1 vs the R payload (both byte-exact)
proves true 2x. Summed to mono, R3 is corrupted by design (the two channels add
incoherently) -- the honest acoustic ceiling.

SCOPE / HONESTY (v1):
  * The truly "superconservative" sub-kbps floor (the BFSK/WS record-holders
    326/562 bps) uses the BFSK/WS PHYs, which have no RS(255,k)+CRC32 frame API
    that decodes through m10_decode._decode_section. Integrating them under this
    one sync was the one risky piece; it is DEFERRED to v2. The conservative floor
    here is the MOST-ROBUST DQPSK rung (R0, P10/RS127), which DOES self-test
    byte-exact. The full eval report-card (SNR/BW/flutter/clock/IMD scoring from
    eval_decode) is likewise a deferred v2 -- this master only carries the sounder
    audio for it (front Schroeder sounder, reused verbatim), not the report logic.
  * No rung is claimed that does not self-test byte-exact (see the build() clean +
    summed-mono self-check and fullspectrum_decode.py).

Seeds (logged): R0=771001 R1=771002 R2=771003  R3_L=771010 R3_R=771011.
Payloads are RAW seeded random bytes (no lzma) -> manifest sec["pack"] is None;
decode via _decode_section directly (not the DOOM decode() wrapper). Per-channel
raw payload sidecars (.bin) + the manifest JSON are TRACKED (cal_d2x convention);
the big stereo WAV is gitignored.

Run:
    python3 experiments/tape_v2/fullspectrum_master.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import warnings

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
DOOM_SHIP = _HERE / "doom_ship"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE, DOOM_SHIP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                    # noqa: E402
from m3_codec import Rung                                   # noqa: E402
import m10_master as m10m                                   # noqa: E402 (make_scheme, _codeword_crcs)
from make_master2 import (                                  # noqa: E402
    GLOBAL_CHIRP_T, _build_sounder, _make_global_chirp, _silence,
)
import make_stereo_cal_master as M                          # noqa: E402 (probe helpers: _tone, PROBE_*)

SR = codec.FS
assert SR == 48_000

MASTER_ID = "fullspectrum_v1"
WAV_PATH = _HERE / "fullspectrum_master.wav"
MANIFEST_PATH = _HERE / "fullspectrum_manifest.json"
SIDECAR_DIR = _HERE / "fullspectrum_sidecars"

# ---- layout constants (m10/eval values, verbatim) -------------------------
LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
PEAK = 0.70
RS_N = 255

# ---- crosstalk-probe lead-in (reuse make_stereo_cal_master params) --------
PROBE_L_HZ = M.PROBE_L_HZ          # 1000 Hz (L only)
PROBE_R_HZ = M.PROBE_R_HZ          # 1700 Hz (R only)
PROBE_DUR = M.PROBE_DUR            # 1.5 s

# ---- the rung ladder (robust -> aggressive), PROVEN m10 d2x/dqpsk family --
# `channel_mode`: "mono"  -> SAME payload on L and R (acoustic-mono recoverable)
#                 "stereo"-> INDEPENDENT payloads on L vs R (true-2x top)
# `payload_bytes`: rounded UP to a whole number of rs_k codewords at build time.
# `frame_bytes`: small (one re-sync per ~frame); the calibration payloads are a
#                few KB so a couple of frames is plenty.
LADDER = [
    {"name": "fs_r0_robust_dqpsk_p10_rs127", "channel_mode": "mono",
     "kind": "dqpsk", "P": 10, "N": 256, "spacing": 4, "min_spacing_hz": 562.0,
     "pilot_hz": 4500, "rs_k": 127, "payload_bytes": 4000, "frame_bytes": 2000,
     "seed": 771001,
     "role": "robust floor -- most flutter-robust DQPSK rung (low P, heavy RS)"},
    {"name": "fs_r1_mid_dqpsk_p10_rs191", "channel_mode": "mono",
     "kind": "dqpsk", "P": 10, "N": 256, "spacing": 4, "min_spacing_hz": 562.0,
     "pilot_hz": 4500, "rs_k": 191, "payload_bytes": 4000, "frame_bytes": 2500,
     "seed": 771002,
     "role": "mid -- m10 r2 config (proven on tape9 via rescue)"},
    {"name": "fs_r2_midhi_d2x_p18_rs127", "channel_mode": "mono",
     "kind": "dense2x_drop", "P": 18, "N": 256, "spacing": 2, "skip": 64,
     "drop": "DROP_P18", "pilot_hz": 4875, "rs_k": 127,
     "payload_bytes": 4000, "frame_bytes": 3000, "seed": 771003,
     "role": "mid-high -- m10 r5 D2X drop (DOOM-mini rate)"},
    {"name": "fs_r3_top_d2x_p21_rs159", "channel_mode": "stereo",
     "kind": "dense2x_drop", "P": 21, "N": 256, "spacing": 2, "skip": 64,
     "drop": "DROP_P21", "pilot_hz": 4875, "rs_k": 159,
     "payload_bytes": 4000, "frame_bytes": 3000,
     "seed_L": 771010, "seed_R": 771011,
     "role": "TOP -- proven D2X_P21_N256_sp2_drop1 RS(255,159), DOOM-tape record; "
             "INDEPENDENT L/R -> true ~9820 bps stereo"},
]

DROPS = {"DROP_P18": m10m.DROP_P18, "DROP_P21": m10m.DROP_P21}


def _rung_scheme(rung: dict):
    """Build the modem scheme for a rung via the FROZEN m10_master.make_scheme."""
    spec = dict(rung)
    if "drop" in spec:
        spec["drop_freqs_hz"] = DROPS[spec["drop"]]
    return m10m.make_scheme(spec)


def _round_to_rs(nbytes: int, rs_k: int) -> int:
    n_cw = max(1, int(round(nbytes / rs_k)))
    return n_cw * rs_k


def _seeded_payload(seed: int, nbytes: int) -> bytes:
    rng = np.random.default_rng(seed)
    return bytes(rng.integers(0, 256, size=nbytes, dtype=np.uint8))


def _encode_rung_body(rung: dict, payload: bytes, sch):
    """Modulate a rung's payload into (audio, manifest-entry-fragments).

    Returns (audio float32, meta, frame_starts_relative, crc32_codewords, net_bps,
    gross_bps). frame_starts_relative are sample offsets relative to the body start
    (the caller adds the absolute body start position)."""
    m_rung = Rung(name=rung["name"], M=rung["P"], K=1,
                  rs_n=RS_N, rs_k=rung["rs_k"], frame_bytes=rung["frame_bytes"])
    frames_bits, meta = codec.encode_payload(payload, m_rung)
    parts: list[np.ndarray] = []
    frame_starts_rel: list[int] = []
    pos = 0
    for fbits in frames_bits:
        audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
        frame_starts_rel.append(pos)
        parts.append(audio)
        pos += len(audio)
        gap = _silence(FRAME_GAP_S)
        parts.append(gap)
        pos += len(gap)
    body = np.concatenate(parts).astype(np.float32)
    gross = float(sch.gross_bps)
    net = gross * rung["rs_k"] / RS_N
    return body, meta, frame_starts_rel, gross, net


def build(out_wav: pathlib.Path = WAV_PATH) -> dict:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)

    # ---- assemble the two channels in lock-step -------------------------------
    L_parts: list[np.ndarray] = []
    R_parts: list[np.ndarray] = []
    pos = 0  # absolute sample position (both channels stay length-aligned)

    def add(sigL: np.ndarray, sigR: np.ndarray) -> None:
        nonlocal pos
        sigL = np.asarray(sigL, dtype=np.float32)
        sigR = np.asarray(sigR, dtype=np.float32)
        assert len(sigL) == len(sigR), (len(sigL), len(sigR))
        L_parts.append(sigL)
        R_parts.append(sigR)
        pos += len(sigL)

    def add_both(sig: np.ndarray) -> None:
        """Same audio on L and R (chirp / sounder / mono rungs)."""
        add(sig, sig)

    def add_gap(d: float = GAP_S) -> None:
        add_both(_silence(d))

    manifest: dict = {
        "SR": SR,
        "tape": MASTER_ID,
        "master_id": MASTER_ID,
        "product": "fullspectrum_evaluation_v1",
        "channels": ["L", "R"],
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "rx_window_plan": {
            "primary": "hann256_skip0", "alternate": "rect128_skip64",
            "reason": "Hann(Nw=128) non-orthogonal at 1-bin spacing (probe)"},
        "crosstalk_probes": {},
        "deferred_v2": [
            "sub-kbps BFSK/WS floor rung (326/562 bps record-holders): no "
            "RS(255,k)+CRC32 frame API through _decode_section",
            "full eval report-card (SNR/BW/flutter/clock/IMD scoring): sounder "
            "audio is present, scoring logic deferred",
        ],
        "ws_payloads": [],
    }

    # ---- lead + global up-chirp (BOTH channels) ----
    add_both(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_both(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (BOTH channels, reused verbatim) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_both(sounder_audio)
    add_gap()

    # ---- crosstalk probes (L-only tone, gap, R-only tone) ----
    probe_amp = 0.5
    tL = M._tone(PROBE_L_HZ, PROBE_DUR, probe_amp)
    tR = M._tone(PROBE_R_HZ, PROBE_DUR, probe_amp)
    sil_probe = _silence(PROBE_DUR)
    l_probe_start = pos
    add(tL, sil_probe)                 # L probe present, R silent
    add_gap()
    r_probe_start = pos
    add(sil_probe, tR)                 # R probe present, L silent
    add_gap()
    pd = int(round(PROBE_DUR * SR))
    manifest["crosstalk_probes"] = {
        "L": {"freq_hz": PROBE_L_HZ, "channel": "L",
              "start_frame": int(l_probe_start), "end_frame": int(l_probe_start + pd)},
        "R": {"freq_hz": PROBE_R_HZ, "channel": "R",
              "start_frame": int(r_probe_start), "end_frame": int(r_probe_start + pd)},
        "probe_amp": probe_amp,
    }

    # ---- the rung ladder ----
    print(f"[build] master_id={MASTER_ID}  ({len(LADDER)} rungs)")
    print(f"[build] {'rung':34s} {'mode':7s} {'phy':28s} {'RS':>9} "
          f"{'net':>8} {'cw':>4} {'sec':>6}")
    for rung in LADDER:
        sch = _rung_scheme(rung)
        rs_k = int(rung["rs_k"])
        body_start = pos

        if rung["channel_mode"] == "mono":
            nbytes = _round_to_rs(rung["payload_bytes"], rs_k)
            payload = _seeded_payload(rung["seed"], nbytes)
            bodyL, meta, fs_rel, gross, net = _encode_rung_body(rung, payload, sch)
            bodyR = bodyL                          # identical audio on both channels
            metaR = meta
            fs_rel_R = fs_rel
            # one sidecar shared by both channels
            scar = SIDECAR_DIR / f"{rung['name']}.bin"
            scar.write_bytes(payload)
            scar_rel = str(scar.relative_to(_HERE))
            scarR_rel = scar_rel
            crc = m10m._codeword_crcs(payload, rs_k)
            crcR = crc
            sha_L = hashlib.sha256(payload).hexdigest()
            sha_R = sha_L
            payload_len_L = len(payload)
            payload_len_R = len(payload)
            seeds = {"seed": rung["seed"]}
        else:  # independent stereo
            nbytes = _round_to_rs(rung["payload_bytes"], rs_k)
            payloadL = _seeded_payload(rung["seed_L"], nbytes)
            payloadR = _seeded_payload(rung["seed_R"], nbytes)
            assert payloadL != payloadR, "stereo rung payloads must differ"
            bodyL, meta, fs_rel, gross, net = _encode_rung_body(rung, payloadL, sch)
            bodyR, metaR, fs_rel_R, _g2, _n2 = _encode_rung_body(rung, payloadR, sch)
            # bodies are identical length (same framing) -- pad defensively
            if len(bodyL) != len(bodyR):
                n = max(len(bodyL), len(bodyR))
                bodyL = np.concatenate([bodyL, np.zeros(n - len(bodyL), np.float32)])
                bodyR = np.concatenate([bodyR, np.zeros(n - len(bodyR), np.float32)])
            scarL = SIDECAR_DIR / f"{rung['name']}.L.bin"
            scarR = SIDECAR_DIR / f"{rung['name']}.R.bin"
            scarL.write_bytes(payloadL)
            scarR.write_bytes(payloadR)
            scar_rel = str(scarL.relative_to(_HERE))
            scarR_rel = str(scarR.relative_to(_HERE))
            crc = m10m._codeword_crcs(payloadL, rs_k)
            crcR = m10m._codeword_crcs(payloadR, rs_k)
            sha_L = hashlib.sha256(payloadL).hexdigest()
            sha_R = hashlib.sha256(payloadR).hexdigest()
            payload_len_L = len(payloadL)
            payload_len_R = len(payloadR)
            seeds = {"seed_L": rung["seed_L"], "seed_R": rung["seed_R"]}

        add(bodyL, bodyR)
        add_gap()

        # absolute frame starts (per channel; identical for mono rungs)
        frame_starts = [int(body_start + f) for f in fs_rel]
        frame_starts_R = [int(body_start + f) for f in fs_rel_R]

        drop_freqs = DROPS[rung["drop"]] if "drop" in rung else []
        entry = {
            "name": rung["name"],
            "kind": rung["kind"],
            "channel_mode": rung["channel_mode"],
            "scheme": sch.name,
            "phy": sch.name,
            "role": rung.get("role", ""),
            "status": "ACTIVE",
            "gross_bps": gross,
            "projected_net_bps": net,
            "section_net_bps": net,
            # RAW payload -> no lzma pack (decode via _decode_section directly)
            "pack": None,
            "payload_sidecar": scar_rel,        # L (and shared, for mono rungs)
            "payload_sidecar_R": scarR_rel,     # R (== L for mono rungs)
            "payload_len": payload_len_L,
            "payload_len_R": payload_len_R,
            "payload_sha256_L": sha_L,
            "payload_sha256_R": sha_R,
            "seeds": seeds,
            "crc32_codewords": crc,             # L codeword CRCs
            "crc32_codewords_R": crcR,          # R codeword CRCs
            "meta": meta,                       # L meta (== R meta; identical framing)
            "meta_R": metaR,
            "frame_starts": frame_starts,       # L frame starts (== R for mono rungs)
            "frame_starts_R": frame_starts_R,
            "dqpsk_params": {
                "P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
                "skip": rung.get("skip"),
                "min_spacing_hz": rung.get("min_spacing_hz", 375.0),
                "drop_freqs_hz": [float(f) for f in drop_freqs],
                "pilot_hz": rung["pilot_hz"],
            },
            "carrier_freqs_hz": [round(float(f), 1) for f in sch.freqs[sch.data_idx]],
            "pilot_hz_actual": round(float(sch.freqs[sch.pilot_idx]), 1),
        }
        manifest["ws_payloads"].append(entry)
        sec_s = (pos - body_start) / SR
        print(f"[build] {rung['name']:34s} {rung['channel_mode']:7s} "
              f"{sch.name:28s} RS({RS_N},{rs_k:3d}) {net:8.1f} "
              f"{meta['n_codewords']:>4} {sec_s:5.1f}s")

    # ---- global down-chirp + tail (>= 1 s silence around end chirp per SOP) ----
    add_both(_silence(1.0))
    manifest["tx_chirp1"] = pos
    add_both(_make_global_chirp(up=False))
    add_gap()
    add_both(_silence(TAIL))

    L = np.concatenate(L_parts).astype(np.float32)
    R = np.concatenate(R_parts).astype(np.float32)
    assert len(L) == len(R)
    stereo = np.column_stack([L, R])
    peak = float(np.max(np.abs(stereo)))
    if peak > 1e-9:
        stereo = (stereo / peak * PEAK).astype(np.float32)   # SOP peak 0.70
    dur_s = stereo.shape[0] / SR

    manifest["duration_seconds"] = dur_s
    sf.write(str(out_wav), stereo, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"\n[build] {out_wav.name}  {dur_s:.1f}s ({dur_s/60:.2f} min) stereo, "
          f"peak {PEAK}  ({stereo.nbytes/1e6:.0f} MB)")
    print(f"[build] manifest -> {MANIFEST_PATH.name}  sidecars -> {SIDECAR_DIR.name}/")
    return {"wav_seconds": dur_s, "wav_path": str(out_wav),
            "manifest_path": str(MANIFEST_PATH), "n_rungs": len(LADDER)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    build(pathlib.Path(args.out))
