//! global_sync — find the master's start/end chirps, estimate deck clock, and
//! resample the whole raw capture back to nominal timing.
//!
//! Port of `analyze_master2.global_sync_and_resample` (+ helpers). This is the
//! front end a REAL capture goes through before `decoder::decode_combo_section`:
//! it turns mic/line-in audio (arbitrary lead-in, deck running at 0.8–1.1×) into
//! the nominal-rate `audio_nominal` + the `align` offset the decoder expects.

use crate::sync::{limit_denominator, resample_poly, valid_correlate};
use std::f64::consts::PI;

const FS: f64 = 48_000.0;
const GLOBAL_CHIRP_T: f64 = 0.20;
const GLOBAL_CHIRP_F0: f64 = 500.0;
const GLOBAL_CHIRP_F1: f64 = 5_000.0;

/// Result of global sync (mirrors the Python dict fields the decoder uses).
pub struct GlobalSync {
    pub audio_nominal: Vec<f64>,
    pub speed: f64,
    pub chirp0_meas: i64,
    pub chirp1_meas: i64,
    pub chirp0_nominal: i64,
    pub measured_spacing: i64,
    pub resample_num: u64,
    pub resample_den: u64,
    /// Sync-chirp matched-filter peak / median (a real "signal lock" strength;
    /// >~4 = a clean lock, ~1 = noise).
    pub lock_quality: f64,
}

fn global_chirp(up: bool) -> Vec<f64> {
    let n = (GLOBAL_CHIRP_T * FS) as usize;
    let (f0, f1) = if up {
        (GLOBAL_CHIRP_F0, GLOBAL_CHIRP_F1)
    } else {
        (GLOBAL_CHIRP_F1, GLOBAL_CHIRP_F0)
    };
    let beta = (f1 - f0) / GLOBAL_CHIRP_T;
    (0..n)
        .map(|i| {
            let t = i as f64 / FS;
            (2.0 * PI * (f0 * t + 0.5 * beta * t * t)).cos()
        })
        .collect()
}

fn dc_remove_normalize(x: &[f64]) -> Vec<f64> {
    if x.is_empty() {
        return Vec::new();
    }
    // Sanitize non-finite values (NaN / ±Inf) to 0 before any arithmetic.
    // Without this, NaN propagates through the FFT into the lock-quality sort
    // (`partial_cmp(NaN)` returns None) and the `.unwrap()` panics — a real
    // panic reachable from untrusted/corrupted audio input.
    let safe: Vec<f64> = x
        .iter()
        .map(|&v| if v.is_finite() { v } else { 0.0 })
        .collect();
    let mean = safe.iter().sum::<f64>() / safe.len() as f64;
    let mut y: Vec<f64> = safe.iter().map(|v| v - mean).collect();
    let pk = y.iter().fold(0.0f64, |m, v| m.max(v.abs()));
    if pk > 1e-12 {
        for v in y.iter_mut() {
            *v /= pk;
        }
    }
    y
}

fn speed_match_ref(reference: &[f64], speed: f64) -> Vec<f64> {
    if (speed - 1.0).abs() < 1e-4 {
        return reference.to_vec();
    }
    let (num, den) = limit_denominator(speed, 2000);
    resample_poly(reference, num as usize, den as usize)
}

/// Sample index of the chirp START within `[lo, hi]`, with parabolic sub-sample
/// peak refinement (rounded to int). Mirrors `_locate_chirp`.
fn locate_chirp(audio: &[f64], reference: &[f64], lo: i64, hi: i64) -> i64 {
    let lo = lo.max(0) as usize;
    let hi = (hi.min(audio.len() as i64)).max(0) as usize;
    if hi <= lo {
        return lo as i64;
    }
    let seg = &audio[lo..hi];
    if seg.len() < reference.len() {
        return lo as i64;
    }
    let corr = valid_correlate(seg, reference);
    let mut peak = 0usize;
    let mut best = f64::NEG_INFINITY;
    for (i, &c) in corr.iter().enumerate() {
        let a = c.abs();
        if a > best {
            best = a;
            peak = i;
        }
    }
    let mut peakf = peak as f64;
    if peak > 0 && peak < corr.len() - 1 {
        let (y0, y1, y2) = (corr[peak - 1].abs(), corr[peak].abs(), corr[peak + 1].abs());
        let denom = y0 - 2.0 * y1 + y2;
        if denom.abs() > 1e-12 {
            peakf = peak as f64 + 0.5 * (y0 - y2) / denom;
        }
    }
    lo as i64 + peakf.round() as i64
}

