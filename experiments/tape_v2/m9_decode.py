"""m9_decode.py -- recover the master9 ladder from a captured (or clean) WAV.

Manifest-driven, m8_decode pattern: ONE global sync (chirp pair + front sounder),
then each rung decoded with its proper path:

  * DQPSK / drop-null sections -> the COMMON master9 receiver chain (MASTER9_PLAN
    s2.2-2.4): decode through BOTH the proven h4 EMA-integer-drift front-end AND
    the x9_resampling_pll continuous-tau-hat resampling PLL, plus a timing-front-
    end + RS-mode sweep, and KEEP the CRC-verified byte-exact winner. The CRC32-
    per-codeword manifest guard rejects any RS miscorrection (no truth leak).
  * M9a (freqdiff) sections -> x9_freqdiff.FreqDiffDQPSKScheme.demod (frequency-
    differential, timing-immune). SKIPPED gracefully if the module is absent.

Every section's RS output is the H9-PACKED blob; we unpack_payload it and verify
against the manifest sha256 of the original + packed bytes. Per-rung result records
which front-end won (front_end_used) and the per-carrier SER.

Output: results/m9_results_<capture>.json (m8 schema + per-rung front_end_used).

Usage:
    python3 experiments/tape_v2/m9_decode.py experiments/tape_v2/master9_draft.wav
    python3 experiments/tape_v2/m9_decode.py experiments/tape_v2/captures/tape9_run1.wav
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, correlate

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2  # noqa: E402
import hyp_common as hc  # noqa: E402
import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
from h4_dqpsk import DQPSKScheme, FS as DQ_FS, PAD_LO_S, PAD_HI_S  # noqa: E402
from h9_payload_codec import unpack_payload  # noqa: E402
from m9_master import DropNullDQPSK, make_scheme  # noqa: E402

# Optional front-end modules (coded to the PLAN interface; reconciled by the Gate).
try:
    from x9_resampling_pll import ResamplingPLLDemod
    _HAVE_PLL = True
except Exception:  # pragma: no cover
    ResamplingPLLDemod = None
    _HAVE_PLL = False

try:
    from x9_freqdiff import FreqDiffDQPSKScheme
    _HAVE_FREQDIFF = True
except Exception:  # pragma: no cover
    FreqDiffDQPSKScheme = None
    _HAVE_FREQDIFF = False

SR = codec.FS
MANIFEST_PATH = _HERE / "master9_manifest.json"
RESULTS_DIR = _HERE / "results"

# ---- per-rung receiver sweep (MASTER9_PLAN s2.4) --------------------------
# timing front-ends: resampling PLL (default) + pilot-EMA at several alphas.
# RS modes: errors-only + errors-and-erasures at a few erase-fractions, all
# CRC32-guarded so erasures can never miscorrect. Kept deliberately small so a
# clean self-check is fast; the Gate phase widens it.
PLL_BW_HZ = 30.0
EMA_ALPHAS = (0.5, 0.4, 0.6)
ERASE_FRACS = (0.0, 0.25, 0.5)

# ---- per-frame timing DRIFT TRACKER (issue #26) ---------------------------
# Global sync fits ONE constant clock ratio (correct at both chirps = endpoint
# average), so on a long tape whose true speed WANDERS (slow wow, below flutter)
# the residual per-frame timing error is a smooth BOW: ~0 at the chirps, up to
# tens of thousands of samples mid-tape. Once the bow exceeds the per-frame
# preamble search slack (PAD_LO_S = 0.30 s = 14400 samples), find_preamble
# latches a spurious peak and the frame demods at chance. RS interleaving is
# cross-frame, so ~50% dead frames -> every codeword fails -> total wipeout.
#
# Fix: a forward-predicted, confidence-gated, dead-banded tracker carried across
# a section's frames. We PREDICT each frame's start with a running drift_pred,
# measure where the preamble was ACTUALLY found, and (only when the lock is
# confident AND the residual is beyond a deadband the demod's own pilot loop
# can't absorb) nudge drift_pred toward the measured residual, capped per frame.
#
# PARITY: the deadband makes the tracker a strict NO-OP on a well-tracked / clean
# capture -- there the preamble lands at the predicted position (residual ~0),
# so drift_pred stays exactly 0 and `st` is byte-identical to the frozen path.
DRIFT_DEADBAND = 1500   # samples; |residual| <= this -> no update (demod handles it)
DRIFT_STEP = 4000       # samples; per-frame cap on the drift_pred correction
DRIFT_CONF_MIN = 20.0   # min preamble matched-filter prominence (peak/median) to trust
#   (empirical: pure-noise prominence tops out ~9; a real, even heavily buried,
#    sync chirp lands ~75+ -- so 20 cleanly separates a true lock from a spurious peak)


def _preamble_n(preamble_seconds: float) -> int:
    """Length in samples of the sync chirp (== find_preamble's n_pre)."""
    return int(preamble_seconds * hc.SAMPLE_RATE)


def _preamble_prominence(win: np.ndarray, preamble_seconds: float) -> float:
    """Matched-filter prominence (peak / median of |corr|) of the sync chirp in
    `win`. High on a confident lock; low on noise / a spurious peak. A cheap,
    truth-free confidence signal for the drift tracker -- computed only when the
    residual already exceeds the deadband, so it never runs on the no-drift path."""
    pre = hc.make_preamble(preamble_seconds).astype(np.float64)
    y = np.asarray(win, np.float64)
    if len(y) < len(pre):
        return 0.0
    corr = np.abs(correlate(y, pre, mode="valid"))
    if corr.size == 0:
        return 0.0
    med = float(np.median(corr))
    return (float(np.max(corr)) / med) if med > 1e-12 else 0.0


def _drift_update(drift_pred: int, residual: float, win: np.ndarray,
                  preamble_seconds: float) -> int:
    """Forward-predicted, confidence-gated, dead-banded drift update.

    NO-OP when |residual| <= DRIFT_DEADBAND (the clean / well-tracked path), so
    the tracker is provably inert on a capture with no wow (parity gate). Beyond
    the deadband, a CONFIDENT preamble lock nudges drift_pred toward the residual,
    capped at +-DRIFT_STEP so a single mis-locked frame can't corrupt the predictor."""
    if abs(residual) <= DRIFT_DEADBAND:
        return drift_pred
    if _preamble_prominence(win, preamble_seconds) < DRIFT_CONF_MIN:
        return drift_pred           # un-trusted lock: never move the predictor
    step = int(np.clip(residual, -DRIFT_STEP, DRIFT_STEP))
    return drift_pred + step


# ===========================================================================
# Scheme reconstruction from a manifest entry (mirror m9_master.make_scheme).
# ===========================================================================
def _scheme_from_entry(sec: dict):
    kind = sec["kind"]
    if kind == "freqdiff":
        if not _HAVE_FREQDIFF:
            return None
        p = sec["freqdiff_params"]
        return FreqDiffDQPSKScheme(p["P"], p["N"], p["spacing"], pilot_hz=p["pilot_hz"])
    p = sec["dqpsk_params"]
    if kind == "dqpsk_dropnull":
        return DropNullDQPSK(p["P"], p["N"], p["spacing"], p["drop_freqs_hz"],
                             pilot_hz=p["pilot_hz"])
    # plain dqpsk (incl. M8 dense-375 via min_spacing_hz)
    return DQPSKScheme(p["P"], p["N"], p["spacing"],
                       min_spacing_hz=p.get("min_spacing_hz", 562.0))


def _nominal_frame_bits(meta: dict) -> list[int]:
    fb = meta["frame_bits"]
    n = meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


# ===========================================================================
# Front-end demod of all frames in a section -> (rx_frames, per-carrier SER vs
# the reference packed bytes, front_end label).
# A "front_end" is a callable (win, nd) -> (bits, diag).
# ===========================================================================
def _demod_section_frames(audio_nom, sec, align, sch, frontend):
    meta = sec["meta"]
    nom_bits = _nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    full_frame = np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8)),
                            np.float32)
    flen_full = len(full_frame)
    n_pre = _preamble_n(sch.preamble_seconds)
    rx_frames: list[np.ndarray] = []
    diags: list[dict] = []
    drift_pred = 0   # per-frame timing drift tracker (issue #26); 0 on a clean tape
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align + drift_pred
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(audio_nom), st + flen_full + pad_hi)
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        bits, diag = frontend(win, nd)
        rx_frames.append(np.asarray(bits, np.uint8))
        diags.append(diag)
        ds = diag.get("preamble_at")
        if ds is not None:
            residual = (w_lo + int(ds) - n_pre) - st
            drift_pred = _drift_update(drift_pred, residual, win, sch.preamble_seconds)
    return rx_frames, diags


