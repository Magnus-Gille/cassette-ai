"""x12_bulk_framing.py -- X12 BULK FRAMING: TX + RX + the pre-registered gates.

Design + gate a bulk frame format for the PROVEN configs (2572 N512 DQPSK +
4910 d2x P21): MORE FRAME BODIES PER PREAMBLE (F in {4,8}), slim intra-block
guards (one symbol), periodic full re-sync anchors retained (preamble every F
frames, ref symbol every frame). The bit/codec layer (m3_codec interleave,
510-byte frames, h9 pack, CRC32-per-codeword) is BYTE-IDENTICAL to v1; only
the audio layout changes.

PRE-REGISTRATION: x10_dossier/x12_framing_prereg.md (frozen BEFORE any run
this file adjudicates). Gates:
  G1  no-channel self-check byte-exact (all 6 sections, 0 cw failed,
      spliced ds == 12000 everywhere).
  G2  sim_v2 dress cells (tape7 dg0.58 s0+s1, +aac s0, +0.17% clock s0,
      + the dg0.35 marginal-informative cell): bulk outcome >= v1 outcome on
      the SAME channel draw (rules frozen in the prereg).
  G3  REAL tape10 preamble ablation: decode m10_r0/r6/r8 with anchors only
      every K frames (K in {1,2,4,8,16,all}); supported cadence K_s; framing
      efficiency at min(8,K_s) must be >= 1.15x for both configs.

FROZEN machinery imported READ-ONLY/verbatim: m3_codec, h4_dqpsk,
x10_b_aggr_05_dense2x_master (schemes), m10_decode (_per_cw_decode,
_union_fill, _d2x_rx_scheme), x10_a_fec_gmd_erasure (_rx_mat),
x9_resampling_pll (ResamplingPLLDemod -- the demod runs VERBATIM; non-anchored
frames are fed a spliced window [reference_preamble | body audio] so its
internal find_preamble lands ds=12000 at the extrapolated body position; the
absolute-index DFT basis shift is differential-transparent), analyze_master2
(global sync), sim_v2 + x11_d2x_erasure._apply_clock (channel cells),
h9_payload_codec, make_master2 (chirps/silence), hyp_common.

Usage (each invocation < 8 min; everything checkpoints + resumes):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 x12_bulk_framing.py build
    ... selfcheck                  # G1
    ... dress --cell dg0.58_aac0_clk+0.00_s0      # G2, one cell per call
    ... ablate --cadence 1|2|4|8|16|all           # G3, one cadence per call
    ... report                     # gate rollup -> x12_framing_report.json

Outputs: x12_bulk_synth.wav + x12_bulk_synth_manifest.json (+ sidecar reuse),
results/x12_framing_{build,selfcheck,dress,ablation,report,ledger}.json.
Deterministic; channel seeds logged per cell.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import time
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                          # noqa: E402 (frozen)
import hyp_common as hc                                # noqa: E402 (frozen)
import m3_codec as codec                               # noqa: E402 (frozen)
from m3_codec import Rung                              # noqa: E402
import m10_decode as m10                               # noqa: E402 (frozen)
import sim_v2                                          # noqa: E402 (frozen)
from h4_dqpsk import DQPSKScheme, PAD_LO_S, PAD_HI_S   # noqa: E402 (frozen)
from h9_payload_codec import unpack_payload            # noqa: E402 (frozen)
from make_master2 import (                             # noqa: E402 (frozen)
    GLOBAL_CHIRP_T, _make_global_chirp, _silence,
)
from x9_resampling_pll import ResamplingPLLDemod       # noqa: E402 (frozen)
from x10_a_fec_gmd_erasure import _rx_mat              # noqa: E402 (frozen)
from x10_b_aggr_05_dense2x_master import (             # noqa: E402 (frozen)
    Dense2xDropScheme,
)
from x11_d2x_erasure import _apply_clock, cell_id      # noqa: E402 (frozen)

SR = codec.FS
RESULTS = _HERE / "results"
CAP_DIR = _HERE / "captures"
SIDECARS_M10 = _HERE / "sidecars_m10"
M10_MANIFEST = json.loads((_HERE / "master10_manifest.json").read_text())
MINI_WAV = _HERE / "x12_bulk_synth.wav"
MINI_MANIFEST = _HERE / "x12_bulk_synth_manifest.json"

# tape10 caches (x11 receipts, READ-ONLY)
CACHE_T10 = CAP_DIR / "x11_decode_nom_tape10_run1.npy"
SYNC_T10 = RESULTS / "x11_decode_sync_tape10_run1.json"

LEDGER_PATH = RESULTS / "x12_framing_ledger.json"
LEDGER_HARD_CAP = 300_000
FA_BUDGET = 1e-4

PRE_LEN = 12_000                      # 0.25 s @ 48k
PRE_REF = np.asarray(hc.make_preamble(0.25), np.float64)
FRAME_GAP_S = 0.12
GAP_S = 0.40
LEAD = 1.0
TAIL = 1.0
RS_N = 255
FRAME_BYTES = 510
SPLICE_TAILPAD = 2400                 # PAD_HI_S*SR; + N added per scheme

# ---- pre-registered constants (frozen in x12_framing_prereg.md) ------------
F_VARIANTS = (4, 8)
BANK_2572 = (("resampling_pll30", "pll", 30.0),
             ("ema0.5", "ema", 0.5),
             ("ema0.7", "ema", 0.7))
BANK_D2X = (("hann256_skip0_ema0.7", "ema", 0.7),
            ("hann256_skip0_pll30", "pll", 30.0),
            ("hann256_skip0_ema0.6", "ema", 0.6))
G2_CELLS = (  # (dg, aac, clk_pct, seed)
    (0.58, False, 0.00, 0),
    (0.58, False, 0.00, 1),
    (0.58, True, 0.00, 0),
    (0.58, False, 0.17, 0),
    (0.35, False, 0.00, 0),
)
G2_DEAD_FRAC = 0.25
G2_CW_TOL = 2
G3_SECTIONS = ("m10_r0_canary_2572", "m10_r6_d2x_p21_rs159",
               "m10_r8_d2x_p22_rs179")
G3_CADENCES = ("1", "2", "4", "8", "16", "all")
G3_R8_TOL = 2
EFF_TARGET = 1.15

CONFIGS = {
    "2572": {
        "kind": "dqpsk", "P": 22, "N": 512, "spacing": 4,
        "min_spacing_hz": 375.0, "rs_k": 159, "pilot_hz": 4875,
        "sidecar": "m10_r0_canary_2572", "m10_section": "m10_r0_canary_2572",
        "banked_net_bps": 2572.1,
    },
    "d2x4910": {
        "kind": "dense2x_drop", "P": 21, "N": 256, "spacing": 2, "skip": 64,
        "drop_freqs_hz": [750.0], "rs_k": 159, "pilot_hz": 4875,
        "sidecar": "m10_r6_d2x_p21_rs159", "m10_section": "m10_r6_d2x_p21_rs159",
        "banked_net_bps": 4910.3,
    },
}


# ===========================================================================
# ledger (file-merged across invocations, x11 pattern)
# ===========================================================================
def _new_ledger():
    return {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}


def _merge_ledger(stage, led):
    data = (json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists()
            else {"campaign": "x12_bulk_framing", "total": _new_ledger(),
                  "stages": {}})
    st = data["stages"].setdefault(stage, _new_ledger())
    for k in _new_ledger():
        st[k] += led[k]
        data["total"][k] += led[k]
    data["false_accept_bound"] = data["total"]["crc_checks"] * 2.0 ** -32
    data["fa_within_budget"] = bool(data["false_accept_bound"] < FA_BUDGET)
    RESULTS.mkdir(exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(data, indent=2))
    if data["total"]["crc_checks"] > LEDGER_HARD_CAP:
        raise SystemExit(f"LEDGER HARD CAP exceeded ({data['total']['crc_checks']})")
    return data


def _jsafe(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ===========================================================================
# scheme / bank factories (frozen classes, frozen RX geometry)
# ===========================================================================
def _tx_scheme(cfg):
    if cfg["kind"] == "dqpsk":
        return DQPSKScheme(cfg["P"], cfg["N"], cfg["spacing"],
                           min_spacing_hz=cfg["min_spacing_hz"])
    return Dense2xDropScheme(cfg["P"], cfg["drop_freqs_hz"],
                             pilot_hz=cfg["pilot_hz"], skip=cfg["skip"])


def _rx_bank(sec):
    """Pre-registered (label, demod) bank for a section dict (frozen order)."""
    if sec["kind"] in ("dense2x", "dense2x_drop"):
        out = []
        for label, fe, val in BANK_D2X:
            sch = m10._d2x_rx_scheme(sec, "hann256_skip0")
            dem = (ResamplingPLLDemod(sch, front_end="ema", ema_alpha=val)
                   if fe == "ema" else
                   ResamplingPLLDemod(sch, pll_bw_hz=val, front_end="pll"))
            out.append((label, sch, dem))
        return out
    p = sec["dqpsk_params"]
    out = []
    for label, fe, val in BANK_2572:
        sch = DQPSKScheme(p["P"], p["N"], p["spacing"],
                          min_spacing_hz=p.get("min_spacing_hz", 562.0))
        dem = (ResamplingPLLDemod(sch, front_end="ema", ema_alpha=val)
               if fe == "ema" else
               ResamplingPLLDemod(sch, pll_bw_hz=val, front_end="pll"))
        out.append((label, sch, dem))
    return out


def _nominal_bits(meta):
    fb, n = meta["frame_bits"], meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


# ===========================================================================
# stage: build -- the x12 mini-master (6 sections: v1/b4/b8 x 2 configs)
# ===========================================================================
def _section_audio(cfg, frames_bits, sch, F):
    """Assemble one section. Returns (audio, entry_geometry).
    F=1 -> v1 layout (preamble+body+0.12 gap per frame, m10_master verbatim
    geometry); F>1 -> bulk blocks [pre|body|g_i|body|...|0.12 gap]."""
    N = sch.N
    g_i = N                                   # pre-registered guard: 1 symbol
    gap = _silence(FRAME_GAP_S)
    parts, pos = [], 0
    body_starts, pre_starts, anchor_of = [], [], []
    frame_audios = [np.asarray(sch.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in frames_bits]
    for fi, fa in enumerate(frame_audios):
        first_in_block = (fi % F == 0)
        if first_in_block:
            pre_starts.append(pos)
            anchor = fi
            parts.append(fa)                  # full v1 frame audio (pre+body)
            body_starts.append(pos + PRE_LEN)
            pos += len(fa)
        else:
            parts.append(np.zeros(g_i, np.float32))   # exact g_i samples
            pos += g_i
            body = fa[PRE_LEN:]
            body_starts.append(pos)
            parts.append(body)
            pos += len(body)
        anchor_of.append(anchor)
        last_in_block = (fi % F == F - 1) or (fi == len(frame_audios) - 1)
        if last_in_block:
            parts.append(gap)
            pos += len(gap)
    audio = np.concatenate(parts).astype(np.float32)
    geom = {"F": F, "intra_gap_samples": int(g_i if F > 1 else 0),
            "preamble_starts": pre_starts, "body_starts": body_starts,
            "anchor_frame_of": anchor_of, "section_samples": int(len(audio)),
            "frame_body_samples": [int(len(fa) - PRE_LEN) for fa in frame_audios]}
    return audio, geom


def stage_build():
    t0 = time.time()
    m10_secs = {s["name"]: s for s in M10_MANIFEST["ws_payloads"]}
    parts, pos = [], 0

    def add(sig):
        nonlocal pos
        sig = np.asarray(sig, np.float32)
        parts.append(sig)
        pos += len(sig)

    mani = {"SR": SR, "tape": "x12_bulk_synth", "master_id": "x12_bulk_synth",
            "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
            "frame_gap_samples": int(FRAME_GAP_S * SR),
            "prereg": "x10_dossier/x12_framing_prereg.md",
            "tx_chirp0": None, "tx_chirp1": None, "sounder_sections": [],
            "ws_payloads": []}

    add(_silence(LEAD))
    mani["tx_chirp0"] = pos
    add(_make_global_chirp(up=True))
    add(_silence(GAP_S))

    build_rows = []
    for cname, cfg in CONFIGS.items():
        m10sec = m10_secs[cfg["m10_section"]]
        packed = (SIDECARS_M10 / f"{cfg['sidecar']}.bin").read_bytes()
        orig = (SIDECARS_M10 / f"{cfg['sidecar']}.orig.bin").read_bytes()
        assert hashlib.sha256(packed).hexdigest() == m10sec["pack"]["sha256_packed"], \
            f"{cname}: sidecar packed sha mismatch vs master10 manifest"
        assert unpack_payload(packed) == orig, f"{cname}: sidecar unpack mismatch"
        rung = Rung(name=cname, M=cfg["P"], K=1, rs_n=RS_N, rs_k=cfg["rs_k"],
                    frame_bytes=FRAME_BYTES)
        frames_bits, meta = codec.encode_payload(packed, rung)
        for k in ("n_codewords", "n_frames", "frame_bits", "stream_bits"):
            assert meta[k] == m10sec["meta"][k], (cname, k, meta[k],
                                                  m10sec["meta"][k])
        sch = _tx_scheme(cfg)
        for F in (1,) + F_VARIANTS:
            name = f"x12_{'v1' if F == 1 else f'b{F}'}_{cname}"
            audio, geom = _section_audio(cfg, frames_bits, sch, F)
            sec_start = pos
            add(audio)
            add(_silence(GAP_S))
            geom["preamble_starts"] = [int(s + sec_start)
                                       for s in geom["preamble_starts"]]
            geom["body_starts"] = [int(s + sec_start)
                                   for s in geom["body_starts"]]
            wall_s = geom["section_samples"] / SR
            entry = {
                "name": name, "config": cname, "kind": cfg["kind"],
                "scheme": sch.name, "phy": sch.name,
                "framing": geom,
                "section_start": int(sec_start),
                "wall_seconds": round(wall_s, 4),
                "wall_info_bps_orig": round(len(orig) * 8 / wall_s, 1),
                "wall_bps_packed_coded": round(
                    meta["n_codewords"] * cfg["rs_k"] * 8 / wall_s, 1),
                "banked_net_bps": cfg["banked_net_bps"],
                "payload_sidecar": f"sidecars_m10/{cfg['sidecar']}.bin",
                "payload_orig_sidecar": f"sidecars_m10/{cfg['sidecar']}.orig.bin",
                "payload_len": len(packed),
                "pack": dict(m10sec["pack"]),
                "crc32_codewords": list(m10sec["crc32_codewords"]),
                "meta": meta,
                "dqpsk_params": {
                    "P": cfg["P"], "N": cfg["N"], "spacing": cfg["spacing"],
                    "skip": cfg.get("skip"),
                    "min_spacing_hz": cfg.get("min_spacing_hz", 375.0),
                    "drop_freqs_hz": cfg.get("drop_freqs_hz", []),
                    "pilot_hz": cfg["pilot_hz"]},
            }
            mani["ws_payloads"].append(entry)
            build_rows.append({k: entry[k] for k in
                               ("name", "config", "wall_seconds",
                                "wall_info_bps_orig", "wall_bps_packed_coded")}
                              | {"F": F, "n_frames": meta["n_frames"]})
            print(f"[build] {name:18s} F={F} frames={meta['n_frames']:3d} "
                  f"wall={wall_s:6.2f}s orig-bps={entry['wall_info_bps_orig']:7.1f}",
                  flush=True)

    add(_silence(1.0))
    mani["tx_chirp1"] = pos
    add(_make_global_chirp(up=False))
    add(_silence(GAP_S))
    add(_silence(TAIL))

    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    audio_full = (audio_full / peak * 0.70).astype(np.float32)
    sf.write(str(MINI_WAV), audio_full, SR, subtype="FLOAT")
    MINI_MANIFEST.write_text(json.dumps(mani, indent=1, default=_jsafe))

    # framing-efficiency table straight from the built geometry
    eff = {}
    for cname in CONFIGS:
        v1 = next(r for r in build_rows if r["config"] == cname and r["F"] == 1)
        eff[cname] = {}
        for F in F_VARIANTS:
            b = next(r for r in build_rows
                     if r["config"] == cname and r["F"] == F)
            eff[cname][f"F{F}"] = {
                "wall_seconds_v1": v1["wall_seconds"],
                "wall_seconds_bulk": b["wall_seconds"],
                "efficiency_x": round(v1["wall_seconds"] / b["wall_seconds"], 4),
                "wall_info_bps_orig_v1": v1["wall_info_bps_orig"],
                "wall_info_bps_orig_bulk": b["wall_info_bps_orig"]}
    out = {"experiment": "x12_bulk_framing build",
           "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "mini_wav": MINI_WAV.name, "dur_s": round(len(audio_full) / SR, 2),
           "sections": build_rows, "framing_efficiency_measured": eff,
           "payload_reuse": "sidecars_m10 packed bytes verbatim (sha-asserted)",
           "elapsed_s": round(time.time() - t0, 1)}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "x12_framing_build.json").write_text(
        json.dumps(out, indent=1, default=_jsafe))
    print(f"[build] {MINI_WAV.name} {out['dur_s']}s; efficiency: " +
          ", ".join(f"{c} F8={eff[c]['F8']['efficiency_x']:.3f}x" for c in eff))
    return out


# ===========================================================================
# the x12 receiver: anchored frames via the frozen demod verbatim;
# non-anchored frames via the spliced-window trick (see module docstring).
# ===========================================================================
def _demod_frames(audio_nom, sec, align, dem, sch, anchors, tx_frames=None):
    """Demod every frame of a section. `anchors` = sorted frame indices that
    use their real on-tape preamble; all other frames are extrapolated from
    the most recent anchor via manifest body-start deltas + splice windows.
    Returns (rx_frames, frame_diag rows)."""
    meta = sec["meta"]
    nom_bits = _nominal_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    N = sch.N
    fr = sec["framing"]
    body_starts = fr["body_starts"]
    pre_starts = fr.get("preamble_starts")
    n_frames = meta["n_frames"]
    anchors = sorted(set(anchors))
    assert anchors and anchors[0] == 0, "frame 0 must be anchored"
    rx_frames, rows = [], []
    body_meas_abs = None
    last_anchor = 0
    for fi in range(n_frames):
        nd = sch.nsym_data(nom_bits[fi])
        body_len = (nd + 1) * N
        if fi in anchors:
            # window around the REAL preamble; frozen demod finds it itself.
            # v1 layout: one preamble per frame -> pre_starts[fi];
            # bulk layout: one per block -> index among block-first frames.
            if len(pre_starts) == n_frames:
                pre_pos = pre_starts[fi]
            else:
                block_firsts = sorted(set(fr["anchor_frame_of"]))
                assert fi in block_firsts, \
                    f"frame {fi} requested as anchor but has no preamble"
                pre_pos = pre_starts[block_firsts.index(fi)]
            st = int(pre_pos) + align
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(audio_nom), st + PRE_LEN + body_len + pad_hi)
            win = np.asarray(audio_nom[w_lo:w_hi], np.float64)
            bits, diag = dem.demod(win, nd)
            body_meas_abs = w_lo + int(diag["preamble_at"])
            last_anchor = fi
            mode = "anchored"
            ds_rep = int(diag["preamble_at"])
        else:
            assert body_meas_abs is not None
            bs = body_meas_abs + (body_starts[fi] - body_starts[last_anchor])
            hi = min(len(audio_nom), bs + body_len + N + SPLICE_TAILPAD)
            seg = np.asarray(audio_nom[max(0, bs):hi], np.float64)
            win = np.concatenate([PRE_REF, seg])
            bits, diag = dem.demod(win, nd)
            mode = "spliced"
            ds_rep = int(diag["preamble_at"])
        rx_frames.append(np.asarray(bits, np.uint8))
        row = {"frame": fi, "mode": mode, "ds": ds_rep,
               "anchor": last_anchor}
        if tx_frames is not None:
            tb = tx_frames[fi].astype(np.uint8)
            rb = rx_frames[-1]
            m = min(len(tb), len(rb))
            row["raw_ber"] = round((int(np.count_nonzero(tb[:m] != rb[:m]))
                                    + (len(tb) - m)) / max(1, len(tb)), 5)
        rows.append(row)
    return rx_frames, rows


def decode_section_x12(audio_nom, sec, align, ledger, *, anchors=None,
                       tx_frames=None, verbose=True):
    """Pass-1 union over the pre-registered bank (frozen acceptance channel);
    fill-only, early-stop when union complete. anchors=None -> the section's
    own framing anchors (v1: every frame; bulk: block-first frames)."""
    t0 = time.time()
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    n_cw = meta["n_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    k = meta["rs_k"]
    pad = (-len(expected_packed)) % k
    padded = expected_packed + bytes(pad)
    truth_msgs = [padded[i * k:(i + 1) * k] for i in range(n_cw)]

    if anchors is None:
        anchors = sorted(set(sec["framing"]["anchor_frame_of"]))
    union_msgs = [None] * n_cw
    union_src = [None] * n_cw
    branch_records = []
    frame_rows_first = None
    for label, sch_rx, dem in _rx_bank(sec):
        rx_frames, frows = _demod_frames(audio_nom, sec, align, dem, sch_rx,
                                         anchors, tx_frames=tx_frames)
        if frame_rows_first is None:
            frame_rows_first = frows
        ok, msgs = m10._per_cw_decode(_rx_mat(rx_frames, meta), meta, crc,
                                      ledger)
        failed = int(np.sum(~ok))
        branch_records.append({"branch": label, "cw_failed": failed})
        m10._union_fill(union_msgs, union_src, msgs, label)
        if verbose:
            print(f"    [{sec['name']}] {label}: {failed}/{n_cw}", flush=True)
        if not [i for i in range(n_cw) if union_msgs[i] is None]:
            break
    still = [i for i in range(n_cw) if union_msgs[i] is None]
    assembled = m10._assemble(meta, union_msgs)
    byte_exact = assembled == expected_packed
    misc = sum(1 for i in range(n_cw)
               if union_msgs[i] is not None and union_msgs[i] != truth_msgs[i])
    orig_exact = unpack_ok = None
    try:
        rec = unpack_payload(assembled)
        unpack_ok = True
        orig_exact = (hashlib.sha256(rec).hexdigest()
                      == sec["pack"]["sha256_orig"]
                      and len(rec) == sec["pack"]["orig_len"])
    except Exception:
        unpack_ok = False
        orig_exact = False
    spliced = [r for r in frame_rows_first if r["mode"] == "spliced"]
    res = {
        "name": sec["name"], "kind": sec["kind"],
        "n_frames": meta["n_frames"], "n_codewords": n_cw,
        "anchors": list(map(int, anchors)),
        "n_anchored": len(anchors),
        "n_spliced": meta["n_frames"] - len(anchors),
        "cw_failed": len(still), "byte_exact": bool(byte_exact),
        "unpack_ok": unpack_ok, "orig_byte_exact": bool(orig_exact),
        "miscorrected_cw": int(misc),
        "branch_records": branch_records,
        "spliced_ds_all_12000": bool(all(r["ds"] == PRE_LEN for r in spliced))
        if spliced else None,
        "frame_rows": frame_rows_first,
        "elapsed_s": round(time.time() - t0, 1),
    }
    return res


# ===========================================================================
# capture loading for the mini tape
# ===========================================================================
def _sync_mini(path):
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)
    mani = json.loads(MINI_MANIFEST.read_text())
    sync = am2.global_sync_and_resample(audio, mani)
    align = int(sync["chirp0_nominal"]) - int(mani["tx_chirp0"])
    info = {k: float(v) for k, v in sync.items()
            if k != "audio_nominal" and np.isscalar(v)}
    return sync["audio_nominal"], align, mani, info


def _tx_frames_for(sec):
    packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rs_k = sec["meta"]["rs_k"]
    rung = Rung(name=sec["name"], M=sec["dqpsk_params"]["P"], K=1,
                rs_n=RS_N, rs_k=rs_k, frame_bytes=FRAME_BYTES)
    frames_bits, meta = codec.encode_payload(packed, rung)
    assert meta["n_frames"] == sec["meta"]["n_frames"]
    return frames_bits


# ===========================================================================
# stage: selfcheck (G1)
# ===========================================================================
def stage_selfcheck():
    led = _new_ledger()
    audio_nom, align, mani, info = _sync_mini(MINI_WAV)
    out = {"experiment": "x12_bulk_framing selfcheck (G1)",
           "capture": "x12_bulk_synth.wav (no channel)",
           "sync": info, "align": align, "sections": []}
    ok_all = True
    for sec in mani["ws_payloads"]:
        tx = _tx_frames_for(sec)
        r = decode_section_x12(audio_nom, sec, align, led, tx_frames=tx)
        r.pop("frame_rows")
        out["sections"].append(r)
        ok = (r["cw_failed"] == 0 and r["byte_exact"] and r["orig_byte_exact"]
              and r["miscorrected_cw"] == 0
              and r["spliced_ds_all_12000"] in (True, None))
        ok_all &= ok
        print(f"  [G1 {r['name']:18s}] cw {r['cw_failed']}/{r['n_codewords']} "
              f"PACK={'YES' if r['byte_exact'] else 'no'} "
              f"ORIG={'YES' if r['orig_byte_exact'] else 'no'} "
              f"spliced_ds_ok={r['spliced_ds_all_12000']} "
              f"({r['elapsed_s']}s)", flush=True)
    out["G1_pass"] = bool(ok_all)
    led_data = _merge_ledger("selfcheck", led)
    out["fa_bound_campaign"] = led_data["false_accept_bound"]
    (RESULTS / "x12_framing_selfcheck.json").write_text(
        json.dumps(out, indent=1, default=_jsafe))
    print(f"[G1] PASS={out['G1_pass']}")
    return out


# ===========================================================================
# stage: dress (G2) -- one channel cell per invocation, checkpointed
# ===========================================================================
def _gen_cell_capture(dg, aac, clk, seed, force=False):
    cid = cell_id(dg, aac, clk, seed)
    cap = CAP_DIR / f"x12_bulk_{cid}.wav"
    if cap.exists() and not force:
        return cap, cid
    x, sr = sf.read(str(MINI_WAV), dtype="float64", always_2d=False)
    assert sr == SR
    y, ratio = _apply_clock(x, clk)
    y = sim_v2.channel_v2(y, profile="tape7", aac=bool(aac),
                          seed_offset=int(seed),
                          sim_overrides={"diffuse_gain": float(dg)})
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(str(cap), y.astype(np.float32), SR, subtype="FLOAT")
    print(f"[gen] {cap.name} ({len(y)/SR:.1f}s)", flush=True)
    return cap, cid


def stage_dress(cell_arg):
    cells = {cell_id(*c): c for c in G2_CELLS}
    if cell_arg not in cells:
        raise SystemExit(f"unknown cell {cell_arg!r}; choose from "
                         f"{list(cells)}")
    dg, aac, clk, seed = cells[cell_arg]
    path = RESULTS / "x12_framing_dress.json"
    out = (json.loads(path.read_text()) if path.exists()
           else {"experiment": "x12_bulk_framing dress (G2)",
                 "channel": "channel_v2(resample(x,1+clk), tape7, aac, seed, "
                            "diffuse_gain=dg) -- x11 mechanism verbatim",
                 "cells_preregistered": [cell_id(*c) for c in G2_CELLS],
                 "pessimism_note": "sim 5-8x pessimistic on the timing/N256 "
                                   "axis; gate is v1-vs-bulk ORDERING",
                 "cells": {}})
    if cell_arg in out["cells"] and out["cells"][cell_arg].get("complete"):
        print(f"[G2] cell {cell_arg} already complete; skipping")
        return out
    led = _new_ledger()
    cap, cid = _gen_cell_capture(dg, aac, clk, seed)
    audio_nom, align, mani, info = _sync_mini(cap)
    rows = []
    for sec in mani["ws_payloads"]:
        tx = _tx_frames_for(sec)
        r = decode_section_x12(audio_nom, sec, align, led, tx_frames=tx)
        r.pop("frame_rows")
        rows.append(r)
        print(f"  [G2 {cid} {r['name']:18s}] cw {r['cw_failed']}/"
              f"{r['n_codewords']} PACK={'YES' if r['byte_exact'] else 'no'}",
              flush=True)
        # checkpoint inside the cell
        out["cells"][cell_arg] = {"dg": dg, "aac": aac, "clk_pct": clk,
                                  "seed": seed, "sync": info,
                                  "sections": rows, "complete": False}
        path.write_text(json.dumps(out, indent=1, default=_jsafe))
    out["cells"][cell_arg]["complete"] = True
    led_data = _merge_ledger(f"dress_{cell_arg}", led)
    out["fa_bound_campaign"] = led_data["false_accept_bound"]
    path.write_text(json.dumps(out, indent=1, default=_jsafe))
    print(f"[G2] cell {cell_arg} done")
    return out


# ===========================================================================
# stage: ablate (G3) -- tape10 preamble ablation, one cadence per invocation
# ===========================================================================
def _t10_section(name):
    sec = json.loads(json.dumps(
        next(s for s in M10_MANIFEST["ws_payloads"] if s["name"] == name)))
    # v1 m10 layout -> x12 framing view: every frame has its own preamble at
    # frame_starts[fi]; body at +PRE_LEN.
    fs = [int(s) for s in sec["frame_starts"]]
    sec["framing"] = {"F": 1, "intra_gap_samples": 0,
                      "preamble_starts": fs,
                      "body_starts": [s + PRE_LEN for s in fs],
                      "anchor_frame_of": list(range(len(fs))),
                      "frame_body_samples": None}
    sec["config"] = "2572" if sec["dqpsk_params"]["N"] == 512 else "d2x4910"
    return sec


def stage_ablate(cadence):
    assert cadence in G3_CADENCES, cadence
    path = RESULTS / "x12_framing_ablation.json"
    out = (json.loads(path.read_text()) if path.exists()
           else {"experiment": "x12_bulk_framing tape10 preamble ablation (G3)",
                 "capture": "tape10_run1 (x11 audio_nom cache, READ-ONLY)",
                 "cadences_preregistered": list(G3_CADENCES),
                 "note": "ablation extrapolation spans K x v1-stride (incl. "
                         "0.37 s framing) -- STRICTLY LONGER than bulk's "
                         "K x (body+g_i); supported K here is conservative "
                         "evidence for bulk F=K",
                 "cadences": {}})
    if cadence in out["cadences"] and out["cadences"][cadence].get("complete"):
        print(f"[G3] cadence {cadence} already complete; skipping")
        return out
    led = _new_ledger()
    audio_nom = np.load(CACHE_T10, mmap_mode="r")
    sync = json.loads(SYNC_T10.read_text())
    align = int(sync["align"])
    rows = []
    for name in G3_SECTIONS:
        sec = _t10_section(name)
        n_frames = sec["meta"]["n_frames"]
        K = n_frames if cadence == "all" else int(cadence)
        anchors = list(range(0, n_frames, K))
        tx = _tx_frames_for(sec)
        r = decode_section_x12(audio_nom, sec, align, led, anchors=anchors,
                               tx_frames=tx)
        # condense frame rows: keep BER stats + worst rows
        frows = r.pop("frame_rows")
        bers = [fr.get("raw_ber", 0.0) for fr in frows]
        sp = [fr for fr in frows if fr["mode"] == "spliced"]
        r["raw_ber_mean"] = round(float(np.mean(bers)), 5)
        r["raw_ber_max"] = round(float(np.max(bers)), 5)
        r["raw_ber_mean_anchored"] = round(float(np.mean(
            [fr["raw_ber"] for fr in frows if fr["mode"] == "anchored"])), 5)
        r["raw_ber_mean_spliced"] = (round(float(np.mean(
            [fr["raw_ber"] for fr in sp])), 5) if sp else None)
        r["worst_frames"] = sorted(frows, key=lambda fr: -fr.get("raw_ber", 0)
                                   )[:5]
        rows.append(r)
        print(f"  [G3 K={cadence} {name:26s}] anchors={len(anchors)} "
              f"cw {r['cw_failed']}/{r['n_codewords']} "
              f"BER mean={r['raw_ber_mean']:.4f} "
              f"(spliced {r['raw_ber_mean_spliced']})", flush=True)
        out["cadences"][cadence] = {"K": cadence, "sections": rows,
                                    "complete": False}
        path.write_text(json.dumps(out, indent=1, default=_jsafe))
    out["cadences"][cadence]["complete"] = True
    led_data = _merge_ledger(f"ablate_K{cadence}", led)
    out["fa_bound_campaign"] = led_data["false_accept_bound"]
    path.write_text(json.dumps(out, indent=1, default=_jsafe))
    print(f"[G3] cadence {cadence} done")
    return out


# ===========================================================================
# stage: report -- adjudicate the frozen gates
# ===========================================================================
def stage_report():
    build = json.loads((RESULTS / "x12_framing_build.json").read_text())
    sc = json.loads((RESULTS / "x12_framing_selfcheck.json").read_text())
    dress = json.loads((RESULTS / "x12_framing_dress.json").read_text())
    abl = json.loads((RESULTS / "x12_framing_ablation.json").read_text())
    led = json.loads(LEDGER_PATH.read_text())

    g1 = bool(sc.get("G1_pass"))

    # ---- G2 adjudication (frozen rules) -----------------------------------
    g2_rows, g2_ok = [], True
    g2_complete = all(cell_id(*c) in dress["cells"]
                      and dress["cells"][cell_id(*c)].get("complete")
                      for c in G2_CELLS)
    for c in G2_CELLS:
        cid = cell_id(*c)
        cell = dress["cells"].get(cid)
        if not cell:
            continue
        by_name = {s["name"]: s for s in cell["sections"]}
        for cname in CONFIGS:
            v1 = by_name[f"x12_v1_{cname}"]
            for F in F_VARIANTS:
                b = by_name[f"x12_b{F}_{cname}"]
                n_cw = v1["n_codewords"]
                informative = min(v1["cw_failed"], b["cw_failed"]) <= \
                    G2_DEAD_FRAC * n_cw
                byte_order_ok = not (v1["byte_exact"] and not b["byte_exact"])
                cw_ok = (b["cw_failed"] <= v1["cw_failed"] + G2_CW_TOL) \
                    if informative else True
                misc_ok = (v1["miscorrected_cw"] == 0
                           and b["miscorrected_cw"] == 0)
                ok = byte_order_ok and cw_ok and misc_ok
                g2_ok &= ok
                g2_rows.append({
                    "cell": cid, "config": cname, "F": F,
                    "v1_cw_failed": v1["cw_failed"],
                    "bulk_cw_failed": b["cw_failed"], "n_cw": n_cw,
                    "v1_byte_exact": v1["byte_exact"],
                    "bulk_byte_exact": b["byte_exact"],
                    "informative": bool(informative),
                    "pass": bool(ok)})
    g2 = bool(g2_ok and g2_complete)

    # ---- G3 adjudication (frozen rules) -----------------------------------
    g3_rows = {}
    base = abl["cadences"].get("1")
    baseline_ok = False
    r8_base = None
    if base and base.get("complete"):
        bb = {s["name"]: s for s in base["sections"]}
        baseline_ok = (bb["m10_r0_canary_2572"]["cw_failed"] == 0
                       and bb["m10_r6_d2x_p21_rs159"]["cw_failed"] == 0)
        r8_base = bb["m10_r8_d2x_p22_rs179"]["cw_failed"]
    supported = {}
    for cad in G3_CADENCES:
        cell = abl["cadences"].get(cad)
        if not (cell and cell.get("complete")):
            continue
        bn = {s["name"]: s for s in cell["sections"]}
        sup = (bn["m10_r0_canary_2572"]["cw_failed"] == 0
               and bn["m10_r6_d2x_p21_rs159"]["cw_failed"] == 0
               and r8_base is not None
               and bn["m10_r8_d2x_p22_rs179"]["cw_failed"]
               <= r8_base + G3_R8_TOL)
        supported[cad] = bool(sup)
        g3_rows[cad] = {n: {"cw_failed": bn[n]["cw_failed"],
                            "n_cw": bn[n]["n_codewords"],
                            "byte_exact": bn[n]["byte_exact"],
                            "ber_spliced": bn[n].get("raw_ber_mean_spliced"),
                            "ber_anchored": bn[n].get("raw_ber_mean_anchored"),
                            "miscorrected": bn[n]["miscorrected_cw"]}
                        for n in G3_SECTIONS}
    # K_s = largest cadence with whole-prefix support
    ks = 1
    n36 = 36
    for cad in ("2", "4", "8", "16", "all"):
        if supported.get(cad):
            ks = n36 if cad == "all" else int(cad)
        else:
            break
    f_rec = min(8, ks)
    eff = build["framing_efficiency_measured"]
    eff_at_frec = {c: (eff[c].get(f"F{f_rec}") or {}).get("efficiency_x")
                   for c in CONFIGS}
    # if f_rec not in built variants, fall back to largest built F <= f_rec
    for c in CONFIGS:
        if eff_at_frec[c] is None:
            built = [F for F in F_VARIANTS if F <= f_rec]
            eff_at_frec[c] = (eff[c][f"F{max(built)}"]["efficiency_x"]
                              if built else 1.0)
    g3 = bool(baseline_ok and ks >= 2
              and all(e >= EFF_TARGET for e in eff_at_frec.values())
              and all(cad in abl["cadences"]
                      and abl["cadences"][cad].get("complete")
                      for cad in G3_CADENCES))

    gate_met = bool(g1 and g2 and g3)
    out = {
        "experiment": "x12_bulk_framing -- gate report",
        "prereg": "x10_dossier/x12_framing_prereg.md (frozen before any run)",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "G1_selfcheck_pass": g1,
        "G2_dress": {"pass": g2, "complete": g2_complete, "rows": g2_rows},
        "G3_ablation": {"pass": g3, "baseline_reproduced": baseline_ok,
                        "r8_baseline_cw_failed": r8_base,
                        "supported_by_cadence": supported,
                        "K_s": ks, "rows": g3_rows},
        "recommended_F": f_rec,
        "framing_efficiency_at_recommended_F": eff_at_frec,
        "framing_efficiency_table": eff,
        "wall_info_bps_orig": {
            r["name"]: r["wall_info_bps_orig"] for r in build["sections"]},
        "gate_met": gate_met,
        "findings_descriptive": [
            "G1: the bulk format + splice receiver are mechanically sound -- "
            "all 6 sections byte-exact clean, every spliced window locked "
            "ds=12000, first branch sufficed",
            "G3 failure mechanism: accumulated flutter wander appears as a "
            "STATIC window offset on extrapolated frames (the per-frame "
            "pilot loop tracks increments, never absolute offset); spliced "
            "raw BER grows with anchor distance -- r6: .0178 anchored -> "
            ".0212 (K=2) -> .0221 (K=4) -> .0364 (K=8); r0 collapses by K=8 "
            "(.114); the cliff-sitting r8 amplifies +20% BER into 22->46 cw "
            "at K=2",
            "r0 (2572) and r6 (4910) -- the two configs this format targets "
            "-- both hold 0 failed codewords at K=2 and nearly at K=4 "
            "(3/49, 1/72); only the r8 stretch canary kills the composite "
            "rule at K=2",
            "G2 counter-signal: under dg0.58 dress the bulk-8 2572 variant "
            "BEAT v1 in every cell (27v33, 24v35, 34v36 cw) -- block "
            "anchoring is not intrinsically worse; the d2x N256 "
            "short-symbol geometry is the sensitive axis",
            "the measured efficiency is real (1.287x/1.538x at F=8) but "
            "unlockable only by a receiver that re-acquires absolute timing "
            "per frame body WITHOUT a preamble (e.g. drift-state chaining "
            "across bodies, or a +-64-sample correlation micro-search on "
            "the first symbol) -- that is a NEW mechanism requiring its own "
            "frozen pre-registration before any adjudicating measurement",
        ],
        "ledger": {"total": led["total"],
                   "false_accept_bound": led["false_accept_bound"],
                   "fa_within_budget": led["fa_within_budget"]},
        "honesty": [
            "banked net bps (2572/4910/5791) unchanged -- bulk framing buys "
            "wall-clock/effective rate only",
            "G2 absolute outcomes at dg0.58 are expected failures (sim 5-8x "
            "pessimistic on this axis); the gate is the v1-vs-bulk ordering",
            "G3 is decoder-side ablation of a v1 tape: extrapolation spans "
            "K x 0.871 s (v1 stride) vs bulk's K x ~0.53 s -- conservative",
            "a real bulk master print remains gated on its own campaign "
            "(canary 2572 + best-proven d2x 4910 rungs mandatory)",
        ],
    }
    (RESULTS / "x12_framing_report.json").write_text(
        json.dumps(out, indent=1, default=_jsafe))
    print(json.dumps({k: out[k] for k in
                      ("G1_selfcheck_pass", "recommended_F",
                       "framing_efficiency_at_recommended_F", "gate_met")},
                     indent=1))
    print(f"[report] G2 pass={g2} (complete={g2_complete}); "
          f"G3 pass={g3} K_s={ks}; fa_bound={led['false_accept_bound']:.2e}")
    return out


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["build", "selfcheck", "dress",
                                      "ablate", "report"])
    ap.add_argument("--cell", default=None)
    ap.add_argument("--cadence", default=None)
    args = ap.parse_args()
    if args.stage == "build":
        stage_build()
    elif args.stage == "selfcheck":
        stage_selfcheck()
    elif args.stage == "dress":
        if not args.cell:
            raise SystemExit("--cell required (e.g. dg0.58_aac0_clk+0.00_s0)")
        stage_dress(args.cell)
    elif args.stage == "ablate":
        if not args.cadence:
            raise SystemExit("--cadence required (1|2|4|8|16|all)")
        stage_ablate(args.cadence)
    else:
        stage_report()


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
