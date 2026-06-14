# REAL_CHANNEL.md — measured parameters of OUR physical cassette channel

The acoustic loop: **laptop speaker -> cassette tape -> deck playback -> room ->
iPhone Voice Memos -> iCloud -> Mac**. This document records every measured
parameter of that physical channel from two real captures, and — front and
centre — the one term the simulator (`src/channel.py`) does **not** model and
which has repeatedly killed short-symbol modems on real audio:
**spectral contamination (inter-symbol + reverb leakage across tone bins).**

Machine-readable companion: [`experiments/tape_v2/real_channel_params.json`](../experiments/tape_v2/real_channel_params.json).

Captures (both LOCAL + gitignored):
- `experiments/tape_v2/captures/tape3_run1.wav` — master3, combinatorial **M16,K2** modem (N=77 samples/sym, 623 Hz FFT bins, 1-bin tone spacing).
- `experiments/tape_v2/captures/voicememo_run1.wav` — master2 ladder incl. **c2_m32_k2** (N=159, 302 Hz bins). Master region ~12 s..1010 s of a 41-min over-run.

Method: `global_sync_and_resample` (chirp clock recovery + whole-tape resample to
nominal 48 k) + `analyze_sounder` (H(f), SNR(f), flutter, noise floor) from
`analyze_master2.py`; leakage measured directly on known-lit-tone symbols,
genie-aligned per symbol so it is **not** a timing artifact.

---

## TL;DR — the durable finding

The channel is **clean by every classical metric** (≈40 dB SNR, 0.3–0.4 %
flutter, clock recovered to ~1.000x, noise floor ≤ −58 dBFS, monotone HF rolloff).
Noise and timing are **not** the limiter. The limiter is **spectral
contamination**: on symbols we *know* are correctly placed, **~37 %** (M16) of the
post-EQ tone energy lands **outside** the lit tones. That contamination splits
into two mechanisms:

| mechanism | M16 (N=77) | M32 (N=159) | scales with symbol length? |
|---|---|---|---|
| **adjacent-bin** (FFT-skirt + adjacent-symbol smear into ±1 bin) | 0.112 | 0.047 | **yes — halves per 2× symbol length** |
| **distant/diffuse** (reverb + room/speaker/mic + AAC re-quant) | 0.240 | 0.251 | **no — flat ~0.25 floor** |

The diffuse ~25 % floor is the durable, length-independent enemy. It is exactly
what `src/channel.py` omits, and it is why the sim loved short-symbol M16 (more
rate) while real audio floors a *genie* M16 decoder at bit-BER ~0.17–0.20. Tones
spaced 1 FFT bin apart cannot survive a 25 % diffuse cross-bin floor regardless
of SNR.

---

## 1. H(f) magnitude and per-tone SNR (300–11000 Hz)

Measured from the 64-tone multitone sounder (300 Hz → 11 kHz), magnitude relative
to peak.

| | master3 / tape3 | master2 / voicememo |
|---|---|---|
| **HF rolloff** (H[300 Hz] − H[11 kHz]) | **−22.1 dB** | **−29.9 dB** |
| SNR(f) median | 40.6 dB | 39.1 dB |
| SNR(f) p10 | 32.7 dB | 31.8 dB |
| fraction of tones below 8 dB SNR | 0.0 | 0.0 |

The rolloff is smooth and monotone (tape + speaker + mic + AAC low-pass combined).
High tones are ~10–20× weaker than low tones, so a tone detector **must** divide
out H(f) before picking the loudest K bins — but EQ then *amplifies the
contamination* in the weak high bins (see §3). Per-tone SNR is excellent
everywhere: **noise is not the problem.** Full H(f) and SNR(f) curves are in the
JSON (`Hf_magnitude.H_db_*`, `snr_db_per_tone_*`).

## 2. Flutter, noise floor, clock offset

| | master3 / tape3 | master2 / voicememo |
|---|---|---|
| **Flutter (WRMS, 3 kHz tone)** | **0.31 %** | **0.44 %** |
| Noise floor | **−63.1 dBFS** | **−57.9 dBFS** |
| Recovered clock (chirp spacing) | **1.0009×** | **1.0001×** |
| Recovered clock (3 kHz tone) | 1.0009× | 1.0006× |

