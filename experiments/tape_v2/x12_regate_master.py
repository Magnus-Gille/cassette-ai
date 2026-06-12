"""x12_regate_master.py -- assemble the x12-regate ladder (canaries + C3 probe).

Builds x12_master_regate.wav: ONE global sync (chirp pair + sounder, the
m9/m10 architecture) + 3 sections:

  c0  x12_c0_anchor_2572     BYTE-IDENTICAL m10_r0 canary reuse (asserted)
  c1  x12_c1_d2x_4910        BYTE-IDENTICAL m10_r6 canary reuse (asserted)
                             -- the MANDATORY canary pair (prereg canary rule)
  c3  x12_c3_dbpsk_p12_ext   the only GO from the x12 frontier re-gate: a
                             uniform-DBPSK probe (90-deg boundary, 1 bit per
                             carrier per symbol) on 8 rule-picked mid carriers
                             + the 4 >9 kHz ext bins, N256/sp2 grid, pilot
                             4875, RS k from the frozen rate rule.

The DBPSK pieces are NEW x12 classes that SUBCLASS the frozen machinery
(import, never edit): TX inherits the Schroeder-phase dense2x modulator
verbatim -- only the bit<->phase mapping changes (q in {0,2} -> dphi in
{0,pi}); RX subclasses ResamplingPLLDemod overriding ONLY the decision
boundary (round to the pi grid instead of pi/2).

print_authorized starts FALSE ("pending"); x12_frontier_regate.py final sets
it after the no-channel self-check + the 8-seed blocking screen adjudicate.

Run:  python3 x12_regate_master.py [--out x12_master_regate.wav]
Deterministic (LADDER_SEED logged).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
from m10_master import (                                   # noqa: E402
    make_scheme as m10_make_scheme, _codeword_crcs,
    MANIFEST_PATH as M10_MANIFEST_PATH, RS_N, FRAME_BYTES, GAP_S,
    FRAME_GAP_S, LEAD, TAIL,
)
from x10_b_aggr_05_dense2x_master import (                 # noqa: E402
    Dense2xDropScheme, D2X_N, D2X_SKIP)
from x9_resampling_pll import ResamplingPLLDemod           # noqa: E402
from h4_dqpsk import FS                                    # noqa: E402

SR = codec.FS
CASS = codec.CASS
M10_SIDECARS = _HERE / "sidecars_m10"

OUT_DIR = _HERE
WAV_PATH = OUT_DIR / "x12_master_regate.wav"
MANIFEST_PATH = OUT_DIR / "x12_master_regate_manifest.json"
SIDECAR_DIR = OUT_DIR / "sidecars_x12_regate"
REGATE_JSON = _HERE / "results" / "x12_frontier_regate.json"

MASTER_ID = "x12_regate"
LADDER_SEED = 20260612
RECORD_BPS = 5791.1764705882354


# ===========================================================================
# DBPSK on the dense2x drop geometry: 1 bit/carrier/symbol, dphi in {0, pi}.
# TX = the frozen Schroeder modulator verbatim (q*(pi/2) with q in {0,2}).
# ===========================================================================
class X12DBPSKDropScheme(Dense2xDropScheme):
    def __init__(self, P: int, drop_freqs_hz, *, pilot_hz: float = 4875.0,
                 skip: int = D2X_SKIP):
        super().__init__(P, drop_freqs_hz, pilot_hz=pilot_hz, skip=skip)
        self.bits_per_sym = self.P                 # 1 bit per data carrier
        self.gross_bps = self.bits_per_sym / (D2X_N / FS)
        self.name = f"DBPSK_P{P}_N{D2X_N}_sp2_ext"

    def bits_to_quadrants(self, bits: np.ndarray) -> np.ndarray:
        """Carrier-block mapping (same RS-friendly structure as DQPSK):
        data carrier j carries the j-th contiguous nd-bit block; bit b ->
        quadrant 2b -> dphi in {0, pi}."""
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        nd = len(bits) // bps
        bm = bits.reshape(self.P, nd)
        return (bm.T.astype(int)) * 2

    def quadrants_to_bits(self, q: np.ndarray) -> np.ndarray:
        q = np.asarray(q, int) % 4
        return ((q.T) // 2).astype(np.uint8).reshape(-1)


class X12DBPSKDemod(ResamplingPLLDemod):
    """The frozen resampling-PLL front-end with ONLY the decision boundary
    changed: round dphi to the pi grid (DBPSK, 90-deg boundary) instead of
    pi/2 (DQPSK).  Same structure as the parent _decide, including the
    one-shot DD timing refinement and the no-truth quality metric."""

    def _decide(self, c, dtau, refine: bool, *, return_quality: bool = False):
        sch = self.sch
        fd = sch.freqs[sch.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])
        dphi = np.angle(d[:, sch.data_idx])
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
        q = (np.round(dphi / np.pi).astype(int) % 2) * 2
        if refine:
            res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            num = (res * fd[None, :]).sum(axis=1)
            den = (fd ** 2).sum()
            dtau_res = num / (2 * np.pi * den)
            dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
            q = (np.round(dphi2 / np.pi).astype(int) % 2) * 2
            dphi = dphi2
        if return_quality:
            resd = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            return q, float(np.sqrt(np.mean(resd ** 2)))
        return q


# ===========================================================================
def make_scheme_x12(rung: dict):
    if rung["kind"] == "dbpsk_drop":
        return X12DBPSKDropScheme(rung["P"], rung["drop_freqs_hz"],
                                  pilot_hz=rung.get("pilot_hz", 4875.0),
                                  skip=rung.get("skip") or D2X_SKIP)
    return m10_make_scheme(rung)


def _rx_dbpsk(sec: dict, geometry: str):
    p = sec["dqpsk_params"]
    skip = 0 if geometry == "hann256_skip0" else 64
    sch = X12DBPSKDropScheme(p["P"], p["drop_freqs_hz"],
                             pilot_hz=p["pilot_hz"], skip=skip)
    if geometry == "rect128_skip64":
        sch._win = np.ones(sch.Nw)
    return sch


def dbpsk_frontends(sec: dict):
    """The frozen x12 DBPSK receiver sweep (prereg section 6)."""
    plan = [("hann256_skip0", "ema", 0.7), ("hann256_skip0", "ema", 0.6),
            ("hann256_skip0", "ema", 0.8), ("hann256_skip0", "pll", 30.0),
            ("rect128_skip64", "ema", 0.7)]
    out = []
    for geo, fe, val in plan:
        sch = _rx_dbpsk(sec, geo)
        if fe == "ema":
            dem = X12DBPSKDemod(sch, front_end="ema", ema_alpha=val)
            label = f"{geo}_ema{val}"
        else:
            dem = X12DBPSKDemod(sch, pll_bw_hz=val, front_end="pll")
            label = f"{geo}_pll{val:g}"
        out.append((label, lambda w, nd, d=dem: d.demod(w, nd)))
    return out


# ===========================================================================
def _ladder():
    """c0/c1 are frozen m10 twins; c3 geometry/k come from the adjudication
    (rule-derived, builder refuses anything but a GO verdict)."""
    adj = json.loads(REGATE_JSON.read_text())["stages"]["adjudication"]
    c3 = adj["per_candidate"]["x12_c3_dbpsk_p12_ext"]
    assert c3["verdict"].startswith("GO"), "C3 is not GO -- nothing to build"
    k_star = int(c3["G_C2"]["rate_rule_k_star"])
    drops = [float(f) for f in c3["drop_freqs_hz"]]
    return [
        {"name": "x12_c0_anchor_2572", "tier": "canary", "kind": "dqpsk",
         "P": 22, "N": 512, "spacing": 4, "min_spacing_hz": 375.0,
         "rs_k": 159, "offset": 98304, "orig_bytes": 8192, "pilot_hz": 4875,
         "reuse_sidecar": "m10_r0_canary_2572",
         "m10_twin": "m10_r0_canary_2572",
         "role": "canary -- must reprove 2572 orig-exact on any capture"},
        {"name": "x12_c1_d2x_4910", "tier": "canary", "kind": "dense2x_drop",
         "P": 21, "N": 256, "spacing": 2, "skip": 64,
         "drop_freqs_hz": [750.0], "rs_k": 159, "offset": 118784,
         "orig_bytes": 12288, "pilot_hz": 4875,
         "reuse_sidecar": "m10_r6_d2x_p21_rs159",
         "m10_twin": "m10_r6_d2x_p21_rs159",
         "role": "canary -- best-proven d2x banker (4910 net), mandatory"},
        {"name": "x12_c3_dbpsk_p12_ext", "tier": "probe", "kind": "dbpsk_drop",
         "P": int(c3["carrier_table"] and 12), "N": 256, "spacing": 2,
         "skip": 64, "drop_freqs_hz": drops, "rs_k": k_star,
         "offset": 16384, "orig_bytes": 2048, "pilot_hz": 4875,
         "role": f"x12 GO probe -- DBPSK 90-deg boundary, 8 mids + 4 ext "
                 f"bins, RS(255,{k_star}) by the frozen rate rule; banks the "
                 f">9 kHz DBPSK SER map"},
    ]


def build(out_wav: pathlib.Path = WAV_PATH) -> str:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    full = CASS.read_bytes()
    assert len(full) == 153823, f"unexpected cassette-LLM size {len(full)}"
    m10_manifest = json.loads(M10_MANIFEST_PATH.read_text())
    m10_secs = {s["name"]: s for s in m10_manifest["ws_payloads"]}
    ladder = _ladder()

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
        "print_block_reason": "pending: no-channel self-check + 8-seed "
                              "blocking screen (x12_frontier_regate final)",
        "prereg": "x10_dossier/x12_frontier_prereg.md (frozen "
                  "2026-06-12T15:54Z)",
        "tx_chirp0": None, "tx_chirp1": None,
        "sounder_sections": [],
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "cass_path": str(CASS),
        "cass_sha256": hashlib.sha256(full).hexdigest(),
        "ladder_seed": LADDER_SEED,
        "rx_window_plan": {
            "primary": "hann256_skip0", "alternate": "rect128_skip64",
            "reason": "the proven d2x plan; the DBPSK probe sweeps the same "
                      "geometries at the 90-deg boundary"},
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

    for rung in ladder:
        rung_start_pos = pos
        sch = make_scheme_x12(rung)
        orig = full[rung["offset"]: rung["offset"] + rung["orig_bytes"]]
        assert len(orig) == rung["orig_bytes"], rung
        packed, pmeta = pack_payload(orig, algo="auto")
        assert unpack_payload(packed) == orig, f"H9 roundtrip {rung['name']}"

        if rung.get("reuse_sidecar"):
            ref = (M10_SIDECARS / f"{rung['reuse_sidecar']}.bin").read_bytes()
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
                "drop_freqs_hz": [float(f)
                                  for f in rung.get("drop_freqs_hz", [])],
                "pilot_hz": rung["pilot_hz"]},
            "carrier_freqs_hz": [round(float(f), 1)
                                 for f in sch.freqs[sch.data_idx]],
            "pilot_hz_actual": round(float(sch.freqs[sch.pilot_idx]), 1),
        }
        manifest["ws_payloads"].append(entry)
        sec_s = (pos - rung_start_pos) / SR
        print(f"[build] {rung['name']:24s} {sch.name:24s} "
              f"RS({RS_N},{rung['rs_k']:3d}) gross={gross:6.1f} "
              f"net={net:7.1f} frames={meta['n_frames']:3d} "
              f"cw={meta['n_codewords']:3d} sec={sec_s:5.1f}s [{rung['tier']}]")

    # ---- canary byte-identity vs master10 (the m10 reuse convention) -------
    for name, twin in (("x12_c0_anchor_2572", "m10_r0_canary_2572"),
                       ("x12_c1_d2x_4910", "m10_r6_d2x_p21_rs159")):
        a = next(s for s in manifest["ws_payloads"] if s["name"] == name)
        b = m10_secs[twin]
        assert a["pack"]["sha256_packed"] == b["pack"]["sha256_packed"], name
        assert a["crc32_codewords"] == b["crc32_codewords"], name
        assert a["pack"]["sha256_orig"] == b["pack"]["sha256_orig"], name

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
    print(f"\n[build] {out_wav.name} {dur_s:.1f}s ({dur_s/60:.2f} min), "
          f"peak 0.70; canary byte-identity vs m10: VERIFIED")
    print("[build] print_authorized=False (pending self-check + sim screen)")
    return f"{out_wav.name} {dur_s:.1f}s, {len(manifest['ws_payloads'])} sections"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    print(build(pathlib.Path(args.out)))
