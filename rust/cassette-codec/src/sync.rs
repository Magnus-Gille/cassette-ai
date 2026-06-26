//! sync — chirp preamble, matched-filter sync, speed estimation, and the
//! per-symbol flutter-tracking non-coherent tone demodulator.
//!
//! Port of `src/hyp_common.py` (make_preamble / find_preamble) and
//! `experiments/deepdive2/dd_common.py` (estimate_speed / correct_speed /
//! tracked_tone_demod). Pure energy detection + a timing tracker — no coherent
//! phase — which is why it survives tape wow/flutter.

use rustfft::{num_complex::Complex, FftPlanner};
use std::f64::consts::PI;

const FS: f64 = 48_000.0;
use crate::{PREAMBLE_AMP, PREAMBLE_F0, PREAMBLE_F1, PREAMBLE_SECONDS};

/// Linear up-chirp 800→3200 Hz, amplitude 0.65, f64. Matches
/// `scipy.signal.chirp(t, f0, t1, f1, method="linear")` with `phi=0` (returns
/// cosine of the swept phase).
pub fn make_preamble(seconds: f64) -> Vec<f64> {
    let n = (seconds * FS) as usize;
    let beta = (PREAMBLE_F1 - PREAMBLE_F0) / seconds; // chirp rate (Hz/s)
    (0..n)
        .map(|i| {
            let t = i as f64 / FS;
            let phase = 2.0 * PI * (PREAMBLE_F0 * t + 0.5 * beta * t * t);
            PREAMBLE_AMP * phase.cos()
        })
        .collect()
}

// ---------------------------------------------------------------------------
// FFT helpers (linear convolution / valid cross-correlation)
// ---------------------------------------------------------------------------

fn next_pow2(n: usize) -> usize {
    let mut p = 1;
    while p < n {
        p <<= 1;
    }
    p
}

/// Full linear convolution of two real signals via FFT (length `a+b-1`).
fn fft_convolve(a: &[f64], b: &[f64]) -> Vec<f64> {
    let l_full = a.len() + b.len() - 1;
    let l = next_pow2(l_full);
    let mut planner = FftPlanner::<f64>::new();
    let fwd = planner.plan_fft_forward(l);
    let inv = planner.plan_fft_inverse(l);

    let mut fa: Vec<Complex<f64>> = vec![Complex::new(0.0, 0.0); l];
    let mut fb: Vec<Complex<f64>> = vec![Complex::new(0.0, 0.0); l];
    for (i, &x) in a.iter().enumerate() {
        fa[i].re = x;
    }
    for (i, &x) in b.iter().enumerate() {
        fb[i].re = x;
    }
    fwd.process(&mut fa);
    fwd.process(&mut fb);
    for i in 0..l {
        fa[i] = fa[i] * fb[i];
    }
    inv.process(&mut fa);
    let scale = 1.0 / l as f64;
    fa[..l_full].iter().map(|c| c.re * scale).collect()
}

/// Valid cross-correlation: `out[i] = sum_j a[i+j] * b[j]`, length `a-b+1`.
/// Equals `conv(a, reverse(b))[b.len()-1 .. a.len()]`.
pub(crate) fn valid_correlate(a: &[f64], b: &[f64]) -> Vec<f64> {
    if a.len() < b.len() {
        return Vec::new();
    }
    let mut b_rev = b.to_vec();
    b_rev.reverse();
    let conv = fft_convolve(a, &b_rev);
    conv[(b.len() - 1)..a.len()].to_vec()
}

/// Cross-correlate `audio` with the preamble and return the sample index of the
/// first DATA sample after the preamble (`peak + len(preamble)`).
pub fn find_preamble(audio: &[f64], seconds: f64) -> usize {
    let pre = make_preamble(seconds);
    if audio.len() < pre.len() {
        return 0;
    }
    let corr = valid_correlate(audio, &pre);
    let mut best_i = 0usize;
    let mut best_v = f64::NEG_INFINITY;
    for (i, &c) in corr.iter().enumerate() {
        let a = c.abs();
        if a > best_v {
            best_v = a;
            best_i = i;
        }
    }
    best_i + pre.len()
}

