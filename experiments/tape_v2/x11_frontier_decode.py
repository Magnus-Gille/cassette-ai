"""x11_frontier_decode.py -- decode/self-check the x11-frontier sections.

The x10 dense2x union-receiver pattern, parametrized by the x11 manifest:
ONE global sync (chirp pair), then per-section CRC32-guarded union decode.
dense2x sections sweep the manifest rx_window_plan (hann256_skip0 primary,
rect128_skip64 alternate) x (EMA alpha 0.6-0.8 + resampling-PLL 30/45);
the anchor uses the exact production m9 chain.  ERASE_FRACS=(0.0,) is
pre-registered (tape9: erasures monotonically hurt).  Every CRC32 acceptance
test is counted into the trial ledger (campaign false-accept budget < 1e-4).

Primary x11 use: the MANDATORY no-channel self-check of the section
generators (byte-exact AND orig-exact on the clean wav).  No tape pass is
sanctioned (manifest print_authorized=false), but the decoder works on a
capture if one ever exists -- with the anchor-reproves-2572 validity rule.

Usage:
    python3 x11_frontier_decode.py x11_master_frontier.wav --out-tag selfcheck_nochan
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
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

import analyze_master2 as am2                          # noqa: E402
import m3_codec as codec                               # noqa: E402
from h4_dqpsk import DQPSKScheme                       # noqa: E402
from h9_payload_codec import unpack_payload            # noqa: E402
import m9_decode as m9d                                # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod       # noqa: E402
from x10_b_aggr_05_dense2x_master import Dense2xDropScheme  # noqa: E402

SR = codec.FS
RESULTS_DIR = _HERE / "results"
MANIFEST_PATH = _HERE / "x11_master_frontier_manifest.json"
ERASE_FRACS = (0.0,)        # pre-registered


# ===========================================================================
def _tx_scheme(sec):
    p = sec["dqpsk_params"]
    if sec["kind"] == "dqpsk":
        return DQPSKScheme(p["P"], p["N"], p["spacing"],
                           min_spacing_hz=p.get("min_spacing_hz", 562.0))
    if sec["kind"] == "dense2x_drop":
        return Dense2xDropScheme(p["P"], p["drop_freqs_hz"],
                                 pilot_hz=p["pilot_hz"],
                                 skip=p.get("skip") or 64)
    raise ValueError(sec["kind"])


def _rx_scheme(sec, geometry):
    p = sec["dqpsk_params"]
    skip = 0 if geometry == "hann256_skip0" else 64
    sch = Dense2xDropScheme(p["P"], p["drop_freqs_hz"],
                            pilot_hz=p["pilot_hz"], skip=skip)
    if geometry == "rect128_skip64":
        sch._win = np.ones(sch.Nw)
    return sch


def _frontends_for(sec):
    out = []
    if sec["kind"] == "dqpsk":          # anchor: production m9 chain
        sch = _tx_scheme(sec)
        pll = ResamplingPLLDemod(sch, pll_bw_hz=30.0, front_end="pll")
        out.append(("anchor_pll30", sch, lambda w, nd, d=pll: d.demod(w, nd)))
        for a in (0.5, 0.6, 0.4):
            ema = ResamplingPLLDemod(sch, front_end="ema", ema_alpha=a)
            out.append((f"anchor_ema{a}", sch,
                        lambda w, nd, d=ema: d.demod(w, nd)))
        return out
    plan = [("hann256_skip0", "ema", 0.7), ("hann256_skip0", "ema", 0.8),
            ("hann256_skip0", "ema", 0.6), ("hann256_skip0", "pll", 30.0),
            ("hann256_skip0", "pll", 45.0), ("rect128_skip64", "ema", 0.7),
            ("rect128_skip64", "pll", 30.0), ("hann256_skip0", "ema", 0.5)]
    for geo, fe, val in plan:
        sch = _rx_scheme(sec, geo)
        if fe == "ema":
            dem = ResamplingPLLDemod(sch, front_end="ema", ema_alpha=val)
            label = f"{geo}_ema{val}"
        else:
            dem = ResamplingPLLDemod(sch, pll_bw_hz=val, front_end="pll")
            label = f"{geo}_pll{val:g}"
        out.append((label, sch, lambda w, nd, d=dem: d.demod(w, nd)))
    return out


def _decode_section(audio_nom, sec, align, ledger):
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    sch_tx = _tx_scheme(sec)

    best, attempts = None, []
    for label, sch_rx, fe in _frontends_for(sec):
        rx_frames, _diags = m9d._demod_section_frames(audio_nom, sec, align,
                                                      sch_rx, fe)
        for ef in ERASE_FRACS:
            out, cwf, misc, _ne = m9d._rs_merge_guarded(
                rx_frames, meta, crc_table, erase_frac=ef, rel_cw=None)
            ledger["crc_trials"] += meta["n_codewords"]
            exact = out == expected_packed
            byte_err = sum(a != b for a, b in zip(out, expected_packed)) + abs(
                len(out) - len(expected_packed))
            att = {"front_end": label, "erase_frac": ef, "byte_exact": exact,
                   "cw_failed": cwf, "miscorrected": misc,
                   "byte_errors": byte_err, "_packed": out,
                   "_rx_frames": rx_frames}
            attempts.append({k: v for k, v in att.items()
                             if not k.startswith("_")})
            if best is None or m9d._better(att, best):
                best = att
            if exact:
                break
        if best is not None and best.get("byte_exact"):
            break

    per_carrier_ser = m9d._per_carrier_ser(best["_rx_frames"], sec, sch_tx,
                                           expected_packed) if best else None
    recovered_packed = best["_packed"] if best else bytes(meta["payload_len"])
    res = {
        "name": sec["name"], "kind": sec["kind"], "tier": sec.get("tier"),
        "scheme": sec["phy"], "margin_gate_verdict": sec.get("margin_gate_verdict"),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
        "projected_net_bps": sec.get("projected_net_bps"),
        "x_record": sec.get("x_record"),
        "rs_codewords_failed": best["cw_failed"] if best else meta["n_codewords"],
        "miscorrected_cw": best["miscorrected"] if best else 0,
        "byte_errors": best["byte_errors"] if best else None,
        "byte_exact": bool(best["byte_exact"]) if best else False,
        "front_end_used": best["front_end"] if best else None,
        "per_carrier_ser": per_carrier_ser,
        "sweep_attempts": attempts,
    }
    return res, recovered_packed


# ===========================================================================
def decode(recording_path: str, out_tag: str | None = None,
           verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest.get("master_id") == "x11_frontier", \
        "manifest master_id mismatch -- refusing"
    audio, sr = sf.read(recording_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)

    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]

    ledger = {"crc_trials": 0}
    results = []
    for sec in manifest["ws_payloads"]:
        r, recovered_packed = _decode_section(audio_nom, sec, align, ledger)
        pack = sec["pack"]
        try:
            recovered_orig = unpack_payload(recovered_packed)
            sha_o = hashlib.sha256(recovered_orig).hexdigest()
            r["unpack_ok"] = True
            r["orig_byte_exact"] = (sha_o == pack["sha256_orig"]
                                    and len(recovered_orig) == pack["orig_len"])
        except Exception as exc:
            r["unpack_ok"] = False
            r["orig_byte_exact"] = False
            r["unpack_error"] = str(exc)
        results.append(r)
        if verbose:
            print(f"  [{r['name']:32s}] cw {r['rs_codewords_failed']}/"
                  f"{r['n_codewords']} fe={r['front_end_used']} "
                  f"PACK={'YES' if r['byte_exact'] else 'no'} "
                  f"ORIG={'YES' if r['orig_byte_exact'] else 'no'}", flush=True)

    anchor_ok = any(r["name"] == "x11_anchor_2572" and r["orig_byte_exact"]
                    for r in results)
    fa_bound = ledger["crc_trials"] * 2.0 ** -32
    out = {
        "recording": str(recording_path),
        "tape": "x11_frontier",
        "print_authorized": manifest.get("print_authorized"),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "payloads": results,
        "anchor_reproved": bool(anchor_ok),
        "tape_pass_valid": bool(anchor_ok),
        "miscorrected_total": sum(r["miscorrected_cw"] for r in results),
        "crc_trial_ledger": {"crc_trials": ledger["crc_trials"],
                             "false_accept_bound": fa_bound,
                             "budget": 1e-4,
                             "within_budget": bool(fa_bound < 1e-4)},
        "n_byte_exact_packed": sum(bool(r["byte_exact"]) for r in results),
        "n_orig_exact": sum(bool(r["orig_byte_exact"]) for r in results),
        "n_payloads": len(results),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    json_path = RESULTS_DIR / f"x11_frontier_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[x11_decode] anchor_reproved={anchor_ok} "
              f"orig-exact {out['n_orig_exact']}/{out['n_payloads']} "
              f"misc={out['miscorrected_total']} "
              f"fa_bound={fa_bound:.2e} -> {json_path.name}")
    return out


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, args.out_tag)
