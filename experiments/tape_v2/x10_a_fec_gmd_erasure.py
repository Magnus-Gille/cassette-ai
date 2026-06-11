"""x10_a_fec_gmd_erasure.py -- X10 candidate 3 (A-fec-gmd-erasure).

Structural carrier-class errors-and-erasures RS retry keyed to the
deterministic carrier-block byte layout (CRC32-guarded trial ladder).

Mechanism
---------
h4_dqpsk.bits_to_quadrants is CARRIER-BLOCK mapped: data carrier j carries the
j-th contiguous 2*nd-bit block of every frame, and m3_codec's global column
interleave (tx byte sb = j*n_cw + i <-> codeword i, position j) is fully
deterministic.  So every byte position of every RS codeword belongs to a known
small set of data carriers ("carrier byte-classes").  The tape9 forensics
(results/x10_forensics_errors.json) proved the 2632-2896 failures are owned by
one or two structurally-sick carriers (dc0 750 Hz ISI; m7's dc5 4500 Hz notch).
Positional class erasure converts those bytes from errors (cost 2) to erasures
(cost 1) in the RS budget 2f + e <= n-k, robust to the measured confident-error
property that killed margin-ranked erasure (x10_c_margin_erasure: 0/45).

Pre-registered per X10_PLAN.md (frozen 2026-06-11), candidate 3:
  * pass-1 = per-codeword CRC32-guarded UNION across the x10 front-end bank
    (resampling_pll30 + ema {0.5,0.6,0.65,0.7,0.8}) -- identical to
    x10_union_probe.py (verified against its results JSON).
    NOTE the plan baseline is "union+late-window"; x10_late_window results did
    not exist when this ran (parallel candidate). Baseline here = union bank;
    declared in the results JSON.
  * pass-2 trial ladder on each remaining CRC-failed codeword: erase the byte
    class of the worst-1 / worst-2 / worst-3 carriers.  Carriers ranked
    TRUTH-FREE by the angular dispersion (RMS of the wrapped post-decision
    phase residual) of dphi on the ema0.6 branch, per section.  Erasure sets =
    singletons/pairs/triples drawn from the 4 worst-ranked carriers (14 sets),
    sets ordered fewest-erasures-first; branches = the 4 bank members with the
    fewest pass-1 failures (ties: bank order).  <= 56 trials per codeword
    (bound: 60).  Every trial = reedsolo errors-and-erasures decode + manifest
    CRC32 check; accept only on CRC match.  All CRC-acceptance trials
    (pass-1 + ladder) are ledgered against the campaign budget (< 4e5 trials,
    expected false-accepts < 1e-4 at 2^-32/trial).
  * post-hoc truth check: every accepted codeword is compared against the
    payload sidecar (scoring only) -> miscorrected_cw must be 0.
  * regression: tape9 landed rungs (m0-m3, m4b, m8) + union-banked (m4, m5)
    must stay byte-exact through THIS pipeline; m8_tape_mono_lossless
    m8_dq_p10n512_rs127 through THIS pipeline; tape7_run1 + tape4_run1 named
    rungs re-decoded with the UNCHANGED production decoders (their manifests
    carry no per-codeword CRC tables, so the union/ladder machinery cannot
    accept anything there -- zero false-accept channel by construction).

No frozen file is edited; everything here imports h4_dqpsk / x9_resampling_pll
/ analyze_master2 / m9_decode / m3_codec read-only.  Deterministic: no RNG.

Usage (each stage < 8 min, checkpoints after every section):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
        experiments/tape_v2/x10_a_fec_gmd_erasure.py <stage>
    stages: unittest | tape9 | m8 | regress7 | regress4 | report

Results:
    results/x10_gmd_erasure_unittest.json
    results/x10_gmd_erasure_tape9_run1.json
    results/x10_gmd_erasure_m8_tape_mono_lossless.json
    results/x10_gmd_erasure_regression.json
"""
from __future__ import annotations

import json
import math
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

import analyze_master2 as am2                      # noqa: E402
import m3_codec as codec                           # noqa: E402
from m3_codec import Rung                          # noqa: E402
import m9_decode as md                             # noqa: E402 (read-only import)
from h9_payload_codec import unpack_payload        # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod   # noqa: E402
from reedsolo import RSCodec, ReedSolomonError     # noqa: E402
import hashlib                                     # noqa: E402

