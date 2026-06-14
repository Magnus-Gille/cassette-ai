"""modems_ofdm.py — OFDM modem ladder for the physical-tape test (frozen interface).

Reuses the OFDM engine from experiments/capacity/c4_ofdm_bitload.py:
  short FFT (N=256) + cyclic prefix, Gray-QAM, dense pilots, wide acquisition
  + incremental per-symbol timing tracking with a frequency-domain residual-slope
  correction. That tracker is what keeps the window locked through wow/flutter.

Frozen interface (see project spec):
    SR = 48000
    CONFIGS = {...}                                  # robust -> aggressive
    modulate(payload: bytes, config: str) -> np.float32[]   # chirp preamble + framed symbols, peak 0.70
    demodulate(audio: np.float32[], config: str) -> bytes | None

Canonical frame (identical in all modems):
    MAGIC=b"CA" + >H len + payload + >I zlib.crc32(payload)

Configs (robust -> aggressive):
    c4_bpsk      : uniform BPSK on all data subcarriers, with a 3x repetition
                   inner code (majority vote) for robustness on the harsh real loop.
    c4_qpsk      : uniform QPSK on all data subcarriers (no inner repetition).
    c4_realmodel : per-subcarrier bit-loading from the REAL measured deck profile
                   (experiments/dpd/channel_model.json snr_freq/snr_db) via a gap
                   approximation; weak/null subcarriers -> 0 bits.
    c4_simloaded : the SIM-trained loading (channel-probe through cs.full_chain on
                   calibration seeds), i.e. the explicit sim->real TRANSFER test.
                   It may well fail on the real null structure (documented).
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys
import zlib

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc          # noqa: E402

SR = 48_000
FS = SR

# --- OFDM framing (copied from c4_ofdm_bitload) ---------------------------
N_FFT = 256             # spacing = 187.5 Hz, symbol ~5.3 ms (flutter-robust)
N_CP = 32               # ~0.67 ms cyclic prefix
N_SYM = N_FFT + N_CP

F_LOW = 500.0
F_HIGH = 10_300.0
SC_LOW = int(np.ceil(F_LOW * N_FFT / FS))
SC_HIGH = int(np.floor(F_HIGH * N_FFT / FS))
ALL_SC = np.arange(SC_LOW, SC_HIGH + 1)

PILOT_SPACING = 4
PILOT_INDICES = np.array([sc for sc in ALL_SC if (sc - SC_LOW) % PILOT_SPACING == 2])
DATA_INDICES = np.array([sc for sc in ALL_SC if sc not in set(PILOT_INDICES)])
PILOT_AMP = 1.5

N_REF_SYMS = 4
ACQ_SEARCH = 60
TIMING_SEARCH = 4
_K = np.arange(N_FFT)

PEAK = 0.70

# --- subcarrier centre frequencies (for real-model loading) ---------------
DATA_FREQS = DATA_INDICES * FS / N_FFT


# --- Gray-mapped QAM constellations (copied from c4) ----------------------
def _gray_qam(bps: int) -> np.ndarray:
    if bps == 1:
        return np.array([-1.0 + 0j, 1.0 + 0j])
    if bps == 2:
        return np.array([-1 - 1j, -1 + 1j, 1 - 1j, 1 + 1j]) / np.sqrt(2)
    side = int(round(np.sqrt(2 ** bps)))
    half = bps // 2
    gray = [i ^ (i >> 1) for i in range(side)]
    levels = np.arange(-(side - 1), side, 2, dtype=float)
    pos_for_gray = {g: levels[k] for k, g in enumerate(gray)}
    pts = np.zeros(2 ** bps, dtype=complex)
    for sym in range(2 ** bps):
        gi = sym >> half
        gq = sym & ((1 << half) - 1)
        pts[sym] = pos_for_gray[gi] + 1j * pos_for_gray[gq]
    return pts / np.sqrt(np.mean(np.abs(pts) ** 2))


CONST = {b: _gray_qam(b) for b in (1, 2, 4, 6)}
BITPAT = {
    b: np.array([[(idx >> (b - 1 - j)) & 1 for j in range(b)] for idx in range(2 ** b)],
                dtype=np.uint8)
    for b in (1, 2, 4, 6)
}


def _osym(fd: np.ndarray) -> np.ndarray:
    x = np.fft.ifft(fd, n=N_FFT)
    return np.concatenate([x[-N_CP:], x]).real.astype(np.float64)


_rng_ref = np.random.default_rng(777)
REF_SYM = (2 * _rng_ref.integers(0, 2, size=len(ALL_SC)) - 1).astype(float)
PILOT_PATTERN = np.ones(len(PILOT_INDICES))


def _ref_fd() -> np.ndarray:
    fd = np.zeros(N_FFT, dtype=complex)
    fd[ALL_SC] = REF_SYM * PILOT_AMP
    return fd


def _peak_normalize(audio: np.ndarray, peak: float = PEAK) -> np.ndarray:
    pk = float(np.max(np.abs(audio))) if audio.size else 0.0
    if pk > 1e-9:
        audio = audio * (peak / pk)
    return audio.astype(np.float32)


# =========================================================================
# Tracked per-symbol demod (copied from c4_ofdm_bitload).
# =========================================================================
def _lock_score(fd_rx: np.ndarray):
    Hp = fd_rx[PILOT_INDICES] / (PILOT_PATTERN * PILOT_AMP)
    ph = np.unwrap(np.angle(Hp))
    slope = np.polyfit(PILOT_INDICES, ph, 1)[0]
    res = np.std(ph - (slope * PILOT_INDICES + np.mean(ph - slope * PILOT_INDICES)))
    score = float(np.sum(np.abs(Hp))) / (1.0 + 5.0 * res)
    return score, slope


def _track_demod(rx: np.ndarray, n_syms: int | None = None):
    """Walk the data symbols with timing tracking. Returns list of (eq_data, good)."""
    pos0 = N_REF_SYMS * N_SYM

    best = None
    for off in range(-ACQ_SEARCH, ACQ_SEARCH + 1):
        seg = rx[pos0 + off:pos0 + off + N_SYM]
        if len(seg) < N_SYM:
            continue
        fd_rx = np.fft.fft(seg[N_CP:N_CP + N_FFT])
        score, _ = _lock_score(fd_rx)
        if best is None or score > best[0]:
            best = (score, off)
    drift = float(best[1]) if best is not None else 0.0

    out = []
    pos = pos0
    idx = 0
    pmag_ref = None
    while pos + drift + N_SYM <= len(rx):
        base = int(round(pos + drift))
        best = None
        for d in range(-TIMING_SEARCH, TIMING_SEARCH + 1):
            seg = rx[base + d:base + d + N_SYM]
            if len(seg) < N_SYM:
                break
            fd_rx = np.fft.fft(seg[N_CP:N_CP + N_FFT])
            score, slope = _lock_score(fd_rx)
            if best is None or score > best[0]:
                best = (score, d, fd_rx, slope)
        if best is None:
            break
        _, d, fd_rx, slope = best
        fd_rx = fd_rx * np.exp(-1j * slope * _K)
        Hp = fd_rx[PILOT_INDICES] / (PILOT_PATTERN * PILOT_AMP)
        H = (np.interp(DATA_INDICES, PILOT_INDICES, Hp.real)
             + 1j * np.interp(DATA_INDICES, PILOT_INDICES, Hp.imag))
        H = np.where(np.abs(H) > 1e-6, H, 1e-6)
        eq = fd_rx[DATA_INDICES] / H
        pmag = np.abs(Hp)
        med = float(np.median(pmag))
        if pmag_ref is None:
            pmag_ref = med
        ph = np.unwrap(np.angle(Hp))
        sl = np.polyfit(PILOT_INDICES, ph, 1)[0]
        ph_res = float(np.std(ph - (sl * PILOT_INDICES
                                    + np.mean(ph - sl * PILOT_INDICES))))
        good = (med > 0.45 * pmag_ref) and (ph_res < 0.55)
        if good:
            pmag_ref = 0.9 * pmag_ref + 0.1 * med
        out.append((eq, good))
        drift += d
        pos += N_SYM
        idx += 1
        if n_syms is not None and idx >= n_syms:
            break
    return out


# =========================================================================
# Bit-loading tables (one per config) -> ACTIVE subcarrier set + bps.
# =========================================================================
_CHANNEL_MODEL_PATH = ROOT / "experiments" / "dpd" / "channel_model.json"


def _bit_loading_from_snr(snr_db: np.ndarray, gap_db: float, max_bps: int) -> np.ndarray:
    gamma = 10 ** (gap_db / 10.0)
    snr_lin = 10 ** (snr_db / 10.0)
    b = np.log2(1.0 + snr_lin / gamma)
    out = np.zeros(len(b), dtype=int)
    out[b >= 1.0] = 1
    out[b >= 2.3] = 2
    out[b >= 4.3] = 4
    out[b >= 6.3] = 6
    return np.minimum(out, max_bps)


def _real_model_loading(gap_db: float = 6.0, max_bps: int = 4) -> np.ndarray:
    """Per-subcarrier bit-load from the REAL measured deck profile.

    Interpolate the measured snr_db(freq) onto our data-subcarrier frequencies,
    then gap-approximate. Weak/null carriers -> 0 bits. The real profile is
    centred near 0 dB median, so a small gap is used; most carriers load BPSK at
    best, many drop to 0 -> this is the honest real-measurement loading.
    """
    d = json.load(open(_CHANNEL_MODEL_PATH))
    sf = np.asarray(d["snr_freq"], dtype=float)
    sd = np.asarray(d["snr_db"], dtype=float)
    snr_at_sc = np.interp(DATA_FREQS, sf, sd)
    return _bit_loading_from_snr(snr_at_sc, gap_db=gap_db, max_bps=max_bps)


# --- SIM-trained loading: probe the standard sim channel on calibration seeds.
def _probe_sim_snr(cal_seeds=range(40, 48), n_probe_syms: int = 50) -> np.ndarray:
    import capture_scenarios as cs  # noqa: E402
    rng = np.random.default_rng(12345)
    qpsk = CONST[2]
    known_idx = rng.integers(0, 4, size=(n_probe_syms, len(DATA_INDICES)))
    tx_data = qpsk[known_idx]

    pre = hc.make_preamble(0.25)
    ref_td = [_osym(_ref_fd()) for _ in range(N_REF_SYMS)]
    data_td = []
    for s in range(n_probe_syms):
        fd = np.zeros(N_FFT, dtype=complex)
        fd[DATA_INDICES] = tx_data[s]
        fd[PILOT_INDICES] = PILOT_PATTERN * PILOT_AMP
        data_td.append(_osym(fd))
    audio = _peak_normalize(np.concatenate(
        [pre, np.concatenate(ref_td), np.concatenate(data_td), np.zeros(int(0.05 * FS))]))

    err = np.zeros(len(DATA_INDICES))
    sig = np.zeros(len(DATA_INDICES))
    for seed in cal_seeds:
        rx_audio, sr, _ = cs.full_chain(audio, "normal", "usb_soundcard", seed=seed)
        start = hc.find_preamble(rx_audio, 0.25)
        rx = np.asarray(rx_audio, dtype=np.float64)[start:]
        syms = _track_demod(rx, n_syms=n_probe_syms)
        for s, (eq, good) in enumerate(syms):
            if not good:
                continue
            ref0 = tx_data[s]
            alpha = np.vdot(ref0, eq) / np.vdot(ref0, ref0)
            eq2 = eq / alpha
            err += np.abs(eq2 - ref0) ** 2
            sig += np.abs(ref0) ** 2
    snr_lin = sig / np.maximum(err, 1e-12)
    return 10.0 * np.log10(np.maximum(snr_lin, 1e-9))


# --- Loading-table cache (lazy: sim probe only built when first needed) ----
_LOADING_CACHE: dict[str, np.ndarray] = {}


def _uniform_loading(bps: int) -> np.ndarray:
    return np.full(len(DATA_INDICES), bps, dtype=int)


def _get_loading(config: str) -> np.ndarray:
    if config in _LOADING_CACHE:
        return _LOADING_CACHE[config]
    if config == "c4_bpsk":
        load = _uniform_loading(1)
        load[DATA_FREQS > _BPSK_FMAX] = 0  # drop the unreliable high band
    elif config == "c4_qpsk":
        load = _uniform_loading(2)
    elif config == "c4_realmodel":
        load = _real_model_loading(gap_db=6.0, max_bps=4)
    elif config == "c4_simloaded":
        load = _bit_loading_from_snr(_probe_sim_snr(), gap_db=9.0, max_bps=4)
    else:
        raise ValueError(f"unknown config {config!r}")
    _LOADING_CACHE[config] = load
    return load


# c4_bpsk uses a 5x repetition inner code (majority vote) + a frequency
# interleaver so the repeated copies land on different subcarriers/symbols.
# The worn deck kills the top subcarriers (9-10 kHz) in a CORRELATED way, so
# without interleaving all copies of a bit would hit the same dead carrier and
# repetition would not help; the interleaver buys the needed frequency diversity.
_REP = {"c4_bpsk": 7, "c4_qpsk": 1, "c4_realmodel": 1, "c4_simloaded": 1}
# Interleave the emitted bit stream (all configs) with a prime-stride permutation
# so burst/selective errors are spread before they reach the repetition/CRC.
_INTERLEAVE = {"c4_bpsk": True, "c4_qpsk": False,
               "c4_realmodel": False, "c4_simloaded": False}
# c4_bpsk (robust anchor) additionally restricts to the reliable sub-band:
# above ~7.6 kHz the worn deck (+ global resample residual) hits a ~50% BER wall,
# so those carriers are dropped. The rest see a ~10% raw BER floor that the 7x
# repetition + interleave knocks down enough for the frame CRC to pass.
_BPSK_FMAX = 7600.0

CONFIGS = {
    "c4_bpsk":      {"loading": "uniform-bpsk<=7.6kHz", "rep": 7, "interleave": True,
                     "desc": "robust anchor: BPSK on <=7.6 kHz + 7x repetition + freq interleave"},
    "c4_qpsk":      {"loading": "uniform-qpsk", "rep": 1, "interleave": False,
                     "desc": "uniform QPSK on all data subcarriers"},
    "c4_realmodel": {"loading": "real-deck-bitload", "rep": 1, "interleave": False,
                     "desc": "per-SC bit-load from real channel_model.json (gap-approx)"},
    "c4_simloaded": {"loading": "sim-trained-bitload", "rep": 1, "interleave": False,
                     "desc": "sim-trained loading (explicit sim->real transfer test)"},
}


def _block_perm(n: int) -> np.ndarray:
    """Deterministic prime-stride permutation of range(n); invertible via argsort.
    Spreads adjacent bits far apart so a frequency-selective fade that wipes out
    a contiguous block of subcarriers hits DE-CORRELATED interleaved positions."""
    import math
    if n <= 1:
        return np.arange(n)
    stride = 97
    while math.gcd(stride, n) != 1:
        stride += 1
    return (np.arange(n) * stride) % n


def _interleave(bits: np.ndarray, bits_per_sym: int) -> np.ndarray:
    """Block-interleave `bits` in fixed blocks spanning INTERLEAVE_SYMS OFDM
    symbols. The block size depends only on the config (bits_per_sym), not on
    payload length, so demod can invert it without side information. A trailing
    partial block (< block size) is left in place."""
    block = bits_per_sym * INTERLEAVE_SYMS
    out = bits.copy()
    perm = _block_perm(block)
    nfull = len(bits) // block
    for b in range(nfull):
        seg = bits[b * block:(b + 1) * block]
        out[b * block:(b + 1) * block] = seg[perm]
    return out


def _deinterleave(bits: np.ndarray, bits_per_sym: int) -> np.ndarray:
    block = bits_per_sym * INTERLEAVE_SYMS
    out = bits.copy()
    perm = _block_perm(block)
    inv = np.argsort(perm)
    nfull = len(bits) // block
    for b in range(nfull):
        seg = bits[b * block:(b + 1) * block]
        out[b * block:(b + 1) * block] = seg[inv]
    return out


INTERLEAVE_SYMS = 8  # block spans 8 OFDM symbols (~42 ms) of frequency diversity


def _active(config: str):
    load = _get_loading(config)
    mask = load > 0
    return DATA_INDICES[mask], load[mask], mask


def _bits_per_sym(config: str) -> int:
    _, bps, _ = _active(config)
    return int(np.sum(bps))


# =========================================================================
# Frame helpers (canonical)
# =========================================================================
MAGIC = b"CA"


def _frame(payload: bytes) -> bytes:
    return MAGIC + struct.pack(">H", len(payload)) + payload + struct.pack(">I", zlib.crc32(payload))


def _bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")


def _bits_to_bytes(bits: np.ndarray) -> bytes:
    usable = len(bits) - (len(bits) % 8)
    if usable <= 0:
        return b""
    return np.packbits(np.asarray(bits[:usable], dtype=np.uint8), bitorder="big").tobytes()


def _unframe(data: bytes) -> bytes | None:
    if len(data) < 8 or data[:2] != MAGIC:
        return None
    (L,) = struct.unpack(">H", data[2:4])
    end = 4 + L
    if len(data) < end + 4:
        return None
    payload = data[4:end]
    (crc,) = struct.unpack(">I", data[end:end + 4])
    if zlib.crc32(payload) != crc:
        return None
    return payload


# =========================================================================
# Shared bit-stream builder (feeds both tx_bits and modulate)
# =========================================================================
def _build_bit_grid(payload: bytes, config: str):
    """Return (bit_grid, n_syms, bits_per_sym) — the exact bit array fed to the
    symbol mapper, after frame packing, repetition, zero-padding and interleaving.
    Shared by tx_bits() and modulate() so they cannot drift apart.
    """
    active_sc, active_bps, _ = _active(config)
    bits_per_sym = int(np.sum(active_bps))
    rep = _REP[config]

    frame_bits = _bytes_to_bits(_frame(payload))
    if rep > 1:
        frame_bits = np.repeat(frame_bits, rep)

    total = len(frame_bits)
    n_syms = max(1, int(np.ceil(total / bits_per_sym)))
    if _INTERLEAVE[config]:
        n_syms = int(np.ceil(n_syms / INTERLEAVE_SYMS) * INTERLEAVE_SYMS)
    grid = n_syms * bits_per_sym
    bit_grid = np.zeros(grid, dtype=np.uint8)
    bit_grid[:total] = frame_bits
    if _INTERLEAVE[config]:
        bit_grid = _interleave(bit_grid, bits_per_sym)
    return bit_grid, n_syms, bits_per_sym


def tx_bits(payload: bytes, config: str) -> np.ndarray:
    """Return the ground-truth transmitted bit stream for payload+config.

    This is the EXACT bit array fed to the OFDM symbol mapper: canonical frame
    bits, repetition-expanded, zero-padded to whole symbols, and interleaved
    (for configs that use interleaving). Returned as uint8.
    """
    if config not in CONFIGS:
        raise ValueError(f"unknown config {config!r}")
    bit_grid, _, _ = _build_bit_grid(payload, config)
    return bit_grid


def _decode_bits_raw(audio: np.ndarray, config: str) -> np.ndarray:
    """Return raw symbol-mapper output bits without deinterleave/vote/CRC.

    Uses the SAME sync + equalize path as demodulate() / _decode_bits(), but
    returns the flat bit stream directly out of the symbol decisions — i.e. at
    the same layer as tx_bits(). Never raises; returns empty array on failure.
    """
    try:
        audio = np.asarray(audio, dtype=np.float64)
        start = hc.find_preamble(audio, 0.25)
        if start >= len(audio) - (N_REF_SYMS + 1) * N_SYM:
            return np.zeros(0, dtype=np.uint8)
        rx = audio[start:]
        syms = _track_demod(rx)
        if not syms:
            return np.zeros(0, dtype=np.uint8)
        active_sc, active_bps, mask = _active(config)
        out_bits = []
        for eq, _good in syms:
            eq_active = eq[mask]
            for k, bps in enumerate(active_bps):
                const = CONST[bps]
                idx = int(np.argmin(np.abs(eq_active[k] - const) ** 2))
                out_bits.append(BITPAT[bps][idx])
        if not out_bits:
            return np.zeros(0, dtype=np.uint8)
        return np.concatenate(out_bits).astype(np.uint8)
    except Exception:
        return np.zeros(0, dtype=np.uint8)


def rx_bits(audio: np.ndarray, config: str) -> np.ndarray:
    """Best-effort recovered bit stream from audio (same layer as tx_bits).

    Returns the flat bit array from symbol decisions, at the SAME layer as
    tx_bits() — i.e. after repetition/interleaving on tx, but BEFORE
    deinterleaving and majority-vote on rx. This is the correct layer for
    computing raw BER vs tx_bits(). Never returns None.
    """
    if config not in CONFIGS:
        raise ValueError(f"unknown config {config!r}")
    return _decode_bits_raw(audio, config)


# =========================================================================
# Modulator
# =========================================================================
def modulate(payload: bytes, config: str) -> np.ndarray:
    if config not in CONFIGS:
        raise ValueError(f"unknown config {config!r}")
    active_sc, active_bps, _ = _active(config)

    bit_grid, n_syms, bits_per_sym = _build_bit_grid(payload, config)
    grid = len(bit_grid)

    pre = hc.make_preamble(0.25)
    ref_td = [_osym(_ref_fd()) for _ in range(N_REF_SYMS)]

    data_td = []
    bi = 0
    for _ in range(n_syms):
        fd = np.zeros(N_FFT, dtype=complex)
        for sc, bps in zip(active_sc, active_bps):
            idx = 0
            for _k in range(bps):
                bit = int(bit_grid[bi]) if bi < grid else 0
                bi += 1
                idx = (idx << 1) | bit
            fd[sc] = CONST[bps][idx]
        fd[PILOT_INDICES] = PILOT_PATTERN * PILOT_AMP
        data_td.append(_osym(fd))

    audio = np.concatenate([pre, np.concatenate(ref_td), np.concatenate(data_td),
                            np.zeros(int(0.05 * FS))])
    return _peak_normalize(audio)


# =========================================================================
# Demodulator
# =========================================================================
def _decode_bits(audio: np.ndarray, config: str) -> np.ndarray | None:
    audio = np.asarray(audio, dtype=np.float64)
    start = hc.find_preamble(audio, 0.25)
    if start >= len(audio) - (N_REF_SYMS + 1) * N_SYM:
        return None
    rx = audio[start:]
    syms = _track_demod(rx)
    if not syms:
        return None

    active_sc, active_bps, mask = _active(config)
    out_bits = []
    for eq, _good in syms:
        eq_active = eq[mask]
        for k, bps in enumerate(active_bps):
            const = CONST[bps]
            idx = int(np.argmin(np.abs(eq_active[k] - const) ** 2))
            out_bits.append(BITPAT[bps][idx])
    if not out_bits:
        return None
    return np.concatenate(out_bits).astype(np.uint8)


def demodulate(audio: np.ndarray, config: str) -> bytes | None:
    if config not in CONFIGS:
        raise ValueError(f"unknown config {config!r}")
    try:
        bits = _decode_bits(audio, config)
    except Exception:
        return None
    if bits is None:
        return None

    if _INTERLEAVE[config]:
        bps_sym = _bits_per_sym(config)
        ntrim = (len(bits) // bps_sym) * bps_sym
        bits = _deinterleave(bits[:ntrim], bps_sym)

    rep = _REP[config]
    if rep > 1:
        n = (len(bits) // rep) * rep
        if n == 0:
            return None
        votes = bits[:n].reshape(-1, rep).sum(axis=1)
        bits = (votes > (rep // 2)).astype(np.uint8)

    data = _bits_to_bytes(bits)
    return _unframe(data)


# =========================================================================
# Self-test
# =========================================================================
def _resample_to_nominal(audio: np.ndarray, speed_offset: float) -> np.ndarray:
    """Mimic the analyzer's global speed normalisation: undo the deck speed
    offset by resampling back toward nominal. The real analyzer ESTIMATES this
    ratio; here we apply the (approximately) inverse ratio and leave residual
    drift for the per-symbol tracker to absorb."""
    if abs(speed_offset) < 1e-6:
        return audio
    from fractions import Fraction
    from scipy.signal import resample_poly as _rp
    # full_chain applied ratio = 1+speed_offset; undo with the inverse.
    inv = 1.0 / (1.0 + float(speed_offset))
    frac = Fraction(inv).limit_denominator(4000)
    return _rp(np.asarray(audio, dtype=np.float64), frac.numerator, frac.denominator)


def _gross_bps(config: str, payload_len: int = 96) -> float:
    audio = modulate(bytes(payload_len), config)
    frame_len = payload_len + 8
    return float(frame_len * 8) / (len(audio) / FS)


def _run_selftest(n_seeds: int = 8, payload_len: int = 96):
    import capture_scenarios as cs  # noqa: E402
    rng = np.random.default_rng(2024)

    rows = []
    clean_all_ok = True
    for config in CONFIGS:
        # (1) clean byte-exact round trip
        payload = bytes(rng.integers(0, 256, size=payload_len, dtype=np.uint8).tolist())
        clean = demodulate(modulate(payload, config), config)
        clean_ok = (clean == payload)
        clean_all_ok = clean_all_ok and clean_ok

        # (2) normal + (3) worn passrates
        n_norm = 0
        n_worn = 0
        for s in range(n_seeds):
            pl = bytes(rng.integers(0, 256, size=payload_len, dtype=np.uint8).tolist())
            audio = modulate(pl, config)

            rx, sr, _ = cs.full_chain(audio, "normal", "usb_soundcard",
                                      speed_offset=0.0, seed=s)
            if demodulate(np.asarray(rx, dtype=np.float64), config) == pl:
                n_norm += 1

            rx2, sr2, _ = cs.full_chain(audio, "worn", "usb_soundcard",
                                        speed_offset=-0.12, seed=s)
            rx2n = _resample_to_nominal(np.asarray(rx2, dtype=np.float64), -0.12)
            if demodulate(rx2n, config) == pl:
                n_worn += 1

        rows.append({
            "config": config,
            "gross_bps": round(_gross_bps(config, payload_len), 2),
            "clean_ok": bool(clean_ok),
            "normal_passrate": round(n_norm / n_seeds, 3),
            "worn_passrate": round(n_worn / n_seeds, 3),
        })
        r = rows[-1]
        print(f"[{config:13s}] clean={'OK' if r['clean_ok'] else 'FAIL'} "
              f"gross={r['gross_bps']:7.1f} bps  normal={r['normal_passrate']:.3f} "
              f"worn={r['worn_passrate']:.3f}")
    print(f"[clean_roundtrip_all_ok] {clean_all_ok}")
    return rows, clean_all_ok


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--payload", type=int, default=96)
    args = ap.parse_args()

    # tx_bits / rx_bits alignment check (clean round-trip, hamming must be 0)
    print("\n[tx/rx bit alignment check (no channel)]")
    import numpy as _np_check
    _rng_chk = _np_check.random.default_rng(42)
    _test_pl = bytes(_rng_chk.integers(0, 256, size=args.payload, dtype=_np_check.uint8).tolist())
    _all_bits_ok = True
    for _cfg in CONFIGS:
        _tb = tx_bits(_test_pl, _cfg)
        _audio = modulate(_test_pl, _cfg)
        _rb = rx_bits(_audio, _cfg)
        _n = len(_tb)
        if len(_rb) < _n:
            _rb = _np_check.concatenate([_rb, _np_check.zeros(_n - len(_rb), dtype=_np_check.uint8)])
        else:
            _rb = _rb[:_n]
        _hamming = int(_np_check.count_nonzero(_tb != _rb))
        _ok = _hamming == 0
        _all_bits_ok = _all_bits_ok and _ok
        print(f"  {_cfg}: hamming={_hamming}  {'OK' if _ok else 'FAIL — alignment wrong!'}")
    if not _all_bits_ok:
        print("  ERROR: tx_bits/rx_bits alignment failed")
        import sys as _sys_chk
        _sys_chk.exit(1)

    rows, ok = _run_selftest(args.seeds, args.payload)
    print(json.dumps({"clean_roundtrip_ok": ok, "rows": rows}, indent=2))
