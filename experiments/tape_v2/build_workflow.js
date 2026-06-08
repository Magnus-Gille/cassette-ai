export const meta = {
  name: 'tape-v2-frontier-master',
  description: 'Build a self-describing ~16-18 min tape test master that exercises the capacity-campaign winners (MFSK/Gray, combinatorial k-of-M, bit-loaded OFDM) as a robustness LADDER on a real cassette, plus analyzer + record instructions. Validated byte-exact clean and through a simulated harsh deck.',
  phases: [
    { title: 'Modems', detail: '3 modem adapters (index/Gray, combinatorial, OFDM) behind one frozen interface, each self-tested' },
    { title: 'Master', detail: 'Assemble master2.wav ladder + manifest + payload sidecars; validate clean byte-exact' },
    { title: 'Analyzer', detail: 'analyze_master2.py + RECORD_ME.md; validate through simulated harsh/0.88-clock channel' },
  ],
}

const ROOT = '/Users/magnus/repos/cassette-ai'
const DIR = ROOT + '/experiments/tape_v2'

// ---------------------------------------------------------------------------
// Frozen interface + ground-truth context shared by every agent.
// ---------------------------------------------------------------------------
const PRIMER = [
  'PROJECT: cassette data-storage. We are building a PHYSICAL tape test (record a WAV to a real',
  'cassette deck, play it back, capture it, decode + byte-compare). Work in ' + DIR + ' .',
  '',
  'BACKGROUND — the capacity campaign (just completed, simulation only, channel "normal" = 42 dB SNR,',
  '11 kHz, 0.10% wow/flutter) produced these winners, measured net bps:',
  '  - MFSK-32 (frontier anchor):            net 1076 bps   src/hyp_h2_mfsk.py MFSKScheme(M=32)',
  '  - C1 Gray-MFSK M=16, 400-7000 Hz:       net 1209 bps   experiments/capacity/c1_gray_mfsk.py',
  '  - C2 combinatorial k-of-M FSK:          net 2412 bps   experiments/capacity/c2_combo_mfsk.py  (M=48,K=6 best)',
  '  - C4 bit-loaded OFDM-QAM:                net 3968 bps   experiments/capacity/c4_ofdm_bitload.py',
  'REUSE the DSP in those scripts — do not reinvent the modems. Import or copy their core.',
  '',
  'CRITICAL REALITY: the REAL cassette acoustic loop (laptop->tape->deck->speaker->iPhone mic), measured',
  'in experiments/dpd/channel_model.json + channel_summary.json, is MUCH harsher than the sim:',
  '  clock ~0.88x (huge steady speed offset), flutter ~2.2%, per-carrier SNR median ~12.6 dB',
  '  (p10 ~7.7 dB), ~11% of carriers < 8 dB, real frequency-selective NULLS, IMD floor ~-10.5 dB.',
  'So the aggressive configs (C2 K=6, C4 QPSK) may NOT survive the real loop. That is EXPECTED and is',
  'the point: we ship a LADDER (robust -> aggressive) so the recording reveals where each method really',
  'breaks. "This config fails on real tape" is a valid, valuable result.',
  '',
  'FROZEN MODEM INTERFACE — every modem module MUST expose exactly this (so the assembler + analyzer',
  'can call any modem uniformly). Python, @48 kHz, float32:',
  '',
  '    SR = 48000',
  '    CONFIGS = { "<config_name>": {<params>}, ... }   # ordered robust -> aggressive',
  '    def modulate(payload: bytes, config: str) -> np.ndarray:',
  '        # returns float32 @48k = [0.25s chirp preamble via hc.make_preamble(0.25)] + [framed-payload symbols],',
  '        # peak-normalized to 0.70. Frame the payload with the CANONICAL frame below before mapping to symbols.',
  '    def demodulate(audio: np.ndarray, config: str) -> bytes | None:',
  '        # audio @48k, ALREADY globally resampled to ~nominal speed by the analyzer. Do LOCAL fine sync via',
  '        # hc.find_preamble(audio,0.25). Recover bytes, verify the canonical frame; return payload bytes if the',
  '        # CRC checks, else None. Never raise.',
  '',
  'CANONICAL FRAME (identical in all modems; use struct + zlib):',
  '    import struct, zlib',
  '    MAGIC = b"CA"',
  '    frame = MAGIC + struct.pack(">H", len(payload)) + payload + struct.pack(">I", zlib.crc32(payload))',
  '    # demod: read 2-byte magic (must == b"CA"), 2-byte length L, L payload bytes, 4-byte CRC32; verify; else None.',
  'Map frame bytes -> bits MSB-first -> symbols. Keep sections SHORT (payloads ~64-110 bytes) so intra-section',
  'drift stays small; that is what makes them survive the real deck.',
  '',
  'Harness import bootstrap (the modems reuse hc.make_preamble / hc.find_preamble for a COMMON chirp sync):',
  '    import sys, pathlib',
  '    ROOT = pathlib.Path("' + ROOT + '")',
  '    for p in ["src","tests/e2e"]: sys.path.insert(0, str(ROOT/p))',
  '    import hyp_common as hc',
  '',
  'For sim self-tests, push audio through: import capture_scenarios as cs;',
  '    rx, sr, diag = cs.full_chain(audio, tape_preset, "usb_soundcard", speed_offset=OFF, seed=s)',
  'Use tape_preset in {"normal","worn"} and speed_offset in {0.0, -0.12} (-0.12 ~ emulates the 0.88x deck clock;',
  'your demod sees this only AFTER the analyzer resamples, but in your OWN self-test apply a global resample-to-',
  'nominal step first to mimic the analyzer, then decode). Keep shell output bounded (summary lines only).',
].join('\n')

