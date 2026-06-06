# Real-World Transmission Front-Ends

How the cassette codec survives (or fails) when the tape audio is not piped through a
transparent USB soundcard but instead crosses a *real transmission path* — a cable into a
phone mic, an acoustic gap across a room, or a Bluetooth headset link. Five Monte-Carlo
experiments (T1–T5) on the production CAS3 BFSK codec and the H2 MFSK-32 winner, plus a
purpose-built "rugged" narrowband fallback.

Tape core for the whole study is the **normal** preset
(`snr_db=42, bandwidth_hz=12000, wow_flutter_wrms=0.0010, burst_rate_per_s=0.3, burst_length_ms=6`);
the transmission front-end is added *on top* of that tape channel.

Data: `RESULTS/data/rw_*.json`. Plots: `RESULTS/plots/rw_*.png`.
Reference baselines: B0 BFSK net ~478 bps / 0.64 MB-C90-stereo on a transparent path;
H2 MFSK-32 net ~1076 bps (the only single-cassette-fitting modem on normal tape).

---

## 1. Deployment Matrix

Cells: **WORKS** (P_full=1.0 at a usable rate) / **MARGINAL** (decodes but tiny rate or
needs heavy FEC) / **FAILS** (clean_decode_prob = 0). `cdp` = clean_decode_prob,
`net` = projected net bits/s after FEC + erasure overhead.

| Transmission path | BFSK-B0 | MFSK-32 (H2) | Rugged BFSK (750/2100 Hz, rep3) |
|---|---|---|---|
| **USB soundcard** (P1, transparent) | **WORKS** cdp=1.00, raw_BER=0.000 | **WORKS** raw_BER=0.0025, net≈1076 | n/a (over-engineered for clean path) |
| **Cable → phone mic** (P2, TRRS, 7.5 kHz cap, hard clip) | **WORKS** cdp=0.92, net=93 | **MARGINAL** cdp=0.00, net=269 *padded only*, needs rate-2/10 FEC | n/a |
| **Acoustic close + quiet** (P3) | **FAILS** cdp=0.00, raw_BER=0.495 | **FAILS** cdp=0.00, raw_BER=0.264 | not tested (close path already lost to reverb) |
| **Acoustic far + noisy** (P4, 0.5–2 m, 5–30 dB) | **FAILS** cdp=0.00, raw_BER=0.495 everywhere | **FAILS** cdp=0.00, raw_BER≥0.38 everywhere | **FAILS** at 1 m: p_content_clean=0.083 (rep3) / 0.25 (rep5) |
| **Bluetooth narrowband** (P5, HFP/voip 12k) | **FAILS** cdp=0.00, raw_BER=0.495 | **FAILS** cdp=0.00, raw_BER=0.376 | **WORKS** content_BER=0, 12/12 seeds, net=13.4 |

Sources: USB/P3 row `rw_smoketest.json`; cable `rw_cable_trrs_mic.json`; acoustic
`rw_acoustic_far_noisy.json`; Bluetooth `rw_bluetooth_narrow.json`; rugged
`rw_rugged_mode.json`.

Note the inversion in the bottom two rows: the **standard modems** that win on cable/USB are
exactly the ones that die on Bluetooth and acoustic, while the **rugged fallback** that is
pointless on a clean path is the *only* survivor of the Bluetooth link — and even rugged
cannot clear the 1 m acoustic gap.

---

## 2. Operating Envelopes

### Mic bandwidth cap (T1, cable path)
The phone-recorder MEMS mic cuts at ~7.5 kHz. BFSK (tones 1200/2400 Hz) is untouched. MFSK-32
spreads 32 tones over a 400–10000 Hz grid, so **9 of 32 tones (~28%) sit above the cutoff and
are silenced**. Effect: MFSK raw_BER jumps from 0.0036 (ceiling) to 0.0668 (padded) and
clean_decode_prob collapses to 0.00, even with the level set correctly. Minimum viable fix:
re-grid MFSK tones into 400–7000 Hz before any phone-mic capture.

### Clipping robustness (T1)
The line-level → mic-level mismatch hard-clips the waveform. **BFSK is completely immune**:
raw_BER = 0.0404 is *identical* across P1 ceiling, P2 unpadded (clipped), and P2 padded —
amplitude distortion is irrelevant to frequency-keyed signalling, and corr_peak stays ≥0.835.
MFSK-32 is *not* immune: clipping adds intermodulation that lifts its raw_BER from 0.067
(padded) to 0.108 (unpadded), because narrow-band tone discrimination degrades under
nonlinearity. So clipping is a non-issue for BFSK but a second penalty for dense MFSK.

