# R4 - Literature Survey: Aerial Acoustic Data Systems

Survey date: 2026-06-10  
Purpose: Inform master9 design by mapping what shipped systems and academic work achieve speaker->microphone, and extracting receiver techniques transferable to the cassette channel.

---

## 1. ggwave / GibberLink

**What it is.** ggwave (Georgi Gerganov, 2020–) is the most widely deployed open-source data-over-sound library. GibberLink (ElevenLabs Hackathon 2025) popularised it for AI-agent communication.

**Modulation.** Multi-frequency FSK (MFSK). Data split into 4-bit nibbles; each transmission slot carries 3 bytes via 6 simultaneous tones drawn from a 96-frequency grid.

**Frequency parameters.**
- Audible band: F0 = 1875 Hz, frequency spacing dF = 46.875 Hz, span ~4.5 kHz (1875–6375 Hz).
- Ultrasonic band: F0 = 15000 Hz, same dF.
- At 48 kHz / N=1024 samples per frame: bin width = 48000/1024 = 46.875 Hz exactly. Each "tone" occupies exactly 1 FFT bin. No OFDM, no cyclic prefix.

**Protocol table (48 kHz default).**

| Mode | framesPerTx | bytesPerTx | tones | symbol dur (ms) | gross bps |
|---|---|---|---|---|---|
| Audible Normal | 9 | 3 | 6 | 9×21.3=192 ms | 3B/192ms = 125 bps |
| Audible Fast | 6 | 3 | 6 | 128 ms | ~187 bps |
| Audible Fastest | 3 | 3 | 6 | 64 ms | ~375 bps |
| DT/MT Normal | 9 | 1 | 2 | 192 ms | ~42 bps |
| DT/MT Fast | 6 | 1 | 2 | 128 ms | ~63 bps |
| DT/MT Fastest | 3 | 1 | 2 | 64 ms | ~125 bps |

With Reed-Solomon overhead, net payload rate is 64–268 bps depending on mode and message length. The 2025 academic evaluation (Evaluating Acoustic Data Transmission Schemes, arXiv:2602.02249) measured ggwave_a at 268 bps gross in a real indoor multipath environment.

**Sync.** Start/end markers are special distinct tone sequences (not data tones). Receiver correlates against known markers; no continuous pilot tracking.

**Robustness.** Very robust to room multipath because: (a) 192 ms symbols are long compared to any room reverb (~10–30 ms T60), so ISI is absorbed within the symbol; (b) single-tone detection is insensitive to phase; (c) RS ECC.

**Ceiling.** ~300–400 bps. MFSK is spectrally inefficient — 6 tones simultaneously convey only 3 bytes = 24 bits. This is 4 bps/Hz across the 4.5 kHz span = 5.3 bps/Hz if corrected for the 6 active tones per 4.5 kHz. But the long symbol duration (192 ms Normal) is wasted whitespace vs throughput. The library makes no attempt at phase-coherent or QAM modulation.

**Sources:** https://github.com/ggerganov/ggwave · https://arxiv.org/pdf/2602.02249 · https://brianbraatz.github.io/p/gibberlink-nutshell/

---

## 2. libquiet / Quiet.js OFDM

**What it is.** libquiet wraps liquid-dsp and exposes a set of JSON-configurable modem profiles including OFDM, GMSK, FSK, and QAM modes. Available as a C library and a JavaScript port (Quiet.js).

**Key profiles (from quiet-profiles.json).**

| Profile | Modulation | Center freq | OFDM subcarriers | CP len | Inner FEC | Outer FEC | Target rate |
|---|---|---|---|---|---|---|---|
| audible | GMSK | 4200 Hz | — | — | v27 (½) | none | ~1–2 kbps |
| audible-7k-channel-0 | arb16opt (16-QAM) | 9200 Hz | 48 | 8–16 | v29 | rs8 | ~7 kbps |
| audible-7k-channel-1 | arb16opt (16-QAM) | 15500 Hz | 48 | 8–16 | v29 | rs8 | ~7 kbps |
| cable-64k | QAM-1024 | 10200 Hz | 128 | 20 | v27p23 | rs8 | ~64 kbps |
| ultrasonic-3600 | V29 | 18500 Hz | 64 | — | v27 | none | ~3.6 kbps |
| ultrasonic | GMSK | 19000 Hz | — | — | v27 | none | ~1–2 kbps |
| ultrasonic-fsk-fast | FSK-16 | 18800 Hz | — | — | v29 | none | ~600 bps |

