# Cassette-AI — capacity roadmap & remaining research

_Last updated 2026-06-08._

## Where we are vs. the ceiling

The hard wall is Shannon: `C = B·log₂(1 + SNR)`. Against real tape numbers we are
currently at **1–3 % of Shannon** — the gap is flutter, nonlinearity (−10.5 dB IMD),
and the missing FEC layer, **not** missing modulation cleverness.

| Channel | BW | SNR | Shannon/track | We get | % |
|---|---|---|---|---|---|
| Acoustic loop (harsh) | ~11 kHz | ~13 dB | ~48 kbps | ~700 net bps | ~1.5 % |
| Sim "normal" | 11 kHz | 42 dB | ~150 kbps | 1–4 kbps | 1–3 % |
| Good deck, electrical | ~15 kHz | ~50 dB | ~250 kbps | — | — |

Practical heroic-effort ceiling ≈ 10–30 % of Shannon (flutter/azimuth/IMD eat the rest).

## Current frontier (simulation, `docs/capacity_pushing_results.md`)

- Baselines: B0 BFSK **478 net bps**; MFSK-32 **1076 net bps** (1.45 MB/C90-stereo).
- Campaign #1 winners: C4 bit-loaded OFDM **3968 bps / 3.69× / 5.33 MB** (sim only),
  C2 combinatorial k-of-M **2412 bps / 2.24×**. C4 **collapses on real flutter**;
  C2 is the real-tape champion (non-coherent).

## Remaining research, prioritized (≈5–20× collective headroom, mostly NOT modulation)

1. **Electrical line-in (hardware, ~€30 UCA222).** The gate. Removes acoustic hop +
   most flutter; SNR +~30 dB; unlocks higher-order QAM and the stereo ×2 multiplier.
2. **SNR engineering (~2–4×).** Channel-matched pre-emphasis, record-level vs IMD,
   Type II/IV tape. Each +6 dB ≈ +1 bit/symbol/subcarrier.
3. **FEC layer (~1.3–1.7× net, and turns "fails" into "recovers").** Deep interleave +
   LDPC/turbo + RaptorQ fountain. The projection *assumes* an outer code we never built.
   **This is also what's needed to byte-exact-decode the real captures** (see below).
4. **Flutter/timing tracking.** Continuous-pilot PLL so coherent OFDM/QAM survives the
   real loop — the sim→real bridge.
5. **Empirical characterization.** More decks/tapes/sides → real burst distribution.
6. **Modulation (~plateaued, ~1.1–1.3× left).** Only the C2×C4 hybrid (index modulation
   on active subcarriers) is untested.

Practical reliable plateau ≈ **a few–several MB per C90** — ~20× the 150 KB quantized
LLM already proven to fit. The model-on-a-cassette goal is **not capacity-limited** any
more; it's reliability- and reader-hardware-limited.

## Scheduled work

- **Deep-dive campaign #2** (routine `trig_01BNAg13q4Q9q4pgK1F2wfzC`, fires 2026-06-08
  23:00 CEST, branch `capacity-deepdive-2`): 8 new hypotheses (pre-emphasis, interleave+
  LDPC/fountain, flutter PLL, combinatorial-OFDM, live CSI bit-loading, probabilistic
  shaping, concatenated soft FEC, 4-track diversity), each on sim **and** harsh-real-proxy
  channels; then stacks winners; runs in waves until quota, committing/pushing each wave.
  Sim-only (cloud) — cannot touch the local real captures.

## Real-tape decode status (local task, NOT in the scheduled run)

First physical capture decoded: **sync bug fixed** (chirp lead-in window), channel is
**great** (39 dB / 0.44 % flutter), data ~90 % recoverable per symbol. **Not byte-exact yet** —
needs (a) per-tone equalization (sounder-H(f)/ON-gain based; blind EQ already cuts mfsk
0.25→0.10) and (b) the FEC layer. Capture saved (`experiments/tape_v2/captures/`), so this
is iterable offline. Details: `experiments/tape_v2/REAL_DECODE_FINDINGS.md`.

