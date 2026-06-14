# BPS-Push — Morning Report (2026-06-15)

**Goal:** beat the standing real-tape record of **5791 net bps**. Built overnight, validated through a
calibrated filter across **three real cassette burns**, adversarially red-teamed, and packaged as ONE master
tape to record this morning. **The tape adjudicates the frontier — this report is deliberately honest about
what is solid vs. what is a coin-flip.**

> This is the second draft. An adversarial red-team pass corrected the first draft's over-claims (it had
> headlined +44 % / 8535). The numbers below are the *post-red-team* honest figures. See §"What the red-team
> found" at the bottom.

---

## TL;DR (read this)

- **Guaranteed floor:** the master re-records the proven r8 anchor → **5791** will close (it already has, byte-exact).
- **The defensible beat:** `r8_bulkframe_safe` → **~6179 (+7 %)**. Same proven r8 modulation, just one long
  preamble per frame; the BER-drop is a real mechanism and it closes with margin in the full-master replay
  across all three burns. **If anything beats the record this morning, this is the most likely.**
- **Upside candidates (tape adjudicates):** three higher-order rungs (8-DPSK on the cleanest carriers, ±ext-band
  DBPSK) project **6359–6488 (+10–12 %)** and held byte-exact across three real burns — but the margins are
  within seed noise and the carrier choice is tape10-derived, so treat them as candidates, not promises.
- **One diagnostic rung:** the aggressive bulk-stack top rung does **NOT** close at its RS rate in the faithful
  replay (long-frame fragility) — it's recorded to *measure*, not claimed as a record.
- **Realistic outcome:** a new acoustic record of **~6.2–6.5 kbps (+7 to +12 %)** on a tape10-quality burn.

---

## ☕ DO THIS MORNING (15 min)

