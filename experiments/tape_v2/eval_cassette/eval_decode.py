"""eval_decode.py -- decode an EVALUATION-CASSETTE capture and print a REPORT CARD.

HYBRID predict + confirm:
  1. Global chirp sync + clock recovery (analyze_master2.global_sync_and_resample,
     reused VERBATIM -- the proven up/down-chirp matched filter + 0.80..1.10 speed
     scan + whole-recording resample to nominal).
  2. CHARACTERIZE the link: reuse analyze_master2.analyze_sounder (H(f), per-tone
     SNR, flutter, noise floor, recovered clock), then ADD usable-BW / HF-rolloff
     (from H(f)), two-tone IMD (3rd-order products below carriers), and diffuse
     contamination (1-bin-spaced off-tone leakage) -> a measured-channel dict.
  3. PREDICT the achievable tier from a calibrated tier-requirements table
     (min SNR / max flutter / min usable BW / max diffuse / max IMD per tier);
     PREDICT = highest tier whose every requirement the measured channel meets.
  4. CONFIRM: decode every tier's seeded payload byte-exact; the highest
     byte-exact tier = the confirmed tier.
  5. CROSS-CHECK predict vs confirm and explain any gap.
  6. ADVICE: identify the binding bottleneck (the metric that blocks the next
     tier) and emit ranked actions with expected tier gain.

CLI:
    python3 eval_decode.py <wav> [--selfcheck] [--out-tag TAG]

  --selfcheck : the HARD GATE.  Decode the master directly (no channel); EVERY
                tier MUST be byte_exact AND the characterization must read sane
                clean-channel values, or the master+decoder are inconsistent.

Results -> results/<tag>_eval.json   (and the report card to stdout).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import warnings
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
BPS_PUSH = ROOT / "experiments" / "tape_v2" / "bps_push_2026_06_14"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "tape_v2", BPS_PUSH / "harness",
           BPS_PUSH / "candidates", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from reedsolo import RSCodec, ReedSolomonError                # noqa: E402
import analyze_master2 as am2                                  # noqa: E402

# Reuse the master's own tier-scheme builder + framing (single source of truth).
import importlib.util
_spec = importlib.util.spec_from_file_location("eval_master", _HERE / "eval_master.py")
_em = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_em)

build_tier_scheme = _em.build_tier_scheme
encode_tier = _em.encode_tier

SR = 48_000
RS_N = 255
MANIFEST_PATH = _HERE / "eval_manifest.json"
RESULTS_DIR = _HERE / "results"


# ===========================================================================
# TIER REQUIREMENTS TABLE (the heart of PREDICT + ADVICE).
# Min channel each tier needs.  Derived from the project's empirical findings
# (the 39 dB / 0.44% clean acoustic loop; the 5791-pass / 6179-fail real-tape
# margin gate; the level-8.5 IMD-bloom failure; the diffuse acoustic cap) and
# CALIBRATED against the sim presets (see results/eval_sim_validation.json) so
# PREDICT tracks CONFIRM within ~+-1 tier as the channel worsens.
#
# All thresholds are on the MEASURED metrics (the same scale eval_decode reads),
# NOT on the channel's true parameters -- the sounder's per-tone SNR runs higher
# than the channel SNR and is flutter-coupled, so the table is calibrated to what
# the decoder actually measures (see eval_sim_validate.py for the calibration
# sweep that fixed these break-points).
#
# Metrics (all measured by characterize()):
#   min_snr_db        : per-tone SNR median floor (measured scale).
#   max_flutter       : flutter WRMS % ceiling -- the dominant high-tier gate
#                       (deck-mechanical / capture-clock).
#   min_bw_hz         : usable bandwidth within 30 dB of the passband peak (the
#                       30 dB window matches the TX pre-emphasis 0.05-clip
#                       headroom, so the carriers can be equalized back up).
#   max_hf_rolloff_db : H(f) at 9 kHz relative to the passband peak; tiers that
#                       place carriers out to 9 kHz (T3+) need the rolloff no
#                       deeper than this (a tier passes iff measured >= this).
#   max_diffuse       : off-tone leakage fraction ceiling (acoustic-reverb cap).
#   max_imd_db        : 3rd-order IMD below carriers; LESS NEGATIVE = worse
#                       (saturation). A tier passes iff measured_imd_db <= this.
# PREDICT = highest tier meeting EVERY requirement.
# ===========================================================================
TIER_REQUIREMENTS = [
    {"tier": "T0", "min_snr_db": 14.0, "max_flutter": 1.50, "min_bw_hz": 1800.0,
     "max_hf_rolloff_db": -90.0, "max_diffuse": 0.55, "max_imd_db": -8.0,
     "note": "robust floor: survives a bad acoustic loop / worn deck"},
    {"tier": "T1", "min_snr_db": 14.0, "max_flutter": 1.40, "min_bw_hz": 2200.0,
     "max_hf_rolloff_db": -90.0, "max_diffuse": 0.52, "max_imd_db": -9.0,
     "note": "BFSK-class baseline rate"},
    {"tier": "T2", "min_snr_db": 15.0, "max_flutter": 1.35, "min_bw_hz": 3500.0,
     "max_hf_rolloff_db": -90.0, "max_diffuse": 0.48, "max_imd_db": -11.0,
     "note": "MFSK-class; needs a few clean low-mid carriers"},
    {"tier": "T3", "min_snr_db": 18.0, "max_flutter": 1.20, "min_bw_hz": 5500.0,
     "max_hf_rolloff_db": -40.0, "max_diffuse": 0.42, "max_imd_db": -14.0,
     "note": "the 2572 DQPSK record; carriers to 9 kHz (pre-emphasized)"},
    {"tier": "T4", "min_snr_db": 18.0, "max_flutter": 1.30, "min_bw_hz": 6000.0,
     "max_hf_rolloff_db": -38.0, "max_diffuse": 0.38, "max_imd_db": -18.0,
     "note": "dense2x drop grid; tighter flutter + cleaner mids"},
    {"tier": "T5", "min_snr_db": 21.0, "max_flutter": 1.10, "min_bw_hz": 8000.0,
     "max_hf_rolloff_db": -32.0, "max_diffuse": 0.34, "max_imd_db": -22.0,
     "note": "the PROVEN DOOM tape; clean deck + clean capture"},
    {"tier": "T6", "min_snr_db": 23.0, "max_flutter": 1.00, "min_bw_hz": 9000.0,
     "max_hf_rolloff_db": -30.0, "max_diffuse": 0.30, "max_imd_db": -26.0,
     "note": "the 5791 record; full grid, marginal carriers at 15deg"},
    {"tier": "T7", "min_snr_db": 44.0, "max_flutter": 0.40, "min_bw_hz": 9500.0,
     "max_hf_rolloff_db": -28.0, "max_diffuse": 0.28, "max_imd_db": -29.0,
     "note": "8-DPSK higher-order; needs the cleanest mids + tight clock"},
]
TIER_ORDER = [r["tier"] for r in TIER_REQUIREMENTS]
REQ_BY_TIER = {r["tier"]: r for r in TIER_REQUIREMENTS}


# ===========================================================================
# Added-probe measurements (IMD + diffuse) on the nominal-rate recording
# ===========================================================================
def _grab_section(audio_nom, start, length, align, trim=0.2):
    st = int(start) + int(align)
    ti = int(trim * SR)
    a = audio_nom[max(0, st + ti): st + length - ti]
    return np.asarray(a, dtype=np.float64)


def _tone_amp(seg, f_hz, half_bw=20.0):
    """Peak magnitude in a +-half_bw band around f_hz (Hann-windowed rfft)."""
    n = len(seg)
    if n < 256:
        return 0.0
    win = np.hanning(n)
    sp = np.abs(np.fft.rfft(seg * win))
    fax = np.fft.rfftfreq(n, 1.0 / SR)
    bl = np.searchsorted(fax, f_hz - half_bw)
    bh = max(np.searchsorted(fax, f_hz + half_bw), bl + 1)
    bh = min(bh, len(sp))
    return float(np.max(sp[bl:bh])) if bh > bl else 0.0


def measure_imd(audio_nom, manifest, align) -> dict:
    """3rd-order IMD: the (2f1-f2) and (2f2-f1) products below the carriers."""
    sec = manifest.get("probe_sections", {}).get("imd")
    if sec is None:
        return {"imd_db": None}
    info = sec["info"]
    seg = _grab_section(audio_nom, sec["start"], sec["length"], align, trim=0.3)
    if seg.size < SR // 2:
        return {"imd_db": None}
    f1, f2 = info["f1_hz"], info["f2_hz"]
    a1 = _tone_amp(seg, f1)
    a2 = _tone_amp(seg, f2)
    carrier = max(a1, a2, 1e-12)
    imd_lo = _tone_amp(seg, info["imd3_lo_hz"])
    imd_hi = _tone_amp(seg, info["imd3_hi_hz"])
    imd = max(imd_lo, imd_hi, 1e-12)
    imd_db = 20.0 * np.log10(imd / carrier)
    return {"imd_db": float(imd_db),
            "imd_lo_db": float(20.0 * np.log10(max(imd_lo, 1e-12) / carrier)),
            "imd_hi_db": float(20.0 * np.log10(max(imd_hi, 1e-12) / carrier))}


def measure_diffuse(audio_nom, manifest, align) -> dict:
    """Off-tone leakage fraction on the 1-bin-spaced multitone: energy landing
    OFF the lit bins / total energy across the probe band (== spectral
    contamination).  Higher = more reverb/room diffuse floor."""
    sec = manifest.get("probe_sections", {}).get("diffuse")
    if sec is None:
        return {"diffuse_frac": None}
    info = sec["info"]
    seg = _grab_section(audio_nom, sec["start"], sec["length"], align, trim=0.3)
    Nd = int(info["N"])
    if seg.size < Nd * 4:
        return {"diffuse_frac": None}
    tone_bins = np.asarray(info["tone_bins"], int)
    df = SR / Nd
    # Analysis band: from one bin below the lowest lit tone to one above the
    # highest -> the contiguous probe band where leakage should be measured.
    band_lo = int(tone_bins.min()) - 2
    band_hi = int(tone_bins.max()) + 3
    # Average power spectrum over consecutive N-length blocks (genie-free).
    nblk = seg.size // Nd
    if nblk < 1:
        return {"diffuse_frac": None}
    acc = np.zeros(Nd // 2 + 1)
    win = np.hanning(Nd)
    for b in range(nblk):
        blk = seg[b * Nd:(b + 1) * Nd]
        acc += np.abs(np.fft.rfft(blk * win)) ** 2
    psd = acc / nblk
    band = psd[band_lo:band_hi]
    lit_local = tone_bins - band_lo
    total = float(band.sum()) + 1e-18
    lit = float(band[lit_local].sum())
    diffuse = 1.0 - lit / total
    return {"diffuse_frac": float(diffuse), "diffuse_band_hz":
            [round(band_lo * df, 1), round(band_hi * df, 1)]}


def measure_bandwidth(sounder: dict) -> dict:
    """Usable bandwidth + HF rolloff from the sounder H(f).  Usable BW = highest
    frequency whose H(f) is within 30 dB of the passband peak.  The 30 dB window
    (not 20) matches the modems' TX pre-emphasis 0.05-clip headroom: a carrier up
    to ~26 dB below peak is equalized back up, so a 30 dB-down frequency is still
    'usable' in the sense the modems need.  hf_rolloff_db_at_9k is the separate
    gate the high tiers (carriers to 9 kHz) read."""
    freqs = sounder.get("sounder_freqs")
    H_db = sounder.get("H_db")
    if not freqs or not H_db:
        return {"usable_bw_hz": None, "hf_rolloff_db_at_9k": None}
    freqs = np.asarray(freqs, float)
    H_db = np.asarray(H_db, float)
    # passband reference: peak over the 500-3000 Hz strong band
    band = (freqs >= 500) & (freqs <= 3000)
    ref = float(np.max(H_db[band])) if band.any() else float(np.max(H_db))
    usable = freqs[H_db >= ref - 30.0]
    usable_bw = float(usable.max()) if usable.size else 0.0
    # HF rolloff: H(f) at ~9 kHz relative to the passband peak
    hf = float(np.interp(9000.0, freqs, H_db)) - ref
    return {"usable_bw_hz": usable_bw, "hf_rolloff_db_at_9k": hf,
            "passband_ref_db": ref}


def characterize(audio_nom, manifest, sync) -> dict:
    """Full measured-channel dict: reuse analyze_master2.analyze_sounder + add
    usable-BW/HF-rolloff, IMD, diffuse contamination, dropout rate."""
    sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    align = sync["chirp0_nominal"] - sync["expected_chirp0"]
    bw = measure_bandwidth(sounder)
    imd = measure_imd(audio_nom, manifest, align)
    diff = measure_diffuse(audio_nom, manifest, align)

    # dropout rate: fraction of the recording that is near-silent gaps where it
    # should not be (crude: not used as a gate here, reported for advice).
    ch = {
        "snr_db_median": sounder.get("snr_db_median"),
        "snr_db_p10": sounder.get("snr_db_p10"),
        "flutter_pct": sounder.get("flutter_wrms_pct"),
        "noise_floor_dbfs": sounder.get("noise_floor_dbfs"),
        "recovered_clock": sync["speed"],
        "recovered_clock_from_tone": sounder.get("recovered_clock_from_tone"),
        "usable_bw_hz": bw.get("usable_bw_hz"),
        "hf_rolloff_db_at_9k": bw.get("hf_rolloff_db_at_9k"),
        "imd_db": imd.get("imd_db"),
        "diffuse_frac": diff.get("diffuse_frac"),
        "frac_below_8db": sounder.get("frac_below_8db"),
    }
    return ch, sounder


# ===========================================================================
# PREDICT: highest tier meeting every requirement
# ===========================================================================
def _tier_meets(ch: dict, req: dict) -> tuple[bool, list[str]]:
    """Return (meets, list of failing-metric strings) for one tier's requirements.
    Missing measurements are treated as PASS for that metric (don't block on a
    metric we couldn't read), except SNR/flutter/BW which are the load-bearing
    gates -- a missing one there is treated as a soft pass but flagged."""
    fails = []
    snr = ch.get("snr_db_median")
    if snr is not None and snr < req["min_snr_db"]:
        fails.append(f"SNR {snr:.1f} dB < {req['min_snr_db']:.0f}")
    flut = ch.get("flutter_pct")
    if flut is not None and flut > req["max_flutter"]:
        fails.append(f"flutter {flut:.2f}% > {req['max_flutter']:.2f}%")
    bw = ch.get("usable_bw_hz")
    if bw is not None and bw < req["min_bw_hz"]:
        fails.append(f"usable BW {bw:.0f} Hz < {req['min_bw_hz']:.0f}")
    roll = ch.get("hf_rolloff_db_at_9k")
    if roll is not None and roll < req["max_hf_rolloff_db"]:
        fails.append(f"HF rolloff {roll:.0f} dB < {req['max_hf_rolloff_db']:.0f} dB at 9k")
    diff = ch.get("diffuse_frac")
    if diff is not None and diff > req["max_diffuse"]:
        fails.append(f"diffuse {diff:.2f} > {req['max_diffuse']:.2f}")
    imd = ch.get("imd_db")
    if imd is not None and imd > req["max_imd_db"]:
        fails.append(f"IMD {imd:.0f} dB > {req['max_imd_db']:.0f} dB")
    return (len(fails) == 0, fails)


def predict_tier(ch: dict) -> dict:
    """PREDICT = highest tier whose every requirement the measured channel meets.
    Returns the predicted tier id (or None below T0), plus the per-tier pass map
    and, for the first failing tier, the binding metrics."""
    pass_map = {}
    predicted = None
    first_fail = None
    for req in TIER_REQUIREMENTS:
        meets, fails = _tier_meets(ch, req)
        pass_map[req["tier"]] = {"meets": meets, "fails": fails}
        if meets:
            predicted = req["tier"]
        elif first_fail is None:
            first_fail = {"tier": req["tier"], "fails": fails}
    return {"predicted": predicted, "pass_map": pass_map, "first_fail": first_fail}


# ===========================================================================
# CONFIRM: decode every tier's seeded payload byte-exact
# ===========================================================================
def _hamming_ber(tx: np.ndarray, rx: np.ndarray) -> float:
    n = len(tx)
    if n == 0:
        return 0.0
    m = min(n, len(rx))
    errs = int(np.count_nonzero(tx[:m] != rx[:m])) if m else 0
    errs += (n - m)
    return errs / n


def _regenerate_payload(seed: int, message_bytes: int) -> bytes:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=message_bytes, dtype=np.uint8).tobytes()


def decode_tier_bits(rx_coded_bits, rs_k, n_cw, crc32_codewords):
    """Inverse of encode_tier: truncate, de-interleave, RS-decode each codeword,
    accept iff the recovered message CRC32 matches the manifest's (no-truth).
    Returns (message_bytes, codewords_passed)."""
    rsc = RSCodec(RS_N - rs_k)
    need_bits = n_cw * RS_N * 8
    rx = np.asarray(rx_coded_bits, np.uint8).ravel()
    if len(rx) < need_bits:
        rx = np.concatenate([rx, np.zeros(need_bits - len(rx), np.uint8)])
    rx = rx[:need_bits]
    rx_bytes = np.packbits(rx)[:n_cw * RS_N]
    rx_mat = rx_bytes.reshape(RS_N, n_cw).T            # de-interleave
    out = bytearray()
    passed = 0
    for i in range(n_cw):
        msg = None
        try:
            decoded = rsc.decode(bytes(rx_mat[i]))[0]
            if len(decoded) == rs_k:
                msg = bytes(decoded)
        except (ReedSolomonError, Exception):
            msg = None
        ok = (msg is not None and (zlib.crc32(msg) & 0xFFFFFFFF) == crc32_codewords[i])
        passed += int(ok)
        out += (msg if (msg is not None and len(msg) == rs_k) else bytes(rs_k))
    return bytes(out), passed


def confirm_tiers(audio_nom, manifest, sync) -> list[dict]:
    align = sync["chirp0_nominal"] - sync["expected_chirp0"]
    pad = int(0.30 * SR)
    rows = []
    for entry in manifest["tiers"]:
        rs_k = int(entry["rs_k"])
        n_cw = int(entry["n_codewords"])
        message_bytes = int(entry["message_bytes"])
        coded_bits = int(entry["coded_bits"])
        crc32_cw = entry["crc32_codewords"]

        # regenerate transmitted payload + tx coded bits (for raw BER)
        payload = _regenerate_payload(entry["payload_seed"], message_bytes)
        assert hashlib.sha256(payload).hexdigest() == entry["payload_sha256"]
        tx_coded_bits, _, _ = encode_tier(payload, rs_k)
        assert len(tx_coded_bits) == coded_bits

        # rebuild the SAME scheme from the tier spec via the master's builder
        tier_spec = _tier_dict_for(entry)
        fs = build_tier_scheme(tier_spec)

        start = int(entry["segment_start_sample"]) + align
        body_end = int(entry["body_end_sample"]) + align
        w_lo = max(0, start - pad)
        w_hi = min(len(audio_nom), body_end)           # trim exactly to body end
        window = np.asarray(audio_nom[w_lo:w_hi], np.float32)

        mod_ref = getattr(fs, "_modulate_ref", None)
        if mod_ref is not None:
            mod_ref._nbits = coded_bits

        rx_bits = np.asarray(fs.demodulate(window, SR), np.uint8)
        raw_ber = _hamming_ber(tx_coded_bits, rx_bits)
        msg, cw_passed = decode_tier_bits(rx_bits, rs_k, n_cw, crc32_cw)
        byte_exact = (msg[:message_bytes] == payload)

        rows.append({
            "tier": entry["tier"],
            "scheme": fs.name,
            "scheme_label": entry["scheme_label"],
            "substituted": entry.get("substituted", False),
            "enables": entry["enables"],
            "rs_k": rs_k,
            "n_codewords": n_cw,
            "codewords_passed": cw_passed,
            "byte_exact": bool(byte_exact),
            "raw_ber": float(raw_ber),
            "gross_bps": float(fs.gross_bps),
            "net_bps": float(fs.gross_bps * rs_k / RS_N),
        })
    return rows


def _tier_dict_for(entry: dict) -> dict:
    """Reconstruct the TIERS-style dict the master builder needs from a manifest
    tier entry's scheme_spec + rs_k."""
    spec = dict(entry["scheme_spec"])
    spec["rs_k"] = entry["rs_k"]
    spec["tier"] = entry["tier"]
    return spec


# ===========================================================================
# ADVICE engine (metric -> diagnosis -> ranked actions)
# ===========================================================================
def _advice_for_metric(metric: str, ch: dict, target_tier: str) -> list[dict]:
    """Ranked actions for a binding metric, tagged with expected tier gain.
    The action MAP follows SPEC sec.5."""
    if metric == "SNR":
        return [
            {"action": "raise record level toward ~7.0 (Dolby OFF) and check cabling/amp",
             "gain": "+1 tier"},
            {"action": "quieter room + closer mic, or a better-quality mic",
             "gain": "+1 tier"},
            {"action": "go electrical line-in (USB interface) instead of acoustic",
             "gain": "+1-2 tiers"},
        ]
    if metric == "flutter":
        return [
            {"action": "service the deck: belt, capstan, pinch-roller",
             "gain": "+1 tier"},
            {"action": "capture with Voice Memos (sample-accurate clock), NOT the "
                       "Continuity / live-Mac mic which jitters",
             "gain": "+1 tier"},
        ]
    if metric == "usable BW" or metric == "BW":
        return [
            {"action": "clean the heads and check azimuth alignment", "gain": "+1 tier"},
            {"action": "use fresher tape (worn tape rolls off HF)", "gain": "+0.5 tier"},
            {"action": "a speaker/mic with flatter HF response", "gain": "+0.5 tier"},
        ]
    if metric == "diffuse":
        return [
            {"action": "deader / quieter room, closer mic, or direct coupling",
             "gain": "+0.5 tier"},
            {"action": "go electrical line-in (USB interface) -- the real fix for "
                       "the acoustic reverb floor", "gain": "+1-2 tiers"},
        ]
    if metric == "IMD":
        return [
            {"action": "DROP record level to ~7.0 (8.5 saturates -> IMD bloom)",
             "gain": "+1 tier"},
            {"action": "confirm Dolby NR is OFF at record AND playback", "gain": "+1 tier"},
        ]
    return [{"action": f"investigate {metric}", "gain": "?"}]


_METRIC_KEY = {  # binding-metric label -> the action map key
    "SNR": "SNR", "flutter": "flutter", "usable BW": "BW", "HF rolloff": "BW",
    "diffuse": "diffuse", "IMD": "IMD",
}


def build_advice(ch: dict, confirmed_tier: str | None, pred: dict) -> dict:
    """Identify the binding bottleneck to the NEXT tier above the confirmed tier
    and emit ranked actions.  The next tier is confirmed+1 (or T0 if nothing
    confirmed); its failing metrics are the bottleneck."""
    # next tier above confirmed
    if confirmed_tier is None:
        next_idx = 0
    else:
        next_idx = TIER_ORDER.index(confirmed_tier) + 1
    if next_idx >= len(TIER_ORDER):
        return {"next_tier": None, "bottleneck": [], "actions": [],
                "note": "already at the top tier (T7) -- no higher tier to advise toward."}
    next_tier = TIER_ORDER[next_idx]
    req = REQ_BY_TIER[next_tier]
    meets, fails = _tier_meets(ch, req)

    if meets:
        # confirmed < next but metrics say next should pass -> the link is
        # metric-clean but the decode didn't close (sync / azimuth / realization).
        return {
            "next_tier": next_tier,
            "bottleneck": [],
            "actions": [
                {"action": "metrics clear the next tier but it did not decode -- "
                           "re-capture (a clean re-take often closes it); check "
                           "start/end chirps have ~1 s silence and Dolby is OFF",
                 "gain": "+1 tier"}],
            "note": "no metric blocks the next tier; the gap is realization/sync, "
                    "not the channel."}

    # rank failing metrics by how far they overshoot (the binding one first).
    binding = []
    for f in fails:
        # f like "SNR 12.0 dB < 15" / "flutter 0.55% > 0.45%"
        label = f.split()[0]
        # map composite labels
        if f.startswith("usable BW"):
            label = "usable BW"
        elif f.startswith("HF rolloff"):
            label = "HF rolloff"
        binding.append({"metric": label, "detail": f})

    actions = []
    seen = set()
    for b in binding:
        key = _METRIC_KEY.get(b["metric"], b["metric"])
        for a in _advice_for_metric(key, ch, next_tier):
            sig = a["action"]
            if sig not in seen:
                seen.add(sig)
                actions.append({**a, "addresses": b["metric"]})
    return {"next_tier": next_tier, "bottleneck": binding, "actions": actions,
            "note": ""}


# ===========================================================================
# main decode + report card
# ===========================================================================
def decode(wav_path: str, *, selfcheck: bool = False, out_tag: str | None = None,
           verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["master_id"] == "eval_cassette_v1", manifest["master_id"]

    audio, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)

    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]

    ch, sounder = characterize(audio_nom, manifest, sync)
    pred = predict_tier(ch)
    rows = confirm_tiers(audio_nom, manifest, sync)

    # confirmed tier = highest byte-exact tier
    exact = [r["tier"] for r in rows if r["byte_exact"]]
    confirmed = max(exact, key=lambda t: TIER_ORDER.index(t)) if exact else None
    predicted = pred["predicted"]

    # cross-check
    cross = _cross_check(predicted, confirmed)
    advice = build_advice(ch, confirmed, pred)

    result = {
        "wav": str(wav_path),
        "master_id": manifest["master_id"],
        "selfcheck": bool(selfcheck),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "channel": ch,
        "predict": {"predicted_tier": predicted, "pass_map": pred["pass_map"],
                    "first_fail": pred["first_fail"]},
        "confirm": rows,
        "confirmed_tier": confirmed,
        "cross_check": cross,
        "advice": advice,
        "all_byte_exact": all(r["byte_exact"] for r in rows),
    }

    if verbose:
        _print_report_card(wav_path, result, manifest, selfcheck)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(wav_path).stem
    out_json = RESULTS_DIR / f"{tag}_eval.json"
    out_json.write_text(json.dumps(result, indent=2, default=float))
    if verbose:
        print(f"[eval] wrote {out_json}")

    if selfcheck:
        _assert_selfcheck(result)
    return result


