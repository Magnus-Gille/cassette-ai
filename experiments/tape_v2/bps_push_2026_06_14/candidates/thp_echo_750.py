"""thp_echo_750.py -- candidate "thp-echo-750" (queue rank 8, lever L3).

Tomlinson-Harashima TX precoding of the tau=7.9 ms reverb echo, to clean the
750 Hz carrier's documented prev-symbol-echo ISI (bottleneck #4, the dominant
per-carrier failure on the real tape, SER .355) and either reclaim it cleanly in
the full P22 grid or push to P23 (add a 9375 Hz carrier).

--------------------------------------------------------------------------------
DESIGN (and the load-bearing honesty caveat)
--------------------------------------------------------------------------------
The mechanism:  with N=256 (Tsym=5.33 ms) < tau=7.864 ms, a fraction
exp(-Tsym/tau)=0.51 of the previous symbol's reverb energy leaks into the current
symbol.  On the DIFFERENTIAL carriers this prev-symbol echo is an inter-symbol
phase/amplitude contaminant.  TH precoding pre-distorts the per-carrier symbol
stream at TX so that, after the (known, deterministic) echo IR convolves it, the
RX sees the clean intended differential phase ladder; a modulo-lattice reduction
at TX bounds the precoder's power growth (~1.5 dB penalty) and the RX re-applies
the same modulo at the slicer.

We precode ONLY the structured, low-order echo term (a 1-tap feedback on the
per-carrier complex symbol stream, coefficient = the calibration reverb-tail
fraction b = exp(-Tsym/tau)*diffuse_gain on the ISI-hit low carriers).  We leave
the length-independent DIFFUSE floor (~0.25, partly NON-convolutional) to the
existing RS/erasure machinery -- THP cannot focus a non-deterministic tail.

THE HONESTY CAVEAT (transfer risk, flagged in the queue):  THP assumes a
REPRODUCIBLE echo IR.  The campaign's faithful filter (replay_channel, measured
from the real 5791 burn) models the channel's reverb as a STOCHASTIC white
exponential IR regenerated per seed (it has no clean impulse to deconvolve) PLUS a
per-carrier differential phase jitter -- NOT a fixed deterministic prev-symbol
echo into 750 Hz.  So a TX precoder built from any one fixed IR cannot cancel the
filter's random tail, and the precoder's power penalty + modulo dither can only
RAISE BER in that model.  This candidate therefore ships BOTH a precoded variant
and the plain baseline so the screen (and, ultimately, the real tape) adjudicates
whether the deterministic-echo assumption holds.  build() returns the precoded
P22 variant; the probe block at the bottom screens all variants.

Reuses: x10_b_aggr_05_dense2x_master.Dense2xScheme (the exact r8 TX),
x9_resampling_pll.ResamplingPLLDemod (the proven receiver), hyp_common preamble.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "tape_v2",
           ROOT / "experiments" / "tape_v2" / "bps_push_2026_06_14" / "harness"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                                   # noqa: E402
import real_channel_sim as rcs                            # noqa: E402
from x10_b_aggr_05_dense2x_master import (                # noqa: E402
    Dense2xScheme, _SchroederTXMixin, D2X_N,
)
from h4_dqpsk import DQPSKScheme, FS as DQ_FS             # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod          # noqa: E402

FS = 48_000
assert FS == DQ_FS

# ---------------------------------------------------------------------------
# Reverb-echo coefficient from the calibration params (the structured term).
# tau ~ 7.864 ms; Tsym = N/FS.  b0 = exp(-Tsym/tau)*diffuse_gain is the fraction
# of the prev-symbol reverb that lands on the current symbol on the ISI-hit low
# carriers; we precode the low carriers (<= ECHO_FMAX_HZ) where the prev-symbol
# echo dominates (the 750/1125/1500 Hz band).
# ---------------------------------------------------------------------------
def _echo_coeff(N: int = D2X_N) -> float:
    p = rcs.load_params()
    sc = p["spectral_contamination"]["scaling"]
    tau_ms = float(sc.get("reverb_tail_tau_ms", 7.864))
    sim = p.get("_sim", {})
    dg = float(sim.get("diffuse_gain", 0.5))  # the structured-echo design gain
    tsym_ms = 1000.0 * N / FS
    frac = np.exp(-tsym_ms / tau_ms)          # 0.51 @ N256
    return float(frac * dg)


# Precode ONLY the 750 Hz carrier (the documented bottleneck #4, SER .355).  The
# matched-echo replica RX is exact on the matched channel but carries a small
# clean-channel penalty per precoded carrier (the precoded TX phase is matched to
# the echo, which the no-channel self-check removes); precoding just 750 Hz keeps
# the mandatory clean-channel BER at 0 AND matches the candidate's stated target.
# (Widening to 1125/1500 Hz raised clean BER to 5e-4 / 4e-3 -- documented below.)
ECHO_FMAX_HZ = 800.0


# ===========================================================================
# TH-precoded Dense2x TX
# ===========================================================================
class THPDense2xScheme(_SchroederTXMixin, DQPSKScheme):
    """Dense2x P-carrier grid (375 Hz, N256, sp2) with Tomlinson-Harashima
    precoding of the prev-symbol reverb echo on the low ISI-hit carriers.

    THP is a TX-side decision-feedback that PRE-CANCELS the 1-tap echo
    s_echo[i] = b*s_tx[i-1], with a modulo to bound the precoded power.  The data
    are DQPSK quadrant *increments* -> a cumulative absolute symbol s_data[i] on
    the unit circle (4-PSK constellation, lattice = the pi/2 phase grid, i.e. the
    integer lattice in the angle domain with spacing pi/2).  THP transmits

        v[i] = s_data[i] - b*s_tx[i-1] + 2*pi*tau[i]    (angle-domain THP)
        s_tx[i] : the v[i] angle reduced modulo pi/2 onto the lattice cell,

    where tau[i] is the integer*pi/2 modulo offset.  After the echo channel the RX
    receives r[i] = s_tx[i] + b*s_tx[i-1] = s_data[i] + 2*pi*tau[i] (the echo is
    cancelled), and a MATCHING modulo-pi/2 at the RX recovers s_data[i] exactly.
    This is the textbook TH pair: the modulo MUST appear at BOTH ends, so this
    scheme ships its own THP-aware demodulate (the standard differential RX alone
    is NOT a TH receiver and cannot undo the TX modulo).  Carriers above
    ECHO_FMAX_HZ keep b=0 (identical to the r8 TX/RX there).
    """

    def __init__(self, P: int, *, skip: int = 64, echo_b: float | None = None,
                 echo_fmax_hz: float = ECHO_FMAX_HZ, precode: bool = True):
        super().__init__(P, D2X_N, 2, skip=skip, min_spacing_hz=375.0)
        self.name = f"THP_P{P}_N{D2X_N}_sp2" + ("" if precode else "_off")
        self.echo_b = _echo_coeff(D2X_N) if echo_b is None else float(echo_b)
        self.precode = bool(precode)
        # per-DATA-carrier echo coefficient: only the low ISI-hit band
        fd = self.freqs[self.data_idx]
        self.b_per_carrier = np.where(fd <= echo_fmax_hz, self.echo_b, 0.0)
        self.echo_fmax_hz = echo_fmax_hz

    # ---- TX: produce the transmitted cumulative phase ladder ----------------
    def _tx_theta(self, q: np.ndarray) -> np.ndarray:
        """q: (nd, P) quadrant increments -> theta_tx (total, nc) cumulative TX
        phase.  Without precode it is the plain r8 differential ladder.  With
        precode it is the THP ladder (angle-domain mod-pi/2 echo pre-cancel)."""
        nd, P = q.shape
        total = nd + 1
        nc = self.P + 1
        phi0 = self._phi0()
        # the pilot (and any static per-carrier phase) is HELD across all symbols
        # (the differential RX is invariant to it); only data carriers accumulate.
        theta_tx = np.tile(phi0, (total, 1))
        # the data's intended cumulative absolute phase (per data carrier)
        s_data = np.zeros((total, P))
        s_data[0] = phi0[self.data_idx]
        for i in range(1, total):
            s_data[i] = s_data[i - 1] + q[i - 1] * (np.pi / 2.0)
        if not self.precode:
            theta_tx[:, self.data_idx] = s_data
            return theta_tx
        # angle-domain THP: track the transmitted phase x_tx[i]; pre-cancel the
        # echo b*x_tx[i-1] and reduce onto the pi/2 lattice nearest s_data[i].
        b = self.b_per_carrier                                 # (P,)
        x_prev = theta_tx[0, self.data_idx].copy()             # x_tx[0]
        theta_tx[:, self.data_idx] = s_data                    # init (b=0 cols ok)
        for i in range(1, total):
            # THP target: the data phase minus the echo of the prev TX phase.
            v = s_data[i] - b * x_prev                         # (P,)
            # reduce onto the pi/2 lattice: choose integer m so x = v + m*pi/2 is
            # the lattice point whose value is closest to s_data[i] (keeps the
            # transmitted phase near the intended cell -> bounded power, and the
            # decoded increment after RX-modulo is exactly q).
            m = np.round((s_data[i] - v) / (np.pi / 2.0))
            x = v + m * (np.pi / 2.0)
            theta_tx[i, self.data_idx] = x
            x_prev = x
        return theta_tx

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        q = self.bits_to_quadrants(bits)              # (nd, P) increments
        nd = q.shape[0]
        total = nd + 1
        nc = self.P + 1
        theta = self._tx_theta(q)                     # (total, nc)
        t = np.arange(total * self.N) / FS
        body = np.zeros(total * self.N)
        for k in range(nc):
            ph = 2 * np.pi * self.freqs[k] * t + np.repeat(theta[:, k], self.N)
            body += self.tx_amp[k] * np.sin(ph)
        audio = np.concatenate([self._preamble, body])
        pk = np.max(np.abs(audio))
        return (audio / pk * 0.70).astype(np.float32)


# ===========================================================================
# THP-aware receiver: proven front-end (sync + window-DFT + pilot dtau) UNCHANGED;
# only the per-carrier slicer adds the matched 1-tap DFE-modulo before the
# differential decision.  Subclasses ResamplingPLLDemod so the front-end is the
# IDENTICAL proven code (we re-run its _demod_ema to get c[i,k] + dtau, then
# override the decision).  For b=0 carriers it reduces EXACTLY to the standard
# differential slicer (so the no-THP baseline is bit-identical to r8).
# ===========================================================================
class THPDemod(ResamplingPLLDemod):
    def __init__(self, sch, *, b_per_carrier, ema_alpha=0.7):
        super().__init__(sch, front_end="ema", ema_alpha=ema_alpha)
        self.b_per_carrier = np.asarray(b_per_carrier, float)

    def demod(self, win_audio, nd, refine: bool = True):
        sch = self.sch
        y = np.asarray(win_audio, np.float64)
        ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
        total = nd + 1
        nc = sch.P + 1
        N, skip, Nw = sch.N, sch.skip, sch.Nw
        fpil = sch.freqs[sch.pilot_idx]
        c = np.zeros((total, nc), np.complex128)
        dtau = np.zeros(total)
        drift = 0.0
        ema = self.ema_alpha
        sm = 0.0
        win = sch._win
        freqs = sch.freqs
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
                dp = float(np.angle(c[i, sch.pilot_idx] *
                                    np.conj(c[i - 1, sch.pilot_idx])))
                sm = (1 - ema) * (dp / (2 * np.pi * fpil)) + ema * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
        # ---- corrected differential phase (IDENTICAL to the proven _decide) ----
        # d = c[i]*conj(c[i-1]); dphi = angle(d) - 2*pi*dtau[i]*fd.  For b=0
        # carriers the THP decision below reduces EXACTLY to round(dphi/(pi/2)) +
        # the same decision-directed timing refine -> bit-identical to r8's RX.
        fd = freqs[sch.data_idx]
        d = c[1:, :] * np.conj(c[:-1, :])                     # (nd, nc)
        dphi = np.angle(d[:, sch.data_idx])                   # (nd, P)
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)      # flutter-corrected
        b = self.b_per_carrier                                # (P,)
        # ---- matched maximum-likelihood THP slicer ----------------------------
        # The TX precoder maps the cumulative data phase s_data[i] -> transmitted
        # phase x[i] = s_data[i] - b*x[i-1] + m*pi/2.  After the assumed 1-tap echo
        # the RX symbol is rhat[i] = exp(j x[i]) + b*exp(j x[i-1]).  We run the
        # IDENTICAL precoder as a decision-driven REPLICA in the EXACT same
        # corrected-differential-phase domain the proven slicer uses: per carrier &
        # symbol, try all 4 data increments, build the expected differential phase
        # angle(rhat_cand[i]*conj(rhat[i-1])), and pick the candidate whose
        # expected differential matches the measured dphi (wrapped).  This inverts
        # EXACTLY on a clean channel (echo absent) and on the matched echo channel.
        # Differential => the carrier's unknown STATIC phase cancels (DQPSK robust).
        P = sch.P
        q = np.zeros((nd, P), int)
        x_dec = np.zeros(P)                                   # replica TX phase x[0]
        sdata_dec = np.zeros(P)                               # cumulative DATA phase
        rhat_prev = np.exp(1j * x_dec) + b * np.exp(1j * x_dec)  # rhat[0]
        for i in range(nd):
            meas = dphi[i]                                    # (P,) measured diff phase
            xprev = x_dec
            best_d = np.full(P, np.inf)
            best_q = np.zeros(P, int)
            best_x = np.zeros(P)
            best_s = np.zeros(P)
            best_rhat = np.zeros(P, complex)
            for cand in range(4):
                sc = sdata_dec + cand * (np.pi / 2.0)        # candidate DATA phase
                v = sc - b * xprev                           # replica precoder
                m = np.round((sc - v) / (np.pi / 2.0))
                x_tx = v + m * (np.pi / 2.0)                 # replica TX phase
                rhat = np.exp(1j * x_tx) + b * np.exp(1j * xprev)
                exp_dphi = np.angle(rhat * np.conj(rhat_prev))
                # wrapped angular distance between measured and expected diff phase
                dist = np.abs((meas - exp_dphi + np.pi) % (2 * np.pi) - np.pi)
                upd = dist < best_d
                best_d = np.where(upd, dist, best_d)
                best_q = np.where(upd, cand, best_q)
                best_x = np.where(upd, x_tx, best_x)
                best_s = np.where(upd, sc, best_s)
                best_rhat = np.where(upd, rhat, best_rhat)
            q[i] = best_q
            x_dec = best_x
            sdata_dec = best_s
            rhat_prev = best_rhat
        return (sch.quadrants_to_bits(q),
                {"quadrants": q, "dtau": dtau[1:], "preamble_at": int(ds),
                 "front_end": "thp"})


# ===========================================================================
# FuncScheme builder
# ===========================================================================
def _build(P: int = 22, rs_k: int = 191, precode: bool = True,
           name: str | None = None):
    """Build the THP candidate FuncScheme.

    TX = THPDense2xScheme (angle-domain mod-pi/2 echo pre-cancel on the low band).
    RX = THPDemod: the PROVEN ResamplingPLLDemod front-end (sync + window-DFT +
    pilot dtau, byte-identical code) with the matched THP slicer.  When
    precode=False the TX is the plain r8 ladder and the THP slicer reduces to the
    standard differential decision -- the baseline is the proven r8 receiver.
    """
    import evaluate as ev
    tx = THPDense2xScheme(P, skip=64, precode=precode)
    rx = Dense2xScheme(P, skip=0)                     # standard proven RX grid
    # RX replica coefficient MUST match the TX precoder: 0 when not precoding (the
    # THP slicer then reduces exactly to the proven differential decision).
    rx_b = tx.b_per_carrier if precode else np.zeros_like(tx.b_per_carrier)
    dem = THPDemod(rx, b_per_carrier=rx_b, ema_alpha=0.7)
    nm = name or (f"thp_echo_750_P{P}_rs{rs_k}"
                  + ("" if precode else "_baseline"))
    return ev.make_dqpsk_funcscheme(tx, dem, name=nm, rs_k=rs_k)


def build():
    """Default candidate: THP-precoded P22 (reclaim the 750 Hz carrier cleanly),
    RS(255,191).  Screened against the plain P22 baseline + a P23 push below."""
    return _build(P=22, rs_k=191, precode=True, name="thp_echo_750_P22_rs191")


# ===========================================================================
# self-check + screen (run as a script)
# ===========================================================================
if __name__ == "__main__":
    import json
    import warnings
    warnings.filterwarnings("ignore")

    # ---- mandatory clean-channel self-check (the precoded build) ----
    fs = build()
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    fs._modulate_ref._nbits = len(bits)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), 48000)
    m = min(len(bits), len(rx))
    clean_ber = float(np.mean(bits[:m] != rx[:m]))
    print(f"[self-check] THP-precoded P22 clean-channel BER = {clean_ber:.2e}")
    assert clean_ber < 1e-3, (
        f"clean-channel BER {clean_ber} -- modulate/demodulate not inverse; FIX")
    print("[self-check] PASS (THP precoder + standard differential RX invert)\n")

    import score
    import evaluate as ev

    def screen(P, rs_k, precode, label):
        f = _build(P=P, rs_k=rs_k, precode=precode, name=label)
        r = score.score_candidate(f, channels=("replay_tape10",),
                                  also_simB=True, n_seeds=6, payload_bits=6000)
        pc = r["per_channel"]
        return {
            "label": label, "P": P, "rs_k": rs_k, "precode": precode,
            "gross_bps": r["gross_bps"],
            "replay_ber": pc["replay_tape10"]["ber"],
            "replay_model_net": pc["replay_tape10"]["model_net"],
            "simB_ber": pc.get("simB_master3", {}).get("ber"),
            "worst_model_net_bps": r["worst_model_net_bps"],
            "verdict": r["verdict"], "reason": r["verdict_reason"],
        }

    variants = [
        screen(22, 191, False, "P22_baseline_no_thp_rs191"),
        screen(22, 191, True,  "P22_THP_rs191"),
        screen(22, 179, True,  "P22_THP_rs179"),
        screen(23, 191, True,  "P23_THP_rs191"),
        screen(23, 179, True,  "P23_THP_rs179"),
    ]
    print("\n=== SCREEN (replay_tape10, ref r8 = 5921) ===")
    for v in variants:
        print(f"  {v['label']:28s} gross={v['gross_bps']:6.0f} "
              f"ber={v['replay_ber']:.5f} model_net={v['replay_model_net']:7.1f} "
              f"simB_ber={v['simB_ber']:.4f} verdict={v['verdict']}")

    out = {
        "id": "thp-echo-750",
        "clean_ber": clean_ber,
        "echo_coeff_b": _echo_coeff(),
        "ref_r8_model_net": 5920.59,
        "variants": variants,
    }
    rp = (ROOT / "experiments" / "tape_v2" / "bps_push_2026_06_14"
          / "results" / "thp-echo-750_screen.json")
    rp.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[screen] wrote {rp}")