// ---------------------------------------------------------------------------
// Rational resampler (windowed-sinc polyphase, scipy.resample_poly-alike)
// ---------------------------------------------------------------------------

/// Best rational approximation of `val` with denominator ≤ `max_den`
/// (CPython `Fraction.limit_denominator`). Returns `(num, den)`, both > 0.
pub fn limit_denominator(val: f64, max_den: u64) -> (u64, u64) {
    // Exact dyadic ratio of the f64, then integer continued fraction.
    let (mut n, mut d) = float_to_ratio(val);
    if d <= max_den {
        return (n, d);
    }
    let (mut p0, mut q0, mut p1, mut q1) = (0i128, 1i128, 1i128, 0i128);
    let (mut nn, mut dd) = (n as i128, d as i128);
    loop {
        let a = nn.div_euclid(dd);
        let q2 = q0 + a * q1;
        if q2 > max_den as i128 {
            break;
        }
        let p2 = p0 + a * p1;
        p0 = p1;
        q0 = q1;
        p1 = p2;
        q1 = q2;
        let rem = nn - a * dd;
        nn = dd;
        dd = rem;
        if dd == 0 {
            break;
        }
    }
    let k = (max_den as i128 - q0) / q1;
    let b1n = p0 + k * p1;
    let b1d = q0 + k * q1;
    let b2n = p1;
    let b2d = q1;
    // pick whichever bound is closer to val
    let err1 = (b1n as f64 / b1d as f64 - val).abs();
    let err2 = (b2n as f64 / b2d as f64 - val).abs();
    if err2 <= err1 {
        n = b2n as u64;
        d = b2d as u64;
    } else {
        n = b1n as u64;
        d = b1d as u64;
    }
    (n.max(1), d.max(1))
}

fn float_to_ratio(val: f64) -> (u64, u64) {
    // Approximate the float by num/den with den = 2^k bounded; good enough as a
    // seed for limit_denominator on the positive ratios we use (0.8..1.2).
    let den: u64 = 1 << 30;
    let num = (val * den as f64).round() as u64;
    let g = gcd(num, den);
    (num / g, den / g)
}

fn gcd(mut a: u64, mut b: u64) -> u64 {
    while b != 0 {
        let t = b;
        b = a % b;
        a = t;
    }
    a.max(1)
}

fn sinc(x: f64) -> f64 {
    if x.abs() < 1e-12 {
        1.0
    } else {
        (PI * x).sin() / (PI * x)
    }
}

fn i0(x: f64) -> f64 {
    // modified Bessel I0 via series
    let mut sum = 1.0;
    let mut term = 1.0;
    let y = x * x / 4.0;
    for k in 1..50 {
        term *= y / (k as f64 * k as f64);
        sum += term;
        if term < 1e-12 * sum {
            break;
        }
    }
    sum
}

/// Kaiser-windowed lowpass FIR (firwin-equivalent, scale=True at DC), gain `up`.
fn design_fir(up: usize, down: usize) -> Vec<f64> {
    let max_rate = up.max(down);
    let f_c = 1.0 / max_rate as f64; // cutoff (Nyquist = 1.0)
    let half_len = 10 * max_rate;
    let n_taps = 2 * half_len + 1;
    let beta = 5.0;
    let m = (n_taps - 1) as f64 / 2.0;
    let denom = i0(beta);
    let mut h = vec![0.0f64; n_taps];
    let mut dc = 0.0;
    for i in 0..n_taps {
        let x = i as f64 - m;
        let r = (i as f64 - m) / m; // -1..1
        let w = i0(beta * (1.0 - r * r).max(0.0).sqrt()) / denom;
        let val = f_c * sinc(f_c * x) * w;
        h[i] = val;
        dc += val;
    }
    // normalize DC gain to 1, then scale by up (scipy resample_poly convention)
    for v in h.iter_mut() {
        *v = *v / dc * up as f64;
    }
    h
}

