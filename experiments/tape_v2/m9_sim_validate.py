"""m9_sim_validate.py -- the PRE-REGISTERED master9 gate harness (MASTER9_PLAN s4).

Runs EXACTLY the frozen 5-gate SHIP/HOLD/REJECT protocol of MASTER9_PLAN.md s4
on every ladder rung, over the frozen seed/stress grid, and emits a per-rung
verdict. The gates are FROZEN: this harness must never tune a gate, threshold, or
rung parameter to pass. Genuine code bugs revealed by a failure may be fixed (and
are logged in x9_dossier/M9_gate_report.md), but the gate definitions below are a
literal transcription of the plan.

=== Channel config (MASTER9_PLAN s4.0, FROZEN) ===
  Nominal:  sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)
  Sanity:   profile='tape4' (quieter take) -- reported, not a SHIP gate
  Seeds:    nominal axis 8 seeds {0..7}; each stress axis 4 seeds {0..3}

=== HF-flutter injection (MASTER9_PLAN s4.1, x9_flutter_gate) ===
  5-23.4 Hz band jitter at {12,16,20} us RMS. SHIP threshold = 12 us (>=3/4);
  16 us is the headroom cell (the record passes 12 us 3/4, is on its cliff at
  16 us 1/4). The injection is VALIDATED (x9_flutter_gate.py) to reproduce the
  real m8 N512-pass / N1024-fail differential.

=== SHIP / HOLD / REJECT rule (MASTER9_PLAN s4.2, FROZEN) ===
A rung SHIPs iff ALL of:
  1. Nominal:           >= 7/8 seeds byte-exact (aac=False, dg=0.58).
  2. dg-pessimism:      >= 6/8 seeds byte-exact at dg=0.65.
  3. HF-flutter 12 us:  >= 3/4 seeds byte-exact (5-23.4 Hz injection).
  4. Combo SNR-2 dB AND flutter_frac 0.30:  >= 3/4 seeds byte-exact.
  5. Byte-margin floor: mean BYTE-error-rate over nominal seeds
        <= 0.6 * (255-k)/(2*255)
     (RS127->0.151, RS159->0.113, RS179->0.089, RS191->0.075).
HOLD: passes 1,2,5 but fails timing gate 3 or 4 (experimental, never headline).
REJECT: fails nominal (1) or the byte-margin floor (5).

Hard structural rules (non-negotiable): self-tracking pilot in every rung (built
in); CRC32-per-codeword guard ON (built in); spacing < 750 Hz is HOLD by rule
(M8); shorter symbol is the default at equal rate.

Checkpointing: every completed (rung, cell) is appended to
results/m9_sim_validate_partial.json so a long run survives interruption; the
final verdict lands in results/m9_sim_validate_<tag>.json.

Usage:
    python3 experiments/tape_v2/m9_sim_validate.py [--rungs m9_m0_... ...]
                                                   [--workers 4] [--tag run1]
                                                   [--profile tape7] [--quick]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from scipy import signal

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "deepdive2", ROOT / "tests" / "e2e", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                          # noqa: E402
from m3_codec import Rung                          # noqa: E402
import sim_v2                                       # noqa: E402
import real_channel_sim as rcs                      # noqa: E402  (FROZEN; read-only)
from h4_dqpsk import (                              # noqa: E402
    DQPSKScheme, build_section, nominal_frame_bits,
    PAD_LO_S, PAD_HI_S, FS,
)
from x9_resampling_pll import ResamplingPLLDemod   # noqa: E402
from x9_flutter_gate import gate_jitter            # noqa: E402  (VALIDATED injection)
from m9_master import DropNullDQPSK, make_scheme    # noqa: E402

try:
    from x9_freqdiff import FreqDiffDQPSKScheme
    _HAVE_FREQDIFF = True
except Exception:                                   # pragma: no cover
    FreqDiffDQPSKScheme = None
    _HAVE_FREQDIFF = False

RESULTS_DIR = _HERE / "results"
MANIFEST_PATH = _HERE / "master9_manifest.json"
SR = codec.FS
assert SR == FS == 48_000

# ---- FROZEN gate constants (MASTER9_PLAN s4) ------------------------------
NOMINAL_DG = 0.58
PESSIMISM_DG = 0.65
N_SEEDS_NOMINAL = 8                 # {0..7}
N_SEEDS_STRESS = 4                  # {0..3}
HF_FLUTTER_SHIP_US = 12.0          # SHIP line (gate 3)
HF_FLUTTER_HEADROOM_US = (16.0, 20.0)   # diagnostic headroom cells
COMBO_SNR_DELTA_DB = -2.0
COMBO_FLUTTER_FRAC = 0.30
SNR_DIAG_DELTA_DB = -4.0           # diagnostic only (not a SHIP gate)
CLOCK_OFFSETS = (-0.0015, 0.0015)  # +-0.15% static resample (diagnostic)
REVERB_TAU_SCALES = (0.5, 1.5)     # diagnostic CP/ISI margin

# receiver sweep (MASTER9_PLAN s2.4): resampling-PLL (default) + EMA alphas;
# RS errors-only + errors-and-erasures, all CRC32-guarded.
PLL_BW_HZ = 30.0
EMA_ALPHAS = (0.5, 0.4, 0.6)
ERASE_FRACS = (0.0, 0.25, 0.5)


# ===========================================================================
# Scheme reconstruction from a manifest rung entry (mirror m9_decode).
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
    return DQPSKScheme(p["P"], p["N"], p["spacing"],
                       min_spacing_hz=p.get("min_spacing_hz", 562.0))


# ===========================================================================
# Channel variants for one section clip (each returns a float64 array).
#   nominal / dg / snr / flutter_frac via channel_v2 overrides;
#   HF-flutter via x9_flutter_gate.gate_jitter (5-23.4 Hz, VALIDATED);
#   clock offset via a static resample;
#   reverb tau scale via a deep-copied params override (the knob lives in
#     params['spectral_contamination']['scaling'], not _sim, so we pass it as a
#     sim_override-equivalent by patching the runtime params via sim_v2 kw).
# ===========================================================================
def _channel_nominal(x, *, profile, seed, dg, snr_delta, flutter_frac):
    """The aac=False faithful channel with diffuse_gain/flutter_frac/SNR overrides
    -- the public sim_v2.channel_v2 path the gate's nominal/dg/combo cells use."""
    overrides = {"diffuse_gain": float(dg)}
    if flutter_frac is not None:
        overrides["flutter_residual_frac"] = float(flutter_frac)
    snr_db = None
    if snr_delta:
        snr_db = sim_v2.PROFILES[profile]["snr_db"] + float(snr_delta)
    return np.asarray(sim_v2.channel_v2(
        x, profile=profile, aac=False, seed_offset=int(seed),
        snr_db=snr_db, sim_overrides=overrides), np.float64)


