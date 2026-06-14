# MASTER9 — Final Adjudicated Plan

**Adjudicator synthesis of designs A / B / C** · 2026-06-10 · branch `deepdive-3-overnight`
**Anchor record:** 934 net bps (DQPSK P10 N512 sp8 750 Hz, RS(255,127), 0/62 cw failed on m8 tape)
**Mandate:** the best *implementable* master9 tape (≤ ~16 min audio, single recording, robust-early →
stretch-late) that honestly maximizes proven net bps, with ≥2 near-certain new records, several
mid-risk 1.5–3× rungs, and ≤2 moonshots. R2 measurements and R6 sim caveats outrank designer enthusiasm.

---

## 0. Adjudication: what each design got right, and the conflicts resolved

All load-bearing facts below were re-verified against the actual code (`h4_dqpsk.py`, `A_ladder.json`)
this session, not taken on a designer's word.

### 0.1 The decisive conflict — the 2× density axis (C wins, A/B's headline is downgraded)

The three designs offer two different paths to ~2× rate. They are **not** equivalent:

| path | spacing | asserts (verified) | code change | sim status | attacks the binding impairment? |
|---|---|---|---|---|---|
| **A3/A4/A5, B1/B1b — dense 22c @ 375 Hz, N512** | 375 Hz | orth `(4·384)%512=0` PASS; top 9000≤9500 PASS; **floor `375≥562` FAILS** (`h4_dqpsk.py:101`) | **YES** — must relax the frozen floor assert | **UNVALIDATED** (R6 §5.4: sim is blind to flutter-ICI <750 Hz; Table C off-bin energy there is the reverb skirt, not flutter sidebands) | **No** — adds density on the sim-blind axis |
| **C R3 — N256 sp4 @ 750 Hz** | 750 Hz | orth `(4·192)%256=0` PASS; top 8250≤9500 PASS; floor `750≥562` PASS | **NONE** | proven frequency grid; only the symbol length is new | **Yes** — halves symbol period ⇒ doubles pilot update rate (187.5 Hz) |

Verified arithmetic: N256, df=187.5 Hz, b0=round(750/187.5)=4, carriers {750,1500,…,8250} Hz, pilot 4500 Hz
— **bit-identical to the 934 record's frequency plan**. gross = 2·10/(256/48000) = 3750.

**Why C's path wins as the headline 2× bet:** R2 §2/§5 + R6 §3/§5.4 are unanimous that the record is
**timing-cliff-limited**, not noise- or density-limited (min margin 0.04°; N1024 died *because* its
pilot rate halved). The N256 rung moves the binding risk axis the *right* way — half the per-symbol
flutter drift, double the correction rate — while the 375 Hz/N512 rungs move density on the exact axis
the sim cannot vouch for and that needs a frozen-code change. At matched RS the two paths deliver near-
identical net bps (R3 RS159 = 2338 vs A3 RS159 = 2572), so there is no rate reason to prefer the riskier
path. **R6 §5.4 "prefer shorter symbols at equal net rate" is explicit and decides this.**

**A/B's 375 Hz dense rungs are therefore demoted from headline to a single, code-gated, sim-unvalidated
HOLD stretch (M8)** — carried only to gather real-tape flutter-ICI data for master10, never counted as a
sim-blessed record.

### 0.2 What each design contributes to the final ladder

- **From A (proven-PHY scaler):** the RS-thinning backbone on the proven N512 grid (M1/M2). This is the
  lowest-risk path to a new record and A is right that it is "nearly free" (0/62 cw failed at RS127, a
  ~14× over-provision). Adopted as the near-certain records.
- **From C (portfolio optimizer):** (a) the N256 short-symbol centerpiece (M4) — the structurally correct
  2× bet; (b) RS-bracketing so a correlated miss *locates the cliff* instead of just losing (M1/M2 bracket
  N512, M4/M5 bracket N256); (c) the drop-3750-Hz-null rung (M3) — free margin, since that one carrier
  threw 401/1138 = 35% of all raw errors per R2 §0; (d) the two measurement probes. Adopted wholesale —
  this is the EV-optimal structure for a near-cliff record.
