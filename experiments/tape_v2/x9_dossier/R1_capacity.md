# R1 — First-Principles Capacity & Engineering Envelope (master9)

Derived entirely from MEASURED channel params + the m8 real-tape decode (934 bps record). Seed 20260610.

## Measured anchors (m8 tape, 2026-06-10)

- SNR median **38.3 dB** (p10 33.1 dB)
- Noise floor **-55.6 dBFS**
- Flutter **0.41% wrms**, clock offset +0.117%
- Reverb tail tau **7.9 ms**, band 300-11000 Hz
- H(f) shape from master3 sounder, median-anchored to m8 (shift -2.25 dB)

## Part 1 — Per-band SNR, Shannon capacity, bit-loading

Formulas: `gamma_k=10^(SNR_k/10)`; Shannon `c_k=log2(1+gamma_k)` bits/s/Hz; discrete loading `b_k=floor(log2(1+gamma_k/Gamma))` with gap Gamma (0 dB Shannon, 6 dB realistic uncoded-QAM+RS, 9 dB conservative).

- **Shannon capacity, full 300-11000 Hz band: 82847 bps** (unachievable upper bound; assumes continuous water-filling over the sounder grid).
- Gross bit rate of an idealized Nyquist-spaced OFDM (one subcarrier per 104 Hz, no overhead):
  - gap 0 dB (Shannon-tight int loading): 53248 bps
  - **gap 6 dB (realistic): 52312 bps**
  - gap 9 dB (conservative): 50960 bps
- Median bits/subcarrier: gap0 8, gap6 8, gap9 8
- Water-filling: 64/64 subcarriers active, power spread only 0.0 dB -> **near-degenerate; use every usable subcarrier at ~equal power.**

Per-band profile:

| Band (Hz) | mean SNR (dB) | min SNR | mean H (dB) | Shannon b/Hz | bits@gap6 | bits@gap9 |
|---|---|---|---|---|---|---|
| 300-750 | 39.3 | 33.4 | -2.5 | 13.04 | 8.0 | 8.0 |
| 750-1500 | 32.1 | 24.5 | -9.2 | 10.66 | 7.5 | 6.9 |
| 1500-3000 | 36.2 | 29.1 | -7.3 | 12.01 | 7.8 | 7.6 |
| 3000-4500 | 40.8 | 28.8 | -22.5 | 13.56 | 7.9 | 7.7 |
| 4500-6000 | 43.5 | 35.9 | -20.9 | 14.44 | 8.0 | 8.0 |
| 6000-7500 | 40.5 | 39.1 | -25.2 | 13.46 | 8.0 | 8.0 |
| 7500-9000 | 36.4 | 36.2 | -27.2 | 12.10 | 8.0 | 8.0 |
| 9000-11000 | 35.5 | 30.4 | -27.1 | 11.78 | 8.0 | 7.7 |

## Part 2 — Flutter -> residual phase noise, constellation closure (ANCHOR-CALIBRATED)

**Corrected physics:** flutter is a COMMON TIMING error; the pilot carrier removes 2*pi*f_k*dtau from every carrier, so a DQPSK slicer sees only the RESIDUAL timing jitter, not raw flutter. We calibrate residual phase to the PROVEN m8 record instead of guessing the flutter PSD shape.

- Anchor: DQPSK closes to 9000 Hz on the m8 tape (0/62 RS codeword failures) => assume sigma_phi(9 kHz) = 10 deg.
- => residual timing jitter sigma_tau_res = 3.09 us (0.148 samples) at N=512.
- Untracked differential timing across T ~40us (=>~130deg@9k); pilot suppresses to ~3us (=>10deg@9k), a ~13x (~22dB) reduction.
- **Load-bearing relation:** sigma_phi(f) = 10 deg x (f/9000) x (T/T512) x sqrt(BL_ema/BL). Linear in carrier freq AND symbol length.

**Independent validation (N=1024 failure):** model predicts sigma_phi(9k) goes 10.0 deg (N512, DQPSK margin +3.5 dB) -> 20.0 deg (N1024, margin -2.5 dB). The collapsed N1024 margin reproduces the OBSERVED real-tape N1024 failure.

