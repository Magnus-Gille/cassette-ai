"""m3_decode.py — recover the master3 ladder payloads from a captured WAV.

Pipeline (mirrors analyze_master2, extended to the m3 per-frame payload layout)
------------------------------------------------------------------------------
  (a) WHOLE-TAPE SYNC: analyze_master2.global_sync_and_resample locates the two
      global chirps (lead-in robust: searches a generous head window), recovers
      the deck speed, and resamples the whole recording back to nominal 48 k. The
      chirp0 alignment offset anchors every manifest sample position.
  (b) PER-PAYLOAD DECODE: for each manifest payload, each frame's nominal start =
      manifest frame_start + chirp0 align. We hand a GENEROUS window (the frame
      audio + pad on both sides) to make_tracked_combo(rung).demodulate, which
      self-syncs off the frame's own 0.25 s chirp preamble and runs the dd_common
      per-symbol energy-lock flutter tracker. Collect the per-frame recovered bits,
      feed them to m3_codec.decode_payload (de-interleave + RS-decode), and
      byte-compare to the sidecar.
  (c) SOUNDER: analyze_master2.analyze_sounder reports the fresh channel readout
      (H(f), SNR, flutter %, noise floor, recovered clock).
  (d) Print a per-payload table and write results JSON to results/.

Usage
-----
    python3 m3_decode.py <recording.wav> [--out-tag TAG]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2", ROOT / "experiments" / "capacity",
           _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                                 # noqa: E402
from d3d4_combo_tracked import make_tracked_combo        # noqa: E402
import analyze_master2 as am2                            # noqa: E402

SR = codec.FS
MANIFEST_PATH = _HERE / "master3_manifest.json"
RESULTS_DIR = _HERE / "results"

# Per-frame window pad (seconds) on each side, so the modem's local find_preamble
# sees the full 0.25 s chirp preamble and the last symbol + tail.
WINDOW_PAD = 0.30


# ---------------------------------------------------------------------------
# Sounder: reuse analyze_master2.analyze_sounder (its manifest schema matches —
# both use sounder_sections with start/length/kind/info).
# ---------------------------------------------------------------------------
def _sounder_readout(audio_nom: np.ndarray, manifest: dict, sync: dict) -> dict:
    try:
        return am2.analyze_sounder(audio_nom, manifest, sync)
    except Exception as e:  # never let the sounder break payload decode
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Per-payload decode
# ---------------------------------------------------------------------------
def _decode_payload(audio_nom: np.ndarray, sec: dict, align: int) -> dict:
    meta = sec["meta"]
    import dataclasses
    rung = codec.RUNGS_BY_NAME[sec["rung"]]
    # The master may have built this payload with a per-payload frame_bytes
    # override (deep-interleave probes). meta is the source of truth — honor it so
    # the re-encoded tx_frames and the decode framing match the recorded master.
    if meta.get("frame_bytes") and meta["frame_bytes"] != rung.frame_bytes:
        rung = dataclasses.replace(rung, frame_bytes=int(meta["frame_bytes"]))
    sch = make_tracked_combo(rung.M, rung.K)

    # The modulated length of every full frame is identical (same #bits except the
    # last). Use the manifest frame_starts to bound each frame window; the next
    # frame start (or chirp1 region) bounds the end. We pad generously.
    starts = sec["frame_starts"]
    pad = int(WINDOW_PAD * SR)
    n_frames = meta["n_frames"]

    # nominal modulated samples per full frame: preamble + ceil(fb_bits/bps)*N
    N = sch.samples_per_sym
    bps = sch.bits_per_sym
    pre = len(sch._preamble)

    def frame_audio_len(nbits: int) -> int:
        n_syms = int(np.ceil(nbits / bps))
        return pre + n_syms * N

    frames_bits = []
    raw_err_acc = 0
    raw_err_tot = 0
    # reconstruct the tx bits per frame for raw-BER (re-encode the sidecar)
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    tx_frames, _ = codec.encode_payload(expected, rung)

    for fi in range(n_frames):
        nbits = len(tx_frames[fi])
        flen = frame_audio_len(nbits)
        st = starts[fi] + align
        w_lo = max(0, st - pad)
        w_hi = min(len(audio_nom), st + flen + pad)
        window = np.asarray(audio_nom[w_lo:w_hi], dtype=np.float32)
        rb = np.asarray(sch.demodulate(window, SR), dtype=np.uint8).ravel()

        # raw BER vs the known tx frame bits
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(rb))
        errs = int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_err_acc += errs
        raw_err_tot += len(tb)
        frames_bits.append(rb)

    recovered = codec.decode_payload(frames_bits, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == expected
    byte_err = sum(a != b for a, b in zip(recovered, expected)) + abs(len(recovered) - len(expected))
    raw_ber = raw_err_acc / max(1, raw_err_tot)
    return {
        "name": sec["name"], "rung": rung.name,
        "payload_bytes": len(expected), "n_frames": n_frames,
        "n_codewords": meta["n_codewords"],
        "raw_ber": raw_ber, "rs_codewords_failed": cw_failed,
        "byte_errors": byte_err, "byte_exact": bool(exact),
        "rs_n": rung.rs_n, "rs_k": rung.rs_k,
    }


def decode(recording_path: str, out_tag: str | None = None, verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(recording_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)

    # whole-tape sync + resample (lead-in robust). Reuse master2's proven routine;
    # its manifest contract is tx_chirp0/tx_chirp1, which master3 also provides.
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]

    sounder = _sounder_readout(audio_nom, manifest, sync)

    results = []
    for sec in manifest["payloads"]:
        results.append(_decode_payload(audio_nom, sec, align))

    if verbose:
        print(f"[m3_decode] {recording_path}")
        print(f"  recovered clock: {sync['speed']:.4f}x "
              f"(offset {sync['speed_offset']*100:+.2f}%), "
              f"spacing {sync['measured_spacing']}/{sync['expected_spacing']}, "
              f"align {align:+d}")
        if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
            print(f"  sounder: flutter {sounder.get('flutter_wrms_pct', float('nan')):.2f}%, "
                  f"SNR med {sounder.get('snr_db_median', float('nan')):.1f} dB, "
                  f"nf {sounder.get('noise_floor_dbfs', float('nan')):.1f} dBFS")
        print(f"  {'payload':<20} {'rung':<9} {'bytes':>7} {'frames':>6} "
              f"{'rawBER':>8} {'cwFail':>6} {'byteErr':>8} {'EXACT':>6}")
        for r in results:
            print(f"  {r['name']:<20} {r['rung']:<9} {r['payload_bytes']:>7} "
                  f"{r['n_frames']:>6} {r['raw_ber']:>8.4f} "
                  f"{r['rs_codewords_failed']:>6} {r['byte_errors']:>8} "
                  f"{'YES' if r['byte_exact'] else 'no':>6}")
        n_exact = sum(r["byte_exact"] for r in results)
        print(f"  byte-exact payloads: {n_exact}/{len(results)}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    out = {
        "recording": str(recording_path),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {k: v for k, v in (sounder or {}).items()
                    if k not in ("H_db", "snr_db_per_tone", "sounder_freqs")},
        "payloads": results,
        "n_byte_exact": sum(r["byte_exact"] for r in results),
        "n_payloads": len(results),
    }
    json_path = RESULTS_DIR / f"m3_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m3_decode] wrote {json_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape-playback WAV")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, out_tag=args.out_tag)
