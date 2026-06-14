# BPS-Push — Morning Report (2026-06-15)

**Goal:** beat the standing real-tape record of **5791 net bps**. Built overnight, validated through a
calibrated filter, and packaged as ONE master tape to record this morning. The tape adjudicates the frontier.

---

## ☕ DO THIS MORNING (15 min)

1. **Verify the gate locally first** (proves the master decodes itself, byte-exact):
   ```
   cd /Users/magnus/repos/cassette-ai
   python3 experiments/tape_v2/bps_push_2026_06_14/bps_push_master.py        # regenerates the WAV if needed
   python3 experiments/tape_v2/bps_push_2026_06_14/bps_push_decode.py \
       experiments/tape_v2/bps_push_2026_06_14/master/bps_push_master.wav --selfcheck
   ```
   Expect: `-> 6/6 rungs byte-exact`. (Already confirmed twice overnight.)

2. **Record to tape.** Play `master/bps_push_master.wav` into the deck. **SOP (do not skip):**
   - **Dolby NR OFF** at record AND playback.
   - **Record level ~7.0** (NOT 8.5 — saturation blooms the IMD floor and kills the dense carriers).
   - Readback speaker **~55** (rms ~0.04, loud but no clip).
   - The master already has ~1 s silence around the start/end chirps — they are the sync anchors.

3. **Capture the playback** on the **iPhone in Voice Memos** (sample-accurate clock — do NOT live-capture
   on the Mac). Start the phone recording FIRST, then play the tape from the very start, let the FULL master
   play through the end down-chirp, then stop. It auto-syncs via iCloud.

4. **Decode the readback:**
   ```
   QTA="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta"
   ffmpeg -hide_banner -loglevel error -y -i "$QTA" -ac 1 -ar 48000 \
       experiments/tape_v2/captures/bps_push_run1.wav
   python3 experiments/tape_v2/bps_push_2026_06_14/bps_push_decode.py \
       experiments/tape_v2/captures/bps_push_run1.wav --out-tag bps_push_run1
   ```
   The table prints, per rung: `byte_exact`, raw BER, and net bps. **The new record = the net@k of the
   highest rung that decodes byte-exact.** The raw BER also tells us the max RS rate that *was* achievable,
   so even a near-miss rung quantifies the headroom.

---

## What the master contains — the 6-rung ladder

One WAV, 59.6 s, 20,845 info bytes, FLOAT32 48 kHz mono, peak 0.70. Same layout as the proven m10 master
(lead → up-chirp → 45 s sounder → rungs → down-chirp → tail), so the existing global sync works unchanged.
Rungs run conservative → aggressive; the tape decides how high we get.

| # | rung | modulation | gross | RS | **net@k (if byte-exact)** | sim model_net | risk |
|---|---|---|---|---|---|---|---|
| 1 | `anchor_r8_proven` | proven r8 DQPSK ×22 | 8250 | 179 | **5791** (= the record) | — | NONE — safety net |
| 2 | `r8_bulkframe_safe` | r8 PHY, long single-preamble frame | 8250 | 191 | **6179** | 7215 | LOW |
| 3 | `dapsk_8dpsk3` | 8-DPSK on 3 cleanest carriers + DQPSK | 8812 | 184 | **6359** | 6774 | MED |
| 4 | `stack_8dpsk3_ext4` | + 4 ext-band DBPSK carriers (9.4–10.5 kHz) | 9562 | 173 | **6488** | 6938 | MED |
| 5 | `stack_bulkframe_TOP` | 8-DPSK×3 + 6 ext + bulk frame | 9938 | 191 | **7443** | 8535 | HIGH — the stretch |
| 6 | `robustness_hedge_dapsk7` | 8-DPSK on 7 cleanest + DQPSK | 9562 | 173 | **6488** | 6525 | MED — carrier-flip insurance |

**net@k** = the cassette net bps the rung delivers IF it decodes byte-exact at its (conservatively chosen)
RS rate. Every new rung's net@k already beats 5791 by **+7 % to +29 %**. The `sim model_net` is the *achievable*
rate the measured raw BER supports (usually higher than net@k — we under-claimed the RS rate on purpose).

---

## Validation — why we trust this (and exactly how much)

**The filter is calibrated against reality.** The first-pass margin metric was a red herring (it marked the
*proven* r8 as failing). The metric that actually reproduces the real-tape outcomes is **RS-closure on the
trace-driven tape10 replay BER** (the channel measured from the actual 5791 burn). It reproduces all four
anchors: r8 (5791) and r6 (4910) PROVEN-backed; the killed 6179 and 5247 correctly rejected. Reference: r8 =
5921–6632 model-net depending on seed depth.

**Three validation passes on the actual master:**
- **A — no-channel self-check (HARD GATE): 6/6 byte-exact**, raw BER 0.0. Independently re-run and confirmed.
  Proves the master and decoder are self-consistent.
- **B — through Sim B (parametric): 0/6.** Expected and not a kill — Sim B is documented-pessimistic on the
  differential DQPSK track (it fails even the proven r8). This is the conservative floor.
