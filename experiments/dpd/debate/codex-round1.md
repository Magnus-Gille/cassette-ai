# Codex round 1: skeptical case against DPD/adaptive-RX as the primary avenue

## Verdict

The receiver-side erasure result is real, useful, and non-circular. It is not,
however, evidence that "DPD-inspired channel modeling" is the most fruitful path to
higher reliable bitrate.

The strongest counter-case is this: the measured channel is not mainly an
unknown-channel-estimation problem. It is a waveform/coding mismatch problem. The
current stack uses hard non-coherent OOK, all-ON high-PAPR markers, carrier-major
bit mapping, and hard Reed-Solomon byte decoding over a sparse frequency-selective
null comb plus a -10.5 dB self-intermodulation floor. A smarter receiver can salvage
some near-misses, but it cannot recover information that the OOK waveform never
made distinguishable, and it does not fix the IMD/PAPR ceiling.

So: keep per-carrier reliability estimates, but demote the DPD framing. The
highest-ROI work is a capacity-oriented waveform and code: soft-decision FEC with
proper time/frequency interleaving, lower-PAPR coherent/differential modulation, and
OFDM-style pilots/CP if we stay multicarrier.

## Verified facts I am using

From `characterize.py` / `channel_summary.json`:

- 50 captured configs.
- Median per-carrier on/off SNR: 12.58 dB.
- SNR p10/p90: 7.71 / 15.67 dB.
- Carriers below 8 dB: 11.11%; below 5 dB: 5.56%.
- Median marker jitter: 6.52 ms, small versus 60-100 ms symbols.
- Median off-grid IMD/leakage floor: -10.49 dB.

From `RESULTS/tape_test/batch_results.json`:

- Flat production decode: 7/50 byte-exact.
- The flat passes max out at 333 gross bps.
- At gross >=400 bps: 0/29 flat configs pass.
- At gross >=467 bps: 0/16 flat configs pass.

From `offline_proof.py`:

- Channel-aware RS-erasure decode: 13/50 byte-exact.
- At gross >=400 bps: 4/29 pass.
- At gross >=467 bps: 2/16 pass.
- Still 0/4 at 480 bps, 0/4 at 533 bps, and 0/4 at 640 bps.

From `adaptive_decode.py`:

- Deployable decision-directed erasure decode: 12/50 byte-exact.
- At gross >=400 bps: 3/29 pass.
- At gross >=467 bps: 1/16 pass.
- It also finds one RS-accepted wrong decode, so CRC is mandatory.

From `selftest_adaptive.py` as run now:

- The from-scratch preamble/wow modem is not byte-exact.
- It measures marker wow as 27.96%, flags no dead carriers, and returns no payload.
- That is not a minor productization issue. It is a control-plane failure in the
  exact sync/training mechanism the DPD/adaptive-RX proposal depends on.

## 1. Where DPD/adaptive-RX is dead-end or low-ROI

### A. It is not really DPD anymore

Classical DPD is transmit-side pre-inversion of a known-ish deterministic
nonlinearity. This product cannot pre-invert the room or speaker because the room
and speaker are unknown at playback. Once transmit-side predistortion is mostly
ruled out, the remaining idea is receiver-side reliability estimation.

That is useful, but it is coding-side channel-state information, not correction.
The receiver can say "this carrier is unreliable" and spend parity accordingly. It
cannot restore a carrier whose off-state is buried under self-generated IMD or room
leakage. Calling that DPD risks spending effort on a channel-modeling apparatus
when the practical gain comes from a much simpler thing: mark bad observations as
low-confidence and use a code that can exploit that confidence.

### B. The measured gain is config-yield, not a proven bitrate frontier

The headline 7 -> 13 is real, but it overstates bitrate progress.

Flat decode has no passes above 333 gross bps. Offline erasure creates only four
passes at >=400 gross bps out of 29 attempts, and only two at >=467 gross bps out
of 16. The deployable decision-directed version is thinner: three at >=400 and one
at >=467.

That is not yet a reliable-rate increase. It is salvage of a few near-misses. A
customer bitrate claim needs a new frontier such as "467 gross bps passes almost
always across repeated recordings/rooms." The current evidence says "some 400-467
gross frames were close enough that better erasure bookkeeping rescued them."

### C. RS-erasure capacity is naturally capped

With RS(48), a block can correct up to 24 unknown byte errors or 48 known byte
erasures. A bad carrier owns a contiguous run of codeword bits because of the
carrier-major mapping. For a typical 101 byte payload plus 48 parity bytes:

- K=24 gives about 149 / 24 = 6.2 codeword bytes per carrier.
- K=32 gives about 149 / 32 = 4.7 codeword bytes per carrier.
- The measured 11% null rate means roughly 2.6 bad carriers at K=24 or 3.5 at K=32.

That sounds erasure-friendly, and it explains the +6. But it also shows the ceiling.
At K=24, erasing eight carriers is about 50 bytes, already beyond RS(48)'s erasure
budget. At higher rates the problem is not only a few totally dead carriers; there
are residual hard-decision errors on the "not erased" carriers too. The offline
proof can erase the worst 1-4 carriers and rescue some frames, but it cannot fix
the many 480/533/640 bps failures because their error mass is no longer a small
set of isolated byte bursts.

