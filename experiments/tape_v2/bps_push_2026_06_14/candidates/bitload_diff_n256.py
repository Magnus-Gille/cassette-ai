"""bitload-diff-n256 — per-carrier bit-loaded DIFFERENTIAL PHY (L2, queue rank 2).

The FLAGSHIP rate lever: instead of a uniform DQPSK (2 bits/carrier) over all 22
carriers (the proven r8, 8250 gross -> 5921 model-net), assign EACH carrier its
own differential order — DBPSK(1) / DQPSK(2) / 8-DPSK(3) / 16-DAPSK(4) — by its
MEASURED post-impairment per-carrier reliability, so the strong carriers carry
more bits and the marginal ones carry fewer.  The loading table is FIXED side-info
(registered with the decode config, not transmitted).

Reuse, not reinvention
----------------------
TX geometry, pilot, Schroeder phasing and the published-H(f) pre-emphasis are the
EXACT r8 Dense2x (x10_b_aggr_05_dense2x_master.Dense2xScheme); only the per-carrier
symbol map is generalized from "all 2 bits" to a per-carrier (n_phase_bits,
n_amp_bits) table.  Sync is hyp_common.make_preamble/find_preamble (the proven
chirp), identical to every repo scheme.  The RX is the same per-symbol absolute-
basis complex DFT + unmodulated-pilot differential de-rotation as
h4_dqpsk.DQPSKScheme.demod / x9_resampling_pll — only the per-carrier SLICER is
generalized (M-DPSK sectors + optional amplitude ring).

Why differential, why amplitude is risky
-----------------------------------------
The channel's per-tone phase is non-reproducible (~70 deg over 4 s) -> absolute
coherence is dead; we detect symbol-to-symbol (5.3 ms apart) exactly like DQPSK.
The amplitude axis (DAPSK rings) is pilot-AGC referenced, but MEASURED amplitude
jitter on the replay channel is severe (per-carrier |c[i]|/|c[i-1]| CV 50-380 %,
pilot-normalized CV 30-230 %) because the diffuse cross-bin floor corrupts every
carrier's magnitude — so the amplitude bit is gated OFF by default (the conservative
loader caps at 8-DPSK).  An aggressive variant that enables 16-DAPSK on the cleanest
mids is provided to SCREEN the amplitude-ring transfer honestly.

Build entry points
------------------
    build()                  -> the recommended (conservative, phase-only) variant
    build_variant(name)      -> 'conservative' | 'aggressive_dapsk' | 'r8_baseline'
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                              # noqa: E402
from h4_dqpsk import DQPSKScheme                     # noqa: E402
from x10_b_aggr_05_dense2x_master import Dense2xScheme  # noqa: E402

FS = 48_000


# ---------------------------------------------------------------------------
# Gray code tables for M-DPSK phase sectors (M = 2,4,8,16) and the 2-ring
# amplitude bit.  Each carrier carries n_phase_bits (Gray-coded phase sector,
# differential) + n_amp_bits (0 or 1; the amplitude ring, differential mag).
# ---------------------------------------------------------------------------
def _gray_tables(nbits: int):
    """Return (enc, dec): enc[bit-tuple]->sector index, dec[sector]->bit-tuple
    for an nbits Gray code (0..2**nbits-1)."""
    M = 1 << nbits
    dec = {}
    enc = {}
    for v in range(M):
        g = v ^ (v >> 1)                  # binary-reflected Gray
        bits = tuple((g >> (nbits - 1 - j)) & 1 for j in range(nbits))
        dec[v] = bits
        enc[bits] = v
    return enc, dec


_GRAY_ENC = {nb: _gray_tables(nb)[0] for nb in (1, 2, 3, 4)}
_GRAY_DEC = {nb: _gray_tables(nb)[1] for nb in (1, 2, 3, 4)}


# ---------------------------------------------------------------------------
# The bit-loaded differential scheme.
# ---------------------------------------------------------------------------
class BitLoadedDiffScheme:
    """Per-carrier bit-loaded differential multicarrier on the r8 Dense2x grid.

    loading: list of (n_phase_bits, n_amp_bits) per data carrier, in carrier-
    frequency order matching Dense2xScheme(P=22).data_idx.  n_phase_bits in
    {1,2,3,4} -> M-DPSK with M=2**n_phase_bits; n_amp_bits in {0,1} -> a 2-ring
    differential-amplitude bit (ring_ratio).  bits_per_sym = sum over carriers.
    """

    def __init__(self, loading, *, ring_ratio: float = 2.2, P: int = 22):
        # The TX/geometry twin is the EXACT r8 Dense2x (skip=64 sets Nw for the
        # orthogonality assert; pre-emphasis + Schroeder phi0 inherited).
        self._geo = Dense2xScheme(P, skip=64)
        self._rx_geo = Dense2xScheme(P, skip=0)        # hann256_skip0 RX window
        assert len(loading) == self._geo.P, (len(loading), self._geo.P)
        self.P = self._geo.P
        self.N = self._geo.N
        self.skip = self._geo.skip
        self.Nw = self._geo.Nw
        self.freqs = self._geo.freqs
        self.bins = self._geo.bins
        self.pilot_idx = self._geo.pilot_idx
        self.data_idx = self._geo.data_idx
        self.tx_amp = self._geo.tx_amp
        self._win_tx = None
        self.ring_ratio = float(ring_ratio)
        self.ring_mid = math.sqrt(self.ring_ratio)     # decision boundary (low/high)
        self.loading = [(int(p), int(a)) for (p, a) in loading]
        self.n_phase = np.array([p for p, _ in self.loading], int)
        self.n_amp = np.array([a for _, a in self.loading], int)
        self.M = (1 << self.n_phase).astype(int)       # phase order per carrier
        self.bits_per_carrier = self.n_phase + self.n_amp
        self.bits_per_sym = int(self.bits_per_carrier.sum())
        self.gross_bps = self.bits_per_sym / (self.N / FS)
        self._preamble = hc.make_preamble(0.25).astype(np.float64)
        self.preamble_seconds = 0.25
        bits_tag = "".join(str(b) for b in self.bits_per_carrier)
        self.name = f"BLDiff_P{self.P}_N{self.N}_b{self.bits_per_sym}"
        # RX window/skip (hann256_skip0 — the proven primary front-end)
        self._win = self._rx_geo._win
        self._rx_skip = self._rx_geo.skip
        self._rx_Nw = self._rx_geo.Nw

    # ---- bit <-> symbol mapping (carrier-major blocks, like r8) -----------
    def nsym_for_bits(self, nbits: int) -> int:
        return int(math.ceil(nbits / self.bits_per_sym))

    def _split_carrier_bits(self, bits: np.ndarray, nd: int):
        """Carrier-major: carrier j owns the j-th contiguous
        nd*bits_per_carrier[j]-bit block of the frame (RS-friendly error
        concentration, same convention as DQPSKScheme.bits_to_quadrants)."""
        per = self.bits_per_carrier
        blocks = []
        off = 0
        for j in range(self.P):
            w = int(per[j]) * nd
            blk = bits[off:off + w]
            if len(blk) < w:
                blk = np.concatenate([blk, np.zeros(w - len(blk), np.uint8)])
            blocks.append(blk.reshape(nd, int(per[j])))
            off += w
        return blocks                                  # list of (nd, per[j])

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        bits = np.asarray(bits, np.uint8)
        nd = self.nsym_for_bits(len(bits))
        pad = nd * self.bits_per_sym - len(bits)
        if pad > 0:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        blocks = self._split_carrier_bits(bits, nd)

        total = nd + 1                                 # +1 reference symbol
        nc = self.P + 1

        # Per-carrier, per-symbol phase INCREMENT and absolute ring level.
        # dphi_inc[s, k] = the differential phase step applied to carrier k going
        # from symbol s to s+1; ring_lvl[s, k] = the amplitude of carrier k at
        # symbol s+1 (1.0 unless an amplitude bit selects the high ring).
        dphi_inc = np.zeros((nd, nc))
        ring_lvl = np.ones((nd, nc))                   # amplitude for symbols 1..nd
        for di, j in enumerate(self.data_idx):
            npb = int(self.n_phase[di])
            nab = int(self.n_amp[di])
            blk = blocks[di]                           # (nd, npb+nab)
            phbits = blk[:, :npb]
            enc = _GRAY_ENC[npb]
            M = 1 << npb
            sect = np.array([enc[tuple(int(b) for b in phbits[s])]
                             for s in range(nd)], int)
            dphi_inc[:, j] = sect * (2 * np.pi / M)
            if nab:
                ab = blk[:, npb].astype(int)
                ring_lvl[:, j] = np.where(ab == 1, self.ring_ratio, 1.0)

        # Cumulative phase ladder: carry the FULL previous row forward (so the
        # unmodulated pilot keeps its Schroeder phi0 across all symbols) then add
        # the per-carrier increment to the data carriers — h4/Dense2x-identical.
        theta = np.zeros((total, nc))
        amp = np.ones((total, nc))
        kk0 = np.arange(nc, dtype=np.float64)
        theta[0] = -np.pi * kk0 * kk0 / nc             # Schroeder initial phase
        for i in range(1, total):
            theta[i] = theta[i - 1] + dphi_inc[i - 1]
            amp[i] = ring_lvl[i - 1]

        t = np.arange(total * self.N) / FS
        body = np.zeros(total * self.N)
        for kk in range(nc):
            ph = 2 * np.pi * self.freqs[kk] * t + np.repeat(theta[:, kk], self.N)
            a = np.repeat(amp[:, kk], self.N)
            body += self.tx_amp[kk] * a * np.sin(ph)
        audio = np.concatenate([self._preamble, body])
        pk = np.max(np.abs(audio))
        return (audio / pk * 0.70).astype(np.float32)

    # ---- differential demod (per-carrier variable-order slicer) -----------
    def _carrier_dft(self, y, ds, total):
        """Per-symbol absolute-basis complex DFT with the proven pilot EMA
        integer-drift window tracker (h4-identical).  Returns (c, dtau)."""
        N, skip, Nw = self.N, self._rx_skip, self._rx_Nw
        win = self._win
        freqs = self.freqs
        nc = self.P + 1
        fpil = freqs[self.pilot_idx]
        c = np.zeros((total, nc), np.complex128)
        dtau = np.zeros(total)
        drift = 0.0
        ema = 0.7
        sm = 0.0
        for i in range(total):
            base = ds + i * N + int(round(drift))
            lo = base + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS
            E = np.exp(-2j * np.pi * np.outer(freqs, tt))
            c[i] = E @ (seg * win)
            if i > 0:
                dp = float(np.angle(c[i, self.pilot_idx] *
                                    np.conj(c[i - 1, self.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
        return c, dtau

    def demodulate(self, audio: np.ndarray, sr: int,
                   nd: int | None = None) -> np.ndarray:
        y = np.asarray(audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), self.preamble_seconds)
        # recover nd: caller may set _nd; else infer from payload length budget
        if nd is None:
            nd = getattr(self, "_nd", None)
        if nd is None:
            # infer from remaining audio length
            nd = max(1, (len(y) - ds) // self.N - 1)
        total = nd + 1
        c, dtau = self._carrier_dft(y, ds, total)

        fd = self.freqs[self.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])              # (nd, nc)
        dphi = np.angle(d[:, self.data_idx])           # (nd, P)
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)

        # one-shot decision-directed common-timing refine using a UNIFORM
        # quarter-turn slice (robust, order-agnostic), exactly as the proven
        # DQPSK refine — it only removes a residual common-timing slope.
        q4 = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
        res = (dphi - q4 * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_res = num / (2 * np.pi * den)
        dphi = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]

        # ABSOLUTE-ring amplitude detection (for ring carriers).  The TX sets each
        # ring carrier to one of two ABSOLUTE levels {1.0, ring_ratio} (× the fixed
        # per-carrier tx_amp·H(f) gain), so the bit is read from the symbol
        # magnitude relative to the carrier's own LOW-ring reference, with the
        # common per-symbol channel-gain wander removed via the pilot AGC.
        mag = np.abs(c[1:, :])                          # (nd, nc), symbols 1..nd
        pil = mag[:, self.pilot_idx][:, None] + 1e-12   # pilot magnitude per symbol
        magn = mag[:, self.data_idx] / pil              # pilot-AGC normalized

        # per-carrier variable-order slice -> recover carrier-major bit blocks
        out_blocks = []
        for di in range(self.P):
            npb = int(self.n_phase[di])
            nab = int(self.n_amp[di])
            M = 1 << npb
            dec = _GRAY_DEC[npb]
            ph = dphi[:, di]
            # M-DPSK sector decision: nearest multiple of 2*pi/M
            sect = np.round(ph / (2 * np.pi / M)).astype(int) % M
            blk = np.zeros((nd, npb + nab), np.uint8)
            for s in range(nd):
                blk[s, :npb] = dec[int(sect[s])]
            if nab:
                # Two-level absolute ring: normalize this carrier's pilot-AGC
                # magnitude by its own LOW-ring reference (the cluster of symbols
                # whose magnitude sits in the bottom band), threshold at ring_mid.
                a = magn[:, di]
                lo_ref = np.percentile(a, 25)           # ~low-ring level
                ratio = a / (lo_ref + 1e-12)
                blk[:, npb] = (ratio > self.ring_mid).astype(np.uint8)
            out_blocks.append(blk.reshape(-1))
        bits = np.concatenate(out_blocks)
        return bits.astype(np.uint8)


# ---------------------------------------------------------------------------
# Loading tables.  Carrier order = Dense2xScheme(22).data_idx frequency order:
#   750 1125 1500 1875 2250 2625 3000 3375 3750 4125 4500
#   5250 5625 6000 6375 6750 7125 7500 7875 8250 8625 9000
# Each entry is (n_phase_bits, n_amp_bits).
# ---------------------------------------------------------------------------
CARRIERS_HZ = [750, 1125, 1500, 1875, 2250, 2625, 3000, 3375, 3750, 4125, 4500,
               5250, 5625, 6000, 6375, 6750, 7125, 7500, 7875, 8250, 8625, 9000]

# Measured per-carrier differential phase std (deg) through replay_tape10
# (6 seeds, 200 symbols; see screen log).  This drives the loader.
MEAS_PHASE_STD_DEG = {
    750: 10.33, 1125: 13.64, 1500: 19.06, 1875: 12.13, 2250: 12.46,
    2625: 16.59, 3000: 18.00, 3375: 9.55, 3750: 10.59, 4125: 17.05,
    4500: 13.38, 5250: 10.45, 5625: 15.74, 6000: 14.35, 6375: 14.52,
    6750: 14.98, 7125: 13.58, 7500: 12.98, 7875: 11.74, 8250: 12.28,
    8625: 14.66, 9000: 11.93,
}

# Conservative loader: bump the CLEANEST carriers (phase std small enough that
# the 8-DPSK 22.5 deg boundary still gives BER ~<=0.02) from DQPSK -> 8-DPSK;
# everything else stays DQPSK; NO amplitude ring (measured AM jitter too large).
# Threshold chosen so 8-DPSK est-BER stays under ~0.015 (std <= ~11 deg).
_8DPSK_PHASE_STD_THR = 11.0


def _conservative_loading():
    load = []
    for f in CARRIERS_HZ:
        std = MEAS_PHASE_STD_DEG[f]
        if std <= _8DPSK_PHASE_STD_THR:
            load.append((3, 0))                        # 8-DPSK
        else:
            load.append((2, 0))                        # DQPSK
    return load


def _aggressive_dapsk_loading():
    """Flagship: 8-DPSK on the clean mids, plus a 16-DAPSK amplitude bit on the
    very cleanest low/mid carriers (4 bits).  Screens the amplitude-ring transfer
    — expected to FAIL the AM-jitter floor, which is the honest result to report."""
    load = []
    # cleanest carriers get the amplitude ring (lowest phase std AND low HF index)
    dapsk_set = {750, 3375, 3750, 5250, 1875}
    for f in CARRIERS_HZ:
        std = MEAS_PHASE_STD_DEG[f]
        npb = 3 if std <= _8DPSK_PHASE_STD_THR + 1.5 else 2
        nab = 1 if f in dapsk_set else 0
        load.append((npb, nab))
    return load


def _r8_baseline_loading():
    return [(2, 0)] * len(CARRIERS_HZ)


def loading_table(variant: str = "conservative"):
    if variant == "conservative":
        return _conservative_loading()
    if variant == "aggressive_dapsk":
        return _aggressive_dapsk_loading()
    if variant == "r8_baseline":
        return _r8_baseline_loading()
    raise ValueError(f"unknown variant {variant!r}")


def loading_summary(variant: str = "conservative"):
    load = loading_table(variant)
    return {f"{f}": (p + a) for f, (p, a) in zip(CARRIERS_HZ, load)}


# ---------------------------------------------------------------------------
# FuncScheme adapter — wraps modulate/demodulate, sets nd from payload bits.
# ---------------------------------------------------------------------------
def _make_funcscheme(scheme: BitLoadedDiffScheme, rs_k: int = 179):
    from hyp_common import FuncScheme

    def modulate(bits):
        b = np.asarray(bits, np.uint8)
        modulate._nbits = len(b)
        return np.asarray(scheme.modulate(b), np.float32)
    modulate._nbits = 0

    def demodulate(audio, sr):
        nd = scheme.nsym_for_bits(modulate._nbits)
        return scheme.demodulate(np.asarray(audio, np.float64), sr, nd=nd)

    fs = FuncScheme(name=scheme.name, gross_bps=float(scheme.gross_bps),
                    modulate=modulate, demodulate=demodulate)
    fs.rs_k = rs_k
    fs.scheme = scheme
    fs.loading = scheme.loading
    fs.carriers_hz = CARRIERS_HZ
    fs._modulate_ref = modulate
    return fs


def build_variant(variant: str = "conservative", *, rs_k: int = 179):
    scheme = BitLoadedDiffScheme(loading_table(variant))
    return _make_funcscheme(scheme, rs_k=rs_k)


def build():
    """The recommended candidate: the conservative phase-only bit-loaded PHY."""
    return build_variant("conservative", rs_k=179)