def _channel_reverb_tau(x, *, profile, seed, dg, reverb_tau_scale):
    """Diagnostic reverb-tau cell: the reverb_tail_tau_ms knob lives in
    params['spectral_contamination']['scaling'], not _sim, so it is unreachable
    via sim_v2.channel_v2's sim_overrides. Reproduce the EXACT aac=False nominal
    path here on a deep-copied params with tau scaled (real_channel_sim FROZEN;
    we only read+copy it). This mirrors sim_v2.channel_v2(aac=False) byte-for-byte
    except for the scaled tau."""
    import copy
    prof = sim_v2.PROFILES[profile]
    params = copy.deepcopy(rcs.load_params())
    sim = dict(params.get("_sim", {})); sim.update(sim_v2.SIM2)
    sim["diffuse_gain"] = float(dg)
    params["_sim"] = sim
    params["flutter_wrms_pct"]["master3"] = prof["flutter_wrms_pct"]
    params["spectral_contamination"]["scaling"]["reverb_tail_tau_ms"] *= float(reverb_tau_scale)
    snr = prof["snr_db"] + float(sim.get("snr_delta_db", 0.0))
    return np.asarray(rcs.real_channel(x, params=params, capture="master3",
                                       snr_db=float(snr), seed_offset=int(seed)),
                      np.float64)


