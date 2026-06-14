# master9 Design A — Proven-PHY Scaler

**Designer A mandate:** maximize the expected REAL-TAPE record gain with minimum
architecture risk, by scaling the *proven* DQPSK PHY (the 934 bps record) along its
own axes — RS rate first, carrier count via denser orthogonal spacing (AAC gone),
D8PSK only where R2's measured per-carrier margins justify it. Every number below is
anchored to the x9 dossiers (R1–R6).

**Scope discipline.** This design proposes **one** trivial, dossier-licensed code change
and no others. The proven rungs (A0–A2) are buildable today with
`h4_dqpsk.DQPSKScheme(P, N, spacing)` exactly as it stands: the scheme auto-builds the
carrier grid, picks the mid-band pilot at `nc//2`, applies the master3 TX pre-emphasis,
and decodes with the proven pilot-EMA + decision-directed front end. The dense rungs
(A3–A6) at 375 Hz spacing require relaxing **one assert** — see the boxed
implementation note below. The only per-rung knobs are `P`, `spacing`, and `rs_k`
(plus an optional per-carrier bit map for the one experimental rung). Ladder arithmetic
is in `A_ladder.json` (this directory).

> **REQUIRED implementation note (one line).** `h4_dqpsk.py` L101 hard-asserts
> `spacing*df >= 562.0` (the old AAC-masking floor). The dense rungs use 375 Hz
> spacing, which **fails this assert**. R2 §4 declares the 562 Hz floor **OBSOLETE on
> lossless captures** (150–200 Hz now supportable). The fix is to relax the assert to
> the measured floor — change `>= 562.0` to `>= 200.0` (or gate it behind a
> `min_spacing_hz` kwarg defaulting to 562 so the proven path is untouched). The
> orthogonality assert at L115 (`(spacing*Nw)%N==0`) **already passes** at spacing=4
> (verified), so no window/DSP change is needed — only the obsolete numeric floor moves.
> This is the single code change Designer A's ladder requires; it is mechanical and
> fully evidence-backed.

---

## 0. Anchors I am scaling from (verified this session)

| Fact | Value | Source |
|---|---|---|
| Record PHY | DQPSK P10, N512, spacing 8 bins = 750 Hz, carriers 750–8250 Hz, pilot 4500 Hz, RS(255,127) | A_ladder, `h4_dqpsk.py` |
| Record real result | 934 net bps, raw SER **1.8 %**, **0/62** RS codewords failed | R2 §0 |
| Record margin | min margin to a wrong QPSK decision **0.04°** (one symbol from failure); 8.9 % of symbols inside the D8PSK 22.5° boundary | R2 §0, R6audit §0 |
| Supportable spacing (lossless) | **150–200 Hz at 20–25 dB SIR**; skirt-limited plateau ~30 dB across 150–500 Hz; 562 Hz AAC floor **obsolete** | R2 §4 |
| Orthogonality constraint (code) | `(spacing·Nw) % N == 0`, `Nw = 3N/4`. At N512 this admits **only spacing ∈ {4, 8, 16, …}** (multiples of 4). spacing 4 = **375 Hz** is the densest orthogonal grid the current window supports; 5/6 (468/562 Hz) are NOT orthogonal | `h4_dqpsk.py` L114–117, verified |
| Flutter / timing | required tracking BW ~28.6 Hz; N512 per-symbol residual 5.4 µs after DD; **N1024 dies** (pilot updates halve, 34.8 µs raw dtau) | R2 §2, R6audit §3 |
| HF-flutter gate (validated proxy) | inject 5–23.4 Hz band jitter; N512 RS127 survives 12 µs (3/4), on cliff at 16 µs (1/4); N1024 dead 0/8 at 16 µs | R6audit §3 |
| Per-carrier health (proven grid) | nulls at 3750 Hz (SER 6.3 %, out-SNR 8.2 dB), weak 6750/7500/8250 (7.7–9 dB); strong 750–3000 & 5250–6000 (12–16 dB) | R2 §0, §3 |
| Reverb tail | τ ≈ 7.9 ms; no-CP DQPSK works because **differential** phase cancels slow ISI | R1 §3, R4 §14.3 |
| Guard rails | CRC32-per-codeword manifest (0 silent miscorrections proven); self-tracking pilot MANDATORY every rung | R3 §3, R6 §5.4 |

