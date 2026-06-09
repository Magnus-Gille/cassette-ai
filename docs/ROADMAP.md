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

## Later — product & UX ideas (parked 2026-06-09)

- **Companion phone app** — record tape playback + decode on-device + show progress
  ("loading your AI…"), then run the recovered tiny model. The natural endgame packaging
  of the acoustic / zero-hardware path. BLOCKED ON: real-audio decode robustness must
  land first (the app wraps a working decoder, can't substitute for one).
- **Data-flow visualization** — visualize the decode pipeline: recovered spectrogram,
  per-frame raw BER, tracker lock/desync over time, RS-correction heatmap, bytes-recovered
  progress. Doubles as (a) a debugging tool for sim-vs-real gaps and (b) a demo artifact.

## Immediate technical blocker (2026-06-09)
First physical recording of master3 (real cassette-LLM) captured CLEANLY (sounder: 40.6 dB
SNR, 0.31% flutter, clock recovered) but decoded **0/3 — chance BER on every payload**. The
deep-dive `make_tracked_combo` modem was only ever sim-tested; it does not survive real
acoustic audio (coloration + sync/numerical edges, same class as the dd#1 real-capture gap
fixed last night for the OLD modem). Capture saved (`captures/tape3_run1.wav`) for offline
debug. NEXT: harden the tracked combinatorial demod for real audio (per-tone equalization +
robust per-frame preamble sync + fix the dd_common matmul divide-by-zero), validate on the
saved capture, THEN re-attempt. The tape/channel is not the problem — the decoder is.

### master4 PHY re-tier — measured on the master2 real capture (2026-06-09)
Mapped which modem configs survive OUR real channel via the hardened demod + genie ceiling
on `captures/voicememo_run1.wav` (tool `experiments/tape_v2/m2_modem_survival.py`, results
`results/real_modem_survival.json`; see `REAL_DECODE_FINDINGS.md` for the full table).
Decisive results: the real lever is **K (simultaneous tones), not symbol length N** —
K>=4 collapses (genie BER 0.36/0.55), K<=2 is the only viable regime, and the longest
symbol (M48,K6) is the worst. **c2_m32_k2 (M32,K2,N=159) is the only config that is
RS-closable on our channel** — genie byte-error rate 0.164 < robust-RS ceiling 0.251,
winning on error CONCENTRATION (its genie bit-BER ~0.088 merely ties M16, but K=2 packs
those errors into far fewer bytes). RIDER: only the GENIE closes it; the achievable
concentration-lock tracker still loses lock (raw byte-ER 0.637). master4 = M32,K2 PHY +
a stronger timing/detection front-end (pilot/known-symbol aid). The sim's omission of
reverb/leakage/AAC is WHY it over-rewarded high-K short-symbol PHYs.

### Sim/real gap CLOSED — improved simulator built + validated (2026-06-09)
Extended the simulator with the real-channel terms `src/channel.py` lacks, in a NEW
wrapper `experiments/tape_v2/real_channel_sim.py` (the frozen `cassette_channel` is
untouched): (1) a **diffuse leakage/reverb tail** = the length-INDEPENDENT ~25% cross-bin
floor (reverb + room/speaker/mic + AAC), (2) **calibrated HF rolloff** from the smoothed
measured H(f), (3) an **adjacent-bin ISI smear** = a fixed-time tail whose corrupting
fraction shrinks with symbol length (reproducing the 0.112 M16 -> 0.047 M32 split), plus
realistic residual flutter. Calibrated via `experiments/tape_v2/validate_real_sim.py`
(params in the `_sim` block of `real_channel_params.json`).
**Validation (results/real_sim_validation.json):** the OLD sim wrongly blessed M16,K2
(genie byte-ER 0.014, RS trivially closes); the NEW sim FLOORS M16 (genie byte-ER 0.358 >
robust-RS ceiling 0.251 = RS-uncloseable, bit-BER 0.105 in the measured real band) while
reproducing M32,K2's symbol-length advantage (lower byte-ER 0.292, near/under ceiling). The
improved sim would have PREDICTED the master3 M16 failure. master4 recommendation:
**combinatorial M32,K2 (N=159) + robust interleaved RS(255,127)**, with the load-bearing
rider that a pilot/known-symbol timing front-end is required to realise the genie ceiling.
Full write-up: `docs/REAL_CHANNEL.md` section 5.
