# X12 BULK-FRAMING PRE-REGISTRATION (FROZEN 2026-06-12, before any experiment)

Campaign: **x12-bulk-framing** — design + gate a bulk frame format for the two
PROVEN configs (2572 N512 + 4910 d2x), per the x12 working brief. This file is
frozen BEFORE the first build/selfcheck/dress/ablation run it adjudicates.
Implementation: `experiments/tape_v2/x12_bulk_framing.py` (new file; every
committed module is imported read-only/verbatim). Results land ONLY in
`results/x12_framing_*.json`.

## 0. Motivation (measured, prior receipts)

v1 framing spends **0.37 s fixed per frame** (0.25 s chirp preamble + 0.12 s
gap). At the d2x geometry that is ~43% of section wall time. m10doom ships
decode 520 frames byte-exact but every frame re-locks on its own preamble; the
longest demonstrated continuous pilot hold is ONE frame body (~0.5–1.0 s).
Bulk framing = more frame bodies per preamble. The risk axis is timing
reacquisition without per-frame anchors; this campaign measures exactly that,
on sim AND on the real tape10 capture, before any bulk master is printed.

## 1. The bulk frame format (frozen)

A **block** = `[0.25 s chirp preamble][body_0][g_i][body_1][g_i]…[body_{F-1}][0.12 s gap]`

- `body_f` = the UNCHANGED v1 frame body: 1 reference symbol + nd data symbols
  of N samples (continuous-phase DQPSK/D2X, per-frame ref symbol RETAINED —
  the mandated per-frame re-sync anchor).
- `g_i` (intra-block guard) = **N samples** (one symbol: 512 @ N512, 256 @
  N256) of silence between bodies — absorbs the ±200-sample drift clamp so a
  late window never reads the next body.
- Inter-block gap stays 0.12 s; preamble waveform/level unchanged
  (`hc.make_preamble(0.25)` inside the per-frame-normalized modulate output;
  block frame 0 keeps its full v1 audio, frames 1..F-1 contribute body only).
- The bit/codec layer (m3_codec RS(255,k) column interleave, 510-byte frames,
  h9 packing, CRC32-per-codeword sidecar tables) is **byte-identical to v1**;
  only the audio layout changes.
- Periodic full re-sync anchor cadence = the block length **F**. Variants
  built and tested: **F ∈ {4, 8}** plus the v1 control (F=1). Design max is
  F=8 (cost model: 87% of recoverable time already banked at F=8).

Configs under test (payloads byte-identical to the proven m10 sections,
reusing `sidecars_m10/*.bin` verbatim, sha-asserted):

| config | scheme | RS | payload | v1 stride | predicted eff F=4 | F=8 |
|---|---|---|---|---|---|---|
| 2572    | DQPSK P22 N512 sp4 (msp 375) | (255,159) | r0 sidecar, 8192 B  | 65888 | 1.244x | 1.297x |
| d2x4910 | D2X_drop P21 N256 sp2 (drop 750) | (255,159) | r6 sidecar, 12288 B | 43104 | 1.438x | 1.551x |

(eff = v1 stride / mean bulk samples-per-frame; exact numbers re-computed from
the built tape and reported.)

## 2. The x12 receiver (frozen)

Frozen DSP only; the ONLY new logic is window anchoring:

- **Anchored frame** (block-first, or every frame in v1): window
  `[pre_start+align−PAD_LO, pre_start+align+12000+body+PAD_HI]`, demodulated
  by the frozen `ResamplingPLLDemod.demod` verbatim (its internal
  `hc.find_preamble` locks the real preamble). Measured body position
  `w_lo + diag['preamble_at']` becomes the block anchor.
- **Non-anchored frame**: nominal body start `bs_f = body_meas(anchor) +
  (manifest body_start_f − manifest body_start_anchor)`; the decode window is
  the SPLICE `concat(reference_preamble, audio[bs_f : bs_f+body+N+2400])`,
  passed to the SAME frozen `demod`. `find_preamble` locks the clean spliced
  preamble at offset 0 (ds = 12000 exactly; asserted in G1), so the frozen
  per-symbol DFT/EMA/PLL/DD-refine code runs verbatim with the body anchored
  at the extrapolated position. The absolute-index DFT basis shift is
  phase-transparent to the differential decision (constant per-carrier phase).
  No truth is used; the extrapolation uses only manifest geometry + the
  anchor's measured preamble position.
- **Branch banks (frozen, pre-registered order, union fill-only, early-stop
  when union complete; pass-1-union level only — NO late-window/erasure
  rescue inside this campaign, the framing variable must be isolated):**
  - 2572 / r0: `resampling_pll30`, `ema0.5`, `ema0.7` (pll30 = tape10 winner).
  - d2x / r6 / r8: `hann256_skip0_ema0.7`, `hann256_skip0_pll30`,
    `hann256_skip0_ema0.6` (tape10 probe-ranked).
- Acceptance channel: frozen `m10_decode._per_cw_decode` (RS errors-only +
  CRC32-per-codeword) + `m10_decode._union_fill` (strictly additive).
  Every RS attempt and CRC check ledgered in
  `results/x12_framing_ledger.json`; campaign budget `crc_checks·2^-32 <
  1e-4` (hard abort at 300,000 checks). Post-hoc miscorrection audit vs the
  truth sidecars on every run (scoring only); miscorrected must be 0.

