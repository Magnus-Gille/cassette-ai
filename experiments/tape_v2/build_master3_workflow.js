export const meta = {
  name: 'master3-real-payload-tape',
  description: 'Build master3.wav: a recordable robustness LADDER carrying the real 153KB cassette-LLM, using the deep-dive #2 winning modem (M-K flutter-tracked combinatorial) + global RS interleave. Goal: first byte-exact recovery of a real payload off a physical tape. Validated clean + through a sim flutter channel.',
  phases: [
    { title: 'Codec', detail: 'RS global-interleave encode/decode + ladder rungs; self-test clean + sim-real byte-exact' },
    { title: 'MasterDecoder', detail: 'assemble master3.wav + physical decoder + RECORD_ME; validate clean + sim-flutter byte-exact' },
  ],
}

const ROOT = '/Users/magnus/repos/cassette-ai'
const DIR = ROOT + '/experiments/tape_v2'

const PRIMER = [
  'Repo ' + ROOT + ', branch tape-test-3. We are building a PHYSICAL tape test that carries a REAL',
  'payload (the 153,823-byte cassette-LLM) and aims for the FIRST byte-exact recovery of a real file',
  'off a cassette, using the deep-dive #2 breakthrough. Work in ' + DIR + ' .',
  '',
  'REUSE these existing, working modules — do NOT reinvent them:',
  '  experiments/deepdive2/d3d4_combo_tracked.py :',
  '     make_tracked_combo(M, K) -> a scheme object with:',
  '       .modulate(bits: uint8[]) -> float32 audio @48k, INCLUDING its own 0.25s chirp preamble',
  '       .demodulate(audio, sr) -> recovered uint8 bits (flutter-tracked, self-syncs from the preamble',
  '          via dd_common.tracked_tone_demod: global speed estimate + per-symbol energy-lock tracking)',
  '       .gross_bps, .preamble_seconds, .samples_per_sym, .bits_per_sym',
  '  experiments/deepdive2/w4_endtoend.py : the PROVEN global-RS-interleave pipeline (run_global):',
  '     RS(255,191) over the payload, column-interleave the 255-byte codewords across frames, each frame',
  '     = frame_bytes*8 bits modulated independently (own preamble for re-sync), demod per frame, concat',
  '     bits, de-interleave, RS-decode. THIS recovered the full 153KB LLM byte-exact through the worn',
  '     channel. Refactor its encode/decode into reusable functions (do not just call its CLI).',
  '  experiments/tape_v2/analyze_master2.py : global_sync_and_resample(audio, manifest) — whole-tape',
  '     chirp sync + speed recovery WITH the lead-in fix (searches a generous window). REUSE it for the',
  '     master3 decoder so it survives arbitrary recorder lead-in.',
  '  experiments/tape_v2/make_master2.py / make_sounder (experiments/dpd) : global sync chirps + the',
  '     45s channel sounder + manifest pattern. REUSE.',
  '  Payload: experiments/dpd/cassette_llm/stories260K_int4.cass (153823 bytes, tracked).',
  '',
  'CHANNELS (experiments/deepdive2/dd_common.py): CHANNELS["real"] = worn preset + speed_offset -0.12.',
  'FS=48000. For a 0.44% flutter validation (the clean-real-capture regime measured last night),',
  'use capture_scenarios.full_chain with the wow_flutter set ~0.0044 (see experiments/deepdive2/',
  'w5_flutter_sweep.py for how flutter is injected). reedsolo (RSCodec) is installed.',
  '',
  'CONTEXT: deep-dive #2 found M16,K2 (real net 2309, BER 1.3e-3, survival 1.0) and M12/M14,K2 as the',
  'real frontier on the worn+0.88x proxy (~0.25% flutter). BUT the tracker only holds to ~0.3% flutter;',
  'at 0.44% (our actual capture) survival drops to ~0.80. So the LADDER must include a ROBUST rung',
  '(wider tone spacing = lower M, and a heavier RS rate) designed to survive >=0.5% flutter, so that',
  'SOMETHING lands byte-exact even if the frontier rung fails on real flutter. The point of this tape is',
  'the FIRST confirmed byte-exact physical recovery, not max rate.',
  'Keep shell output bounded.',
].join('\n')