const MODEM_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['module_file', 'configs', 'clean_roundtrip_ok', 'per_config', 'notes'],
  properties: {
    module_file: { type: 'string' },
    configs: { type: 'array', items: { type: 'string' }, description: 'config names exposed, robust->aggressive' },
    clean_roundtrip_ok: { type: 'boolean', description: 'every config decodes byte-exact with NO channel' },
    per_config: {
      type: 'array',
      description: 'one row per config',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['config', 'gross_bps', 'normal_passrate', 'worn_passrate'],
        properties: {
          config: { type: 'string' },
          gross_bps: { type: 'number' },
          normal_passrate: { type: 'number', description: 'frac of seeds decoding byte-exact through sim normal' },
          worn_passrate: { type: 'number', description: 'frac decoding byte-exact through sim worn + speed_offset=-0.12' },
        },
      },
    },
    notes: { type: 'string', description: '<=100 words: what survives, what breaks, honest caveats' },
  },
}

// ---------------------------------------------------------------------------
// Phase 1 — three modem adapters in parallel (barrier: assembler needs all 3)
// ---------------------------------------------------------------------------
phase('Modems')

const MODEMS = [
  { id: 'index', label: 'modem:index/gray', model: 'sonnet', file: 'modems_index.py',
    spec:
      'BUILD modems_index.py exposing the frozen interface for the single-tone index-modulation ladder:\n' +
      '  CONFIGS (robust -> aggressive):\n' +
      '    "mfsk32"      : plain MFSK-32 (the anchor), reuse src/hyp_h2_mfsk.py MFSKScheme(M=32, walsh_k=0).\n' +
      '    "c1_gray_m16" : Gray-coded MFSK M=16 over 400-7000 Hz, reuse experiments/capacity/c1_gray_mfsk.py.\n' +
      'Wrap each so modulate(payload,config) frames the payload (canonical frame) -> bits -> the scheme\'s\n' +
      'symbols WITH the hc.make_preamble(0.25) chirp in front; demodulate(audio,config) does find_preamble sync,\n' +
      'recovers bits, parses+CRC-checks the frame, returns payload or None.\n' +
      'mfsk32 is the MUST-PASS reference: it should have the highest worn_passrate.',
  },
  { id: 'combo', label: 'modem:combinatorial', model: 'sonnet', file: 'modems_combo.py',
    spec:
      'BUILD modems_combo.py exposing the frozen interface for the combinatorial k-of-M multitone FSK ladder.\n' +
      'Reuse the DSP (combinatorial-number-system bijection + exact-FFT-bin tones + top-K magnitude demod) from\n' +
      'experiments/capacity/c2_combo_mfsk.py.\n' +
      '  CONFIGS (robust -> aggressive):\n' +
      '    "c2_m32_k2" : M=32, K=2  (~9 bits/sym, robust)\n' +
      '    "c2_m32_k4" : M=32, K=4  (15 bits/sym, mid)\n' +
      '    "c2_m48_k6" : M=48, K=6  (23 bits/sym, the C2 winner, aggressive)\n' +
      'Each config: modulate frames payload (canonical frame) -> bits -> k-of-M symbols with the chirp preamble;\n' +
      'demodulate syncs, top-K detect, inverse-combinatorial -> bits -> frame -> CRC -> payload or None.\n' +
      'Expect K=6 to degrade most on worn; K=2 to be robust. Report the honest passrate spread.',
  },
  { id: 'ofdm', label: 'modem:ofdm', model: 'opus', file: 'modems_ofdm.py',
    spec:
      'BUILD modems_ofdm.py exposing the frozen interface for the OFDM ladder (the headline + the transfer test).\n' +
      'Reuse the OFDM engine (short FFT N=256, CP, Gray-QAM, pilot-based per-subcarrier equalization, wide\n' +
      'acquisition + incremental per-symbol timing tracking) from experiments/capacity/c4_ofdm_bitload.py.\n' +
      '  CONFIGS (robust -> aggressive):\n' +
      '    "c4_bpsk"      : uniform BPSK on all data subcarriers (most robust; receiver equalizes via pilots,\n' +
      '                     NO TX bit-loading needed).\n' +
      '    "c4_qpsk"      : uniform QPSK on all data subcarriers.\n' +
      '    "c4_realmodel" : bit-load per subcarrier from the REAL measured deck profile in\n' +
      '                     experiments/dpd/channel_model.json (snr_freq/snr_db) via a gap-approx; weak/null\n' +
      '                     subcarriers -> 0 bits. This is the same-deck, real-measurement loading.\n' +
      '    "c4_simloaded" : the as-built SIM-trained loading from c4_ofdm_bitload.py (frozen sim SNR map).\n' +
      '                     This is the explicit sim->real TRANSFER test; it may well fail on the real null\n' +
      '                     structure. Document that.\n' +
      'Add a small RS or repetition inner-protection ONLY if needed to make c4_bpsk robust; keep frames\n' +
      'canonical. modulate prepends the chirp preamble. demodulate must be robust to the residual timing the\n' +
      'analyzer leaves after global resampling. This is the hardest module — get CP/pilot equalization right and\n' +
      'PASS the no-channel sanity (clean byte-exact) before anything else.',
  },
]

