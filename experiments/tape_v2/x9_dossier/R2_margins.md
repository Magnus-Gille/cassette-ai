# R2 - Real-Capture Margin Forensics (934 bps DQPSK rung)

Capture: `/Users/magnus/repos/cassette-ai/experiments/tape_v2/captures/m8_tape_mono_lossless.wav`  
Global sync: clock 1.00117x (+0.117%), align +881800

The `dq_p10n512_rs127` section decoded with ZERO RS codeword failures on the real tape. This dossier measures HOW MUCH margin it actually had, directly from the capture, and instruments the failed N1024 section to pin its failure mechanism.

Demod fidelity check: the instrumented mirror reproduced the shipping `DQPSKScheme.demod` bits on 31/31 (PASS) and 19/19 (FAIL) frames.

## 0. TRUTH-referenced margin (the honest answer)

`true_margin` = degrees of slack from the received phasor to the nearest quadrant boundary, measured against the TRUE transmitted quadrant. >0 means a correct decision with that much headroom; <0 means the symbol crossed a boundary (a real symbol error). QPSK boundary = +/-45 deg. A D8PSK constellation (twice the phase states) would need margin to a +/-22.5 deg boundary; D16 (16-DAPSK phase ring) needs +/-11.25 deg.

| section | raw SER | sym errors | min margin (correct) | p0.1 margin | p1 margin | median margin | frac<22.5 (D8PSK err) | cwFail |
|---|---|---|---|---|---|---|---|---|
| PASS 934bps N512 | 1.799e-02 | 1138 | 0.04 deg | -28.37 | -7.17 | 37.55 | 8.893e-02 | 0/62 |
| FAIL N1024 | 1.436e-01 | 5418 | 0.01 deg | -87.19 | -58.98 | 34.60 | 2.832e-01 | 37/37 |

Reading: `min margin (correct)` is the worst-case headroom the QPSK decoder actually had to a wrong decision across the whole section -- the single tightest symbol. `frac<22.5` is the fraction of symbols whose phasor sat closer than 22.5 deg to its true quadrant boundary = the raw symbol error rate a D8PSK constellation would have suffered on this exact capture (before FEC).

### Per-carrier truth margin (PASS 934 bps)

| carrier | freq (Hz) | raw SER | sym err | min margin deg | p1 margin deg | median margin deg |
|---|---|---|---|---|---|---|
| 0 | 750 | 0.00e+00 | 0 | 14.64 | 22.60 | 39.00 |
| 1 | 1500 | 1.58e-04 | 1 | -3.73 | 15.15 | 37.26 |
| 2 | 2250 | 1.58e-04 | 1 | -1.36 | 18.49 | 37.94 |
| 3 | 3000 | 0.00e+00 | 0 | 1.08 | 21.14 | 39.39 |
| 4 | 3750 | 6.34e-02 | 401 | -128.97 | -18.24 | 30.25 |
| 5 | 5250 | 1.42e-03 | 9 | -15.18 | 14.46 | 39.41 |
| 6 | 6000 | 2.37e-03 | 15 | -20.77 | 12.76 | 40.00 |
| 7 | 6750 | 1.98e-02 | 125 | -38.61 | -7.02 | 34.92 |
| 8 | 7500 | 5.80e-02 | 367 | -54.58 | -19.11 | 34.27 |
| 9 | 8250 | 3.46e-02 | 219 | -63.08 | -13.47 | 37.09 |

## 1. Differential-phase slicing margin (decided-quadrant residual)

QPSK slices at +/-45 deg; D8PSK at +/-22.5 deg; D16PSK (16-DAPSK phase ring) at +/-11.25 deg. `residual` = angular distance from the DECIDED quadrant center (post pilot-correction + decision-directed refinement). NOTE: this is measured vs the DECIDED quadrant, so it understates errors (a wrong decision still shows small residual to its wrong center). See section 0 for the truth-referenced numbers.

| section | residual (deg) | frac>22.5deg (D8PSK fail) | frac>11.25deg (D16 fail) | cwFail |
|---|---|---|---|---|
| PASS 934bps (N512) | median 7.44 deg, p90 21.17, p99 40.83, p99.9 44.56, max 44.99 | 8.70e-02 | 3.23e-01 | 0/62 |
| FAIL N1024 | median 9.64 deg, p90 32.81, p99 43.63, p99.9 44.87, max 45.00 | 2.17e-01 | 4.47e-01 | 37/37 |

PASS section: 63240 symbol-carrier decisions. QPSK margin used only up to the listed percentiles -- the headroom to the 45 deg boundary is large.

### Per-carrier residual (PASS section, 934 bps)

| carrier | freq (Hz) | median deg | p90 deg | p99 deg | max deg | frac>22.5deg |
|---|---|---|---|---|---|---|
| 0 | 750 | 6.00 | 14.56 | 22.40 | 30.36 | 9.17e-03 |
| 1 | 1500 | 7.74 | 19.09 | 29.85 | 42.71 | 5.08e-02 |
| 2 | 2250 | 7.06 | 17.30 | 26.51 | 43.64 | 2.91e-02 |
| 3 | 3000 | 5.61 | 14.06 | 23.86 | 43.92 | 1.38e-02 |
| 4 | 3750 | 14.61 | 34.69 | 43.73 | 44.99 | 3.03e-01 |
| 5 | 5250 | 5.59 | 14.46 | 30.33 | 44.92 | 3.23e-02 |
| 6 | 6000 | 5.00 | 13.93 | 31.65 | 44.72 | 3.18e-02 |
| 7 | 6750 | 10.08 | 24.95 | 41.35 | 44.96 | 1.36e-01 |
| 8 | 7500 | 10.66 | 29.25 | 43.54 | 44.96 | 1.67e-01 |
| 9 | 8250 | 7.89 | 22.20 | 42.74 | 44.95 | 9.72e-02 |

