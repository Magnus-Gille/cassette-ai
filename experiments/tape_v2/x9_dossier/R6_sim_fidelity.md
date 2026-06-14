# R6 — Simulator Fidelity Audit + master9 Gate Design

**Date:** 2026-06-10 · **Branch:** deepdive-3-overnight · **Author:** R6 subagent
**Scope:** Audit `experiments/tape_v2/real_channel_sim.py` (FROZEN channel) + `sim_v2.py`
(AAC-roundtrip wrapper) for *dense-OFDM / DQPSK* fidelity, and pre-register the
master9 SHIP/HOLD gates. Empirical probes: `experiments/tape_v2/x9_sim_probes.py`
→ `results/x9_sim_probes.json`.

**Headline verdict.** The sim is **trustworthy in the frequency domain**
(off-bin contamination, HF rolloff, RS-cliff for tone-grid modems — honest to
slightly pessimistic) and **catastrophically optimistic in the timing/phase
domain**. Measured: the sim has **~100–200× too little flutter-jitter energy
above 5 Hz**. That single defect fully explains the m8 sim→real disaster —
**all three N1024 DQPSK rungs passed the sim gate (2/2 seeds) and died totally on
the real tape (35–37/37 codewords failed)**, while the N512 rung that the sim
rated equally was the one that actually won (934 bps, 0 cw failed). master9 gates
below are built specifically to refuse to trust the sim where it is blind.

---

## 1. How the sim models each phenomenon (mechanism walk-through)

The pipeline is `sim_v2.channel_v2(x, profile, aac)`:
`real_channel(...)` (tape+room physics) **then** an optional real AAC round-trip.
`real_channel` itself wraps the FROZEN `src/channel.py::cassette_channel` and
layers three measured terms. Full chain, in order:

### 1a. Flutter / wow — `src/channel.py` time-warp (THE WEAK LINK)
`cassette_channel_diagnostics` (lines 52–69):

```python
inst = a1*sin(2π·0.55·t + p1) + a2*sin(2π·4.8·t + p2) + 0.18·white   # a1≈N(1,.08), a2≈N(.45,.05)
inst = inst / rms(inst) * wow_flutter_wrms
warped_t = t + cumsum(inst)/fs
y = interp(t, warped_t, y)                                            # resampling trajectory
```

- **Model class:** a resampling trajectory (so it correctly produces frequency-
  proportional phase error 2π·f·τ on every tone — the right *kind* of impairment).
- **Spectrum:** **two discrete sinusoids (0.55 Hz wow, 4.8 Hz flutter) + 18 %
  broadband white** before rms-normalization. After normalization to
  `wow_flutter_wrms`, the *displacement* PSD is two delta spikes on a tiny floor.
  The instantaneous *timing-jitter* PSD (the thing the symbol-rate tracker sees)
  therefore has almost no energy between the spikes and essentially nothing above
  ~5 Hz (see §2, Table A).
- **Driven amplitude:** `real_channel` does **not** drive the full measured
  flutter. It applies `flutter = flutter_full × flutter_residual_frac` with
  `flutter_residual_frac = 0.15` (the "post-sync residual" assumption: the global
  chirp-resample + per-symbol tracker is *assumed* to remove 85 % of it). For
  tape7 that is 0.365 % × 0.15 = **0.055 % wrms** reaching the detector.

