export const meta = {
  name: 'cassette-capacity-push',
  description: 'Push cassette net-data capacity past the MFSK-32 frontier without raising error rate: 5 hypotheses (safe→moonshot), measured in the frozen harness, then adjudicated.',
  phases: [
    { title: 'Reference', detail: 'Re-measure B0 + MFSK-32 frontier (deterministic anchor)' },
    { title: 'Experiments', detail: '5 hypotheses C1..C5 implemented + measured in parallel' },
    { title: 'Synthesis', detail: 'Adjudicate vs pre-registered bars, write results doc' },
  ],
}

const ROOT = '/Users/magnus/repos/cassette-ai'

// ---------------------------------------------------------------------------
// Shared harness primer — every agent gets this so they use the SAME contract.
// ---------------------------------------------------------------------------
const PRIMER = [
  'You are working in the repo ' + ROOT + ' (a cassette data-storage research project).',
  'There is a FROZEN evaluation harness you MUST import and use — do not reinvent it:',
  '',
  '  src/hyp_common.py provides:',
  '    - FuncScheme(name, gross_bps, modulate, demodulate, erasure_fn=None): adapter.',
  '      modulate(bits:uint8[]) -> float32 audio @48k INCLUDING its own chirp preamble (overhead).',
  '      demodulate(audio, sr) -> recovered uint8 bits. Must self-sync from the preamble (NO oracle timing).',
  '    - make_preamble(seconds=0.25) / find_preamble(audio, seconds) : the standard chirp sync to reuse.',
  '    - evaluate_scheme(scheme, tape_preset="normal", n_seeds=N, payload_bits=B, capture_key="usb_soundcard")',
  '        -> dict with raw_bit_error_rate, erasure_rate, gross_bps (Monte-Carlo through the real channel).',
  '    - project_to_cassette(raw_ber, erasure_rate, gross_bps) -> dict with required_code_rate, net_bps,',
  '        MB_C90_stereo, P_full. This is the conservative BER->code-rate projection. net_bps is THE metric.',
  '',
  '  Path bootstrap at the top of your script (canonical):',
  '    import sys, pathlib',
  '    ROOT = pathlib.Path("' + ROOT + '")',
  '    for p in ["src","tests/e2e"]: sys.path.insert(0, str(ROOT/p))',
  '    import hyp_common as hc',
  '',
  'The channel (tape preset "normal"): 42 dB SNR, 11 kHz low-pass, 0.10% wow/flutter,',
  'bursts 0.30/s x 6 ms. Capture usb_soundcard is near-transparent. Usable band ~400..10500 Hz.',
  '',
  'The BER->code-rate table (project_to_cassette) is conservative and STEP-shaped. Key knees:',
  '  raw BER <= 1e-4 -> code rate 0.92 ; <= 1e-3 -> 0.85 ; <= 3e-3 -> 0.80 ; <= 1e-2 -> 0.70.',
  'So LOWERING raw BER below a knee is itself a net-rate win. P_full must stay 1.0 (whole-file recovery).',
  '',
  'CANONICAL EVAL SETTINGS for final numbers: n_seeds=16, payload_bits=4000, tape_preset="normal".',
  'You may use n_seeds=8 for fast grid sweeps, but CONFIRM your best config at n_seeds=16, payload_bits=4000.',
  'The harness RNG is seed-deterministic, so results are reproducible run-to-run.',
  '',
  'REFERENCE FRONTIER you must beat (MFSK-32, measured at the canonical settings):',
  '',
  'SANITY GATE (do this before trusting any result): run your modulate->demodulate with NO channel',
  '(pass the audio straight back to demodulate). Raw BER must be ~0. If it is not, your demod has a BUG —',
  'fix it before reporting. The prior campaign wasted two hypotheses on demod bugs; do not repeat that.',
  '',
  'Write your script to experiments/capacity/<file>.py and a results JSON to',
  'experiments/capacity/results/<id>.json. Keep shell output bounded (print only summary lines).',
].join('\n')

