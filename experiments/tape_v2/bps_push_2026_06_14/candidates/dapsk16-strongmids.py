"""dapsk16-strongmids.py  --  candidate id "dapsk16-strongmids" (queue rank 3).

HIGHER-ORDER DIFFERENTIAL on the proven N256 / 375 Hz / 187.5-sym DQPSK grid
(r8 D2X P22 geometry).  Three variants are exposed; ``build()`` returns the one
named by the module-level VARIANT (default 'a').  Each variant is a per-carrier
differential constellation assignment over the 22 Dense2x data carriers:

  (a) 8dpsk_uniform : 8-DPSK on ALL 22 carriers (3 bits/carrier, pure
                      differential phase, NO amplitude).  22*3*187.5 = 12375
                      gross.  Cleanest test of whether the channel's ~11 deg/sym
                      differential phase jitter tolerates the 8-PSK 22.5 deg
                      boundary (half of DQPSK's 45 deg).
  (b) 16dapsk_8mids : 16-DAPSK (1 differential-amplitude ring bit + 3 differential
                      8-PSK phase bits = 4 bits) on the 8 cleanest mid carriers,
                      DQPSK (2 bits) everywhere else.
  (c) 8dpsk_14mids  : 8-DPSK (3 bits) on the 14 cleanest mid carriers, DQPSK
                      (2 bits) on the rest.

DSP reuse (no sync/pilot reinvented):
  * TX subclasses Dense2xScheme -> inherits the 375 Hz grid, pilot@4875,
    Schroeder-phased initial symbol, measured-H(f) TX pre-emphasis, the proven
    chirp preamble (hyp_common.make_preamble), and the carrier layout.
  * RX reuses the EXACT proven h4/x9 EMA pilot-tracking loop (per-symbol complex
    DFT on an absolute sample basis + unmodulated-pilot differential de-rotation
    + integer window-drift tracker), then dispatches a per-carrier M-DPSK / DAPSK
    slicer instead of the DQPSK-only quadrant slicer.

Everything is DIFFERENTIAL (symbol-to-symbol, 5.3 ms apart): no absolute phase
or amplitude reference is used.  The amplitude ring is a DIFFERENTIAL magnitude
ratio |c[i]| / |c[i-1]| (DRM-style star-QAM), pilot-magnitude-independent.
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

import hyp_common as hc                                  # noqa: E402
from hyp_common import FuncScheme                        # noqa: E402
from x10_b_aggr_05_dense2x_master import Dense2xScheme    # noqa: E402

FS = 48_000

# ---------------------------------------------------------------------------
# Gray code tables for M-DPSK phase (2/4/8 sectors).
# ---------------------------------------------------------------------------
def _gray_tables(nbits: int):
    """Return (enc, dec): enc[i] = Gray code of integer i (nbits wide), and dec
    the inverse.  M = 2**nbits phase sectors, sector s carries differential
    phase 2*pi*s/M.  Gray ensures a single-sector slip = 1 bit error."""
    M = 1 << nbits
    enc = [i ^ (i >> 1) for i in range(M)]   # natural index -> gray symbol value
    # We map BITS (msb-first) -> integer i -> gray sector value g; on RX we take
    # the decided sector g -> i (inverse gray) -> bits.
    inv = {g: i for i, g in enumerate(enc)}
    return enc, inv


# DAPSK amplitude: two rings with ratio R.  A differential-amplitude bit b drives
# the ring transition (DRM 16-DAPSK / 4-DAPSK standard 2-level mapping):
#   b=0 -> next ring = same as previous ring (ratio 1)
#   b=1 -> next ring = the OTHER ring (ratio R if currently inner -> outer, 1/R
#          if currently outer -> inner)
# Receiver decides b from the differential magnitude ratio rho = |c[i]|/|c[i-1]|:
#   rho near 1   -> b=0 (no ring change)
#   rho near R   -> b=1 (inner->outer)
#   rho near 1/R -> b=1 (outer->inner)
# i.e. b = 0 iff rho is within [1/sqrt(R), sqrt(R)] (the geometric guard band).
RING_RATIO = 2.0    # ring_sep ~6 dB (queue spec: ring_ratio 2, ring_sep_db 6)


class DiffMultitoneScheme(Dense2xScheme):
    """Per-carrier differential constellation over the Dense2x P22 grid.

    ``bits_per_carrier`` : length-P list, total info bits/symbol for each data
                           carrier (2 = DQPSK, 3 = 8-DPSK, 4 = 16-DAPSK).
    ``ring_carrier``     : length-P bool list, True if that carrier spends 1 of
                           its bits on a differential-amplitude ring (the rest on
                           M-DPSK phase, M = 2**(bits-1)).  False = all bits on
                           phase (M = 2**bits).
    """

    def __init__(self, bits_per_carrier, ring_carrier, *, name: str,
                 skip: int = 64, ring_ratio: float = RING_RATIO):
        super().__init__(22, skip=skip)        # P22 Dense2x grid, pilot@4875
        assert len(bits_per_carrier) == self.P
        assert len(ring_carrier) == self.P
        self.bits_per_carrier = list(int(b) for b in bits_per_carrier)
        self.ring_carrier = list(bool(r) for r in ring_carrier)
        self.ring_ratio = float(ring_ratio)
        self.name = name
        # phase order (in bits) per carrier
        self.phase_bits = [b - (1 if r else 0)
                           for b, r in zip(self.bits_per_carrier, self.ring_carrier)]
        for pb in self.phase_bits:
            assert pb in (1, 2, 3), f"phase order {pb} unsupported (need 1/2/3 bits)"
        self.M = [1 << pb for pb in self.phase_bits]
        self._gray = [_gray_tables(pb) for pb in self.phase_bits]
        self.bits_per_sym = int(sum(self.bits_per_carrier))
        # info bits/sec = info bits/symbol * symbol rate (N/FS).  Per the guide
        # this is the STEADY-STATE gross (preamble overhead not subtracted).
        self.gross_bps = self.bits_per_sym / (self.N / FS)
        # carrier-block bit layout: carrier j owns a contiguous block of the
        # frame bits so a faded carrier corrupts a contiguous slice (RS-friendly),
        # matching the proven bits_to_quadrants block convention.
        #
        # RECEIVER GEOMETRY = the proven hann256_skip0 front-end (the exact RX
        # that won r8: build_dense2x_candidate uses RX skip=0 = full Hann(256)
        # window, the 2-bin soft guard).  TX keeps skip=64 (Schroeder/Nw asserts)
        # but the demod analyses with skip=0 so the carriers stay orthogonal over
        # the full N-sample symbol (Nw=128 from skip=64 loses that and smears the
        # differential phase ~20 deg even on a clean signal).
        self._rx_skip = 0
        self._rx_Nw = self.N - 2 * self._rx_skip
        assert (self.spacing * self._rx_Nw) % self.N == 0
        self._rx_win = np.hanning(self._rx_Nw)

    # ---- bit <-> per-(symbol,carrier) symbol value -------------------------
    def _layout(self, nbits: int):
        """Return (nd, list of (carrier, start_bit) ) for the carrier-block
        layout.  Each carrier j carries nd * bits_per_carrier[j] contiguous bits.
        nd = ceil(nbits / bits_per_sym).  Returns nd and a flat plan."""
        bps = self.bits_per_sym
        nd = int(math.ceil(nbits / bps))
        return nd

    def _encode_symbols(self, bits: np.ndarray):
        """bits -> (phase_sectors[nd,P] int, ring_bits[nd,P] int or -1).

        Carrier-block layout: the frame's bit vector is split into P contiguous
        blocks, block j -> carrier j, each block is nd*bits_per_carrier[j] bits
        laid out symbol-major within the carrier (symbol 0 first ...)."""
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        nd = len(bits) // bps
        # block boundaries
        sectors = np.zeros((nd, self.P), int)
        rings = np.full((nd, self.P), -1, int)
        off = 0
        for j in range(self.P):
            bpc = self.bits_per_carrier[j]
            blk = bits[off: off + nd * bpc].reshape(nd, bpc)   # (nd, bpc)
            off += nd * bpc
            pb = self.phase_bits[j]
            enc, _ = self._gray[j]
            if self.ring_carrier[j]:
                # first bit = ring, remaining pb bits = phase (msb-first)
                rings[:, j] = blk[:, 0]
                pblk = blk[:, 1:1 + pb]
            else:
                pblk = blk[:, 0:pb]
            # phase bits (msb-first) -> integer index -> gray sector value
            idx = np.zeros(nd, int)
            for b in range(pb):
                idx = (idx << 1) | pblk[:, b]
            sectors[:, j] = np.asarray(enc, int)[idx]
        return nd, sectors, rings

    def _decode_symbols(self, sectors: np.ndarray, rings: np.ndarray,
                        nbits: int) -> np.ndarray:
        """Inverse of _encode_symbols -> flat bit vector (length nbits, trimmed)."""
        nd = sectors.shape[0]
        bps = self.bits_per_sym
        out = np.zeros(nd * bps, np.uint8)
        off = 0
        for j in range(self.P):
            bpc = self.bits_per_carrier[j]
            pb = self.phase_bits[j]
            _, inv = self._gray[j]
            # gray sector value -> natural index -> phase bits (msb-first)
            sec = sectors[:, j]
            idx = np.array([inv.get(int(s), 0) for s in sec], int)
            blk = np.zeros((nd, bpc), np.uint8)
            col = 0
            if self.ring_carrier[j]:
                blk[:, 0] = np.clip(rings[:, j], 0, 1).astype(np.uint8)
                col = 1
            for b in range(pb):
                shift = pb - 1 - b
                blk[:, col + b] = (idx >> shift) & 1
            out[off: off + nd * bpc] = blk.reshape(-1)
            off += nd * bpc
        return out[:nbits]

    # ---- modulate ----------------------------------------------------------
    def modulate(self, bits: np.ndarray) -> np.ndarray:
        nd, sectors, rings = self._encode_symbols(bits)
        total = nd + 1                       # +1 reference symbol
        nc = self.P + 1
        # cumulative differential phase ladder; pilot stays at its Schroeder phi0.
        phi0 = self._phi0()                  # Schroeder initial phases (nc,)
        theta = np.zeros((total, nc))
        theta[0] = phi0
        # per-carrier amplitude ladder (ring state); reference symbol = inner ring
        amp = np.ones((total, nc))           # linear amplitude multiplier
        R = self.ring_ratio
        ring_state = np.zeros(self.P, int)   # 0 = inner ring, 1 = outer ring
        for i in range(1, total):
            theta[i] = theta[i - 1]
            for jj, k in enumerate(self.data_idx):
                sec = sectors[i - 1, jj]
                Mk = self.M[jj]
                theta[i, k] += 2 * np.pi * sec / Mk
            amp[i] = amp[i - 1]
            # ring carriers: differential amplitude transition
            for jj, k in enumerate(self.data_idx):
                if not self.ring_carrier[jj]:
                    continue
                b = rings[i - 1, jj]
                if b == 1:
                    ring_state[jj] ^= 1      # flip ring
                amp[i, k] = (R if ring_state[jj] == 1 else 1.0)
        # synthesize
        t = np.arange(total * self.N) / FS
        body = np.zeros(total * self.N)
        for k in range(nc):
            ph = 2 * np.pi * self.freqs[k] * t + np.repeat(theta[:, k], self.N)
            a = np.repeat(self.tx_amp[k] * amp[:, k], self.N)
            body += a * np.sin(ph)
        audio = np.concatenate([self._preamble, body])
        pk = np.max(np.abs(audio))
        return (audio / pk * 0.70).astype(np.float32)

    # ---- demodulate (self-syncing FuncScheme signature) --------------------
    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Self-sync from the chirp preamble; recover nd from the audio length;
        reuse the proven EMA pilot-tracking loop; per-carrier M-DPSK/DAPSK slice.
        Returns the recovered bit vector (carrier-block layout)."""
        assert sr == FS
        y = np.asarray(audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), self.preamble_seconds)
        N, skip, Nw = self.N, self._rx_skip, self._rx_Nw   # proven hann256_skip0 RX
        # number of whole symbols (incl. the reference symbol) in the body.  The
        # body is exactly total*N samples starting at ds.  find_preamble's ds can
        # be a few samples off under the channel (sync jitter), so ROUND rather
        # than floor: flooring loses the final symbol and (with the carrier-block
        # layout) shifts every carrier's bit block -> catastrophic BER.  The last
        # symbol's analysis window is zero-padded if it runs a few samples off the
        # end (harmless: <1 symbol of pad on a Hann-windowed DFT).
        total = int(max(1, round((len(y) - ds) / N)))
        nc = self.P + 1
        fpil = self.freqs[self.pilot_idx]
        win = self._rx_win
        freqs = self.freqs
        c = np.zeros((total, nc), np.complex128)
        dtau = np.zeros(total)
        drift = 0.0
        ema = 0.5
        sm = 0.0
        for i in range(total):
            base = ds + i * N + int(round(drift))
            lo = base + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS
            E = np.exp(-2j * np.pi * np.outer(freqs, tt))
            # E and (seg*win) are both fully finite; numpy's threaded complex
            # GEMM spuriously raises FP flags from SIMD tail lanes (same idiom as
            # the proven h4/x9 DFT).  The result is correct (clean BER 0); silence
            # the cosmetic warning without touching numerics.
            with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
                c[i] = E @ (seg * win)
            if i > 0:
                dp = float(np.angle(c[i, self.pilot_idx] *
                                    np.conj(c[i - 1, self.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
        nd = total - 1
        if nd <= 0:
            return np.zeros(0, np.uint8)
        fd = self.freqs[self.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])              # (nd, nc) differential
        dphi = np.angle(d[:, self.data_idx])           # (nd, P)
        # pilot de-rotation of the common timing term (flutter), h4-identical
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
        # one-shot decision-directed common-timing refinement (LS slope over the
        # DECIDED phase residual; uses the per-carrier sector size, no truth).
        sectors = self._slice_phase(dphi)
        res = self._phase_residual(dphi, sectors)
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_res = num / (2 * np.pi * den)
        dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
        sectors = self._slice_phase(dphi2)
        # amplitude rings: differential magnitude ratio per carrier
        mag = np.abs(c[:, self.data_idx])              # (total, P)
        rings = self._slice_rings(mag)                 # (nd, P)
        return self._decode_symbols(sectors, rings, nd * self.bits_per_sym)

    # ---- per-carrier phase slicer (variable M) -----------------------------
    def _slice_phase(self, dphi: np.ndarray) -> np.ndarray:
        """dphi (nd,P) -> decided sector VALUE per carrier (nd,P).

        The transmitted differential phase for carrier j is 2*pi*sec/M where
        ``sec`` is the Gray-coded value stored in ``sectors`` (see modulate).
        So rounding dphi to the nearest 2*pi/M directly recovers ``sec`` (the
        Gray value); _decode_symbols then inverts Gray -> bits.  No second Gray
        application here."""
        nd = dphi.shape[0]
        sectors = np.zeros((nd, self.P), int)
        for j in range(self.P):
            Mk = self.M[j]
            sectors[:, j] = np.round(dphi[:, j] / (2 * np.pi / Mk)).astype(int) % Mk
        return sectors

    def _phase_residual(self, dphi: np.ndarray, sectors: np.ndarray) -> np.ndarray:
        """Residual angle after removing the decided sector center, wrapped to
        (-pi,pi].  Used for the DD timing-slope refinement (no truth).
        ``sectors`` holds the decided sector VALUE (the Gray value = the natural
        multiple of 2*pi/M actually transmitted), so the center is 2*pi*sec/M."""
        nd = dphi.shape[0]
        res = np.zeros((nd, self.P))
        for j in range(self.P):
            Mk = self.M[j]
            center = 2 * np.pi * sectors[:, j] / Mk
            res[:, j] = (dphi[:, j] - center + np.pi) % (2 * np.pi) - np.pi
        return res

    # ---- per-carrier ring slicer (differential amplitude) ------------------
    def _slice_rings(self, mag: np.ndarray) -> np.ndarray:
        """mag (total,P) -> ring bits (nd,P), -1 where the carrier has no ring.

        Differential-amplitude decision: rho[i] = |c[i]| / |c[i-1]|.  A ring
        transition (b=1) multiplies the amplitude by R (inner->outer) or 1/R
        (outer->inner); b=0 keeps the ratio at 1.  Decide b=1 iff rho is outside
        the geometric guard band [1/sqrt(R), sqrt(R)] (i.e. log|rho| is closer to
        +-log(R) than to 0).  Robust to any common per-symbol gain (flutter AGC),
        since both magnitudes scale together."""
        R = self.ring_ratio
        nd = mag.shape[0] - 1
        rings = np.full((nd, self.P), -1, int)
        if not any(self.ring_carrier):
            return rings
        logR = math.log(R)
        # rho per symbol step
        prev = mag[:-1, :]
        cur = mag[1:, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            lr = np.log(np.clip(cur, 1e-12, None) / np.clip(prev, 1e-12, None))
        # decision threshold at log(R)/2 (geometric midpoint between ratio 1 and R)
        thr = logR / 2.0
        for j in range(self.P):
            if not self.ring_carrier[j]:
                continue
            rings[:, j] = (np.abs(lr[:, j]) > thr).astype(int)
        return rings


# ===========================================================================
# Variant definitions
# ===========================================================================
# Dense2x P22 data carriers (Hz), in order (idx 0..21):
#   750 1125 1500 1875 2250 2625 3000 3375 3750 4125 4500
#   5250 5625 6000 6375 6750 7125 7500 7875 8250 8625 9000
DATA_FREQS = [750, 1125, 1500, 1875, 2250, 2625, 3000, 3375, 3750, 4125, 4500,
              5250, 5625, 6000, 6375, 6750, 7125, 7500, 7875, 8250, 8625, 9000]

# "cleanest mids" (queue's hand-picked guess): exclude the documented-marginal
# carriers (750 Hz echo ISI; 4500 Hz deck notch; 5625 / 6750 notch-adjacent) and
# the HF rolloff band.  THESE GUESSES WERE WRONG on the replay channel (variants
# b/c put 8-DPSK on 1500/3000/2625/6000 Hz which actually have p90 27-72 deg).
CLEAN_MIDS_8 = [1500, 3000, 3750, 4125, 5625, 6000, 1125, 2625]            # 8 cleanest
CLEAN_MIDS_14 = [1500, 3000, 3750, 4125, 5625, 6000, 1125, 2625,
                 1875, 5250, 6375, 750, 4500, 7125]                         # 14 cleanest

# MEASURED per-carrier differential-phase p90 (deg) on replay_tape10, pooled over
# 6 seeds with the proven r8 DQPSK TX (the carrier-loading CSI).  This is the
# rank-2 "bit-load by MEASURED effective SINR" CSI, and it OVERRIDES the guesses
# above.  Carriers ranked CLEANEST-first (lowest symbol-to-symbol phase jitter):
#   3375:15.2  5250:15.4  750:15.8  9000:16.9  7875:16.9  3750:17.3  8250:17.7
#   7500:19.2  1875:19.8  2250:20.1  1125:20.7  7125:21.1  4500:22.1  6750:22.1
#   8625:22.6  2625:27.2  4125:27.9  3000:30.8  5625:33.0  1500:47.8  6000:72.5
# The 8-DPSK boundary is +-22.5 deg, so only carriers with p90 << 22.5 carry the
# extra bit with margin.  Sweeping n8 (8-DPSK on the n cleanest) on replay_tape10
# the model_net PEAKS at n8=3 (model_net 6774) and stays > 5921 up to n8=13.
CSI_CLEANEST = [3375, 5250, 750, 9000, 7875, 3750, 8250, 7500, 1875, 2250,
                1125, 7125, 4500, 6750]


def _idx(freqs):
    return [DATA_FREQS.index(f) for f in freqs]


def _variant_a():
    """8-DPSK on ALL 22 carriers (3 bits/carrier, no ring). gross 12375."""
    bpc = [3] * 22
    ring = [False] * 22
    return DiffMultitoneScheme(bpc, ring, name="dapsk16sm_a_8dpsk_uniform")


def _variant_b():
    """16-DAPSK (4b: 1 ring + 3 phase) on 8 cleanest mids, DQPSK (2b) elsewhere."""
    bpc = [2] * 22
    ring = [False] * 22
    for j in _idx(CLEAN_MIDS_8):
        bpc[j] = 4
        ring[j] = True
    return DiffMultitoneScheme(bpc, ring, name="dapsk16sm_b_16dapsk_8mids")


def _variant_c():
    """8-DPSK (3b) on 14 cleanest mids, DQPSK (2b) on the rest."""
    bpc = [2] * 22
    ring = [False] * 22
    for j in _idx(CLEAN_MIDS_14):
        bpc[j] = 3
    return DiffMultitoneScheme(bpc, ring, name="dapsk16sm_c_8dpsk_14mids")


def _variant_d():
    """WINNER: 8-DPSK (3b) on the 3 CSI-cleanest carriers (3375/5250/750 Hz),
    DQPSK (2b) on the other 19.  gross 8812.5.  Replay model_net peak (6774).
    This is the measured-CSI bit-loading instantiation the queue's hand-picks
    missed -- the extra bit goes only where the phase jitter clears 22.5 deg."""
    bpc = [2] * 22
    ring = [False] * 22
    for j in _idx(CSI_CLEANEST[:3]):
        bpc[j] = 3
    return DiffMultitoneScheme(bpc, ring, name="dapsk16sm_d_8dpsk_csi3")


def _variant_e():
    """Robustness hedge: 8-DPSK on the 7 CSI-cleanest carriers (all p90<18 deg),
    DQPSK elsewhere.  gross 9562.5, replay model_net ~6525 -- more headroom over
    the record if a couple of the 3-carrier set flips burn-to-burn."""
    bpc = [2] * 22
    ring = [False] * 22
    for j in _idx(CSI_CLEANEST[:7]):
        bpc[j] = 3
    return DiffMultitoneScheme(bpc, ring, name="dapsk16sm_e_8dpsk_csi7")


VARIANTS = {"a": _variant_a, "b": _variant_b, "c": _variant_c,
            "d": _variant_d, "e": _variant_e}
VARIANT = "d"           # default = the measured-CSI winner


def build(variant: str | None = None) -> FuncScheme:
    """Return a hyp_common.FuncScheme for the requested variant (default 'a').

    The scheme object itself satisfies the FuncScheme duck-type (name, gross_bps,
    modulate, demodulate), but we wrap it in a real FuncScheme so the harness's
    isinstance/attribute checks behave and rs_k can be attached for the cassette
    cross-check.  A plain (non-DQPSK-adapter) FuncScheme is fine here: the guide
    says non-DQPSK schemes need no margin metric; model_net/BER is primary."""
    v = variant or VARIANT
    sch = VARIANTS[v]()
    fs = FuncScheme(name=sch.name, gross_bps=float(sch.gross_bps),
                    modulate=sch.modulate, demodulate=sch.demodulate)
    fs.rs_k = None        # report raw model_net; RS rate chosen post-hoc
    fs._scheme = sch
    return fs


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="a", choices=list(VARIANTS))
    args = ap.parse_args()
    fs = build(args.variant)
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), 48000)
    m = min(len(bits), len(rx))
    ber = float(np.mean(bits[:m] != rx[:m])) + (len(bits) - m) / len(bits)
    print(f"variant {args.variant}: gross={fs.gross_bps:.0f} bits={len(bits)} "
          f"rx={len(rx)} clean_ber={ber:.2e}")
