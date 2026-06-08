"""dd_references.py — in-run reference anchors for deep-dive #2.

Re-measures, on BOTH the sim 'normal' and the harsh real-proxy (worn + 0.88x)
channels:
  * MFSK-32 naive (fixed-window demod) — the prior frontier yardstick.
  * MFSK-32 + flutter tracker (dd.tracked_tone_demod) — the bridged version.

Also exposes a TrackedMFSK Scheme wrapper other experiments can import, plus a
real-channel SURVIVAL metric (fraction of seeds whose whole file is recoverable).
"""
from __future__ import annotations
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import numpy as np
import dd_common as dd
import hyp_common as hc

FS = dd.FS
RESULTS = pathlib.Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)

# Recoverable-BER threshold for the per-seed whole-file SURVIVAL metric on the
# real channel. A seed below this decodes to a recoverable file; a seed above it
# has lost symbol sync (catastrophic) and the file is lost. 3e-2 -> outer rate
# >= 0.55, comfortably codeable; sync-loss seeds sit at ~0.2-0.4 BER.
SURVIVE_BER = 3e-2


def survival_fraction(per_seed_ber, thresh=SURVIVE_BER):
    a = np.asarray(per_seed_ber, dtype=float)
    return float(np.mean(a <= thresh)) if len(a) else 0.0


class TrackedMFSK:
    """MFSK-32 whose demod is the flutter tracker. Modulate is the stock MFSK."""
    def __init__(self, M=32):
        self._inner = dd.mfsk32_scheme() if M == 32 else _mfsk(M)
        self.M = self._inner.M
        self.bps = self._inner.bits_per_sym
        self.N = self._inner.samples_per_sym
        self.freqs = self._inner.freqs
        self.gross_bps = self._inner.gross_bps
        self.name = f"MFSK{self.M}_tracked"
        self.preamble_seconds = self._inner.preamble_seconds
        self.erasure_fn = None

    def modulate(self, bits):
        return self._inner.modulate(bits)

    def demodulate(self, audio, sr):
        n_bits = 1 << 20  # decode all available
        syms, drifts, locks = dd.tracked_tone_demod(
            audio, self.freqs, self.N, self.bps, n_bits=n_bits,
            preamble_seconds=self.preamble_seconds)
        out = []
        for e in syms:
            s = int(np.argmax(e))
            out.extend([(s >> (self.bps - 1 - j)) & 1 for j in range(self.bps)])
        return np.array(out, dtype=np.uint8)


def _mfsk(M):
    from hyp_h2_mfsk import MFSKScheme
    return MFSKScheme(M=M, walsh_k=0)


def main():
    seeds = 12
    refs = {}
    schemes = {
        "MFSK32_naive": dd.mfsk32_scheme(),
        "MFSK32_tracked": TrackedMFSK(32),
    }
    for key, sch in schemes.items():
        out = dd.evaluate_dual(sch, n_seeds=seeds)
        for ch in ("sim", "real"):
            out[ch]["survival"] = survival_fraction(out[ch]["per_seed_ber"])
        refs[key] = out
        print(dd.fmt(out))
        print(f"     survival sim={out['sim']['survival']:.2f} "
              f"real={out['real']['survival']:.2f}")
    with open(RESULTS / "references.json", "w") as f:
        json.dump(refs, f, indent=2, default=float)
    print(f"[saved] {RESULTS/'references.json'}")


if __name__ == "__main__":
    main()