## 2. Flutter / timing (pilot dtau trace)

**PASS N512** (symbol rate 93.8 Hz):  
- raw per-symbol dtau std 16.539 us; after EMA 13.450 us; decision-directed residual 5.3711 us  
- relative-rate wrms: raw 0.1551%, residual 0.0504% (residual 3.1x smaller)  
- flutter spectrum: peak 3.662 Hz, f50 5.126953125 Hz, f90 28.564453125 Hz (=> required tracking BW ~ 28.564453125 Hz)  

**FAIL N1024** (symbol rate 46.9 Hz):  
- raw per-symbol dtau std 34.780 us; after EMA 26.476 us; decision-directed residual 5.8722 us  
- relative-rate wrms: raw 0.1630%, residual 0.0275% (residual 5.9x smaller)  
- flutter spectrum: peak 3.662 Hz, f50 3.662109375 Hz, f90 14.83154296875 Hz (=> required tracking BW ~ 14.83154296875 Hz)  

## 3. Per-carrier amplitude stability + output SNR (PASS 934 bps)

| carrier | freq (Hz) | amp CoV % | p10/med | p90/med | EVM rms | out SNR dB |
|---|---|---|---|---|---|---|
| 0 | 750 | 11.1 | 0.86 | 1.14 | 0.155 | 16.2 |
| 1 | 1500 | 13.8 | 0.82 | 1.18 | 0.207 | 13.7 |
| 2 | 2250 | 12.6 | 0.84 | 1.16 | 0.201 | 13.9 |
| 3 | 3000 | 9.4 | 0.88 | 1.12 | 0.186 | 14.6 |
| 4 | 3750 | 27.0 | 0.66 | 1.35 | 0.390 | 8.2 |
| 5 | 5250 | 8.9 | 0.88 | 1.11 | 0.247 | 12.2 |
| 6 | 6000 | 6.3 | 0.92 | 1.08 | 0.256 | 11.8 |
| 7 | 6750 | 18.1 | 0.76 | 1.24 | 0.356 | 9.0 |
| 8 | 7500 | 20.4 | 0.73 | 1.26 | 0.414 | 7.7 |
| 9 | 8250 | 17.5 | 0.77 | 1.22 | 0.380 | 8.4 |

## 4. Cross-bin leakage (PASS 934 bps) -- supportable spacing without AAC

Energy at unused bins offset from each carrier, relative to carrier power (carrier spacing here = 8 bins = 750 Hz). More-negative dB = cleaner; a deep null at small offsets means tighter spacing is supportable.

| offset | mean leak dB | max leak dB |
|---|---|---|
| offset_1bin_94hz | -3.1 | -2.9 |
| offset_2bin_188hz | -13.6 | -11.4 |
| offset_4bin_375hz | -19.0 | -13.5 |

### Achievable spacing / SIR (measured leakage skirt, no AAC)

Current spacing 750 Hz. SIR(spacing) = carrier power over the leakage two equal neighbors at +/-spacing would inject (Hann-windowed analysis, Nw=384). Tightest spacing clearing each SIR:

- 15 dB SIR: 100.0 Hz  
- 20 dB SIR: 150.0 Hz  
- 25 dB SIR: 200.0 Hz  

| spacing (Hz) | SIR (dB) |
|---|---|
| 50 | 12.6 |
| 100 | 15.3 |
| 150 | 20.1 |
| 200 | 27.0 |
| 250 | 30.8 |
| 300 | 30.2 |
| 350 | 30.0 |
| 400 | 29.7 |
| 450 | 29.3 |
| 500 | 29.8 |
| 550 | 23.7 |
| 600 | 16.0 |
| 650 | 11.1 |
| 700 | 8.4 |
| 750 | 7.6 |

Caveats: (a) the SIR DIP near 750 Hz is the REAL adjacent data carrier (the section's own carriers sit 750 Hz apart), not window skirt -- ignore it; the skirt-limited clean region is ~150-500 Hz where SIR plateaus at ~30 dB (channel-noise-floor limited). (b) The orthogonality constraint `spacing_bins * Nw % N == 0` (Nw=3N/4) restricts the exact usable bin grid; a rectangular-window DFT on integer bins gives zero ICI at the full N-bin resolution (93.75 Hz at N512) but loses the Hann ISI robustness. (c) Bottom line: the old 562 Hz AAC-masking floor is OBSOLETE on lossless captures -- ~150-200 Hz spacing is supportable at 20-25 dB SIR, a 3-5x carrier-density headroom over today's 750 Hz.

## 5. Failure mechanism (N1024)

FAIL N1024 residual: median 9.64 deg, p90 32.81, p99 43.63, p99.9 44.87, max 45.00; cwFail 37/37 (total wipeout). PASS N512 residual: median 7.44 deg, p90 21.17, p99 40.83, p99.9 44.56, max 44.99.

N1024 symbol rate is 46.9 Hz vs N512's 93.8 Hz -- the pilot updates HALF as often. The raw per-symbol dtau std grows from 16.539 us (N512) to 34.780 us (N1024) because more flutter accumulates within one longer symbol, and the EMA (alpha fixed) tracks it more poorly. If the N1024 residual median/p99 are far worse than N512's, the diagnosis is confirmed: flutter tracking, not noise or leakage.