1. **Verify the gate locally first** (proves the master decodes itself, byte-exact):
   ```
   cd /Users/magnus/repos/cassette-ai
   python3 experiments/tape_v2/bps_push_2026_06_14/bps_push_master.py      # regenerates the WAV if needed
   python3 experiments/tape_v2/bps_push_2026_06_14/bps_push_decode.py \
       experiments/tape_v2/bps_push_2026_06_14/master/bps_push_master.wav --selfcheck
   ```
   Expect `-> 6/6 rungs byte-exact`. (NOTE: a passing self-check proves the encoder and decoder agree — it does
   NOT prove the modulation survives a real channel. That's what the tape is for.)

2. **Record to tape.** Play `master/bps_push_master.wav` into the deck. **SOP (do not skip):**
   - **Dolby NR OFF** at record AND playback.
   - **Record level ~7.0** (NOT 8.5 — saturation blooms the IMD floor and kills the dense carriers).
   - Readback speaker **~55** (rms ~0.04, loud but no clip).
   - ~1 s silence around the start/end chirps — they are the sync anchors.

3. **Capture** on the **iPhone in Voice Memos** (sample-accurate clock — do NOT live-capture on the Mac). Start
   the phone recording FIRST, then play the tape from the very start through the end down-chirp, then stop. It
   auto-syncs via iCloud.

4. **Decode the readback:**
   ```
   QTA="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta"
   ffmpeg -hide_banner -loglevel error -y -i "$QTA" -ac 1 -ar 48000 \
       experiments/tape_v2/captures/bps_push_run1.wav
   python3 experiments/tape_v2/bps_push_2026_06_14/bps_push_decode.py \
       experiments/tape_v2/captures/bps_push_run1.wav --out-tag bps_push_run1
   ```
   Per rung it prints `byte_exact`, raw BER, and net bps. **The new record = the net@k of the highest rung that
   decodes byte-exact.** The raw BER also tells you the max RS rate that *was* achievable, so a near-miss rung
   still quantifies the headroom (and tells you what to re-record at a derated rate).

---

## The ladder — what to expect per rung

One WAV, 59.6 s, 20,845 info bytes, FLOAT32 48 kHz mono, peak 0.70. Standard m10 layout (lead → up-chirp →
45 s sounder → 6 rungs → down-chirp → tail), so the existing global sync works unchanged. Two numbers per rung:
**net@k** = the cassette net delivered IF the rung closes byte-exact at its (conservative) recorded RS rate;
**full-master replay** = what the most faithful channel model (tape10's measured channel, applied to the whole
master and decoded end-to-end) actually did.

| # | rung | modulation | gross | RS | net@k | replay BER | replay closes? | call |
|---|---|---|---|---|---|---|---|---|
| 1 | `anchor_r8_proven` | proven r8 DQPSK ×22 | 8250 | 179 | **5791** | 0.0051 | ✅ | floor — guaranteed |
| 2 | `r8_bulkframe_safe` | r8 PHY, long single-preamble frame | 8250 | 191 | **6179** | 0.0092 | ✅ | **defensible beat (+7 %)** |
| 3 | `dapsk_8dpsk3` | 8-DPSK on 3 cleanest carriers + DQPSK | 8812 | 184 | **6359** | 0.0124 | ✅ | candidate (+10 %) |
| 4 | `stack_8dpsk3_ext4` | + 4 ext-band DBPSK carriers (9.4–10.5 kHz) | 9562 | 173 | **6488** | 0.0116 | ✅ | candidate (+12 %) |
| 5 | `stack_bulkframe_TOP` | 8-DPSK×3 + 6 ext + long bulk frame | 9938 | 191 | ~~7443~~ | 0.0201 | ❌ 37/39 cw | **diagnostic — does not close** |
| 6 | `robustness_hedge_dapsk7` | 8-DPSK on 7 cleanest + DQPSK | 9562 | 173 | **6488** | 0.0191 | ✅ | candidate / carrier-flip insurance |

Rung 5 is recorded to *measure* whether a good deck can close the aggressive stack — at its faithful-replay BER
(0.0201) the RS rate it needs (k_max 178) is below its recorded RS191, so it leaves 2/39 codewords short. Its
raw BER off the tape will tell us the achievable rate; do not count it as a record.

---

## Validation — three real burns, and exactly how much to trust it

**The filter** screens a candidate by pushing fresh random bits through a *trace-driven replay* of a real
cassette burn (the channel — H(f), diffuse floor, flutter — measured from that burn's front sounder) and
mapping the resulting raw BER to a closeable net bps via RS-closure. It reproduces the real-tape anchor
*outcomes*: the proven r8 (5791) and r6 (4910) are claim-backed; the killed 6179 and 5247 are not (their
claimed net exceeds what their BER supports). *Honest scope:* this is a rate/closure bound, not a model of the
burn-to-burn carrier-flip that physically killed 6179 — that risk is covered by screening on multiple real
burns, below.

**Two-capture stability (the de-risking that matters):** every rung was re-screened (n_seeds=8) on a SECOND
genuinely-different real burn (`tape9`) and stress-tested on a THIRD (`doom`, the 4910 burn). Result: **all six
rungs stayed above the r8 reference on all three burns**, and tape9 actually scored *better* than tape10 — so
tape10 is the conservative binding case, not an optimistic outlier. The carrier-flip risk did **not** bite
across three burns. (Measured channels: tape10 35.4 dB/0.42 %, tape9 41.1 dB/0.43 %, doom 38.7 dB/0.40 %.)

**Honest caveats — what could still go wrong on the morning tape:**
1. **Seed noise is large.** `model_net` swings ~±15–25 % across seed draws — bigger than the inter-rung deltas.
   The load-bearing metric is **byte-exact closure at the recorded RS rate** (which has margin), not the
   model_net ranking. Don't read precision into the +7/+10/+12 % — read "these rungs are in the neighbourhood
   above the record; the tape says which actually land."
2. **Carrier selection is tape10-derived** (the 8-DPSK carriers were chosen on tape10's measurement). They held
   on tape9 and doom, but the morning deck's azimuth/EQ could differ — a carrier that flips dirty would push
   that rung's BER up. The conservative RS rates absorb some of this; the hedge rung (rung 6, 8-DPSK spread over
   7 carriers) is the insurance.
3. **Ext-band is mildly optimistic.** The replay does not model the HF timing-slope (~0.0037°/Hz) that erodes
   the decision boundary above 9 kHz, so the ext-band DBPSK carriers (rungs 4–5) may do slightly worse on tape.
4. **Long bulk frames are clock-sensitive.** The bulk rungs (2 and 5) decode one long frame whose symbol count
   is inferred post-resample; rung 2 (proven modulation) handled it, rung 5 (aggressive) did not fully. A deck
   with a very different clock than tape10 is the risk.
5. **The self-check proves consistency, not survivability** — it cannot detect a wrong-but-consistent carrier
   choice; only the tape can.

---

## The campaign story (how we got here)

Three independent stabs (academic literature / first-principles / moonshot) → 10 candidates → screened through
the calibrated filter.

**Diagnosis:** the project sits at ~4.5 % of Shannon. The channel has ~35–41 dB SNR — **noise is not the
limiter, coherence is** (per-tone phase drift, reverb ISI τ≈7.9 ms, per-burn carrier instability). DQPSK spends
2 of ~13 possible bits/carrier. The move: **convert the wasted per-carrier headroom into bits without needing
absolute coherence.**

**What won (and the evidence backs):**
- **Bulk framing** — one long preamble instead of one per short frame; the pilot tracker's lock transient
  amortizes (BER drops) and the 0.37 s/frame overhead is amortized. On the **proven r8 modulation** (rung 2),
  this is the most defensible win.
- **8-DPSK on the CSI-cleanest carriers** — 3 bits/carrier of pure differential phase (no amplitude), on the
  ~3 carriers whose measured jitter clears the 22.5° boundary. Held across three burns; modest, noise-adjacent.
- **Ext-band DBPSK** — 1-bit carriers above 9 kHz (90° boundary survives where DQPSK dies). Additive, mildly
  optimistic in sim.

**What died (results too):**
- **All amplitude/DAPSK axes DEAD** — the ~25 % diffuse cross-bin floor corrupts \|r\| (CV 50–380 %).
- **Single-carrier V.34/DFE/TCM moonshot DEAD** — clean-channel inverts, but the ~40 dB HF rolloff makes the
  band too frequency-selective for one wide carrier. **This validates multitone as the right architecture.**
- **Tomlinson-Harashima echo precoding** doesn't transfer (real reverb is stochastic). **Uniform 8-DPSK** and
  **16-DPSK** die to phase jitter. **Stacking bulk-framing onto the higher-order modulation** (rung 5) breaks
  the long-frame decode — the levers compound in *sim* but the combined long frame is fragile in the full
  pipeline.

---

## What the red-team found (and how it was adjudicated)

An adversarial pass attacked every headline. Adjudication:
- **VALID, fixed:** the top rung (5) was overstated — it does not close at RS191 (now labelled diagnostic);
  the seed noise is larger than the first draft's "±10 %" (now ±15–25 %, and the headline numbers were pulled
  back from +44 % to +7–12 %); carrier selection is tape10-derived (now disclosed); ext-band HF-slope omission
  and self-check-≠-survivability (now disclosed).
- **REFUTED:** the red-team's claim that the hedge rung "fails two-capture (5888)" was an n_seeds=4 noise draw —
  at n8 on the genuinely-different tape9/doom burns it scores 6675/7050, comfortably above the 6632 reference
  (this very discrepancy proves the seed-noise point). The two-capture guard *was* run on three real burns.
  Its claim that "the filter can't separate r8 from 6179" misread the anchor script's `ref_net=0` sentinel; the
  separation is real via claim-backing.

Net: the result is **real but modest** — a defensible +7 % (bulk-framed r8) with +10–12 % upside the tape
adjudicates — not the inflated first-draft headline. Recording costs nothing and measures the true frontier.

---

## Files & reproduction
- Master: `master/bps_push_master.wav` (gitignored) + `master/bps_push_manifest.json` (tracked).
- Build/decode: `bps_push_master.py`, `bps_push_decode.py`.
- Filter: `harness/{evaluate,score,replay_channel}.py`; anchors `results/anchor_confirm.json`.
- Two-capture: `results/two_capture_screen.json`, `results/HARDENING_NOTES.md`.
- Screens: `results/{gauntlet_full,recommended_ladder,stack_screen,through_replay_tape10_decode}.json`.
- Context: `BRIEFING.md`. Branch: `exp/bps-push-2026-06-14`.

**Bottom line:** the master self-checks byte-exact and, on three real-burn replays, projects a new acoustic
record of **~6.2–6.5 kbps vs 5.79 kbps (+7 to +12 %)** — most defensibly via bulk-framing the proven modulation.
Record it; the highest byte-exact rung is the real new number.