**Clock note:** the Voice-Memos capture path runs at ~**1.000×** — there is no
Continuity-style resample. The *prior* capture path (Continuity / AirPlay-ish)
ran at ~**0.88×**, which the global chirp sync must and does correct. Residual
offset here is pure tape-speed (deck) and is fully recovered by the two-chirp
spacing estimate. Flutter (wow/flutter time-warp) is **already modeled** by
`src/channel.py`; these measured values (0.3–0.4 %) are the realistic operating
point and are *4–6× lower* than the worst case feared earlier.

## 3. THE KEY NEW TERM — spectral contamination / leakage

For each symbol whose lit tones we know (master3 robust frame0 for M16; master2
c2_m32_k2 rep0 for M32), we genie-align the symbol to the ±15-sample offset that
decodes it correctly, divide tone energies by the sounder H(f) EQ, and measure:

```
off-tone leakage frac = 1 − (energy in the K lit tones) / (total tone energy)
```

Genie alignment removes timing as a cause: this is contamination on *correctly
placed* symbols.

| metric | M16 (N=77, 623 Hz bins) | M32 (N=159, 302 Hz bins) |
|---|---|---|
| off-tone leakage, genie-aligned, **median** | **0.374** | **0.307** |
| off-tone leakage, all symbols, median | 0.420 | 0.338 |
| **adjacent-bin** leakage (±1 bin of a lit tone) | 0.112 | 0.047 |
| **distant/diffuse** leakage (non-adjacent bins) | 0.240 | 0.251 |
| spurious-3rd-tone / weakest-lit-tone ratio | 0.90 | 0.75 |

**Reading the table:**
- A *clean* symbol would have leakage ≈ 0. We measure **~37 %** energy in the
  wrong bins even when the symbol is perfectly aligned and EQ'd. A correctly
  detected K-of-M pair barely clears this floor — hence the genie-decoder BER
  floor of ~0.17–0.20 reported in `REAL_DECODE_FINDINGS.md`.
- The spurious-3rd ratio ~0.9 (M16) means a wrong tone is, on the median symbol,
  ~90 % as strong as the weakest *correct* tone: a single bin of contamination
  flips the K-of-M decision.

### Scaling with symbol length — two separable mechanisms

Doubling the symbol length (N=77 → N=159, halving the bin width) moves the two
mechanisms in opposite ways:

- **Adjacent-bin leakage halves: 0.112 → 0.047.** This is FFT spectral-skirt +
  adjacent-symbol energy bleeding into the ±1 neighbouring bins. Longer symbols =
  narrower bins = sharper skirts = more inter-tone orthogonality. This is the part
  that *re-tiering to M32 buys back.*
- **Distant/diffuse leakage is flat: 0.240 → 0.251.** This is the **reverb tail +
  room/speaker/mic transfer + AAC re-quantization** smearing energy uniformly
  across *all* bins. It does **not** shrink with symbol length. This ~25 % floor is
  the hard limit; no symbol-length or window choice removes it.

A single-exponential fit `leak(N) ≈ A·exp(−N/τ)` (lumping both mechanisms) gives
**A ≈ 0.52, τ ≈ 380 samples ≈ 7.9 ms** — interpret τ as an effective leakage/reverb
tail time constant. (The two-mechanism split above is the more honest model; the
exponential is a convenient scalar for sim parameterization.) Overall leakage drops
only ~0.9 dB per 2× symbol length because the diffuse floor dominates.

### Why this killed M16 (and the design consequence)

M16/N=77 places tones **1 FFT bin (623 Hz) apart**. With a ~25 % flat diffuse
floor + ~11 % adjacent-bin smear, the wrong bins routinely out-rank a weak lit
tone (worse after EQ multiplies the weak high bins ~20×). M32/N=159 (302 Hz bins)
halves the adjacent term and reached ~0.10 raw BER on master2 — survivable with
RS(255,127). The architectural lesson: **on this real channel, tone spacing must
be set against the diffuse leakage floor, not just against noise or flutter.**

---

## 4. How to add this to the simulator

