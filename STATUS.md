Cassette AI viability sprint status

## 🏆📼 THE LOOP IS CLOSED: DOOM decoded BYTE-EXACT off the physical cassette (2026-06-13 night)
The whole-point moment. The DOOM v3 prize tape's side A was recorded to a real C90, played back
acoustically (deck speaker → air → iPhone Voice Memos, readback ~55), and decoded:
**0/9225 codewords failed, sha256 matches the original byte-for-byte — the HTML off the tape is
identical to the dist artifact.** All 9 Episode-1 maps + sound + THE MAGNETIC VAULT, recovered
through the air into a phone. Capture: clock 1.00022×, SNR 38.9 dB, flutter 0.38%. Net 4910 bps
(d2x P21 N256, RS159). The resampling-PLL front-end tracked the 42-min flutter to 84 stragglers
(best single branch); union + the carrier-class erasure ladder cleared the final 6 (6 trials, 0
misc, fa_bound 1.17e-05). Capture backed up to captures/doom_tape_readback.m4a + iCloud.
Result: `results/m10doom3_results_doom_tape_readback.json`. **Three-day arc: 934 → 5791 bps,
confirmed-novel, hand-built level, 9-track album — and a cassette that holds DOOM and reads itself
back.** (Notify note: Ratatoskr Telegram bot was inactive/.env missing + m365 token stale →
notified Magnus by himalaya email instead.)


## 🏆×4 STANDING RECORD: 5791 bps byte-exact (2026-06-12 eve, master10 burn, fresh C90, 10/10 rungs)
Lower-volume run (35.4 dB SNR!) — entire ladder landed: canary reproved, 2632–2896 re-banked on a
2nd physical tape, d2x 3362/4910/4910 clean, **5791 via the x11 rescue chain** (window sweep 19 cw +
erasure ladder 3 cw, 0 misc, fa 2.5e-07). The synthetic-only d2x rescue proved itself on real tape
by winning the record rung. Arc: 934 → 2572 → 2896 → **5791 (×6.2 in 3 days)**. Capacity now:
C60 side 1.24 MB · C90 side 1.86 MB · whole C90 3.73 MB. Result: results/x11_decode_results_tape10_run1.json
(commit 82bb4be). **x12 leads:** re-gate the killed >4910 frontier designs against tape10's better-than-
assumed channel (RS223/5247, DBPSK ext-band); bulk framing (~1.4×); re-encode DOOM at d2x (~14 min).

## ⚡ OPERATOR QUICK REFERENCE (2026-06-12, post-x11 — supersedes older hints below)
| Tape | Burn | Decode the capture with | Time |
|---|---|---|---|
| **master10** (rate assault → expected new record) | `bash experiments/tape_v2/play_master10.sh` | `python3 experiments/tape_v2/x11_decode.py <cap.wav>` ← NOT m10_decode (stale hint in play script) | 6.04 min, C60 ok |
| **DOOM v2** (real Freedoom, E1M1+E1M2+monsters) | `bash experiments/tape_v2/doom_ship/play_doom_tape_v2.sh` | `python3 experiments/tape_v2/doom_ship/m10doom2_decode.py <cap.wav>` | **43.99 min — needs a C90 side** |
| DOOM v1 fallback (miniwad) | `play_doom_tape.sh` | `m10doom_decode.py` | 12.38 min, C60 ok |
| Bonus, no burn: replay the EXISTING master9 tape → capture again | (just play + record) | feeds replay-fusion (x10 REPLAY_DIVERSITY) | ~8 min |

**x11 verdict (2026-06-12):** d2x rescue path PROVEN (23/23 synthetic marginal sections incl. AAC +
clock-offset axes, 0 misc, banked at the pre-registered ≥30% gate); frontier beyond 4910 honestly
KILLED by its own margin gate (this geometry tops out where master10 reaches — next bits must come
from the physical burn); 6 historical rungs rescued (tape7 + m8 N1024); both x10 dress gaps closed.
No master10b — master10.wav blessed as-is; x11_decode.py is the shipping receiver (never-worse,
d2x rescue armed). Compute loop CONVERGED for this geometry. Next multipliers, in order: (1) the
master10 burn itself; (2) "bulk framing" campaign (~1.4× on everything — the m9 framing pays a
measured 31% tax: 0.004366 s/B all-in vs modulation capacity; PLL holds lock 520+ frames so longer
frames are safe — needs its own gated campaign + tape); (3) RS223/5247 + DBPSK ext-band post-hoc
leads (own pre-registered campaign).