### Closure table, N=512, anchor-calibrated; criterion 3-sigma <= theta_min

Differential schemes use the EMA (current single-pilot) residual; coherent use a tighter multi-pilot PLL at BL=20 Hz. Margin dB (positive = closes; x = fails).

| Carrier | sigma_EMA (deg) | sigma_PLL20 (deg) | DBPSK | DQPSK | D8PSK | coh-QPSK | coh-16QAM |
|---|---|---|---|---|---|---|---|
| 750 | 0.83 | 0.42 | +31.1 | +25.1 | +19.1 | +31.1 | +23.4 |
| 1500 | 1.67 | 0.83 | +25.1 | +19.1 | +13.1 | +25.1 | +17.4 |
| 3000 | 3.33 | 1.67 | +19.1 | +13.1 | +7.0 | +19.1 | +11.3 |
| 4500 | 5.00 | 2.50 | +15.6 | +9.5 | +3.5 | +15.6 | +7.8 |
| 6000 | 6.67 | 3.33 | +13.1 | +7.0 | +1.0 | +13.1 | +5.3 |
| 7500 | 8.33 | 4.17 | +11.1 | +5.1 | -0.9x | +11.1 | +3.4 |
| 9000 | 10.00 | 5.00 | +9.5 | +3.5 | -2.5x | +9.5 | +1.8 |

Highest carrier (Hz) that closes per constellation (N=512):

| DBPSK | DQPSK | D8PSK | 16-DAPSK(phase) | coh-QPSK | coh-16QAM |
|---|---|---|---|---|---|
| 11000 | 11000 | 6750 | 6750 | 11000 | 11000 |

(Margin = 20log10(theta_min/(3*sigma)). Coherent rows also need amplitude stability — see caveats.)

## Part 3 — ICI for dense packing + reverb ISI

N=512, bin width 93.75 Hz, reverb tau 7.9 ms, flutter residual frac 0.15.

Flutter ICI: offset `eps = f*sigma_residual/Df` bins; ICI power `~(pi*eps)^2/3` (rect window), Hann adjacent ~0.25x. Reverb ISI: ANCHORED so the proven no-CP config sits at 18 dB SIR, scaling with the guard as `exp(-guard/tau)`; a CP adds to the existing N/8 internal guard.

### Flutter ICI (residual flutter, Hann window), SIR in dB at worst carriers

| Spacing | 1500 Hz | 3000 Hz | 6000 Hz | 9000 Hz |
|---|---|---|---|---|
| 94 Hz (1bin) | 41 | 35 | 29 | 25 |
| 188 Hz (2bin) | 47 | 41 | 35 | 31 |
| 375 Hz (4bin) | 53 | 47 | 41 | 37 |
| 750 Hz (8bin) | 59 | 53 | 47 | 43 |

### Reverb ISI vs cyclic prefix

| CP | guard (ms) | tail past guard | ISI SIR (dB) | CP overhead |
|---|---|---|---|---|
| CP=0.0ms | 1.3 | 0.844 | 18.0 | 0.0% |
| CP=2.7ms | 4.0 | 0.599 | 19.5 | 20.2% |
| CP=5.3ms | 6.6 | 0.430 | 20.9 | 33.2% |

### Densest honest spacing + constellation cap per receiver tier

| Tier | need SIR (dB) | CP (ms) | reverb-ISI floor (dB) | densest spacing (ICI) | limiter |
|---|---|---|---|---|---|
| tier1_simple(DQPSK,no-CP,1pilot) | 18 | 0.0 | 18.0 | 2 bins (188 Hz) | OK (margin-limited) |
| tier2_mid(D8PSK,CP2.7,multi-pilot) | 23 | 2.7 | 19.5 | 4 bins (375 Hz) | reverb-ISI floor |
| tier3_adv(16QAM,CP5.3,PLL+eq) | 26 | 5.3 | 20.9 | 4 bins (375 Hz) | reverb-ISI floor |

