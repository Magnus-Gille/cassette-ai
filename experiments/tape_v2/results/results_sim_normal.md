# tape_v2 analysis — `sim_normal`

- Recovered global clock (speed): **1.0000x** (offset +0.00%)
- Chirp spacing: measured 47829887 vs expected 47829873 samples
- Sounder SNR(f): median 56.6 dB, p10 51.4 dB, frac<8dB 0%
- Flutter (steady tone): 0.27% WRMS
- Noise floor: -50.6 dBFS

| Config | Reps | Passes | Passrate | Gross bps | Net bytes | Raw BER | Proj net bps | Proj P_full | FEC OK |
|---|---|---|---|---|---|---|---|---|---|
| mfsk32 | 89 | 89 | 1.00 | 1037 | 8544 | 0.0000 | 978 | 1.00 | YES |
| c1_gray_m16 | 88 | 86 | 0.98 | 1138 | 8256 | 0.0000 | 997 | 1.00 | YES |
| c2_m32_k2 | 88 | 88 | 1.00 | 1392 | 8448 | 0.0000 | 1312 | 1.00 | YES |
| c2_m32_k4 | 88 | 85 | 0.97 | 1896 | 8160 | 0.0007 | 1535 | 1.00 | YES |
| c2_m48_k6 | 88 | 85 | 0.97 | 1905 | 8160 | 0.0006 | 1542 | 1.00 | YES |
| c4_bpsk | 88 | 88 | 1.00 | 529 | 8448 | 0.0010 | 403 | 1.00 | YES |
| c4_qpsk | 88 | 81 | 0.92 | 2133 | 7776 | 0.0023 | 1625 | 1.00 | YES |
| c4_realmodel | 89 | 69 | 0.78 | 418 | 6624 | 0.0005 | 338 | 1.00 | YES |
| c4_simloaded | 88 | 84 | 0.95 | 1953 | 8064 | 0.0015 | 1488 | 1.00 | YES |

**Reliable frontier (passrate=1.0):** c2_m32_k2 @ 1392 gross bps
**Frontier (passrate>=0.8):** c4_qpsk @ 2133 gross bps
**FEC-recoverable (P_full>=0.95) configs:** mfsk32, c1_gray_m16, c2_m32_k2, c2_m32_k4, c2_m48_k6, c4_bpsk, c4_qpsk, c4_realmodel, c4_simloaded (best net bps: 1625 from c4_qpsk)
