"""make_d2x_stereo_indep_cal.py -- INDEPENDENT-payload stereo d2x calibration master.

The rigorous 2x proof. Unlike make_d2x_stereo_cal.py (the SAME payload on L and R),
this puts a DIFFERENT seeded payload on each channel, each encoded with the proven
d2x r6 config (Dense2x DQPSK, P=21, RS(255,159), ~4910 net bps). Decoding ch0 against
the L payload AND ch1 against the R payload -- both byte-exact -- proves the two
channels carry genuinely independent data, i.e. true 2x (~9820 net bps), not one
signal copied/bled across both. (Same-payload can't tell those two apart.)

The teeth: a CROSS-decode (ch0 vs the R manifest) decodes RS-clean to ch0's own
payload, which differs from R's reference -> byte_exact False, BER ~0.5. That mismatch
is what makes the same-payload ambiguity impossible here.

Outputs (in experiments/tape_v2/):
    cal_d2x_L.wav / cal_d2x_R.wav             per-channel mono bodies (intermediate, gitignored)
    cal_d2x_L_manifest.json / _R_manifest     per-channel decode manifests
    cal_d2x_L_payload.bin / _R_payload.bin     per-channel raw payload sidecars
    cal_d2x_stereo_indep.wav                   the stereo master to record (gitignored)
    cal_d2x_stereo_indep.json                  routing/probe + per-channel seed/manifest sidecar

Decode each channel against ITS OWN manifest:
    python3 decode_d2x_cal.py <capture> --channel 0 --manifest cal_d2x_L_manifest.json
    python3 decode_d2x_cal.py <capture> --channel 1 --manifest cal_d2x_R_manifest.json
Routing/crosstalk:
    python3 analyze_stereo_cal.py <capture> --sidecar cal_d2x_stereo_indep.json

Run:  python3 make_d2x_stereo_indep_cal.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
TAPE_V2 = ROOT / "experiments" / "tape_v2"
DOOM_SHIP = TAPE_V2 / "doom_ship"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", TAPE_V2, DOOM_SHIP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from m10doom3_master import build_tape  # noqa: E402
import make_stereo_cal_master as M  # noqa: E402  (probe helpers + params: SR, _tone, _silence, ...)

SR = M.SR
PAYLOAD_BYTES = 150_000
FRAME_BYTES = 5100          # same as make_d2x_cal.py (proven r6 calibration framing)
SEED_L = 1234               # matches the proven mono/same-payload cal for continuity
SEED_R = 5678               # different payload -> the independence the proof needs


def _build_body(seed: int, tag: str):
    """Encode a 150 KB seeded payload to a mono d2x body via the proven build_tape."""
    rng = np.random.default_rng(seed)
    payload = bytes(rng.integers(0, 256, size=PAYLOAD_BYTES, dtype=np.uint8))
    wav = TAPE_V2 / f"cal_d2x_{tag}.wav"
    manifest = TAPE_V2 / f"cal_d2x_{tag}_manifest.json"
    sidecar = TAPE_V2 / f"cal_d2x_{tag}_payload.bin"
    sidecar_rel = f"cal_d2x_{tag}_payload.bin"
    res = build_tape(
        payload, out_wav=wav, manifest_path=manifest, sidecar_path=sidecar,
        payload_sidecar_rel=sidecar_rel, section_name=f"cal_d2x_{tag}_r6",
        frame_bytes=FRAME_BYTES, tape_id=f"cal_d2x_{tag}",
        role="calibration-raw-payload-indep", verbose=False,
    )
    body, sr = sf.read(str(wav), dtype="float32", always_2d=False)
    if sr != SR:
        raise SystemExit(f"body sr {sr} != {SR}")
    if body.ndim > 1:
        body = body[:, 0]
    return payload, body.astype(np.float32), res, sidecar_rel, manifest.name


def main() -> None:
    import warnings
    warnings.filterwarnings("ignore")

    plL, bodyL, resL, sideL, manL = _build_body(SEED_L, "L")
    plR, bodyR, resR, sideR, manR = _build_body(SEED_R, "R")
    assert plL != plR, "payloads must differ for an independence proof"

    # Same payload size + framing -> identical body length; pad defensively to align.
    if len(bodyL) != len(bodyR):
        n = max(len(bodyL), len(bodyR))
        bodyL = np.concatenate([bodyL, np.zeros(n - len(bodyL), np.float32)])
        bodyR = np.concatenate([bodyR, np.zeros(n - len(bodyR), np.float32)])

    # Crosstalk-probe lead-in (L-only tone, then R-only tone), exactly as the
    # same-payload make_d2x_stereo_cal.py -- so analyze_stereo_cal can localize routing.
    pre, mid, post = M._silence(M.PRE_SIL), M._silence(M.MID_SIL), M._silence(M.POST_SIL)
    probe_amp = min(0.7, max(0.3, 0.9 * float(max(np.max(np.abs(bodyL)),
                                                   np.max(np.abs(bodyR))))))
    tL = M._tone(M.PROBE_L_HZ, M.PROBE_DUR, probe_amp)
    tR = M._tone(M.PROBE_R_HZ, M.PROBE_DUR, probe_amp)
    sil = M._silence(M.PROBE_DUR)
    lead_L = np.concatenate([pre, tL, mid, sil, post])
    lead_R = np.concatenate([pre, sil, mid, tR, post])
    L = np.concatenate([lead_L, bodyL])
    R = np.concatenate([lead_R, bodyR])

    out = TAPE_V2 / "cal_d2x_stereo_indep.wav"
    sf.write(str(out), np.column_stack([L, R]), SR, subtype="FLOAT")

    pre_n = len(pre)
    pd = int(round(M.PROBE_DUR * SR))
    r_start = pre_n + pd + len(mid)
    side = {
        "sr": SR, "channels": ["L", "R"], "independent_payloads": True,
        "leadin_seconds": round(len(lead_L) / SR, 3),
        "L": {"manifest": manL, "payload": sideL, "seed": SEED_L,
              "net_bps": resL["net_bps"]},
        "R": {"manifest": manR, "payload": sideR, "seed": SEED_R,
              "net_bps": resR["net_bps"]},
        "probes": {
            "L": {"freq_hz": M.PROBE_L_HZ, "channel": "L",
                  "start_frame": pre_n, "end_frame": pre_n + pd},
            "R": {"freq_hz": M.PROBE_R_HZ, "channel": "R",
                  "start_frame": r_start, "end_frame": r_start + pd},
        },
    }
    (TAPE_V2 / "cal_d2x_stereo_indep.json").write_text(json.dumps(side, indent=2) + "\n")

    print(f"wrote {out.name}  {len(L) / SR:.1f}s stereo ({L.nbytes * 2 / 1e6:.0f} MB)  "
          f"probe_amp={probe_amp:.2f}")
    print(f"  L: seed {SEED_L}  {resL['net_bps']:.0f} net bps  -> {manL} / {sideL}")
    print(f"  R: seed {SEED_R}  {resR['net_bps']:.0f} net bps  -> {manR} / {sideR}")
    print(f"  payloads differ: {plL != plR}  (150000 B each, independent)")
    print("wrote sidecar cal_d2x_stereo_indep.json")


if __name__ == "__main__":
    main()