# ===========================================================================
# RS merge with CRC32-per-codeword miscorrection guard + optional erasures.
# Returns (recovered_packed, cw_failed, miscorrected, n_erase).
# ===========================================================================
def _rs_merge_guarded(rx_frames, meta, crc_table, *, erase_frac=0.0, rel_cw=None):
    """Errors-only (erase_frac==0) or errors-and-erasures RS merge with the
    CRC32 manifest guard. When erase_frac>0, rel_cw (per-codeword per-symbol
    reliability, lower=worse) selects the erased positions. CRC-guarded so an
    erasure can never silently miscorrect."""
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    from reedsolo import RSCodec, ReedSolomonError

    # reassemble the de-interleaved codeword matrix exactly as decode_payload does
    fb_bits = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]
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
    rx_mat = rx_bytes.reshape(rs_n, n_cw).T

    rsc = RSCodec(rs_n - rs_k)
    twot = rs_n - rs_k
    n_erase_max = int(round(erase_frac * twot)) if erase_frac > 0 else 0
    recovered = bytearray()
    cw_failed = miscorrected = n_erase = 0
    for i in range(n_cw):
        row = bytearray(rx_mat[i].tobytes())
        epos = []
        if n_erase_max and rel_cw is not None and i < len(rel_cw):
            epos = sorted(int(j) for j in np.argsort(rel_cw[i])[:n_erase_max])
            n_erase += len(epos)
        try:
            dec = (rsc.decode(row, erase_pos=epos)[0] if epos else rsc.decode(row)[0])
            msg = bytes(dec)
            if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
                miscorrected += 1
                cw_failed += 1
                recovered += bytes(rs_k)          # reject the miscorrection
            else:
                recovered += msg
        except (ReedSolomonError, Exception):
            cw_failed += 1
            recovered += bytes(rs_k)
    out = bytes(recovered)[:meta["payload_len"]]
    return out, cw_failed, miscorrected, n_erase


