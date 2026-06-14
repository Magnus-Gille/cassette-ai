# Pushing the cassette capacity ceiling — adjudicated results

**Status:** Adjudicated against the pre-registration in
`docs/capacity_pushing_hypotheses.md`. Bars were fixed BEFORE results.
**Reference frontier (re-measured in every run, harness-matched):** MFSK-32 —
gross 1412 bps, raw BER 2.02e-3, **net 1075.6 bps**, MB/C90-stereo 1.445,
P_full 1.0. B0 baseline net 472.1 bps.

All five experiments were verified independently: each re-measures MFSK-32 in
its own run to net 1075.6 (matches the frontier), each passes a zero-channel
loopback sanity gate (BER = 0.0), each syncs from the signal via
`find_preamble`/chirp correlation (no oracle timing), and all share the frozen
conservative BER→code-rate projection table in `src/hyp_common.py`. The C4
bit-loading table is trained on calibration seeds 40–51, disjoint from eval
seeds 0–15 — no realisation leakage. **No demod bugs were found; no result is
marked INCONCLUSIVE.**

## 1. Scorecard

| # | Hypothesis | Mechanism | Bar (×) | Net bps | Ratio | Raw BER | P_full | Verdict |
|---|---|---|---|---|---|---|---|---|
| C1 | Gray-coded MFSK + band re-tune | Gray maps adjacent-tone errors to 1-bit flips; M=16 over 400–7000 Hz widens Δf | ≥1.10 (1183) | **1209.0** | 1.124 | 2.97e-3 | 1.0 | **ACCEPT** |
| C2 | Combinatorial K-of-M multitone FSK | Light K of M tones → log₂C(M,K) bits/sym; M=48, K=6 → 23 bits/sym | ≥1.25 (1345) | **2412.2** | 2.243 | 5.56e-3 | 1.0 | **ACCEPT** |
| C3 | Soft-decision FEC credit | Soft-Viterbi LLRs from FFT bins → higher achievable code rate at same raw BER | ≥1.15 (1237) | 1080.5 | 1.005 | 2.02e-3 | 1.0 | **REJECT (fair)** |
| C4 | Bit-loaded OFDM-QAM + erasure | Per-SC water-filling QAM from probed SNR; QPSK on clean carriers, BPSK elsewhere | ≥1.25 (1345) | **3968.3** | 3.689 | 4.69e-4 | 1.0 | **ACCEPT** |
| C5 | Faster-than-Nyquist tone packing | Hop = α·N_burst (α=0.78), coherent matched-filter bank | ≥1.50 (1614) | 1406.2 | 1.307 | 3.00e-3 | 1.0 | **REJECT (fair)** |

## 2. Per-hypothesis findings

**C1 — Gray-coded MFSK + band re-tune → ACCEPT.** The Gray-coding lever is real
but small: on M=32 it cut raw BER 2.02e-3→1.58e-3, yet both sit in the same 0.80
code-rate bucket, so net stays flat at 1076. The actual win is operating-point
tuning: M=16 over 400–7000 Hz gives Δf=440 Hz (vs 309 Hz for M=32 over the full
band), and the wider tone spacing tolerates a 12% higher gross (1587 bps) while
holding BER at 2.97e-3 (0.80 bucket). Net 1209 = 1.12× clears the 1.10× bar.
*Caveat:* BER sits just below the 3e-3 knee; seeds 8/11 saw 1–1.7% BER (burst
dropouts), so variance is moderate, but the mean holds P_full=1.0.

**C2 — Combinatorial K-of-M multitone FSK → ACCEPT.** Placing all M tones at
exact FFT bin centres eliminates inter-tone leakage, making top-K magnitude
detection lossless (sanity BER 0.0 for every (M,K)). M=48/K=6 carries 23
bits/symbol vs 5 for MFSK-32, lifting gross to 3618 bps. The 6 simultaneous
tones split SNR by ~7.8 dB, raising raw BER to 5.6e-3 — still inside the 1e-2
knee (rate 0.70) — so the huge gross gain dominates the SNR penalty. Net 2412 =
2.24× clears the 1.25× bar. M=16 configs collapsed (BER>4e-2) as wider spacing
amplified wow/flutter. Sound, no bug.

**C3 — Soft-decision FEC credit → REJECT (fair).** The soft K=7 convolutional
Viterbi (log-sum-exp LLRs from FFT bins) only reaches P_full=1.0 at R=3/4,
giving net 1081 vs MFSK-32's 1076 — a 0.5% gain, far below the 1.15× bar. R=5/6
catastrophically fails on seed 9 (post-FEC BER 0.324) and R=7/8 fails 4/16 seeds.
Root cause is the channel, not a bug: cassette burst dropouts (6 ms × ~0.3/s)
cluster within the short constraint-length window, defeating high-rate codes; the
FEC's extra MFSK symbols (more audio) cost more than the ~1 dB soft-decoding gain
buys. A fair reject — the channel's burst structure forbids the gain.