---

## 1. Design thesis (why this ladder, in one paragraph)

The record sits on a **timing cliff**, not a noise cliff (R6audit §0: min margin 0.04°,
SNR median 38 dB so noise is never the limiter — R1 Part 4). Two axes are therefore
*free* and one is *expensive*:

- **RS rate is nearly free.** The record decoded with **0/62** codeword failures at
  RS(255,127). The raw SER was 1.8 %; RS(255,127) corrects up to 25 % byte-symbol
  errors per codeword (t=64). That is a ~14× over-provision. Thinning RS to k=179 or
  k=191 on the *identical* proven PHY is the single safest rate gain available
  (R1 C1; R6audit §5.5 step 2). **+50 % net bps for ~zero new PHY risk.**
- **Carrier count via 375 Hz spacing is cheap** now that AAC is gone (R2 §4: 150–200 Hz
  supportable; we take a conservative 375 Hz = exactly orthogonal under the existing
  window, half the proven spacing). This **doubles carriers (10→22)** across the same
  750–9000 Hz band with no constellation-order change. The risk is flutter-ICI, which
  R1 §3 shows is negligible at ≥1 bin spacing after pilot tracking (SIR ≥25 dB at
  9 kHz, 2-bin), and reverb-ISI, which differential phase already cancels. **~2.75×
  net bps.**
