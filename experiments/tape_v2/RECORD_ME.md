# Record this: `master2.wav` (16.65 min)

One file, the whole modem ladder, fully self-locating: two wide-band global chirps
(500–5000 Hz, 0.2 s) bracket everything, so the analyzer recovers the deck speed and
re-aligns automatically. Validated end-to-end: clean decode is 100% byte-exact, and the
analyzer survives a simulated 0.88x / worn channel (clock recovered to 0.00% error).

---

## How to record (one pass to tape)

1. **Write to tape.** Play `experiments/tape_v2/master2.wav` start-to-finish through the
   laptop → cassette deck, recording to tape in a single pass. Do not pause/seek.
2. **Read back the tape** using ONE of the two capture paths below.
3. **Leave ~1 s of silence** before the first chirp and after the last on BOTH ends —
   the chirps are the sync anchors; if they are clipped, global alignment fails.
4. Save the capture as WAV (or m4a) and run:
   `python3 experiments/tape_v2/analyze_master2.py <your_recording.wav>`
   → per-config pass-rate table + reliable frontier + fresh channel sounding,
   written to `experiments/tape_v2/results/`.

### Level SOP (carried over from the prior runs — do not skip)
- **Dolby NR OFF** at BOTH record and playback. (NR companding mangles the multitone/QAM.)
- **Record level ~7.0, NOT 8.5.** 8.5 saturates the tape and raises the intermodulation
  floor (~−10.5 dB measured) which is what kills the dense QAM carriers.
- **Readback speaker ~55** (acoustic path): loud but no clipping (rms ~0.04 target).
- One continuous take; the analyzer handles a steady speed offset in 0.80–1.10x.

---

## Two capture paths (record the SAME tape twice, or pick one)

### (i) ACOUSTIC loop — speaker → iPhone mic
The harsh real regime measured in `experiments/dpd/channel_model.json`:
**clock ~0.88x, flutter ~2.2%, per-carrier SNR median ~12.6 dB (p10 ~7.7 dB), ~11% of
carriers < 8 dB, real frequency-selective nulls, IMD floor ~−10.5 dB.**

- Setup: tape deck speaker → iPhone mic, ~speaker 55, ~1 s silence around the chirps.
- **Expected outcome:** only the ROBUST ladder rungs survive. In the simulated
  worn/0.88x stand-in, the frontier is the low-rate single-tone / k-of-2 / BPSK rungs;
  the aggressive `c2_m48_k6`, `c4_qpsk`, `c4_realmodel`, `c4_simloaded` rungs collapse on
  the null structure. Treat any robust-rung pass-rate ≥ 0.8 as the acoustic frontier.
- This path is the honest "can it survive a real living-room loop" test.

### (ii) ELECTRICAL line-in — 3.5 mm / USB interface (e.g. Behringer UCA222)
Much closer to the 42 dB-SNR simulation regime where the aggressive C2/C4 configs were
originally measured. A 3.5 mm cable is enough to WRITE to tape, but most laptops/phones
have **no line-in** (the combo jack is mic-only), so READING the tape electrically needs
a USB interface such as the **UCA222** (noted in `STATUS.md`).

- Setup: deck line-out → UCA222 line-in → USB → laptop; record at a healthy, non-clipping
  level. Dolby OFF both ends, ~1 s silence around the chirps.
- **Expected outcome:** the frontier should CLIMB well above the acoustic loop. In the
  clean (`normal`, 1.0x) simulation the full ladder decodes and the frontier reaches
  `c4_qpsk` (~2133 gross bps) at pass-rate ≥ 0.8, with `c2_m32_k2` (~1392 bps) perfect.
  On real line-in, expect the dense rungs to partially survive — this is exactly the
  sim→real **transfer test**.

---

## What's on the tape (16.65 min)

| Block | Time | What it tests |
|---|---|---|
| **Lead + up-chirp** | ~1.2 s | global sync anchor 0 (`tx_chirp0`) |
| **Channel sounder** | ~45 s | 2× 64-tone Schroeder multitone → H(f)+SNR(f); 12 s steady 3 kHz tone → wow/flutter + recovered clock; 3 s silence → noise floor |
| **Modem ladder** | ~15.7 min | 794 sections, 88–89 reps each, interleaved robust→aggressive: `mfsk32`, `c1_gray_m16`, `c2_m32_k2`, `c2_m32_k4`, `c2_m48_k6`, `c4_bpsk`, `c4_qpsk`, `c4_realmodel`, `c4_simloaded`. Each section is a short ~96-byte payload framed with CRC32 so drift stays small and the analyzer can score pass-rate per config. |
| **Down-chirp + tail** | ~1.2 s | global sync anchor 1 (`tx_chirp1`) — its spacing vs anchor 0 recovers the deck speed |

## Reality check (read this before celebrating the bps numbers)

The capacity campaign's headline rates — **C4 OFDM-QAM at 3.69 kbps and C2 k-of-M at
2.41 kbps net** — were measured **at 42 dB SNR in simulation**. The real acoustic loop is
~**30 dB noisier** (SNR median ~12.6 dB) with ~2.2% flutter and a 0.88x clock. So this
recording is the test of whether those numbers **transfer to physical tape**, not a
confirmation that they do. The ladder is deliberately ordered robust→aggressive precisely
so the recording reveals *where each method breaks* — "this config fails on real tape" is
a valid and valuable result.
