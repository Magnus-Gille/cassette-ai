"""make_narrowband_master.py -- a READY-TO-BURN narrowband cassette master that
carries the MNIST ONNX model on the R-1 combinatorial-MFSK floor PHY, re-gridded
into the ~470-2200 Hz band a worn Grundig deck still passes cleanly.

WHY NARROWBAND
--------------
The worn deck only passes <=~2.4 kHz cleanly. The R-1 floor rung
(non-coherent combinatorial-MFSK, energy demod + per-symbol timing tracker --
the PHY that recovered the 153 KB cassette-LLM byte-exact off a worn tape) is
ALREADY band-parameterized: ComboMFSKScheme(M, K, f_low=, f_high=). Here we drop
M to 12, light K=2 of them, and pack the whole tone bank into [470, 2200] Hz, so
every carrier lives under the deck's clean ceiling. RS(255,95) gives a heavy FEC
margin; the net rate is ~331 bps -> ~10 min of tape for the ~26 KB model. That's
fine: the point is a robust, worn-deck-survivable carrier, not speed.

LAYOUT (mono, 48 kHz, float):
  [lead 1 s]
  global up-chirp (tx_chirp0)          <- the SAME chirp anchors as the full-spectrum master
  0.40 s gap
  combo section: per-frame combinatorial-MFSK (each frame self-syncs on its own
                 0.25 s chirp preamble), RS(255,95) + global column-interleave
  1.0 s silence
  global down-chirp (tx_chirp1)
  0.40 s gap
  [tail 1 s]
  -> peak-normalize 0.70 (SOP).

ENCODE: m3_codec.encode_payload (RS(255,95) -> global column-interleave -> per-frame
bit chunks). Each frame is modulated by ComboMFSKScheme.modulate (via
make_tracked_combo's underlying scheme, band 470-2200). frame_bytes is chosen so a
single-frame loss stays well within RS (each dead frame nicks ~frame_bytes/n_cw
bytes per codeword, must be <= (rs_n-rs_k)/2 = 80).

DECODE/VERIFY (in-process): mirror fullspectrum_decode._decode_combo_section --
am2.global_sync_and_resample -> slice frames by frame_starts+align -> band-matched
make_tracked_combo demod -> m3_codec.decode_payload -> assert byte-exact vs the
mnist sidecar.

Outputs (tracked except the WAV): narrowband_master.wav (gitignored),
narrowband_manifest.json, narrowband_sidecars/mnist-12.onnx.

Run:
    python3 experiments/tape_v2/make_narrowband_master.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import warnings
import zlib

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                     # noqa: E402
from m3_codec import Rung                                    # noqa: E402
from make_master2 import (                                   # noqa: E402
    GLOBAL_CHIRP_T, GLOBAL_CHIRP_F0, GLOBAL_CHIRP_F1,
    _make_global_chirp, _silence,
)
from d3d4_combo_tracked import make_tracked_combo            # noqa: E402

SR = codec.FS
assert SR == 48_000

MASTER_ID = "narrowband_mnist_v1"
WAV_PATH = _HERE / "narrowband_master.wav"
MANIFEST_PATH = _HERE / "narrowband_manifest.json"
SIDECAR_DIR = _HERE / "narrowband_sidecars"
MNIST_SRC = ROOT / "payloads" / "llm_tape_fit" / "mnist" / "mnist-12.onnx"

# ---- narrowband combo config ----------------------------------------------
M = 12
K = 2
F_LOW = 470.0
F_HIGH = 2200.0
RS_N = 255
RS_K = 95
FRAME_BYTES = 2000      # <= (RS_N-RS_K)/2 * n_cw guard; ~36 frames for ~26 KB

# ---- layout (mirror the full-spectrum master) ------------------------------
LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
PEAK = 0.70


def _codeword_crcs(message: bytes, rs_k: int) -> list[int]:
    """zlib.crc32 of each rs_k-byte codeword MESSAGE chunk (m8/m9/m10 convention)."""
    pad = (-len(message)) % rs_k
    padded = message + bytes(pad)
    return [zlib.crc32(padded[i:i + rs_k]) & 0xFFFFFFFF
            for i in range(0, len(padded), rs_k)]


def build(out_wav: pathlib.Path = WAV_PATH) -> dict:
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    payload = MNIST_SRC.read_bytes()
    print(f"[build] payload {MNIST_SRC.name}: {len(payload)} bytes")

    # ---- RS + interleave + per-frame bit chunks (m3_codec) ----
    rung = Rung(name="narrowband_mnist", M=M, K=K,
                rs_n=RS_N, rs_k=RS_K, frame_bytes=FRAME_BYTES)
    frames_bits, meta = codec.encode_payload(payload, rung)
    n_cw = meta["n_codewords"]
    # single-frame-loss guard: a dead frame nicks ~frame_bytes/n_cw bytes/codeword
    per_cw = FRAME_BYTES / n_cw
    assert per_cw <= (RS_N - RS_K) // 2, (
        f"frame_bytes too large: {per_cw:.1f} > {(RS_N - RS_K)//2} bytes/cw")
    print(f"[build] RS({RS_N},{RS_K}) n_cw={n_cw} n_frames={meta['n_frames']} "
          f"frame_bits={meta['frame_bits']} stream_bits={meta['stream_bits']} "
          f"(~{per_cw:.1f} bytes/cw per dead frame)")

    # ---- modem (band-parameterized combinatorial-MFSK) ----
    sch = make_tracked_combo(M, K, f_low=F_LOW, f_high=F_HIGH)
    gross = float(sch.gross_bps)
    net = gross * RS_K / RS_N
    print(f"[build] {sch.name}: N={sch.samples_per_sym} bps_sym={sch.bits_per_sym} "
          f"freqs {sch.freqs[0]:.1f}..{sch.freqs[-1]:.1f} Hz  "
          f"gross {gross:.1f}  net {net:.1f} bps")

    parts: list[np.ndarray] = []
    pos = 0

    def add(sig: np.ndarray) -> None:
        nonlocal pos
        sig = np.asarray(sig, dtype=np.float32)
        parts.append(sig)
        pos += len(sig)

    manifest: dict = {
        "SR": SR,
        "tape": MASTER_ID,
        "master_id": MASTER_ID,
        "product": "narrowband_mnist_floor_v1",
        "channels": ["mono"],
        "tx_chirp0": None,
        "tx_chirp1": None,
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": GLOBAL_CHIRP_F0, "f1": GLOBAL_CHIRP_F1},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "payload_file": str((SIDECAR_DIR / MNIST_SRC.name).relative_to(_HERE)),
        "ws_payloads": [],
    }

    # ---- lead + global up-chirp ----
    add(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add(_make_global_chirp(up=True))
    add(_silence(GAP_S))

    # ---- combo section ----
    body_start = pos
    frame_starts: list[int] = []
    for fbits in frames_bits:
        audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
        frame_starts.append(pos)
        add(audio)
        add(_silence(FRAME_GAP_S))
    body_end = frame_starts[-1] + len(
        np.asarray(sch.modulate(frames_bits[-1].astype(np.uint8)), dtype=np.float32)
    )

    # ---- sidecar + manifest section ----
    scar = SIDECAR_DIR / MNIST_SRC.name
    scar.write_bytes(payload)
    entry = {
        "name": "nb_floor_combo_m12k2_rs95",
        "kind": "combo_mfsk",
        "channel_mode": "mono",
        "scheme": sch.name,
        "phy": sch.name,
        "role": "narrowband (470-2200 Hz) combinatorial-MFSK M12/K2 floor, "
                "RS(255,95). The worn-deck-survivable MNIST carrier.",
        "status": "ACTIVE",
        "gross_bps": gross,
        "projected_net_bps": net,
        "section_net_bps": net,
        "pack": None,
        "payload_sidecar": str(scar.relative_to(_HERE)),
        "payload_len": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "crc32_codewords": _codeword_crcs(payload, RS_K),
        "meta": {
            "M": M, "K": K, "f_low": F_LOW, "f_high": F_HIGH,
            "rs_n": RS_N, "rs_k": RS_K,
            "frame_bytes": FRAME_BYTES,
            "frame_bits": meta["frame_bits"],
            "n_codewords": n_cw,
            "n_frames": meta["n_frames"],
            "stream_bits": meta["stream_bits"],
            "payload_len": meta["payload_len"],
        },
        "combo_params": {
            "M": M, "K": K, "f_low": F_LOW, "f_high": F_HIGH,
            "bits_per_sym": int(sch.bits_per_sym),
            "samples_per_sym": int(sch.samples_per_sym),
            "preamble_seconds": float(sch.preamble_seconds),
        },
        "frame_starts": [int(s) for s in frame_starts],
        "body_end": int(body_end),
    }
    manifest["ws_payloads"].append(entry)

    # ---- 1 s silence + global down-chirp + tail (SOP) ----
    add(_silence(1.0))
    manifest["tx_chirp1"] = pos
    add(_make_global_chirp(up=False))
    add(_silence(GAP_S))
    add(_silence(TAIL))

    mono = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(mono)))
    if peak > 1e-9:
        mono = (mono / peak * PEAK).astype(np.float32)
    dur_s = len(mono) / SR
    manifest["duration_seconds"] = dur_s

    sf.write(str(out_wav), mono, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"\n[build] {out_wav.name}  {dur_s:.1f}s ({dur_s/60:.2f} min) mono, "
          f"peak {PEAK}  ({mono.nbytes/1e6:.0f} MB)")
    print(f"[build] manifest -> {MANIFEST_PATH.name}  sidecar -> "
          f"{SIDECAR_DIR.name}/{MNIST_SRC.name}")
    return {"wav_seconds": dur_s, "wav_path": str(out_wav),
            "manifest_path": str(MANIFEST_PATH), "n_frames": meta["n_frames"],
            "net_bps": net, "payload_len": len(payload)}


# ===========================================================================
# In-process VERIFY: decode the freshly built master byte-exact.
# Mirrors fullspectrum_decode._decode_combo_section, but builds the BAND-matched
# combo scheme (f_low/f_high from the manifest meta).
# ===========================================================================
def verify(wav_path: pathlib.Path = WAV_PATH,
           manifest_path: pathlib.Path = MANIFEST_PATH) -> bool:
    import analyze_master2 as am2                             # noqa: E402

    manifest = json.loads(pathlib.Path(manifest_path).read_text())
    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert sr == SR, sr

    sync = am2.global_sync_and_resample(np.asarray(audio, dtype=np.float32), manifest)
    audio_nom = np.asarray(sync["audio_nominal"], dtype=np.float32)
    align = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])

    sec = manifest["ws_payloads"][0]
    meta = sec["meta"]
    m_, k_ = int(meta["M"]), int(meta["K"])
    f_low, f_high = float(meta["f_low"]), float(meta["f_high"])
    sch = make_tracked_combo(m_, k_, f_low=f_low, f_high=f_high)

    starts = [int(s) for s in sec["frame_starts"]]
    body_end = int(sec["body_end"])
    sidecar = (_HERE / sec["payload_sidecar"]).read_bytes()
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
        except Exception:
            rb = np.zeros(0, dtype=np.uint8)
        frames_bits.append(rb)

    recovered = codec.decode_payload(frames_bits, meta)
    n_fail = int(getattr(codec.decode_payload, "last_codewords_failed", 0))
    byte_exact = bool(recovered == sidecar)
    print(f"[verify] align={align:+d} speed={sync['speed']:.5f} "
          f"n_frames={len(starts)} cwFail={n_fail}/{meta['n_codewords']} "
          f"byte_exact={byte_exact}")
    return byte_exact


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()
    info = build(pathlib.Path(args.out))
    print(f"\n[summary] duration={info['wav_seconds']:.1f}s "
          f"({info['wav_seconds']/60:.2f} min) n_frames={info['n_frames']} "
          f"net_bps={info['net_bps']:.1f} payload={info['payload_len']}B")
    if not args.no_verify:
        ok = verify(pathlib.Path(args.out))
        print(f"[summary] PYTHON byte_exact = {ok}")
        sys.exit(0 if ok else 1)
