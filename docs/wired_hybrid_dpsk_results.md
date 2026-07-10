# Wired hybrid D8PSK rate push — adjudicated simulator result

**Date:** 2026-07-10  
**Scope:** UCA222-calibrated simulator result; physical P23/8-DPSK tape still
required.

## Outcome

The recommended next wired master is:

```text
P23 fixed grid, pilot at 4875 Hz
16 carriers: Gray differential 8-PSK (3 bits/symbol)
 7 carriers: Gray differential QPSK  (2 bits/symbol)
RS(255,155), global column interleave
62 bits/symbol × 187.5 symbols/s = 11625 gross bps/channel
11625 × 155/255 = 7066.18 net bps/channel
stereo = 14132.35 net bps
```

This is **16.7% above** the plain P23/RS179 simulator recommendation
(12108.82 stereo), **43.9% above** the current cross-deck physical P21/RS159
profile (9820.59 stereo), and projects **9.54 MB on a C90** under the repo's
steady-state post-RS convention.

The 16 promoted carriers, ranked from real wired phase tails, are:

```text
1125, 3375, 3750, 1875, 3000, 5250, 4125, 4500,
5625, 6000, 6375, 2250, 6750, 7125, 7500, 7875 Hz
```

The seven DQPSK carriers are 750, 1500, 2625, 8250, 8625, 9000, and 9375 Hz.
The unmeasured P23 edge carriers (750 and 9375 Hz) deliberately remain QPSK.

## Why this waveform

P23 fills the 375-Hz grid, so the next bits must come from constellation order,
coding, or overhead. Uniform 8-DPSK was not credible: the real phase tails are
strongly carrier-dependent. The experiment therefore reused the repo's
`DiffMultitoneScheme`, generalized it to P23, and promoted carriers in the order
measured on four long physical wired traces.

The key result is a coded-modulation trade rather than “more PSK everywhere.”
With RS179 the loading cliff was five promoted carriers. Broadening the 8-DPSK
set while strengthening RS moved the stable optimum to 16 carriers / RS155.
Eighteen carriers / RS151 was 79 bps stereo faster, but its peak-normalized
crest factor was 0.73 dB above plain P23 and reduced average drive by 0.53 dB.
The selected 16-carrier profile costs only 0.22 dB crest factor and 0.32 dB
average drive, a better physical-transfer trade.

## Real UCA222 calibration evidence

`exp_wired_constellation_audit.py` re-demodulates two real tape recordings,
both L and R, through the production Hann256/EMA receiver:

- `d2x_tape_20260622_144837.wav`
- `d2x_tape_indep_20260622_154412.wav`

That yields four signed residual matrices with 45879 symbols per carrier/trace.
The audit uses truth only for scoring after timing recovery and decision-directed
refinement. Contiguous circular bootstraps preserve carrier correlation and
time bursts. The raw residual cache is gitignored; its SHA-256 is stored in the
tracked JSON result.

The supposedly “not yet run” independent-payload capture is real and healthy:
it was re-decoded during this session against its separate L/R manifests, with
both channels byte-exact, 0/944 failed codewords, and zero payload BER. The old
STATUS entry saying that proof had not run was stale.

## Confirmation matrix

The final confirmation compares plain P23/RS179 with the hybrid candidate using
an 8192-byte deterministic payload, production RS encode/decode, production
global interleave, and 510-byte frames.

| Gate | Plain P23/RS179 | Hybrid P23 D8×16/RS155 |
|---|---:|---:|
| Wired 50 dB / 0.0465% flutter | 32/32 | **32/32** |
| Wired-worn 44 dB / 0.093% | 32/32 | **32/32** |
| Moderate stress 38 dB / 0.20% | 32/32 | **32/32** |
| Real-trace contiguous bootstraps | 64/64 | **64/64** |
| Extreme 32 dB / 0.40% | 18/32 | **13/32** |

The UCA-calibrated gate is therefore **160/160 byte- and hash-exact**, with zero
failed codewords. The 32-dB cell is explicitly not passed; importantly, the
plain P23 control also fails it. Yesterday's 4/4 harsh-cell pass was a small-seed
false positive, corrected by the 32-seed confirmation.

## Reproduction

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
  python3 experiments/tape_v2/exp_wired_constellation_audit.py

OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
  python3 experiments/tape_v2/exp_wired_hybrid_dpsk.py --confirm
```

Primary artifacts:

- `experiments/tape_v2/exp_wired_constellation_audit.py`
- `experiments/tape_v2/exp_wired_hybrid_dpsk.py`
- `experiments/tape_v2/results/wired_constellation_audit.json`
- `experiments/tape_v2/results/wired_hybrid_dpsk_papr_confirm.json`

The intermediate ladder, cliff, and coding-tradeoff JSONs remain as audit trail.

## Limits and next physical gate

This does not yet prove that midpoint 8-DPSK symbols survive magnetic recording.
The empirical simulator reuses residuals measured while QPSK was transmitted;
data-dependent echo, changed decision-directed tracking, saturation/IMD, moving
notches, and P23's two edge bins can still invalidate the transfer. The
parametric wired model is linear and cannot close those gaps.

Build one independent-L/R physical master containing:

1. P21/RS159 physical control.
2. Plain fixed-pilot P23/RS179 control.
3. Hybrid P23 D8×5/RS179 conservative rung.
4. Hybrid P23 D8×16/RS155 candidate.
5. Hybrid P23 D8×18/RS151 stretch.

Promote the 14.13-kbps profile only if both channel hashes are exact on the
known-good deck and a second working deck. Record level/PAPR must be graded by
the front sounder; use the existing Dolby-off, level≈7 SOP.

If higher-order phase transfer is the remaining limiter, the next receiver
experiments are multi-pilot phase-slope timebase correction and length-3
multiple-symbol differential detection, grounded in
[scattered-pilot sampling-clock recovery](https://scholars.lib.ntu.edu.tw/bitstream/123456789/148944/1/01285934.pdf)
and [MSDD](https://ntrs.nasa.gov/citations/19900046187).
