# R6 (audit) — Simulator Fidelity + master9 Gate, with a BUILT & VALIDATED HF-flutter gate

**Date:** 2026-06-10 · **Branch:** deepdive-3-overnight
**Supersedes the unbuilt piece of** `R6_sim_fidelity.md`: that dossier correctly
diagnosed the timing blind spot and *proposed* an HF-flutter injection gate but
never built it. This audit **builds it, runs it through the real h4 DQPSK decoder,
and reports three iterations (two failed, one validated)** — so the master9 gate
rests on a tested proxy, not a hypothesis.

Empirical artifacts (all reads-only, seeds logged):
- `experiments/tape_v2/x9_sim_probes.py` → `results/x9_sim_probes.json` (jitter PSD, sim vs real)
- `experiments/tape_v2/x9_flutter_inject.py` → `results/x9_flutter_inject.json` (v1, flat — FAILED)
- `experiments/tape_v2/x9_flutter_inject_v2.py` → `results/x9_flutter_inject_v2.json` (v2, full-PSD-shaped — FAILED)
- `experiments/tape_v2/x9_flutter_gate.py` → `results/x9_flutter_gate.json` (v3, 5–23 Hz band — **VALIDATED**)
- logs in `x9_dossier/x9_flutter_*.log`

---

## 0. Headline

1. **The sim is honest in frequency, blind in time.** Off-bin contamination, HF
   rolloff, and the RS-cliff for tone-grid modems are modelled honestly-to-slightly-
   pessimistically. Flutter timing-jitter above 5 Hz is **~100–200× too weak**, which
   is *the* reason the m8 sim mis-greenlit both N1024 DQPSK rungs (sim 2/2 seeds PASS;
   real 37/37 and 35/35 RS codewords failed) while rating them as safe as the N512
   rung that actually won.
2. **The missing impairment is specifically 5–23.4 Hz residual flutter.** I built an
   injection and proved empirically that **only** jitter in the 5–23.4 Hz band
   reproduces the real "N512 survives / N1024 dies" split. Broadband or full-PSD
   injections kill N512 just as hard (no differential). At **12 µs** band-RMS the
   real outcome reappears (N512 3/4 seeds byte-exact, N1024 2/8); at **16 µs** N1024
   is cleanly dead 0/8 while N512 is on its cliff.
3. **The 934 bps record has thinner margin than it looks.** Confirmed two ways:
   R2's truth-margin (min margin **0.04°** — one symbol from failure; 8.9 % of
   symbols inside the D8PSK boundary) and my injection (N512 RS127 tolerates only
   ~12–14 µs of 5–23 Hz jitter before its cliff). Treat 934 bps as the **ceiling of
   what is currently reproducible**, not a comfortable floor.

---

## 1. How the sim models each phenomenon

Pipeline: `sim_v2.channel_v2(x, profile, aac)` = `real_channel(...)` (tape+room)
**then** an optional real AAC round-trip. `real_channel` wraps the FROZEN
`src/channel.py::cassette_channel` and layers three measured terms.

### 1a. Flutter / wow — `src/channel.py` time-warp (THE WEAK LINK)
`cassette_channel_diagnostics`, L52–69:
```python
inst = a1·sin(2π·0.55·t+p1) + a2·sin(2π·4.8·t+p2) + 0.18·white   # a1~N(1,.08), a2~N(.45,.05)
inst = inst / rms(inst) · wow_flutter_wrms
warped_t = t + cumsum(inst)/fs ;  y = interp(t, warped_t, y)      # resampling trajectory
```
- **Class:** resampling trajectory → correct *kind* of impairment (frequency-
  proportional phase error 2π·f·τ; high carriers hurt most — confirmed by R2's
  per-carrier SER, see §2).
- **Spectrum:** two discrete sinusoids (0.55 Hz wow, 4.8 Hz flutter) + 18 % white.
  After rms-normalization the displacement PSD is two delta spikes on a tiny floor;
  the **timing-jitter PSD above ~5 Hz is essentially empty** (Table A).
