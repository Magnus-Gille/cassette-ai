"""x10_b_aggr_05_dense2x_decode.py -- recover the master10-dense2x tape.

m9_decode pattern: ONE global sync (chirp pair), then per-section decode through
a CRC32-guarded union receiver.  For the dense2x sections the receiver sweeps
BOTH probe-validated window geometries (TX is identical for all of them):

  hann256_skip0  -- Hann over the full 256-sample symbol (2-bin orthogonal,
                    soft guard; probe winner: mean SER 3.85 % @ ema0.7)
  rect128_skip64 -- rect window, 1.33 ms hard guard, integer-cycle orthogonal
                    at 1-bin spacing (probe: 5.8 %)

per geometry: x9 resampling PLL (bw 30/45) + proven EMA loop (alpha 0.5-0.8).
ERASE_FRACS = (0.0,) is PRE-REGISTERED: erasures monotonically hurt on tape9.
Every CRC32 acceptance test is counted into a trial ledger; the cumulative
false-accept bound (trials * 2^-32) is reported and must stay < 1e-4.

The anchor section decodes through the EXACT production m9 chain (PLL bw30 +
EMA 0.5/0.6 on the native Hann/skip64 N512 geometry) -- it must reprove
2572 net bps orig-exact or the whole tape pass is void.

Usage:
    python3 x10_b_aggr_05_dense2x_decode.py x10_master_dense2x.wav --out-tag selfcheck
    python3 x10_b_aggr_05_dense2x_decode.py captures/tape10_run1.wav
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
from x10_b_aggr_05_dense2x_master import (             # noqa: E402
    Dense2xScheme, Dense2xDropScheme, MANIFEST_PATH,
)

SR = codec.FS
RESULTS_DIR = _HERE / "results"
ERASE_FRACS = (0.0,)        # pre-registered: erasures only hurt on tape9


# ===========================================================================
# scheme factories
# ===========================================================================
def _tx_scheme(sec):
    """Framing/flen/quadrant-mapping scheme (geometry-independent of rx skip)."""
    p = sec["dqpsk_params"]
    if sec["kind"] == "dqpsk":
        return DQPSKScheme(p["P"], p["N"], p["spacing"],
                           min_spacing_hz=p.get("min_spacing_hz", 562.0))
    if sec["kind"] == "dense2x":
        return Dense2xScheme(p["P"], skip=p.get("skip") or 64)
    if sec["kind"] == "dense2x_drop":
        return Dense2xDropScheme(p["P"], p["drop_freqs_hz"],
                                 pilot_hz=p["pilot_hz"],
                                 skip=p.get("skip") or 64)
    raise ValueError(sec["kind"])


def _rx_scheme(sec, geometry):
    """Receiver-window variant of the section's scheme."""
    p = sec["dqpsk_params"]
    skip = 0 if geometry == "hann256_skip0" else 64
    if sec["kind"] == "dense2x":
        sch = Dense2xScheme(p["P"], skip=skip)
    else:
        sch = Dense2xDropScheme(p["P"], p["drop_freqs_hz"],
                                pilot_hz=p["pilot_hz"], skip=skip)
    if geometry == "rect128_skip64":
        sch._win = np.ones(sch.Nw)
    return sch


