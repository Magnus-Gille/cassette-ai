# B_design.md — master9, Designer B ("modern receiver moonshot")

**Author:** Designer B · **Date:** 2026-06-10 · **Branch:** deepdive-3-overnight
**Mandate:** highest rate a *modern receiver architecture* can honestly defend on
the measured cassette acoustic channel — dense pilot-tracked OFDM with a cyclic
prefix, scattered/continual pilots, and a resampling timing PLL (UWA/DRM receiver
chains from R5), with bit-loaded coherent constellations on the strong carriers
R2 measured. Every parameter is justified by a dossier number; fallback rungs are
proven-PHY anchors so the tape cannot come back empty.

Anchors used throughout (all measured, all cited):
- Record: DQPSK P10 N512 sp8 RS127 = **934 net bps**, raw SER 1.8 %, 0/62 cw failed (R1 Part 5, R2 §0).
- Cross-bin leakage on the **lossless** capture: ~150–200 Hz spacing supportable at 20–25 dB SIR; clean skirt plateau ~30 dB at 200–500 Hz; 562 Hz AAC floor is OBSOLETE (R2 §4).
- Per-carrier out-SNR (R2 §3): strong = 750–3000 Hz (16.2/13.7/13.9/14.6 dB) and 5250–6000 Hz (12.2/11.8 dB); 3750 Hz is a deck null (8.2 dB, SER 6.3 %); 6750–8250 Hz weak (7.7–9.0 dB).
- Flutter required tracking BW ~28.6 Hz (f90); per-symbol pilot EMA residual 13.5 µs, decision-directed 5.4 µs (R2 §2). N1024 dies because pilot rate halves (R2 §5).
- Reverb diffuse tail τ ≈ 7.9 ms; deck clock +0.117 %; SNR median 38.3 dB / p10 33.1 (R1).
- Sim is **honest in frequency, blind in timing** — ~100–200× too little flutter jitter above 5 Hz (R6, R6-audit Table A). The **validated** 5–23.4 Hz HF-flutter gate (`x9_flutter_gate.py`) is the only trustworthy timing stress; SHIP requires clearing it.

---

## 0. Design thesis — where the *receiver* actually buys rate, and where it doesn't

The naïve moonshot is "switch everything to coherent CP-OFDM 16/64-QAM like DRM."
The dossiers say that is a trap at the proven symbol length, and the arithmetic
proves it:

1. **The reverb-ISI floor caps constellation ORDER, not carrier DENSITY** (R1 Part 3).
   No-CP reverb-ISI SIR is 18 dB; a 5.3 ms CP lifts it only to 20.9 dB. DQPSK needs
   18 dB and clears; a 6-dB-margin 16-QAM needs 26 dB and never clears on this channel
   without shortening the acoustic path. So denser SPACING is cheap; higher ORDER is
   the expensive axis. A receiver that just adds a CP does not change this floor.

2. **At N512 a CP is net-negative for same-order rungs.** A CP steals symbol rate:
   22-carrier QPSK differential (no CP) = **2572 net bps** vs the same 22 carriers
   coherent with a 96-sample CP = **2166 net bps** (computed; CP overhead 16 %). The
   8 ms reverb tail is ALREADY cancelled to first order by *differential* phase (R4
   §14.3): ISI from symbol N−1 hits symbols N and N+1 equally, so the phase *difference*
   is clean. A CP only earns its overhead when it unlocks something differential can't —
   namely **coherent higher-order QAM** (16-QAM cannot be done differentially without a
   D16-APSK 11.25° ring that R1 Part 2 shows fails above 6.75 kHz).

3. **Therefore the honest receiver moonshot is two moves, not one:**
   - **(A) Push carrier density with a modern channel tracker.** The proven DQPSK PHY
     already self-tracks via one pilot; replacing the single-pilot EMA with a
     **2D scattered/continual-pilot estimator + a resampling timing PLL** (UWA two-stage
     chain, R5 §2.2) lets us run the 375 Hz (4-bin) grid R2 says is now legal, doubling
     carriers at the same N512 timing safety. This is the workhorse.
   - **(B) Spend a CP only where it unlocks 16-QAM, on the strong carriers only.** R2's
     out-SNR map says exactly which carriers can carry 4 bits (750–3000, 5250–6000 Hz);
     a *coherent* receiver with per-carrier scattered-pilot equalization is the only way
     to read 16-QAM, and it needs the CP to make the channel per-bin flat. Bit-load
     16-QAM there and QPSK elsewhere.

