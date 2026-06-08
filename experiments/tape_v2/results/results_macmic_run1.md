# tape_v2 analysis — `macmic_run1`

- Recovered global clock (speed): **0.8020x** (offset -19.80%)
- Chirp spacing: measured 38360617 vs expected 47829873 samples
- Sounder SNR(f): median 9.5 dB, p10 6.4 dB, frac<8dB 28%
- Flutter (steady tone): 95.57% WRMS
- Noise floor: -29.6 dBFS

| Config | Reps | Passes | Passrate | Gross bps | Net bytes | Raw BER | Proj net bps | Proj P_full | FEC OK |
|---|---|---|---|---|---|---|---|---|---|
| mfsk32 | 89 | 0 | 0.00 | 1037 | 0 | 0.5943 | 49 | 0.00 | no |
| c1_gray_m16 | 88 | 0 | 0.00 | 1138 | 0 | 0.5361 | 54 | 0.00 | no |
| c2_m32_k2 | 88 | 0 | 0.00 | 1392 | 0 | 0.5534 | 66 | 0.00 | no |
| c2_m32_k4 | 88 | 0 | 0.00 | 1896 | 0 | 0.5312 | 90 | 0.00 | no |
| c2_m48_k6 | 88 | 0 | 0.00 | 1905 | 0 | 0.5437 | 91 | 0.00 | no |
| c4_bpsk | 88 | 0 | 0.00 | 529 | 0 | 0.7156 | 25 | 0.00 | no |
| c4_qpsk | 88 | 0 | 0.00 | 2133 | 0 | 0.5848 | 102 | 0.00 | no |
| c4_realmodel | 89 | 0 | 0.00 | 418 | 0 | 0.7149 | 20 | 0.00 | no |
| c4_simloaded | 88 | 0 | 0.00 | 1953 | 0 | 0.5928 | 93 | 0.00 | no |

**Reliable frontier (passrate=1.0):** none
**Frontier (passrate>=0.8):** none
**FEC-recoverable (P_full>=0.95) configs:** none