### 1b. HF rolloff — measured H(f) FIR (`real_channel`, add_hf, lines 132–138)
`_hf_fir` builds a 129-tap FIR whose magnitude follows the *smoothed* measured
`H_db_master3` sounder curve (`_smooth_db`, win=5, drops the −49 dB notch spikes
so the EQ doesn't ring). Applied via `fftconvolve`. This is honest: it is the
literal measured deck transfer function (300–11000 Hz, ~22 dB master3 rolloff).

### 1c. Adjacent-bin ISI — fixed-length short reverb tail (add_isi, lines 147–157)
A white exponential IR, `τ = adj_tail_samples` (20 samp), `g = adj_gain`, length
6τ, prepended with a unit direct path. Because the tail length is fixed in
**samples**, a longer symbol spends a smaller *fraction* of its window corrupted —
this reproduces the measured adjacent-bin shrink (0.112 @ M16/N77 → 0.047 @
M32/N159). Convolutional, so it smears a copy of the signal into ±1 bins.

### 1d. Diffuse floor — `diffuse_gain` reverb tail (add_reverb, lines 169–180)
The hard limit. A longer white exponential IR (`τ = reverb_tail_tau_ms ≈ 7.86 ms`,
length 8τ ≈ 63 ms), energy `g_diffuse` relative to the direct path, convolved in.
Being **convolutional** (a smeared copy of the signal), its cross-bin leakage
*fraction* is ~length-independent (matches the flat ~0.25 distant-bin floor that
kills 1-bin-spaced grids), yet a longer FFT still concentrates each true tone, so
M32 keeps its processing-gain edge. `diffuse_gain` = **0.65** (sim_v2 SIM2
override), vs 0.5 in the JSON `_sim` block (v1).

### 1e. AWGN — inside `cassette_channel` (lines 82–85)
Flat Gaussian at the profile SNR (tape7 = 36.4 dB; tape4 = 40.4 dB). Per-tone
SNR is excellent everywhere on the real tape (p10 ≈ 33 dB) — **noise is not the
limiter** and the model agrees.

### 1f. AAC round-trip — `sim_v2.aac_roundtrip` (the v2 addition)
mono → stereo 24-bit WAV → **real Apple `afconvert` AAC-LC, 48 kHz, ~205 kbps
CBR** → decode → mono, sample-aligned (codec priming delay measured once via a
chirp; here delay=0, residual −0.0004 samp, corr 0.99998). Applied *after* the
tape+room physics ("the phone encodes what it heard"), with a 0.95-peak
normalize/restore so the codec sees a healthy level.

---

## 2. Per-phenomenon fidelity verdict for DENSE-OFDM / DQPSK

All numbers from `x9_sim_probes.py`: inject a pure 4500 Hz tone (the DQPSK pilot
freq), recover instantaneous timing jitter τ(t) by heterodyne+unwrap, Welch-PSD
it, and compare against the **real m8 capture's continuous 4500 Hz DQPSK pilot**
(region 300–540 s, steadiest 8 s window @ 410–418 s). Seeds 0,1,2 on the sim.

### Table A — flutter timing-jitter RMS by band (the load-bearing measurement)

| band | sim aac-off | sim aac-on | **REAL m8** | **REAL / sim** |
|---|---|---|---|---|
| 0.05–1 Hz (wow) | 140.0 µs | 140.0 µs | 809.3 µs | **5.8×** |
| 1–5 Hz | 6.71 µs | 6.71 µs | 176.8 µs | **26×** |
| 5–23.4 Hz | 0.24 µs | 0.24 µs | 33.9 µs | **142×** |
| 23.4–46.9 Hz | 0.07 µs | 0.07 µs | 11.1 µs | **158×** |
| 46.9–200 Hz | 0.04 µs | 0.06 µs | 8.9 µs | **205×** |
| total | 140.1 µs | 140.1 µs | 838.6 µs | 6.0× |

> The 23.4 Hz / 46.9 Hz band edges are the **symbol-rate-tracking Nyquist** of
> N1024 (FS/1024/2 = 23.4 Hz) and N512 (46.9 Hz): a per-symbol pilot tracker can
> only follow jitter components *below* its symbol rate / 2. The sim has
> **0.07 µs** of jitter in 23–47 Hz; the real tape has **11.1 µs (158×)**. That is
> precisely the band the N1024 tracker must follow and cannot. Cross-checks at
> bandpass 80 Hz (tighter) give 5–23 Hz = 25 µs, 23–47 Hz = 7 µs — same ~100×
> gap, so this is not a pilot-window-contamination artifact (real pilot tonality
> 0.68; a 749 Hz sounder tone gives an even *higher* HF figure → 11 µs is a
> conservative lower bound).

**Why the sim is blind here:** its only AC jitter components are deltas at 0.55
and 4.8 Hz. PSD at 20 Hz: sim 2e-16 vs real 5e-11 s²/Hz — **a millionfold gap**.
Real cassette flutter is *broadband* (capstan/pinch-roller scrape, tape-pack
modulation, head contact) extending past 50 Hz; the two-sinusoid model captures
none of it. AAC on vs off changes the jitter spectrum by <30 % → AAC is **not**
the timing problem.

### Table B — pilot-tracker residual & resulting phase noise (per `pilot_tracker_residual`)

After the actual h4 EMA(α=0.5) pilot tracker runs over the measured trajectory:

| source | resid N512 | resid N1024 | phase noise @7500 Hz, N512 | @7500 Hz, N1024 |
|---|---|---|---|---|
| sim aac-off | 5.6 µs | 10.8 µs | 15.1° | 29.3° |
| **REAL m8** | 31.4 µs | 54.5 µs | **84.6°** | **147.1°** |

> QPSK decision boundary = **45°** rms ⇒ catastrophic. The sim says N1024 leaves
> **29°** (survivable; consistent with its 2/2 sim PASS). Reality leaves **147°**
> — a coin flip. N512 reality is 84.6° (still over 45°, but the decision-directed
> refinement + thicker RS127 pulled it back; the sim's 15° vastly understates
> even the rung that *worked*). **The sim under-predicts real data-carrier phase
> noise by ~5×, and ranks N1024 as the *safer* rung when it is by far the more
> dangerous.** Longer symbol = lower tracker update rate = the model's blind spot
> becomes the dominant impairment.

### Verdicts

| phenomenon | sim fidelity for dense-OFDM | evidence |
|---|---|---|
| **Flutter-ICI (93–375 Hz spacing)** | **NOT honest — optimistic.** Sim produces almost no flutter sidebands (jitter is ~DC). P3 (Table C) shows off-bin energy in sim is the *static reverb skirt*, not flutter modulation. A real dense grid would see flutter-ICI the sim can't generate. | Table A; P3 |
| **Phase noise / D8PSK margins** | **NOT honest — optimistic by ~5×.** Real per-symbol phase jitter ~85° (N512) / 147° (N1024) at 7.5 kHz vs sim 15° / 29°. D8PSK (boundary 22.5°) would look fine in sim and fail on tape. | Table B |
| **Reverb ISI for CP design** | **Honest-ish (geometry right, may be slightly short).** Diffuse τ≈7.86 ms is the *measured* tail; ISI ≈ 1.5 symbols at N256. CP length sizing off the sim's τ is defensible, but treat τ as a *point estimate* — stress it ±50 % (§4). | params; STATUS note (~8 ms tail) |
| **Off-bin / distant contamination (tone grids)** | **Honest to slightly PESSIMISTIC.** dg=0.65 matched 7/9 WS rungs; the one frequency-domain mismatch (m16k2_rs159) was sim-*PASS*/real-FAIL but that rung is a **fixed-grid non-self-tracking WS rung**, which the briefing flags as a *separate* known failure mode (no self-tracking front-end), not a contamination miscalibration. m16_rs191 sim is *pessimistic* (sim FAIL seed1 / real comfortable PASS). | §3; sim_v2_validation.json |
| **HF rolloff / AWGN / clock offset** | **Honest.** Literal measured H(f) and per-tone SNR; clock is a static resample the decoder removes. | §1b, §1e |

### Table C — P3: sim off-bin leakage vs spacing (sim only, no analysis window)

| N | bin width | adj1/main | adj2/main | distant/main |
|---|---|---|---|---|
| 256 | 187.5 Hz | 0.031 | 0.015 | 0.198 |
| 512 | 93.8 Hz | 0.049 | 0.025 | 0.251 |
| 1024 | 46.9 Hz | 0.092 | 0.047 | 0.332 |

> Note this *grows* with N — but that is the **diffuse reverb skirt** (a fixed-
> time convolution captured more fully by a longer FFT), **not** flutter-ICI.
> AAC on vs off barely moves it (≤0.001). So for a dense grid the sim models the
> reverb/codec contamination floor but is **blind to the flutter-driven ICI** that
> a real <375 Hz-spacing grid would suffer. **Do not trust the sim to bless any
> spacing tighter than the proven 750 Hz without a flutter-augmented re-run (§4).**

---

## 3. AAC question — the captures are now LOSSLESS (Voice Memos ALAC)

**Recommendation: run the faithful master9 sim with `aac=False`, and keep
`diffuse_gain` in the 0.55–0.62 range (with seed averaging), NOT 0.65.** Rationale,
with explicit evidence and explicit uncertainty:

1. **The explicit AAC stage already contributes ~nothing.** `sim_v2_validation.json`
   `aac_mechanism_check`: on the gate-defining m32_rs111 rung, `raw_ber_aac_true =
   0.1123` vs `raw_ber_aac_false = 0.1115` — `aac_clearly_worse = False`. The real
   afconvert AAC-LC at 205 kbps is transparent enough that it does not measurably
   add contamination on top of the diffuse floor. So removing it costs almost
   nothing in fidelity **and** removes the slow afconvert subprocess per call.

2. **`diffuse_gain=0.65` was over-fit to AAC captures and likely double-counts
   codec damage that no longer exists.** The dg=0.65 value was the *closest honest
   compromise* on AAC-era tapes where the binding constraint was "AAC kills turbo"
   (m32_rs111 must FAIL). It is openly documented as **gate-not-fully-met**
   (`gate_met=False`): the two constraints are mutually exclusive — m16_rs191 PASS
   wants **dg ≤ ~0.6**, m32_rs111 FAIL wants **dg ≥ ~0.65**. Since the masking-
   skirt mechanism that forced 562 Hz spacing was an *AAC* artifact (300 Hz died
   on AAC, survived nothing else), a lossless capture removes that adversary. The
   defensible lossless recalibration is the **dg ≤ ~0.6 branch the sim itself
   identified as the m16_rs191-PASS branch** — i.e. the value at which the
   frequency-domain rungs match the (now comfortable) real PASS.

3. **Honest uncertainty / caveat — do NOT over-relax dg.** dg is *not purely* AAC:
   it lumps reverb + room + speaker/mic + codec into one number. The m8 real tape
   still showed a substantial distant-bin floor (every fixed-grid WS rung failed
   at raw BER 0.07–0.19 on the lossless tape). So the contamination floor is
   *real and largely codec-independent*; dropping dg below ~0.5 would make the sim
   optimistic about tone-grid contamination. **The dg sensitivity (single-seed,
   noisy) from the m7 probes:**

   | dg | m16_rs191 | m32_rs111 | m32_rs159 |
   |---|---|---|---|
   | 0.55 | 0.020 | 0.055 | 0.084 |
   | 0.60 | 0.058 | 0.066 | 0.075 |
   | 0.62 | 0.070 | 0.092 | 0.078 |
   | 0.65 | 0.034 | 0.112 | 0.070 |

   (Non-monotone = single-seed noise; **always average ≥4 seeds for any dg
   decision.**) **Concrete recommendation: `aac=False`, `diffuse_gain=0.58`
   (mid-point of the 0.55–0.62 lossless branch), and re-validate against the m8
   real per-rung BERs before trusting master9 frequency-domain rungs.** Treat dg
   as a ±0.07 uncertainty band and stress it (§4).

> **Bottom line on AAC:** keeping `aac=True` is harmless-but-slow and risks the
> dg=0.65 double-count. Switch to `aac=False` and recalibrate dg downward against
> the lossless m8 tape. **But this only fixes the frequency-domain side. It does
> NOTHING for the timing-domain blindness, which is where master9 will actually
> die.** No dg value fixes flutter; see §4.

---

## 4. PRE-REGISTERED master9 GATES

Design principle: **the sim is allowed to grant a SHIP only for impairments it
models honestly; for the timing/flutter axis it is blind, so the gate forces a
flutter-augmented stress that emulates the missing ~100× HF jitter, and caps how
much the sim's timing-domain PASS can be trusted.** Pre-register before any
master9 tape is burnt.

### 4.0 Channel config (faithful sim)
- `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)` as nominal.
- Also run `profile='tape4'` (quieter take) as a sanity bound — master9 may sit
  between them.
- **All seeds set + logged.** Every cell averages a seed sweep; never trust a
  single seed (the m8 disaster's M16 rung flipped on one seed).

### 4.1 Seeds per rung
- **Nominal axis: 8 seeds** `{0..7}` (up from h8's 6; the sim's seed variance is
  the only honest source of margin signal it has).
- **Each stress axis: 4 seeds** `{0..3}` (h8 used 3; bump to 4 for a tighter
  fraction estimate).

### 4.2 Stress envelope (learned from h8's 96-cell matrix that validated DQPSK
N512, AND from the N1024 failure that h8's envelope was too weak to catch)

| axis | h8 value | **master9 value** | why |
|---|---|---|---|
| flutter_residual_frac | 0.15→0.30→0.50 | **0.15→0.30→0.60** | bump ceiling; but see HF-flutter axis below — *this knob does not help*, it only scales the benign 2-sinusoid spectrum |
| **HF-flutter injection (NEW, mandatory)** | — | **add broadband jitter τ with PSD flat to 60 Hz, total RMS = {0, 1×, 2×} of the measured real residual (Table A, 5–200 Hz ≈ 35 µs)** | the *only* axis that emulates the sim's documented 100–200× blind spot; gate decisions on long-symbol / dense-phase rungs MUST clear the 1× cell |
| SNR delta | −2, −4 dB | **−2, −4 dB** | unchanged (sim SNR is honest) |
| clock offset | (implicit) | **±0.15 % static resample** | exercises the decoder's chirp-resync (measured deck +0.117 %) |
| reverb τ | (fixed 7.86 ms) | **×{0.5, 1.0, 1.5}** | CP / ISI sizing margin; τ is a point estimate |
| AAC bitrate | 204.8k→96k | **drop** (captures lossless) — optional 256k ALAC-equiv = identity | no longer the adversary |
| seed sweep | {0..5} | **{0..7} nominal, {0..3} stress** | realization variance |

The **HF-flutter injection** is the centerpiece. Implementation: synthesize a
jitter trajectory `τ_hf(t)` as filtered white noise (Butterworth LP at 60 Hz,
flat-ish PSD), scale to target RMS, add to the channel's warp trajectory (or
post-warp resample). Calibrate "1×" to the measured real residual band-energy
(Table A: 5–200 Hz total ≈ 35 µs RMS). A rung that the sim passes only because it
never saw HF flutter will collapse at 1×, exactly reproducing the N1024 failure.
**Validation of the injection itself:** before trusting it, confirm it reproduces
the known ground truth — N1024 DQPSK must FAIL at 1× and N512 DQPSK must PASS at
1× (matching the real m8 tape). If it doesn't, the injection is mis-scaled; do not
ship gates built on it.

### 4.3 SHIP / HOLD rule per rung (pre-registered)

A rung is **SHIP** iff ALL of:
1. **Nominal:** ≥ 7/8 seeds byte-exact at (`aac=False`, dg=0.58).
2. **dg-pessimism:** ≥ 6/8 seeds byte-exact at dg=0.65 (defends the lossless-
   recalibration uncertainty — survive even if the floor is worse than estimated).
3. **HF-flutter 1×:** ≥ 3/4 seeds byte-exact with the 1× broadband-jitter
   injection (defends the documented timing blind spot — the gate that h8 lacked).
4. **SNR −2 dB AND flutter_frac 0.30 combo:** ≥ 3/4 seeds byte-exact.
5. **Margin floor:** mean **codeword-symbol (byte) error rate** across the nominal
   seeds ≤ **0.6 × (RS correction capacity)**, where capacity = (255−k)/(2·255)
   (symbol-level: RS191→0.125, RS159→0.188, RS127→0.251). Measure on bytes, not
   bits (RS corrects byte symbols; a byte fails if any of its 8 bits do, so
   byte-error-rate > bit-BER — comparing bit-BER to symbol-capacity would be
   optimistic). A rung whose sim byte-error-rate sits within 0.6× of its cliff is
   a HOLD: e.g. m16_rs191 ran at sim raw bit-BER ~0.034 (seed-dependent, flipped
   one seed to 31/43 cw failed) — already on the RS-191 cliff in sim, so seed
   variance + the sim's optimism is enough to eat the margin.

A rung is **HOLD** (carry as experimental, expect possible loss, never headline)
iff it passes 1,2,5 but fails the **timing** gates (3 or 4) — i.e. the sim likes
it but it leans on impairments the sim under-models. **The N1024 DQPSK rungs would
have been HOLD, not SHIP, under this rule.**

A rung is **REJECT** iff it fails nominal (gate 1) or the margin floor (gate 5).

### 4.4 Hard structural rules (non-negotiable, from the m8 lessons)
- **Self-tracking front-end is MANDATORY for every rung** (DQPSK pilot, or the
  0.25 Hz timing-trajectory h5/h6 front-end). Every fixed-grid WS rung failed on
  the lossless m8 tape; the sim cannot be trusted to catch that because its
  flutter is too smooth for a fixed grid to look bad. **Do not ship any
  non-self-tracking rung regardless of sim PASS.**
- **Prefer shorter symbols at equal net rate.** N512 beat N1024 on the real tape
  *because* its pilot updates twice as fast. Symbol length is a *timing-tracking*
  decision, not just an ISI/processing-gain decision. For any new rung, the
  shorter-symbol variant is the default; a longer-symbol variant is SHIP-eligible
  only if it clears the HF-flutter 1× gate (which it generally won't).
- **Carrier spacing ≤ 750 Hz is UNVALIDATED by the sim.** The sim is blind to
  flutter-ICI (§2, Table C). Any master9 rung with spacing < 750 Hz must be
  treated as HOLD until either (a) a flutter-augmented sim run blesses it, or
  (b) a physical tape proves it. The lossless-removes-562-Hz-constraint hope is
  *plausible but unproven* — gate it, don't assume it.
- **CRC32-per-codeword miscorrection guard stays on** (receiver-side; the manifest
  tables). A sim PASS with an undetected RS miscorrection is worse than a clean
  fail.

### 4.5 Recommended master9 rung ladder (gate-driven)
1. **Anchor (SHIP, proven):** `DQ_P10_N512_sp8 RS127` — the 934 bps record. Re-burn
   to confirm reproducibility; it is the floor.
2. **Push (SHIP-candidate):** a *shorter or equal-symbol* DQPSK variant that adds
   data carriers or a thinner RS while **keeping N≤512** so the pilot rate stays
   high — e.g. `DQ_P12_N512` (more carriers, spacing still ≥562 Hz check) or
   `DQ_P10_N512 RS111`. Must clear all of §4.3 incl. HF-flutter 1×.
3. **Stretch (HOLD, experimental):** at most one dense-grid or D8PSK rung, carried
   only to gather real-tape data on the flutter-ICI / phase-noise frontier. Label
   experimental; never count it toward the headline rate.

---

## 5. Artifacts & reproducibility
- Probe script: `experiments/tape_v2/x9_sim_probes.py` (seeds 0–2; reads the real
  `captures/m8_tape_mono_lossless.wav`).
- Probe results: `experiments/tape_v2/results/x9_sim_probes.json`.
- Cross-references (read-only): `real_channel_sim.py`, `sim_v2.py`,
  `src/channel.py` (flutter trajectory L52–69), `h4_dqpsk.py` (pilot tracker
  L183–231), `h8_dqpsk_stress.py` (the 96-cell stress this audit extends),
  `results/m8_results_m8_tape_mono_lossless.json` (real outcomes),
  `results/m8_sim_validate_summary.json` (sim gate that mis-greenlit N1024),
  `results/sim_v2_validation.json` (dg=0.65 calibration, gate_met=False).

### Key uncertainties (stated honestly)
- Real jitter measured on the DQPSK pilot (tonality 0.68) — the 5–200 Hz figure is
  a **conservative lower bound** (tighter bandpass lowers it ~30 %; a sounder tone
  raises it). The 100× sim gap survives both — direction is certain, magnitude is
  ±~2×.
- dg lossless recalibration (0.58) is a *recommendation from single-seed probes*;
  it MUST be re-validated with ≥4 seeds against the m8 real per-rung BERs before
  master9 frequency-domain rungs are trusted.
- The HF-flutter injection is a *proposed* fix, not yet built; §4.2 specifies a
  self-test (must reproduce N1024-fail / N512-pass) before any gate relies on it.
