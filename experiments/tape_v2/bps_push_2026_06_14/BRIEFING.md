# BPS-Push Campaign — Briefing (2026-06-14, overnight)

**Goal:** beat the standing real-tape record of **5791 net bps** and prepare a NEW master
to record on real cassette in the morning. Filter = the simulator (+ real-tape replay).
Whatever doesn't survive contact with the sim is dropped — UNLESS there is a clear,
*understood* reason the real tape is better than the sim (see §5, the sim is known-pessimistic
on the coherent DQPSK track).

---

## 1. Current SOTA (the thing to beat)

PHY family (all high-rate rungs share this): **continuous-phase DQPSK multicarrier + 1 unmodulated
mid-band pilot**, on a **375 Hz carrier grid**, **2 bits/carrier/symbol**, **RS(255,k)** outer FEC with
global column-major interleave, **per-frame 0.25 s up/down chirp preamble + 0.12 s gap**, Schroeder-phased
TX for low PAPR. `skip` is a cyclic-prefix-like boundary guard (`Nw = N − 2·skip`) → de-facto CP-OFDM.
Symbol rate = `FS/N`, FS=48000.

| rung | scheme | N | sym/s | carriers | bits/sym | RS(255,k) | gross | **NET bps** | status |
|---|---|---|---|---|---|---|---|---|---|
| **r8** | D2X_P22_N256_sp2 | 256 | 187.5 | 22 | 2 | 179 | 8250 | **5791.2** | **RECORD, byte-exact off tape10 (via x11 rescue)** |
| **r6** | D2X_P21_N256_sp2_drop1 | 256 | 187.5 | 21 | 2 | 159 | 7875 | **4910.3** | DOOM ship tape, byte-exact, most-exercised |
| r3 | DQPSK P11 N256 sp4 | 256 | 187.5 | 11 | 2 | 179 | — | 2895.6 | clean bank |
| 2572 | DQPSK P22 N512 sp4 | 512 | 93.75 | 22 | 2 | 159 | 4125 | 2572.1 | prior record |

Config dict (r6 canonical): `P=21, N=256, spacing=2, skip=64, drop_freqs_hz=[750.0], rs_k=159,
pilot_hz=4875, min_spacing_hz=375.0, kind="dense2x_drop"`. Ladder def: `m10_master.py:103-149`,
`make_scheme: m10_master.py:153`. DQPSK scheme: `h4_dqpsk.py:91` (`DQPSKScheme.__init__`), gross_bps
`h4_dqpsk.py:111-118`. Dense2x consts: `x10_b_aggr_05_dense2x_master.py:79-90`.

**net bps = gross_bps × rs_k / 255.** Carrier grid 750–9000 Hz (375 Hz spacing). Pilot @ 4875 Hz.

## 2. The receiver (composed superset: `m10_decode.py` → `x11_decode.py`)

1. Global sync + clock recovery: `analyze_master2.py:136 global_sync_and_resample` — up/down chirp
   matched-filter; chirp0 searched over generous lead-in window; chirp1 via 0.80–1.10 speed scan;
   whole recording resampled to nominal via `resample_poly`.
2. Per-carrier demod + timing: `ResamplingPLLDemod` (`x9_resampling_pll.py`), front-ends `hann256_skip0`
   (primary, 2-bin soft guard) + `rect128_skip64`. Unmodulated pilot's differential phase tracks
   flutter dτ and de-rotates data carriers (`h4_dqpsk.py:203-224`).
3. Pass 1: CRC32-guarded ensemble UNION over (geometry × front-end) branches — fill-only, additive.
4. Pass 2: late-window dc0 stitch (window-shift grid) — fixes 750 Hz prev-symbol echo ISI.
5. Pass 3: carrier-class errors-and-erasures RS ladder (truth-free residual-dispersion ranking).
6. Stage B: gated x11 d2x rescue (`x11_d2x_erasure.py:507`) — fires only on failing d2x sections;
   **this is what lands the 5791 record.**
7. FEC: RS(255,k) + global column de-interleave; **CRC32-per-codeword is the only acceptance channel**
   (no truth used; false-accept budget < 1e-4).

## 3. The measured REAL cassette channel (the design target)

Source: `real_channel_params.json` (two captures: master3=tape3 electrical-ish, master2=voicememo acoustic).

- **SNR median ~40 dB** (40.6 m3 / 39.1 m2), p10 ~32 dB, **frac<8 dB = 0.0. NOISE IS NOT THE LIMITER.**
- **Wow/flutter 0.31–0.44 % WRMS**; decode removes the bulk via chirp resample + per-symbol tracker →
  only ~15 % RESIDUAL reaches the symbol detector.