- **Constellation order (D8PSK/16QAM) is the expensive axis** and is the one the sim
  *cannot* validate (R6 §2: phase-noise margins optimistic ~5×; "D8PSK would look fine
  in sim and fail on tape"). R2 measured that blanket D8PSK eats 8.9 % raw SER on this
  exact capture. So D8PSK appears in **exactly one experimental rung**, applied only to
  carriers whose *measured* `frac<22.5°` is small, never counted toward the headline.

The ladder is therefore **robust-early → stretch-late** within one recording:
re-prove the record, then walk RS rate up on the proven grid, then take the dense
grid up its own RS ladder (this is where the new record should land), then carry one
HOLD-grade D8PSK experimental rung purely to gather real-tape phase-noise data for
master10.

---

## 2. The ladder (7 rungs, robust → stretch)

All rungs: `N=512` (symbol rate 93.75 Hz — the proven pilot-update rate; **never N1024**,
R6audit §3), continuous-phase DQPSK, mid-band unmodulated pilot, master3 TX pre-emphasis,
skip = N/8 = 64 (Nw=384 Hann window), RS(255,k) global column-interleave, frame_bytes=510,
0.25 s per-frame chirp preamble, 0.12 s frame gap. Payloads are h9-gzip-packed slices of
`stories260K_int4.cass` (153823 B) at staggered offsets. Channel build/decode is identical
to the m8 tape architecture (global chirp pair + front Schroeder sounder; DQPSK sections
self-track via pilot, no per-section sounder needed).

| # | name | P | spacing | carriers (Hz) | pilot (Hz) | constellation | RS | gross | **net bps** | tape s | risk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 | reprove | 10 | 8 bins / 750 Hz | 750–8250 (proven set) | 4500 | DQPSK | (255,127) | 1875 | **933.8** | 38.4 | proven |
| A1 | rs179 | 10 | 8 / 750 | 750–8250 | 4500 | DQPSK | (255,179) | 1875 | **1316.2** | 35.8 | low |
| A2 | rs191 | 10 | 8 / 750 | 750–8250 | 4500 | DQPSK | (255,191) | 1875 | **1404.4** | 33.2 | low |
| A3 | dense_rs159 | 22 | 4 / 375 | 750–9000 (22) | 4875 | DQPSK | (255,159) | 4125 | **2572.1** | 43.9 | medium |
| A4 | dense_rs179 | 22 | 4 / 375 | 750–9000 (22) | 4875 | DQPSK | (255,179) | 4125 | **2895.6** | 38.4 | medium |
| A5 | dense_rs191 | 22 | 4 / 375 | 750–9000 (22) | 4875 | DQPSK | (255,191) | 4125 | **3089.7** | 35.7 | high |
| A6 | d8_bitload_rs127 | 22 | 4 / 375 | 750–9000 (22) | 4875 | D8/DQPSK bit-loaded | (255,127) | 5250 | **2054.4** | 41.2 | lottery |

Body 266.6 s + global sync overhead ~9.4 s + two diagnostic probes ~24 s = **300 s = 5.00 min**
(budget ≤ 16 min; **3.2× headroom**). The slack is intentional: payloads are sized for
≥26–63 codewords/rung so a real decode yields statistically meaningful per-carrier SER, and
the headroom leaves room to re-burn if the first take has a level error.

### Net-bps arithmetic (one worked example each axis)

- **net = gross × k/255**, **gross = 2·P / (N/FS)** with FS=48000, N=512 ⇒ symbol period
  N/FS = 10.667 ms, symbol rate 93.75 Hz.
- A2 (RS axis): gross = 2·10·93.75 = 1875; net = 1875 × 191/255 = **1404.4 bps**.
- A3 (density axis): gross = 2·22·93.75 = 4125; net = 4125 × 159/255 = **2572.1 bps**.
- A5 (best DQPSK headline candidate): net = 4125 × 191/255 = **3089.7 bps** = **3.31× the record.**
- A6 (order axis, experimental): see §5 for the bit-loaded gross derivation (5250) and
  why it is graded lottery and excluded from the headline.

---

## 3. Per-rung rationale, anchored to R2's measured numbers

### A0 — reprove (proven, 934 bps)
Identical PHY to the record, half the payload (6000 orig B → 30 codewords). **Purpose:**
confirm reproducibility on a *fresh* tape and re-measure the real pilot jitter to re-anchor
the HF-flutter gate level (R6audit §6: "re-measure on the first master9 capture"). It is the
floor — and per R6audit §0 it is *near* its cliff, so do not assume comfortable headroom.

### A1 / A2 — RS-rate scaling on the proven grid (low risk)
The record had **0/62** codeword failures at RS(255,127) with raw SER 1.8 %. Per-codeword
byte-error budget at k=127 is t=64; at k=179 it is t=38; at k=191 it is t=32. R2 §0 measured
per-carrier SER on the proven grid: worst is 3750 Hz at 6.3 %, then 7500 Hz 5.8 %, 8250 Hz
3.5 %; the other 7 carriers are ≤ 2 %. With the column interleave spreading errors uniformly
across codewords (R3 §2), the expected byte-error rate is ~ raw-SER-weighted ≈ 2–3 % of bytes,
i.e. ~6–8 errors per 255-byte codeword — comfortably inside t=32 (k=191). **A2 at 1404 bps is
the conservative honest extension of the record** (R1 C1; R6audit §5.5 step 2). A1 (k=179) is
the safety intermediate if A2's margin is wanted as a fallback headline.

> Risk note: the high carriers (3750, 6750–8250 Hz) carry essentially all the error
> (R2 §0). RS(255,191) leaves t=32; if those 4 carriers degrade on the fresh tape beyond
> their m8 figures, A2 is the first to feel it — hence "low", not "proven". A1 absorbs that.

### A3 / A4 — dense 375 Hz DQPSK (medium risk — the new-record band)
Half the proven spacing: 22 carriers at 375 Hz across 750–9000 Hz, pilot auto-placed at
4875 Hz. **Why 375 Hz and not tighter:** R2 §4 measures 150–200 Hz as *supportable* at
20–25 dB SIR, but the **code's Hann-window orthogonality constraint admits only
spacing-divisible-by-4** at N512 (verified: spacing 4 = 375 Hz is the densest orthogonal
grid; 5 and 6 fail `(spacing·Nw)%N==0`). 375 Hz also sits on the **30 dB SIR plateau**
(R2 §4 table: 400 Hz → 29.7 dB, 350 Hz → 30.0 dB), i.e. channel-noise-floor-limited, not
skirt-limited — the safe interior of the measured envelope. Flutter-ICI at this spacing is
negligible: R1 §3 gives 2-bin (188 Hz) SIR ≥31 dB at 9 kHz after pilot tracking, and we use
4-bin (375 Hz). Reverb-ISI is differentially cancelled (R4 §14.3). **A3 at 2572 bps is the
expected solid result; A4 at 2896 bps (k=179) is the expected new record** if the dense grid
behaves like the proven grid (same per-carrier physics, just twice as many tones in the same
band). Both graded medium because <750 Hz spacing is **sim-unvalidated** (R6 §5.4) — the sim
is blind to flutter-ICI — so the real tape is the first true test of this density.

### A5 — dense 375 Hz, RS(255,191) (high risk — the stretch headline)
Same grid, thinnest RS that still gives meaningful protection (t=32). net **3089.7 bps = 3.31×**.
This is the aggressive headline shot. Graded **high** because it combines the two
medium risks (375 Hz unvalidated × thin RS) — if the dense grid's raw SER comes in
materially above the proven grid's 1.8 % (plausible: 22 carriers include the weak HF set
twice as densely, and the new HF carriers 8625/9000 Hz are *past* the proven 8250 Hz edge
into deeper rolloff), t=32 may not hold. A5 should be evaluated against the §5.3 gate; if it
fails the byte-margin floor in sim it is carried as HOLD and A4 is the headline.