const REF_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['b0_net_bps', 'mfsk32_gross_bps', 'mfsk32_raw_ber', 'mfsk32_net_bps', 'mfsk32_mb_c90_stereo', 'mfsk32_p_full', 'n_seeds', 'payload_bits', 'deterministic_note'],
  properties: {
    b0_net_bps: { type: 'number' },
    mfsk32_gross_bps: { type: 'number' },
    mfsk32_raw_ber: { type: 'number' },
    mfsk32_net_bps: { type: 'number' },
    mfsk32_mb_c90_stereo: { type: 'number' },
    mfsk32_p_full: { type: 'number' },
    n_seeds: { type: 'integer' },
    payload_bits: { type: 'integer' },
    deterministic_note: { type: 'string' },
  },
}

const EXP_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['hypothesis_id', 'name', 'implemented_file', 'best_config', 'gross_bps', 'raw_ber',
    'erasure_rate', 'net_bps', 'mb_c90_stereo', 'p_full', 'ratio_vs_mfsk32', 'sanity_ber_noChannel',
    'verdict', 'bug_suspected', 'notes'],
  properties: {
    hypothesis_id: { type: 'string' },
    name: { type: 'string' },
    implemented_file: { type: 'string' },
    best_config: { type: 'string', description: 'human-readable description of the winning configuration' },
    gross_bps: { type: 'number' },
    raw_ber: { type: 'number' },
    erasure_rate: { type: 'number' },
    net_bps: { type: 'number' },
    mb_c90_stereo: { type: 'number' },
    p_full: { type: 'number' },
    ratio_vs_mfsk32: { type: 'number', description: 'net_bps / mfsk32 reference net_bps' },
    sanity_ber_noChannel: { type: 'number', description: 'raw BER of modulate->demodulate with NO channel; must be ~0' },
    verdict: { type: 'string', enum: ['ACCEPT', 'REJECT', 'INCONCLUSIVE'] },
    bug_suspected: { type: 'boolean' },
    notes: { type: 'string', description: 'what worked, the SNR/BER tradeoff observed, and honest caveats (<=120 words)' },
  },
}

// ---------------------------------------------------------------------------
// Phase 0 — reference anchor
// ---------------------------------------------------------------------------
phase('Reference')
const ref = await agent(
  PRIMER + '\n\n' +
  'TASK: Establish the reference anchor for the whole campaign.\n' +
  'Write experiments/capacity/c0_reference.py that:\n' +
  '  1. Measures the shipping BFSK baseline via hc.measure_baseline_B0(n_seeds=16, payload_bits=4000).\n' +
  '  2. Measures MFSK-32 (no FEC) at the canonical settings. Reuse the existing implementation in\n' +
  '     src/hyp_h2_mfsk.py (class MFSKScheme(M=32, walsh_k=0)) wrapped through hc.evaluate_scheme +\n' +
  '     hc.project_to_cassette. Do NOT rewrite the MFSK modem.\n' +
  '  3. Prints and saves both to experiments/capacity/results/c0_reference.json.\n' +
  'Return the MFSK-32 numbers (these anchor every later comparison) and B0 net_bps.\n' +
  'In deterministic_note, confirm whether re-running gives identical numbers (it should).',
  { label: 'c0:reference', phase: 'Reference', model: 'sonnet', schema: REF_SCHEMA, agentType: 'implementer' }
)

const REFLINE = ref
  ? ('MFSK-32 REFERENCE (beat this): gross_bps=' + ref.mfsk32_gross_bps.toFixed(0) +
     ', raw_ber=' + ref.mfsk32_raw_ber.toExponential(2) +
     ', net_bps=' + ref.mfsk32_net_bps.toFixed(1) +
     ', MB_C90_stereo=' + ref.mfsk32_mb_c90_stereo.toFixed(3) +
     ', P_full=' + ref.mfsk32_p_full.toFixed(2) +
     '. B0 baseline net_bps=' + ref.b0_net_bps.toFixed(1) + '.')
  : 'MFSK-32 REFERENCE: net_bps=1076 (cached; reference agent failed — use this fallback).'
