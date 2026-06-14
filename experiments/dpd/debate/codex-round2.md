# Codex round 2: revised position after Claude's rebuttal

## Short answer

Claude changed my mind on two material points:

1. The detector-domain bakeoff I proposed is necessary but insufficient. It bakes
   in the old OOK waveform's IMD/leakage floor, so it cannot measure lower-PAPR
   masters, drive control, or DPSK.
2. A real PAPR/IMD A/B take should happen before a full soft-FEC rewrite. The
   possible ceiling move is too large and the experiment is too cheap to defer.

Claude also clarified something I should have said more cleanly: live per-carrier
CSI is not the enemy. The final stack almost certainly needs it. My objection is
to treating "DPD/adaptive erasure" as the primary bitrate mechanism. Correctly
scoped, the receiver should measure a small per-carrier reliability vector and use
it for LLR scaling, carrier disabling, and bit loading.

Where I still hold firm:

- The deployable erasure gain is a useful floor, not a reliable-rate frontier.
  Current evidence is 7/50 -> 12/50 total yield, but only 0/29 -> 3/29 at >=400
  gross bps and 0/16 -> 1/16 at >=467 gross bps.
- The current from-scratch `adaptive_modem.py` control plane is not reusable until
  proven. It still measures a synthetic 0.4% wow channel as 27.96%, flags no dead
  carriers, and recovers no payload.
- Lower PAPR on the current OOK/RS stack is a physics test and maybe a near-term
  boost, but not a final architecture. OOK tone absence and hard RS burst failure
  remain structural problems.

## Response to Claude's three pushbacks

### 1. "Bank the proven erasure gain"

Conceded, with a boundary.

The deployable decision-directed erasure decoder should be banked. It costs no new
recording, no extra parity, and no tape-master change. On the existing recording it
raises byte-exact yield from 7/50 to 12/50 and exposes a mandatory deployment bug:
RS success is not an acceptance criterion because one RS-accepted wrong decode was
observed. A payload CRC is non-negotiable.

But "bank it" means "make it the fallback floor for OOK tapes", not "make it the
bitrate plan." The high-rate counts are still sparse:

| Decoder | All configs | >=400 gross bps | >=467 gross bps | 480/533/640 gross bps |
|---|---:|---:|---:|---:|
| Flat OOK+RS | 7/50 | 0/29 | 0/16 | 0/12 |
| Deployable RS-erasure | 12/50 | 3/29 | 1/16 | 0/12 |
| Offline best erasure | 13/50 | 4/29 | 2/16 | 0/12 |

That is free reliability around the existing frontier. It is not evidence that
467+ gross bps is ready across 10 tapes and 10 uncontrolled rooms.

### 2. "Your preferred stack still needs the same live CSI"

Mostly conceded.

Soft LDPC or convolutional coding with per-carrier LLR scaling, carrier disabling,
and pilot-SNR bit loading all require live per-carrier CSI. In that narrow sense,
Claude is right: the erasure result is a degenerate proof that receiver CSI helps,
and the final plan promotes that CSI from "erase these byte spans" to "weight these
soft bits and allocate rate."

The remaining disagreement is scope and artifact reuse. The final receiver does
not need a room inverse, a DPD model, or the current broken adaptive modem. It needs
a robust training/control plane that measures detector-domain reliability:

- known ON and OFF evidence per carrier, because all-ON markers only measure gain;
- pilot or marker timing that does not turn 0.4% wow into 27.96%;
- CSI exported as SNR/LLR scale and usable-rate estimates, not as a correction
  filter pretending to undo an unknown room.

So yes: CSI survives. No: the present preamble/wow implementation has not earned a
place in the critical path.

### 3. "PAPR/IMD reduction is the cheapest big lever"

Conceded, and this changes my sequencing recommendation.

The measured IMD/off-grid floor is -10.49 dB. With the 9 dB implementation gap
used in round 1, the raw SNR threshold for 2 bits/carrier is:

`9 dB + 10*log10(3) = 13.77 dB`

On the pooled 1188 measured carriers:

| Effective SNR/IMD gain | 2-bit-capable carriers | 3-bit-capable carriers | Mean capacity estimate |
|---:|---:|---:|---:|
| 0 dB | 32.2% | 1.8% | 1.68 b/carrier |
| +3 dB | 71.3% | 23.7% | 2.40 b/carrier |
| +6 dB | 89.6% | 66.1% | 3.21 b/carrier |

Those are not product rates after pilots, CP, CRC, and FEC, but they show why the
IMD lever deserves an early physical A/B. A 3 dB waveform/level win can move more
carriers across the 2-bit threshold than a decoder rewrite can invent downstream.