def _apply_channel(section, *, profile, seed, dg, snr_delta, flutter_frac,
                   hf_us, clock_off, reverb_tau_scale):
    x = np.asarray(section, np.float64)
    n0 = len(x)
    if clock_off:
        # static deck-clock offset BEFORE the channel: the decoder's global
        # chirp-resync removes it (s2.1). Here the clip has no global chirp, so we
        # resample back to nominal length AFTER the channel (proxy for the resync).
        from fractions import Fraction
        f = Fraction(1.0 + clock_off).limit_denominator(100000)
        x = signal.resample_poly(x, f.numerator, f.denominator)

    if reverb_tau_scale not in (None, 1.0):
        y = _channel_reverb_tau(x, profile=profile, seed=seed, dg=dg,
                                reverb_tau_scale=reverb_tau_scale)
    else:
        y = _channel_nominal(x, profile=profile, seed=seed, dg=dg,
                             snr_delta=snr_delta, flutter_frac=flutter_frac)

    if clock_off:
        y = signal.resample(y, n0)          # undo the static stretch (chirp-resync proxy)

    if hf_us and hf_us > 0:
        tau = gate_jitter(len(y), int(seed), hf_us * 1e-6)   # 5-23.4 Hz, VALIDATED
        t = np.arange(len(y)) / FS
        y = np.interp(t, np.clip(t - tau, 0.0, t[-1]), y)
    return y


# ===========================================================================
# CRC32-guarded RS merge (MASTER9_PLAN s2.3) -- identical contract to
# m9_decode._rs_merge_guarded but local (errors-only here; erasures via the
# per-frame reliability proxy).  Returns (packed_bytes, cw_failed, miscorrected).
# ===========================================================================
def _rs_merge_guarded(rx_frames, meta, crc_table, *, erase_frac, rel_cw):
    from reedsolo import RSCodec, ReedSolomonError
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    fb_bits, n_frames = meta["frame_bits"], meta["n_frames"]
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
    cw_failed = miscorrected = 0
    for i in range(n_cw):
        row = bytearray(rx_mat[i].tobytes())
        epos = []
        if n_erase_max and rel_cw is not None and i < len(rel_cw):
            epos = sorted(int(j) for j in np.argsort(rel_cw[i])[:n_erase_max])
        try:
            dec = (rsc.decode(row, erase_pos=epos)[0] if epos else rsc.decode(row)[0])
            msg = bytes(dec)
            if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
                miscorrected += 1
                cw_failed += 1
                recovered += bytes(rs_k)
            else:
                recovered += msg
        except (ReedSolomonError, Exception):
            cw_failed += 1
            recovered += bytes(rs_k)
    out = bytes(recovered)[:meta["payload_len"]]
    return out, cw_failed, miscorrected


