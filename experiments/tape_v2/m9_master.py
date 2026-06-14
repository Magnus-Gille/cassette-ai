"""m9_master.py -- assemble master9.wav: the master9 deliverable tape.

ONE physical recording, ONE global sync (chirp pair + front sounder), then the
10-rung master9 ladder (MASTER9_PLAN.md s1), two diagnostic probes, robust-early
-> stretch-late:

  M0  reprove-934     DQPSK P10 N512 sp8  RS127  proven record (canary)   933.8
  M1  thin-159        DQPSK P10 N512 sp8  RS159  near-certain record #1   1169.1
  M2  thin-191        DQPSK P10 N512 sp8  RS191  near-certain record #2   1404.4
  M3  drop-null-9c    DQPSK P9  N512 sp8  RS159  drop 3750 Hz null        1052.2
  M4  N256 CENTER     DQPSK P10 N256 sp4  RS159  short-symbol 2x bet      2338.2
  M4b N256 var        DQPSK P10 N256 sp4  RS159  2nd realization (var.)   2338.2
  M5  N256 rs179      DQPSK P10 N256 sp4  RS179  N256 stretch            2632.4
  M6  N256 rs191      DQPSK P10 N256 sp4  RS191  N256 cliff-bracket      2808.8
  M7  N256 P11 9000   DQPSK P11 N256 sp4  RS179  +carrier top probe      2895.6
  M8  dense-375 HOLD  DQPSK P22 N512 sp4  RS159  375 Hz flutter-ICI HOLD 2572.1
  M9a freq-diff       FDQPSK P11 N512 sp8 RS159  timing-immune lottery   1169.1

Architecture follows m8_master.py EXACTLY where possible:
  * global chirp0 (up) -> front Schroeder sounder -> P1 -> P2 -> rungs -> chirp1 (down).
  * each section carries its own params + an h9-PACKED slice of stories260K_int4.cass
    at a staggered offset, RS(255,k)-framed (m3_codec), per-frame 0.25 s chirp
    preamble + 0.12 s gap, with a CRC32-per-codeword manifest miscorrection guard.
  * DQPSK sections (incl. the M3 drop-null variant) decode via h4_dqpsk.DQPSKScheme
    / DropNullDQPSK; M9a via x9_freqdiff.FreqDiffDQPSKScheme. m9_decode reconstructs
    every section from the manifest.

DIAGNOSTIC PROBES (MASTER9_PLAN s3, ~28 s, decode-only, no manifest/FEC dependency):
  P1  repeated-sounder stationary-null map (3x 4 s Schroeder back-to-back, ~12 s)
  P2a 8 s continuous 4500 Hz pilot tone (re-anchor 5-23.4 Hz jitter)
  P2b 8 s 10-carrier Schroeder multitone level-ramp (-12,-9,-6,-3 dBFS, AM/AM knee)

M8 is the ONE rung needing the frozen-code change: h4_dqpsk.DQPSKScheme is built
with min_spacing_hz=375 ONLY for M8 (375 Hz spacing); every other rung uses the
default 562 floor (bit-identical to the proven record). M8 is status=HOLD; whether
it is burned onto the physical tape is the Ship phase's call (built here regardless
so the tape is ready either way).

Run:
    python3 experiments/tape_v2/m9_master.py [--no-m8] [--out master9_draft.wav]
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
from h4_dqpsk import DQPSKScheme, FS as DQ_FS  # noqa: E402
from h9_payload_codec import pack_payload, unpack_payload  # noqa: E402
from make_master2 import (  # noqa: E402
    GLOBAL_CHIRP_T,
    _build_sounder,
    _make_global_chirp,
    _schroeder_multitone,
    _silence,
    _steady_tone,
)
from x9_freqdiff import FreqDiffDQPSKScheme  # noqa: E402

SR = codec.FS
assert SR == DQ_FS == 48_000
CASS = codec.CASS

OUT_DIR = _HERE
LADDER_PATH = _HERE / "m9_ladder.json"
SIDECAR_DIR = OUT_DIR / "sidecars_m9"
WAV_PATH = OUT_DIR / "master9.wav"          # FINAL tape (Ship phase). Draft via --out.
MANIFEST_PATH = OUT_DIR / "master9_manifest.json"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
RS_N = 255
FRAME_BYTES = 510

# ---- probe sounder freqs (mirror the front sounder's Schroeder probe) ----
SOUNDER_FREQS = np.round(np.geomspace(300, 11000, 64)).astype(int).tolist()


# ===========================================================================
# M3 drop-null DQPSK: the proven P10 N512 sp8 frequency plan with the 3750 Hz
# carrier REMOVED (9 data carriers + pilot). Subclass overrides ONLY the carrier
# geometry; modulate/demod (and the resampling-PLL/EMA front-ends) operate on the
# overridden self.freqs/data_idx/pilot_idx/tx_amp unchanged.
# ===========================================================================
class DropNullDQPSK(DQPSKScheme):
    """DQPSK on the N512 sp8 grid with a list of data carriers DROPPED (e.g. the
    3750 Hz stationary deck null, R2 s0: 35 % of all raw errors). Builds P data
    carriers placed on the proven grid skipping `drop_freqs_hz`, pilot at 4500 Hz.

    P = number of REMAINING data carriers (9 for M3). The base DQPSKScheme is
    constructed with this P (so bits_per_sym, the (nd,P) quadrant matrix, the
    carrier-block bit mapping, and gross_bps are all correct), then freqs/bins/
    pilot_idx/data_idx/tx_amp are overridden to the custom geometry.
    """

    def __init__(self, P: int, N: int, spacing: int, drop_freqs_hz, *,
                 pilot_hz: float = 4500.0, skip=None, min_spacing_hz: float = 562.0):
        # base scheme with P data carriers (placeholder contiguous geometry)
        super().__init__(P, N, spacing, skip=skip, min_spacing_hz=min_spacing_hz)
        df = SR / N
        b0 = int(round(750.0 / df))
        # full comb the record uses: P+len(drop)+1 carriers contiguous from 750 Hz
        n_drop = len(drop_freqs_hz)
        nc_full = P + n_drop + 1
        bins_full = b0 + spacing * np.arange(nc_full)
        freqs_full = bins_full * df
        pilot_idx_full = int(np.argmin(np.abs(freqs_full - pilot_hz)))
        drop_set = {round(float(f)) for f in drop_freqs_hz}
        keep = []
        for k in range(nc_full):
            if k == pilot_idx_full:
                continue
            if round(float(freqs_full[k])) in drop_set:
                continue
            keep.append(k)
        assert len(keep) == P, (len(keep), P, drop_set)
        # final carrier set = pilot + kept data carriers, sorted by frequency
        idx = sorted(keep + [pilot_idx_full])
        new_freqs = freqs_full[idx]
        new_bins = bins_full[idx]
        new_pilot = idx.index(pilot_idx_full)
        # override geometry
        self.freqs = new_freqs.astype(np.float64)
        self.bins = new_bins.astype(int)
        self.pilot_idx = int(new_pilot)
        self.data_idx = np.array([i for i in range(len(idx)) if i != new_pilot])
        self.name = f"DQ_P{P}_N{N}_sp{spacing}_dropnull"
        self.dropped_freqs_hz = [float(f) for f in drop_freqs_hz]
        # recompute TX pre-emphasis on the NEW freqs (same published H(f) curve)
        import real_channel_sim as rcs
        params = rcs.load_params()
        Hf = params["Hf_magnitude"]
        fm = np.asarray(Hf["sounder_freqs_master3"], float)
        Hd = np.asarray(Hf["H_db_master3"], float)
        Hl = 10.0 ** (np.interp(self.freqs, fm, Hd) / 20.0)
        Hl = Hl / (Hl.max() + 1e-12)
        self.tx_amp = 1.0 / np.clip(Hl, 0.05, None)
        self.tx_amp = self.tx_amp / self.tx_amp.max()


# ===========================================================================
# Scheme factory: build the right modem for a ladder rung.
# ===========================================================================
def make_scheme(rung: dict):
    kind = rung["kind"]
    if kind == "dqpsk":
        msh = rung.get("min_spacing_hz", 562.0)
        return DQPSKScheme(rung["P"], rung["N"], rung["spacing"], min_spacing_hz=msh)
    if kind == "dqpsk_dropnull":
        return DropNullDQPSK(rung["P"], rung["N"], rung["spacing"],
                             rung["drop_freqs_hz"], pilot_hz=rung["pilot_hz"])
    if kind == "freqdiff":
        return FreqDiffDQPSKScheme(rung["P"], rung["N"], rung["spacing"],
                                   pilot_hz=rung["pilot_hz"])
    raise ValueError(f"unknown rung kind {kind!r}")


def _codeword_crcs(packed: bytes, rs_k: int) -> list[int]:
    """CRC32 of each RS codeword's MESSAGE bytes (m8 pattern). Receiver-side
    miscorrection guard -- no truth leak."""
    pad = (-len(packed)) % rs_k
    padded = packed + bytes(pad)
    return [zlib.crc32(padded[i:i + rs_k]) & 0xFFFFFFFF
            for i in range(0, len(padded), rs_k)]


# ===========================================================================
# Diagnostic probes (MASTER9_PLAN s3). Decode-only, no manifest/FEC dependency.
# Each returns (audio, manifest_entry) where the entry records its span(s) so
# m9_decode can locate the probe regions without a payload sidecar.
# ===========================================================================
def _build_probe_p1(pos0: int):
    """P1 -- repeated-sounder stationary-null map: 3x 4 s Schroeder back-to-back."""
    parts, spans, pos = [], [], pos0
    n_rep = 3
    for rep in range(n_rep):
        g = _silence(0.3)
        parts.append(g); pos += len(g)
        mt = _schroeder_multitone(SOUNDER_FREQS, 4.0, 0.45)
        spans.append({"rep": rep, "start": int(pos), "length": int(len(mt))})
        parts.append(mt); pos += len(mt)
        g = _silence(0.3)
        parts.append(g); pos += len(g)
    audio = np.concatenate(parts).astype(np.float32)
    entry = {"kind": "probe_p1_null_map", "n_repeats": n_rep,
             "sounder_freqs": SOUNDER_FREQS, "spans": spans,
             "seconds_each": 4.0}
    return audio, entry, pos


def _build_probe_p2(pos0: int):
    """P2 -- (a) 8 s 4500 Hz pilot tone + (b) 8 s 10-carrier level-ramp."""
    parts, pos = [], pos0
    # (a) steady 4500 Hz pilot
    g = _silence(0.3); parts.append(g); pos += len(g)
    pilot = _steady_tone(4500.0, 8.0, 0.50)
    a_start = pos
    parts.append(pilot); pos += len(pilot)
    a_len = len(pilot)
    g = _silence(0.3); parts.append(g); pos += len(g)
    # (b) 10-carrier Schroeder multitone level-ramp: 4 amplitudes (-12..-3 dBFS),
    # 2 s each. The Schroeder multitone is peak-normalized to 1.0 internally; we
    # scale to each target dBFS PRE-tape so the capture measures IMD vs drive.
    ramp_carriers = [750, 1500, 2250, 3000, 3750, 5250, 6000, 6750, 7500, 8250]
    amps_dbfs = [-12.0, -9.0, -6.0, -3.0]
    ramp_spans = []
    for db in amps_dbfs:
        g = _silence(0.2); parts.append(g); pos += len(g)
        amp = 10.0 ** (db / 20.0)
        mt = _schroeder_multitone(ramp_carriers, 2.0, amp)
        ramp_spans.append({"amp_dbfs": db, "start": int(pos), "length": int(len(mt))})
        parts.append(mt); pos += len(mt)
        g = _silence(0.2); parts.append(g); pos += len(g)
    audio = np.concatenate(parts).astype(np.float32)
    entry = {"kind": "probe_p2_jitter_imd",
             "pilot": {"freq_hz": 4500.0, "start": int(a_start), "length": int(a_len),
                       "seconds": 8.0},
             "level_ramp": {"carriers_hz": ramp_carriers, "spans": ramp_spans}}
    return audio, entry, pos


# ===========================================================================
def build(out_wav: pathlib.Path = WAV_PATH, include_m8: bool = True) -> str:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    ladder = json.loads(LADDER_PATH.read_text())
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
        "tape": "master9",
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "cass_path": str(CASS),
        "cass_sha256": hashlib.sha256(full).hexdigest(),
        "probes": {},
        "ladder_seed": ladder.get("seed"),
        "include_m8": include_m8,
        "ws_payloads": [],
    }

    # ---- lead + global up-chirp ----
    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (same as m8) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # ---- diagnostic probes P1, P2 (right after the front sounder) ----
    p1_audio, p1_entry, pos2 = _build_probe_p1(pos)
    add_raw(p1_audio)
    assert pos == pos2, (pos, pos2)
    manifest["probes"]["P1"] = p1_entry
    add_gap()
    p2_audio, p2_entry, pos3 = _build_probe_p2(pos)
    add_raw(p2_audio)
    assert pos == pos3, (pos, pos3)
    manifest["probes"]["P2"] = p2_entry
    add_gap()

    # ---- rungs ----
    rung_secs: list[tuple[str, float]] = []
    for rung in ladder["rungs"]:
        if rung["name"] == "m9_m8_dense375" and not include_m8:
            manifest["ws_payloads"].append(
                {"name": rung["name"], "kind": rung["kind"], "skipped": True,
                 "status": rung.get("status"), "role": rung.get("role")})
            continue
        rung_start_pos = pos
        sch = make_scheme(rung)
        orig = full[rung["offset"]: rung["offset"] + rung["orig_bytes"]]
        assert len(orig) == rung["orig_bytes"], rung
        packed, pmeta = pack_payload(orig, algo="auto")
        assert unpack_payload(packed) == orig, f"H9 roundtrip failed for {rung['name']}"

        sidecar = SIDECAR_DIR / f"{rung['name']}.bin"          # PACKED blob
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

        # scheme-specific carrier metadata
        if rung["kind"] == "freqdiff":
            data_freqs = [round(float(f), 1) for f in sch.freqs[sch.chain_idx]]
            extra = {"freqdiff_params": {
                        "P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
                        "pilot_hz": rung["pilot_hz"]},
                     "chain_freqs_hz": data_freqs,
                     "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1),
                     "null_pair_idx": [int(j) for j in np.where(sch.null_pair)[0]]}
        else:
            data_freqs = [round(float(f), 1) for f in sch.freqs[sch.data_idx]]
            extra = {"dqpsk_params": {
                        "P": rung["P"], "N": rung["N"], "spacing": rung["spacing"],
                        "min_spacing_hz": rung.get("min_spacing_hz", 562.0),
                        "drop_freqs_hz": rung.get("drop_freqs_hz", []),
                        "pilot_hz": rung["pilot_hz"]},
                     "carrier_freqs_hz": data_freqs,
                     "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1)}

        entry = {
            "name": rung["name"],
            "kind": rung["kind"],
            "scheme": sch.name,
            "phy": sch.name,
            "role": rung.get("role", ""),
            "status": rung.get("status", "ACTIVE"),
            "risk": rung.get("risk", ""),
            "expected_verdict": rung.get("expected_verdict", ""),
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
            **extra,
        }
        manifest["ws_payloads"].append(entry)
        sec_s = (pos - rung_start_pos) / SR
        rung_secs.append((rung["name"], sec_s))

        print(
            f"[build] {rung['name']:24s} {sch.name:22s} RS({RS_N},{rung['rs_k']:3d}) "
            f"gross={gross:6.1f} net={net:6.1f} "
            f"orig={rung['orig_bytes']} packed={pmeta['packed_len']} "
            f"({pmeta['algo']},-{pmeta['reduction_pct']:.1f}%) "
            f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
            f"sec={sec_s:5.1f}s [{rung.get('status','ACTIVE')}]"
        )

    # ---- global down-chirp + tail ----
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
    print(f"[build] probes P1+P2 ~{(p1_audio.shape[0]+p2_audio.shape[0])/SR:.1f}s")
    print(f"[build] manifest -> {MANIFEST_PATH}")
    print(f"[build] sidecars -> {SIDECAR_DIR}")
    n_active = sum(1 for e in manifest["ws_payloads"] if not e.get("skipped"))
    return (
        f"{out_wav.name} {dur_s:.1f}s ({dur_s / 60:.2f} min), "
        f"{n_active} rungs + P1 + P2"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-m8", action="store_true",
                    help="exclude the M8 dense-375 HOLD rung from the tape")
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    print(build(pathlib.Path(args.out), include_m8=not args.no_m8))