const modemResults = await parallel(MODEMS.map((m) => () =>
  agent(
    PRIMER + '\n\n' + m.spec + '\n\n' +
    'Write the module to ' + DIR + '/' + m.file + ' and a self-test that, for EACH config: (1) proves clean\n' +
    'byte-exact round-trip (no channel) on a ~96-byte payload; (2) measures normal_passrate over >=8 seeds\n' +
    'through cs.full_chain("normal", speed_offset=0.0) and worn_passrate over >=8 seeds through\n' +
    'cs.full_chain("worn", speed_offset=-0.12) WITH a global resample-to-nominal step before decode (mimicking\n' +
    'the analyzer). Pass = frame CRC matches AND payload byte-exact. Return the structured result. If clean\n' +
    'round-trip is not byte-exact for a config, FIX it before reporting (that is a bug, not a channel result).',
    { label: m.label, phase: 'Modems', model: m.model, schema: MODEM_SCHEMA, agentType: 'implementer' }
  )
))

const modems = modemResults.filter(Boolean)
log('Modems built: ' + modems.map((r) => r.module_file.split('/').pop() + (r.clean_roundtrip_ok ? ' OK' : ' CLEAN-FAIL')).join('  '))
const modemSummary = modems.map((r) =>
  r.module_file.split('/').pop() + ': ' + (r.per_config || []).map((c) =>
    c.config + '(gross' + Math.round(c.gross_bps) + ' norm' + (c.normal_passrate ?? 0).toFixed(2) + ' worn' + (c.worn_passrate ?? 0).toFixed(2) + ')').join(' ')
).join('\n')

