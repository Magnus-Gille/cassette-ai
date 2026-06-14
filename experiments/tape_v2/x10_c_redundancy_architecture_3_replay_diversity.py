"""x10_c_redundancy_architecture_3_replay_diversity.py -- Replay diversity:
CRC-guarded per-codeword union across TWO playbacks of the existing master9
tape (zero new mastering).

Targets the residual failed codewords that within-capture branch-union cannot
fix on tape9_run1 (m6: 10 cw, m7: 4 cw, per x10_union_probe), and measures the
recorded-in vs playback-borne impairment split via a PRE-REGISTERED
independence statistic.

==========================================================================
PRE-REGISTERED DECISION RULE -- FROZEN 2026-06-12, BEFORE the tape9_run2
capture exists (verified absent from captures/ and the Voice Memos store at
freeze time). Do not edit after the capture lands.
==========================================================================
Statistic: per-capture failed set F_c = codewords NOT CRC32-recovered by ANY
  front-end branch within capture c (within-capture union over the FROZEN
  branch set below, erase_frac=0 only). Cross-capture overlap, pooled over
  rungs m9_m6_n256_rs191 and m9_m7_n256_p11_9000 with both F_1, F_2 nonempty:

      overlap_pct = 100 * sum(|F_1 ^ F_2|) / sum(min(|F_1|, |F_2|))

  (per-rung overlap also reported; pooled statistic is the decision input).
Decision:
  overlap_pct >= 80  -> errors are RECORDED-IN; redirect campaign spend to TX.
  overlap_pct <= 40  -> errors are PLAYBACK-BORNE; fund replay/multi-pass
                        diversity as a standing branch in future campaigns.
  40 < overlap < 80  -> indeterminate; no spend redirection either way.
Sanity arms (DIAGNOSTIC PASS requires all):
  run2 flutter_wrms_pct within 1.5x of run1; run2 noise floor within 1.5x in
  AMPLITUDE (|delta dBFS| <= 20*log10(1.5) = 3.52 dB); all 6 m9-landed rungs
  (m0,m1,m2,m3,m4b,m8) orig-exact on run2 STANDALONE (standalone := within-
  capture branch union, the ensemble decode); miscorrected_cw == 0 post-hoc vs
  manifest truth on BOTH captures; total CRC-acceptance trials within the
  campaign false-accept budget (< 1e-4 at 2^-32 per trial).
RECORD PASS (separate, additional): m7 residual cw -> 0 across the two-capture
  union banks 2896 net bps EXPLICITLY as a multi-pass-category record that
  does NOT supersede single-capture records (sidecar-CRC convention caveat).
==========================================================================
FROZEN BRANCH SET: resampling_pll(bw=30) + ema alpha in {0.5,0.6,0.65,0.7,0.8}.
  Superset of every m9 winner; includes the extended alphas x10_union_probe
  showed fix m4/m5 within-capture. ema0.4 excluded (always worst in m9).
  AMENDMENT before any run2 capture exists (2026-06-12): ema0.8 ADDED after
  the run1 fidelity check showed it has unique wins on m6 (union 17->10
  failed cw); run1 is prior evidence, the freeze deadline is the run2 capture.
  Deviation from plan: no late-window/gmd/pfft branch modules have landed as
  importable x10 modules at freeze time, so they are not included.
==========================================================================

All CRC32-per-codeword guarded (manifest crc table). Sidecar/truth bytes are
used for SCORING and post-hoc miscorrection audit only -- never in decisions.
Deterministic: no RNG anywhere (numpy seed set for hygiene only).

Usage (each stage < 8 min):
  # stage A: per-capture per-branch per-codeword CRC-guarded decode + cache
  OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
    experiments/tape_v2/x10_c_redundancy_architecture_3_replay_diversity.py \
    decode --capture experiments/tape_v2/captures/tape9_run1.wav --tag tape9_run1
  # stage B: cross-capture CRC-guarded union + overlap matrix + verdicts
  ... fuse --tag-a tape9_run1 --tag-b tape9_run2 --label real_replay_pair --real-pair
  # (sim surrogate validation: fuse --tag-a dress_s0 --tag-b dress_s1
  #  --label sim_dress_pair   -- decision rule NOT armed)

Outputs:
  results/x10_replay_cw_<tag>.json   (stage A cache, one per capture)
  results/x10_replay_fusion.json     (stage B, accumulates one entry per label)
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
import soundfile as sf
from fractions import Fraction
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")
np.random.seed(0)  # hygiene only; pipeline is deterministic

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                      # noqa: E402
import m9_decode as m9d                            # noqa: E402  (import-only; frozen file untouched)
from h9_payload_codec import unpack_payload        # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod   # noqa: E402

SR = 48000
MANIFEST_PATH = _HERE / "master9_manifest.json"
RESULTS_DIR = _HERE / "results"
FUSION_PATH = RESULTS_DIR / "x10_replay_fusion.json"

# ---- FROZEN (see module docstring) ----------------------------------------
PLL_BW_HZ = 30.0
BRANCH_ALPHAS = (0.5, 0.6, 0.65, 0.7, 0.8)
BRANCHES = ("resampling_pll30",) + tuple(f"ema{a}" for a in BRANCH_ALPHAS)
DECISION_RUNGS = ("m9_m6_n256_rs191", "m9_m7_n256_p11_9000")
OVERLAP_HI = 80.0   # >= : recorded-in -> redirect spend to TX
OVERLAP_LO = 40.0   # <= : playback-borne -> fund replay diversity
SANITY_RATIO = 1.5  # flutter + noise-floor amplitude comparability bound
LANDED_RUNGS = ("m9_m0_reprove934", "m9_m1_thin159", "m9_m2_thin191",
                "m9_m3_dropnull9c", "m9_m4b_n256_rs159_var", "m9_m8_dense375")
FALSE_ACCEPT_BUDGET = 1e-4  # campaign-wide, at 2^-32 per CRC-acceptance trial
M7_NET_BPS = 2896.0
# ---------------------------------------------------------------------------


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def _true_msgs(sec: dict) -> list[bytes]:
    """Per-codeword TRUE message bytes from the payload sidecar (scoring /
    post-hoc audit only). Mirrors _rs_merge_guarded's reassembly order:
    recovered = concat(msg_cw0, msg_cw1, ...)[:payload_len]."""
    meta = sec["meta"]
    rs_k, n_cw = meta["rs_k"], meta["n_codewords"]
    packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    padded = packed + bytes(n_cw * rs_k - len(packed))
    return [padded[i * rs_k:(i + 1) * rs_k] for i in range(n_cw)]


def _rx_codeword_matrix(rx_frames, meta) -> np.ndarray:
    """Rebuild the de-interleaved (n_cw x rs_n) received codeword byte matrix.
    Same math as m9_decode._rs_merge_guarded (copied into this NEW file; the
    frozen file is not edited)."""
    rs_n, n_cw = meta["rs_n"], meta["n_codewords"]
    fb_bits, n_frames, stream_bits = meta["frame_bits"], meta["n_frames"], meta["stream_bits"]
    pieces = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else (stream_bits - fb_bits * (n_frames - 1))
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


def _crc_guarded_cw_decode(rx_mat: np.ndarray, meta: dict, crc_table: list[int]):
    """Errors-only RS decode of every codeword + CRC32 acceptance.
    Returns (accepted: dict cw_idx -> bytes, failed_idx, n_trials)."""
    from reedsolo import RSCodec, ReedSolomonError
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    rsc = RSCodec(rs_n - rs_k)
    accepted: dict[int, bytes] = {}
    failed: list[int] = []
    n_trials = 0
    for i in range(meta["n_codewords"]):
        n_trials += 1
        try:
            msg = bytes(rsc.decode(bytearray(rx_mat[i].tobytes()))[0])
            if (zlib.crc32(msg) & 0xFFFFFFFF) == crc_table[i]:
                accepted[i] = msg
            else:
                failed.append(i)
        except (ReedSolomonError, Exception):
            failed.append(i)
    return accepted, failed, n_trials


def _assemble_and_verify(accepted: dict[int, bytes], sec: dict):
    """Assemble packed payload from CRC-accepted codewords (NO truth used for
    assembly), then score: packed byte_exact vs sidecar, orig_exact via
    unpack + sha256 vs manifest."""
    meta = sec["meta"]
    rs_k, n_cw = meta["rs_k"], meta["n_codewords"]
    blob = b"".join(accepted.get(i, bytes(rs_k)) for i in range(n_cw))
    out = blob[:meta["payload_len"]]
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    byte_exact = out == expected
    byte_errors = sum(a != b for a, b in zip(out, expected)) + abs(len(out) - len(expected))
    orig_exact = False
    try:
        orig = unpack_payload(out)
        pk = sec["pack"]
        orig_exact = (hashlib.sha256(orig).hexdigest() == pk["sha256_orig"]
                      and len(orig) == pk["orig_len"])
    except Exception:
        pass
    return byte_exact, byte_errors, orig_exact


# ===========================================================================
# Stage A -- decode one capture: per-section per-branch CRC-guarded codewords.
# ===========================================================================
def stage_decode(capture: str, tag: str, sections_filter: list[str] | None) -> dict:
    t0 = time.time()
    manifest = _load_manifest()
    audio, sr = sf.read(capture, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)

    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    except Exception as exc:
        sounder = {"error": str(exc)}
    sstats = {k: sounder.get(k) for k in
              ("flutter_wrms_pct", "snr_db_median", "noise_floor_dbfs")} \
        if isinstance(sounder, dict) else {}

    out = {
        "capture": str(capture), "tag": tag, "branches": list(BRANCHES),
        "pll_bw_hz": PLL_BW_HZ, "erase_frac": 0.0,
        "sync": {"speed": float(sync["speed"]), "speed_offset": float(sync["speed_offset"]),
                 "chirp0_nominal": int(sync["chirp0_nominal"]), "align": int(align)},
        "sounder": sstats, "sections": {}, "n_trials": 0,
        "seeds": "deterministic decode -- no RNG used",
    }

    for sec in manifest["ws_payloads"]:
        name = sec["name"]
        if sec.get("skipped"):
            continue
        if sec["kind"] == "freqdiff":
            # m9a collapsed 37/37 on tape (predicted); timing-immune scheme has
            # no front-end branches -> excluded from replay fusion by design.
            continue
        if sections_filter and name not in sections_filter:
            continue
        sch = m9d._scheme_from_entry(sec)
        meta = sec["meta"]
        crc_table = sec["crc32_codewords"]
        truth = _true_msgs(sec)

        per_branch = {}
        sec_accepted: dict[int, bytes] = {}
        sec_accept_src: dict[int, list[str]] = {}
        conflicts = []
        for bname in BRANCHES:
            if bname == "resampling_pll30":
                dem = ResamplingPLLDemod(sch, pll_bw_hz=PLL_BW_HZ, front_end="pll")
            else:
                dem = ResamplingPLLDemod(sch, front_end="ema",
                                         ema_alpha=float(bname[3:]))
            fe = lambda w, nd, d=dem: d.demod(w, nd)
            tb = time.time()
            rx_frames, _diags = m9d._demod_section_frames(audio_nom, sec, align, sch, fe)
            rx_mat = _rx_codeword_matrix(rx_frames, meta)
            accepted, failed, n_tr = _crc_guarded_cw_decode(rx_mat, meta, crc_table)
            out["n_trials"] += n_tr
            per_branch[bname] = {"cw_failed": len(failed), "failed_idx": failed,
                                 "sec_s": round(time.time() - tb, 2)}
            for i, msg in accepted.items():
                if i in sec_accepted:
                    if sec_accepted[i] != msg:
                        conflicts.append({"cw": i, "branches": [sec_accept_src[i], bname]})
                    else:
                        sec_accept_src[i].append(bname)
                else:
                    sec_accepted[i] = msg
                    sec_accept_src[i] = [bname]

        # post-hoc audit vs manifest truth (audit ONLY -- not used in decisions)
        misc_idx = [i for i, msg in sec_accepted.items() if msg != truth[i]]
        union_failed = sorted(set(range(meta["n_codewords"])) - set(sec_accepted))
        byte_exact, byte_errors, orig_exact = _assemble_and_verify(sec_accepted, sec)

        out["sections"][name] = {
            "n_codewords": meta["n_codewords"], "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
            "projected_net_bps": sec.get("projected_net_bps"),
            "per_branch": per_branch,
            "within_capture_union": {
                "cw_failed": len(union_failed), "failed_idx": union_failed,
                "byte_exact": bool(byte_exact), "byte_errors": int(byte_errors),
                "orig_exact": bool(orig_exact),
            },
            "miscorrected_accepted_cw": misc_idx,       # expect [] (CRC guard)
            "crc_conflicts": conflicts,                 # expect [] (2^-32 events)
            "accepted_msgs_hex": {str(i): sec_accepted[i].hex() for i in sec_accepted},
            "accept_src": {str(i): v for i, v in sec_accept_src.items()},
        }
        u = out["sections"][name]["within_capture_union"]
        print(f"  [{tag}] {name:<24} union cwf {u['cw_failed']:>3}/{meta['n_codewords']:<3} "
              f"exact={u['byte_exact']} orig={u['orig_exact']} "
              f"misc={len(misc_idx)}", flush=True)

    out["elapsed_s"] = round(time.time() - t0, 1)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"x10_replay_cw_{tag}.json"
    path.write_text(json.dumps(out, indent=1, default=float))
    print(f"[stage A] {tag}: wrote {path} ({out['elapsed_s']} s, "
          f"{out['n_trials']} CRC trials)")
    return out


# ===========================================================================
# Stage B -- cross-capture CRC-guarded union + overlap matrix + verdicts.
# ===========================================================================
def stage_fuse(tag_a: str, tag_b: str, label: str, real_pair: bool) -> dict:
    manifest = _load_manifest()
    secs_by_name = {s["name"]: s for s in manifest["ws_payloads"]}
    caches = {}
    for t in (tag_a, tag_b):
        p = RESULTS_DIR / f"x10_replay_cw_{t}.json"
        caches[t] = json.loads(p.read_text())

    # ---- sanity arm: capture comparability -------------------------------
    sa, sb = caches[tag_a]["sounder"], caches[tag_b]["sounder"]
    sanity = {"flutter_a": sa.get("flutter_wrms_pct"), "flutter_b": sb.get("flutter_wrms_pct"),
              "nf_dbfs_a": sa.get("noise_floor_dbfs"), "nf_dbfs_b": sb.get("noise_floor_dbfs")}
    try:
        fr = max(sanity["flutter_a"], sanity["flutter_b"]) / max(
            1e-9, min(sanity["flutter_a"], sanity["flutter_b"]))
        nfr = 10 ** (abs(sanity["nf_dbfs_a"] - sanity["nf_dbfs_b"]) / 20.0)
        sanity.update(flutter_ratio=round(fr, 3), nf_amp_ratio=round(nfr, 3),
                      comparable=bool(fr <= SANITY_RATIO and nfr <= SANITY_RATIO))
    except Exception:
        sanity.update(flutter_ratio=None, nf_amp_ratio=None, comparable=None)

    # landed-rung regression on capture B standalone (within-capture union)
    landed_b = {}
    for r in LANDED_RUNGS:
        sb_sec = caches[tag_b]["sections"].get(r)
        landed_b[r] = bool(sb_sec and sb_sec["within_capture_union"]["orig_exact"])
    sanity["landed_rungs_orig_exact_on_b"] = landed_b
    sanity["landed_all_ok_on_b"] = all(landed_b.values())

    # ---- per-section cross-capture union ----------------------------------
    fusion_secs = {}
    total_trials = sum(caches[t]["n_trials"] for t in (tag_a, tag_b))
    total_misc = 0
    pooled_inter = pooled_min = 0
    for name in caches[tag_a]["sections"]:
        if name not in caches[tag_b]["sections"]:
            continue
        A, B = caches[tag_a]["sections"][name], caches[tag_b]["sections"][name]
        sec = secs_by_name[name]
        fa = set(A["within_capture_union"]["failed_idx"])
        fb = set(B["within_capture_union"]["failed_idx"])
        inter, uni = sorted(fa & fb), sorted(fa | fb)
        overlap_pct = (100.0 * len(inter) / min(len(fa), len(fb))
                       if fa and fb else None)
        if name in DECISION_RUNGS and fa and fb:
            pooled_inter += len(inter)
            pooled_min += min(len(fa), len(fb))

        # union of accepted msgs across captures; cross-capture conflict check
        acc: dict[int, bytes] = {}
        src: dict[int, list[str]] = {}
        xconf = []
        for t in (tag_a, tag_b):
            S = caches[t]["sections"][name]
            for k, hx in S["accepted_msgs_hex"].items():
                i, msg = int(k), bytes.fromhex(hx)
                if i in acc and acc[i] != msg:
                    xconf.append({"cw": i, "tags": [src[i], t]})
                elif i in acc:
                    src[i].append(t)
                else:
                    acc[i], src[i] = msg, [t]
        truth = _true_msgs(sec)
        misc_idx = [i for i, m in acc.items() if m != truth[i]]
        total_misc += len(misc_idx)
        res_failed = sorted(set(range(sec["meta"]["n_codewords"])) - set(acc))
        byte_exact, byte_errors, orig_exact = _assemble_and_verify(acc, sec)
        fusion_secs[name] = {
            "n_codewords": sec["meta"]["n_codewords"],
            "projected_net_bps": sec.get("projected_net_bps"),
            "failed_a": sorted(fa), "failed_b": sorted(fb),
            "intersection": inter, "union_of_failed": uni,
            "overlap_pct": overlap_pct,
            "cross_capture_union": {"cw_failed": len(res_failed),
                                    "failed_idx": res_failed,
                                    "byte_exact": bool(byte_exact),
                                    "byte_errors": int(byte_errors),
                                    "orig_exact": bool(orig_exact)},
            "fixed_by_second_capture": sorted(fa - fb), "fixed_a_to_b": sorted(fb - fa),
            "miscorrected_accepted_cw": misc_idx, "cross_capture_conflicts": xconf,
        }

    pooled_overlap = (100.0 * pooled_inter / pooled_min) if pooled_min else None
    if pooled_overlap is None:
        decision = "not-evaluable (decision rungs have empty failed sets)"
    elif pooled_overlap >= OVERLAP_HI:
        decision = "RECORDED-IN: redirect campaign spend to TX rungs"
    elif pooled_overlap <= OVERLAP_LO:
        decision = "PLAYBACK-BORNE: fund replay/multi-pass diversity as standing branch"
    else:
        decision = "INDETERMINATE: no spend redirection either way"

    false_accept = total_trials * 2.0 ** -32
    m7 = fusion_secs.get("m9_m7_n256_p11_9000", {})
    m7_res = m7.get("cross_capture_union", {}).get("cw_failed")
    record_pass = bool(m7 and m7["cross_capture_union"]["orig_exact"]
                       and total_misc == 0)

    entry = {
        "label": label, "tags": [tag_a, tag_b], "real_pair": bool(real_pair),
        "decision_rule_armed": bool(real_pair),
        "branches": list(BRANCHES),
        "captures": {t: {"path": caches[t]["capture"], "sync": caches[t]["sync"],
                         "sounder": caches[t]["sounder"]} for t in (tag_a, tag_b)},
        "sanity": sanity,
        "sections": fusion_secs,
        "pooled_overlap_pct_m6_m7": pooled_overlap,
        "decision_if_armed": decision,
        "decision_applies": bool(real_pair),
        "m7_residual_cw_after_union": m7_res,
        "record_pass_m7_2896_multipass_category": record_pass if real_pair else None,
        "record_pass_note": ("multi-pass category record; does NOT supersede "
                             "single-capture records (sidecar-CRC convention caveat)"),
        "trials_total": total_trials,
        "false_accept_bound": false_accept,
        "false_accept_budget_ok": bool(false_accept < FALSE_ACCEPT_BUDGET),
        "miscorrected_total_posthoc": total_misc,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    fusion = json.loads(FUSION_PATH.read_text()) if FUSION_PATH.exists() else \
        {"what": "x10 replay-diversity fusion (cross-capture CRC-guarded union)",
         "pre_registered_rule": {
             "statistic": "pooled overlap = 100*sum|Fa^Fb|/sum(min|Fa|,|Fb|) over m6,m7",
             "thresholds": {"recorded_in_ge": OVERLAP_HI, "fund_diversity_le": OVERLAP_LO},
             "frozen": "2026-06-12 BEFORE tape9_run2 capture exists",
             "branches": list(BRANCHES), "sanity_ratio": SANITY_RATIO,
             "false_accept_budget": FALSE_ACCEPT_BUDGET},
         "pairs": {}}
    fusion["pairs"][label] = entry
    FUSION_PATH.write_text(json.dumps(fusion, indent=1, default=float))

    print(f"[stage B] pair '{label}' ({tag_a} x {tag_b})  armed={real_pair}")
    print(f"  sanity comparable={sanity.get('comparable')} "
          f"flutter_ratio={sanity.get('flutter_ratio')} nf_amp_ratio={sanity.get('nf_amp_ratio')} "
          f"landed_ok_on_b={sanity['landed_all_ok_on_b']}")
    for name, s in fusion_secs.items():
        cc = s["cross_capture_union"]
        ov = "-" if s["overlap_pct"] is None else f"{s['overlap_pct']:.0f}%"
        print(f"  {name:<24} Fa={len(s['failed_a']):>2} Fb={len(s['failed_b']):>2} "
              f"^={len(s['intersection']):>2} ov={ov:>4}  union-> {cc['cw_failed']:>2} cwf "
              f"exact={cc['byte_exact']} orig={cc['orig_exact']}")
    print(f"  pooled overlap (m6,m7) = {pooled_overlap}  -> {decision}"
          f"{' [ARMED]' if real_pair else ' [validation only, rule NOT armed]'}")
    print(f"  trials={total_trials} false_accept_bound={false_accept:.2e} "
          f"(budget ok={entry['false_accept_budget_ok']})  miscorrected={total_misc}")
    print(f"[stage B] wrote {FUSION_PATH}")
    return entry


# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode")
    d.add_argument("--capture", required=True)
    d.add_argument("--tag", required=True)
    d.add_argument("--sections", default=None,
                   help="comma-separated section names (default: all dqpsk)")
    f = sub.add_parser("fuse")
    f.add_argument("--tag-a", required=True)
    f.add_argument("--tag-b", required=True)
    f.add_argument("--label", required=True)
    f.add_argument("--real-pair", action="store_true",
                   help="arm the pre-registered decision rule (real tape9 run1 x run2)")
    args = ap.parse_args()
    if args.cmd == "decode":
        flt = args.sections.split(",") if args.sections else None
        stage_decode(args.capture, args.tag, flt)
    else:
        stage_fuse(args.tag_a, args.tag_b, args.label, args.real_pair)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
