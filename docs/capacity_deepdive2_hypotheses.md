# Capacity deep-dive #2 — pre-registration

**Question.** Building on deep-dive #1 (C1–C5), can we push *net* bits/cassette
further — and crucially, can we make a high-rate scheme **survive the REAL tape
channel** (worn deck, ~0.88× clock, ~2.5% flutter, heavy 10 ms bursts), not just
the clean 42 dB simulation? Deep-dive #1 only ever scored on the sim 'normal'
channel; #2 scores **every** hypothesis on BOTH channels.

## Methodology (frozen + extended)

* **Frozen harness:** `src/hyp_common.py` → `evaluate_scheme` →
  `project_to_cassette` (the conservative BER→code-rate table; 5% erasure
  margin always applied; P_full step model). Net-bps and MB/C90-stereo are the
  projected metrics, subject to **P_full = 1.0** (whole-file recovery).
* **Dual channel (NEW):** every hypothesis is measured on
  * **sim** = preset `normal`, speed_offset 0, capture `usb_soundcard` (42 dB);
  * **real** = preset `worn` + **speed_offset = −0.12** (the ~0.88× flutter-heavy
    acoustic loop: 36 dB SNR, 2.5% wow/flutter, 1 burst/s × 10 ms, 9 kHz BW).
  Where relevant we also cross-check `experiments/dpd/channel_model.json`
  (measured real tape: clock 0.88, flutter 2.2%, SNR median ~12.6 dB).
* **Survival metric (NEW):** the harsh channel produces *per-seed catastrophic
  sync loss* (a seed either decodes at low BER or loses symbol timing and sits
  at 0.2–0.7 BER). Mean BER mixes these, so we additionally report
  **survival = fraction of seeds with BER ≤ 3e-2** (≈ whole-file recoverable;
  outer rate ≥ 0.55). Real-channel P_full = 1.0 in practice requires
  survival ≈ 1.0.
* **Mandatory sanity gate:** loopback (no-channel) BER must be ~0 for every modem
  (catches demod bugs). Tracked demods must still pass this.
* **The sim→real bridge** is a reusable front end in
  `experiments/deepdive2/dd_common.py`: `estimate_speed` (chirp-preamble,
  normalized-correlation, coarse→fine→parabolic; recovers 0.88 to <0.4%) +
  `tracked_tone_demod` (global speed correction → wide initial acquisition →
  per-symbol energy-lock micro-tracking with a center-bias against drift random-
  walk and burst-induced slips). No oracle timing anywhere.
* **Fair REJECT vs INCONCLUSIVE:** a REJECT counts only if the experiment is
  sound (sanity passes, sync from signal). A suspected demod bug → INCONCLUSIVE.
  "No improvement possible" is a valid, valuable result.

## Reference anchors (re-measured in-run, dual channel, n_seeds=12)

| Scheme | sim net | sim surv | real net | real surv | real BER | note |
|---|---|---|---|---|---|---|
| MFSK-32 naive (fixed window) | **1076** | 1.00 | 67 | 0.00 | 0.82 | the #1 frontier yardstick; collapses on real (12% clock) |
| MFSK-32 **+ tracker** | **1331** | 1.00 | 134 | **0.58** | 0.095 | timing recovery alone: BER→0 on sim (rate 0.94), best real survivor |
| C2 k-of-M (M=48,K=6) +spd | **2412** | 1.00 | 172 | 0.00 | 0.221 | sim champion #1; fixed-window reshape can't track flutter → real collapse |
| C4 OFDM bit-load +spd | **3968** | 1.00 | 233 | 0.00 | 0.206 | sim frontier; 9/12 real seeds at ~0.04 BER, 3 catastrophic → closest to surviving |

**Headline state:** on the harsh real channel **nothing yet reaches P_full = 1.0.**
Best real survival is MFSK-32+tracker at 58%. The central #2 challenge is to lift a
high-rate scheme to survival ≈ 1.0 on worn+0.88× while holding sim net high.

Two frontier metrics are tracked:
* **SIM frontier:** net_bps at P_full=1.0 (current best C4 = 3968).
* **REAL frontier:** net_bps at survival≈1.0 (current best: *none clears 0.9*;
  MFSK-tracker 134 bps @ 0.58 is the incumbent to beat).

## Hypotheses and PRE-REGISTERED accept bars

All bars require the sanity gate to pass. Bars fixed BEFORE results.

| # | Hypothesis | Mechanism | SIM accept bar | REAL accept bar |
|---|---|---|---|---|
| **D1** | Channel-matched pre-emphasis / spectral shaping | Shape TX spectrum to flatten post-channel SNR(f); push more carriers above QAM thresholds. Applied to C4 loading. | C4 sim net ≥ **4400** (≥1.11× C4) at P_full=1.0 | ≥10% real-net gain vs C4+spd, OR raise real survival |
| **D2** | Deep interleaving + fountain (RaptorQ/LDPC) over WHOLE payload | Convert burst dropouts + catastrophic-seed sync loss into recoverable erasures; realize the outer code the projection assumes. End-to-end whole-file recovery. | n/a (outer code; measured as erasure-path net) | **survival ≥ 0.90** on real for a tracked PHY (the prize), net > 134 |
| **D3** | Continuous-pilot PLL flutter tracker | Adaptive per-window resampling vs 2.5% flutter so coherent OFDM survives worn+0.88×. The sim→real bridge. | hold C4 sim net ≥ 3968 | C4-class real **survival ≥ 0.90**, real net ≥ **1000** |
| **D4** | Combinatorial-OFDM / index modulation | Modulate WHICH subcarriers are active (k-of-M) on top of their QAM — extra bits/symbol cheaply. | sim net ≥ **4400** (≥1.11× C4) at P_full=1.0 | not worse on real than C4+spd |
| **D5** | Live decision-directed per-carrier bit-loading + null erasure | Adapt loading to THIS tape's nulls at the RX (CSI), mark dead carriers as erasures — fixes C4's frozen-map fragility. | C4 sim net ≥ **4100** | real **survival ≥ 0.90**, real net ≥ **1200** |
| **D6** | Probabilistic amplitude shaping / non-uniform constellations | Claw back the ~1.5 dB shaping gap in the power-limited QPSK regime. | sim net ≥ **4300** (≥1.08× C4) | no real regression |
| **D7** | Modern soft-decision concatenated FEC + deep interleaving | CCSDS RS+conv or polar WITH interleaving on burst+AWGN — beat the conservative table honestly where C3 failed. | net (any PHY) ≥ **1.15×** its uncoded projection | improve real survival of its PHY |
| **D8** | Full 4-track (2 sides × stereo) + cross-track MRC / erasure coding | Model ~30 dB inter-track crosstalk; quantify true aggregate per-cassette capacity with cross-track diversity. | aggregate MB/cassette ≥ **1.8×** single-track at equal per-track P_full | real aggregate survival ≥ single-track |

**Notes.** D3 is essentially the bridge primitive already prototyped (tracker);
its experiment hardens it to C4-class survival. D2/D7 are the only genuinely
*stackable* levers (outer codes multiply any PHY's net / convert losses to
erasures). D1/D4/D5/D6 are competing/▢complementary PHY refinements. D8 is an
orthogonal aggregate-capacity axis.

## Results

(filled in `docs/capacity_deepdive2_results.md` per wave.)