# ===========================================================================
# per-section union receiver
# ===========================================================================
def _frontends_for(sec):
    """Ordered (label, scheme, demod) candidates; probe-ranked first so the
    early-stop usually takes the first attempt."""
    out = []
    if sec["kind"] == "dqpsk":          # anchor: exact production m9 chain
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

    best = None
    attempts = []
    for label, sch_rx, fe in _frontends_for(sec):
        rx_frames, diags = m9d._demod_section_frames(audio_nom, sec, align,
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
        "name": sec["name"], "kind": sec["kind"], "role": sec.get("role", ""),
        "scheme": sec["phy"], "phy": sec["phy"],
        "payload_bytes": len(expected_packed),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
        "gross_bps": sec.get("gross_bps"),
        "projected_net_bps": sec.get("projected_net_bps"),
        "x_record": sec.get("x_record"),
        "rs_codewords_failed": best["cw_failed"] if best else meta["n_codewords"],
        "miscorrected_cw": best["miscorrected"] if best else 0,
        "byte_errors": best["byte_errors"] if best else None,
        "byte_exact": bool(best["byte_exact"]) if best else False,
        "front_end_used": best["front_end"] if best else None,
        "erase_frac_used": best["erase_frac"] if best else None,
        "per_carrier_ser": per_carrier_ser,
        "sweep_attempts": attempts,
    }
    return res, recovered_packed


# ===========================================================================
def decode(recording_path: str, out_tag: str | None = None,
           verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
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
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    except Exception as exc:
        sounder = {"error": str(exc)}

    ledger = {"crc_trials": 0}
    results = []
    for sec in manifest["ws_payloads"]:
        r, recovered_packed = _decode_section(audio_nom, sec, align, ledger)
        pack = sec["pack"]
        crc_ok = unpack_ok = orig_exact = None
        try:
            recovered_orig = unpack_payload(recovered_packed)
            unpack_ok = True
            sha_o = hashlib.sha256(recovered_orig).hexdigest()
            orig_exact = (sha_o == pack["sha256_orig"]
                          and len(recovered_orig) == pack["orig_len"])
            crc_ok = orig_exact
        except Exception as exc:
            unpack_ok = False
            r["unpack_error"] = str(exc)
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        r["unpack_ok"] = unpack_ok
        r["orig_byte_exact"] = orig_exact
        r["crc_check"] = crc_ok
        results.append(r)
        if verbose:
            print(f"  [{r['name']:24s}] cw {r['rs_codewords_failed']}/"
                  f"{r['n_codewords']} fe={r['front_end_used']} "
                  f"PACK={'YES' if r['byte_exact'] else 'no'} "
                  f"ORIG={'YES' if r['orig_byte_exact'] else 'no'}", flush=True)

    anchor_ok = any(r["name"] == "x10_anchor_m8dense375"
                    and r.get("orig_byte_exact") for r in results)
    fa_bound = ledger["crc_trials"] * 2.0 ** -32
    out = {
        "recording": str(recording_path),
        "tape": "master10_dense2x",
        "candidate": "B-aggr-05-dense2x",
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {k: v for k, v in (sounder or {}).items()
                    if k not in ("H_db", "snr_db_per_tone", "sounder_freqs",
                                 "H_phase", "phase_rad", "H_phase_rad")},
        "payloads": results,
        "anchor_reproved": bool(anchor_ok),
        "tape_pass_valid": bool(anchor_ok),
        "crc_trial_ledger": {"crc_trials": ledger["crc_trials"],
                             "false_accept_bound": fa_bound,
                             "budget": 1e-4,
                             "within_budget": bool(fa_bound < 1e-4)},
        "n_byte_exact_packed": sum(bool(r.get("byte_exact")) for r in results),
        "n_orig_exact": sum(bool(r.get("orig_byte_exact")) for r in results),
        "n_payloads": len(results),
    }
    ex = [r for r in results if r.get("orig_byte_exact")
          and r["name"] != "x10_anchor_m8dense375"]
    if ex and anchor_ok:
        bestr = max(ex, key=lambda r: r.get("projected_net_bps") or 0)
        out["best_orig_exact_rung"] = {
            "name": bestr["name"],
            "net_bps": bestr.get("projected_net_bps"),
            "x_record": bestr.get("x_record"),
            "front_end": bestr.get("front_end_used")}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    json_path = RESULTS_DIR / f"x10_dense2x_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[x10_decode] anchor_reproved={anchor_ok} "
              f"orig-exact {out['n_orig_exact']}/{out['n_payloads']} "
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
