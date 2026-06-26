//! dqpsk — the R0 robust coherent-DQPSK rung demod (port of
//! `h4_dqpsk.DQPSKScheme.demod` / `x9_resampling_pll.ResamplingPLLDemod._demod_ema`).
//!
//! P parallel continuous-phase carriers (plus one mid-band unmodulated pilot)
//! at ≥562 Hz spacing, each carrying DQPSK (2 bits/carrier/symbol as a phase
//! increment symbol-to-symbol on the SAME carrier, so static channel phase
//! cancels). Per symbol we take a Hann-windowed complex DFT at each carrier on
//! an ABSOLUTE sample-time basis (so integer window re-centering is phase
//! transparent), use the pilot carrier's differential phase to track common
//! timing (EMA-smoothed, integer drift tracker), then differentially decide
//! each data carrier with a one-shot decision-directed timing refinement.
//!
//! This is the EMA front-end only (`ema_alpha = 0.5`) — the self-syncing clean
//! path that produced the golden record. Correctness is gated by RS(255,127),
//! which clears the residual BER (see `tests/r0_parity.rs`).

use crate::framing::{
    assemble, decode_payload, per_cw_decode, rx_codeword_matrix, ComboMeta, DecodedPayload,
};
use crate::sync::find_preamble;
use std::f64::consts::PI;

const FS: f64 = 48_000.0;

/// Gray decode: quadrant index q -> (a, b) bit pair.
/// GRAY_ENC = {(0,0):0,(0,1):1,(1,1):2,(1,0):3}; this is its inverse.
#[inline]
fn gray_dec(q: i64) -> (u8, u8) {
    match q {
        0 => (0, 0),
        1 => (0, 1),
        2 => (1, 1),
        _ => (1, 0), // 3
    }
}

/// Wrap to (-pi, pi]: `((x + pi) mod 2pi) - pi`, matching numpy `(x+pi)%(2pi)-pi`.
#[inline]
fn wrap_pi(x: f64) -> f64 {
    (x + PI).rem_euclid(2.0 * PI) - PI
}

/// The DQPSK scheme geometry + precomputed DFT basis.
pub struct DqpskScheme {
    pub p: usize,
    pub n: usize,
    pub spacing: usize,
    pub skip: usize,
    pub nw: usize,
    pub bins: Vec<usize>,
    pub freqs: Vec<f64>,
    pub pilot_idx: usize,
    pub data_idx: Vec<usize>,
    pub bits_per_sym: usize,
    pub preamble_seconds: f64,
    win: Vec<f64>,
    /// basis_re/im[k][n] = cos/sin(-2*pi*bins[k]*n/N), the n-dependent DFT factor.
    basis_re: Vec<Vec<f64>>,
    basis_im: Vec<Vec<f64>>,
}

impl DqpskScheme {
    /// Build the scheme from the section's `dqpsk_params`. `skip = None` -> N/8.
    /// For R0: P=10, N=256, spacing=4 -> bins [4,8,..,44], pilot_idx=5 (4500 Hz).
    pub fn new(p: usize, n: usize, spacing: usize, skip: Option<usize>) -> Self {
        let skip = skip.unwrap_or(n / 8);
        let df = FS / n as f64;
        let b0 = (750.0 / df).round() as usize;
        let nc = p + 1;
        let bins: Vec<usize> = (0..nc).map(|i| b0 + spacing * i).collect();
        let freqs: Vec<f64> = bins.iter().map(|&b| b as f64 * df).collect();
        let pilot_idx = nc / 2;
        let data_idx: Vec<usize> = (0..nc).filter(|&i| i != pilot_idx).collect();
        let nw = n - 2 * skip;
        // symmetric Hann(Nw): w[k] = 0.5*(1 - cos(2*pi*k/(Nw-1)))
        let win: Vec<f64> = (0..nw)
            .map(|k| 0.5 * (1.0 - (2.0 * PI * k as f64 / (nw as f64 - 1.0)).cos()))
            .collect();
        // precompute the fixed n-dependent DFT basis exp(-2j*pi*bins[k]*n/N)
        let mut basis_re = vec![vec![0.0f64; nw]; nc];
        let mut basis_im = vec![vec![0.0f64; nw]; nc];
        for k in 0..nc {
            for nn in 0..nw {
                let ang = -2.0 * PI * bins[k] as f64 * nn as f64 / n as f64;
                basis_re[k][nn] = ang.cos();
                basis_im[k][nn] = ang.sin();
            }
        }
        DqpskScheme {
            p,
            n,
            spacing,
            skip,
            nw,
            bins,
            freqs,
            pilot_idx,
            data_idx,
            bits_per_sym: 2 * p,
            preamble_seconds: 0.25,
            win,
            basis_re,
            basis_im,
        }
    }

