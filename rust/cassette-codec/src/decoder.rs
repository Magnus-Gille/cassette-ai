//! decoder — the R-1 floor-rung driver (port of
//! `fullspectrum_decode._decode_combo_section`).
//!
//! Each frame is sliced out of the globally-synced/resampled `audio_nominal` by
//! its `frame_starts` (+ the global `align`), started ~50 ms early for preamble
//! margin, and handed to the self-syncing combinatorial demod. The recovered
//! per-frame bits go through the same RS(255,k) + global-interleave decode.

use crate::combo::ComboScheme;
use crate::framing::{decode_payload, ComboMeta, DecodedPayload};
use crate::global_sync::global_sync_and_resample;
use crate::sync::tracked_tone_demod;

/// Frame-layout info for the floor section (from the manifest section block).
///
/// `f_low`/`f_high` are the combinatorial tone-bank band edges (Hz). The
/// full-spectrum floor rung uses the default 400/10000; a narrowband manifest
/// (e.g. the worn-deck 470-2200 Hz MNIST master) carries its own edges so the
/// Rust grid matches the transmitter exactly.
pub struct FloorSection {
    pub m: usize,
    pub k: usize,
    pub f_low: f64,
    pub f_high: f64,
    pub frame_starts: Vec<i64>,
    pub body_end: i64,
    pub guard: i64,
}

/// Default combinatorial band (`400..10_000 Hz`) — the full-spectrum floor rung.
pub const DEFAULT_F_LOW: f64 = 400.0;
pub const DEFAULT_F_HIGH: f64 = 10_000.0;

/// Everything needed to decode the floor rung off a raw capture: the two global
/// sync-chirp positions plus the section/framing layout. For the shipped
/// full-spectrum test tape these are fixed (see the bundled manifest).
pub struct FloorManifest {
    pub tx_chirp0: i64,
    pub tx_chirp1: i64,
    pub section: FloorSection,
    pub meta: ComboMeta,
}

/// Result of an end-to-end capture decode.
pub struct CaptureResult {
    pub payload: DecodedPayload,
    /// deck speed estimate (1.0 = nominal; 0.88 = a slow worn deck)
    pub speed: f64,
    /// global align offset applied to frame positions
    pub align: i64,
    /// sync-chirp lock strength (peak/median; >~4 = clean lock)
    pub lock_quality: f64,
}

/// Full pipeline a real mic/line-in capture goes through: global chirp sync +
/// resample-to-nominal, then the floor decode. `raw` is f64 PCM at 48 kHz.
pub fn decode_floor_from_capture(raw: &[f64], manifest: &FloorManifest) -> CaptureResult {
    let sync = global_sync_and_resample(raw, manifest.tx_chirp0, manifest.tx_chirp1);
    let align = sync.chirp0_nominal - manifest.tx_chirp0;
    let payload = decode_combo_section(&sync.audio_nominal, &manifest.section, align, &manifest.meta);
    CaptureResult {
        payload,
        speed: sync.speed,
        align,
        lock_quality: sync.lock_quality,
    }
}

/// Decode the floor rung from globally-synced nominal audio.
///
/// `audio_nom` is f64 PCM after global sync/resample. `align` maps tx frame
/// positions onto the captured timeline. Returns the recovered payload bytes.
pub fn decode_combo_section(
    audio_nom: &[f64],
    section: &FloorSection,
    align: i64,
    meta: &ComboMeta,
) -> DecodedPayload {
    let sch = ComboScheme::new_band(section.m, section.k, section.f_low, section.f_high);
    let n_total = audio_nom.len() as i64;
    let starts = &section.frame_starts;

    let mut frames_bits: Vec<Vec<u8>> = Vec::with_capacity(starts.len());
    for (i, &st) in starts.iter().enumerate() {
        let a = (align + st - section.guard).max(0);
        let nxt = if i + 1 < starts.len() {
            starts[i + 1]
        } else {
            section.body_end
        };
        let b = n_total.min((a + 1).max(align + nxt));
        if b <= a {
            frames_bits.push(Vec::new());
            continue;
        }
        let seg = &audio_nom[a as usize..b as usize];

        // self-syncing per-frame combinatorial demod (make_tracked_combo defaults)
        let syms = tracked_tone_demod(
            seg,
            &sch.freqs,
            sch.n,
            sch.bits_per_sym,
            1 << 20,
            sch.preamble_seconds,
            40,    // acq
            3,     // track
            true,  // do_speed
            0.03,  // center_bias
            0.0,   // vel_gain
        );
        let mut bits: Vec<u8> = Vec::with_capacity(syms.len() * sch.bits_per_sym);
        for e in &syms {
            sch.energies_to_bits(e, &mut bits);
        }
        frames_bits.push(bits);
    }

    decode_payload(&frames_bits, meta)
}
