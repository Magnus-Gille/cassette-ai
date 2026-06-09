"""h4_dqpsk.py — HYPOTHESIS H4: differential QPSK on wide-spaced carriers.

P parallel CONTINUOUS-PHASE carriers (plus 1 unmodulated pilot) at the proven
>=562 Hz spacing, each carrying DQPSK: 2 bits/carrier/symbol encoded as a
phase increment SYMBOL-TO-SYMBOL on the SAME carrier, so static channel phase
(reverb IR, EQ, AAC) cancels to first order.  Carrier-phase reference comes
from the carriers themselves (window complex DFT per symbol on an ABSOLUTE
sample-time basis), never from genie timing.

Achievable demod:
  - frame sync: hc.find_preamble (same chirp preamble as the WS schemes)
  - per symbol: Hann-windowed complex DFT at each carrier over the symbol
    window (skipping `skip` boundary samples to dodge the short adj-ISI tail),
    exponent referenced to ABSOLUTE window-sample index so integer window
    re-centering is phase-transparent (f_k * N / FS is an integer).
  - pilot carrier (unmodulated, mid-band): its differential phase measures the
    common timing change dtau between consecutive symbols -> corrects every
    data carrier by 2*pi*f_k*dtau and drives an integer window drift tracker.
  - optional one-shot decision-directed refinement of dtau (LS slope of
    post-decision phase residuals vs carrier frequency), then re-decide.

Payload pipeline: m3_codec interleaved RS(255,k) frames (m5-style), 8 KB
slices of stories260K_int4.cass, per-frame preamble, 0.12 s frame gaps.

Channel: sim_v2.channel_v2(profile='tape7', aac=True, seed_offset=seed) — one
pass per (rung, seed) over the rung's whole multi-frame section.

Stages (see --stage):
  sanity   no-channel demod (must be BER 0) + channel_v2(aac=False, snr=45)
  control  PROVEN WS_M16_K1_sp3_N256 @ RS(255,191) through THIS harness,
           seeds {0,1}: expected byte-exact seed0, marginal/fail seed1.
  full     all DQPSK rungs x seeds {0,1,2}
  all      sanity -> control -> full, write results/h4_dqpsk_results.json

Truth (the payload slice) is used ONLY for scoring (raw BER, per-carrier SER,
byte-exact), never inside the demod.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                          # noqa: E402
import m3_codec as codec                         # noqa: E402
from m3_codec import Rung                        # noqa: E402
import real_channel_sim as rcs                   # noqa: E402
import sim_v2                                    # noqa: E402
from assault_widespace import (                  # noqa: E402
    build as ws_build, _demod_frame_achievable, eq_for,
)

FS = 48_000
RESULTS = _HERE / "results"
CASS = codec.CASS
BASELINE_NET_BPS = 561.8

LEAD_S = 0.5
TAIL_S = 0.5
FRAME_GAP_S = 0.12
PAD_LO_S = 0.30      # window pad before nominal frame start (preamble search)
PAD_HI_S = 0.05      # window pad after nominal frame end (timing wander)

GRAY_ENC = {(0, 0): 0, (0, 1): 1, (1, 1): 2, (1, 0): 3}   # quadrant index q -> dphi = q*pi/2
GRAY_DEC = {v: k for k, v in GRAY_ENC.items()}


# ===========================================================================
# DQPSK scheme
# ===========================================================================
class DQPSKScheme:
    """P data carriers + 1 mid-band pilot, continuous phase across the frame.

    Carriers sit on integer FFT bins of N (bin = FS/N Hz), `spacing` bins apart
    (>=562.5 Hz physical), starting at 750 Hz — deliberately in the strong
    low-mid band (HF rolloff is the enemy; with few carriers we don't need it).
    """

    def __init__(self, P: int, N: int, spacing: int, skip: int | None = None):
        if skip is None:
            skip = N // 8                      # 32 @ N=256, 64 @ N=512
        self.P, self.N, self.spacing, self.skip = P, N, spacing, skip
        df = FS / N
        b0 = int(round(750.0 / df))
        nc = P + 1
        bins = b0 + spacing * np.arange(nc)
        freqs = bins * df
        assert freqs[-1] <= 9500.0, f"top carrier {freqs[-1]:.0f} Hz > 9500"
        assert spacing * df >= 562.0, f"spacing {spacing*df:.0f} Hz < 562"
        self.bins = bins.astype(int)
        self.freqs = freqs.astype(np.float64)
        self.pilot_idx = nc // 2
        self.data_idx = np.array([i for i in range(nc) if i != self.pilot_idx])
        self.bits_per_sym = 2 * P
        self._preamble = hc.make_preamble(0.25).astype(np.float64)
        self.preamble_seconds = 0.25
        self.name = f"DQ_P{P}_N{N}_sp{spacing}"
        self.gross_bps = self.bits_per_sym / (N / FS)
        # demod window — Nw MUST keep the carriers orthogonal:
        # (spacing * df) * Nw / FS = spacing * Nw / N must be an integer, so
        # strong low carriers do not leak into weak (rolled-off) high carriers.
        self.Nw = N - 2 * skip
        assert (spacing * self.Nw) % N == 0, (
            f"carriers not orthogonal over analysis window: "
            f"spacing={spacing} Nw={self.Nw} N={N}")
        self._win = np.hanning(self.Nw)
        # TX pre-emphasis from the PUBLISHED sounder H(f) curve (master3) — the
        # same measured curve the proven WS RX-EQ uses; no genie. Equalizes the
        # RECEIVED carrier amplitudes so residual window leakage is symmetric.
        params = rcs.load_params()
        Hf = params["Hf_magnitude"]
        fm = np.asarray(Hf["sounder_freqs_master3"], float)
        Hd = np.asarray(Hf["H_db_master3"], float)
        Hl = 10.0 ** (np.interp(self.freqs, fm, Hd) / 20.0)
        Hl = Hl / (Hl.max() + 1e-12)
        self.tx_amp = 1.0 / np.clip(Hl, 0.05, None)
        self.tx_amp = self.tx_amp / self.tx_amp.max()

    # ---- modulate one frame ------------------------------------------------
    def nsym_data(self, nbits: int) -> int:
        return int(math.ceil(nbits / self.bits_per_sym))

    def bits_to_quadrants(self, bits: np.ndarray) -> np.ndarray:
        """Frame bits -> (nd, P) quadrant indices, CARRIER-BLOCK mapping:
        data carrier j carries the j-th contiguous 2*nd-bit block of the frame.
        A faded/dead carrier then corrupts a contiguous 1/P slice of the
        frame's bytes (RS-friendly error concentration) instead of sprinkling
        2 bad bits into every symbol's bytes."""
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        nd = len(bits) // bps
        bm = bits.reshape(self.P, nd, 2)              # carrier-major blocks
        q = np.zeros((nd, self.P), int)
        for (a, b), qq in GRAY_ENC.items():
            q[((bm[:, :, 0] == a) & (bm[:, :, 1] == b)).T] = qq
        return q

    def quadrants_to_bits(self, q: np.ndarray) -> np.ndarray:
        """(nd, P) quadrants -> frame bits (inverse of bits_to_quadrants)."""
        nd = q.shape[0]
        bm = np.zeros((self.P, nd, 2), np.uint8)
        for qq, (a, b) in GRAY_DEC.items():
            m = (q == qq).T
            bm[:, :, 0][m] = a
            bm[:, :, 1][m] = b
        return bm.reshape(-1)

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        q = self.bits_to_quadrants(bits)
        nd = q.shape[0]
        total = nd + 1                       # +1 reference symbol
        nc = self.P + 1
        # phase ladder theta[i, k] (cumulative shifts; pilot stays at 0)
        theta = np.zeros((total, nc))
        for i in range(1, total):
            theta[i] = theta[i - 1]
            theta[i, self.data_idx] += q[i - 1] * (np.pi / 2.0)
        t = np.arange(total * self.N) / FS   # GLOBAL time across the frame body
        body = np.zeros(total * self.N)
        for k in range(nc):
            ph = 2 * np.pi * self.freqs[k] * t + np.repeat(theta[:, k], self.N)
            body += self.tx_amp[k] * np.sin(ph)
        audio = np.concatenate([self._preamble, body])
        pk = np.max(np.abs(audio))
        return (audio / pk * 0.70).astype(np.float32)

    # ---- achievable demod of one frame window ------------------------------
    def demod(self, win_audio: np.ndarray, nd: int, refine: bool = True):
        """Returns (bits, diag). diag has per-carrier quadrant decisions
        (nd, P) and pilot-estimated dtau trace. NO truth used."""
        y = np.asarray(win_audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), self.preamble_seconds)
        total = nd + 1
        nc = self.P + 1
        N, skip, Nw = self.N, self.skip, self.Nw
        fpil = self.freqs[self.pilot_idx]
        c = np.zeros((total, nc), np.complex128)
        dtau = np.zeros(total)               # seconds, per symbol (vs previous)
        drift = 0.0                          # samples, accumulated
        ema = 0.5                            # pilot smoothing (flutter is lowpass)
        sm = 0.0
        for i in range(total):
            base = ds + i * N + int(round(drift))
            lo = base + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS   # ABSOLUTE basis: shifts transparent
            E = np.exp(-2j * np.pi * np.outer(self.freqs, tt))
            c[i] = E @ (seg * self._win)
            if i > 0:
                dp = float(np.angle(c[i, self.pilot_idx] *
                                    np.conj(c[i - 1, self.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                # y(t)=x(t-tau): pilot dphi = -2*pi*f*dtau_chan, so the window
                # must move OPPOSITE to the measured dtau to follow the signal.
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
        # differential decisions
        fd = self.freqs[self.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])          # (nd, nc)
        dphi = np.angle(d[:, self.data_idx])       # (nd, P)
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
        if refine:
            # one-shot decision-directed common-timing refinement:
            # residual phase after removing decided quadrant ~ 2*pi*f*dtau_res
            res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            num = (res * fd[None, :]).sum(axis=1)
            den = (fd ** 2).sum()
            dtau_res = num / (2 * np.pi * den)      # (nd,)
            dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
            q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
        return self.quadrants_to_bits(q), {"quadrants": q, "dtau": dtau[1:],
                                           "preamble_at": int(ds)}


# ===========================================================================
# Section build / decode (m5-style frame train, one channel pass per section)
# ===========================================================================
def _silence(sec: float) -> np.ndarray:
    return np.zeros(int(sec * FS), np.float32)


SOUNDER_FREQS = np.round(np.geomspace(300, 11000, 64)).astype(int).tolist()
SOUNDER_DUR_S = 3.0
SOUNDER_REPS = 2


def _make_sounder():
    """m2-style Schroeder multitone sounder (2 reps). Returns (audio, spans)."""
    from make_master2 import _schroeder_multitone
    parts, spans, pos = [], [], 0
    for _ in range(SOUNDER_REPS):
        g = _silence(0.5)
        parts.append(g); pos += len(g)
        mt = _schroeder_multitone(SOUNDER_FREQS, SOUNDER_DUR_S, 0.60)
        spans.append((pos, len(mt)))
        parts.append(mt); pos += len(mt)
        g = _silence(0.5)
        parts.append(g); pos += len(g)
    return np.concatenate(parts).astype(np.float32), spans


def measure_sounder_eq(y: np.ndarray, spans, freqs_target) -> np.ndarray:
    """Per-capture H(f) from the in-section sounder (mirrors
    analyze_master2.analyze_sounder), interpolated to freqs_target ->
    normalized, clipped linear EQ. ACHIEVABLE: uses only the known probe."""
    fr = np.asarray(SOUNDER_FREQS, float)
    acc = np.zeros(len(fr))
    n_used = 0
    for st, ln in spans:
        ti = int(0.3 * FS)
        seg = np.asarray(y[st + ti: st + ln - ti], np.float64)
        if len(seg) < FS:
            continue
        win = np.hanning(len(seg))
        sp = np.abs(np.fft.rfft(seg * win))
        fax = np.fft.rfftfreq(len(seg), 1.0 / FS)
        mags = []
        for f in fr:
            lo = np.searchsorted(fax, f - 30)
            hi = max(np.searchsorted(fax, f + 30), lo + 1)
            mags.append(float(np.max(sp[lo:hi])))
        acc += np.asarray(mags)
        n_used += 1
    H = acc / max(1, n_used)
    Hn = H / (np.max(H) + 1e-12)
    H_db = 20.0 * np.log10(np.maximum(Hn, 1e-6))
    Hl = 10.0 ** (np.interp(np.asarray(freqs_target, float), fr, H_db) / 20.0)
    Hl = Hl / (Hl.max() + 1e-12)
    return np.clip(Hl, 0.05, None)


def build_section(frame_audios: list[np.ndarray], with_sounder: bool = True):
    """Returns (section, frame_starts, sounder_spans)."""
    parts, starts, pos = [], [], 0

    def add(sig):
        nonlocal pos
        parts.append(np.asarray(sig, np.float32))
        pos += len(sig)

    add(_silence(LEAD_S))
    spans = []
    if with_sounder:
        snd, spans0 = _make_sounder()
        spans = [(s + pos, ln) for s, ln in spans0]
        add(snd)
    for fa in frame_audios:
        starts.append(pos)
        add(fa)
        add(_silence(FRAME_GAP_S))
    add(_silence(TAIL_S))
    sec = np.concatenate(parts)
    pk = float(np.max(np.abs(sec)))
    return (sec / pk * 0.95).astype(np.float32), starts, spans


def nominal_frame_bits(meta: dict) -> list[int]:
    fb = meta["frame_bits"]
    n = meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


def _payload_slice(offset: int, nbytes: int = 8192) -> bytes:
    full = CASS.read_bytes()
    return full[offset: offset + nbytes]


# ---- DQPSK rung -----------------------------------------------------------
def run_dqpsk_rung(spec: dict, seed: int, *, channel: str = "v2",
                   snr_db: float | None = None) -> dict:
    """channel: 'v2' (full), 'v2_noaac_snr' (sanity rung), 'none' (no channel)."""
    t0 = time.time()
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name=spec["name"], M=spec["P"], K=1,
                rs_n=255, rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _spans = build_section(frame_audios)

    if channel == "none":
        y = section.astype(np.float64)
    elif channel == "v2_noaac_snr":
        y = sim_v2.channel_v2(section, profile="tape7", aac=False,
                              seed_offset=seed, snr_db=snr_db)
    else:
        y = sim_v2.channel_v2(section, profile="tape7", aac=True,
                              seed_offset=seed)

    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    P = sch.P
    car_err = np.zeros(P, int)
    car_tot = np.zeros(P, int)
    rx_frames = []
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi])
        flen = len(frame_audios[fi])
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(y), st + flen + pad_hi)
        bits, diag = sch.demod(y[w_lo:w_hi], nd)
        rx_frames.append(bits)
        # ---- scoring only (truth) ----
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(bits))
        raw_err += int(np.count_nonzero(tb[:m] != bits[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        tq = sch.bits_to_quadrants(tb)
        rq = diag["quadrants"][: len(tq)]
        car_err += (rq != tq[: len(rq)]).sum(axis=0)
        car_tot += len(rq)

    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == payload
    byte_err = sum(a != b for a, b in zip(recovered, payload)) + abs(
        len(recovered) - len(payload))
    net = sch.gross_bps * spec["rs_k"] / 255.0
    eff = len(payload) * 8 / (len(section) / FS)
    return {
        "rung": spec["name"], "scheme": sch.name, "seed": seed,
        "channel": channel,
        "P": P, "N": spec["N"], "spacing": spec["spacing"],
        "carrier_freqs_hz": [round(f, 1) for f in sch.freqs[sch.data_idx]],
        "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1),
        "rs_k": spec["rs_k"], "gross_bps": round(sch.gross_bps, 1),
        "net_bps": round(net, 1), "effective_bps_incl_overhead": round(eff, 1),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "section_seconds": round(len(section) / FS, 1),
        "raw_ber": raw_err / max(1, raw_tot),
        "per_carrier_ser": [round(float(e) / max(1, t), 5)
                            for e, t in zip(car_err, car_tot)],
        "rs_codewords_failed": cw_failed,
        "byte_errors": byte_err,
        "byte_exact": bool(exact),
        "wall_s": round(time.time() - t0, 1),
    }


# ---- WS control rung (the PROVEN 561.8 bps config through THIS harness) ----
def run_control_rung(seed: int) -> dict:
    t0 = time.time()
    ws = ws_build(16, 1, 3, 256)
    payload = _payload_slice(16384, 8192)            # same slice as m5/m7 rs191 rung
    rung = Rung(name="ctrl_ws_rs191", M=16, K=1, rs_n=255, rs_k=191,
                frame_bytes=510)
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [np.asarray(ws.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in tx_frames]
    section, starts, spans = build_section(frame_audios)
    y = sim_v2.channel_v2(section, profile="tape7", aac=True, seed_offset=seed)
    y = y.astype(np.float64)
    # per-capture EQ from the in-section sounder (same as m5/m7 real decodes)
    eq = measure_sounder_eq(y, spans, ws.freqs)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    rx_frames = []
    for fi, st in enumerate(starts):
        nsym = int(math.ceil(nom_bits[fi] / ws.bits_per_sym))
        flen = len(frame_audios[fi])
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(y), st + flen + pad_hi)
        rb = np.asarray(_demod_frame_achievable(ws, eq, y[w_lo:w_hi], nsym,
                                                "contrast"), np.uint8).ravel()
        rx_frames.append(rb)
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == payload
    return {
        "rung": "control_WS_M16_K1_sp3_N256_rs191", "seed": seed,
        "raw_ber": raw_err / max(1, raw_tot),
        "rs_codewords_failed": cw_failed,
        "n_codewords": meta["n_codewords"],
        "byte_exact": bool(exact),
        "net_bps": round(750.0 * 191 / 255, 1),
        "section_seconds": round(len(section) / FS, 1),
        "wall_s": round(time.time() - t0, 1),
    }


# ===========================================================================
# Rung ladder
# ===========================================================================
# spacing = 750 Hz (4 bins @ N=256, 8 bins @ N=512) — beyond the proven-safe
# 562 Hz AND exactly orthogonal over the Nw = 3N/4 analysis window.
DQ_RUNGS = [
    {"name": "dq_p6n256_rs95",  "P": 6, "N": 256, "spacing": 4, "rs_k": 95,
     "offset": 0,     "payload_bytes": 8192, "frame_bytes": 510},   # net 838
    {"name": "dq_p6n256_rs159", "P": 6, "N": 256, "spacing": 4, "rs_k": 159,
     "offset": 8192,  "payload_bytes": 8192, "frame_bytes": 510},   # net 1403
    {"name": "dq_p6n512_rs159", "P": 6, "N": 512, "spacing": 8, "rs_k": 159,
     "offset": 16384, "payload_bytes": 8192, "frame_bytes": 510},   # net 702
    {"name": "dq_p6n512_rs191", "P": 6, "N": 512, "spacing": 8, "rs_k": 191,
     "offset": 24576, "payload_bytes": 8192, "frame_bytes": 510},   # net 843
    {"name": "dq_p4n256_rs127", "P": 4, "N": 256, "spacing": 4, "rs_k": 127,
     "offset": 32768, "payload_bytes": 8192, "frame_bytes": 510},   # net 747
    {"name": "dq_p4n256_rs159", "P": 4, "N": 256, "spacing": 4, "rs_k": 159,
     "offset": 40960, "payload_bytes": 8192, "frame_bytes": 510},   # net 935
    # long-symbol hedge: reverb-tail ISI fraction collapses at N=1024
    {"name": "dq_p10n1024_rs159", "P": 10, "N": 1024, "spacing": 16, "rs_k": 159,
     "offset": 49152, "payload_bytes": 8192, "frame_bytes": 510},   # net 584
    {"name": "dq_p10n1024_rs191", "P": 10, "N": 1024, "spacing": 16, "rs_k": 191,
     "offset": 57344, "payload_bytes": 8192, "frame_bytes": 510},   # net 702
]
SEEDS = [0, 1, 2]

# Extension ladder (run after the main full stage PASSed with raw BER ~0 at
# N=1024: find the ceiling). Same protocol: achievable decoder, seeds {0,1,2}.
#  - p10n1024 rs223: thinner RS on the error-free PHY            net 819.9
#  - p12n1024 sp12 (562.5 Hz, the proven-minimum spacing): 24 b/sym
#    rs191 -> net 842.6, rs223 -> net 983.8
#  - p10n512 rs127: doubled symbol rate, 10 carriers, heavy RS   net 933.8
EXT_RUNGS = [
    {"name": "dq_p10n1024_rs223", "P": 10, "N": 1024, "spacing": 16, "rs_k": 223,
     "offset": 65536, "payload_bytes": 8192, "frame_bytes": 510},
    {"name": "dq_p12n1024_rs191", "P": 12, "N": 1024, "spacing": 12, "rs_k": 191,
     "offset": 73728, "payload_bytes": 8192, "frame_bytes": 510},
    {"name": "dq_p12n1024_rs223", "P": 12, "N": 1024, "spacing": 12, "rs_k": 223,
     "offset": 81920, "payload_bytes": 8192, "frame_bytes": 510},
    {"name": "dq_p10n512_rs127",  "P": 10, "N": 512, "spacing": 8, "rs_k": 127,
     "offset": 90112, "payload_bytes": 8192, "frame_bytes": 510},
]


def _run_dq(args):
    spec, seed, channel, snr = args
    return run_dqpsk_rung(spec, seed, channel=channel, snr_db=snr)


def stage_sanity() -> dict:
    out = {"no_channel": [], "v2_noaac_snr45": []}
    # 1) no-channel: every config must demod at BER exactly 0
    for spec in DQ_RUNGS:
        s = dict(spec, payload_bytes=2040)           # short: 4 frames
        r = run_dqpsk_rung(s, 0, channel="none")
        out["no_channel"].append({k: r[k] for k in
                                  ("rung", "raw_ber", "byte_exact")})
        print(f"  [sanity none ] {r['rung']:16s} BER={r['raw_ber']:.2e} "
              f"exact={r['byte_exact']}", flush=True)
    # 2) light channel rung: flutter+EQ+reverb, no AAC, SNR 45
    for spec in (DQ_RUNGS[0], DQ_RUNGS[2], DQ_RUNGS[6]):
        s = dict(spec, payload_bytes=2040)
        r = run_dqpsk_rung(s, 0, channel="v2_noaac_snr", snr_db=45.0)
        out["v2_noaac_snr45"].append({k: r[k] for k in
                                      ("rung", "raw_ber", "per_carrier_ser",
                                       "byte_exact")})
        print(f"  [sanity lite ] {r['rung']:16s} BER={r['raw_ber']:.4f} "
              f"SER={r['per_carrier_ser']} exact={r['byte_exact']}", flush=True)
    return out


def stage_control() -> list[dict]:
    rows = []
    for seed in (0, 1):
        r = run_control_rung(seed)
        rows.append(r)
        print(f"  [control seed{seed}] rawBER={r['raw_ber']:.4f} "
              f"cw_failed={r['rs_codewords_failed']}/{r['n_codewords']} "
              f"exact={r['byte_exact']} ({r['wall_s']}s)", flush=True)
    return rows


def stage_full(workers: int = 4, rungs=None) -> list[dict]:
    jobs = [(spec, seed, "v2", None)
            for spec in (rungs if rungs is not None else DQ_RUNGS)
            for seed in SEEDS]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_run_dq, jobs):
            rows.append(r)
            print(f"  [full {r['rung']:16s} seed{r['seed']}] "
                  f"rawBER={r['raw_ber']:.4f} cw={r['rs_codewords_failed']}"
                  f"/{r['n_codewords']} exact={r['byte_exact']} "
                  f"SER={r['per_carrier_ser']} ({r['wall_s']}s)", flush=True)
    return rows


def verdict(full_rows: list[dict]) -> dict:
    by_rung: dict[str, list[dict]] = {}
    for r in full_rows:
        by_rung.setdefault(r["rung"], []).append(r)
    table = []
    for name, rows in by_rung.items():
        n_exact = sum(r["byte_exact"] for r in rows)
        table.append({
            "rung": name, "net_bps": rows[0]["net_bps"],
            "exact_seeds": n_exact, "n_seeds": len(rows),
            "raw_ber_per_seed": [round(r["raw_ber"], 5) for r in rows],
        })
    passing = [t for t in table
               if t["exact_seeds"] >= 2 and t["net_bps"] > BASELINE_NET_BPS]
    partial_rate = [t for t in table
                    if t["exact_seeds"] >= 2 and t["net_bps"] >= 400.0]
    # mechanism check: raw SER < 2% on >= half the carriers anywhere
    mech = False
    for r in full_rows:
        sers = r["per_carrier_ser"]
        if sum(s < 0.02 for s in sers) >= len(sers) / 2:
            mech = True
            break
    if passing:
        v = "PASS"
    elif partial_rate or mech:
        v = "PARTIAL"
    else:
        v = "FAIL"
    best = max((t for t in table if t["exact_seeds"] >= 2),
               key=lambda t: t["net_bps"], default=None)
    return {"verdict": v, "table": sorted(table, key=lambda t: -t["net_bps"]),
            "best_surviving": best, "mechanism_ser_ok": mech,
            "baseline_net_bps": BASELINE_NET_BPS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["sanity", "control", "full", "extend", "all"])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / "h4_dqpsk_results.json"
    out: dict = {}
    if out_path.exists():
        try:
            out = json.loads(out_path.read_text())
        except Exception:
            out = {}
    out.setdefault("hypothesis", "H4 DQPSK on wide-spaced continuous-phase carriers")
    out.setdefault("channel", "sim_v2.channel_v2(profile='tape7', aac=True)")
    out["seeds"] = SEEDS

    if args.stage in ("sanity", "all"):
        print("== stage: sanity ==", flush=True)
        out["sanity"] = stage_sanity()
        out_path.write_text(json.dumps(out, indent=2, default=float))
    if args.stage in ("control", "all"):
        print("== stage: control ==", flush=True)
        out["control"] = stage_control()
        out_path.write_text(json.dumps(out, indent=2, default=float))
    if args.stage in ("full", "all"):
        print("== stage: full ==", flush=True)
        rows = stage_full(args.workers)
        out["full"] = rows
        out["verdict"] = verdict(rows)
        out_path.write_text(json.dumps(out, indent=2, default=float))
        print(json.dumps(out["verdict"], indent=2))
    if args.stage == "extend":
        print("== stage: extend (ceiling search) ==", flush=True)
        rows = stage_full(args.workers, rungs=EXT_RUNGS)
        out["extension"] = rows
        out["verdict_with_extension"] = verdict(out.get("full", []) + rows)
        out_path.write_text(json.dumps(out, indent=2, default=float))
        print(json.dumps(out["verdict_with_extension"], indent=2))
    print(f"[done] wrote {out_path}")


if __name__ == "__main__":
    main()
