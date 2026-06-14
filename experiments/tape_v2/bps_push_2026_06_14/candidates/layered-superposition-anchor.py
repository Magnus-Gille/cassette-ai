"""layered-superposition-anchor.py -- queue rank 6, lever L10.

Layered / superposition modulation with a GUARANTEED hard floor:

  BASE LAYER  = the PROVEN r8 Dense2x P22 DQPSK (22 carriers, 2 bits/sym,
                187.5 sym/s, pilot@4875).  Full power.  Decoded FIRST and
                ROBUST -> guarantees the >=5791 record floor.  Its phase
                ladder is byte-identical to x10_b_aggr_05_dense2x_master's
                Schroeder-phased TX (the exact r8/r6 modulator).

  ENH  LAYER  = a LOW-POWER differential-amplitude (2-DAPSK) ring superimposed
                on the strong, two-capture-stable mid carriers.  One amplitude
                bit per enh-carrier per symbol, encoded as a BOUNDED two-ring
                state machine (stay/toggle) so the running amplitude never
                drifts (the canonical DAPSK amplitude bit, Webb).  Pilot
                magnitude is the AGC reference; the bit is read DIFFERENTIALLY
                (|c[i]|/|c[i-1]|), so it inherits the absolute-coherence-free
                property that lets DQPSK survive the channel's 70-deg phase
                non-reproducibility.

  RX = successive cancellation: decode the base DQPSK (unchanged proven demod),
       then differential-amplitude-detect the residual ring.  Because the ring
       is differential and the base phase is unchanged, the two layers are
       (to first order) orthogonal -- the amplitude perturbation barely moves
       the DQPSK phase decision, and the phase carries no amplitude info.

gross_bps = base 8250 + enh (n_enh carriers x 1 bit x 187.5 sym/s).

The point is a CAPPED-downside record attempt: if the enhancement layer fails
in the channel, the base still decodes the proven 5791.  The combined BER (base
bits + enhancement bits) is what the harness scores; a failing enhancement
inflates that combined BER, which the model_net correctly penalises -- but the
*recorded* downside on real tape is still the proven base rung.

The ``eps`` parameter is the fractional amplitude swing of the ring around the
base amplitude (a0 = 1-eps, a1 = 1+eps; geometric-mean ~= 1 so the base drive
is preserved).  Enhancement power below base ~= 20*log10(eps) dB:
    eps 0.40 -> ~ -8 dB,  0.316 -> -10 dB,  0.251 -> -12 dB,  0.20 -> -14 dB.

build(eps=...) returns one configured FuncScheme; build() (the contract entry)
returns the default (-12 dB, conservative) rung.
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

import hyp_common as hc                                   # noqa: E402
from hyp_common import FuncScheme                         # noqa: E402
from x10_b_aggr_05_dense2x_master import Dense2xScheme    # noqa: E402

FS = 48_000

# The two-capture-stable strong mid carriers (exclude the documented marginals
# 2625/3750/6750 and the 4500 deck-notch).  These get the differential-amplitude
# enhancement ring; everything else stays pure proven DQPSK.
ENH_CARRIERS_HZ_DEFAULT = [
    750.0, 1125.0, 1500.0, 1875.0, 2250.0, 3000.0, 3375.0, 4125.0,
    5250.0, 5625.0, 6000.0, 6375.0, 7125.0,
]


# ===========================================================================
class LayeredSuperposition:
    """The TX/RX engine.  One frame = preamble + (nd+1) symbols (the +1 is the
    differential reference symbol, exactly like the proven DQPSK)."""

    def __init__(self, eps: float = 0.251, *, enh_carriers_hz=None,
                 P: int = 22):
        self.base = Dense2xScheme(P, skip=64)          # the exact r8 TX
        # PROVEN RX window: hann256_skip0 (full 256-sample symbol, 2-bin soft
        # guard).  The TX uses skip=64 (Nw=128) but the receiver that won the
        # record demods on the full Nw=256 Hann window -- using the TX skip in
        # the RX is wrong (it leaves the carriers non-orthogonal -> BER ~0.33).
        self.base_rx = Dense2xScheme(P, skip=0)        # hann256_skip0 front-end
        self.eps = float(eps)
        # two-ring amplitudes, geometric mean ~= 1 so base drive is preserved
        self.a0 = 1.0 - self.eps
        self.a1 = 1.0 + self.eps
        # log-ratio of a switch (toggle) vs a stay; the slicer threshold is half
        self.log_switch = math.log(self.a1 / self.a0)   # > 0

        fd = self.base.freqs[self.base.data_idx]         # data-carrier freqs
        enh_hz = ENH_CARRIERS_HZ_DEFAULT if enh_carriers_hz is None \
            else enh_carriers_hz
        # map each requested enh freq to the data-carrier index it sits on
        enh_local = []
        for f in enh_hz:
            j = int(np.argmin(np.abs(fd - f)))
            if abs(fd[j] - f) < 1.0:
                enh_local.append(j)
        self.enh_local = np.asarray(sorted(set(enh_local)), int)  # idx into data
        self.n_enh = len(self.enh_local)

        self.P = self.base.P
        self.base_bits_per_sym = self.base.bits_per_sym       # 2*P
        self.enh_bits_per_sym = self.n_enh                    # 1 amp bit / enh car
        self.bits_per_sym = self.base_bits_per_sym + self.enh_bits_per_sym
        self.gross_bps = self.bits_per_sym / (self.base.N / FS)
        self.name = (f"LSA_eps{self.eps:.3f}_P{self.P}_enh{self.n_enh}")

    # --- bit split ----------------------------------------------------------
    def _nd_for(self, nbits: int) -> int:
        return int(math.ceil(nbits / self.bits_per_sym))

    # === TX =================================================================
    def modulate(self, bits: np.ndarray) -> np.ndarray:
        bits = np.asarray(bits, np.uint8)
        nd = self._nd_for(len(bits))
        nbits = nd * self.bits_per_sym
        if len(bits) < nbits:
            bits = np.concatenate([bits, np.zeros(nbits - len(bits), np.uint8)])

        # ---- split: per symbol, first base_bits_per_sym are BASE, rest ENH ---
        bm = bits.reshape(nd, self.bits_per_sym)
        base_bits_flat = bm[:, :self.base_bits_per_sym]      # (nd, 2P)
        enh_bits = bm[:, self.base_bits_per_sym:]            # (nd, n_enh)

        # ---- BASE: quadrants via the proven carrier-block Gray map -----------
        # base.bits_to_quadrants expects a flat (2*P*nd) frame in carrier-major
        # block order; feed it the per-symbol base bits in that same convention.
        # Reconstruct the carrier-block-ordered flat vector: data carrier j
        # carries the j-th contiguous 2*nd-bit block (h4 bits_to_quadrants).
        # base_bits_flat[i] is symbol i's 2P bits in carrier order (c0b0 c0b1
        # c1b0 c1b1 ...).  bits_to_quadrants wants carrier-major: all of c0's
        # bits, then c1's...  -> transpose to (P, nd, 2) then ravel.
        bb = base_bits_flat.reshape(nd, self.P, 2)           # (nd, P, 2)
        bb = np.transpose(bb, (1, 0, 2)).reshape(-1)         # carrier-major flat
        q = self.base.bits_to_quadrants(bb)                  # (nd, P)
        assert q.shape == (nd, self.P)

        # ---- ENH: per enh-carrier bounded two-ring state machine -------------
        # ring index r in {0,1}; start at 0 (= reference symbol amplitude a0/a1?)
        # The reference symbol (symbol -1, the first emitted) sits at ring 0;
        # data symbol i toggles ring on enh bit 1, stays on bit 0.  amp gain of
        # data symbol i on enh-carrier = a[ring_after_symbol_i].
        total = nd + 1
        # per-symbol amplitude GAIN for every data carrier (default 1.0)
        gain = np.ones((total, self.P))
        ring = np.zeros(self.n_enh, int)                     # ref symbol at ring0
        gain[0, self.enh_local] = self._ring_amp(ring)
        for i in range(nd):
            toggle = enh_bits[i].astype(int)                 # (n_enh,)
            ring = ring ^ toggle
            gain[i + 1, self.enh_local] = self._ring_amp(ring)

        audio = self._synthesize(q, gain)
        # stash for the clean-channel inverse check / framing
        self._last_nd = nd
        return audio.astype(np.float32)

    def _ring_amp(self, ring: np.ndarray) -> np.ndarray:
        return np.where(ring == 0, self.a0, self.a1)

    def _synthesize(self, q: np.ndarray, gain: np.ndarray) -> np.ndarray:
        """Schroeder-phased DQPSK body (h4/Dense2x verbatim) with a per-symbol
        per-carrier amplitude GAIN multiplier carrying the enhancement ring."""
        base = self.base
        nd = q.shape[0]
        total = nd + 1
        nc = base.P + 1
        # phase ladder (Schroeder initial phase, pilot stays at its phi0)
        theta = np.zeros((total, nc))
        theta[0] = base._phi0()
        for i in range(1, total):
            theta[i] = theta[i - 1]
            theta[i, base.data_idx] += q[i - 1] * (np.pi / 2.0)
        # full per-(symbol,carrier) amplitude = tx_amp[k] * gain (gain=1 for
        # pilot + non-enh carriers; ring amp for enh carriers)
        nc_gain = np.ones((total, nc))
        nc_gain[:, base.data_idx] = gain                     # gain is (total, P)
        t = np.arange(total * base.N) / FS
        body = np.zeros(total * base.N)
        for k in range(nc):
            ph = 2 * np.pi * base.freqs[k] * t + np.repeat(theta[:, k], base.N)
            amp = base.tx_amp[k] * np.repeat(nc_gain[:, k], base.N)
            body += amp * np.sin(ph)
        audio = np.concatenate([base._preamble, body])
        pk = np.max(np.abs(audio))
        return audio / pk * 0.70

    # === RX =================================================================
    def demodulate(self, audio: np.ndarray, sr: int,
                   nd: int | None = None) -> np.ndarray:
        base = self.base
        rx = self.base_rx                              # hann256_skip0 RX window
        y = np.asarray(audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), rx.preamble_seconds)
        if nd is None:
            nd = getattr(self, "_last_nd", None)
        if nd is None:
            # infer from audio length (preamble + (nd+1)*N)
            body = len(y) - ds
            nd = max(1, body // rx.N - 1)
        total = nd + 1
        nc = rx.P + 1
        N, skip, Nw = rx.N, rx.skip, rx.Nw
        fpil = rx.freqs[rx.pilot_idx]
        win = rx._win
        freqs = rx.freqs

        # ---- per-symbol complex DFT with the PROVEN integer-drift EMA loop ----
        c = np.zeros((total, nc), np.complex128)
        dtau = np.zeros(total)
        drift = 0.0
        ema = 0.5
        sm = 0.0
        for i in range(total):
            b = ds + i * N + int(round(drift))
            lo = b + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS
            E = np.exp(-2j * np.pi * np.outer(freqs, tt))
            c[i] = E @ (seg * win)
            if i > 0:
                dp = float(np.angle(c[i, rx.pilot_idx] *
                                    np.conj(c[i - 1, rx.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))

        # ---- BASE: differential DQPSK decision (h4 verbatim + DD refine) -----
        fd = rx.freqs[rx.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])
        dphi = np.angle(d[:, rx.data_idx])
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
        res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_res = num / (2 * np.pi * den)
        dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
        q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4   # (nd, P)

        # base bits, per symbol, in carrier order (c0b0 c0b1 c1b0 c1b1 ...)
        base_bits_sym = self._quadrants_to_symbits(q)         # (nd, 2P)

        # ---- ENH: differential AMPLITUDE detection on the residual ring ------
        # AGC: normalise each symbol's data-carrier magnitudes by the pilot
        # magnitude (the unmodulated reference) so the slowly-varying channel
        # gain divides out.  The ring bit is the SYMBOL-TO-SYMBOL toggle of the
        # AGC'd magnitude on each enh carrier.
        mag = np.abs(c[:, rx.data_idx])                       # (total, P)
        pil = np.abs(c[:, rx.pilot_idx])[:, None]             # (total, 1)
        magn = mag / np.clip(pil, 1e-12, None)                # AGC'd (total, P)
        # also divide out the static per-carrier H/tx shape: normalise each
        # carrier by its own median over the frame (the differential ratio is
        # what carries the bit, so a per-carrier constant cancels anyway, but
        # this stabilises the log).
        ml = np.log(np.clip(magn, 1e-12, None))               # (total, P)
        dlog = ml[1:, :] - ml[:-1, :]                         # (nd, P) sym-to-sym
        thr = 0.5 * self.log_switch
        toggle = (np.abs(dlog[:, self.enh_local]) > thr).astype(np.uint8)  # (nd, n_enh)

        # ---- reassemble the bitstream: per symbol [base 2P bits | enh n_enh] -
        out = np.zeros((nd, self.bits_per_sym), np.uint8)
        out[:, :self.base_bits_per_sym] = base_bits_sym
        out[:, self.base_bits_per_sym:] = toggle
        return out.reshape(-1)[: nd * self.bits_per_sym]

    def _quadrants_to_symbits(self, q: np.ndarray) -> np.ndarray:
        """(nd, P) quadrants -> (nd, 2P) bits in per-symbol carrier order.
        Inverse of the bb construction in modulate (carrier-major -> per-sym)."""
        nd = q.shape[0]
        # use the proven inverse map then reshape back to per-symbol carrier order
        from h4_dqpsk import GRAY_DEC
        bm = np.zeros((nd, self.P, 2), np.uint8)             # (nd, P, 2)
        for qq, (a, b) in GRAY_DEC.items():
            m = (q == qq)
            bm[:, :, 0][m] = a
            bm[:, :, 1][m] = b
        return bm.reshape(nd, self.P * 2)                    # (nd, 2P)


# ===========================================================================
def _make_funcscheme(eng: LayeredSuperposition,
                     rs_k: int = 191) -> FuncScheme:
    """Wrap the engine as a FuncScheme.  The harness drives modulate with a
    fresh bit vector then demodulate(audio, FS); we recover nd from the engine's
    stashed _last_nd (set on the matching modulate call, same convention as
    evaluate.make_dqpsk_funcscheme which stashes _nbits)."""
    holder = {"nbits": None}

    def modulate(bits):
        holder["nbits"] = len(bits)
        return eng.modulate(np.asarray(bits, np.uint8))

    def demodulate(audio, sr):
        nb = holder["nbits"]
        nd = eng._nd_for(nb) if nb else None
        out = eng.demodulate(np.asarray(audio, np.float32), sr, nd=nd)
        # return exactly the requested bit count (modulate pads to a full
        # symbol; the harness compares against the unpadded tx bits)
        return out[:nb] if nb else out

    fs = FuncScheme(name=eng.name, gross_bps=float(eng.gross_bps),
                    modulate=modulate, demodulate=demodulate)
    fs.rs_k = rs_k
    fs.eng = eng
    return fs


def build(eps: float = 0.251, *, rs_k: int = 191, enh_carriers_hz=None):
    """Contract entry.  Default = conservative ~ -12 dB enhancement, RS(255,191).

    eps maps to enhancement-power-below-base ~= 20*log10(eps):
        0.40 -> -8 dB, 0.316 -> -10 dB, 0.251 -> -12 dB, 0.20 -> -14 dB.
    """
    eng = LayeredSuperposition(eps=eps, enh_carriers_hz=enh_carriers_hz)
    return _make_funcscheme(eng, rs_k=rs_k)


if __name__ == "__main__":
    # Quick clean-channel self-check across the power sweep.
    import warnings
    warnings.filterwarnings("ignore")
    for eps in (0.40, 0.316, 0.251, 0.20):
        fs = build(eps)
        rng = np.random.default_rng(0)
        bits = rng.integers(0, 2, 4000, dtype=np.uint8)
        audio = fs.modulate(bits)
        rx = fs.demodulate(np.asarray(audio, np.float32), 48000)
        m = min(len(bits), len(rx))
        ber = float(np.mean(bits[:m] != rx[:m])) + (len(bits) - m) / len(bits)
        print(f"eps={eps:.3f} (~{20*np.log10(eps):+.1f} dB)  gross={fs.gross_bps:.0f}"
              f"  clean BER={ber:.2e}  n_enh={fs.eng.n_enh}")
