# X10 Campaign Plan — Pre-Registered (FROZEN 2026-06-11)

This is the pre-registered plan for the x10 campaign. The 8 selected candidates below,
including their full plans and gates, are **frozen verbatim** as of 2026-06-11. No
post-hoc edits to plans, gates, thresholds, search spaces, or axis classifications are
permitted. All new code goes in new `experiments/tape_v2/x10_*.py` files; results to
`experiments/tape_v2/results/x10_*.json`; docs to `experiments/tape_v2/x10_dossier/`.

## Context (verified 2026-06-11)

- Goal: maximize ACOUSTIC byte-exact data rate off a consumer cassette (deck speaker →
  air → stock iPhone mic). Phone-only, NO electrical line-in.
- Current REAL-TAPE RECORD: **2572 net bps byte-exact** (rung `m9_m8_dense375`:
  DQ_P22_N512_sp4, RS(255,159), min_spacing_hz=375, resampling_pll front-end), decoded
  from `captures/tape9_run1.wav`. Per-rung results: `results/m9_results_tape9_run1.json`.
- m9 outcome anatomy: 6/11 rungs orig-exact (934/1052/1169/1404/2338/2572). FAILED:
  m5 n256_rs179 2632 (2/44 cw), m6 n256_rs191 2809 (28/41 cw), m7 n256_p11 2896
  (5/43 cw), m9a freqdiff (37/37), plain m4 ema (5/48, but variant m4b landed). The
  2632–2896 band failing with only 2–5 bad codewords on m5/m7 is the visible frontier.
- Channel (tape9 capture): clock 1.0017x, flutter 0.43%, SNR 41.1 dB, nf −51.2 dBFS.
  Band ~300 Hz–12 kHz, HF droop, magnetic-hysteresis IMD.
- Campaign-wide CRC false-accept budget (pre-registered): expected false-accepts
  < 1e-4 at 2^-32 per trial, i.e. total CRC-acceptance trials capped at 4e5
  campaign-wide, ledgered by `x10_ensemble_decode.py`.

---

## Selected Candidates (8) — plans and gates VERBATIM

### 1. C-redundancy-architecture-1-frontend-ensemble-union

- **Bet:** C
- **Title:** CRC32-guarded per-codeword union across a widened timing-front-end ensemble (productionize the validated prototype)
- **rx_only:** true

**Rationale:** The only candidate already validated end-to-end on the gold capture: verified this session that results/x10_union_orig_verify_tape9_run1.json shows m5 orig_exact=true at 2632.35 net bps (new record, +60) and m4 orig_exact=true at 2338, banked blind from the existing tape9_run1.wav. Judges 9.5/10/9.5. Near-certain anchor of the campaign, and the common receiver every other rx candidate plugs into. Absorbs C-control-tracking-1 (same mechanism): its widened-bank and structurally-different-member ideas are merged here.

