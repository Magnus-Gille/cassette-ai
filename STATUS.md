Cassette AI viability sprint status

## 🏆 MILESTONE: real LLM bytes recovered byte-exact off a physical cassette (2026-06-09 pm)
Branch `codex/challenger`. **The acoustic dream works.** Recorded `master4.wav` (dual-rung) to a
real cassette, played it back acoustically (deck speaker → iPhone Voice Memos → iCloud), decoded:
the **wide-spaced-tone rung (WS_M16_K1_sp3 @ RS(255,111)) recovered 24,576 bytes of the real
cassette-LLM (`stories260K_int4.cass[:24576]`) BYTE-EXACT** — plus its 2 KB probe. raw BER 0.46%,
0/222 RS codewords failed (clean, not RS-rescued). Channel: clock 1.0009×, flutter 0.32%, SNR 40.4 dB
(matches the faithful sim). CSS rung (Codex) FAILED on real tape (raw BER 0.19–0.25) despite passing
in sim — a CSS-specific sim→real gap (pilot timing). So WS is the proven real-tape acoustic PHY.
Decoder: `m4_decode.py`; capture `captures/tape4_run1.wav` (gitignored). Result in REAL_DECODE_FINDINGS.md.

**The arc that got here** (all on branch `codex/challenger`, the Claude-vs-Codex competition branch):
characterized OUR real channel + folded it into a faithful sim (`real_channel_sim.py`, validated:
predicts the M16 failure the clean sim missed); proved one-shot EQ/calibration is dead (channel is
TIME-VARYING); creative "assault" found the win — **wide tone spacing + contrast detector** beats the
diffuse contamination floor (narrow-spaced k-of-M can't). CSS (chirp SS) had genie≈0 in sim but lost
on real tape. Wired path validated in sim: C4 OFDM QPSK ~4860 bps stereo, 3.28 MB/C90 (~€30 UCA222).

**NEXT (parked, see docs/ROADMAP.md "push the acoustic rate"):** we OVER-CODED ~5× (0.46% BER vs RS
correcting 28%). Reclaim it: lighter RS (RS(255,223) → ~650 bps → full model ~31 min), + denser WS
configs (real channel gentler than the pessimistic sim) → plausibly full 153 KB model in ~20–30 min
on the 90-min tape. Cheap first test (no re-record): measure actual per-codeword byte errors from
tape4 → exact achievable rate; recalibrate sim to the tape4 data point; then a master5 rate-ladder.

## Next-test challenger: master6 WS turbo-geometry ladder (2026-06-09 pm)
Latest local result files show `master5` already exists as a **same-PHY RS-rate ladder** for
`WS_M16_K1_sp3_N256`, with fastest rung RS(255,223) ≈ **656 bps** if it passes real tape.
That is the current "best in class" next test. To beat it, this session added a PHY-geometry
challenger rather than another RS-only rung:

- New artifact: `experiments/tape_v2/m6_master.py` builds `master6.wav` (7.41 min) and
  `master6_manifest.json`; `m6_decode.py` decodes it.
- Candidate PHY: **WS_M32_K2_sp2_N320** = 8 bits/symbol, 1200 gross bps, guard-spaced tones.
- Rungs: RS(255,95/111/127/159/191) = **447 / 522 / 598 / 748 / 899 bps**.
- Control rung: proven `WS_M16_K1_sp3_N256` at RS(255,223) = **656 bps**.
- No-channel validation: `python3 m6_master.py && python3 m6_decode.py master6.wav` -> **6/6
  byte-exact**, best no-channel rung `m32_turbo_rs191_4k` at 899 bps.
- Sim probe summary saved in `results/m6_turbo_candidate_summary.json`: M32K2 is unstable at
  full pessimistic contamination, but at 0.8x contamination RS95/111 pass 2/2, and at 0.6x
  every rung through RS223 passes 2/2. Because tape4 real BER (0.46%) was far gentler than
  the pessimistic sim, **M32K2 belongs on the next real-cassette test as the stretch rung**.
  Load-bearing pass: `m32_turbo_rs159_4k` (748 bps) beats M16 RS223 if it passes; `rs191`
  (899 bps) is the hero stretch.

## No-cable acoustic challenge: CSS-safe profile found (2026-06-09)
Branch `codex/challenger` is dirty with the acoustic assault work. New result this
session: the speaker -> cassette -> deck speaker -> phone microphone path is **not**
dead. The faithful real-channel sim says narrow-tone schemes fail because of the
measured ~25% diffuse, time-varying cross-bin contamination floor, but corrected
LoRa-style CSS avoids that failure mode.

Implemented `experiments/tape_v2/assault_css_optimize.py` and saved
`experiments/tape_v2/results/assault_css_optimize.json`. It sweeps CSS pilot density
and RS strength. Best no-cable safe point: **CSS-SAFE = SF6, 9 kHz sweep, fc 5 kHz,
pilot_every=2, Gray, +/-2 sample combining, interleaved RS(255,95), net 223.5 bps,
4/4 byte-exact stress seeds, max raw BER 0.039**. Upside rung: **CSS-FAST =
RS(255,127), net 298.8 bps, 3/4 stress seeds / 7/8 longer prior seeds**. The near
tie pilot_every=4 + RS(255,79) also passed 4/4 at 223.1 bps, but denser pilots are
preferred for physical timing margin.

Docs updated: `docs/REAL_CHANNEL.md` section 7, `docs/ROADMAP.md`, `REPORT.md`.
Online research checked and referenced in `REAL_CHANNEL.md`: Disney/ETH smartphone
acoustic transmission, 2026 acoustic-device evaluation survey, LoRa/CSS tutorial,
CSS matched-filter receiver design, and acoustic CSS work. **Next physical step:
record master4 with two acoustic rungs: CSS-SAFE + CSS-FAST, then decode the saved
phone-mic capture.** Hardware line-in remains the high-rate route, but it is not the
only path.

## Capacity push #1, tape test v2, first real decode (2026-06-08 eve)
Branch `acoustic-data-over-sound` (pushed to origin). Three threads this session:

**1. Capacity campaign #1** (`experiments/capacity/`, `docs/capacity_pushing_*.md`):
pre-registered + adjudicated 5 hypotheses vs the MFSK-32 frontier (1076 net bps).
Winners: C4 bit-loaded OFDM **3968 bps / 3.69× / 5.33 MB-C90-stereo** (sim; the prior
H3 OFDM reject was a TIMING bug, not flat-loading), C2 combinatorial k-of-M **2412 / 2.24×**.
Rejects (fair): C3 soft-FEC (burst channel), C5 FTN (below 1.5× bar). Gains don't stack
(competing PHYs). All sim @ 42 dB.

**2. Tape test v2** (`experiments/tape_v2/`): self-describing 16.65-min `master2.wav`
(gitignored, regen via `make_master2.py`) — 9-config robust→aggressive ladder + analyzer.
Analyzer now reports raw BER → `project_to_cassette` → net bps + FEC-recoverability (tests
the net-rate CLAIMS, not just unprotected-frame survival). Sim-worn proxy: C2 m32_k2 best
real-channel recoverable (~729 net bps); OFDM collapses on flutter.

**3. First REAL physical capture decoded.** Capture path that WORKED: iPhone Voice Memos →
iCloud → Mac `.qta` (NOT Continuity live-capture — that's clock-jittery & gated; see CLAUDE.md).
Fixed a sync bug (chirp0 search window too narrow for real lead-in) → global sync restored
(clock 1.0001×, sounder flutter 0.44%, **SNR 39 dB** — acoustic loop is great when quiet).
Residual ~0.1 BER = channel colouration; per-tone EQ cuts mfsk 0.25→0.096. **Not byte-exact
yet** — needs equalization + the FEC layer (deep-dive D2/D7). Findings:
`experiments/tape_v2/REAL_DECODE_FINDINGS.md`. Capture saved for offline iteration.

**Docs added:** `CLAUDE.md` (project instructions incl. the proven capture method),
`docs/ROADMAP.md` (plateau analysis: we're at 1–3% of Shannon; biggest levers are electrical
line-in + SNR + FEC, NOT modulation), `docs/audio_magic_{deep,overview}.html`.

**Scheduled:** autonomous deep-dive #2 (routine `trig_01BNAg13q4Q9q4pgK1F2wfzC`, fires 23:00
CEST 2026-06-08, branch `capacity-deepdive-2`) — 8 new hypotheses, runs in waves until quota,
commits+pushes each wave. Sim-only (can't touch local real captures).

**Next:** (local) finish real-capture decode = per-tone EQ (sounder-H(f) based) + FEC layer,
validate offline on the saved capture; (hardware) electrical line-in for stereo ×2 + OFDM.

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
