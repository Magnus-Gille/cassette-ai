# Two-capture hardening of the BPS-push ladder

**Date:** 2026-06-15 (pre-morning-burn de-risk)
**Branch:** `exp/bps-push-2026-06-14`
**Artifact:** `results/two_capture_screen.json` (+ `.log`); harness
`harness/two_capture_screen.py`.

## Why

The #1 stated weakness of the bps-push result: the 6-rung ladder was screened on
**ONE** faithful replay channel (`replay_tape10`, the 5791 burn). A single channel
cannot see the **burn-to-burn carrier flips** that killed the old 6179 config — those
only surface when a *second real burn* (different deck-state / azimuth / day) measures
a different per-carrier margin set. Goal: get a genuine second capture into the replay
filter and re-screen all 6 rungs on BOTH **before** the morning record.

## Second captures registered

The replay channel only needs a capture's **front sounder** to measure H(f) / SNR /
flutter / clock. Two genuinely different real burns now measure cleanly (the doom entry
in `replay_channel.py:CAPTURES` was wired to its manifest; tape9 was already registerable):

| capture | source | flutter | SNR (median) | clock ratio | H(f) range |
|---|---|---|---|---|---|
| **tape10** (orig) | `master10_manifest` + `captures/tape10_run1.wav` (5791 burn) | 0.418 % | 35.4 dB | 1.00067 | −41.6 .. 0 dB |
| **tape9** (NEW, primary 2nd) | `master9_manifest` + `captures/tape9_run1.wav` (a *different* real burn of the DQPSK ladder) | 0.434 % | 41.1 dB | 1.00170 | −43.3 .. 0 dB |
| **doom** (NEW, 3rd stress) | `m10doom3_manifest` + `captures/doom_tape_readback.wav` (the 4910 DOOM burn) | 0.398 % | 38.7 dB | 1.00105 | −44.7 .. 0 dB |

These are three independent burns (different masters, different days, different
deck-states) — exactly the burn-to-burn variance the single-channel screen was blind to.

## Sanity: the anchor holds on the 2nd capture

Re-confirmed r8 (`build_dense2x_candidate(22,179)`) on the second capture, n_seeds=8:

- **tape9** r8 BER = 0.0100 → E ≈ 19.7 byte-errors → RS179 (corrects 38) **CLOSES**, model_net 6956.
- **doom**  r8 BER = 0.0122 → E ≈ 23.9 → RS179 **CLOSES**, model_net 6697.

r8 does **not** collapse on either second capture — the measurements are well-calibrated.
(tape9 even scores *better* than tape10, consistent with its higher SNR.) Had r8 collapsed,
the second-capture channel would be miscalibrated and discarded; it does not, so it ships.

## Two-capture screen — per-rung table (n_seeds = 8)

`model_net` = gross × k_max(ber)/255 (the rs_k-independent yardstick compared vs r8).
**Two-capture worst** = min(tape10, tape9). doom is a third stress point. r8's two-capture
reference (worst of tape10, tape9) = **6632**.

| rung | gross | t10 BER | t10 mn | t9 BER | t9 mn | doom mn | **2-cap worst** | cassette_net @rs_k | verdict |
|---|---|---|---|---|---|---|---|---|---|
| anchor_r8 | 8250 | 0.0126 | 6632 | 0.0100 | 6956 | 6697 | **6632** | 5791 (rs179) | **REF** |
| r8_bulkframe | 8250 | 0.0078 | 7215 | 0.0066 | 7376 | 7247 | **7215** | 6179 (rs191) | **GO** |
| dapsk_8dpsk3 | 8812 | 0.0142 | 6877 | 0.0107 | 7361 | 7119 | **6877** | 6359 (rs184) | **GO** |
| stack_8dpsk3_ext4 | 9562 | 0.0177 | 7012 | 0.0124 | 7725 | 7538 | **7012** | 6488 (rs173) | **GO** |
| stack_bulkframe_TOP | 9938 | 0.0089 | 8535 | 0.0076 | 8729 | 8574 | **8535** | 7443 (rs191) | **GO** |
| robustness_hedge_dapsk7 | 9562 | 0.0201 | 6675 | 0.0160 | 7238 | 7050 | **6675** | 6488 (rs173) | **GO** |

## Verdict — the second capture CONFIRMS the ladder

**All 6 rungs are two-capture-stable.** Every rung's two-capture-worst model_net beats
the r8 two-capture reference (6632), and every rung also clears the doom stress point.
No rung degrades materially on the second capture; **no rung flips below r8.**

The decisive structural finding: **tape9 (the genuinely different burn) scores BETTER than
tape10 on EVERY rung** (and doom sits between them). So `tape10` remains the *binding
worst-case* on all rungs — which means the original single-`tape10` screen was already the
**conservative** channel, not an optimistic outlier. The carrier-flip risk the gate was
built to catch did not bite: the per-carrier margins that carry the 8-DPSK / ext-band bits
held up across all three burns.

Two-capture-worst ordering is unchanged from the recommended ladder:

> anchor_r8 (5791, REF) → robustness_hedge_dapsk7 (6675) ≈ dapsk_8dpsk3 (6877) →
> stack_8dpsk3_ext4 (7012) → r8_bulkframe (7215) → **stack_bulkframe_TOP (8535, TOP)**

### Per-rung calls

- **anchor_r8** — REF / floor. Unchanged; the proven 5791.
- **r8_bulkframe** — robust GO. 2-cap worst 7215 (+583 over ref). Same PHY as the anchor,
  inherits its two-capture stability; rs191 still closes with margin (k_max ≈ 223 at the
  bulk BER). Keep.
- **dapsk_8dpsk3** — robust GO. 2-cap worst 6877 (+245). The 8-DPSK bit on the 3 CSI-clean
  carriers held on the second burn (no flip). Keep at rs184.
- **stack_8dpsk3_ext4** — robust GO. 2-cap worst 7012 (+380). Both orthogonal levers
  (8-DPSK + ext-band) survived the second burn. Keep at rs173.
- **stack_bulkframe_TOP** — robust GO, the campaign top. 2-cap worst **8535** (+1903 over
  ref, +44 % over the original 5921 reference). The bulk-frame multiplier and the stacked
  higher-order modulation both held on the second + third burn. Keep at rs191 (conservative
  vs the k_max≈219 the BER would allow — the HF-rolloff hedge is retained).
- **robustness_hedge_dapsk7** — robust GO, and still the right insurance rung. 2-cap worst
  6675 (+43 over ref — the thinnest margin of the six, as designed: it trades peak rate for
  flip-robustness). Record it alongside the aggressive rungs.

### Recommended ladder change

**None required.** The second capture validates the morning ladder as-is — order, RS rates,
and the stretch top are all confirmed two-capture-stable. The only update is to the scoring
caveat: the previous note "single-faithful-channel, same limitation as the reference itself"
is now **retired** — the ladder is screened on **three** independent real burns (tape10,
tape9, doom), with tape10 the binding worst case on every rung.

One honest caveat preserved: the replay still measures each channel from its **magnitude**
sounder + a calibrated phase-jitter term; it does not replay a literal per-carrier phase
snapshot (non-reproducible by design). So a pathological morning azimuth that drives a clean
carrier's symbol-to-symbol phase past the 8-PSK boundary is still adjudicated by the real
tape — but it would now have to be worse than **two** good prior burns, not one. The
conservative rs_k derates (TOP at rs191 vs k_max≈219; stacks at rs173) absorb that residual.
This de-risks, it does not eliminate; the morning tape remains the final judge.
