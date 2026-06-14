"""x10_union_probe.py -- BET C evidence probe: demod-hypothesis diversity.

Question: on the REAL tape9_run1 capture, are the failed RS codewords of the
frontier N256 rungs (m4 2338 / m5 2632 / m6 2809 / m7 2896) DISJOINT across
timing front-ends?  If yes, a per-codeword CRC32-guarded UNION across the
front-end ensemble recovers sections that every single front-end loses --
zero airtime overhead, receiver-only, retroactive on the existing capture.

Also measures two stronger fusions:
  * per-frame front-end selection (pick per frame the FE with lowest pilot
    |dtau| RMS, recompose, RS+CRC) -- selection diversity ahead of RS;
  * bitwise majority vote across 3 FEs, then RS+CRC.

Everything is CRC32-per-codeword guarded (manifest crc table, the sanctioned
m9 guard) -- no truth leak into decisions; sidecar bytes are used for SCORING
only (byte_exact), exactly like m9_decode.

Usage:
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
        experiments/tape_v2/x10_union_probe.py \
        experiments/tape_v2/captures/tape9_run1.wav

Output: experiments/tape_v2/results/x10_union_probe_<capture>.json
Seeds: deterministic (no RNG used anywhere in this probe).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                      # noqa: E402
import m3_codec as codec                           # noqa: E402
import m9_decode as md                             # noqa: E402 (read-only import)
from x9_resampling_pll import ResamplingPLLDemod   # noqa: E402
from reedsolo import RSCodec, ReedSolomonError     # noqa: E402

SR = codec.FS
SECTIONS = ("m9_m4_n256_rs159", "m9_m5_n256_rs179",
            "m9_m6_n256_rs191", "m9_m7_n256_p11_9000")
# ensemble: proven PLL + proven alphas + the UNEXPLORED alpha band 0.65-0.8
FRONTENDS = (("resampling_pll30", dict(front_end="pll", pll_bw_hz=30.0)),
             ("ema0.5", dict(front_end="ema", ema_alpha=0.5)),
             ("ema0.6", dict(front_end="ema", ema_alpha=0.6)),
             ("ema0.65", dict(front_end="ema", ema_alpha=0.65)),
             ("ema0.7", dict(front_end="ema", ema_alpha=0.7)),
             ("ema0.8", dict(front_end="ema", ema_alpha=0.8)))
MAJORITY_OF = ("ema0.6", "resampling_pll30", "ema0.7")


def _rx_mat(rx_frames, meta):
    """Reassemble the de-interleaved codeword matrix (same math as m9_decode)."""
    fb_bits, n_frames = meta["frame_bits"], meta["n_frames"]
    stream_bits = meta["stream_bits"]
    rs_n, n_cw = meta["rs_n"], meta["n_codewords"]
    pieces = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else stream_bits - fb_bits * (n_frames - 1)
        rb = (np.asarray(rx_frames[fi], np.uint8).ravel()
              if fi < len(rx_frames) else np.zeros(nominal, np.uint8))
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    rx_bits = np.concatenate(pieces)[:stream_bits]
    if len(rx_bits) < stream_bits:
        rx_bits = np.concatenate([rx_bits, np.zeros(stream_bits - len(rx_bits), np.uint8)])
    rx_bytes = np.packbits(rx_bits)[:n_cw * rs_n]
    return rx_bytes.reshape(rs_n, n_cw).T


def _per_cw_decode(rx_mat, meta, crc_table):
    """Errors-only RS per codeword + CRC32 guard -> (ok_mask, msgs)."""
    rs_n, rs_k, n_cw = meta["rs_n"], meta["rs_k"], meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    ok = np.zeros(n_cw, bool)
    msgs: list[bytes | None] = [None] * n_cw
    for i in range(n_cw):
        try:
            msg = bytes(rsc.decode(bytearray(rx_mat[i].tobytes()))[0])
        except (ReedSolomonError, Exception):
            continue
        if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
            continue        # CRC guard: reject miscorrection
        ok[i] = True
        msgs[i] = msg
    return ok, msgs


def _assemble(meta, msgs):
    out = bytearray()
    for i in range(meta["n_codewords"]):
        out += msgs[i] if msgs[i] is not None else bytes(meta["rs_k"])
    return bytes(out)[:meta["payload_len"]]


def main():
    cap = sys.argv[1] if len(sys.argv) > 1 else str(_HERE / "captures" / "tape9_run1.wav")
    manifest = json.loads((_HERE / "master9_manifest.json").read_text())
    audio, sr = sf.read(cap, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    t0 = time.time()
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    print(f"[sync] {time.time()-t0:.1f}s  clock={sync.get('clock_ratio')}", flush=True)

    out_path = _HERE / "results" / f"x10_union_probe_{pathlib.Path(cap).stem}.json"
    report = {"capture": cap, "frontends": [n for n, _ in FRONTENDS],
              "majority_of": list(MAJORITY_OF), "sections": []}

    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    for name in SECTIONS:
        sec = secs[name]
        sch = md._scheme_from_entry(sec)
        meta = sec["meta"]
        crc = sec["crc32_codewords"]
        expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        n_cw = meta["n_codewords"]
        srec = {"name": name, "rs_k": meta["rs_k"], "n_codewords": n_cw,
                "net_bps": sec.get("projected_net_bps"), "per_fe": {}}
        fe_masks, fe_msgs, fe_frames, fe_dtau = {}, {}, {}, {}
        for fe_name, kw in FRONTENDS:
            ts = time.time()
            dem = ResamplingPLLDemod(sch, **kw)
            rx_frames, diags = md._demod_section_frames(
                audio_nom, sec, align, sch, lambda w, nd, d=dem: d.demod(w, nd))
            ok, msgs = _per_cw_decode(_rx_mat(rx_frames, meta), meta, crc)
            fe_masks[fe_name], fe_msgs[fe_name], fe_frames[fe_name] = ok, msgs, rx_frames
            fe_dtau[fe_name] = [
                float(np.sqrt(np.mean(np.square(d.get("dtau"))))) if d.get("dtau") is not None
                and len(d.get("dtau")) else 0.0 for d in diags]
            failed = [int(i) for i in np.flatnonzero(~ok)]
            srec["per_fe"][fe_name] = {"cw_failed": len(failed), "failed_idx": failed,
                                       "sec_s": round(time.time() - ts, 1)}
            print(f"[{name}] {fe_name}: {len(failed)}/{n_cw} failed {failed}"
                  f" ({time.time()-ts:.1f}s)", flush=True)

        # ---- fusion 1: per-codeword CRC-guarded union across the ensemble ----
        union_msgs: list[bytes | None] = [None] * n_cw
        for fe_name, _ in FRONTENDS:
            for i in range(n_cw):
                if union_msgs[i] is None and fe_msgs[fe_name][i] is not None:
                    union_msgs[i] = fe_msgs[fe_name][i]
        u_failed = [i for i in range(n_cw) if union_msgs[i] is None]
        u_exact = _assemble(meta, union_msgs) == expected
        srec["union"] = {"cw_failed": len(u_failed), "failed_idx": u_failed,
                         "byte_exact": bool(u_exact)}
        print(f"[{name}] UNION: {len(u_failed)}/{n_cw} failed {u_failed} "
              f"byte_exact={u_exact}", flush=True)

        # ---- fusion 2: per-frame FE selection by pilot |dtau| RMS ----
        n_frames = meta["n_frames"]
        sel_frames, sel_pick = [], []
        for fi in range(n_frames):
            best = min(FRONTENDS, key=lambda t: fe_dtau[t[0]][fi])[0]
            sel_pick.append(best)
            sel_frames.append(fe_frames[best][fi])
        ok_s, msgs_s = _per_cw_decode(_rx_mat(sel_frames, meta), meta, crc)
        s_failed = [int(i) for i in np.flatnonzero(~ok_s)]
        srec["frame_select"] = {"cw_failed": len(s_failed), "failed_idx": s_failed,
                                "byte_exact": _assemble(meta, msgs_s) == expected,
                                "picks": sel_pick}
        print(f"[{name}] FRAME-SELECT: {len(s_failed)}/{n_cw} failed", flush=True)

        # ---- fusion 3: bitwise majority across 3 FEs, then RS+CRC ----
        maj_frames = []
        for fi in range(n_frames):
            stack = np.stack([np.asarray(fe_frames[f][fi], np.uint8)
                              for f in MAJORITY_OF])
            maj_frames.append((stack.sum(axis=0) >= 2).astype(np.uint8))
        ok_m, msgs_m = _per_cw_decode(_rx_mat(maj_frames, meta), meta, crc)
        m_failed = [int(i) for i in np.flatnonzero(~ok_m)]
        srec["majority3"] = {"cw_failed": len(m_failed), "failed_idx": m_failed,
                             "byte_exact": _assemble(meta, msgs_m) == expected}
        print(f"[{name}] MAJORITY3: {len(m_failed)}/{n_cw} failed", flush=True)

        # ---- fusion 4: union of all four (union + select + majority) ----
        all_msgs = list(union_msgs)
        for src in (msgs_s, msgs_m):
            for i in range(n_cw):
                if all_msgs[i] is None and src[i] is not None:
                    all_msgs[i] = src[i]
        a_failed = [i for i in range(n_cw) if all_msgs[i] is None]
        srec["grand_union"] = {"cw_failed": len(a_failed), "failed_idx": a_failed,
                               "byte_exact": _assemble(meta, all_msgs) == expected}
        print(f"[{name}] GRAND-UNION: {len(a_failed)}/{n_cw} failed "
              f"byte_exact={srec['grand_union']['byte_exact']}", flush=True)

        report["sections"].append(srec)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"[checkpoint] {out_path}", flush=True)
    print(f"[done] total {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