**OFDM profile detail (audible-7k).** 48 subcarriers at 9200 Hz center; CP length 8–16 samples at 44.1 kHz (0.18–0.36 ms). Subcarrier spacing ~220 Hz. 16-QAM = 4 bits/carrier. Gross ~7 kbps. CP choice is very short — it assumes a low-reverb environment (cable, anechoic, or very close range).

**Cable-64k.** 128 subcarriers, QAM-1024 (10 bits/carrier), CP 20 samples at 44.1 kHz = 0.45 ms — designed for wired 3.5 mm cable, not air. The very short CP and 10-bit constellation require cable-quality SNR (>30 dB) and near-zero multipath. Over air, this profile degrades badly.

**Sync.** Quiet relies on preamble-based timing detection (cross-correlation with a known Zadoff-Chu-like sequence) and single-pass frame synchronisation. No continuous pilot tracking; phase offset is corrected per-frame but not per-symbol. This means moderate oscillator drift (tape flutter) will accumulate within a frame and corrupt late symbols.

**Robustness vs our channel.** The 7 kbps air profile achieves ~7 kbps in benign conditions (quiet room, close range, no flutter). The arXiv:2602.02249 evaluation found "many existing schemes face challenges in practical usage, largely due to severe multipath propagation indoors and varying audio characteristics." Quiet profiles lack symbol-by-symbol timing correction, making them vulnerable to flutter.

**Sources:** https://quiet.github.io/quiet-blog/2016/03/30/quiet-profile-lab-build-modem-learn-dsp.html · https://github.com/quiet/quiet-js/blob/master/quiet-profiles.json · https://quiet.github.io/

---

## 3. Chirp.io

**What it is.** Chirp (now acquired by Asio Ltd) was a commercial data-over-sound SDK. Deployed in venues (Disney parks, retail) for proximity triggering and small-payload broadcasts.

**Modulation.** M-ary FSK ("sonic barcode" encoding). Data encoded as a sequence of tones from a chromatic-scale-like frequency grid. Later versions added broader-band ultrasonic modes.

**Rates.** Audible profiles: ~20–200 bps. Ultrasonic / faster profiles: up to ~2 kbps. The R&D team reported achieving "2× higher than any recorded for data-over-sound communications using a smartphone" in internal testing, implying ~2–4 kbps at some point, but no peer-reviewed number is public.

**Range.** 1 cm to 100 m depending on mode; >99% reliability at rated range.

**Sync.** Proprietary. Assumed preamble-based. The company does not disclose pilot/timing details.

**Sources:** https://medium.com/chirp-io/sending-data-using-sound-with-chirp-25ad5cff199a · https://audioxpress.com/article/r-d-stories-aoip-delivers-on-flexibility-is-controllability-next-1

---

## 4. Disney Research Zurich — Acoustic Broadcast to Smartphones

**Citation.** Mangold, Frigg, Gross (Disney Research Zurich / ETH Zurich). "Acoustic Data Transmission to Collaborating Smartphones — An Experimental Study." SIGGRAPH Mobile Workshop 2013.

**Application.** Broadcast data from cinema/venue sound system to audience smartphones. Data is hidden in or alongside the movie soundtrack.

**Approach.** Acoustic SDR; encodes data in the audio channel. Collaborating smartphones share received fragments over Wi-Fi/Bluetooth to collectively correct errors (cooperative diversity).

**Rate.** Not publicly disclosed in the abstract. Targeting "sufficient for NFC-style payloads" (URL, session key, short identifiers) — likely 100–500 bps.

**Techniques.** Multipath tolerance via redundancy and cooperation; no disclosed CP or pilot details. The cooperative model is their distinguishing contribution, not a higher per-device rate.