SR = codec.FS
RESULTS = _HERE / "results"

# ---- pre-registered receiver bank (== x10_union_probe.py FRONTENDS) -------
FRONTENDS = (("resampling_pll30", dict(front_end="pll", pll_bw_hz=30.0)),
             ("ema0.5", dict(front_end="ema", ema_alpha=0.5)),
             ("ema0.6", dict(front_end="ema", ema_alpha=0.6)),
             ("ema0.65", dict(front_end="ema", ema_alpha=0.65)),
             ("ema0.7", dict(front_end="ema", ema_alpha=0.7)),
             ("ema0.8", dict(front_end="ema", ema_alpha=0.8)))
RANKING_BRANCH = "ema0.6"        # pre-registered: m9's winning N256 alpha
N_LADDER_BRANCHES = 4            # 4 branches x 14 sets = 56 <= 60 patterns/cw
TOP_RANKED = 4                   # erasure sets drawn from the 4 worst carriers
MAX_PATTERNS_PER_CW = 60         # frozen gate bound

TAPE9_SECTIONS_LANDED = ("m9_m0_reprove934", "m9_m1_thin159", "m9_m2_thin191",
                         "m9_m3_dropnull9c", "m9_m4b_n256_rs159_var",
                         "m9_m8_dense375")
TAPE9_SECTIONS_UNION = ("m9_m4_n256_rs159", "m9_m5_n256_rs179")
TAPE9_SECTIONS_TARGET = ("m9_m6_n256_rs191", "m9_m7_n256_p11_9000")


