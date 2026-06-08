# Encoding Hypotheses — Pre-Registration

**Status:** PRE-REGISTERED (written before any hypothesis is implemented).
**Date:** 2026-06-05.
**Harness:** `src/hyp_common.py` (shared metric contract). Standard channel for
ALL schemes: tape preset **"normal"** (snr 42 dB, band 11 kHz → ~10.5 kHz
effective, wf 0.10 %, burst 0.3/s × 6 ms), capture **usb_soundcard**
(transparent). Worn stress point: preset **"worn"** (snr 36, band 9 k, wf
0.25 %, burst 1.0/s × 10 ms). Monte-Carlo over deterministic `seed_offset`.
No oracle/genie bit-timing — every scheme syncs from its own declared preamble,
which is counted as overhead in `gross_bps`.

This document is the contract: the **claim**, **prior-art lineage**, **method**,
**metric**, and **FIXED accept threshold** for each hypothesis are fixed here
and will NOT be softened after seeing results. The Adjudicate phase compares
measured numbers against these thresholds verbatim.

---

## Baseline B0 — the yardstick (MEASURED)

The shipping CAS3/BFSK codec (`src/cassette_format.py`, 1200 bit/s gross BFSK)
wrapped as a Scheme and run through the exact standard harness
(`measure_baseline_B0`, 20 seeds, 4000 payload bits, normal tape). Saved to
`RESULTS/data/hyp_baseline_B0.json`. Key numbers:

| metric | value |
|---|---|
| `gross_bps` (payload bits / s of audio, framing+leader paid) | **537.9** |
| `raw_bit_error_rate` (in-frame, post-CRC) | 1e-6 (floor) |
| `erasure_rate` (mean frame loss incl. 1 catastrophic seed) | 0.05 |
| `fraction_complete` at 4000-bit payload | **0.95** |
| `per_frame_loss_est` (steady-state, non-catastrophic) | 0.002 |
| `frames_for_target_payload` (1.271 MB @ 256 B/frame) | 4965 |
| **`P_full_fixed_framing` for 1.271 MB (no outer code)** | **4.8e-5** |
| `required_code_rate` (projected, with outer fountain) | 0.889 |
| `net_bps` (projected) | **478.1** |
| `MB_C90_stereo` (projected, with outer code) | 0.642 |
| `MB_C60_stereo` (projected, with outer code) | 0.427 |
| `P_full` (projected, with outer code) | 1.0 |

**Read this carefully — two distinct P_full numbers:**

- **`P_full_fixed_framing = 4.8e-5`** is B0 *as it ships*: per-frame CRC but NO
  outer erasure code. A 1.271 MB payload is 4965 frames; whole-file recovery
  needs ZERO frame losses, so at ~0.2 % steady per-frame loss
  `(1-0.002)^4965 ≈ 5e-5`. **This is the honest baseline for the
  reliability question** and the number H1's precondition checks (it is far
  below 0.80).
- **`P_full = 1.0` (projected)** assumes an *ideal outer fountain code is bolted
  on* (the `project_to_cassette` model). It exists only so every scheme is
  projected on the same generous basis. B0's shipped artifact does NOT have
  this code; H1 is precisely the experiment that adds it.

**The B0 numbers every hypothesis is compared against:**
`B0.net_bps = 478.1 bps`, `B0.gross_bps = 537.9 bps`,
`B0.P_full_fixed_framing(1.271 MB) = 4.8e-5`.

Even with an ideal outer code, B0 projects to **0.64 MB / C90 stereo** — about
half the 1.271 MB target. So B0 alone does NOT hold the file; the throughput
hypotheses (H2/H3/H5) exist to close that gap, and H1 exists to make whatever
rate we run actually recover WHOLE.

### Projection model (conservative, fixed)

`project_to_cassette` (documented in `hyp_common.py`) makes these assumptions,
fixed here so no hypothesis can game them:

1. **Independence.** Bit/symbol/frame errors are treated as independent. Burst
   dropouts are short relative to a megabyte payload and are assumed spread by
   interleaving; we credit NO burst-correlation gain.
2. **Erasures → ideal MDS/RaptorQ fountain.** Overhead = `e/(1-e) + 5 %`
   reception margin (`_erasure_overhead`). This is the cheap path (H1).
3. **Bit errors → hard-decision RS/LDPC.** Safe code rate read from a
   deliberately pessimistic BER→rate table (`_BER_RATE_TABLE`) that sits below
   the Shannon hard-decision limit `1 − H₂(p)`.
4. **Composition.** `required_code_rate = rate_bit_errors / (1 + erasure_overhead)`;
   `net_bps = gross_bps × required_code_rate`; `MB = net_bps × seconds × tracks
   / 8e6` with C90=5374 s, C60=3574 s, stereo=2 tracks.
5. **P_full** is the product of per-layer success estimates; the table/overhead
   margins are what make ≥ target_P achievable.

---

## Over-arching question (pre-registered)