const REFNET = ref ? ref.mfsk32_net_bps : 1076
log('Reference anchored: ' + REFLINE)

// ---------------------------------------------------------------------------
// Phase 1 — five hypotheses, parallel (barrier: synthesis needs all five)
// ---------------------------------------------------------------------------
phase('Experiments')

const EXPERIMENTS = [
  {
    id: 'C1', label: 'C1:gray-mfsk', model: 'sonnet',
    bar: 1.10,
    spec:
      'HYPOTHESIS C1 (SAFE BET): Gray-coded MFSK + operating-point / band re-tune.\n' +
      'Mechanism: most MFSK symbol errors are ADJACENT-tone confusions. The frontier maps symbol->bits\n' +
      'with plain binary; an adjacent-tone slip flips ~log2(M)/2 bits. GRAY-coding the symbol<->bits map\n' +
      'makes an adjacent slip flip exactly 1 bit, cutting raw BER ~2-3x. Since the frontier BER (2.1e-3)\n' +
      'sits just above the 1e-3 table knee, dropping below 1e-3 lifts the code rate 0.80->0.85 (and below\n' +
      '1e-4 -> 0.92). Also re-tune: (a) push the band up toward ~10.5 kHz, (b) sweep M in {16,32,64} and\n' +
      'the symbol period (try slightly longer T_sym than strict orthogonality for flutter margin).\n' +
      'Crib from src/hyp_h2_mfsk.py (MFSKScheme) but ADD a Gray permutation on the tone<->symbol mapping\n' +
      'in BOTH modulate and demodulate. Verify the no-channel sanity BER is ~0. Sweep, then confirm the\n' +
      'best (highest net_bps with P_full=1.0) at n_seeds=16, payload_bits=4000.\n' +
      'ACCEPT bar: net_bps >= 1.10x the MFSK-32 reference, P_full=1.0.',
  },
  {
    id: 'C2', label: 'C2:combinatorial-fsk', model: 'sonnet',
    bar: 1.25,
    spec:
      'HYPOTHESIS C2 (LIKELY): Combinatorial k-of-M multitone FSK (tone-index modulation).\n' +
      'Mechanism: instead of lighting ONE of M tones (log2(M) bits/symbol), light K of M tones at once,\n' +
      'carrying floor(log2(C(M,K))) bits/symbol. Demod stays non-coherent magnitude detection: pick the\n' +
      'K largest tone-bin energies. Map symbol<->K-subset with the combinatorial number system (a clean\n' +
      'bijection between integers in [0, C(M,K)) and K-subsets). Tradeoff to MEASURE: total symbol energy\n' +
      'is split across K tones, so per-tone SNR drops ~10*log10(K) dB -> BER rises with K. Find the (M,K)\n' +
      'that MAXIMISES net_bps while keeping P_full=1.0. Suggested grid: M in {16,24,32,48}, K in {1..6}.\n' +
      'Keep tones on an orthogonal grid (Olivia-style, T_sym=1/delta_f); reuse hc.make_preamble for sync.\n' +
      'No-channel sanity BER must be ~0 (validates the combinatorial bijection + top-K demod). Confirm\n' +
      'best at n_seeds=16, payload_bits=4000.\n' +
      'ACCEPT bar: net_bps >= 1.25x the MFSK-32 reference, P_full=1.0.',
  },
  {
    id: 'C3', label: 'C3:soft-decision', model: 'sonnet',
    bar: 1.15,
    spec:
      'HYPOTHESIS C3 (PLAUSIBLE): Soft-decision FEC credit — the projection table is too pessimistic.\n' +
      'Mechanism: project_to_cassette maps raw (hard) BER -> a conservative HARD-decision code rate. But\n' +
      'MFSK FFT bin energies are natively SOFT (reliability) information; a soft-decision decoder buys\n' +
      '~1.5-2 dB of coding gain, i.e. recovers the file at a HIGHER code rate than the hard table grants\n' +
      'for the SAME raw BER. Your job: PROVE this honestly by simulation, not by editing the table.\n' +
      'Concretely: (a) take MFSK-32 at the frontier operating point; (b) extract per-symbol soft metrics\n' +
      '(e.g. the gap between top-1 and top-2 bin energies as an LLR proxy); (c) actually encode the\n' +
      'payload with a real code (e.g. a rate-R convolutional code with Viterbi, or an LDPC/RS with\n' +
      'soft-input) and DECODE it soft, sweeping R upward until the post-FEC whole-file error just stays 0\n' +
      'over the Monte-Carlo seeds; (d) report the max R that holds vs the hard-table R at that same raw BER.\n' +
      'net_bps_soft = gross_bps * R_soft. Be rigorous: P_full=1.0 means ZERO residual errors across all\n' +
      'seeds at the chosen R. If soft decoding does NOT beat the hard table here, say so (REJECT is fine).\n' +
      'ACCEPT bar: net_bps >= 1.15x the MFSK-32 reference at the SAME measured raw BER, P_full=1.0.',
  },
  {
    id: 'C4', label: 'C4:bitloaded-ofdm', model: 'opus',
    bar: 1.25,
    spec:
      'HYPOTHESIS C4 (STRETCH): Bit-loaded OFDM-QAM (water-filling) + erasure on nulls.\n' +
      'Context: a PRIOR OFDM attempt (src/hyp_h3_ofdm.py) was REJECTED because FLAT loading gave a uniform\n' +
      '~9% raw BER that forced a rate-0.1 outer code. The fix to test: do NOT load all subcarriers equally.\n' +
      'Probe the per-subcarrier SNR (send a known pilot OFDM symbol through the channel, measure each bin),\n' +
      'then BIT-LOAD: assign QAM order per subcarrier from its SNR (water-filling / a gap-approximation\n' +
      'b_i = log2(1 + SNR_i/Gamma)), drop hopeless subcarriers to ZERO bits (and/or mark them erasures).\n' +
      'Strong subcarriers carry 4-6 bits, weak ones 1-2 or none, so the AGGREGATE raw BER stays low while\n' +
      'gross rises. Use a cyclic prefix for flutter/timing robustness and Gray-mapped QAM. Crib structure\n' +
      'from src/hyp_h3_ofdm.py but add the channel-probe + per-carrier loading. No-channel sanity BER ~0.\n' +
      'Confirm best at n_seeds=16, payload_bits=4000. This is hard DSP — get the FFT framing, CP, and\n' +
      'pilot-based equalisation right, and watch for the demod bug that sank the last OFDM attempt.\n' +
      'ACCEPT bar: net_bps >= 1.25x the MFSK-32 reference, P_full=1.0. An honest REJECT (channel error\n' +
      'eats the spectral efficiency even with loading) is a perfectly acceptable result.',
  },
  {
    id: 'C5', label: 'C5:ftn-packing', model: 'opus',
    bar: 1.50,
    spec:
      'HYPOTHESIS C5 (MOONSHOT): Faster-than-Nyquist / non-orthogonal signaling, or 2D tone-time index mod.\n' +
      'Pick the more promising of two speculative levers and test it honestly:\n' +
      '  (a) FTN tone packing: place MFSK tones CLOSER than the orthogonality spacing (delta_f < 1/T_sym)\n' +
      '      and/or shorten T_sym below 1/delta_f, accepting controlled inter-tone interference, then\n' +
      '      separate the tones with a short equaliser or a per-window least-squares / matched-filter bank\n' +
      '      that knows the (fixed) tone set. More bits per band-second IF the decoder can de-correlate.\n' +
      '  (b) 2D index modulation: jointly index over (which tone) x (which of several sub-slot positions /\n' +
      '      phase) to pack extra bits per symbol beyond log2(M).\n' +
      'Whatever you choose, keep it self-syncing (hc.make_preamble) and pass the no-channel sanity BER (~0).\n' +
      'Sweep the packing factor; find the most aggressive setting that still holds P_full=1.0 at canonical\n' +
      'settings. This is a moonshot: "no improvement possible" (the channel SNR/flutter floor forbids it)\n' +
      'is a fully acceptable, valuable outcome — report it plainly with the data that shows it.\n' +
      'ACCEPT bar: net_bps >= 1.50x the MFSK-32 reference, P_full=1.0.',
  },
]