**C4 — Bit-loaded OFDM-QAM + erasure → ACCEPT (new frontier).** The prior OFDM
H3 reject was a *timing* bug, not flat-loading: a long FFT + wow/flutter clock
drift + seed-dependent ~25–40-sample sync offset walked fixed symbol windows
off-boundary, collapsing whole frames to ~50% BER. Fixes: short FFT N=256, wide
±50-sample acquisition + incremental per-symbol tracking with frequency-domain
pilot-slope correction (EVM held ~18 dB), and channel-probe bit-loading from
disjoint calibration seeds. Result: gross 4902, raw BER 4.69e-4 (below the 1e-3
knee → 0.85 bucket), net 3968 = 3.69×. Erasure marking was tested and *hurt*
(net 3628 vs 3968) — burst symbols still decode, so the fountain overhead isn't
worth it. *Caveat:* the ~13 dB clean SNR is power-limited and only supports QPSK;
gross is bounded by band SNR, not the 16/64-QAM the framework allows. At 12% of
the single-channel Shannon bound for this band/SNR — plausible, not over-claimed.

**C5 — Faster-than-Nyquist tone packing → REJECT (fair).** Compressing the
symbol hop to α=0.78 of the orthogonal period genuinely lifts gross 1481→1846
bps while the coherent matched-filter bank still separates tones (sanity BER 0.0
at all α). Best net 1406 = 1.31×, P_full 1.0 — a real gain, but below the 1.5×
(1614) moonshot bar. Inter-carrier interference pins raw BER at the 3e-3 knee at
α=0.78; packing tighter (α≤0.76) crosses into the 1e-2 knee and the gross gain is
more than eaten. The 42 dB SNR + flutter floor sets the ICI ceiling. "No
improvement past 1.5×" is the pre-registered acceptable null — a fair reject with
a documented sub-threshold gain.

## 3. Bottom line

**New best: C4 bit-loaded OFDM-QAM — net 3968.3 bps, MB/C90-stereo 5.33,
P_full 1.0. That is 3.69× the MFSK-32 frontier (1075.6 → 3968.3 bps) and 8.41×
the B0 baseline.** Per cassette (C90 stereo) capacity rises from 1.445 MB to
**5.33 MB**.

**Ranked accepts:** C4 (3.69×) > C2 (2.24×) > C1 (1.12×).

**Do the gains stack? Mostly NO — they are competing PHYs, not orthogonal
levers.** C1 (single-tone MFSK with Gray), C2 (multitone combinatorial FSK), and
C4 (OFDM-QAM) are three mutually exclusive physical layers; you ship one, not a
product of all three. There is no measured stack, and none is claimed.

The only genuinely orthogonal lever is C3 (soft-FEC code-rate credit), which —
had it worked — would multiply *any* PHY's net by a rate-bucket ratio. It did
NOT clear its bar on this burst channel, so we do not stack it. For reference
only, an *unmeasured, optimistic* projection of a working soft-FEC credit on C4
(lifting the 0.85→0.92 bucket) would give ~4295 bps; this is a **projection, not
a measurement**, and C3's actual result argues against it on this channel.

**Honest conclusion: the new frontier is a single PHY (C4), 3.69× over MFSK-32.
The improvement is real and bug-checked, not a stacking artefact.**

## 4. What would move the needle next (grounded in the data)

- **Raise the clean SNR to unlock higher-order QAM.** C4 is power-limited at
  ~13 dB → QPSK ceiling, only 12% of Shannon. Better tape/bias/pre-emphasis or
  per-SC power-loading toward 18–24 dB would admit 16/64-QAM and lift gross well
  past 4902. This is the single biggest lever the data points to.
- **Attack burst dropouts directly** (interleaving + erasure-aware outer code).
  Bursts are what killed C3 and capped C1's variance. A deep block interleaver
  ahead of a long-constraint or LDPC outer code would let soft-FEC's ~1 dB
  AWGN gain actually convert to a code-rate-bucket jump.
- **Combine C4's OFDM bit-loading with C2's combinatorial idea per-subcarrier**
  is NOT free (both are already SNR-bound), but index-modulation across active
  subcarriers could add a few bits/symbol cheaply — worth a measured probe.
- **Push C4 N_FFT / pilot density tradeoff** — 13 pilots of 52 SCs is heavy;
  if tracking can hold with fewer pilots, those SCs carry data.

## 5. Caveats

- **Simulation only.** All results come from `cs.full_chain` (tape preset
  `normal`, capture `usb_soundcard`) — a modelled wow/flutter + burst-dropout +
  AWGN channel, not a physical deck. Real-tape numbers may differ.
- **Conservative projection table.** The BER→code-rate map in `hyp_common.py`
  leaves margin below the Shannon hard-decision limit, so net_bps is
  deliberately under-claimed; P_full=1.0 is a step model that bakes in the
  margin rather than integrating a fragile tail.
- **C4 is power-limited, not bandwidth-limited** at this SNR; its gross is
  bounded by band SNR, and the QPSK ceiling means the water-filling framework is
  under-utilised.
- **No measured stacking.** The 3.69× frontier is one PHY. Any multiplicative
  combination across C1/C2/C4 is physically meaningless; the only stackable lever
  (C3) failed its bar on this burst channel.
- **C1 variance.** C1's BER sits just under the 3e-3 knee with two outlier seeds;
  it clears the bar on the mean but has the least margin of the three accepts.
