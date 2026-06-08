# tape_v2 analysis — `voicememo_trim`

- Recovered global clock (speed): **1.0087x** (offset +0.87%)
- Chirp spacing: measured 48247919 vs expected 47829873 samples
- Sounder SNR(f): median 13.7 dB, p10 7.0 dB, frac<8dB 19%
- Flutter (steady tone): 74.87% WRMS
- Noise floor: -22.5 dBFS

| Config | Reps | Passes | Passrate | Gross bps | Net bytes | Raw BER | Proj net bps | Proj P_full | FEC OK |
|---|---|---|---|---|---|---|---|---|---|
| mfsk32 | 89 | 0 | 0.00 | 1037 | 0 | 0.5628 | 49 | 0.00 | no |
| c1_gray_m16 | 88 | 0 | 0.00 | 1138 | 0 | 0.5904 | 54 | 0.00 | no |
| c2_m32_k2 | 88 | 0 | 0.00 | 1392 | 0 | 0.5538 | 66 | 0.00 | no |
| c2_m32_k4 | 88 | 0 | 0.00 | 1896 | 0 | 0.5391 | 90 | 0.00 | no |
| c2_m48_k6 | 88 | 0 | 0.00 | 1905 | 0 | 0.5571 | 91 | 0.00 | no |
| c4_bpsk | 88 | 0 | 0.00 | 529 | 0 | 0.7003 | 25 | 0.00 | no |
| c4_qpsk | 88 | 0 | 0.00 | 2133 | 0 | 0.5793 | 102 | 0.00 | no |
| c4_realmodel | 89 | 0 | 0.00 | 418 | 0 | 0.7285 | 20 | 0.00 | no |
| c4_simloaded | 88 | 0 | 0.00 | 1953 | 0 | 0.5622 | 93 | 0.00 | no |

**Reliable frontier (passrate=1.0):** none
**Frontier (passrate>=0.8):** none
**FEC-recoverable (P_full>=0.95) configs:** none
