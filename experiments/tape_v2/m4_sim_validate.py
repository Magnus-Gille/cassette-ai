"""m4_sim_validate.py — Validation (B): push master4.wav through the FAITHFUL
real_channel_sim at capture="master3" (clean tape) and "master2" (AAC voicememo),
decode with m4_decode, and report byte-exact per payload for a couple of seeds.

This is the sim analogue of recording the tape: the same master4.wav that would be
laid to cassette is run through real_channel_sim.real_channel (the calibrated
channel that reproduces our measured acoustic loop), then handed to the SAME
m4_decode pipeline (global sync + sounder EQ + per-scheme readers). Byte-exact is
verified by comparison to the sidecars (m4_decode does this internally).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import real_channel_sim as rcs    # noqa: E402
import m4_decode                  # noqa: E402

SR = 48_000


def run(capture: str, seeds, master=str(_HERE / "master4.wav")):
    params = rcs.load_params()
    audio, sr = sf.read(master, dtype="float32", always_2d=False)
    assert sr == SR, sr
    rows_by_seed = {}
    for seed in seeds:
        y = rcs.real_channel(audio.astype(np.float64), params=params,
                             capture=capture, seed_offset=int(seed))
        # peak-normalise like a real capture would be
        pk = float(np.max(np.abs(y))) + 1e-12
        y = (y / pk * 0.95).astype(np.float32)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp = tf.name
        sf.write(tmp, y, SR, subtype="FLOAT")
        tag = f"sim_{capture}_seed{seed}"
        print(f"\n=== capture={capture} seed={seed} ===")
        out = m4_decode.decode(tmp, out_tag=tag, verbose=True)
        pathlib.Path(tmp).unlink(missing_ok=True)
        rows_by_seed[seed] = out["payloads"]
    return rows_by_seed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures", nargs="+", default=["master3", "master2"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1])
    args = ap.parse_args()
    summary = {}
    for cap in args.captures:
        summary[cap] = run(cap, args.seeds)
    # compact final summary
    print("\n\n#### SUMMARY (byte-exact per payload) ####")
    for cap, by_seed in summary.items():
        print(f"\ncapture={cap}")
        names = [r["name"] for r in next(iter(by_seed.values()))]
        for nm in names:
            cells = []
            for seed, rows in by_seed.items():
                r = next(x for x in rows if x["name"] == nm)
                cells.append(f"s{seed}:{'YES' if r['byte_exact'] else 'no'}"
                             f"(cw{r['rs_codewords_failed']}/{r['n_codewords']},"
                             f"raw{r['raw_ber']:.3f})")
            print(f"  {nm:<14} " + "  ".join(cells))
    (_HERE / "results").mkdir(exist_ok=True)
    (_HERE / "results" / "m4_sim_validate_summary.json").write_text(
        json.dumps(summary, indent=2, default=float))


if __name__ == "__main__":
    main()
