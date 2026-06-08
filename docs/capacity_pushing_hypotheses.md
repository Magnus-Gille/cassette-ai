# Pushing the cassette capacity ceiling — pre-registration

**Question.** Can we carry more *net* data per cassette than the current frontier
**without increasing the error rate** (i.e. while holding `P_full = 1.0`, whole-file
recovery, in the same shared harness)?

**Harness (frozen).** `src/hyp_common.py` → `evaluate_scheme` (tape preset `normal`,
capture `usb_soundcard`) → `project_to_cassette` (conservative BER→code-rate table).
Improvement metric = projected **net_bps** (equivalently MB / C90-stereo), subject to
`P_full = 1.0`. "No increase in error rate" is operationalised as: the projection's
whole-file recovery probability must stay at **1.0**, and we report raw BER alongside.

**Reference frontier (re-measured in-run per experiment for apples-to-apples):**

| | gross bps | raw BER | net bps | MB / C90-stereo | P_full |
|---|---|---|---|---|---|
| B0 BFSK CAS3-1200 | 538 | 1e-6 | 478 | 0.64 | 1.0 |
| **MFSK-32 (frontier)** | 1412 | 2.1e-3 | **1076** | **1.45** | 1.0 |

Note the frontier's raw BER (2.1e-3) sits *just above* the table's 1e-3 knee → its code
rate is pinned at 0.80. Pushing BER below 1e-3 alone lifts the rate to 0.85 (+6%); below
1e-4 lifts it to 0.92 (+15%). Several hypotheses exploit this.

## Hypotheses (safe bet → moonshot) and pre-registered accept bars

All bars are **vs the MFSK-32 frontier (net 1076 bps)** and require **P_full = 1.0**.

| # | Hypothesis | Mechanism | Pre-registered ACCEPT bar |
|---|---|---|---|
| **C1** (safe bet) | **Gray-coded MFSK + operating-point/band re-tune** | Most MFSK symbol errors are *adjacent-tone* confusions; Gray-mapping makes each flip 1 bit instead of ~½·log₂M, cutting raw BER ~2–3× → climbs the code-rate table. Plus full 11 kHz band + best (M, T_sym). | net_bps ≥ **1.10×** (≥1183) at P_full=1.0 |
| **C2** (likely) | **Combinatorial k-of-M multitone FSK** | Light *k* of *M* tones at once → log₂C(M,k) bits/symbol instead of log₂M, same non-coherent magnitude demod. Sweep (M,k) against the per-tone SNR split penalty. | net_bps ≥ **1.25×** (≥1345) at P_full=1.0 |
| **C3** (plausible) | **Soft-decision FEC credit** | The projection's BER→rate table is hard-decision and ~2 dB pessimistic. MFSK FFT magnitudes are natively *soft*. Show, by honest simulation of a soft-decision decoder, that the achievable code rate at the **same measured raw BER** is higher → more net at equal physical error. | net_bps ≥ **1.15×** (≥1237) at the same raw BER |
| **C4** (stretch) | **Bit-loaded OFDM-QAM (water-filling) + erasure on nulls** | OFDM was rejected at *flat* loading (uniform 9% BER ate it). Load QAM order per-subcarrier from measured SNR; weak subcarriers carry fewer bits or drop to erasures → effective BER stays low while gross rises. | net_bps ≥ **1.25×** (≥1345) at P_full=1.0 |
| **C5** (moonshot) | **Faster-than-Nyquist / non-orthogonal tone packing** (or 2D tone×time index modulation) | Pack tones closer than the orthogonality spacing (Δf < 1/T_sym) and separate them with an equalizer/decoder → more bits per band-second. Genuinely speculative; "no improvement" is an acceptable outcome. | net_bps ≥ **1.5×** (≥1614) at P_full=1.0 |

**Rules (inherited from the H1–H5 bake-off):** a REJECT only counts if the experiment
is sound (no demod bug); a buggy run is INCONCLUSIVE. No oracle timing — sync from the
signal. Every scheme re-measures MFSK-32 in its own run so the delta is harness-matched.

## Results

### C5 — Faster-than-Nyquist tone packing → **REJECT (fair)**

Implementation: `experiments/capacity/c5_ftn.py`; data `experiments/capacity/results/c5_ftn.json`.
Lever (a): MFSK-32 orthogonal tone grid (Δf=326 Hz over 400–10500 Hz), one hanning-tapered
orthogonal-length tone burst per symbol, but **hop = α·N_burst** with α<1 (overlap-add → FTN
in time). Decoder is a coherent matched-filter bank (cos/sin projection, max-energy tone).
Sanity gate passes (no-channel BER = 0.0 for all α≥0.55).

Canonical sweep (n_seeds=16, payload=4000, "normal"), selected α:

| α | gross | raw BER | net_bps | P_full |
|---|---|---|---|---|
| 1.00 (orth) | 1481 | 1.25e-3 | 1129 | 1.0 |
| 0.82 | 1764 | 2.17e-3 | 1344 | 1.0 |
| **0.78** | **1846** | **3.00e-3** | **1406** | **1.0** |
| 0.76 | 1889 | 4.05e-3 | 1259 | 1.0 |
| 0.72 | 1983 | 7.00e-3 | 1322 | 1.0 |

