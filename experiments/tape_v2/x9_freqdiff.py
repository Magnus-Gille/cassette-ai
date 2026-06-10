r"""x9_freqdiff.py -- FREQUENCY-DIFFERENTIAL DQPSK (master9 lottery rung M9a).

The distinctive bet no scaler ladder carries.  The proven DQPSK record encodes
2 bits/carrier as a phase increment SYMBOL-TO-SYMBOL on the SAME carrier
(time-differential).  That mapping is killed by symbol-timing jitter: the binding
impairment that caps the 934 bps record (R2 min margin 0.04 deg; R6 Table B:
real per-symbol phase noise ~85 deg @ N512).  This module instead encodes 2 bits
on the phase DIFFERENCE BETWEEN ADJACENT CARRIERS *within one symbol*, so common
symbol-timing jitter cancels identically.

THE TIMING-IMMUNITY DERIVATION (the whole point of this rung)
------------------------------------------------------------
A symbol-timing error tau shifts the per-symbol analysis window.  The cassette
channel's flutter is a resampling trajectory y(t) = x(t - tau(t)) (R6 1a), so a
tone at frequency f sampled with window-timing error tau acquires a measured DFT
phase term  -2*pi*f*tau  (the same 2*pi*f*tau the pilot loop tracks).  Write the
measured per-symbol carrier phase as

    phase(c[i,k]) = phi_data[i,k]  +  theta_chan(f_k)  -  2*pi*f_k*tau_i

where phi_data is the modulation, theta_chan(f_k) is the static channel phase at
f_k (reverb IR + EQ + AAC), and tau_i is the timing error of symbol i.

  * TIME-DIFFERENTIAL (h4, the record):  d = angle(c[i,k] * conj(c[i-1,k]))
        d = dphi_data  +  0  -  2*pi*f_k*(tau_i - tau_{i-1})
          = dphi_data  -  2*pi*f_k * Dtau
    The static theta_chan(f_k) cancels (same carrier), GOOD -- but the timing
    term is  -2*pi*f_k*Dtau, proportional to the symbol-to-symbol timing CHANGE
    Dtau.  Dtau is exactly the flutter jitter the tracker fights; its residual is
    what eats the QPSK margin.  This term does NOT vanish.  *Worse at high f_k.*

  * FREQUENCY-DIFFERENTIAL (THIS module):  d = angle(c[i,k] * conj(c[i,k-1]))
    Both carriers are in the SAME symbol i, so they share the SAME tau_i:
        d = dphi_data  +  (theta_chan(f_k) - theta_chan(f_{k-1}))
              -  2*pi*(f_k - f_{k-1})*tau_i
          = dphi_data  +  dtheta_chan  -  2*pi*SPACING*tau_i
    Because f_k - f_{k-1} = SPACING is the SAME (750 Hz) for every adjacent pair,
    the timing term  dphi_timing = -2*pi*SPACING*tau_i  is a CONSTANT PER ADJACENT
    PAIR -- it does not depend on the carrier index k, only on SPACING and the
    common per-symbol timing tau_i.  Common symbol-timing jitter therefore appears
    as ONE identical rotation shared by all data pairs in a symbol, removable by a
    band-edge phase reference (carrier 0) or any one known training pair.  The
    fast per-symbol Dtau wander that caps the time-differential record simply
    DOES NOT MAP onto the frequency-differential decision.  Timing jitter stops
    mattering -- that is the paradigm result M9a probes.

The price (honest):  frequency-differential trades timing-immunity for sensitivity
to the FREQUENCY-SELECTIVE channel tilt dtheta_chan between adjacent carriers
750 Hz apart.  R2 sec.3 shows per-carrier EVM up to 0.41 and amp CoV up to 27 %
(the 3750 Hz deck null), so dtheta_chan is real and must be DE-ROTATED per pair
using the sounder-measured H(f) phase tilt before slicing.  The 3750 Hz null
corrupts BOTH pairs touching it, so those pairs are flagged (erasure-eligible).

PHY (M9a, per MASTER9_PLAN sec.1.3 / C_design R-LOT)
----------------------------------------------------
  * P11 carriers + 1 pilot on the proven N512 sp8 = 750 Hz grid:
        {750,1500,2250,3000,3750,4500,5250,6000,6750,7500,8250,9000} Hz
    pilot = 4500 Hz (mid-band, unmodulated -- window-drift tracking ONLY, never a
    data carrier, exactly as the proven record's self-tracking rule requires).
  * chain = the other 11 carriers {750..3750, 5250..9000}; carrier 0 = 750 Hz is
    the band-edge per-symbol PHASE REFERENCE (its absolute phase carries no data).
  * data = QPSK on the 10 adjacent-carrier phase differences within each symbol
        bits[pair j] = quadrant of angle(c[i, chain[j]] * conj(c[i, chain[j-1]]))
    10 pairs * 2 bits = 20 bits/symbol = the SAME gross as the record's 10 carriers
    (gross = 2*10/(N/FS) = 1875 bps; net @ RS159 = 1169 bps), but timing-immune.

API: mirrors h4_dqpsk.DQPSKScheme so m9_master / m9_decode drop it in --
    modulate(bits) -> float32 audio with the 0.25 s chirp preamble
    demod(win_audio, nd, ...) -> (bits, diag)
plus bits_to_quadrants / quadrants_to_bits / nsym_data / gross_bps / name /
freqs / data_idx / pilot_idx for parity with the time-differential scheme.

Channel / payload: identical to h4 (sim_v2.channel_v2; m3_codec RS frames; h9 pack).
Truth (the payload) is used ONLY for scoring, never inside demod.
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc           # noqa: E402  (preamble + find_preamble, shared)
import real_channel_sim as rcs    # noqa: E402  (published master3 H(f) for TX pre-emph)

FS = 48_000

# Gray map: (bit_a, bit_b) -> quadrant q ; dphi = q * pi/2.  Same table as h4 so a
# decoded F-DQPSK frame interleaves byte-for-byte identically with the RS layer.
GRAY_ENC = {(0, 0): 0, (0, 1): 1, (1, 1): 2, (1, 0): 3}
GRAY_DEC = {v: k for k, v in GRAY_ENC.items()}

# Null carriers the chain skips at the *frequency-differential* level: a pair that
# touches a stationary deck null has a corrupt dtheta_chan that the sounder tilt
# cannot fully undo, so it is flagged erasure-eligible.  3750 Hz is the measured
# m8 null (R2 sec.0: 35 % of all raw errors from that one carrier).
NULL_FREQS_HZ = (3750.0,)


class FreqDiffDQPSKScheme:
    """Frequency-differential DQPSK on the proven 750 Hz carrier grid.

    Mirrors h4_dqpsk.DQPSKScheme's public surface so m9_master/m9_decode can drop
    it in.  Differs ONLY in the data mapping (phase differences BETWEEN ADJACENT
    CARRIERS within a symbol, vs h4's same-carrier symbol-to-symbol differences)
    and the per-pair channel-tilt de-rotation in demod.

    Args
    ----
    P        number of CHAIN data carriers (11 for M9a) -> P-1 diff-pairs of data.
    N        DFT length (512 for M9a).
    spacing  carrier spacing in bins (8 @ N512 -> 750 Hz).
    skip     boundary samples dropped from each symbol window (default N//8).
    pilot_hz mid-band unmodulated pilot frequency (4500 Hz; window-drift tracking).
    """

    def __init__(self, P: int, N: int, spacing: int, skip: int | None = None,
                 pilot_hz: float = 4500.0):
        if skip is None:
            skip = N // 8
        self.P, self.N, self.spacing, self.skip = P, N, spacing, skip
        df = FS / N
        b0 = int(round(750.0 / df))
        # full carrier comb: P chain carriers + 1 pilot = P+1 tones on the grid.
        nc = P + 1
        bins = b0 + spacing * np.arange(nc)
        freqs = bins * df
        assert freqs[-1] <= 9500.0, f"top carrier {freqs[-1]:.0f} Hz > 9500"
        assert spacing * df >= 562.0, f"spacing {spacing*df:.0f} Hz < 562"
        self.df = df
        self.bins = bins.astype(int)
        self.freqs = freqs.astype(np.float64)
        self.spacing_hz = float(spacing * df)
        # pilot = the carrier closest to pilot_hz (4500 Hz -> idx for the mid tone).
        self.pilot_idx = int(np.argmin(np.abs(self.freqs - pilot_hz)))
        # chain = every carrier except the pilot.  carrier 0 of the chain is the
        # band-edge per-symbol phase reference (no data on its absolute phase).
        self.chain_idx = np.array([i for i in range(nc) if i != self.pilot_idx])
        self.n_pairs = len(self.chain_idx) - 1            # adjacent diff-pairs
        assert self.n_pairs >= 1, "need >= 2 chain carriers for one diff-pair"
        # which pairs straddle a stationary null (erasure-eligible at decode)?
        cf = self.freqs[self.chain_idx]
        null_pair = np.zeros(self.n_pairs, bool)
        for j in range(1, len(self.chain_idx)):
            lo, hi = cf[j - 1], cf[j]
            if any(abs(lo - nf) < 1.0 or abs(hi - nf) < 1.0 or (lo <= nf <= hi)
                   for nf in NULL_FREQS_HZ):
                null_pair[j - 1] = True
        self.null_pair = null_pair                        # (n_pairs,)
        # per-pair carrier-frequency gap (Hz).  This is SPACING (750 Hz) for every
        # adjacent pair EXCEPT the one straddling the pilot, whose gap is 2*SPACING
        # (the chain skips the mid-band pilot carrier).  The deterministic band-edge
        # anchor in demod uses THIS per-pair gap, not a single SPACING constant.
        self.pair_gap_hz = (cf[1:] - cf[:-1]).astype(np.float64)   # (n_pairs,)

        self.bits_per_sym = 2 * self.n_pairs
        # ONE leading TRAINING symbol with KNOWN zero quadrants (q=0 on every pair).
        # Frequency-differential decode needs the STATIC per-pair channel phase tilt
        # beta_j = theta_chan(f_hi_j) - theta_chan(f_lo_j) (the deck H(f) phase, which
        # over a 750 Hz step can reach >100 deg -- R2 sec.3 EVM up to 0.41).  beta_j
        # is not learnable from a cold start by blind decision-direction (chicken-and-
        # egg at chance), so a single known reference symbol measures it directly --
        # fully achievable (no truth: the receiver knows the training value is 0).
        # Cost: 1 symbol/frame (~0.5 % overhead at ~200 data symbols/frame).
        self.n_train = 1
        self._preamble = hc.make_preamble(0.25).astype(np.float64)
        self.preamble_seconds = 0.25
        self.name = f"FDQ_P{P}_N{N}_sp{spacing}"
        self.gross_bps = self.bits_per_sym / (N / FS)
        # parity alias with h4 (m9_master logs sch.data_idx / sch.P etc.)
        self.data_idx = self.chain_idx

        # analysis window: same orthogonality constraint as h4 (carriers stay
        # orthogonal over Nw = 3N/4 so strong low carriers do not leak into weak
        # rolled-off high ones, which would corrupt the frequency-axis difference).
        self.Nw = N - 2 * skip
        assert (spacing * self.Nw) % N == 0, (
            f"carriers not orthogonal over analysis window: "
            f"spacing={spacing} Nw={self.Nw} N={N}")
        self._win = np.hanning(self.Nw)

        # TX pre-emphasis from the PUBLISHED master3 sounder H(f) (same curve h4
        # uses; no genie) -- equalizes RECEIVED carrier amplitudes so the adjacent-
        # carrier difference is taken between two tones of comparable magnitude.
        params = rcs.load_params()
        Hf = params["Hf_magnitude"]
        fm = np.asarray(Hf["sounder_freqs_master3"], float)
        Hd = np.asarray(Hf["H_db_master3"], float)
        Hl = 10.0 ** (np.interp(self.freqs, fm, Hd) / 20.0)
        Hl = Hl / (Hl.max() + 1e-12)
        self.tx_amp = 1.0 / np.clip(Hl, 0.05, None)
        self.tx_amp = self.tx_amp / self.tx_amp.max()

        # published channel-phase tilt between adjacent chain carriers (de-rotation
        # seed; the per-capture sounder refines it in demod if measured tilt given).
        if "H_phase_master3" in Hf and "sounder_freqs_master3" in Hf:
            fp = np.asarray(Hf["sounder_freqs_master3"], float)
            php = np.asarray(Hf["H_phase_master3"], float)
            self._chan_phase = np.interp(self.freqs, fp, php)
        else:
            self._chan_phase = np.zeros(nc)

    # ---- bit <-> quadrant mapping (FREQUENCY-axis: pair j carries block j) -----
    def nsym_data(self, nbits: int) -> int:
        return int(math.ceil(nbits / self.bits_per_sym))

    def bits_to_quadrants(self, bits: np.ndarray) -> np.ndarray:
        """Frame bits -> (nd, n_pairs) quadrant indices, PAIR-BLOCK mapping:
        diff-pair j carries the j-th contiguous 2*nd-bit block of the frame (same
        contiguous-block discipline h4 uses on carriers, so a corrupt pair hits a
        contiguous 1/n_pairs byte slice -- RS-friendly)."""
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        nd = len(bits) // bps
        bm = bits.reshape(self.n_pairs, nd, 2)            # pair-major blocks
        q = np.zeros((nd, self.n_pairs), int)
        for (a, b), qq in GRAY_ENC.items():
            q[((bm[:, :, 0] == a) & (bm[:, :, 1] == b)).T] = qq
        return q

    def quadrants_to_bits(self, q: np.ndarray) -> np.ndarray:
        """(nd, n_pairs) quadrants -> frame bits (inverse of bits_to_quadrants)."""
        nd = q.shape[0]
        bm = np.zeros((self.n_pairs, nd, 2), np.uint8)
        for qq, (a, b) in GRAY_DEC.items():
            m = (q == qq).T
            bm[:, :, 0][m] = a
            bm[:, :, 1][m] = b
        return bm.reshape(-1)

    # ---- modulate one frame ---------------------------------------------------
    def modulate(self, bits: np.ndarray) -> np.ndarray:
        """Build the audio for one frame.

        Within each symbol the chain carriers carry a CUMULATIVE phase ladder ALONG
        FREQUENCY: chain carrier 0 is the reference (absolute phase 0); chain
        carrier j sits at the reference phase + sum of the first j pair-quadrant
        phase shifts.  Then  angle(c[i,chain[j]] * conj(c[i,chain[j-1]])) = q[i,j]*pi/2
        recovers the j-th pair's quadrant -- no dependence on the previous SYMBOL,
        so there is no time-differential reference symbol.  The pilot stays
        unmodulated (phase 0) for window-drift tracking.
        """
        qd = self.bits_to_quadrants(bits)                 # (nd, n_pairs) DATA
        nd = qd.shape[0]
        nc = self.P + 1
        # prepend n_train known-zero-quadrant TRAINING symbols (beta calibration)
        q = np.concatenate([np.zeros((self.n_train, self.n_pairs), int), qd], axis=0)
        total = q.shape[0]
        # per-symbol absolute phase of every carrier
        theta = np.zeros((total, nc))
        # cumulative frequency-axis phase ladder along the chain (carrier 0 ref)
        # phase of chain[j] = sum_{m<=j} q[:, m-1]*pi/2  (j>=1); chain[0] = 0
        cum = np.cumsum(q * (np.pi / 2.0), axis=1)        # (total, n_pairs)
        for j in range(1, len(self.chain_idx)):
            theta[:, self.chain_idx[j]] = cum[:, j - 1]
        # pilot + chain[0] stay at phase 0 (theta already zero there)
        t = np.arange(total * self.N) / FS                # GLOBAL time across body
        body = np.zeros(total * self.N)
        for k in range(nc):
            ph = 2 * np.pi * self.freqs[k] * t + np.repeat(theta[:, k], self.N)
            body += self.tx_amp[k] * np.sin(ph)
        audio = np.concatenate([self._preamble, body])
        pk = np.max(np.abs(audio))
        return (audio / pk * 0.70).astype(np.float32)

    # ---- achievable demod of one frame window ---------------------------------
    def demod(self, win_audio: np.ndarray, nd: int, refine: bool = True,
              eq_tilt: np.ndarray | None = None):
        """Returns (bits, diag).

        diag has the (nd, n_pairs) quadrant decisions, the pilot-estimated dtau
        trace (window-drift tracking only), and the per-pair erasure flags.
        NO truth used.

        The pilot drives the SAME integer window-drift loop the proven record uses
        (so the window stays centred symbol-to-symbol).  But the DATA decision is
        frequency-differential, so the residual per-symbol timing wander the pilot
        loop cannot fully remove DOES NOT enter the decision -- it cancels in the
        adjacent-carrier difference (see module derivation).

        eq_tilt : optional per-carrier channel PHASE at self.freqs (radians),
                  e.g. from the per-capture sounder; overrides the published tilt.
        """
        y = np.asarray(win_audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), self.preamble_seconds)
        nc = self.P + 1
        N, skip, Nw = self.N, self.skip, self.Nw
        fpil = self.freqs[self.pilot_idx]
        total = self.n_train + nd            # n_train leading reference symbols
        c = np.zeros((total, nc), np.complex128)
        dtau = np.zeros(total)               # seconds, per symbol (window-drift)
        lo_samp = np.zeros(total)            # window start sample per symbol (anchor)
        drift = 0.0                          # samples, accumulated
        ema = 0.5
        sm = 0.0
        prev_pilot = None
        for i in range(total):
            base = ds + i * N + int(round(drift))
            lo = base + skip
            lo_samp[i] = lo
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
            tt = (lo + np.arange(Nw)) / FS   # ABSOLUTE basis: window shift transparent
            E = np.exp(-2j * np.pi * np.outer(self.freqs, tt))
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                c[i] = E @ (seg * self._win)  # spurious BLAS warn on macOS Accelerate
            # window-drift tracking via the pilot (NOT a data correction)
            cur = c[i, self.pilot_idx]
            if prev_pilot is not None:
                dp = float(np.angle(cur * np.conj(prev_pilot)))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
            prev_pilot = cur

        # ---- FREQUENCY-DIFFERENTIAL decision --------------------------------
        ci = self.chain_idx
        cc = c[:, ci]                                     # (total, n_chain)
        d = cc[:, 1:] * np.conj(cc[:, :-1])               # (total, n_pairs): adjacent
        dphi_all = np.angle(d)                            # (total, n_pairs)

        # DETERMINISTIC band-edge anchor (resolves the QPSK pi-fold ambiguity).
        # The absolute-time DFT references each carrier's phase to the window start
        # sample lo_i, so the measured adjacent-carrier difference for pair j carries
        # a known alignment rotation R_ij = 2*pi*(f_hi_j - f_lo_j)*lo_i/FS =
        # 2*pi*pair_gap_j*lo_i/FS -- computable PURELY receiver-side (lo_i from the
        # preamble + pilot drift, pair_gap from the fixed grid; no truth).  The gap is
        # SPACING (750 Hz) for every pair except the pilot-straddling pair (2*SPACING).
        # Subtracting it deterministically removes the band-edge offset so the blind DD
        # refinement below only cleans up the SMALL residual (static channel tilt +
        # sub-sample timing), without the 4-fold sign ambiguity a global pi rotation
        # would hide.  NOTE: only the COMMON per-symbol timing term cancels in the
        # adjacent-carrier difference; this deterministic gap*lo term is the residual
        # absolute-phase reference, NOT a timing correction -- the timing-immunity
        # claim (common per-symbol jitter cancels) is independent of it.
        R = 2 * np.pi * np.outer(lo_samp, self.pair_gap_hz) / FS   # (total, n_pairs)
        dphi_all = dphi_all - R

        good = ~self.null_pair if (~self.null_pair).any() else np.ones(self.n_pairs, bool)

        # ---- STATIC per-pair channel tilt from the TRAINING symbol(s) -------
        # The leading n_train symbols carry KNOWN q=0, so after the anchor they read
        #     dphi_train[t,j] = beta_j + gamma_train[t]
        # beta_j (the static per-pair channel tilt, constant over symbols -- the
        # deck H(f) phase the design says to de-rotate) is the per-pair circular mean
        # of the training reads MINUS the training symbol's common rotation gamma_t
        # (estimated as the circular mean across the good pairs of that symbol, since
        # q=0 there).  No truth: the value 0 is the known training payload.
        nt = self.n_train
        train = dphi_all[:nt]                              # (nt, n_pairs)
        gtr = np.angle(np.exp(1j * train[:, good]).mean(axis=1))    # (nt,) common rot
        beta = np.angle(np.exp(1j * (train - gtr[:, None])).mean(axis=0))  # (n_pairs,)
        # optional MEASURED sounder tilt seed (per-capture H(f) phase) -- if given it
        # REPLACES the training estimate (the sounder spans the whole section, lower
        # variance than a single symbol); on a clean signal both are ~0 (no-op).
        if eq_tilt is not None:
            tilt0 = np.asarray(eq_tilt, float)[ci]
            beta = tilt0[1:] - tilt0[:-1]

        # ---- decode the DATA symbols (de-rotate static beta, track common gamma) --
        dphi0 = dphi_all[nt:] - beta[None, :]              # (nd, n_pairs)
        # gamma_i = common per-SYMBOL rotation (the -2*pi*SPACING*tau_i timing term,
        # constant over pairs j) -- the residual the band-edge / pilot loop leaves.
        # With beta known, gamma is a SINGLE rotation per symbol; estimate it by
        # decision-directed circular mean over the good pairs and refine.
        gamma = np.zeros(nd)
        q = np.round(dphi0 / (np.pi / 2.0)).astype(int) % 4
        n_passes = 3 if refine else 0
        for _ in range(n_passes):
            corr = dphi0 - gamma[:, None]
            q = np.round(corr / (np.pi / 2.0)).astype(int) % 4
            res = (dphi0 - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            gamma = np.angle(np.exp(1j * res[:, good]).mean(axis=1))  # per-symbol (nd,)
        corr = dphi0 - gamma[:, None]
        q = np.round(corr / (np.pi / 2.0)).astype(int) % 4

        return self.quadrants_to_bits(q), {
            "quadrants": q,
            "dtau": dtau[nt:],
            "preamble_at": int(ds),
            "null_pair": self.null_pair.copy(),
            "pair_static_tilt_rad": beta,
            "common_rot_rad": gamma,
            "pair_freqs_hi_hz": [round(float(f), 1) for f in self.freqs[ci][1:]],
        }


# convenience alias matching the h4 class name pattern for symmetry
FreqDiffScheme = FreqDiffDQPSKScheme


if __name__ == "__main__":
    # quick self-describe
    s = FreqDiffDQPSKScheme(11, 512, 8)
    print(f"{s.name}: chain freqs Hz = "
          f"{[round(float(f)) for f in s.freqs[s.chain_idx]]}")
    print(f"  pilot = {s.freqs[s.pilot_idx]:.0f} Hz  spacing = {s.spacing_hz:.1f} Hz")
    print(f"  {s.n_pairs} diff-pairs  bits/sym = {s.bits_per_sym}  "
          f"gross = {s.gross_bps:.1f} bps  net(RS159) = {s.gross_bps*159/255:.1f} bps")
    print(f"  null pairs (3750 Hz-adjacent): "
          f"{[j for j in range(s.n_pairs) if s.null_pair[j]]}")