This gives a ladder that is **proven-anchored at the bottom, receiver-engineered in
the middle (the expected new record), and a true coherent-16QAM moonshot at the top** —
each rung justified, each timing-gated.

---

## 1. The master9 receiver chain (Designer-B common front-end)

One front-end serves every rung; rungs differ only in constellation/CP/pilot density.
It is a strict superset of the proven h4 pilot tracker, so the proven rung still
decodes through it unchanged. Stages, in order (this is codeable without guessing):

### 1.1 Global sync (unchanged, proven)
- Up-chirp → front Schroeder sounder (64 tones, 300–11000 Hz, ×2) → sections → down-chirp,
  exactly as `m8_master.py`. `m8_decode.py` recovers deck speed (resample to remove the
  +0.117 % static clock, R1) and aligns on the chirp pair. **Static clock is NOT flutter**
  (R4 §14.2) — it is removed once, globally, by `resample_poly` against the chirp delta.

### 1.2 Per-capture H(f) and per-carrier complex channel seed
- From the front sounder, `measure_sounder_eq` (h4 lines 261–288) gives |H(f)| on the
  64-tone grid, interpolated to each rung's carriers. This seeds the coherent rungs'
  per-carrier channel estimate `H_est[c]` (magnitude from sounder, phase bootstrapped
  from the rung's leading reference symbol). For differential rungs it is TX pre-emphasis
  only (already in h4, lines 122–129).

### 1.3 Stage-1 bulk-Doppler resampling timing PLL (NEW — UWA two-stage, R5 §2.2)
Replaces h4's integer-window `drift` clamp with a continuous **resampling** loop:
- A mid-band **continual pilot** (unmodulated tone, present every symbol) drives a
  second-order PLL on its symbol-to-symbol differential phase: `dtau` (timing) and its
  trend (rate). Loop BW set to **30 Hz** (R2 f90 = 28.6 Hz → track BW ≥ f90).
- Instead of snapping the FFT window to an integer offset, **resample the symbol stream
  onto `t − τ̂(t)`** with a polyphase interpolator (`scipy.signal` / `np.interp`, the same
  mechanism the validated gate uses in `x9_flutter_gate.channel_gate`). This converts the
  wideband flutter (every tone scaled by the same `τ̇`) into a small residual CFO before
  the FFT — the canonical Stojanovic/Freitag UWA move (R5 §2.2, PMC4789520).
- **Why this beats h4's `drift` clamp:** h4 clips `drift` to ±200 samples and re-centers on
  integers; the resampler tracks sub-sample `τ(t)` continuously, which is what the 5–23.4 Hz
  residual flutter (33.9 µs, R6-audit Table A) demands. This is the structurally-better
  timing front-end R6-audit §5.5 says is required to exceed the record by more than "thin RS".

### 1.4 Stage-2 residual-CFO from null subcarriers (NEW — R5 §2.4)
- Reserve **2 null subcarriers** (zero TX power) per rung, one near each band edge. After
  each FFT, any energy on a null bin is residual CFO; minimize it with a per-block Newton
  step `CFO = −Σ Y[k_null]·Y*[k_null−1] / Σ|Y[k_null]|²` and derotate before slicing.
- Cost: 2 carriers (~4–9 % of a rung's grid). Benefit: drives residual timing below 1 % of
  Δf without decision feedback — the layer h4 lacks (R5 §2.4).

### 1.5 Stage-3 scattered-pilot 2D channel tracking (NEW — DRM, R5 §1.3)
- **Coherent rungs only.** A DRM-style scattered pilot grid: known-phase cells every
  **4th symbol × every 5th carrier** (R5 §1.3), plus the continual mid-band pilot from
  1.3. Time-interpolate pilot phase (flutter coherence time ~100–500 ms ≫ 4-symbol gap →
  safe, R5 Rule 3) and frequency-interpolate across carriers (reverb coherence BW ~125 Hz
  → pilots every 5×375 Hz = 1875 Hz is **too sparse**; densify to every **3rd carrier**
  = 1125 Hz to satisfy R5 Rule 4 BW_coh/2 = 62.5 Hz only loosely — see Risk R-7). This
  yields per-carrier per-symbol `H_est[c,t]`; divide before slicing.
- **Pilot boost +3 dB** (R5 §1.3) for channel-estimation SNR.
- Decision-directed refinement: `H_est[c] = α·H_est[c] + (1−α)·Y[c]/decision[c]`, α=0.9
  (R4 §14.2 R-6), correcting the slow 27 % amplitude CoV on the null carrier (R2 §3).

### 1.6 Stage-4 per-symbol decision-directed timing refinement (proven, kept)
- h4's one-shot LS-slope refinement (lines 221–229): residual phase vs carrier frequency →
  `dtau_res`, re-decide. Proven to cut residual timing 3.1× (R2 §2). Kept verbatim for the
  differential rungs; for coherent rungs it refines the Stage-3 phase.

### 1.7 RS + CRC32-per-codeword miscorrection guard (proven, mandatory)
- `m3_codec` interleaved RS(255,k), **soft erasure** capability: carriers flagged by the
  null-CFO residual or low pilot SNR are marked erasures (RS corrects 2× as many erasures
  as errors). CRC32-per-codeword manifest table guards every correction (R3 conclusion 6;
  0 silent miscorrections across the entire R3 sweep). **Non-negotiable.**

> **Receiver summary in one line:** proven h4 pilot core → upgraded to a resampling
> timing PLL (Stage 1) + null-CFO trim (Stage 2) + DRM scattered-pilot coherent EQ
> (Stage 3, coherent rungs) + the proven DD refinement (Stage 4) + erasure-RS/CRC (Stage 5).

---

## 2. The rung ladder (robust-early → stretch-late)

Carrier grid math: N512, Δf = FS/512 = **93.75 Hz/bin**. 4-bin spacing = **375 Hz**
(orthogonal: 4×384 mod 512 = 0, verified). 8-bin = 750 Hz (proven). The 4-bin 750→9000 Hz
grid has **23 positions** (verified). Coherent CP-OFDM uses the full-N FFT after CP removal,
so all integer bins are orthogonal automatically (the h4 `Nw=3N/4` constraint applies only
to the windowed differential path).

| # | name | PHY | carriers (data) | spacing | N (+CP) | constellation | pilots | RS | gross bps | **net bps** | tape s | risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | reprove | DQPSK diff (h4, no CP) | 10 @ 750–8250 | 750 Hz (8b) | 512 | DQPSK 2b | 1 continual | 127 | 1875 | **934** | 37 | proven |
| B1 | dense-diff | DQPSK diff + Stage1/2 PLL | 22 @ 750–9000 | 375 Hz (4b) | 512 | DQPSK 2b | 1 cont + 2 null | 159 | 4125 | **2572** | 32 | low |
| B1b | dense-diff-thin | as B1, thinner RS | 22 @ 750–9000 | 375 Hz (4b) | 512 | DQPSK 2b | 1 cont + 2 null | 179 | 4125 | **2896** | 29 | medium |
| B2 | coh-QPSK-CP | coherent CP-OFDM | 22 @ 750–9000 | 375 Hz (4b) | 512+96 | QPSK 2b | scattered + 2 null | 159 | 3474 | **2166** | 35 | medium |
| B3 | bitloaded-moonshot | coherent CP-OFDM bit-load | 20 @ 750–9000 | 375 Hz (4b) | 512+96 | 16QAM(9)/QPSK(11) | scattered + 2 null | 159 | 4579 | **2855** | 31 | high |
| B4 | 16QAM-strong | coherent CP-OFDM | 10 @ strong | 375 Hz (4b) | 512+96 | 16QAM 4b | scattered + 2 null | 127 | 3158 | **1573** | 37 | high (proof-of-concept) |

Ladder body ≈ 201 s + 2 probes (33 s) + global sync (8 s) = **242 s ≈ 4.0 min** (budget 16 min — huge headroom; payloads are gzip-packed `stories260K_int4.cass` slices via `h9_payload_codec`, staggered offsets, robust-early ordering).

### 2.1 Net-bps arithmetic, per rung (explicit)

**B0 reprove (proven floor):** symbol rate = 48000/512 = 93.75 sym/s; 10 carriers × 2 bits =
20 bits/sym; gross = 20 × 93.75 = **1875**; net = 1875 × 127/255 = **933.8**. Identical PHY to
the record; re-burn to confirm reproducibility and re-anchor the pilot-jitter gate (R6-audit §6).

**B1 dense-diff (the safe push, expected first new record):** 22 data carriers × 2 bits ×
93.75 = gross **4125**; net = 4125 × 159/255 = **2572.1**. The 375 Hz spacing is licensed by R2 §4
(skirt plateau ~30 dB SIR at 200–500 Hz; 375 Hz sits inside it). The continual pilot + Stage-1
resampling PLL keeps N512 timing safety; RS159 (vs the record's 127) is *raised* protection because
22 carriers spread error across more codewords than 10 did. Same symbol length as the record →
inherits its proven 5–23.4 Hz timing margin.

**B1b dense-diff-thin (stretch the dense rung):** same grid, RS179 → net = 4125 × 179/255 = **2895.6**.
Thinner FEC; the weak HF carriers 6750–8250 (R2 out-SNR 7.7–9 dB) carry the risk. Gated, not assumed.

**B2 coh-QPSK-CP (the receiver-architecture test):** CP = 96 samples (2.0 ms); symbol rate =
48000/608 = 78.9 sym/s; 22 × 2 × 78.9 = gross **3474**; net = 3474 × 159/255 = **2166**. *Lower than
B1* — that is the point: this rung exists to prove the **coherent scattered-pilot chain works on the
real tape at all**, de-risking B3/B4. It carries the same data B1 does at lower rate so a B1 success +
B2 success isolates whether coherence (not just density) survives. Honest: B2 is a stepping stone, not
a record candidate.

**B3 bitloaded-moonshot (the honest record-stretch):** 20 data carriers on the 4-bin grid (3 reserved
as continual+scattered pilots, 2 as nulls → 23 grid − 3 = 20 data, with pilots overlaid on scattered
positions). **9 carriers × 16-QAM (4b)** on the strong set {750,1125,1500,1875,2250,2625,3000, 5250,
5625,6000 Hz}, **11 carriers × QPSK (2b)** on the rest. bits/sym = 9×4 + 11×2 = 58; gross = 58 × 78.9 =
**4579**; net = 4579 × 159/255 = **2855**. This is the rung where the modern receiver earns its keep:
16-QAM is only readable with coherent per-carrier EQ (Stage 3), and only on carriers R2 measured at
≥11.8 dB out-SNR; the CP makes those carriers per-bin flat so 16-QAM closes (R1 Part 2: coh-16QAM
margin +5.3 dB @ 6000 Hz, +11.3 @ 3000 Hz). **2855 net bps = 3.06× the record.**

**B4 16QAM-strong (coherent-16QAM proof-of-concept):** 10 strong carriers × 4 bits × 78.9 = gross
**3158**; net = 3158 × 127/255 = **1573**. Heavy RS127 because 16-QAM raw SER is high even on strong
carriers (R1: amplitude fading is the extra risk vs PSK). Lower net than B3 but it is the *clean
isolated test* of 16-QAM-on-tape — if B3 fails ambiguously, B4 tells you whether it was the 16-QAM or
the bit-loading logic. A diagnostic rung that happens to carry real payload.

### 2.2 Why these and not the alternatives

- **No N1024 anywhere.** R2 §5 / R6-audit §3 are unambiguous: N1024 died 37/37 on the real tape and
  dies 0/8 at the 16 µs gate. Every B rung keeps N ≤ 512 so the pilot updates ≥ 93.75 Hz (R4 §14.4:
  N512 = 1.6× Nyquist over 30 Hz flutter; N1024 = 1.4× and under-tracks). The CP rungs use N512+CP, not
  a longer N — the CP buys ISI immunity *without* lowering the pilot rate below the N512 line.
- **No D8PSK / D16-APSK.** R2 §0: 8.9 % of N512 symbols already sit inside the 22.5° D8PSK boundary on
  the *passing* rung; R1 Part 2: D8PSK fails above 6.75 kHz. Differential higher-order is a dead end on
  this flutter; the path to >2 bits/carrier is **coherent** 16-QAM on strong carriers (B3/B4), not
  differential 8-PSK. This is the core Designer-B departure from a differential-only ladder.
- **No spacing below 375 Hz.** R6-audit §5.4 hard rule: sub-750 Hz spacing is sim-unvalidated for
  flutter-ICI. 375 Hz is the chosen step because R1 Part 3 shows flutter-ICI is ≥37 dB SIR even at
  9 kHz for 4-bin spacing (negligible), and R2 §4 measures the leakage skirt clean there. 188 Hz
  (2-bin) is left for master10 after Probe 1 validates it (R1 Part 3 says 2-bin is 31 dB SIR @ 9 kHz —
  plausible but unproven; gate it).

---

## 3. Pre-registered SHIP / HOLD / REJECT gates (per R6-audit §5.3, frozen before burn)

Run every rung through `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`
(R6 §3: lossless captures → AAC off, dg recalibrated to the 0.55–0.60 branch, re-validated ≥4 seeds
against m8 per-rung BER first). Sanity-bound with `profile='tape4'`. All seeds logged.

A rung is **SHIP** iff ALL of:
1. **Nominal:** ≥ 7/8 seeds byte-exact at (aac=False, dg=0.58).
2. **dg-pessimism:** ≥ 6/8 seeds byte-exact at dg=0.65.
3. **HF-flutter timing gate (the gate h8 lacked):** ≥ 3/4 seeds byte-exact under the **validated**
   5–23.4 Hz injection at **16 µs** RMS (`x9_flutter_gate.gate_jitter` / `channel_gate`). The record
   passes 12 µs (3/4) and is on its cliff at 16 µs — so a rung clearing 16 µs has *genuine* timing
   margin the record lacks. **Freeze the threshold at 16 µs before the run; do not move it after.**
4. **Combo SNR −2 dB AND flutter_frac 0.30:** ≥ 3/4 seeds byte-exact.
5. **Byte-margin floor:** mean byte-error-rate over nominal seeds ≤ 0.6 × (255−k)/(2·255)
   (RS127 → 0.151, RS159 → 0.113, RS179 → 0.089). Measure on **bytes**, not bits (R6-audit §5.3).

**HOLD** (carry as experimental, never headline): passes 1,2,5 but fails the timing gate 3 or 4 —
the sim likes it but it leans on flutter the sim under-models. **REJECT:** fails nominal (1) or floor (5).

**Pre-registered per-rung verdict expectation (so results can be scored against intent):**
- B0: SHIP (it is the proven floor; if it does not pass the gate the gate is mis-scaled — abort and re-anchor).
- B1: **SHIP-candidate** — same N512 timing as the record, only density changed; expected to clear 16 µs.
- B1b: SHIP-candidate if RS179 holds the byte floor; else HOLD.
- B2: SHIP-candidate (coherent QPSK has *more* phase margin than DQPSK per R1 Part 2 coh-QPSK column, and the CP adds ISI margin) — but the scattered-pilot EQ is new code; gate it hard.
- B3: **HOLD by default** (16-QAM leans on coherent amplitude stability the sim cannot vouch for — R6 §2 verdict "phase noise / D8PSK margins NOT honest"; the same blindness covers 16-QAM amplitude). It is the *headline-if-it-survives-real-tape*, never a sim-blessed headline.
- B4: HOLD (same reason; proof-of-concept).

> **Honest headline framing:** the *defensible* master9 record claim is **B1 at 2572 net bps (2.75×)**
> if it clears all five gates including 16 µs — pure density on the proven symbol length with a better
> timing front-end. **B3 at 2855 (3.06×) is the moonshot**, carried as HOLD; it only becomes the
> headline if the *real tape* decodes it byte-exact (R6-audit §5.5: a dense/coherent rung is real-tape
> evidence-gathering, never a sim headline).

---

## 4. Hard structural rules (non-negotiable, from the m8 lessons)

- **Self-tracking front-end in every rung** (R3 conclusion 2, R6-audit §5.4): every fixed-grid WS rung
  failed on the real tape; the sim cannot catch it. Every B rung has a continual pilot + the Stage-1
  resampling PLL. **No non-self-tracking rung ships regardless of sim PASS.**
- **Prefer shorter symbols at equal net rate** (R3 conclusion 3): N ≤ 512 everywhere; CP rungs use
  N512+CP, never N1024.
- **CRC32-per-codeword guard ON** (R3 conclusion 6): manifest tables; receiver-side; no truth leak.
- **K=3 tone density forbidden** (R3 conclusion 4): irreducible ~6 % floor at this SNR. (Not used here —
  B rungs are PSK/QAM per-carrier, not k-of-M tone combinations.)
- **Pilots boosted +3 dB, never data-bearing** (R5 §1.3); a pilot in every rung.

---

## 5. Diagnostic probes (what master10 needs; ~33 s total, within budget)

Two cheap on-tape probes, decoded by `m8_decode`-style analysis, measuring the two things the
dossiers flag as the binding unknowns for the *next* tape.

### Probe 1 — sub-375 Hz spacing + stationary-null map (≈15 s)
**Purpose (R6-audit §5.4 + R1 "what the data cannot answer"):** is **188 Hz (2-bin)** spacing legal,
and are the master3 −49 dB H(f) spikes real stationary nulls or sounder artifacts?
**Content:** (a) **repeat the front Schroeder sounder a 3rd and 4th time** interleaved through the
ladder (≈8 s) so a per-capture null map can be differenced against the front sounder — a real
stationary null repeats, an artifact does not (R1: "a repeated sounder would disambiguate"). (b) A
**7 s 2-bin (188 Hz) DQPSK micro-burst** of 30 carriers 750–6000 Hz carrying a known 256-byte CRC'd
pattern. Decode measures real cross-bin SIR at 188 Hz vs the R2 §4 prediction (188 Hz → 20.1 dB SIR).
**Master10 payoff:** if 188 Hz clears ~15 dB SIR on real tape, the dense-diff grid doubles again
(44 carriers → ~5000 net bps DQPSK), the single biggest density unlock left.

### Probe 2 — pilot-jitter PSD re-anchor + coherent-16QAM EVM micro-burst (≈18 s)
**Purpose (R6-audit §6: "re-measure the real pilot jitter on the first master9 capture and re-anchor
the gate level"; R1: flutter PSD shape unmeasured):** (a) A **10 s steady dual-tone** (continual pilots
at 1875 + 7125 Hz, the B3 pilot freqs) so the analyzer can recover the real 5–23.4 Hz flutter jitter
RMS on *this* deck/tape and re-anchor the 16 µs gate level (it was calibrated to the m8 tape; a
different tape may sit elsewhere). The two separated tones also directly measure the **frequency-slope**
(first-order channel tilt) the dual-pilot Stage-3 estimator relies on. (b) An **8 s coherent-16QAM
micro-burst** on the 6 strongest carriers (750–3000 Hz) carrying a known pattern; decode reports real
**per-carrier 16-QAM EVM** and amplitude CoV — the exact quantity R6 §2 says the sim cannot vouch for
("coherent-receiver amplitude stability is unproven on this channel"). **Master10 payoff:** turns the
B3/B4 16-QAM HOLD into a measured go/no-go and tells you whether 64-QAM on the top-3 carriers
(out-SNR 14–16 dB, R5 §4.4 says 64-QAM needs ~22 dB → likely no) is worth probing.

---

## 6. Concrete build/decode plumbing (so this is codeable without guessing)

- **TX builder:** extend `m8_master.py` pattern. B0/B1/B1b reuse `h4_dqpsk.DQPSKScheme` verbatim
  (B1: `P=22, N=512, spacing=4`; the existing `assert spacing*Nw % N == 0` passes for 4-bin, and
  `assert freqs[-1] <= 9500` passes at 9000 Hz). B2/B3/B4 need a **new `CohOFDMScheme`** modeled on
  `experiments/capacity/c4_ofdm_bitload.py` (which already has N_FFT/N_CP, dense pilots, per-symbol
  timing-slope tracking, erasure flags) — set `N_FFT=512, N_CP=96`, swap its uniform QAM for the
  per-carrier `bitload` map (16-QAM strong / QPSK rest), add the 2 null subcarriers and DRM scattered
  pilot positions. PAPR: apply **Schroeder phasing** to the multitone (R1 Part 4: keeps PAPR ~5 dB
  regardless of carrier count vs ~13 dB random; mandatory at 22+ carriers to avoid tape IMD at record
  level >7). Peak-normalize to 0.70 (h4 convention), record at level ~7.0, Dolby OFF (project SOP).
- **Manifest:** per-rung `dqpsk_params` / `cohofdm_params` (carriers, bins, N, CP, bitload, pilot
  positions, null bins, RS k), H9 pack metadata (orig/packed len, sha256, gzip), and the
  CRC32-per-codeword table (R3). Payloads: staggered `stories260K_int4.cass` slices, gzip-packed.
- **RX:** extend `m8_decode.py`. DQPSK rungs → `DQPSKScheme.demod` upgraded with the Stage-1 resampler
  (replace the integer `drift` clamp at h4 lines 197–214 with the polyphase resample of
  `x9_flutter_gate.channel_gate` form, driven by the PLL) + Stage-2 null-CFO trim. Coherent rungs →
  `CohOFDMScheme.demod` with Stage-3 scattered-pilot 2D interpolation. All rungs → erasure-RS + CRC
  guard. **Receivers sweep timing- AND freq-trajectory variants** (R3 conclusion 5: m8_m32k2_rs127
  only flipped on the *freq*-trajectory, not timing — sweep both, plus erasure-frac {0, 0.25, 0.5}).
- **Validation harness:** the pre-registered gates run via `x9_flutter_gate.py` (extend `GATE_RUNGS`
  with B1/B2/B3) + an h8-style nominal/dg/SNR stress matrix. Re-validate dg=0.58 against m8 per-rung
  BER (≥4 seeds) before trusting any frequency-domain B rung (R6 §3).

---

## 7. Risks (ranked, each with the dossier number that raises it and the mitigation)

1. **B3/B4 coherent-16QAM amplitude stability is sim-invisible (R6 §2, R6-audit Table B verdict).**
   The sim under-models phase noise ~5× and cannot vouch for the per-carrier amplitude eq 16-QAM needs.
   *Mitigation:* B3/B4 are HOLD-by-default; Probe 2 measures real 16-QAM EVM; B2 (coherent QPSK) de-risks
   the coherent chain at lower order first; B4 isolates 16-QAM from bit-loading. Never headline B3 off sim.
2. **The 934 record sits near its timing cliff (R2 §0 min margin 0.04°; R6-audit §0.3, gate 12–16 µs).**
   Any rung adding carriers spreads the *same* timing residual over more decisions. *Mitigation:* B1 keeps
   the proven N512 symbol length (same per-symbol residual) and only adds density + a *better* tracker
   (Stage-1 resampler), which should *reduce* residual below the record's, not just hold it.
3. **375 Hz spacing flutter-ICI is sim-unvalidated (R6-audit §5.4; R1 Part 3 says ~37 dB SIR but sim is
   blind to flutter-ICI).** *Mitigation:* B1 is gated through the 16 µs HF-flutter cell which *does*
   inject the missing band; R1 Part 3's analytic SIR (4-bin = 37 dB @ 9 kHz) is the independent check;
   Probe 1 measures real 2-bin SIR for master10 before going tighter.
4. **The new scattered-pilot/resampler code is unproven (no real-tape evidence yet).** A bug in the
   PLL or 2D interpolation could silently degrade. *Mitigation:* the front-end is a strict superset of
   proven h4 — run the proven B0 rung *through the new front-end* in sim; it must still decode byte-exact
   (regression test), else the front-end is broken, not the channel.
5. **CP=96 (2.0 ms) is shorter than the 8 ms reverb tail (R1 Part 3 / R5 §1.5).** Coherent rungs lean
   partly on the scattered-pilot EQ, not just the CP, to mop up residual ISI. *Mitigation:* the τ×{0.5,1.5}
   stress (R6-audit §5.2) brackets the reverb estimate; B2 tests the CP+EQ combo at safe QPSK before B3.
6. **dg=0.58 lossless recalibration is from few-seed probes (R6 §3 caveat).** A wrong dg makes the
   frequency-domain B rungs mis-graded. *Mitigation:* gate 2 (dg=0.65 pessimism, ≥6/8) forces survival even
   if the floor is worse than estimated; re-validate dg vs m8 per-rung BER ≥4 seeds before the run.
7. **Scattered-pilot frequency density vs reverb coherence BW (R5 Rule 4: BW_coh ≈ 125 Hz → pilots ≤
   62.5 Hz apart, but 375 Hz grid can't pilot that densely).** Frequency interpolation across 1125 Hz
   pilot gaps may miss a sharp null. *Mitigation:* the per-capture sounder H(f) (Stage 1.2) seeds the
   magnitude between pilots; bit-loading already zeros the known 3750 Hz null (R2); Probe 1's null map
   catches new stationary nulls for master10.

---

## 8. Single-line recommendation

Burn master9 with the B-ladder: **B0 (proven floor) → B1 (2572 net bps, the defensible new record via
density + a resampling timing PLL) → B1b/B2 (gated stretches) → B3 (2855 net bps coherent-16QAM
moonshot, HOLD, headline only on real-tape success) → B4 (16-QAM proof-of-concept)**, plus the two
probes that turn master10's two biggest unknowns (188 Hz spacing legality, real 16-QAM EVM) into measured
numbers. Defensible target **2.75× (B1)**; moonshot **3.06× (B3)** — both engineered to dossier numbers,
neither assumed.