**Sources:** https://studios.disneyresearch.com/2014/04/04/acoustic-data-transmission-to-collaborating-smartphones-an-experimental-study/

---

## 5. Dhwani — Microsoft Research Acoustic NFC

**Citation.** Nandakumar, Chintalapudi, Padmanabhan, Venkatesan (MSR India). "Dhwani: Secure Peer-to-Peer Acoustic NFC." ACM SIGCOMM 2013.

**What it is.** Replaces NFC hardware with smartphone speaker+mic. Designed for near-field (< 30 cm) device-to-device payment/pairing.

**Modulation.** OFDM. Occupies 24 kHz total bandwidth.

**Data rate.** 2.4 kbps at the physical layer, sufficient for existing NFC payloads.

**Security.** JamSecure: the transmitter simultaneously jams its own transmission with noise it knows; the nearby legitimate receiver subtracts the jamming via self-interference cancellation; a distant eavesdropper sees only noise. This is an application-layer security feature, not a PHY rate technique.

**Multipath.** Near-field means minimal room multipath. CP design not disclosed.

**Sources:** https://www.microsoft.com/en-us/research/project/dhwani/ · https://dl.acm.org/doi/10.1145/2534169.2486037

---

## 6. LISNR — Ultrasonic Proximity SDK

**What it is.** Commercial proximity/payment SDK (automotive, retail). Operates near-ultrasonic (17–22 kHz).

**Modulation.** Proprietary. Center frequency 18 kHz (good tradeoff: low audibility, fair mic/speaker response, reliable <1 m).

**Rates.** 1.38–2.76 kbps (rate-1/2 coded to uncoded). Purpose is token/ID transmission for proximity events, not bulk data.

**Source:** https://lisnr.com/data-over-sound/

---

## 7. High Data Rate Near-Ultrasonic Communication (arXiv:2103.11261)

**Citation.** EUSIPCO 2021 paper.

**Band.** 18–20 kHz (near-ultrasonic consumer devices).

**Key claim.** 4 kbps over up to 5 m — "an order of magnitude higher than similar systems in the literature" at time of writing.

**Modulation.** Coherent modulation + phase-coherent adaptive equalization. Authors drew analogies to underwater acoustic (UWAC) channels: the near-ultrasonic indoor channel exhibits similar multipath and frequency-selective fading to shallow-water acoustic.

**Receiver techniques.** Adaptive equalization (DFE-style or iterative). "Phase-coherent" implies absolute phase recovery, not differential — so a pilot-aided PLL or decision-directed carrier tracking is required.

**Source:** https://arxiv.org/abs/2103.11261 · https://eurasip.org/Proceedings/Eusipco/Eusipco2021/pdfs/0001681.pdf

---

## 8. Ultrasonic Airborne OFDM (50 kHz transducers)

**Citation.** "Evaluation of Multiple-Channel OFDM Based Airborne Ultrasonic Communications." Ultrasonics vol. 71, 2016.

**Transducers.** Commercial SensComp capacitive ultrasonic at 50 kHz center. Not consumer speakers/mics.

**Modulation.** BPSK and 16-QAM OFDM with CP.

**Rates.**
- BPSK: 45 kbps, error-free up to 11 m LOS.
- 16-QAM: 180 kbps, up to 6 m.

**CP.** Included to mitigate multipath; specific length not disclosed in abstract. BER "significantly improved" with CP vs without.

**Relevance.** Proves the physics supports high rates when the transducers have flat frequency response. Consumer speakers roll off severely above 8–10 kHz, which is the binding constraint in our channel.

**Source:** https://pubmed.ncbi.nlm.nih.gov/27365316/

---

## 9. Acoustic OFDM Symbol-by-Symbol Doppler Compensation (PMC 4789520)

**Citation.** "An Acoustic OFDM System with Symbol-by-Symbol Doppler Compensation for Underwater Communication." Sensors, 2016.

**Domain.** Underwater (30 m vertical link), but the Doppler compensation technique transfers directly to flutter.

