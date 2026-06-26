//! Byte-exact parity test for the R3 D2X stereo rung (true 2x — INDEPENDENT
//! payloads on L and R).
//!
//! R3 (`D2X_P21_N256_sp2_drop1`): p=21, spacing=2, pilot=4875 Hz, drops=[750],
//! rs_k=159 / n_cw=25 / n_frames=3. Each channel is decoded independently via
//! `decode_d2x_ensemble` from its own nominal WAV (`r3_L_nominal.wav` /
//! `r3_R_nominal.wav`) with its own align/section/crc/payload, and BOTH must be
//! byte-exact. Fixtures: `gen_r123_fixtures.py` (r3.json).

use cassette_codec::dqpsk::{decode_d2x_ensemble, D2XSection};
use cassette_codec::framing::ComboMeta;
use serde::Deserialize;
use std::path::PathBuf;

#[derive(Deserialize)]
struct Meta {
    rs_n: usize,
    rs_k: usize,
    n_codewords: usize,
    frame_bits: usize,
    n_frames: usize,
    stream_bits: usize,
    payload_len: usize,
}
#[derive(Deserialize)]
struct Section {
    frame_starts: Vec<i64>,
    body_end: i64,
    p: usize,
    n: usize,
    spacing: usize,
    pilot_hz: f64,
    drop_freqs_hz: Vec<f64>,
    meta: Meta,
}
#[derive(Deserialize)]
struct ChanFixture {
    align: i64,
    section: Section,
    crc32_codewords: Vec<u32>,
    payload: Vec<u8>,
}
#[derive(Deserialize)]
struct R3Fixture {
    channels: std::collections::HashMap<String, ChanFixture>,
}

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../experiments/tape_v2/rust_fixtures/fixtures")
}

fn load_wav_f64(path: &PathBuf) -> Vec<f64> {
    let mut reader = hound::WavReader::open(path)
        .unwrap_or_else(|e| panic!("open {}: {e}\nRun gen_r123_fixtures.py first.", path.display()));
    let spec = reader.spec();
    assert_eq!(spec.channels, 1, "R3 per-channel fixtures are mono");
    match spec.sample_format {
        hound::SampleFormat::Float => reader.samples::<f32>().map(|s| s.unwrap() as f64).collect(),
        hound::SampleFormat::Int => {
            let max = (1i64 << (spec.bits_per_sample - 1)) as f64;
            reader.samples::<i32>().map(|s| s.unwrap() as f64 / max).collect()
        }
    }
}

fn decode_channel(label: &str) -> (bool, usize) {
    let dir = fixtures_dir();
    let json = std::fs::read_to_string(dir.join("r3.json"))
        .unwrap_or_else(|e| panic!("read r3.json: {e}\nRun gen_r123_fixtures.py first."));
    let fx: R3Fixture = serde_json::from_str(&json).expect("parse r3.json");
    let ch = fx.channels.get(label).expect("channel present");
    let audio = load_wav_f64(&dir.join(format!("r3_{label}_nominal.wav")));

    let section = D2XSection {
        p: ch.section.p,
        n: ch.section.n,
        spacing: ch.section.spacing,
        drop_freqs_hz: ch.section.drop_freqs_hz.clone(),
        pilot_hz: ch.section.pilot_hz,
        frame_starts: ch.section.frame_starts.clone(),
        body_end: ch.section.body_end,
    };
    let m = &ch.section.meta;
    let meta = ComboMeta {
        rs_n: m.rs_n,
        rs_k: m.rs_k,
        n_codewords: m.n_codewords,
        frame_bits: m.frame_bits,
        n_frames: m.n_frames,
        stream_bits: m.stream_bits,
        payload_len: m.payload_len,
    };

    let dec = decode_d2x_ensemble(&audio, &section, ch.align, &meta, &ch.crc32_codewords);
    let byte_exact = dec.bytes == ch.payload;
    eprintln!(
        "[rust/r3] chan={} align={:+} byte_exact={} cwFail={}/{} ({} bytes)",
        label, ch.align, byte_exact, dec.codewords_failed, meta.n_codewords, ch.payload.len()
    );
    (byte_exact, dec.codewords_failed)
}

#[test]
fn r3_left_byte_exact() {
    let (ok, cwf) = decode_channel("L");
    assert!(ok, "R3 L must decode byte-exact (cw_failed={cwf})");
}

#[test]
fn r3_right_byte_exact() {
    let (ok, cwf) = decode_channel("R");
    assert!(ok, "R3 R must decode byte-exact (cw_failed={cwf})");
}