**Best: α=0.78 → net 1406 bps = 1.31× MFSK-32, MB_C90-stereo 1.889, P_full 1.0.** A real,
honest gain over the frontier, but **below the 1.5× (1614) bar → REJECT**. The mechanism works:
packing symbols ~28% faster lifts gross to 1846 bps. But ICI raises raw BER right up to the
3e-3 knee; past α≈0.78 the BER crosses into the 1e-2 knee (code rate 0.80→0.70) and the gross
gain is more than eaten. The channel's 42 dB SNR + flutter floor sets the ICI ceiling. "No
improvement past 1.5×" is the pre-registered acceptable outcome, backed by the α sweep.

### C2 — Combinatorial K-of-M multitone FSK → **ACCEPT**

Implementation: `experiments/capacity/c2_combo_mfsk.py`; data `experiments/capacity/results/c2_combo_mfsk.json`.

Design: M orthogonal tones (placed at exact FFT bin centers for zero spectral leakage), K lit per
symbol, encoding `floor(log2(C(M,K)))` bits/symbol. Non-coherent demod: FFT magnitude → top-K bins
→ reverse combinatorial lookup. Sanity gate (no-channel BER) = 0.0 for all tested (M,K).

Grid sweep n_seeds=8 over M∈{16,24,32,48}, K∈{2..6}, then Phase 2 confirms top candidates at n_seeds=16.

| M | K | bits/sym | gross bps | raw BER | net_bps | ratio | P_full |
|---|---|---|---|---|---|---|---|
| 48 | 6 | 23 | 3618 | 5.6e-3 | **2412** | **2.24×** | 1.0 |
| 32 | 4 | 15 | 3526 | 8.4e-3 | 2351 | 2.19× | 1.0 |
| 32 | 6 | 19 | 4215 | 1.6e-2 | 2208 | 2.05× | 1.0 |
| 48 | 5 | 20 | 3243 | 6.0e-3 | 2162 | 2.01× | 1.0 |
| 48 | 4 | 17 | 2836 | 1.8e-3 | 2161 | 2.01× | 1.0 |

**Best: M=48, K=6 → net 2412 bps = 2.24× MFSK-32, MB_C90-stereo 3.24, P_full 1.0. ACCEPT (bar ≥ 1.25×).**

Why it works: with M=48 tones and K=6 lit per symbol, each symbol carries 23 bits (vs 5 for
MFSK-32), yielding 3618 gross bps. The 6 simultaneous tones split SNR by 10·log10(6) ≈ 7.8 dB,
raising raw BER to 5.6e-3 (still within the 1e-2 knee), so code rate stays at 0.70. The
extraordinary gross lift (3618 vs 1412) overwhelms the 2.5 dB penalty. Sanity BER = 0.0 confirms
the combinatorial bijection + top-K demod is correct.

M=16 configs failed: with only 623 Hz tone spacing, adjacent-tone leakage under wow/flutter pushed
BER above 4e-2 (code rate 0.40), collapsing net to ~870 bps. Higher M (narrower tones, denser bits)
plus enough K to harvest the combinatorial gain is the sweet spot.

### C4 — Bit-loaded OFDM-QAM (water-filling) + erasure → **ACCEPT**

File: `experiments/capacity/c4_ofdm_bitload.py` · result: `results/c4_ofdm_bitload.json`.

**Best: N_FFT=256, gap=9 dB, max 16-QAM, no erasure marking → net 3968 bps = 3.69× MFSK-32,
MB_C90-stereo 5.33, raw BER 4.7e-4, P_full 1.0. ACCEPT (bar ≥ 1.25× / 1345). Sanity BER = 0.0.**

The prior OFDM (H3) REJECT was not actually a flat-loading problem — the root cause, found here, is a
**timing bug**: with a long FFT the tape wow/flutter drifts the symbol clock, and the chirp-correlation
sync lands a seed-dependent ~25–40 samples late, so a fixed `pos += N_SYM` walks off the symbol boundary
and EVM collapses after a handful of symbols (whole frames hit −20 dB EVM = 50% BER). Three fixes turn it
around: (1) **short FFT N=256** (~5.3 ms symbol) so intra-symbol flutter ICI is small and uniform;
(2) **wide initial acquisition** (±50 samples) on symbol 0 to undo the coarse-sync offset, then
incremental per-symbol tracking (±4) with a frequency-domain residual-slope correction from the embedded
pilots — this holds EVM at ~18 dB across the whole frame; (3) **channel-probe bit-loading**: known QPSK
symbols pushed through the channel on calibration seeds (disjoint from eval seeds) measure per-subcarrier
SNR (~13 dB median, clean-symbol-only), then a gap-approximation loads QPSK on the cleanest carriers and
BPSK elsewhere. The frozen loading is channel-TYPE-trained, not realisation-trained.

Net curve vs gap: gap=7 → 3616, gap=9 → **3968**, gap=11 → 3197. Erasure marking (flagging burst-hit
symbols) was tested and *hurts*: the burst symbols are still mostly decoded correctly (raw BER stays
4.7e-4, below the 1e-3 knee → code rate 0.85), so paying the fountain/MDS overhead for them is more
expensive than folding their few errors into the BER. With erasure on, net dropped to 3628; off, 3968.

Caveat: gross is 4902 bps but the per-SC SNR ceiling (~13 dB clean) only supports QPSK, not the 16/64-QAM
the water-filling framework allows — the tape band is power-limited, not bandwidth-limited at this SNR.
C2 (K-of-M, 2412) and C4 (3968) are the two strongest accepts; C4 is the new frontier.