def _cross_check(predicted, confirmed) -> dict:
    if predicted is None and confirmed is None:
        return {"agree": True, "note": "both below T0 (link too poor for any tier)"}
    pi = TIER_ORDER.index(predicted) if predicted else -1
    ci = TIER_ORDER.index(confirmed) if confirmed else -1
    delta = ci - pi
    if delta == 0:
        return {"agree": True, "delta_tiers": 0, "note": "predict == confirm"}
    if delta < 0:
        return {"agree": False, "delta_tiers": delta,
                "note": (f"confirmed {confirmed} < predicted {predicted}: a "
                         f"sync / IMD / azimuth issue the metrics missed -- the "
                         f"channel looks good but the decode didn't close.")}
    return {"agree": False, "delta_tiers": delta,
            "note": (f"confirmed {confirmed} > predicted {predicted}: the "
                     f"requirements table is conservative here (the link beat its "
                     f"predicted tier).")}


def _enables_label(rows, confirmed):
    if confirmed is None:
        return "(no tier closed -- link below T0)"
    for r in rows:
        if r["tier"] == confirmed:
            return r["enables"]
    return ""


def _fmt(v, fmt="{:.1f}", none="n/a"):
    return none if v is None else fmt.format(v)


def _print_report_card(wav_path, result, manifest, selfcheck):
    ch = result["channel"]
    confirmed = result["confirmed_tier"]
    predicted = result["predict"]["predicted_tier"]
    rows = result["confirm"]
    cross = result["cross_check"]
    advice = result["advice"]
    sync = result["sync"]

    net_by_tier = {e["tier"]: e["projected_net_bps"] for e in manifest["tiers"]}
    conf_net = net_by_tier.get(confirmed, 0)

    mode = "  [SELF-CHECK: no channel]" if selfcheck else ""
    print()
    print("=== CASSETTE LINK REPORT CARD ===" + mode)
    agree = "[agree]" if cross.get("agree") else "[MISMATCH]"
    print(f"Confirmed tier: {confirmed or '--'} (~{conf_net:.0f} bps)   "
          f"Predicted: {predicted or '--'}   {agree}")
    print(f"Enables: {_enables_label(rows, confirmed)}")
    if not cross.get("agree"):
        print(f"  ! {cross['note']}")
    print("-- Channel " + "-" * 30)
    print(f" SNR {_fmt(ch['snr_db_median'])} dB (p10 {_fmt(ch['snr_db_p10'])}) "
          f"| usable BW {_fmt(ch['usable_bw_hz'],'{:.0f}')} Hz "
          f"(HF {_fmt(ch['hf_rolloff_db_at_9k'],'{:.0f}')} dB) "
          f"| flutter {_fmt(ch['flutter_pct'],'{:.2f}')}%")
    print(f" clock {_fmt(ch['recovered_clock'],'{:.3f}')}x "
          f"| IMD {_fmt(ch['imd_db'],'{:.0f}')} dB "
          f"| diffuse {_fmt(ch['diffuse_frac'],'{:.2f}')} "
          f"| noise floor {_fmt(ch['noise_floor_dbfs'],'{:.0f}')} dBFS")
    # confirm table
    print("-- Tiers " + "-" * 32)
    print(f" {'tier':4s} {'net':>6} {'exact':>6} {'cw_ok':>8} {'raw_ber':>9}  enables")
    for r in rows:
        ex = "YES" if r["byte_exact"] else "no"
        sub = " (sub)" if r["substituted"] else ""
        print(f" {r['tier']:4s} {r['net_bps']:>6.0f} {ex:>6} "
              f"{r['codewords_passed']:>3}/{r['n_codewords']:<3} "
              f"{r['raw_ber']:>9.5f}  {r['enables'][:40]}{sub}")
    # bottleneck + advice
    nxt = advice.get("next_tier")
    if nxt:
        nxt_net = net_by_tier.get(nxt, 0)
        print(f"-- Bottleneck to next tier ({nxt}, ~{nxt_net:.0f} bps) " + "-" * 6)
        if advice["bottleneck"]:
            for b in advice["bottleneck"]:
                print(f" {b['detail']}")
        elif advice.get("note"):
            print(f" {advice['note']}")
        for i, a in enumerate(advice["actions"], 1):
            print(f"   -> #{i} {a['action']}   ({a['gain']})")
    else:
        print(f"-- Bottleneck " + "-" * 18)
        print(f" {advice.get('note', 'at the top tier')}")
    print(" Note: 10 MB+ capacity tiers (electrical/stereo) exist but have no "
          "curated payload yet -- gap, not shipped.")
    print("=" * 40)