const results = await parallel(EXPERIMENTS.map((e) => () =>
  agent(
    PRIMER + '\n\n' + REFLINE + '\n\n' + e.spec + '\n\n' +
    'Return the structured result. ratio_vs_mfsk32 = your best net_bps / ' + REFNET.toFixed(1) + '. ' +
    'Set verdict ACCEPT only if net_bps >= ' + e.bar + 'x reference AND p_full=1.0 AND sanity_ber_noChannel ~0. ' +
    'If your demod could not reach ~0 sanity BER, set bug_suspected=true and verdict=INCONCLUSIVE. ' +
    'Be scientifically honest — a clean REJECT backed by data is worth more than an inflated ACCEPT.',
    { label: e.label, phase: 'Experiments', model: e.model, schema: EXP_SCHEMA, agentType: 'implementer' }
  )
))

const good = results.filter(Boolean)
log('Experiments done: ' + good.length + '/5 returned. ' +
    good.map((r) => r.hypothesis_id + '=' + (r.net_bps ? r.net_bps.toFixed(0) : '?') + 'bps/' + r.verdict).join('  '))

// ---------------------------------------------------------------------------
// Phase 2 — synthesis / adjudication
// ---------------------------------------------------------------------------
phase('Synthesis')

const synthesis = await agent(
  'You are adjudicating a capacity-pushing campaign on a cassette data-storage modem.\n' +
  'The pre-registration (bars fixed BEFORE results) is in docs/capacity_pushing_hypotheses.md — READ IT.\n\n' +
  'Reference frontier (MFSK-32): ' + REFLINE + '\n\n' +
  'Here are the five experiment results (JSON):\n' +
  JSON.stringify(good, null, 2) + '\n\n' +
  'Also read each experiment\'s saved JSON + script under experiments/capacity/ to verify the numbers and\n' +
  'sanity-check for demod bugs (a result with non-trivial sanity_ber_noChannel, or net_bps that beats the\n' +
  'Shannon-ish expectation implausibly, is suspect -> mark INCONCLUSIVE, not ACCEPT).\n\n' +
  'Produce docs/capacity_pushing_results.md with:\n' +
  '  1. A scorecard table (# | hypothesis | mechanism | bar | measured net_bps | ratio | raw BER | P_full | verdict).\n' +
  '  2. For each hypothesis: 2-4 sentences on what the data showed and WHY (the SNR/BER/spectral tradeoff).\n' +
  '     Distinguish a FAIR reject (sound experiment, channel forbids it) from INCONCLUSIVE (suspected bug).\n' +
  '  3. The bottom line: what is the NEW best net_bps / MB-per-cassette, by how much it beats MFSK-32, and\n' +
  '     whether the gains STACK (e.g. Gray + combinatorial + soft, if independent). Give the stacked\n' +
  '     projection explicitly but label it as a projection, not a measurement, unless an agent measured it.\n' +
  '  4. A short "what would move the needle next" list grounded in the data.\n' +
  '  5. Caveats (simulation only, conservative table, etc.).\n' +
  'Be rigorous and skeptical. If the honest answer is "no improvement possible", say exactly that and show\n' +
  'the data. Return a concise plain-text executive summary (<=200 words) for the human, including the final\n' +
  'scorecard line per hypothesis and the new best MB/C90-stereo.',
  { label: 'synthesis', phase: 'Synthesis', model: 'opus', agentType: 'implementer' }
)

return {
  reference: ref,
  experiments: good,
  synthesis,
}