### A6 — per-carrier bit-loaded D8/DQPSK (lottery — experimental, NOT headline)
The one constellation-order probe. R2 §0 measured each carrier's `frac<22.5°` — the raw
symbol-error rate that carrier *would* suffer under D8PSK on this exact capture. The bit map
assigns **3 bits (D8PSK)** to carriers whose measured `frac<22.5°` ≤ ~5 % and **2 bits
(DQPSK)** elsewhere (full map in `A_ladder.json` rung `m9_s1_d8_bitload`, each entry tagged
with its R2 reference carrier and measured `frac`):

| measured carrier (proven grid) | frac<22.5° | class | dense carriers it gates |
|---|---|---|---|
| 750 | 0.9 % | D8PSK-safe | 750, 1125 |
| 3000 | 1.4 % | D8PSK-safe | 3000, 3375 |
| 2250 | 2.9 % | D8PSK-marginal | 2250, 2625 |
| 6000 | 3.2 % | D8PSK-marginal | 6000, 6375 |
| 5250 | 3.2 % | D8PSK-marginal | 5250, 5625 |
| 1500 | 5.1 % | D8PSK-marginal | 1500, 1875 |
| 8250 | 9.7 % | DQPSK-only | 8250, 8625, 9000 |
| 6750 | 13.6 % | DQPSK-only | 6750, 7125 |
| 7500 | 16.7 % | DQPSK-only | 7500, 7875 |
| 3750 | 30.3 % | DQPSK-only (deck null) | 3750, 4125, 4500 |

This yields 12 carriers × 3 bits + 10 carriers × 2 bits = 56 bits/symbol ⇒ gross 5250,
net at RS(255,127) = **2054 bps**. **It is graded lottery and excluded from the headline**
for three load-bearing reasons:
1. R6 §2: the sim under-predicts real phase noise ~5×; **D8PSK looks fine in sim and fails
   on tape**. We cannot trust a sim PASS here.
2. R2 §0: even on the *proven* PASS rung, 8.9 % of all symbols already sat inside the D8PSK
   boundary — and that was the rung that *barely* survived QPSK.
3. The dense-grid carriers are *interpolated* from proven-grid measurements 375 Hz away; the
   true D8PSK margin at, e.g., 1125 Hz is inferred, not measured.