- **From B (modern receiver):** the **resampling timing PLL** front-end upgrade (continuous sub-sample
  `τ̂(t)` tracking via the same polyphase-resample mechanism the validated gate uses) — this is the
  "structurally better timing front-end" R6 §5.5 says is required to beat the record by more than thin RS,
  and it is a strict superset of the proven h4 pilot loop, so it is safe to adopt ladder-wide. Also B's
  null-subcarrier residual-CFO trim. **B's coherent CP-OFDM 16-QAM moonshot (B3/B4) is kept as the single
  experimental order-axis HOLD**, but downgraded below C's frequency-differential idea on EV grounds
  (16-QAM amplitude stability is exactly where R6 §2 says the sim is blind; it is a pure real-tape gamble).

### 0.3 Conflicts explicitly resolved against research

| claim | designer | verdict | basis |
|---|---|---|---|
| "375 Hz/N512 dense is low-risk, the new-record band" | A (A3 "low"), B (B1 "low") | **Downgrade to HOLD** | floor-assert change required; R6 §5.4 sim-UNVALIDATED <750 Hz |
| "N256 short-symbol is the honest 2×" | C (R3) | **Adopt as centerpiece** | passes all asserts, proven grid, R6 §5.4 prefers short symbols |
| "Blanket / strong-carrier D8PSK viable" | A (A6), C (R-D8) | **Demote to single HOLD probe** | R2 §0: 8.9% of *passing*-rung symbols already inside D8PSK boundary; R6 §2 sim optimistic ~5× |
| "Coherent 16-QAM is the 3× moonshot" | B (B3) | **Keep as the one order-axis HOLD** | R1 Part 2 closes only on strong carriers; R6 §2 sim blind to its amplitude stability |
| RS191 on proven grid is "low" risk | A (A2 "low"), C (R1b "low") | **Grade low, but it is the upper cliff-bracket** | RS191 t=32 vs measured per-carrier SER up to 6.3%; near the byte-margin floor |

---

## 1. The final master9 ladder (10 rungs, robust → stretch)

All rungs share the common receiver chain (§2), an unmodulated mid-band pilot (mandatory self-tracking,
R6 §5.4), master3 TX pre-emphasis, Schroeder multitone phasing (PAPR control, R1 §4), CRC32-per-codeword
manifest guard (R3), and h9-gzip-packed `stories260K_int4.cass` payload slices at staggered offsets.
Net-bps = gross·k/255, gross = 2·P/(N/FS), FS=48000 — every figure recomputed and verified this session.

| # | name | source | P | N | spacing | carriers (Hz) | pilot (Hz) | const. | RS(255,k) | gross | **net bps** | × rec | tape s | risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **M0** | reprove-934 | A0/B0/C-R0 | 10 | 512 | 8b/750 Hz | 750–8250 (proven 10) | 4500 | DQPSK | 127 | 1875 | **933.8** | 1.00 | 42 | **proven** |
| **M1** | thin-159 | A1/C-R1a | 10 | 512 | 8b/750 Hz | 750–8250 | 4500 | DQPSK | 159 | 1875 | **1169.1** | 1.25 | 50 | **low** |
| **M2** | thin-191 (N512 cliff-bracket) | A2/C-R1b | 10 | 512 | 8b/750 Hz | 750–8250 | 4500 | DQPSK | 191 | 1875 | **1404.4** | 1.50 | 42 | **low** |
| **M3** | drop-null-9c | C-R2 | 9 | 512 | 8b/750 Hz | 750–3000,5250–8250 (no 3750) | 4500 | DQPSK | 159 | 1687.5 | **1052.2** | 1.13 | 55 | **low** |
| **M4** | N256-short-symbol **CENTERPIECE** | C-R3 | 10 | 256 | 4b/750 Hz | 750–8250 (proven 10) | 4500 | DQPSK | 159 | 3750 | **2338.2** | 2.50 | 30 | **medium** |
| **M5** | N256-rs179 | C/adj | 10 | 256 | 4b/750 Hz | 750–8250 | 4500 | DQPSK | 179 | 3750 | **2632.4** | 2.82 | 26 | **medium** |
| **M6** | N256-rs191 (N256 cliff-bracket) | C-R3b | 10 | 256 | 4b/750 Hz | 750–8250 | 4500 | DQPSK | 191 | 3750 | **2808.8** | 3.01 | 24 | medium-high |
| **M7** | N256-P11-9000 | adj (new) | 11 | 256 | 4b/750 Hz | 750–9000 (11) | 4500 | DQPSK | 179 | 4125 | **2895.6** | 3.10 | 24 | high |
| **M8** | dense-375 (flutter-ICI probe) | A3/B1 | 22 | 512 | 4b/375 Hz† | 750–9000 (22) | 4875 | DQPSK | 159 | 4125 | **2572.1** | 2.75 | 36 | **HOLD** |
| **M9** | freq-differential **OR** coh-16QAM-strong (pick ONE) | C-R-LOT / B-B4 | 11/10 | 512 | 8b/750 Hz | see §1.3 | mid | F-DQPSK / 16QAM | 159/127 | 1875/3158 | **1169 / 1573** | 1.25 / 1.68 | 46 / 37 | **lottery / HOLD** |

