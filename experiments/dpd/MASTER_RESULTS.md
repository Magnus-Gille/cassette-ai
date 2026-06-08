# 15-min experiment master — results (recorded 2026-06-08)

Recording: `master_recorded.wav` (12.7 min capture of the cassette→speaker→iPhone link;
clock 0.889). One file, three experiments + full offline analysis. **No new recording
needed for anything below.**

## TL;DR
- The link is **excellent** (50 dB marker SNR, 13–17 dB per-carrier SNR, wow 0.19%). The
  earlier "bad decode" was entirely **cassette drift breaking frame location**, fixed by
  locating frames via their pilot markers (drift-immune) instead of a global clock.
- **Two free levers stack:** low-PAPR rendering (TX master, no cost) + channel-aware
  erasure decode (RX app, no re-record) take byte-exact yield **21/66 → 41/66 (≈2×)** and
  push a viable rate from **333 → 467 gross bps (9/11)**.
- The low-PAPR win comes from **cleaner all-ON markers** (sync/gain reference), *not* higher
  data SNR (phase-0 and low-PAPR have identical 13.0/12.9 dB per-carrier SNR).

## A. Channel model  (`channel_model_full.png`)
| Quantity | Value | Note |
|---|---|---|
| clock (phone/cassette) | 0.889 | stable |
| **drift vs linear clock** | **±0.65 s over 12.7 min** | > the 0.4 s frame lead → why global-clock slicing cut mid-tape frames |
| wow (short-term) | 0.19 % rms | mild |
| per-carrier SNR (64-tone) | median 17 dB | healthy across 1.5–7 kHz |
| marker SNR (OOK) | ~50 dB | pilots crystal-clear → robust frame location |
| THD (sweep) | −37 dB @ low drive → −31 dB @ high | **level-dependent compression** is real |
| H(f) | treble rolloff + nulls | pre-emphasis curve ±12 dB extracted |
| group delay | noisy/non-flat | coherent **DPSK would need equalization**, not drop-in |

## B. PAPR / IMD sweep — inconclusive at the IMD-floor level
Off-grid IMD floor ≈ −20…−24 dB across {in-phase, low-PAPR, random} × 4 drive levels, with
only ~2 dB spread and no consistent ordering. So low-PAPR's benefit does **not** show up as a
cleaner IMD floor here — it shows up in *decoding* (Block C). Honest null on the IMD metric.

## C. OOK reliability — byte-exact / 11 reps  (`deep_analysis.png`)
| Rate | Config | phase-0 base→+eras | low-PAPR base→+eras |
|---|---|---|---|
| 250 | K20/80 | 10→10 | 8→9 |
| 333 | K20/60 | 10→**11** | 10→**11** |
| 300 | K24/80 | 0→4 | 0→4 |
| 400 | K24/60 | 0→2 | 2→4 |
| 467 | K28/60 | 1→2 | **6→9** |
| 533 | K32/60 | 0→1 | 2→4 |
| **Total /66** | | **21 → 30** | **28 → 41** |

Findings:
1. **Reliable rate is gated by carrier count vs the null comb, not gross bps.** K20 (250/333)
   ≈ rock-solid; K24+ pack carriers into nulls → byte bursts (byteerr ~20, just over RS) →
   exactly what erasure rescues (300: 0→4, 400: 0→4 combined).
2. **Low-PAPR is a free TX win**, decisive where PAPR is worst (467 K28: 1→6 baseline; →9 with
   erasure). Mechanism = cleaner markers, not data SNR.
3. **Both levers compose:** low-PAPR + erasure = **41/66**, and makes **467 bps usable (9/11)** —
   up from a 333 bps frontier.

## D. Capacity headroom
Per-carrier SNR median ~13 dB → Shannon (9 dB gap) ≈ **1.79 bits/carrier** vs OOK's 1.0, with
only ~10% of carriers < 8 dB. So beyond the levers above there is still ~1.8× from
bit-loading / multi-level — consistent with the prior recording.

## What this implies (no new recording needed to act)
- **Ship now:** low-PAPR marker rendering on the master + CRC-guarded decision-directed
  erasure decode in the app. Frontier moves 333 → 467 gross bps at ~80% reliability.
- **Cheapest remaining build (offline):** soft-decision FEC / LLR bakeoff on the measured
  per-carrier energies (Codex's #3) — not yet run; it's a code build, not a measurement.
- **Needs a future recording:** DPSK (group delay is non-flat → needs equalization) and a
  true bit-loaded waveform.

## Files
```
deep_analysis.py / deep_results.json / deep_analysis.png   reliability frontier + erasure + SNR comb
channel_model.py / channel_model_full.{png,json}           H(f), phase, THD, SNR(f), wow, DRIFT, pre-emphasis
analyze_master.py / master_results.json                    raw per-rate pass table
make_master.py / master.wav / master_manifest.json         the recorded master + layout
```