    /// Number of data symbols carrying `nbits` (ceil division by bits/symbol).
    #[inline]
    pub fn nsym_data(&self, nbits: usize) -> usize {
        (nbits + self.bits_per_sym - 1) / self.bits_per_sym
    }

    /// Per-symbol complex DFT at one carrier on the absolute-time basis:
    /// `c = exp(-2j*pi*bins[k]*lo/N) * sum_n g[n]*exp(-2j*pi*bins[k]*n/N)`.
    /// `seg` is the already-windowed segment (g[n] = audio*win). Returns (re, im).
    #[inline]
    fn dft_carrier(&self, k: usize, seg: &[f64], lo: i64) -> (f64, f64) {
        let br = &self.basis_re[k];
        let bi = &self.basis_im[k];
        let mut s_re = 0.0;
        let mut s_im = 0.0;
        for nn in 0..self.nw {
            let g = seg[nn];
            s_re += g * br[nn];
            s_im += g * bi[nn];
        }
        let ang_lo = -2.0 * PI * self.bins[k] as f64 * (lo as f64) / self.n as f64;
        let (pf_im, pf_re) = ang_lo.sin_cos();
        (pf_re * s_re - pf_im * s_im, pf_re * s_im + pf_im * s_re)
    }

    /// Demodulate one frame window into the per-symbol quadrant matrix
    /// `q[i][j]` (i in 0..nd data symbols, j in 0..P data carriers) under a
    /// chosen pilot-EMA `ema_alpha` and analysis-window `shift` (samples added
    /// to `skip`). This is the shared core of `_demod_ema` /
    /// `_shift_pass_ema` + `_decide_refine`. With `ema=0.5, shift=0` it is the
    /// original single front-end path.
    pub fn demod_q(&self, win_audio: &[f64], nd: usize, ema: f64, shift: i64) -> Vec<Vec<i64>> {
        let ds = find_preamble(win_audio, self.preamble_seconds) as i64;
        let total = nd + 1;
        let nc = self.p + 1;
        let n = self.n as i64;
        let skip = self.skip as i64;
        let fpil = self.freqs[self.pilot_idx];

        // per-symbol c[i][k] (complex), pilot-tracked EMA timing
        let mut c_re = vec![vec![0.0f64; nc]; total];
        let mut c_im = vec![vec![0.0f64; nc]; total];
        let mut dtau = vec![0.0f64; total];
        let mut drift = 0.0f64;
        let mut sm = 0.0f64;
        let mut seg = vec![0.0f64; self.nw];

        for i in 0..total {
            let base = ds + (i as i64) * n + drift.round() as i64;
            let lo = base + skip + shift;
            // gather the windowed segment (zero-pad if short / out of range)
            for nn in 0..self.nw {
                let idx = lo + nn as i64;
                let v = if idx >= 0 && (idx as usize) < win_audio.len() {
                    win_audio[idx as usize]
                } else {
                    0.0
                };
                seg[nn] = v * self.win[nn];
            }
            for k in 0..nc {
                let (re, im) = self.dft_carrier(k, &seg, lo);
                c_re[i][k] = re;
                c_im[i][k] = im;
            }
            if i > 0 {
                // dp = angle(c[i,pil] * conj(c[i-1,pil]))
                let (a_re, a_im) = (c_re[i][self.pilot_idx], c_im[i][self.pilot_idx]);
                let (b_re, b_im) = (c_re[i - 1][self.pilot_idx], c_im[i - 1][self.pilot_idx]);
                let pr = a_re * b_re + a_im * b_im; // re of a*conj(b)
                let pi_ = a_im * b_re - a_re * b_im; // im of a*conj(b)
                let dp = pi_.atan2(pr);
                sm = (1.0 - ema) * (dp / (2.0 * PI * fpil)) + ema * sm;
                dtau[i] = sm;
                drift -= dtau[i] * FS;
                drift = drift.clamp(-200.0, 200.0);
            }
        }

        // differential decisions (refine=true)
        let fd: Vec<f64> = self.data_idx.iter().map(|&j| self.freqs[j]).collect();
        let pp = self.data_idx.len();
        // dphi[i][j] for i in 0..nd
        let mut dphi = vec![vec![0.0f64; pp]; nd];
        for i in 0..nd {
            for (j, &dj) in self.data_idx.iter().enumerate() {
                // d = c[i+1]*conj(c[i]); angle of d at carrier dj
                let (a_re, a_im) = (c_re[i + 1][dj], c_im[i + 1][dj]);
                let (b_re, b_im) = (c_re[i][dj], c_im[i][dj]);
                let pr = a_re * b_re + a_im * b_im;
                let pim = a_im * b_re - a_re * b_im;
                let ang = pim.atan2(pr);
                dphi[i][j] = ang - 2.0 * PI * dtau[i + 1] * fd[j];
            }
        }
        let qpi = PI / 2.0;
        let den: f64 = fd.iter().map(|f| f * f).sum();
        // initial decision
        let mut q = vec![vec![0i64; pp]; nd];
        for i in 0..nd {
            for j in 0..pp {
                q[i][j] = (dphi[i][j] / qpi).round() as i64;
            }
        }
        // one-shot decision-directed common-timing refinement
        for i in 0..nd {
            let mut num = 0.0f64;
            for j in 0..pp {
                let res = wrap_pi(dphi[i][j] - q[i][j] as f64 * qpi);
                num += res * fd[j];
            }
            let dtau_res = num / (2.0 * PI * den);
            for j in 0..pp {
                let dphi2 = dphi[i][j] - 2.0 * PI * dtau_res * fd[j];
                q[i][j] = (dphi2 / qpi).round() as i64;
            }
        }
        q
    }