`src/channel.py::cassette_channel` currently models: 5th-order Butterworth
low-pass (band-limit), wow/flutter time-warp, AWGN, dropouts, speed offset. It
does **not** model reverb / room impulse response / spectral leakage / AAC
artifacts — the exact terms that contaminate adjacent + distant tone bins. To
make the sim punish short symbols the way reality does, add, in order of impact:

1. **Diffuse reverb / leakage tail (the big one).** Convolve the signal with a
   short exponentially-decaying impulse response before (or after) the band-limit:
   `h[n] = δ[n] + g·exp(−n/τ)·white`, with **τ ≈ 8 ms** (≈380 samples @ 48 k) and
   gain `g` set so that the diffuse cross-bin energy reaches **~25 % of symbol
   energy** for a 1-bin-spaced multitone (calibrate against
   `distant_bin_leakage_*` in the JSON). This single term reproduces the
   length-independent floor that floors M16 and rewards longer symbols/wider tone
   spacing. It must be **frequency-flat** (diffuse), not just an HF rolloff.

2. **Stronger, calibrated HF rolloff.** Replace the flat 12 kHz Butterworth with
   the measured monotone H(f): **~22–30 dB** down at 11 kHz vs 300 Hz. Use the
   `Hf_magnitude.H_db_master3` curve directly as an FIR/IIR magnitude target so
   high tones are ~10–20× weaker (forcing the decoder to EQ, which then amplifies
   contamination — the realistic failure path).

3. **Adjacent-symbol smear (ISI).** Let each symbol's tail leak a few percent of
   its energy into the next symbol window (a one-tap memory between symbols, ~5–11 %
   into ±1 bins). This is the term that *shrinks* with symbol length, so it must be
   modeled as a fixed *time* (not a fixed fraction of the symbol) to reproduce the
   0.112 → 0.047 scaling.

4. **AAC re-quantization (Voice-Memos path only).** Optional: encode→decode the
   sim signal through AAC (~64–128 kbps) to inject codec pre-echo/quantization. In
   practice its effect folds into the diffuse term (1); model it explicitly only if
   matching the Voice-Memos capture specifically.

**Calibration targets** (from the JSON, use master3 as canonical, master2 as the
AAC/Voice-Memos variant):
- HF rolloff: −22 dB (master3) / −30 dB (master2) at 11 kHz.
- Flutter WRMS: 0.31 % / 0.44 %.
- Noise floor: −63 / −58 dBFS; per-tone SNR median ~40 dB.
- **Off-tone leakage on a 1-bin-spaced K-of-M symbol: ~37 % total**, of which
  ~25 % is diffuse (length-independent) and the rest adjacent-bin (halves per 2×
  symbol length).

A sim with terms (1)–(3) calibrated to these numbers will, like reality, floor a
short-symbol M16 modem and favour the longer-symbol M32 PHY — closing the sim/real
gap that this codebase has been fighting.

---

## 5. The IMPROVED simulator (built) — `real_channel_sim.py`

`experiments/tape_v2/real_channel_sim.py::real_channel(...)` is a thin WRAPPER over
the **frozen** `src/channel.py::cassette_channel` (which is never edited). It calls
the frozen channel for the physics it already does well, then layers the three
missing real-channel terms, parameterized from the `_sim` block of
`real_channel_params.json`:

| term | implementation | calibrated knob | reproduces |
|---|---|---|---|
| **residual flutter** | drive frozen channel at `flutter_full × 0.15` | `flutter_residual_frac` | the small post-sync flutter the detector actually sees (global resample removes the bulk; full flutter would double-count and wrongly punish long symbols) |
| **calibrated HF rolloff** | FIR from the *smoothed* measured H(f) | — | high tones ~10–20× weaker, forcing EQ |
| **adjacent-bin leakage** | short reverb tail of FIXED length in *samples* (`adj_tail_samples=20`) | `adj_gain=1.0` | the *length-dependent* 0.112 (M16) → 0.047 (M32) split |
| **diffuse floor** | convolutional white tail, τ≈8 ms | `diffuse_gain=0.5` | the *length-independent* ~25 % cross-bin floor |

