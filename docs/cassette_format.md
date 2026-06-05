# Cassette v3 Prototype Format

This is an implementable clean-channel prototype, not a hardware-ready modem. It fixes the byte layout and recovery semantics so later physical work can replace the BFSK modem without changing the container.

## Physical Layer

- Mono PCM, 48 kHz.
- Logical bit rate: 1200 bit/s, 40 samples/bit.
- BFSK symbols: 1200 Hz for `0`, 2400 Hz for `1`.
- Leader: 2.0 seconds of 1200 Hz tone.
- Sync chirp: 0.25 seconds linear 800 Hz to 3200 Hz. The prototype decoder assumes clean fixed timing after the chirp; a physical decoder should detect this by correlation.
- Trailer: 1.0 seconds of 1200 Hz tone.

## Container Layout

All integers are little-endian.

| Section | Fields |
|---|---|
| Header | `magic="CAS3"`, `version=3`, flags, header length, payload length, frame count, frame payload bytes, sample rate, bit rate, SHA-256 payload hash |
| Frame | resync marker `1d ea c0 de`, 32-bit sequence number, 16-bit payload length, payload bytes, CRC-32 over sequence/length/payload |
| Tail | marker `TAIL`, frame count, SHA-256 payload hash, CRC-32 over tail hash/count |

The current prototype uses 256-byte payload frames. Header and tail hashes cover the original payload. Frame CRCs cover individual chunks so a decoder can keep good frames after localized corruption.

## Resync And Graceful Degradation

The resync marker appears before every frame. On CRC failure, a decoder discards that frame and scans forward to the next marker. Decoding returns:

- recovered frame count
- missing frame sequence numbers
- bad frame count
- tail hash status
- complete/incomplete status
- recovered payload bytes assembled from valid frames in order

Complete recovery requires all frames, valid frame CRCs, a valid tail, and a matching payload hash. Incomplete recovery is still useful for model formats that can tolerate missing shards or for later erasure-code reconstruction.

## Determinism

`src/cassette_format.py` has deterministic `encode_audio -> decode_audio` roundtrip behavior on a clean channel. `src/decoder_profile.py` profiles the decoder on fixed pseudo-payloads and writes `RESULTS/data/decoder_profile.csv`.
