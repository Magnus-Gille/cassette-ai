"""x10_b_aggr_03_toneplan_v2_scheme.py — B-aggr-03: channel-mapped N256 tone plan.

Candidate B-aggr-03-toneplan-v2 for master10: a DQPSK scheme subclass that takes
EXPLICIT carrier bins + an explicit pilot bin, so the tone plan can be mapped to
the measured tape9 channel instead of a contiguous comb from 750 Hz:

  * DROP the 750 Hz slot at N256 — tape9 forensics (x10_forensics_errors.json):
    previous-symbol acoustic-echo ISI gives carrier 0 ~40-45 % SER at N256 while
    mid carriers are near-clean; masking it alone would have banked m5/m6/m7
    (2632/2809/2896 bps) byte-exact.
  * PILOT ON THE MEASURED NOTCH (4500 Hz): the tape9 sounder shows a static deck
    notch at 4400-4700 Hz (-21.6 dB @4407, -28.1 dB @4666). m5/m6 proved the
    pilot SURVIVES there (24 dB) while m7 proved data there dies (21.5 % SER).
    Pilot needs only phase tracking -> park it on the notch, keep data off it.
  * EXTEND past 9 kHz (9750 / 10500 Hz): headroom map (x10_headroom.json) shows
    >=10 dB SNR375 to 11 kHz; the frozen base asserts top<=9500 — relaxed ONLY
    in this subclass (top<=11000, the sounder-curve edge).

FROZEN-CODE CONTRACT: h4_dqpsk.py is never edited. MappedDQPSK does NOT call
DQPSKScheme.__init__ (the base builds a placeholder contiguous comb whose
top-carrier assert (<=9500 Hz) structurally rejects the stretch plan before any
override could run — the same reason DropNullDQPSK's super()-then-override
pattern cannot be reused here). Instead it replicates the base init attribute-
for-attribute with the explicit-bin geometry and STRICTER asserts:
  * pairwise orthogonality over the analysis window for ALL carrier pairs
    (the base only asserts the uniform-comb spacing case),
  * min adjacent physical spacing >= 750 Hz (the proven-safe N256 spacing),
  * no carrier below 1000 Hz (enforces the dropped-750 rule),
  * top carrier <= 11000 Hz (the ONLY relaxation vs the base 9500).
modulate()/demod()/bits_to_quadrants()/quadrants_to_bits() are inherited
UNCHANGED from the frozen base and consume only the attributes set here; the
x9_resampling_pll front-ends consume the same attribute set (verified:
P, N, skip, Nw, _win, freqs, pilot_idx, data_idx, preamble_seconds, name).

Ladder (X10_LADDER below), all N256 rungs RS(255,179), grid df=187.5 Hz,
bins are multiples of 4 (=750 Hz steps) so every pair is orthogonal over
Nw=192:

  x0  anchor   m8_dense375 VERBATIM (DQ_P22_N512_sp4, msh=375, k159)   2572.1
  x1a banker   P11 N256: data 1500..9750 (no 750, no 4500), pilot 4500 2895.6
  x1b banker   same scheme, second payload slice (m4/m4b lesson)       2895.6
  x2a stretch  P12 N256: banker + 10500, pilot 4500                    3158.8
  x2b stretch  same scheme, second payload slice                       3158.8
  x3  pvar     P11 N256: pilot 6000, data has 10500 instead of 6000    2895.6

x3 deviation from the adjudicated plan ("pilot at 5865"): 5865 Hz is not
representable on an orthogonal bin — the nearest bin 31 (5812.5 Hz) violates
the mod-4 orthogonality the demod window requires ((3*192)%256 != 0), which
would leak the always-on pilot into every data carrier. The nearest ORTHOGONAL
slot is bin 32 = 6000 Hz; the rung keeps its insurance role (pilot somewhere
other than 4500 in case the deck notch migrates). Its data set therefore swaps
6000 -> 10500 (4500 stays data-free: 21.5 % SER on tape9 is a known kill).

Self-test:  python3 experiments/tape_v2/x10_b_aggr_03_toneplan_v2_scheme.py
  (geometry asserts + no-channel loopback BER==0 for every rung; seed logged)
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                      # noqa: E402
import real_channel_sim as rcs               # noqa: E402  (FROZEN; read-only)
from h4_dqpsk import DQPSKScheme, FS         # noqa: E402  (FROZEN; subclassed only)

TOP_FREQ_MAX_HZ = 11000.0    # relaxed top assert (sounder curve edge), subclass-only
BOT_FREQ_MIN_HZ = 1000.0     # enforces the dropped-750 rule at N256
MIN_ADJ_SPACING_HZ = 750.0   # proven-safe N256 spacing (m4b/m5/m7 family)


class MappedDQPSK(DQPSKScheme):
    """DQPSK on EXPLICIT carrier bins (data_bins + pilot_bin) of the N-FFT grid.

    Inherits every method from the frozen DQPSKScheme; only the geometry-setting
    __init__ is replaced (see module docstring for why super().__init__ cannot
    be called). All attributes the inherited methods + x9 front-ends consume are
    set here, with stricter pairwise-orthogonality asserts.
    """

    def __init__(self, P: int, N: int, data_bins, pilot_bin: int,
                 skip: int | None = None, name: str | None = None):
        # ---- replicate base init (attribute-for-attribute) ----
        if skip is None:
            skip = N // 8
        data_bins = [int(b) for b in data_bins]
        pilot_bin = int(pilot_bin)
        assert len(data_bins) == P, (len(data_bins), P)
        assert len(set(data_bins)) == P, "duplicate data bins"
        assert pilot_bin not in data_bins, "pilot bin collides with a data bin"
        df = FS / N
        all_bins = np.array(sorted(data_bins + [pilot_bin]), int)
        freqs = all_bins * df
        # spacing attr: the (uniform) grid step in bins, kept for naming/diags.
        gaps = np.diff(all_bins)
        spacing = int(np.gcd.reduce(all_bins - all_bins[0])) if len(all_bins) > 1 else 0
        self.P, self.N, self.spacing, self.skip = P, N, spacing, skip
        self.Nw = N - 2 * skip
        # ---- STRICT asserts (superset of the base, except the top freq) ----
        assert freqs[-1] <= TOP_FREQ_MAX_HZ, f"top carrier {freqs[-1]:.0f} > {TOP_FREQ_MAX_HZ:.0f}"
        assert freqs[0] >= BOT_FREQ_MIN_HZ, f"bottom carrier {freqs[0]:.0f} < {BOT_FREQ_MIN_HZ:.0f}"
        assert gaps.min() * df >= MIN_ADJ_SPACING_HZ, (
            f"min adjacent spacing {gaps.min() * df:.0f} Hz < {MIN_ADJ_SPACING_HZ:.0f}")
        # pairwise orthogonality over the analysis window: for every bin pair,
        # (delta_bin * Nw) % N == 0 (the base asserts only the uniform case).
        for i in range(len(all_bins)):
            for j in range(i + 1, len(all_bins)):
                d = int(all_bins[j] - all_bins[i])
                assert (d * self.Nw) % N == 0, (
                    f"bins {all_bins[i]},{all_bins[j]} not orthogonal over Nw={self.Nw}")
        self.bins = all_bins.astype(int)
        self.freqs = freqs.astype(np.float64)
        self.pilot_idx = int(np.where(all_bins == pilot_bin)[0][0])
        self.data_idx = np.array([i for i in range(len(all_bins)) if i != self.pilot_idx])
        assert len(self.data_idx) == P
        self.bits_per_sym = 2 * P
        self._preamble = hc.make_preamble(0.25).astype(np.float64)
        self.preamble_seconds = 0.25
        self.name = name or f"DQM_P{P}_N{N}_b{pilot_bin}"
        self.gross_bps = self.bits_per_sym / (N / FS)
        self._win = np.hanning(self.Nw)
        # ---- TX pre-emphasis re-fit at the new freqs (same published curve) ----
        params = rcs.load_params()
        Hf = params["Hf_magnitude"]
        fm = np.asarray(Hf["sounder_freqs_master3"], float)
        Hd = np.asarray(Hf["H_db_master3"], float)
        assert fm.max() >= self.freqs.max(), (
            f"published H(f) curve ends at {fm.max():.0f} Hz < top carrier")
        Hl = 10.0 ** (np.interp(self.freqs, fm, Hd) / 20.0)
        Hl = Hl / (Hl.max() + 1e-12)
        self.tx_amp = 1.0 / np.clip(Hl, 0.05, None)
        self.tx_amp = self.tx_amp / self.tx_amp.max()
        self.data_bins = [int(b) for b in data_bins]
        self.pilot_bin = pilot_bin


# ===========================================================================
# master10 ladder — B-aggr-03-toneplan-v2 (offsets staggered through the .cass)
# net_bps = gross * rs_k / 255 (the m9 record convention, sidecar-CRC caveat).
# ===========================================================================
# N256 bin map (df = 187.5 Hz): bin*187.5 Hz. All bins multiples of 4 (750 Hz).
_BANKER_DATA = [8, 12, 16, 20, 28, 32, 36, 40, 44, 48, 52]      # 1500..9750, no 4500
_STRETCH_DATA = _BANKER_DATA + [56]                              # + 10500
_PVAR_DATA = [8, 12, 16, 20, 28, 36, 40, 44, 48, 52, 56]        # 6000->pilot, +10500
_PILOT_NOTCH = 24                                                # 4500 Hz (tape9 notch)
_PVAR_PILOT = 32                                                 # 6000 Hz (insurance)

X10_LADDER = [
    # anchor offset 65536 = the EXACT slice m9_m8_dense375 carried on tape9, so
    # the anchor is byte-identical (scheme AND payload) to the standing record
    # rung — offset 0 packs 75.9 % (13 cw), too thin a reprove.
    {"name": "x10_x0_anchor2572", "kind": "dqpsk", "role": "m8-anchor-VERBATIM-must-reprove-2572",
     "P": 22, "N": 512, "spacing": 4, "min_spacing_hz": 375.0, "pilot_hz": 4875.0,
     "rs_k": 159, "offset": 65536, "orig_bytes": 8192, "net_bps": 2572.1, "x_record": 1.0,
     "status": "ANCHOR", "risk": "proven (the standing record, byte-for-byte scheme+payload)"},
    {"name": "x10_x1a_banker2896", "kind": "dqpsk_mapped", "role": "banker-channel-mapped-N256",
     "P": 11, "N": 256, "data_bins": _BANKER_DATA, "pilot_bin": _PILOT_NOTCH,
     "rs_k": 179, "offset": 8192, "orig_bytes": 8192, "net_bps": 2895.6, "x_record": 1.13,
     "status": "ACTIVE", "risk": "medium (m7 minus its two sick carriers, plus 9750)"},
    {"name": "x10_x1b_banker2896_var", "kind": "dqpsk_mapped", "role": "banker-second-realization",
     "P": 11, "N": 256, "data_bins": _BANKER_DATA, "pilot_bin": _PILOT_NOTCH,
     "rs_k": 179, "offset": 16384, "orig_bytes": 8192, "net_bps": 2895.6, "x_record": 1.13,
     "status": "ACTIVE", "risk": "medium (realization hedge, m4/m4b lesson)"},
    {"name": "x10_x2a_stretch3158", "kind": "dqpsk_mapped", "role": "stretch-12-carriers-to-10500",
     "P": 12, "N": 256, "data_bins": _STRETCH_DATA, "pilot_bin": _PILOT_NOTCH,
     "rs_k": 179, "offset": 24576, "orig_bytes": 8192, "net_bps": 3158.8, "x_record": 1.23,
     "status": "ACTIVE", "risk": "high (10500 Hz: AAC band edge + HF droop)"},
    {"name": "x10_x2b_stretch3158_var", "kind": "dqpsk_mapped", "role": "stretch-second-realization",
     "P": 12, "N": 256, "data_bins": _STRETCH_DATA, "pilot_bin": _PILOT_NOTCH,
     "rs_k": 179, "offset": 32768, "orig_bytes": 8192, "net_bps": 3158.8, "x_record": 1.23,
     "status": "ACTIVE", "risk": "high (realization hedge)"},
    {"name": "x10_x3_pvar2896", "kind": "dqpsk_mapped", "role": "pilot-variant-notch-migration-insurance",
     "P": 11, "N": 256, "data_bins": _PVAR_DATA, "pilot_bin": _PVAR_PILOT,
     "rs_k": 179, "offset": 40960, "orig_bytes": 8192, "net_bps": 2895.6, "x_record": 1.13,
     "status": "ACTIVE", "risk": "medium-high (pilot off-notch hedge; carries 10500)"},
]

LADDER_SEED = 20260612   # logged build seed (modulation itself is deterministic)


def make_scheme_x10(rung: dict):
    """Scheme factory for the x10 ladder + manifest entries (decoder mirror)."""
    kind = rung["kind"]
    if kind == "dqpsk":
        return DQPSKScheme(rung["P"], rung["N"], rung["spacing"],
                           min_spacing_hz=rung.get("min_spacing_hz", 562.0))
    if kind == "dqpsk_mapped":
        return MappedDQPSK(rung["P"], rung["N"], rung["data_bins"], rung["pilot_bin"])
    raise ValueError(f"unknown x10 rung kind {kind!r}")


# ===========================================================================
# self-test: geometry + no-channel loopback (must be BER exactly 0)
# ===========================================================================
def _selftest():
    rng = np.random.default_rng(LADDER_SEED)
    print(f"[selftest] seed={LADDER_SEED}")
    ok = True
    for rung in X10_LADDER:
        sch = make_scheme_x10(rung)
        net = sch.gross_bps * rung["rs_k"] / 255.0
        assert abs(net - rung["net_bps"]) < 0.5, (rung["name"], net, rung["net_bps"])
        bits = rng.integers(0, 2, 4080, dtype=np.uint8)  # one 510-byte frame
        audio = sch.modulate(bits)
        nd = sch.nsym_data(len(bits))
        rx, _ = sch.demod(np.asarray(audio, np.float64), nd)
        ber = float(np.mean(rx[: len(bits)] != bits))
        flag = "OK " if ber == 0.0 else "FAIL"
        ok &= ber == 0.0
        dfreqs = [round(float(f), 1) for f in sch.freqs[sch.data_idx]]
        print(f"  [{flag}] {rung['name']:<24} {sch.name:<18} net={net:7.1f} "
              f"pilot={sch.freqs[sch.pilot_idx]:6.1f} BER={ber:.2e}")
        print(f"        data: {dfreqs}")
    print(f"[selftest] {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return ok


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    sys.exit(0 if _selftest() else 1)
