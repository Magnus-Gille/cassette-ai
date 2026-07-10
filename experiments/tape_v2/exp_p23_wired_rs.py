"""End-to-end RS validation of a higher-rate wired D2X cassette profile.

Hypothesis
----------
The electrical/UCA222 path has enough bandwidth and timing margin to extend the
shipping P21 D2X grid by two data carriers (P23, top tone 9375 Hz).  Keeping the
physically proven RS(255,179) rate is the conservative step; RS(255,207) is a
stretch that converts more of the wired margin into payload rate.

Unlike ``dryrun_d2x_wired.py``'s quick byte-error projection, this experiment
uses the production m3 codec end to end: RS encode, global column interleave,
per-frame modulation/channel/demodulation, deinterleave, RS decode, and payload
hash comparison.  Random seeds and payload bytes are deterministic and logged.

Run::

    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
      python3 experiments/tape_v2/exp_p23_wired_rs.py

Output: ``experiments/tape_v2/results/p23_wired_rs_validation.json``.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = ROOT / "experiments" / "tape_v2"
for path in (ROOT / "src", ROOT / "tests" / "e2e",
             ROOT / "experiments" / "capacity",
             ROOT / "experiments" / "deepdive2", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from assault_wired import FS, WIRED, WIRED_WORN, wired_channel  # noqa: E402
import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
from x10_b_aggr_05_dense2x_master import (  # noqa: E402
    DROP_P21,
    PILOT_HZ,
    Dense2xDropScheme,
    Dense2xScheme,
)
from x9_resampling_pll import ResamplingPLLDemod  # noqa: E402

RESULT = HERE / "results" / "p23_wired_rs_validation.json"
PAYLOAD_SEED = 20260709
CHANNEL_SEEDS = [0, 1, 2, 3]
PAYLOAD_BYTES = 8192
FRAME_BYTES = 510  # production m10 framing

CONFIGS = [
    {
        "id": "control_p21_rs159",
        "P": 21,
        "rs_k": 159,
        "drop": DROP_P21,
        "role": "current tape-proven/full-spectrum wired control",
    },
    {
        "id": "candidate_p23_rs179",
        "P": 23,
        "rs_k": 179,
        "drop": None,
        "role": "recommended: add 9375-Hz carrier, retain proven RS179",
    },
    {
        "id": "stretch_p23_rs207",
        "P": 23,
        "rs_k": 207,
        "drop": None,
        "role": "stretch: convert wired margin to a thinner code",
    },
]

CHANNELS = {
    "wired": WIRED,
    "wired_worn": WIRED_WORN,
    "stress_38db_0p20pct": {
        "snr_db": 38.0,
        "bandwidth_hz": 11_000.0,
        "wow_flutter_wrms": 0.002,
    },
    "stress_32db_0p40pct": {
        "snr_db": 32.0,
        "bandwidth_hz": 11_000.0,
        "wow_flutter_wrms": 0.004,
    },
}

OPERATING_CHANNELS = ("wired", "wired_worn")


def make_schemes(config: dict):
    if config["drop"] is not None:
        tx = Dense2xDropScheme(config["P"], config["drop"],
                              pilot_hz=PILOT_HZ, skip=64)
        rx = Dense2xDropScheme(config["P"], config["drop"],
                              pilot_hz=PILOT_HZ, skip=0)
    else:
        tx = Dense2xScheme(config["P"], skip=64)
        rx = Dense2xScheme(config["P"], skip=0)
    return tx, ResamplingPLLDemod(rx, front_end="ema", ema_alpha=0.7)


def evaluate(config: dict, preset: dict, payload: bytes, channel_seed: int) -> dict:
    tx, demod = make_schemes(config)
    rung = Rung(name=config["id"], M=config["P"], K=1,
                rs_n=255, rs_k=config["rs_k"], frame_bytes=FRAME_BYTES)
    frames, meta = codec.encode_payload(payload, rung)

    rx_frames = []
    raw_errors = 0
    raw_bits = 0
    audio_samples = 0
    front_ends: dict[str, int] = {}
    for frame_index, tx_bits in enumerate(frames):
        audio = tx.modulate(np.asarray(tx_bits, np.uint8))
        audio_samples += len(audio)
        seed = channel_seed * 10_000 + frame_index
        through = wired_channel(audio, preset, seed_offset=seed)
        n_symbols = tx.nsym_data(len(tx_bits))
        rx_bits, diag = demod.demod(np.asarray(through, np.float64), n_symbols,
                                    refine=True)
        rx_bits = np.asarray(rx_bits, np.uint8).ravel()[:len(tx_bits)]
        if len(rx_bits) < len(tx_bits):
            rx_bits = np.concatenate(
                [rx_bits, np.zeros(len(tx_bits) - len(rx_bits), np.uint8)])
        raw_errors += int(np.count_nonzero(rx_bits != tx_bits))
        raw_bits += len(tx_bits)
        rx_frames.append(rx_bits)
        front_end = str(diag.get("front_end", "unknown"))
        front_ends[front_end] = front_ends.get(front_end, 0) + 1

    recovered = codec.decode_payload(rx_frames, meta)
    gross = float(tx.gross_bps)
    projected_net = gross * config["rs_k"] / 255.0
    audio_seconds = audio_samples / FS
    return {
        "channel_seed": channel_seed,
        "byte_exact": recovered == payload,
        "sha256_match": hashlib.sha256(recovered).digest()
        == hashlib.sha256(payload).digest(),
        "codewords_failed": int(codec.decode_payload.last_codewords_failed),
        "raw_ber": raw_errors / max(1, raw_bits),
        "n_frames": meta["n_frames"],
        "n_codewords": meta["n_codewords"],
        "front_ends": front_ends,
        "audio_seconds_excluding_interframe_gaps": audio_seconds,
        "payload_wall_bps_excluding_interframe_gaps": len(payload) * 8 / audio_seconds,
        "gross_bps": gross,
        "projected_net_bps_mono": projected_net,
        "projected_net_bps_stereo": 2 * projected_net,
    }


def main() -> dict:
    rng = np.random.default_rng(PAYLOAD_SEED)
    payload = rng.integers(0, 256, PAYLOAD_BYTES, dtype=np.uint8).tobytes()
    out = {
        "experiment": "p23-wired-production-rs-validation",
        "hypothesis": (
            "P23 D2X at RS(255,179) raises the wired rate by adding a 9375-Hz "
            "carrier while preserving the tape-proven RS179 code strength; "
            "P23/RS207 is the stretch profile."
        ),
        "payload_seed": PAYLOAD_SEED,
        "channel_seeds": CHANNEL_SEEDS,
        "payload_bytes": PAYLOAD_BYTES,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "frame_bytes": FRAME_BYTES,
        "channels": CHANNELS,
        "configs": [],
    }

    started = time.time()
    for config in CONFIGS:
        record = {k: v for k, v in config.items() if k != "drop"}
        record["drop_freqs_hz"] = ([float(f) for f in config["drop"]]
                                    if config["drop"] is not None else [])
        record["channels"] = {}
        for channel_name, preset in CHANNELS.items():
            rows = []
            for seed in CHANNEL_SEEDS:
                row = evaluate(config, preset, payload, seed)
                rows.append(row)
                print(
                    f"[{config['id']} {channel_name} s{seed}] "
                    f"exact={row['byte_exact']} cw_fail={row['codewords_failed']} "
                    f"BER={row['raw_ber']:.3e} "
                    f"net={row['projected_net_bps_mono']:.1f}/ch",
                    flush=True,
                )
            record["channels"][channel_name] = {
                "passes": sum(int(row["byte_exact"]) for row in rows),
                "trials": len(rows),
                "max_raw_ber": max(row["raw_ber"] for row in rows),
                "max_codewords_failed": max(row["codewords_failed"] for row in rows),
                "rows": rows,
            }
        record["all_trials_byte_exact"] = all(
            row["byte_exact"]
            for channel in record["channels"].values()
            for row in channel["rows"]
        )
        record["operating_trials_byte_exact"] = all(
            row["byte_exact"]
            for channel_name in OPERATING_CHANNELS
            for row in record["channels"][channel_name]["rows"]
        )
        out["configs"].append(record)

    control = out["configs"][0]
    candidate = out["configs"][1]
    control_net = control["channels"]["wired"]["rows"][0][
        "projected_net_bps_stereo"]
    candidate_net = candidate["channels"]["wired"]["rows"][0][
        "projected_net_bps_stereo"]
    out["conclusion"] = {
        "recommended_config": candidate["id"],
        "recommended_operating_trials_byte_exact": candidate[
            "operating_trials_byte_exact"],
        "recommended_stress_38db_passes": candidate["channels"][
            "stress_38db_0p20pct"]["passes"],
        "recommended_stress_32db_passes": candidate["channels"][
            "stress_32db_0p40pct"]["passes"],
        "baseline_stereo_bps": control_net,
        "recommended_stereo_bps": candidate_net,
        "gain_pct": 100.0 * (candidate_net / control_net - 1.0),
        "stretch_stereo_bps": out["configs"][2]["channels"]["wired"]["rows"][0][
            "projected_net_bps_stereo"],
        "scope": (
            "Simulator-supported wired result, not a physical-tape proof. "
            "The model omits moving notches, magnetic nonlinearity/IMD, "
            "azimuth, stereo crosstalk, and the full-tape global sync path."
        ),
    }
    out["runtime_seconds"] = time.time() - started
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(out, indent=2, default=float) + "\n")
    print(f"[done] {RESULT} ({out['runtime_seconds']:.1f}s)")
    return out


if __name__ == "__main__":
    import warnings

    warnings.filterwarnings("ignore")
    main()
