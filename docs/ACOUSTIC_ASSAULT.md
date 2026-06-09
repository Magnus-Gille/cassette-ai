# ACOUSTIC ASSAULT — adjudication (2026-06-09)

Adjudicates the creative campaign to recover data byte-exact off a REAL cassette, both
**acoustic** (phone next to speaker) and **wired** (deck line-out). The faithful simulator
`experiments/tape_v2/real_channel_sim.py` reproduces the measured acoustic contamination
(validated: it correctly fails the M16/M32 tone schemes that the OLD sim wrongly blessed,
matching the real-capture survival map — `results/real_sim_validation.json`).

**The bar.** A config "lives" only if the **ACHIEVABLE** (real, non-genie) decode path is
**RS-closable to byte-exact** — judged on the byte-error rate (the true RS input), and
confirmed by a TRUE end-to-end roundtrip (encode → modulate → faithful sim → real tracker →
de-interleave → RS-decode → compare bytes). The genie ceiling (oracle symbol + best timing)
is reported only as a diagnostic; it never decides a verdict. Every scheme is gated by a
no-channel **sanity BER ≈ 0** to prove the demod has no bug inflating a SURVIVES.

---

## 1. Scorecard

All numbers on the **master3 (tape)** capture model unless noted; master2 = AAC voicememo path.

| Approach | Sanity BER | Genie BER | Achievable byte-ER | RS-closable (achievable, true end-to-end)? | Net bps | Verdict |
|---|---|---|---|---|---|---|
| **Wide-space + guards** (`WS_M16_K1_sp3_N256`) | **0.0** | 0.023 | ~0.11 (per-sym) | **YES — byte-exact at the frame level**; verified 2/3–3/3 seeds, marginal on robust RS | **374** (robust) / 279 (safe) | **SURVIVES (tape), PARTIAL (AAC)** |
| **Chirp-SS / CSS** (`SF6 bw9000 fc5000`, pilot-aided) | **0.0** | **~0.000** | **0.164** (pilot_every=2) | **YES — 7/8 seeds at RS(255,127); 4/4 at RS(255,95)** | 299 (FAST) / **223** (SAFE) | **SURVIVES (with pilot front-end)** |
| Acoustic tone PHY (M32K2, ±repetition) | 0.0 | 0.023–0.27 | 0.34–0.66 | **NO** — genie RS-closable, achievable never is | — | **FAILS** |
| **Wired line-in** (`OFDM c4_qpsk`) | 0.0 (CRC clean) | n/a (CRC) | **0.0** (CRC-clean) | **YES** trivially; worn deck CRC 0.88 → mid-RS closes | **4860** stereo / 2430 per ch | **SURVIVES** |

Notes that decide the verdicts (honest):

- **The evaluator is faithful, not a soft harness.** The legacy 1-bin `M16K2 sp1 N77` baseline
  reproduces the VALIDATED real floor (genie ~0.196, RS-uncloseable) and FAILS the true
  closure test (126/126 codewords). The `sp2` near-miss decoy (480 Hz guard) also FAILS
  closure (126/126) even though its per-symbol aggregate byte-ER (~0.11) looks identical to
  the winner's. Only `sp3` (562 Hz guard) passes. Independently re-run here:
  `sp3 = byte-exact (0/126)`, `sp2 = 126/126 fail`, `base = 126/126 fail`.
- **Per-symbol byte-ER is optimistic; the frame-level RS roundtrip is the real gate.** The
  ranked-by-per-symbol "best" in `assault_widespace_master3_contrast.json` is `M24K2sp2N256`
  (ach byte-ER 0.242), but it does NOT pass true closure. `WS_M16_K1_sp3_N256` is the config
  that actually closes — K=1 (orthogonal MFSK) is more tracker-robust than K=2 here.
- **Acoustic tone PHY (`assault_acoustic.json`) is the control that FAILS:** every variant
  (M32K2, wide-M8/M4, ×2/×3 repetition diversity) is genie-RS-closable but the achievable
  tracker floors at byte-ER 0.34–0.66. `survivors_achievable: []`. This is the wall the other
  two approaches had to beat, and it confirms the win is real, not a metric artifact.

---

## 2. THE ACOUSTIC VERDICT

**YES — there is now a phone-next-to-speaker PHY the faithful sim says SURVIVES byte-exact on
the achievable path.** Two independent routes clear the wall that floored every 1-bin tone
scheme; the tone PHY itself still FAILS.

### Primary acoustic recommendation: WIDE-SPACE `WS_M16_K1_sp3_N256`

- **PHY:** M=16, K=1 (orthogonal MFSK), tone spacing = 3 FFT bins, N=256 samples/symbol →
  **188 Hz bins, 562 Hz guards**, tones 400–9188 Hz, 4 bits/symbol, contrast detector
  (tone energy minus its own guard-bin pedestal). No pilot front-end; the plain
  concentration-lock tracker suffices.
- **FEC:** interleaved RS(255,127) (robust rung, `m3_codec`) + global column interleave.
- **Projected net:** gross 750 bps × RS 0.498 = **~374 net bps → ~0.25 MB per C90 (mono)**,
  ~0.50 MB using both stereo tracks if the real tape supports it.
- **Physical close-coupling needed:** **NONE on the tape path.** The contamination sweep shows
  it stays byte-exact at FULL measured contamination (1.0) down to 0.2× — it closes at the
  real channel's measured reverb/ISI level, no blanket/jammed-phone required.