- **C — through the FAITHFUL tape10 replay (the real predictor): 5/6 byte-exact**, every rung's model_net > 5791:

  | rung | byte_exact | raw_ber | model_net |
  |---|---|---|---|
  | anchor_r8_proven | ✅ | 0.0051 | 7571 |
  | r8_bulkframe_safe | ✅ | 0.0092 | 7053 |
  | dapsk_8dpsk3 | ✅ | 0.0124 | 7119 |
  | stack_8dpsk3_ext4 | ✅ | 0.0116 | 7838 |
  | stack_bulkframe_TOP | ⚠️ 37/39 cw | 0.0201 | 6937 |
  | robustness_hedge_dapsk7 | ✅ | 0.0191 | 6825 |

  Only the HIGH-risk stretch rung leaves 2/39 codewords short at its aggressive RS191 — by design. On a
  tape10-quality burn, the realistic new record is rungs 2–4/6 (**~6179–6488 net**), with rung 5 the reach.

**Honest caveats (read these):**
- `model_net` has **~±10 % seed-variance** — the *deltas* are load-bearing, the absolutes are noisy.
- Every GO is a **hedge-GO**: the single faithful capture (replay_doom wasn't registerable) can't see
  burn-to-burn carrier flips — the exact failure that killed the old 6179. That risk is *why* this is a
  ladder, and why RS rates are derated. The morning tape is the real adjudicator.
- A real decoder bug was found and fixed during the gate (symbol-count inference from window length →
  trimmed to `body_end_sample`); without the fix the dapsk/stack rungs decoded at chance.

---

## The campaign story (how we got here)

Three independent stabs → 10 candidates → screened through the calibrated filter.

**The diagnosis (first-principles):** the project sits at ~4.5 % of Shannon. The real channel has ~40 dB SNR —
**noise is not the limiter, coherence is** (per-tone phase drifts 69–78° over 4 s, reverb ISI τ≈7.9 ms,
per-burn carrier instability). DQPSK spends 2 of a possible ~13 bits/carrier; ~30 dB of per-carrier headroom is
wasted because higher constellations can't hold absolute phase. The winning move: **convert that headroom into
bits without needing absolute coherence.**

**What won (and stacks):**
- **Bulk framing** (+19–23 %): one long preamble instead of one per short frame. The pilot tracker's lock
  transient amortizes, so BER *drops* (0.0186→0.0078) AND the 0.37 s/frame overhead is amortized. On the
  proven r8 PHY — lowest modulation risk.
- **8-DPSK on the CSI-cleanest carriers** (+14 %): 3 bits/carrier of *pure differential phase* (no amplitude),
  but ONLY on the ~3 carriers whose measured phase jitter clears the 22.5° boundary. Carrier choice is driven
  by measured CSI, not intuition (the queue's hand-picked "clean mids" were wrong).
- **Ext-band DBPSK** (+12–16 %): 1-bit carriers above 9 kHz where DQPSK dies to the timing slope but DBPSK's
  90° boundary survives. Additive.
- **The stack compounds:** 8-DPSK × ext-band × bulk-framing → model_net **8535** (+44 % over the seed-4 ref),
  the bulk-framing BER-drop is even steeper on the stacked modulation.

**What died (and why — these are results too):**
- **16-DAPSK / any amplitude axis: DEAD.** The ~25 % diffuse cross-bin floor corrupts \|r\| (CV 50–380 %);
  the amplitude bit costs more than it carries. Differential *phase* is the only viable higher-order axis.
- **Single-carrier V.34-style moonshot: DEAD.** Clean-channel inverts perfectly, but the 35 dB HF rolloff
  across 6 kHz makes the band too frequency-selective for one wide carrier — the DFE can't equalize deep nulls.
  This **validates multitone** as the right architecture for this channel.
- **Tomlinson-Harashima echo precoding: doesn't transfer** (real reverb is stochastic, not the deterministic
  IR THP needs). **Uniform 8-DPSK** and **16-DPSK** die to phase jitter. **Layered enhancement** dies to the
  same dead amplitude axis.

---

## Files & reproduction
- Master: `master/bps_push_master.wav` (gitignored, regenerable) + `master/bps_push_manifest.json` (tracked).
- Build/decode: `bps_push_master.py`, `bps_push_decode.py`.
- Filter: `harness/{evaluate,score,replay_channel}.py`; anchors `results/anchor_confirm.json`,
  reference `results/r8_reference.json`.
- Candidates: `candidates/` (dapsk16-strongmids, extband_dbpsk, bulk-frame-contpilot, stacked_flagship, …).
- Screens: `results/{gauntlet_full,recommended_ladder,stack_screen,through_replay_tape10_decode}.json`.
- Full context: `BRIEFING.md`. Branch: `exp/bps-push-2026-06-14`.

**Bottom line:** the master is built, self-checks byte-exact, and projects a new record of **~6.2–7.4 kbps**
(vs 5.79 kbps) on a tape10-quality burn. Record it, decode it, and the highest byte-exact rung is the new number.