**OFDM parameters.** 81 active subcarriers; cyclic prefix 0.5T₀ (50% of symbol duration = very generous, ~5 ms); symbol duration 10.67 ms; center 24 kHz, bandwidth 7.6 kHz.

**Data rate.** 7.5 kbps with 16QAM + 64QAM; Turbo coded; free of errors in sea trials with source moving at up to 2 m/s.

**Doppler/flutter technique.** Two-stage:
1. Coarse: monitor drift of Power Delay Profile (PDP) across symbols. The PDP peak shifts in delay when the source moves; the shift rate gives a Doppler estimate.
2. Fine: continual pilot subcarriers distributed within each OFDM symbol. Per-symbol phase rotation of each pilot gives residual CFO (carrier frequency offset). ICI matrix is computed and corrected in frequency domain.

**Key lesson.** Symbol-by-symbol pilot tracking outperforms single-pass resampling when velocity/flutter changes rapidly across symbols — exactly our flutter scenario. The PDP-drift approach is the acoustic equivalent of our existing timing-trajectory front-end (h5_pll_decode.py).

**Source:** https://pmc.ncbi.nlm.nih.gov/articles/PMC4789520/

---

## 10. Adaptive F-FFT / Partial-FFT for ICI Mitigation (arXiv:2110.05129)

**Citation.** "Adaptive F-FFT Demodulation for ICI Mitigation in Differential Underwater Acoustic OFDM Systems." 2021.

**Problem.** Doppler spread (here: flutter) causes ICI in standard OFDM. When Doppler shift equals ~10–20% of subcarrier spacing, BER degrades badly.

**Solution.** F-FFT: multiple partial FFTs over overlapping time segments within one symbol; select the segment that maximises coherence. Reduces ICI by several dB vs conventional OFDM detection.

**Relevance.** Flutter at 0.41% wrms. At 750 Hz carrier spacing (master8), 0.41% of 750 Hz = 3.1 Hz frequency deviation — 0.4% of spacing, small. At 94 Hz spacing (N512, 8-bin grid at 48 kHz), 0.41% of 94 Hz = 0.39 Hz, still <0.5% of spacing. ICI from flutter is not our current binding problem; timing desync between symbols is (as confirmed by N1024 failure). F-FFT is a tool if we shrink subcarrier spacing into the ~50–100 Hz range to pack more carriers.

**Source:** https://arxiv.org/abs/2110.05129

---

## 11. ChirpCast (arXiv:1508.07099)

**Citation.** "ChirpCast: Data Transmission via Audio." 2015. Ultrasonic broadcast of WiFi keys.

**Rate.** 200 bps. Commodity laptop speakers + built-in microphones.

**Techniques.** Undisclosed (abstract only). Robust room-specific broadcasting emphasis.

**Note.** Historically significant as an early "acoustic air-gap" demo, but well below what we have achieved.

**Source:** https://arxiv.org/abs/1508.07099

---

## 12. Mitigating Acoustic Multipath Effects Using OFDM (MDPI Electronics, April 2026)

**Citation.** MDPI Electronics 2026, DOI: 10.3390/electronics15081717.

**Setup.** Experimental SDR study. FFT length 64, CP 16 samples (CP/FFT = 25%). 48 data carriers. QPSK modulation. 48 kHz sample rate. Gross bitrate ~3.6 kbps.

**Result.** CP-OFDM successfully eliminates ISI from room multipath when CP > channel impulse response length. CP of 16/48000 = 0.33 ms protects against ~0.33 ms delay spread. A typical domestic room has T60 ~200–400 ms but first-reflection delay spread only ~5–20 ms; CP must exceed the dominant reflections' time-of-arrival spread, not T60.

**Source:** https://www.mdpi.com/2079-9292/15/8/1717

---

## 13. Summary Rate Table