## 3. Gates (frozen pass rules)

### G1 — no-channel self-check (blocking)
Build the x12 mini-master (`x12_bulk_synth.wav`: lead, global up-chirp, the 6
sections `x12_{v1,b4,b8}_{2572,d2x4910}` each + 0.4 s gap, global down-chirp,
tail; NO front sounder — none of the frozen DQPSK/d2x decode paths consume
it). Decode it clean through the x12 receiver.
**PASS** = all 6 sections byte-exact (packed AND orig), 0 failed codewords,
0 miscorrections, and every spliced window reports `preamble_at == 12000`.

### G2 — sim_v2 dress, bulk >= v1 on the same channel draws (blocking)
Channel cells (frozen; `y = channel_v2(resample(x, 1+clk), profile='tape7',
aac, seed, sim_overrides={'diffuse_gain': dg})`, the x11 mechanism verbatim):

| cell | dg | aac | clk % | seed | role |
|---|---|---|---|---|---|
| dg0.58_aac0_clk+0.00_s0 | 0.58 | off | 0 | 0 | dress (brief-mandated) |
| dg0.58_aac0_clk+0.00_s1 | 0.58 | off | 0 | 1 | dress (brief-mandated) |
| dg0.58_aac1_clk+0.00_s0 | 0.58 | on  | 0 | 0 | dress + AAC (brief-mandated) |
| dg0.58_aac0_clk+0.17_s0 | 0.58 | off | +0.17 | 0 | dress + clock (brief-mandated) |
| dg0.35_aac0_clk+0.00_s0 | 0.35 | off | 0 | 0 | marginal-informative (x11-screen-established regime; dg0.58 kills d2x outright 90/90, so ordering needs a live cell) |

One channel pass per cell over the whole mini tape → v1 and bulk sections see
the SAME channel realization. Known calibration: this sim is 5–8x pessimistic
on the timing/N256 axis; absolute outcomes at dg0.58 are expected to be
failures — the gate is the **v1-vs-bulk ordering**, not the absolute rate.

**Per (config, F∈{4,8}, cell) pass rule:**
1. byte-exact ordering: NOT (v1 byte_exact AND bulk not byte_exact);
2. cell is *informative* iff min(v1.cw_failed, bulk.cw_failed) ≤ 25% of n_cw
   (at least one side alive); for informative cells additionally require
   `bulk.cw_failed <= v1.cw_failed + 2` (2-codeword draw-noise allowance,
   frozen here);
3. both-dead cells (both > 25%) satisfy the gate vacuously but are reported.
**G2 PASS** = every (config, F, cell) satisfies 1–3, 0 miscorrections.

### G3 — REAL-capture preamble ablation on tape10 (blocking; the cadence evidence)
Re-decode tape10_run1's existing v1-framed sections `m10_r0_canary_2572`,
`m10_r6_d2x_p21_rs159`, `m10_r8_d2x_p22_rs179` (cached `audio_nom` +
sync reused READ-ONLY from the x11 receipts) through the x12 receiver with
decoder-side preamble ablation: anchor cadence **K ∈ {1, 2, 4, 8, 16, all}**
(K=1 = every preamble used = baseline; 'all' = single anchor at frame 0;
ablated frames decoded via the splice path at manifest-extrapolated
positions). NOTE the ablation extrapolation distance at cadence K spans
K × v1-stride (incl. 0.37 s framing) — STRICTLY LONGER than the bulk format's
K × (body+g_i), so a supported K here is conservative evidence for bulk-F=K.

Metrics per (section, K): union cw_failed, byte_exact, per-frame raw BER vs
the TX sidecar bits (scoring only), splice-anchor offsets.

**Cadence K is SUPPORTED** iff r0 union cw_failed(K)=0 AND r6 union
cw_failed(K)=0 AND r8 union cw_failed(K) ≤ r8 union cw_failed(K=1)+2.
**K_s** = the largest K whose entire prefix {2,…,K} is supported (no
cherry-picking an isolated lucky cadence). Precondition: the K=1 baseline must
reproduce r0=0/49 and r6=0/72 with the frozen banks (tape10 receipts say the
first branch alone achieved both); if not, report honestly and stop.

**G3 PASS** = K_s ≥ 2 AND the framing efficiency at F=min(8,K_s) (measured
from the built tape geometry) ≥ **1.15x** effective bps for BOTH configs.

### Campaign verdict
`gate_met = G1 AND G2 AND G3`. Recommended bulk cadence for any future
master = **F_rec = min(8, K_s)**, preamble every F_rec frames, ref symbol
every frame, g_i = N guard — only printable after its own master-level
dress + canon canary rules (canary 2572 + best-proven d2x 4910 mandatory,
per the standing x12 discipline; NOT part of this campaign).

## 4. Honesty commitments
- Banked net bps (2572/4910/5791) are NOT claimed to change: bulk framing
  buys wall-clock/effective bps only. Effective bps reported as
  orig_bytes·8 / section wall seconds (gzip leverage included, stated).
- Real-capture evidence (G3) outranks sim (G2); sim REJECTs on the
  timing/density axes remain predictions-to-test (falsified 3x previously).
- All RNG seeded and logged; the x12 receiver and this prereg are frozen
  before the first adjudicated measurement; any deviation found later is
  reported as a protocol break in the report JSON.
- Every CRC trial ledgered; FA bound reported; miscorrections must be 0.
