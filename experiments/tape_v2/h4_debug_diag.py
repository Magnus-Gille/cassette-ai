"""h4_debug_diag.py — diagnose the H4 demod on the lite channel.

Variants of the demod (pilot correction / drift sign / refinement) on one
P6_N256 frame train through channel_v2(aac=False, snr=45), plus per-carrier
channel gain |c| profile and the pilot dtau trace.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                  # noqa: E402
import sim_v2                            # noqa: E402
from h4_dqpsk import DQPSKScheme, build_section, FS  # noqa: E402

rng = np.random.default_rng(42)


def demod_variant(sch, win, nd, *, pilot=True, drift_sign=0, refine=False,
                  ema=0.0):
    """drift_sign: 0=no recentre, +1=drift+=dtau*FS (orig), -1=drift-=dtau*FS."""
    y = np.asarray(win, np.float64)
    ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
    total = nd + 1
    nc = sch.P + 1
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    fpil = sch.freqs[sch.pilot_idx]
    c = np.zeros((total, nc), np.complex128)
    dtau = np.zeros(total)
    dtau_s = 0.0
    drift = 0.0
    for i in range(total):
        base = ds + i * N + int(round(drift))
        lo = base + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(sch.freqs, tt))
        c[i] = E @ (seg * sch._win)
        if i > 0 and pilot:
            dp = float(np.angle(c[i, sch.pilot_idx] * np.conj(c[i - 1, sch.pilot_idx])))
            d = dp / (2 * np.pi * fpil)
            dtau_s = (1 - ema) * d + ema * dtau_s
            dtau[i] = dtau_s
            if drift_sign:
                drift += drift_sign * dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx])
    if pilot:
        dphi = dphi - 2 * np.pi * np.outer(dtau[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    if refine:
        res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_res = num / (2 * np.pi * den)
        dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
        q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
    return q, c, dtau


def main():
    sch = DQPSKScheme(6, 256, 4)
    nd = 400
    bits = rng.integers(0, 2, nd * sch.bits_per_sym).astype(np.uint8)
    fa = sch.modulate(bits)
    section, starts = build_section([fa])
    y = sim_v2.channel_v2(section, profile="tape7", aac=False, seed_offset=0,
                          snr_db=45.0)
    st = starts[0]
    win = y[max(0, st - int(0.3 * FS)): st + len(fa) + int(0.05 * FS)]

    # truth quadrants
    bm = bits.reshape(nd, sch.P, 2)
    from h4_dqpsk import GRAY_ENC
    tq = np.array([[GRAY_ENC[(int(a), int(b))] for a, b in row] for row in bm])

    variants = [
        ("no-pilot no-drift no-refine", dict(pilot=False, drift_sign=0, refine=False)),
        ("pilot   no-drift no-refine", dict(pilot=True, drift_sign=0, refine=False)),
        ("pilot   drift(+) no-refine", dict(pilot=True, drift_sign=+1, refine=False)),
        ("pilot   drift(-) no-refine", dict(pilot=True, drift_sign=-1, refine=False)),
        ("pilot   drift(-) refine   ", dict(pilot=True, drift_sign=-1, refine=True)),
        ("pilot   drift(-) ref ema.5", dict(pilot=True, drift_sign=-1, refine=True, ema=0.5)),
        ("nopilot drift(0) refine   ", dict(pilot=False, drift_sign=0, refine=True)),
    ]
    for name, kw in variants:
        q, c, dtau = demod_variant(sch, win, nd, **kw)
        ser = (q != tq).mean(axis=0)
        print(f"{name}: SER/carrier = {np.array2string(ser, precision=3)}  "
              f"mean={ser.mean():.4f}")
    # channel profile
    q, c, dtau = demod_variant(sch, win, nd, pilot=True, drift_sign=-1)
    amp = np.abs(c).mean(axis=0)
    amp = amp / amp.max()
    print("\ncarriers (Hz):", [round(f) for f in sch.freqs])
    print("pilot idx:", sch.pilot_idx)
    print("mean |c| (norm):", np.array2string(amp, precision=3))
    print("dtau samples: rms={:.3f} max={:.3f}".format(
        np.std(dtau * FS), np.max(np.abs(dtau * FS))))
    # phase-error spread per carrier (vs truth, diagnostic only)
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau[1:], sch.freqs[sch.data_idx])
    err = (dphi - tq * (np.pi / 2) + np.pi) % (2 * np.pi) - np.pi
    print("phase-err rms/carrier (rad):", np.array2string(err.std(axis=0), precision=3))


if __name__ == "__main__":
    main()