/// Find both global chirps, estimate clock, resample whole recording to nominal.
/// `tx_chirp0`/`tx_chirp1` come from the manifest.
pub fn global_sync_and_resample(audio: &[f64], tx_chirp0: i64, tx_chirp1: i64) -> GlobalSync {
    let audio = dc_remove_normalize(audio);
    let up = global_chirp(true);
    let down = global_chirp(false);
    let exp_spacing = tx_chirp1 - tx_chirp0;
    let n = audio.len() as i64;

    // PASS 1: locate chirp0 in a generous lead-in window
    let head_hi = (n as f64).min((0.45 * n as f64).max(60.0 * FS)) as i64;
    let mut c0 = locate_chirp(&audio, &up, 0, head_hi);

    // PASS 2: locate chirp1 via a speed scan with speed-matched templates
    let mut best: Option<(f64, f64, i64)> = None; // (corr, speed, c1)
    let mut sp = 0.80;
    while sp <= 1.1001 {
        let ds = speed_match_ref(&down, sp);
        let centre = c0 + (sp * exp_spacing as f64) as i64;
        let win = (0.04 * exp_spacing as f64) as i64 + FS as i64;
        let lo = (centre - win).max(0);
        let hi = (centre + win + ds.len() as i64).min(n);
        if hi > lo && (hi - lo) as usize >= ds.len() {
            let seg = &audio[lo as usize..hi as usize];
            let corr = valid_correlate(seg, &ds);
            let mut pk = 0usize;
            let mut val = f64::NEG_INFINITY;
            for (i, &c) in corr.iter().enumerate() {
                let a = c.abs();
                if a > val {
                    val = a;
                    pk = i;
                }
            }
            if best.map_or(true, |(bv, _, _)| val > bv) {
                best = Some((val, sp, lo + pk as i64));
            }
        }
        sp += 0.01;
    }
    let coarse_speed = best.map_or(1.0, |(_, s, _)| s);

    // PASS 3: refine both chirp positions with the winning speed template
    let up_s = speed_match_ref(&up, coarse_speed);
    let down_s = speed_match_ref(&down, coarse_speed);
    c0 = locate_chirp(
        &audio,
        &up_s,
        (c0 - FS as i64 / 2).max(0),
        c0 + up_s.len() as i64 + FS as i64 / 2,
    );
    let c1_centre = best.map_or(c0 + (coarse_speed * exp_spacing as f64) as i64, |(_, _, c)| c);
    let c1 = locate_chirp(
        &audio,
        &down_s,
        (c1_centre - FS as i64 / 2).max(0),
        c1_centre + down_s.len() as i64 + FS as i64 / 2,
    );

    let mut measured_spacing = c1 - c0;
    if measured_spacing <= 0 {
        measured_spacing = (coarse_speed * exp_spacing as f64).round() as i64;
    }
    let speed = measured_spacing as f64 / exp_spacing as f64;

    // resample whole recording back to nominal: stretch by exp_spacing/measured_spacing
    let (num, den) = limit_denominator(exp_spacing as f64 / measured_spacing as f64, 20000);
    let audio_nominal = if num != den {
        dc_remove_normalize(&resample_poly(&audio, num as usize, den as usize))
    } else {
        dc_remove_normalize(&audio)
    };

    // re-locate chirp0 in the resampled domain to anchor section offsets
    let nn = audio_nominal.len() as i64;
    let head_hi2 = (nn as f64).min((0.45 * nn as f64).max(60.0 * FS)) as i64;
    let c0_nom = locate_chirp(&audio_nominal, &up, 0, head_hi2);

    // lock strength: peak/median of the up-chirp matched filter in a tight
    // window around the located nominal chirp0.
    let lock_quality = {
        let lo = (c0_nom - FS as i64 / 2).max(0) as usize;
        let hi = ((c0_nom + up.len() as i64 + FS as i64 / 2).min(nn)) as usize;
        if hi > lo && hi - lo >= up.len() {
            let corr = valid_correlate(&audio_nominal[lo..hi], &up);
            let mut mags: Vec<f64> = corr.iter().map(|c| c.abs()).collect();
            let peak = mags.iter().cloned().fold(0.0f64, f64::max);
            // Defence-in-depth: treat NaN as equal (partial_cmp returns None for NaN).
            mags.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            let med = mags[mags.len() / 2].max(1e-9);
            peak / med
        } else {
            0.0
        }
    };

    GlobalSync {
        audio_nominal,
        speed,
        chirp0_meas: c0,
        chirp1_meas: c1,
        chirp0_nominal: c0_nom,
        measured_spacing,
        resample_num: num,
        resample_den: den,
        lock_quality,
    }
}