// ---------------------------------------------------------------------------
// Phase 1 — codec + ladder contract
// ---------------------------------------------------------------------------
phase('Codec')

const CODEC_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['module_file', 'rungs', 'clean_byte_exact', 'sim_real_results', 'notes'],
  properties: {
    module_file: { type: 'string' },
    rungs: { type: 'array', items: { type: 'string' }, description: 'rung names robust->frontier with their (M,K,RS) params' },
    clean_byte_exact: { type: 'boolean', description: 'every rung encode->decode (no channel) byte-exact incl a >=32KB payload' },
    sim_real_results: { type: 'array', description: 'per rung: byte-exact through dd CHANNELS["real"]?',
      items: { type: 'object', additionalProperties: false,
        required: ['rung', 'payload_bytes', 'real_byte_exact', 'raw_ber', 'net_bps'],
        properties: { rung: { type: 'string' }, payload_bytes: { type: 'integer' },
          real_byte_exact: { type: 'boolean' }, raw_ber: { type: 'number' }, net_bps: { type: 'number' } } } },
    notes: { type: 'string' },
  },
}

const codec = await agent(
  PRIMER + '\n\n' +
  'TASK: build experiments/tape_v2/m3_codec.py — the payload<->frames codec + the ladder rungs.\n' +
  'Define RUNGS (a list, robust -> frontier), each {name, M, K, rs_n, rs_k, frame_bytes}:\n' +
  '  - "robust"   : wide spacing + heavy FEC for >=0.5% flutter. Suggest M=8,K=2 (or M=10,K=2) and\n' +
  '                 RS(255,127) (rate 0.5). Must survive 0.44% sim flutter (validated in phase 2).\n' +
  '  - "mid"      : M=12,K=2, RS(255,159) (rate ~0.62).\n' +
  '  - "frontier" : M=16,K=2, RS(255,191) (rate 0.749) — the deep-dive verified real champion.\n' +
  '  (Tune M/K/RS if your own sim tests show better robustness; justify in notes.)\n' +
  'Expose:\n' +
  '  encode_payload(payload: bytes, rung) -> (list_of_frame_bit_arrays:uint8[], meta:dict)\n' +
  '     using w4 run_global-style RS(rs_n,rs_k) + GLOBAL column-interleave of codewords across frames\n' +
  '     (frame size = rung.frame_bytes). meta carries everything decode needs (n_codewords, shape,\n' +
  '     n_frames, payload_len, rung params).\n' +
  '  decode_payload(list_of_recovered_frame_bit_arrays:uint8[], meta) -> bytes\n' +
  '     inverse: concat -> de-interleave -> RS-decode -> truncate to payload_len. Must tolerate a few\n' +
  '     fully-wrong frames (that is the whole point of global interleave).\n' +
  'SELF-TEST in __main__: for each rung (a) clean encode->decode of a >=32KB slice of the .cass byte-exact;\n' +
  '(b) end-to-end through dd CHANNELS["real"]: modulate each frame with make_tracked_combo(M,K), push\n' +
  'through cs.full_chain, demodulate, decode -> byte-exact. Report per rung. Frontier must match the\n' +
  'w4 result (byte-exact on real). Return the structured result.',
  { label: 'codec', phase: 'Codec', model: 'opus', schema: CODEC_SCHEMA, agentType: 'implementer' }
)

const codecLine = codec
  ? ('m3_codec.py built. rungs: ' + (codec.rungs || []).join(', ') + '. clean byte-exact: ' + codec.clean_byte_exact +
     '. sim-real: ' + (codec.sim_real_results || []).map((r) => r.rung + '=' + (r.real_byte_exact ? 'EXACT' : 'fail') + '@' + Math.round(r.net_bps) + 'bps').join(' '))
  : 'm3_codec.py: phase-1 agent FAILED — inspect experiments/tape_v2/m3_codec.py before proceeding.'
log(codecLine)

// ---------------------------------------------------------------------------
// Phase 2 — master assembler + physical decoder + record instructions
// ---------------------------------------------------------------------------
phase('MasterDecoder')