**Finding:** Flutter ICI is negligible at all spacings >=1 bin (residual-timing-driven wobble is small after pilot tracking). The reverb-ISI FLOOR (~18 dB no-CP, ~21 dB with 5.3ms CP) is the real cap on constellation ORDER: it comfortably clears DQPSK (need 18 dB) but NOT a 6dB-margin 16QAM (need 26 dB) even with a CP. => denser SPACING is cheap; higher ORDER is the expensive axis and needs a CP + the reverb floor lifted (shorter acoustic path / line-in).

## Part 4 — PAPR + tape saturation backoff

PAPR = 10log10(max|x|^2 / mean|x|^2), measured on x4-oversampled multitone. Random p99.9 ~ 10log10(N)+8 dB; Schroeder phi_k=-pi*k^2/N and Newman give low-crest deterministic multitone.

| #carriers | PAPR random (mean) | random p99.9 | Schroeder | Newman |
|---|---|---|---|---|
| 1 | 3.0 | 3.0 | 3.0 | 3.0 |
| 2 | 5.9 | 6.0 | 5.9 | 5.9 |
| 4 | 7.2 | 9.0 | 6.0 | 6.0 |
| 8 | 8.2 | 10.7 | 5.5 | 5.6 |
| 11 | 8.7 | 11.3 | 5.7 | 5.7 |
| 16 | 9.0 | 12.2 | 5.6 | 5.6 |
| 32 | 9.8 | 12.4 | 5.6 | 5.6 |
| 64 | 10.3 | 12.8 | 5.4 | 5.6 |
| 128 | 10.7 | 13.0 | 5.5 | 5.4 |

m8 SNR median 38.3 dB; even 10-20 dB of PAPR backoff leaves >18 dB SNR => noise is NOT the saturation limiter. The real ceiling is tape IMD/saturation when the PEAK clips at record level >7. Schroeder/Newman phasing keeps PAPR ~3-5 dB regardless of carrier count, removing the per-doubling penalty; STRONGLY recommended for master9 multitone.

## Part 5 — Candidate operating points for master9

net_bps_proj = gross_bps x RS code rate (k/255). gross from carriers x bits/sym / symbol-period.

| ID | PHY | carriers | spacing | N (CP) | constellation | RS | gross bps | **net bps** | risk |
|---|---|---|---|---|---|---|---|---|---|
| C0-proven | DQPSK | 10 | 750Hz/8b | 512 | DQPSK (2 b/carrier) | RS(255,127) | 1875 | **934** | PROVEN |
| C1-widen | DQPSK | 12 | 750Hz/8b | 512 | DQPSK | RS(255,159) | 2250 | **1403** | SAFE |
| C2-dense4 | DQPSK | 22 | 375Hz/4b | 512 | DQPSK | RS(255,159) | 4125 | **2572** | MEDIUM |
| C3-d8psk | D8PSK | 10 | 750Hz/8b | 512 | D8PSK (3 b/carrier) | RS(255,159) | 2812 | **1754** | MEDIUM |
| C4-d8psk-dense | D8PSK | 22 | 375Hz/4b | 512 | D8PSK | RS(255,127) | 6188 | **3858** | HIGH |
| C5-16qam | coh-16QAM | 10 | 750Hz/8b | 512 | 16QAM (4 b/carrier) | RS(255,127) | 3750 | **1868** | HIGH |
| C6-cp-d8psk | D8PSK+CP | 20 | 375Hz/6b | 768 (2.7ms) | D8PSK | RS(255,159) | 3209 | **2001** | MEDIUM-HIGH |
| C7-moonshot | coh-16QAM+CP | 40 | 375Hz/4b | 512 (2.7ms) | 16QAM | RS(255,127) | 15000 | **7471** | MOONSHOT |
| C8-bitloaded | bit-loaded OFDM | 12 | 750Hz/8b | 512 | 16QAM(LF)/D8PSK(MF)/DQPSK(HF) | RS(255,159) | 3375 | **2104** | MEDIUM-HIGH |

### Rationale per candidate