| System | Bandwidth | Modulation | Rate | Distance | Self-tracking? |
|---|---|---|---|---|---|
| ggwave Fastest | ~4.5 kHz | MFSK-6 | ~375 bps gross | 1–10 m | No (long symbol absorbs drift) |
| libquiet audible-7k | ~5 kHz | 16-QAM OFDM 48sc | ~7 kbps | 0.5–2 m | No |
| Dhwani | 24 kHz | OFDM | 2.4 kbps | <30 cm | Minimal |
| LISNR | ~4 kHz | Proprietary FSK | 1.4–2.8 kbps | <1 m | No |
| ChirpCast | ultrasonic | FSK | 200 bps | room | No |
| EUSIPCO-2021 NUSC | 2 kHz (18–20) | Coherent OFDM+DFE | **4 kbps** | 5 m | Yes (pilot+adaptive EQ) |
| Sensors-2016 UW-OFDM | 7.6 kHz | 16QAM/64QAM | **7.5 kbps** | 30 m UW | Yes (PDP+continual pilot) |
| 50 kHz ultrasonic OFDM | 45 kHz | 16-QAM | 180 kbps | 6 m | No (specialized transducers) |
| **master8 DQPSK (ours)** | 8.25 kHz | DQPSK 10sc | **934 bps net** | tape→speaker→mic | Yes (pilot EMA+DD) |

---

## 14. What Transfers to Our Channel

### 14.1 Our advantages vs the literature

- **SNR.** Median 38.3 dB (p10 33.1 dB). This is exceptional. The NUSC paper targets ~20–25 dB; ggwave works at 10–15 dB. Our 38 dB gives approximately 3.5 extra bits/symbol on every carrier (64-QAM vs QPSK margin). Shannon capacity on a 10 kHz channel at 38 dB SNR: C = 10000 × log2(1 + 10^3.83) ≈ 10000 × 12.7 ≈ **127 kbps** theoretical. We are using ~0.7% of that capacity.

- **Bandwidth.** We use 0.75–9.0 kHz today. The channel extends to ~11 kHz (Schroeder sounder). Most literature systems target 2–5 kHz (audible phones) or push to ultrasonic to avoid audibility constraints. We have no audibility constraint.

- **Lossless capture.** Removing AAC (which forced minimum 562 Hz tone spacing) potentially allows carrier spacing down to ~100–200 Hz — a 4–7× density increase if the reverb leakage permits it.

### 14.2 Our unique challenge: cassette flutter

No aerial acoustic system in the literature deals with cassette flutter. The closest analog is underwater Doppler (moving transducers). Key comparison:

- Cassette flutter: 0.41% wrms, dominant at 3–30 Hz (flutter spectrum). At a carrier of 5000 Hz, 0.41% → ±20.5 Hz frequency deviation. At subcarrier spacing 750 Hz (master8), 20.5/750 = 2.7% of spacing — negligible ICI. At spacing 94 Hz, 20.5/94 = 22% — significant ICI.
- Timing effect: flutter appears as timing jitter. At N=512 samples / 10.67 ms symbol, 0.41% wrms = ±43 µs (1.8% of symbol period) = ±2.1 samples at 48 kHz. The pilot tracking in master8 reduces residual to ~5 µs.
- Sampling frequency offset (SFO): deck clock +0.117% is a uniform stretch, corrected by global Schroeder chirp realignment. This is NOT flutter; it is constant. Pilot-based SFO trackers (used in optical OFDM, arXiv:2601.x) would address drift within a transmission.

**Flutter handling approaches from the literature applicable here:**
1. **Continual pilot subcarriers (PMC 4789520):** Place 1–2 unmodulated pilots at known frequencies every symbol. Phase rotation of pilots = CFO + flutter phase noise. Correct per-symbol. This is exactly master8's pilot-EMA approach. Extension: use 2 pilots at separated frequencies to get both timing and frequency-offset information simultaneously.
2. **PDP drift monitoring (PMC 4789520):** Track when the channel impulse response "slides" in delay — equivalent to our chirp timing trajectory front-end. Already implemented in h5_pll_decode.py.
3. **Decision-directed carrier tracking (master8):** Already implemented. Residual timing std drops 3.1× with DD refinement. Literature agrees: DD tracking reduces residual phase error by ~6 dB vs pilot-only.

### 14.3 Cyclic prefix design