def _frame_reliability_to_cw(diags, meta):
    """Coarse per-codeword reliability proxy from frame-level |dtau| RMS (lower
    = worse -> erase first). CRC guard makes a wrong pick harmless."""
    n_frames = meta["n_frames"]
    rs_n, n_cw = meta["rs_n"], meta["n_codewords"]
    frame_bad = np.zeros(n_frames)
    for fi in range(min(n_frames, len(diags))):
        d = diags[fi].get("dtau") if isinstance(diags[fi], dict) else None
        frame_bad[fi] = (float(np.sqrt(np.mean(np.square(d))))
                         if d is not None and len(d) else 0.0)
    fb_bits = meta["frame_bits"]
    rel = np.zeros((n_cw, rs_n))
    for j in range(rs_n):
        for i in range(n_cw):
            stream_byte = j * n_cw + i
            fi = min((stream_byte * 8) // fb_bits, n_frames - 1)
            rel[i, j] = -frame_bad[fi]
    return rel


# ===========================================================================
# Decode one channelled section clip with the FULL master9 receiver sweep.
# Returns (byte_exact, cw_failed, byte_error_rate, front_end_used).
# byte_error_rate is computed against the EXPECTED packed bytes on the WINNING
# attempt -- the quantity gate 5 (byte-margin floor) measures.
# ===========================================================================
def _decode_section_clip(y, starts, meta, sch, crc_table, expected_packed, *,
                         is_freqdiff, eq_tilt=None):
    nom_bits = nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    flen_full = None

    def demod_all(frontend):
        rx, diags = [], []
        for fi, st in enumerate(starts):
            nd = sch.nsym_data(nom_bits[fi])
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(y), st + _flen(fi) + pad_hi)
            bits, diag = frontend(y[w_lo:w_hi], nd)
            rx.append(np.asarray(bits, np.uint8))
            diags.append(diag if isinstance(diag, dict) else {})
        return rx, diags

    # frame length lookup (each frame's modulated audio length, ex-gap)
    _flen_cache: dict[int, int] = {}

    def _flen(fi):
        if fi not in _flen_cache:
            fb = np.zeros(meta["frame_bits"], np.uint8)
            _flen_cache[fi] = len(np.asarray(sch.modulate(fb), np.float32))
        return _flen_cache[fi]

    # build candidate front-ends
    frontends = []
    if is_freqdiff:
        frontends.append(("freqdiff",
                          lambda w, nd, s=sch, t=eq_tilt: s.demod(w, nd, refine=True,
                                                                  eq_tilt=t)))
    else:
        pll = ResamplingPLLDemod(sch, pll_bw_hz=PLL_BW_HZ, front_end="pll")
        frontends.append(("resampling_pll", lambda w, nd, d=pll: d.demod(w, nd)))
        for a in EMA_ALPHAS:
            ema = ResamplingPLLDemod(sch, front_end="ema", ema_alpha=a)
            frontends.append((f"ema{a}", lambda w, nd, d=ema: d.demod(w, nd)))

    best = None
    for fe_name, fe in frontends:
        rx, diags = demod_all(fe)
        rel_cw = _frame_reliability_to_cw(diags, meta)
        for ef in ERASE_FRACS:
            out, cwf, misc = _rs_merge_guarded(rx, meta, crc_table,
                                               erase_frac=ef, rel_cw=rel_cw)
            exact = out == expected_packed
            berr = sum(a != b for a, b in zip(out, expected_packed)) + abs(
                len(out) - len(expected_packed))
            att = {"front_end": fe_name, "erase_frac": ef, "byte_exact": exact,
                   "cw_failed": cwf, "miscorrected": misc, "byte_errors": berr}
            if best is None or _better(att, best):
                best = att
            if exact:
                break
        if best and best["byte_exact"]:
            break

    ber = best["byte_errors"] / max(1, len(expected_packed))
    return best["byte_exact"], best["cw_failed"], ber, best["front_end"], best["miscorrected"]


def _better(att, best):
    if att["byte_exact"] != best["byte_exact"]:
        return att["byte_exact"]
    if att["cw_failed"] != best["cw_failed"]:
        return att["cw_failed"] < best["cw_failed"]
    return att["byte_errors"] < best["byte_errors"]


# ===========================================================================
# One gate cell: build the rung section, channel it, decode, score.
# Worker entry (picklable: takes only plain data, rebuilds the scheme).
# ===========================================================================
def run_cell(rung_entry, cell):
    t0 = time.time()
    sch = _scheme_from_entry(rung_entry)
    if sch is None:
        return {**cell, "rung": rung_entry["name"], "byte_exact": None,
                "skipped_module_absent": True, "wall_s": 0.0}
    meta = rung_entry["meta"]
    crc_table = rung_entry["crc32_codewords"]
    expected_packed = (_HERE / rung_entry["payload_sidecar"]).read_bytes()
    is_fd = rung_entry["kind"] == "freqdiff"

    # rebuild this rung's standalone section clip (LEAD + sounder + frames + gaps)
    section, starts = _build_clip(sch, meta, expected_packed)

    y = _apply_channel(
        section,
        profile=cell["profile"], seed=cell["seed"], dg=cell["dg"],
        snr_delta=cell["snr_delta"], flutter_frac=cell["flutter_frac"],
        hf_us=cell["hf_us"], clock_off=cell["clock_off"],
        reverb_tau_scale=cell["reverb_tau_scale"],
    )

    exact, cwf, ber, fe, misc = _decode_section_clip(
        y, starts, meta, sch, crc_table, expected_packed, is_freqdiff=is_fd)
    return {**cell, "rung": rung_entry["name"], "byte_exact": bool(exact),
            "cw_failed": int(cwf), "n_codewords": meta["n_codewords"],
            "byte_error_rate": round(float(ber), 6), "front_end": fe,
            "miscorrected": int(misc), "wall_s": round(time.time() - t0, 1)}