- **Amplitude actually applied:** `real_channel` drives `flutter = flutter_full ×
  flutter_residual_frac`, `flutter_residual_frac = 0.15` ("post-sync residual"
  assumption). tape7: 0.365 % × 0.15 = **0.055 % wrms** at the detector.

### 1b. HF rolloff — measured H(f) FIR (add_hf, L132–138)
129-tap FIR following the **smoothed** measured `H_db_master3` sounder curve
(`_smooth_db`, win=5, drops the −49 dB notch spikes so the EQ doesn't ring),
applied via `fftconvolve`. Honest: the literal measured deck transfer function
(300–11000 Hz, ~22 dB master3 rolloff).

### 1c. Adjacent-bin ISI — fixed-length short reverb tail (add_isi, L147–157)
White exponential IR, τ = `adj_tail_samples` (20 samp), gain `adj_gain`, length 6τ,
unit direct path. Tail length fixed in **samples** → a longer symbol corrupts a
smaller *fraction* of its window → reproduces the measured adjacent-bin shrink
(0.112 @ M16/N77 → 0.047 @ M32/N159). Convolutional (smears a copy into ±1 bins).

### 1d. Diffuse floor — `diffuse_gain` reverb tail (add_reverb, L169–180)
The hard frequency-domain limit. Longer white exponential IR (τ = `reverb_tail_tau_ms`
≈ 7.86 ms, length 8τ ≈ 63 ms), energy `g_diffuse` relative to direct, convolved in.
Being convolutional, its cross-bin *fraction* is length-independent (matches the flat
~0.25 distant-bin floor that kills 1-bin grids) while a longer FFT still concentrates
each true tone (M32 keeps its processing-gain edge). `diffuse_gain` = **0.65** (sim_v2
SIM2 override) vs 0.5 in the JSON `_sim` block.

### 1e. AWGN — inside `cassette_channel` (L82–85)
Flat Gaussian at profile SNR (tape7 = 36.4 dB; tape4 = 40.4 dB). Real per-tone SNR is
excellent (p10 ≈ 33 dB) — **noise is not the limiter**, and the model agrees.

### 1f. AAC round-trip — `sim_v2.aac_roundtrip`
mono → stereo 24-bit WAV → **real Apple afconvert AAC-LC, 48 kHz, ~205 kbps CBR** →
decode → mono, sample-aligned (codec priming delay measured once via chirp; here
delay 0, residual −0.0004 samp, corr 0.99998). Applied *after* tape+room physics,
with a 0.95-peak normalize/restore.

---

## 2. Per-phenomenon fidelity verdict for DENSE-OFDM / DQPSK

All sim/real jitter numbers from `x9_sim_probes.json` (inject a 4500 Hz pilot tone,
heterodyne→unwrap→Welch-PSD; real ground truth = the m8 capture's continuous 4500 Hz
DQPSK pilot, region 300–540 s, steadiest 8 s @ 410–418 s; sim seeds 0,1,2).
**Reproduced independently this session** (1-seed spot check: 23–47 Hz band = 0.075 µs
sim, matching the logged 0.07 µs).

### Table A — flutter timing-jitter RMS by band (the load-bearing measurement)

| band | sim aac-off | **REAL m8** | **REAL / sim** | meaning |
|---|---|---|---|---|
| 0.05–1 Hz (wow) | 140.0 µs | 809.3 µs | 5.8× | both trackers follow |
| 1–5 Hz | 6.71 µs | 176.8 µs | 26× | both follow |
| **5–23.4 Hz** | **0.24 µs** | **33.9 µs** | **142×** | N512 follows, **N1024 cannot** (its Nyquist=23.4 Hz) |
| 23.4–46.9 Hz | 0.07 µs | 11.1 µs | 158× | only N≤512 partly follows |
| 46.9–200 Hz | 0.04 µs | 8.9 µs | 205× | neither follows |
| total | 140.1 µs | 838.6 µs | 6.0× | dominated by wow |

> AAC on vs off changes the jitter spectrum <30 % → **AAC is not the timing problem.**
> The 5–23.4 Hz band (142× gap) is the one where N512's faster pilot has an edge and
> N1024 does not — and §3 proves empirically that this is exactly the band whose
> injection reproduces the real failure.

### Table B — REAL truth-referenced margins (from R2, `R2_margins.md`, measured on the capture)

| section | raw SER | median margin | **min margin (correct)** | frac < 22.5° (D8PSK err) | RS cw failed |
|---|---|---|---|---|---|
| **PASS 934 bps N512** | 1.80 % | 37.5° | **0.04°** | 8.9 % | 0/62 |
| **FAIL N1024** | 14.4 % | 34.6° | — (p1 = −59°) | 28.3 % | 37/37 |

> Per-carrier (R2): the high carriers carry the errors — carrier @3750 Hz SER 6.3 %
> (min margin −129°), @7500 Hz 5.8 %, @8250 Hz 3.5 %; carrier @750 Hz error-free.
> This is the **frequency-proportional 2π·f·τ signature of flutter**, worst at high f
> — the impairment class the sim models in *kind* but ~100× too weak in *magnitude*.

### Verdicts

| phenomenon | sim fidelity for dense-OFDM | evidence |
|---|---|---|
| **Flutter-ICI (93–375 Hz spacing)** | **NOT honest — optimistic.** Sim's off-bin energy is the static reverb skirt, not flutter modulation (Table C grows with N because a longer FFT captures more of the *fixed-time* reverb tail, not because of flutter sidebands). | Table A; §2 Table C |
| **Phase noise / D8PSK margins** | **NOT honest — optimistic.** Real N512 already has 8.9 % of symbols inside the 22.5° D8PSK boundary and N1024 28.3 %; sim shows clean margins. **D8PSK would look fine in sim and fail on tape.** | R2 Table B |
| **Reverb ISI for CP design** | **Honest-ish (geometry right, treat τ as point estimate).** Diffuse τ ≈ 7.86 ms is *measured*; ISI ≈ 1.5 symbols at N256. Size CP off it but stress τ ±50 %. | params; STATUS ~8 ms tail |
| **Off-bin / distant contamination (tone grids)** | **Honest to slightly PESSIMISTIC.** dg=0.65 matched 7/9 WS rungs; sim M16 mean BER ~0.035 is *higher* than real ~0.022 (`sim_v2_validation.json`) — the frequency-domain model errs toward *over*-punishing, which is the safe direction. The one sim-PASS/real-FAIL WS rung is a **non-self-tracking** rung (separate known failure mode), not a contamination miscalibration. | §4; sim_v2_validation.json |
| **HF rolloff / AWGN / clock offset** | **Honest.** Literal H(f), per-tone SNR; clock is a static resample the decoder removes (deck +0.117 %). | §1b/1e |

### Table C — sim off-bin leakage vs spacing (sim only, rectangular window)

| N | bin width | adj1/main | adj2/main | distant/main |
|---|---|---|---|---|
| 256 | 187.5 Hz | 0.031 | 0.015 | 0.198 |
| 512 | 93.8 Hz | 0.049 | 0.025 | 0.251 |
| 1024 | 46.9 Hz | 0.092 | 0.047 | 0.332 |

> Grows with N = the **diffuse reverb skirt** captured more fully by a longer FFT,
> **not** flutter-ICI. **Do not trust the sim to bless any spacing tighter than the
> proven 750 Hz without the flutter-augmented run of §3.**

---

## 3. THE HF-FLUTTER INJECTION — built, three iterations, validated

R6's gate hinges on a flutter-augmented stress cell; previously that cell was
vaporware. I built it and pushed real DQPSK payloads through the **actual h4
DQPSK decoder** (pilot tracker + decision-directed refinement + RS) under injection.

**Method:** after `channel_v2`, resample the output onto `t − τ_hf(t)` (a frequency-
proportional phase perturbation, the correct impairment class), where `τ_hf` is
band-limited white noise. The FROZEN channel is untouched (injection is a post-channel
resample). Gate rungs are the two whose real outcome is known and **opposite**:
`dq_p10n512_rs127` (real PASS, 934 bps) and `dq_p10n1024_rs159/rs223` (real FAIL).

### Iteration log (the negative results are load-bearing)

| version | τ_hf spectrum | result at the level matching the real N1024 residual | why |
|---|---|---|---|
| **v1** | flat 3–60 Hz, scaled by total band-RMS | N512 BER 0.22 ≈ N1024 0.18 — **no differential** | flat spectrum over-weights >47 Hz, where **neither** tracker helps → kills N512 too |
| **v2** | shaped to the FULL real PSD (incl. 47–200 Hz) | same — both die at every level > 0 | the 47–200 Hz tail still erases N512's edge |
| **v3** | **5–23.4 Hz band only** | **N512 survives, N1024 dies — the real split** | this is exactly the band N512 tracks (Nyquist 46.9 Hz) and N1024 cannot (23.4 Hz) |

### v3 result (`x9_flutter_gate.json`, band 5–23.4 Hz, 4 seeds)

| 5–23.4 Hz RMS | N512 RS127 byte-exact | N512 mean BER | N1024 byte-exact | N1024 mean BER |
|---|---|---|---|---|
| 0 µs | 4/4 | 0.0275 | 8/8 | 0.0002 |
| **12 µs** | **3/4** | 0.0321 | **2/8** | 0.0223 |
| **16 µs** | 1/4 | 0.0389 | **0/8** | 0.0478 |
| 20 µs | 0/4 | 0.0495 | 0/8 | 0.0760 |

> **N1024 BER is always 1.8–2× the N512 BER at every level > 0** — a monotone,
> mechanism-consistent differential. At **12 µs** the real outcome is reproduced
> (N512 mostly survives, N1024 mostly dies); by **16 µs** N1024 is cleanly dead 0/8
> while N512 is on its RS127 cliff. **The injection is a valid proxy for the sim's
> documented timing blind spot.**
>
> **Two honest caveats.** (a) The differential window is *narrow* (~12–16 µs) and
> seed-fragile right at the N512 edge — which is itself the finding: the 934 bps
> record has little timing margin (corroborates R2's 0.04° min margin). (b) A pure-
> jitter resample injection does **not** reproduce *all* of the real channel (it
> omits frequency-selective fade dynamics); it is calibrated to reproduce the one
> outcome that matters for the gate — the N512/N1024 timing differential — and it does.

---

## 4. AAC question — captures are now LOSSLESS (Voice Memos ALAC)

**Recommendation: faithful master9 sim runs with `aac=False`; recalibrate
`diffuse_gain` to the 0.55–0.60 lossless branch (≥4-seed averaged), NOT 0.65.**
Evidence + explicit uncertainty:

1. **The explicit AAC stage already adds ~nothing.** `sim_v2_validation.json`
   `aac_mechanism_check` (m32_rs111 rung): `raw_ber_aac_true = 0.1123` vs
   `aac_false = 0.1115`, `aac_clearly_worse = False`. afconvert AAC-LC at 205 kbps is
   transparent enough that it does not measurably add contamination on top of the
   diffuse floor. Removing it costs ~nothing in fidelity and drops a slow subprocess.
2. **dg=0.65 was over-fit to AAC captures (gate_met=False).** It is documented as the
   *closest honest compromise*, not a met gate: m16_rs191 PASS wants **dg ≤ ~0.6**,
   m32_rs111 FAIL wants **dg ≥ ~0.65** — mutually exclusive under one knob. The
   masking-skirt mechanism that forced 562 Hz spacing was an AAC artifact (300 Hz died
   on AAC only); lossless removes that adversary, so the defensible recalibration is
   the **dg ≤ 0.6 branch**.
3. **Do NOT over-relax dg.** It lumps reverb+room+speaker/mic+codec into one number.
   The lossless m8 tape still showed a substantial distant-bin floor (every fixed-grid
   WS rung failed at raw BER 0.07–0.19). Below ~0.5 the sim turns optimistic about
   tone-grid contamination. Also note the sim's intrinsic M16 BER (~0.035) is already
   *higher* than real (~0.022) — the frequency model is slightly pessimistic, so there
   is **no urgency** to lower dg; pick **dg = 0.58 ± 0.07** and stress it (§5).

> **Bottom line:** `aac=True` is harmless-but-slow and risks the dg=0.65 double-count.
> Switch to `aac=False`, dg≈0.58, re-validate against m8 real per-rung BERs. **This
> fixes only the frequency side — it does nothing for the timing blindness, which is
> where master9 dies. No dg value fixes flutter; §3/§5 do.**

---

## 5. PRE-REGISTERED master9 GATES

**Principle:** grant SHIP only for impairments the sim models honestly; for the
timing/flutter axis the sim is blind, so a **validated** HF-flutter cell (§3) forces
the missing 5–23.4 Hz jitter and caps how much a timing-domain sim PASS is trusted.
Pre-register before any master9 tape is burnt.

### 5.0 Channel config
- Nominal: `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`.
- Sanity bound: also `profile='tape4'` (quieter take).
- **All seeds set + logged; every cell averages a seed sweep.** Never trust one seed
  (the m8 N512 record flipped on seed 2 of my 16 µs injection).

### 5.1 Seeds per rung
- Nominal axis: **8 seeds** `{0..7}`. Each stress axis: **4 seeds** `{0..3}`.

### 5.2 Stress envelope (and why h8's was blind)

> **Proof h8's envelope was useless on the real failure:** h8's 96-cell matrix rated
> **all four N1024 rungs as "strict PASS, zero failed axes"** (`h8_dqpsk_stress.json`)
> — every one died on tape. h8's flutter axis (`flutter_residual_frac` 0.15→0.50)
> only **scales the benign two-sinusoid spectrum**; it adds **no** energy in the
> 5–23.4 Hz band, so it never stresses the actual failure mode. The new HF-flutter
> cell is the fix.

| axis | h8 | **master9** | why |
|---|---|---|---|
| **HF-flutter (NEW, mandatory)** | — | **inject 5–23.4 Hz band jitter at {12, 16, 20} µs RMS** (`x9_flutter_gate.py`) | the ONLY axis that emulates the 142× timing blind spot; validated to reproduce N512-pass/N1024-fail |
| flutter_residual_frac | 0.15→0.50 | keep 0.15→0.30 as a *minor* axis | scales wow only; **does not substitute for the HF cell** |
| SNR delta | −2, −4 dB | **−2, −4 dB** | sim SNR is honest |
| clock offset | implicit | **±0.15 % static resample** | exercises chirp-resync (deck +0.117 %) |
| reverb τ | fixed 7.86 ms | **×{0.5, 1.0, 1.5}** | CP/ISI sizing margin |
| AAC bitrate | 204.8k→96k | **drop** (lossless) | no longer the adversary |

### 5.3 SHIP / HOLD / REJECT rule (pre-registered)

A rung is **SHIP** iff ALL of:
1. **Nominal:** ≥ 7/8 seeds byte-exact (`aac=False`, dg=0.58).
2. **dg-pessimism:** ≥ 6/8 seeds byte-exact at dg=0.65.
3. **HF-flutter 16 µs:** ≥ 3/4 seeds byte-exact with the 5–23.4 Hz injection at
   **16 µs** (`x9_flutter_gate.py` cell). *This is the gate h8 lacked.* The proven
   934 bps N512 record passes the **12 µs** cell (3/4) but is on its cliff at 16 µs
   (1/4) — so this rule is **deliberately strict**: it would mark even the current
   record as **HOLD-not-SHIP** at 16 µs. Recommended operating threshold therefore is
   **12 µs for SHIP, 16 µs as the "headroom" cell**; a rung that clears 16 µs at ≥3/4
   has genuine timing margin the record lacks. *(Choose one threshold and freeze it
   before the run; do not move it after seeing results.)*
4. **Combo SNR −2 dB AND flutter_frac 0.30:** ≥ 3/4 seeds byte-exact.
5. **Margin floor (byte-level):** mean **byte**-error-rate over nominal seeds ≤
   0.6 × RS capacity = 0.6 × (255−k)/(2·255) (RS127 → 0.151, RS159 → 0.113,
   RS191 → 0.075). Measure on **bytes**, not bits — RS corrects byte symbols and a
   byte fails if any bit does, so byte-error-rate > bit-BER; comparing bit-BER to
   symbol capacity is optimistic.

A rung is **HOLD** (experimental, never headline) iff it passes 1,2,5 but fails the
**timing** gate 3 or 4 — the sim likes it but it leans on impairments the sim
under-models. **Both N1024 DQPSK rungs would be HOLD, not SHIP, under this rule.**

A rung is **REJECT** iff it fails nominal (1) or the byte margin floor (5).

### 5.4 Hard structural rules (non-negotiable)
- **Self-tracking front-end MANDATORY for every rung** (DQPSK pilot or the 0.25 Hz
  timing-trajectory h5/h6 front-end). Every fixed-grid WS rung failed on the lossless
  m8 tape; the sim can't catch it (flutter too smooth). **Ship no non-self-tracking
  rung regardless of sim PASS.**
- **Prefer shorter symbols at equal net rate.** N512 beat N1024 *because* its pilot
  updates twice as fast — a timing decision, not just ISI/processing-gain. Default to
  the shorter-symbol variant; a longer-symbol variant is SHIP-eligible only if it
  clears the HF-flutter 16 µs gate (it generally won't — N1024 dies 0/8 there).
- **Carrier spacing < 750 Hz is UNVALIDATED.** The sim is blind to flutter-ICI
  (Table C). Treat any sub-750 Hz rung as HOLD until a flutter-augmented run or a
  physical tape blesses it. "Lossless removes the 562 Hz constraint" is *plausible but
  unproven* — gate it.
- **CRC32-per-codeword miscorrection guard stays ON** (manifest tables). A sim PASS
  with an undetected RS miscorrection is worse than a clean fail.

### 5.5 Recommended master9 ladder (gate-driven)
1. **Anchor (SHIP, proven):** `DQ_P10_N512_sp8 RS127` — the 934 bps record. Re-burn to
   confirm reproducibility; it is the floor (and, per §3, it is *near* its cliff — do
   not assume comfortable headroom).
2. **Push (SHIP-candidate, keep N ≤ 512):** add data carriers or thin RS while keeping
   the pilot rate high — e.g. `DQ_P12_N512` (check spacing ≥ 562 Hz) or
   `DQ_P10_N512 RS111`. Must clear all of §5.3 incl. the HF-flutter cell. Because the
   record already sits near its timing cliff, **the realistic master9 gain is modest
   (thinner RS / a couple more carriers), not 2–5×, unless a structurally better
   timing front-end is added** (e.g. a second pilot for higher-order timing, or
   per-carrier phase tracking on the high carriers that R2 shows carry all the error).
3. **Stretch (HOLD, experimental):** at most one dense-grid or D8PSK rung, carried only
   to gather real-tape data on the flutter-ICI / phase-noise frontier. R2 shows D8PSK
   would already fail (8.9 % of N512 symbols inside its 22.5° boundary even on the
   PASS rung). Label experimental; never count toward the headline.

---

## 6. Key uncertainties (stated honestly)
- Real jitter measured on the DQPSK pilot (tonality 0.68) — the 5–200 Hz figure is a
  **conservative lower bound** (tighter bandpass −30 %; a sounder tone higher). The
  ~100× sim gap survives both — direction certain, magnitude ±~2×.
- The HF-flutter injection reproduces the **N512/N1024 timing differential** (its
  purpose) but is a *jitter-only* proxy; it does not model frequency-selective fade
  dynamics. Use it as the timing gate, not as a full channel.
- The injection's validating level (12–16 µs of 5–23.4 Hz jitter) is calibrated to the
  m8 tape; a different deck/tape may sit elsewhere. **Re-measure the real pilot jitter
  on the first master9 capture and re-anchor the gate level** before trusting it for a
  second tape.
- dg lossless recalibration (0.58) is a recommendation from single-/few-seed probes;
  re-validate with ≥4 seeds against the m8 real per-rung BERs before trusting master9
  frequency-domain rungs.
