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
| D1 | Pre-emphasis / spectral shaping | — | — | — | pending |
| D2 | Deep interleave + fountain | — | — | — | pending |
| D3 | Continuous-pilot flutter tracker | — | — | — | pending |
| D4 | Combinatorial-OFDM index mod | — | — | — | pending |
| D5 | Live DD bit-loading + null erasure | — | — | — | pending |
| D6 | Probabilistic amplitude shaping | — | — | — | pending |
| D7 | Soft concatenated FEC + interleave | — | — | — | pending |
| D8 | 4-track + cross-track diversity | — | — | — | pending |

(Findings appended as each completes.)
