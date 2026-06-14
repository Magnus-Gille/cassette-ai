export const meta = {
  name: 'real-channel-characterize-and-close-the-gap',
  description: 'Measure & document OUR real cassette channel from the saved captures (esp. the spectral-leakage/reverb term the sim lacks), map which modem configs actually survive real audio (validate M32), and fold the measured terms back into the simulator so it reproduces real behavior. All SW, no re-recording.',
  phases: [
    { title: 'Measure+Map', detail: 'characterize the real channel from captures; map modem survival incl M32 validation' },
    { title: 'Close-gap', detail: 'add measured terms to the sim channel; show it now predicts M16 failure / M32 survival; document' },
  ],
}

const ROOT = '/Users/magnus/repos/cassette-ai'
const DIR = ROOT + '/experiments/tape_v2'

const PRIMER = [
  'Repo ' + ROOT + ', branch tape-test-3. We have TWO real cassette captures (acoustic loop:',
  'laptop->tape->deck->speaker->iPhone Voice Memos->iCloud), both LOCAL + gitignored:',
  '  - ' + DIR + '/captures/tape3_run1.wav  : the master3 recording (deep-dive M16,K2 modem +',
  '      global RS interleave). master3_manifest.json. Decodes 0/3.',
  '  - ' + DIR + '/captures/voicememo_run1.wav : last night\'s master2 recording (the LADDER of OLD',
  '      configs: mfsk32, c1_gray_m16, c2_m32_k2, c2_m32_k4, c2_m48_k6). master2_manifest.json. Trim',
  '      to the master region first (content ~12s..1010s; full file is a 41-min over-run).',
  '',
  'ESTABLISHED (read experiments/tape_v2/REAL_DECODE_FINDINGS.md + m3_decode_v2.py + debug_m3.py FIRST):',
  '  * Both captures are CLEAN channel-wise: sounder ~40 dB SNR, ~0.3-0.44% flutter, clock recovered.',
  '  * The signal IS present (master3 frame0 symbol0 decodes byte-exact).',
  '  * master3\'s M16,K2 modem (N=77 samples/sym, tones ~1 FFT-bin / 623 Hz apart) is FUNDAMENTALLY',
  '    floored on real audio: a GENIE decoder (oracle symbol + best per-symbol timing + per-tone EQ)',
  '    still floors at bit-BER ~0.17-0.20. Root cause = SPECTRAL CONTAMINATION: short-window FFT skirts',
  '    + adjacent-symbol leakage smear energy across the closely-spaced bins; ~65% off-tone leakage',
  '    energy; EQ amplifies weak-bin contamination ~20x. NOT noise, NOT timing.',
  '  * m3_decode_v2.py has the hardened demod (FFT detection + sounder-H(f) per-tone EQ + wide-window',
  '    energy-concentration timing tracker + a GENIE-ceiling computation). analyze_master2.analyze_sounder',
  '    measures H(f)/SNR(f)/flutter. reedsolo installed. c2_combo_mfsk.ComboMFSKScheme is the combinatorial PHY.',
  '',
  'CRITICAL CONTEXT — the sim/real gap we are closing: src/channel.py (cassette_channel) models band-limit',
  '+ wow/flutter (time-warp) + AWGN + dropouts + speed offset. It DOES NOT model acoustic REVERB / room',
  'impulse response / spectral leakage / AAC artifacts — the very things that contaminate adjacent tone bins',
  'and killed M16. That omission is WHY sim loved short-symbol M16 (more rate) while real audio punishes it.',
  'The durable fix the user wants: MEASURE these real-channel effects and DOCUMENT them so future sims',
  'include them.',
  'Keep shell output bounded.',
].join('\n')

// ---------------------------------------------------------------------------
phase('Measure+Map')