A6 exists to **harvest real D8PSK per-carrier SER** so master10 can bit-load from *measured*
dense-grid data instead of interpolation. Heavy RS(255,127) (t=64) gives it the best chance
of a byte-exact surprise without betting the record on it.

---

## 4. Receiver architecture (precise enough to code without guessing)

The receiver is the **proven `h4_dqpsk.DQPSKScheme.demod` chain**, unchanged, run per rung.
Stated explicitly so an implementer can reproduce it:

### 4.1 Global sync (once per tape)
1. Cross-correlate the up-chirp (`f0=500, f1=5000 Hz, T=0.20 s`) to find tape start; the
   down-chirp at the end gives total span ⇒ **deck-clock scale factor** (m8 measured
   +0.117 %). Resample the whole capture by `1/(1+clock)` to a nominal grid (this removes the
   *static* SFO; flutter is the residual the pilot then tracks). This is the m8/m7-proven
   global resample — the DQPSK sections do not need the front sounder, but it is present for
   the WS-family heritage and for the §6 probes.

### 4.2 Per-rung, per-frame demod (the proven loop, `h4_dqpsk.py` L183–231)
For each frame in the rung's train (window = nominal start − 0.30 s lead, + frame len + 0.05 s):
1. **Frame sync:** `hc.find_preamble` on the 0.25 s chirp preamble → sample offset `ds`.
2. **Per-symbol complex DFT** at each of the `nc = P+1` carrier frequencies over the
   `Nw = N − 2·skip = 384`-sample Hann window starting `skip=64` samples into the symbol
   (dodges the short adjacent-ISI tail). The DFT exponent is referenced to the **absolute
   sample index** `(lo + arange(Nw))/FS`, so integer window re-centering is phase-transparent
   (each carrier freq is an integer multiple of FS/N).
3. **Pilot timing track:** the pilot carrier (`pilot_idx = nc//2`, unmodulated) gives the
   inter-symbol differential phase `dp = angle(c[i,pilot]·conj(c[i−1,pilot]))`; convert to a
   timing increment `dtau = dp/(2π·f_pilot)`, **EMA-smooth with α=0.5** (flutter is lowpass),
   and slide the analysis window by `−dtau·FS` samples (clipped ±200). This is the closed-loop
   per-symbol timing correction that beat N1024 (R2 §2; R3 §3).
4. **Differential QPSK decision:** `d = c[1:]·conj(c[:-1])` per data carrier; subtract the
   pilot-derived common timing term `2π·dtau·f_k`; round `dphi/(π/2) mod 4` → Gray quadrant.
5. **One-shot decision-directed refinement** (refine=True): from the post-decision phase
   residual, LS-fit a residual common-timing slope `dtau_res` vs carrier frequency, subtract,
   re-decide. R2 §2: this cuts per-symbol residual 16.5 µs → 5.4 µs.
6. **Carrier-block bit mapping** (`bits_to_quadrants`): data carrier *j* carries the *j*-th
   contiguous 2·nd-bit block of the frame, so a dead carrier corrupts a *contiguous* byte
   slice (RS-friendly concentration) rather than sprinkling errors into every byte.

### 4.3 FEC + guard (the merge layer, m8_decode pattern)
1. De-interleave the per-frame bit streams into the RS(255,k) column codewords
   (`codec.decode_payload`), errors-only RS decode.
2. **CRC32-per-codeword manifest guard ON** (R3 §3, R6 §5.4): the manifest carries a CRC32
   per codeword; any RS "correction" whose CRC fails is rejected as a miscorrection. Proven
   0 silent miscorrections across aggressive erasure sweeps — keep it.
3. h9-unpack (gzip) → verify orig CRC + length → byte-exact check.

### 4.4 Receiver sweep per rung (decode-time robustness, no PHY change)
Because every fixed-grid rung on the m8 tape died from ~0.75-symbol/frame timing wander
(R3 §1), and R3 §2.5 showed a *free* win was missed by fixing on one trajectory kind, the
master9 decoder must, per rung, sweep and pick the byte-exact (CRC-verified) winner over:
- **pilot-EMA timing (default)** AND, as a fallback, the h5/h6 **timing- and freq-trajectory**
  front-ends at bandwidths {0.05, 0.08, 0.10, 0.25 Hz} (R3 found bw 0.08 optimal for K=3);