Where I still disagree: lower-PAPR OOK+RS+bit-loading should not be assumed to be
the final stack. Reducing IMD helps everything, but OOK still makes "no tone" the
symbol most corrupted by leakage, and hard RS still fails on residual non-erased
errors. PAPR-first is a measurement and ceiling unlock, not a reason to postpone
soft decisions indefinitely.

## Corrected experiment plan

Yes, the bakeoff must be split.

### A. Old recording: fixed-IMD detector-domain bakeoff

Use the existing real recording and `chan_lib.measure_frame()` to estimate
per-carrier detector-domain distributions: `P(power | bit=1, carrier)` and
`P(power | bit=0, carrier)`, plus marker jitter and observed hard-decision errors.
Then run randomized frames at the existing gross-rate points: 400, 467, 533, and
640 bps.

This can test:

- current hard OOK + RS;
- deployable RS-erasure and genie/best RS-erasure;
- time/frequency bit interleavers under the same measured OOK detector statistics;
- soft OOK LLRs with per-carrier scaling;
- soft-FEC families at fixed impairment;
- 0/1 carrier disabling and rate allocation at fixed OOK evidence.

This cannot honestly test:

- lower-PAPR masters;
- removing all-ON markers;
- drive-level compression relief;
- DBPSK/DQPSK phase decisions;
- true 2-bit ASK/PSK constellation distance;
- CP/pilot changes that alter the waveform actually sent through tape/speaker/mic.

For those, the old OOK energy samples have already absorbed the old self-generated
leakage floor. Replaying them only asks "which decoder best survives this
impairment?", not "can we remove the impairment?"

Fixed-IMD kill/keep criteria:

- If RS-erasure cannot reach >=95% byte-exact at 467 gross bps in this favorable
  harness, stop treating erasure as the primary bitrate path.
- If soft LLR/FEC/interleaving beats RS-erasure by >=25% net reliable bitrate at
  the same byte-exact target, make soft coding primary and keep CSI only as LLR
  calibration.
- If soft FEC cannot beat erasure by at least 15% after overhead at fixed OOK
  impairment, do not spend a large rewrite on OOK-soft alone. Move waveform first.

### B. New recording: waveform/PAPR/IMD and DPSK tests

Make a physical A/B take. At minimum:

1. Current OOK master as control.
2. Low-PAPR OOK-compatible master:
   - Schroeder or optimized carrier phases;
   - no same-phase all-ON markers;
   - balanced ON/OFF training patterns;
   - record/playback drive sweep around the current usable level;
   - same carrier set, payload length, and gross-rate points as the control.
3. Optional next master: DBPSK per carrier, because OOK detector-domain replay
   cannot simulate phase decisions from amplitude-only observations.

Measure:

- PAPR/crest factor at the master;
- off-grid IMD/leakage floor in the recording;
- pooled per-carrier SNR p10/median/p90;
- fraction of carriers above 13.77 dB raw SNR;
- byte-exact pass counts at 400/467/533/640 gross bps;
- marker/preamble timing stability.

Waveform keep criteria:

- Keep low-PAPR/drive changes if off-grid floor improves by >=3 dB without losing
  more than about 1 dB median on/off SNR, and if 400/467 gross pass counts improve
  in the same-room control.
- Treat +6 dB as a major ceiling unlock: it moves the measured 2-bit-capable
  carrier fraction from 32.2% to 89.6%.
- Kill PAPR-only as a major lever if the improvement is <2 dB, if sync gets worse,
  or if lower drive simply trades IMD for too much SNR loss.

DPSK needs its own recording because the old OOK capture contains no phase-symbol
evidence. It should not be judged from OOK power distributions.

## Sequencing adjudication

Recommended order:

1. **Ship/bank CRC-guarded RS-erasure now.** This is a hygiene/floor change, not a
   research bet. It gives 7/50 -> 12/50 yield on the existing take and prevents the
   known RS-miscorrection class from becoming an undetected product failure.
2. **Run the PAPR/IMD A/B physical take before a full soft-FEC rewrite.** Claude is
   right here. A one-session waveform/level experiment can test whether the
   -10.49 dB self-inflicted floor can be moved by 3-6 dB. If yes, it changes the
   capacity budget for every later decoder.
3. **Run the fixed-IMD codec bakeoff, but interpret it narrowly.** It is still the
   cheapest way to decide whether RS-erasure is capped and whether soft LLR/FEC is
   worth implementing. Ideally run it on both the old OOK take and any successful
   low-PAPR take.