Our channel has reverb tail ~8 ms (from real_channel_params.json: `reverb_tail_tau_ms = 7.86 ms`). Adjacent-bin leakage is dominated by a ~20-sample exponential reverb tail (0.42 ms). Distant-bin leakage has a flat ~25% floor independent of symbol length.

**CP rule (standard OFDM):** CP duration must exceed the channel's maximum multipath delay spread. For us: 8 ms reverb tail. At 48 kHz, that is 384 samples. A symbol of N=512 with a CP of 384 would use 75% overhead — catastrophically inefficient.

**Why DQPSK without CP works:** master8 uses *differential* phase — the phase difference between symbol N and symbol N+1 on the same carrier. ISI from symbol N-1 smearing into symbol N affects both symbols equally (same multipath), so the differential cancels the slow-varying ISI. This is the key insight that lets us avoid CP. The reverb tail must not span more than ~half a symbol for this to hold. At N=512 (10.67 ms), the 8 ms tail is 75% of the symbol — marginal but apparently sufficient (proven by zero RS failures).

**For higher-order constellations (16QAM, 64QAM):** absolute phase matters, so ISI cannot be differentially cancelled. Full CP would be needed. A 8 ms CP at 48 kHz = 384 samples. Usable symbol length must be much larger (N ≥ 2048, 10:1 ratio) to keep CP overhead < 10%. At N=2048 on a 48 kHz channel: symbol rate = 48000/2048 ≈ 23.4 Hz; with 10 carriers at QPSK = 20 bps/symbol × 23.4 symbols/s = 468 gross bps — worse than master8. For CP-OFDM to win, we need more carriers or higher-order modulation.

**The libquiet audible-7k profile uses CP=8–16 samples at ~44 kHz = 0.18–0.36 ms.** That profile would see severe ISI in our channel (reverb 8 ms >> CP 0.36 ms). It works for libquiet at short range because a typical near-field room acoustic has a much shorter effective delay spread (first reflections arrive in 1–5 ms, and at close range direct-path energy dominates). Our tape channel forces multipath through a ~7 ms exponential.

### 14.4 Pilot density for time-varying channels

Standard OFDM rule (Nyquist in time): pilot update interval should be ≤ T_coherence/2, where T_coherence ≈ 1/(2×max_flutter_rate). Flutter dominant at up to 30 Hz (from R2 margins: f90 = 28.6 Hz). T_coherence ≈ 1/(2×30) ≈ 16.7 ms. A pilot every 16.7 ms = every ~1.6 symbols at N=512 (10.67 ms). master8 updates timing on every symbol — over-sampled by ~1.6×, which is healthy margin.

For OFDM with N=512 (same symbol rate), 1 pilot per symbol is sufficient. Scaling to N=256 (symbol rate 187.5 Hz, symbol duration 5.3 ms): pilot every 5.3 ms = 3.1× over-sampled at 30 Hz flutter. Fine. Scaling to N=1024: symbol rate 46.9 Hz, duration 21.3 ms = under-sampled for 30 Hz flutter (1.4× Nyquist margin only). This is consistent with N1024 failing (confirmed in R2 margins).

**Quantitative pilot spacing recommendation:** Maximum safe symbol duration ≈ 1/(2 × f_flutter_90) = 1/(2×30) = 16.7 ms. Comfortable target: symbol duration ≤ 10 ms. N=480 or N=512 at 48 kHz = 10.0–10.67 ms sits right at the comfortable edge. N=256 (5.33 ms) provides 3× safety margin.

### 14.5 Frequency-selective fading nulls

The channel H(f) shows notches: at ~750 Hz a deep null at ~3127 Hz (-49.5 dB in master3), and at ~793 Hz a 16.7 dB drop in master2. These are room standing-wave nodes, not fixed — they drift slightly between recordings. OFDM's key advantage over single-carrier is that per-subcarrier equalization neutralises these nulls, provided the subcarrier spacing is narrow enough that each subcarrier sees a flat H. At 750 Hz spacing (master8), a null at 3127 Hz will destroy the whole carrier (H = -49.5 dB). At 94 Hz spacing, that null would hit at most 2–3 adjacent carriers, with neighbours at 3000 Hz and 3094 Hz possibly surviving. Per-carrier equalization + bit-loading (skip deeply-faded carriers) is the standard mitigant — widely used in power-line and DSL OFDM.

