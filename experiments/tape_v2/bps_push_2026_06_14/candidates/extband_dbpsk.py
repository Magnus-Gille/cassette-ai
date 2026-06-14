"""extband_dbpsk.py -- candidate "extband-dbpsk" (queue rank 4, lever L5).

ADDITIVE on top of the PROVEN r8 (Dense2xScheme P22, the 5791 record): keep the
22 base carriers (750..9000 Hz, 375 Hz grid) as DQPSK (2 bits/carrier) EXACTLY
as r8, and ADD up to N_ext extension-band carriers above 9000 Hz on the SAME
375 Hz grid (9375, 9750, 10125, 10500, [10875, 11250]) each carrying 1-bit
DBPSK (90 deg decision boundary).

Why DBPSK, not DQPSK, in the ext band (briefing #4.3):
  the timing slope c1 ~= 0.00368 deg/Hz  x ~10 kHz ~= 37 deg eats the DQPSK
  45-deg decision boundary above ~9 kHz; DBPSK's 90-deg boundary survives the
  static slope, and the symbol-to-symbol differential op cancels it to first
  order anyway.  Channel phase jitter on tape10 is only ~11 deg RMS at these
  freqs (measured, _replay_cache/tape10_measure.json), far inside 90 deg.

gross = 8250 (the 22 DQPSK carriers) + N_ext * 1 * 187.5.
  N_ext=4 -> 9000 gross.  N_ext=2 -> 8625.  N_ext=6 -> 9375.

PHY reuse (no sync/pilot reinvention):
  * TX = the exact h4/Dense2x Schroeder continuous-phase multitone modulator,
    extended to the wider carrier grid; the base-22 DQPSK phase ladder is
    byte-identical to Dense2xScheme.modulate, the ext carriers just add a 0/pi
    increment instead of 0/pi/2/3pi/2.
  * Sync = hyp_common.make_preamble / find_preamble (the proven chirp), inherited
    via the preamble baked into modulate().
  * RX = the exact h4 EMA pilot-tracking integer-window-drift DFT loop (pilot @
    4875 Hz de-rotates flutter dtau on every carrier); base carriers sliced into
    DQPSK quadrants, ext carriers sliced into DBPSK bits (sign of the de-rotated
    differential real part).  No coherent/absolute phase anywhere.

The ext band gets a TX power boost (EXT_BOOST_DB) on top of the H(f) pre-emphasis
to offset the HF rolloff, exactly as the queue config specifies.

Build via build() -> FuncScheme.  N_ext / boost are module constants so the
screen can sweep them (see __main__).
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
import real_channel_sim as rcs                           # noqa: E402
from hyp_common import FuncScheme                         # noqa: E402
from h4_dqpsk import DQPSKScheme, FS, GRAY_ENC, GRAY_DEC  # noqa: E402

D2X_N = 256
D2X_SPACING = 2          # 2 bins @ N=256 = 375 Hz grid
D2X_SKIP_TX = 64         # TX Nw=128 (only sets the scheme asserts on TX)
D2X_SKIP_RX = 0          # RX hann256_skip0 (2-bin soft guard) -- the proven r8 RX
D2X_MIN_SPACING = 375.0
PILOT_HZ = 4875.0        # the proven m8_dense375 pilot (grid center, idx 11 @ P22)
RS_K = 179               # the r8 outer code (gross*179/255)

# ext band: contiguous on the SAME 375 Hz grid above 9000 Hz
EXT_FREQS_ALL = [9375.0, 9750.0, 10125.0, 10500.0, 10875.0, 11250.0]
EXT_BOOST_DB = 3.0       # extra TX power on the ext carriers (queue config)

GRAY_ENC = dict(GRAY_ENC)
GRAY_DEC = dict(GRAY_DEC)


class ExtBandDBPSKScheme:
    """r8 Dense2x P22 DQPSK base + N_ext 1-bit DBPSK ext-band carriers.

    Carrier layout (375 Hz grid, df = FS/N = 187.5 Hz, spacing=2 bins):
        base:  750 .. 9000 Hz  (23 bins incl. pilot @ 4875) -> 22 DQPSK data
        ext :  9375 .. (9000 + 375*N_ext) Hz                -> N_ext DBPSK data

    Bit order in a frame, carrier-block mapping (same convention as
    DQPSKScheme.bits_to_quadrants): the first 22 contiguous (2*nd)-bit blocks
    feed the 22 DQPSK carriers (2 bits/sym each), then N_ext contiguous nd-bit
    blocks feed the ext DBPSK carriers (1 bit/sym each).  A dead carrier corrupts
    one contiguous slice of the frame -> RS-friendly.
    """

    def __init__(self, n_ext: int = 4, *, ext_boost_db: float = EXT_BOOST_DB,
                 rs_k: int = RS_K):
        assert 0 <= n_ext <= len(EXT_FREQS_ALL), n_ext
        self.n_ext = int(n_ext)
        self.ext_boost_db = float(ext_boost_db)
        self.rs_k = int(rs_k)
        self.N = D2X_N
        self.spacing = D2X_SPACING
        self.skip = D2X_SKIP_RX
        df = FS / self.N
        b0 = int(round(750.0 / df))

        # --- base 22-carrier DQPSK grid (identical to Dense2xScheme P22) ------
        P_base = 22
        nc_base = P_base + 1                 # 23 carriers incl pilot
        base_bins = b0 + self.spacing * np.arange(nc_base)
        base_freqs = base_bins * df
        # pilot is the grid-center carrier (nc//2 -> idx 11 -> 4875 Hz), matching
        # Dense2xScheme exactly.
        pilot_idx = nc_base // 2
        assert abs(base_freqs[pilot_idx] - PILOT_HZ) < 1e-6, base_freqs[pilot_idx]

        # --- ext carriers (continue the SAME grid above 9000 Hz) -------------
        ext_bins = b0 + self.spacing * (nc_base + np.arange(self.n_ext))
        ext_freqs = ext_bins * df
        if self.n_ext:
            assert abs(ext_freqs[0] - 9375.0) < 1e-6, ext_freqs[0]
            for got, want in zip(ext_freqs, EXT_FREQS_ALL):
                assert abs(got - want) < 1e-6, (got, want)

        # --- assembled carrier set: [base 23] + [ext n_ext] ------------------
        self.bins = np.concatenate([base_bins, ext_bins]).astype(int)
        self.freqs = np.concatenate([base_freqs, ext_freqs]).astype(np.float64)
        nc = len(self.freqs)
        self.pilot_idx = int(pilot_idx)
        # data carriers: every non-pilot carrier
        self.data_idx = np.array([i for i in range(nc) if i != self.pilot_idx])
        # which data carriers are DQPSK (base) vs DBPSK (ext)
        self.dqpsk_idx = np.array([i for i in self.data_idx if i < nc_base])
        self.dbpsk_idx = np.array([i for i in self.data_idx if i >= nc_base],
                                  dtype=int)
        assert len(self.dqpsk_idx) == P_base
        assert len(self.dbpsk_idx) == self.n_ext

        # bits per symbol: 2 per DQPSK carrier + 1 per DBPSK carrier
        self.bits_per_sym = 2 * P_base + 1 * self.n_ext
        self.gross_bps = self.bits_per_sym / (self.N / FS)
        self.P = len(self.data_idx)               # total data carriers
        self._P_base = P_base

        # --- orthogonality guard over the RX window --------------------------
        self.Nw = self.N - 2 * self.skip          # 256 @ skip0
        assert (self.spacing * self.Nw) % self.N == 0, (
            "carriers not orthogonal over analysis window")
        self._win = np.hanning(self.Nw)

        # --- preamble (the proven chirp) -------------------------------------
        self._preamble = hc.make_preamble(0.25).astype(np.float64)
        self.preamble_seconds = 0.25
        self.name = f"ExtDBPSK_P22+{self.n_ext}ext_N256_sp2_rs{self.rs_k}"

        # --- TX pre-emphasis (the published master3 H(f), same as r8) + the
        #     ext-band boost --------------------------------------------------
        params = rcs.load_params()
        Hf = params["Hf_magnitude"]
        fm = np.asarray(Hf["sounder_freqs_master3"], float)
        Hd = np.asarray(Hf["H_db_master3"], float)
        Hl = 10.0 ** (np.interp(self.freqs, fm, Hd) / 20.0)
        Hl = Hl / (Hl.max() + 1e-12)
        tx_amp = 1.0 / np.clip(Hl, 0.05, None)
        # extra boost on the ext carriers only
        if self.n_ext:
            tx_amp[self.dbpsk_idx] *= 10.0 ** (self.ext_boost_db / 20.0)
        self.tx_amp = (tx_amp / tx_amp.max()).astype(np.float64)

    # ---- Schroeder per-carrier static initial phase (differential-invariant) -
    def _phi0(self):
        nc = len(self.freqs)
        k = np.arange(nc, dtype=np.float64)
        return -np.pi * k * k / nc

    # ---- bit packing --------------------------------------------------------
    def nsym_data(self, nbits: int) -> int:
        return int(math.ceil(nbits / self.bits_per_sym))

    def _pack_symbols(self, bits: np.ndarray):
        """frame bits -> (q_dq (nd, 22) quadrant idx, b_ext (nd, n_ext) bit).

        carrier-block mapping: 22 contiguous 2*nd-bit DQPSK blocks first, then
        n_ext contiguous nd-bit DBPSK blocks."""
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        nd = len(bits) // bps
        n_dq_bits = 2 * self._P_base * nd
        dq_bits = bits[:n_dq_bits].reshape(self._P_base, nd, 2)   # carrier-major
        q = np.zeros((nd, self._P_base), int)
        for (a, b), qq in GRAY_ENC.items():
            q[((dq_bits[:, :, 0] == a) & (dq_bits[:, :, 1] == b)).T] = qq
        ext_bits = bits[n_dq_bits:].reshape(self.n_ext, nd)        # carrier-major
        b_ext = ext_bits.T.astype(int)                            # (nd, n_ext)
        return q, b_ext

    def _unpack_symbols(self, q: np.ndarray, b_ext: np.ndarray) -> np.ndarray:
        """inverse of _pack_symbols -> frame bits."""
        nd = q.shape[0]
        dq_bits = np.zeros((self._P_base, nd, 2), np.uint8)
        for qq, (a, b) in GRAY_DEC.items():
            m = (q == qq).T
            dq_bits[:, :, 0][m] = a
            dq_bits[:, :, 1][m] = b
        dq_flat = dq_bits.reshape(-1)
        if self.n_ext:
            ext_flat = b_ext.T.astype(np.uint8).reshape(-1)       # carrier-major
            return np.concatenate([dq_flat, ext_flat])
        return dq_flat

    # ---- modulate -----------------------------------------------------------
    def modulate(self, bits: np.ndarray) -> np.ndarray:
        q, b_ext = self._pack_symbols(bits)
        nd = q.shape[0]
        total = nd + 1                        # +1 reference symbol
        nc = len(self.freqs)
        theta = np.zeros((total, nc))
        theta[0] = self._phi0()
        for i in range(1, total):
            theta[i] = theta[i - 1]
            # DQPSK carriers: increment by q*pi/2
            theta[i, self.dqpsk_idx] += q[i - 1] * (np.pi / 2.0)
            # DBPSK carriers: increment by bit*pi
            if self.n_ext:
                theta[i, self.dbpsk_idx] += b_ext[i - 1] * np.pi
        t = np.arange(total * self.N) / FS
        body = np.zeros(total * self.N)
        for k in range(nc):
            ph = 2 * np.pi * self.freqs[k] * t + np.repeat(theta[:, k], self.N)
            body += self.tx_amp[k] * np.sin(ph)
        audio = np.concatenate([self._preamble, body])
        pk = np.max(np.abs(audio))
        return (audio / pk * 0.70).astype(np.float32)

    # ---- demodulate (h4 EMA pilot-tracking DFT loop, mixed slicer) ----------
    def _demod_window(self, win_audio: np.ndarray, nd: int):
        """Returns (q (nd,22), b_ext (nd,n_ext)). h4-identical front-end."""
        y = np.asarray(win_audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), self.preamble_seconds)
        total = nd + 1
        nc = len(self.freqs)
        N, skip, Nw = self.N, self.skip, self.Nw
        fpil = self.freqs[self.pilot_idx]
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
            E = np.exp(-2j * np.pi * np.outer(self.freqs, tt))
            c[i] = E @ (seg * self._win)
            if i > 0:
                dp = float(np.angle(c[i, self.pilot_idx] *
                                    np.conj(c[i - 1, self.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))

        d = c[1:, :] * np.conj(c[:-1, :])          # (nd, nc)

        # --- DQPSK base carriers (refined, h4-identical) ---------------------
        fdq = self.freqs[self.dqpsk_idx]
        dphi = np.angle(d[:, self.dqpsk_idx])
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fdq)
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
        # one-shot decision-directed common-timing refinement (h4-identical),
        # estimated on the DQPSK carriers (the dense, reliable set)
        res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fdq[None, :]).sum(axis=1)
        den = (fdq ** 2).sum()
        dtau_res = num / (2 * np.pi * den)          # (nd,)
        dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fdq[None, :]
        q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4

        # --- DBPSK ext carriers ---------------------------------------------
        if self.n_ext:
            fext = self.freqs[self.dbpsk_idx]
            dphi_e = np.angle(d[:, self.dbpsk_idx])
            # de-rotate by the SAME pilot dtau + the DD common-timing residual
            dphi_e = dphi_e - 2 * np.pi * np.outer(dtau[1:], fext)
            dphi_e = dphi_e - 2 * np.pi * dtau_res[:, None] * fext[None, :]
            # DBPSK: bit=1 if phase increment is pi (Re < 0), else 0
            b_ext = (np.cos(dphi_e) < 0.0).astype(int)   # (nd, n_ext)
        else:
            b_ext = np.zeros((nd, 0), int)
        return q, b_ext

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        nd = self._nd_hint
        q, b_ext = self._demod_window(np.asarray(audio, np.float64), nd)
        return self._unpack_symbols(q, b_ext).astype(np.uint8)


# ===========================================================================
def build(n_ext: int = 4, *, ext_boost_db: float = EXT_BOOST_DB,
          rs_k: int = RS_K) -> FuncScheme:
    """Return a hyp_common.FuncScheme for the ext-band DBPSK candidate.

    The FuncScheme.demodulate(audio, sr) signature gives no nd; the harness sets
    payload bit count via modulate's closure (mirrors make_dqpsk_funcscheme), so
    we recover nd from the bit count the same way.
    """
    sch = ExtBandDBPSKScheme(n_ext, ext_boost_db=ext_boost_db, rs_k=rs_k)

    state = {"nbits": 0}

    def modulate(bits: np.ndarray) -> np.ndarray:
        bits = np.asarray(bits, np.uint8)
        state["nbits"] = len(bits)
        return np.asarray(sch.modulate(bits), np.float32)

    def demodulate(audio: np.ndarray, sr: int) -> np.ndarray:
        sch._nd_hint = sch.nsym_data(state["nbits"])
        return sch.demodulate(audio, sr)

    fs = FuncScheme(name=sch.name, gross_bps=float(sch.gross_bps),
                    modulate=modulate, demodulate=demodulate)
    fs.rs_k = sch.rs_k
    fs.tx_scheme = sch
    fs._sch = sch
    return fs


if __name__ == "__main__":
    import json

    # ---- mandatory clean-channel self-check (RED/GREEN) -------------------
    print("== clean-channel self-check ==", flush=True)
    for ne in (2, 4, 6):
        fs = build(ne)
        rng = np.random.default_rng(0)
        bits = rng.integers(0, 2, 4000, dtype=np.uint8)
        audio = fs.modulate(bits)
        rx = fs.demodulate(np.asarray(audio, np.float32), 48000)
        m = min(len(bits), len(rx))
        ber = float(np.mean(bits[:m] != rx[:m]))
        print(f"  n_ext={ne} gross={fs.gross_bps:.0f} clean_ber={ber:.2e}",
              flush=True)
        assert ber < 1e-3, f"clean BER {ber} (n_ext={ne}) -- not invertible"
    print("  clean-channel self-check PASSED", flush=True)