### Acoustic breakdown cliff (T3) — there is no cliff, it is a wall
Across the entire tested grid — distance {0.5, 1.0, 2.0 m} × ambient SNR {30, 22, 15, 10, 5 dB} —
**clean_decode_prob = 0.00 at every single point** for both modems (`breakdown_cliffs`: "FAILS
everywhere"). The failure mode is **reverb-driven sync loss, not ambient noise**: the chirp
preamble correlation is destroyed before bit detection starts.
- corr_peak vs distance (MFSK-32): 0.297 @0.5 m → 0.159 @1.0 m → 0.090 @2.0 m — all below the
  ~0.6 viable floor. SNR barely moves these numbers (e.g. 0.297→0.260 from 30→5 dB at 0.5 m).
- BFSK-B0 sits at raw_BER=0.495 (random) and corr_peak≈0.277 at 0.5 m, flat across all SNRs.
- **Repetition coding makes it worse**: MFSK-32 rep3 raw_BER 0.378→0.439 at 0.5 m/30 dB —
  majority-voting three sync-lost copies amplifies errors.
A viable acoustic path needs chirp-resistant sync (long Costas array), room EQ, or RT60 < 0.1 s
(near-field direct coupling), none of which exist at this operating point.

### Bluetooth verdict (T4)
HFP/voip is hostile to all standard FSK. bfsk_b0 (tones inside the 3400 Hz passband!) still
collapses to raw_BER=0.495 — the voip codec's noise-suppression / VAD destroys steady tones
even in-band. mfsk32 loses half its grid to the 3400 Hz lowpass (raw_BER=0.376). A
purpose-built narrowband BFSK (1000/2000 Hz, 600 bd) survives *partially* (raw_BER=0.136,
6/12 seeds <0.10) proving the 2:1 octave ratio matters — but net is only ~16 bps and
clean_decode_prob=0.00. **corr_peak is a liar here**: bfsk_b0 shows corr_peak=0.898 (the chirp
survives the codec) while the data is random — never trust sync acquisition alone over a lossy
voice codec.

### Rugged-mode rate cost & reliability (T5)
Rugged design: BFSK at **750/2100 Hz** (both tones inside the 300–3400 Hz telephony band),
50 baud, single 1.0 s chirp preamble, repetition-coded.
- **Bluetooth P5: solved.** rep3 → content_BER=0 on 12/12 seeds, net **13.4 bps**,
  0.018 MB/C90-stereo, P_full=1.00. The 750/2100 Hz tones pass libopus voip cleanly
  (corr≈0.98 per tone). rep5 is more conservative: 8.1 bps, 0.011 MB/C90.
- **Acoustic 1 m P4: still closed.** rep5 reaches only p_content_clean=0.25 (3/12 seeds);
  rep3 only 0.083. corr_peak floor 0.13–0.17 is far below lockable. The 500 ms reverb tail
  fills ~25 symbol periods of ISI at 20 ms symbols — symbol period must exceed RT60 to beat
  ISI, which rep coding cannot fix.

> **Caution on P_full for rugged@P4.** The erasure-based projection reports
> `rep5@P4 P_full=1.0`, but the honest end-to-end metric `p_content_clean=0.25` shows the path
> is *not* reliable. Trust `content_ber_analysis.p_content_clean`, not the erasure projection,
> for the marginal acoustic case.

Rate context: at 13.4 bps a 1.271 MB payload takes ~440 hours. Rugged mode is for **small
bootstrap payloads** (metadata, keys, sync frames), never bulk transfer.

### Net-rate summary (projected, after FEC + erasure overhead)
| Path | Best modem | net_bps | MB / C90-stereo | P_full |
|---|---|---|---|---|
| USB soundcard | MFSK-32 | ~1076 | ~1.45 | 1.0 |
| Cable → phone mic (padded) | MFSK-32 (needs rate-2/10 FEC) | 269 | 0.36 | 1.0 |
| Cable → phone mic | BFSK-B0 | 93 | 0.12 | 1.0 |
| Acoustic (any) | — | 0 effective | — | 0.0 |
| Bluetooth narrowband | Rugged BFSK rep3 | 13.4 | 0.018 | 1.0 |

---

## 3. What We Learned

1. **FSK is clipping-proof; amplitude distortion is a non-event for BFSK.** Identical raw_BER
   (0.040) clipped vs padded vs clean. Don't bother padding a line→mic cable for BFSK; you
   *must* pad for dense MFSK (intermodulation).
2. **The phone-mic 7.5 kHz cap is the real cable killer, not clipping.** It silences MFSK-32's
   top 9 tones. MFSK on any phone path requires a 400–7000 Hz tone re-grid.
3. **Acoustic phone-mic capture does not work at all** in the tested range — not at 0.5 m, not
   at 30 dB SNR. The wall is reverb-induced sync loss (RT60≈0.25–0.5 s), and it is
   distance-dominated, not noise-dominated.
4. **Repetition coding cannot rescue a sync-lost path** — it amplifies errors. Sync acquisition
   must be fixed *first* (chirp-resistant correlation / equalization).
5. **Bluetooth HFP destroys standard FSK even in-band**, because voip noise-suppression/VAD
   attacks steady tones. Only a purpose-built narrowband, repetition-coded modem with tones
   well inside 300–3400 Hz survives.
6. **A narrowband/rugged mode rescues exactly one bad path (Bluetooth), and only for tiny
   payloads** (13.4 bps). It does **not** rescue the acoustic path — symbol period < RT60 is a
   hard physical wall that rep coding can't cross.
7. **corr_peak is not a reliability oracle on lossy paths.** It measures chirp survival, which
   can stay high (0.90) while data tones are random — verify with end-to-end content BER.
8. **Hopeless paths:** all acoustic capture (close *and* far) at this operating point. Bluetooth
   is "alive but near-useless" for bulk; only cable and USB carry real throughput.

---

## 4. Recommendations for Real Use

- **Full 1.271 MB payload — recommended setup:** USB soundcard (or a custom raw-PCM phone app,
  established as transparent in the prior sweep) with **MFSK-32**. This is the only path that
  fits a single cassette. Net ~1076 bps, ~1.45 MB/C90-stereo on normal tape.
- **Acceptable fallback #1 — cable → phone mic:** use **MFSK-32 re-gridded to 400–7000 Hz with
  a level pad and ~rate-2/10 FEC** (≈269 bps, 0.36 MB/C90), or plain **BFSK-B0** (93 bps,
  0.12 MB) if FEC is not available. Multiple C90s required for the full payload.
- **Acceptable fallback #2 — Bluetooth, bootstrap only:** **rugged BFSK 750/2100 Hz, 50 bd,
  rep3** (13.4 bps). Use *only* to ferry keys/metadata/sync frames, never the model weights.
- **Do not attempt acoustic over-the-air capture** until a chirp-resistant sync (long Costas
  array) and room EQ exist, or the geometry guarantees RT60 < 0.1 s near-field coupling.
- **Verify on real hardware:** (a) the actual phone-recorder mic cutoff (7.5 kHz is an
  assumption that gates MFSK tone count); (b) real BT-HFP codec behaviour vs the libopus-voip
  approximation — confirm the 750/2100 Hz tones survive a real headset; (c) the line→mic level
  ratio and whether real AGC matches `_agc`; (d) real RIR/RT60 in the intended capture room to
  confirm the acoustic wall.

---

## 5. Caveats (simulation fidelity)

- **Synthetic RIR:** room reverb is an exponentially-decaying gaussian burst, not a measured
  impulse response. Real rooms have early reflections and modal structure that could shift the
  acoustic wall either way; the *direction* (reverb kills sync) is robust, the exact corr_peak
  numbers are not.
- **Modeled mic/speaker responses:** brick-wall-ish lowpass + bass rolloff, not measured device
  curves. The 7.5 kHz cap (MFSK-critical) is an assumed number.
- **No real handheld motion:** no Doppler/wow from a hand-held phone, no time-varying distance.
  Real acoustic capture could be worse than these static-geometry results.
- **Codec-roundtrip approximations:** Bluetooth modeled as lowpass + libopus `-application voip
  -b:a 12k`; real HFP (mSBC/CVSD) noise-suppression and VAD may differ in how aggressively they
  attack tones.
- **Erasure-based P_full vs content BER:** the projection's P_full can over-report on marginal
  paths (see rugged@P4); the content-BER clean-decode probability is the honest metric and is
  what the matrix uses for MARGINAL/FAILS calls.
- T2 (acoustic *close + quiet*) agent returned NULL and left **no data on disk**
  (`rw_acoustic_close.json` absent); the close-acoustic verdict here is inferred from the P3
  smoketest row and the T3 far-noisy results, both of which show total reverb-driven failure.

---

*Traceability:* `RESULTS/data/rw_smoketest.json`, `rw_cable_trrs_mic.json`,
`rw_acoustic_far_noisy.json`, `rw_bluetooth_narrow.json`, `rw_rugged_mode.json`;
plots `RESULTS/plots/rw_cable_trrs_mic.png`, `rw_acoustic_far_noisy.png`,
`rw_bluetooth_narrow.png`, `rw_rugged_mode.png`.