† **M8 is the ONE rung requiring a frozen-code change** (relax `h4_dqpsk.py:101` `spacing*df>=562` to a
`min_spacing_hz` kwarg defaulting to 562; the orthogonality assert L115 already passes at sp4). It is a
HOLD by rule (sim-unvalidated <750 Hz, R6 §5.4) and never counts toward the headline.

**Tape budget:** body info-time ≈ 233 s + per-frame overhead (~0.37 s × ~20 frames/rung × 10 rungs ≈ 70 s)
+ global sync ≈ 17 s + two probes ≈ 28 s ≈ **6.3 min of 16** — leaving ~9.7 min spare. **The spare is
deliberately reserved (per C FACT 1):** burn a **second realization of M4** (different payload offset) for
variance reduction on the single highest-value bet, and lengthen M0/M1/M2 payloads so each yields
≥30 codewords for statistically meaningful real per-carrier SER. Variance reduction beats headline padding
when the headline rung is fragile.

### 1.1 Net-bps arithmetic (one worked line per distinct axis)

- **RS axis (M2):** gross = 2·10·(48000/512) = 1875; net = 1875·191/255 = **1404.4 bps**.
- **Short-symbol axis (M4):** gross = 2·10·(48000/256) = 3750; net = 3750·159/255 = **2338.2 bps = 2.50×**.
- **Short-symbol + RS thin (M6):** net = 3750·191/255 = **2808.8 bps = 3.01×** — *crosses 3× on the proven
  frequency grid with no code change*, the headline-if-it-lands.
- **Short-symbol + extra carrier (M7):** gross = 2·11·(48000/256) = 4125; net = 4125·179/255 = **2895.6 bps**.
- **Density axis (M8, HOLD):** gross = 2·22·(48000/512) = 4125; net = 4125·159/255 = **2572.1 bps**.
- **Drop-null (M3):** gross = 2·9·(48000/512) = 1687.5; net = 1687.5·159/255 = **1052.2 bps**.

### 1.2 Why this ordering (robust-early → stretch-late)

M0–M3 are the near-certain band (proven N512 grid, RS-thinned / null-dropped): the tape *cannot come back
empty*. M4–M7 are the N256 record push, laid in increasing risk (RS159→179→191, then +carrier). M8 is the
single code-changed density probe. M9 is the single structurally-novel lottery. If the deck/levels drift
during the take, the high-value M4–M7 rungs sit in the *middle* of the tape (best-tracked region), not the
fragile head or tail.

### 1.3 M9 — pick ONE before burn (the single experimental slot)

The ladder carries **exactly one** experimental rung in slot M9 (the second moonshot beyond M8). Choose by
which question master10 most needs answered; freeze the choice before the run:

- **Option M9a — frequency-differential DQPSK (C R-LOT, preferred):** bits on carrier k =
  `angle(c[i,k]·conj(c[i,k-1]))` *within the same symbol*. Common symbol-timing jitter cancels identically
  — immune to the exact failure mode that caps the record. P11 N512 sp8 (10 diff-pairs), RS159, sounder-H(f)
  tilt de-rotation per pair, skip the pair straddling 3750 Hz. net = **1169 bps**. **Preferred** because if
  it lands clean, master10's *entire architecture* pivots away from time-differential and timing jitter stops
  mattering — a paradigm result worth a 46 s ticket at P≈0.3. Value is information, not rate.