- **Honest caveat (verified here, sharper than the original write-up):** on a deep-interleave
  40 KB payload (315 codewords) the robust rung is **marginal** — 2/3 seeds byte-exact, the
  third failing at **6/315 codewords** (byte-ER 0.019, just over the t=64 robust budget). On a
  16 KB payload it is a clean 0/126. So robust-RS WS lives but sits **right at the edge**; the
  safe move is one RS rung lower (RS(255,111)→326 bps or RS(255,95)→279 bps) to buy margin,
  exactly the lesson the CSS optimizer learned on its one stress seed.
- **AAC path (master2) is PARTIAL:** 2/3 seeds byte-exact, worst seed 5/126 cw (byte-ER 0.040).
  The AAC frame-dependent nonlinearity is the residual; a one-step-lower RS rate or modest
  close-coupling closes it. If the phone records uncompressed (WAV/voice-memo lossless), this
  caveat disappears.

### Alternative acoustic recommendation: CHIRP-SS / CSS (diversity / AAC-robust)

- **PHY:** LoRa-style CSS, SF6 (64 chips), 9 kHz sweep, fc 5 kHz, Gray symbols, **pilot every 2
  data symbols** (load-bearing — interpolates the smooth ±10-sample flutter drift), incoherent
  ±2-sample combining.
- **Why it matters:** the spread-spectrum processing gain collapses the GENIE BER from ~0.10 to
  **~0** — it averages the diffuse floor away at its root instead of dodging it with guards. It
  is the most robust against the diffuse/AAC floor (genie 0.0005 even on AAC).
- **FEC / net:** **CSS-SAFE** = RS(255,95) → **223 bps**, 4/4 stress seeds byte-exact (~0.30 MB
  /C90). **CSS-FAST** = RS(255,127) → 299 bps, 7/8 seeds (upside rung).
- **Cost:** lower rate than WS and it REQUIRES the pilot-aided timing front-end. Carry it as the
  robustness/diversity rung, not the headline rate.

**Bottom line:** the acoustic wall ("data in 1-bin tones can't survive a 25% diffuse floor") is
broken two ways. WS gives the highest acoustic rate with no pilot and no close-coupling but sits
at the edge of the robust RS budget; CSS gives a lower but rock-solid rate via processing gain.
Both want a real-tape confirmation on master4.

---

## 3. THE WIRED VERDICT

**SURVIVES, decisively — and it is the high-rate route.** Removing the acoustic hop (deck
LINE-OUT → USB interface → lossless PCM) deletes the entire diffuse-contamination term; only
frozen tape physics (band-limit, post-sync residual flutter ~0.046%, deck SNR ~50 dB) remain.
Every high-rate config is byte-clean on the achievable path:

- **C4 OFDM uniform-QPSK** (N_FFT 256, ~187 Hz spacing, dense pilots + per-symbol timing
  tracker): gross **3897 bps**, achievable BER **0.0**, CRC-clean. Worn-deck (44 dB, 11 kHz,
  2× residual flutter) CRC-pass drops to 0.88 — the mid RS(255,159) rung closes it with margin.
- Combinatorial M16/M32/M48: genie BER 0, achievable byte-ER ~0.003, all RS-closable.

**Recommended wired config:** C4 OFDM QPSK + interleaved **RS(255,159)** (rate 0.624) →
**2430 net bps/channel, 4860 bps STEREO (L+R), ~3.28 MB per C90.**

**Hardware (~EUR30):** any class-compliant USB audio interface with line-in — **Behringer
UCA222 (~EUR30)** RCA line-in, or Focusrite Scarlett Solo (~EUR110). Deck RCA/3.5 mm line-out
→ interface line-in → record a lossless WAV. Stereo doubles throughput; enough for the 150 KB
LLM payload with comfortable margin.

---

## 4. Recommendation — single best next physical step per path

- **ACOUSTIC (master4):** Re-record **master4 with `WS_M16_K1_sp3_N256` as the headline rung**,
  but at **RS(255,111) (~326 bps)** rather than the edge-of-budget robust RS(255,127) — the
  40 KB-payload reproduction here shows the robust rung is marginal (one seed at 6/315 cw).
  Lay down **CSS-SAFE (SF6, pilot_every=2, RS(255,95), 223 bps)** as the second rung for
  diversity / AAC robustness. Decode the real capture with the existing
  `assault_widespace.rs_closure_test` / CSS pipeline and confirm byte-exact off real tape. If
  the phone path is AAC, prefer a lossless-recording app to remove the master2 caveat.
- **WIRED:** Buy a **Behringer UCA222 (~EUR30)**, wire **deck RCA line-out → UCA222 line-in →
  lossless WAV**, and record **master4-wired with C4 OFDM QPSK + RS(255,159)**. This is the
  fast, byte-exact, high-capacity (3.28 MB/C90 stereo) route and the recommended primary
  channel for real cassette I/O.

---

### Tools & artifacts
- Wide-space: `experiments/tape_v2/assault_widespace.py`;
  `results/assault_widespace_{master3,master2}_contrast.json` (per-symbol sweep);
  true closure via `assault_widespace.rs_closure_test` (reproduced here).
- CSS: `experiments/tape_v2/assault_css.py`, `assault_css_optimize.py`;
  `results/assault_css.json`, `results/assault_css_optimize.json`.
- Acoustic tone control (FAILS): `experiments/tape_v2/assault_acoustic.py`;
  `results/assault_acoustic.json`.
- Wired: `experiments/tape_v2/assault_wired.py`; `results/assault_wired.json`.
- Faithful sim + validation: `real_channel_sim.py`, `validate_real_sim.py`;
  `results/real_sim_validation.json`. Full physics write-up: `docs/REAL_CHANNEL.md`.
