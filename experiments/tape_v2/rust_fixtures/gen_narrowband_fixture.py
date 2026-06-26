"""Generate the golden parity fixture for the Rust narrowband-MNIST decoder.

Mirrors gen_floor_fixtures.py but for the narrowband (470-2200 Hz) combinatorial-
MFSK M12/K2 RS(255,95) MNIST master (make_narrowband_master.py). Dumps:

  fixtures/narrowband_nominal.wav   audio_nominal AFTER am2.global_sync_and_resample (mono f32)
  fixtures/narrowband.json          align + section{M,K,f_low,f_high,frame_starts,body_end}
                                    + meta + ground-truth payload (mnist-12.onnx bytes)

The Rust test (tests/narrowband_parity.rs) must reproduce mnist-12.onnx byte-exact
from narrowband_nominal.wav via the BAND-parameterized combo path
(ComboScheme::new_band / FloorSection.f_low,f_high). Run:

    python3 experiments/tape_v2/rust_fixtures/gen_narrowband_fixture.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import make_narrowband_master as nbm           # noqa: E402
import analyze_master2 as am2                  # noqa: E402
import m3_codec as codec                       # noqa: E402
from d3d4_combo_tracked import make_tracked_combo  # noqa: E402

SR = 48_000
OUT = _HERE / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    print("[gen] building narrowband MNIST master (temp)...")
    tmp = pathlib.Path(tempfile.mkdtemp()) / "narrowband_master_fix.wav"
    nbm.build(tmp)
    manifest = json.loads(nbm.MANIFEST_PATH.read_text())
    sec = manifest["ws_payloads"][0]
    meta = sec["meta"]
    m_, k_ = int(meta["M"]), int(meta["K"])
    f_low, f_high = float(meta["f_low"]), float(meta["f_high"])

    audio, sr = sf.read(str(tmp), dtype="float32", always_2d=False)
    assert sr == SR, sr
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.asarray(audio, dtype=np.float32)

    # global chirp-pair sync -> nominal (clean: no channel, just the master itself)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = np.asarray(sync["audio_nominal"], dtype=np.float32)
    align = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])

    # decode in Python (band-matched) to confirm byte-exact before dumping
    sch = make_tracked_combo(m_, k_, f_low=f_low, f_high=f_high)
    starts = [int(s) for s in sec["frame_starts"]]
    body_end = int(sec["body_end"])
    sidecar = (pathlib.Path(nbm._HERE) / sec["payload_sidecar"]).read_bytes()
    guard = int(0.05 * SR)
    n = len(audio_nom)
    frames_bits = []
    for i, st in enumerate(starts):
        a = max(0, align + st - guard)
        nxt = starts[i + 1] if i + 1 < len(starts) else body_end
        b = min(n, max(a + 1, align + int(nxt)))
        seg = np.asarray(audio_nom[a:b], dtype=np.float32)
        try:
            rb = np.asarray(sch.demodulate(seg, SR), dtype=np.uint8)
        except Exception:  # noqa: BLE001
            rb = np.zeros(0, dtype=np.uint8)
        frames_bits.append(rb)
    recovered = codec.decode_payload(frames_bits, meta)
    n_fail = int(getattr(codec.decode_payload, "last_codewords_failed", 0))
    byte_exact = bool(recovered == sidecar)
    assert byte_exact, f"Python decode NOT byte-exact (cwFail={n_fail}) — aborting fixture"

    sf.write(str(OUT / "narrowband_nominal.wav"), audio_nom, SR, subtype="FLOAT")
    rec = {
        "label": "narrowband",
        "byte_exact_python": byte_exact,
        "rs_codewords_failed": n_fail,
        "sync": {
            "speed": float(sync["speed"]),
            "resample_num": int(sync["resample_num"]),
            "resample_den": int(sync["resample_den"]),
            "chirp0_nominal": int(sync["chirp0_nominal"]),
            "tx_chirp0": int(manifest["tx_chirp0"]),
            "tx_chirp1": int(manifest["tx_chirp1"]),
            "align": align,
        },
        "section": {
            "name": sec["name"],
            "M": m_, "K": k_, "f_low": f_low, "f_high": f_high,
            "frame_starts": starts,
            "body_end": body_end,
            "guard_samples": guard,
        },
        "meta": {k: (int(v) if isinstance(v, (int, np.integer)) else v)
                 for k, v in meta.items()},
        "payload_len": int(meta["payload_len"]),
        "payload": list(sidecar),
    }
    (OUT / "narrowband.json").write_text(json.dumps(rec))
    print(f"[gen] narrowband align={align:+d} speed={sync['speed']:.5f} "
          f"nom_len={len(audio_nom)} payload={len(sidecar)}B "
          f"M{m_}K{k_} band {f_low:.0f}-{f_high:.0f}Hz "
          f"py_byte_exact={byte_exact} cwFail={n_fail}/{meta['n_codewords']}")
    print("[gen] wrote fixtures/narrowband_nominal.wav + fixtures/narrowband.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
