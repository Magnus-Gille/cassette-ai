export const meta = {
  name: 'acoustic-assault-plus-wired',
  description: 'Fight hard for the phone-next-to-speaker acoustic path using the now-FAITHFUL sim: creative robust PHYs (wide-spaced+guard tones, chirp spread-spectrum, close-coupling sensitivity), AND validate the wired/electrical path. Find a config that the faithful sim says actually survives real tape.',
  phases: [
    { title: 'Explore', detail: 'wide-spacing+guard, chirp spread-spectrum, close-coupling sensitivity, wired path — all on the faithful sim' },
    { title: 'Synthesize', detail: 'adjudicate; recommend the acoustic master4 PHY + the wired plan' },
  ],
}

const ROOT = '/Users/magnus/repos/cassette-ai'
const DIR = ROOT + '/experiments/tape_v2'

const PRIMER = [
  'Repo ' + ROOT + ', branch tape-test-3. GOAL: do NOT give up on the acoustic "phone next to the',
  'speaker" path — find a modulation that actually survives our REAL cassette channel, using the now-',
  'FAITHFUL simulator. Be creative and rigorous; honesty is the whole value of this project.',
  '',
  'THE FAITHFUL SIM (use this for all ACOUSTIC tests): experiments/tape_v2/real_channel_sim.py wraps the',
  'frozen src/channel.py and ADDS the measured real-channel contamination (diffuse reverb/leakage tail,',
  'measured H(f) HF rolloff, adjacent-bin smear), parameterized from experiments/tape_v2/real_channel_params.json.',
  'It is VALIDATED: it reproduces the real M16 failure (genie byte-ER ~0.36) that the old clean sim wrongly',
  'blessed. So a config that survives THIS sim should survive real tape. Read REAL_CHANNEL.md +',
  'REAL_DECODE_FINDINGS.md + real_channel_sim.py FIRST.',
  '',
  'WHAT WE KNOW (the wall): noise is fine (~40 dB), bulk timing handled. The killer is SPECTRAL',
  'CONTAMINATION — energy smearing into ADJACENT tone bins — worst for closely-spaced (1-bin) tones, and',
  'partly TIME-VARYING (flutter ~5 Hz; channel non-reproducible over seconds, so one-shot EQ/calibration is',
  'dead — proven). Every scheme tried so far packs tones ~1 bin apart (M16-M48) and all fail; the genie',
  'ceiling itself floors at ~0.17-0.20 bit-BER for M16. The robust RS(255,127) closes ~25% byte errors.',
  '',
  'METHODOLOGY (mandatory): (1) no-channel sanity BER ~0 first (catch demod bugs). (2) Evaluate through',
  'real_channel_sim.py. (3) Report BOTH the genie ceiling (oracle symbol + best per-symbol timing + EQ) AND',
  'the achievable (real tracker) BER, and whether a robust interleaved RS (rate ~0.5) closes it to byte-exact.',
  'A config only "works" if the ACHIEVABLE path is RS-closable, not just the genie. Reuse: m3_codec.py (RS +',
  'global interleave), m3_decode_v2.py (hardened FFT demod + genie ceiling), c2_combo_mfsk.ComboMFSKScheme,',
  'src/hyp_h4_css.py (the buggy chirp attempt — fix or rewrite), dd_common timing tracker. reedsolo installed.',
  'Keep shell output bounded.',
].join('\n')

phase('Explore')

const SCHEME_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['name', 'module_file', 'best_config', 'sanity_ber', 'genie_ber', 'achievable_ber', 'rs_closable_achievable', 'net_bps', 'verdict', 'notes'],
  properties: {
    name: { type: 'string' }, module_file: { type: 'string' },
    best_config: { type: 'string' },
    sanity_ber: { type: 'number' }, genie_ber: { type: 'number' }, achievable_ber: { type: 'number' },
    rs_closable_achievable: { type: 'boolean', description: 'does the ACHIEVABLE (non-genie) decode close to byte-exact under a robust interleaved RS in the faithful sim?' },
    net_bps: { type: 'number', description: 'projected net bps if it works (0 if it does not)' },
    verdict: { type: 'string', enum: ['SURVIVES', 'PARTIAL', 'FAILS'] },
    notes: { type: 'string', description: '<=120 words: what worked, the key tradeoff, honest caveats' },
  },
}

