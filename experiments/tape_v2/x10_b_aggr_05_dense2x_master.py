"""x10_b_aggr_05_dense2x_master.py -- assemble the master10-dense2x tape.

STEP 2 of the B-aggr-05 candidate (probe gate = GO, see
results/x10_b_aggr_05_dense2x_probe.json): time-densification 2x on the proven
375 Hz carrier grid -- DQPSK at N=256 / spacing=2 / skip=64 (187.5 sym/s, the
m8_dense375 tone plan at double symbol rate).

PROBE-DRIVEN DESIGN (all measured on the REAL tape9/m8tape captures):
  * The plan's literal Hann(Nw=128) receiver is NON-ORTHOGONAL at the 1-bin
    carrier spacing (measured ~50-70 % SER).  TX is unchanged; the receiver
    uses Hann(256)/skip0 (2-bin spacing, soft guard; measured mean SER 3.85 %)
    with rect(128)/skip64 as the sweep alternate (5.8 %).
  * Carrier kill-list from measured per-carrier SER at the dense2x geometry:
    750 Hz (35.5 %, prev-symbol echo ISI at short windows -- same dc0 failure
    as m4-m7), 4500 Hz (18.8 %, static deck notch), 5625 Hz (12.4 %, notch),
    6750 Hz (4.5 %).  P18 drops all four; P21 drops 750 Hz only.
  * Schroeder-phased initial symbol (phi0_k = -pi k^2/nc): the differential RX
    is invariant to per-carrier static phase, but the all-zero-phase initial
    symbol of h4.modulate sets the frame peak -> Schroeder lowers crest factor
    so the per-frame peak normalization yields more average drive (the 5.4 dB
    under-drive found by the headroom analysis).  No soft clipping is added:
    the channel is hysteresis-IMD dominated; TX clipping would add coherent
    IMD on the 375 Hz grid for a fraction-of-dB further PAPR gain.

LADDER (one tape, robust-early -> stretch-late, m9_master architecture):
  A   x10_anchor_m8dense375  DQPSK P22 N512 sp4 RS159  reprove-2572 anchor
  R1  x10_d2x_p18_rs127      D2X  P18 N256 sp2 RS127  derate    net 3361.8
  R2  x10_d2x_p21_rs159      D2X  P21 N256 sp2 RS159  banker    net 4910.3
  R3  x10_d2x_p22_rs179      D2X  P22 N256 sp2 RS179  stretch   net 5791.2

Per-rung: h9-packed slice of stories260K_int4.cass, RS(255,k) m3_codec frames,
0.25 s chirp preamble + 0.12 s gaps, CRC32-per-codeword manifest guard,
sha256(orig)+sha256(packed) for the pre-registered orig-exact claim discipline.

Run:
    python3 x10_b_aggr_05_dense2x_master.py [--out x10_master_dense2x.wav]
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

import m3_codec as codec                       # noqa: E402
from m3_codec import Rung                      # noqa: E402
from h4_dqpsk import DQPSKScheme, FS as DQ_FS  # noqa: E402
from m9_master import DropNullDQPSK            # noqa: E402
from h9_payload_codec import pack_payload, unpack_payload  # noqa: E402
from make_master2 import (                     # noqa: E402
    GLOBAL_CHIRP_T, _build_sounder, _make_global_chirp, _silence,
)

SR = codec.FS
assert SR == DQ_FS == 48_000
CASS = codec.CASS

OUT_DIR = _HERE
WAV_PATH = OUT_DIR / "x10_master_dense2x.wav"
MANIFEST_PATH = OUT_DIR / "x10_master_dense2x_manifest.json"
SIDECAR_DIR = OUT_DIR / "sidecars_x10_dense2x"

LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
RS_N = 255
FRAME_BYTES = 510

D2X_N = 256
D2X_SPACING = 2
D2X_SKIP = 64           # TX-side: only sets Nw for the scheme asserts
D2X_MIN_SPACING = 375.0
PILOT_HZ = 4875.0       # the proven m8_dense375 pilot (grid center)

# probe-measured kill lists (results/x10_b_aggr_05_dense2x_probe.json gate)
DROP_P18 = [750.0, 4500.0, 5625.0, 6750.0]
DROP_P21 = [750.0]


# ===========================================================================
# Schroeder-phased TX mixin: h4_dqpsk.DQPSKScheme.modulate verbatim with a
# per-carrier static initial phase phi0 (differential-RX invariant).
# ===========================================================================
class _SchroederTXMixin:
    def _phi0(self):
        nc = self.P + 1
        k = np.arange(nc, dtype=np.float64)
        return -np.pi * k * k / nc

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        q = self.bits_to_quadrants(bits)
        nd = q.shape[0]
        total = nd + 1
        nc = self.P + 1
        theta = np.zeros((total, nc))
        theta[0] = self._phi0()
        for i in range(1, total):
            theta[i] = theta[i - 1]
            theta[i, self.data_idx] += q[i - 1] * (np.pi / 2.0)
        t = np.arange(total * self.N) / DQ_FS
        body = np.zeros(total * self.N)
        for k in range(nc):
            ph = 2 * np.pi * self.freqs[k] * t + np.repeat(theta[:, k], self.N)
            body += self.tx_amp[k] * np.sin(ph)
        audio = np.concatenate([self._preamble, body])
        pk = np.max(np.abs(audio))
        return (audio / pk * 0.70).astype(np.float32)


class Dense2xScheme(_SchroederTXMixin, DQPSKScheme):
    """Full contiguous 375 Hz grid at N=256/sp2 (P22 -> 750..9000 Hz,
    pilot_idx=nc//2 -> 4875 Hz natively)."""

    def __init__(self, P: int, *, skip: int = D2X_SKIP):
        super().__init__(P, D2X_N, D2X_SPACING, skip=skip,
                         min_spacing_hz=D2X_MIN_SPACING)
        self.name = f"D2X_P{P}_N{D2X_N}_sp{D2X_SPACING}"


class Dense2xDropScheme(_SchroederTXMixin, DropNullDQPSK):
    """375 Hz grid at N=256/sp2 with measured-bad carriers dropped."""

    def __init__(self, P: int, drop_freqs_hz, *, pilot_hz: float = PILOT_HZ,
                 skip: int = D2X_SKIP):
        super().__init__(P, D2X_N, D2X_SPACING, drop_freqs_hz,
                         pilot_hz=pilot_hz, skip=skip,
                         min_spacing_hz=D2X_MIN_SPACING)
        self.name = f"D2X_P{P}_N{D2X_N}_sp{D2X_SPACING}_drop{len(drop_freqs_hz)}"


# ===========================================================================
def make_scheme(rung: dict):
    kind = rung["kind"]
    if kind == "dqpsk":           # the anchor (proven m8_dense375 geometry)
        return DQPSKScheme(rung["P"], rung["N"], rung["spacing"],
                           min_spacing_hz=rung.get("min_spacing_hz", 562.0))
    if kind == "dense2x":
        return Dense2xScheme(rung["P"], skip=rung.get("skip", D2X_SKIP))
    if kind == "dense2x_drop":
        return Dense2xDropScheme(rung["P"], rung["drop_freqs_hz"],
                                 pilot_hz=rung.get("pilot_hz", PILOT_HZ),
                                 skip=rung.get("skip", D2X_SKIP))
    raise ValueError(f"unknown rung kind {kind!r}")


LADDER = [
    {"name": "x10_anchor_m8dense375", "kind": "dqpsk", "P": 22, "N": 512,
     "spacing": 4, "min_spacing_hz": 375.0, "rs_k": 159, "offset": 98304,
     "orig_bytes": 8192, "pilot_hz": 4875,
     "role": "anchor -- must reprove 2572 orig-exact or the tape pass is void",
     "status": "ACTIVE"},
    {"name": "x10_d2x_p18_rs127", "kind": "dense2x_drop", "P": 18, "N": 256,
     "spacing": 2, "skip": 64, "drop_freqs_hz": DROP_P18, "rs_k": 127,
     "offset": 106496, "orig_bytes": 12288, "pilot_hz": 4875,
     "role": "derate -- geometry validation + ~3362 net bank",
     "status": "ACTIVE"},
    {"name": "x10_d2x_p21_rs159", "kind": "dense2x_drop", "P": 21, "N": 256,
     "spacing": 2, "skip": 64, "drop_freqs_hz": DROP_P21, "rs_k": 159,
     "offset": 118784, "orig_bytes": 12288, "pilot_hz": 4875,
     "role": "banker -- record attempt ~4910 net",
     "status": "ACTIVE"},
    {"name": "x10_d2x_p22_rs179", "kind": "dense2x", "P": 22, "N": 256,
     "spacing": 2, "skip": 64, "rs_k": 179,
     "offset": 131072, "orig_bytes": 12288, "pilot_hz": 4875,
     "role": "stretch -- keeps 750 Hz; probe predicts byte-ER 0.113 > thr 0.089",
     "status": "ACTIVE"},
]

LADDER_SEED = 20260612   # deterministic build; logged per convention


def _codeword_crcs(packed: bytes, rs_k: int) -> list[int]:
    pad = (-len(packed)) % rs_k
    padded = packed + bytes(pad)
    return [zlib.crc32(padded[i:i + rs_k]) & 0xFFFFFFFF
            for i in range(0, len(padded), rs_k)]


def _crest_db(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2))) + 1e-30
    return round(20 * np.log10(float(np.max(np.abs(x))) / rms), 2)


