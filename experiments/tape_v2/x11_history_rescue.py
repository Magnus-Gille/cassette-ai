"""x11_history_rescue.py -- x11-history: the composed superset receiver vs the
UNBANKED historical archive (tape7 / m8_tape / tape4-css).

PRE-REGISTERED GATE (frozen in the x11 brief BEFORE any run):
  PASS = >=1 previously-FAILED historical rung newly orig-exact (sha256 vs its
  manifest sidecar) with 0 miscorrections and 0 regressions on already-banked
  rungs on the same captures. Per-rung before/after codeword tables reported.
  Negative results acceptable with error anatomy.

Targets (before-state from the blessed decoders, results/ receipts):
  tape7_run1 (m7_decode):  m16_rs159 1/52, m16_rs223 9/37, m32_rs111 28/37,
                           m32_rs127 2/33, m32_rs159 12/26, m32_rs191 22/22
       banked regression:  m16_rs111 0/74, m16_rs191 0/43, m32_rs95 0/44
  m8_tape_mono_lossless (m8_decode): ctrl_m16k1_rs191 9/9 (combo 1/9),
       m32k2_rs127 6/6, m16k2_rs159 36/36, m16k2_rs191 31/31, m16k3_rs159 37/37,
       dq_p10n1024_rs159 37/37, dq_p10n1024_rs223 35/35
       banked regression:  dq_p10n512_rs127 0/62 orig-exact (the 934 rung),
                           m32k2_rs159 orig-exact (combo-rescued by m8_decode)
  tape4_run1 (m4_decode):  css_test2k 22/22 raw BER .188, css_llm6k 65/65 .249
       -> NO composed-receiver path exists for CSS (different PHY); recorded as
          error anatomy, not attempted (see _tape4_css_anatomy).

Composition (strictly additive, CRC32-guarded fill-only; one acceptance
channel = RS decode success + per-codeword CRC32; every trial ledgered;
false_accept_bound = crc_checks * 2^-32 < 1e-4 campaign-wide):

  DQPSK sections (m8 N1024/N512): m10_decode._decode_section UNCHANGED --
      pass-1 ensemble union (pll30 + ema bank), pass-3 carrier-class
      errors-and-erasures ladder (<=60 patterns/cw, 4 branches).
  WS sections (M16/M32 K1/K2): pass-1 union over the WS front-end bank
      [plain m6 contrast EQ demod; H6 combo timing-trajectory steered demod at
      loop bandwidths 0.25 (the proven one), 0.5, 0.125, 1.0 Hz], then a
      reliability-ranked errors-and-erasures retry ladder on CRC-failing
      codewords ONLY (gap-metric byte reliabilities, F in WS_F_GRID erasures,
      <=60 patterns/cw, 4 best branches, fill-only).
  WS K=3 (m8_m16k3): plain branch only -- no combo engine exists for K=3 and
      no reliability stream, hence no ladder; honest no-rescue-path record.

CRC tables: manifest crc32_codewords where present (m8). master7 PREDATES the
sidecar-CRC convention; its per-codeword CRC32 table is derived from the
tracked payload sidecar with the identical convention (verified bit-exact
against master8's manifest tables). Source is logged per section. Post-hoc
truth audit (miscorrected_cw) is computed for every accepted codeword.

FROZEN inputs (read-only): m10_decode.py and every m*/h*/x9_*/x10_* module,
captures/h5_audio_nom_tape7_run1.npy + results/h5_sync_meta_tape7_run1.json
(the H5-era tape7 sync, reused), captures/x10_m10_nom_composed_regression_
m8_tape.npy + its sync json (the x10-era m8 sync, reused).

Usage (chunkable; each invocation < 8 min; checkpoints per section):
    python3 experiments/tape_v2/x11_history_rescue.py tape7 [--sections a,b]
    python3 experiments/tape_v2/x11_history_rescue.py m8    [--sections a,b]
    python3 experiments/tape_v2/x11_history_rescue.py tape4
    python3 experiments/tape_v2/x11_history_rescue.py summarize

Outputs: results/x11_history_rescue_<cap>.json (+ _summary.json).
WS demod caches: captures/x11_ws_<cap>_<section>_<branch>.npz (gitignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import zlib

import numpy as np

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import m10_decode as m10                      # noqa: E402  READ-ONLY superset receiver
import m3_codec as codec                      # noqa: E402
import analyze_master2 as am2                 # noqa: E402
import hyp_common as hc                       # noqa: E402
import h5_pll_decode as h5                    # noqa: E402
from h6_combo_decode import ComboEngine       # noqa: E402
from h2_erasure_decode import _stream_bytes_and_rel  # noqa: E402
from m6_decode import _ws_eq_from_sounder     # noqa: E402
from assault_widespace import build as ws_build, _demod_frame_achievable  # noqa: E402
from h9_payload_codec import unpack_payload   # noqa: E402
from reedsolo import RSCodec, ReedSolomonError  # noqa: E402

SR = codec.FS
RESULTS_DIR = _HERE / "results"
CAP_DIR = _HERE / "captures"

# ---- pre-registered WS bank + ladder bounds (frozen before first run) ------
WS_COMBO_BWS = (0.25, 0.5, 0.125, 1.0)        # 0.25 = the m8/h6-proven loop bw
WS_F_GRID = (4, 8, 12, 16, 24, 32, 48, 64, 80)  # erasure counts, capped at nk
MAX_PATTERNS_PER_CW = 60                       # identical to the frozen m10 bound
N_LADDER_BRANCHES = 4                          # identical to the frozen m10 bound
WS_PAD_S = 0.30                                # m6/m8 plain-branch window pad
FA_BUDGET = 1e-4

CAPTURES = {
    "tape7": dict(
        wav="captures/tape7_run1.wav",
        manifest="master7_manifest.json",
        nom_cache="captures/h5_audio_nom_tape7_run1.npy",
        sync_meta="results/h5_sync_meta_tape7_run1.json",
        style="m7",
        baseline="results/m7_results_tape7_run1.json",
        banked=("m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k"),
    ),
    "m8": dict(
        wav="captures/m8_tape_mono_lossless.wav",
        manifest="master8_manifest.json",
        nom_cache="captures/x10_m10_nom_composed_regression_m8_tape.npy",
        sync_meta="results/x10_m10_sync_composed_regression_m8_tape.json",
        style="m8",
        baseline="results/m8_results_m8_tape_mono_lossless.json",
        banked=("m8_dq_p10n512_rs127", "m8_m32k2_rs159"),
    ),
}


# ---------------------------------------------------------------------------
def _crc_table(sec):
    """Manifest CRC table, or (master7) the identical convention derived from
    the tracked payload sidecar (verified bit-exact vs master8 manifests)."""
    if "crc32_codewords" in sec:
        return list(sec["crc32_codewords"]), "manifest"
    raw = (_HERE / sec["payload_sidecar"]).read_bytes()
    k, n_cw = sec["meta"]["rs_k"], sec["meta"]["n_codewords"]
    padded = raw + bytes((-len(raw)) % k)
    tab = [zlib.crc32(padded[i * k:(i + 1) * k]) & 0xFFFFFFFF for i in range(n_cw)]
    return tab, "derived_from_payload_sidecar(master7 predates sidecar-CRC)"


def _truth_msgs(sec):
    raw = (_HERE / sec["payload_sidecar"]).read_bytes()
    k, n_cw = sec["meta"]["rs_k"], sec["meta"]["n_codewords"]
    padded = raw + bytes((-len(raw)) % k)
    return [padded[i * k:(i + 1) * k] for i in range(n_cw)], raw


# ---------------------------------------------------------------------------
# WS front-end branches
# ---------------------------------------------------------------------------
def _ws_branch_plain(audio_nom, sec, align, sounder):
    phy = sec["phy_params"]
    ws = ws_build(phy["M"], phy["K"], phy["spacing"], phy["N"])
    eq = _ws_eq_from_sounder(ws, sounder)
    meta = sec["meta"]
    nsym = meta["frame_bits"] // ws.bits_per_sym
    flen = len(np.asarray(ws.modulate(np.zeros(meta["frame_bits"], np.uint8)),
                          np.float32))
    pad = int(WS_PAD_S * SR)
    bits = []
    for start in sec["frame_starts"]:
        st = int(start) + align
        lo = max(0, st - pad)
        hi = min(len(audio_nom), st + flen + pad)
        window = np.asarray(audio_nom[lo:hi], np.float32)
        rb = np.asarray(_demod_frame_achievable(ws, eq, window, nsym, "contrast"),
                        np.uint8).ravel()
        bits.append(rb)
    bits_mat = np.stack(bits)
    rel = np.zeros((len(bits), nsym))           # plain branch carries no reliability
    rx_mat, rel_cw = _stream_bytes_and_rel(bits_mat, rel, meta, ws.bits_per_sym,
                                           "mean")
    return rx_mat, None                          # None => not ladder-eligible


def _ws_branch_combo(audio_nom, sec, align, eng, bw, cache_path):
    """H6 combo: pass-1 greedy -> timing trajectory(bw) -> steered instrumented
    re-demod. Mirrors m8_decode._combo_decode_section numerics exactly."""
    meta = sec["meta"]
    nF = meta["n_frames"]
    if cache_path.exists():
        z = np.load(cache_path)
        si_arr, gap_arr = z["si"], z["gap"]
    else:
        si_arr = np.zeros((nF, eng.nsym), np.int64)
        lock_arr = np.zeros((nF, eng.nsym), np.float64)
        gap_arr = np.zeros((nF, eng.nsym), np.float64)
        for fi, start in enumerate(sec["frame_starts"]):
            yy = h5.frame_window(audio_nom, eng, start, align)
            ds = hc.find_preamble(yy.astype(np.float32), eng.ws.preamble_seconds)
            _si, d, _lock, _ok, _eps = eng.demod_frame_pass1(yy, ds)
            tau = h5.build_tau_timing(d, eng.fs_sym, bw)
            si, lock, gap = eng.demod_frame_steered_instr(yy, int(ds), tau)
            si_arr[fi], lock_arr[fi], gap_arr[fi] = si, lock, gap
        np.savez_compressed(cache_path, si=si_arr, lock=lock_arr, gap=gap_arr)
    bits_mat = np.stack([eng.bits_from_si(si) for si in si_arr])
    rx_mat, rel_cw = _stream_bytes_and_rel(bits_mat, gap_arr, meta, eng.bps, "mean")
    return rx_mat, rel_cw


# ---------------------------------------------------------------------------
# WS reliability-ranked errors-and-erasures retry ladder (fill-only).
# ---------------------------------------------------------------------------
def _ws_erasure_ladder(meta, crc, pool, union_msgs, union_src, ledger,
                       verbose=True, name=""):
    n_cw, nk = meta["n_codewords"], meta["rs_n"] - meta["rs_k"]
    failed = [i for i in range(n_cw) if union_msgs[i] is None]
    rec = {"target_cws": list(failed), "accepted": [], "trials": 0,
           "f_grid": [f for f in WS_F_GRID if f <= nk],
           "branches": [b[0] for b in pool]}
    if not failed or not pool:
        return rec
    rsc = RSCodec(nk)
    fgrid = [f for f in WS_F_GRID if f <= nk]
    for i in failed:
        recovered = False
        n_tr = 0
        for F in fgrid:
            if recovered:
                break
            for bname, mat, rel in pool[:N_LADDER_BRANCHES]:
                if n_tr >= MAX_PATTERNS_PER_CW:
                    break
                epos = sorted(int(p) for p in np.argsort(rel[i])[:F])
                n_tr += 1
                ledger["rs_attempts"] += 1
                try:
                    msg = bytes(rsc.decode(bytearray(mat[i].tobytes()),
                                           erase_pos=epos)[0])
                except (ReedSolomonError, Exception):
                    continue
                ledger["crc_checks"] += 1
                if (zlib.crc32(msg) & 0xFFFFFFFF) != crc[i]:
                    ledger["crc_rejects"] += 1
                    continue
                ledger["crc_accepts"] += 1
                union_msgs[i] = msg              # fill-only: i is CRC-failing here
                union_src[i] = f"ws_ladder:{bname}:F{F}"
                rec["accepted"].append({"cw": int(i), "branch": bname,
                                        "n_erased": F, "trials_used": n_tr})
                recovered = True
                break
        rec["trials"] += n_tr
    if verbose:
        print(f"    [ws_ladder {name}] recovered {len(rec['accepted'])}/"
              f"{len(failed)} ({rec['trials']} trials)", flush=True)
    return rec


# ---------------------------------------------------------------------------
# composed WS section decode (pass-1 union over WS bank + ladder)
# ---------------------------------------------------------------------------
def _decode_ws_section(audio_nom, sec, align, sounder, ledger, cap_key,
                       verbose=True):
    t0 = time.time()
    meta = sec["meta"]
    n_cw = meta["n_codewords"]
    crc, crc_src = _crc_table(sec)
    truth, expected = _truth_msgs(sec)
    K = meta["K"]

    union_msgs: list[bytes | None] = [None] * n_cw
    union_src: list[str | None] = [None] * n_cw
    branch_records = []
    pool = []                                    # ladder-eligible (name, mat, rel)
    best = None

    eng = ComboEngine(sec, sounder) if K <= 2 else None
    branches = [("ws_plain_contrast", None)]
    if eng is not None:
        branches += [(f"ws_combo_bw{bw:g}", bw) for bw in WS_COMBO_BWS]

    for label, bw in branches:
        if bw is None:
            rx_mat, rel_cw = _ws_branch_plain(audio_nom, sec, align, sounder)
        else:
            cache = CAP_DIR / f"x11_ws_{cap_key}_{sec['name']}_bw{bw:g}.npz"
            rx_mat, rel_cw = _ws_branch_combo(audio_nom, sec, align, eng, bw, cache)
        ok, msgs = m10._per_cw_decode(rx_mat, meta, crc, ledger)
        failed = [int(i) for i in np.flatnonzero(~ok)]
        branch_records.append({"branch": label, "stage": "ensemble",
                               "cw_failed": len(failed), "failed_idx": failed})
        if rel_cw is not None:
            pool.append((label, rx_mat, rel_cw, len(failed)))
        m10._union_fill(union_msgs, union_src, msgs, label)
        if best is None or len(failed) < best["cw_failed"]:
            best = {"branch": label, "cw_failed": len(failed)}
        if verbose:
            print(f"    [{sec['name']}] {label}: {len(failed)}/{n_cw}", flush=True)
        if not [i for i in range(n_cw) if union_msgs[i] is None]:
            break

    still = [i for i in range(n_cw) if union_msgs[i] is None]
    ladder_rec = None
    if still and pool:
        pool_sorted = [(n, m, r) for n, m, r, _f in
                       sorted(pool, key=lambda x: x[3])]
        ladder_rec = _ws_erasure_ladder(meta, crc, pool_sorted, union_msgs,
                                        union_src, ledger, verbose=verbose,
                                        name=sec["name"])
        still = [i for i in range(n_cw) if union_msgs[i] is None]

    assembled = m10._assemble(meta, union_msgs)
    byte_exact = assembled == expected
    byte_err = sum(a != b for a, b in zip(assembled, expected)) + abs(
        len(assembled) - len(expected))
    misc = sum(1 for i in range(n_cw)
               if union_msgs[i] is not None and union_msgs[i] != truth[i])

    res = {
        "name": sec["name"], "kind": "ws", "scheme": "widespace",
        "phy": sec["phy"], "role": sec.get("role", ""),
        "llm_offset": sec.get("llm_offset", 0),
        "payload_bytes": len(expected),
        "n_frames": meta["n_frames"], "n_codewords": n_cw,
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
        "gross_bps": sec.get("gross_bps"),
        "projected_net_bps": sec.get("projected_net_bps"),
        "effective_bps": sec.get("effective_bps"),
        "crc_table_source": crc_src,
        "rs_codewords_failed": len(still),
        "failed_idx_final": still,
        "miscorrected_cw": int(misc),
        "byte_errors": int(byte_err),
        "byte_exact": bool(byte_exact),
        "front_end_used": best["branch"] if best else None,
        "best_single_branch": best,
        "union_sources": sorted({s for s in union_src if s}),
        "rescued_cw": [{"cw": i, "source": union_src[i]} for i in range(n_cw)
                       if union_src[i] and union_src[i].startswith("ws_ladder:")],
        "branch_records": branch_records,
        "ladder": ladder_rec,
        "no_rescue_path": bool(K > 2),
        "elapsed_s": round(time.time() - t0, 1),
    }
    return res, assembled


# ---------------------------------------------------------------------------
def _finalize(sec, r, assembled, style):
    """Unpack + integrity. m8 style: h9 pack (gzip) -> sha256_orig. m7 style:
    raw payload IS the original; orig-exact == byte-exact, sha256s recorded."""
    if style == "m8":
        pack = sec["pack"]
        try:
            orig = unpack_payload(assembled)
            sha_o = hashlib.sha256(orig).hexdigest()
            r["unpack_ok"] = True
            r["orig_byte_exact"] = bool(sha_o == pack["sha256_orig"]
                                        and len(orig) == pack["orig_len"])
            r["sha256_orig_recovered"] = sha_o
        except Exception as exc:
            r["unpack_ok"] = False
            r["orig_byte_exact"] = False
            r["unpack_error"] = str(exc)
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        r["sha256_orig_manifest"] = pack["sha256_orig"]
    else:                                        # m7: no packing
        expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        r["pack_algo"] = None
        r["sha256_payload_recovered"] = hashlib.sha256(assembled).hexdigest()
        r["sha256_payload_sidecar"] = hashlib.sha256(expected).hexdigest()
        r["unpack_ok"] = None
        r["orig_byte_exact"] = bool(r["byte_exact"])
    return r


def _tape4_css_anatomy():
    """tape4 css rungs: NO composed-receiver path exists (CSS chirp-spread PHY;
    the composed receiver's banks are DQPSK/WS-specific). Error anatomy from
    the blessed m4_decode receipts: raw BER 0.188 (css_test2k) / 0.249
    (css_llm6k) => P(byte corrupted) ~= 1-(1-p)^8 = 0.81 / 0.90; RS(255,k)
    corrects <= (255-k)/2 errors ~= 12-25% of bytes, and even erasure-perfect
    decoding caps at (255-k) ~= 25-50%. The stream is 3-7x beyond ANY
    receiver-side FEC rescue; rescuing CSS needs a re-record (or SNR), not a
    receiver. Recorded as a structural negative, not attempted."""
    base = json.loads((RESULTS_DIR / "m4_results_tape4_run1.json").read_text())
    out = {"capture": "captures/tape4_run1.wav", "decoder": "none",
           "attempted": False,
           "reason": "no CSS path in the composed superset receiver "
                     "(DQPSK/WS-specific banks); see anatomy",
           "anatomy": _tape4_css_anatomy.__doc__.strip(), "rungs": {}}
    for r in base["payloads"]:
        if r["name"].startswith("css"):
            p = float(r["raw_ber"])
            out["rungs"][r["name"]] = {
                "before_cw_failed": f"{r['rs_codewords_failed']}/{r['n_codewords']}",
                "raw_ber": p,
                "p_byte_corrupt": round(1 - (1 - p) ** 8, 3),
                "rs": [r["rs_n"], r["rs_k"]],
                "max_correctable_frac_errors_only":
                    round((r["rs_n"] - r["rs_k"]) / 2 / r["rs_n"], 3),
                "max_correctable_frac_erasure_perfect":
                    round((r["rs_n"] - r["rs_k"]) / r["rs_n"], 3),
                "verdict": "unrescuable receiver-side (>=3x beyond FEC radius)",
            }
    return out


# ---------------------------------------------------------------------------
def run_capture(cap_key, sections=None, verbose=True):
    cfg = CAPTURES[cap_key]
    manifest = json.loads((_HERE / cfg["manifest"]).read_text())
    baseline = json.loads((_HERE / cfg["baseline"]).read_text())
    base_by_name = {r["name"]: r for r in baseline["payloads"]}

    audio_nom = np.load(_HERE / cfg["nom_cache"], mmap_mode="r")
    sync_meta = json.loads((_HERE / cfg["sync_meta"]).read_text())
    if cap_key == "tape7":
        align = int(sync_meta["align"])
        sounder = sync_meta["sounder"]           # full H5-era sounder (H_db etc.)
    else:
        align = int(sync_meta["align"])
        sounder = am2.analyze_sounder(audio_nom, manifest, sync_meta)

    json_path = RESULTS_DIR / f"x11_history_rescue_{cap_key}.json"
    out = (json.loads(json_path.read_text()) if json_path.exists() else {
        "capture": cfg["wav"], "manifest": cfg["manifest"],
        "decoder": "x11_history_rescue (composed superset, READ-ONLY m10 import)",
        "frozen_inputs": [cfg["nom_cache"], cfg["sync_meta"]],
        "preregistered": {
            "gate": ">=1 previously-failed rung newly orig-exact, 0 miscorrections,"
                    " 0 regressions on banked rungs",
            "ws_bank": ["ws_plain_contrast"] + [f"ws_combo_bw{b:g}" for b in WS_COMBO_BWS],
            "ws_f_grid": list(WS_F_GRID),
            "max_patterns_per_cw": MAX_PATTERNS_PER_CW,
            "n_ladder_branches": N_LADDER_BRANCHES,
            "dqpsk_path": "m10_decode._decode_section unchanged",
        },
        "banked_regression_rungs": list(cfg["banked"]),
        "ledger": {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0,
                   "crc_accepts": 0},
        "payloads_by_name": {},
        "section_order": [s["name"] for s in manifest["ws_payloads"]],
    })
    ledger = out["ledger"]
    out["align"] = align
    if verbose:
        print(f"[x11_history] {cap_key}: align {align:+d}, "
              f"{len(manifest['ws_payloads'])} sections", flush=True)

    for sec in manifest["ws_payloads"]:
        if sections and sec["name"] not in sections:
            continue
        kind = sec.get("kind")
        if kind == "dqpsk":
            r, assembled = m10._decode_section(audio_nom, sec, align, ledger,
                                               rescue=True, verbose=verbose)
            r["crc_table_source"] = "manifest"
        else:
            r, assembled = _decode_ws_section(audio_nom, sec, align, sounder,
                                              ledger, cap_key, verbose=verbose)
        r = _finalize(sec, r, assembled, cfg["style"])

        b = base_by_name.get(sec["name"], {})
        r["before"] = {
            "decoder": "m7_decode" if cfg["style"] == "m7" else "m8_decode",
            "cw_failed": b.get("rs_codewords_failed"),
            "n_codewords": b.get("n_codewords"),
            "byte_exact": b.get("byte_exact"),
            "orig_byte_exact": b.get("orig_byte_exact",
                                     b.get("byte_exact") if cfg["style"] == "m7"
                                     else None),
            "combo_cw_failed": (b.get("combo_decode") or {}).get(
                "rs_codewords_failed"),
        }
        r["banked_before"] = sec["name"] in cfg["banked"]
        r["newly_banked"] = bool(r.get("orig_byte_exact")
                                 and not r["banked_before"]
                                 and not r["before"].get("orig_byte_exact"))
        r["regression"] = bool(r["banked_before"]
                               and not r.get("orig_byte_exact"))
        out["payloads_by_name"][sec["name"]] = r

        done = [out["payloads_by_name"][n] for n in out["section_order"]
                if n in out["payloads_by_name"]]
        out["payloads"] = done
        out["n_orig_exact"] = sum(bool(x.get("orig_byte_exact")) for x in done)
        out["n_newly_banked"] = sum(bool(x.get("newly_banked")) for x in done)
        out["n_regressions"] = sum(bool(x.get("regression")) for x in done)
        out["n_miscorrected"] = sum(int(x.get("miscorrected_cw") or 0) for x in done)
        out["false_accept_bound"] = ledger["crc_checks"] * 2.0 ** -32
        out["fa_within_budget"] = bool(out["false_accept_bound"] < FA_BUDGET)
        json_path.write_text(json.dumps(out, indent=2, default=float))
        if verbose:
            print(f"  [{r['name']:22s}] before {r['before']['cw_failed']}/"
                  f"{r['before']['n_codewords']} -> after "
                  f"{r.get('rs_codewords_failed')}/{r.get('n_codewords')} "
                  f"ORIG={'YES' if r.get('orig_byte_exact') else 'no'}"
                  f"{' NEWLY-BANKED' if r['newly_banked'] else ''}"
                  f"{' REGRESSION!' if r['regression'] else ''} "
                  f"({r.get('elapsed_s')}s) -> checkpointed", flush=True)
    return out


def run_tape4():
    out = _tape4_css_anatomy()
    p = RESULTS_DIR / "x11_history_rescue_tape4.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"[x11_history] tape4 css anatomy -> {p}")
    return out


def summarize():
    summ = {"campaign": "x11-history", "captures": {}, "newly_banked": [],
            "regressions": [], "total_miscorrected": 0,
            "ledger_total": {"rs_attempts": 0, "crc_checks": 0,
                             "crc_rejects": 0, "crc_accepts": 0}}
    for cap in ("tape7", "m8"):
        p = RESULTS_DIR / f"x11_history_rescue_{cap}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        rows = []
        for r in d.get("payloads", []):
            rows.append({
                "rung": r["name"], "phy": r["phy"],
                "before_cw": f"{r['before']['cw_failed']}/{r['before']['n_codewords']}",
                "after_cw": f"{r['rs_codewords_failed']}/{r['n_codewords']}",
                "orig_exact": bool(r.get("orig_byte_exact")),
                "newly_banked": bool(r.get("newly_banked")),
                "regression": bool(r.get("regression")),
                "miscorrected": int(r.get("miscorrected_cw") or 0),
                "net_bps": r.get("projected_net_bps"),
                "effective_bps": r.get("effective_bps"),
                "front_end": r.get("front_end_used"),
                "union_sources": r.get("union_sources"),
            })
            if r.get("newly_banked"):
                summ["newly_banked"].append({
                    "capture": cap, "rung": r["name"],
                    "net_bps": r.get("projected_net_bps"),
                    "effective_bps": r.get("effective_bps")})
            if r.get("regression"):
                summ["regressions"].append({"capture": cap, "rung": r["name"]})
            summ["total_miscorrected"] += int(r.get("miscorrected_cw") or 0)
        for k in summ["ledger_total"]:
            summ["ledger_total"][k] += int(d["ledger"][k])
        summ["captures"][cap] = {"rows": rows,
                                 "fa_bound": d.get("false_accept_bound")}
    p4 = RESULTS_DIR / "x11_history_rescue_tape4.json"
    if p4.exists():
        summ["captures"]["tape4"] = json.loads(p4.read_text())
    summ["false_accept_bound_total"] = (
        summ["ledger_total"]["crc_checks"] * 2.0 ** -32)
    summ["fa_within_budget"] = summ["false_accept_bound_total"] < FA_BUDGET
    summ["gate"] = {
        "pass": bool(summ["newly_banked"]) and not summ["regressions"]
                and summ["total_miscorrected"] == 0
                and summ["fa_within_budget"],
        "n_newly_banked": len(summ["newly_banked"]),
        "n_regressions": len(summ["regressions"]),
        "miscorrected": summ["total_miscorrected"],
    }
    p = RESULTS_DIR / "x11_history_rescue_summary.json"
    p.write_text(json.dumps(summ, indent=2, default=float))
    print(json.dumps(summ["gate"], indent=2))
    print(f"[x11_history] summary -> {p}")
    return summ


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", choices=["tape7", "m8", "tape4", "summarize"])
    ap.add_argument("--sections", default="")
    args = ap.parse_args()
    if args.capture == "summarize":
        summarize()
    elif args.capture == "tape4":
        run_tape4()
    else:
        run_capture(args.capture,
                    sections=[s for s in args.sections.split(",") if s] or None)