### D. The Shannon/bit-loading number is an upper bound, not an implementation plan

Using the pooled measured SNRs and the stated 9 dB coding gap, I get:

- mean capacity: about 1.68 bits/carrier.
- median capacity: about 1.71 bits/carrier.
- carriers capable of >=2 bits/carrier: 32%.
- carriers capable of >=3 bits/carrier: 1.8%.
- carriers capable of >=4 bits/carrier: 0%.

So even before overhead, the practical constellation menu is mostly 0/1/2 bits, not
rich water-filling. A crude practical assignment of 0 bits on the 11% dead carriers,
2 bits on the 32% strong carriers, and 1 bit elsewhere gives about:

`0.11*0 + 0.32*2 + 0.57*1 = 1.21 bits/carrier`

That is a useful gain, but it is not a robust 1.8-1.9x deployed net-rate plan after
training, pilots, CRC, and stronger FEC. The 1.8-ish number is a capacity-flavored
upper bound for the measured detector-domain SNRs, not a reason to double down on
the current OOK/RS architecture.

### E. The new adaptive modem currently fails before the channel model matters

The from-scratch `adaptive_modem.py` path is in sync bring-up and fails its own
synthetic test. The failure mode is especially damaging to this proposal:

- measured wow: 27.96% despite a synthetic channel with only 0.4% wow and 0.15%
  flutter;
- dead carriers flagged: none;
- recovered payload: none.

If the training/control plane cannot reliably locate markers and measure a known
synthetic channel, the next dollars should not go into more elaborate DPD modeling.
They should go into a simpler, more standard modem structure where sync, pilots,
equalization, and soft decoding are first-class design elements.

## 2. The real bottleneck

The bottleneck is not raw average SNR. Median SNR is 12.6 dB, 89% of carriers are
above 8 dB, and marker jitter is only 6.5 ms against 60-100 ms symbols. That is
enough channel for a better low-order modem.

The bottleneck is also not "the null comb" alone. The null comb is the trigger, but
if nulls were the whole story, erasing the worst carriers would recover most
high-rate configs. It does not: offline erasure still leaves 25/29 configs at
>=400 gross bps failed, and all 480/533/640 bps configs failed.

The real bottleneck is the combination of:

1. hard non-coherent OOK amplitude decisions;
2. carrier-major byte bursts into a hard RS decoder;
3. sparse frequency-selective nulls;
4. a -10.5 dB PAPR-driven IMD/leakage floor;
5. an unfinished sync/training path for the proposed adaptive waveform.

That is a waveform/code bottleneck. The channel estimate is a supporting input, not
the main act.

The IMD number is the biggest warning. A -10.5 dB off-grid floor means the modem is
manufacturing a noise floor near the same scale as the SNR threshold it wants to
exploit. Receiver-side modeling cannot remove unknown intermod products once they
land in an OOK off bin. Reducing PAPR or using a waveform less dependent on
amplitude absence is likely higher ROI than estimating the existing broken
amplitude channel more precisely.

## 3. Cheaper or higher-ROI alternatives

### A. Soft-decision FEC plus real time/frequency interleaving

Replace hard RS byte correction as the primary code with a soft-decision LDPC,
polar, convolutional/Viterbi, or Raptor-style code over bit/channel LLRs. Use the
preamble or decision-directed estimate only to scale LLRs per carrier.

Why this is higher ROI:

- It uses all soft evidence, not just "erase these bytes."
- It handles partial fades and residual errors on non-erased carriers.
- It naturally subsumes erasure decoding: a dead carrier is just near-zero
  confidence.
- It breaks the current carrier-major burst pathology at the bit/code level.

Expected impact: a practical 2-4 dB coding gain versus hard RS is a more credible
route to making 400-533 gross bps reliable than more erasure heuristics. At the
same approximate code rate as RS48 on 101 byte payloads, this is plausibly a
1.3-1.8x reliable gross-rate improvement over the current 250-333 bps frontier.

### B. Fix the interleaver before modeling more channel

The current carrier-major layout intentionally concentrates each bad carrier into a
byte run. That makes the offline erasure proof easy, but it is a bad default if the
decoder is hard RS and the channel has multiple simultaneous notches.

A better design is a time/frequency interleaver matched to the FEC:

- for RS-like byte codes, distribute carrier damage across multiple independent
  code blocks or explicit erasure stripes;
- for bit-level soft codes, randomize across carrier and time so a null becomes
  low-confidence bits rather than a codeword-local byte burst;
- add CRC per block/frame so miscorrections are rejected.

Expected impact: this is cheap and should recover many 400 bps near-misses without
new modulation. It may not unlock 640 bps alone, but it attacks the actual failure
mechanism more directly than a DPD analogy.

### C. DBPSK/DQPSK or coherent per-carrier modulation instead of OOK

