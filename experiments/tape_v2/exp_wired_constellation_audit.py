"""Measure counterfactual M-DPSK phase margin on real wired tape captures.

The audit re-demodulates four independent channel traces (two recordings x L/R)
with the production D2X Hann256/EMA front end, then scores its phase residuals
against the known transmitted quadrants.  The QPSK residual distribution gives
an empirical error proxy for narrower differential constellations:

* 8-DPSK decision boundary: 22.5 degrees
* 16-DPSK decision boundary: 11.25 degrees

No truth is used by timing recovery or the decision-directed refinement; truth
is used only after demodulation to score residuals and symbol errors.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = ROOT / "experiments" / "tape_v2"
for path in (ROOT / "src", ROOT / "tests" / "e2e",
             ROOT / "experiments" / "deepdive2",
             ROOT / "experiments" / "capacity", HERE,
             HERE / "doom_ship"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import analyze_master2 as am2  # noqa: E402
from h4_dqpsk import PAD_HI_S, PAD_LO_S  # noqa: E402
import m3_codec as codec  # noqa: E402
from m3_codec import Rung  # noqa: E402
import m9_decode as m9d  # noqa: E402
import m10_decode as m10  # noqa: E402
from x10_c_evm_probe import _ema_demod_soft  # noqa: E402

FS = 48_000
OUT = HERE / "results" / "wired_constellation_audit.json"
RESIDUALS_OUT = HERE / "captures" / "wired_constellation_residuals.npz"

TRACES = [
    {
        "id": "same_payload_L",
        "capture": "captures/d2x_tape_20260622_144837.wav",
        "manifest": "cal_d2x_manifest.json",
        "channel": 0,
    },
    {
        "id": "same_payload_R",
        "capture": "captures/d2x_tape_20260622_144837.wav",
        "manifest": "cal_d2x_manifest.json",
        "channel": 1,
    },
    {
        "id": "independent_payload_L",
        "capture": "captures/d2x_tape_indep_20260622_154412.wav",
        "manifest": "cal_d2x_L_manifest.json",
        "channel": 0,
    },
    {
        "id": "independent_payload_R",
        "capture": "captures/d2x_tape_indep_20260622_154412.wav",
        "manifest": "cal_d2x_R_manifest.json",
        "channel": 1,
    },
]


def wrap_phase(x: np.ndarray) -> np.ndarray:
    return (x + np.pi) % (2 * np.pi) - np.pi


def load_trace(trace: dict):
    manifest_path = HERE / trace["manifest"]
    capture_path = HERE / trace["capture"]
    manifest = json.loads(manifest_path.read_text())
    audio, sr = sf.read(capture_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio[:, trace["channel"]]
    if sr != FS:
        frac = Fraction(FS, sr).limit_denominator(20_000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator).astype(np.float32)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])
    return manifest, audio_nom, align, sync, capture_path


def audit_trace(trace: dict) -> dict:
    manifest, audio_nom, align, sync, capture_path = load_trace(trace)
    sec = manifest["ws_payloads"][0]
    meta = sec["meta"]
    sch = m10._d2x_rx_scheme(sec, "hann256_skip0")
    known = (HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                rs_n=meta["rs_n"], rs_k=meta["rs_k"],
                frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(known, rung)
    nominal_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    full_len = len(np.asarray(sch.modulate(
        np.zeros(meta["frame_bits"], np.uint8))))
    freqs = sch.freqs[sch.data_idx]
    residuals = [[] for _ in range(sch.P)]
    errors = np.zeros(sch.P, int)
    totals = np.zeros(sch.P, int)

    for frame_index, frame_start in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nominal_bits[frame_index])
        start = int(frame_start) + align
        window = np.asarray(audio_nom[max(0, start - pad_lo):
                                      min(len(audio_nom), start + full_len + pad_hi)],
                            np.float64)
        c, dtau = _ema_demod_soft(sch, window, nd, alpha=0.7)
        q_true = sch.bits_to_quadrants(
            np.asarray(tx_frames[frame_index], np.uint8))
        n = min(nd, len(q_true), len(c) - 1)

        differential = c[1:n + 1] * np.conj(c[:n])
        phase = np.angle(differential[:, sch.data_idx])
        phase -= 2 * np.pi * np.outer(dtau[1:n + 1], freqs)

        # Production-style, truth-free decision-directed common timing refine.
        q_first = np.round(phase / (np.pi / 2)).astype(int) % 4
        decision_residual = wrap_phase(phase - q_first * (np.pi / 2))
        dtau_residual = ((decision_residual * freqs[None, :]).sum(axis=1)
                         / (2 * np.pi * (freqs ** 2).sum()))
        phase_refined = phase - 2 * np.pi * dtau_residual[:, None] * freqs[None, :]
        q_final = np.round(phase_refined / (np.pi / 2)).astype(int) % 4
        truth_residual = wrap_phase(
            phase_refined - q_true[:n] * (np.pi / 2))

        for carrier in range(sch.P):
            residuals[carrier].append(truth_residual[:, carrier])
            errors[carrier] += int(np.count_nonzero(
                q_final[:, carrier] != q_true[:n, carrier]))
            totals[carrier] += n

    signed_degrees = np.column_stack([
        np.degrees(np.concatenate(residuals[carrier]))
        for carrier in range(sch.P)
    ])
    per_carrier = []
    for carrier, freq in enumerate(freqs):
        degrees = np.abs(signed_degrees[:, carrier])
        per_carrier.append({
            "freq_hz": float(freq),
            "n_symbols": int(len(degrees)),
            "dqpsk_ser": float(errors[carrier] / max(1, totals[carrier])),
            "rms_deg": float(np.sqrt(np.mean(degrees ** 2))),
            "p90_deg": float(np.percentile(degrees, 90)),
            "p99_deg": float(np.percentile(degrees, 99)),
            "p99p9_deg": float(np.percentile(degrees, 99.9)),
            "max_deg": float(np.max(degrees)),
            "d8psk_error_proxy": float(np.mean(degrees > 22.5)),
            "d16psk_error_proxy": float(np.mean(degrees > 11.25)),
        })

    return {
        "id": trace["id"],
        "capture": trace["capture"],
        "capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
        "manifest": trace["manifest"],
        "channel": trace["channel"],
        "speed": float(sync["speed"]),
        "n_frames": meta["n_frames"],
        "n_codewords": meta["n_codewords"],
        "per_carrier": per_carrier,
        "_signed_residual_deg": signed_degrees.astype(np.float32),
    }


def main() -> dict:
    started = time.time()
    traces = []
    residual_arrays = {}
    for trace in TRACES:
        row = audit_trace(trace)
        residual_arrays[row["id"]] = row.pop("_signed_residual_deg")
        traces.append(row)
        worst8 = max(c["d8psk_error_proxy"] for c in row["per_carrier"])
        print(f"[{row['id']}] speed={row['speed']:.6f} "
              f"worst D8 proxy={worst8:.4e}", flush=True)

    by_freq: dict[float, list[dict]] = {}
    for trace in traces:
        for carrier in trace["per_carrier"]:
            by_freq.setdefault(carrier["freq_hz"], []).append(carrier)

    cross_trace = []
    for freq, rows in sorted(by_freq.items()):
        worst8 = max(row["d8psk_error_proxy"] for row in rows)
        worst16 = max(row["d16psk_error_proxy"] for row in rows)
        worst99 = max(row["p99_deg"] for row in rows)
        worst999 = max(row["p99p9_deg"] for row in rows)
        cross_trace.append({
            "freq_hz": freq,
            "worst_dqpsk_ser": max(row["dqpsk_ser"] for row in rows),
            "worst_d8psk_error_proxy": worst8,
            "worst_d16psk_error_proxy": worst16,
            "worst_p99_deg": worst99,
            "worst_p99p9_deg": worst999,
            "d8psk_conservative": bool(worst8 <= 1e-3 and worst99 <= 22.5),
            "d16psk_conservative": bool(worst16 <= 1e-3 and worst99 <= 11.25),
        })

    selected8 = [row["freq_hz"] for row in cross_trace
                 if row["d8psk_conservative"]]
    selected16 = [row["freq_hz"] for row in cross_trace
                  if row["d16psk_conservative"]]
    RESIDUALS_OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(RESIDUALS_OUT, **residual_arrays)
    residuals_sha = hashlib.sha256(RESIDUALS_OUT.read_bytes()).hexdigest()
    out = {
        "experiment": "real-wired-d2x-constellation-audit",
        "decision_boundaries_deg": {"dqpsk": 45.0, "d8psk": 22.5,
                                     "d16psk": 11.25},
        "selection_rule": (
            "conservative iff worst error proxy across all four traces <=1e-3 "
            "and worst p99 is inside that constellation's boundary"
        ),
        "traces": traces,
        "cross_trace": cross_trace,
        "selected_d8psk_hz": selected8,
        "selected_d16psk_hz": selected16,
        "residuals_npz": str(RESIDUALS_OUT.relative_to(HERE)),
        "residuals_sha256": residuals_sha,
        "runtime_seconds": time.time() - started,
        "scope": (
            "Counterfactual thresholding of DQPSK residuals on two real wired "
            "recordings and both stereo channels; a new M-DPSK waveform still "
            "requires end-to-end simulation and physical recording."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"D8 conservative carriers: {selected8}")
    print(f"D16 conservative carriers: {selected16}")
    print(f"[done] {OUT} ({out['runtime_seconds']:.1f}s)")
    return out


if __name__ == "__main__":
    import warnings

    warnings.filterwarnings("ignore")
    main()