# ===========================================================================
# Carrier-class byte map: codeword (i, j) -> set of data-carrier blocks.
# ===========================================================================
def carrier_class_map(meta: dict, P: int):
    """positions[i][c] = sorted byte positions j of codeword i whose 8 stream
    bits touch data-carrier block c.  Derived ONLY from the manifest meta +
    the m3_codec interleave (tx byte sb = j*n_cw + i) + the h4 carrier-block
    frame layout (block c covers frame bits [c*2*nd_f, (c+1)*2*nd_f))."""
    fb = int(meta["frame_bits"])
    n_frames = int(meta["n_frames"])
    stream_bits = int(meta["stream_bits"])
    rs_n, n_cw = int(meta["rs_n"]), int(meta["n_codewords"])
    assert stream_bits == rs_n * n_cw * 8, "stream/codeword accounting mismatch"
    bps = 2 * P
    nb = [fb] * (n_frames - 1) + [stream_bits - fb * (n_frames - 1)]
    nd_f = [int(math.ceil(n / bps)) for n in nb]
    fstart = np.concatenate([[0], np.cumsum(nb)]).astype(np.int64)
    positions = [[[] for _ in range(P)] for _ in range(n_cw)]
    carsets = [[None] * rs_n for _ in range(n_cw)]
    for j in range(rs_n):
        for i in range(n_cw):
            b0 = (j * n_cw + i) * 8
            fi = int(np.searchsorted(fstart, b0, side="right") - 1)
            fi = min(fi, n_frames - 1)
            o = b0 - int(fstart[fi])
            blk = 2 * nd_f[fi]
            cars = sorted({min(P - 1, (o + t) // blk) for t in range(8)})
            carsets[i][j] = cars
            for c in cars:
                positions[i][c].append(j)
    return positions, carsets


# ===========================================================================
# Residual-capturing demod: identical math to ResamplingPLLDemod._decide but
# stashes the wrapped post-decision phase residual (nd, P) per call.  Used for
# the TRUTH-FREE carrier ranking only -- the data path uses the stock class.
# Fidelity is asserted at runtime: its quadrants must equal the stock branch.
# ===========================================================================
class ResidCaptureDemod(ResamplingPLLDemod):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.last_resd = None

    def _decide(self, c, dtau, refine, *, return_quality: bool = False):
        sch = self.sch
        fd = sch.freqs[sch.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])
        dphi = np.angle(d[:, sch.data_idx])
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
        if refine:
            res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            num = (res * fd[None, :]).sum(axis=1)
            den = (fd ** 2).sum()
            dtau_res = num / (2 * np.pi * den)
            dphi = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
            q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
        resd = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        self.last_resd = resd
        if return_quality:
            return q, float(np.sqrt(np.mean(resd ** 2)))
        return q


# ===========================================================================
# Shared per-codeword helpers (mirrors x10_union_probe, verified against it).
# ===========================================================================
def _rx_mat(rx_frames, meta):
    fb_bits, n_frames = meta["frame_bits"], meta["n_frames"]
    stream_bits = meta["stream_bits"]
    rs_n, n_cw = meta["rs_n"], meta["n_codewords"]
    pieces = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else stream_bits - fb_bits * (n_frames - 1)
        rb = (np.asarray(rx_frames[fi], np.uint8).ravel()
              if fi < len(rx_frames) else np.zeros(nominal, np.uint8))
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    rx_bits = np.concatenate(pieces)[:stream_bits]
    if len(rx_bits) < stream_bits:
        rx_bits = np.concatenate([rx_bits, np.zeros(stream_bits - len(rx_bits), np.uint8)])
    rx_bytes = np.packbits(rx_bits)[:n_cw * rs_n]
    return rx_bytes.reshape(rs_n, n_cw).T


def _per_cw_decode(rx_mat, meta, crc_table, ledger):
    """Errors-only RS per codeword + CRC32 guard. Every attempt is a ledgered
    CRC-acceptance trial."""
    rs_n, rs_k, n_cw = meta["rs_n"], meta["rs_k"], meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    ok = np.zeros(n_cw, bool)
    msgs: list[bytes | None] = [None] * n_cw
    for i in range(n_cw):
        ledger["pass1_trials"] += 1
        try:
            msg = bytes(rsc.decode(bytearray(rx_mat[i].tobytes()))[0])
        except (ReedSolomonError, Exception):
            continue
        if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
            continue
        ok[i] = True
        msgs[i] = msg
    return ok, msgs


def _assemble(meta, msgs):
    out = bytearray()
    for i in range(meta["n_codewords"]):
        out += msgs[i] if msgs[i] is not None else bytes(meta["rs_k"])
    return bytes(out)[:meta["payload_len"]]


def _expected_msgs(expected_packed: bytes, meta: dict, crc_table) -> list[bytes]:
    """Truth codeword messages (scoring only) + CRC-table sanity assert."""
    k, n_cw = meta["rs_k"], meta["n_codewords"]
    pad = (-len(expected_packed)) % k
    padded = expected_packed + bytes(pad)
    msgs = [padded[i * k:(i + 1) * k] for i in range(n_cw)]
    for i, m in enumerate(msgs):
        assert (zlib.crc32(m) & 0xFFFFFFFF) == crc_table[i], \
            f"manifest CRC table mismatch at cw {i} (padding convention?)"
    return msgs


# ===========================================================================
# One section through the full pipeline: bank demod -> pass-1 union ->
# carrier ranking -> pass-2 erasure trial ladder -> post-hoc truth check.
# ===========================================================================
def decode_section(audio_nom, sec, align, ledger, *, run_ladder=True):
    t0 = time.time()
    sch = md._scheme_from_entry(sec)
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    truth_msgs = _expected_msgs(expected, meta, crc)
    n_cw = meta["n_codewords"]
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    nk = rs_n - rs_k

    srec = {"name": sec["name"], "phy": sec.get("phy"), "rs": [rs_n, rs_k],
            "n_codewords": n_cw, "n_frames": meta["n_frames"],
            "net_bps": sec.get("projected_net_bps"), "per_fe": {}}

    # ---- bank demod (stock front-ends; production-faithful) ----
    fe_msgs, fe_frames, fe_failed = {}, {}, {}
    for fe_name, kw in FRONTENDS:
        dem = ResamplingPLLDemod(sch, **kw)
        rx_frames, _diags = md._demod_section_frames(
            audio_nom, sec, align, sch, lambda w, nd, d=dem: d.demod(w, nd))
        ok, msgs = _per_cw_decode(_rx_mat(rx_frames, meta), meta, crc, ledger)
        fe_msgs[fe_name], fe_frames[fe_name] = msgs, rx_frames
        failed = [int(i) for i in np.flatnonzero(~ok)]
        fe_failed[fe_name] = failed
        srec["per_fe"][fe_name] = {"cw_failed": len(failed), "failed_idx": failed}
        print(f"  [{sec['name']}] {fe_name}: {len(failed)}/{n_cw} failed", flush=True)

    # ---- pass-1: per-codeword CRC-guarded union (bank order) ----
    union_msgs: list[bytes | None] = [None] * n_cw
    union_src: list[str | None] = [None] * n_cw
    for fe_name, _ in FRONTENDS:
        for i in range(n_cw):
            if union_msgs[i] is None and fe_msgs[fe_name][i] is not None:
                union_msgs[i] = fe_msgs[fe_name][i]
                union_src[i] = fe_name
    u_failed = [i for i in range(n_cw) if union_msgs[i] is None]
    srec["union"] = {"cw_failed": len(u_failed), "failed_idx": u_failed}
    print(f"  [{sec['name']}] UNION: {len(u_failed)}/{n_cw} failed {u_failed}",
          flush=True)

    # ---- truth-free carrier ranking from the ema0.6 residual dispersion ----
    # (computed with the resid-capture subclass; fidelity-checked bit-exact
    #  against the stock ema0.6 branch decisions)
    rank_dem = ResidCaptureDemod(sch, front_end="ema", ema_alpha=0.6)
    P = sch.P
    ss = np.zeros(P)
    nn = 0
    rank_bits_match = True
    pad_lo = int(md.PAD_LO_S * SR)
    pad_hi = int(md.PAD_HI_S * SR)
    nom_bits = md._nominal_frame_bits(meta)
    full_frame = np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8)),
                            np.float32)
    flen_full = len(full_frame)
    stock06 = fe_frames[RANKING_BRANCH]
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st_i = int(st) + align
        w_lo = max(0, st_i - pad_lo)
        w_hi = min(len(audio_nom), st_i + flen_full + pad_hi)
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        bits, _d = rank_dem.demod(win, nd)
        if not np.array_equal(np.asarray(bits, np.uint8),
                              np.asarray(stock06[fi], np.uint8)):
            rank_bits_match = False
        resd = rank_dem.last_resd
        ss += (resd ** 2).sum(axis=0)
        nn += resd.shape[0]
    disp_deg = np.degrees(np.sqrt(ss / max(1, nn)))
    rank = [int(c) for c in np.argsort(-disp_deg)]
    srec["carrier_ranking"] = {
        "metric": "RMS wrapped post-decision dphi residual (deg), ema0.6 branch",
        "dispersion_deg": [round(float(x), 2) for x in disp_deg],
        "rank_worst_first": rank,
        "data_carrier_freqs_hz": [float(sch.freqs[k]) for k in sch.data_idx],
        "fidelity_bits_match_stock_ema06": bool(rank_bits_match),
    }
    print(f"  [{sec['name']}] rank(worst first)={rank[:6]} "
          f"disp={[round(float(disp_deg[c]),1) for c in rank[:4]]} deg "
          f"fidelity={rank_bits_match}", flush=True)

    # ---- pass-2: bounded carrier-class erasure trial ladder ----
    final_msgs = list(union_msgs)
    final_src = list(union_src)
    ladder_rec = {"enabled": bool(run_ladder), "target_cws": u_failed,
                  "branches": [], "sets": [], "trials": 0, "accepted": [],
                  "skipped_sets_infeasible": 0}
    if run_ladder and u_failed:
        positions, _carsets = carrier_class_map(meta, P)
        top = rank[:TOP_RANKED]
        sets = ([(c,) for c in top]
                + [(top[a], top[b]) for a in range(4) for b in range(a + 1, 4)]
                + [tuple(top[x] for x in range(4) if x != skip)
                   for skip in (3, 2, 1, 0)])
        ladder_rec["sets"] = [list(s) for s in sets]
        branches = sorted(
            (n for n, _ in FRONTENDS),
            key=lambda n: (len(fe_failed[n]),
                           [x[0] for x in FRONTENDS].index(n)))[:N_LADDER_BRANCHES]
        ladder_rec["branches"] = branches
        fe_mats = {b: _rx_mat(fe_frames[b], meta) for b in branches}
        rsc = RSCodec(nk)
        for i in u_failed:
            recovered = False
            n_tr = 0
            for s in sets:
                if recovered:
                    break
                epos = sorted(set().union(*[positions[i][c] for c in s]))
                if len(epos) > nk:
                    ladder_rec["skipped_sets_infeasible"] += 1
                    continue
                for b in branches:
                    if n_tr >= MAX_PATTERNS_PER_CW:
                        break
                    n_tr += 1
                    ledger["ladder_trials"] += 1
                    row = bytearray(fe_mats[b][i].tobytes())
                    try:
                        msg = bytes(rsc.decode(row, erase_pos=list(epos))[0])
                    except (ReedSolomonError, Exception):
                        continue
                    if (zlib.crc32(msg) & 0xFFFFFFFF) != crc[i]:
                        continue
                    final_msgs[i] = msg
                    final_src[i] = f"ladder:{b}:erase{list(s)}(e={len(epos)})"
                    ladder_rec["accepted"].append(
                        {"cw": int(i), "branch": b, "erased_carriers": list(s),
                         "n_erased": len(epos), "trials_used": n_tr})
                    recovered = True
                    break
            ladder_rec["trials"] += n_tr
        print(f"  [{sec['name']}] LADDER: recovered "
              f"{len(ladder_rec['accepted'])}/{len(u_failed)} "
              f"({ladder_rec['trials']} trials)", flush=True)
    srec["ladder"] = ladder_rec

    # ---- post-hoc truth check (scoring only) ----
    misc = 0
    for i in range(n_cw):
        if final_msgs[i] is not None and final_msgs[i] != truth_msgs[i]:
            misc += 1
    out = _assemble(meta, final_msgs)
    byte_exact = out == expected
    byte_err = sum(a != b for a, b in zip(out, expected)) + abs(len(out) - len(expected))
    orig_exact = None
    if "pack" in sec:
        try:
            orig = unpack_payload(out)
            sha = hashlib.sha256(orig).hexdigest()
            orig_exact = (sha == sec["pack"]["sha256_orig"]
                          and len(orig) == sec["pack"]["orig_len"])
        except Exception:
            orig_exact = False
    elif sec.get("payload_orig_sidecar"):
        try:
            orig = unpack_payload(out)
            orig_exact = orig == (_HERE / sec["payload_orig_sidecar"]).read_bytes()
        except Exception:
            orig_exact = False
    res_failed = [i for i in range(n_cw) if final_msgs[i] is None]
    srec["final"] = {"cw_failed": len(res_failed), "failed_idx": res_failed,
                     "byte_exact": bool(byte_exact), "byte_errors": int(byte_err),
                     "orig_exact": orig_exact,
                     "miscorrected_cw_posthoc": int(misc),
                     "cw_sources": final_src}
    srec["elapsed_s"] = round(time.time() - t0, 1)
    print(f"  [{sec['name']}] FINAL: {len(res_failed)}/{n_cw} failed, "
          f"byte_exact={byte_exact} orig_exact={orig_exact} misc={misc} "
          f"({srec['elapsed_s']}s)", flush=True)
    return srec