def _assert_selfcheck(result):
    """HARD GATE: every tier byte-exact AND clean-channel characterization sane."""
    errs = []
    failed = [r["tier"] for r in result["confirm"] if not r["byte_exact"]]
    if failed:
        errs.append(f"tiers not byte-exact on no-channel self-check: {failed}")
    ch = result["channel"]
    # clean-channel sanity: high SNR, ~0 flutter, full BW, low IMD, low diffuse
    snr = ch.get("snr_db_median")
    if snr is None or snr < 30.0:
        errs.append(f"clean SNR too low: {snr}")
    flut = ch.get("flutter_pct")
    if flut is None or flut > 0.5:
        errs.append(f"clean flutter not ~0: {flut}")
    bw = ch.get("usable_bw_hz")
    if bw is None or bw < 9000.0:
        errs.append(f"clean usable BW not full: {bw}")
    imd = ch.get("imd_db")
    if imd is None or imd > -25.0:
        errs.append(f"clean IMD not low: {imd}")
    diff = ch.get("diffuse_frac")
    if diff is None or diff > 0.30:
        errs.append(f"clean diffuse not low: {diff}")
    clk = ch.get("recovered_clock")
    if clk is None or abs(clk - 1.0) > 0.02:
        errs.append(f"clean clock not ~1.0: {clk}")
    if errs:
        raise AssertionError("HARD GATE FAILED (self-check):\n  " + "\n  ".join(errs))
    print("[selfcheck] HARD GATE PASSED: all tiers byte-exact + clean-channel "
          "characterization sane.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--selfcheck", action="store_true",
                    help="HARD GATE: no-channel decode, every tier MUST be byte-exact "
                         "and the characterization must read sane clean values")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.wav, selfcheck=args.selfcheck, out_tag=args.out_tag)
