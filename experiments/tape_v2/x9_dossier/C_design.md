# master9 — Designer C ("Portfolio Optimizer") Design

**Author:** Designer C · **Date:** 2026-06-10 · **Branch:** deepdive-3-overnight
**Anchor record:** 934 net bps (DQPSK P10 N512 sp8 750 Hz, RS(255,127), 0/62 cw failed on m8 tape)
**Mandate:** best *expected-value* tape — each rung is a bet; maximize Σ P(land)×value + information-gained-on-failure, under the ≤16-min budget. Single recording, robust-early → stretch-late.

All net_bps and tape_seconds below are recomputed from the **actual code arithmetic**
(`m8_master.py`: FRAME_BYTES=510, RS_N=255, per-frame preamble 0.25 s, FRAME_GAP 0.12 s;
`h4_dqpsk.py`: `gross_bps = (2·P)/(N/FS)`, `net = gross·rs_k/255`). They match `A_ladder.json`
to ±0.6 s (preamble rounding). Payload = h9-gzip-packed `stories260K_int4.cass` slices; gzip on
int4 weights is ≈neutral (treat packed ≈ orig, the conservative assumption A also used).

---

## 0. The three facts that drive this portfolio (and why I diverge from a pure scaler)

**FACT 1 — The record is near its timing cliff, not on a plateau.** R6-audit §3 built and
validated an HF-flutter injection: the proven N512 RS127 rung passes the 12 µs (5–23.4 Hz) cell
3/4 seeds but collapses to 1/4 at 16 µs. R2 §0: its *truth-referenced min margin is 0.04°* — one
symbol from failure — with 8.9 % of symbol-decisions already inside the D8PSK 22.5° boundary.
**Implication:** the cheap "just thin the RS / add a couple carriers on the proven PHY" gains are
real but *bounded* — they spend the same fixed timing margin. A pure scaler ladder (A's approach)
banks most of its EV on rungs that all share one correlated failure mode (N512 timing). Good EV
demands a **structurally different timing front-end** as the high-value bet, not just more carriers.

**FACT 2 — Sub-750 Hz spacing is triple-blocked at N512, and the sim cannot bless it.**
The shipping demod window is Hann over `Nw = 3N/4` with the orthogonality assert
`(spacing_bins·Nw) % N == 0`. At N512 that permits only spacing multiples of 4 bins; the smallest,
sp=4 = **375 Hz, fails the hard `spacing·df ≥ 562` assert** (`h4_dqpsk.py:101`). So A's headline
"22 carriers @ 375 Hz, N512" (A r2/r2b/r3, 2572–3230 net bps) **requires a code change to the
frozen-pattern demod AND lands exactly in the spacing band R6 §2/§5.4 flags UNVALIDATED** (the sim
is blind to flutter-ICI below 750 Hz; Table C off-bin "leakage" there is the reverb skirt, not the
flutter sidebands a real dense grid would suffer). EV-wise those rungs are *high* risk dressed as
*low* — I keep at most one, heavily caveated, and never headline it.

**FACT 3 — There is a legal, orthogonal, ≥562 Hz path to 2× density that ALSO improves the
binding impairment: drop N, not spacing.** At **N256, sp=4 → 750 Hz spacing** the orthogonality
assert passes, `750 ≥ 562` passes, and the carrier/pilot frequency grid is **bit-identical to the
proven 934 rung** (750–8250 Hz data, 4500 Hz pilot). N256 halves the symbol period (5.33 ms),
**doubles the gross rate AND doubles the pilot update rate** — directly attacking the one
impairment that kills everything (R4 §14.4: "N=256 provides 3× safety margin"; R6 §5.4: "prefer
shorter symbols… a timing decision, not just ISI"; R3 conclusion #3: "short symbols beat long").
**This is my centerpiece bet** — it's the only ~2× rung whose risk axis points the *right* way.

The differential-DQPSK reverb argument holds at N256 (R4 §14.3: ISI ≈ 1.5 symbols, cancelled by
the symbol-to-symbol differential since both symbols of a pair see the same multipath). The one new
risk is flutter accumulating *within* the shorter window — but that's smaller per symbol, not
larger, and the residual is tracked twice as often.

---

## 1. Receiver architecture (one chain; every rung self-tracks)

Identical structural front-end for every DQPSK/D8PSK rung (the mandatory self-tracking rule,
R6 §5.4). Coded once; rungs differ only in (P, N, spacing, constellation, bitload, rs_k).

**Per-section decode (`h4_dqpsk.DQPSKScheme.demod` pattern, extended):**

1. **Global sync (once per tape):** Schroeder chirp-pair (up @ start, down @ end) → estimate deck
   clock (m8: +0.117 %) → static resample whole capture to 48 kHz nominal. Front Schroeder sounder
   re-measures H(f); anchor median to the section (m8 used −2.25 dB shift). This is unchanged from
   m8_decode.

2. **Per-frame preamble find:** `hc.find_preamble` on the 0.25 s preamble → sample-accurate frame
   start `ds`.

3. **Per-symbol pilot timing loop (the closed loop):** unmodulated mid-band pilot (4500 Hz). Each
   symbol `i`: complex DFT at every carrier over the Hann window `Nw = 3N/4` on an **absolute time
   basis** (so window shifts are phase-transparent). Pilot differential phase
   `dp = angle(c[i,pilot]·conj(c[i-1,pilot]))` → `dtau = dp/(2π·f_pilot)`, EMA-smoothed (α=0.5),
   integer-drifted into the next window position (clip ±200 samp). **This is the loop N512 wins
   with and N1024 loses with** (R2 §2: pilot updates halve at N1024 → 34.8 µs raw dtau vs N512's
   16.5 µs). At N256 it runs at **187.5 Hz update** (vs 93.8 Hz at N512) — strictly tighter.

4. **Differential decision + decision-directed common-timing refinement:** form
   `d = c[i]·conj(c[i-1])`, subtract the pilot-estimated `2π·f_k·dtau` per carrier, slice to the
   constellation grid (QPSK π/2, D8PSK π/4). Then one DD pass: residual phase after removing the
   decided symbol ≈ `2π·f·dtau_res`; regress residual vs carrier freq → refine common timing →
   re-decide (R2: DD cuts residual 5.4 µs from 13.5 µs EMA-only).

5. **Receiver-side sweep variants (cheap, mandatory — R3 conclusion #5):** decode each section under
   a small grid and pick the variant with the most CRC-clean codewords: timing-trajectory bandwidth
   ∈ {pilot-EMA-only, +DD, h5/h6 0.25 Hz freq-trajectory}, EMA α ∈ {0.4, 0.5, 0.6}. R3 proved a
   *freq*-trajectory flips rungs the timing-trajectory misses; sweeping both is free margin.

6. **FEC + miscorrection guard:** column-de-interleave the per-frame bytes → RS(255,k) errors-only
   (optionally errors-and-erasures using the per-symbol `gap`/`lock` reliability metric) → **verify
   each codeword's message CRC32 against the manifest table** (R3: 0 silent miscorrections across the
   entire aggressive sweep). A codeword that RS "corrects" but whose CRC fails is rejected, never
   trusted. Whole-section byte-exact iff all codewords reconstruct + sha256 matches manifest.

**Rung-specific additions** are called out per rung below (frequency-differential mapping for R-LOT;
per-carrier amplitude EQ for the D8PSK rung).

---

## 2. The ladder (robust-early → stretch-late, ≤16 min)

Ordered as laid to tape. EV column = my subjective P(land byte-exact on the real tape) × value
(net bps), with the *information* a failure buys noted. P(land) is calibrated to the dossiers: the
proven PHY at N512 with thinner RS is ~0.9; N256 (untested symbol length but right-direction
physics + sim-gateable) ~0.55; sub-750 spacing / D8PSK / freq-diff are 0.15–0.4.

| # | name | PHY | net bps | tape s | risk | P(land) |
|---|---|---|---|---|---|---|
| R0 | reprove-934 | DQPSK P10 N512 sp8 750 Hz, RS(255,127) | **934** | 42.4 | proven | 0.97 |
| R1a | thin-159 | DQPSK P10 N512 sp8, RS(255,**159**) | **1169** | 50.0 | low | 0.92 |
| R1b | thin-191 (cliff-bracket hi) | DQPSK P10 N512 sp8, RS(255,**191**) | **1404** | 42.4 | low | 0.80 |
| R2 | drop-null-9c | DQPSK **P9** (no 3750 Hz) N512 sp8, RS(255,159) | **1052** | 54.8 | low | 0.90 |
| **R3** | **short-symbol-2×** | **DQPSK P10 N256 sp4 750 Hz, RS(255,159)** | **2338** | 28.7 | **medium** | 0.55 |
| R3b | short-symbol-thin (cliff-bracket) | DQPSK P10 N256 sp4, RS(255,**191**) | **2809** | 24.3 | medium-high | 0.35 |
| R-LOT | freq-differential | **frequency-DQPSK** P11 N512 sp8, RS(255,159) | **1169** | 46.3 | lottery | 0.30 |
| R-D8 | d8-strong-7c | **D8PSK** P7 (strong carriers only) N512 sp8, RS(255,127) | **980** | 60.5 | high | 0.30 |
| P1+P2 | two diagnostic probes (§4) | — | — | 28.0 | — | — |

**Body total:** 42.4+50.0+42.4+54.8+28.7+24.3+46.3+60.5 = **349.4 s** rungs + **28.0 s** probes
= **377.4 s**. Plus global sync overhead (chirps + sounder + lead/gaps, m8 ≈ 17 s): **≈ 394 s ≈ 6.6 min.**
Comfortably inside 16 min — leaving headroom to (a) repeat R3 with a different seed/offset as a
second realization, and/or (b) lengthen any rung's payload. **I deliberately leave ~9 min of budget
unspent**: per FACT 1 the record has thin margin, so the EV-right move is *more seeds / more
bracketing*, not cramming more distinct dense rungs that share the timing failure mode. A second R3
realization (different payload offset) doubles the information from the single most valuable bet.

### Per-rung rationale, arithmetic, and the *information* each failure buys

**R0 reprove-934 (PROVEN, 934 bps).** Re-burn the exact record PHY, half payload (4096 B). gross
= 2·10/(512/48000) = 1875; net = 1875·127/255 = **933.8**. Non-negotiable floor + reproducibility
control: if R0 fails byte-exact on master9, the tape/deck/levels regressed and *every* higher rung's
result is suspect — it's the canary. Failure-info: tells us the channel itself moved.

**R1a thin-159 / R1b thin-191 (LOW, 1169 / 1404 bps).** Same proven PHY, lighter FEC. R0 decoded
with **0/62 cw failed** at RS127 → large unused correction budget. net scales rs_k/255: 1875·159/255
= **1169**; 1875·191/255 = **1404**. **R1a and R1b are a deliberate RS-bracket on the proven PHY** —
the single cheapest piece of information on this tape. R2 §0 says the real raw SER was 1.8 % ⇒ byte-
error-rate ≈ 1−(1−0.018)^? per byte; RS127 corrects 64 sym/cw, RS191 corrects 32, RS159 corrects 48.
If R1b (RS191, t=32) lands and R1a (RS159, t=48) trivially lands, the cliff is above RS191 and the
*proven floor for master10 is ≥1404 bps*. If R1b fails but R1a lands, the cliff sits between t=32 and
t=48 and we've **located it to within one bracket** — directly setting master10's RS budget. Either
way the bracket converts the 934 record's "unknown margin" into a measured number. (R1b reuses 6144 B
so n_frames=17 packs the bracket into the same tape time as R0.)

**R2 drop-null-9c (LOW, 1052 bps).** Identical PHY but **delete the 3750 Hz carrier** — R2 §per-carrier
shows it is a deck null: SER 6.3 %, out-SNR 8.2 dB, EVM 0.39, amp CoV 27 %, and it threw 401 of the
1138 raw symbol errors *by itself* (35 % of all errors from one of ten carriers). Removing it should
**lower the section's raw SER from 1.8 % toward ~1.1 %**, lifting margin for *free* while costing only
1 carrier. gross = 2·9/(512/48000)·= 1687.5; net = 1687.5·159/255 = **1052**. EV value is less the
1052 bps (below R1a) and more the **clean experiment**: does excising the worst carrier buy enough
margin to then run RS191 on 9 carriers next tape? This is the bit-loading-around-nulls principle
(R1 Part-1, R4 R-4) tested in its simplest, lowest-risk form. Failure-info: if even the null-free 9c
fails RS159, the problem is *not* the 3750 Hz carrier and the margin story is wrong.

**R3 short-symbol-2× (MEDIUM, 2338 bps) — THE CENTERPIECE BET.** DQPSK, **N256, sp=4 → 750 Hz
spacing**, identical carrier/pilot frequency plan to the record (verified: data carriers
{750,1500,2250,3000,3750,5250,6000,6750,7500,8250} Hz, pilot 4500 Hz — bit-for-bit the m8 grid).
gross = 2·10/(256/48000) = **3750**; net = 3750·159/255 = **2338.2**; 6144 B → 20 frames → **28.7 s**.
This is the *only* path to ~2× that (a) needs **no code change** (orthogonality + 562 Hz asserts both
pass), (b) reuses the **proven frequency plan** (no new spacing to validate), and (c) moves the
binding risk axis the **right way**: half the symbol period ⇒ half the per-symbol flutter drift the
tracker must absorb *and* double the pilot update rate (187.5 Hz). Every dossier points here: R4 §14.4
(N256 = 3× flutter safety margin), R6 §5.4 ("prefer shorter symbols… SHIP-eligible default is the
shorter-symbol variant"), R3 #3, R5 Principle 5. The honest risk: N256 has never been burned to tape;
ISI is now 1.5 symbols (R4 §14.3) but differentially cancelled, and the higher carriers see the same
2π·f·τ flutter — but the residual τ is *smaller and tracked faster*. **Gate it hard (§3): R3 must
clear the 12 µs HF-flutter cell at ≥3/4 seeds — if it can't, it's a HOLD, not a SHIP.** EV: 0.55 ×
2338 ≈ 1286 *expected* bps from one rung, and on the *upside* it sets a new record at 2.5× with the
least structural novelty of any 2× option on the table.

**R3b short-symbol-thin (MEDIUM-HIGH, 2809 bps) — the N256 RS-bracket.** Same N256 PHY, RS(255,191).
net = 3750·191/255 = **2808.8**, 24.3 s. Pairs with R3 exactly as R1b pairs with R0: **brackets the
N256 cliff.** If both R3 and R3b land, master10's N256 floor is ≥2809; if R3 lands and R3b fails, we
have N256's RS budget pinned in one shot. Cheap (24.3 s) and high-information precisely *because*
N256 is the unknown — bracketing the unknown is where bracketing pays most.

**R-LOT frequency-differential DQPSK (LOTTERY, 1169 bps) — the structurally-different bet.**
The distinctive idea no scaler ladder carries. Instead of differencing each carrier against *itself
one symbol earlier* (time-differential, the scheme that dies from symbol-timing jitter), difference
**adjacent carriers within the SAME symbol** (frequency-differential): bits on carrier `k` are
`angle(c[i,k]·conj(c[i,k-1]))`. Because both carriers are sampled in the *same* DFT window, **any
common symbol-timing error cancels identically** — the exact failure mode (per-symbol dtau wander)
that killed every fixed-grid rung and capped the record. P11 carriers + the pilot form **10 usable
frequency-differential pairs** (carrier 0 is the per-symbol phase reference, anchored by the pilot/H(f)
tilt; each subsequent carrier carries 2 bits relative to its lower neighbour). gross = 2·10/(512/48000)
= **1875**, net = 1875·159/255 = **1169**, 46.3 s — i.e. *same gross as the record but with the
timing-immune mapping*. The value here is not rate (it equals R1a) but **architecture**: it proves
whether removing time-differential dependence is viable at all. **Risk = lottery** because (a) it's never been
implemented here, (b) frequency-differential trades timing-immunity for sensitivity to the *frequency-
selective* channel tilt between adjacent carriers (750 Hz apart) — the 3750 Hz null would corrupt
*both* pairs touching it, not just one carrier. **Mitigant:** use the measured H(f) tilt (sounder)
to de-rotate the per-pair channel phase before slicing; skip the pair straddling 3750 Hz. EV value is
mostly **information**: if frequency-differential lands clean where time-differential is cliff-limited,
master10's entire architecture pivots to it (timing jitter stops mattering) — that's a *paradigm*
result worth a 46 s lottery ticket even at P≈0.3. Failure-info: tells us channel-tilt across 750 Hz
exceeds the QPSK margin, quantifying coherence bandwidth for free.

**R-D8 d8-strong-7c (HIGH, 980 bps) — the constellation-order probe, restricted to where it can
survive.** R2 §3 + R1 Part-2 are unambiguous: blanket D8PSK dies (R6: 8.9 % of N512 symbols already
inside the 22.5° boundary; R1: D8PSK closes only to ~6750 Hz under the EMA pilot). So run D8PSK
**only on the 7 carriers R2 shows can take it** — out-SNR ≥ 11.8 dB, frac>22.5° ≤ ~5 %:
{750, 1500, 2250, 3000, 5250, 6000} Hz (drop 3750/6750/7500/8250 — all >9 % or null). That's 6
strong + treat one more (6000) → 7 carriers × 3 bits. gross = 3·7/(512/48000) = **1968.75**; net =
1968.75·127/255 = **980**, heavy RS127 to absorb the thinner phase margin, 60.5 s. **Risk = high**:
even strong carriers ran median residual 5–8°, p99 ~30–40° (R2 §1) — D8PSK's 22.5° boundary leaves
little p99 headroom, and the sim *cannot* vet it (R6 §2: "D8PSK would look fine in sim and fail on
tape"). It earns its slot only as the cheapest honest probe of the *order* axis (vs R3's *density*
axis): if 7-carrier D8PSK lands, master10 gets bit-loading-by-order on strong carriers; if it fails,
we've measured exactly how far short the phase margin is. **Per-rung addition:** decision-directed
per-carrier *amplitude* EMA (`H_est[c] = α·H_est[c] + (1−α)·rx[c]/decision[c]`, R4 R-6) before
slicing, since D8PSK amplitude-fades matter where DQPSK shrugs them off.

---

## 3. Pre-registered SHIP/HOLD gates (adopt R6-audit §5 verbatim; per-rung verdicts)

Run faithful sim `sim_v2.channel_v2(profile='tape7', aac=False, diffuse_gain=0.58)`, sanity-bound
`profile='tape4'`. 8 seeds nominal {0..7}, 4 seeds {0..3} per stress axis, **all logged**.

**A rung SHIPs iff ALL:** (1) ≥7/8 nominal byte-exact; (2) ≥6/8 at dg=0.65 (lossless-recalibration
pessimism); (3) **HF-flutter cell** (`x9_flutter_gate.py`, 5–23.4 Hz band) ≥3/4 byte-exact at the
**frozen threshold** — *pick 12 µs as the SHIP threshold and freeze it before the run* (R6-audit §5.3:
the record itself passes 12 µs 3/4 but is on its cliff at 16 µs; demanding 16 µs would HOLD the record
itself); (4) combo SNR −2 dB AND flutter_frac 0.30 ≥3/4; (5) **byte**-error-rate over nominal ≤
0.6×(255−k)/(2·255) [RS127→0.151, RS159→0.113, RS191→0.075]. **HOLD** if passes 1,2,5 but fails the
timing gates 3/4. **REJECT** if fails nominal (1) or byte-margin (5).

**Hard structural rules (non-negotiable):** every rung self-tracks (pilot); CRC32-per-codeword guard
ON; spacing <750 Hz treated as HOLD until a flutter-augmented run blesses it; shorter symbol is the
default at equal rate.

| rung | expected gate verdict | why |
|---|---|---|
| R0 reprove | **SHIP** | it IS the proven record |
| R1a rs159 | **SHIP** | proven PHY, more RS slack than R0 used |
| R1b rs191 | **SHIP-candidate / cliff-bracket** | RS191 is near the byte-margin floor (gate 5: t=32 → cap 0.075) — may land as HOLD; that's the point of bracketing |
| R2 drop-null-9c | **SHIP** | strictly easier than R0 (worst carrier removed), RS159 |
| **R3 short-symbol** | **SHIP iff clears the 12 µs HF-flutter cell** (run `x9_flutter_gate.py` adapted to N256: its tracker Nyquist is 93.75 Hz, so it follows 5–23.4 Hz *better* than N512 — physics predicts PASS) | the centerpiece; gate decides headline-eligibility |
| R3b short-symbol-thin | **HOLD-likely** (RS191 byte-margin + N256-novel) | carried as the upper cliff-bracket |
| R-LOT freq-diff | **HOLD (experimental)** | sim can't vet a new constellation mapping faithfully; carry for real-tape info |
| R-D8 d8-strong | **HOLD (experimental)** | R6 §2: sim is optimistic on D8PSK phase margin by ~5×; never headline |

**Headline claim policy:** only rungs that SHIP under all five gates count toward the master9
headline net-bps. Realistically that's R0/R1a/R2 for sure, R1b/R3 if gates clear → **plausible honest
headline 1404–2338 bps (1.5–2.5×)**; R3b/R-LOT/R-D8 are information-gathering HOLDs that may *upgrade*
the record but are reported as experimental until a real-tape CRC-verified decode confirms them.

---

## 4. Diagnostic probes (what master10 needs; ~28 s total)

Two cheap inserts that measure the things R1 §"What the data CANNOT answer" flags as unknown. Both
are *pure-measurement* sounders — no payload, no FEC — placed right after the front sounder.

**P1 — Repeated-sounder stationary-null map (12 s).** R1/R6 both flag: the master3 H(f) had −49 dB
spikes we *smoothed as artifacts*; if any are **real stationary nulls** they silently kill specific
carriers. Emit the **same Schroeder sounder 3× back-to-back** (4 s each, low PAPR per R1 Part-4).
Decode: per-bin |H(f)| across the three repeats; a bin that is consistently −40 dB in all three is a
**real stationary null** (master10 must skip it / bit-load around it); a bin deep in only one repeat
is flutter/fade jitter (transient). **Output for master10:** a verified per-carrier go/no-go + the
true coherence bandwidth (how many adjacent bins a null spans) — the exact input the R-LOT
frequency-differential rung and any dense rung need to place carriers. Directly answers R1's
"frequency-selective stationary nulls vs sounder artifacts" unknown.

**P2 — Pilot-jitter PSD re-anchor + tape-saturation knee (16 s).** Two sub-probes:
(a) **8 s continuous 4500 Hz pilot tone** → on capture, heterodyne+unwrap→Welch-PSD the instantaneous
timing jitter and **re-measure the 5–23.4 Hz band-RMS on THIS tape/deck** (m8 = 33.9 µs). R6 §6 is
explicit: "re-measure the real pilot jitter on the first master9 capture and re-anchor the gate level
before trusting it for a second tape." This converts the HF-flutter gate from m8-calibrated to
master9-calibrated — the single most load-bearing number for sizing master10's N and RS. (b) **8 s
multitone level-ramp:** the 10-carrier Schroeder-phased multitone (PAPR ~5 dB, R1 Part-4) emitted at
**4 rising amplitudes** (−12, −9, −6, −3 dBFS pre-tape) → on capture, measure inter-modulation-distortion
floor vs level. This is the **measured AM/AM saturation knee** R1 flags as currently only a qualitative
SOP ("record level >7 saturates"). **Output for master10:** the real PAPR backoff budget — how hard we
can drive the tape before IMD eats dense-carrier margin, which sets whether a 16/22-carrier dense rung
is even physically possible regardless of timing.

Both probes are decode-only-needs-the-capture (no manifest dependency), so they cost nothing if a rung
fails. 12 + 16 = **28 s**, well within the ~9 min of spare budget.

---

## 5. Risks (ranked) and the EV logic of the whole tape

1. **R3 (N256) is unproven on real tape** — it's the centerpiece *and* the largest single EV swing.
   Mitigated by: identical frequency plan to the record, no code change, physics-favorable risk axis,
   hard HF-flutter gate, and a second R3 realization in the spare budget. If R3 fails the gate it
   drops to HOLD and the tape still bands 1404 bps (R1b) honestly.
2. **All N512 SHIP rungs share one correlated failure mode** (the timing cliff per FACT 1). The
   RS-brackets (R1a/R1b, R3/R3b) are designed so that a correlated miss still *locates the cliff*
   rather than just losing — failure converts to information.
3. **R-LOT / R-D8 sim-invisibility** — the sim cannot faithfully vet a new constellation mapping
   (R-LOT) or D8PSK phase margin (R-D8, R6 §2 optimistic ~5×). Mitigated by labeling both HOLD and
   never counting them toward the headline; they're pure information bets carried on spare budget.
4. **Sub-750 Hz density deliberately excluded** — A's 375 Hz/N512 dense rungs would need a frozen-code
   change and sit in the spacing band R6 declares UNVALIDATED. Excluding them is itself a risk-managed
   *choice*: I trade A's nominally-higher headline (3230 bps) for a portfolio whose 2× bet (R3) has a
   defensible, gateable, code-clean basis. If master10's flutter-augmented sim later blesses 375 Hz,
   it's a fast follow.
5. **Payload/manifest integrity** — the CRC32-per-codeword guard (proven 0 miscorrections, R3) plus
   sha256-per-section in the manifest is the backstop against a "decoded" but wrong result. Non-negotiable.
6. **Budget under-spend is intentional, not waste** — given a near-cliff record, the highest-EV use of
   the remaining ~9 min is *more seeds and a repeated R3*, not more distinct dense rungs that all bet
   on the same timing margin. Variance reduction > headline padding when the headline rung is fragile.

**Bottom line.** This tape bets a near-certain 1.5× (R1a/R1b/R2, proven PHY, RS-thinned + null-dropped),
one well-supported 2.5× centerpiece (R3, short-symbol — the only honest 2× whose risk points the right
way), two structurally-novel lottery tickets bought on spare budget (R-LOT frequency-differential,
R-D8 order-on-strong-carriers), and two measurement probes that hand master10 the numbers the dossiers
say we're currently missing (stationary-null map, re-anchored jitter + IMD knee). EV-optimal under the
constraint that the 934 record is a cliff, not a plateau.