// ---------------------------------------------------------------------------
// Phase 2 — assemble the master
// ---------------------------------------------------------------------------
phase('Master')

const master = await agent(
  PRIMER + '\n\nThe three modem modules are built and self-tested. Their per-config sim pass-rates:\n' +
  modemSummary + '\n\n' +
  'TASK: Build the recordable test master. Write ' + DIR + '/make_master2.py that assembles ' + DIR + '/master2.wav\n' +
  '(target 16-18 minutes), ' + DIR + '/master2_manifest.json (SR, tx_chirp0/tx_chirp1 sample offsets, and a\n' +
  'sections[] list: each {kind, config, rep, start_sample, length, payload_sidecar}), and per-section payload\n' +
  'sidecars (the exact known bytes) under ' + DIR + '/sidecars/.\n\n' +
  'LAYOUT (all self-locating; two global sync chirps bracket everything, ~1s lead/tail, ~0.4s gaps):\n' +
  '  1. Lead silence + global up-chirp anchor (reuse the make_sounder/master_lib chirp from experiments/dpd if\n' +
  '     convenient, else hc.make_preamble-style chirp). Record its offset as tx_chirp0.\n' +
  '  2. SOUNDER (~45s): a multitone probe across ~300-11000 Hz + a steady tone (~6s) + silence (~2s) so the\n' +
  '     analyzer can FRESHLY measure THIS recording\'s real H(f), SNR(f), flutter and global clock. Reuse\n' +
  '     experiments/dpd/make_sounder.py helpers if available.\n' +
  '  3. LADDER, robust -> aggressive, each config repeated R times with a fixed known per-section payload\n' +
  '     (e.g. "CASSETTE-AI v2 | <config> rep<r> | <some quotable text + 0-9 digits>", ~96 bytes). Order the\n' +
  '     sections by ascending aggressiveness across ALL modules so a deck that fades partway still captures the\n' +
  '     robust configs cleanly. Configs to include (call the modems via their CONFIGS):\n' +
  '       index:  mfsk32, c1_gray_m16\n' +
  '       combo:  c2_m32_k2, c2_m32_k4, c2_m48_k6\n' +
  '       ofdm:   c4_bpsk, c4_qpsk, c4_realmodel, c4_simloaded\n' +
  '     Pick R per config (more reps for the robust anchors, e.g. R~10-14; fewer for aggressive, R~8) to land\n' +
  '     the total at 16-18 min. Interleave reps so a localized tape dropout does not wipe all reps of one config.\n' +
  '  4. Trailing global down-chirp anchor (record offset tx_chirp1) + tail silence.\n' +
  '  Final mix peak-normalized to ~0.95.\n\n' +
  'VALIDATION GATE (must pass before returning): re-read master2.wav, and using the manifest + each modem\'s\n' +
  'demodulate, decode EVERY section directly (no channel) and assert byte-exact == its sidecar. Print a census:\n' +
  'duration, #sections per config, gross bps per config, total payload bytes. Return a concise summary string\n' +
  '(duration, section counts, and confirmation that clean decode is 100% byte-exact).',
  { label: 'make-master', phase: 'Master', model: 'sonnet', agentType: 'implementer' }
)
log('Master assembled: ' + (master ? String(master).slice(0, 300) : 'FAILED'))