Two implementation notes that mattered:
- The HF curve is **smoothed** before building the FIR — the raw H(f) has isolated
  −49 dB measurement *nulls* that, combined with the decoder's clipped EQ, would
  amplify FIR transition-band ringing ~1000× (a sim artifact, not real physics).
- The detector EQ clips at **`eq_clip = 0.05`**, not the `1e-3` the real
  `m2_modem_survival` used. At `1e-3` the EQ over-amplifies M32's deep-HF tones
  (~23×) and spuriously inflates M32 BER *in sim*; `0.05` is a realistic
  regularized EQ and lets M32's narrower-bin advantage show — matching the real
  M32-survives finding.

### Validation — the improved sim now PREDICTS the M16 failure

`experiments/tape_v2/validate_real_sim.py` pushes the M16,K2 and M32,K2 modems
through the **OLD** sim (frozen `cassette_channel` at its historical realistic
defaults: 0.07 % flutter, 12 kHz band, 40 dB SNR — no reverb/measured-HF/ISI) and
the **NEW** sim, with the SAME oracle-timed (±15) + sounder-H(f)-EQ + top-K FFT
detector the real measurement used. Both modems are run on the **same** master3
H(f)/flutter so the only variable is symbol length. Results
(`results/real_sim_validation.json`):

| modem | sim | N | genie bit-BER | genie byte-ER | RS-closeable? |
|---|---|---|---|---|---|
| M16,K2 | **old** | 77 | 0.006 | 0.014 | **YES** (wrongly blessed) |
| M16,K2 | **new** | 77 | 0.105 | **0.358** | **NO** (> 0.251 ceiling) |
| M32,K2 | **old** | 159 | 0.007 | 0.013 | YES |
| M32,K2 | **new** | 159 | 0.141 | **0.292** | marginal (near ceiling) |

**Reading the result:**
- The **OLD sim wrongly predicted M16 success** — byte-ER 0.014, RS trivially
  closes. This is exactly why the codebase over-rewarded short-symbol M16.
- The **NEW sim floors M16**: byte-ER 0.358 sits *above* the robust-RS byte-
  correction ceiling (0.251) → **RS-uncloseable**, and bit-BER 0.105 is in the
  measured real failure band. **The improved sim would have predicted the M16
  failure before we recorded master3.**
- The **NEW sim reproduces M32's symbol-length advantage**: M32 has strictly lower
  byte-ER (0.292 < 0.358) and sits *near/under* the ceiling — consistent with the
  real survival map, where M32,K2's genie byte-ER (0.164) was the only one under
  the ceiling. (Absolute M32 RS-closure is marginal in sim, mirroring the real
  rider: the *genie* closes it but the achievable tracker does not without a
  pilot-aided front-end.)

### master4 recommendation

- **PHY: combinatorial M=32, K=2** (N=159, ~302 Hz bins). The only RS-closeable
  config on the real channel: K=2 concentrates symbol errors into few bytes, and
  the narrower bins halve adjacent-bin leakage vs M16. The improved sim confirms it
  is strictly better than M16.
- **FEC: robust rung — interleaved RS(255,127)** (rate 0.498, corrects ~0.251
  byte-error fraction, deep interleave ≥10 frames). This is the most robust rung in
  the existing `m3_codec.py` ladder.
- **Front-end RIDER (load-bearing):** realising the genie ceiling requires a
  **pilot / known-symbol timing aid**. The concentration-lock tracker alone loses
  lock on K-of-M (real raw byte-ER ~0.64); the PHY+RS are necessary but not
  sufficient until the timing front-end is strengthened.

Tools: `experiments/tape_v2/real_channel_sim.py` (the improved channel),
`experiments/tape_v2/validate_real_sim.py` (OLD-vs-NEW validation + master4 pick),
`results/real_sim_validation.json` (machine-readable verdict).

---

## 6. Training-based channel EQUALIZATION — tested, does NOT crack the wall

