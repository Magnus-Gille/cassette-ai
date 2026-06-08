# Capacity deep-dive #2 — results scorecard

**Status:** IN PROGRESS. Pre-registration + accept bars in
`docs/capacity_deepdive2_hypotheses.md` (fixed before results). All work on
branch `capacity-deepdive-2`. Shared harness: `experiments/deepdive2/dd_common.py`
(frozen `src/hyp_common.py` underneath). Dual-channel: **sim** (normal, 42 dB) and
**real** (worn + speed_offset −0.12, the ~0.88× flutter+burst loop).

## Reference anchors (in-run, n_seeds=12)

| Scheme | sim net | sim surv | real net | real surv | real BER |
|---|---|---|---|---|---|
| MFSK-32 naive | 1076 | 1.00 | 67 | 0.00 | 0.82 |
| MFSK-32 + tracker | 1331 | 1.00 | 134 | 0.58 | 0.095 |
| C2 k-of-M (48,6) +spd | 2412 | 1.00 | 172 | 0.00 | 0.221 |
| C4 OFDM bit-load +spd | 3968 | 1.00 | 233 | 0.00 | 0.206 |

**SIM frontier:** C4 = 3968 net bps (P_full 1.0). **REAL frontier:** nobody at
survival≥0.9 yet; MFSK-tracker (134 bps @ 0.58) is the incumbent.

### Foundational findings (Wave 0 — infrastructure)
1. The harsh real channel is dominated by the **12% deck-clock offset**: naive
   fixed-window demods collapse (BER 0.8+). A preamble-derived global speed
   estimator recovers 0.88 to <0.4%.
2. **Per-symbol timing tracking is mandatory** on real. It also *helps sim*:
   MFSK-32 sim net 1076→1331 purely by eliminating fixed-window timing drift
   (BER→0, rate 0.94).
3. The prior "C2 is the real-tape champion" only held on the *mild* clean
   acoustic loop (0.44% flutter). On worn+0.88× C2's fixed-window reshape
   collapses (172 net, 0% survival). **C4 is actually closest to real survival**
   (9/12 seeds ~0.04 BER), bottlenecked by 3 catastrophic-acquisition seeds and a
   ~0.04 BER floor.

## Wave 1 scorecard

| # | Hypothesis | sim net | real net | real surv | Verdict |
|---|---|---|---|---|---|
| D1 | Pre-emphasis / spectral shaping | 3968 | 233 | 0.00 | **REJECT (fair)** |
| D2 | Deep interleave + fountain/erasure | — | — | — | **REJECT (fair)** |
| **D3×D4** | **Flutter tracker × combinatorial index-mod** | 2857–3636 | **2309** | **1.00** | **ACCEPT (breakthrough)** |
| D5 | Live DD bit-loading + null erasure | — | — | — | pending |
| D6 | Probabilistic amplitude shaping | 3968 | 233 | 0.00 | **REJECT (fair)** |
| D7 | Soft concatenated FEC + interleave | — | — | — | agent running |
| D8 | 4-track + cross-track diversity | — | — | — | agent running |

### THE HEADLINE — D3×D4: real channel cracked

The central #2 challenge ("make a high-rate scheme survive worn+0.88×") is **solved.**
Combining the **flutter tracker (D3)** — global preamble speed correction +
per-symbol energy-lock micro-tracking — with a **non-coherent combinatorial
k-of-M tone PHY (D4 index modulation)** gives the first scheme to reach
**P_full = 1.0 / survival 1.0 on the harsh real channel**:

| config | sim net | sim surv | real net | real surv | real BER |
|---|---|---|---|---|---|
| **M16,K2 (real champion)** | 2857 | 1.00 | **2309** | **1.00** | 1.4e-3 |
| M16,K3 (best sim survivor) | 3636 | 1.00 | 2174 | 0.92 | 1.7e-2 |
| M24,K3 | 2661 | 1.00 | 1722 | 1.00 | 1.3e-2 |
| M48,K6 (old C2 champ) | 2929 | 1.00 | 689 | 0.00 | 7.1e-2 |

**Real frontier: 2309 net bps at P_full 1.0** — **17× the previous real incumbent**
(MFSK-tracker 134) and **2.1× even the sim MFSK-32 frontier (1076).** Per C90
stereo: 2.1 MB recoverable from the *worn* deck.