- **Option M9b — coherent 16-QAM on strong carriers (B B4):** 10 strong carriers (750–3000, 5250–6000 Hz)
  × 16-QAM, N512+CP96, scattered-pilot EQ, RS127. net = **1573 bps**. The clean isolated test of whether
  coherent higher-order is viable on tape at all. Higher rate but R6 §2 says the sim is *blind* to the
  amplitude stability it needs — pure real-tape gamble, and it needs the new `CohOFDMScheme` code.

**Recommendation: M9a.** It needs no new constellation-EQ code (reuses the DQPSK DFT front-end with a
frequency-axis difference), and it directly attacks the binding impairment rather than the order axis the
sim cannot vet. M9b is the alternate if the team prefers to probe the order axis and is willing to write
`CohOFDMScheme`.

---

## 2. Receiver architecture (precise enough to implement)

One chain serves every rung; it is a strict superset of the proven `h4_dqpsk.DQPSKScheme.demod`, so M0
decodes through it unchanged (regression anchor). Adopted from C's chain + B's resampling-PLL upgrade.

### 2.1 Global sync (once per tape — unchanged, proven `m8_decode` path)
1. Cross-correlate the up-chirp (`f0=500, f1=5000 Hz, T=0.20 s`) for tape start; the down-chirp gives total
   span ⇒ **static deck-clock scale** (m8: +0.117 %). `resample_poly` the whole capture by `1/(1+clock)` to
   the 48 kHz nominal grid. **Static clock ≠ flutter** — removed once here; flutter is the residual the pilot
   tracks (R4 §14.2).
2. Front Schroeder sounder (64 tones, 300–11000 Hz, ×2) → `measure_sounder_eq` (h4 L261–288) → per-capture
   `|H(f)|`, anchored to each section's carriers (m8 used a −2.25 dB median shift). Seeds the M9a tilt
   de-rotation and the per-carrier amplitude reference.

### 2.2 Per-rung, per-frame demod (the proven loop + resampling-PLL upgrade)
For each frame (window = nominal start − `PAD_LO=0.30 s`, + frame len + `PAD_HI=0.05 s`):
1. **Frame sync:** `hc.find_preamble` on the 0.25 s chirp preamble → sample offset `ds`.
2. **Per-symbol complex DFT** at each of `nc=P+1` carrier freqs over the `Nw=N−2·skip` Hann window
   (`skip=N//8`: 32 @ N256, 64 @ N512), exponent on the **absolute sample index** so window re-centering is
   phase-transparent (each `f_k·N/FS` is an integer bin).