    /// (nd, P) quadrants -> frame bits, carrier-block layout (inverse of
    /// `bits_to_quadrants`): `bits[j*(2*nd) + i*2 + {0,1}]`.
    pub fn quadrants_to_bits(&self, q: &[Vec<i64>]) -> Vec<u8> {
        let pp = self.data_idx.len();
        let nd = q.len();
        let mut bits = vec![0u8; pp * nd * 2];
        for j in 0..pp {
            for i in 0..nd {
                let qq = q[i][j].rem_euclid(4);
                let (a, b) = gray_dec(qq);
                let base = j * (2 * nd) + i * 2;
                bits[base] = a;
                bits[base + 1] = b;
            }
        }
        bits
    }

    /// Demodulate one frame window into frame bits (carrier-block layout) via
    /// the original single EMA=0.5 front-end. `win_audio` is the padded frame
    /// window (f64); `nd` = data symbols.
    pub fn demod(&self, win_audio: &[f64], nd: usize) -> Vec<u8> {
        let q = self.demod_q(win_audio, nd, 0.5, 0);
        self.quadrants_to_bits(&q)
    }
}

/// Frame-layout info for the R0 section (from the manifest section block).
pub struct R0Section {
    pub p: usize,
    pub n: usize,
    pub spacing: usize,
    pub skip: Option<usize>,
    pub pilot_hz: f64,
    pub frame_starts: Vec<i64>,
    pub body_end: i64,
}