## Later — product & UX ideas (parked 2026-06-09)

- **Companion phone app** — record tape playback + decode on-device + show progress
  ("loading your AI…"), then run the recovered tiny model. The natural endgame packaging
  of the acoustic / zero-hardware path. BLOCKED ON: real-audio decode robustness must
  land first (the app wraps a working decoder, can't substitute for one).
- **Data-flow visualization** — visualize the decode pipeline: recovered spectrogram,
  per-frame raw BER, tracker lock/desync over time, RS-correction heatmap, bytes-recovered
  progress. Doubles as (a) a debugging tool for sim-vs-real gaps and (b) a demo artifact.

## Immediate technical blocker (2026-06-09)
First physical recording of master3 (real cassette-LLM) captured CLEANLY (sounder: 40.6 dB
SNR, 0.31% flutter, clock recovered) but decoded **0/3 — chance BER on every payload**. The
deep-dive `make_tracked_combo` modem was only ever sim-tested; it does not survive real
acoustic audio (coloration + sync/numerical edges, same class as the dd#1 real-capture gap
fixed last night for the OLD modem). Capture saved (`captures/tape3_run1.wav`) for offline
debug. NEXT: harden the tracked combinatorial demod for real audio (per-tone equalization +
robust per-frame preamble sync + fix the dd_common matmul divide-by-zero), validate on the
saved capture, THEN re-attempt. The tape/channel is not the problem — the decoder is.

### master4 PHY re-tier — measured on the master2 real capture (2026-06-09)
Mapped which modem configs survive OUR real channel via the hardened demod + genie ceiling
on `captures/voicememo_run1.wav` (tool `experiments/tape_v2/m2_modem_survival.py`, results
`results/real_modem_survival.json`; see `REAL_DECODE_FINDINGS.md` for the full table).
Decisive results: the real lever is **K (simultaneous tones), not symbol length N** —
K>=4 collapses (genie BER 0.36/0.55), K<=2 is the only viable regime, and the longest
symbol (M48,K6) is the worst. **c2_m32_k2 (M32,K2,N=159) is the only config that is
RS-closable on our channel** — genie byte-error rate 0.164 < robust-RS ceiling 0.251,
winning on error CONCENTRATION (its genie bit-BER ~0.088 merely ties M16, but K=2 packs
those errors into far fewer bytes). RIDER: only the GENIE closes it; the achievable
concentration-lock tracker still loses lock (raw byte-ER 0.637). master4 = M32,K2 PHY +
a stronger timing/detection front-end (pilot/known-symbol aid). The sim's omission of
reverb/leakage/AAC is WHY it over-rewarded high-K short-symbol PHYs.

### Sim/real gap CLOSED — improved simulator built + validated (2026-06-09)
Extended the simulator with the real-channel terms `src/channel.py` lacks, in a NEW
wrapper `experiments/tape_v2/real_channel_sim.py` (the frozen `cassette_channel` is
untouched): (1) a **diffuse leakage/reverb tail** = the length-INDEPENDENT ~25% cross-bin
floor (reverb + room/speaker/mic + AAC), (2) **calibrated HF rolloff** from the smoothed
measured H(f), (3) an **adjacent-bin ISI smear** = a fixed-time tail whose corrupting
fraction shrinks with symbol length (reproducing the 0.112 M16 -> 0.047 M32 split), plus
realistic residual flutter. Calibrated via `experiments/tape_v2/validate_real_sim.py`
(params in the `_sim` block of `real_channel_params.json`).
**Validation (results/real_sim_validation.json):** the OLD sim wrongly blessed M16,K2
(genie byte-ER 0.014, RS trivially closes); the NEW sim FLOORS M16 (genie byte-ER 0.358 >
robust-RS ceiling 0.251 = RS-uncloseable, bit-BER 0.105 in the measured real band) while
reproducing M32,K2's symbol-length advantage (lower byte-ER 0.292, near/under ceiling). The
improved sim would have PREDICTED the master3 M16 failure. master4 recommendation:
**combinatorial M32,K2 (N=159) + robust interleaved RS(255,127)**, with the load-bearing
rider that a pilot/known-symbol timing front-end is required to realise the genie ceiling.
Full write-up: `docs/REAL_CHANNEL.md` section 5.

### Training-based channel EQUALIZATION — tested, does NOT crack the wall (2026-06-09)
Tested whether a KNOWN training sequence (the global chirp + 64-tone Schroeder sounder, both
already in every capture) lets us estimate the COMPLEX channel H(f) (mag + PHASE) and
EQUALIZE/deconvolve the ~25% diffuse off-tone-leakage floor — the ISI that floors all
configs. Tool `experiments/tape_v2/eq_train_test.py`, results `results/eq_train_results.json`.
**DECISIVE: the channel is TIME-VARYING.** Two sounder reps ~4 s apart give complex H(f)
phases that disagree by **~69-78 deg** (after removing a bulk delay) in BOTH captures
(tape3 has no AAC, so flutter per-symbol phase jitter is the dominant cause; AAC adds to it).
An LTI reverb would give identical H(f); it does not — so a single trained H(f) is stale by
the time the data plays and CANNOT invert the floor. Complex MMSE EQ makes it WORSE
(M32 distant leakage 0.020 -> 0.233, genie byte-ER 0.40 -> 0.68); no EQ mode closes RS on
genie OR achievable. **The diffuse floor is NOT an equalizable LTI reverb — it is
non-stationary phase + AAC, irreducible by static training EQ.** master4 must NOT spend a
front-loaded calibration block on equalization; if EQ at all, it must be per-symbol
pilot-aided/adaptive (track phase continuously), a bigger PHY change than a preamble. The
proven levers stand: M32,K2 + interleaved RS + a phase-robust per-symbol timing front-end.
Full write-up: `docs/REAL_CHANNEL.md` section 6.

### Acoustic modulation search through the FAITHFUL sim — verdict PARTIAL (2026-06-09)
Did NOT give up on the "phone next to the speaker" path: searched for a modulation that beats
the ~25% diffuse cross-bin floor, all through the VALIDATED `real_channel_sim.py`
(`experiments/tape_v2/assault_acoustic.py`, results `results/assault_acoustic.json`). Tested
(a) M32,K2 baseline, (b) WIDE-spaced low-M MFSK (the "separate tones past the smear reach"
idea — **NEGATIVE**: low-M is *worse*, genie ~0.18-0.36; the diffuse floor spreads over ALL
bins so fewer bins concentrate more contamination and K=1 has no error concentration),
(c) M32,K2 with x2/x3 SYMBOL REPETITION + energy-combine. Also tested LoRa-style CSS/chirp
spread-spectrum directly — **near chance (~0.47-0.50)**: spread energy competes head-on with
the equally-broadband diffuse smear, so processing gain does NOT materialise.
**Result:** x3-repetition M32,K2 drives the GENIE byte-ER to 0.087 (RS-closable) — diversity
DOES help the ceiling — but the ACHIEVABLE (real tracked) byte-ER stays 0.34-0.66, above the
0.20 RS margin, for EVERY config. The wall is now confirmed to be the per-symbol TIMING
front-end (the concentration-lock tracker loses lock on K-of-M under contamination), not the
diffuse floor itself for the diversity schemes. **Honest verdict: PARTIAL** — genie-closable
with diversity, but not achievable-closable without a pilot-aided timing front-end (the same
load-bearing rider the survival map and EQ test already flagged). Acoustic byte-exact remains
uncracked open-loop.

### HYPOTHESIS B (REVISITED) — CSS done CORRECTLY beats the wall (2026-06-09)
The earlier CSS attempt above ("near chance ~0.47-0.50") shared the H4
negative-frequency-fold bug: it took `np.real()` of a complex baseband chirp then
cast the real RX audio straight back to complex and dechirped, folding the image.
Rebuilt cleanly in `experiments/tape_v2/assault_css.py` on the canonical LoRa CHIP
GRID (base phase pi(n^2/N - n), symbol s = x exp(j2pi s n/N)), real PASSBAND at
carrier fc, RX = bandpass -> analytic(Hilbert) -> downconvert -> resample to N
chips -> dechirp -> FFT. **No-channel sanity BER = 0.0000** (SF6-9; where H4
died). Through the FAITHFUL `real_channel_sim`: **GENIE bit-BER ~0.000** (vs
0.09-0.18 for every tone scheme) on BOTH master3 and master2 — the spread-spectrum
processing gain averages out the diffuse cross-bin floor exactly as theory says,
the FIRST scheme to clear the wall at the ceiling. Achievable path uses the
load-bearing **pilot-aided timing aid** (known pilot every `pilot_every` syms locks
the boundary; smooth flutter drift interpolated between) + Gray coding + incoherent
+/-2 combining: byte-ER 0.164 (master3) / 0.215 (master2/AAC), and the full
interleaved RS(255,127) roundtrip closes **byte-exact on 7/8 flutter realizations**.
Net ~299 bps. Then `experiments/tape_v2/assault_css_optimize.py` swept pilot density
and RS strength on the adversarial seed set. The all-clean no-cable profile is now:
**CSS-SAFE = SF6, 9 kHz sweep, fc 5 kHz, pilot_every=2, Gray, +/-2 combining,
RS(255,95), net 223.5 bps, 4/4 byte-exact seeds, max raw BER 0.039**. CSS-FAST =
same PHY with RS(255,127), net 298.8 bps, 3/4 seeds. **Verdict: SURVIVES IN THE
FAITHFUL SIM AT SAFE RATE** — genie demolishes the wall, and the stronger RS rung
turns the near-survivor into an all-clean stress result. Recommendation flips to
**record master4 with two CSS acoustic rungs: CSS-SAFE + CSS-FAST**. Full write-up:
`docs/REAL_CHANNEL.md` section 7; results `results/assault_css_optimize.json`.

### HYPOTHESIS A (REVISITED) — WIDE-SPACED tones + GUARD BANDS crack the wall (2026-06-09)
The earlier `assault_acoustic.py` wide-spacing attempt was NEGATIVE because it used extreme
low-M (fewer bins concentrate MORE diffuse contamination) with NO guard bins and the standard
absolute top-K detector. `experiments/tape_v2/assault_widespace.py` does it correctly: keep a
moderate M but space the tones `spacing` FFT bins apart with EMPTY GUARD BINS between them
(so the adjacent-smear skirt lands in ignored guards, not on neighbour data tones), a longer
symbol N for finer bins, K<=2, and a CONTRAST detector (tone energy minus its own guard-bin
pedestal, subtracting the local diffuse floor). Sweep of 194 configs through the FAITHFUL
`real_channel_sim`; the legacy 1-bin M16K2 baseline reproduces the VALIDATED genie floor
(0.196 BER, RS-uncloseable), confirming the evaluator is honest. **Winner: WS_M16_K1_sp3_N256**
(M16, K1, spacing 3 bins, N=256 -> 188 Hz bins, 562 Hz guards, tones 400-9000 Hz, 4 bits/sym):
genie byte-ER 0.078, achievable (non-genie tracker) byte-ER 0.109. **TRUE end-to-end RS-closure**
(`m3_codec` RS(255,127) + global interleave, frame-by-frame through the sim, achievable demod):
**BYTE-EXACT 3/3 seeds on master3 (tape) at FULL measured contamination** — and byte-exact all
the way down to contamination 0.2, so **NO physical close-coupling is required on the tape path**.
master2 (AAC) is PARTIAL (2/3 seeds; AAC frame nonlinearity costs one bad seed 5/126 cw). Note
the guard must clear the smear with margin: sp2 (480 Hz guard) FAILS true closure while sp3
(562 Hz) survives — the per-symbol aggregate metric does not see this, so the frame-level
RS-closure is the load-bearing gate. **net ~373 bps** (gross 750, robust RS 0.498). Unlike the
CSS path this needs NO pilot-aided front-end — the plain concentration-lock tracker suffices,
at a HIGHER rate. **Verdict: SURVIVES on the tape channel.** The wall was the 1-bin tone packing,
not the channel. Recommend recording master4 with WS_M16_K1_sp3_N256 (and CSS as the
diversity/AAC-robust alternative). Tools: `experiments/tape_v2/assault_widespace.py`; results
`results/assault_widespace_{master3,master2}_contrast.json`. Full write-up: `REAL_DECODE_FINDINGS.md`.

### HYPOTHESIS C — the WIRED / line-in path WORKS (2026-06-09)
Built `experiments/tape_v2/assault_wired.py` (results `results/assault_wired.json`): a wired
channel model = the FROZEN `cassette_channel` at a decent-deck operating point (50 dB SNR,
13 kHz band, post-sync RESIDUAL flutter ~0.046% — the same 0.15x residual the validated
acoustic sim uses, since the global resample + per-symbol tracker remove the bulk) with **NO
acoustic contamination** (no reverb / room-IR / speaker+mic / AAC). This models deck
LINE-OUT -> USB interface -> lossless PCM, removing the acoustic hop while keeping tape
physics. **Every high-rate config survives byte-clean:** C2 combinatorial M16/M32/M48 (genie
BER 0, achievable byte-ER ~0.003, RS-closable), and the C4 OFDM frontier QPSK (gross 3897 bps,
CRC-clean, achievable BER 0). On a conservative WORN deck (44 dB, 11 kHz, 0.09% residual)
the QPSK frontier still passes CRC ~0.88 (achBER 0.5%) — the mid RS(255,159) rung closes it
with margin. **WIRED MASTER: C4 OFDM QPSK + RS(255,159) rate 0.624 -> net 2430 bps/channel,
4860 bps STEREO (L+R both available on the wired path), ~3.28 MB per C90.** Hardware: any
class-compliant USB interface with line-in (Behringer UCA222 ~EUR30, or Focusrite Scarlett
Solo ~EUR110). The wired path is the recommended route to high-rate byte-exact cassette I/O;
the acoustic path remains capped by spectral contamination + the timing front-end.

### ADJUDICATION — the acoustic path now LIVES; wired is the high-rate route (2026-06-09)
Cross-examined all three assaults genie-vs-ACHIEVABLE with the true end-to-end RS roundtrip as
the sole gate, and independently re-ran the load-bearing closure tests. Full write-up:
`docs/ACOUSTIC_ASSAULT.md`. Verdicts:
- **Acoustic LIVES, two ways.** `WS_M16_K1_sp3_N256` (wide-space + 562 Hz guards + contrast
  detector, no pilot) is byte-exact through the faithful sim on the ACHIEVABLE tracker + robust
  RS — verified here: sp3 byte-exact (0/126 cw) while the sp2 decoy and the legacy 1-bin base
  both FAIL (126/126), confirming the evaluator is honest. Net ~374 bps, ~0.25 MB/C90, NO
  physical close-coupling needed (closes at full measured contamination). **Honesty correction:**
  on a deep 40 KB payload the robust rung is MARGINAL (re-run: 2/3 seeds exact, one fails 6/315
  cw, byte-ER 0.019) — so master4 should drop one RS rung (RS(255,111), ~326 bps) for margin.
  CSS (SF6, pilot_every=2, RS(255,95), 223 bps, 4/4 stress seeds) is the diversity/AAC-robust
  alternative (genie ~0 via processing gain). The plain acoustic TONE PHY still FAILS
  (`assault_acoustic.json`: achievable byte-ER 0.34–0.66, no survivors).
- **Wired SURVIVES decisively** — C4 OFDM QPSK + RS(255,159) → 4860 bps stereo, 3.28 MB/C90,
  byte-clean; ~EUR30 Behringer UCA222. The recommended primary route.
- **Next physical steps:** (acoustic) record master4 = WS_M16_K1_sp3_N256 @ RS(255,111) headline
  + CSS-SAFE second rung, prefer lossless phone recording; (wired) UCA222 line-in, master4-wired
  = C4 OFDM QPSK + RS(255,159).

### master4 ASSEMBLED — dual-scheme recordable master + decoder (2026-06-09)
Integrated the two surviving acoustic schemes into a single recordable master and a matching
decoder. `experiments/tape_v2/m4_master.py` writes `master4.wav` (16.8 min, one side; gitignored)
+ `master4_manifest.json` + `sidecars_m4/`. Layout = lead silence -> up-chirp -> ~45 s sounder ->
SCHEME-1 (wide-spaced) payloads -> SCHEME-2 (CSS) payloads -> down-chirp -> tail. Payloads:
WS `ws_test2k` (2 KB random) + `ws_llm24k` (`stories260K_int4.cass[:24576]`) at RS(255,111);
CSS `css_test2k` (2 KB random) + `css_llm6k` (`[:6144]`) at RS(255,95). WS frames modulated via
`assault_widespace.build(16,1,3,256).modulate` and read with `_demod_frame_achievable(...,"contrast")`
using a per-tone EQ derived from THIS recording's sounder H(f); CSS modulated as one
`modulate_piloted(syms, pilot_every=2)` stream and read with `demod_piloted`. `m4_decode.py` recovers
timing (global chirps), reads each scheme, runs `decode_payload`, and byte-compares to the sidecar.
**Validation (all byte-exact, verified against sidecars):** (A) no-channel decode of master4.wav =
4/4 byte-exact, raw BER 0, 0 RS fail. (B) through faithful `real_channel_sim` (`m4_sim_validate.py`):
capture=master3 seeds 0,1 = 4/4 each (raw BER 0.002-0.026, 0 RS fail); capture=master2 (AAC) seeds 0,1
= 4/4 each (raw BER 0.006-0.026, 0 RS fail). The dual-scheme master is ready to record;
`RECORD_ME_v4.md` has the capture procedure.

## Next: push the acoustic rate (parked 2026-06-09, after the milestone)
master4 proved WS_M16_K1_sp3 @ RS(255,111) = ~326 net bps recovers real LLM bytes byte-exact
on tape. BUT the real channel left HUGE RS margin: raw BER 0.46% (~3.6% byte err) vs RS(255,111)
correcting 28% -> we over-coded ~5x. Levers to reclaim it (test in sim/offline FIRST, no re-record):
  1. Lighter RS: at 0.46% BER, RS(255,223) (rate 0.875, corrects 16/255) closes -> ~650 net bps
     -> full 153KB model in ~31 min (from 63).
  2. More bits/sym: real channel is far gentler than our (pessimistic) faithful sim, so denser WS
     configs it rejected may now hold -> M32/M64 wide-spaced (5-6 b/sym) or shorter N. Stacked: ~1000-1300
     net bps -> full model ~20-25 min.
  3. Two working rungs (fix CSS sim->real gap, or two WS configs safe+fast) for redundancy.
CHEAP FIRST EXPERIMENT (no re-record): measure the ACTUAL per-codeword byte-error distribution from
the tape4 capture (captures/tape4_run1.wav, ws_llm24k) -> exact lightest RS that closes -> real
achievable rate. Then re-calibrate the faithful sim to this tape4 data point + sweep denser WS.
Then ONE master5 rate-ladder tape to confirm, then the full model. Goal: full 153KB LLM in ~25-30 min.
