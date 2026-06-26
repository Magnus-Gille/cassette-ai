"""Generate R0 (robust DQPSK) parity fixtures for the Rust port.

Reuses the per-channel `<chan>_nominal.wav` already produced by gen_floor_fixtures.py
(same master, same global-synced nominal audio) — we only add the R0 section
metadata + ground-truth payload + per-codeword CRC32. The Rust DQPSK decoder must
recover the R0 payload BYTE-EXACT from those nominal WAVs across clean/normal/worn.

Run gen_floor_fixtures.py FIRST (it writes the *_nominal.wav + *.json this reads).
Run: python3 experiments/tape_v2/rust_fixtures/gen_r0_fixtures.py
"""
from __future__ import annotations
import json, pathlib, sys
import numpy as np, soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m10_decode as m10        # noqa: E402
OUT = _HERE / "fixtures"
SR = 48000
R0_NAME = "fs_r0_robust_dqpsk_p10_rs127"


def _r0_section(manifest):
    return [s for s in manifest["ws_payloads"] if s.get("name") == R0_NAME][0]


def main():
    manifest = json.loads((ROOT / "experiments/tape_v2/fullspectrum_manifest.json").read_text())
    sec = _r0_section(manifest)
    meta = sec["meta"]
    sidecar = (ROOT / "experiments/tape_v2" / sec["payload_sidecar"]).read_bytes()

    # static R0 section descriptor (channel-independent)
    desc = {
        "name": sec["name"],
        "tx_chirp0": int(manifest["tx_chirp0"]),
        "tx_chirp1": int(manifest["tx_chirp1"]),
        "frame_starts": [int(s) for s in sec["frame_starts"]],
        "body_end": int(sec["body_end"]),
        "dqpsk_params": sec["dqpsk_params"],
        "carrier_freqs_hz": sec["carrier_freqs_hz"],
        "pilot_hz_actual": sec.get("pilot_hz_actual"),
        "meta": {k: (int(v) if isinstance(v, (int, np.integer)) else v) for k, v in meta.items()},
        "crc32_codewords": [int(c) for c in sec["crc32_codewords"]],
        "payload_len": int(meta["payload_len"]),
        "payload": list(sidecar),
    }
    (OUT / "r0_section.json").write_text(json.dumps(desc))
    print(f"[r0] section: P={sec['dqpsk_params']['P']} N={sec['dqpsk_params']['N']} "
          f"sp={sec['dqpsk_params']['spacing']} pilot={sec.get('pilot_hz_actual')} "
          f"RS(255,{meta['rs_k']}) n_cw={meta['n_codewords']} n_frames={meta['n_frames']} "
          f"payload={len(sidecar)}B")

    ok = True
    for label in ("clean", "normal", "worn"):
        jf = OUT / f"{label}.json"
        wf = OUT / f"{label}_nominal.wav"
        if not jf.exists() or not wf.exists():
            print(f"[r0] SKIP {label}: run gen_floor_fixtures.py first ({wf.name} missing)")
            continue
        align = int(json.loads(jf.read_text())["sync"]["align"])
        audio_nom, sr = sf.read(str(wf), dtype="float32", always_2d=False)
        assert sr == SR
        ledger = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
        r, _assembled = m10._decode_section(np.asarray(audio_nom), sec, align, ledger,
                                            rescue=False, verbose=False)
        be = bool(r["byte_exact"])
        ok &= be
        print(f"[r0] {label:6s} align={align:+d} byte_exact={be} "
              f"cwFail={r['rs_codewords_failed']}/{r['n_codewords']} "
              f"front_end={r.get('front_end_used')}")
    print(f"[r0] {'ALL PYTHON-SIDE BYTE-EXACT' if ok else 'WARNING: a channel was NOT byte-exact'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