**Plan:** Productionize /Users/magnus/repos/cassette-ai/experiments/tape_v2/x10_union_probe.py + x10_union_verify_orig.py into x10_ensemble_decode.py following the m9_decode.py pattern (am2.global_sync_and_resample -> per-section demod -> RS+CRC). Bank: x9_resampling_pll.ResamplingPLLDemod with pll_bw {15,30,45} Hz and ema alpha {0.40..0.85 step 0.05}; fusion = per-codeword accept-any-CRC-verified-branch (replaces the per-section winner of _rs_merge_guarded), erase_frac=0. Expose a registration hook so x10_late_window / x10_gmd / x10_pfft variants become additional union branches (the structurally-different members needed for m7's common-mode floor). UNIFORM ADMISSION REQUIREMENT (campaign-wide): any branch entering the production union bank must first pass the full 4-capture regression suite (tape9_run1: m9_m0_reprove934/m9_m1_thin159/m9_m2_thin191/m9_m3_dropnull9c/m9_m4b_n256_rs159_var/m9_m8_dense375 plus x10-banked m4@2338 and m5@2632; m8_tape_mono_lossless: m8_dq_p10n512_rs127; tape7_run1: m16_rs111_8k/m16_rs191_8k/m32_rs95_4k; tape4_run1: ws_test2k/ws_llm24k) with 0 regressions and the miscorrected_cw post-hoc truth check run on all 4 captures — under accept-any-CRC union the only real regression channel is a CRC false-accept. CAMPAIGN LEDGER: x10_ensemble_decode.py maintains the campaign-level CRC-acceptance trial ledger (branches x codewords x patterns, summed across contributing experiments) in results/x10_ensemble_decode_<capture>.json, against the pre-registered cumulative false-accept budget: expected false-accepts < 1e-4 at 2^-32 per trial, i.e. total trials capped at 4e5 campaign-wide. RECORD CONVENTION (surfaced in the gate, not buried in the dossier): per-codeword CRC32 acceptance uses the manifest sidecar (m9_decode.py crc_table = sec['crc32_codewords']), i.e. truth-derived receiver-side information; only the whole-payload CRC32 is in-stream — all record claims from this receiver explicitly inherit that sidecar caveat, same convention as the standing 2572 record. Runs: full re-decode of captures/tape9_run1.wav (all 11 sections) plus regression re-decodes of m8_tape_mono_lossless.wav, tape7_run1.wav, tape4_run1.wav. Outputs: results/x10_ensemble_decode_<capture>.json (per-branch failed-cw sets, union verdicts, sha256 orig-exact checks, trial-count ledger) and x10_dossier/ENSEMBLE_UNION.md. OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2, per-section chunking, <8 min per invocation.

**Gate:**
- **Metric:** orig_exact (sha256 vs manifest) per rung under blind CRC-guarded union on tape9_run1; regression count over the named landed rungs across all 4 captures; miscorrected_cw post-hoc vs manifest truth on all 4 captures; cumulative CRC-acceptance trial count vs pre-registered budget
- **Threshold:** m5 orig-exact at 2632 net bps AND m4 orig-exact at 2338 reproduced in the production decoder; 0 regressions across the full named 4-capture suite (tape9: 6 m9-EXACT rungs + union-banked m4/m5; m8_tape_mono_lossless: m8_dq_p10n512_rs127; tape7: m16_rs111_8k/m16_rs191_8k/m32_rs95_4k; tape4: ws_test2k/ws_llm24k); miscorrected_cw = 0 verified post-hoc against manifest truth on all 4 captures; total logged CRC-acceptance trials within the pre-registered campaign budget (< 4e5 trials, expected false-accepts < 1e-4); record claims stated under the sidecar per-codeword-CRC convention, caveat declared in the gate output itself
- **Evidence tier:** real-capture
- **Seeds:** deterministic decode, no RNG; numpy/scipy versions logged

---

### 2. B-cons-01-late-window-dc0

- **Bet:** B
- **Title:** Per-carrier DFT window placement at N256: late window for the 750 Hz carrier, center for the rest (merged with B-aggr-01-dc0-splitwindow)
- **rx_only:** true

**Rationale:** Highest-scored unexecuted candidate (9.5/9/9; twin B-aggr-01 9.5/9/8.5). Every causal link is measured on the real capture and was re-verified this session in results/x10_forensics_errors.json: monotone window-shift sweep (dc0 SER 0.576 at -24 smp falling toward +32, reaching 0.13 at +32 — already measured, hence excluded from any pass criterion), per-carrier decoupled preferences, and genie mask-dc0 counterfactuals with per-cw error counts far under t on m5/m6/m7. The only credible existing-capture path to m7's 4 stubborn codewords and the 2896 record. Constant per-carrier window offset cancels in the differential, so the stitch is mathematically free.

**Plan:** New /Users/magnus/repos/cassette-ai/experiments/tape_v2/x10_late_window.py: subclass x9_resampling_pll.ResamplingPLLDemod, override the single _dft_symbols chokepoint to also compute a second symbol matrix at window start +S; compose per-carrier quadrant matrices (dc0 from the late pass, carriers 1..P from center). PRE-REGISTERED SEARCH SPACE (frozen before any decode): scalar dc0 late-shift grid S in {16,24,32,40} samples; per-carrier shift vectors with dc0 offset in {0,+8,+16,+24,+32,+40} and carriers 1..P each in {-8,0,+8}, selected per-carrier INDEPENDENTLY (decoupled argmin, per the measured decoupled preferences — no full cross-product). PRE-REGISTERED TRUTH-FREE SELECTION STATISTIC: per (carrier, shift) cell, decision-EVM = mean angular distance of the differential phase to the nearest QPSK decision centroid over the section's data symbols, plus the pilot-carrier post-PLL residual for pilot cells; per-carrier argmin of this statistic selects the stitched vector. Branches entering the union bank: one stitched matrix per scalar S (4) plus one decoupled-argmin stitched matrix; the total number of CRC-acceptance trials contributed to the union bank MUST be logged in results/x10_late_window_tape9_run1.json and rolled into the x10_ensemble_decode campaign ledger (budget: expected false-accepts < 1e-4 campaign-wide). Register all stitched variants as branches in the x10_ensemble_decode union bank (CRC32 guard intact, erase_frac=0) so selection stays blind; admission requires passing the full 4-capture regression suite per the campaign-wide rule. Pass-2 fallback on still-failed codewords: disagreement-gated structured erasures (only bytes where center and late passes disagree on dc0 bits) — NOT blanket positional erasure. Runs: re-decode captures/tape9_run1.wav sections m4/m5/m6/m7; mandatory regression on the full named 4-capture suite (tape9 landed rungs incl. m0-m3/m4b/m8 and union-banked m4/m5, m8_tape_mono_lossless m8_dq_p10n512_rs127, tape7 m16_rs111_8k/m16_rs191_8k/m32_rs95_4k, tape4 ws_test2k/ws_llm24k — must stay 0 cw failed). Results -> results/x10_late_window_tape9_run1.json; per-section <8 min, OPENBLAS_NUM_THREADS=2.

**Gate:**
- **Metric:** cw_failed on m7/m6/m5 under union+late-window vs the x10 union baseline; dc0 SER under truth-free stitched selection; regression count over the full named 4-capture suite; miscorrected_cw post-hoc vs manifest truth on all 4 captures; CRC-acceptance trial count logged
- **Threshold:** PASS = m7 cw_failed 0/43 (banks 2896 orig-exact, +324 over record, sidecar-CRC convention caveat inherited). MINIMUM PASS (must be NEW evidence, not the already-measured 0.13@+32) = >=1 additional CRC-verified codeword on m6 or m7 vs the x10 union baseline, OR dc0 SER <= 0.10 under truth-free stitched selection, OR m6 cw_failed reduced >=50% vs the union baseline. dc0 SER <= 0.15 is DIAGNOSTIC only — it restates the measured forensics fact and counts as neither pass tier. All tiers additionally require: 0 regressions on the full 4-capture suite, miscorrected_cw = 0 verified post-hoc against manifest truth on all 4 captures, and the trial count logged in results/x10_late_window_tape9_run1.json within the campaign false-accept budget (< 1e-4)
- **Evidence tier:** real-capture
- **Seeds:** deterministic decode; scalar grid {16,24,32,40}, per-carrier vector space {0..+40}x{-8,0,+8}, and decision-EVM selection statistic all pre-registered before any decode

---

### 3. A-fec-gmd-erasure

- **Bet:** A
- **Title:** Structural carrier-class errors-and-erasures RS retry keyed to the deterministic carrier-block byte layout (CRC32-guarded trial ladder)
- **rx_only:** true

**Rationale:** Best FEC candidate (8/7.5/7). Purely POSITIONAL erasure of carrier-class byte positions is robust to the measured confident-error property that killed margin-ranked erasure (x10_c_margin_erasure: 0/45 rescues) — it erases positions regardless of decision margin. The 2e+f<=n-k arithmetic checks against manifest geometry (~25.5 dc0 bytes/cw on m5). Independent mechanism to mop up m7/m6 residuals if window stitching saturates at the +32 sweep edge; zero tape cost.

**Plan:** New /Users/magnus/repos/cassette-ai/experiments/tape_v2/x10_gmd_erasure_decode.py importing h4_dqpsk, x9_resampling_pll, analyze_master2 (no frozen-file edits). Derive each carrier's byte positions inside every codeword from nominal_frame_bits(meta) + the full-depth interleave (copy the m9_decode.py reshape(rs_n,n_cw).T mapping into the new file); UNIT-TEST the map against the forensics dc0 byte-attribution counts before trusting it. After union+late-window pass-1, for each remaining CRC-failed codeword run a bounded trial ladder: erase worst-1 / worst-2 / worst-3 carrier byte-classes (carriers ranked truth-free by angular dispersion of dphi residuals), <=60 patterns per cw, reedsolo RSCodec.decode(..., erase_pos=...), accept only on manifest CRC32 match; log the total trial count in results/x10_gmd_erasure_tape9_run1.json and roll it into the x10_ensemble_decode campaign ledger (pre-registered cumulative budget: expected false-accepts < 1e-4 at 2^-32/trial). DROP the per-byte margin-ranked GMD arm — it has a direct measured null. Branches/patterns feed the union bank only after passing the campaign-wide 4-capture regression admission suite. Runs: captures/tape9_run1.wav m5/m6/m7; regression on the FULL 4-capture suite — tape9 landed rungs (m0-m3/m4b/m8 + union-banked m4/m5), m8_tape_mono_lossless.wav (m8_dq_p10n512_rs127), tape7_run1.wav (m16_rs111_8k/m16_rs191_8k/m32_rs95_4k), tape4_run1.wav (ws_test2k/ws_llm24k). Results -> results/x10_gmd_erasure_tape9_run1.json. Runtime trivial.

**Gate:**
- **Metric:** additional CRC-verified codewords recovered vs the union+late-window baseline; miscorrected_cw / false-accept count (post-hoc truth check vs manifest on all 4 captures); regression count over the full named 4-capture suite; total trial count vs campaign budget
- **Threshold:** PASS = >=1 additional codeword on m7 or m6 with miscorrected_cw = 0 verified post-hoc against manifest truth on all 4 captures AND 0 regressions on the full 4-capture suite (tape9 landed + union-banked rungs, m8_dq_p10n512_rs127, tape7 m16_rs111_8k/m16_rs191_8k/m32_rs95_4k, tape4 ws_test2k/ws_llm24k); FULL PASS = m7 residual -> 0 (2896 banked under the sidecar-CRC convention caveat); trial ladder bounded to <=60 patterns/cw, total trials logged and within the campaign-wide false-accept budget (< 1e-4 expected false-accepts, < 4e5 cumulative trials)
- **Evidence tier:** real-capture
- **Seeds:** deterministic; carrier-ranking metric pre-registered (angular dispersion, truth-free)

---

### 4. A-underwater-pfft-adaptive

- **Bet:** A
- **Title:** Partial-FFT demodulation with adaptive per-carrier segment weights (differential-OFDM eigendecomposition variant)
- **rx_only:** true

**Rationale:** The frontier rx slot (8/6.5/7.5): per-carrier segment weighting is a strict superset of window placement — it synthesizes a longer effective guard at dc0 AND samples intra-symbol flutter at ~750 Hz, exactly the headroom beyond the +32 shift edge where late-window saturates. The realistic receiver path to m6 (2809) and to hardening m7. Built-in uniform-weight no-regression baseline; UWA literature (Yerramalli/Stojanovic/Mitra TSP 2012; Han et al. eigendecomposition for differential OFDM) maps directly onto our DQPSK PHY.

**Plan:** New /Users/magnus/repos/cassette-ai/experiments/tape_v2/x10_pfft.py: subclass x9_resampling_pll.ResamplingPLLDemod, override _dft_symbols to return Q in {2,4} contiguous partial sums per carrier, shape (nsym, nc, Q); HARD PRECONDITION: sum over Q at uniform weights reproduces the production demod bit-exactly. STEP 1 (cheap diagnostic, decides solver investment): per-segment SER on the failed m4/m5 frames — confirm early-segment >> late-segment error excess at dc0 (edge-ISI signature) before building the weight solver. STEP 2: per-carrier complex weights via eigendecomposition of the pilot/decision-error covariance over a sliding ~64-frame window, seeded from h4_dqpsk.measure_sounder_eq spans, decision-directed with quality gating; freeze weight updates on carriers with running SER > 10%. Register pfft branches (Q x {pll, ema0.6, ema0.7}) into the x10_ensemble_decode union bank — admission requires passing the campaign-wide FULL 4-capture regression suite (tape9 landed + union-banked rungs, m8_tape_mono_lossless m8_dq_p10n512_rs127, tape7 m16_rs111_8k/m16_rs191_8k/m32_rs95_4k, tape4 ws_test2k/ws_llm24k) with the miscorrected_cw post-hoc truth check on all 4 captures; CRC-acceptance trials contributed by pfft branches logged in results/x10_pfft_tape9_run1.json and rolled into the campaign ledger (budget < 1e-4 expected false-accepts). Runs: tape9_run1 m4-m7 + the full 4-capture regression. Results -> results/x10_pfft_tape9_run1.json. Sequenced AFTER late-window (it must beat that baseline, not the m9 one).

**Gate:**
- **Metric:** bit-exact uniform-weight reproduction (precondition); dc0 SER vs best late-window branch; additional CRC-verified cw on m6/m7; regression count over the full named 4-capture suite; miscorrected_cw post-hoc vs manifest truth on all 4 captures; trial count vs campaign budget
- **Threshold:** PRECONDITION: uniform weights reproduce baseline exactly. KILL = step-1 shows no early-segment error excess at dc0. PASS (landed candidate, counts in campaign accounting) = >=1 additional CRC-verified cw on m6 or m7 vs the union+late-window baseline. DIAGNOSTIC PASS (justifies keeping pfft branches in the bank, does NOT count as landed) = >=1.5x further dc0 SER reduction vs the best late-window branch with zero additional codewords. Both tiers require: 0 regressions on the full 4-capture suite, miscorrected_cw = 0 verified post-hoc against manifest truth on all 4 captures, and logged trial count within the campaign false-accept budget (< 1e-4)
- **Evidence tier:** real-capture
- **Seeds:** deterministic; window/Q grid pre-registered (Q in {2,4}, 64-frame sliding window)

---

### 5. B-aggr-03-toneplan-v2

- **Bet:** B
- **Title:** Channel-mapped N256 tone plan for master10: drop the 750 Hz slot, pilot on the measured notch, extend past 9 kHz (merges B-cons-04 notch rule + A-bitloading-1 dual-offset hedge)
- **rx_only:** false

**Rationale:** Best new-master backbone (8.5/7.5/7). All three placement errors are measured on tape9: dc0 N256 collapse (genie mask -> 0 failed cw, max cw err ~22 vs t=38 on m7), static 4407-4666 Hz notch under m7's data carrier while its 40 dB bin was wasted on the pilot (m5/m6 accidentally inverted this and survived), and >=10 dB SNR375 across 9-11 kHz unused. Subclass legality verified against frozen asserts. Banker 2896, stretch ~3158, at zero rate cost relative to m7.

**Plan:** New files: x10_b_toneplan.py (subclass of h4_dqpsk.DQPSKScheme with explicit bins + pilot_bin; re-assert (spacing*Nw)%N==0; relax the 9500 Hz assert ONLY in the subclass; re-fit tx_amp at new freqs via rcs.load_params Hf interp) + x10_b_master.py / x10_b_decode.py per the m9_master/m9_decode pattern (manifest, chirp anchors, CRC32 tables). RECORD CONVENTION (pre-registered NOW, before mastering): master10 continues the manifest-sidecar per-codeword CRC32 convention — the same convention under which the standing 2572 record was set, keeping net-bps figures comparable; every ship-gate record claim explicitly inherits the sidecar caveat (no in-stream per-cw CRC, no rate charge). Ladder on master10: M0 anchor = m8_dense375 VERBATIM (must reprove 2572 or the tape pass is void); banker rung = 11 data carriers 1500-9750 notch-skipped, pilot at 4500 (proven pilot-viable), RS(255,179) -> 2896; stretch rung = 12 carriers to 10500 -> ~3158; every rung in TWO payload offsets (m4/m4b realization lesson) plus a pilot-variant rung (pilot at 5865) as notch-migration insurance. Decoder re-derives pilot/carrier placement from the in-master sounder at decode time and uses the x10_ensemble_decode union receiver (plus late-window/pfft branches if landed), with its CRC-acceptance trials logged into the campaign ledger. SIM PRE-GATE AXIS CLASSIFICATION (frozen BEFORE any sim run): tape-BLOCKING failure axes = IMD/dense-packing at the new tone placements, notch-placement sensitivity, AAC-survival of the new bins; prediction-to-test-ONLY axes (logged, never a cut) = timing/flutter, N256 symbol length, density — per the m9 calibration where sim rejected all N256 and real tape landed it. Post-hoc reassignment of an axis between classes is prohibited. Blocking-axis seed discipline: no rung is KILLed on a blocking axis from the 8-seed screen alone — a KILL requires a 16-seed confirmation run failing the criterion at 16-seed scale (g1 < 14/16). Sim: sim_v2.channel_v2(profile='tape7', aac in {False,True}, dg 0.58/0.65) + x9_flutter_gate. Tape cost ~2 min/rung, shared with the bitload and dense2x rungs.

**Gate:**
- **Metric:** Pre-gate: g1 nominal byte-exact seed count + g5 mean byte-error-rate vs RS budget (frozen before runs), with the blocking-vs-prediction axis list frozen before any sim run. Ship gate: orig_exact (sha256) + net bps per rung on the new capture, with the m8 anchor; miscorrected_cw post-hoc vs manifest truth; campaign trial ledger
- **Threshold:** Pre-gate: g1 >= 7/8 seeds and g5 <= 0.089 (k179) on the 8-seed screen; failures on the pre-registered prediction-only axes (timing/N256/density) are logged as prediction-to-test, never a cut; a KILL on a pre-registered blocking axis (IMD/notch/AAC placement) additionally requires a mandatory 16-seed confirmation run with g1 < 14/16. SHIP = m8 anchor reproves 2572 orig-exact (else the tape pass is void) AND banker rung orig-exact >= 2896 net bps under the pre-registered sidecar-CRC convention (record claim inherits that caveat); stretch rung counted separately; miscorrected_cw = 0 verified post-hoc against manifest truth on the new capture; union-receiver CRC-acceptance trials logged within the campaign false-accept budget (< 1e-4)
- **Evidence tier:** real-capture
- **Seeds:** sim pre-gate: 8 seeds (0-7) screen + 16 seeds (0-15) mandatory confirmation before any blocking-axis KILL, set+logged; decode deterministic

---

### 6. B-aggr-04-bitload-n512

- **Bet:** B
- **Title:** Per-carrier D-MPSK bit-loading (D8PSK/DQPSK/DBPSK) at the proven m8 N512/375 Hz geometry — measured floor 3040 net bps, census-gated (merges B-cons-05; adopts a confidence-bounded tail rule)
- **rx_only:** false

**Rationale:** 8.5/7/7.5 — the safest path above 3000: the 3040 figure is a measured FLOOR (z=2.6 hard-decision loading from in-situ EVM through the exact winning front-end at the geometry that banked 2572 orig-exact), not a projection. It changes nothing about the proven geometry except per-carrier constellation order, respects the hysteresis lesson (phase-only, no rings), and a free rx-only census kills it cheaply if flutter tails are heavy. Adopts C-control-tracking-3's tail-gating idea, upgraded to a sample-size-honest estimator.

**Plan:** PHASE A (rx-only, gates the tape spend): new x10_bitload_census.py re-demods the m8-geometry sections of captures/tape9_run1.wav AND captures/m8_tape_mono_lossless.wav with the production front-end (same tracker that will decode); per-carrier differential phase-error histograms + amp-ratio stats. PRE-REGISTERED LOADING RULE (replaces the raw-p999 order statistic, which at ~2-3k symbols/carrier/capture has ~2-3 expected tail exceedances and is too noisy to gate on): carrier qualifies for 3 bits iff (a) the binomial upper 95% confidence limit on P(|dphi err| > 15 deg) is < 1e-3 per carrier per capture, AND (b) the absolute max excursion stays inside the 22.5 deg D8PSK decision boundary on BOTH captures, AND (c) f < 5 kHz on BOTH captures (intersection loading vs the known carrier-quality migration); D-BPSK on carriers < 12 dB in-situ; amplitude rings excluded entirely. DERATE PATH (pre-registered BEFORE the census runs): if 4-7 carriers qualify, the load table is derated to the qualifying set and the derated banker's OWN ship threshold is computed and frozen pre-tape as its design net bps from that load table; the derated rung goes to tape only if its design net bps > 2572, else KILL before tape — no post-hoc reclassification against the 3040 full-load target. Emit load table + (if derated) the frozen derated design net bps -> results/x10_bitload_census.json. PHASE B: new x10_b_bitload.py — mixed-order differential M-PSK scheme (per-carrier bits vector, Gray-mapped; carrier-major packing keeps RS bytes carrier-attributable; h9_payload_codec + per-cw CRC32 unchanged; ResamplingPLLDemod timing reused — the pilot loop is constellation-agnostic; new _decide for mixed orders). RECORD CONVENTION (pre-registered): master10 rungs continue the manifest-sidecar per-codeword CRC32 convention; record claims inherit the sidecar caveat (consistent with the standing 2572 record). Master10 rungs: banker z=2.6 load (3040 floor, RS k159) + stretch z=1.7/k179, beside the same-tape m8 pure-DQPSK anchor. Sim gate per the frozen m9 matrix with the pre-registered note that D8PSK will look 5-8x pessimistic; novel mapping = HOLD-by-rule -> goes to tape anyway. Decode via the union receiver with CRC-acceptance trials logged into the campaign ledger.

**Gate:**
- **Metric:** Phase A: number of carriers passing the pre-registered confidence-bounded D8PSK rule (binomial upper 95% CL on P(|dphi err|>15deg) < 1e-3 AND max excursion < 22.5deg AND f<5kHz, on BOTH captures). Tape: banker rung orig_exact (sha256) + net bps with m8 anchor; miscorrected_cw post-hoc vs manifest truth; campaign trial ledger
- **Threshold:** Phase A GO = >=8 qualifying carriers (full load, ship target 3040); 4-7 = derate to the qualifying set with the derated design net bps frozen PRE-TAPE, required > 2572, and that frozen figure becomes the derated rung's own ship threshold; <4 qualifying OR derated design <= 2572 = KILL before tape. SHIP (full load) = banker rung orig-exact >= 3040 net bps AND m8 anchor reproves 2572 orig-exact (else the tape pass is void); SHIP (derated) = derated banker orig-exact >= its pre-registered design net bps (> 2572) AND the m8 anchor reproves 2572. All record claims under the pre-registered sidecar-CRC convention (caveat inherited); miscorrected_cw = 0 verified post-hoc against manifest truth on the new capture; union-receiver trial count logged within the campaign false-accept budget (< 1e-4)
- **Evidence tier:** real-capture
- **Seeds:** census deterministic; sim pre-gate 8 seeds (0-7) logged; loading rule and derate ship threshold frozen before census/tape

---

### 7. B-aggr-05-dense2x

- **Bet:** B
- **Title:** Time-densification 2x: 375 Hz grid at 187.5 sym/s via N256/skip=64/spacing=2 — the funded frontier slot (target 4400-5100 net, derate rung bounds the downside)
- **rx_only:** false

**Rationale:** The one high-risk ladder slot (7/6/5.5): the only candidate that can DOUBLE the record, with a measured-grounded geometry argument — it keeps the N512-proven 1.33 ms guard (the measured cure for the dc0 echo) and the m8-proven 375 Hz spacing while doubling symbol rate; the scheme is legal without touching frozen code (asserts verified). Downside bounded to one tape evening by an rx-only echo-tail go/no-go (recalibrated for the shorter window per the judges' correction) and a P18/RS127 derate rung that still sets a record at ~3500-4000 if it lands.

**Plan:** STEP 1 (rx-only go/no-go, runs BEFORE any mastering): new x10_dense2x_probe.py measures the echo-tail energy profile over 1.33-4 ms from tape9_run1 m0/m8 sections (extending the forensics window-position machinery) and predicts per-carrier SER at Nw=128, explicitly including the ~3x tail-concentration factor of the shorter window AND the ~4.8 dB per-symbol energy loss vs N512 — the threshold is calibrated for Nw=128, not 'what N512 tolerates'. Verify doubled pilot-rate tracking with x9_resampling_pll.residual_stats. STEP 2 on GO: new x10_b_dense2x.py — base rung DQPSKScheme(P=22, N=256, spacing=2, skip=64, min_spacing_hz=375.0) direct; notch-skipping explicit-bins subclass for the banker; 3 rungs on master10: P18/RS(255,127) derate, P21/RS159 banker (~4400-4900 net), P22/RS179 stretch; front-end sweep pll_bw {30,45,60} + ema 0.5-0.8 through the union receiver (CRC-acceptance trials logged into the campaign ledger); Schroeder-phased initial symbol + light PAPR normalization at master build. RECORD CONVENTION (pre-registered): master10 rungs continue the manifest-sidecar per-codeword CRC32 convention; record claims inherit the sidecar caveat. CLAIM DISCIPLINE (pre-registered): any record or net-bps claim requires sha256 orig_exact vs manifest; a rung that is byte-exact-but-not-orig-exact counts ONLY as geometry validation with no rate claim. Sim g1-g5 run and logged but pre-registered as prediction-to-test on this axis (sim rejected ALL N256 and real tape landed m4b/m8). Tape ~1.5 min/rung behind the m8 anchor.

**Gate:**
- **Metric:** STEP 1: predicted mean byte-error-rate for the P18/RS127 rung at Nw=128 (echo-tail + window-energy corrected) vs RS budget. Tape: best dense2x rung sha256 orig_exact net bps, with the m8 anchor; miscorrected_cw post-hoc vs manifest truth; campaign trial ledger
- **Threshold:** GO = predicted byte-ER <= 0.6 x (255-127)/(2x255) = 0.150 for P18; NO-GO = abort, zero tape spent. ALL tape outcomes additionally require the m8 anchor to reprove 2572 orig-exact, else the tape pass is void. SUCCESS = P18 derate rung sha256 orig-exact (validates the geometry AND banks ~3500-4000 net under the sidecar-CRC convention); byte-exact-but-not-orig-exact = geometry validation only, NO rate claim (pre-registered). RECORD = P21 banker sha256 orig-exact >= 4400 net bps (sidecar caveat inherited). miscorrected_cw = 0 verified post-hoc against manifest truth on the new capture; union-receiver trial count logged within the campaign false-accept budget (< 1e-4)
- **Evidence tier:** real-capture
- **Seeds:** sim 8 seeds logged as prediction-only; probe deterministic

---

### 8. C-redundancy-architecture-3-replay-diversity

- **Bet:** C
- **Title:** Replay diversity: CRC-guarded per-codeword union across TWO playbacks of the existing master9 tape — zero new mastering, targets m7's common-mode floor and measures recorded-in vs playback-borne impairment
- **rx_only:** false

**Rationale:** 7/5/6 — the only remaining free diversity branch against the one measured hard floor (m7 cw {20,23,25,26} fail under ALL front-ends on one capture), at ~10 min operator cost and near-zero code cost (reuses the union machinery verbatim). Even in the expected partial-overlap outcome, the cross-capture independence measurement is the single most valuable unknown for pricing every future TX rung (coding vs mastering spend). Honest expectation: diagnosis likely, +324 (2896) possible.

**Plan:** OPERATOR step (~10 min, no new mastering): one additional playback of the existing master9 tape captured via the proven Voice Memos -> iCloud SOP (Dolby off, speaker ~55, 1 s lead-in per CLAUDE.md) -> experiments/tape_v2/captures/tape9_run2.wav. Code: new x10_replay_fusion.py — (1) decode run2 STANDALONE with x10_ensemble_decode as a sanity gate (deck-state comparable: measured flutter_wrms and noise floor within 1.5x of run1, all 6 landed rungs still orig-exact); (2) per-codeword CRC-guarded union across {tape9_run1, tape9_run2} x all branches (including late-window/gmd/pfft branches if landed) — the x2 capture multiplier on CRC-acceptance trials is logged in results/x10_replay_fusion.json and rolled into the campaign ledger (budget: expected false-accepts < 1e-4 campaign-wide); (3) headline output = cross-capture failed-codeword overlap matrix per section (the independence statistic) + orig-exact verdicts. PRE-REGISTERED DECISION RULE on the independence statistic (frozen before the capture): cross-capture failed-cw overlap on m6/m7 >= 80% -> declare errors recorded-in and redirect campaign spend to TX rungs; <= 40% -> fund replay/multi-pass diversity as a standing branch in future campaigns; 40-80% -> indeterminate, no spend redirection either way. Results -> results/x10_replay_fusion.json + x10_dossier/REPLAY_DIVERSITY.md. Tier-2 coherent DFT averaging across captures only if the union leaves 1-2 stragglers (separate function, time-permitting).

**Gate:**
- **Metric:** cross-capture codeword-failure overlap on m6/m7 (independence statistic) evaluated against the pre-registered decision rule; m7 residual cw after cross-capture union; run2 standalone sanity (flutter/noise-floor ratio vs run1, landed-rung regressions); miscorrected_cw post-hoc vs manifest truth on both captures; trial count vs campaign budget
- **Threshold:** DIAGNOSTIC PASS = run2 sanity within 1.5x AND all 6 landed rungs orig-exact on run2 standalone AND the pre-registered decision rule applied to the measured overlap (>= 80% -> errors recorded-in, redirect spend to TX; <= 40% -> fund multi-pass diversity in future campaigns; 40-80% -> indeterminate) — failable via the sanity arms, decision rule frozen pre-capture. RECORD PASS = m7 residual cw -> 0 across the two-capture union, banking 2896 orig-exact EXPLICITLY as a separate multi-pass-category record that does NOT supersede single-capture records (this categorization is part of the threshold, not a dossier footnote), under the sidecar-CRC convention caveat. Both tiers require miscorrected_cw = 0 verified post-hoc against manifest truth on both captures and the doubled trial count logged within the campaign false-accept budget (< 1e-4)
- **Evidence tier:** real-capture
- **Seeds:** deterministic decode; capture pair logged with SOP parameters; overlap decision thresholds (80%/40%) pre-registered before capture

---

## Rejected Candidates (with reasons)

| ID | Reason |
|---|---|
| A-underwater-nullbin-doppler | Targets residual Doppler-scale the resampling front-end already models; cannot touch dc0 (the measured killer) and is largely redundant with the validated union alpha sweep (judges 6/4/6). |
| A-underwater-dd-phase-tracking | Its fine-alpha core is already banked by the validated union ensemble, and per-carrier phase-bias EMA cannot fix the measured data-dependent dc0 echo ISI — fully subsumed by selections #1/#2. |
| A-otfs-virtual-pilot-iced | Smooth-trajectory de-rotation is the wrong model for the measured per-symbol, data-dependent dc0 echo; its m5 headline is already banked by the cheaper union. |
| A-otfs-doppler-batch-smoother | Forensics caps front-end-only gains and its valuable control arm (ema 0.65-0.8) is already validated in the union bank — the distinctive non-causal smoother is the low-value remainder. |
| A-otfs-reliability-bin-mapping | Subsumed by funded B-aggr-03 toneplan-v2, which delivers the same 750 Hz eviction plus notch-aware pilot placement and band extension on one master. |
| A-otfs-isfft-spreading-adjudication | Correct do-not-run adjudication — file the citations in x10_dossier to close the question; banks 0 bps by design, nothing to fund. |
| A-hf-modems-long-interleaver | Premise refuted by measured forensics: per-cw errors are under-dispersed (var/mean 0.32-0.46) and the mapping is already a full-depth interleave — the failure is the mean at the RS cliff, which re-interleaving cannot fix. |
| A-hf-modems-dd-virtual-probe | Probe/trajectory fitting cannot repair confident, data-dependent dc0 echo errors (measured); remaining value duplicated by the union and the virtual-pilot family. |
| A-hf-modems-8psk-bitload | Duplicate of funded B-aggr-04 bit-loading, which already holds the in-situ EVM table and the census pre-check. |
| A-hf-modems-serial-tone-dfe | Inverts the measured constraint ordering (IMD is solved at 375 Hz spacing; timing/reverb-ISI bind); an unanchored DFE-under-flutter PHY with no regression anchor is a negative-expectation tape spend. |
| A-bitloading-1-zerobit-regrid | Strong (7.83 avg) but a strict subset of funded B-aggr-03; its dual-payload-offset hedge and k191 sibling rung are folded into that plan. |
| A-bitloading-2-mixedorder-LC | Duplicate of the funded bit-loading slot; variable-radix packing adds implementation surface without distinct gain. |
| A-bitloading-3-measured-margin-rule | Calibration infrastructure, not a rung; its measured-margin loading rule and gamma discipline are folded into B-aggr-04's pre-registered load table. |
| A-fec-fountain-outer | Breakeven-marginal at measured residuals (its own math) and pure rate loss on clean rungs; revisit as insurance only if frontier rungs persistently fail by 1-2 codewords. |
| A-fec-ldpc-soft | Largest new-code surface, sim-only gating on the unanchored N256 axis, and the known LLR-miscalibration trap under flutter-correlated differential noise; RS is not the binding constraint once dc0 is fixed. |
| A-fec-uep-rs | Headline arithmetic fails on measured numbers (rate-1/2 RS cannot carry ~86% byte errors on c0); the surviving variant collapses to the funded drop-c0 regrid. |
| A-tape-prior-art-rx-adaptive-tracking | Core mechanism (fine alpha + CRC-guarded merge) already executed by the union; its preferred per-frame dtau selection metric was measured to collapse (m7 39/43). |
| A-tape-prior-art-bitloading | Duplicate of the funded bit-loading slot (B-aggr-04) at higher rederivation cost. |
| A-tape-prior-art-allpass-preeq | Physics flaw: the measured trailing echo (\|r\|<1) is minimum-phase, so the all-pass excess is ~identity and a phase-only inverse leaves the echo ISI untouched. |
| A-tape-prior-art-bandext | Band extension is folded into B-aggr-03's 12-carrier stretch rung; the standalone HF-boost-vs-IMD risk does not merit a separate master slot. |
| B-cons-02-carrier-stitch-frontends | Margin amplifier subsumed by the funded late-window per-carrier stitcher plus the union bank; alternate carrier maps can ride as extra branches there if needed. |
| B-cons-03-structural-dc0-erasures | Its margin-ranking premise has a direct measured null (x10_c_margin_erasure: 0/45 rescues — confident errors); superseded by A-fec-gmd's purely positional carrier-class erasure. |
| B-cons-04-notch-aware-tone-plan | Merged into funded B-aggr-03: pilot-on-notch placement and decode-time pilot re-derivation are explicit steps in that plan. |
| B-cons-05-bitload-m8-geometry | Duplicate of funded B-aggr-04 (same 3040 measured floor); funded once, with the rx-only census pre-check. |
| B-aggr-01-dc0-splitwindow | Duplicate of selected B-cons-01; its truth-free per-carrier shift selection and disagreement-gated erasure fallback are merged into that plan. |
| B-aggr-02-fe-matrix | Extended alphas already live in the union bank and the wow-band pre-tracker premise is weak (the DD residual is likely not wow-band); margin amplifier below the funding line. |
| C-info-theory-1-measured-waterfill-loading | Phase-only core duplicates the funded bit-loading slot; differential amplitude rings push the hysteresis-amplitude axis the project deliberately avoids. |
| C-info-theory-2-per-band-symbol-tiling | Dual-stream machinery (two pilots/preambles, cross-band IMD on sim's unanchored axis) to recover ~658 bps of LF rate; the funded drop-LF regrid captures most of the value. |
| C-info-theory-3-self-noise-shaping | Attribution is inferential and competes with the measured timing/echo explanations of the same gap; at most ride the 80 s A/B placement probe on master10 spare tape as a free diagnostic — no placement search funded. |
| C-control-tracking-1-crc-arbitrated-frontend-bank | Same union mechanism as selection #1, which already ran and validated; its widened-bank and structurally-different-member ideas are merged into the productionization plan. |
| C-control-tracking-2-rts-smoother-joint-tracker | 3-5 days of Kalman/RTS machinery whose highest-value parts (per-carrier delay = window shift; realization diversity) are delivered by funded #2/#1; dc0 is per-symbol ISI a smoother cannot remove. |
| C-control-tracking-3-tracker-licensed-8dpsk-bitloading | Duplicate of the funded census-gated bit-loading with an added tracker dependency that inflates the critical path; its tail-gating rule is adopted (in confidence-bounded form) in B-aggr-04's plan. |
| C-waveform-geometry-1-warp-subspace-regression | Margin converter that needs a k191 re-cut on new tape to bank anything; the measured warp share (~35% of phase-error power at 8 kHz) caps gains below cheaper funded amplifiers. |
| C-waveform-geometry-2-constant-q-tiling | Elegant, but only ~+132 bps over the funded drop-bin-4 toneplan at the cost of dual-clock TX/RX lanes on a one-shot tape; revisit if master10's banker lands and LF rate matters. |
| C-waveform-geometry-3-constant-envelope-fm | Thesis contradicts the measured constraint ordering (timing phase noise >> IMD at proven spacing) and Stage-1 DFE-under-flutter is unanchored; at most the 15 s Stage-0 probe may ride master10 spare tape uncommitted. |
| C-redundancy-architecture-2-two-tier-outer-erasure | Its own honest algebra shows standalone loss vs the now-banked 2632 (9.3% residual -> ~2621); insurance layer to revisit only after the dc0 fixes shrink residuals well below breakeven. |
