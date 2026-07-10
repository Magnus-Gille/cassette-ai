"""Push wired cassette bitrate with real-trace-calibrated hybrid D8PSK.

This experiment generalizes the repo's proven P22 ``DiffMultitoneScheme`` to a
P23 grid with the proven 4875-Hz pilot.  It promotes an increasing number of
real-capture-ranked carriers from DQPSK (2 bits/symbol) to Gray 8-DPSK
(3 bits/symbol), while retaining production RS encoding and global interleave.

Every rung is judged twice:

1. Full waveform simulation through wired/worn and two stress presets.
2. Contiguous block bootstrap of signed phase residuals measured on two real
   tape recordings x both UCA222 channels (preserves carrier/time correlation).

The empirical stage is deliberately the stronger higher-order-modulation gate;
the linear wired waveform model does not include moving notches or measured
phase tails.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
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
from x10_b_aggr_05_dense2x_master import Dense2xDropScheme  # noqa: E402

_DAPS_PATH = (HERE / "bps_push_2026_06_14" / "candidates"
              / "dapsk16-strongmids.py")
_SPEC = importlib.util.spec_from_file_location("wired_dapsk_base", _DAPS_PATH)
_DAPS = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_DAPS)
DiffMultitoneScheme = _DAPS.DiffMultitoneScheme
gray_tables = _DAPS._gray_tables

AUDIT_JSON = HERE / "results" / "wired_constellation_audit.json"
RESIDUALS_NPZ = HERE / "captures" / "wired_constellation_residuals.npz"
OUT = HERE / "results" / "wired_hybrid_dpsk.json"

PAYLOAD_SEED = 20260710
PAYLOAD_BYTES = 8192
FRAME_BYTES = 510
WAVEFORM_SEEDS = [0, 1, 2, 3]
BOOTSTRAP_OFFSETS = 8

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

# Ranked by the worst D8 error proxy across the four long real wired traces.
# 750 and 9375 Hz were not data carriers in those captures, so they remain
# DQPSK in every evidence-backed rung.
RANKED_D8_HZ = [
    1125, 3375, 3750, 1875, 3000, 5250, 4125, 4500, 5625, 6000, 6375,
    2250, 6750, 7125, 7500, 7875, 8250, 9000, 8625, 2625, 1500,
]

CONFIGS = [
    {"id": "p23_dq_rs179", "n8": 0, "rs_k": 179, "role": "P23 control"},
    {"id": "p23_dq_rs191", "n8": 0, "rs_k": 191, "role": "FEC-only banker"},
    {"id": "p23_dq_rs199", "n8": 0, "rs_k": 199, "role": "FEC-only stretch"},
    {"id": "p23_d8x1_rs179", "n8": 1, "rs_k": 179, "role": "lowest-risk D8"},
    {"id": "p23_d8x3_rs179", "n8": 3, "rs_k": 179, "role": "small D8 set"},
    {"id": "p23_d8x5_rs179", "n8": 5, "rs_k": 179, "role": "cross-deck banker"},
    {"id": "p23_d8x14_rs179", "n8": 14, "rs_k": 179, "role": "broad D8 stretch"},
    {"id": "p23_d8x21_rs179", "n8": 21, "rs_k": 179, "role": "measured-grid D8 top"},
    {"id": "p23_d8x21_rs191", "n8": 21, "rs_k": 191, "role": "max-rate stretch"},
]

REFINE_CONFIGS = [
    {"id": f"p23_d8x{n8}_rs179", "n8": n8, "rs_k": 179,
     "role": "D8 loading-cliff refinement"}
    for n8 in range(6, 14)
]

# Trade extra constellation bits for progressively stronger RS while keeping
# candidate net rate near/above the five-carrier banker.
TRADEOFF_CONFIGS = [
    {"id": "p23_d8x8_rs171", "n8": 8, "rs_k": 171,
     "role": "D8/FEC tradeoff"},
    {"id": "p23_d8x10_rs167", "n8": 10, "rs_k": 167,
     "role": "D8/FEC tradeoff"},
    {"id": "p23_d8x12_rs163", "n8": 12, "rs_k": 163,
     "role": "D8/FEC tradeoff"},
    {"id": "p23_d8x14_rs159", "n8": 14, "rs_k": 159,
     "role": "D8/FEC tradeoff"},
    {"id": "p23_d8x16_rs155", "n8": 16, "rs_k": 155,
     "role": "D8/FEC tradeoff"},
    {"id": "p23_d8x18_rs151", "n8": 18, "rs_k": 151,
     "role": "D8/FEC tradeoff"},
    {"id": "p23_d8x21_rs143", "n8": 21, "rs_k": 143,
     "role": "D8/FEC tradeoff"},
]

EDGE_CONFIGS = [
    {"id": "p23_d8x19_rs149", "n8": 19, "rs_k": 149,
     "role": "coded-modulation edge"},
    {"id": "p23_d8x20_rs147", "n8": 20, "rs_k": 147,
     "role": "coded-modulation edge"},
]

CONFIRM_CONFIGS = [
    {"id": "p23_dq_rs179", "n8": 0, "rs_k": 179,
     "role": "paired confirmation control"},
    {"id": "p23_d8x18_rs151", "n8": 18, "rs_k": 151,
     "role": "paired confirmation candidate"},
]


class P23HybridDPSK(DiffMultitoneScheme):
    """P23 fixed-pilot grid with per-data-carrier DQPSK/8-DPSK loading."""

    def __init__(self, d8_freqs_hz):
        # Initialize inherited DSP state, then widen/replace only the geometry
        # and variable-order descriptors.  Modulate/demodulate remain verbatim.
        super().__init__([2] * 22, [False] * 22,
                         name="p23_hybrid_init", skip=64)
        geometry = Dense2xDropScheme(23, [], pilot_hz=4875.0, skip=64)
        self.P = 23
        self.freqs = geometry.freqs.copy()
        self.bins = geometry.bins.copy()
        self.pilot_idx = int(geometry.pilot_idx)
        self.data_idx = geometry.data_idx.copy()
        self.tx_amp = geometry.tx_amp.copy()
        self.bits_per_carrier = [
            3 if round(float(freq)) in set(d8_freqs_hz) else 2
            for freq in self.freqs[self.data_idx]
        ]
        self.ring_carrier = [False] * self.P
        self.phase_bits = list(self.bits_per_carrier)
        self.M = [1 << bits for bits in self.phase_bits]
        self._gray = [gray_tables(bits) for bits in self.phase_bits]
        self.bits_per_sym = int(sum(self.bits_per_carrier))
        self.gross_bps = self.bits_per_sym / (self.N / FS)
        self._rx_skip = 0
        self._rx_Nw = self.N
        self._rx_win = np.hanning(self.N)
        self.d8_freqs_hz = sorted(int(f) for f in d8_freqs_hz)
        self.name = f"P23Hybrid_D8x{len(self.d8_freqs_hz)}_b{self.bits_per_sym}"


def make_payload() -> bytes:
    rng = np.random.default_rng(PAYLOAD_SEED)
    return rng.integers(0, 256, PAYLOAD_BYTES, dtype=np.uint8).tobytes()


def make_codec_frames(config: dict, payload: bytes):
    rung = Rung(name=config["id"], M=23, K=1, rs_n=255,
                rs_k=config["rs_k"], frame_bytes=FRAME_BYTES)
    return codec.encode_payload(payload, rung)


def decode_result(rx_frames, meta, payload: bytes) -> dict:
    recovered = codec.decode_payload(rx_frames, meta)
    return {
        "byte_exact": recovered == payload,
        "sha256_match": hashlib.sha256(recovered).digest()
        == hashlib.sha256(payload).digest(),
        "codewords_failed": int(codec.decode_payload.last_codewords_failed),
    }


def waveform_trial(config: dict, channel_name: str, preset: dict,
                   seed: int, payload: bytes) -> dict:
    d8 = RANKED_D8_HZ[:config["n8"]]
    scheme = P23HybridDPSK(d8)
    frames, meta = make_codec_frames(config, payload)
    rx_frames = []
    raw_errors = 0
    raw_bits = 0
    crests = []
    body_rms = []
    for frame_index, tx_bits in enumerate(frames):
        audio = scheme.modulate(np.asarray(tx_bits, np.uint8))
        rms = float(np.sqrt(np.mean(np.asarray(audio, np.float64) ** 2)))
        crests.append(20 * math.log10(float(np.max(np.abs(audio))) / max(rms, 1e-12)))
        body_rms.append(rms)
        through = wired_channel(audio, preset,
                                seed_offset=seed * 10_000 + frame_index)
        rx_bits = np.asarray(scheme.demodulate(through, FS), np.uint8)
        rx_bits = rx_bits[:len(tx_bits)]
        if len(rx_bits) < len(tx_bits):
            rx_bits = np.concatenate(
                [rx_bits, np.zeros(len(tx_bits) - len(rx_bits), np.uint8)])
        raw_errors += int(np.count_nonzero(rx_bits != tx_bits))
        raw_bits += len(tx_bits)
        rx_frames.append(rx_bits)
    result = decode_result(rx_frames, meta, payload)
    result.update({
        "seed": seed,
        "channel": channel_name,
        "raw_ber": raw_errors / max(1, raw_bits),
        "crest_db_max": max(crests),
        "rms_mean": float(np.mean(body_rms)),
    })
    return result


def empirical_trial(config: dict, trace_id: str, residual_deg: np.ndarray,
                    residual_freqs: list[float], offset_seed: int,
                    payload: bytes) -> dict:
    d8 = RANKED_D8_HZ[:config["n8"]]
    scheme = P23HybridDPSK(d8)
    frames, meta = make_codec_frames(config, payload)
    scheme_freqs = [float(f) for f in scheme.freqs[scheme.data_idx]]
    source_by_freq = {round(f): i for i, f in enumerate(residual_freqs)}
    # Unmeasured edge bins stay DQPSK; borrow the nearest measured residual.
    source_cols = [source_by_freq[min(source_by_freq,
                                      key=lambda known: abs(known - freq))]
                   for freq in scheme_freqs]
    matrix = np.asarray(residual_deg[:, source_cols], np.float64)
    rng = np.random.default_rng(70_000 + offset_seed)
    cursor = int(rng.integers(0, len(matrix)))
    rx_frames = []
    raw_errors = 0
    raw_bits = 0
    for tx_bits in frames:
        nd, sectors, _ = scheme._encode_symbols(np.asarray(tx_bits, np.uint8))
        idx = (cursor + np.arange(nd)) % len(matrix)
        noise = np.radians(matrix[idx])
        cursor = int((cursor + nd) % len(matrix))
        centers = np.zeros((nd, scheme.P), np.float64)
        for carrier, order in enumerate(scheme.M):
            centers[:, carrier] = 2 * np.pi * sectors[:, carrier] / order
        decided = scheme._slice_phase(centers + noise)
        rings = np.full((nd, scheme.P), -1, int)
        rx_bits = scheme._decode_symbols(decided, rings, len(tx_bits))
        rx_bits = np.asarray(rx_bits, np.uint8)[:len(tx_bits)]
        raw_errors += int(np.count_nonzero(rx_bits != tx_bits))
        raw_bits += len(tx_bits)
        rx_frames.append(rx_bits)
    result = decode_result(rx_frames, meta, payload)
    result.update({
        "trace_id": trace_id,
        "offset_seed": offset_seed,
        "raw_ber": raw_errors / max(1, raw_bits),
    })
    return result


def summarize(rows: list[dict]) -> dict:
    return {
        "passes": sum(int(row["byte_exact"]) for row in rows),
        "trials": len(rows),
        "max_raw_ber": max(row["raw_ber"] for row in rows),
        "max_codewords_failed": max(row["codewords_failed"] for row in rows),
        "rows": rows,
    }


def main(configs=None, out_path: pathlib.Path = OUT) -> dict:
    configs = CONFIGS if configs is None else configs
    if not AUDIT_JSON.exists() or not RESIDUALS_NPZ.exists():
        raise SystemExit("run exp_wired_constellation_audit.py first")
    audit = json.loads(AUDIT_JSON.read_text())
    residual_freqs = [row["freq_hz"] for row in audit["cross_trace"]]
    residual_npz = np.load(RESIDUALS_NPZ)
    payload = make_payload()
    started = time.time()
    out = {
        "experiment": "wired-p23-hybrid-d8psk",
        "payload_seed": PAYLOAD_SEED,
        "payload_bytes": PAYLOAD_BYTES,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "frame_bytes": FRAME_BYTES,
        "waveform_seeds": WAVEFORM_SEEDS,
        "bootstrap_offsets_per_trace": BOOTSTRAP_OFFSETS,
        "ranked_d8_hz": RANKED_D8_HZ,
        "audit_sha256": hashlib.sha256(AUDIT_JSON.read_bytes()).hexdigest(),
        "residuals_sha256": hashlib.sha256(RESIDUALS_NPZ.read_bytes()).hexdigest(),
        "configs": [],
    }

    for config in configs:
        d8 = RANKED_D8_HZ[:config["n8"]]
        scheme = P23HybridDPSK(d8)
        projected_mono = scheme.gross_bps * config["rs_k"] / 255.0
        record = dict(config)
        record.update({
            "d8_freqs_hz": d8,
            "bits_per_symbol": scheme.bits_per_sym,
            "gross_bps_mono": scheme.gross_bps,
            "projected_net_bps_mono": projected_mono,
            "projected_net_bps_stereo": 2 * projected_mono,
            "waveform": {},
        })
        for channel_name, preset in CHANNELS.items():
            rows = [waveform_trial(config, channel_name, preset, seed, payload)
                    for seed in WAVEFORM_SEEDS]
            record["waveform"][channel_name] = summarize(rows)
            print(f"[{config['id']} {channel_name}] "
                  f"{record['waveform'][channel_name]['passes']}/{len(rows)} "
                  f"maxBER={record['waveform'][channel_name]['max_raw_ber']:.3e}",
                  flush=True)

        empirical_rows = []
        for trace_id in residual_npz.files:
            for offset_seed in range(BOOTSTRAP_OFFSETS):
                empirical_rows.append(empirical_trial(
                    config, trace_id, residual_npz[trace_id], residual_freqs,
                    offset_seed, payload))
        record["empirical_phase_bootstrap"] = summarize(empirical_rows)
        record["stable_uca_gate"] = bool(
            all(record["waveform"][channel]["passes"]
                == record["waveform"][channel]["trials"]
                for channel in ("wired", "wired_worn", "stress_38db_0p20pct"))
            and record["empirical_phase_bootstrap"]["passes"]
            == record["empirical_phase_bootstrap"]["trials"]
        )
        record["stable_extreme_32db"] = bool(
            record["waveform"]["stress_32db_0p40pct"]["passes"]
            == record["waveform"]["stress_32db_0p40pct"]["trials"]
        )
        record["stable_all_gates"] = bool(
            record["stable_uca_gate"] and record["stable_extreme_32db"]
        )
        print(f"[{config['id']} empirical] "
              f"{record['empirical_phase_bootstrap']['passes']}/"
              f"{record['empirical_phase_bootstrap']['trials']} "
              f"maxBER={record['empirical_phase_bootstrap']['max_raw_ber']:.3e} "
              f"uca_stable={record['stable_uca_gate']} "
              f"extreme32={record['stable_extreme_32db']}", flush=True)
        out["configs"].append(record)

    stable = [record for record in out["configs"] if record["stable_uca_gate"]]
    winner = max(stable, key=lambda record: record["projected_net_bps_stereo"],
                 default=None)
    out["conclusion"] = {
        "winner": winner["id"] if winner else None,
        "winner_stereo_bps": (winner["projected_net_bps_stereo"]
                              if winner else None),
        "winner_n8": winner["n8"] if winner else None,
        "winner_extreme_32db_stable": (winner["stable_extreme_32db"]
                                        if winner else None),
        "scope": (
            "Waveform simulator plus block bootstrap of real wired QPSK phase "
            "residuals. Counterfactual D8 midpoint symbols and a new physical "
            "P23/D8 tape remain unmeasured."
        ),
    }
    out["runtime_seconds"] = time.time() - started
    out_path.write_text(json.dumps(out, indent=2, default=float) + "\n")
    print(f"[done] winner={out['conclusion']['winner']} -> {out_path} "
          f"({out['runtime_seconds']:.1f}s)")
    return out


if __name__ == "__main__":
    import argparse
    import warnings

    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser()
    parser.add_argument("--refine", action="store_true",
                        help="run only the n8=6..13 loading-cliff refinement")
    parser.add_argument("--tradeoff", action="store_true",
                        help="sweep stronger RS against broader D8 loading")
    parser.add_argument("--edge", action="store_true",
                        help="test the n8=19/20 coded-modulation edge")
    parser.add_argument("--confirm", action="store_true",
                        help="32-seed paired control/candidate confirmation")
    args = parser.parse_args()
    if args.refine:
        main(REFINE_CONFIGS, HERE / "results" / "wired_hybrid_dpsk_refine.json")
    elif args.tradeoff:
        main(TRADEOFF_CONFIGS,
             HERE / "results" / "wired_hybrid_dpsk_tradeoff.json")
    elif args.edge:
        main(EDGE_CONFIGS, HERE / "results" / "wired_hybrid_dpsk_edge.json")
    elif args.confirm:
        WAVEFORM_SEEDS[:] = range(32)
        BOOTSTRAP_OFFSETS = 16
        main(CONFIRM_CONFIGS,
             HERE / "results" / "wired_hybrid_dpsk_confirm.json")
    else:
        main()