/// Decode the R0 (robust DQPSK) rung from globally-synced nominal audio.
///
/// Mirrors `m9_decode._demod_section_frames` + `m10._decode_section` pass-1 EMA
/// front-end: slice each frame's padded window, EMA-demod via `DqpskScheme`,
/// then the same RS(255,k) + column de-interleave decode as the floor rung.
pub fn decode_r0_section(
    audio_nom: &[f64],
    section: &R0Section,
    align: i64,
    meta: &ComboMeta,
) -> DecodedPayload {
    let sch = DqpskScheme::new(section.p, section.n, section.spacing, section.skip);
    let n_total = audio_nom.len() as i64;

    // window length: preamble + (nsym_data(frame_bits)+1)*N (fixed across frames,
    // exactly as the Python flen_full = len(modulate(zeros(frame_bits)))).
    let preamble_samples = (sch.preamble_seconds * FS) as i64; // 12000
    let nd_nominal = sch.nsym_data(meta.frame_bits);
    let flen_full = preamble_samples + (nd_nominal as i64 + 1) * section.n as i64;
    let pad_lo = (0.30 * FS) as i64; // 14400
    let pad_hi = (0.05 * FS) as i64; // 2400

    let nf = meta.n_frames;
    let mut frames_bits: Vec<Vec<u8>> = Vec::with_capacity(section.frame_starts.len());
    for (fi, &st) in section.frame_starts.iter().enumerate() {
        let nominal = if fi < nf - 1 {
            meta.frame_bits
        } else {
            meta.stream_bits - meta.frame_bits * (nf - 1)
        };
        let nd = sch.nsym_data(nominal);
        let st_i = st + align;
        let w_lo = (st_i - pad_lo).max(0);
        let w_hi = n_total.min(st_i + flen_full + pad_hi);
        if w_hi <= w_lo {
            frames_bits.push(Vec::new());
            continue;
        }
        let win = &audio_nom[w_lo as usize..w_hi as usize];
        frames_bits.push(sch.demod(win, nd));
    }

    decode_payload(&frames_bits, meta)
}

/// Per-frame analysis windows (slice bounds + data-symbol count) for the R0
/// section — shared geometry of `decode_r0_section` / Python
/// `_demod_section_frames`.
struct FrameWindow {
    lo: usize,
    hi: usize,
    nd: usize,
}

fn r0_frame_windows(
    audio_nom: &[f64],
    sch: &DqpskScheme,
    section: &R0Section,
    align: i64,
    meta: &ComboMeta,
) -> Vec<FrameWindow> {
    let n_total = audio_nom.len() as i64;
    let preamble_samples = (sch.preamble_seconds * FS) as i64; // 12000
    let nd_nominal = sch.nsym_data(meta.frame_bits);
    let flen_full = preamble_samples + (nd_nominal as i64 + 1) * section.n as i64;
    let pad_lo = (0.30 * FS) as i64; // 14400
    let pad_hi = (0.05 * FS) as i64; // 2400
    let nf = meta.n_frames;

    let mut out = Vec::with_capacity(section.frame_starts.len());
    for (fi, &st) in section.frame_starts.iter().enumerate() {
        let nominal = if fi < nf - 1 {
            meta.frame_bits
        } else {
            meta.stream_bits - meta.frame_bits * (nf - 1)
        };
        let nd = sch.nsym_data(nominal);
        let st_i = st + align;
        let w_lo = (st_i - pad_lo).max(0);
        let w_hi = n_total.min(st_i + flen_full + pad_hi);
        let (lo, hi) = if w_hi <= w_lo {
            (0usize, 0usize)
        } else {
            (w_lo as usize, w_hi as usize)
        };
        out.push(FrameWindow { lo, hi, nd });
    }
    out
}

/// Fill `union` with the first CRC-passing candidate per codeword index (never
/// replaces). Returns the number of codewords still missing.
fn union_fill(union: &mut [Option<Vec<u8>>], msgs: Vec<Option<Vec<u8>>>) -> usize {
    for (i, m) in msgs.into_iter().enumerate() {
        if union[i].is_none() {
            if let Some(bytes) = m {
                union[i] = Some(bytes);
            }
        }
    }
    union.iter().filter(|m| m.is_none()).count()
}

