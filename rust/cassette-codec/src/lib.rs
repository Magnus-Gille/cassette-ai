//! cassette-codec — pure-Rust decoder for the cassette-ai acoustic data tape.
//!
//! This is a port of the Python R-1 **combinatorial-MFSK floor rung**
//! (`fullspectrum_decode._decode_combo_section` + `d3d4_combo_tracked` +
//! `dd_common.tracked_tone_demod` + `c2_combo_mfsk` + `m3_codec`), the
//! self-syncing, non-coherent rung that survives a worn deck where every
//! coherent DQPSK rung fails.
//!
//! The crate is `std`, f64 throughout the DSP, and dependency-light so it can
//! be embedded in sagascript (Rust/Tauri) and a future companion app.
//!
//! Correctness contract: the floor payload decodes **byte-exact** versus the
//! Python reference across the clean / `normal` / `worn+−0.12` cassette
//! channels (see `tests/`).

pub mod rs;
pub mod combo;
pub mod sync;
pub mod framing;
pub mod global_sync;
pub mod decoder;

/// Sample rate of every master/capture in this project (Hz).
pub const SAMPLE_RATE: u32 = 48_000;

/// Chirp preamble parameters (must match `src/hyp_common.py`).
pub const PREAMBLE_F0: f64 = 800.0;
pub const PREAMBLE_F1: f64 = 3_200.0;
pub const PREAMBLE_SECONDS: f64 = 0.25;
pub const PREAMBLE_AMP: f64 = 0.65;
