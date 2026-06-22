"""make_d2x_stereo_cal.py -- stereo d2x calibration master.

Takes the proven mono d2x body (cal_d2x_mono.wav, ~4910 net bps) and duplicates it
on L+R with the same front L-only / R-only crosstalk-probe lead-in used by
make_stereo_cal_master.py. Decoding each channel independently demonstrates true 2x
at the high bitrate (~9820 net bps stereo) over the electrical line-in.

Decode:   python3 decode_d2x_cal.py <capture>.wav --channel 0   (L, vs cal_d2x_payload.bin)
          python3 decode_d2x_cal.py <capture>.wav --channel 1   (R, same payload)
Routing/crosstalk:  python3 analyze_stereo_cal.py <capture>.wav --sidecar cal_d2x_stereo.json

Same payload on both channels keeps it simple; on the electrical loopback crosstalk is
~ -56 dB, so the channels are effectively independent. (For a rigorous real-tape 2x
proof, encode two independent payloads -- a later step.)

Run:  python3 make_d2x_stereo_cal.py
"""
import json
import pathlib

import numpy as np
import soundfile as sf

import make_stereo_cal_master as M  # reuse probe helpers + params (SR, _tone, _silence, ...)

HERE = pathlib.Path(__file__).resolve().parent
BODY = HERE / "cal_d2x_mono.wav"
OUT = HERE / "cal_d2x_stereo.wav"
SIDE = HERE / "cal_d2x_stereo.json"
SR = M.SR


def main() -> None:
    if not BODY.exists():
        raise SystemExit(f"missing {BODY} -- run make_d2x_cal.py first")
    body, sr = sf.read(str(BODY), dtype="float32", always_2d=False)
    if sr != SR:
        raise SystemExit(f"body sr {sr} != {SR}")
    if body.ndim > 1:
        body = body[:, 0]

    pre, mid, post = M._silence(M.PRE_SIL), M._silence(M.MID_SIL), M._silence(M.POST_SIL)
    probe_amp = min(0.7, max(0.3, 0.9 * float(np.max(np.abs(body)))))
    tL = M._tone(M.PROBE_L_HZ, M.PROBE_DUR, probe_amp)
    tR = M._tone(M.PROBE_R_HZ, M.PROBE_DUR, probe_amp)
    sil = M._silence(M.PROBE_DUR)

    lead_L = np.concatenate([pre, tL, mid, sil, post])
    lead_R = np.concatenate([pre, sil, mid, tR, post])
    L = np.concatenate([lead_L, body])
    R = np.concatenate([lead_R, body])
    sf.write(str(OUT), np.column_stack([L, R]), SR, subtype="FLOAT")

    pre_n = len(pre)
    pd = int(round(M.PROBE_DUR * SR))
    r_start = pre_n + pd + len(mid)
    side = {
        "sr": SR, "channels": ["L", "R"], "body_source": BODY.name,
        "leadin_seconds": round(len(lead_L) / SR, 3),
        "probes": {
            "L": {"freq_hz": M.PROBE_L_HZ, "channel": "L",
                  "start_frame": pre_n, "end_frame": pre_n + pd},
            "R": {"freq_hz": M.PROBE_R_HZ, "channel": "R",
                  "start_frame": r_start, "end_frame": r_start + pd},
        },
    }
    SIDE.write_text(json.dumps(side, indent=2) + "\n")
    print(f"wrote {OUT.name}  {len(L)/SR:.1f}s stereo ({L.nbytes*2/1e6:.0f} MB)  "
          f"probe_amp={probe_amp:.2f}")
    print(f"wrote sidecar {SIDE.name}")


if __name__ == "__main__":
    main()