- **Bandwidth 300–11000 Hz**, monotone HF rolloff **22 dB (m3) / 30 dB (m2)** → effective ceiling ~10.5 kHz.
  High tones 10–20× weaker. Full per-tone H(f) (64 freqs) + per-tone SNR in params JSON.
- **Clock** 1.0009× (m3) / 1.0001× (m2). Recovered from chirp pair.
- **THE LIMITER — spectral contamination / off-tone leakage** (genie-aligned, EQ'd, NOT a timing artifact):
  off-tone 0.374 (M16/N77) / 0.307 (M32/N159); split = **adjacent-bin** 0.112(M16)/0.047(M32) [shrinks with
  symbol length] + **distant-bin diffuse floor ~0.24–0.25** [length-INDEPENDENT]. Reverb tail **τ≈7.9 ms**.
  → N256 symbol (5.33 ms) < τ ⇒ prev-symbol echo ISI (the 750 Hz failure).
- **Phase non-reproducibility:** per-tone phase drifts **median 69–78°** between two sounder reps ~4 s apart,
  magnitude ratio 0.66–1.78× ⇒ time-varying channel. **This killed coherent/absolute-phase PHYs** (CSS,
  DD bit-loading). Differential phase (symbol-to-symbol, 5.3 ms apart) is fine — that's why DQPSK works.
- **IMD:** NOT modeled in either sim. Controlled operationally (record level ~7.0, NOT 8.5; Dolby OFF).

## 4. The bottleneck (dossier conclusions — what actually caps the rate)

1. **Carrier-set width ceiling at this geometry.** Only ~16 of 22 carriers are two-capture-stable at
   DQPSK/187.5. 16×375×k/255 caps ~4494 (RS191). Beating 5791 needs: **more bits/sym on the strong mids**,
   a **different symbol rate**, **1-bit DBPSK in the >9 kHz ext band**, or **bulk framing** — NOT more
   carriers, NOT plain OFDM (already de-facto CP-OFDM; denser bins die to flutter ICI, CP64 dies to echo).
2. **Carrier non-stationarity between burns:** per-carrier SER flips classes burn-to-burn on the same deck;
   marginal carriers (2625/3750/6750 Hz, 4500 Hz deck-notch) at 10–19° margin (<15° rule).
3. **Timing slope c1≈0.00368°/Hz** eats the DQPSK decision boundary above ~9 kHz ⇒ band extension at
   2 bits/sym is dead at this symbol rate; the only open axis there is 1-bit DBPSK.
4. **750 Hz prev-symbol echo ISI** (dominant per-carrier failure, SER .355) — fixed by late-window shift,
   always dropped at r6.
5. **Bulk framing** gated at 1.0× so far (flutter wander appears as static offset on extrapolated frames).

## 5. The simulators & the trust model (CRITICAL)

**Sim A — `src/channel.py::cassette_channel`** (FROZEN): band-limit (butter LP) + wow/flutter (0.55 Hz wow
+ 4.8 Hz flutter + noise, time-warp) + AWGN + Poisson dropouts + speed. Used by `hyp_common` harness with
preset "normal" (42 dB / 11 kHz / 0.10 %). **Known to OVER-REWARD dense short-symbol PHYs** because it omits
the spectral-contamination floor.

**Sim B — `experiments/tape_v2/real_channel_sim.py::real_channel(x, capture="master3"|"master2", symbol_len=…)`**:
calls frozen Sim A at RESIDUAL flutter (15 %), then adds (i) calibrated HF rolloff FIR from measured H(f),
(ii) adjacent-bin ISI (fixed-time short reverb tail), (iii) diffuse floor (convolutional white tail τ=7.9 ms,
gain 0.5). **This is the calibrated pre-screen.** Tunables in `real_channel_params.json["_sim"]`.

**Trust model (how to use the filter honestly):**
- Sim B was calibrated against the **non-coherent K-of-M** leakage measurement. For the **coherent
  differential DQPSK** track it is **PESSIMISTIC** (5–8× on byte-ER): the 5791 r8 rung FAILED its own faithful
  sim probe yet decoded byte-exact off real tape. The differential receiver + pilot rejects much of the
  diffuse contamination that the sim charges in full.
- ⇒ **A DQPSK-family candidate that PASSES Sim B / real-replay is a STRONG GO.** A candidate that only
  marginally beats 5791 in Sim B, or fails it but has sound first-principles reasoning, is a **HEDGE GO** —
  put it on the master as an extra ladder rung. Recording extra rungs is nearly free; the real tape adjudicates.
- **Best available filter = TRACE-DRIVEN REPLAY:** the real captures are ON DISK
  (`captures/tape10_run1.wav` = 5791, `doom_ship/.../doom_tape_readback.wav` = 4910, `tape9_run1.wav`,
  `voicememo_run1.wav`, plus `_sim_*.wav` and pre-channeled `.npy`). Use the analyzer to extract the
  empirical per-carrier complex H(f), per-tone SNR, residual phase-jitter, and reverb IR from a real
  capture's sounder, and drive candidate evaluation with THAT. Far more faithful than the parametric sim.
- **Anchor requirement:** any evaluation harness MUST reproduce the known outcomes before its new numbers are
  trusted: **5791 r8 PASSES** on tape10; the four x12 >5791 candidates (P16 RS223 ~5247; P22 RS191 ~6179/6186)
  were **KILLED** on the two-capture margin gate. If the harness can't separate these, fix the harness first.

Pass/fail: `TARGET_P_FULL=0.95`; reliable frontier = highest gross with passrate ≥ 0.999 (secondary ≥ 0.80);
practical real-tape close threshold raw BER ≲ 0.10 with RS(255,127)-class. Shipping PHY hit raw BER 0.005–0.008.

## 6. The lever map (pre-identified; stabs refine/extend/cite/kill these)

We sit at **~4.5 % of Shannon** (40 dB × 10 kHz ≈ 130 kbps). SNR is unused; **coherence is the wall.**
The central move: **convert the 30 dB of wasted per-carrier SNR headroom into bits/sym WITHOUT needing
absolute coherence.**

- **L1 — Differential amplitude-phase (DAPSK / star-QAM):** add amplitude rings (absolute-coherence-free,
  pilot gives AGC) on top of differential phase. 16-DAPSK = 4 bits/sym on strong mids, stays flutter-immune.
  Doubles the strong carriers. *Top candidate.*
- **L2 — Per-carrier bit/power loading on the differential PHY:** measure each carrier's post-impairment
  effective SNR from real captures; assign DBPSK/DQPSK/8-DPSK/16-DAPSK per carrier. C4 redone on the proven
  differential PHY with real measured CSI. The dossier's own #1 recommendation. *Top candidate.*
- **L3 — Tomlinson-Harashima / TX precoding for the reverb echo:** pre-cancel the measurable τ=7.9 ms echo
  (the 750 Hz problem) at TX. Recovers dropped carriers + cleans constellations. Attacks bottleneck #4.
- **L4 — Bulk / continuous-pilot framing:** amortize the 0.37 s/frame chirp+gap overhead with a continuous
  pilot PLL across long frames. Up to ~1.5×. Near-free, composes with everything. Blocker to solve: flutter
  wander across the long frame.
- **L5 — Ext-band 1-bit DBPSK carriers (9–10.5 kHz):** +~4 carriers × 1 bit × 187.5 ≈ +750 gross. Additive,
  low-risk. master11 already measured this band GO at DBPSK.
- **L6 — Symbol-rate / FFT-size sweep:** N=256 (5.33 ms) < τ. Try N=320/384 (6.7/8 ms) to cut ISI, possibly
  enabling higher-order or more carriers. Trade symbols/s vs ISI vs carriers.
- **L7 — Higher code rate via soft-decision FEC (LDPC/polar) or MSDD:** if modulation drives raw BER low,
  RS(255,205)=0.80 or soft LDPC closer to capacity ⇒ more net bps at same gross. MSDD recovers the
  differential-vs-coherent loss to enable reliable higher-order differential.
- **L8 — MOONSHOT: V.34-style single-carrier + adaptive DFE + TCM.** Abandon multitone. The reverb that
  *hurts* OFDM is what a DFE *handles natively*. V.34 = 9.6 bits/s/Hz over 3.5 kHz/36 dB phone lines; our
  channel is 10 kHz/40 dB. Slow phase drift tracked by a carrier loop (exactly what V.34 does).
- **L9 — MOONSHOT: PRML / partial-response on saturated magnetic recording** (how DAT/HDD hit density).
  Harder to sim-validate (needs magnetic hysteresis). Lower priority.
- **L10 — MOONSHOT: layered/hierarchical modulation** (robust anchor layer + fine layer that adds rate when
  SNR allows) using the 40 dB headroom.

## 7. Deliverable for the morning

A NEW master WAV = **proven 5791 r8 anchor + a LADDER of surviving candidate rungs** at increasing rate,
each with its decode config registered so the morning decode adjudicates the frontier. Plus: operator SOP
(record level ~7.0, Dolby OFF, ~1 s silence around chirps), a decode command, and a morning report.

## 8. Working area & conventions

- Working dir: `experiments/tape_v2/bps_push_2026_06_14/` (candidates/ harness/ results/ master/).
- Branch: `exp/bps-push-2026-06-14` (never push to master).
- Python 3.11+, numpy/scipy/soundfile/reedsolo; seeds set & logged. Big WAVs gitignored.
- Real captures on disk under `experiments/tape_v2/captures/` and `.../` (see §5).