const results = await parallel([
  // A — wide-spaced tones + guard bands + differential detection
  () => agent(
    PRIMER + '\n\n' +
    'HYPOTHESIS A — WIDE-SPACED tones + guard bands (attack the adjacent-bin contamination directly).\n' +
    'Instead of cramming tones 1 FFT-bin apart, use FEWER tones spaced 3-8 bins apart with EMPTY guard bins\n' +
    'between them, so the smear/leakage lands in guards (ignored) not in neighbour data tones. Also try a\n' +
    'DIFFERENTIAL/contrast detector (a lit tone vs its own adjacent guard bin) instead of absolute top-K.\n' +
    'Build experiments/tape_v2/assault_widespace.py. Sweep: tone count M, guard width (bins between tones),\n' +
    'symbol length N (longer N -> finer bins -> more room for guards), and K (lit tones; K<=2 is the proven\n' +
    'viable regime). Find the config with the best ACHIEVABLE RS-closable net_bps in the faithful sim.\n' +
    'ALSO: for your best config, sweep the sim contamination/reverb parameter DOWN (simulating "phone jammed\n' +
    'against the speaker" / a blanket reducing reverb) and report the threshold at which it becomes RS-closable\n' +
    '— i.e. how much physical close-coupling would be needed. Return the structured result.',
    { label: 'A:wide-space', phase: 'Explore', model: 'opus', schema: SCHEME_SCHEMA, agentType: 'implementer' }
  ),
  // B — chirp spread spectrum (the wildcard)
  () => agent(
    PRIMER + '\n\n' +
    'HYPOTHESIS B — CHIRP SPREAD-SPECTRUM (LoRa/CSS-style) — the wildcard, theoretically ideal for our\n' +
    'channel. Each symbol is a linear frequency sweep (chirp) over the usable band; data is encoded in the\n' +
    'cyclic SHIFT of the chirp. Detection: multiply by the conjugate base chirp ("dechirp") then FFT -> a\n' +
    'single peak whose bin = the data symbol. WHY it should beat tone schemes here: the energy is SPREAD over\n' +
    'the WHOLE band, so frequency-selective contamination / nulls / adjacent-bin smear corrupt only PART of\n' +
    'each symbol (processing gain averages it out), and the chirp is intrinsically robust to timing/doppler\n' +
    '(flutter). This is the modulation built for multipath+doppler. Our src/hyp_h4_css.py attempt was buggy\n' +
    '(BER ~0.5) and never given a fair shot — FIX it or rewrite cleanly in experiments/tape_v2/assault_css.py.\n' +
    'Sweep the spreading factor (chirp length / bandwidth-time product) for the best ACHIEVABLE RS-closable\n' +
    'net_bps in the faithful sim. Get the no-channel sanity BER to ~0 FIRST (that is where H4 failed). This\n' +
    'is the most important creative angle — give it your best shot. Return the structured result.',
    { label: 'B:chirp-ss', phase: 'Explore', model: 'opus', schema: SCHEME_SCHEMA, agentType: 'implementer' }
  ),
  // C — wired / electrical path
  () => agent(
    PRIMER + '\n\n' +
    'HYPOTHESIS C — THE WIRED / ELECTRICAL path (do this in parallel; the user wants it too). Model the\n' +
    'electrical line-in chain: deck line-out -> USB interface -> lossless PCM. This REMOVES the acoustic hop\n' +
    '(room reverb, speaker+mic response, AAC compression) but KEEPS the tape physics (band-limit ~12-15 kHz,\n' +
    'wow/flutter ~0.3%, tape-hiss SNR ~48-55 dB for a decent deck, dropouts). So it is essentially the OLD\n' +
    'clean sim (which was electrical-ish all along) WITHOUT the acoustic contamination real_channel_sim adds.\n' +
    'Build experiments/tape_v2/assault_wired.py: a wired channel model (src/channel.py good/pristine preset\n' +
    '+ realistic tape flutter, NO acoustic contamination term) and validate the HIGH-RATE configs on it:\n' +
    'the C4 bit-loaded OFDM (sim frontier 3968 bps), C2 combinatorial (2412), and the M16/M32 tracked combos.\n' +
    'Confirm which survive (genie + achievable + RS), and project net bps + MB/C90 (stereo x2 is available on\n' +
    'the wired path!). Document the hardware (e.g. Behringer UCA222 ~EUR30) and the recommended WIRED master\n' +
    'config. Return the structured result (best_config = the wired master recommendation, net_bps = its\n' +
    'projected net).',
    { label: 'C:wired', phase: 'Explore', model: 'opus', schema: SCHEME_SCHEMA, agentType: 'implementer' }
  ),
])

