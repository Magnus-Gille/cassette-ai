# tape_v2 analysis — `stereo_L`

- Recovered global clock (speed): **1.0018x** (offset +0.18%)
- Chirp spacing: measured 47913876 vs expected 47829873 samples
- Sounder SNR(f): median 40.1 dB, p10 31.6 dB, frac<8dB 0%
- Flutter (steady tone): 0.31% WRMS
- Noise floor: -50.5 dBFS

| Config | Reps | Passes | Passrate | Gross bps | Net bytes | Raw BER | Proj net bps | Proj P_full | FEC OK |
|---|---|---|---|---|---|---|---|---|---|
| mfsk32 | 89 | 75 | 0.84 | 1037 | 7200 | 0.0011 | 790 | 1.00 | YES |
| c1_gray_m16 | 88 | 87 | 0.99 | 1138 | 8352 | 0.0001 | 997 | 1.00 | YES |
| c2_m32_k2 | 88 | 88 | 1.00 | 1392 | 8448 | 0.0001 | 1219 | 1.00 | YES |
| c2_m32_k4 | 88 | 88 | 1.00 | 1896 | 8448 | 0.0013 | 1445 | 1.00 | YES |
| c2_m48_k6 | 88 | 87 | 0.99 | 1905 | 8352 | 0.0034 | 1270 | 1.00 | YES |
| c4_bpsk | 88 | 80 | 0.91 | 529 | 7680 | 0.0259 | 202 | 1.00 | YES |
| c4_qpsk | 88 | 1 | 0.01 | 2133 | 96 | 0.1071 | 102 | 0.00 | no |
| c4_realmodel | 89 | 61 | 0.69 | 418 | 5856 | 0.1654 | 20 | 0.00 | no |
| c4_simloaded | 88 | 43 | 0.49 | 1953 | 4128 | 0.0868 | 186 | 1.00 | YES |

**Reliable frontier (passrate=1.0):** c2_m32_k4 @ 1896 gross bps
**Frontier (passrate>=0.8):** c2_m48_k6 @ 1905 gross bps
**FEC-recoverable (P_full>=0.95) configs:** mfsk32, c1_gray_m16, c2_m32_k2, c2_m32_k4, c2_m48_k6, c4_bpsk, c4_simloaded (best net bps: 1445 from c2_m32_k4)