# ===========================================================================
# Capture-level driver (master9 / master8 manifests).
# ===========================================================================
def _load_capture(cap_path: str, manifest: dict):
    audio, sr = sf.read(cap_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    return sync


def run_capture(cap_path: str, manifest_name: str, section_names, out_name: str):
    manifest = json.loads((_HERE / manifest_name).read_text())
    t0 = time.time()
    sync = _load_capture(cap_path, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    print(f"[sync] {time.time()-t0:.1f}s clock={sync.get('clock_ratio')} "
          f"align={align}", flush=True)

    out_path = RESULTS / out_name
    report = {
        "experiment": "x10_a_fec_gmd_erasure",
        "candidate": "A-fec-gmd-erasure (X10_PLAN.md candidate 3, frozen)",
        "capture": cap_path, "manifest": manifest_name,
        "deterministic": True, "seeds": "none (no RNG)",
        "frontends": [n for n, _ in FRONTENDS],
        "baseline_note": ("pass-1 baseline = CRC-guarded union over the bank "
                          "(== x10_union_probe). The plan's union+late-window "
                          "baseline was unavailable (x10_late_window results "
                          "absent when this ran); ladder gains are measured vs "
                          "union-only and may overlap late-window gains."),
        "ladder_preregistration": {
            "ranking": "per-carrier RMS wrapped post-decision dphi residual, "
                       "ema0.6 branch, per section (truth-free)",
            "sets": "singletons/pairs/triples from the 4 worst-ranked carriers "
                    "(14 sets), fewest-erasures-first",
            "branches": f"{N_LADDER_BRANCHES} bank members with fewest pass-1 "
                        "failures (ties: bank order)",
            "max_patterns_per_cw": MAX_PATTERNS_PER_CW,
            "feasibility": "skip set if n_erased > rs_n - rs_k",
        },
        "sync": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                 for k, v in sync.items()
                 if k != "audio_nominal" and np.isscalar(v)},
        "align": int(align),
        "ledger": {"pass1_trials": 0, "ladder_trials": 0},
        "sections": [],
    }

    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    for name in section_names:
        sec = secs[name]
        if sec.get("skipped") or sec.get("kind") == "freqdiff":
            report["sections"].append({"name": name, "skipped": True})
            continue
        srec = decode_section(audio_nom, sec, align, report["ledger"])
        report["sections"].append(srec)
        tot = report["ledger"]["pass1_trials"] + report["ledger"]["ladder_trials"]
        report["ledger"]["total_trials"] = tot
        report["ledger"]["expected_false_accepts"] = tot * 2.0 ** -32
        out_path.write_text(json.dumps(report, indent=2, default=_jsafe))
        print(f"[checkpoint] {out_path}", flush=True)
    print(f"[done] {time.time()-t0:.1f}s total", flush=True)
    return report


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
# Stage: unittest -- validate the carrier-class byte map before trusting it.
# ===========================================================================
def stage_unittest():
    manifest = json.loads((_HERE / "master9_manifest.json").read_text())
    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    forens = json.loads((RESULTS / "x10_forensics_errors.json").read_text())
    out = {"experiment": "x10_a_fec_gmd_erasure unittest", "tests": []}
    ok_all = True

    test_secs = ["m9_m5_n256_rs179", "m9_m6_n256_rs191", "m9_m7_n256_p11_9000",
                 "m9_m0_reprove934"]
    for name in test_secs:
        sec = secs[name]
        sch = md._scheme_from_entry(sec)
        meta = sec["meta"]
        P = sch.P
        expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        positions, carsets = carrier_class_map(meta, P)
        n_cw, rs_n, rs_k = meta["n_codewords"], meta["rs_n"], meta["rs_k"]

        # CRC-table sanity (validates padding convention for truth msgs)
        _expected_msgs(expected, meta, sec["crc32_codewords"])

        # ---- T1 synthetic: corrupt exactly carrier c's frame-bit blocks; the
        # corrupted byte positions per codeword must equal my class map.
        rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                    rs_n=rs_n, rs_k=rs_k, frame_bytes=meta["frame_bytes"])
        tx_frames, meta2 = codec.encode_payload(expected, rung)
        assert meta2["stream_bits"] == meta["stream_bits"]
        clean_mat = _rx_mat(tx_frames, meta)
        nb = md._nominal_frame_bits(meta)
        t1_ok = True
        for c in range(P):
            bad_frames = []
            for fi, fr in enumerate(tx_frames):
                fr2 = np.array(fr, np.uint8)
                nd_f = int(math.ceil(nb[fi] / (2 * P)))
                lo, hi = c * 2 * nd_f, min((c + 1) * 2 * nd_f, nb[fi])
                fr2[lo:hi] ^= 1
                bad_frames.append(fr2)
            bad_mat = _rx_mat(bad_frames, meta)
            for i in range(n_cw):
                got = sorted(int(j) for j in np.flatnonzero(clean_mat[i] != bad_mat[i]))
                if got != positions[i][c]:
                    t1_ok = False
        # ---- T2 forensics cross-check: every bad byte's attributed carriers
        # must be a subset of my class set at that (cw, j).
        t2_ok = True
        n_checked = 0
        fsec = forens["sections"].get(name, {})
        for f in (fsec.get("codewords", {}) or {}).get("failed_forensics", []):
            i = f["cw"]
            for ent in f.get("bad_bytes_j_frame_carriers_symrange", []):
                j, _fr, cars = ent[0], ent[1], ent[2]
                if not set(int(c) for c in cars) <= set(carsets[i][j]):
                    t2_ok = False
                n_checked += 1
        sizes = [len(positions[0][c]) for c in range(P)]
        rec = {"section": name, "P": P, "rs": [rs_n, rs_k],
               "t1_synthetic_block_corruption": t1_ok,
               "t2_forensics_attribution_subset": t2_ok,
               "t2_bytes_checked": n_checked,
               "class_sizes_cw0": sizes,
               "crc_table_sanity": True}
        ok_all = ok_all and t1_ok and t2_ok
        out["tests"].append(rec)
        print(f"[unittest] {name}: T1={t1_ok} T2={t2_ok} ({n_checked} forensics "
              f"bytes) class_sizes={sizes}", flush=True)
    out["all_pass"] = ok_all
    (RESULTS / "x10_gmd_erasure_unittest.json").write_text(
        json.dumps(out, indent=2, default=_jsafe))
    print(f"[unittest] ALL {'PASS' if ok_all else 'FAIL'}", flush=True)
    return ok_all