const good = results.filter(Boolean)
const summary = good.map((r) => r.name + ': ' + r.verdict + ' (' + r.best_config + ', genie ' + (r.genie_ber ?? 0).toFixed(3) +
  ', achievable ' + (r.achievable_ber ?? 0).toFixed(3) + ', RS-closable=' + r.rs_closable_achievable + ', net ' + Math.round(r.net_bps || 0) + ' bps)').join('\n')
log('Explore done:\n' + summary)

phase('Synthesize')

const synth = await agent(
  'You are adjudicating a creative campaign to make data recoverable off a REAL cassette, both ACOUSTIC\n' +
  '(phone next to speaker) and WIRED. The faithful simulator real_channel_sim.py reproduces the real\n' +
  'acoustic contamination (validated). Three approaches were tested (results below + their JSONs/scripts in\n' +
  'experiments/tape_v2/). Read REAL_CHANNEL.md, REAL_DECODE_FINDINGS.md, and each assault_*.py + results.\n\n' +
  'Results:\n' + JSON.stringify(good, null, 2) + '\n\n' +
  'Adjudicate rigorously (genie vs ACHIEVABLE; RS-closable on the achievable path is the bar; verify no\n' +
  'demod bug inflated a SURVIVES verdict via the no-channel sanity BER). Produce docs/ACOUSTIC_ASSAULT.md:\n' +
  '  1. Scorecard: each approach (wide-space, chirp-SS, wired) — genie BER, achievable BER, RS-closable?,\n' +
  '     net bps, verdict.\n' +
  '  2. THE ACOUSTIC VERDICT: is there now a phone-next-to-speaker PHY the faithful sim says SURVIVES (byte-\n' +
  '     exact via RS on the achievable path)? If yes, name the exact master4 config + projected net bps +\n' +
  '     MB/C90, and how much (if any) physical close-coupling it needs. If no, say so plainly and give the\n' +
  '     closest miss + what it would take.\n' +
  '  3. THE WIRED VERDICT: the recommended wired config + projected capacity + the ~EUR30 hardware.\n' +
  '  4. Recommendation: the single best next physical step for EACH path (acoustic master4, wired setup).\n' +
  'Append a dated entry to docs/ROADMAP.md and update REAL_DECODE_FINDINGS.md. Be honest and specific; a\n' +
  'data-backed "acoustic now works with config X" or "acoustic still falls short, wired is the route" are\n' +
  'both fine — say which the data supports. Return a concise plain-text executive summary (<=220 words):\n' +
  'does the acoustic path live (and how), the wired verdict, and the concrete next step for each.',
  { label: 'synthesize', phase: 'Synthesize', model: 'opus', agentType: 'implementer' }
)

return { explore: good, synthesis: synth }