# ===========================================================================
def build(out_wav: pathlib.Path = WAV_PATH) -> str:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    full = CASS.read_bytes()
    assert len(full) == 153823, f"unexpected cassette-LLM size {len(full)}"

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
        "tape": "master10_dense2x",
        "candidate": "B-aggr-05-dense2x",
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
        assert unpack_payload(packed) == orig, f"H9 roundtrip failed {rung['name']}"

        sidecar = SIDECAR_DIR / f"{rung['name']}.bin"
        sidecar.write_bytes(packed)
        sidecar_orig = SIDECAR_DIR / f"{rung['name']}.orig.bin"
        sidecar_orig.write_bytes(orig)

        m_rung = Rung(name=rung["name"], M=rung["P"], K=1,
                      rs_n=RS_N, rs_k=rung["rs_k"], frame_bytes=FRAME_BYTES)
        frames_bits, meta = codec.encode_payload(packed, m_rung)
        frame_starts: list[int] = []
        crest = None
        for fbits in frames_bits:
            audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), np.float32)
            if crest is None:
                crest = _crest_db(audio[len(sch._preamble):])
            frame_starts.append(pos)
            add_raw(audio)
            add_raw(_silence(FRAME_GAP_S))
        add_gap()

        gross = sch.gross_bps
        net = gross * rung["rs_k"] / RS_N
        eff = net * rung["orig_bytes"] / pmeta["packed_len"]

        entry = {
            "name": rung["name"], "kind": rung["kind"],
            "scheme": sch.name, "phy": sch.name,
            "role": rung.get("role", ""), "status": rung.get("status", "ACTIVE"),
            "gross_bps": gross, "projected_net_bps": net,
            "x_record": round(net / 2572.1, 3),
            "effective_bps": eff,
            "crest_factor_body_db": crest,
            "payload_sidecar": str(sidecar.relative_to(OUT_DIR)),
            "payload_orig_sidecar": str(sidecar_orig.relative_to(OUT_DIR)),
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
                "min_spacing_hz": rung.get("min_spacing_hz", D2X_MIN_SPACING),
                "drop_freqs_hz": rung.get("drop_freqs_hz", []),
                "pilot_hz": rung["pilot_hz"]},
            "carrier_freqs_hz": [round(float(f), 1)
                                 for f in sch.freqs[sch.data_idx]],
            "pilot_hz_actual": round(float(sch.freqs[sch.pilot_idx]), 1),
        }
        manifest["ws_payloads"].append(entry)
        sec_s = (pos - rung_start_pos) / SR
        print(f"[build] {rung['name']:24s} {sch.name:24s} RS({RS_N},{rung['rs_k']:3d}) "
              f"gross={gross:6.1f} net={net:6.1f} x{net/2572.1:4.2f} "
              f"frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d} "
              f"crest={crest}dB sec={sec_s:5.1f}s")

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
    print(f"[build] manifest -> {MANIFEST_PATH.name}, sidecars -> {SIDECAR_DIR.name}/")
    return f"{out_wav.name} {dur_s:.1f}s ({dur_s/60:.2f} min), {len(LADDER)} rungs"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    print(build(pathlib.Path(args.out)))