> **Does ANY scheme reliably hold the full 1.271 MB TinyStories-1M payload on a
> single C90 (or C60), in stereo, with P(full recovery) ≥ 0.95 on the
> normal-tape dropout channel?**

A "yes" requires BOTH: (a) projected `MB_C90_stereo ≥ 1.271` (enough net
throughput), AND (b) a credible `P_full ≥ 0.95` mechanism (an outer code that
actually survives 4965-frame-scale loss, not just a projection). The cleanest
"yes" is a throughput winner (H2/H3/H5) **combined with** H1's fountain layer.
We will report the answer for C90 and, if C90 fails, for C60, at both the
normal and worn operating points.

---

## H1 — Rateless fountain / LT erasure coding over BFSK

- **Claim.** Layering a rateless fountain code (LT/RaptorQ) over the EXISTING
  BFSK modulation turns the dropout channel's irrecoverable frame losses into
  cheap erasures, so a 1.271 MB file is recovered WHOLE with ≥ 0.95 probability
  at modest overhead — fixing the reliability problem B0 cannot, *without*
  changing the modem.
- **Prior-art lineage.** Luby, *LT Codes* (FOCS 2002); Shokrollahi, *Raptor
  Codes* (2006); RaptorQ, **RFC 6330** (2011). Rateless erasure coding is the
  textbook answer to a known-erasure (CRC-marked dropped frame) channel.
- **Method.** Keep BFSK modulation + per-frame CRC (so dropped/corrupt frames
  are *marked* erasures). Replace fixed framing with fountain-coded symbols:
  encode the payload into K source blocks, emit N = K·(1+overhead) coded
  blocks, each carried in a CRC'd BFSK frame with a block-ID header. Decode by
  collecting any K(1+ε) surviving blocks and running peeling/Gaussian
  elimination. Measure erasure_rate via the real channel (frame CRC failures),
  then check whether the declared overhead suffices for whole-file recovery at
  1.271 MB scale.
- **Metric.** `P_full(1.271 MB)` from the fountain decoder at a fixed outer-code
  overhead, plus the overhead fraction. Compared against B0's
  `P_full_fixed_framing`.
- **FIXED ACCEPT THRESHOLD.**
  **ACCEPT iff `P_full(1.271 MB) ≥ 0.95` at outer-code overhead ≤ 20 % on the
  normal-tape dropout channel AND the fixed-framing baseline B0 gives
  `P_full < 0.80` on the same.**
  (B0 measured `P_full_fixed_framing = 4.8e-5 < 0.80` ✓ precondition already
  satisfied.) Targets reliability, not raw speed.

---

## H2 — MFSK / Olivia-style multi-tone

- **Claim.** Replacing binary FSK with M-ary orthogonal multi-tone signalling
  (M ∈ {4, 8, 16}) plus light FEC, packed into the 10.5 kHz usable band,
  delivers ≥ 1.5× B0's reliable net throughput.
- **Prior-art lineage.** Soviet/ham HF multi-tone telegraphy; **Olivia MFSK**
  (Pawel Jalocha, 2005) — orthogonal tones + Walsh/convolutional FEC, designed
  for low-SNR fading HF, directly analogous to the tape channel.
- **Method.** M orthogonal tones spaced for orthogonality over a symbol
  (Δf = 1/T_sym), Goertzel/FFT non-coherent detection, each symbol carries
  log₂(M) bits. Add a light FEC (Olivia-style Walsh + interleave, or a
  convolutional inner code) sized to the measured BER. Shared chirp preamble
  (`make_preamble`) for sync. Sweep M to find the band-vs-robustness optimum.
- **Metric.** `net_bps` from `evaluate_scheme` → `project_to_cassette` on the
  normal tape.
- **FIXED ACCEPT THRESHOLD.**
  **ACCEPT iff reliable `net_bps ≥ 1.5 × B0.net_bps`** (i.e. ≥ **717.1 bps**).

---

## H3 — OFDM with pilot-tracked QAM + per-subcarrier bit-loading

- **Claim.** A multicarrier OFDM waveform with pilot-tracked equalisation and
  water-filling bit-loading (more bits on clean mid-band subcarriers, fewer on
  the rolled-off HF edge) exploits the flat-ish 300 Hz–10.5 kHz band to reach
  ≥ 2.0× B0's net throughput.
- **Prior-art lineage.** Multicarrier modems: **V.34 / ADSL/VDSL DMT**
  (Cioffi et al.), where per-subcarrier bit-loading over a coloured channel is
  the canonical capacity-approaching technique. Pilot-tracked QAM is standard
  in DVB/Wi-Fi OFDM.
- **Method.** IFFT-based OFDM with cyclic prefix sized to the channel's
  effective delay spread; scattered pilot tones for per-symbol channel
  estimation and phase/timing tracking (handles wow/flutter as slow phase
  drift); per-subcarrier SNR measured from pilots → bit-loading table
  (BPSK/QPSK/16-QAM/…). Coded with an LDPC/convolutional inner code. Chirp
  preamble for coarse sync + frame/symbol timing.