# ===========================================================================
# Stage: regress7 / regress4 -- UNCHANGED production decoders, results
# redirected out of the repo results dir (no clobbering).
# ===========================================================================
def _run_production(mod_name: str, cap: str, names):
    import importlib
    mod = importlib.import_module(mod_name)
    tmp = pathlib.Path("/tmp/x10_gmd_regress")
    tmp.mkdir(parents=True, exist_ok=True)
    mod.RESULTS_DIR = tmp                  # runtime redirect, no file edits
    res = mod.decode(cap, out_tag="x10_gmd_regress", verbose=True)
    rows = []
    for r in res.get("payloads", []):
        if r.get("name") in names:
            rows.append({"name": r["name"], "byte_exact": bool(r.get("byte_exact")),
                         "rs_codewords_failed": r.get("rs_codewords_failed"),
                         "projected_net_bps": r.get("projected_net_bps")})
    return rows


def _merge_regression(key: str, payload):
    path = RESULTS / "x10_gmd_erasure_regression.json"
    data = json.loads(path.read_text()) if path.exists() else {
        "experiment": "x10_a_fec_gmd_erasure regression suite",
        "note": ("tape7/tape4 use the UNCHANGED production decoders "
                 "(m7_decode/m4_decode); their manifests have no per-codeword "
                 "CRC tables so the union/ladder cannot accept anything there "
                 "(zero false-accept channel by construction)."),
    }
    data[key] = payload
    path.write_text(json.dumps(data, indent=2, default=_jsafe))
    print(f"[regression] wrote {path} ({key})", flush=True)


