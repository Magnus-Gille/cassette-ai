"""m4_decode.py — recover the master4 dual-scheme payloads from a captured WAV.

Pipeline (mirrors analyze_master2 / m3_decode_v2, extended to the m4 layout)
---------------------------------------------------------------------------
  (a) WHOLE-TAPE SYNC: analyze_master2.global_sync_and_resample locates the two
      global chirps (lead-in robust), recovers deck speed, resamples to nominal
      48 k. align = chirp0_nominal - manifest tx_chirp0 anchors every position.
  (b) SOUNDER EQ: analyze_master2.analyze_sounder reads the fresh channel H(f);
      we interpolate it to the wide-spaced scheme's tone freqs to build the
      per-tone EQ gain table (exactly as m3_decode_v2 derives its sounder gains).
  (c) SCHEME-1 (wide-spaced): for each payload, each frame's window =
      frame_start + align (+/- pad) is demodulated with the VALIDATED achievable
      reader assault_widespace._demod_frame_achievable(scheme, eq, y_frame, nsym,
      detector="contrast"); collected frame bits -> m3_codec.decode_payload.
  (d) SCHEME-2 (CSS): the payload's window from stream_start + align is read as one
      piloted stream via scheme.demod_piloted(...), un-Gray'd, re-split into frames
      at the exact bit positions, -> m3_codec.decode_payload.
  (e) Each recovered payload is byte-compared to its sidecar. Prints a per-payload
      table: scheme, bytes, raw error rate, RS blocks failed, byte-exact yes/no.

Usage
-----
    python3 m4_decode.py <recording.wav> [--out-tag TAG]
    python3 m4_decode.py master4.wav            # (A) no-channel self-check
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

import m3_codec as codec                                  # noqa: E402
from m3_codec import Rung                                 # noqa: E402
import analyze_master2 as am2                             # noqa: E402
from assault_widespace import build as ws_build, _demod_frame_achievable  # noqa: E402
from assault_css import CSSScheme                          # noqa: E402

SR = codec.FS
MANIFEST_PATH = _HERE / "master4_manifest.json"
RESULTS_DIR = _HERE / "results"

# Per-frame window pad (s) so the WS find_preamble sees the full 0.25 s preamble.
WS_WINDOW_PAD = 0.30
# CSS stream window pad (s) before/after; demod_piloted self-syncs off its preamble.
CSS_PAD = 0.40


# ---------------------------------------------------------------------------
# Sounder-based per-tone EQ for the wide-spaced scheme (mirror m3_decode_v2).
# ---------------------------------------------------------------------------
def _ws_eq_from_sounder(ws, sounder: dict) -> np.ndarray:
    """Interpolate the recording's own sounder H(f) (dB) to the WS tone freqs,
    return a normalized, clipped per-tone gain table — the same form the WS
    achievable reader expects (assault_widespace.eq_for): divide tone energies by
    this to flatten the channel before the contrast top-K."""
    sf_freqs = np.asarray(sounder.get("sounder_freqs", []), dtype=np.float64)
    H_db = np.asarray(sounder.get("H_db", []), dtype=np.float64)
    if len(sf_freqs) < 2:
        return np.ones(ws.M)
    Hlin = 10.0 ** (np.interp(ws.freqs, sf_freqs, H_db) / 20.0)
    Hlin = Hlin / (Hlin.max() + 1e-12)
    return np.clip(Hlin, 0.05, None)   # eq_clip used by the validated sim/decoder


# ---------------------------------------------------------------------------
# Scheme 1 — wide-spaced, per-frame
# ---------------------------------------------------------------------------
def _decode_ws(audio_nom, sec, align, ws, eq) -> dict:
    meta = sec["meta"]
    rung = Rung(name="ws", M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    starts = sec["frame_starts"]
    pad = int(WS_WINDOW_PAD * SR)
    n_frames = meta["n_frames"]
    N, bps, pre = ws.N, ws.bits_per_sym, len(ws._preamble)

    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    tx_frames, _ = codec.encode_payload(expected, rung)

    frames_bits, raw_err, raw_tot = [], 0, 0
    for fi in range(n_frames):
        nbits = len(tx_frames[fi])
        nsym = int(np.ceil(nbits / bps))
        flen = pre + nsym * N
        st = starts[fi] + align
        w_lo = max(0, st - pad)
        w_hi = min(len(audio_nom), st + flen + pad)
        win = np.asarray(audio_nom[w_lo:w_hi], dtype=np.float32)
        rb = np.asarray(_demod_frame_achievable(ws, eq, win, nsym, "contrast"),
                        dtype=np.uint8).ravel()
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        frames_bits.append(rb)

    recovered = codec.decode_payload(frames_bits, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == expected
    byte_err = sum(a != b for a, b in zip(recovered, expected)) + abs(len(recovered) - len(expected))
    return {
        "name": sec["name"], "scheme": "widespace", "phy": sec["phy"],
        "payload_bytes": len(expected), "n_frames": n_frames,
        "n_codewords": meta["n_codewords"],
        "raw_ber": raw_err / max(1, raw_tot),
        "rs_codewords_failed": cw_failed,
        "byte_errors": byte_err, "byte_exact": bool(exact),
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
    }


# ---------------------------------------------------------------------------
# Scheme 2 — CSS piloted stream
# ---------------------------------------------------------------------------
def _decode_css(audio_nom, sec, align, css, phy) -> dict:
    meta = sec["meta"]
    gray = phy["gray"]
    pilot_every = phy["pilot_every"]
    n_data = sec["n_data_syms"]
    pad_bits = sec["stream_pad_bits"]

    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name="css", M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    frames, _ = codec.encode_payload(expected, rung)
    fb_bits = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]
    tx_all = np.concatenate([np.asarray(f, np.uint8) for f in frames]).astype(np.uint8)

    # window: the whole piloted stream + pads. demod_piloted self-syncs off the
    # 0.25 s preamble at the window head, so begin the window before stream_start.
    pre_samples = int(0.25 * SR) + css.N_PRE_SYMS * css.sps
    n_pilots = (n_data + pilot_every - 1) // pilot_every + 1
    total_syms = n_data + n_pilots
    stream_len = pre_samples + total_syms * css.sps
    pad = int(CSS_PAD * SR)
    st = sec["stream_start"] + align
    w_lo = max(0, st - pad)
    w_hi = min(len(audio_nom), st + stream_len + pad)
    win = np.asarray(audio_nom[w_lo:w_hi], dtype=np.float64)

    rx_syms = css.demod_piloted(win, n_data, pilot_every)
    rx_vals = [css._ungray(int(g)) for g in rx_syms] if gray else list(rx_syms)
    rx_bits = (css.graysym_to_bits([css._gray(int(v)) for v in rx_vals]) if gray
               else np.concatenate([css._sym_to_bits(int(v)) for v in rx_vals]))
    rx_bits = np.asarray(rx_bits, np.uint8)
    if pad_bits:
        rx_bits = rx_bits[:len(rx_bits) - pad_bits] if len(rx_bits) >= pad_bits else rx_bits

    # raw BER vs the known framed bit stream (pre-modulation, pre-pad)
    m = min(len(tx_all), len(rx_bits))
    raw_err = int(np.count_nonzero(tx_all[:m] != rx_bits[:m])) + abs(len(tx_all) - len(rx_bits))
    raw_ber = raw_err / max(1, len(tx_all))

    # re-split into frames at the exact bit positions, then decode
    rec_frames = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else (stream_bits - fb_bits * (n_frames - 1))
        seg = rx_bits[fi * fb_bits: fi * fb_bits + nominal]
        rec_frames.append(seg)
    recovered = codec.decode_payload(rec_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == expected
    byte_err = sum(a != b for a, b in zip(recovered, expected)) + abs(len(recovered) - len(expected))
    return {
        "name": sec["name"], "scheme": "css", "phy": sec["phy"],
        "payload_bytes": len(expected), "n_frames": n_frames,
        "n_codewords": meta["n_codewords"],
        "raw_ber": raw_ber,
        "rs_codewords_failed": cw_failed,
        "byte_errors": byte_err, "byte_exact": bool(exact),
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
    }


# ---------------------------------------------------------------------------
def decode(recording_path: str, out_tag: str | None = None, verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(recording_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)

    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    except Exception as e:
        sounder = {"error": str(e)}

    wphy = manifest["ws_phy"]
    ws = ws_build(wphy["M"], wphy["K"], wphy["spacing"], wphy["N"])
    eq = _ws_eq_from_sounder(ws, sounder)

    cphy = manifest["css_phy"]
    css = CSSScheme(sf=cphy["sf"], bw=cphy["bw"], fc=cphy["fc"])

    results = []
    for sec in manifest["ws_payloads"]:
        results.append(_decode_ws(audio_nom, sec, align, ws, eq))
    for sec in manifest["css_payloads"]:
        results.append(_decode_css(audio_nom, sec, align, css, cphy))

    if verbose:
        print(f"[m4_decode] {recording_path}")
        print(f"  recovered clock: {sync['speed']:.4f}x "
              f"(offset {sync['speed_offset']*100:+.2f}%), align {align:+d}")
        if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
            print(f"  sounder: flutter {sounder.get('flutter_wrms_pct', float('nan')):.2f}%, "
                  f"SNR med {sounder.get('snr_db_median', float('nan')):.1f} dB, "
                  f"nf {sounder.get('noise_floor_dbfs', float('nan')):.1f} dBFS")
        print(f"  {'payload':<14} {'scheme':<10} {'RS':>9} {'bytes':>7} {'frames':>6} "
              f"{'rawBER':>8} {'cwFail':>8} {'byteErr':>8} {'EXACT':>6}")
        for r in results:
            rs = f"({r['rs_n']},{r['rs_k']})"
            cw = f"{r['rs_codewords_failed']}/{r['n_codewords']}"
            print(f"  {r['name']:<14} {r['scheme']:<10} {rs:>9} "
                  f"{r['payload_bytes']:>7} {r['n_frames']:>6} {r['raw_ber']:>8.4f} "
                  f"{cw:>8} {r['byte_errors']:>8} {'YES' if r['byte_exact'] else 'no':>6}")
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
    json_path = RESULTS_DIR / f"m4_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m4_decode] wrote {json_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="captured tape-playback WAV (or master4.wav)")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    decode(args.recording, out_tag=args.out_tag)