---

## 15. Concrete Recommendations for master9

Based on this survey and the measured channel parameters:

### R-1: Stay differential (DQPSK / D8PSK), do NOT switch to coherent QAM
Reason: the 8 ms reverb tail makes CP-OFDM with coherent high-order QAM extremely inefficient. CP overhead at N=512 would be 75%. The differential approach (master8) already cancels slow ISI; it proved robust with zero RS failures. Move from DQPSK (2 bits/symbol) toward D8PSK (3 bits/symbol) first. D8PSK requires the decision margin to drop from 45° to 22.5°. From R2 margins: PASS section has 8.7% of carrier-symbols exceeding 22.5° residual — too high for reliable D8PSK today. Headroom exists on most carriers (carrier 0 at 750 Hz has only 0.9% >22.5°); carrier 4 at 3750 Hz has 30% >22.5° — a channel null, must skip. **Action: implement D8PSK with per-carrier order selection (2 or 3 bits based on measured EVM), skip carrier 4 entirely or replace it.**

### R-2: Increase carrier count from 10 to ~20–40
Current density: 10 carriers at 750 Hz spacing, 750–8250 Hz. With lossless capture (AAC constraint gone), the minimum safe spacing from cross-bin leakage data (R2): offset_2bin at 188 Hz = -13.6 dB mean leak. For DQPSK, this leakage causes phase noise ~arctan(0.21) ≈ 12°, within the 45° QPSK slicing margin. Minimum safe spacing without AAC: **~375 Hz (4 bins at N=512, 93.75 Hz/bin)** — a 2× density increase. Target: 20 carriers at 375 Hz spacing, 375–8250 Hz (using only up to ~8.5 kHz where the channel has ≥28 dB SNR). Gross bps scales 2× from density alone.

### R-3: Add a second unmodulated pilot at a different frequency
Current: 1 mid-band pilot (4500 Hz). Adding a second pilot at e.g. 2250 Hz gives: (a) two independent timing observations per symbol → better EMA noise reduction; (b) differential pilot phase between the two frequencies estimates frequency-selective phase slope (first-order channel tilt) → enables simple per-symbol equaliser update. This is the "distributed pilot" approach used in EUSIPCO-2021 NUSC and the UW-OFDM papers.

### R-4: Bit-loading on a per-carrier basis
Carriers 4 (3750 Hz) and 7–9 (6750–8250 Hz) show output SNR of 7.7–9.0 dB in R2 margins — marginal for QPSK (requires ~7 dB for BER 1e-3). Carriers 0–3 (750–3000 Hz) show 13–16 dB output SNR — comfortable for 8PSK. Bit-loading: assign more bits/symbol to high-SNR carriers, fewer to low-SNR, zero to nulled carriers. Standard water-filling. Academic precedent: all practical ADSL/VDSL/cable deployments, plus the NUSC paper's "adaptive equalization." Estimated gain over flat DQPSK: 1.3–1.6× in net bps.

### R-5: Reduce symbol length to N=256 for a carrier-spacing experiment
At N=256 (5.33 ms), carrier spacing = 187.5 Hz, flutter margin is 3× Nyquist. Reverb ISI per symbol = 8 ms / 5.33 ms = 1.5 symbols — this is worse, but differential phase still cancels it (same ISI on both symbols of the pair). Cross-bin leakage from reverb at 2-bin offset (375 Hz) would be: reverb tail 20 samples / 256 samples = 7.8%, vs the measured 0.047 for M32. Small enough. Target: 40 carriers at 187.5 Hz spacing, 375–7875 Hz, 4 below the rolloff-deep region. With DQPSK 2 bits/carrier + 40 carriers + symbol rate 187.5 Hz: gross = 40 × 2 × 187.5 / 2 = **7500 bps gross**; with RS(255,127) = 50% overhead: **~3750 bps net**. This is the highest near-term plausible estimate. Needs sim validation.

