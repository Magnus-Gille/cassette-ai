# R5: Literature Review — Communication Over Flutter/Doppler-Impaired Channels
## Relevance to master9 (cassette-AI, acoustic loop, 10 kHz BW, 38 dB SNR, 0.41% flutter, 8 ms reverb)

*Produced by research subagent, 2026-06-10.*

---

## 1. DRM / DRM30 / HamDRM-EasyDRF: OFDM Over HF Radio

### 1.1 What DRM Is

Digital Radio Mondiale (DRM) is the ITU/ETSI standard for digital HF/MW/LW broadcasting (below 30 MHz). It was engineered for the hardest known linear OFDM channels: shortwave propagation combines severe multipath (delay spreads up to 7 ms), Doppler spread from ionospheric movement (up to ~10 Hz), plus slow frequency drift. The ETSI standard (ES 201 980) defines four robustness modes optimised for different trade-offs between delay-spread and Doppler tolerance. This makes DRM the closest published broadcast standard to our cassette channel.

**Sources:** [Wikipedia: Digital Radio Mondiale](https://en.wikipedia.org/wiki/Digital_Radio_Mondiale) · [SigIDWiki DRM](https://www.sigidwiki.com/wiki/Digital_Radio_Mondiale_(DRM)) · [AllSDR DRM deep-dive](https://allsdr.blogspot.com/2016/07/digital-radio-mondiale-drm.html) · [DRM.org Technology](https://www.drm.org/about-drm/drm-technology/)

---

### 1.2 OFDM Mode Parameters (DRM30, 10 kHz channel)

The four robustness modes A–D span the design space of subcarrier-spacing vs. guard-interval, trading throughput for immunity to delay spread and Doppler:

| Mode | Δf (Hz) | GI (ms) | T_useful (ms) | T_symbol (ms) | GI/Ts | Carriers @ 10 kHz | Max net bps @ 10 kHz (64-QAM, PC3) |
|------|---------|---------|--------------|--------------|-------|-------------------|--------------------------------------|
| A    | 41.67   | 2.66    | 24.00        | 26.66        | 11%   | ~228              | ~34,800                              |
| B    | 46.88   | 5.33    | 21.33        | 26.66        | 25%   | ~206              | ~21,000 (audio); ~56,000 peak        |
| C    | 68.18   | 5.33    | 14.67        | 20.00        | 36%   | ~138              | ~45,200                              |
| D    | 107.14  | 7.33    | 9.33         | 16.66        | 79%   | ~88               | ~30,400                              |

Notes:
- Mode A: designed for medium-wave, low-Doppler, moderate multipath. Guard interval covers ≤2.66 ms delay spread. Subcarrier spacing 41.67 Hz means Doppler tolerance ~1–2 Hz RMS.
- Mode B: long-distance SW, 5.33 ms guard interval (covers the cassette's ~8 ms reverb tail only partially). 46.88 Hz spacing → ~2–3 Hz Doppler tolerance. Practical audio throughput in 10 kHz channel (Mode B, 64-QAM PC3): ~21 kbps audio coded; gross ~56 kbps at code rate ≈ 0.6.
- Mode C: better Doppler tolerance (68 Hz spacing → ~5–6 Hz tolerance), same 5.33 ms GI.
- Mode D: most robust — 107 Hz spacing (tolerates ~10 Hz Doppler), 7.33 ms GI. Minimum throughput ~6.1 kbps for 10 kHz at lowest code rate.

**Key throughput figure:** DRM30 Mode A, 64-QAM, Protection Class 3 (highest code rate ~0.67) in 10 kHz: ~34.8 kbps net. In 20 kHz: up to 72 kbps. Lower protection classes and smaller constellations reduce this proportionally.

**Spectral efficiency:** Mode A @ 34.8 kbps / 10 kHz = **3.48 bits/s/Hz** (including pilots, guard interval overhead, and ~2/3 code rate). With 64-QAM and rate 2/3 ideally you'd get 4 bits/s/Hz, so overhead is roughly 13% for pilots + guard interval combined.

**Source:** [AllSDR DRM article](https://allsdr.blogspot.com/2016/07/digital-radio-mondiale-drm.html)

---

### 1.3 DRM Pilot Pattern and Channel Tracking

DRM uses a **scattered pilot** grid in the time-frequency plane. From the ETSI spec:
- Scattered pilots repeat in a regular 4-symbol × 5-subcarrier pattern (Mode B). Every 4th OFDM symbol in every 5th subcarrier slot is a known reference cell.
- **Pilot boost:** pilots are transmitted at +3 dB relative to data cells to improve channel estimation SNR.
- The pilot density (fraction of cells used for pilots): roughly 5% of the OFDM time-frequency grid for scattered pilots, plus ~2-3% for continual reference pilots (fixed positions every symbol), plus 1-2% for frequency/time reference cells (FAC/SDC overhead). Total overhead: ~15–20% of all cells.
- **Coherence requirement:** the pilot grid spacing must satisfy: time separation ≤ coherence time/2, frequency separation ≤ coherence bandwidth/2. DRM mode B has pilot time spacing of 4 × 26.66 ms = 106 ms, implying coherence time ≥ 106 ms, i.e., Doppler spread ≤ ~9 Hz. Frequency pilot spacing = 5 × 46.88 Hz = 234 Hz, implying coherence bandwidth ≥ 234 Hz.

**The DRM scattered pilot approach is directly portable to cassette-AI:** insert scattered known-phase subcarriers at a grid density matching the flutter coherence time (~1/flutter_bw ≈ 1/2 s, very long) and the frequency coherence bandwidth (~300 Hz based on observed reverb).

---

### 1.4 HamDRM / EasyDRF: DRM Adapted for Amateur Radio

HamDRM (by Cesco HB9TLK) is a 1:1 adaptation of DRM30 for ham radio over SSB transceivers. EasyDRF wraps it in a file-transfer application. Parameters:

- **Bandwidth:** 2.5 kHz (OFDM signal occupies 350 Hz to 2850 Hz within the SSB audio passband)
- **Modes:** Uses DRM modes A, B, and E (a hamDRM-specific VHF/UHF mode)
- **Modulation:** 4-QAM, 16-QAM, 64-QAM selectable
- **Throughput:** In 2.5 kHz with 16-QAM Mode B, approximately **2–4 kbps** net (scaled from the 10 kHz numbers: 2.5/10 × 21 kbps ≈ 5 kbps, reduced by lower code rate for HF margin ≈ 2–3 kbps). DRM30 in 2.5 kHz Mode B 64-QAM nominally ~8.75 kbps raw, ~5–6 kbps after FEC.

**The cassette channel (10 kHz, 38 dB SNR) is significantly better than the HamDRM target (2.5 kHz, HF propagation SNR ~20–25 dB).** We should be operating closer to DRM Mode A than Mode D.

**Sources:** [EasyDRF homepage](https://dazdsp.org/tech/EasyDRF/) · [EasyDRF GitHub](https://github.com/DazDSP/EasyDRF)

---

### 1.5 What Transfers to master9

| DRM concept | Cassette equivalent | Parameter to use |
|-------------|---------------------|-----------------|
| Guard interval ≥ max delay spread | Reverb tail ~8 ms | GI ≥ 8–10 ms; Mode B/C fits (5.33 ms is marginal; Mode D 7.33 ms is right) |
| Δf ≫ Doppler spread | Flutter ~0.41% wrms at ~1 Hz rate → Doppler ≈ 0.01–0.05 Hz | Δf = 50–100 Hz is 1000× Doppler → already fine; any DRM mode is Doppler-tolerant here |
| Scattered pilot grid | Yes, already doing mid-band unmodulated pilot. Should add scattered pilots at 4-symbol × 5-carrier spacing | Overhead ~5% cells; huge return for channel estimation |
| Pilot boost +3 dB | Our pilot is unmodulated; could transmit at 3 dB higher power | Improves H(f) estimation quality |
| 64-QAM with rate 2/3 code | At 38 dB SNR, 64-QAM is theoretically fine (needs ~23 dB SNR); rate 2/3 RS leaves useful margin | Try 16-QAM per carrier first; 64-QAM feasible if amplitude flatness holds |

**The fundamental lesson from DRM:** the guard interval determines delay-spread robustness; subcarrier spacing determines Doppler robustness. For our channel the Doppler is tiny (0.41% flutter at ~1–5 Hz), so the constraint is the 8 ms reverb — Mode D parameters (GI = 7.33 ms, Δf = 107 Hz) are most appropriate. But current master8 uses N=512 @ 48 kHz = 10.67 ms symbols with NO cyclic prefix, which is effectively equivalent to Mode B-ish symbol duration. The ISI from 8 ms reverb on a 10.67 ms symbol with no CP is the dominant impairment — adding CP of ~8 ms would cost ~43% overhead but eliminate ISI entirely.

---

## 2. Underwater Acoustic OFDM: Standard Receiver Chain for 0.1–1% Doppler

### 2.1 Why UWA Is the Closest Cousin

Underwater acoustic (UWA) channels share the cassette channel's defining properties:
- **Wideband Doppler:** vessel motion at 0.5–10 knots → 0.03–0.7% Doppler (same order as our 0.41% flutter)
- **Delay spread:** multipath reflections from sea surface and bottom → 5–50 ms (similar to our 8 ms reverb)
- **Audio-frequency band:** 1–50 kHz carrier frequencies → similar DSP complexity

UWA OFDM is a rich research field. The canonical receiver (Stojanovic/Freitag/Preisig, 2006–2010) is a two-stage pipeline that handles wideband Doppler exactly as we need for cassette flutter.

**Sources:** [PMC: Symbol-by-Symbol Doppler Compensation](https://pmc.ncbi.nlm.nih.gov/articles/PMC4789520/) · [PMC: Time-Varying Filter for Doppler](https://pmc.ncbi.nlm.nih.gov/articles/PMC6339152/) · [CMU DSP Workshop paper](http://users.ece.cmu.edu/~crberger/09_01_DSPworkshop.pdf)

---

### 2.2 The Standard Two-Stage UWA Receiver Chain

The canonical receive pipeline (directly applicable to cassette flutter compensation):

**Stage 1 — Bulk Doppler resampling (coarse):**
1. Detect the wideband Doppler scale factor `a` (= v/c for acoustics; = flutter deviation for cassette) by correlating known preamble/postamble chirps or by tracking pilot tone phase over many symbols.
2. Resample the entire received block at rate `1/(1+a)` using a polyphase interpolator. This converts the "wideband Doppler" (all frequencies scaled by the same factor) to a narrow residual CFO.
3. After resampling, the channel looks like a static multipath channel with a small residual frequency offset.

**Stage 2 — Residual CFO from null subcarriers (fine):**
1. In the OFDM grid, designate a set of subcarriers as null (zero-power, known to receiver). After FFT, any energy on a null subcarrier is directly proportional to the residual CFO.
2. Minimize null-carrier leakage energy: this gives a CFO estimate accurate to ~1% of subcarrier spacing.
3. Apply a phase rotation per sample before the FFT (or per-subcarrier derotation after) to zero the residual.

**Per-symbol pilot phase tracking (Stage 3, optional):**
After stages 1 and 2, residual time-varying phase noise (residual flutter) is tracked by comparing pilot subcarrier phases symbol-to-symbol. This is exactly what our current DQPSK master8 pilot does (EMA α=0.5 timing correction). UWA literature confirms: this is the correct approach, and an EMA is sufficient for slowly-varying Doppler.

**Reference parameters from PMC4789520 (acoustic OFDM at 24 kHz center):**
- FFT size N=1024, Δf=93.75 Hz (= 96 kHz/1024), symbol duration 10.67 ms
- Guard interval = 0.5 × T₀ = 5.33 ms (50% overhead!)
- Active subcarriers: 81 out of 1024
- Pilot pattern: continual pilots at indices {±6, ±12, ...} in every symbol (not scattered — every symbol gets pilots)
- Achieves 7.5 kbps in 10 kHz using 16-QAM + 64-QAM + turbo code r=1/2 and r=1/3

**Reference parameters from PMC6339152 (time-varying filter for Doppler):**
- Short-range config: N=512, Δf=37.1 Hz, GI=6.4 ms
- Long-range config: N=1024, Δf=19.5 Hz, GI=9 ms
- Doppler range: up to Mach factor giving 50% of Δf shift before ICI becomes severe
- Data rates: 2,328 bps raw, 776 bps coded (short range); 16 bps (long range extreme multipath)

---

### 2.3 Design Rules from UWA Literature

From the CMU DSP workshop paper (Berger et al., OFDM for UWA channels with Doppler spread):

**Rule 1 — Subcarrier spacing vs. Doppler spread:**
`Δf >> D_max` where `D_max` is the maximum Doppler spread.  
Recommended: `Δf ≥ 4 × D_max` to keep ICI below -20 dB.  
For cassette: flutter = 0.41% wrms at center freq 5 kHz → D_max ≈ 0.0041 × 5000 ≈ 20 Hz (peak, not RMS). So `Δf ≥ 4 × 20 = 80 Hz`.  
Current master8 has Δf = 750 Hz — this is 37× the Doppler spread. Very conservative; could narrow spacing to 80–150 Hz range and pack 5–8× more carriers into 10 kHz.

**Rule 2 — Guard interval vs. delay spread:**
`T_GI ≥ τ_max` where `τ_max` is the maximum delay spread.  
For cassette: reverb tail ~8 ms → `T_GI ≥ 8 ms`.  
At Δf=94 Hz: T_useful = 10.67 ms, T_symbol = 21.3 ms with 10 ms GI → 47% overhead.  
At Δf=46.88 Hz (DRM Mode B): T_useful = 21.33 ms, T_symbol = 26.66 ms with 10 ms GI → 37% overhead.

**Rule 3 — Pilot spacing in time:**
`T_pilot ≤ T_coherence / 2` where `T_coherence = 1 / D_max`.  
Flutter at 1–5 Hz rate → coherence time ~100–500 ms. So pilots every ~50–200 ms is sufficient.  
At 10.67 ms symbols, every 4–18 symbols. DRM's 4-symbol pilot grid is conservative but safe.

**Rule 4 — Pilot spacing in frequency:**
`Δf_pilot ≤ BW_coherence / 2` where `BW_coherence` = frequency coherence bandwidth = 1 / τ_max.  
τ_max = 8 ms → BW_coherence = 125 Hz.  
Pilot spacing ≤ 62.5 Hz → at Δf=46.88 Hz, pilots every ~1–2 subcarriers is needed.  
This is a tight constraint: with our current 750 Hz carrier spacing and 10 carriers, pilot-per-carrier is already implicitly satisfied because each carrier self-tracks via DQPSK.

---

### 2.4 Null-Subcarrier CFO Method (Direct Copy for master9)

In our channel, the bulk Doppler (flutter) is measured via chirp comparison (we already do this: the Schroeder sounder gives drift estimate). The **null-subcarrier CFO** method adds a complementary per-block residual correction:

1. Designate 2–4 subcarriers at the band edges (or between data blocks) as nulls — transmit zero.
2. After FFT, the energy `|Y[k_null]|²` is zero if CFO=0. The gradient `d(sum)/d(CFO)` gives the CFO estimate.
3. Newton step: `CFO_est = -sum(Y[k_null]×Y*[k_null-1]) / sum(|Y[k_null]|²)` (simplified form).
4. Correct the sample stream: multiply by `exp(-j × 2π × CFO_est × n / N)` before the next FFT.

Cost: 2–4 subcarriers out of, say, 80 = 2.5–5% overhead. Benefit: residual timing error reduced from ~few % of Δf to ~0.01% of Δf. This is beyond what our current EMA pilot achieves because it operates per-block rather than per-decision.

---

## 3. MT63, OLIVIA, Serial-Tone HF Modems (MIL-STD-188-110)

### 3.1 MT63

MT63 is a narrow-band OFDM mode invented by Pawel Jalocha (SP9VRC) for amateur HF. Key specs:
- **64 subcarriers** (BPSK per subcarrier), spread across 500, 1000, or 2000 Hz bandwidth
- **Symbol rate** per carrier: 5 baud (MT63-500), 10 baud (MT63-1000), 20 baud (MT63-2000)
- **Net throughput:** ~5 characters/sec = ~40–50 bps *payload* (with redundant coding), or ~100 bps uncoded. In MT63-2000: ~160 bps usable text.
- **Spectral efficiency:** 160 bps / 2000 Hz = **0.08 bits/s/Hz** — extremely poor by modern standards.
- **Multipath tolerance:** Guard interval is implicit; the very slow symbol rate (50 ms/symbol for MT63-1000) means multipath delay spread of 8 ms = 16% of symbol, which causes modest ISI.
- **Doppler tolerance:** 120 Hz mistuning tolerance — massive, because Δf = 1000 Hz / 64 = 15.6 Hz and the symbol period is long enough that Doppler causes negligible phase rotation.
- **Interleaving depth:** 3.2 to 12.8 seconds (long interleaver) — addresses burst errors, not useful for cassette.

**Relevance:** MT63's architecture (many BPSK subcarriers, very slow symbol rate) is the extreme opposite of efficiency — it achieves robustness by trading bandwidth for raw coding redundancy. Our cassette channel is far better than MT63's target; we do not want MT63's architecture. Its lesson: BPSK with heavy redundancy is always possible even on terrible channels, but it caps throughput at ~0.1 bits/s/Hz.

**Sources:** [MT63 Wikipedia](https://en.wikipedia.org/wiki/MT63) · [MT63 QSL page](https://www.qsl.net/ea3dlv/Info/mt63.htm) · [ARRL MT63](https://www.arrl.org/mt-63) · [NBEMS Digital Mode Comparison](https://www.jeffreykopcak.com/2017/07/26/digital-communications-in-amateur-radio-narrow-band-emergency-messaging-system-nbems/)

---

### 3.2 OLIVIA

OLIVIA (by Bartosz Wszolek SP5ELA) is an MFSK mode with forward error correction:
- **Architecture:** M tones (2, 4, 8, 16, 32, 64, 128, 256) across configurable bandwidth (125–2000 Hz)
- **Baud rate:** 31.25 baud (fixed); bandwidth divided by tone count gives tone spacing
- **Most common variant:** OLIVIA 8/500 = 8 tones, 500 Hz bandwidth, 62.5 Hz spacing
- **Net throughput:** ~40–50 bps of text (similar to MT63) — designed for near-zero-BER at very low SNR
- **Spectral efficiency:** ~0.08–0.1 bits/s/Hz — same order as MT63
- **FEC:** Walsh-Hadamard transform coding + convolutional code — rate ~1/4 to 1/8
- **Doppler tolerance:** Very good; the 31.25 baud rate means each tone lasts 32 ms, and mistuning of ±15 Hz shifts are tolerated.

**Relevance:** OLIVIA and MT63 represent the *robustness extreme* of HF modem design — they work below the noise floor but achieve almost no throughput. They confirm that on a 10 kHz channel with 38 dB SNR, we can do far better (they'd be appropriate at ~0 dB SNR, not 38 dB).

**Sources:** [NBEMS OLIVIA Configuration](http://mail.w1hkj.com/FldigiHelp/olivia_configuration_page.html) · [OLIVIA description SP5ELA](https://www.qsl.net/aa3eu/oliviamixw.htm)

---

### 3.3 MIL-STD-188-110: Single-Carrier Serial-Tone PSK

MIL-STD-188-110 defines the US military HF modem standard. The "serial tone" (ST) waveform is the baseline:

**Architecture:** Single carrier PSK at 1800 Hz, 2400 symbols/second (fixed), 3 kHz bandwidth.

**Data rates and modulation:**
| Rate (bps) | Modulation | Bits/symbol |
|-----------|-----------|-------------|
| 75–600    | BPSK      | 1           |
| 1200      | QPSK      | 2           |
| 2400      | 8-PSK     | 3           |
| 4800      | 8-PSK (×2 rate) | 3 |

**Adaptive DFE equalizer:**
- 20 feedforward + 20 feedback taps, RLS algorithm
- Designed to handle the Watterson HF channel (deep spectral nulls from 2-path Rayleigh fading)
- Converges in ~30 ms using a known training preamble
- Spectral efficiency at 4800 bps in 3 kHz: **1.6 bits/s/Hz** (with RLS DFE, good multipath)

**MIL-STD-188-110B/C extensions:**
- Appendix D: wideband modes, 3–24 kHz bandwidth, up to 9600 bps in 3 kHz, up to ~38.4 kbps in 12 kHz
- These use an enhanced serial tone with higher QAM orders (16-QAM, 32-QAM) and a more aggressive adaptive equalizer.

**Is DFE relevant for cassette?**
The DFE architecture addresses *frequency-selective fading* (deep nulls from 2-path interference) rather than Doppler. Our cassette channel has frequency-selective fading from the deck's H(f) response (known, compensated at encode time using the params JSON) and from reverb-induced ISI. A DFE would work, but it requires a known training sequence at the start of every data block and a closed-loop adaptation — no feedback channel available at encode time. The OFDM approach with CP/ZP avoids needing a DFE entirely by converting ISI into per-subcarrier flat fading.

**Spectral efficiency comparison with cassette:**
- MIL-STD-188-110B: ~1.6 bits/s/Hz in 3 kHz at 4800 bps
- DRM Mode A 64-QAM: ~3.5 bits/s/Hz in 10 kHz
- Current master8 DQPSK: 934 bps / 10 kHz = **0.093 bits/s/Hz** (only 10 carriers!)
- Shannon bound at 38 dB SNR, 10 kHz: ~10 × log2(1 + 6310) ≈ 126 kbps = 12.6 bits/s/Hz

**Sources:** [MIL-STD-188-110 SigIDWiki](https://www.sigidwiki.com/wiki/MIL-STD-188-110_Serial) · [RapidM 110B](https://www.rapidm.com/standard/mil-std-188-110b/) · [MIL-STD Modem Primer](http://www.n2ckh.com/MARS_ALE_FORUM/MIL_STD_MODEM_PRIMER.pdf)

---

## 4. Cassette/Tape Data History

### 4.1 Kansas City Standard (KCS, 1975) and Variants

The KCS (also "Byte standard") was the first widely adopted microcomputer cassette standard, born from a 1975 Kansas City symposium (Byte magazine):

- **Encoding:** AFSK (audio FSK) — zero bit = 4 cycles of 1200 Hz; one bit = 8 cycles of 2400 Hz
- **Rate:** 300 baud = ~27 bytes/second net (with 11-bit framing: start + 8 data + 2 stop)
- **Bandwidth used:** ~1200–2400 Hz (very conservative)
- **Physical tape:** standard cassette at 4.76 cm/s

**Variants and rate progression:**

| Standard | Year | Encoding | Baud | Net bps (approx) | Frequencies |
|----------|------|----------|------|-----------------|-------------|
| KCS/CUTS-300 | 1975 | AFSK | 300 | 273 | 1200/2400 Hz |
| CUTS-1200 | 1977 | AFSK (reduced cycles) | 1200 | 873 | 1200/2400 Hz (1 or 2 cycles) |
| MSX-2400 | 1983 | AFSK | 2400 | ~1745 | 2400/4800 Hz |
| Quick CUTS | ~1980 | AFSK half-cycle | 2400 | ~2000 | 1200/2400 Hz (phase) |
| Tarbell | ~1977 | Manchester | 3000 bps | ~1500 | 1500 Hz biphase |

**Source:** [Kansas City Standard Wikipedia](https://en.wikipedia.org/wiki/Kansas_City_standard)

---

### 4.2 ZX Spectrum: ROM Loader and Turbo Loaders

The ZX Spectrum (1982) used a hardware comparator on the cassette input that generated digital pulses from tape audio, which the CPU measured in T-states:

**Standard ROM loader:**
- Encoding: **pulse width modulation (PWM)** — zero = ~489 µs full-cycle; one = ~977 µs full-cycle
- Rate for mixed data: ~1364 baud ≈ **1364 bps** (170 bytes/sec)
- Rate for all-zeros: 2046 baud; all-ones: 1023 baud
- Frequency range: ~1000–2000 Hz

**Turbo loaders:**
- Simple speedups (e.g., "Turbo 3000"): halve the timing counters → **3000 baud** ≈ 375 bytes/sec
- Speedlock and similar commercial: 3000–4000 baud; frequencies up to ~4 kHz

**DeciLoad (modern, 2023):**
- Encoding: **8b/10b line coding** instead of PWM — converts 8-bit bytes to 10-bit balanced symbols, eliminating DC component and enabling self-clocking
- Baud rates: **8102, 10417, 11513, 12868, 16827 baud** (five options)
- At 8102 baud with 8b/10b: net data rate = 8102 × (8/10) = **6482 bps** = 810 bytes/sec
- At 16827 baud: net ~**13462 bps** = 1683 bytes/sec
- No error correction — suitable for known-good media (no tape flutter correction)
- Receiver: edge-timing monitor with adaptive PLL tracking tape speed variation
- Signal frequency: "no significant content above half the baud rate" → at 16827 baud, top frequency ~8 kHz

**Source:** [Spectrum tape interface SinclairWiki](https://sinclair.wiki.zxnet.co.uk/wiki/Spectrum_tape_interface) · [DeciLoad GitHub](https://github.com/ZXnutronic/DeciLoad) · [ZX Spectrum loading analysis - Shredzone](https://shred.zone/cilla/story/440/spectrum-loading.html)

---

### 4.3 Commodore 64 Datasette and Fastloaders

The Commodore 64 (1982) used a 9-pin port connected to a proprietary Datasette unit.

**Standard ROM:** 300 baud, FSK-based → **300 bps** (very slow, saved twice for redundancy)

**Commercial fastloaders:**
- Turbo Tape 64: ~**3000 bps** (×10 speedup, ~375 bytes/sec)
- INPUT64 Supertape: **3600 baud** standard, **7200 baud** high-speed mode (noted as "too fast for ordinary datasette")
- Fast Evil (Evil Dead loader): 240 CPU cycle threshold → ~**4100 bps** fastest commercial loader
- Typical range: 2000–4000 bps for robust commercial loaders; 7200 baud at the hardware limit

**Techniques:**
- All used PWM encoding (pulse width measuring, same as Spectrum)
- Speed improvement came from tighter timing loops in Z80/6510 code, not from new modulation schemes
- Physical limit was the Datasette's cassette head bandwidth (~8–10 kHz usable) and mechanical flutter

**Source:** [C64-Wiki Datassette](https://www.c64-wiki.com/wiki/Datassette_Encoding) · [Lemon64: Turbo Tape speed](https://www.lemon64.com/forum/viewtopic.php?t=54041) · [Retro Computing Forum: 475 bytes/sec](https://retrocomputingforum.com/t/c64-turbo-tape-rate-of-475-bytes-sec-1-6mb-on-a-60min-tape/2090)

---

### 4.4 Tape Physics: What the Medium Supports

**Head gap and maximum frequency:**
The theoretical maximum recording frequency at 4.76 cm/s is governed by the head gap width. A 2 µm gap gives λ_min = 4 µm, corresponding to f_max = v / λ = 47.6 mm/s / 4 µm ≈ **11,900 Hz** (≈12 kHz). This matches the practical observation that Type I cassette frequency response is -3 dB at ~10–12 kHz.

**SNR:**
- Type I (ferric) cassette: typically 50–56 dB SNR weighted (Dolby OFF), 44–50 dB unweighted
- Our measured channel: noise floor -55.6 dBFS, signal near -17 dBFS → **~38 dB SNR** (consistent with IEC measurements)

**Wow & Flutter:**
- Consumer cassette deck spec: 0.08–0.2% wrms (EIAJ/IEC weighted)
- Our measured: 0.41% wrms (somewhat above spec, typical for a non-audiophile deck)
- 0.41% wrms at, say, 5 kHz center → instantaneous Doppler shift ≈ ±0.41% × 5000 Hz = ±20 Hz peak, ~3 Hz RMS

**Shannon capacity of the channel:**
Using C = B × log₂(1 + SNR):
- B = 10,000 Hz, SNR = 6310 (38 dB) → **C ≈ 126 kbps** (hard theoretical ceiling)
- Current master8 achieves 934 bps = **0.74% of Shannon capacity**
- At 38 dB SNR and 10 kHz, 16-QAM (4 bits/symbol) requires ~14 dB SNR per carrier → ample margin
- 64-QAM (6 bits/symbol) requires ~22 dB → feasible if per-carrier SNR ≥ 22 dB
- 256-QAM (8 bits/symbol) requires ~28 dB → tight but possible at median carrier SNR

**Source:** [Audio Cassette Tape Wikipedia](https://en.wikipedia.org/wiki/Cassette_tape) · [HN thread: cassette channel capacity](https://news.ycombinator.com/item?id=28962169) · [Audio tape specs Wikipedia](https://en.wikipedia.org/wiki/Audio_tape_specifications)

---

### 4.5 Higher-Rate Cassette Attempts: 3600+ bps

Documented rates exceeding 2400 bps on standard cassette hardware:

| System | Rate | Encoding | Notes |
|--------|------|----------|-------|
| INPUT64 Supertape | 7200 baud | PWM | Documented as "too fast for ordinary datasette" |
| DeciLoad 16827 | ~13.5 kbps net | 8b/10b self-clocking | Requires clean media, no RS correction |
| ZX Spectrum turbo loaders | 3000–4000 baud | PWM | Widespread commercial use |
| Amstrad CPC turbo | 2000–4000 baud | PWM | CPC firmware has no speed limit |
| General statement | Max ~6000–8000 baud | PWM/8b10b | Above ~8 kHz, head bandwidth limits |

The key lesson from microcomputer cassette history: **the tape head bandwidth (not flutter) was the binding physical limit on speed.** PWM encodings push higher tones into the 4–8 kHz range, and head H(f) rolloff kills them above ~10 kHz. AFSK/FSK variants stayed in the 1–5 kHz band and never exceeded ~3 kbps. The only documented attempts to exceed ~4 kbps used PWM with narrow pulses (= wideband signal) and had reliability issues.

None of these systems used multi-carrier (OFDM) approaches — they were all single-bit-at-a-time serial decoders on limited CPUs. The entire ~126 kbps Shannon budget was wasted.

---

## 5. Synthesis: Flutter/Doppler Design Principles and master9 Recommendations

### 5.1 Unified Design Framework

Across all four channel families (DRM/HF, UWA acoustic, MT63/serial-tone HF, cassette tape history), a consistent set of design principles emerges for channels with flutter/Doppler:

**Principle 1 — Decouple Doppler and delay spread handling.**
Use cyclic prefix (or zero-padding) to handle delay spread/ISI independently of the Doppler tracker. The CP length sets the ISI-free zone; the Doppler tracker operates on residuals. Never try to absorb ISI into the timing tracker — the two impairments are orthogonal and should be handled separately.

**Principle 2 — Subcarrier spacing must exceed Doppler spread by 4–10×.**
For cassette (D_max ≈ 20 Hz peak Doppler at 5 kHz center): Δf ≥ 80–200 Hz. The current master8 Δf = 750 Hz is 37× — far more conservative than needed. Reducing to Δf = 94 Hz would allow 10 kHz / 94 Hz ≈ 106 active subcarriers vs. the current 10.

**Principle 3 — Guard interval must exceed reverb tail with margin.**
Reverb ~8 ms: CP should be ≥ 10 ms. At Δf = 94 Hz, T_useful = 10.67 ms, T_CP = 10 ms → T_symbol = 20.67 ms, overhead = 48%. This is expensive but ISI-free. Alternatively: Δf = 46.88 Hz (DRM Mode B): T_useful = 21.33 ms, T_CP = 10 ms → T_symbol = 31.33 ms, overhead = 32%.

**Principle 4 — Use scattered pilots at grid density matching coherence time and bandwidth.**
Flutter coherence time ~100–500 ms → pilot every 4–20 symbols (conservative: every 4).  
Reverb coherence bandwidth ~125 Hz → pilot every 1–2 subcarriers at 94 Hz spacing.  
Overhead for DRM-style pilot grid: ~15–20% of cells.

**Principle 5 — Self-tracking is mandatory (confirmed by master8 real-tape result).**
All fixed-grid decoders failed on real tape; only self-tracking decoders (pilot-driven timing) succeeded. The literature confirms: any system that relies on pre-estimated H(f) without per-block correction will diverge. The null-subcarrier CFO method from UWA acoustics adds another self-correction layer.

**Principle 6 — Differential encoding (DQPSK) provides phase-reference-free resilience.**
DRM uses coherent QAM with explicit channel estimation; UWA uses coherent OFDM with pilots; but for a low-overhead receiver, differential encoding (as in DQPSK) eliminates the need for absolute phase tracking at the cost of ~3 dB. At 38 dB SNR this is a cheap trade.

---

### 5.2 Concrete master9 Recommendations

**R5-REC-1: Add a cyclic prefix (CP) of 10–12 ms.**
The single most important change. Reverb tail = 8 ms → CP ≥ 10 ms eliminates ISI entirely. Cost: ~47% overhead on a 10.67 ms useful symbol. Mitigate this by increasing useful symbol length. With Δf = 46.88 Hz (Mode-B-style): T_useful = 21.33 ms, CP = 10 ms → 32% overhead → net symbol rate = 31.6 OFDM symbols/sec.

**R5-REC-2: Move from 10 to 60–100 subcarriers across 750–9000 Hz.**
Current: 10 carriers × 750 Hz spacing = 7500 Hz occupied. Proposed: 90 carriers × 94 Hz spacing, occupying 8460 Hz (750 Hz–9210 Hz). At 2 bits/carrier (QPSK): 90 × 2 × 31.6 = **5688 gross bps**. With 20% pilot overhead and rate-1/2 RS: ~2275 net bps. With 4 bits/carrier (16-QAM): ~4550 net bps. With 6 bits/carrier (64-QAM): ~6825 net bps.

**R5-REC-3: Add scattered pilots in 2D (time-frequency grid), not just a single mid-band pilot.**
Following DRM mode B pattern: pilots at every 4th symbol × every 5th subcarrier (at 94 Hz spacing: every 5 × 94 = 470 Hz). This provides continuous H(f) tracking across the full 10 kHz band, catching frequency-selective fading nulls that the current single-pilot approach misses. Pilot overhead: ~5% cells. Boost pilot amplitude by +3 dB (DRM practice).

**R5-REC-4: Implement null-subcarrier CFO correction per OFDM block (from UWA literature).**
Reserve 4 subcarriers as nulls (2 at each band edge). After FFT per block, minimize null-carrier leakage energy to get a per-block residual CFO estimate. Apply correction before the next block. Cost: 4/90 = 4.4% bandwidth. Benefit: eliminates residual timing error to <1% of Δf without decision-directed feedback.

**R5-REC-5: Consider differential encoding (DQPSK) per subcarrier across time (as now), OR switch to coherent QAM with pilot-based channel estimation.**
At 38 dB SNR, coherent 16-QAM (or 64-QAM) with DRM-style scattered pilot interpolation will give 2× or 3× the spectral efficiency of DQPSK QPSK. The pilot grid (Rec 3) provides the channel estimates. The trade-off: coherent decoding requires accurate H(f) estimation per subcarrier per symbol, adding implementation complexity. Start with DQPSK QPSK (safe, proven), then try coherent 16-QAM as a second variant.

**R5-REC-6: Do not use single-carrier serial-tone (DFE/equalizer) architecture.**
MIL-STD-188-110 serial tone achieves ~1.6 bits/s/Hz in a similar bandwidth, compared to DRM's 3.5 bits/s/Hz with multi-carrier. For our channel (38 dB SNR, 10 kHz) the spectral efficiency difference is 2×. OFDM with CP is clearly superior when the channel is linear and the delay spread is bounded.

**R5-REC-7: Do not model on MT63/OLIVIA.**
These are designed for SNR ≈ -10 to +10 dB; they achieve 0.08 bits/s/Hz. At 38 dB SNR we can do 50–100× better. They are instructive only as a lower bound.

**R5-REC-8: The cassette physics supports up to 12 kHz usable bandwidth; consider extending to 11 kHz.**
Current: 750–9000 Hz. The Schroeder sounder extends to 11 kHz; Type I tape supports 12 kHz at 4.76 cm/s. At Δf = 94 Hz, extending to 11 kHz adds ~(11000-9000)/94 ≈ 21 more subcarriers = +23% capacity. Worth including if H(f) at 9–11 kHz is not too attenuated.

---

### 5.3 Expected master9 Throughput (Projection)

Using R5-REC-1 through R5-REC-5, and extrapolating from the DRM spectral efficiency:

| Configuration | Carriers | Δf (Hz) | Modulation | Code rate | Gross bps | Overhead | Net bps |
|---------------|----------|---------|-----------|----------|-----------|----------|---------|
| Conservative (DQPSK) | 80 | 94 | QPSK (2b) | 1/2 | 4,800 | 30% CP + 15% pilot | ~2,900 |
| Moderate (DQPSK) | 80 | 94 | QPSK (2b) | 2/3 | 4,800 | same | ~3,900 |
| Aggressive (16-QAM) | 90 | 94 | 16-QAM (4b) | 2/3 | 10,800 | same | ~8,700 |
| Stretch (64-QAM) | 90 | 94 | 64-QAM (6b) | 1/2 | 8,100 | same | ~6,500 |

These projections assume the 38 dB SNR holds per carrier (it may not for 64-QAM at the band edges where H(f) rolls off). **The realistic near-term target for master9 is 3,000–5,000 net bps (3–5× the record), with 8,000+ bps plausible if 16-QAM per carrier works at median SNR.**

---

## 6. Source Summary

- [Wikipedia: Digital Radio Mondiale](https://en.wikipedia.org/wiki/Digital_Radio_Mondiale)
- [SigIDWiki: DRM](https://www.sigidwiki.com/wiki/Digital_Radio_Mondiale_(DRM))
- [AllSDR DRM deep-dive blog](https://allsdr.blogspot.com/2016/07/digital-radio-mondiale-drm.html)
- [DRM.org technology page](https://www.drm.org/about-drm/drm-technology/)
- [EasyDRF DazDSP page](https://dazdsp.org/tech/EasyDRF/)
- [EasyDRF GitHub](https://github.com/DazDSP/EasyDRF)
- [PMC4789520: Acoustic OFDM symbol-by-symbol Doppler compensation](https://pmc.ncbi.nlm.nih.gov/articles/PMC4789520/)
- [PMC6339152: Time-varying filter for Doppler in UWA OFDM](https://pmc.ncbi.nlm.nih.gov/articles/PMC6339152/)
- [CMU DSP Workshop: OFDM for UWA channels with Doppler spread](http://users.ece.cmu.edu/~crberger/09_01_DSPworkshop.pdf)
- [ResearchGate: Doppler estimation and compensation for UWA OFDM](https://www.researchgate.net/publication/252050122_Doppler_estimation_and_compensation_for_underwater_acoustic_OFDM_systems)
- [Wikipedia: MT63](https://en.wikipedia.org/wiki/MT63)
- [ARRL: MT-63](https://www.arrl.org/mt-63)
- [Fldigi: OLIVIA configuration](http://mail.w1hkj.com/FldigiHelp/olivia_configuration_page.html)
- [Jeffrey Kopcak: NBEMS digital mode comparison](https://www.jeffreykopcak.com/2017/07/26/digital-communications-in-amateur-radio-narrow-band-emergency-messaging-system-nbems/)
- [MIL-STD-188-110 SigIDWiki](https://www.sigidwiki.com/wiki/MIL-STD-188-110_Serial)
- [RapidM: MIL-STD-188-110B](https://www.rapidm.com/standard/mil-std-188-110b/)
- [MIL-STD Modem Primer](http://www.n2ckh.com/MARS_ALE_FORUM/MIL_STD_MODEM_PRIMER.pdf)
- [Wikipedia: Kansas City Standard](https://en.wikipedia.org/wiki/Kansas_City_standard)
- [Wikipedia: List of cassette tape data storage formats](https://en.wikipedia.org/wiki/List_of_cassette_tape_data_storage_formats)
- [Sinclair Wiki: Spectrum tape interface](https://sinclair.wiki.zxnet.co.uk/wiki/Spectrum_tape_interface)
- [Shredzone: ZX Spectrum loading analysis](https://shred.zone/cilla/story/440/spectrum-loading.html)
- [DeciLoad GitHub](https://github.com/ZXnutronic/DeciLoad)
- [C64-Wiki: Datassette Encoding](https://www.c64-wiki.com/wiki/Datassette_Encoding)
- [Retro Computing Forum: C64 Turbo Tape rate](https://retrocomputingforum.com/t/c64-turbo-tape-rate-of-475-bytes-sec-1-6mb-on-a-60min-tape/2090)
- [Lemon64: Fastest tape loader](https://www.lemon64.com/forum/viewtopic.php?t=61968)
- [Wikipedia: Cassette tape](https://en.wikipedia.org/wiki/Cassette_tape)
- [Wikipedia: Audio tape specifications](https://en.wikipedia.org/wiki/Audio_tape_specifications)
- [HN thread: maximum audio cassette bitrate](https://news.ycombinator.com/item?id=28962169)