- **Metric.** `net_bps` from `evaluate_scheme` → `project_to_cassette` on the
  normal tape.
- **FIXED ACCEPT THRESHOLD.**
  **ACCEPT iff `net_bps ≥ 2.0 × B0.net_bps`** (i.e. ≥ **956.1 bps**).

---

## H4 — Chirp spread spectrum / LoRa-style

- **Claim.** Cyclic-shifted chirp (CSS) symbols, dechirped and FFT-demodulated,
  match B0's net throughput while surviving dropouts strictly better — the
  spread-spectrum processing gain makes each symbol robust to burst loss.
- **Prior-art lineage.** Radar pulse-compression chirps; **Semtech LoRa** CSS
  modulation (cyclic-shift chirp symbols, spreading-factor SF, dechirp + FFT
  bin = symbol). Proven for low-SNR, fading, interference-heavy links.
- **Method.** Up-chirp base symbol across the usable band; each symbol is a
  cyclic time-shift encoding SF bits; demod multiplies by the conjugate
  down-chirp and takes the FFT, peak bin = symbol. Sweep SF for the
  rate/robustness trade. Shared chirp preamble for sync. Compare dropout
  survival at *equal net rate* to B0 (encode the same net_bps for both, compare
  `P_full`).
- **Metric.** `net_bps` AND `P_full` at equal net rate vs B0, on the normal tape.
- **FIXED ACCEPT THRESHOLD.**
  **ACCEPT iff `net_bps ≥ 1.0 × B0.net_bps`** (i.e. ≥ **478.1 bps**)
  **AND dropout-survival (`P_full` at equal net rate) strictly > B0's.**

---

## H5 — GCR/RLL magnetic-recording channel code + bandlimited NRZI

- **Claim.** A run-length-limited (GCR/MFM/RLL) channel code with 2-level
  NRZI-style signalling, bandlimited to the channel, achieves ≥ 1.5× B0's
  reliable net throughput by packing bits at the channel's true symbol rate with
  DC-balance / clock-recovery guarantees.
- **Prior-art lineage.** Magnetic recording channel codes: **Commodore 1541 GCR**
  (group-coded recording), **MFM/RLL** disk and tape codes — designed exactly
  for the saturation-recording magnetic channel with self-clocking and bounded
  run lengths.
- **Method.** Map payload through a GCR/RLL encoder (e.g. 4→5 GCR or (1,7) RLL)
  guaranteeing min/max run lengths and DC balance, signal as 2-level NRZI
  transitions bandlimited to ~10.5 kHz, recover the clock from transitions.
  Chirp preamble for coarse sync.
- **Metric.** `net_bps` from `evaluate_scheme` → `project_to_cassette` on the
  normal tape.
- **FIXED ACCEPT THRESHOLD.**
  **ACCEPT iff reliable `net_bps ≥ 1.5 × B0.net_bps`** (i.e. ≥ **717.1 bps**).
- **MODEL-FIDELITY CAVEAT (pre-registered up front).** `src/channel.py` is a
  **linear, bandlimited** model: it applies AWGN, a low-pass, wow/flutter
  resampling and burst dropouts, but it does **NOT model magnetic saturation,
  hysteresis, or the nonlinear write/read transfer of a real tape head**. GCR/RLL
  codes earn their advantage precisely from operating a *saturating* magnetic
  channel (transitions, not amplitudes). Therefore a simulator REJECTION of H5
  is *itself informative about model fidelity*, not necessarily about the code:
  it would indicate our channel under-represents the regime GCR/RLL is built for.
  We will say so explicitly in the Adjudicate phase and will not treat an H5 sim
  rejection as evidence GCR/RLL is useless on real tape.

---

## Summary of fixed thresholds (echoed verbatim)

| Hyp | Threshold (FIXED) | Numeric (using B0.net_bps = 478.1, B0.gross_bps = 537.9) |
|---|---|---|
| H1 | P_full(1.271 MB) ≥ 0.95 at overhead ≤ 20 % AND B0 fixed-framing P_full < 0.80 | B0 P_full_fixed = 4.8e-5 < 0.80 ✓ |
| H2 | reliable net_bps ≥ 1.5 × B0.net_bps | ≥ 717.1 bps |
| H3 | net_bps ≥ 2.0 × B0.net_bps | ≥ 956.1 bps |
| H4 | net_bps ≥ 1.0 × B0.net_bps AND dropout-survival > B0's | ≥ 478.1 bps + strictly better P_full |
| H5 | reliable net_bps ≥ 1.5 × B0.net_bps (sim caveat: linear channel) | ≥ 717.1 bps |

**Over-arching:** does ANY scheme reliably hold 1.271 MB on a C90 (or C60),
stereo, at P_full ≥ 0.95? Reported in Adjudicate for both normal and worn tape.
