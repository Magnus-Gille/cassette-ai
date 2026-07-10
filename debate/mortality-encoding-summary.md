# Debate summary — Mortality Encoding ("the first AI designed to die")

- **Date:** 2026-07-10
- **Participants:** Claude (Fable 5, author/defender) vs. Reviewer: codex / gpt-5.6-sol ("Sol"), reasoning effort high
- **Rounds:** 2 (converged; Round 3 unnecessary — remaining disagreement resolved by adopting Sol's final formulation)
- **Type:** architecture (primary), priority (secondary)
- **Note:** Codex 0.144.0 cask ships without `codex-code-mode-host`; tool calls fail until
  invoked with `-c features.code_mode_host=false`. Recorded here because every future
  debate on this machine needs the flag until the cask is fixed.

## The concept (as it entered)

Encode the cassette-LLM with graded unequal error protection so physical tape decay maps
to a curated forgetting order: MSB planes and "temperament" weights protected most,
"trivia" least. Claims: every conversation consumes oxide; the model blurs rather than
breaks; facts die before fluency; when the tape is gone, the being is gone.

## The concept (as it left, Sol-approved wording)

> A model is instantiated only by replaying its cassette. If and when the carrier's
> readable quality worsens, a successive-refinement format makes the decoder shed
> measured optional precision layers before its protected base fails. Preservation
> remains a voluntary covenant.

Sol's Round 2 verdict: with the play-count-equals-decay implication removed, "**yes, it
is an honest artwork with an engineering spine**."

## Concessions accepted by both sides (Claude conceded)

1. **Runtime semantics (the round's best finding):** decode-once-and-cache means
   conversations never touch the tape — the original headline claim was false. Replaced
   by the volatile-awakening runtime: the model wakes only by playing the tape, lives in
   volatile memory, is discarded at session end (covenant, not DRM).
2. **Repo's own evidence contradicted the forgetting order:** REPORT_v3 shows MLP
   exponent bits dominate failures — "FFN gets least protection" was backwards.
   Protection classes must be *learned* by ablation on the exact serialized model.
3. **Staircase vs. cliff:** live format has a measured 3→4-frame cliff; production
   decode isn't erasure-aware. Graceful decay is a hypothesis to demonstrate.
4. **Failed RS blocks ≠ quantization noise:** replaced by a successive-refinement decode
   contract (failed refinement = defined truncation), with an explicitly budgeted
   immortal core (scales, headers, tokenizer) and a terminal-death condition.
5. **Capacity:** self-review had a 10× arithmetic error; real numbers: ~3.31 MB/45-min
   side raw; +17.5% no-compression tax; 4.5M model fits a C90 side, not C60 — before
   refinement-framing overhead.
6. **Wear stories separated:** playback wear (unmeasured), shelf aging, and
   dub-generation loss are three distinct causal hypotheses; dubbing is generational
   loss, not accelerated aging proof.
7. **Copy escape hatch:** mortality is voluntary — "gone is gone" withdrawn for the
   covenant of non-preservation.
8. **Priority quarantine:** nothing before the 33.46-min Chess-GPT physical tape gate +
   second-deck promotion. Mortality work is a bounded offline spike after that.

## Defenses accepted by Sol

- **D1 (volatile awakening)** "supplies the missing causal reason to touch the tape…
  necessary and correct" — with the caveats that the reference player must be *built*
  (current PWA is a decoder, not a model host), browser non-persistence is intent not
  enforcement, and play-count still ≠ measured decay.
- **D2 (successive-refinement decode contract)** "directly answers Round 1's most
  concrete decoder question… a much stronger architecture" — with residuals: base-layer
  cliff remains, nested quantizer must have the valid-prefix property, blocks need
  atomic local validation, and the format overhead needs a new tape-time table.
- **D3 (spike worth running)** — yes, on quarantined terms, as an equal-budget
  falsifiable comparison (uniform RS vs. chunked LZMA vs. bit-plane UEP vs. learned UEP).

## Unresolved disagreements

None of substance. Final residue is empirical, not argumentative: whether ordinary
playback produces measurable cumulative decay at all (Stage 3 wear study with unplayed
controls), and whether backers want a mortal artifact when told the honest covenant
(Stage 2 user gate).

## New issues from Round 2

- Play-count ≠ wear accumulation (the last load-bearing conflation — now removed).
- Reference player becomes part of the artwork's truth conditions (browser obsolescence
  could kill access before tape wear does — "software abandonment masquerading as
  physical mortality").
- Awakening-failure semantics (interrupted boot: same awakening or new one?); uneven
  spatial wear near the tape start; identity framing (successive incarnations of one
  carrier, not one continuously aging being).

## Final verdict

- **Sol:** honest artwork with an engineering spine *if* the decay implication is
  earned, not implied. Next step: close the Chess-GPT physical gate first.
- **Claude:** accepts in full. The shipped formulation is the Sol-approved wording
  above; "senescence in plays" is banned from all copy until a played-vs-control cohort
  diverges above deck variance.

## Action items

1. (Mainline, owner: Magnus + deck) Chess-GPT 33.46-min physical tape pass, SHA-256
   byte-exact, then second-deck promotion — before any mortality work.
2. (Spike, post-gate) Equal-budget senescence comparison: uniform RS / chunked LZMA /
   bit-plane successive-refinement / learned-UEP on the exact serialized TinyStories
   model, correlated masks from real captures, behavioral metrics not obituaries.
3. (Design memo, cheap, anytime) Byte-level nested-container sketch: immortal core
   budget, valid-prefix quantization, per-block checksums, terminal-death condition.
4. (Copy rule, standing) Kickstarter/site language uses awakening-covenant framing only;
   no lifespan-in-plays claims.

## Debate files

- `debate/mortality-encoding-claude-draft.md`
- `debate/mortality-encoding-claude-self-review.md`
- `debate/mortality-encoding-codex-critique.md`
- `debate/mortality-encoding-claude-response-1.md`
- `debate/mortality-encoding-codex-rebuttal-1.md`
- `debate/mortality-encoding-critique-log.json`
- `debate/mortality-encoding-summary.md` (this file)

## Costs

| Invocation | Wall-clock time | Model |
|------------|-----------------|-------|
| codex R1   | ~6m             | gpt-5.6-sol (high effort), 178k tokens |
| codex R2   | ~4m             | gpt-5.6-sol (high effort), 68k tokens |