const CHAR_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['doc_file', 'params_file', 'hf_rolloff_db', 'flutter_pct', 'offtone_leakage_frac', 'key_findings'],
  properties: {
    doc_file: { type: 'string' }, params_file: { type: 'string' },
    hf_rolloff_db: { type: 'number', description: 'HF rolloff of H(f) across the usable band, dB' },
    flutter_pct: { type: 'number' },
    offtone_leakage_frac: { type: 'number', description: 'measured energy leaking outside the lit tones (0..1) — the contamination the sim lacks' },
    key_findings: { type: 'string', description: '<=150 words: the measured real-channel params + the leakage/reverb finding' },
  },
}

const MAP_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['results_file', 'configs', 'best_real_config', 'm32_validated', 'notes'],
  properties: {
    results_file: { type: 'string' },
    configs: { type: 'array', description: 'per modem config measured on the master2 real capture',
      items: { type: 'object', additionalProperties: false,
        required: ['config', 'N_samples', 'raw_ber', 'genie_ber', 'rs_closable'],
        properties: { config: { type: 'string' }, N_samples: { type: 'integer' },
          raw_ber: { type: 'number' }, genie_ber: { type: 'number' },
          rs_closable: { type: 'boolean', description: 'genie/raw BER low enough for a robust RS (rate ~0.5) to close to byte-exact?' } } } },
    best_real_config: { type: 'string', description: 'the config that best survives OUR real channel + why' },
    m32_validated: { type: 'boolean', description: 'does M32,K2 (N=159) decode our real audio markedly better than M16 / RS-closable?' },
    notes: { type: 'string' },
  },
}

const measured = await parallel([
  () => agent(
    PRIMER + '\n\n' +
    'TASK A — characterize and DOCUMENT our real channel. Using BOTH captures (run the sounder via\n' +
    'analyze_master2.analyze_sounder; analyze tone segments directly), measure and write up:\n' +
    '  1. H(f) magnitude across 300-11000 Hz (the HF rolloff — m3_decode_v2 noted ~26 dB). Per-tone SNR(f).\n' +
    '  2. Flutter %, noise floor, clock offset (Voice-Memos ~1.0 vs the prior 0.88x Continuity path).\n' +
    '  3. THE KEY NEW TERM the sim lacks: SPECTRAL CONTAMINATION / inter-symbol + reverb leakage. Quantify\n' +
    '     it: for known-lit-tone symbols, what fraction of energy lands OUTSIDE the lit tones / in adjacent\n' +
    '     bins? How does it scale with symbol length (compare M16/N=77 vs M32/N=159 segments)? Estimate an\n' +
    '     effective reverb tail / leakage coefficient. This is the durable finding.\n' +
    'Write docs/REAL_CHANNEL.md (human writeup: every measured parameter of OUR physical channel, with the\n' +
    'leakage/reverb finding front and center, and a "how to add this to the simulator" section) and a\n' +
    'machine-readable experiments/tape_v2/real_channel_params.json. Return the structured result.',
    { label: 'characterize', phase: 'Measure+Map', model: 'opus', schema: CHAR_SCHEMA, agentType: 'implementer' }
  ),
  () => agent(
    PRIMER + '\n\n' +
    'TASK B — map which modem configs survive OUR real channel (validate the M32 re-tier). On the master2\n' +
    'real capture (captures/voicememo_run1.wav, trimmed to the master region; master2_manifest.json), run\n' +
    'the HARDENED demod approach from m3_decode_v2.py (FFT-bin detection + sounder-H(f) per-tone EQ +\n' +
    'wide-window energy-concentration timing tracker) AND the GENIE ceiling on each modem config that is\n' +
    'present: mfsk32, c1_gray_m16, c2_m32_k2 (M32,N=159 — THE candidate), c2_m32_k4, c2_m48_k6. For each,\n' +
    'report N (samples/symbol), measured raw BER, genie-ceiling BER, and whether a robust RS (rate ~0.5,\n' +
    'corrects ~25% symbols) would close it to byte-exact. The decisive comparison: does the longer-symbol\n' +
    'M32,K2 (N=159, ~302 Hz bins) decode markedly better than M16 (N=77) — i.e. is its genie/raw BER\n' +
    'clearly RS-closable (≲0.10), validating a master4 re-tier? Also test whether even-longer symbols help.\n' +
    'Write results to experiments/tape_v2/results/real_modem_survival.json. Return the structured result\n' +
    'with an honest best_real_config recommendation for master4.',
    { label: 'survival-map', phase: 'Measure+Map', model: 'opus', schema: MAP_SCHEMA, agentType: 'implementer' }
  ),
])

