# P23 wired bitrate hypothesis — simulator adjudication

**Date:** 2026-07-09  
**Scope:** simulator-supported recommendation for the electrical/UCA222 path;
not a new physical-tape record.

## Outcome

Use the existing D2X modem at its maximum legal grid width, **P23**, and keep
the tape-proven **RS(255,179)** code for the first physical test. This adds one
data carrier at 9375 Hz relative to the physical P22 record and two relative to
the portable/full-spectrum P21 profile, without introducing a new modulation
family or a thinner code than the physical P22 proof.

The rate is

```text
symbol rate = 48000 / 256 = 187.5 symbols/s
gross        = P × 2 bits × 187.5 = 375P bps
net/channel  = gross × rs_k / 255
```

For P23/RS179 this is **6054.4 bps/channel** and **12108.8 bps stereo**, a
**23.3%** increase over the current cross-deck P21/RS159 stereo profile
(9820.6 bps). At the repo's asymptotic post-RS convention, that raises a C90
from **6.63 MB to 8.17 MB**. The P23/RS207 stretch reaches 7001.5 bps/channel,
14002.9 stereo, or 9.45 MB/C90, but has materially less stress margin.

P23 is the present geometry ceiling: the full carrier comb reaches 9375 Hz.
P24 would reach 9750 Hz and violates the modem's 9500-Hz limit.

## End-to-end experiment

`experiments/tape_v2/exp_p23_wired_rs.py` runs the production codec rather than
only projecting closure from average BER:

1. RS encode with the selected `(255,k)` code.
2. Global column interleave using `m3_codec.encode_payload`.
3. Modulate every production-sized 510-byte frame with the real D2X TX.
4. Pass it through the repo's wired, wired-worn, and two stress channels.
5. Decode with the production Hann256/skip0 EMA receiver.
6. Deinterleave, Reed–Solomon decode, and compare the recovered payload hash.

The payload seed is `20260709`; channel seeds are `0..3`. Each configuration
therefore has 16 paired trials: four each at wired (50 dB/0.0465% flutter),
wired-worn (44 dB/0.093%), 38 dB/0.20%, and 32 dB/0.40%.

| Configuration | Net stereo | Wired | Wired-worn | 38 dB stress | 32 dB stress |
|---|---:|---:|---:|---:|---:|
| P21/drop-750 RS159 control | 9820.6 | 4/4 | 4/4 | 4/4 | 4/4 |
| **P23 RS179 recommended** | **12108.8** | **4/4** | **4/4** | **4/4** | **4/4** |
| P23 RS207 stretch | 14002.9 | 4/4 | 4/4 | 4/4 | **2/4** |

The recommended profile had zero codeword failures in all 16 trials. Its
maximum pre-FEC BER was 0.00241 at 38 dB and 0.01933 at 32 dB; the actual RS
decode still recovered the complete payload. The stretch profile's 32 dB
failures left 9 and 2 undecodable codewords, which is why it should remain a
test-ladder rung rather than the default.

Reproduce with:

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
  python3 experiments/tape_v2/exp_p23_wired_rs.py
```

Raw results: `experiments/tape_v2/results/p23_wired_rs_validation.json`.

## Honest storage accounting

The project's advertised `net_bps` is the steady-state PHY rate after RS. It
does not charge per-frame chirps, frame gaps, the global sounder, or end chirps.
With the experiment's short production-sized frames, the observed payload rate
excluding inter-frame gaps was 3239.9 bps/channel for the P21 control and
3903.3 for P23/RS179. That is still a 20.5% gain, but the absolute C90 capacity
would be lower than the asymptotic 8.17 MB until framing overhead is amortized.
Any product capacity claim must divide recovered information bits by the full
emitted master duration.

## What this does and does not prove

This is stronger than the older `dryrun_d2x_wired.py` result because it performs
real interleaving and RS decode. It is still a simulator result. The wired model
does not reproduce moving deck notches, magnetic saturation/IMD, azimuth error,
stereo crosstalk, dropouts, or whole-tape global-sync failure. It also cannot
turn the physical mono P22 record into a stereo P23 proof by arithmetic.

The next physical master should therefore contain, on **independent L/R
payloads**, the P21/RS159 control, P22/RS179 positive-control rung, P23/RS179
candidate, and P23/RS207 stretch. Success means byte- and hash-exact recovery
on both channels; P23/RS179 should become the high-capacity profile only after
that pass on at least the known-good deck and one additional deck.

## Research direction after P23

The grid is then full, so further gains require better detection/coding rather
than another carrier. The most relevant magnetic-recording work points to
pilot/all-carrier timebase resampling and PRML/NPML sequence detection for the
measured one-to-two-symbol echo memory. Those are follow-on hypotheses, not
part of the P23 claim. Useful primary references are Chen and Lee's
[pilot-phase-slope sampling-clock recovery](https://scholars.lib.ntu.edu.tw/bitstream/123456789/148944/1/01285934.pdf),
Czyzewski et al.'s [pilot-derived non-uniform resampling for analog-tape
wow](https://doi.org/10.1016/j.sigpro.2009.09.015), IBM's
[PRML magnetic-recording detector](https://doi.org/10.1109/49.124468), and its
[adaptive NPML tape detector](https://doi.org/10.1147/JRD.2010.2041034).