# ===========================================================================
# DQPSK / drop-null section decode -- the full common chain + sweep.
# ===========================================================================
def _decode_dqpsk_section(audio_nom, sec, align):
    sch = _scheme_from_entry(sec)
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()

    # --- build the candidate timing front-ends (MASTER9_PLAN s2.4) ---
    frontends: list[tuple[str, callable]] = []
    if _HAVE_PLL:
        pll = ResamplingPLLDemod(sch, pll_bw_hz=PLL_BW_HZ, front_end="pll")
        frontends.append(("resampling_pll", lambda w, nd, d=pll: d.demod(w, nd)))
    # proven h4 EMA-integer-drift loop (the record's front-end) at several alphas
    for a in EMA_ALPHAS:
        if _HAVE_PLL:
            ema = ResamplingPLLDemod(sch, front_end="ema", ema_alpha=a)
            frontends.append((f"ema{a}", lambda w, nd, d=ema: d.demod(w, nd)))
        elif a == 0.5:
            frontends.append(("ema0.5", lambda w, nd, s=sch: s.demod(w, nd)))

    best = None  # dict of the winning attempt
    attempts: list[dict] = []
    for fe_name, fe in frontends:
        rx_frames, diags = _demod_section_frames(audio_nom, sec, align, sch, fe)
        # per-codeword reliability for erasure mode: use the per-symbol pilot
        # residual |dtau| aggregated per frame (lower=better). Build a coarse
        # per-codeword reliability proxy from frame-level dtau RMS.
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
                break  # this front-end+erase combo nailed it; stop early
        if best is not None and best.get("byte_exact"):
            break

    # per-carrier SER from the winning front-end's frames (scoring only)
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
        "sweep_attempts": attempts,
    }
    return res, recovered_packed


def _better(att, best):
    """Prefer byte_exact, then fewer cw_failed, then fewer byte_errors."""
    if att["byte_exact"] != best["byte_exact"]:
        return att["byte_exact"]
    if att["cw_failed"] != best["cw_failed"]:
        return att["cw_failed"] < best["cw_failed"]
    return att["byte_errors"] < best["byte_errors"]


