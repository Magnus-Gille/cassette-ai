"""stacked_flagship.py -- THE UNTESTED STACK of the orthogonal winning levers.

Task 2 of the finalization.  Combine, in ONE scheme, the two orthogonal levers
that each beat the record on their own:

  (a) 8-DPSK on the CSI-cleanest IN-BAND carriers (dapsk16 lever L2): the extra
      phase bit goes only where the measured per-carrier differential-phase p90
      clears the 22.5 deg 8-PSK boundary.  Start with dapsk16's 3-carrier set
      (3375/5250/750 Hz); also try the 7-carrier robust set.  DQPSK on the rest.
  (b) Ext-band 1-bit DBPSK on the SAME 375 Hz grid ABOVE 9000 Hz (extband lever
      L5): 9375/9750/10125/10500 (+10875/11250), 90 deg boundary, +3 dB TX boost.

The two levers are ORTHOGONAL: (a) raises bits/sym on the cleanest mid carriers
(phase margin), (b) adds carriers in a band the base grid leaves empty (frequency
extent).  Neither touches the other's resource, so the hypothesis is that their
model_net gains ADD.

DSP reuse -- NOTHING reinvented:
  * Subclasses ``DiffMultitoneScheme`` (dapsk16-strongmids) -> inherits the entire
    differential M-DPSK TX/RX: the 375 Hz grid, Schroeder phi0, measured-H(f) TX
    pre-emphasis, the proven chirp preamble, the EMA pilot-tracking integer-drift
    DFT loop, the one-shot DD timing-slope refine, and the per-carrier variable-M
    slicer.  DBPSK is ALREADY supported there as the M=2 (phase_bits=1) case.
  * The ONLY new code: extend the carrier grid above 9000 Hz (append ext bins on
    the same b0 + spacing*k grid), give those carriers phase_bits=1 (DBPSK) and a
    +3 dB TX boost, and recompute data_idx / tx_amp / freqs / the gray + M tables
    over the widened carrier set.  Sync/pilot/RX loop are untouched.

Build via ``build(n8=3, n_ext=4)``.  Mandatory clean-channel self-check (BER<1e-3)
runs in __main__.
"""
from __future__ import annotations

import importlib.util
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

# Load the dapsk16-strongmids module (hyphenated filename) to subclass its
# DiffMultitoneScheme + reuse its measured-CSI carrier ranking.
_spec = importlib.util.spec_from_file_location(
    "dapsk16_strongmids", _HERE / "dapsk16-strongmids.py")
_dapsk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dapsk)

DiffMultitoneScheme = _dapsk.DiffMultitoneScheme
DATA_FREQS = _dapsk.DATA_FREQS
CSI_CLEANEST = _dapsk.CSI_CLEANEST
_gray_tables = _dapsk._gray_tables

FS = 48_000

# ext band: contiguous on the SAME 375 Hz grid above 9000 Hz (matches extband_dbpsk)
EXT_FREQS_ALL = [9375.0, 9750.0, 10125.0, 10500.0, 10875.0, 11250.0]
EXT_BOOST_DB = 3.0