- errors-only RS AND errors-and-erasures with erase-frac {0, 0.25, 0.5} keyed on the pilot
  `gap`/`lock` reliability metric (CRC-guarded so erasures can never miscorrect).

For the proven DQPSK rungs the EMA path is expected to win outright (it is what won the
record); the sweep is insurance for A3–A6 where the dense grid / D8PSK may need the tighter
trajectory tracker.

---

## 5. Pre-registered gate (which rung becomes the headline)

Following R6audit §5.3, pre-registered **before** any tape is burnt, evaluated in the
faithful sim `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)` plus the
validated HF-flutter cell `x9_flutter_gate.py` (5–23.4 Hz band injection). Choose ONE
HF-flutter threshold and freeze it: **SHIP at 12 µs, treat 16 µs as the headroom cell.**

A rung is **SHIP** iff ALL of:
1. Nominal ≥ 7/8 seeds byte-exact (aac=False, dg=0.58).
2. dg-pessimism ≥ 6/8 seeds byte-exact at dg=0.65.
3. HF-flutter 12 µs ≥ 3/4 seeds byte-exact (the gate h8 lacked).
4. Combo SNR −2 dB AND flutter_frac 0.30 ≥ 3/4 seeds.
5. Byte-margin floor: mean **byte**-error-rate over nominal seeds ≤ 0.6 × (255−k)/(2·255)
   (RS127→0.151, RS159→0.113, RS179→0.089, RS191→0.075).

**Self-tracking pilot is present in every rung by construction** (the unmodulated mid-band
carrier), so the non-negotiable structural rule of R6 §5.4 is satisfied ladder-wide.

**Expected gate outcome (honest prediction):**
- A0/A1/A2: SHIP (proven grid, generous RS).
- A3/A4: SHIP-candidate — they will pass the *frequency-domain* gates in sim, but 375 Hz is
  sim-unvalidated for flutter-ICI (R6 §5.4), so they are SHIP-on-tape-evidence: the real
  decode is the validator. If a flutter-augmented sim run blesses 375 Hz, promote to SHIP.
- A5: likely HOLD (thin RS × unvalidated density may fail gate 5) → A4 is the realistic
  headline, A5 the stretch.
- A6: HOLD/experimental by rule (fails the timing/phase gate; D8PSK margins are exactly where
  the sim is blind). **Never the headline.**

**Realistic headline expectation: ~2.9× the record (A4, 2896 bps)**, with A5 (3.3×) as the
stretch and A2 (1.5×) as the guaranteed-safe fallback. This is squarely inside R1's MEDIUM
band (C2 2572 / C8 2104) and consistent with R4's "conservative 2–2.7×, ambitious 3.5–4.5×".

---

## 6. Diagnostic probes for master10 (~24 s total)

Two cheap unmodulated probes appended to the tape body (before the end chirp), measuring the
two things the dossiers flag as the biggest unknowns for the *next* tape.

### Probe P1 — dense-grid pilot-jitter sounder (~12 s)
**What:** a single continuous unmodulated tone at **6000 Hz** for 12 s (a steady HF pilot,
higher than the 4500 Hz pilot the record measured). **Why:** R6 §6 says the 5–23.4 Hz jitter
figure is a *lower bound* and must be re-measured per tape to re-anchor the HF-flutter gate;
R1 "what data cannot answer" lists the flutter **PSD shape / corner** as unmeasured. A 12 s
HF tone lets `x9_sim_probes`-style heterodyne→unwrap→Welch recover the real per-band timing
jitter at 6 kHz directly. **master10 payoff:** a measured flutter PSD shape replaces the
assumed two-sinusoid model, so the sim's timing blindness (the thing that mis-greenlit N1024)
can finally be calibrated, and the densest-honest constellation order can be set from data.