## 🏆🏆🏆 RECORD RAISED TO 2896 bps — receiver-only, NO new tape + master10 READY (2026-06-12)
Branch `deepdive-3-overnight`, commit pending. The x10 three-bet campaign (44 candidates, 8 selected
with pre-registered gates, adversarially verified, 51 agents) banked new records by RE-DECODING the
existing tape9 capture with a composed superset receiver (`m10_decode.py`):
- **m7 = 2896 net bps orig-exact (0/43 cw)** — late-window dc0 stitching + carrier-class erasure ladder
- m6 = 2809 (0/41), m5 = 2632 — all CRC32-guarded, **0 miscorrections, 0 regressions across all 4
  real captures** (tape9/tape8-lossless/tape7/tape4), 2196 CRC accepts / 0 rejects.
The three receiver wins: (1) ensemble-union across a widened timing-front-end bank; (2) per-carrier
late DFT-window placement at N256 (the dc0 750 Hz carrier wants window offset +32); (3) structural
carrier-class errors-and-erasures RS retry keyed to the carrier-block byte layout.
**KEY FORENSIC INSIGHT: the m5/m6/m7 deaths were ONE carrier (dc0 @750 Hz) with a reverb-tail bias
that a late window + erasure class fixes — not noise.**

**master10.wav BUILT & READY TO BURN (6.04 min!, 10 rungs):** canary 2572 → proven 2632/2809/2896/
2896twin → frontier **3362/4910/4910twin** → stretch **5791** → tail-canary. Dense2x geometry (375→
~187 Hz spacing equivalent at N256, P18-P22) cleared its pre-registered real-capture probe gate with
5.2× margin (predicted byte-ER 0.029 vs 0.151 threshold, measured on tape9). Self-check 10/10
orig-exact; dress: canaries 2/2 (seed-0 landed via the full rescue chain — union 32→31, erasure
ladder rescued all 31, 0 misc — the composed machinery proving itself), N256/d2x rungs die in sim
as always (the known-unmodelable timing axis; same pattern that preceded the real 2338/2572 landings).
**Honest tiers: 2632-2896 rungs are real-capture-proven configs; 3362-4910 frontier rests on
per-carrier extrapolation (weakest: the 4500 Hz deck-notch carrier at 18.8° margin); 5791 is a
lottery ticket. BURN: `bash experiments/tape_v2/play_master10.sh` (do NOT use stale x10_master10*.wav).**

Negatives (honest, gates worked): D8PSK bit-loading KILLed pre-tape (0/22 carriers passed census);
pfft-adaptive failed cleanly; replay-diversity machinery built but needs an operator step — a
**second capture of the SAME master9 tape** (just replay + record, no re-burn) would test replay fusion.
Critic: non-blocking; gaps logged in ship report (d2x erasure-ladder never validated on d2x sections;
AAC + clock-offset dress axes unexercised — mitigated by lossless SOP + real-capture regressions).
Dossier: `x10_dossier/` (X10_PLAN, X10_gate_report, MASTER10_SHIP_REPORT, B_AGGR_05_DENSE2X,
ENSEMBLE_UNION, REPLAY_DIVERSITY). DOOM tape also ready (12.38 min, see DOOM section below + e5b58cf).

## 🏆🏆 NEW REAL-TAPE RECORD: 2572 bps byte-exact — ×2.75 the old 934 (2026-06-11)
Branch `deepdive-3-overnight`. **master9 recorded and decoded.** Capture clean (clock 1.0017×,
flutter 0.43%, SNR 41.1 dB; capture came via Downloads `.m4a`/ALAC, not iCloud — one error frame
≈85 ms dropped, immaterial). Decode: `results/m9_results_tape9_run1.json`; source backed up to
`captures/tape9_run1.m4a` (irreplaceable — back up externally too).

