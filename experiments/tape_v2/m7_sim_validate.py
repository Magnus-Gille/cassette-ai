"""m7_sim_validate.py -- push master7.wav (merged m5+m6 ladder) through the
FAITHFUL real_channel_sim and decode with m7_decode, to predict the per-rung
real-tape behaviour before recording.

Same approach as m5_sim_validate / m4_sim_validate. capture="master3" = clean
tape, "master2" = AAC voicememo path.
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
import m7_decode                  # noqa: E402

SR = 48_000


def run(capture: str, seeds, master=str(_HERE / "master7.wav")):
    params = rcs.load_params()
    audio, sr = sf.read(master, dtype="float32", always_2d=False)
    assert sr == SR, sr
    rows_by_seed = {}
    for seed in seeds:
        y = rcs.real_channel(audio.astype(np.float64), params=params,
                             capture=capture, seed_offset=int(seed))
        pk = float(np.max(np.abs(y))) + 1e-12
        y = (y / pk * 0.95).astype(np.float32)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp = tf.name
        sf.write(tmp, y, SR, subtype="FLOAT")
        tag = f"sim_{capture}_seed{seed}"
        print(f"\n=== capture={capture} seed={seed} ===")
        out = m7_decode.decode(tmp, out_tag=tag, verbose=True)
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
    print("\n\n#### SUMMARY (byte-exact per rung) ####")
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
            print(f"  {nm:<16} " + "  ".join(cells))
    (_HERE / "results").mkdir(exist_ok=True)
    (_HERE / "results" / "m7_sim_validate_summary.json").write_text(
        json.dumps(summary, indent=2, default=float))


if __name__ == "__main__":
    main()