# ===========================================================================
def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "unittest"
    RESULTS.mkdir(parents=True, exist_ok=True)
    if stage == "unittest":
        ok = stage_unittest()
        sys.exit(0 if ok else 1)
    elif stage == "tape9":
        names = (list(TAPE9_SECTIONS_LANDED[:4])
                 + ["m9_m4_n256_rs159", "m9_m4b_n256_rs159_var",
                    "m9_m5_n256_rs179", "m9_m6_n256_rs191",
                    "m9_m7_n256_p11_9000", "m9_m8_dense375"])
        run_capture(str(_HERE / "captures" / "tape9_run1.wav"),
                    "master9_manifest.json", names,
                    "x10_gmd_erasure_tape9_run1.json")
    elif stage == "m8":
        run_capture(str(_HERE / "captures" / "m8_tape_mono_lossless.wav"),
                    "master8_manifest.json",
                    ["m8_dq_p10n512_rs127", "m8_dq_p10n1024_rs159",
                     "m8_dq_p10n1024_rs223"],
                    "x10_gmd_erasure_m8_tape_mono_lossless.json")
    elif stage == "regress7":
        rows = _run_production("m7_decode",
                               str(_HERE / "captures" / "tape7_run1.wav"),
                               {"m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k"})
        _merge_regression("tape7_run1", rows)
    elif stage == "regress4":
        rows = _run_production("m4_decode",
                               str(_HERE / "captures" / "tape4_run1.wav"),
                               {"ws_test2k", "ws_llm24k"})
        _merge_regression("tape4_run1", rows)
    else:
        raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
