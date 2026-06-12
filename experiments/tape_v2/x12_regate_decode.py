"""x12_regate_decode.py -- decode/self-check the x12-regate ladder.

The x11 union-receiver pattern parametrized by the x12 manifest: ONE global
sync (chirp pair), then per-section CRC32-guarded union decode.

  dqpsk / dense2x_drop sections (the canary pair) reuse the FROZEN x11
  front-end sweep verbatim (x11_frontier_decode._frontends_for / _tx_scheme,
  imported, not copied);
  dbpsk_drop sections use the frozen x12 DBPSK sweep
  (x12_regate_master.dbpsk_frontends -- ResamplingPLLDemod subclass with the
  90-deg decision boundary).

ERASE_FRACS=(0.0,) is pre-registered.  Every CRC32 acceptance test is counted
into the trial ledger (campaign false-accept budget < 1e-4).  Validity rule
(prereg canary rule): a tape pass is valid iff BOTH canaries (2572 anchor AND
4910 d2x banker) decode orig-exact.

Primary x12 use: the MANDATORY no-channel self-check of the section
generators (byte-exact AND orig-exact on the clean wav):
    python3 x12_regate_decode.py x12_master_regate.wav --out-tag selfcheck_nochan
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

import analyze_master2 as am2                              # noqa: E402
import m3_codec as codec                                   # noqa: E402
from h9_payload_codec import unpack_payload                # noqa: E402
import m9_decode as m9d                                    # noqa: E402
from x11_frontier_decode import (                          # noqa: E402
    _tx_scheme as _x11_tx_scheme, _frontends_for as _x11_frontends)
from x12_regate_master import (                            # noqa: E402
    X12DBPSKDropScheme, dbpsk_frontends)

SR = codec.FS
RESULTS_DIR = _HERE / "results"
MANIFEST_PATH = _HERE / "x12_master_regate_manifest.json"
ERASE_FRACS = (0.0,)            # pre-registered


def _tx_scheme(sec):
    if sec["kind"] == "dbpsk_drop":
        p = sec["dqpsk_params"]
        return X12DBPSKDropScheme(p["P"], p["drop_freqs_hz"],
                                  pilot_hz=p["pilot_hz"],
                                  skip=p.get("skip") or 64)
    return _x11_tx_scheme(sec)


def _frontends_for(sec):
    if sec["kind"] == "dbpsk_drop":
        return [(label, None, fe) for label, fe in dbpsk_frontends(sec)]
    return _x11_frontends(sec)


def _decode_section(audio_nom, sec, align, ledger):
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    sch_tx = _tx_scheme(sec)

    best, attempts = None, []
    for label, sch_rx, fe in _frontends_for(sec):
        rx_frames, _diags = m9d._demod_section_frames(
            audio_nom, sec, align, sch_rx if sch_rx is not None else sch_tx, fe)
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
        "scheme": sec["phy"],
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
        "projected_net_bps": sec.get("projected_net_bps"),
        "rs_codewords_failed": best["cw_failed"] if best else meta["n_codewords"],
        "miscorrected_cw": best["miscorrected"] if best else 0,
        "byte_errors": best["byte_errors"] if best else None,
        "byte_exact": bool(best["byte_exact"]) if best else False,
        "front_end_used": best["front_end"] if best else None,
        "per_carrier_ser": per_carrier_ser,
        "carrier_freqs_hz": sec.get("carrier_freqs_hz"),
        "sweep_attempts": attempts,
    }
    return res, recovered_packed


# ===========================================================================
def decode(recording_path: str, out_tag: str | None = None,
           verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest.get("master_id") == "x12_regate", \
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
            print(f"  [{r['name']:24s}] cw {r['rs_codewords_failed']}/"
                  f"{r['n_codewords']} fe={r['front_end_used']} "
                  f"PACK={'YES' if r['byte_exact'] else 'no'} "
                  f"ORIG={'YES' if r['orig_byte_exact'] else 'no'}", flush=True)

    def _ok(name):
        return any(r["name"] == name and r["orig_byte_exact"] for r in results)

    anchor_ok = _ok("x12_c0_anchor_2572")
    d2x_ok = _ok("x12_c1_d2x_4910")
    fa_bound = ledger["crc_trials"] * 2.0 ** -32
    out = {
        "recording": str(recording_path),
        "tape": "x12_regate",
        "print_authorized": manifest.get("print_authorized"),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "payloads": results,
        "anchor_2572_reproved": bool(anchor_ok),
        "d2x_4910_canary_reproved": bool(d2x_ok),
        "tape_pass_valid": bool(anchor_ok and d2x_ok),
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
    json_path = RESULTS_DIR / f"x12_regate_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[x12_decode] canaries anchor={anchor_ok} d2x4910={d2x_ok} "
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
