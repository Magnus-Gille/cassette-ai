"""assault_css_optimize.py -- optimize the no-cable acoustic CSS path.

This builds on assault_css.py, which fixed the old H4 CSS bug by using a real
passband chirp and analytic-signal receiver. The first CSS assault proved the
ceiling was excellent but left an uncomfortable result: RS(255,127) closed 7/8
flutter seeds, failing one adversarial seed.

This script sweeps the two honest robustness knobs for the speaker->phone path:

  * pilot_every: known CSS pilot spacing for timing interpolation.
  * RS(255,k): outer-code strength after global interleave.

The target is not "lowest BER"; it is the highest net bps that recovers the test
payload byte-exact on every checked seed through real_channel_sim.

Run:
    python3 experiments/tape_v2/assault_css_optimize.py

Faster smoke run:
    python3 experiments/tape_v2/assault_css_optimize.py --payload-bytes 1024 \
        --seeds 2 --pilots 2 --rs-ks 95
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ("src", "experiments/tape_v2"):
    s = str(ROOT / _p)
    if s not in sys.path:
        sys.path.insert(0, s)

from assault_css import CSSScheme, load_params, real_channel  # noqa: E402
from m3_codec import Rung, decode_payload, encode_payload  # noqa: E402

FS = 48_000
RESULTS = ROOT / "experiments" / "tape_v2" / "results"
REPORT = ROOT / "REPORT.md"


def _roundtrip(
    scheme: CSSScheme,
    params: dict,
    payload: bytes,
    *,
    pilot_every: int,
    rs_k: int,
    seed_offset: int,
) -> dict:
    rung = Rung(
        name=f"css_rs{rs_k}",
        M=0,
        K=0,
        rs_n=255,
        rs_k=rs_k,
        frame_bytes=2000,
    )
    frames, meta = encode_payload(payload, rung)
    all_tx_bits = np.concatenate([np.asarray(f, np.uint8) for f in frames]).astype(np.uint8)
    pad = (-len(all_tx_bits)) % scheme.bits_per_sym
    if pad:
        all_tx_bits = np.concatenate([all_tx_bits, np.zeros(pad, np.uint8)])

    tx_vals = scheme._bits_to_syms(all_tx_bits)
    tx_syms = [scheme._gray(int(v)) for v in tx_vals]
    audio = scheme.modulate_piloted(tx_syms, pilot_every)
    y = real_channel(
        audio,
        params=params,
        capture="master3",
        symbol_len=scheme.sps,
        seed_offset=seed_offset,
    )

    rx_syms = scheme.demod_piloted(y, len(tx_syms), pilot_every)
    rx_vals = [scheme._ungray(int(g)) for g in rx_syms]
    rx_bits = np.concatenate([scheme._sym_to_bits(int(v)) for v in rx_vals]).astype(np.uint8)
    rx_bits = rx_bits[: len(all_tx_bits) - pad] if pad else rx_bits

    stream_bits = meta["stream_bits"]
    nominal_tx = np.concatenate([np.asarray(f, np.uint8) for f in frames])[:stream_bits]
    raw_ber = float(np.mean(rx_bits[:stream_bits] != nominal_tx[: len(rx_bits[:stream_bits])]))

    rec_frames = []
    fb_bits = meta["frame_bits"]
    for fi in range(meta["n_frames"]):
        nominal = (
            fb_bits
            if fi < meta["n_frames"] - 1
            else stream_bits - fb_bits * (meta["n_frames"] - 1)
        )
        rec_frames.append(rx_bits[fi * fb_bits : fi * fb_bits + nominal])

    recovered = decode_payload(rec_frames, meta)
    return {
        "byte_exact": recovered == payload,
        "raw_bit_ber": raw_ber,
        "cw_failed": int(decode_payload.last_codewords_failed),
        "n_codewords": int(meta["n_codewords"]),
        "n_frames": int(meta["n_frames"]),
    }


def sweep(args: argparse.Namespace) -> dict:
    params = load_params()
    scheme = CSSScheme(sf=args.sf, bw=args.bw, fc=args.fc)
    rng = np.random.default_rng(args.payload_seed)
    payload = bytes(rng.integers(0, 256, size=args.payload_bytes, dtype=np.uint8).tolist())

    out = {
        "scheme": scheme.name,
        "capture_model": "master3",
        "payload_bytes": args.payload_bytes,
        "seed_offsets": list(range(args.seeds)),
        "rs_n": 255,
        "results": [],
    }

    print(
        f"CSS optimize: {scheme.name}, payload={args.payload_bytes}B, "
        f"seeds={args.seeds}"
    )
    print(
        f"  {'pilot':>5} {'rs_k':>5} {'net_bps':>8} {'ok':>5} "
        f"{'maxBER':>7} {'cwFail':>18} {'sec':>6}"
    )

    for pilot_every in args.pilots:
        for rs_k in args.rs_ks:
            t0 = time.time()
            seed_results = [
                _roundtrip(
                    scheme,
                    params,
                    payload,
                    pilot_every=pilot_every,
                    rs_k=rs_k,
                    seed_offset=seed_offset,
                )
                for seed_offset in range(args.seeds)
            ]
            net_bps = (
                scheme.bits_per_sym
                * FS
                / scheme.sps
                * (pilot_every / (pilot_every + 1.0))
                * (rs_k / 255.0)
            )
            oks = [r["byte_exact"] for r in seed_results]
            bers = [r["raw_bit_ber"] for r in seed_results]
            fails = [r["cw_failed"] for r in seed_results]
            row = {
                "pilot_every": pilot_every,
                "rs_k": rs_k,
                "net_bps": round(net_bps, 1),
                "ok_count": int(sum(oks)),
                "seed_count": len(oks),
                "all_byte_exact": bool(all(oks)),
                "max_raw_bit_ber": round(float(max(bers)), 5),
                "cw_failed_by_seed": fails,
                "seconds": round(time.time() - t0, 1),
            }
            out["results"].append(row)
            print(
                f"  {pilot_every:5d} {rs_k:5d} {net_bps:8.1f} "
                f"{sum(oks):2d}/{len(oks):<2d} {max(bers):7.3f} "
                f"{str(fails):>18s} {row['seconds']:6.1f}",
                flush=True,
            )

    winners = [r for r in out["results"] if r["all_byte_exact"]]
    if winners:
        best = max(winners, key=lambda r: r["net_bps"])
        out["best_all_clean"] = best
    else:
        out["best_all_clean"] = None

    RESULTS.mkdir(parents=True, exist_ok=True)
    path = pathlib.Path(args.out)
    if not path.is_absolute():
        path = RESULTS / path
    path.write_text(json.dumps(out, indent=2) + "\n")

    if out["best_all_clean"]:
        b = out["best_all_clean"]
        summary = (
            "\n## CSS acoustic optimizer\n\n"
            f"`experiments/tape_v2/assault_css_optimize.py` swept pilot density "
            f"and RS strength for the no-cable CSS path through the faithful "
            f"real-channel simulator. Best all-clean point in this run: "
            f"pilot_every={b['pilot_every']}, RS(255,{b['rs_k']}), "
            f"net {b['net_bps']} bps, {b['ok_count']}/{b['seed_count']} "
            f"byte-exact seeds; max raw BER {b['max_raw_bit_ber']}.\n"
        )
        with REPORT.open("a") as f:
            f.write(summary)

    print(f"\nSaved {path}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=int, default=6)
    ap.add_argument("--bw", type=float, default=9000.0)
    ap.add_argument("--fc", type=float, default=5000.0)
    ap.add_argument("--payload-bytes", type=int, default=4000)
    ap.add_argument("--payload-seed", type=int, default=7)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--pilots", type=int, nargs="+", default=[2, 3, 4])
    ap.add_argument("--rs-ks", type=int, nargs="+", default=[127, 111, 95, 79, 63])
    ap.add_argument("--out", default="assault_css_optimize.json")
    sweep(ap.parse_args())


if __name__ == "__main__":
    main()