/// The R0 RESCUE ENSEMBLE: CRC32-guarded per-codeword union across a front-end
/// EMA-alpha bank, then (for codewords still failing) the late-window dc0
/// stitched branches — the Rust port of `m10_decode._decode_section` (pass-1
/// ensemble union + pass-2 late-window dc0). Matches the Python rescue path on
/// a hard acoustic capture (vm38: front-end bank -> 1/31, late-window -> 0/31).
///
/// `crc32` is the manifest per-codeword CRC table (`crc32_codewords`). A decode
/// is only ever trusted when its CRC32 matches, so RS-implementation
/// differences vs Python can never cause a silent miscorrection.
pub fn decode_r0_ensemble(
    audio_nom: &[f64],
    section: &R0Section,
    align: i64,
    meta: &ComboMeta,
    crc32: &[u32],
) -> DecodedPayload {
    let sch = DqpskScheme::new(section.p, section.n, section.spacing, section.skip);
    let windows = r0_frame_windows(audio_nom, &sch, section, align, meta);
    let n_cw = meta.n_codewords;
    let mut union: Vec<Option<Vec<u8>>> = vec![None; n_cw];

    // ---- pass 1: front-end EMA-alpha bank + per-codeword union ----------
    // Matches m10's DQPSK_BANK EMA values (pll30 omitted — the EMA sweep alone
    // reaches the rescue=False floor on vm38; the missing codeword is recovered
    // by the late-window pass below).
    const EMA_BANK: [f64; 6] = [0.5, 0.6, 0.65, 0.7, 0.8, 0.4];
    let mut still = n_cw;
    for &ema in EMA_BANK.iter() {
        let frames_bits: Vec<Vec<u8>> = windows
            .iter()
            .map(|w| {
                if w.hi <= w.lo {
                    Vec::new()
                } else {
                    let q = sch.demod_q(&audio_nom[w.lo..w.hi], w.nd, ema, 0);
                    sch.quadrants_to_bits(&q)
                }
            })
            .collect();
        let mat = rx_codeword_matrix(&frames_bits, meta);
        let msgs = per_cw_decode(&mat, meta, crc32);
        still = union_fill(&mut union, msgs);
        if still == 0 {
            break;
        }
    }

    // ---- pass 2: late-window dc0 stitched branches (ema0.6 base) --------
    // Mirror m10 `_late_window_branches` for base ema0.6: per frame demod the
    // dc0 (data carrier 0, 750 Hz) shift grid, then for each scalar dc0 shift S
    // stitch q-col-0 from shift S with all other carriers from shift 0
    // (branch `lw_ema0.6_S{S}`), union CRC-passing candidates. S16 recovers the
    // last codeword on vm38.
    if still > 0 {
        const LW_EMA: f64 = 0.6;
        // DC0_GRID_WIDE[1:] from Python: scalar dc0 late shifts.
        const LW_S: [i64; 10] = [8, 16, 24, 32, 40, 48, 56, 64, 72, 80];

        // base q at shift 0 for every frame (all carriers).
        let q0: Vec<Vec<Vec<i64>>> = windows
            .iter()
            .map(|w| {
                if w.hi <= w.lo {
                    Vec::new()
                } else {
                    sch.demod_q(&audio_nom[w.lo..w.hi], w.nd, LW_EMA, 0)
                }
            })
            .collect();

        for &s in LW_S.iter() {
            if still == 0 {
                break;
            }
            let frames_bits: Vec<Vec<u8>> = windows
                .iter()
                .enumerate()
                .map(|(fi, w)| {
                    if w.hi <= w.lo {
                        return Vec::new();
                    }
                    let qs = sch.demod_q(&audio_nom[w.lo..w.hi], w.nd, LW_EMA, s);
                    // stitch: dc0 (col 0) from shift s, other carriers from shift 0.
                    let mut q = q0[fi].clone();
                    for i in 0..q.len() {
                        q[i][0] = qs[i][0];
                    }
                    sch.quadrants_to_bits(&q)
                })
                .collect();
            let mat = rx_codeword_matrix(&frames_bits, meta);
            let msgs = per_cw_decode(&mat, meta, crc32);
            still = union_fill(&mut union, msgs);
        }
    }

    DecodedPayload {
        bytes: assemble(meta, &union),
        codewords_failed: still,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn r0_geometry() {
        let s = DqpskScheme::new(10, 256, 4, None);
        assert_eq!(s.skip, 32);
        assert_eq!(s.nw, 192);
        assert_eq!(s.bins, vec![4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44]);
        assert_eq!(s.pilot_idx, 5);
        assert_eq!(s.data_idx, vec![0, 1, 2, 3, 4, 6, 7, 8, 9, 10]);
        assert_eq!(s.bits_per_sym, 20);
        assert!((s.freqs[5] - 4500.0).abs() < 1e-9);
        assert!((s.freqs[0] - 750.0).abs() < 1e-9);
        assert!((s.freqs[10] - 8250.0).abs() < 1e-9);
        assert_eq!(s.win.len(), 192);
    }

    #[test]
    fn gray_roundtrip() {
        assert_eq!(gray_dec(0), (0, 0));
        assert_eq!(gray_dec(1), (0, 1));
        assert_eq!(gray_dec(2), (1, 1));
        assert_eq!(gray_dec(3), (1, 0));
    }
}
