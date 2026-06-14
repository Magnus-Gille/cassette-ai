# DPD / channel-modelling experiment — cassette → speaker → iPhone

**Thesis (Magnus):** like Digital Pre-Distortion in radio PAs, use a known test
sequence to model the full acoustic channel and correct for the lossy link.

**Verdict: SUPPORTED, with a precise mechanism.** The over-air loss is *not*
broadband noise — it is **structured and largely correctable**. A channel-aware
decoder recovered nearly 2× as many configs from the *existing* recording with no
re-record and no extra parity. Independently, the measured per-carrier SNR shows
**~1.8–1.9× throughput headroom** the current flat modem leaves on the table.

All work is isolated under `experiments/dpd/` and uses a *frozen* copy of the modem
(`modem_frozen.py`) so it is reproducible regardless of in-flight edits to
`scripts/acoustic_ofdm_modem.py`.

---

## What the recording actually is

`RESULTS/tape_test/batch_recorded.wav` — 415 s, 48 kHz mono, an iPhone capture of a
tape playback of 50 OFDM configs (K parallel OOK tones, 1.5–7 kHz, RS(48) coded).
Frame→config mapping verified via the `[NN]` payload prefix (`off0 = 3`; 7/50
byte-exact — matches `batch_results.json`).

## Method: measure the channel *in the detector's own domain*

Time-domain waveform correlation is meaningless here (the channel scrambles per-
frequency phase), and the modem already does crude per-carrier *magnitude*
equalisation (it normalises each tone to the all-ON marker gain). So a naïve
"invert H(f) at the receiver" buys nothing. Instead, for every config we
regenerate the **byte-exact** transmitted bits and measure, per subcarrier, the
on-symbol vs off-symbol energy — the quantity that actually decides each OOK bit.

## Findings (from the existing recording)

| Quantity | Value | Implication |
|---|---|---|
| Clock (phone/cassette) | **0.891 ± 0.003** (48/50 configs) | static offset, already resampled out — **not** the problem |
| Marker jitter | ~6.5 ms (≪ 60–100 ms symbol) | wow/flutter is mild here |
| Median per-carrier SNR | **12.6 dB** | healthy *on average* |
| Carriers < 8 dB SNR | **11 %** | a sparse comb of **deep frequency-selective nulls** |
| IMD / off-grid floor | **−10.5 dB** | moderate nonlinearity (PAPR-driven) caps SNR |

**The killer:** errors collapse onto a handful of null carriers (e.g. idx5 carrier
19 @ 3 dB → 19 bit-errors alone; idx6 carrier 11 @ 2 dB → 16). The modem's
**carrier-major interleave turns each null into a byte burst**, and a few
simultaneous bursts exhaust RS(48). See `channel_fingerprint.png`.

## Proof 1 — receiver-side, on existing data (non-circular)

A channel-aware decoder estimates per-carrier quality **blind** (received on/off
separability, no ground truth), flags the worst carriers as **erasures**, and uses
RS *erasure* decoding (corrects 2× as many erasures as errors):

```
baseline (flat decode, = modem):   7/50 byte-exact
channel-aware erasure decode:     13/50 byte-exact   (+6, ~1.9×)
```

`offline_proof.py`. Same soft energies, same parity — the only change is *using a
channel-quality estimate*. That directly demonstrates the thesis.

## Proof 2 — headroom the flat scheme wastes

Shannon on the measured per-carrier SNR (conservative 9 dB coding gap):

```
current scheme:   1.00 bit/carrier (OOK), on ALL carriers incl. dead ones
achievable:       ~1.90 bit/carrier (median)  ->  ~1.8× net throughput
```

i.e. ~30 % of the band can carry 2 bits/carrier today; the modem uses 1 everywhere.

---

## Use case changes the answer: 10 tapes → 10 uncontrolled rooms

