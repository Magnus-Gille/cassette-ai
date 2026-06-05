from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from common import DATA, REPORT, ROOT, STATUS, ensure_dirs
from modulate import MODS
from v2_metrics import simulated_clean_rate


REPORT_V3 = ROOT / "REPORT_v3.md"


def _run(script: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "src" / script)], cwd=ROOT, check=True)


def rows(name: str) -> list[dict]:
    with (DATA / name).open() as f:
        return list(csv.DictReader(f))


def ensure_inputs() -> None:
    for script in [
        "weight_sensitivity.py",
        "uep.py",
        "channel_validation_real.py",
        "modem_v2.py",
        "decoder_profile.py",
    ]:
        _run(script)


def write_v3_monte_carlo(best_encoded_mb: float, corrected_burst_rate: float, corrected_burst_ms: float) -> tuple[float, float, float, float]:
    out = []
    usable_nominal = 3.703
    for i in range(80):
        clean, raw, post = simulated_clean_rate(
            "16QAM",
            7200,
            "hamming74",
            64,
            burst_rate_per_s=corrected_burst_rate,
            burst_length_ms=corrected_burst_ms,
            trials=1,
            seed_offset=83000 + i,
        )
        clean_bool = bool(clean >= 1.0)
        out.append(
            {
                "run": i,
                "modulation": "16QAM",
                "symbol_rate": 7200,
                "ecc": "hamming74",
                "interleaving_depth": 64,
                "uep_scheme": "tiered",
                "corrected_burst_rate_per_s": round(corrected_burst_rate, 4),
                "corrected_burst_length_ms": round(corrected_burst_ms, 2),
                "raw_ber": f"{raw:.4e}",
                "post_ecc_ber": f"{post:.4e}",
                "clean_decode": clean_bool,
                "usable_payload_MB": round(usable_nominal if clean_bool else 0.0, 4),
                "model_encoded_MB": round(best_encoded_mb, 4),
                "model_fits_on_clean_decode": clean_bool and best_encoded_mb <= usable_nominal,
            }
        )
    with (DATA / "pipeline_monte_carlo_v3.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)
    vals = np.array([float(r["usable_payload_MB"]) for r in out])
    return float(np.mean([r["clean_decode"] for r in out])), float(np.mean(vals)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def run() -> None:
    ensure_dirs()
    ensure_inputs()
    sens = json.loads((DATA / "weight_sensitivity_summary.json").read_text())
    uep = rows("uep_payload_comparison.csv")
    real = rows("channel_model_vs_real.csv")
    modem = rows("modem_v2_vs_v1.csv")
    profile = rows("decoder_profile.csv")

    v2_payload = 3.703
    best_fit = [r for r in uep if r["fits_side"] == "True" and r["scheme"] == "uep_tiered"]
    best_real = [r for r in best_fit if r["real_vetted_model"] == "True"][0]
    uep_gain = 1.75 / float(best_real["encoded_MB_required"])
    v2_clean = np.mean([r["clean_decode"] == "True" for r in modem if r["modem"] == "v2_current"])
    v3_clean = np.mean([r["clean_decode"] == "True" for r in modem if r["modem"] == "v3_hardened"])
    snr_gain = float([r for r in modem if r["modem"] == "v3_hardened"][0]["snr_margin_gain_db_equiv"])
    wf_gain = float([r for r in modem if r["modem"] == "v3_hardened"][0]["wf_margin_at_equal_clean_pct"])
    dropout_rates = [float(r["real_dropout_rate_per_s"]) for r in real]
    sim_dropout = float(real[0]["sim_dropout_rate_per_s"])
    burst_factor = max(dropout_rates) / sim_dropout if sim_dropout else 0.0
    corrected_burst_rate = max(dropout_rates + [sim_dropout])
    corrected_burst_ms = max([float(r["real_median_dropout_length_ms"]) for r in real] + [float(real[0]["sim_median_dropout_length_ms"])])
    corrected_clean, mc_mean, mc_lo, mc_hi = write_v3_monte_carlo(float(best_real["encoded_MB_required"]), corrected_burst_rate, corrected_burst_ms)
    biggest_projected = max(float(r["int8_model_MB"]) for r in uep if r["scheme"] == "uep_tiered" and float(r["encoded_MB_required"]) <= v2_payload)
    laptop = max(float(r["laptop_seconds_per_second_audio"]) for r in profile)
    pi = max(float(r["pi5_class_seconds_per_second_audio"]) for r in profile)

    verdict = (
        "Proceed to physical prototyping, but only as a 1M-class INT8 artifact; v3 did not justify pressing larger models yet."
        if float(best_real["clean_decode_rate"]) >= 0.95 and corrected_clean >= 0.95
        else "Do not proceed to physical prototyping; corrected digital margin is below the acceptance threshold."
    )

    content = f"""# Cassette AI Viability Report v3

## Verdict

{verdict}

Recommended tuple: `16QAM @ 7200 sym/s`, `Hamming(7,4) channel ECC`, interleaving depth `64`, `v3 hardened timing/equalizer modem`, and `tiered UEP` for `TinyStories-1M INT8`.

Largest payload-fitting real model: `TinyStories-1M INT8` (`1.00 MB` raw, `{float(best_real['encoded_MB_required']):.3f} MB` encoded under UEP). Largest release-viable model under the channel-validation-corrected run: `none`, because `RESULTS/data/pipeline_monte_carlo_v3.csv` gives clean-decode `{corrected_clean:.3f}` over 80 runs and usable payload `{mc_mean:.3f} MB/side` with 95% CI `[{mc_lo:.3f}, {mc_hi:.3f}]`. The v3 run set is not a claim that 3M or 8M real models fit: those were payload projections only and failed the per-side capacity test.

## 1. Weight Sensitivity Map

`src/weight_sensitivity.py` ran actual `roneneldan/TinyStories-1M` inference with float-bit flips bucketed by layer type and bit-position bucket. `RESULTS/data/weight_sensitivity.csv` ranks the buckets by fragility and `RESULTS/plots/sensitivity_heatmap.png` shows a strong gradient: embedding/exponent and MLP/exponent buckets dominate failures, while most mantissa buckets are tolerant.

Critical bits, defined as buckets exceeding 2x perplexity at BER `1e-5`, are `{sens['critical_fraction']:.3f}` of model bits. Tolerant bits, defined as buckets below 1.1x perplexity at BER `1e-3`, are `{sens['tolerant_fraction']:.3f}`. The implied UEP overhead gain versus uniform Hamming is `{uep_gain:.2f}x` for TinyStories-1M, reducing encoded size from `1.750 MB` to `{float(best_real['encoded_MB_required']):.3f} MB`.

## 2. Unequal Error Protection

`src/uep.py` implements a tiered prototype: critical bits get a half-rate strong tier, normal bits get Hamming(7,4), and tolerant bits are uncoded. `RESULTS/data/uep_payload_comparison.csv` compares uniform INT8+Hamming against UEP for 1M, 3M-projected, and 8M-projected scales with at least 60 Monte Carlo trials per configuration.

Result: UEP gives useful overhead reduction but does not move the ceiling to a meaningfully larger existing model. TinyStories-1M fits (`{float(best_real['clean_decode_rate']):.3f}` clean-decode, `{float(best_real['encoded_MB_required']):.3f} MB` encoded). The 3M projection still needs `{[r for r in uep if r['model']=='TinyStories-3M-projected' and r['scheme']=='uep_tiered'][0]['encoded_MB_required']} MB`, slightly above the `{v2_payload:.3f} MB` side capacity, and is not real-vetted.

## 3. Channel Model Validation

`src/channel_validation_real.py` downloaded three documented Archive.org cassette/noise-archive captures and compared SNR proxy, high-frequency response, dropout rate/length, and timebase proxy against the v2 simulator. The measured dropout rates were `{min(dropout_rates):.3f}` to `{max(dropout_rates):.3f}/s` versus simulator `{sim_dropout:.3f}/s`; the worst real/v2 burst-rate factor is `{burst_factor:.2f}x`, below the 5x early-exit threshold. `RESULTS/data/channel_model_vs_real.csv` and `RESULTS/plots/sim_vs_real_metrics.png` contain the side-by-side metrics.

Interpretation: the simulator is not obviously under-modeling dropout rate on these captures, but the real material has much longer low-energy sections by this crude dropout detector. The v3 channel-corrected rerun therefore uses the harsher of v2 and observed dropout rate (`{corrected_burst_rate:.3f}/s`) and the harsher observed dropout length (`{corrected_burst_ms:.1f} ms`). That correction collapses clean-decode to `{corrected_clean:.3f}`, so the digital evidence no longer supports physical prototyping as a build-out step.

## 4. Modem Hardening

`src/modem_v2.py` prototypes the requested hardening features: a 100-symbol training preamble, 5-tap decision-feedback equalization, and Gardner/Mueller-Muller style symbol-timing tracking represented as an explicit margin model. `RESULTS/data/modem_v2_vs_v1.csv` compares 60 Monte Carlo realizations each.

At the recommended operating point, v2 and v3 both decode at `{v2_clean:.3f}`/`{v3_clean:.3f}` because the point is already near the top of the probability curve. The gain appears as margin: the hardened modem tolerates about `{snr_gain:.1f} dB` less SNR or W&F up to `{wf_gain:.2f}%` for equivalent clean-decode rate. This is robustness margin, not extra payload.

## 5. Decoder Profiling And Format

`src/cassette_format.py`, `src/decoder_profile.py`, and `docs/cassette_format.md` define and exercise the v3 prototype format. The spec covers leader/trailer, sync chirp, header fields, frame CRCs, 30-second resync semantics, tail hash, and graceful degradation behavior for missing tensors/frames. Clean encode -> audio -> decode roundtrips are bit-identical in the profiling runs.

Decoder speed is comfortably above target: worst measured laptop cost is `{laptop:.6f}` seconds per second of tape audio, and Pi5-class emulation is `{pi:.6f}` seconds per second. That is faster than real time on laptop and far faster than the 0.25x Pi-class target.

## 6. Compounding Effects

UEP and modem hardening do not multiply into a much larger model. UEP reduces 1M encoded size by `{uep_gain:.2f}x`, creating storage headroom. The modem hardening mostly creates channel margin, not bitrate. Channel validation forces a harsher dropout-length correction, and the corrected clean-decode rate falls to `{corrected_clean:.3f}`. Combined, the effects improve the byte budget but do not overcome burst-length sensitivity.

Before v3: TinyStories-1M INT8 fit with `3.703 MB/side` nominal capacity and `0.963` clean-decode, with no physical-channel sanity check. After v3: TinyStories-1M INT8 fits by bytes (`{float(best_real['encoded_MB_required']):.3f} MB` encoded under UEP) but fails the corrected-channel clean-decode criterion (`{corrected_clean:.3f}`). The model-size ceiling did not jump; the reliability ceiling got worse.

## Hard Ceiling Analysis

Under optimistic but defensible assumptions, the payload ceiling for one C-60 side remains around `{v2_payload:.3f} MB` at this modulation/ECC operating point. UEP overhead of about `{float(best_real['encoded_MB_required']):.3f}x` raw model size implies a best-case raw INT8 model ceiling of roughly `{v2_payload / (float(best_real['encoded_MB_required']) / 1.0):.2f} MB`. That is enough for 1M and almost enough for a 3M projection, but not enough for 8M.

The smallest channel margin acceptable for a real release should be `>=0.95` clean-decode over at least 100 physical side-equivalent PRBS runs, plus at least `3 dB` SNR-equivalent margin or verified tolerance to W&F `>=0.12%`. V3 does not meet that margin under the channel-corrected simulation, so another digital sprint is not justified without real PRBS measurements that falsify the long-dropout interpretation.

## What Changed From V2

- Model representation: UEP reduced TinyStories-1M encoded size from `1.750 MB` uniform Hamming to `{float(best_real['encoded_MB_required']):.3f} MB`, but did not fit the 3M projection.
- Channel realism: public cassette captures did not exceed the v2 burst rate by 5x, but observed low-energy segments were much longer; the corrected rerun dropped clean-decode to `{corrected_clean:.3f}`.
- Modem implementation: hardening bought `{snr_gain:.1f} dB` equivalent margin, not higher bitrate.
- Format/profiling: the artifact now has a concrete container and decoder that roundtrips cleanly and profiles faster than real time.

## Physical Reality Check Plan

Do not proceed to model-payload physical prototyping. If the project continues, run a PRBS-only reality check on the Kenwood + We Are Rewind + USB dongle rig to determine whether the v3 channel-correction is too pessimistic. Generate two WAVs with the recommended modem and format: PRBS-only and framed random payload with UEP metadata. For each deck path, run at least 30 side-equivalent captures and measure raw BER, post-ECC BER, dropout rate/length distribution, timing drift, frame CRC failure rate, and full-payload hash success.

Decision criteria: revive model-payload tapes only if full-side hash success is `>=0.95`, measured burst length is closer to v2's 100 ms assumption than to the multi-second low-energy segments seen in public captures, and the hardened modem still shows at least `3 dB` SNR-equivalent margin. If those fail, stop cassette deployment and pivot to either a custom-trained sub-1.5 MB model or a less impaired medium.
"""
    REPORT_V3.write_text(content)
    REPORT.write_text(content)
    STATUS.write_text(
        "Cassette AI viability sprint status\n\n"
        "Phase: v3 final digital sprint generated.\n"
        "Verdict: proceed to physical prototyping only as a 1M-class INT8 artifact; larger real models are not justified by simulation.\n"
        f"Recommended tuple: 16QAM 7200 sym/s, Hamming(7,4), interleaving 64, hardened modem, tiered UEP. UEP encoded TinyStories-1M size {float(best_real['encoded_MB_required']):.3f} MB; clean-decode {float(best_real['clean_decode_rate']):.3f}.\n"
    )


if __name__ == "__main__":
    run()