/// `scipy.signal.resample_poly(x, up, down)` — upsample by `up`, lowpass, keep
/// every `down`-th sample, with the FIR group delay compensated so the output
/// aligns with the input. Output length = ceil(len(x)*up/down).
pub fn resample_poly(x: &[f64], up: usize, down: usize) -> Vec<f64> {
    if up == down {
        return x.to_vec();
    }
    if x.is_empty() {
        return Vec::new();
    }
    let h = design_fir(up, down);
    let n_taps = h.len();
    let half = (n_taps - 1) / 2;

    // Upsample: y[n*up] = x[n]. Convolve with h. The convolution output index p
    // corresponds to upsampled time p; the group delay is `half`. scipy keeps
    // output samples at positions  down*k + half  (k = 0..n_out-1).
    //
    // NB: index math is i64, NOT usize — on wasm32 `usize` is 32-bit and a large
    // upsample factor makes `x.len()*up` overflow (the bug that returned a
    // truncated buffer and broke the worn-deck decode in the browser).
    let up_i = up as i64;
    let down_i = down as i64;
    let half_i = half as i64;
    let n_taps_i = n_taps as i64;
    let xlen = x.len() as i64;
    let n_out = (((xlen * up_i + down_i - 1) / down_i).max(1)) as usize;
    let up_len = (xlen - 1) * up_i + 1; // length of the virtual upsampled signal
    let mut out = vec![0.0f64; n_out];
    for k in 0..n_out {
        let center = down_i * (k as i64) + half_i;
        // sum over taps hitting a non-zero upsampled sample: j ≡ center (mod up)
        let mut jj = center.rem_euclid(up_i);
        let mut acc = 0.0;
        while jj < n_taps_i {
            let idx = center - jj; // position in the upsampled axis
            if idx >= 0 && idx < up_len && idx % up_i == 0 {
                acc += h[jj as usize] * x[(idx / up_i) as usize];
            }
            jj += up_i;
        }
        out[k] = acc;
    }
    out
}

// ---------------------------------------------------------------------------
// Speed estimation (preamble-derived, no oracle)
// ---------------------------------------------------------------------------

/// Estimate the steady resample ratio applied to the TX audio using only the
/// known chirp preamble. Returns `r_hat`; restore nominal timing by resampling
/// the received audio by `1/r_hat` (see `correct_speed`). Port of
/// `dd_common.estimate_speed`.
pub fn estimate_speed(audio: &[f64], seconds: f64) -> f64 {
    let pre0 = make_preamble(seconds);
    let lead_n = (audio.len() as f64)
        .min((0.6f64).max(seconds / 0.84 * 3.0 + 0.3) * FS)
        .floor() as usize;
    let seg = &audio[..lead_n.min(audio.len())];

    // prefix sums of squares for windowed-energy normalisation
    let mut seg_csum = vec![0.0f64; seg.len()];
    let mut acc = 0.0;
    for (i, &v) in seg.iter().enumerate() {
        acc += v * v;
        seg_csum[i] = acc;
    }

    let score = |r: f64| -> f64 {
        let (num, den) = limit_denominator(r, 4000);
        let pre_r = resample_poly(&pre0, num as usize, den as usize);
        let l = pre_r.len();
        if l >= seg.len() {
            return f64::NEG_INFINITY;
        }
        let corr = valid_correlate(seg, &pre_r);
        // windowed energy E[i:i+L]
        let tmpl_norm = (pre_r.iter().map(|v| v * v).sum::<f64>()).sqrt();
        let mut best = f64::NEG_INFINITY;
        for i in 0..corr.len() {
            let e_full = seg_csum[l - 1 + i];
            let e_prev = if i == 0 { 0.0 } else { seg_csum[i - 1] };
            let win_en = (e_full - e_prev).max(1e-12).sqrt();
            let ncc = corr[i].abs() / (win_en * tmpl_norm + 1e-12);
            if ncc > best {
                best = ncc;
            }
        }
        best
    };

    // Stage 1: coarse grid 0.84..1.06 step 0.004
    let mut best_r = arg_max_ratio(0.84, 1.060001, 0.004, &score);
    // Stage 2: fine ±0.006 step 0.0008
    best_r = arg_max_ratio(best_r - 0.006, best_r + 0.0061, 0.0008, &score);
    // Stage 3: finer ±0.0008 step 0.0002
    best_r = arg_max_ratio(best_r - 0.0008, best_r + 0.00081, 0.0002, &score);
    best_r
}