def _frame_reliability_to_cw(diags, meta):
    """Coarse per-codeword reliability proxy: a frame's mean |dtau| (higher =
    worse). The interleave spreads frame bytes across codewords, so we project
    each codeword's reliability as the mean frame-reliability weighted by how
    many of its bytes came from each frame. Cheap approximation -- only used to
    pick erasure positions, and the CRC guard makes a wrong pick harmless."""
    n_frames = meta["n_frames"]
    rs_n, n_cw = meta["rs_n"], meta["n_codewords"]
    frame_bad = np.zeros(n_frames)
    for fi in range(min(n_frames, len(diags))):
        d = diags[fi].get("dtau")
        frame_bad[fi] = float(np.sqrt(np.mean(np.square(d)))) if d is not None and len(d) else 0.0
    # per-codeword: rs_n symbols, column-interleaved across frames. Map each
    # codeword symbol position to the frame it rode in (same math as encode).
    fb_bits = meta["frame_bits"]
    # symbol (codeword,byte) -> stream byte index -> frame index
    rel = np.zeros((n_cw, rs_n))
    for j in range(rs_n):
        for i in range(n_cw):
            stream_byte = j * n_cw + i
            stream_bit = stream_byte * 8
            fi = min(stream_bit // fb_bits, n_frames - 1)
            rel[i, j] = -frame_bad[fi]   # lower (more negative) = worse -> erase first
    return rel


def _per_carrier_ser(rx_frames, sec, sch, expected_packed):
    """Per-carrier symbol error rate (scoring only, against the reference packed
    bytes re-encoded to TX frames). For freqdiff this is per-pair."""
    meta = sec["meta"]
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    try:
        tx_frames, _ = codec.encode_payload(expected_packed, rung)
    except Exception:
        return None
    is_fd = sec["kind"] == "freqdiff"
    ncar = sch.n_pairs if is_fd else sch.P
    car_err = np.zeros(ncar, int)
    car_tot = np.zeros(ncar, int)
    for fi in range(min(len(tx_frames), len(rx_frames))):
        tb = np.asarray(tx_frames[fi], np.uint8)
        rb = np.asarray(rx_frames[fi], np.uint8)
        m = min(len(tb), len(rb))
        if m == 0:
            continue
        tq = sch.bits_to_quadrants(tb[:m])
        rq = sch.bits_to_quadrants(rb[:m])
        k = min(len(tq), len(rq))
        car_err += (tq[:k] != rq[:k]).sum(axis=0)
        car_tot += k
    return [round(float(e) / max(1, t), 5) for e, t in zip(car_err, car_tot)]


# ===========================================================================
# M9a freqdiff section decode (frequency-differential, CRC-guarded RS merge).
# ===========================================================================
def _decode_freqdiff_section(audio_nom, sec, align, sounder):
    sch = _scheme_from_entry(sec)
    if sch is None:
        return {"name": sec["name"], "kind": "freqdiff", "skipped_module_absent": True,
                "byte_exact": False, "role": sec.get("role", ""),
                "rs_n": sec["meta"]["rs_n"], "rs_k": sec["meta"]["rs_k"],
                "n_codewords": sec["meta"]["n_codewords"],
                "rs_codewords_failed": sec["meta"]["n_codewords"],
                "projected_net_bps": sec.get("projected_net_bps"),
                "status": sec.get("status", "ACTIVE")}, bytes(sec["meta"]["payload_len"])
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    # optional measured per-carrier H(f) phase tilt from the front sounder
    eq_tilt = _sounder_phase_tilt(sounder, sch.freqs)

    def fe(win, nd, _sch=sch, _tilt=eq_tilt):
        return _sch.demod(win, nd, refine=True, eq_tilt=_tilt)

    rx_frames, diags = _demod_section_frames(audio_nom, sec, align, sch, fe)
    rel_cw = _frame_reliability_to_cw(diags, meta)
    best = None
    attempts = []
    for ef in ERASE_FRACS:
        out, cwf, misc, ne = _rs_merge_guarded(
            rx_frames, meta, crc_table, erase_frac=ef, rel_cw=rel_cw)
        exact = out == expected_packed
        byte_err = sum(a != b for a, b in zip(out, expected_packed)) + abs(
            len(out) - len(expected_packed))
        att = {"erase_frac": ef, "byte_exact": exact, "cw_failed": cwf,
               "miscorrected": misc, "byte_errors": byte_err, "_packed": out}
        attempts.append({k: v for k, v in att.items() if not k.startswith("_")})
        if best is None or _better(att, best):
            best = att
        if exact:
            break

    per_pair_ser = _per_carrier_ser(rx_frames, sec, sch, expected_packed)
    res = {
        "name": sec["name"], "kind": "freqdiff", "role": sec.get("role", ""),
        "scheme": sec["phy"], "phy": sec["phy"], "status": sec.get("status", "ACTIVE"),
        "llm_offset": sec.get("llm_offset", 0), "payload_bytes": len(expected_packed),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
        "gross_bps": sec.get("gross_bps"), "projected_net_bps": sec.get("projected_net_bps"),
        "x_record": sec.get("x_record"),
        "rs_codewords_failed": best["cw_failed"], "miscorrected_cw": best["miscorrected"],
        "byte_errors": best["byte_errors"], "byte_exact": bool(best["byte_exact"]),
        "front_end_used": "freqdiff", "erase_frac_used": best["erase_frac"],
        "per_pair_ser": per_pair_ser, "null_pair_idx": sec.get("null_pair_idx"),
        "sweep_attempts": attempts,
    }
    return res, best["_packed"]


def _sounder_phase_tilt(sounder, freqs):
    """Best-effort measured per-carrier channel PHASE at `freqs` from the front
    sounder; None if unavailable (freqdiff then self-calibrates the tilt)."""
    if not isinstance(sounder, dict):
        return None
    for key in ("H_phase", "phase_rad", "H_phase_rad"):
        if key in sounder and "sounder_freqs" in sounder:
            try:
                fr = np.asarray(sounder["sounder_freqs"], float)
                ph = np.asarray(sounder[key], float)
                return np.interp(np.asarray(freqs, float), fr, ph)
            except Exception:
                return None
    return None


# ===========================================================================
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
        if sec.get("skipped"):
            results.append({"name": sec["name"], "kind": sec["kind"],
                            "skipped": True, "byte_exact": None,
                            "status": sec.get("status")})
            continue
        if sec["kind"] == "freqdiff":
            r, recovered_packed = _decode_freqdiff_section(audio_nom, sec, align, sounder)
        else:
            r, recovered_packed = _decode_dqpsk_section(audio_nom, sec, align)

        # ---- unpack + integrity ----
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
        r["effective_bps"] = sec.get("effective_bps")
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        r["unpack_ok"] = unpack_ok
        r["orig_byte_exact"] = orig_exact
        r["crc_check"] = crc_ok
        results.append(r)

    if verbose:
        _print_table(recording_path, sync, sounder, align, results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    out = {
        "recording": str(recording_path),
        "tape": "master9",
        "have_pll": _HAVE_PLL, "have_freqdiff": _HAVE_FREQDIFF,
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {
            k: v for k, v in (sounder or {}).items()
            if k not in ("H_db", "snr_db_per_tone", "sounder_freqs", "H_phase",
                         "phase_rad", "H_phase_rad")
        },
        "payloads": results,
        "n_byte_exact_packed": sum(bool(r.get("byte_exact")) for r in results),
        "n_orig_exact": sum(bool(r.get("orig_byte_exact")) for r in results),
        "n_payloads": len(results),
    }
    json_path = RESULTS_DIR / f"m9_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m9_decode] wrote {json_path}")
    return out


def _print_table(recording_path, sync, sounder, align, results):
    print(f"[m9_decode] {recording_path}")
    print(f"  recovered clock: {sync['speed']:.4f}x "
          f"(offset {sync['speed_offset'] * 100:+.2f}%), align {align:+d}")
    if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
        print(f"  sounder: flutter {sounder['flutter_wrms_pct']:.2f}%, "
              f"SNR med {sounder['snr_db_median']:.1f} dB, "
              f"nf {sounder['noise_floor_dbfs']:.1f} dBFS")
    print(f"\n  {'rung':<24} {'phy':<22} {'RS':>9} {'net':>7} "
          f"{'cwFail':>8} {'front-end':>15} {'PACK':>5} {'ORIG':>5}")
    for r in results:
        if r.get("skipped"):
            print(f"  {r['name']:<24} {'(skipped)':<22} {'':>9} {'':>7} "
                  f"{'':>8} {'':>15} {'-':>5} {'-':>5}")
            continue
        rs = f"({r['rs_n']},{r['rs_k']})"
        cw = f"{r['rs_codewords_failed']}/{r['n_codewords']}"
        pk = "YES" if r.get("byte_exact") else "no"
        og = "YES" if r.get("orig_byte_exact") else "no"
        fe = r.get("front_end_used") or "-"
        if r.get("skipped_module_absent"):
            pk = og = "SKIP"; fe = "module-absent"
        print(f"  {r['name']:<24} {r['phy']:<22} {rs:>9} "
              f"{r.get('projected_net_bps') or 0:7.0f} {cw:>8} {fe:>15} {pk:>5} {og:>5}")
    n_pk = sum(bool(r.get("byte_exact")) for r in results)
    n_og = sum(bool(r.get("orig_byte_exact")) for r in results)
    print(f"\n  byte-exact (packed): {n_pk}/{len(results)}   "
          f"orig-exact (unpacked): {n_og}/{len(results)}")
    ex = [r for r in results if r.get("orig_byte_exact")]
    if ex:
        best = max(ex, key=lambda r: r.get("projected_net_bps") or 0)
        print(f"  best orig-exact rung: {best['name']} -> "
              f"net {best.get('projected_net_bps'):.0f} bps "
              f"(x{best.get('x_record')}, {best.get('front_end_used')})")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape-playback WAV or master9_draft.wav")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, args.out_tag)