3. **Stage-1 — resampling timing PLL (B upgrade, replaces h4's integer `drift` clamp):** the unmodulated
   pilot drives a 2nd-order PLL on its symbol-to-symbol differential phase `dp = angle(c[i,p]·conj(c[i−1,p]))`,
   yielding `dtau = dp/(2π·f_pilot)` and its rate. Loop BW = **30 Hz** (R2 f90=28.6 Hz). Instead of snapping
   the window to an integer offset, **resample the symbol stream onto `t − τ̂(t)`** with a polyphase
   interpolator (the same `np.interp`/`resample_poly` mechanism `x9_flutter_gate.channel_gate` uses). This
   converts wideband flutter (every tone scaled by the same `τ̇`) into a small residual CFO before the FFT —
   the canonical UWA two-stage move (R5 §2.2). *Fallback:* if the PLL underperforms in sim regression, revert
   to the proven EMA(α=0.5) integer-drift clamp (it is what won the record). **At N256 the pilot updates at
   187.5 Hz — strictly tighter than N512's 93.75 Hz** (the whole point of M4).
4. **Stage-2 — null-subcarrier residual-CFO trim (B, coherent/dense rungs only):** reserve 2 null bins
   (M8 only); minimize their post-FFT energy with a per-block Newton step and de-rotate. (Differential rungs
   M0–M7, M9a skip this — they have no spare carriers and differential phase already cancels static CFO.)
5. **Differential decision:** `d = c[1:]·conj(c[:-1])` per data carrier (time-differential for M0–M8;
   **frequency-differential** `c[i,k]·conj(c[i,k−1])` for M9a), subtract the pilot common-timing term
   `2π·dtau·f_k`, slice to the constellation grid (QPSK π/2; D8PSK π/4 only if M9b chosen).
6. **Stage-3 — one-shot decision-directed refinement** (proven, kept): LS-fit residual common-timing slope
   `dtau_res` vs carrier frequency, subtract, re-decide. R2 §2: cuts per-symbol residual 16.5 → 5.4 µs.
7. **Carrier-block bit mapping** (`bits_to_quadrants`): data carrier *j* carries the *j*-th contiguous bit
   block, so a dead carrier corrupts a *contiguous* byte slice (RS-friendly) not every byte.

### 2.3 FEC + guard (merge layer, `m8_decode` pattern — mandatory)
1. Column-de-interleave per-frame bits → RS(255,k) codewords (`m3_codec.decode_payload`), errors-only;
   optionally errors-and-erasures keyed on the pilot `gap`/`lock` reliability metric.
2. **CRC32-per-codeword manifest guard ON** (R3, R6 §5.4): any RS "correction" whose message-CRC32 fails the
   manifest table is rejected as a miscorrection. Proven 0 silent miscorrections — non-negotiable.
3. h9-unpack (gzip) → verify orig CRC + length + per-section sha256 → byte-exact.

### 2.4 Per-rung receiver sweep (decode-time, no PHY change — R3 §5 mandatory)
Every fixed-grid rung on m8 died from ~0.75-symbol/frame timing wander, and R3 found a *free* win was missed
by fixing on one trajectory kind. Per rung, sweep and pick the CRC-verified byte-exact winner over:
- timing front-end ∈ {resampling-PLL (default), pilot-EMA α∈{0.4,0.5,0.6}, h5/h6 freq-trajectory bw∈{0.05,0.08,0.10,0.25 Hz}};
- RS mode ∈ {errors-only, errors+erasures @ erase-frac {0,0.25,0.5}} (CRC-guarded, so erasures can never miscorrect).

### 2.5 Rung-specific notes
- **M9a (freq-differential):** carrier 0 is the per-symbol phase reference (anchored by the pilot/H(f) tilt);
  de-rotate each pair by the sounder-measured channel tilt between adjacent 750 Hz carriers before slicing;
  skip the pair straddling the 3750 Hz null.
- **M9b (16-QAM):** needs `CohOFDMScheme` (model on `experiments/capacity/c4_ofdm_bitload.py`: N_FFT=512,
  N_CP=96, DRM scattered pilots every 4th symbol × 3rd carrier, +3 dB pilot boost, per-carrier `H_est[c,t]`
  divide before slicing, DD amplitude EMA α=0.9 per R4 R-6).

---

## 3. Diagnostic probes (what master10 needs — ~28 s, decode-only, no manifest dependency)

Adopted from C (the highest-leverage pair) with one element from B/A. Placed right after the front sounder.

### P1 — Repeated-sounder stationary-null map (~12 s)
Emit the **same Schroeder sounder 3× back-to-back** (4 s each, low PAPR). Decode per-bin |H(f)| across the
three repeats: a bin consistently ≤ −40 dB in all three is a **real stationary null** (master10 skips/bit-loads
around it); a bin deep in only one repeat is flutter/fade jitter. **Measures:** the master3 −49 dB H(f) spikes
we currently *smooth as artifacts* (R1, R6 §1b) — are they real nulls? Plus the true coherence bandwidth (how
many adjacent bins a null spans) — the exact input M9a (freq-differential) and any dense rung need to place
carriers, and the input that turns the 375 Hz/188 Hz density question into a measured go/no-go.

### P2 — Pilot-jitter re-anchor + tape-saturation knee (~16 s)
Two sub-probes:
- **(a) 8 s continuous 4500 Hz pilot tone** → heterodyne+unwrap→Welch-PSD the instantaneous timing jitter and
  **re-measure the 5–23.4 Hz band-RMS on THIS tape/deck** (m8 = 33.9 µs). R6 §6 is explicit: *re-measure on the
  first master9 capture and re-anchor the gate level before trusting it for a second tape.* This is the single
  most load-bearing number for sizing master10's N and RS — it converts the HF-flutter gate from m8-calibrated
  to master9-calibrated.
- **(b) 8 s multitone level-ramp:** the 10-carrier Schroeder multitone (PAPR ~5 dB) at 4 rising amplitudes
  (−12, −9, −6, −3 dBFS pre-tape). Decode measures the **IMD floor vs level = the AM/AM saturation knee** R1
  currently only flags qualitatively ("record level >7 saturates"). **Measures:** the real PAPR backoff budget
  — how hard the tape can be driven before IMD eats dense-carrier margin, setting whether a 16/22-carrier dense
  rung is physically possible at all (gates master10's M8-class rungs independent of timing).

---

## 4. Pre-registered gates (per R6 §5 — FROZEN before any sim run)

### 4.0 Channel config (fixed)
- **Nominal:** `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)` (R6 §4: lossless captures
  → AAC off; dg recalibrated to the 0.55–0.60 lossless branch, **re-validated ≥4 seeds against m8 per-rung
  BER before trusting any rung**).
- **Sanity bound:** also `profile='tape4'` (quieter take).
- **Seeds:** nominal axis **8 seeds {0..7}**; each stress axis **4 seeds {0..3}**. All logged. Never trust one
  seed (the m8 N512 record flipped on seed 2 of the 16 µs injection).

### 4.1 Stress envelope (fixed)
| axis | setting | why |
|---|---|---|
| **HF-flutter (mandatory)** | inject 5–23.4 Hz band jitter @ {12, 16, 20} µs RMS (`x9_flutter_gate.py`) | the ONLY axis that emulates the 142× timing blind spot; validated to reproduce N512-pass/N1024-fail |
| flutter_residual_frac | 0.15 → 0.30 (minor axis) | scales wow only; does NOT substitute for the HF cell |
| SNR delta | −2, −4 dB | sim SNR is honest |
| clock offset | ±0.15 % static resample | exercises chirp-resync (deck +0.117 %) |
| reverb τ | ×{0.5, 1.0, 1.5} | CP/ISI sizing margin (matters for M8/M9b) |
| AAC | **dropped** (lossless) | no longer the adversary |

### 4.2 SHIP / HOLD / REJECT rule (frozen). HF-flutter SHIP threshold = **12 µs**; 16 µs is the headroom cell.

A rung **SHIPs** iff ALL of:
1. **Nominal:** ≥ 7/8 seeds byte-exact (aac=False, dg=0.58).
2. **dg-pessimism:** ≥ 6/8 seeds byte-exact at dg=0.65.
3. **HF-flutter 12 µs:** ≥ 3/4 seeds byte-exact with the 5–23.4 Hz injection (the gate h8 lacked). *The record
   itself passes 12 µs 3/4 and is on its cliff at 16 µs 1/4 — so 12 µs is the SHIP line, 16 µs marks genuine
   headroom the record lacks.*
4. **Combo SNR −2 dB AND flutter_frac 0.30:** ≥ 3/4 seeds byte-exact.
5. **Byte-margin floor:** mean **byte**-error-rate over nominal seeds ≤ 0.6 × (255−k)/(2·255)
   (RS127 → 0.151, RS159 → 0.113, RS179 → 0.089, RS191 → 0.075). Measure on **bytes**, not bits.

A rung is **HOLD** (experimental, never headline) iff it passes 1,2,5 but fails timing gate 3 or 4.
A rung is **REJECT** iff it fails nominal (1) or the byte-margin floor (5).

**Hard structural rules (non-negotiable):** self-tracking pilot in every rung; CRC32-per-codeword guard ON;
spacing < 750 Hz is HOLD until a flutter-augmented run or physical tape blesses it; shorter symbol is the
default at equal rate.

### 4.3 Pre-registered per-rung verdict expectation (score results against intent)
| rung | expected verdict | rationale |
|---|---|---|
| M0 reprove | **SHIP** | it IS the record; if it fails the gate, the gate is mis-scaled — abort & re-anchor on P2 |
| M1 rs159 | **SHIP** | proven grid, more RS slack than M0 used |
| M2 rs191 | **SHIP / cliff-bracket** | RS191 t=32 near the byte floor (gate 5 cap 0.075); may land HOLD — that's the bracket's purpose |
| M3 drop-null | **SHIP** | strictly easier than M0 (worst carrier removed) |
| **M4 N256 rs159** | **SHIP iff clears 12 µs HF-flutter** | the centerpiece; its tracker Nyquist is 93.75 Hz so it follows 5–23.4 Hz *better* than N512 — physics predicts PASS, the gate decides headline-eligibility |
| M5 N256 rs179 | **SHIP-candidate** | N256 + moderate RS; gate 5 (cap 0.089) the binding test |
| M6 N256 rs191 | **HOLD-likely** | RS191 byte-margin × N256-novel; the upper N256 cliff-bracket |
| M7 N256 P11 | **HOLD** | 9000 Hz past the proven 8250 edge into deeper rolloff |
| M8 dense-375 | **HOLD by rule** | sim-UNVALIDATED <750 Hz; real-tape evidence only |
| M9 (a or b) | **HOLD/lottery by rule** | sim can't faithfully vet a new mapping (M9a) or 16-QAM amplitude (M9b) |

**Headline policy:** only rungs that SHIP under all five gates count toward the master9 headline. Realistically
that is M0/M1/M2/M3 for sure (≥1404 bps banked) and M4 (+M5) if the HF-flutter gate clears → **honest
defensible headline 2338–2632 bps (2.5–2.8×)**, with M6/M7 (≈3×) as real-tape stretch upgrades and M8/M9 as
information HOLDs that may upgrade the record only on a CRC-verified real decode.

---

## 5. Implementation work breakdown

### 5.1 New files
- **`m9_master.py`** — tape builder. Extends `m8_master.py`. Reads a `m9_ladder.json` (derive from
  `A_ladder.json` + the M3–M9 additions in §1). Builds: global up-chirp → front Schroeder sounder ×2 →
  **P1 (sounder ×3)** → **P2 (pilot tone + level-ramp)** → rungs M0…M9 (each: per-frame 0.25 s preamble +
  DQPSK/F-DQPSK/16-QAM section + 0.12 s gap) → down-chirp. Schroeder phasing on every multitone. Peak-normalize
  0.70, record SOP level ~7.0, Dolby OFF.
- **`m9_decode.py`** — decoder. Extends `m8_decode.py`. Global sync (§2.1) → per-rung demod via the common
  chain (§2.2–2.4) → RS+CRC merge (§2.3) → per-rung byte-exact + per-carrier SER report to
  `results/m9_decode_results.json`.
- **`m9_sim_validate.py`** — pre-registered gate harness (§4). Wraps `sim_v2.channel_v2` + `x9_flutter_gate.py`,
  runs the 5-gate matrix per rung over the frozen seed/stress grid, emits SHIP/HOLD/REJECT to
  `results/m9_gate.json`. **Run this BEFORE burning** — it sets which rung is the headline.
- **`x9_resampling_pll.py`** — the Stage-1 resampling timing PLL (§2.2.3) as a drop-in front-end module,
  importable by `m9_decode.py`. Strict superset of the h4 EMA loop (must regression-pass M0 byte-exact in sim).
- **`x9_freqdiff.py`** (only if M9a chosen) — frequency-differential map + sounder-tilt de-rotation.
- **`m9_ladder.json`** — the verified params for all 10 rungs (this plan's §1 table + per-carrier bitload).

### 5.2 One frozen-code change (M8 only, gated)
Relax `h4_dqpsk.py:101` `assert spacing*df >= 562.0` → behind a `min_spacing_hz` kwarg defaulting to 562 (so
M0–M7, M9 paths are untouched). **Only M8 passes `min_spacing_hz=375`.** Do this on the feature branch; never
push to master. The orthogonality assert (L115) already passes at sp4 — no DSP change.

### 5.3 Build + test order
1. `x9_resampling_pll.py` → unit: regression-decode M0 in sim byte-exact through the new front-end (if it
   can't reproduce the proven record, the PLL is broken, not the channel). **Gate: must pass before anything else.**
2. `m9_ladder.json` → `m9_sim_validate.py` → run the §4 gate matrix on M0–M7 (M8/M9 only after the code change).
   This selects the headline rung. **No tape is burnt until the gate matrix is logged.**
3. `m9_master.py` → build `master9.wav`, verify it round-trips through `sim_v2` + `m9_decode.py` byte-exact at
   high SNR (sanity, no channel) for every rung.
4. Burn → capture (Voice Memos lossless, project SOP) → `m9_decode.py` → real per-rung result.
5. **First action on the real capture:** run P2(a) → re-anchor the HF-flutter gate level → re-confirm M4–M7
   verdicts against the *master9-measured* jitter before claiming any record.

### 5.4 Parallelization (no file conflicts)
- **Track A (front-end):** `x9_resampling_pll.py` + `x9_freqdiff.py` — independent modules, parallel.
- **Track B (ladder/build):** `m9_ladder.json` + `m9_master.py` — depends only on this plan, parallel to A.
- **Track C (gate harness):** `m9_sim_validate.py` — depends on `m9_ladder.json` (Track B) and the front-end
  (Track A); start its scaffold in parallel, wire imports when A/B land.
- `m9_decode.py` integrates all three — single owner, last.

---

## 6. Honest expected-outcome table

P(land) calibrated to the dossiers: proven N512 + thinner RS ~0.85–0.92; N256 (untested symbol length but
right-direction physics, sim-gateable) ~0.55; dense-375/freq-diff/16-QAM 0.20–0.35. Expected new-record =
highest net bps among rungs likely to land byte-exact on the real tape.

| rung | net bps | × rec | P(land byte-exact) | E[contribution] | if it fails, we learn |
|---|---|---|---|---|---|
| M0 reprove | 934 | 1.00 | 0.97 | canary | channel/levels regressed → abort ladder |
| M1 rs159 | 1169 | 1.25 | 0.92 | **near-certain record #1** | RS159 cliff below expectation |
| M2 rs191 | 1404 | 1.50 | 0.80 | **near-certain record #2** | locates N512 cliff between t=32 and t=48 |
| M3 drop-null | 1052 | 1.13 | 0.90 | confirms null-excision margin | 3750 Hz wasn't the problem; margin story wrong |
| **M4 N256** | **2338** | **2.50** | **0.55** | **expected new record (the bet)** | short-symbol ISI/flutter-within-window dominates |
| M5 N256 rs179 | 2632 | 2.82 | 0.45 | stretch record | N256 RS budget pinned (with M4) |
| M6 N256 rs191 | 2809 | 3.01 | 0.30 | upper N256 bracket | locates N256 cliff in one shot |
| M7 N256 P11 | 2896 | 3.10 | 0.22 | top-end probe | 9000 Hz past usable rolloff edge |
| M8 dense-375 | 2572 | 2.75 | 0.30 | real flutter-ICI datum for master10 | 375 Hz spacing is a leakage trap |
| M9a freq-diff | 1169 | 1.25 | 0.30 | **paradigm result** if it lands (timing stops mattering) | channel tilt over 750 Hz exceeds QPSK margin |

**Expected new record (honest):** the most likely *actually-landing* record is **M2 at 1404 bps (1.50×)** as
the near-certain floor, with **M4 at 2338 bps (2.50×)** as the expected headline if its HF-flutter gate clears
(P≈0.55) — and a real shot at **M5/M6 ≈ 2.8–3.0×** on the upside. Probability-weighted, the single best
point estimate for the new master9 record is **≈ 2000 bps (≈ 2.1×)**: near-certain past 1400, more-likely-
than-not past 2300, with genuine 3× upside on the N256 cliff-bracket and pure-information HOLDs (M8/M9) that
can only upgrade — never downgrade — the headline.

### Bottom line
Burn the M-ladder: **M0 (proven floor) → M1/M2 (near-certain 1.25–1.5× records, RS-thinned proven grid) →
M3 (free null-excision margin) → M4 (2338 bps centerpiece — short-symbol N256, the structurally-correct 2×
on the proven frequency plan with no code change) → M5/M6/M7 (the N256 cliff-bracket, headline-if-it-lands
to ~3×) → M8 (single code-gated 375 Hz flutter-ICI HOLD) → M9a (frequency-differential lottery)** — plus the
two probes that hand master10 its three missing numbers (stationary-null map, re-anchored 5–23 Hz jitter, IMD
saturation knee). Defensible target **2.5× (M4)**; near-certain floor **1.5× (M2)**; stretch **3× (M6)**.