const master = await agent(
  PRIMER + '\n\n' + codecLine + '\n\n' +
  'm3_codec.py (encode_payload/decode_payload + RUNGS) is built and self-tested. Now build the recordable\n' +
  'master and its physical decoder.\n\n' +
  'TASK 1 — experiments/tape_v2/m3_master.py assembles experiments/tape_v2/master3.wav (gitignored;\n' +
  'captures/ and master*.wav are already ignored) + master3_manifest.json + sidecars under\n' +
  'sidecars_m3/. Layout (self-locating, like master2): ~1s lead + GLOBAL up-chirp (record tx_chirp0) +\n' +
  '~45s SOUNDER (reuse make_sounder/make_master2 helpers) + the LADDER PAYLOADS + GLOBAL down-chirp\n' +
  '(tx_chirp1) + tail. For each payload: call m3_codec.encode_payload(bytes, rung) -> frames; modulate\n' +
  'each frame with make_tracked_combo(rung.M, rung.K) (its own preamble); concatenate the frames with\n' +
  'small (~0.2s) gaps; record in the manifest: {rung, payload_name, codec meta, frame start_samples,\n' +
  'sidecar}. PAYLOADS to include (target total 15-18 min, one cassette side):\n' +
  '  - a known 2 KB TEST file (random, fixed seed) at the "robust" rung  (guaranteed-win probe)\n' +
  '  - a known 2 KB TEST file at the "frontier" rung\n' +
  '  - a 32 KB slice of stories260K_int4.cass at the "robust" rung      (hedge: real data, robustly coded)\n' +
  '  - the FULL 153823-byte stories260K_int4.cass at the "frontier" rung (THE HERO)\n' +
  'Write each payload to a sidecar (the exact known bytes) for byte comparison. Peak-normalise mix to 0.95.\n\n' +
  'TASK 2 — experiments/tape_v2/m3_decode.py takes a captured WAV and recovers each payload:\n' +
  '  reuse analyze_master2.global_sync_and_resample for whole-tape speed/anchor (lead-in-robust); for each\n' +
  '  manifest payload, locate its frames (manifest start_samples + the chirp-derived align), hand each\n' +
  '  frame window to make_tracked_combo(rung).demodulate, collect frame bits, call\n' +
  '  m3_codec.decode_payload -> bytes, byte-compare to the sidecar. Print a per-payload table:\n' +
  '  rung, payload, bytes, raw frame BER, RS codewords failed, BYTE-EXACT yes/no. Write results JSON to\n' +
  '  results/. Also run the channel sounder for the fresh channel readout.\n\n' +
  'TASK 3 — experiments/tape_v2/RECORD_ME_v3.md: how to record (Voice Memos -> iCloud per CLAUDE.md, NOT\n' +
  'Continuity live-capture; Dolby off, levels, full ~16min pass, ~1s silence around chirps). Explain the\n' +
  'ladder + expected outcomes: at the measured 0.44% flutter the robust rung + 2KB probes should land\n' +
  'byte-exact; the frontier 153KB LLM is the stretch (survival ~0.8 in sim at 0.44%). State plainly this\n' +
  'is the attempt at the FIRST byte-exact real-payload recovery off a physical cassette.\n\n' +
  'VALIDATION GATES (must pass before returning, print both):\n' +
  '  (A) CLEAN: decode master3.wav directly (no channel) via m3_decode -> EVERY payload byte-exact,\n' +
  '      INCLUDING the full 153KB LLM. This proves the encode/assemble/decode contract is internally\n' +
  '      consistent (any later failure is the tape, not the tooling).\n' +
  '  (B) SIM-FLUTTER: push master3.wav through cs.full_chain at flutter ~0.0044 (0.44%) + a small speed\n' +
  '      offset (the clean-real-capture regime) and decode -> report which payloads survive byte-exact.\n' +
  '      The robust rung + 2KB probes SHOULD survive; report the frontier honestly.\n' +
  'Return a concise summary: master duration, per-payload clean result (must be all byte-exact), the\n' +
  'sim-flutter survival table, and confirmation master3.wav + manifest + sidecars are written.',
  { label: 'master+decoder', phase: 'MasterDecoder', model: 'opus', agentType: 'implementer' }
)

return { codec, master: master ? String(master).slice(0, 1200) : null }
