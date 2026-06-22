# tape_v2 analysis — `stereo_R`

- Recovered global clock (speed): **1.0018x** (offset +0.18%)
- Chirp spacing: measured 47913880 vs expected 47829873 samples
- Sounder SNR(f): median 40.1 dB, p10 32.7 dB, frac<8dB 0%
- Flutter (steady tone): 0.31% WRMS
- Noise floor: -50.2 dBFS

| Config | Reps | Passes | Passrate | Gross bps | Net bytes | Raw BER | Proj net bps | Proj P_full | FEC OK |
|---|---|---|---|---|---|---|---|---|---|
| mfsk32 | 89 | 89 | 1.00 | 1037 | 8544 | 0.0000 | 978 | 1.00 | YES |
| c1_gray_m16 | 88 | 87 | 0.99 | 1138 | 8352 | 0.0001 | 921 | 1.00 | YES |
| c2_m32_k2 | 88 | 88 | 1.00 | 1392 | 8448 | 0.0000 | 1312 | 1.00 | YES |
| c2_m32_k4 | 88 | 88 | 1.00 | 1896 | 8448 | 0.0000 | 1788 | 1.00 | YES |
| c2_m48_k6 | 88 | 88 | 1.00 | 1905 | 8448 | 0.0001 | 1669 | 1.00 | YES |
| c4_bpsk | 88 | 82 | 0.93 | 529 | 7872 | 0.0030 | 403 | 1.00 | YES |
| c4_qpsk | 88 | 8 | 0.09 | 2133 | 768 | 0.0308 | 813 | 1.00 | YES |
| c4_realmodel | 89 | 69 | 0.78 | 418 | 6624 | 0.0468 | 119 | 1.00 | YES |
| c4_simloaded | 88 | 73 | 0.83 | 1953 | 7008 | 0.0535 | 558 | 1.00 | YES |

**Reliable frontier (passrate=1.0):** c2_m48_k6 @ 1905 gross bps
**Frontier (passrate>=0.8):** c4_simloaded @ 1953 gross bps
**FEC-recoverable (P_full>=0.95) configs:** mfsk32, c1_gray_m16, c2_m32_k2, c2_m32_k4, c2_m48_k6, c4_bpsk, c4_qpsk, c4_realmodel, c4_simloaded (best net bps: 1788 from c2_m32_k4)
