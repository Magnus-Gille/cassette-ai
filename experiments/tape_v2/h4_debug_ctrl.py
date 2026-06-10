"""h4_debug_ctrl.py — isolate why the WS control rung is worse in my harness.

Steps: (0) no-channel decode of the control section (must be raw BER ~0),
(1) rcs.real_channel only (no AAC), (2) channel_v2 aac=False, (3) full
channel_v2. Compare raw BER at each stage, seed 0.
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                 # noqa: E402
from m3_codec import Rung                # noqa: E402
import real_channel_sim as rcs           # noqa: E402
import sim_v2                            # noqa: E402
from assault_widespace import build as ws_build, _demod_frame_achievable, eq_for  # noqa: E402
from h4_dqpsk import (build_section, nominal_frame_bits, _payload_slice, FS,
                      PAD_LO_S, PAD_HI_S, measure_sounder_eq)  # noqa: E402


def decode_section(y, ws, eq, starts, frame_audios, tx_frames, meta):
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    per_frame = []
    for fi, st in enumerate(starts):
        nsym = int(math.ceil(nom[fi] / ws.bits_per_sym))
        flen = len(frame_audios[fi])
        win = y[max(0, st - pad_lo): min(len(y), st + flen + pad_hi)]
        rb = np.asarray(_demod_frame_achievable(ws, eq, win, nsym, "contrast"),
                        np.uint8).ravel()
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(rb))
        e = int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_err += e
        raw_tot += len(tb)
        per_frame.append(round(e / len(tb), 3))
    return raw_err / max(1, raw_tot), per_frame


def main():
    ws = ws_build(16, 1, 3, 256)
    params = rcs.load_params()
    eq = eq_for(ws, params, "master3")
    payload = _payload_slice(16384, 8192)
    rung = Rung(name="ctrl", M=16, K=1, rs_n=255, rs_k=191, frame_bytes=510)
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [np.asarray(ws.modulate(fb.astype(np.uint8)), np.float32)
                    for fb in tx_frames]
    section, starts, spans = build_section(frame_audios)
    print(f"section: {len(section)/FS:.1f}s, {len(starts)} frames")

    ber, pf = decode_section(section.astype(np.float64), ws, eq, starts,
                             frame_audios, tx_frames, meta)
    print(f"stage 0 none (params EQ):       rawBER={ber:.4f}")

    for seed in (0, 1):
        y3 = sim_v2.channel_v2(section, profile="tape7", aac=True,
                               seed_offset=seed)
        ber_a, _ = decode_section(y3, ws, eq, starts, frame_audios, tx_frames, meta)
        eq_m = measure_sounder_eq(y3, spans, ws.freqs)
        ber_b, pf = decode_section(y3, ws, eq_m, starts, frame_audios, tx_frames, meta)
        print(f"seed{seed} aac=True: paramsEQ rawBER={ber_a:.4f} | "
              f"sounderEQ rawBER={ber_b:.4f} frames={pf}")
        print(f"   eq_m={np.array2string(eq_m, precision=2)}")


if __name__ == "__main__":
    main()
