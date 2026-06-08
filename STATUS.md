Cassette AI viability sprint status

## DPD-inspired channel modeling + cassette-LLM (2026-06-08)
Branch: `acoustic-data-over-sound`. All work isolated under `experiments/dpd/`
(uses a FROZEN modem copy so the other agent's edits don't interfere). Full writeups:
`experiments/dpd/FINDINGS.md`, `MASTER_RESULTS.md`, `cassette_llm/MODELS.md`.

**Thesis (DPD): SUPPORTED, re-scoped.** Measured the cassette->speaker->iPhone channel.
It is GOOD on average (~13 dB/carrier SNR, ~50 dB markers, wow 0.19%) but has deep
frequency-selective NULLS; flat OOK + carrier-major interleave turns each null into a
byte burst that exhausts RS. Receiver-side channel-aware ERASURE decode (no re-record):
flat 7/50 -> 13/50 (`offline_proof.py`); deployable decision-directed 7/50 -> 12/50
(`adaptive_decode.py`, found 1 RS miscorrection -> CRC mandatory). Cross-model debate
with Codex (`debate/`): converged that the avenue is fruitful when re-scoped as
"live per-carrier CSI receiver + lower-PAPR, soft-coded waveform"; "DPD" label dropped
(can't pre-invert 10 unknown rooms -> intelligence lives in the phone app).

**New 15-min master recorded + analyzed** (`master_recorded.wav`, 12.7 min, clock 0.889).
Key results (`deep_analysis.py`, `channel_model.py`):
- Two FREE levers STACK: low-PAPR rendering (TX master) + erasure decode (RX) take
  byte-exact yield 21/66 -> 41/66 (~2x); 467 gross bps went 1/11 -> 9/11. Low-PAPR
  win = cleaner all-ON markers (sync/gain), NOT data SNR (phase-0 vs low-PAPR SNR identical).
- Lesson: reliable rate is gated by carrier-count vs nulls, not gross bps. Frontier
  ~333 -> 467 gross bps with both levers. PAPR/IMD-floor metric itself inconclusive (~2 dB).
- Cassette capacity: ~20 net data B/s byte-exact -> ~70 KB (C60), ~106 KB (C90), ~141 KB
  (C120); ~1.8x more in bit-loading/soft-FEC headroom.
- **Analysis gotcha (reusable):** tight 0.35 s frame gaps + cassette DRIFT (+-0.65 s over
  12 min) break global-clock frame slicing -> locate frames by their pilot markers instead.

**Cassette-LLM proof** (`cassette_llm/`): Karpathy stories260K (260K params, 512-vocab),
int4-quantized to a real 150 KB payload (`stories260K_int4.cass`, 129 KB gzipped) that
STILL writes coherent TinyStories. Fits a C120 today / C90 with headroom. `chat.py` is
an interactive playground (fp32 vs int4 toggle). ternary (65 KB, C60) needs QAT - post-hoc
breaks it. Lesson: the 512-token VOCAB is what makes it fit (TinyStories-1M is 48.6 MB
because of its 50K vocab). Grabbed 2 more (`cassette_llm/extra/`): **mnist-12.onnx**
(25.5 KB, MIT, RUNS - classifies digits, fits any tape) and **delphi v0-mamba-200k**
(state-space LM, license NONE-declared, int4=479 KB - over one cassette: 4096 vocab + 64 KB
tokenizer bloat). Candidate research + licenses in MODELS.md.

**License notes:** stories260K + llama2.c = MIT (free, incl. commercial; keep notices).
TinyStories *dataset* = CDLA-Sharing-1.0 (doesn't encumber trained models). ⚠️ roneneldan
TinyStories *model* repos declare NO license; ⚠️ delphi mamba none-declared; ⚠️ avoid
fxmarty/resnet-tiny-mnist (GPL-3.0). TinyStories "update": V2 dataset (GPT-4-only) +
karpathy/tinystories-gpt4-clean (Feb 2026) exist; original tiny models unchanged.

**Data preservation:** `experiments/dpd/master_recorded.wav` (70 MB, the irreplaceable
tape capture) and `master.wav` (76 MB, regenerable via `make_master.py`) are GITIGNORED
(no LFS on this repo). Back up master_recorded.wav externally or set up git-lfs to version it.

**Next:** soft-decision FEC/LLR bakeoff (offline, Codex's #3); wire encode->tape->decode->
infer full loop; QAT-ternary of a ~1M model to fit a C90 with better stories.

## Acoustic data-over-sound modem + cassette-in-the-loop (2026-06-07)
Built a working OFDM acoustic modem and proved a real cassette stores/returns digital
data **byte-exact**, read back acoustically (no special hardware).
- Paths proven: laptop speaker -> air -> iPhone mic (byte-exact to ~467 bps gross),
  AND the full loop laptop -> TAPE -> deck -> speaker -> iPhone mic -> decode (byte-exact).
- Stack: K parallel OOK carriers (1500-7000 Hz) + 7800 Hz pilot framing + periodic
  re-sync markers (tracks clock drift) + Hann demod + carrier-major interleave + Reed-Solomon.
- Tape BATCH run (71-experiment master): reliable frontier ~250 bps; most faster configs
  sit just past FEC. Acoustic readback is SNR-limited (~rms 0.03 before mic clipping).
- Bottleneck = iPhone Continuity clock drift (0.74-0.88x, sample drops) + the acoustic hop.
  Unlock = electrical line-in (Behringer UCA222/UCA222, ~EUR30) -> removes both.
- Key gotchas (see docs/acoustic_modem_lab_log.md): Dolby NR must be OFF both ends;
  record level ~7.0 (8.5 saturates -> intermod); readback speaker ~55 (rms ~0.04, no clip).
  Pre-flight LEVEL CHECKLIST SOP added (Claude prompts levels before each take).
- Tools: scripts/acoustic_ofdm_modem.py (gen/decode), acoustic_{rate_sweep,multitone_probe,
  mfsk_probe}.py, tape_batch_{gen,decode}.py. Research survey: docs/acoustic_modem_research.md.
- Next: UCA222 line-in run (full throughput frontier); DBPSK per-carrier + 2D interleave +
  cyclic prefix (predicted to clear the batch).
- Distribution note: a 3.5mm cable is enough to WRITE to tape, but NOT to READ
  (laptops/phones have no line-in; combo jack is mic-only) -> read needs acoustic (slow) or USB interface.

## Digital sprint (prior, v3)
Phase: v3 final digital sprint generated.
Verdict: do not proceed to model-payload physical prototyping; channel-validation-corrected simulation drops clean-decode below the acceptance threshold.
Best digital tuple: 16QAM 7200 sym/s, Hamming(7,4), interleaving 64, hardened modem, tiered UEP. UEP encoded TinyStories-1M size 1.271 MB, but corrected-channel Monte Carlo clean-decode is 0.075 over 80 runs.

Ad hoc research artifact, 2026-05-07: `RESULTS/carmenta_customer_competitor_report.html` contains an online public-source sweep of Carmenta's named customers, downstream end-user signals, partners, competitors, and press/coverage.
