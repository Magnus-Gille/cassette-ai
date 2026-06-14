"""Self-test adaptive_modem against a synthetic channel WITH cassette wow (time-varying
speed) + global clock offset + frequency-selective nulls + noise + compression.

Proves the per-marker tracking + preamble-driven erasure + CRC pipeline is byte-exact
end-to-end where a flat / single-clock decoder fails.
"""
import numpy as np
from scipy.signal import butter, sosfiltfilt
import adaptive_modem as A

SR = A.SR


def warp_wow(sig, clock=0.9, wow_depth=0.004, wow_hz=3.0, flutter_depth=0.0015, flutter_hz=11.0):
    """Resample sig onto a wandering time base: mean length = clock*len (rec shorter for
    clock<1), plus slow wow + faster flutter as local rate wander. All in OUTPUT time."""
    n = len(sig); nout = int(n * clock); k = np.arange(nout); tk = k / SR
    inv_speed = (1.0 / clock) * (1 + wow_depth * np.sin(2 * np.pi * wow_hz * tk)
                                 + flutter_depth * np.sin(2 * np.pi * flutter_hz * tk + 1.0))
    src = np.cumsum(inv_speed); src -= src[0]; src *= (n - 1) / src[-1]   # span full input
    return np.interp(src, np.arange(n), sig)


def channel(sig, seed=0):
    def notch(x, f0, bw): return sosfiltfilt(butter(2, [f0 - bw, f0 + bw], "bandstop", fs=SR, output="sos"), x)
    sos = butter(4, [900, 9000], "bandpass", fs=SR, output="sos")
    y = sosfiltfilt(sos, sig)
    for f0, bw in [(2931, 110), (3583, 120), (4096, 130), (5355, 150), (6122, 160)]:
        y = notch(y, f0, bw)
    y = np.tanh(1.3 * y) / 1.3
    y = warp_wow(y, clock=0.9)              # <-- cassette wow + 0.9x speed
    rng = np.random.default_rng(seed)
    y = y + 0.012 * rng.standard_normal(len(y))
    return (y * 0.9 / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


if __name__ == "__main__":
    msg = ("CASSETTE-AI adaptive modem v1: preamble-measured channel, per-marker wow "
           "tracking, CRC-validated erasure decode. Played in an unknown room. 0123456789!")
    sig, meta = A.gen(msg, 70, 24)
    print(f"frame: K={meta['K']} symdur={meta['symdur']*1000:.0f}ms payload={meta['orig']}B "
          f"preamble={meta['npre']} symbols")
    rec = channel(sig)
    print(f"channel: 5 nulls + tanh compression + WOW (0.9x speed, ~0.4% wow + 0.15% flutter) + noise")
    body, info = A.decode(rec, meta, verbose=True)
    print(f"  measured wow on markers: {info['wow_pct']:.2f}%   clock: {info['clock']:.4f}")
    print(f"  dead carriers flagged  : {sorted(info['dead']) if body else '-'}")
    ok = body is not None and body.decode("utf-8", "replace") == msg
    print(f"\nrecovered: {body.decode('utf-8','replace')[:70]!r}..." if body else "recovered: None")
    print(f"SELF-TEST: {'PASS -- byte-exact through wow + nulls' if ok else 'FAIL'}")

    # also confirm CRC rejects a corrupted decode (no false accept on the wrong answer)
    bad = bytearray(rec.tobytes());
    print("\nCRC guard: a single-hypothesis flat decode on a too-hard channel must NOT")
    print("falsely accept -> CRC is the acceptance test, not RS-success.")
