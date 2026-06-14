"""h3_amp_diag.py — H3 diagnostic: is the AMPLITUDE dimension itself clean?

Runs one H3 pass (given level, rs191 framing, given seed) through the v2
harness and reports the AM-bit BER CONDITIONED on correctly-detected tones
(truth used only to condition/report), per reference scheme, plus the level
distributions. This separates "amplitude is unusable" from "tone detection of
the -L dB tones is what breaks".

Usage: python3 h3_amp_diag.py --level 6 --seed 0
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                             # noqa: E402
from m3_codec import Rung                            # noqa: E402
from h3_amplitude_bit import (                       # noqa: E402
    AmpWS, demod_frame_amp, am_bits_for_frame,
)
from h3_amp_v2 import (                              # noqa: E402
    build_master, channel_pass, sync_and_eq, frame_window,
    payload_slice, FRAME_BYTES, RS_N,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=float, default=6.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    payload = payload_slice()
    aws = AmpWS(args.level)
    rung = Rung(name="h3diag", M=16, K=1, rs_n=RS_N, rs_k=191,
                frame_bytes=FRAME_BYTES)
    frames, meta = codec.encode_payload(payload, rung)
    fa = [aws.modulate(fb) for fb in frames]
    master, manifest, starts = build_master(fa)
    y, ch_t = channel_pass(master, args.seed)
    audio_nom, align, eq, sync = sync_and_eq(y, manifest, aws.ws)

    all_tones, all_lev, all_txt, all_txa, frame_id = [], [], [], [], []
    for fi, fb in enumerate(frames):
        nsym = int(np.ceil(len(fb) / aws.bits_per_sym))
        flen = len(aws.ws._preamble) + nsym * aws.N
        win = frame_window(audio_nom, starts[fi], align, flen)
        tones, lev_con, lev_raw = demod_frame_amp(aws, eq, win, nsym)
        tx_t, tx_a = AmpWS.tx_symbols(fb)
        all_tones.append(tones); all_lev.append(lev_raw)
        all_txt.append(tx_t); all_txa.append(tx_a)
        frame_id.append(np.full(nsym, fi))

    tones = np.concatenate(all_tones)
    lev = np.concatenate(all_lev)
    txt = np.concatenate(all_txt)
    txa = np.concatenate(all_txa)
    ok = tones == txt
    lev_db = 20 * np.log10(np.maximum(lev, 1e-12))

    print(f"level={args.level} seed={args.seed} nsym={len(tones)} "
          f"tone_sym_er={1 - ok.mean():.4f} align={align}")
    # conditioned level separation per amp class (correctly detected only)
    for cls, name in ((0, "HI"), (1, "LO")):
        m = ok & (txa == cls)
        print(f"  {name}: n={m.sum()} lev_db mean {lev_db[m].mean():+.2f} "
              f"std {lev_db[m].std():.2f}")
    # per-tone conditioned separation
    seps = []
    for t in range(16):
        mh = ok & (txa == 0) & (txt == t)
        ml = ok & (txa == 1) & (txt == t)
        if mh.sum() > 5 and ml.sum() > 5:
            seps.append(lev_db[mh].mean() - lev_db[ml].mean())
    print(f"  per-tone HI-LO separation: mean {np.mean(seps):+.2f} dB "
          f"min {np.min(seps):+.2f} max {np.max(seps):+.2f} (tx {args.level} dB)")

    # achievable AM decisions per frame, then condition on correct tones
    res = {}
    for ref in ("global2m", "tone2m", "dd"):
        errs_all = errs_ok = n_all = n_ok = 0
        idx = 0
        for fi in range(len(frames)):
            n = len(all_tones[fi])
            amp = am_bits_for_frame(all_tones[fi], all_lev[fi],
                                    args.level, ref)
            e = amp != all_txa[fi]
            okf = all_tones[fi] == all_txt[fi]
            errs_all += int(e.sum()); n_all += n
            errs_ok += int((e & okf).sum()); n_ok += int(okf.sum())
            idx += n
        res[ref] = {"am_ber_all": errs_all / n_all,
                    "am_ber_tone_ok": errs_ok / max(1, n_ok)}
        print(f"  ref={ref:9s} am_ber_all={errs_all/n_all:.4f} "
              f"am_ber|tone_ok={errs_ok/max(1,n_ok):.4f}")

    # genie per-tone threshold on correctly-detected symbols (best case)
    g_err = g_tot = 0
    for t in range(16):
        m = ok & (txt == t)
        if m.sum() < 10:
            continue
        v = lev_db[m]; a = txa[m]
        cand = np.unique(v)
        best = (a == 1).sum() if len(cand) == 0 else None
        errs = min(int(np.sum((v < thr) != (a == 1))) for thr in
                   np.concatenate([[v.min() - 1], (np.sort(v)[1:] + np.sort(v)[:-1]) / 2,
                                   [v.max() + 1]]))
        g_err += errs; g_tot += int(m.sum())
    print(f"  GENIE per-tone thr | tone_ok: am_ber={g_err/max(1,g_tot):.4f}")

    out = {"level": args.level, "seed": args.seed,
           "tone_sym_er": float(1 - ok.mean()), "refs": res,
           "genie_per_tone_am_ber_tone_ok": g_err / max(1, g_tot),
           "per_tone_sep_db": {"mean": float(np.mean(seps)),
                               "min": float(np.min(seps)),
                               "max": float(np.max(seps))}}
    p = _HERE / "results" / f"h3_diag_L{args.level:g}_s{args.seed}.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
