"""sc-dfe-tcm-blockcoherent  (queue rank 7 -- the MOONSHOT, lever L8).

V.34-style SINGLE-CARRIER QAM modem with a fractionally-spaced (T/2) adaptive
DECISION-FEEDBACK EQUALIZER and a decision-directed carrier-recovery PLL.

Rationale (briefing L8): the reverb tail (tau=7.9 ms) + diffuse cross-bin floor
that KILL OFDM are *convolutional ISI* -- exactly what a DFE inverts natively.
The slow per-tone phase drift (69-78 deg / 4 s == ~0.07 deg/ms) is tracked by a
decision-directed carrier loop (here: a per-symbol DD phase estimator inside the
equalizer adaptation, which is the V.34 way).

PHY chain
---------
TX:  hyp_common up-chirp preamble (sync anchor)
   + a known PN TRAINING burst of QPSK symbols (equalizer convergence, data-aided)
   + the payload QAM symbol stream
   all RRC-pulse-shaped (beta=0.25) at `baud` and up-converted to `fc`.

RX:  find_preamble (coarse sync, no oracle)
   -> complex down-convert at the NOMINAL carrier  -> matched RRC filter
   -> build a fractionally-spaced (T/2) sample stream
   -> coarse symbol-timing search on the training burst (peak training-energy)
   -> T/2 FFE + symbol-spaced DFE, LMS, data-aided on the PN burst then
      decision-directed on the payload, with a per-symbol decision-directed
      carrier phase de-rotation (the carrier loop) folded into the update
   -> QAM slice + Gray demap.

`build(...)` is parameterised so the screening driver can sweep
{baud, bits_per_sym, fc}.  `build()` with no args returns the headline rung
(4800 baud, 16-QAM, fc=3500 -> 19200 gross).

The clean-channel self-check (modulate->demodulate, NO channel) MUST invert to
BER < 1e-3 or the modem is BROKEN.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc  # noqa: E402  (frozen preamble: make_preamble/find_preamble)

FS = 48_000


# ---------------------------------------------------------------------------
# Pulse shaping
# ---------------------------------------------------------------------------
def rrc_taps(beta: float, sps: int, span_syms: int) -> np.ndarray:
    """Root-raised-cosine FIR, `sps` samples/symbol, +/-`span_syms` symbols.

    Energy-normalised (sum h^2 = 1) so the matched cascade rrc*rrc is a unit-peak
    Nyquist RC pulse (zero ISI at integer symbol offsets)."""
    n = span_syms * sps
    t = np.arange(-n, n + 1, dtype=np.float64) / sps  # symbol periods
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1.0 - beta + 4.0 * beta / np.pi
        elif beta > 0 and abs(abs(ti) - 1.0 / (4.0 * beta)) < 1e-9:
            h[i] = (beta / np.sqrt(2.0)) * (
                (1.0 + 2.0 / np.pi) * np.sin(np.pi / (4.0 * beta))
                + (1.0 - 2.0 / np.pi) * np.cos(np.pi / (4.0 * beta))
            )
        else:
            num = (np.sin(np.pi * ti * (1.0 - beta))
                   + 4.0 * beta * ti * np.cos(np.pi * ti * (1.0 + beta)))
            den = np.pi * ti * (1.0 - (4.0 * beta * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt(np.sum(h ** 2))


# ---------------------------------------------------------------------------
# Gray-coded square QAM
# ---------------------------------------------------------------------------
def _gray_axis(bits_per_axis: int):
    m = 1 << bits_per_axis
    levels = np.arange(-(m - 1), m, 2, dtype=np.float64)   # -(m-1)..(m-1) step 2
    s2l = np.zeros(m)                  # bit-group value -> level
    gidx2bits = {}                     # gray index (level position) -> bit-group
    for b in range(m):
        gray = b ^ (b >> 1)
        s2l[b] = levels[gray]
        gidx2bits[gray] = b
    return levels, s2l, gidx2bits


class QAMMap:
    """Square QAM (QPSK/16/64) with Gray mapping and a hard slicer."""

    def __init__(self, bits_per_sym: int):
        assert bits_per_sym in (2, 4, 6)
        self.bits_per_sym = bits_per_sym
        self.bpa = bits_per_sym // 2
        self.levels, self.s2l, self.gidx2bits = _gray_axis(self.bpa)
        self.m = len(self.levels)
        e = np.mean(self.levels ** 2) * 2.0      # avg symbol energy (I^2+Q^2)
        self.scale = 1.0 / np.sqrt(e)            # -> unit average power

    def map(self, bits: np.ndarray) -> np.ndarray:
        b = np.asarray(bits, np.uint8)
        bps, bpa = self.bits_per_sym, self.bpa
        nsym = len(b) // bps
        b = b[: nsym * bps].reshape(nsym, bps)
        wi = 1 << np.arange(bpa - 1, -1, -1)
        i_idx = (b[:, :bpa] * wi).sum(axis=1)
        q_idx = (b[:, bpa:] * wi).sum(axis=1)
        return (self.s2l[i_idx] + 1j * self.s2l[q_idx]) * self.scale

    def _slice_axis(self, x: np.ndarray) -> np.ndarray:
        m = self.m
        return np.clip(np.round((x + (m - 1)) / 2.0), 0, m - 1) * 2 - (m - 1)

    def slice(self, sym: np.ndarray) -> np.ndarray:
        z = np.asarray(sym) / self.scale
        return (self._slice_axis(z.real) + 1j * self._slice_axis(z.imag)) * self.scale

    def demap(self, sym: np.ndarray) -> np.ndarray:
        z = np.asarray(sym) / self.scale
        I = self._slice_axis(z.real).astype(int)
        Q = self._slice_axis(z.imag).astype(int)
        m, bpa = self.m, self.bpa
        gi = ((I + (m - 1)) // 2)
        gq = ((Q + (m - 1)) // 2)
        out = np.zeros((len(sym), self.bits_per_sym), np.uint8)
        for k in range(len(sym)):
            bi = self.gidx2bits[int(gi[k])]
            bq = self.gidx2bits[int(gq[k])]
            for j in range(bpa):
                out[k, j] = (bi >> (bpa - 1 - j)) & 1
                out[k, bpa + j] = (bq >> (bpa - 1 - j)) & 1
        return out.reshape(-1)


# ---------------------------------------------------------------------------
# Single-carrier modem
# ---------------------------------------------------------------------------
class SCModem:
    def __init__(self, *, baud: int, bits_per_sym: int, fc: float,
                 beta: float = 0.25, span_syms: int = 10,
                 n_train: int = 3000, ffe_taps: int = 41, dfe_taps: int = 12,
                 mu_train: float = 4e-3, mu_dd: float = 6e-4,
                 carrier_bw: float = 0.02, train_seed: int = 12345):
        assert FS % baud == 0, "baud must divide 48000 for integer sps"
        self.baud = baud
        self.bits_per_sym = bits_per_sym
        self.fc = float(fc)
        self.beta = beta
        self.span_syms = span_syms
        self.sps = FS // baud
        assert self.sps % 2 == 0, "need even sps for a T/2 fractionally-spaced FFE"
        self.n_train = n_train
        self.ffe_taps = ffe_taps           # at T/2 spacing
        self.dfe_taps = dfe_taps
        self.mu_train = mu_train
        self.mu_dd = mu_dd
        self.carrier_bw = carrier_bw       # DD phase tracker EMA coefficient
        self.qam = QAMMap(bits_per_sym)
        self.q4 = QAMMap(2)                # training is QPSK (constant modulus)
        self.rrc = rrc_taps(beta, self.sps, span_syms)
        rng = np.random.default_rng(train_seed)
        self.train_bits = rng.integers(0, 2, size=2 * n_train, dtype=np.uint8)
        self.train_syms = self.q4.map(self.train_bits)     # n_train QPSK symbols
        self.preamble = np.asarray(hc.make_preamble(), np.float64)
        self.pre_secs = hc.PREAMBLE_SECONDS
        self._gap = int(0.02 * FS)

    @property
    def gross_bps(self) -> float:
        return float(self.baud * self.bits_per_sym)

    # -- TX ------------------------------------------------------------------
    def modulate(self, bits: np.ndarray) -> np.ndarray:
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        self._last_payload_syms = len(bits) // bps
        data_syms = self.qam.map(bits)
        syms = np.concatenate([self.train_syms, data_syms])
        up = np.zeros(len(syms) * self.sps, np.complex128)
        up[:: self.sps] = syms
        shaped = np.convolve(up, self.rrc)                 # complex baseband
        n = np.arange(len(shaped))
        car = np.exp(2j * np.pi * self.fc * n / FS)
        body = (shaped * car).real * np.sqrt(2.0)
        gap = np.zeros(self._gap, np.float64)
        out = np.concatenate([self.preamble, gap, body])
        out = out / (np.max(np.abs(out)) + 1e-12) * 0.6
        return out.astype(np.float32)

    # -- RX ------------------------------------------------------------------
    def _baseband(self, audio: np.ndarray, start: int) -> np.ndarray:
        """Down-convert from `start` and matched-RRC filter -> complex baseband
        at the line rate.  The carrier index is referenced to `start` so it
        matches the TX carrier phase reference at the body start only if start ==
        body start; the residual constant phase is removed by the equalizer /
        carrier loop, so an exact-sample lock is not required."""
        y = np.asarray(audio, np.float64)[start:]
        n = np.arange(len(y))
        lo = np.exp(-2j * np.pi * self.fc * (n + start) / FS) * np.sqrt(2.0)
        bb = y * lo
        return np.convolve(bb, self.rrc)                   # matched filter

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        assert sr == FS
        ds = hc.find_preamble(np.asarray(audio, np.float32), self.pre_secs)
        body0 = ds + self._gap
        mf = self._baseband(np.asarray(audio, np.float64), body0)

        sps = self.sps
        half = sps // 2
        # The matched cascade peaks at symbol centres located at an unknown
        # integer offset near rrc_delay = len(rrc)-1 (RX 'full' conv group
        # delay).  Search integer offsets over +-1 symbol and lock to the offset
        # whose training-symbol stream has the highest mean power (constant-
        # modulus training -> max energy + open eye at the right phase).
        rrc_delay = len(self.rrc) - 1
        best = None
        for off in range(-sps, sps + 1):
            base = rrc_delay + off
            if base < half:
                continue
            centre = mf[base:: sps]
            if len(centre) < self.n_train + 50:
                continue
            tr = centre[: self.n_train]
            metric = np.mean(np.abs(tr) ** 2)
            if best is None or metric > best[0]:
                best = (metric, base)
        if best is None:
            return np.zeros(0, np.uint8)
        base = best[1]

        # Fractionally-spaced (T/2) input: two streams half a symbol apart,
        # interleaved so the FFE sees 2 samples/symbol.
        n_data = getattr(self, "_last_payload_syms", None)
        bits = self._fse_dfe(mf, base, half, n_data)
        return bits

    def _fse_dfe(self, mf: np.ndarray, base: int, half: int, n_data_syms):
        """T/2 fractionally-spaced FFE + symbol-spaced DFE with a per-symbol
        decision-directed carrier-phase tracker.

        FFE input per symbol k: the `ffe_taps` T/2 samples centred on symbol k,
        i.e. samples mf[base + k*sps + j*half] for j in a window.  DFE feeds back
        past DECISIONS.  Carrier phase theta is tracked from the post-equalizer
        decision error and de-rotates the equalizer output each symbol."""
        sps = self.sps
        Nf = self.ffe_taps                       # T/2 taps
        Nb = self.dfe_taps
        # number of available symbols
        max_k = (len(mf) - base) // sps - 2
        if max_k <= self.n_train + 1:
            return np.zeros(0, np.uint8)
        total_syms = max_k
        if n_data_syms is not None:
            total_syms = min(total_syms, self.n_train + n_data_syms)

        # Pre-extract the T/2 sample matrix: for each symbol k, the FFE window is
        # centred at the symbol centre.  Use Nf T/2-spaced samples symmetric
        # about the centre.
        # T/2 sample positions for symbol k, tap j (j=0..Nf-1):
        #   pos = base + k*sps + (j - Nf//2)*half
        j_off = (np.arange(Nf) - Nf // 2) * half
        ffe = np.zeros(Nf, np.complex128)
        ffe[Nf // 2] = 1.0                       # centre-spike init
        dfe = np.zeros(Nb, np.complex128)
        past_dec = np.zeros(Nb, np.complex128)   # last Nb decisions (newest at 0)
        theta = 0.0                              # carrier phase estimate
        out_bits = []

        q4, qam = self.q4, self.qam
        train = self.train_syms
        for k in range(total_syms):
            centre = base + k * sps
            pos = centre + j_off
            if pos[0] < 0 or pos[-1] >= len(mf):
                break
            x = mf[pos]                          # FFE input vector
            y = ffe @ x - dfe @ past_dec         # equalized symbol (pre-derotate)
            yr = y * np.exp(-1j * theta)         # carrier de-rotation
            if k < self.n_train:
                d = train[k]
                mu = self.mu_train
            else:
                d = qam.slice(yr)
                mu = self.mu_dd
            err = d - yr                         # decision error (post-rotate)
            # carrier loop: DD phase error = angle(yr * conj(d))
            ph_err = np.angle(yr * np.conj(d)) if abs(d) > 1e-9 else 0.0
            theta += self.carrier_bw * ph_err
            # LMS updates use the de-rotated error mapped back through the
            # carrier phase (standard joint equalizer+carrier update):
            e_rot = err * np.exp(1j * theta)
            ffe += mu * e_rot * np.conj(x)
            dfe -= mu * e_rot * np.conj(past_dec)
            # shift decision history
            past_dec = np.roll(past_dec, 1)
            past_dec[0] = d
            if k >= self.n_train:
                out_bits.append(qam.demap(np.array([yr]))[0:self.bits_per_sym])
        if not out_bits:
            return np.zeros(0, np.uint8)
        return np.concatenate(out_bits).astype(np.uint8)


# ---------------------------------------------------------------------------
# FuncScheme builder
# ---------------------------------------------------------------------------
def build(baud: int = 4800, bits_per_sym: int = 4, fc: float = 3500.0,
          **kw):
    """Return a hyp_common.FuncScheme for the single-carrier QAM modem."""
    from hyp_common import FuncScheme
    m = SCModem(baud=baud, bits_per_sym=bits_per_sym, fc=fc, **kw)

    def modulate(bits):
        return m.modulate(bits)

    def demodulate(audio, sr):
        return m.demodulate(audio, sr)

    nm = f"SC_{bits_per_sym}b_{baud}baud_fc{int(fc)}"
    fs = FuncScheme(name=nm, gross_bps=m.gross_bps,
                    modulate=modulate, demodulate=demodulate)
    fs.modem = m
    fs.rs_k = None
    return fs


if __name__ == "__main__":
    fs = build()
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), 48000)
    n = min(len(bits), len(rx))
    ber = np.mean(bits[:n] != rx[:n]) if n else 1.0
    print(f"{fs.name} gross={fs.gross_bps} clean BER={ber:.4g} "
          f"(tx_syms={len(bits)//bits_per_sym if (bits_per_sym:=4) else 0}, rx_bits={len(rx)})")