### Probe P2 — tight-spacing leakage sounder (~12 s)
**What:** a 12 s Schroeder-phased multitone (low PAPR, R1 §4) at **8 carriers spaced 187.5 Hz**
(2 bins at N512) across 1500–2812 Hz, in a clean mid-band region, plus 2 deliberately-nulled
bins between them. **Why:** R2 §4's 150–200 Hz "supportable" figure is a *leakage* measurement,
not a *decode* measurement, and the code's window only orthogonalizes spacing-÷4; the null bins
let master10 measure real cross-bin energy at 2-bin (188 Hz) spacing on *this* tape, and the
diffuse floor on the nulled bins (the null-subcarrier CFO observable from R5 §2.4). **master10
payoff:** decides whether a 188 Hz grid (a 4× density jump, ~doubling the dense rung's carrier
count) is real or a leakage trap — the single highest-leverage unknown for pushing past A5.

Both probes are unmodulated, carry no payload, and cost ~24 s — trivially affordable given the
3.2× tape-budget headroom.

---

## 7. Risks (and why each is mitigated, not ignored)

- **The record is near its timing cliff (0.04° min margin).** A0 re-proves it on a fresh tape;
  if A0 itself fails, the tape has a level/setup problem (check the record-level-7 SOP) and the
  ladder is invalid — fail fast. Mitigation: A0 first, generous RS on A1/A2.
- **375 Hz spacing is sim-unvalidated (flutter-ICI blind spot, R6 §5.4).** Mitigated by (a)
  choosing 375 Hz on the 30 dB SIR plateau, not the 150 Hz edge; (b) R1 §3's measured-tracking
  flutter-ICI SIR ≥25 dB at the worst carrier; (c) grading A3/A4 medium and treating the real
  decode as the validator, with A2 as a guaranteed fallback headline.
- **New HF carriers 8625/9000 Hz are past the proven 8250 Hz edge**, in deeper rolloff. The TX
  pre-emphasis (master3 curve) boosts them, but they may run hotter raw SER than the proven set.
  Mitigated by the carrier-block mapping (their errors concentrate into a contiguous byte slice
  RS can absorb) and by A3's heavier RS(255,159).
- **D8PSK (A6) is where the sim is blind and R2 shows blanket D8PSK fails (8.9 % SER).**
  Mitigated by graded as lottery, excluded from headline, heavy RS(255,127), bit-loaded only on
  carriers with measured low `frac<22.5°`, and existing purely to harvest real data for
  master10.
- **PAPR / tape saturation at 22 carriers.** R1 §4: random 22-tone PAPR ~9 dB, but Schroeder/
  Newman phasing holds it to ~5.6 dB regardless of carrier count. The existing modulator sums
  continuous-phase sines; if peak clipping appears at record level, apply Schroeder phase offsets
  (no decode change — differential phase is per-carrier-differential, unaffected by a fixed
  per-carrier phase offset). Record level ~7.0 per the SOP, never 8.5.
- **Sim dg=0.58 recalibration is from few-seed probes (R6 §6).** Mitigated by gate 2
  (dg-pessimism at 0.65) requiring the rung to survive the worse floor too.

---

## 8. Files

- Design (this doc): `experiments/tape_v2/x9_dossier/A_design.md`
- Ladder arithmetic + per-carrier bit maps: `experiments/tape_v2/x9_dossier/A_ladder.json`
- Record PHY (unchanged, the build/decode primitive): `experiments/tape_v2/h4_dqpsk.py`
- Tape assembly pattern: `experiments/tape_v2/m8_master.py` / `m8_decode.py`
- Faithful sim + HF-flutter gate: `experiments/tape_v2/sim_v2.py`, `x9_flutter_gate.py`
- Evidence base: `R1_capacity.md`, `R2_margins.md`, `R3_ws_rescue.md`, `R4_acoustic_lit.md`,
  `R5_flutter_channels_lit.md`, `R6_sim_fidelity.md`, `R6_sim_fidelity_audit.md` (this dir)
