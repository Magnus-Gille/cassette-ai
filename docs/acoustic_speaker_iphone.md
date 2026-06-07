# Acoustic capture channel — speaker → room → iPhone

Empirical characterization of the **fallback capture path** discovered when the
digital line-in route turned out to be impossible on this hardware.

## Why this path exists

The MacBook Air's 3.5 mm jack is a **mic port only** (System Settings shows it
literally as "Microphone port") — there is no analog line-in. Feeding the deck's
line-level TRS output into it reads **exactly 0.000** (the TRS sleeve grounds the
combo jack's mic contact). So the tape **cannot be read back digitally** through
the laptop without a USB audio interface.

The only available capture device was the **iPhone Continuity-Camera mic**
("Magnus sidekick"). This doc characterizes whether that lossy acoustic path
(laptop speaker → ~0.3 m of quiet room → iPhone mic) can carry data at all.

## Method

`scripts/acoustic_rate_sweep.py` plays back-to-back segments of *alternating*
1200/2400 Hz tones at increasing symbol rates (silence-separated, one recording
covers every rate), then measures per rate — **without needing absolute sync**:

1. segment by RMS envelope,
2. estimate the true alternation period (FFT of `d(t)=(P2400-P1200)/(P2400+P1200)`)
   — this also recovers the capture clock ratio,
3. sample each symbol at its **center** (minimal ISI), phase- and rate-aligned,
   and compare to the known alternation → **accuracy (= 1 − BER)** and **eye**.

Run: `python3 scripts/acoustic_rate_sweep.py gen s.wav` → record with
`ffmpeg -f avfoundation -i ":<iphone>" -ac 1 -ar 48000 -t <dur> r.wav` (start mic,
wait ~2.5 s, then `afplay s.wav`) → `... analyze r.wav s.wav.json`.

## Results (quiet room, occasional car; output vol 75%)

**Frequency response** — fine. The channel passes ~400 Hz–10 kHz within ~11 dB,
peaking near 2 kHz. Both FSK tones come through and sit ~2 dB apart, so spectrally
there is no problem (1200 Hz: −12 dB, 2400 Hz: −10 dB rel peak).

**2-FSK accuracy vs symbol rate** (reproducible across two runs):

| baud | accuracy | eye | verdict |
|------|----------|-----|---------|
| 10   | 100 %    | 0.77 | clean |
| 20   | 100 %    | 0.74 | clean |
| 25   | 100 %    | 0.72 | clean |
| 33   | 100 %    | 0.78 | clean |
| 40   | 100 %    | 0.76 | clean |
| 50   | 99 %     | 0.74 | usable |
| 67   | 78 %     | 0.60 | **cliff** |

**Capture clock offset:** a sent symbol of length `T` appears as **≈0.88·T** in the
48 kHz-labelled iPhone recording — a stable ~12 % clock error across all rates and
both runs. Any real acoustic modem **must** correct this; the existing CAS3
robust front-end only searches ±6 % tape speed, so it would need widening.

## Verdict

- The acoustic speaker→iPhone path **works**, but only for a **slow** modem:
  reliable to ~50 baud, clean with margin ≤40 baud, hard cliff ~60–67 baud
  (reverb/ISI — `rt60≈0.25 s` smears fast symbols).
- The production CAS3 codec is **1200 baud → ~24× too fast** for this path. That is
  why the direct end-to-end BFSK decode of the speaker-recorded signal failed
  (`bad_magic`, est. SNR ~5 dB) even with **no tape in the loop**.
- Practical implication: to read tape back on this laptop, either (a) get a USB
  line-in interface (clean, full-rate, recommended), or (b) build a ~40 baud FSK
  modem + ~12 % clock correction and accept ~5 bytes/s over the air.

Raw data: `RESULTS/data/acoustic_speaker_iphone.json` ·
plot: `RESULTS/plots/acoustic_speaker_iphone.png`.
