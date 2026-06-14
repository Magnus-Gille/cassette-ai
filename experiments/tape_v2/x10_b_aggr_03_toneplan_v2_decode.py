"""x10_b_aggr_03_toneplan_v2_decode.py — recover the x10_master10 ladder.

m9_decode.py pattern, manifest-driven: ONE global sync (chirp pair + front
sounder via analyze_master2), then every rung through the COMMON receiver chain:

  * front-ends: x9 resampling-PLL (bw 30 Hz) + proven EMA-integer-drift loop at
    alphas (0.5, 0.6, 0.65, 0.7) — 0.65/0.7 added per the tape9 forensics note
    that ema0.6 strictly beat 0.5/pll on N256 and finer alphas are unexplored
    receiver-side headroom (a strict SUPERSET of the m9 sweep; nothing removed).
  * RS merge: m9_decode._rs_merge_guarded VERBATIM (imported, not copied) —
    CRC32-per-codeword manifest guard, erase fractions (0.0, 0.25, 0.5).
  * keep the CRC-verified byte-exact winner; per-carrier SER vs the sidecar
    truth (scoring only); h9 unpack + sha256 orig-exact verification.

DECODE-TIME PLACEMENT RE-DERIVATION (new vs m9): the front sounder's H(f) is
interpolated at every rung's carrier+pilot frequencies and logged per rung
(`carrier_H_db`, `notches`), so a migrated deck notch is visible IMMEDIATELY in
the result JSON next to the per-carrier SER it explains. Diagnostics only — it
never changes a decision (tape9 evidence: reliability-driven erasures only hurt).

Self-check (clean draft, must be 6/6 orig-exact):
    python3 experiments/tape_v2/x10_b_aggr_03_toneplan_v2_decode.py \
        experiments/tape_v2/x10_master10_draft.wav
Real capture:
    python3 experiments/tape_v2/x10_b_aggr_03_toneplan_v2_decode.py \
        experiments/tape_v2/captures/<tape10 capture>.wav

Output: results/x10_b_aggr_03_toneplan_v2_results_<tag>.json
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

import analyze_master2 as am2  # noqa: E402
import m3_codec as codec  # noqa: E402
from h4_dqpsk import DQPSKScheme, PAD_LO_S, PAD_HI_S  # noqa: E402
from h9_payload_codec import unpack_payload  # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod  # noqa: E402
# RS merge + helpers imported VERBATIM from the proven m9 decoder (no copy drift)
from m9_decode import (  # noqa: E402
    _rs_merge_guarded, _frame_reliability_to_cw, _per_carrier_ser, _better,
)
from x10_b_aggr_03_toneplan_v2_scheme import MappedDQPSK  # noqa: E402

SR = codec.FS
MANIFEST_PATH = _HERE / "x10_master10_manifest.json"
RESULTS_DIR = _HERE / "results"

PLL_BW_HZ = 30.0
EMA_ALPHAS = (0.5, 0.6, 0.65, 0.7)     # superset of m9 (0.4 dropped: always worst)
ERASE_FRACS = (0.0, 0.25, 0.5)


def _scheme_from_entry(sec: dict):
    p = sec["dqpsk_params"]
    if sec["kind"] == "dqpsk_mapped":
        return MappedDQPSK(p["P"], p["N"], p["data_bins"], p["pilot_bin"])
    return DQPSKScheme(p["P"], p["N"], p["spacing"],
                       min_spacing_hz=p.get("min_spacing_hz", 562.0))


def _nominal_frame_bits(meta: dict) -> list[int]:
    fb = meta["frame_bits"]
    n = meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


def _demod_section_frames(audio_nom, sec, align, sch, frontend):
    meta = sec["meta"]
    nom_bits = _nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    full_frame = np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8)),
                            np.float32)
    flen_full = len(full_frame)
    rx_frames, diags = [], []
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(audio_nom), st + flen_full + pad_hi)
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        bits, diag = frontend(win, nd)
        rx_frames.append(np.asarray(bits, np.uint8))
        diags.append(diag)
    return rx_frames, diags


# ---------------------------------------------------------------------------
# decode-time carrier-placement re-derivation from the in-master sounder
# ---------------------------------------------------------------------------
def _carrier_health(sounder, sch):
    """Interpolated sounder H(f) [dB] at each carrier + pilot, plus the deepest
    in-band sounder notches. Diagnostics only — never changes a decision."""
    if not isinstance(sounder, dict) or "H_db" not in sounder or "sounder_freqs" not in sounder:
        return None
    try:
        fr = np.asarray(sounder["sounder_freqs"], float)
        hd = np.asarray(sounder["H_db"], float)
        all_f = np.asarray(sch.freqs, float)
        h_at = np.interp(all_f, fr, hd)
        band = (fr >= 1000) & (fr <= 11000)
        order = np.argsort(hd[band])
        notch_f = fr[band][order[:3]]
        notch_h = hd[band][order[:3]]
        flagged = [
            {"freq_hz": round(float(all_f[i]), 1),
             "H_db": round(float(h_at[i]), 1),
             "is_pilot": bool(i == sch.pilot_idx)}
            for i in range(len(all_f))
        ]
        return {"carrier_H_db": flagged,
                "deepest_notches": [{"freq_hz": round(float(f), 1), "H_db": round(float(h), 1)}
                                    for f, h in zip(notch_f, notch_h)]}
    except Exception:
        return None


def _decode_section(audio_nom, sec, align, sounder):
    sch = _scheme_from_entry(sec)
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()

    frontends: list[tuple[str, callable]] = []
    pll = ResamplingPLLDemod(sch, pll_bw_hz=PLL_BW_HZ, front_end="pll")
    frontends.append(("resampling_pll", lambda w, nd, d=pll: d.demod(w, nd)))
    for a in EMA_ALPHAS:
        ema = ResamplingPLLDemod(sch, front_end="ema", ema_alpha=a)
        frontends.append((f"ema{a}", lambda w, nd, d=ema: d.demod(w, nd)))

    best = None
    attempts: list[dict] = []
    for fe_name, fe in frontends:
        rx_frames, diags = _demod_section_frames(audio_nom, sec, align, sch, fe)
        rel_cw = _frame_reliability_to_cw(diags, meta)
        for ef in ERASE_FRACS:
            out, cwf, misc, ne = _rs_merge_guarded(
                rx_frames, meta, crc_table, erase_frac=ef, rel_cw=rel_cw)
            exact = out == expected_packed
            byte_err = sum(a != b for a, b in zip(out, expected_packed)) + abs(
                len(out) - len(expected_packed))
            att = {"front_end": fe_name, "erase_frac": ef, "byte_exact": exact,
                   "cw_failed": cwf, "miscorrected": misc, "byte_errors": byte_err,
                   "_packed": out, "_rx_frames": rx_frames}
            attempts.append({k: v for k, v in att.items() if not k.startswith("_")})
            if best is None or _better(att, best):
                best = att
            if exact:
                break
        if best is not None and best.get("byte_exact"):
            break

    per_carrier_ser = _per_carrier_ser(best["_rx_frames"], sec, sch, expected_packed) \
        if best else None
    recovered_packed = best["_packed"] if best else bytes(meta["payload_len"])

    res = {
        "name": sec["name"], "kind": sec["kind"], "role": sec.get("role", ""),
        "scheme": sec["phy"], "phy": sec["phy"], "status": sec.get("status", "ACTIVE"),
        "llm_offset": sec.get("llm_offset", 0),
        "payload_bytes": len(expected_packed),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
        "gross_bps": sec.get("gross_bps"), "projected_net_bps": sec.get("projected_net_bps"),
        "x_record": sec.get("x_record"),
        "rs_codewords_failed": best["cw_failed"] if best else meta["n_codewords"],
        "miscorrected_cw": best["miscorrected"] if best else 0,
        "byte_errors": best["byte_errors"] if best else None,
        "byte_exact": bool(best["byte_exact"]) if best else False,
        "front_end_used": best["front_end"] if best else None,
        "erase_frac_used": best["erase_frac"] if best else None,
        "per_carrier_ser": per_carrier_ser,
        "carrier_freqs_hz": sec.get("carrier_freqs_hz"),
        "pilot_hz": sec.get("pilot_hz"),
        "placement_health": _carrier_health(sounder, sch),
        "sweep_attempts": attempts,
    }
    return res, recovered_packed


def decode(recording_path: str, out_tag: str | None = None, verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(recording_path, dtype="float32", always_2d=False)
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

    results = []
    for sec in manifest["ws_payloads"]:
        r, recovered_packed = _decode_section(audio_nom, sec, align, sounder)
        pack = sec["pack"]
        unpack_ok = orig_exact = None
        try:
            recovered_orig = unpack_payload(recovered_packed)
            unpack_ok = True
            sha_o = hashlib.sha256(recovered_orig).hexdigest()
            orig_exact = (sha_o == pack["sha256_orig"]
                          and len(recovered_orig) == pack["orig_len"])
        except Exception as exc:
            unpack_ok = False
            r["unpack_error"] = str(exc)
        r["effective_bps"] = sec.get("effective_bps")
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        r["unpack_ok"] = unpack_ok
        r["orig_byte_exact"] = orig_exact
        results.append(r)

    anchor = next((r for r in results if r["name"] == "x10_x0_anchor2572"), None)
    anchor_ok = bool(anchor and anchor.get("orig_byte_exact"))

    if verbose:
        _print_table(recording_path, sync, sounder, align, results, anchor_ok)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    out = {
        "recording": str(recording_path),
        "tape": "x10_master10",
        "candidate": "B-aggr-03-toneplan-v2",
        "record_convention": manifest.get("record_convention"),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {k: v for k, v in (sounder or {}).items()
                    if k not in ("H_db", "snr_db_per_tone", "sounder_freqs", "H_phase",
                                 "phase_rad", "H_phase_rad")},
        "anchor_reproved_2572": anchor_ok,
        "tape_pass_valid": anchor_ok,
        "payloads": results,
        "n_byte_exact_packed": sum(bool(r.get("byte_exact")) for r in results),
        "n_orig_exact": sum(bool(r.get("orig_byte_exact")) for r in results),
        "n_payloads": len(results),
    }
    json_path = RESULTS_DIR / f"x10_b_aggr_03_toneplan_v2_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[x10_decode] wrote {json_path}")
    return out


def _print_table(recording_path, sync, sounder, align, results, anchor_ok):
    print(f"[x10_decode] {recording_path}")
    print(f"  recovered clock: {sync['speed']:.4f}x "
          f"(offset {sync['speed_offset'] * 100:+.2f}%), align {align:+d}")
    if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
        print(f"  sounder: flutter {sounder['flutter_wrms_pct']:.2f}%, "
              f"SNR med {sounder.get('snr_db_median')} dB, "
              f"nf {sounder.get('noise_floor_dbfs')} dBFS")
    print(f"\n  {'rung':<24} {'phy':<18} {'RS':>9} {'net':>7} "
          f"{'cwFail':>8} {'front-end':>15} {'PACK':>5} {'ORIG':>5}")
    for r in results:
        rs = f"({r['rs_n']},{r['rs_k']})"
        cw = f"{r['rs_codewords_failed']}/{r['n_codewords']}"
        pk = "YES" if r.get("byte_exact") else "no"
        og = "YES" if r.get("orig_byte_exact") else "no"
        fe = r.get("front_end_used") or "-"
        print(f"  {r['name']:<24} {r['phy']:<18} {rs:>9} "
              f"{r.get('projected_net_bps') or 0:7.0f} {cw:>8} {fe:>15} {pk:>5} {og:>5}")
    n_og = sum(bool(r.get("orig_byte_exact")) for r in results)
    print(f"\n  orig-exact: {n_og}/{len(results)}   "
          f"anchor reproved 2572: {'YES' if anchor_ok else 'NO -- tape pass VOID'}")
    ex = [r for r in results if r.get("orig_byte_exact") and r["name"] != "x10_x0_anchor2572"]
    if ex and anchor_ok:
        best = max(ex, key=lambda r: r.get("projected_net_bps") or 0)
        print(f"  best new orig-exact rung: {best['name']} -> "
              f"net {best.get('projected_net_bps'):.0f} bps ({best.get('front_end_used')})")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape WAV or x10_master10_draft.wav")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, args.out_tag)