Why it works (and why the prior C2 "real champion" claim was wrong): the prior
work scored C2 only on a *mild* acoustic loop (0.44% flutter) and found high-M
(48,6) best on sim. On the *harsh* worn+0.88× channel, high-M's narrow tone
spacing is shredded by 2.5% flutter (M48K6 → 689, 0% survival). With the tracker,
**low-M wide-spacing wins**: M16K2's 2 lit tones of 16 (623 Hz spacing) stay
dominant through flutter and bursts → real BER 1.4e-3, nearly as clean as sim.
Coherent C4-OFDM (sim champion 3968) collapses on real (3/12 seeds total sync
loss, rest at 0.04 BER) — magnitude detection is the right call for real tape.

### Per-hypothesis findings (Wave 1)

**D1 — pre-emphasis → REJECT (fair).** The tape band is power-limited, not
bandwidth-limited. The in-band (500–10.3 kHz) Butterworth response varies <1 dB,
so channel-inverse pre-emphasis ≈ flat. Aggressive +3 dB/oct boosts probe SNR but
the boosted high carriers are noise-dominated → BER 6.6e-2, net collapses to 1283.
No curve clears 4400. (`d1_preemphasis.py`, `results/d1.json`.)

**D2 — deep interleave + fountain/erasure → REJECT (fair).** On the tracked
combinatorial PHY the real-channel errors are *spread* flutter/noise-edge symbol
errors, not detectable bursts: a lock-score erasure detector flagging the bottom
15% of symbols catches only 21–27% of the error symbols. So erasure-marking pays
fountain overhead without removing the error mass (mirrors C4's dd#1 erasure
result). The deep-interleaved hard-decision outer code D2 proposes is **already
realized by the frozen projection's bit-error path** — there is no extra gain to
claim here. Valuable corollary: the projection is the correct model.
(`d2_fountain.py`, `results/d2.json`.)

**D3 — flutter tracker → ACCEPT (the bridge).** `dd_common.tracked_tone_demod`:
preamble speed estimate recovers 0.88 to <0.4%; per-symbol ±3 energy-lock search
with center-bias against drift random-walk + final-symbol zero-pad → sanity BER 0,
sim BER→0 (even *improves* sim: MFSK-32 1076→1331 by killing fixed-window timing
drift), and turns every combinatorial config from real-collapse into real-survival.

**D4 — combinatorial index modulation → ACCEPT (breakthrough).** See headline.
The information rides on *which* k of M tones are lit (index modulation across the
tone bank); on the real flutter channel this dominates QAM-on-subcarriers.

**D6 — amplitude shaping → REJECT (fair).** At ~13 dB per-SC SNR no subcarrier
reaches 16-QAM under any gap (loading is all BPSK/QPSK), so the ~1.5 dB shaping
gap has no constellation to act on. Geometric/probabilistic shaping degenerate to
uniform for ≤QPSK → bit-identical to baseline. Power-limited regime blocks it.
(`d6_shaping.py`, `results/d6.json`.)

### Refined (M,K) frontier (n_seeds=16)

The K=2 wide-spacing ridge holds **survival 1.0 with zero catastrophic seeds**
across M=12–20; net peaks at **M14,K2**:

| config | sim net | real net | real surv | real BER | catastrophic |
|---|---|---|---|---|---|
| M12,K2 | 3066 | 2525 | 1.00 | 8.2e-3 | 0.00 |
| **M14,K2 (REAL FRONTIER)** | 2933 | **2550** | **1.00** | 2.0e-3 | 0.00 |
| M16,K2 | 2857 | 2309 | 1.00 | 1.3e-3 | 0.00 |
| M18,K2 | 2931 | 2072 | 1.00 | 6.1e-3 | 0.00 |
| M20,K2 | 2705 | 1913 | 1.00 | 4.5e-3 | 0.00 |
| M16,K3 (best raw sim) | 3636 | 1581 | 0.75 | 2.1e-2 | 0.00 |

K=3 lifts sim (M16K3=3636) but its tighter spacing loses real survival (0.75).
**The single best real-robust operating point is M14,K2: 2550 net bps real,
2933 sim, survival 1.0.** (`d3d4_refine.py`, `results/d3d4_refine.json`.)