const charR = measured[0]
const mapR = measured[1]
const measuredLine =
  'REAL-CHANNEL MEASURED: ' + (charR ? ('HF rolloff ' + charR.hf_rolloff_db + 'dB, flutter ' + charR.flutter_pct +
    '%, off-tone leakage ' + charR.offtone_leakage_frac + ' (the sim-missing term). doc=' + charR.doc_file) : 'TASK A FAILED') + '\n' +
  'MODEM SURVIVAL: ' + (mapR ? ('best real config = ' + mapR.best_real_config + '; M32 validated=' + mapR.m32_validated + '. ' +
    (mapR.configs || []).map((c) => c.config + '(N' + c.N_samples + ' ber' + (c.raw_ber ?? 0).toFixed(2) + '/genie' + (c.genie_ber ?? 0).toFixed(2) + (c.rs_closable ? ' RS-OK' : '') + ')').join(' ')) : 'TASK B FAILED')
log(measuredLine)

// ---------------------------------------------------------------------------
phase('Close-gap')

const closer = await agent(
  PRIMER + '\n\n' + measuredLine + '\n\n' +
  'The real channel is now measured (docs/REAL_CHANNEL.md + real_channel_params.json) and the modem-survival\n' +
  'map is in results/real_modem_survival.json. Read both.\n\n' +
  'TASK — CLOSE THE SIM/REAL GAP and document it:\n' +
  '1. Extend the simulator with the measured real-channel terms it currently lacks — above all a\n' +
  '   SPECTRAL-LEAKAGE / acoustic-reverb / inter-symbol-contamination term (a short room-impulse-response\n' +
  '   convolution and/or an adjacent-bin energy-bleed), plus the measured H(f) HF rolloff. Put it in a NEW\n' +
  '   module experiments/tape_v2/real_channel_sim.py (a wrapper over cs.full_chain / src/channel.py — do\n' +
  '   NOT break the frozen channel.py) parameterized from real_channel_params.json.\n' +
  '2. VALIDATE the improved sim reproduces reality: show that pushing master3\'s M16,K2 modem through the\n' +
  '   IMPROVED sim now yields a genie/real BER ~matching the measured real failure (~0.17-0.20, RS-uncloseable),\n' +
  '   whereas the OLD sim wrongly predicted success. And that M32,K2 survives the improved sim consistent\n' +
  '   with TASK B\'s real measurement. I.e. the improved sim would have PREDICTED the M16 failure.\n' +
  '3. Using the improved sim, recommend the master4 modem config (likely M32,K2 or whatever TASK B found\n' +
  '   most real-robust) and the robust-rung RS rate that closes it — the config to record next time.\n' +
  '4. Update docs/REAL_CHANNEL.md with the "improved simulator" section (what was added, the validation\n' +
  '   numbers showing sim-now-matches-real, and the master4 recommendation) and append a short note to\n' +
  '   docs/ROADMAP.md. Commit is handled by the parent; just write the files.\n' +
  'Return a concise plain-text summary (<=200 words): the measured real-channel params (esp. the leakage\n' +
  'term), the modem-survival verdict (is M32 the answer?), proof the improved sim now predicts M16 failure,\n' +
  'and the concrete master4 recommendation.',
  { label: 'close-gap', phase: 'Close-gap', model: 'opus', agentType: 'implementer' }
)

return { characterize: charR, survival: mapR, close_gap: closer }