fn arg_max_ratio(lo: f64, hi: f64, step: f64, f: &dyn Fn(f64) -> f64) -> f64 {
    let mut best_r = lo;
    let mut best_v = f64::NEG_INFINITY;
    let mut r = lo;
    while r < hi {
        let v = f(r);
        if v > best_v {
            best_v = v;
            best_r = r;
        }
        r += step;
    }
    best_r
}

/// Resample received audio by `1/r_hat` to restore nominal symbol timing.
/// Port of `dd_common.correct_speed` (short-circuits near r=1).
pub fn correct_speed(audio: &[f64], r_hat: f64) -> Vec<f64> {
    if (r_hat - 1.0).abs() < 1e-4 {
        return audio.to_vec();
    }
    let (num, den) = limit_denominator(1.0 / r_hat, 2000);
    resample_poly(audio, num as usize, den as usize)
}

// ---------------------------------------------------------------------------
// Flutter-tracking non-coherent tone demod
// ---------------------------------------------------------------------------

/// Port of `dd_common.tracked_tone_demod`. Returns one M-length tone-energy
/// vector per recovered symbol (caller maps each via `ComboScheme::energies_to_bits`).
///
/// `freqs`: the M tone frequencies. `n`: samples per symbol. `bps`: bits/sym
/// (used only for the `n_bits` stop). Defaults mirror `make_tracked_combo`:
/// acq=40, track=3, do_speed=true, center_bias=0.03, vel_gain=0.0, n_bits=1<<20.
pub fn tracked_tone_demod(
    audio: &[f64],
    freqs: &[f64],
    n: usize,
    bps: usize,
    n_bits: usize,
    preamble_seconds: f64,
    acq: i64,
    track: i64,
    do_speed: bool,
    center_bias: f64,
    vel_gain: f64,
) -> Vec<Vec<f64>> {
    let audio: Vec<f64> = if do_speed {
        let r = estimate_speed(audio, preamble_seconds);
        correct_speed(audio, r)
    } else {
        audio.to_vec()
    };
    let m = freqs.len();
    let start = find_preamble(&audio, preamble_seconds) as i64;

    // basis[mi][ni] = exp(-2j*pi*freqs[mi]*ni/FS)
    let mut basis_re = vec![vec![0.0f64; n]; m];
    let mut basis_im = vec![vec![0.0f64; n]; m];
    for mi in 0..m {
        for ni in 0..n {
            let ang = -2.0 * PI * freqs[mi] * (ni as f64) / FS;
            basis_re[mi][ni] = ang.cos();
            basis_im[mi][ni] = ang.sin();
        }
    }

    let len = audio.len() as i64;
    // score + energy vector at a given base offset
    let sc_off = |base: i64| -> (f64, Option<Vec<f64>>) {
        if base < 0 {
            return (-1.0, None);
        }
        let b = base as usize;
        let mut seg = vec![0.0f64; n];
        let avail = if b < audio.len() { audio.len() - b } else { 0 };
        if avail < n {
            if avail < n / 2 {
                return (-1.0, None);
            }
            for i in 0..avail {
                let v = audio[b + i];
                seg[i] = if v.is_finite() { v } else { 0.0 };
            }
            // rest stays zero (pad)
        } else {
            for i in 0..n {
                let v = audio[b + i];
                seg[i] = if v.is_finite() { v } else { 0.0 };
            }
        }
        let mut e = vec![0.0f64; m];
        for mi in 0..m {
            let (mut re, mut im) = (0.0f64, 0.0f64);
            let br = &basis_re[mi];
            let bi = &basis_im[mi];
            for ni in 0..n {
                re += br[ni] * seg[ni];
                im += bi[ni] * seg[ni];
            }
            e[mi] = (re * re + im * im).sqrt();
        }
        let mx = e.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let med = median(&e);
        (mx / (med + 1e-9), Some(e))
    };

    // wide acquisition for symbol 0
    let mut best: Option<(f64, i64)> = None;
    let mut off = -acq;
    while off <= acq {
        let (s, _) = sc_off(start + off);
        if s > 0.0 && best.map_or(true, |(bs, _)| s > bs) {
            best = Some((s, off));
        }
        off += 1;
    }
    let mut drift = best.map_or(0.0, |(_, o)| o as f64);
    let mut vel = 0.0f64;
    let mut syms: Vec<Vec<f64>> = Vec::new();
    let mut pos = start as f64;

    while pos + drift + vel + (n as f64 / 2.0).floor() <= len as f64 {
        let predicted = drift + vel;
        let base = (pos + predicted).round() as i64;
        let mut b: Option<(f64, i64, Vec<f64>)> = None;
        let mut d = -track;
        while d <= track {
            let (s, e) = sc_off(base + d);
            if s > 0.0 {
                let s_adj = s * (1.0 - center_bias * (d.abs() as f64));
                if b.as_ref().map_or(true, |(bs, _, _)| s_adj > *bs) {
                    b = Some((s_adj, d, e.unwrap()));
                }
            }
            d += 1;
        }
        let (_, dsel, e) = match b {
            Some(v) => v,
            None => break,
        };
        let (s, _) = sc_off(base + dsel);
        let new_drift = predicted + dsel as f64;
        let increment = new_drift - drift;
        vel = (1.0 - vel_gain) * vel + vel_gain * increment;
        drift = new_drift;
        let _ = s;
        syms.push(e);
        pos += n as f64;
        if syms.len() * bps >= n_bits {
            break;
        }
    }
    syms
}