The diffuse ~25% floor (§3) was hypothesized to be acoustic reverb — a linear,
time-invariant (LTI) convolution that a known training sequence could let us
estimate and **deconvolve** (complex H(f) inversion). The captures already carry
ideal training material: a broadband global chirp (500-5000 Hz), a 64-tone
Schroeder multitone sounder (300-11000 Hz, deterministic phases — covers the FULL
data-tone band WITH phase), and per-frame chirp preambles. We estimated the
COMPLEX channel and equalized the data three ways (complex MMSE `H*/(|H|^2+eps)`,
magnitude-only `1/|H|`, none), marked deep-null bins as erasures, and re-measured.
Tool: `experiments/tape_v2/eq_train_test.py`; results
`experiments/tape_v2/results/eq_train_results.json`.

### THE DECISIVE FINDING — the channel is TIME-VARYING, so H(f) is not invertible

An LTI reverb has a **fixed** complex H(f): two probes of the same channel must
return the same magnitude AND phase. We have two multitone sounder reps ~4 s apart.
After removing a best-fit bulk delay between them (so a sub-sample timing offset is
**not** mistaken for instability), the per-tone phase still disagrees by:

| capture | inter-rep phase diff (after delay-align) | mag ratio | verdict |
|---|---|---|---|
| master3 / tape3 (no AAC) | **median 77.9 deg**, p90 ~145 deg | 0.66-1.78 | **time-varying** |
| master2 / voicememo (AAC) | **median 69.1 deg**, p90 ~145 deg | 0.66-1.78 | **time-varying** |

The phase is essentially **random at high frequency** within seconds, in BOTH
captures. Since tape3 has no AAC, the dominant cause is **flutter-induced
per-symbol phase jitter** (the global resample fixes the mean rate, not the local
phase); AAC's frame-dependent nonlinearity adds to it on master2. **A single
trained H(f) is stale by the time the data plays — there is no fixed reverb to
invert.** This is the conclusive reason training-based equalization cannot work
here, and it is a *new, separable* measurement beyond the §3 leakage floor: the
floor is not just diffuse, it is **non-stationary**.

### Result — complex EQ makes it WORSE (as the instability predicts)

| config | EQ mode | distant leak | genie BER | genie byteER | achievable byteER | RS-close |
|---|---|---|---|---|---|---|
| M16,K2 (tape3) | none | 0.160 | 0.334 | RS fails | RS fails | no |
| M16,K2 (tape3) | mag-only | 0.196 | 0.288 | RS fails | RS fails | no |
| M16,K2 (tape3) | **mmse-complex** | 0.171 | 0.313 | RS fails | RS fails | **no** |
| M32,K2 (master2) | none | 0.020 | 0.142 | 0.403 | 0.547 | no |
| M32,K2 (master2) | mag-only | 0.018 | 0.197 | 0.499 | 0.664 | no |
| M32,K2 (master2) | **mmse-complex** | **0.233** | 0.303 | 0.681 | 0.828 | **no** |

(Leakage uses a tighter complex-Goertzel genie-aligned estimator than §3's FFT
top-K, so absolute 'none' values run lower; the DIRECTION is decisive.) Applying
the stale complex H(f) phase rotates each tone by the wrong angle and **injects**
contamination: M32 distant leakage jumps 0.020 -> 0.233, genie byte-ER
0.403 -> 0.681. Magnitude-only EQ is roughly neutral-to-slightly-worse (the channel
magnitude is also not stationary). **No EQ mode closes RS on the genie OR the
achievable path; acoustic byte-exact remains uncracked.**

### Residual-floor attribution

- **reverb-removed (equalizable LTI part): ~0.** The complex EQ removes no leakage
  and adds leakage — the floor has no static, invertible reverb component to remove
  at the symbol timescale.
- **irreducible (time-varying phase + AAC/null residual): ~all of it.** The floor
  is dominated by per-symbol phase non-stationarity, not a fixed IR. Deep spectral
  nulls (9 null bins on M32, marked as erasures) are a smaller, genuinely
  AAC/channel-shaped component but are not the bottleneck.

### master4 recommendation (updated)

- **A front-loaded calibration/training block + an open-loop equalizing decoder
  will NOT help** — the channel it would calibrate is gone within seconds. Do not
  spend a master4 on a static training sequence for equalization.