4. **Replace the broken preamble/wow path with a minimal CSI pilot path.** Do not
   invest in more elaborate adaptive-modem modeling until the control plane can
   pass synthetic wow/null tests and replay the existing recording sanely.
5. **Then implement soft FEC/interleaving and DBPSK/DQPSK.** The full rewrite should
   consume the measured PAPR result and the codec bakeoff result rather than
   guessing around both.

Why this order: erasure+CRC is nearly free and fixes a real correctness bug; PAPR
can plausibly buy 3-6 dB at the source and move 2-bit-capable carriers from 32.2%
to 71.3-89.6%; soft FEC likely buys 2-4 dB but costs more and still inherits the
old IMD floor if done first. The right split is not "PAPR instead of soft FEC"; it
is "measure the waveform ceiling first, then write the soft decoder against the
right channel."

## Final verdict

Yes: correctly re-scoped as a live per-carrier CSI receiver feeding a lower-PAPR,
soft-coded, capacity-oriented waveform, this avenue is fruitful; OOK+RS erasure is
only the deployable salvage floor.

## Priority-ordered next steps

| Priority | What | Rough cost | Expected reliable-bitrate impact | Kill/keep criterion |
|---:|---|---:|---|---|
| 1 | Add payload CRC and make decision-directed RS-erasure the safe fallback for current OOK tapes. | 0.5 day | Yield on current take: 7/50 -> 12/50; >=400 gross: 0/29 -> 3/29; >=467 gross: 0/16 -> 1/16. Frontier still roughly 333-400 gross. | Keep if CRC rejects every RS-miscorrection and decoder is monotonic versus flat. Do not treat as primary bitrate path unless it reaches >=95% at 467 gross in the fixed-IMD harness. |
| 2 | Physical PAPR/drive A/B: current master vs Schroeder/optimized phases, no all-ON markers, balanced ON/OFF training, drive sweep. | 0.5-1 day plus 1-2 tape takes | If +3 dB effective gain: 2-bit-capable carriers 32.2% -> 71.3%, mean capacity 1.68 -> 2.40 b/carrier. If +6 dB: 89.6%, 3.21 b/carrier. Could move practical frontier toward 467-533 gross before the full rewrite. | Keep if off-grid IMD improves >=3 dB with <=1 dB median SNR loss and 400/467 pass counts improve. Kill as a major lever if <2 dB gain or sync/SNR worsens. |
| 3 | Fixed-IMD detector-domain bakeoff: hard RS, RS-erasure, soft OOK LLRs, interleavers, and soft FEC at 400/467/533/640. | 1-2 days code | No waveform gain, but should quantify whether soft FEC gives >=25% net reliable-rate improvement over erasure at the same byte-exact target. | Kill RS-erasure as primary if it misses >=95% byte-exact at 467. Keep soft-FEC path if it beats erasure by >=25% net, or at least >=15% after overhead. |
| 4 | Minimal live CSI preamble/pilot path, replacing the broken adaptive modem control plane. | 1-2 days | Direct rate impact is negative overhead, about 5-10%, but it enables 10-room adaptation, LLR scaling, and bit loading. | Keep if synthetic 0.4% wow is measured near truth, known notches are flagged, and existing-recording SNR ranks match detector errors. Kill/redo if it repeats the 27.96% wow failure. |
| 5 | Soft-decision FEC plus 2D time/frequency interleaving over per-carrier LLRs. | 2-4 days | Expected 2-4 dB coding gain over hard RS; plausible 1.3-1.8x reliable net-rate lift over the current 250-333 bps frontier, especially after PAPR cleanup. | Keep if it reaches >=95% byte-exact at >=467 gross in harness and repeated physical takes. Kill or simplify if overhead-adjusted gain is <15% over CRC+erasure. |
| 6 | DBPSK first, then bit-loaded DQPSK only on carriers whose live CSI supports it. | 3-5 days plus recordings | Removes OOK's "absence of tone" failure mode. DBPSK target: make 400-533 gross reliable at 1 bit/carrier. After +3 to +6 dB PAPR cleanup, selective 2-bit carriers become plausible. | Keep DBPSK if it beats low-PAPR OOK at 467/533 byte-exact. Keep DQPSK only where pilot SNR predicts and physical BER confirms enough margin. |
| 7 | Final 10-tape / 10-room validation at the chosen advertised rate. | 1-2 days after stack exists | No direct bitrate gain; this is the product truth test. It selects the highest byte-exact reliable rate. | Keep the rate only if all runs pass CRC byte-exact with no undetected errors. Any failure backs off one rate tier or increases redundancy. |
