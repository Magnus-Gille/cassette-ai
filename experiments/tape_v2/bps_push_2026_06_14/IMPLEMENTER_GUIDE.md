# Gauntlet Implementer Guide — build a candidate, screen it through the TRUSTED filter

You implement ONE candidate modem and screen it. The filter is calibrated and PROVEN to reproduce
the real-tape outcomes (see results/anchor_confirm.json: r8=5791 & r6=4910 backed; 6179 & 5247 killed).
**The reference to beat is r8 = 5921 model-net bps on the faithful tape10 replay.**

## The contract (do exactly this)

Create `experiments/tape_v2/bps_push_2026_06_14/candidates/<your_id>.py` exposing:

```python
def build():
    """Return a hyp_common.FuncScheme (name, gross_bps, modulate, demodulate)."""
```

- `modulate(bits: np.uint8[]) -> float32 audio @48k`, INCLUDING its own chirp preamble for sync.
- `demodulate(audio, sr) -> np.uint8[] bits`. Must self-sync from the preamble (NO oracle timing).
  Use `hyp_common.find_preamble` / `make_preamble` for sync (the proven chirp), same as the repo schemes.
- `gross_bps` = STEADY-STATE info bits/sec = (info bits per symbol) × (symbol rate). Per-frame preamble
  overhead is NOT subtracted here (that is the bulk-framing lever's job) — match the repo convention:
  r8 = 22 carriers × 2 bits × 187.5 sym/s = **8250 gross** (its model-net came out 5921, = the record).

## Mandatory self-check (RED/GREEN — do this BEFORE screening; a buggy demod gives a fake-good BER)

```python
import numpy as np, sys, pathlib
H = pathlib.Path("experiments/tape_v2/bps_push_2026_06_14/harness").resolve()
sys.path.insert(0, str(H))
from <your_id> import build
fs = build()
rng = np.random.default_rng(0); bits = rng.integers(0,2,4000,dtype=np.uint8)
audio = fs.modulate(bits)
rx = fs.demodulate(np.asarray(audio,np.float32), 48000)   # NO channel
ber = np.mean(bits[:len(rx)] != rx[:len(rx)])
assert ber < 1e-3, f"clean-channel BER {ber} — modulate/demodulate are not inverse; FIX before screening"
```
If clean-channel BER is not ~0, your modem is broken — fix it, do not screen it. Report honestly if you
cannot get it to invert.

## Screening (the trusted filter)

```python
import score
r = score.score_candidate(fs, channels=("replay_tape10",), also_simB=True, n_seeds=6, payload_bits=6000)
print(r["verdict"], r["worst_model_net_bps"], r["verdict_reason"])
```
- `worst_model_net_bps` = gross × k_max(ber)/255 where k_max corrects the expected byte-errors at the
  measured replay BER. **This is the number that matters.** Beat 5921 (the r8 reference) with margin.
- `also_simB=True` adds simB_master3 as a secondary, KNOWN-PESSIMISTIC check — do NOT fail a candidate
  on Sim B alone (it marks the proven r8 as failing). The replay BER is authoritative.
- verdict: GO (worst replay model_net > 5921), HEDGE (best > 5921 but not robust), NO.

## Reuse the proven DSP (do NOT reimplement sync/pilot/RS from scratch)

- Base multitone PHY: `experiments/tape_v2/h4_dqpsk.py` (`DQPSKScheme`: N=256, 375 Hz grid, pilot, skip,
  Schroeder TX, `modulate`, per-carrier differential demod, `bits_per_sym`, `gross_bps`). For higher-order
  or bit-loaded carriers, SUBCLASS this and override the per-carrier symbol map + the matching slicer.
- Dense2x family: `experiments/tape_v2/x10_b_aggr_05_dense2x_master.py` (`Dense2xScheme(P, skip)`,
  `Dense2xDropScheme(P, drop_freqs_hz)`) — the exact r8/r6 TX. `harness/evaluate.py:build_dense2x_candidate`
  shows how to wrap a (tx, rx) pair via `make_dqpsk_funcscheme` (this also exposes per-carrier margin, but
  margin is DQPSK-only and SECONDARY — the model_net/BER is primary; a plain FuncScheme with no margin is
  fine for non-DQPSK).
- Receiver front-end: `experiments/tape_v2/x9_resampling_pll.py` (`ResamplingPLLDemod`, pilot-phase EMA /
  resampling-PLL timing). Reuse its pilot de-rotation for differential carriers.
- Measured CSI for bit-loading / DAPSK ring design: `experiments/tape_v2/real_channel_params.json`
  (`Hf_magnitude.*` per-tone H(f) over 64 freqs, `snr_db_per_tone_*`, `spectral_contamination`). Also the
  replay channel measured it: `harness/_replay_cache/tape10_measure.json`.
- Channel for screening lives behind `score.score_candidate`; you do not call it directly.

## Differential is mandatory unless justified

The channel's per-tone phase drifts 69–78° over 4 s → absolute coherence is dead. Detect DIFFERENTIALLY
(symbol-to-symbol, 5.3 ms apart) like the proven DQPSK. Amplitude rings (DAPSK) are fine (use the pilot
magnitude as AGC). A single-carrier coherent PHY (moonshot) must carry its own carrier-tracking loop and
justify it; screen it the same way.

## Report back (your final message)

A compact JSON-ish block: `{id, file, gross_bps, clean_ber, replay_ber, simB_ber, worst_model_net_bps,
beats_5921, verdict, what_worked, what_to_fix, recommend_for_master}`. Be honest: if it under-performs,
say so — a clean NO is as valuable as a GO. Commit your candidate file on branch exp/bps-push-2026-06-14.
