# Cassette AI Viability Report v2

## Recommendation

Recommended tuple: `16QAM @ 7200 sym/s`, `hamming74` ECC, interleaving depth `64`, `TinyStories-1M INT8`.

Raw modulation bitrate: `28800 bit/s`. Post-ECC payload bitrate: `16457.14 bit/s`. Final payload per C-60 side: `3.703 MB`.

This replaces the v1 contradiction. The old `16QAM 9600 none I=16` number was only a BER-screen maximum and did not have acceptable full-side clean-decode probability under bursts. The old `16QAM 9600 Hamming I=1` tuple ignored burst resilience. Under v2's realistic burst condition (0.1/s, 100 ms), the recommended tuple is the fastest search-space point that meets the real-LM BER threshold and `>=0.95` clean-decode rate.

## North-Star Answer

The largest real-vetted model that fits is `TinyStories-1M INT8`, about `1.00 MB`. `TinyStories-1M INT4` is not functional even at the lowest tested BER (`1e-7`) with this v2 quantizer, so v1's INT4 conclusion is invalid. The revised answer is viable only for INT8 in this search space: `1.00 MB` fits inside `3.703 MB/side`; no larger real model was tested in v2.

## Fix 1 - Channel Stochasticity

`RESULTS/data/channel_stochasticity_audit.csv` has 10 realistic-channel seeds. The minimum pairwise sample RMS difference is non-zero (`0.068154`), so realizations are not identical. The audit now reports additive-noise SNR from the generated noise component instead of incorrectly counting wow/flutter phase warp as noise. `RESULTS/plots/channel_seed_variance.png` overlays three seed spectrogram contours.

## Fix 2 - Impairment Calibration

`RESULTS/data/impairment_sweep.csv` sweeps SNR 25-50 dB and W&F 0.04-0.5% using the v1 tuple. Clean-decode rate ranges from `0.000` to `1.000`, so impairments are active. In this grid, minimum SNR required to meet each clean-decode threshold is: 0.99 -> 0.04% W&F needs >= 35 dB; 0.07% W&F needs >= 40 dB; 0.12% W&F not met by 50 dB; 0.25% W&F not met by 50 dB; 0.5% W&F not met by 50 dB; 0.95 -> 0.04% W&F needs >= 35 dB; 0.07% W&F needs >= 40 dB; 0.12% W&F needs >= 50 dB; 0.25% W&F not met by 50 dB; 0.5% W&F not met by 50 dB; 0.5 -> 0.04% W&F needs >= 35 dB; 0.07% W&F needs >= 40 dB; 0.12% W&F needs >= 50 dB; 0.25% W&F not met by 50 dB; 0.5% W&F not met by 50 dB. See `RESULTS/plots/clean_decode_vs_impairment.png`.

## Fix 3 - Real Model BER Tolerance

`RESULTS/data/model_ber_threshold_real.csv` contains actual `roneneldan/TinyStories-1M` inference for INT8 and INT4 over six BER levels and five trials each. Baseline holdout perplexity is `33.419`. INT8 remains within 2x perplexity through `1e-05`. INT4 has no passing BER in the tested range; at `1e-7` its median perplexity ratio is already above 2x. Compared with v1's surrogate INT4 threshold of `3.0e-06`, the real INT4 threshold is at least `>30x` lower and effectively absent in the tested range, so all downstream v2 recommendations use the real INT8 threshold `1e-05` instead.

## Fix 4 - Bursts And Interleaving

`RESULTS/data/burst_interleaving.csv` sweeps dropout bursts from 10-500 ms and 0.1-2/s across interleaving depths 1, 4, 16, and 64. Interleaving materially changes clean-decode rate: for the realistic burst condition (0.1/s, 100 ms), depth `64` is best in the v1 tuple sweep with clean-decode `0.925`. This reconciles the v1 depth-1 recommendation: depth 1 was only optimal when burst errors were not modeled. See `RESULTS/plots/clean_decode_vs_interleaving_under_bursts.png`.

## V2 Monte Carlo

`RESULTS/data/pipeline_monte_carlo_v2.csv` contains 80 end-to-end Monte Carlo runs under realistic channel plus bursts, using the real INT8 BER threshold. Clean-decode rate is `0.963`. Usable payload is `3.564 MB/side` with empirical 95% CI `[0.000, 3.703] MB`; the interval is non-degenerate because failed full-side decodes are counted as zero usable payload.

## What Changed From V1

1. Channel stochasticity is now audited directly; seed realizations differ and additive SNR measurement no longer confuses timebase warp with noise.
2. Impairment calibration now proves the modem/decode model degrades across SNR and W&F instead of staying at 1.000 everywhere.
3. Real TinyStories-1M inference replaced the surrogate BER threshold. This invalidated INT4 and moved the viable recommendation to INT8.
4. Bursty dropouts made interleaving matter. The recommendation changed from depth 1 to depth 64 under the realistic burst condition.

## Residual Risks

This remains simulation-only. The largest remaining risks are real cassette burst statistics, deck AGC/noise-reduction behavior, azimuth/head wear, and the simplicity of the prototype modem/ECC abstraction. The next physical step is still a PRBS WAV through an actual consumer deck before putting model bytes on tape.