**6 of 11 rungs orig-exact (byte-exact original payload, 0 codeword failures = CRC-verified):**
m0 934 ✅ · m3 1052 ✅ · m1 1169 ✅ · m2 **1404** ✅ (predicted near-certain floor) ·
**m4b n256_rs159 2338 ✅** (the N256 centerpiece) · **m8 dense375 2572 ✅ HEADLINE (×2.75)**.
**Died (honest):** m5/m6/m7 (2632/2809/2896, N256 high-RS, 2–28 cwFail) · m9a freqdiff (37/37,
sim-unblessable by design) · plain m4 rs159 (5/48) — but its variant **m4b landed clean at the
same 2338**.

**THE N256 BET PAID OFF, exactly as the gate framed it.** The sim REJECTed every N256 rung;
`MASTER9_PLAN.md §1.2/§6` carried them anyway as "a prediction to test, not a reason to cut the
centerpiece" because the sim is blind to the 187.5 Hz pilot-timing axis. The real tape settled it:
**N256 wins on the timing axis the sim couldn't see** — m4b (2338) and m8 dense-375 (2572) both
byte-exact. Blew past the pre-registered estimates (point est ≈2000, optimistic headline 2338):
actual **2572 byte-exact**. P2(a) flutter-gate caveat is moot — these are per-codeword CRC32
exact recoveries (0 cwFail), the strongest evidence available, not BER-threshold claims.

**Capacity at the new rate** (net bps × side-time, ~5% master overhead): **2572 bps ⇒ C60 565 KB/side
(1.13 MB whole) · C90 848 KB/side (1.66 MB whole) · C120 2.21 MB whole.** Unlocks: DOOM
(engine+WAD ~310 KB) writes in **16.5 min — one C60 side**; delphi mamba-200k (479 KB, formerly
"over one cassette") now fits **one C60 side (25 min)**; stories260K / llama2-100k in ~8 min.
chess-gpt-4.5M (3.2 MB) still over (~1.5× C120 whole-tape).

**NEXT:** commit results + STATUS; consider a confirm-run (fresh tape) to reproduce 2572; the
denser N256 high-RS rungs (m5–m7) are the next frontier to chase with a self-tracking front-end.

## 🕹️ PAYLOAD RESEARCH: DOOM (engine + WAD) fits on a C90 at today's rate (2026-06-11)

**Engine:** doomgeneric → WASM (~150–250 KB compressed) + **miniwad** BSD minimal IWAD (~80–120 KB)
= **~250–370 KB total compressed** for the complete playable game.

At 934 bps (proven record): ~36–53 min → fits **one C90 side** (both sides of a C60 at the low end).
At M2 (1404 bps): fits a single C60 side. At M4 (2338 bps): ~15–20 min.

**Artifact format:** decode tape → **one self-contained HTML file** (WASM engine + WAD inlined) → runs
in any browser, any device, zero install. The companion app could launch it in a WebView as the boot moment.

**License note:** DOOM engine is GPL — commercially distributable, source required. Gloriously on-brand
compliance: *binary on side A, source on side B*. WAD: use Freedoom (BSD, sellable, ~25–30 MB full;
or miniwad <250 KB for minimal playable content).

**Bottom line:** "This cassette contains DOOM — engine and all" is achievable with master8's proven rate.
No master9 required. C90 = one complete game.

## 🎬 MASTER9 BUILT & READY TO RECORD — projected 1404→2896 bps (1.5×→3.1×) (2026-06-10)
Branch `deepdive-3-overnight`. `master9.wav` (**482.4 s / 8.04 min**, 11 rungs + 2 diagnostic
probes, peak 0.70) is built and **self-checks byte-exact + orig-exact 11/11 with no channel**
(`m9_decode.py master9.wav` → clock 1.0000×, 0 cw failed every rung). Ready to burn:
`bash experiments/tape_v2/play_master9.sh`. Full plan + adjudicated gates in `x9_dossier/`
(`MASTER9_PLAN.md`, `M9_gate_report.md`, `MASTER9_SHIP_REPORT.md`).

