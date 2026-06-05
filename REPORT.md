# Cassette AI Viability Report v3

## Verdict

Do not proceed to physical prototyping; corrected digital margin is below the acceptance threshold.

Recommended tuple: `16QAM @ 7200 sym/s`, `Hamming(7,4) channel ECC`, interleaving depth `64`, `v3 hardened timing/equalizer modem`, and `tiered UEP` for `TinyStories-1M INT8`.

Largest payload-fitting real model: `TinyStories-1M INT8` (`1.00 MB` raw, `1.271 MB` encoded under UEP). Largest release-viable model under the channel-validation-corrected run: `none`, because `RESULTS/data/pipeline_monte_carlo_v3.csv` gives clean-decode `0.075` over 80 runs and usable payload `0.278 MB/side` with 95% CI `[0.000, 3.703]`. The v3 run set is not a claim that 3M or 8M real models fit: those were payload projections only and failed the per-side capacity test.

## 1. Weight Sensitivity Map

`src/weight_sensitivity.py` ran actual `roneneldan/TinyStories-1M` inference with float-bit flips bucketed by layer type and bit-position bucket. `RESULTS/data/weight_sensitivity.csv` ranks the buckets by fragility and `RESULTS/plots/sensitivity_heatmap.png` shows a strong gradient: embedding/exponent and MLP/exponent buckets dominate failures, while most mantissa buckets are tolerant.

Critical bits, defined as buckets exceeding 2x perplexity at BER `1e-5`, are `0.241` of model bits. Tolerant bits, defined as buckets below 1.1x perplexity at BER `1e-3`, are `0.719`. The implied UEP overhead gain versus uniform Hamming is `1.38x` for TinyStories-1M, reducing encoded size from `1.750 MB` to `1.271 MB`.

## 2. Unequal Error Protection

`src/uep.py` implements a tiered prototype: critical bits get a half-rate strong tier, normal bits get Hamming(7,4), and tolerant bits are uncoded. `RESULTS/data/uep_payload_comparison.csv` compares uniform INT8+Hamming against UEP for 1M, 3M-projected, and 8M-projected scales with at least 60 Monte Carlo trials per configuration.

Result: UEP gives useful overhead reduction but does not move the ceiling to a meaningfully larger existing model. TinyStories-1M fits (`0.967` clean-decode, `1.271 MB` encoded). The 3M projection still needs `3.814 MB`, slightly above the `3.703 MB` side capacity, and is not real-vetted.

## 3. Channel Model Validation

`src/channel_validation_real.py` downloaded three documented Archive.org cassette/noise-archive captures and compared SNR proxy, high-frequency response, dropout rate/length, and timebase proxy against the v2 simulator. The measured dropout rates were `0.022` to `0.067/s` versus simulator `0.111/s`; the worst real/v2 burst-rate factor is `0.60x`, below the 5x early-exit threshold. `RESULTS/data/channel_model_vs_real.csv` and `RESULTS/plots/sim_vs_real_metrics.png` contain the side-by-side metrics.

Interpretation: the simulator is not obviously under-modeling dropout rate on these captures, but the real material has much longer low-energy sections by this crude dropout detector. The v3 channel-corrected rerun therefore uses the harsher of v2 and observed dropout rate (`0.111/s`) and the harsher observed dropout length (`6549.0 ms`). That correction collapses clean-decode to `0.075`, so the digital evidence no longer supports physical prototyping as a build-out step.

## 4. Modem Hardening

`src/modem_v2.py` prototypes the requested hardening features: a 100-symbol training preamble, 5-tap decision-feedback equalization, and Gardner/Mueller-Muller style symbol-timing tracking represented as an explicit margin model. `RESULTS/data/modem_v2_vs_v1.csv` compares 60 Monte Carlo realizations each.

At the recommended operating point, v2 and v3 both decode at `0.967`/`0.967` because the point is already near the top of the probability curve. The gain appears as margin: the hardened modem tolerates about `6.5 dB` less SNR or W&F up to `0.24%` for equivalent clean-decode rate. This is robustness margin, not extra payload.

## 5. Decoder Profiling And Format

`src/cassette_format.py`, `src/decoder_profile.py`, and `docs/cassette_format.md` define and exercise the v3 prototype format. The spec covers leader/trailer, sync chirp, header fields, frame CRCs, 30-second resync semantics, tail hash, and graceful degradation behavior for missing tensors/frames. Clean encode -> audio -> decode roundtrips are bit-identical in the profiling runs.

Decoder speed is comfortably above target: worst measured laptop cost is `0.000189` seconds per second of tape audio, and Pi5-class emulation is `0.000520` seconds per second. That is faster than real time on laptop and far faster than the 0.25x Pi-class target.

## 6. Compounding Effects

UEP and modem hardening do not multiply into a much larger model. UEP reduces 1M encoded size by `1.38x`, creating storage headroom. The modem hardening mostly creates channel margin, not bitrate. Channel validation forces a harsher dropout-length correction, and the corrected clean-decode rate falls to `0.075`. Combined, the effects improve the byte budget but do not overcome burst-length sensitivity.

Before v3: TinyStories-1M INT8 fit with `3.703 MB/side` nominal capacity and `0.963` clean-decode, with no physical-channel sanity check. After v3: TinyStories-1M INT8 fits by bytes (`1.271 MB` encoded under UEP) but fails the corrected-channel clean-decode criterion (`0.075`). The model-size ceiling did not jump; the reliability ceiling got worse.

## Hard Ceiling Analysis

Under optimistic but defensible assumptions, the payload ceiling for one C-60 side remains around `3.703 MB` at this modulation/ECC operating point. UEP overhead of about `1.271x` raw model size implies a best-case raw INT8 model ceiling of roughly `2.91 MB`. That is enough for 1M and almost enough for a 3M projection, but not enough for 8M.

The smallest channel margin acceptable for a real release should be `>=0.95` clean-decode over at least 100 physical side-equivalent PRBS runs, plus at least `3 dB` SNR-equivalent margin or verified tolerance to W&F `>=0.12%`. V3 does not meet that margin under the channel-corrected simulation, so another digital sprint is not justified without real PRBS measurements that falsify the long-dropout interpretation.

## What Changed From V2

- Model representation: UEP reduced TinyStories-1M encoded size from `1.750 MB` uniform Hamming to `1.271 MB`, but did not fit the 3M projection.
- Channel realism: public cassette captures did not exceed the v2 burst rate by 5x, but observed low-energy segments were much longer; the corrected rerun dropped clean-decode to `0.075`.
- Modem implementation: hardening bought `6.5 dB` equivalent margin, not higher bitrate.
- Format/profiling: the artifact now has a concrete container and decoder that roundtrips cleanly and profiles faster than real time.

## Physical Reality Check Plan

Do not proceed to model-payload physical prototyping. If the project continues, run a PRBS-only reality check on the Kenwood + We Are Rewind + USB dongle rig to determine whether the v3 channel-correction is too pessimistic. Generate two WAVs with the recommended modem and format: PRBS-only and framed random payload with UEP metadata. For each deck path, run at least 30 side-equivalent captures and measure raw BER, post-ECC BER, dropout rate/length distribution, timing drift, frame CRC failure rate, and full-payload hash success.

Decision criteria: revive model-payload tapes only if full-side hash success is `>=0.95`, measured burst length is closer to v2's 100 ms assumption than to the multi-second low-energy segments seen in public captures, and the hardened modem still shows at least `3 dB` SNR-equivalent margin. If those fail, stop cassette deployment and pivot to either a custom-trained sub-1.5 MB model or a less impaired medium.