### R-6: For systems above 2× current rate, adopt per-carrier phase tracking (not just timing)
The NUSC paper (4 kbps over air) and the UW-OFDM system (7.5 kbps) both use per-symbol adaptive equalization — not just timing correction, but amplitude and phase update per carrier per symbol. This is equivalent to a per-carrier IIR-filtered complex channel gain estimate, updated from pilot or decision-directed feedback. Implement in the demod loop as: `H_est[c] = alpha * H_est[c] + (1-alpha) * received[c] / decision[c]`, then divide before slicing. This corrects slow frequency-selective fading (the carrier-4 null amplitude CoV of 27% is mostly slow fading at 3750 Hz). Gain: reduce EVM rms from 0.39 to ~0.15 on the problem carriers.

### Rate projection summary

| Scenario | Approach | Gross bps | Est. net bps (RS ~50% overhead) |
|---|---|---|---|
| master8 baseline | DQPSK 10c 750 Hz N=512 | 1875 | 934 |
| D8PSK on best carriers | Mixed 2–3 bits/c, 10c | ~2500 | ~1250 |
| 2× density, DQPSK | 20c 375 Hz N=512 | ~3750 | ~1875 |
| 2× density + D8PSK mix | 20c 375 Hz, 2.5 bits avg | ~4700 | ~2350 |
| N=256 dense DQPSK | 40c 187.5 Hz N=256 | ~7500 | ~3750 |
| N=256 + bit-loading | 40c, 3 bits avg, skip nulls | ~9000 | ~4500 |

Conservative target for master9: **~2000–2500 net bps (2–2.7× current record)**, achievable by doubling carrier density at N=512 with selective D8PSK on strong carriers. Ambitious target: **~3500–4500 net bps** requiring N=256 dense configuration validated in sim.

---

## Sources

- [ggwave GitHub (Georgi Gerganov)](https://github.com/ggerganov/ggwave)
- [Evaluating Acoustic Data Transmission Schemes (arXiv:2602.02249)](https://arxiv.org/pdf/2602.02249)
- [GibberLink technical deep-dive (Lorenzo Palaia)](https://www.lorenzopalaia.com/blog/understanding-gibberlink-a-deep-dive-into-ai-sound-based-communication)
- [quiet-profiles.json (Quiet.js)](https://github.com/quiet/quiet-js/blob/master/quiet-profiles.json)
- [Quiet Modem Project](https://quiet.github.io/)
- [Chirp data-over-sound overview (Medium/Chirp)](https://medium.com/chirp-io/sending-data-using-sound-with-chirp-25ad5cff199a)
- [ChirpCast: Data Transmission via Audio (arXiv:1508.07099)](https://arxiv.org/abs/1508.07099)
- [Disney Research Zurich acoustic broadcast study](https://studios.disneyresearch.com/2014/04/04/acoustic-data-transmission-to-collaborating-smartphones-an-experimental-study/)
- [Dhwani: Secure Peer-to-Peer Acoustic NFC (ACM SIGCOMM 2013)](https://dl.acm.org/doi/10.1145/2534169.2486037)
- [Dhwani Microsoft Research project page](https://www.microsoft.com/en-us/research/project/dhwani/)
- [LISNR data-over-sound overview](https://lisnr.com/data-over-sound/)
- [High Data Rate Near-Ultrasonic Communication (arXiv:2103.11261)](https://arxiv.org/abs/2103.11261)
- [Acoustic OFDM Symbol-by-Symbol Doppler Compensation (PMC 4789520)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4789520/)
- [Evaluation of OFDM-Based Airborne Ultrasonic Comms (PubMed 27365316)](https://pubmed.ncbi.nlm.nih.gov/27365316/)
- [Adaptive F-FFT for ICI Mitigation in Differential UW-OFDM (arXiv:2110.05129)](https://arxiv.org/abs/2110.05129)
- [Mitigating Acoustic Multipath with OFDM: SDR Study (MDPI Electronics 2026)](https://www.mdpi.com/2079-9292/15/8/1717)
- [InaudibleKey acoustic signal key agreement (arXiv:2102.10908)](https://arxiv.org/pdf/2102.10908)
