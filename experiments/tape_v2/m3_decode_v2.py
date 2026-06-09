"""m3_decode_v2.py — real-audio-hardened master3 decoder.

Reuses the PROVEN parts of m3_decode.py unchanged:
  * analyze_master2.global_sync_and_resample  (whole-tape sync + clock + resample)
  * analyze_master2.analyze_sounder            (fresh channel readout, H(f), SNR)
  * hyp_common.find_preamble                   (per-frame chirp sync)
  * m3_codec.decode_payload                    (de-interleave + RS decode)

ONLY the per-frame TONE DEMOD is replaced. The deep-dive make_tracked_combo demod
loses symbol-timing lock on real audio and uses blind median-EQ (wrong for k-of-M).
This module's _HardDemod instead combines:

  (a) FFT-bin energy detection at the exact tone bins (sch._bin_indices).
  (b) PROPER per-tone channel EQ from the SOUNDER H(f): the steady multitone sounder
      measures the true channel gain at 64 freqs; we interpolate H(f) to the 16 data
      tone freqs and divide each tone's energy by its linear gain before top-K. (The
      real channel has a ~26 dB HF rolloff -> high tones are ~20x weaker -> top-K is
      otherwise dominated by spurious low tones.) Optionally a 1-pass decision-directed
      refinement from the recovered on-tones.
  (c) ROBUST per-symbol timing tracking: per symbol, search a WIDE window (+/-track)
      for the offset maximizing an energy-CONCENTRATION lock score (gap between the
      Kth and (K+1)th EQ'd tone energy, normalized), carry the residual drift forward
      (with an optional velocity term) so it follows the flutter wander.

CLI mirrors m3_decode.py and prints the same per-payload table plus a genie-ceiling
upper bound (per-symbol oracle-timed + EQ) so the result is interpretable.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import correlate, resample_poly

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2", ROOT / "experiments" / "capacity",
           _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                                   # noqa: E402
import m3_codec as codec                                  # noqa: E402
from d3d4_combo_tracked import make_tracked_combo         # noqa: E402
import analyze_master2 as am2                             # noqa: E402

SR = codec.FS
MANIFEST_PATH = _HERE / "master3_manifest.json"
RESULTS_DIR = _HERE / "results"
WINDOW_PAD = 0.30


# ---------------------------------------------------------------------------
# Hardened per-frame demod
# ---------------------------------------------------------------------------
class HardDemod:
    """FFT-detection + sounder-EQ + concentration-lock timing tracker.

    Built once per (rung, sounder); reused across all frames of a payload.
    """

    def __init__(self, sch, eq_gain: np.ndarray, *, track: int = 15,
                 center_bias: float = 0.02, vel_gain: float = 0.0,
                 dd_passes: int = 1):
        self.sch = sch
        self.N = sch.samples_per_sym
        self.bps = sch.bits_per_sym
        self.K = sch.K
        self.M = sch.M
        self.bins = np.clip(sch._bin_indices, 0, self.N // 2).astype(int)
        self.rev = sch._rev_table
        self.cap = sch._sym_cap
        self.pre = hc.make_preamble(sch.preamble_seconds).astype(np.float64)
        # per-tone EQ gain (relative channel gain, normalized to max=1). Divide
        # tone energies by this to flatten the channel before top-K.
        self.eq = np.asarray(eq_gain, dtype=np.float64)
        self.eq = self.eq / (self.eq.max() + 1e-12)
        self.eq = np.clip(self.eq, 1e-3, None)            # guard near-zero tones
        self.track = track
        self.center_bias = center_bias
        self.vel_gain = vel_gain
        self.dd_passes = dd_passes

    # --- low level: tone energies at a sample position --------------------
    def _energies(self, win: np.ndarray, p: int):
        seg = win[p:p + self.N]
        if len(seg) < self.N:
            if len(seg) < self.N // 2:
                return None
            seg = np.concatenate([seg, np.zeros(self.N - len(seg))])
        return np.abs(np.fft.rfft(seg, n=self.N))[self.bins]

    def _lock(self, e_eq: np.ndarray) -> float:
        """Energy-concentration lock score: normalized gap between the Kth and
        (K+1)th EQ'd tone energies (how cleanly K tones stand out). Carries
        timing information; unlike max/median it is not dominated by coloration."""
        srt = np.sort(e_eq)[::-1]
        return float((srt[self.K - 1] - srt[self.K]) / (srt[0] + 1e-9))

    def _sym(self, e_eq: np.ndarray) -> int:
        tk = tuple(sorted(np.argpartition(e_eq, -self.K)[-self.K:].tolist()))
        return min(self.rev.get(tk, 0), self.cap - 1)

    # --- one tracked sweep over a frame window, returns raw energy matrix --
    def _sweep(self, win: np.ndarray, dstart: int, nsym: int, eq: np.ndarray):
        emat = np.zeros((nsym, self.M))
        drift = 0.0
        vel = 0.0
        for s in range(nsym):
            predicted = drift + vel
            base = dstart + s * self.N + int(round(predicted))
            best = None
            for d in range(-self.track, self.track + 1):
                e = self._energies(win, base + d)
                if e is None:
                    continue
                lock = self._lock(e / eq) * (1.0 - self.center_bias * abs(d))
                if best is None or lock > best[0]:
                    best = (lock, d, e)
            if best is None:
                continue
            _, d, e = best
            new_drift = predicted + d
            vel = (1.0 - self.vel_gain) * vel + self.vel_gain * (new_drift - drift)
            drift = new_drift
            emat[s] = e
        return emat

    def demod_frame(self, win: np.ndarray, nsym: int) -> np.ndarray:
        win = np.asarray(win, dtype=np.float64)
        c = np.abs(correlate(win, self.pre, mode="valid"))
        pk = int(np.argmax(c))
        dstart = pk + len(self.pre)
        eq = self.eq.copy()
        emat = self._sweep(win, dstart, nsym, eq)
        # decision-directed EQ refinement: re-estimate per-tone gain as the mean
        # energy of that tone over the symbols where it was selected in the top-K,
        # then re-sweep. (A tone's "on" level is the channel gain; the median over
        # all symbols is the OFF level and is wrong for k-of-M.)
        for _ in range(self.dd_passes):
            on_sum = np.zeros(self.M)
            on_cnt = np.zeros(self.M)
            for e in emat:
                tk = np.argpartition(e / eq, -self.K)[-self.K:]
                for t in tk:
                    on_sum[t] += e[t]
                    on_cnt[t] += 1
            new = on_sum / np.maximum(on_cnt, 1)
            # blend with sounder prior where a tone was rarely selected (low count)
            w = np.clip(on_cnt / max(1, nsym * self.K / self.M), 0.0, 1.0)
            cand = np.where(on_cnt > 0, new, eq)
            cand = cand / (cand.max() + 1e-12)
            cand = np.clip(cand, 1e-3, None)
            eq = w * cand + (1.0 - w) * eq
            eq = eq / (eq.max() + 1e-12)
            emat = self._sweep(win, dstart, nsym, eq)
        out = []
        for e in emat:
            si = self._sym(e / eq)
            out.extend([(si >> (self.bps - 1 - j)) & 1 for j in range(self.bps)])
        return np.array(out, dtype=np.uint8)


def _eq_from_sounder(sch, sounder: dict) -> np.ndarray:
    """Interpolate the sounder H(f) (linear) to the 16 data tone freqs."""
    sf_freqs = np.asarray(sounder.get("sounder_freqs", []), dtype=np.float64)
    H_db = np.asarray(sounder.get("H_db", []), dtype=np.float64)
    if len(sf_freqs) < 2:
        return np.ones(sch.M)
    Hlin = 10.0 ** (np.interp(sch.freqs, sf_freqs, H_db) / 20.0)
    return Hlin


# ---------------------------------------------------------------------------
# Per-payload decode
# ---------------------------------------------------------------------------
def _decode_payload(audio_nom, sec, align, eq_gain, *, genie=False) -> dict:
    meta = sec["meta"]
    rung = codec.RUNGS_BY_NAME[sec["rung"]]
    if meta.get("frame_bytes") and meta["frame_bytes"] != rung.frame_bytes:
        rung = dataclasses.replace(rung, frame_bytes=int(meta["frame_bytes"]))
    sch = make_tracked_combo(rung.M, rung.K)
    demod = HardDemod(sch, eq_gain)

    N, bps, pre_n = sch.samples_per_sym, sch.bits_per_sym, len(sch._preamble)
    starts = sec["frame_starts"]
    pad = int(WINDOW_PAD * SR)
    n_frames = meta["n_frames"]
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    tx_frames, _ = codec.encode_payload(expected, rung)

    frames_bits = []
    genie_bits = []
    raw_err = 0
    raw_tot = 0
    genie_err = 0
    for fi in range(n_frames):
        nbits = len(tx_frames[fi])
        nsym = int(np.ceil(nbits / bps))
        flen = pre_n + nsym * N
        st = starts[fi] + align
        w_lo = max(0, st - pad)
        w_hi = min(len(audio_nom), st + flen + pad)
        win = np.asarray(audio_nom[w_lo:w_hi], dtype=np.float32)
        rb = demod.demod_frame(win, nsym)
        tb = tx_frames[fi].astype(np.uint8)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        frames_bits.append(rb)
        if genie:
            gb = _genie_frame(demod, win, nsym, tb)
            gm = min(len(tb), len(gb))
            genie_err += int(np.count_nonzero(tb[:gm] != gb[:gm])) + (len(tb) - gm)
            genie_bits.append(gb)

    recovered = codec.decode_payload(frames_bits, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == expected
    byte_err = sum(a != b for a, b in zip(recovered, expected)) + abs(len(recovered) - len(expected))
    out = {
        "name": sec["name"], "rung": rung.name,
        "payload_bytes": len(expected), "n_frames": n_frames,
        "n_codewords": meta["n_codewords"],
        "raw_ber": raw_err / max(1, raw_tot),
        "rs_codewords_failed": cw_failed,
        "byte_errors": byte_err, "byte_exact": bool(exact),
        "rs_n": rung.rs_n, "rs_k": rung.rs_k,
    }
    if genie:
        grec = codec.decode_payload(genie_bits, meta)
        out["genie_raw_ber"] = genie_err / max(1, raw_tot)
        out["genie_cw_failed"] = codec.decode_payload.last_codewords_failed
        out["genie_byte_exact"] = bool(grec == expected)
    return out


def _genie_frame(demod: HardDemod, win, nsym, tb) -> np.ndarray:
    """Oracle-timed + EQ upper bound: per symbol, search +/-track and prefer the
    offset that decodes the KNOWN symbol; carry the residual. Cheats with the
    answer -> a strict ceiling on what ANY timing tracker could achieve here."""
    win = np.asarray(win, dtype=np.float64)
    bps, N = demod.bps, demod.N
    c = np.abs(correlate(win, demod.pre, mode="valid"))
    dstart = int(np.argmax(c)) + len(demod.pre)
    exp = [int("".join(map(str, tb[s * bps:(s + 1) * bps])), 2) for s in range(nsym)]
    eq = demod.eq
    prev = 0.0
    out = []
    for s in range(nsym):
        base = dstart + s * N + int(round(prev))
        best = None
        fallback = None
        for d in range(-demod.track, demod.track + 1):
            e = demod._energies(win, base + d)
            if e is None:
                continue
            si = demod._sym(e / eq)
            if fallback is None:
                fallback = si
            if si == exp[s] and (best is None or abs(d) < abs(best)):
                best = d
        if best is not None:
            prev += best
            si = exp[s]
        else:
            si = fallback if fallback is not None else 0
        out.extend([(si >> (bps - 1 - j)) & 1 for j in range(bps)])
    return np.array(out, dtype=np.uint8)


def decode(recording_path: str, out_tag=None, verbose=True, genie=True) -> dict:
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

    # build the per-tone EQ once from the sounder (same data tones for all rungs).
    sch16 = make_tracked_combo(16, 2)
    eq_gain = _eq_from_sounder(sch16, sounder)

    results = []
    for sec in manifest["payloads"]:
        results.append(_decode_payload(audio_nom, sec, align, eq_gain, genie=genie))

    if verbose:
        print(f"[m3_decode_v2] {recording_path}")
        print(f"  recovered clock: {sync['speed']:.4f}x, align {align:+d}")
        if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
            print(f"  sounder: flutter {sounder['flutter_wrms_pct']:.2f}%, "
                  f"SNR med {sounder['snr_db_median']:.1f} dB, "
                  f"nf {sounder['noise_floor_dbfs']:.1f} dBFS")
        hdr = (f"  {'payload':<20} {'rung':<9} {'bytes':>7} {'frames':>6} "
               f"{'rawBER':>8} {'cwFail':>7} {'byteErr':>8} {'EXACT':>6}")
        if genie:
            hdr += f" {'genieBER':>9} {'genieCW':>8} {'gEXACT':>7}"
        print(hdr)
        for r in results:
            line = (f"  {r['name']:<20} {r['rung']:<9} {r['payload_bytes']:>7} "
                    f"{r['n_frames']:>6} {r['raw_ber']:>8.4f} "
                    f"{r['rs_codewords_failed']:>4}/{r['n_codewords']:<2} "
                    f"{r['byte_errors']:>8} {'YES' if r['byte_exact'] else 'no':>6}")
            if genie:
                line += (f" {r['genie_raw_ber']:>9.4f} "
                         f"{r['genie_cw_failed']:>3}/{r['n_codewords']:<2} "
                         f"{'YES' if r['genie_byte_exact'] else 'no':>6}")
            print(line)
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
    (RESULTS_DIR / f"m3v2_results_{tag}.json").write_text(
        json.dumps(out, indent=2, default=float))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--out-tag", default=None)
    ap.add_argument("--no-genie", action="store_true")
    args = ap.parse_args()
    decode(args.recording, out_tag=args.out_tag, genie=not args.no_genie)