# ---- per-rung clip construction --------------------------------------------
def _build_clip(sch, meta, expected_packed):
    """Build a standalone per-rung section (LEAD + front sounder + frames@gaps +
    TAIL) and the LOCAL frame_starts. Mirrors h4_dqpsk.build_section, which the
    proven flutter gate (x9_flutter_gate.run_cell) uses, so the decode window
    geometry matches the proven receiver exactly."""
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected_packed, rung)
    frame_audios = [np.asarray(sch.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)
    return section, starts


# ===========================================================================
# Build the cell list for a rung (the FROZEN s4 matrix).
# ===========================================================================
def _make_cells(profile_nominal):
    nominal_seeds = list(range(N_SEEDS_NOMINAL))
    stress_seeds = list(range(N_SEEDS_STRESS))
    cells = []

    def add(name, *, gate, seeds, dg=NOMINAL_DG, snr_delta=0.0, flutter_frac=None,
            hf_us=0.0, clock_off=0.0, reverb_tau_scale=1.0, profile=profile_nominal):
        for s in seeds:
            cells.append({"cell": name, "gate": gate, "seed": s, "profile": profile,
                          "dg": dg, "snr_delta": snr_delta, "flutter_frac": flutter_frac,
                          "hf_us": hf_us, "clock_off": clock_off,
                          "reverb_tau_scale": reverb_tau_scale})

    # --- the 5 SHIP-decision gates (MASTER9_PLAN s4.2) ---
    add("g1_nominal", gate="g1", seeds=nominal_seeds, dg=NOMINAL_DG)
    add("g2_dg_pessimism", gate="g2", seeds=nominal_seeds, dg=PESSIMISM_DG)
    add("g3_hf_flutter_12us", gate="g3", seeds=stress_seeds, hf_us=HF_FLUTTER_SHIP_US)
    add("g4_combo_snr_flutterfrac", gate="g4", seeds=stress_seeds,
        snr_delta=COMBO_SNR_DELTA_DB, flutter_frac=COMBO_FLUTTER_FRAC)
    # gate 5 (byte-margin floor) reuses the g1 nominal cells' byte_error_rate.

    # --- diagnostic headroom / stress cells (reported, NOT SHIP gates) ---
    for us in HF_FLUTTER_HEADROOM_US:
        add(f"d_hf_flutter_{int(us)}us", gate="diag", seeds=stress_seeds, hf_us=us)
    add("d_snr_-4db", gate="diag", seeds=stress_seeds, snr_delta=SNR_DIAG_DELTA_DB)
    for co in CLOCK_OFFSETS:
        add(f"d_clock_{co:+.4f}", gate="diag", seeds=stress_seeds, clock_off=co)
    for rt in REVERB_TAU_SCALES:
        add(f"d_reverb_tau_x{rt}", gate="diag", seeds=stress_seeds, reverb_tau_scale=rt)
    # sanity bound: tape4 nominal (quieter take) -- reported only
    add("d_tape4_nominal", gate="diag", seeds=stress_seeds, profile="tape4")
    return cells


# ===========================================================================
# SHIP / HOLD / REJECT adjudication for one rung from its completed cells.
# Literal transcription of MASTER9_PLAN s4.2.
# ===========================================================================
def _byte_margin_cap(rs_k):
    return round(0.6 * (255 - rs_k) / (2 * 255), 4)


def adjudicate(rung_entry, cells):
    rs_k = rung_entry["meta"]["rs_k"]
    by_gate: dict[str, list] = {}
    for c in cells:
        by_gate.setdefault(c["gate"], []).append(c)

    def frac_exact(gate):
        rows = by_gate.get(gate, [])
        n = len(rows)
        ne = sum(1 for r in rows if r.get("byte_exact"))
        return ne, n

    g1_ne, g1_n = frac_exact("g1")
    g2_ne, g2_n = frac_exact("g2")
    g3_ne, g3_n = frac_exact("g3")
    g4_ne, g4_n = frac_exact("g4")

    # gate 5: mean byte-error-rate over the NOMINAL (g1) seeds
    g1_rows = by_gate.get("g1", [])
    mean_ber = (float(np.mean([r["byte_error_rate"] for r in g1_rows
                               if r.get("byte_error_rate") is not None]))
                if g1_rows else 1.0)
    cap = _byte_margin_cap(rs_k)

    gate1 = g1_n > 0 and g1_ne >= 7      # >= 7/8
    gate2 = g2_n > 0 and g2_ne >= 6      # >= 6/8
    gate3 = g3_n > 0 and g3_ne >= 3      # >= 3/4
    gate4 = g4_n > 0 and g4_ne >= 3      # >= 3/4
    gate5 = mean_ber <= cap

    if gate1 and gate2 and gate3 and gate4 and gate5:
        verdict = "SHIP"
    elif gate1 and gate2 and gate5 and not (gate3 and gate4):
        verdict = "HOLD"          # sim likes it, leans on under-modeled timing
    elif (not gate1) or (not gate5):
        verdict = "REJECT"        # fails nominal or the margin floor
    else:
        verdict = "HOLD"          # e.g. fails dg-pessimism but passes 1,5 -- carry

    # M8 / spacing<750 Hz and M9a freqdiff are HOLD-by-rule regardless of sim
    spacing_hz = None
    if rung_entry["kind"] != "freqdiff":
        spacing_hz = rung_entry["dqpsk_params"]["spacing"] * (FS / rung_entry["dqpsk_params"]["N"])
    rule_hold = (rung_entry.get("status") == "HOLD" or rung_entry["kind"] == "freqdiff"
                 or (spacing_hz is not None and spacing_hz < 750.0))
    final = verdict
    rule_note = ""
    if rule_hold and verdict == "SHIP":
        final = "HOLD"
        rule_note = "HOLD-by-rule (spacing<750Hz / freqdiff / status=HOLD), sim cannot bless"
    elif rule_hold:
        rule_note = "HOLD-by-rule applies (spacing<750Hz / freqdiff / status=HOLD)"

    return {
        "rung": rung_entry["name"], "rs_k": rs_k,
        "net_bps": rung_entry.get("projected_net_bps"),
        "x_record": rung_entry.get("x_record"),
        "expected_verdict": rung_entry.get("expected_verdict", ""),
        "gate1_nominal": {"ne": g1_ne, "n": g1_n, "pass": gate1, "rule": ">=7/8"},
        "gate2_dg065": {"ne": g2_ne, "n": g2_n, "pass": gate2, "rule": ">=6/8"},
        "gate3_hf12us": {"ne": g3_ne, "n": g3_n, "pass": gate3, "rule": ">=3/4"},
        "gate4_combo": {"ne": g4_ne, "n": g4_n, "pass": gate4, "rule": ">=3/4"},
        "gate5_byte_floor": {"mean_byte_err_rate": round(mean_ber, 6),
                             "cap": cap, "pass": gate5, "rule": f"<= {cap}"},
        "verdict_sim": verdict,
        "verdict_final": final,
        "rule_note": rule_note,
        "diag": _diag_summary(by_gate),
    }


def _diag_summary(by_gate):
    out = {}
    for c in by_gate.get("diag", []):
        out.setdefault(c["cell"], {"ne": 0, "n": 0})
        out[c["cell"]]["n"] += 1
        out[c["cell"]]["ne"] += 1 if c.get("byte_exact") else 0
    return out


# ===========================================================================
def _load_rungs(names=None, include_hold=True):
    manifest = json.loads(MANIFEST_PATH.read_text())
    rungs = []
    for sec in manifest["ws_payloads"]:
        if sec.get("skipped"):
            continue
        if names and sec["name"] not in names:
            continue
        if not include_hold and sec.get("status") == "HOLD":
            continue
        rungs.append(sec)
    return rungs


def _checkpoint_path(tag):
    return RESULTS_DIR / f"m9_sim_validate_partial_{tag}.json"


def _load_checkpoint(tag):
    p = _checkpoint_path(tag)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _cell_key(rung_name, cell):
    return f"{rung_name}|{cell['cell']}|s{cell['seed']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rungs", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="run1")
    ap.add_argument("--profile", default="tape7")
    ap.add_argument("--quick", action="store_true",
                    help="2 nominal + 2 stress seeds (smoke); NOT a valid gate run")
    args = ap.parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.quick:
        global N_SEEDS_NOMINAL, N_SEEDS_STRESS
        N_SEEDS_NOMINAL, N_SEEDS_STRESS = 2, 2

    rungs = _load_rungs(args.rungs)
    print(f"== m9_sim_validate: {len(rungs)} rungs, profile={args.profile}, "
          f"workers={args.workers}, tag={args.tag} ==", flush=True)

    ckpt = _load_checkpoint(args.tag)        # {cell_key: result}
    jobs = []
    for rung in rungs:
        for cell in _make_cells(args.profile):
            key = _cell_key(rung["name"], cell)
            if key in ckpt:
                continue
            jobs.append((rung, cell, key))
    print(f"   {len(jobs)} cells to run "
          f"({len(ckpt)} already in checkpoint)", flush=True)

    done = 0
    t_start = time.time()
    if jobs:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_cell, rung, cell): (rung, cell, key)
                    for (rung, cell, key) in jobs}
            for fut in as_completed(futs):
                rung, cell, key = futs[fut]
                try:
                    r = fut.result()
                except Exception as exc:        # log the bug, keep going
                    r = {**cell, "rung": rung["name"], "byte_exact": None,
                         "error": f"{type(exc).__name__}: {exc}"}
                ckpt[key] = r
                done += 1
                if done % 10 == 0 or "error" in r:
                    _checkpoint_path(args.tag).write_text(json.dumps(ckpt, default=float))
                bx = r.get("byte_exact")
                mark = "Y" if bx else ("n" if bx is not None else "ERR")
                print(f"  [{done:4d}/{len(jobs)}] {r['rung']:24s} "
                      f"{r['cell']:24s} s{r['seed']} {mark} "
                      f"ber={r.get('byte_error_rate', float('nan')):.4f} "
                      f"cw={r.get('cw_failed', '?')}/{r.get('n_codewords', '?')} "
                      f"({r.get('wall_s', '?')}s)", flush=True)
        _checkpoint_path(args.tag).write_text(json.dumps(ckpt, default=float))

    # ---- adjudicate ----
    verdicts = []
    for rung in rungs:
        cells = [v for k, v in ckpt.items() if k.startswith(rung["name"] + "|")]
        verdicts.append(adjudicate(rung, cells))

    summary = {
        "tape": "master9",
        "channel_nominal": f"sim_v2.channel_v2(profile='{args.profile}', aac=False, "
                           f"diffuse_gain={NOMINAL_DG})",
        "gates": "MASTER9_PLAN s4.2 (FROZEN): 5-gate SHIP, HOLD, REJECT",
        "n_seeds_nominal": N_SEEDS_NOMINAL, "n_seeds_stress": N_SEEDS_STRESS,
        "hf_flutter_ship_us": HF_FLUTTER_SHIP_US,
        "verdicts": verdicts,
        "wall_min": round((time.time() - t_start) / 60, 1),
    }
    out_path = RESULTS_DIR / f"m9_sim_validate_{args.tag}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=float))
    _print_verdicts(verdicts)
    print(f"\n  wrote {out_path}", flush=True)


def _print_verdicts(verdicts):
    print("\n==== master9 PRE-REGISTERED GATE VERDICTS ====", flush=True)
    print(f"  {'rung':<24} {'net':>5} {'g1':>5} {'g2':>5} {'g3':>4} {'g4':>4} "
          f"{'g5(ber/cap)':>14} {'verdict':>8}")
    for v in verdicts:
        g1 = f"{v['gate1_nominal']['ne']}/{v['gate1_nominal']['n']}"
        g2 = f"{v['gate2_dg065']['ne']}/{v['gate2_dg065']['n']}"
        g3 = f"{v['gate3_hf12us']['ne']}/{v['gate3_hf12us']['n']}"
        g4 = f"{v['gate4_combo']['ne']}/{v['gate4_combo']['n']}"
        g5 = f"{v['gate5_byte_floor']['mean_byte_err_rate']:.3f}/{v['gate5_byte_floor']['cap']:.3f}"
        print(f"  {v['rung']:<24} {v['net_bps'] or 0:5.0f} {g1:>5} {g2:>5} "
              f"{g3:>4} {g4:>4} {g5:>14} {v['verdict_final']:>8}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