class StackedFlagship(DiffMultitoneScheme):
    """8-DPSK-on-clean-carriers (in band) + DBPSK ext-band carriers (above band).

    Built on top of DiffMultitoneScheme: the base 22 carriers carry 2 or 3 bits
    (DQPSK / 8-DPSK by measured CSI), and ``n_ext`` extension carriers above
    9000 Hz carry 1 bit each (DBPSK, the M=2 case of the inherited M-DPSK slicer)
    with a +ext_boost_db TX boost.
    """

    def __init__(self, *, n8: int = 3, n_ext: int = 4,
                 ext_boost_db: float = EXT_BOOST_DB, skip: int = 64):
        # --- base 22-carrier loading: 8-DPSK on the n8 CSI-cleanest, DQPSK else.
        base_bpc = [2] * 22
        for f in CSI_CLEANEST[:n8]:
            base_bpc[DATA_FREQS.index(f)] = 3
        base_ring = [False] * 22

        # Initialise the inherited DiffMultitoneScheme with the base loading.  This
        # builds the 23-carrier (22 data + pilot@4875) grid, tx_amp pre-emphasis,
        # Schroeder phi0, preamble, RX window, gray/M tables for the 22 base
        # carriers.  We then WIDEN every per-carrier array to add the ext carriers.
        super().__init__(base_bpc, base_ring, name="stack_init", skip=skip)

        self.n8 = int(n8)
        self.n_ext = int(n_ext)
        self.ext_boost_db = float(ext_boost_db)
        assert 0 <= n_ext <= len(EXT_FREQS_ALL), n_ext

        if n_ext == 0:
            self.name = f"Stack_8dpsk{n8}_noext"
            return

        # --- append ext carriers on the same grid -----------------------------
        # Base geometry: bins = b0 + spacing*arange(nc_base); nc_base = 23.
        # Ext carriers continue: bins = b0 + spacing*(nc_base + j).
        df = FS / self.N
        b0 = int(round(750.0 / df))
        nc_base = self.P + 1                      # 23 (22 data + pilot)
        ext_bins = b0 + self.spacing * (nc_base + np.arange(n_ext))
        ext_freqs = ext_bins * df
        assert abs(ext_freqs[0] - 9375.0) < 1e-6, ext_freqs[0]
        for got, want in zip(ext_freqs, EXT_FREQS_ALL):
            assert abs(got - want) < 1e-6, (got, want)

        # Widen the carrier arrays.  Inherited layout: self.freqs/self.bins are
        # length nc_base, indexed [0..22] with pilot at self.pilot_idx (=11), and
        # self.data_idx lists the 22 non-pilot indices.  We append ext carriers as
        # new indices [23 .. 23+n_ext-1], all DATA carriers (DBPSK).
        old_nc = len(self.freqs)
        self.freqs = np.concatenate([self.freqs, ext_freqs]).astype(np.float64)
        self.bins = np.concatenate([self.bins, ext_bins]).astype(int)
        ext_idx = np.arange(old_nc, old_nc + n_ext)
        self.data_idx = np.concatenate([self.data_idx, ext_idx]).astype(int)
        self._ext_idx = ext_idx

        # Widen the per-carrier modulation descriptors.  self.P MUST become the
        # new data-carrier count (the inherited TX/RX iterate over data_idx and
        # assume len == P).  bits_per_carrier / ring_carrier / phase_bits / M /
        # _gray are per-DATA-carrier lists aligned to data_idx order.
        self.P = len(self.data_idx)               # 22 + n_ext
        self.bits_per_carrier = self.bits_per_carrier + [1] * n_ext   # DBPSK = 1 bit
        self.ring_carrier = self.ring_carrier + [False] * n_ext
        self.phase_bits = self.phase_bits + [1] * n_ext               # M=2
        self.M = self.M + [2] * n_ext
        self._gray = self._gray + [_gray_tables(1) for _ in range(n_ext)]
        self.bits_per_sym = int(sum(self.bits_per_carrier))
        self.gross_bps = self.bits_per_sym / (self.N / FS)

        # Widen the TX pre-emphasis to cover the ext carriers, then boost them.
        # Recompute from the published master3 H(f) over ALL freqs (base + ext),
        # exactly as both parents do, so the base amplitudes are bit-identical.
        params = rcs.load_params()
        Hf = params["Hf_magnitude"]
        fm = np.asarray(Hf["sounder_freqs_master3"], float)
        Hd = np.asarray(Hf["H_db_master3"], float)
        Hl = 10.0 ** (np.interp(self.freqs, fm, Hd) / 20.0)
        Hl = Hl / (Hl.max() + 1e-12)
        tx_amp = 1.0 / np.clip(Hl, 0.05, None)
        tx_amp[ext_idx] *= 10.0 ** (self.ext_boost_db / 20.0)   # ext boost
        self.tx_amp = (tx_amp / tx_amp.max()).astype(np.float64)

        self.name = f"Stack_8dpsk{n8}_ext{n_ext}_N256_sp2"

    # The inherited modulate/demodulate operate over self.data_idx / self.M /
    # self._gray / self.tx_amp / self.freqs, all of which now include the ext
    # carriers, so NO override is needed.  The RX window orthogonality guard still
    # holds (same N/spacing), and the inherited _phi0 uses self.P+1 carriers -- we
    # override it here so the Schroeder phases cover the FULL widened carrier set.

    def _phi0(self):
        nc = len(self.freqs)
        k = np.arange(nc, dtype=np.float64)
        return -np.pi * k * k / nc


# ===========================================================================
def build(n8: int = 3, n_ext: int = 4, *, ext_boost_db: float = EXT_BOOST_DB,
          rs_k=None) -> FuncScheme:
    """Return a hyp_common.FuncScheme for the stacked flagship.

    n8     : number of CSI-cleanest base carriers bumped to 8-DPSK (3 -> dapsk
             winner set 3375/5250/750; 7 -> robust set, all p90<18 deg).
    n_ext  : number of ext-band DBPSK carriers above 9000 Hz (4 or 6).
    """
    sch = StackedFlagship(n8=n8, n_ext=n_ext, ext_boost_db=ext_boost_db)
    fs = FuncScheme(name=sch.name, gross_bps=float(sch.gross_bps),
                    modulate=sch.modulate, demodulate=sch.demodulate)
    fs.rs_k = rs_k
    fs._scheme = sch
    return fs


def _clean_ber(fs) -> float:
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 4000, dtype=np.uint8)
    audio = fs.modulate(bits)
    rx = fs.demodulate(np.asarray(audio, np.float32), 48000)
    m = min(len(bits), len(rx))
    return float(np.mean(bits[:m] != rx[:m])) + (len(bits) - m) / len(bits)


if __name__ == "__main__":
    print("== stacked_flagship clean-channel self-check (RED/GREEN) ==", flush=True)
    for (n8, ne) in [(3, 4), (3, 6), (7, 4), (7, 6), (3, 0)]:
        fs = build(n8, ne)
        ber = _clean_ber(fs)
        ok = "PASS" if ber < 1e-3 else "FAIL"
        print(f"  n8={n8} n_ext={ne}  {fs.name:34s} gross={fs.gross_bps:7.1f} "
              f"clean_ber={ber:.2e}  [{ok}]", flush=True)
        assert ber < 1e-3, f"clean BER {ber} (n8={n8},n_ext={ne}) -- not invertible"
    print("  ALL PASSED", flush=True)
