# tape_v2 analysis — `sim_worn`

- Recovered global clock (speed): **0.8800x** (offset -12.00%)
- Chirp spacing: measured 42090247 vs expected 47829873 samples
- Sounder SNR(f): median 42.9 dB, p10 32.6 dB, frac<8dB 2%
- Flutter (steady tone): 0.53% WRMS
- Noise floor: -46.2 dBFS

| Config | Reps | Passes | Passrate | Gross bps | Net bytes | Raw BER | Proj net bps | Proj P_full | FEC OK |
|---|---|---|---|---|---|---|---|---|---|
| mfsk32 | 89 | 5 | 0.06 | 1037 | 480 | 0.0355 | 395 | 1.00 | YES |
| c1_gray_m16 | 88 | 33 | 0.38 | 1138 | 3168 | 0.0377 | 433 | 1.00 | YES |
| c2_m32_k2 | 88 | 51 | 0.58 | 1392 | 4896 | 0.0180 | 729 | 1.00 | YES |
| c2_m32_k4 | 88 | 13 | 0.15 | 1896 | 1248 | 0.0780 | 361 | 1.00 | YES |
| c2_m48_k6 | 88 | 1 | 0.01 | 1905 | 96 | 0.1507 | 91 | 0.00 | no |
| c4_bpsk | 88 | 47 | 0.53 | 529 | 4512 | 0.2237 | 25 | 0.00 | no |
| c4_qpsk | 88 | 0 | 0.00 | 2133 | 0 | 0.2641 | 102 | 0.00 | no |
| c4_realmodel | 89 | 0 | 0.00 | 418 | 0 | 0.2219 | 20 | 0.00 | no |
| c4_simloaded | 88 | 0 | 0.00 | 1953 | 0 | 0.2987 | 93 | 0.00 | no |

**Reliable frontier (passrate=1.0):** none
**Frontier (passrate>=0.8):** none
**FEC-recoverable (P_full>=0.95) configs:** mfsk32, c1_gray_m16, c2_m32_k2, c2_m32_k4 (best net bps: 729 from c2_m32_k2)
