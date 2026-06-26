//! Byte-exact parity test for the R2 D2X (dense2x_drop) mono rung.
//!
//! R2 (`D2X_P18_N256_sp2_drop4`): p=18, spacing=2, pilot=4875 Hz,
//! drops=[750,4500,5625,6750]. Decoded via `decode_d2x_ensemble` (primary RX
//! geometry hann256_skip0 + EMA bank), framing rs_k=127 / n_cw=31 / n_frames=3.
//! Asserts byte-exact across the clean / normal / worn channels (reusing
//! <chan>_nominal.wav). Fixtures: `gen_r123_fixtures.py` (r2.json).

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
struct Chan {
    align: i64,
}
#[derive(Deserialize)]
struct R2Fixture {
    section: Section,
    crc32_codewords: Vec<u32>,
    payload: Vec<u8>,
    channels: std::collections::HashMap<String, Chan>,
}

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../experiments/tape_v2/rust_fixtures/fixtures")
}

fn load_wav_f64(path: &PathBuf) -> Vec<f64> {
    let mut reader = hound::WavReader::open(path)
        .unwrap_or_else(|e| panic!("open {}: {e}\nRun gen_r123_fixtures.py first.", path.display()));
    let spec = reader.spec();
    assert_eq!(spec.channels, 1, "fixtures are mono");
    match spec.sample_format {
        hound::SampleFormat::Float => reader.samples::<f32>().map(|s| s.unwrap() as f64).collect(),
        hound::SampleFormat::Int => {
            let max = (1i64 << (spec.bits_per_sample - 1)) as f64;
            reader.samples::<i32>().map(|s| s.unwrap() as f64 / max).collect()
        }
    }
}

fn load_r2() -> R2Fixture {
    let dir = fixtures_dir();
    let json = std::fs::read_to_string(dir.join("r2.json"))
        .unwrap_or_else(|e| panic!("read r2.json: {e}\nRun gen_r123_fixtures.py first."));
    serde_json::from_str(&json).expect("parse r2.json")
}

fn decode_channel(label: &str) -> (bool, usize) {
    let dir = fixtures_dir();
    let fx = load_r2();
    let align = fx.channels.get(label).expect("channel present").align;
    let audio = load_wav_f64(&dir.join(format!("{label}_nominal.wav")));

    let section = D2XSection {
        p: fx.section.p,
        n: fx.section.n,
        spacing: fx.section.spacing,
        drop_freqs_hz: fx.section.drop_freqs_hz.clone(),
        pilot_hz: fx.section.pilot_hz,
        frame_starts: fx.section.frame_starts.clone(),
        body_end: fx.section.body_end,
    };
    let m = &fx.section.meta;
    let meta = ComboMeta {
        rs_n: m.rs_n,
        rs_k: m.rs_k,
        n_codewords: m.n_codewords,
        frame_bits: m.frame_bits,
        n_frames: m.n_frames,
        stream_bits: m.stream_bits,
        payload_len: m.payload_len,
    };

    let dec = decode_d2x_ensemble(&audio, &section, align, &meta, &fx.crc32_codewords);
    let byte_exact = dec.bytes == fx.payload;
    eprintln!(
        "[rust/r2] {:6} align={:+} byte_exact={} cwFail={}/{} ({} bytes)",
        label, align, byte_exact, dec.codewords_failed, meta.n_codewords, fx.payload.len()
    );
    (byte_exact, dec.codewords_failed)
}

#[test]
fn r2_clean_byte_exact() {
    let (ok, cwf) = decode_channel("clean");
    assert!(ok, "clean R2 must decode byte-exact (cw_failed={cwf})");
}

#[test]
fn r2_normal_byte_exact() {
    let (ok, cwf) = decode_channel("normal");
    assert!(ok, "normal R2 must decode byte-exact (cw_failed={cwf})");
}

#[test]
fn r2_worn_byte_exact() {
    let (ok, cwf) = decode_channel("worn");
    assert!(ok, "worn+-0.12 R2 must decode byte-exact (cw_failed={cwf})");
}