OOK is the wrong primitive for this channel because "absence of tone" is exactly
what IMD, leakage, room modes, and speaker nonlinearity corrupt. Differential phase
or coherent pilot-aided PSK keeps every carrier occupied and moves the decision away
from absolute amplitude thresholding.

Start with DBPSK per carrier:

- same 1 bit/carrier nominal payload as OOK;
- less vulnerable to gain normalization errors and off-bin leakage;
- compatible with per-carrier soft metrics;
- likely lower PAPR variability than all-ON/all-OFF OOK framing if phases are
  controlled.

If DBPSK makes K24/60 or K32/60 reliable, that is 400-533 gross bps before coding,
or roughly 1.6-2.1x the current 250 bps reliable low end. Then use DQPSK only on
the strongest carriers. Since only about 32% of measured carriers clear a
2-bit/carrier threshold under the 9 dB gap, mixed DBPSK/DQPSK is more defensible
than blanket 2-bit loading.

### D. Low-PAPR redesign to lift the IMD ceiling

The measured IMD/leakage floor is -10.5 dB. That is a system-created impairment.
Attack it at the transmitter/waveform:

- avoid all-ON multitone symbols;
- use Schroeder or optimized phases;
- add tone reservation or clipping control;
- lower record/playback drive if needed;
- prefer constant-envelope or near-constant-envelope signaling where possible.

This has leverage. The 2-bit/carrier threshold with a 9 dB gap is about 13.8 dB raw
SNR. Today only 32% of carriers exceed that. A 3 dB effective IMD/SNR improvement
would move the threshold to carriers currently above about 10.8 dB, likely around
two-thirds of the band. A 6 dB improvement would put nearly all carriers above the
present 8 dB floor into the 2-bit-capable region. That is a bigger ceiling move
than erasing a few null carriers.

### E. OFDM with CP, pilots, and soft QAM

If the team wants a multicarrier modem, build the standard one:

- cyclic prefix sized for acoustic multipath and tape timing smear;
- pilots for common phase/timing and per-subcarrier equalization;
- soft QAM/PSK demapping;
- bit-loading from pilot SNR;
- LDPC/polar/Raptor code over interleaved LLRs.

The overhead is real: maybe 10-20% CP plus 5-10% pilots. But that overhead buys a
decoder that can actually use the measured channel. The current OOK tone bank is
"OFDM-style" only in frequency placement; it does not get the main OFDM robustness
features.

Expected impact: if raw BER can be pushed below the low single-digit percent range,
rate-2/3 soft FEC at 533-800 gross bps is a more credible route to 350-550 reliable
net bps than trying to extend RS-erasure OOK.

## 4. Is the erasure win a ceiling or a floor?

It is a floor for "using reliability information helps." It is close to a ceiling
for the current OOK + carrier-major + hard RS architecture.

Why: the offline proof uses the same waveform, same hard OOK decisions, same parity,
and only changes erasure positions. That means it can only recover frames where the
dominant error was a small number of identifiable carrier byte bursts. It cannot:

- exploit graded soft information on every bit;
- fix wrong decisions on carriers that were not erased;
- reduce IMD/leakage;
- stabilize the new preamble/wow control path;
- create higher-order constellation distance.

A better waveform/code could make this entire erasure-specific line of work mostly
moot. In that design, the preamble still matters, but only as a normal pilot/LLR
calibration signal. The main gain would come from soft coding, interleaving, PAPR
control, and modulation choice, not from DPD-inspired "correction."

## 5. Single cheapest kill/de-risk experiment

Do a measured-channel codec bakeoff before recording any new adaptive waveform.

Use the existing real recording and `chan_lib.measure_frame()` to build a
detector-domain Monte Carlo harness from the actual per-carrier on/off energy
distributions. Then run 1000 randomized frames at the existing gross-rate points
400, 467, 533, and 640 bps through these decoders:

1. current hard OOK + RS48;
2. best possible RS-erasure receiver using the measured per-carrier reliability;
3. bit-interleaved soft-decision FEC using the same OOK energy samples and
   per-carrier LLR scaling;
4. optional practical 0/1/2 bit-loading constrained by the measured SNRs.

This costs code, not a new tape take, and it directly answers whether the erasure
receiver is the right hill to climb.

Kill criteria:

- If RS-erasure cannot reach at least 95% byte-exact at 467 gross bps in this
  favorable measured-channel harness, stop treating adaptive erasure as the primary
  bitrate avenue.
- If soft FEC/interleaving beats RS-erasure by at least 25% net bitrate at the same
  byte-exact target, make soft coding/waveform redesign primary and keep channel
  estimation only as LLR calibration.
- If RS-erasure is within 10% of the soft-code result and reaches >=95% at 467+
  gross bps, then the adaptive-RX avenue is de-risked enough to justify one real
  preamble-driven recording.

My prediction: RS-erasure will look like the existing proof, a useful salvage
mechanism around 400-467 bps but not a robust 2x path. Soft coding plus a lower-PAPR
or phase-based waveform will dominate once judged by reliable net bitrate rather
than count of rescued configs.