// ---------------------------------------------------------------------------
// Phase 3 — analyzer + record instructions
// ---------------------------------------------------------------------------
phase('Analyzer')

const analyzer = await agent(
  PRIMER + '\n\nThe master (master2.wav + master2_manifest.json + sidecars/) is built and clean-decodes 100%.\n' +
  master + '\n\n' +
  'TASK 1 — Write ' + DIR + '/analyze_master2.py that takes a RECORDING path (the captured tape playback) and:\n' +
  '  (a) finds the two global chirps by correlation; estimates the GLOBAL clock/speed from their measured\n' +
  '      spacing vs the manifest expected spacing (the real deck ran ~0.88x last time, so handle 0.80-1.10);\n' +
  '      resample the whole recording to ~nominal 48k. Also DC-remove / normalize.\n' +
  '  (b) runs the SOUNDER analysis -> fresh real H(f), SNR(f), flutter%, noise floor, recovered clock; print them.\n' +
  '  (c) for each manifest section: coarse-locate by (scaled) manifest offset, hand a generous window to the\n' +
  '      owning modem\'s demodulate (which does local find_preamble fine-sync), CRC-check, byte-compare to the\n' +
  '      sidecar. Aggregate a PASS-RATE table per (config): reps, passes, passrate, gross bps, and effective\n' +
  '      net bytes delivered. Print the reliable frontier = highest-gross config with passrate==1.0 (and the\n' +
  '      highest with passrate>=0.8).\n' +
  '  (d) write a results JSON + a short markdown table to ' + DIR + '/results/.\n' +
  'Route the section->modem dispatch through a small registry that imports modems_index/combo/ofdm.\n\n' +
  'TASK 2 — VALIDATION GATE (must pass): simulate the harsh real deck by pushing master2.wav through\n' +
  'cs.full_chain("worn", speed_offset=-0.12, seed=s) (and also "normal", 0.0) and running your analyzer on the\n' +
  'result. Confirm: chirp sync found, global clock recovered to within ~1%, and the ROBUST configs (mfsk32,\n' +
  'c1_gray_m16, c2_m32_k2, c4_bpsk) decode at high passrate while the aggressive ones degrade — i.e. the\n' +
  'analyzer + ladder behave sensibly end-to-end on a known-hard simulated channel. Print the simulated table.\n\n' +
  'TASK 3 — Write ' + DIR + '/RECORD_ME.md: how to record (play master2.wav -> tape in one pass; then play tape\n' +
  'back and capture). Give BOTH capture paths and their expected outcomes: (i) ACOUSTIC loop (speaker->iPhone\n' +
  'mic) = the harsh ~12.6 dB / 2.2% flutter / 0.88x regime, expect only the robust ladder rungs to pass;\n' +
  '(ii) ELECTRICAL line-in (3.5mm or a USB interface like the UCA222 noted in STATUS.md) = much closer to the\n' +
  '42 dB sim where the aggressive C2/C4 configs were measured, expect the frontier to climb. Include the level\n' +
  'SOP from the prior runs (Dolby NR OFF both ends; record level ~7.0 not 8.5; readback speaker ~55; leave ~1s\n' +
  'silence around the chirps). State plainly that the campaign\'s 3.69x/2.24x numbers were measured at 42 dB SNR\n' +
  'and the acoustic loop is ~30 dB noisier, so this recording TESTS whether they transfer.\n\n' +
  'Return a concise plain-text summary (<=180 words): the simulated-harsh-channel pass-rate table (per config:\n' +
  'gross bps, worn passrate), the analyzer\'s recovered global clock, and what the human should do next to record.',
  { label: 'analyzer', phase: 'Analyzer', model: 'opus', agentType: 'implementer' }
)

return {
  modems,
  master: master ? String(master).slice(0, 600) : null,
  analyzer,
}
