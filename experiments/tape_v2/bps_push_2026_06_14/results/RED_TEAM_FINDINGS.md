# Red-team findings + adjudication (2026-06-15)

An adversarial agent attacked the campaign's claims; a two-capture-hardening agent (run in parallel) tested
two-capture stability. They partially conflicted. This is the adjudication of record (my own arithmetic +
the committed n8 data settle each dispute).

## Verdicts

| # | Attack | Red-team verdict | Adjudicated | Action |
|---|---|---|---|---|
| 1 | Filter can't separate r8 from killed 6179 | BROKEN | **PARTLY VALID.** model_net is blind to same-modulation configs, BUT the anchor test separates via claim-backing (achievable 5921 ≥ r8 claim 5791, < 6179 claim). Red-team misread the `ref_net=0` sentinel. The deeper point — model_net is a rate bound, not a carrier-flip model — is fair. | Reframed the filter in the report as a rate/closure bound; carrier-flip risk covered by 3-burn screening. |
| 2 | Replay overfit (train==test) + ext-band under-penalty | BROKEN/WEAK | **VALID (limitations).** 8-DPSK carriers selected on tape10 + scored on tape10; replay's flat per-carrier jitter can't validate selection; ext-band HF timing-slope not modeled. Partly mitigated: carriers held on tape9+doom. | Disclosed both caveats in the report. |
| 3 | r8 reference unstable; deltas within seed noise | BROKEN | **VALID.** model_net seed variance ~±15–25 %, > inter-rung deltas. | Pulled the headline from +44 % to +7–12 %; made byte-exact closure (not model_net delta) the load-bearing metric. |
| 4 | Self-check is consistency, not survivability | HOLDS/WEAK | **VALID (framing).** 6/6 byte-exact proves encoder==decoder; long-frame symbol-count is clock-sensitive. | Reframed self-check; flagged bulk-frame clock sensitivity. |
| 5 | Top rung (stack_bulkframe_TOP) overstated | BROKEN | **VALID.** Full-master replay BER 0.0201 → k_max 178 < recorded RS191 → does NOT close (37/39 cw). The 8535/7443 are not deliverable. | Demoted to **diagnostic**; pulled its numbers. |

## The one dispute the red-team got WRONG

It claimed the hedge rung "fails two-capture: worst_model_net 5888 < 5921." That was an **n_seeds=4 noise
draw**. At n_seeds=8 on the genuinely-different tape9 and doom burns the hedge scores **6675 / 7050**, both
above the 6632 reference (committed in `two_capture_screen.json`). The red-team also said the two-capture guard
"was disabled (replay_doom not registerable)" — both tape9 AND doom were registered and all six rungs held.
Ironically this very n4-vs-n8 swing is the strongest evidence FOR the red-team's seed-noise point (Attack 3).

## Net judgment

The result is **real but modest**, not the inflated first-draft headline. Honest figures: anchor guarantees
5791; bulk-framed r8 is a defensible **+7 % (~6179)**; three higher-order rungs are **+10–12 %** candidates that
held across three real burns but within noisy margins; the aggressive top rung is diagnostic. The adversarial
pass did its job — the corrected `MORNING_REPORT.md` reflects all valid findings.