fn median(v: &[f64]) -> f64 {
    let mut s = v.to_vec();
    s.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = s.len();
    if n == 0 {
        0.0
    } else if n % 2 == 1 {
        s[n / 2]
    } else {
        0.5 * (s[n / 2 - 1] + s[n / 2])
    }
}

pub const DEFAULT_PREAMBLE_SECONDS: f64 = PREAMBLE_SECONDS;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preamble_length_and_amp() {
        let p = make_preamble(PREAMBLE_SECONDS);
        assert_eq!(p.len(), 12000);
        // first sample: cos(0)*0.65 = 0.65
        assert!((p[0] - 0.65).abs() < 1e-9);
        assert!(p.iter().all(|v| v.abs() <= 0.65 + 1e-9));
    }

    #[test]
    fn find_preamble_locates_inserted_chirp() {
        let pre = make_preamble(PREAMBLE_SECONDS);
        let lead = 1234usize;
        let mut audio = vec![0.0f64; lead];
        audio.extend_from_slice(&pre);
        audio.extend(std::iter::repeat(0.0).take(5000));
        let ds = find_preamble(&audio, PREAMBLE_SECONDS);
        // data starts right after the preamble: lead + len(pre)
        assert!((ds as i64 - (lead + pre.len()) as i64).abs() <= 1);
    }

    #[test]
    fn resample_identity_when_equal() {
        let x: Vec<f64> = (0..100).map(|i| (i as f64 * 0.1).sin()).collect();
        let y = resample_poly(&x, 3, 3);
        assert_eq!(x, y);
    }

    #[test]
    fn limit_denominator_basic() {
        let (n, d) = limit_denominator(0.88, 2000);
        assert!((n as f64 / d as f64 - 0.88).abs() < 1e-6);
        let (n2, d2) = limit_denominator(1.0, 2000);
        assert_eq!((n2, d2), (1, 1));
    }

    #[test]
    fn estimate_speed_recovers_unity_on_clean_chirp() {
        // build audio = lead + preamble + tone; estimate_speed should give ~1.0
        let pre = make_preamble(PREAMBLE_SECONDS);
        let mut audio = vec![0.0f64; 500];
        audio.extend_from_slice(&pre);
        for i in 0..20000 {
            audio.push(0.2 * (2.0 * PI * 1000.0 * i as f64 / FS).sin());
        }
        let r = estimate_speed(&audio, PREAMBLE_SECONDS);
        assert!((r - 1.0).abs() < 0.01, "expected ~1.0, got {r}");
    }
}