- If equalization is pursued, it must be **per-symbol pilot-aided / adaptive**:
  embed pilot tones in EVERY symbol and run a decision-feedback / LMS-adaptive
  equalizer that tracks the phase continuously. That is a substantially larger PHY
  change than a calibration preamble and is NOT validated here.
- The proven, cheaper levers stand (see §5 and the master2 survival map): **M32,K2
  PHY (K=2 error concentration) + interleaved RS(255,127)**, with the load-bearing
  rider that the per-symbol **timing/detection front-end** must be strengthened
  (pilot/known-symbol timing aid) to realise the genie ceiling. Equalization is not
  the missing piece; a phase-robust, per-symbol front-end is.

---

## 7. CHIRP SPREAD-SPECTRUM (LoRa/CSS) — BEATS the contamination wall (2026-06-09)

The durable enemy (§3) is a ~25% **diffuse, length-independent, time-varying**
cross-bin contamination floor that caps EVERY closely-spaced-tone scheme at a
*genie* bit-BER of 0.09–0.18 (M16/M32/M48 all fail). CSS attacks the floor at its
root: it does not place data in narrow bins. Each symbol is a full-band linear
chirp; data is the cyclic frequency shift. Detection = dechirp (multiply by the
conjugate base chirp) + FFT → ONE peak. The diffuse contamination is NOT chirp-
correlated, so the dechirp spreads it across all N bins while concentrating the
true symbol into one — a processing gain ≈ N that AVERAGES the floor away.

Tool: `experiments/tape_v2/assault_css.py` (fixed/rewritten from the buggy
`src/hyp_h4_css.py`, which folded the negative-frequency image and floored at
BER 0.5). The fix: build on the canonical LoRa **chip grid** (N complex samples,
base phase π(n²/N−n), symbol s = ×exp(j2πsn/N)), resample to a REAL passband at
carrier fc, and on RX bandpass → analytic (Hilbert) → downconvert → resample to N
chips → dechirp → FFT. **No-channel sanity BER = 0.0000** for SF6–9 (where H4 died).

Results through the FAITHFUL `real_channel_sim` (the sim that reproduces the real
M16 failure), 9 kHz sweep, fc 5 kHz:

| metric | tone schemes (best, M32K2) | **CSS (SF6, 64 chips)** |
|---|---|---|
| no-channel sanity BER | ~0 | **0.0000** |
| **GENIE bit-BER (master3)** | 0.088–0.18 (RS-uncloseable) | **~0.000** |
| GENIE bit-BER (master2/AAC) | 0.088 | **0.0005** |
| achievable byte-ER (pilot-aided) | 0.64 (tracker loses lock) | **0.164** (master3) / 0.215 (master2) |
| RS(255,127) byte-exact (achievable) | no | **7/8 flutter seeds** |
| net bps (gross 900 × eff 0.667 × RS 0.498) | — | **~299** |

**Reading the result — the first scheme to break the wall:**
- The **GENIE ceiling collapses from ~0.10 to ~0** — the spread-spectrum
  processing gain does exactly what theory predicts against the diffuse floor.
  No tone scheme ever got near this on the faithful sim.
- **Timing is the remaining cost, and it is solvable.** A naive boundary-stepped
  demod fails (contamination creates spurious peaks a blind search locks onto).
  The genie shows every symbol IS recoverable at SOME ±offset, and the needed
  offset DRIFTS SMOOTHLY with flutter (≈±10 samples, ~5 Hz). The fix is the
  load-bearing **pilot-aided timing aid** §6 called for: a known pilot symbol
  every `pilot_every` data symbols locks the boundary exactly (RX knows the
  pilot), and the smooth drift is linearly interpolated between pilots. Gray
  coding (a ±1 bin slip → 1 bit) + incoherent ±2-sample combining trim the
  residual. At `pilot_every=2` this reaches achievable byte-ER 0.164 — under the
  RS robust ceiling (0.251) — and the full interleaved RS(255,127) roundtrip
  closes byte-exact on **7 of 8** flutter realizations.

### Optimizer pass — turn 7/8 into 4/4 on the stress seeds

Tool: `experiments/tape_v2/assault_css_optimize.py`; results:
`experiments/tape_v2/results/assault_css_optimize.json`.

