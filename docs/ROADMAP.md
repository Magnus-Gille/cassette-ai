# Cassette-AI — capacity roadmap & remaining research

_Last updated 2026-06-08._

## Where we are vs. the ceiling

The hard wall is Shannon: `C = B·log₂(1 + SNR)`. Against real tape numbers we are
currently at **1–3 % of Shannon** — the gap is flutter, nonlinearity (−10.5 dB IMD),
and the missing FEC layer, **not** missing modulation cleverness.

| Channel | BW | SNR | Shannon/track | We get | % |
|---|---|---|---|---|---|
| Acoustic loop (harsh) | ~11 kHz | ~13 dB | ~48 kbps | ~700 net bps | ~1.5 % |
| Sim "normal" | 11 kHz | 42 dB | ~150 kbps | 1–4 kbps | 1–3 % |
| Good deck, electrical | ~15 kHz | ~50 dB | ~250 kbps | — | — |

Practical heroic-effort ceiling ≈ 10–30 % of Shannon (flutter/azimuth/IMD eat the rest).

## Current frontier (simulation, `docs/capacity_pushing_results.md`)

- Baselines: B0 BFSK **478 net bps**; MFSK-32 **1076 net bps** (1.45 MB/C90-stereo).
- Campaign #1 winners: C4 bit-loaded OFDM **3968 bps / 3.69× / 5.33 MB** (sim only),
  C2 combinatorial k-of-M **2412 bps / 2.24×**. C4 **collapses on real flutter**;
  C2 is the real-tape champion (non-coherent).

## Remaining research, prioritized (≈5–20× collective headroom, mostly NOT modulation)

1. **Electrical line-in (hardware, ~€30 UCA222).** The gate. Removes acoustic hop +
   most flutter; SNR +~30 dB; unlocks higher-order QAM and the stereo ×2 multiplier.
2. **SNR engineering (~2–4×).** Channel-matched pre-emphasis, record-level vs IMD,
   Type II/IV tape. Each +6 dB ≈ +1 bit/symbol/subcarrier.
3. **FEC layer (~1.3–1.7× net, and turns "fails" into "recovers").** Deep interleave +
   LDPC/turbo + RaptorQ fountain. The projection *assumes* an outer code we never built.
   **This is also what's needed to byte-exact-decode the real captures** (see below).
4. **Flutter/timing tracking.** Continuous-pilot PLL so coherent OFDM/QAM survives the
   real loop — the sim→real bridge.
5. **Empirical characterization.** More decks/tapes/sides → real burst distribution.
6. **Modulation (~plateaued, ~1.1–1.3× left).** Only the C2×C4 hybrid (index modulation
   on active subcarriers) is untested.

Practical reliable plateau ≈ **a few–several MB per C90** — ~20× the 150 KB quantized
LLM already proven to fit. The model-on-a-cassette goal is **not capacity-limited** any
more; it's reliability- and reader-hardware-limited.

## Scheduled work

- **Deep-dive campaign #2** (routine `trig_01BNAg13q4Q9q4pgK1F2wfzC`, fires 2026-06-08
  23:00 CEST, branch `capacity-deepdive-2`): 8 new hypotheses (pre-emphasis, interleave+
  LDPC/fountain, flutter PLL, combinatorial-OFDM, live CSI bit-loading, probabilistic
  shaping, concatenated soft FEC, 4-track diversity), each on sim **and** harsh-real-proxy
  channels; then stacks winners; runs in waves until quota, committing/pushing each wave.
  Sim-only (cloud) — cannot touch the local real captures.

## Real-tape decode status (local task, NOT in the scheduled run)

First physical capture decoded: **sync bug fixed** (chirp lead-in window), channel is
**great** (39 dB / 0.44 % flutter), data ~90 % recoverable per symbol. **Not byte-exact yet** —
needs (a) per-tone equalization (sounder-H(f)/ON-gain based; blind EQ already cuts mfsk
0.25→0.10) and (b) the FEC layer. Capture saved (`experiments/tape_v2/captures/`), so this
is iterable offline. Details: `experiments/tape_v2/REAL_DECODE_FINDINGS.md`.