The product records ~10 cassettes that play at customers' houses — **10 different,
uncontrolled channels**. That **rules out transmit-side pre-distortion** (you can't
bake in the inverse of a room you've never seen and that differs every time). The
intelligence must live in the **phone app**, adapting per playback. Split:

| | same on all tapes? | handles the 10 rooms? |
|---|---|---|
| fixed pre-emphasis (boost treble on master) | yes | only the universal cassette/speaker rolloff |
| **adaptive receiver** (measure live, erase dead carriers) | runs in the app | **yes — this is the core** |
| per-room pre-distortion | impossible here | — |

## Proof 3 — deployable adaptive decoder, on the existing recording

`adaptive_decode.py` — a **decision-directed** decoder: it bootstraps a per-carrier
reliability estimate from the received payload itself (no preamble overhead), then
escalates an erasure ladder and **accepts the first hypothesis that self-validates**
(RS-consistent; a payload CRC in production). Monotonic — it can never do worse than
flat:

```
flat baseline                : 7/50
adaptive (decision-directed) : 12/50   (+5, ~1.7x)  — no config broken
```

It also surfaced a real deployment bug: one weak-FEC config (RS8) **RS-mis-corrected**
(decoded to a valid-but-wrong codeword) — proving **you need a payload CRC** as the
acceptance test, not RS-success alone.

Side-finding that shapes the preamble design: the modem's all-ON marker symbols only
reveal each carrier's **gain**, which the modem already normalises out — so a
gain-based reliability metric is *useless* (erasing low-gain carriers made things
worse). What predicts errors is per-carrier **SNR** (signal vs noise/leakage). All-ON
markers can't see it; a real preamble must send known **ON and OFF** patterns.

## Proof 4 — preamble-driven adaptive modem, end-to-end (synthetic)

`preamble_proto.py` — the product architecture as a working prototype: every cassette
carries a short **training preamble** (alternating all-ON / all-OFF per carrier); the
phone syncs by **energy-envelope cross-correlation** (immune to the channel's phase
scrambling), measures per-carrier SNR live, erases the dead carriers, and RS-erasure-
decodes. Self-tested against an *unknown* synthetic channel with five deep nulls +
noise + compression:

```
preamble measured live -> flags exactly the 5 notched carriers
flat decoder            : FAIL
preamble-driven decoder : PASS (byte-exact)
```

It learns the channel from the preamble alone — nothing about the "room" is baked in.
(Scope note: this isolates null-correction; per-marker clock tracking for cassette
wow is the separate, already-solved piece proven on the real recording.)

## The forward half (fixed pre-emphasis) — optional, needs ONE new recording

The receiver-side proof is in hand. The *transmit*-side win — **pre-emphasis** (lift
the null carriers at TX) + **bit-loading** (skip dead carriers, 2-bit ASK on strong
ones) — is genuine DPD and can only be validated by recording a channel-shaped
master through the same link. Two artdefacts are ready:

- **`sounder_master.wav`** (54 s) — a proper channel sounder: dual-level Farina
  exponential sweeps (→ full H(f) magnitude **+ phase** and harmonic distortion /
  AM-AM compression), a low-PAPR 64-tone Schroeder probe (→ SNR(f) at the data
  operating point), a steady tone (→ wow/flutter), and a silence (→ noise floor).
- **`analyze_sounder.py`** — recovers all of the above + a ready-to-use
  `preemph_db` curve. **Self-tested** (`selftest_sounder.py`) against a synthetic
  channel with known nulls/compression/0.88× clock/noise: recovers clock to 4 dp,
  both nulls, and the lo-vs-hi compression. PASS.

**Next step:** record `sounder_master.wav` once through cassette→speaker→iPhone →
`analyze_sounder.py rec.wav` → build the pre-emphasised, bit-loaded payload → record
→ decode. Expected: byte-exact at ~1.8–2× the current net rate where the flat modem
fails.

## Files
```
modem_frozen.py        frozen modem (byte-exact reference, reproducibility)
chan_lib.py            segmentation, frame→config map, detector-domain measurement
offline_proof.py       Proof 1: channel-aware erasure decode (7→13 PASS)
characterize.py        channel fingerprint + channel_fingerprint.png + summary.json
make_sounder.py        generates sounder_master.wav (record this next)
analyze_sounder.py     sounder → channel_model.json (H, THD, SNR, flutter, preemph)
selftest_sounder.py    validates the sounder design on a synthetic channel
```