**The ladder (robust-early → stretch-late), with the pre-registered sim gate verdict:**
M0 reprove-934 RS127 **SHIP** · M1 thin-159 1169 **HOLD**(near-miss, dg65 only) · M2 thin-191 1404
**REJECT**(N512 cliff) · M3 drop-null 1052 **SHIP** · M4/M4b N256 RS159 2338 **REJECT**(sim N256
ISI — the CENTERPIECE bet) · M5 2632 / M6 2809 / M7 2896 N256 **REJECT** · M8 dense-375 2572
**HOLD-by-rule**(sim blind <750 Hz) · M9a freq-diff 1169 **HOLD-by-rule**(timing-immune lottery).
Plus **P1** (repeated-sounder stationary-null map) + **P2** (pilot-jitter re-anchor + IMD knee).

**The full ladder is on the tape on purpose.** The KILL/REJECT sim verdicts are *headline-
eligibility*, NOT tape-cut decisions: per `MASTER9_PLAN.md §1.2/§6` and `M9_gate_report.md §6`
("burn the full ladder — the sim's N256 REJECT is a prediction to test, not a reason to cut the
centerpiece"), every un-blessable rung is carried as a **prediction-to-test probe**. The sim's
N256 reverb-ISI scaling is **the one axis with no real anchor** (m8 carried no N256 rung); the
C-design thesis is N256 wins on the *timing axis the sim is blind to* (187.5 Hz pilot rate vs
93.8 Hz), which the nominal-reverb death never lets the rung reach — so only the real tape settles it.

**Dress rehearsal** (merged tape through the faithful `channel_v2(tape7, aac=False, dg=0.58)`,
seeds 0+1, `m9_dress_rehearsal.py`): **M0/M1/M2/M3 orig-exact on BOTH seeds, 0 cw failed** — the
N512 near-certain band survives end-to-end (best both-seed rung M2 = 1404 bps, 1.5×). M4–M7 die on
nominal reverb-ISI exactly as the gate predicted (the unanchored axis); M8 seed-splits ([37, 0]);
M9a fails by rule. *Caveat (honest): M2 lands the 2 dress seeds but the 8-seed gate marked it REJECT
(4/8) on the N512 RS cliff — trust the 8-seed gate, not the 2-seed pass.*

**Sim-blessed headline floor (SHIP all 5 gates): M0 (934, reproven) + M3 (1052, 1.13×).** Honest
expected real record: **M2 at 1404 bps (1.5×)** near-certain floor, with **M4 (2338, 2.5×)** the
expected headline if its HF-flutter gate clears on the real capture, and a real shot at M5/M6
(≈2.6–3.0×). Point estimate ≈ **2000 bps (≈2.1×)**.

**Receiver upgrades shipped with m9_decode:** `x9_resampling_pll.py` — 2nd-order 30 Hz resampling
timing PLL (drop-in superset of the h4 EMA; **re-decoded the real m8 934 section byte-exact with
4.90 µs residual vs 5.37 µs EMA**, clears the 16 µs HF-flutter stress the EMA fails) + per-section
PLL-vs-EMA winner-take-better with CRC guard. `x9_freqdiff.py` — frequency-differential DQPSK
(M9a): **timing-immunity proven** (byte-exact under 34 µs injected jitter where time-differential
collapses 16× worse), sim-unblessable by design (static H(f) phase tilt; real sounder de-rotation
is the lottery mechanism).

**Companion app shipped too** (`app/`, commit 9d98dbf, design `docs/COMPANION_APP_DESIGN.md`):
native iOS SwiftUI capture/decode app (lossless AVAudioEngine capture, live waterfall, tier-grading
"Test my setup", CRT boot-moment view) + CassetteDSP Swift package (16/16 golden tests vs Python
reference) + FastAPI decode backend (6/6 tests, wraps m8_decode). Needs: iOS 26.5 sim runtime or
a device + signing team; device capture-fidelity spike before trusting tier verdicts.

**FROZEN constraints held:** `real_channel_sim.py` untouched; `h4_dqpsk.py` carries only the
sanctioned `min_spacing_hz` kwarg (default 562 = bit-identical to the frozen assert; M8 alone passes
375); R*/A/B/C/PLAN dossier files untouched.

**NEXT — record the tape (operator SOP):** (1) Dolby OFF, deck record ~7.0, readback speaker ~55.
(2) Phone **Voice Memos LOSSLESS, START THE PHONE RECORDING FIRST**, then deck, then
`play_master9.sh`. (3) Let the FULL tape play to the end chirp (~1 s silence around chirps = sync
anchors). (4) iCloud-synced `.qta` → `ffmpeg -ac 1 -ar 48000 captures/tape9_run1.wav` →
`python3 experiments/tape_v2/m9_decode.py .../tape9_run1.wav`. (5) **FIRST on the real capture:**
re-anchor the HF-flutter gate from **P2(a)** (8 s 4500 Hz pilot → 5–23.4 Hz band-RMS jitter) before
claiming any N256 verdict — m8 anchor was 33.9 µs.

## 🏆 REAL-TAPE RECORD: 934 bps byte-exact — DQPSK transfers sim→real (2026-06-10)
Branch `deepdive-3-overnight`. master8 recorded **mono + Voice Memos Lossless** (clean capture:
flutter 0.41%, SNR 38.3 dB, clock +0.12%). Decode: `results/m8_results_m8_tape_mono_lossless.json`.

**NEW RECORD — DQ_P10_N512_rs127 = 934 net bps byte-exact, CRC-verified, 0 raw byte errors.**
The entire DQPSK line (H4/H8) — sim-only until this capture — **proved itself on physical tape.**
+25% over 748, +66% over the 562 baseline. Second landing: **WS_M32_K2_rs159 = 748 via H6 combo**
(trajectory + erasures), CRC-verified — reproduces the prior record on a fresh independent tape.

**KEY FINDING (honest): every fixed-grid WS rung FAILED — including the 562 control (BER 0.072,
9/9 cw).** Only self-tracking decoders landed: DQPSK's pilot tone + H6's 0.25 Hz timing-trajectory.
The plain ±15-sample WS path could not follow the residual timing on this capture even at the tape
front (least drift). **Lesson 1: every future rung needs a self-tracking front-end; the bare
fixed-grid path is the fragile one.** Also: **DQPSK N512 BEAT N1024** (which failed 37/37) —
inverts the sim's "bigger N safer" guidance. On real flutter, N512's 2× denser pilot updates win;
real-channel timing/Doppler outranks the reverb-ISI that dominated in sim. **Lesson 2: trust the
real timing channel over sim for symbol-length choices.**

**Per-rung (mono lossless):** ctrl562 ✗(.072) / m32k2_127 ✗(.187) / **m32k2_159 ✅748 combo** /
m16k2_159 ✗(.107) / m16k2_191 ✗(.105) / dq_n1024_159 ✗ / dq_n1024_223 ✗ / **dq_n512_127 ✅934** /
m16k3_159 ✗(.103). 934 trustworthy: per-codeword CRC32 + 0 raw errors (false positive needs CRC
collision on every codeword).

**NEXT:** (1) diagnose the 562-control failure — alignment slip (recoverable, would rescue the WS
rungs) vs genuine BER? Highest-value next step. (2) Push DQPSK: it's the proven primary PHY now —
next ladder sweeps P/N/RS on DQPSK, anchored at N512-class symbol lengths. (3) Wrap a self-tracking
front-end around the WS decoders before trusting them again. (4) Merge `deepdive-3-overnight`.

## 🌙 OVERNIGHT DEEP-DIVE #3: 748 bps REAL-TAPE record + master8 ready to record (2026-06-10 night)
Branch `deepdive-3-overnight` (from codex/challenger). Autonomous 10-hypothesis campaign, all
pre-registered gates + independent adjudicator agents. **RECORD master8 TODAY** (see bottom).

**Simulator upgraded — `sim_v2.py`:** faithful channel + REAL Apple AAC round-trip (afconvert,
sample-aligned, the same encoder family as Voice Memos' LC-AAC 48k/205kbps stereo) + tape7
profile. Calibrated against the real tape7 9-rung outcome matrix: 7/9 match (diffuse_gain
0.65); honest near-miss documented (sim-M16 runs ~1.5× real BER = pessimistic; m16_rs191 sits
on its RS cliff). **SURPRISE FINDING: AAC is ~transparent at 205 kbps** (m32_rs111 BER .1123
aac-on vs .1115 off) — the M32 real-tape death is the diffuse reverb floor, NOT the AAC
masking skirt. Weakens the urgency of the Voice-Memos-Lossless toggle question.

**Wave 1 (adjudicated):** H1 PASS — WS_M16_K2_sp3_N256 (6 b/sym): RS159=701.5 net 3/3 seeds,
RS191=842.6 2/3 (sim). H2 PARTIAL — errors-and-erasures RS flips m16_rs159 on the REAL tape7
capture; **discovery: aggressive erasure flagging → SILENT RS miscorrections** ⇒ CRC guard
mandatory. H3 FAIL (discarded) — amplitude bit floors at ~4%, hurts tone detection too.
H4 PASS — **DQPSK on wide-spaced continuous-phase carriers + pilot: 933.8 net bps 3/3 seeds**
(P10, N512, RS127); N=256 dies (reverb ISI ≈1.5 sym); phase sim→real transfer UNVALIDATED.
H5 PARTIAL — 0.25 Hz timing-trajectory front-end improves BER on ALL 9 real rungs, flips
m32_rs127 (598) byte-exact on the real capture.

**Wave 2 (adjudicated):** H6 PARTIAL/headline — **trajectory+erasures combo under ONE fixed
pre-committed policy (frac:0.25|gap|mean): m32_rs159 byte-exact on the REAL tape7 capture =
748.2 net bps — NEW REAL-TAPE RECORD (+33% vs 562)**, m32_rs111 (522) also flips, total
cwFail 74→17 (−77%), 0 miscorrections (frac-policies clean; pct-policies DO miscorrect).
H7 PARTIAL — density frontier closed at H1's 842.6 in sim; K3@RS159 (1052 net) missed by
exactly 1 codeword on 1 seed → lottery rung. H8 PASS — DQPSK survives the FULL stress
envelope (96/96 cells: 2–3.3× flutter, −4 dB, AAC 96k); errors reverb-dominated, not AWGN.
H9 PASS — payload is compressible: lzma −15.95% / gzip −14.3% (h9_payload_codec.py, auto-
detecting header + CRC32) ⇒ effective-rate ×~1.06–1.19 depending on slice. H10 FAIL (honest)
— trajectory cuts BER on 12/12 sim runs but flips no K2 rung.

**Deliverable: `master8.wav` (9.57 min, reviewed SHIP)** — m8_master.py / m8_decode.py /
m8_sim_validate.py / play_master8.sh + manifest with per-codeword CRC32 tables (receiver-side
miscorrection guard). 9 rungs: ctrl 562 / m32k2 combo 598 + 748 (real-proven) / m16k2 702 +
843 / DQPSK 585 + 820 + **934** / K3 1052 (lottery). All payloads h9-gzip-packed slices of the
real cassette-LLM. Self-check 9/9 byte-exact+orig-exact. Merged-tape sim: DQPSK rungs perfect
2/2 seeds; WS rungs marginal there but rungs 1–3 are already real-tape-proven (the merged sim
is documented-pessimistic on WS). Expectations: proven 562/598/748 should land; DQPSK 585–934
are the headline candidates; 843/1052 are stretch/lottery.

**OPERATOR (same setup as always):** Dolby OFF, record ~7.0, speaker ~55, phone Voice Memos
FIRST, then `bash experiments/tape_v2/play_master8.sh`, let it run through the end chirp +1 s.
Decode: `python3 experiments/tape_v2/m8_decode.py <capture.wav>` (runs plain + combo paths,
unpacks + CRC-verifies payloads, writes results/m8_results_<name>.json).

## 🏆 RATE DOUBLED: 562 bps byte-exact on real tape + external review (2026-06-09 late)
Branch `codex/challenger` (pushed). This session built the rate-push tapes, recorded one, and
got an outside technical review.

**NEW PROVEN RATE — M16 RS(255,191) = 562 bps recovered BYTE-EXACT off the physical cassette**
(~1.7× the 326 bps first milestone). Full 153 KB model now fits **side A of a C90** (~38 min)
or a C60. Decoded from `captures/tape7_run1.wav` (the merged master7 tape). This take was
noisier than the 40 dB best: clock 1.0022×, flutter 0.37%, **SNR 36.4 dB, nf −48 dBFS**.
Per-rung (real tape7): M16 RS111 ✅, **RS191 ✅ (new frontier)**, RS159 ✗ (1/52 cw, margin
variance), RS223 ✗ (9/37). M32 "turbo" ✗ everything but RS95/447 bps (raw BER 0.08–0.14) —
**dense tone packing CONFIRMED AAC-fragile on real tape, exactly as the faithful sim predicted.**
So Claude's wide-spaced M16 PHY is the proven winner; Codex's M32 turbo lost on real tape.

**Artifacts built this session (all committed):**
- `m5_master.py`/`m5_decode.py`/`m5_sim_validate.py` + `play_master5.sh` — M16 RS-rate ladder
  (RS 111/159/191/223). Fixed an m5_decode bug: per-frame nsym/flen (m4 parity) so the short
  final frame doesn't over-read on a noisy channel.
- `m6_*` — Codex's M32 turbo-geometry challenger (committed for reproducibility; m7 imports it).
- `m7_master.py`/`m7_decode.py`/`m7_sim_validate.py` + `play_master7.sh` — **the MERGE**: one
  15.6-min tape, one global sync, 9 rungs (4 M16 + 5 M32), each section carries its own
  `phy_params`; m7_decode reuses `m6_decode._decode_section`. Self-check 9/9. This is the tape
  that was recorded + decoded → the 562 bps result above.
- `docs/ADVICE_BRIEFING.md` — self-contained (~1.4k-word) project summary + 5 asks, for pasting
  into an external model. Sent to "Fable"; its review is the basis for NEXT below.

**Fable review — verdict + roadmap (high-signal; it correctly PREDICTED the tape7 outcome):**
- **AAC is the binding adversary, and it may be a phone TOGGLE.** Settings → Voice Memos →
  Audio Quality → **Lossless** (ALAC) removes the perceptual codec at zero cost to the
  "stock phone/app" premise. UNVERIFIED on Magnus's iOS — **decision #1, his to check.** Whole
  modulation roadmap (turbo, OFDM) forks on it. Method: capture lossless as ground truth, then
  software-transcode to AAC for a controlled A/B (removes take-to-take confound).
- **Why M32 died (named mechanism):** AAC injects quantization noise *adjacent to* tonal peaks
  (masking skirt); 2-bin (300 Hz) spacing sits *inside* that skirt, 3-bin (562 Hz) is outside.
  Proven M16 is AAC-invariant by satisfying "sparse, strong, wide-spaced, long, constant-envelope".
- **Free wins (verified this session, no re-record):** (1) the int4 `.cass` is NOT entropy-coded
  → gzip/zstd ≈ **15% smaller** (154→131 KB) = ~15% effective-rate gain, byte-exact preserved.
  (2) Clean one-variable challenger **M16_K2_sp3** builds: 6 b/sym, 1125 gross, **843 net @ RS191**
  — stays outside BOTH reverb and AAC skirts (the *right* next geometry, not M32). (3) **Errors-
  and-erasures RS** using the contrast detector's reliability score as `erase_pos` (erasures are
  half-price) → near-free coding gain on EXISTING captures; may rescue the failed 159/223 rungs.
- **Bigger bets:** pilot-tracked DQPSK-OFDM (2–4 kbps, gated on lossless; build the pilot-PLL
  resampler first — it also cuts the current PHY's desync). Fountain/RaptorQ carousel for the
  shipped artifact ("decoded at minute 31"). Prior art: MT63 (survives speaker→mic acoustic
  coupling), underwater-acoustic Doppler tracking, DRM/HamDRM, libquiet.
- **Mic placement refinement:** phone at 25–30 cm + absorption *behind the deck* (not over the
  speaker) → +12 dB direct-to-reverb, drops the 25% skirt without muffling HF. Capture **mono**
  (acoustic channel is physically mono; decoder sums to mono anyway; avoids inter-mic combing).

**NEXT (ordered cheapest-first):**
1. MAGNUS: verify the Voice Memos **Lossless** toggle (forks the roadmap).
2. No re-record: erasure-RS decode of `tape7_run1` (rescue 159/223?); M16_K2_sp3 sim sweep;
   wire zstd into the payload path.
3. Recapture **lossless + mono + 25 cm**; software AAC A/B → does it unlock turbo/OFDM?
4. SHIP candidate: whole model on C90 side A @ 562 bps + audio liner notes on side B.
5. If lossless holds: pilot-PLL resampler → DQPSK-OFDM for the Mamba-479 KB tier.

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
