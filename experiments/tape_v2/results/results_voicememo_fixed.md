# tape_v2 analysis — `voicememo_fixed`

- Recovered global clock (speed): **1.0001x** (offset +0.01%)
- Chirp spacing: measured 47834271 vs expected 47829873 samples
- Sounder SNR(f): median 39.1 dB, p10 31.8 dB, frac<8dB 0%
- Flutter (steady tone): 0.44% WRMS
- Noise floor: -57.9 dBFS

| Config | Reps | Passes | Passrate | Gross bps | Net bytes | Raw BER | Proj net bps | Proj P_full | FEC OK |
|---|---|---|---|---|---|---|---|---|---|
| mfsk32 | 89 | 0 | 0.00 | 1037 | 0 | 0.2453 | 49 | 0.00 | no |
| c1_gray_m16 | 88 | 0 | 0.00 | 1138 | 0 | 0.1749 | 54 | 0.00 | no |
| c2_m32_k2 | 88 | 0 | 0.00 | 1392 | 0 | 0.1164 | 66 | 0.00 | no |
| c2_m32_k4 | 88 | 0 | 0.00 | 1896 | 0 | 0.4014 | 90 | 0.00 | no |
| c2_m48_k6 | 88 | 0 | 0.00 | 1905 | 0 | 0.4504 | 91 | 0.00 | no |
| c4_bpsk | 88 | 0 | 0.00 | 529 | 0 | 0.3577 | 25 | 0.00 | no |
| c4_qpsk | 88 | 0 | 0.00 | 2133 | 0 | 0.4242 | 102 | 0.00 | no |
| c4_realmodel | 89 | 0 | 0.00 | 418 | 0 | 0.4665 | 20 | 0.00 | no |
| c4_simloaded | 88 | 0 | 0.00 | 1953 | 0 | 0.3439 | 93 | 0.00 | no |

**Reliable frontier (passrate=1.0):** none
**Frontier (passrate>=0.8):** none
**FEC-recoverable (P_full>=0.95) configs:** none
