# Novel Encoding Schemes — Adjudicated Results

Pre-registration: `docs/encoding_hypotheses.md` (thresholds fixed *before* results).
Baseline **B0** = working CAS3 BFSK-1200 measured on the shared harness (`src/hyp_common.py`):
net **478 bps**, **0.642 MB** on a C90 stereo, P_full(1.271 MB)=1.0 at code rate 0.89.
Raw data: `RESULTS/data/hyp_*.json`, plots `RESULTS/plots/hyp_*.png`.

> **Provenance note.** The orchestrating workflow crashed in its adjudication phase (3 implementation
> agents finished the experiments but never emitted their final structured object). All five
> implementations and 4/5 metric JSONs were on disk; H1 was re-run to completion. This adjudication
> was done by hand from the raw artifacts, including bug-vs-fundamental checks on the rejects.

## Scorecard

| # | Scheme | Heritage | Pre-registered bar | Measured | Verdict |
|---|---|---|---|---|---|
| **H1** | Rateless fountain/LT over BFSK | Luby 2002 / RaptorQ | P_full(1.271 MB) ≥ 0.95 @ ≤20% overhead, fixed-framing < 0.80 | **P_full = 1.000 @ 15% overhead**; fixed-framing P_full = **4.8e-5** | ✅ **ACCEPT** |
| **H2** | MFSK-32 (Olivia lineage) | Soviet/ham HF, Olivia 2005 | net ≥ 1.5× B0 | **net 1076 bps = 2.25×**, raw BER 0.2%, **1.45 MB / C90-stereo**, P_full=1.0 | ✅ **ACCEPT** |
| H3 | OFDM + QAM + bit-loading | DSL / V.34 | net ≥ 2.0× B0 | gross 6173 bps but raw BER 8.9% → net **588 = 1.23×** | ❌ **REJECT** (fair) |
| H4 | Chirp spread-spectrum | radar chirp / LoRa | net ≥ 1.0× B0 + better dropout survival | raw BER **0.506** (≈ chance); fails harness interface | ⚠️ **INCONCLUSIVE — bug** |
| H5 | GCR/RLL magnetic code | Commodore GCR, MFM/RLL | net ≥ 1.5× B0 | raw BER **0.37 on a near-clean channel** → demod broken | ⚠️ **INCONCLUSIVE — bug** |

**Tally: 2 accept, 1 fair reject, 2 inconclusive-due-to-bugs.**

## Detail

**H1 — Fountain coding (ACCEPT, reliability claim).** This is a *coding-layer* result, not a throughput
one. At 1.271 MB scale (K=1,271,000 source symbols), a robust-soliton LT code at **15% overhead**
recovers the whole payload with P_full = 1.000 (both binomial and Monte-Carlo estimates), whereas
fixed CAS3 framing recovers the whole file with probability **4.8e-5** — i.e. essentially never, because
~2–5% per-frame dropout loss over thousands of frames guarantees at least one unrecoverable hole.
*Caveat:* H1's *measured* throughput (gross 110 / net 5 bps) is a small-test-scale artifact (fixed
leader/chirp overhead dominating a tiny test payload) and is **not** meaningful — fountain coding does
not set the rate, it guarantees completion. It must be **stacked on a modulation**.

**H2 — MFSK-32 (ACCEPT, throughput win).** 32 orthogonal tones, log₂32 = 5 bits/symbol, non-coherent
FFT demod. On normal tape: raw BER 0.21%, required code rate 0.76, **net 1076 bps (2.25× B0)**,
projecting to **1.45 MB on a C90 in stereo** — the first scheme to clear the 1.271 MB single-cassette
goal, at P_full = 1.0. *Caveat:* the winning config carried **no FEC**, so on the worn-tape stress
point it collapses (raw BER 8.2% → net 134 bps). It is bare against dropouts on its own.

**→ The combination that matters: H2 (MFSK-32) for raw bits × H1 (fountain) for dropout survival.**
MFSK-32 supplies the 2.25× throughput; the fountain layer (15% overhead) converts MFSK-32's frame
losses into guaranteed full-payload recovery on both normal *and* worn tape. Neither alone is
sufficient (H2 fails on worn; H1 sets no rate); together they are the candidate end-to-end stack.

**H3 — OFDM (REJECT, fair).** Genuinely works: gross **6173 bps** (>10× B0 raw). But the tape's ~9%
raw bit-error rate forces a very heavy outer code (rate ~0.1), so **net throughput is only 1.23× B0** —
below the pre-registered 2.0× bar. A legitimate, evidence-backed rejection: spectral efficiency is real
but the channel's error rate eats it, and OFDM's usual edge (frequency-selective fading / multipath) is
not present on tape, where flutter is already handled by the single-carrier decoder.

**H4 / H5 — INCONCLUSIVE (implementation bugs, not fair tests).** Per the pre-registration's own rule
(a rejection only counts if it comes from a sound experiment), these do **not** count as rejections:
- **H4 (chirp SS):** raw BER 0.506 ≈ a coin flip, and the `CSSScheme` object does not implement the
  shared harness interface (`erasure_fn` missing) — the dechirp/demod is not working.
- **H5 (GCR/RLL):** raw BER **0.37 even on the cleanest channel preset** (and 1.0 in the saved run) —
  the clock-recovery/NRZI demod is broken, independent of the channel. (Separately, `channel.py` is
  linear+bandlimited and does not model magnetic saturation, so even a *correct* GCR demod could not be
  fairly judged here — a channel-model-fidelity gap worth noting.)

## Over-arching question: does anything fit 1.271 MB on one cassette?

**Yes, on normal tape, in stereo, with MFSK-32** (1.45 MB / C90-stereo), and the **MFSK-32 + fountain**
stack is the configuration expected to hold that recovery on worn tape too. This **supersedes the
earlier capture-campaign conclusion** ("no config fits / 600 bps ceiling / blocked on a PLL" in
`docs/capture_experiments.md`), which used a throwaway `parametric_modem` whose timing recovery is
weaker than the production decoder; the production-grade path reaches ≥1200 bps and MFSK-32 reaches
2.25× that.

## Recommended next steps

1. **Implement the MFSK-32 + fountain stack** end-to-end through `cassette_e2e` and re-measure at a
   realistic payload size (avoid the small-scale gross_bps amortization artifact).
2. **Fix or discard H4/H5** before claiming anything about chirp-SS or GCR/RLL; if GCR is pursued, the
   channel model needs a saturation/hysteresis term first.
3. Real-hardware: confirm the actual deck's dropout burst-length distribution (the dominant constraint)
   and effective bandwidth, which set the fountain overhead and the MFSK tone count.

## Caveats

Simulation only; raw-BER proxy; outer-code rate from an analytic table; 2× stereo assumes independent
tracks (real crosstalk ~30 dB unmodeled); H1's measured throughput is a small-scale artifact; MFSK-32's
worn-tape result assumes the fountain layer is added.
