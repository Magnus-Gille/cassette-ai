# x11-FRONTIER — frontier beyond 5791: adjudicated KILL (no new banker qualifies)

**Date:** 2026-06-12 · **Campaign:** x11 · **Verdict:** pre-registered margin gate
KILLED both banker candidates; the F3 ext-band probe survives only in a derated,
pointless form. **No tape pass is sanctioned; `x11_master_frontier.wav` carries
`print_authorized=false`.** The 5791-net stretch already printed on master10 (r8)
remains the frontier of this geometry pending its real-capture pass.

## 1. What was attempted

Three NEW rung candidates designed strictly from measured evidence (the x10
headroom map, the x10 dense2x probe, toneplan-v2's channel-mapped band plan),
each pre-registered with frozen gates BEFORE any new measurement ran
(`results/x11_frontier_margins.json`, frozen 2026-06-12T00:20Z):

| candidate | tier | geometry | design net | gate result |
|---|---|---|---|---|
| x11_f1_d2x_p19_rs179 | banker | d2x P19 drop {750,4500,5625}, RS(255,179) | 5001.5 | **KILL** (derated P16 → 4211.8 < 4910 floor) |
| x11_f2_d2x_p19_rs191 | banker | same grid, RS(255,191) | 5336.8 | **KILL** (derated P16 → 4494.1 < 4910 floor) |
| x11_f3_d2xx_p23_rs127_extband | probe | d2x P23 to 10500 Hz, RS(255,127) | 4295.6 | GO-derated (all 4 ext bins stripped → P16/2988.2, dominated by r5's 3362 — not worth tape) |

Excluded designs (frozen in prereg with arithmetic/evidence reasons): d2x
P21/P22@RS191 (keeps measured-bad carriers, <1× byte-ER margin), D8PSK mixed
constellation (x10 bitload census KILL stands), d3x N128 (no orthogonal window
with any guard), d2.5x (no integer N on the 375 Hz grid).

## 2. Deliverable (a): real-capture-anchored per-carrier margin table

New measurement: full |dphi-error| distributions per carrier per sanctioned
receiver branch (27 branches: hann256_skip0 × ema{.6,.7,.8} × shift{0,+48} +
rect128_skip64 × ema{.6,.7,.8} × shift{−32..+64}) on tape9 GOLD
(m9_m8_dense375 @ stride 256) and the independent m8 capture. Margin metric
(frozen): `45° − p90(|dphi err|)`, best sanctioned branch. Disclosure: per-carrier
SER/RMS at this geometry were already published (x10 probe); the p90/p99
quantiles adjudicated here are new, thresholds frozen first.

**Kills (the reason no banker survives):**

- **2625 Hz: margin 10.2° (SER 3.3%)** — fails the 15° rule on tape9. Not
  previously on any drop list.
- **6750 Hz: margin 10.6° (SER 4.7%)** — fails 15°; consistent with the x10
  probe's 4.5% SER row.
- **3750 Hz: tape9 margin 29.2° but m8 cross-capture margin −2.81°
  (SER 11.2%)** — fails the frozen G_B ≥ 10° cross-capture rule at the
  documented m8 null. Carrier quality migrates between tapes; a banker may not
  stand on one tape's good day.
- **All four >9 kHz extension bins: predicted margins 6.4–10.4° < 15°** — the
  timing-jitter phase error grows ∝ f (fit c1 = 0.00368 °/Hz on the measured
  6375–9000 Hz carriers, c0 ≈ 0) and eats the entire DQPSK boundary above
  ~9 kHz. Band extension at 2 bits/sym is dead at this symbol rate regardless
  of SNR (headroom map showed 10–15 dB up there; irrelevant — the channel is
  timing-limited at high f, EVM-limited elsewhere).

Surviving grid (margin ≥ 15.15° on tape9, m8-confirmed where evidence exists):
16 carriers — the d2x grid minus {750, 2625, 3750, 4500, 5625, 6750} and pilot.
P16 byte-ER prediction 0.0236 (vs r6-banker-era 0.079): the geometry is *clean*
but too narrow to beat 4910 at any pre-registered code rate (RS191 → 4494).

## 3. Deliverable (b): 8-seed sim pre-gate + dress-gap closure

`x11_frontier_pregate.py` → `results/x11_frontier_pregate.json` (prereg frozen
2026-06-12T08:58Z before any cell ran; toneplan-v2 blocking-vs-prediction split).

- **g1/g5 absolute:** f1 0/8 (BER .996), f2 0/8 (.996), f3 0/8 (.879) — the
  documented prediction-only axis for d2x (same calibration as the m9 0/8 →
  real 2338/2632/2896 landings; never a cut). Anchor sanity 6/8, BER .101.
- **B1 ext-bin IMD (blocking): NO FLAG** — F3 ext-bin median SERs 0.032 (9375),
  0.074 (9750), 0.136 (10125), 0.062 (10500) vs threshold 0.151.
- **B3a ext-bin AAC delta (blocking): NO FLAG** — aac vs no-aac deltas ≤ 0.005
  absolute on every bin.
- **B3b full-chain AAC on the CLEAN wav (dress gap): PASS** — 4/4 sections
  byte-exact after a 205 kbps AAC round-trip through global sync + union receiver.
- **B4a full-chain constant +0.17% clock offset (dress gap): PASS** — global
  chirp sync recovered clock_ratio 1.0016968 (truth 1.0017) and resampled it
  out; 4/4 sections byte-exact, alone and combined with AAC.
- **B4b noisy clock delta (anchor, seeds 0–1): NO FLAG** — Δcw_frac = 0.0 on
  both seeds (34/49 both arms @s0, 0/49 both arms @s1); ΔSER 6e-5. The offset
  axis costs nothing once sync has it. Axis not saturated.
- **Ledger:** 16,965 CRC32 acceptance trials this pre-gate, FA bound 3.9e-6
  (campaign budget 1e-4); miscorrected = 0 everywhere.

The two known x10 dress gaps (AAC axis, realistic constant clock offset) are
now CLOSED with positive results — this also de-risks the pending master10
tape pass, since the chain tested is the same architecture.

## 4. Build + self-check (deliverables, all new x11 files)

- `x11_frontier_probe.py` — quantile probe + frozen margin gate (stages:
  prereg/quantiles/secondtape/extbins/margins).
- `x11_frontier_master.py` — builds `x11_master_frontier.wav` (4 sections,
  2.31 min): imports `m10_master.make_scheme`/`_codeword_crcs` verbatim;
  anchor section asserted **byte-identical to m10_r0** (sha256 packed + CRC
  table vs `master10_manifest.json`). `print_authorized=false` embedded.
- `x11_frontier_decode.py` — manifest-driven union receiver (anchor: production
  m9 chain; d2x: rx_window_plan sweep), per-codeword CRC32 acceptance only,
  trial ledger, anchor-reproves-2572 validity rule.
- **No-channel self-check: 4/4 byte-exact AND orig-exact, 0 miscorrections**
  (`results/x11_frontier_results_selfcheck_nochan.json`, FA bound 4.8e-8).
- `x11_frontier_pregate.py` — the section-level 8-seed screen + full-chain
  dress-gap cells described above.
- Frozen-file integrity: nothing frozen was edited; the m10 composed-receiver
  regression re-ran this morning on tape9 (10/11 orig-exact with freqdiff
  37/37-fail as the expected negative, 0 misc) and m8 (orig-exact) —
  `results/x10_m10_results_x11_regress_tape9.json` / `_m8.json`.

## 5. What this buys master12 (design evidence, NOT banked claims)

1. **The honest ceiling statement:** at DQPSK/187.5 sym/s the margin-clean
   carrier set is 16 wide. 16 × 375 × k/255 caps at 4494 (RS191) — below the
   4910 floor. Beating 5791 at this geometry requires either more bits/symbol
   on the strong mids or a different symbol rate, not more carriers.
2. **Post-hoc observation (flagged as such, needs its own pre-registered
   campaign):** the 16-carrier clean set at RS(255,223) would project
   16·375·223/255 = **5247 net** with predicted byte-ER 0.0236 vs cap/1.5 =
   0.0251 — a 1.59× margin pass *on paper*. Thin, erasure-rescue-free
   territory; x12 material only with a real-capture probe of RS223 behavior.
3. **Ext bins are sim-clean but timing-dead at 2 bits:** 9375/10125 now join
   9750/10500 as IMD/AAC-cleared in sim (B1/B3a above), but the measured
   c1 = 0.00368 °/Hz timing slope kills DQPSK there. A 1-bit/sym (DBPSK,
   90° boundary) ext-band rung would have predicted p90 margins of
   51–55° — that axis is open.
4. **Cross-capture rule earns its keep:** 3750 Hz passes tape9 at 29° and
   fails m8 at −3°. Any future margin table without a second-tape column is
   self-deception.

## 6. Receipts

- `results/x11_frontier_margins.json` — prereg + quantiles (tape9, m8) +
  extbins fit + adjudication (margin tables per candidate).
- `results/x11_frontier_pregate.json` — prereg + 44 section cells + 7
  full-chain cells + adjudication (0 blocking flags).
- `results/x11_frontier_results_selfcheck_nochan.json` — 4/4 self-check.
- `x11_master_frontier.wav` + `x11_master_frontier_manifest.json` +
  `sidecars_x11_frontier/` — built, self-checked, **NOT print-authorized**.