- **C0-proven** (934 net bps, PROVEN): The current record. Anchor for all deltas.
- **C1-widen** (1403 net bps, SAFE): Add 2 data carriers (proven SIR up to 9kHz) and lighten RS from k=127->159 since the record decoded with 0 cw failures => large unused margin. Honest extension of the proven point.
- **C2-dense4** (2572 net bps, MEDIUM): Halve the spacing to 375 Hz (lossless capture removes the old 562 Hz AAC-skirt floor). ~22 carriers across 750-9000 Hz. Flutter ICI at 9kHz residual is the risk; needs the multi-pilot timing front-end. ~2x carriers vs proven.
- **C3-d8psk** (1754 net bps, MEDIUM): Same proven grid, 1.5x bits/carrier via D8PSK. Part-2 closure: D8PSK (22.5deg) closes under EMA pilot up to mid-band but margin thins at HF; restrict to 750-6000Hz or add multi-pilot.
- **C4-d8psk-dense** (3858 net bps, HIGH): Stack C2 and C3. Heavy RS (k=127) to absorb the higher raw BER. Only attempt with the multi-pilot PLL + per-carrier eq.
- **C5-16qam** (1868 net bps, HIGH): 2x bits/carrier vs proven DQPSK. Part-2: 16QAM (18.4deg outer) closes only with a PLL at BL~5Hz and only below ~6kHz; amplitude fading (flutter AM + HF rolloff) is the extra risk vs PSK. Needs per-carrier amplitude eq from pilots.
- **C6-cp-d8psk** (2001 net bps, MEDIUM-HIGH): Add a 2.7ms CP to kill reverb ISI, enabling denser spacing, but keep N modest (768<1024) so pilot updates stay fast enough for real flutter. The N=1024 failure is the cautionary precedent.
- **C7-moonshot** (7471 net bps, MOONSHOT): Theoretical ceiling probe. ~40 carriers x 4 bits over 375Hz spacing. Realistically needs soft-decision LDPC, not RS, and a full coherent OFDM receiver. Listed to bound the envelope.
- **C8-bitloaded** (2104 net bps, MEDIUM-HIGH): Directly applies Part-1 bit-loading + Part-2 per-carrier closure: dense constellations only where flutter phase-jitter is small (low f), robust DQPSK where it is large (high f). Best expected-value rung above the proven point.

### Ranked by projected net bps

1. C7-moonshot: **7471** net bps (gross 15000) — MOONSHOT
1. C4-d8psk-dense: **3858** net bps (gross 6188) — HIGH
1. C2-dense4: **2572** net bps (gross 4125) — MEDIUM
1. C8-bitloaded: **2104** net bps (gross 3375) — MEDIUM-HIGH
1. C6-cp-d8psk: **2001** net bps (gross 3209) — MEDIUM-HIGH
1. C5-16qam: **1868** net bps (gross 3750) — HIGH
1. C3-d8psk: **1754** net bps (gross 2812) — MEDIUM
1. C1-widen: **1403** net bps (gross 2250) — SAFE
1. C0-proven: **934** net bps (gross 1875) — PROVEN

## What the measured data CANNOT answer (explicit)

- **Flutter PSD shape / corner f_c** is not directly measured (only its WRMS). Phase-jitter numbers are reported across f_c in {3,6,10} Hz; the real spectrum could concentrate power differently. A pilot-tone instantaneous-frequency PSD from the m8 capture would resolve this.
- **Tape saturation / IMD curve** (the record-level>7 ceiling) is a qualitative SOP, not a measured AM/AM AM/PM curve. PAPR backoff numbers assume a hard peak clip; the true soft-saturation knee is unknown.
- **Frequency-selective stationary nulls vs sounder artifacts:** the master3 H(f) had -49 dB spikes that we SMOOTHED as artifacts. If any are real stationary nulls they would kill specific carriers; a repeated sounder would disambiguate.
- **Coherent-receiver amplitude stability** (needed for 16QAM): flutter AM and HF rolloff drift are not separately characterized; 16QAM closure assumes per-carrier pilot amplitude eq works as well as phase eq, which is unproven on this channel.
- The **N=1024 real-tape FAILURE** is the strongest empirical caution: it says long symbols lose to real flutter despite better sim ISI. Any N>512 candidate (C6) inherits that risk and is graded accordingly.