The first CSS pass used RS(255,127), which is the old "robust" rung, and it closed
7/8 full 12 KB flutter seeds. The failure was not a CSS ceiling failure; it was
one adversarial seed where the code rate was too optimistic. We swept the two
honest knobs on a 4 KB payload across the adversarial seed set:

| profile | net bps | result | max raw BER | note |
|---|---:|---:|---:|---|
| FAST: pilot_every=2, RS(255,127) | 298.8 | 3/4 | 0.040 | old near-survivor; seed3 has 7 failed CW |
| pilot_every=2, RS(255,111) | 261.2 | 3/4 | 0.038 | still one failed CW on seed3 |
| **SAFE: pilot_every=2, RS(255,95)** | **223.5** | **4/4** | **0.039** | recommended no-cable master4-safe profile |
| pilot_every=4, RS(255,79) | 223.1 | 4/4 | 0.048 | tied rate, but fewer pilots and less timing margin |
| EXTRA-safe: pilot_every=2, RS(255,79) | 185.9 | 4/4 | 0.037 | use if the real room is worse than master3 |

**Updated recommendation:** record **two CSS acoustic rungs** on master4:

1. **CSS-SAFE**: SF6, 9 kHz sweep, fc=5 kHz, pilot_every=2, Gray symbols,
   incoherent +/-2 sample combining, interleaved **RS(255,95)**. Net **223.5 bps**.
   This is the no-cable profile that cleared the stress seeds.
2. **CSS-FAST**: same PHY with **RS(255,127)**. Net **298.8 bps**. Keep it on the
   tape as an upside rung; it already closes most flutter realizations and may pass
   on the real physical capture.

This is slower than wired line-in, but it is the first no-cable path with an
all-clean faithful-sim stress result after the real-channel leakage term was added.
For a C90 stereo-equivalent budget, CSS-SAFE projects to ~0.30 MB; CSS-FAST
projects to ~0.40 MB. That is enough for bootstrap metadata, compressed demos, and
the smallest already-proven cassette payloads, but not the 150 KB LLM with a lot
of margin unless both sides/tracks are used and physical results beat the sim.

### Research fit

The online literature supports this direction. Disney/ETH's smartphone acoustic
work is directly aligned with the "speaker system to phone microphone" deployment
and reports that collaboration/receiver diversity improves reliability in real
rooms. Modern acoustic-communication surveys emphasize that real indoor multipath
and device variation make simulation-only claims weak, matching why this repo now
uses measured captures to calibrate `real_channel_sim`. CSS-specific papers are
also consistent with the mechanism here: LoRa/CSS uses dechirp+FFT-style matched
filtering; CSS receiver designs emphasize matched filtering and robust timing, and
long-range acoustic CSS papers call out matched-filter processing gain as the
reason chirps remain stable under multipath/Doppler-like effects. In short: the
repo's measured floor says "do not put data in fragile narrow bins"; the literature
says "use chirps, matched filtering, and explicit timing pilots."

References consulted:
- Disney Research / ETH Zurich, "Acoustic Data Transmission to Collaborating
  Smartphones - An Experimental Study" (WONS 2014):
  https://studios.disneyresearch.com/2014/04/04/acoustic-data-transmission-to-collaborating-smartphones-an-experimental-study/
- Putz et al., "Evaluating Acoustic Data Transmission Schemes for Ad-Hoc
  Communication Between Nearby Smart Devices" (ACM TIOT 2026 / arXiv 2602.02249):
  https://arxiv.org/abs/2602.02249
- Maleki et al., "A Tutorial on Chirp Spread Spectrum for LoRaWAN" (arXiv
  2310.10503): https://arxiv.org/abs/2310.10503
- Kim and Chong, "Chirp Spread Spectrum Transceiver Design and Implementation for
  Real Time Locating System" (2015):
  https://journals.sagepub.com/doi/10.1155/2015/572861
- Nam et al., "Long-Range Acoustic Communication Using Differential Chirp Spread
  Spectrum" (Applied Sciences 2020): https://www.mdpi.com/2076-3417/10/24/8835
