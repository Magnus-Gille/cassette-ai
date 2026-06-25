//! decoder — the R-1 floor-rung driver (port of
//! `fullspectrum_decode._decode_combo_section`).
//!
//! Each frame is sliced out of the globally-synced/resampled `audio_nominal` by
//! its `frame_starts` (+ the global `align`), started ~50 ms early for preamble
//! margin, and handed to the self-syncing combinatorial demod. The recovered
//! per-frame bits go through the same RS(255,k) + global-interleave decode.

use crate::combo::ComboScheme;
use crate::framing::{decode_payload, ComboMeta, DecodedPayload};
use crate::sync::tracked_tone_demod;

/// Frame-layout info for the floor section (from the manifest section block).
pub struct FloorSection {
    pub m: usize,
    pub k: usize,
    pub frame_starts: Vec<i64>,
    pub body_end: i64,
    pub guard: i64,
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
    let sch = ComboScheme::new(section.m, section.k);
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
