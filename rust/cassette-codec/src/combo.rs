//! combo — combinatorial K-of-M multitone FSK (the R-1 floor PHY).
//!
//! Port of `experiments/capacity/c2_combo_mfsk.py` (tone grid + combinatorial
//! number-system bijection + bits/sym) and the energy→bits mapping of
//! `experiments/deepdive2/d3d4_combo_tracked.py`.
//!
//! All M tones sit at EXACT FFT-bin centres (Olivia orthogonality) so the FFT
//! magnitude at each tone bin is a leakage-free energy measurement. Information
//! is carried by WHICH K of M tones are lit — index modulation across the bank,
//! decoded non-coherently (energy only), which is what shrugs off tape flutter.

use std::collections::HashMap;

const SAMPLE_RATE: f64 = 48_000.0;
const USABLE_F_LOW: f64 = 400.0;
const USABLE_F_HIGH: f64 = 10_000.0;

/// Build the exact-bin orthogonal tone grid for `m` tones.
///
/// Returns `(n_samples_per_sym, bin_indices, freqs)`. Mirrors
/// `_build_tone_grid` exactly: sweep N near the Olivia estimate until all M
/// tones land in `[f_low, f_high]` at integer FFT bins.
pub fn build_tone_grid(m: usize) -> (usize, Vec<usize>, Vec<f64>) {
    let bw = USABLE_F_HIGH - USABLE_F_LOW;
    let delta_f_est = bw / (m.max(2) - 1) as f64;
    for d_n in -10i64..30 {
        let n = ((SAMPLE_RATE / delta_f_est).round() as i64) + d_n;
        if n <= 0 {
            continue;
        }
        let n = n as usize;
        let delta_f = SAMPLE_RATE / n as f64;
        let b0 = (USABLE_F_LOW / delta_f).ceil() as i64;
        let b1 = b0 + m as i64 - 1;
        let fa = b0 as f64 * delta_f;
        let fb = b1 as f64 * delta_f;
        if fa >= USABLE_F_LOW - 1e-3 && fb <= USABLE_F_HIGH + 1e-3 {
            let bins: Vec<usize> = (b0..b0 + m as i64).map(|x| x as usize).collect();
            let freqs: Vec<f64> = bins.iter().map(|&b| b as f64 * delta_f).collect();
            return (n, bins, freqs);
        }
    }
    panic!("Could not find clean integer-bin tone grid for M={m}");
}

/// All K-subsets of {0..M-1} in lexicographic order (the combinatorial number
/// system). `table[i]` is the i-th subset (sorted asc); `rev[subset] = i`.
fn build_comb_tables(m: usize, k: usize) -> (Vec<Vec<usize>>, HashMap<Vec<usize>, usize>, usize) {
    let mut subsets: Vec<Vec<usize>> = Vec::new();
    let mut idx = vec![0usize; k];
    for i in 0..k {
        idx[i] = i;
    }
    loop {
        subsets.push(idx.clone());
        // advance to next lexicographic combination of range(m) choose k
        let mut i = k as isize - 1;
        while i >= 0 && idx[i as usize] == m - k + i as usize {
            i -= 1;
        }
        if i < 0 {
            break;
        }
        idx[i as usize] += 1;
        for j in (i as usize + 1)..k {
            idx[j] = idx[j - 1] + 1;
        }
    }
    let n_sym = subsets.len();
    let rev: HashMap<Vec<usize>, usize> =
        subsets.iter().cloned().enumerate().map(|(i, s)| (s, i)).collect();
    (subsets, rev, n_sym)
}

/// The combinatorial K-of-M scheme: grid + tables + symbol sizing.
pub struct ComboScheme {
    pub m: usize,
    pub k: usize,
    /// samples per symbol (FFT size)
    pub n: usize,
    pub bins: Vec<usize>,
    pub freqs: Vec<f64>,
    pub bits_per_sym: usize,
    pub sym_cap: usize,
    pub preamble_seconds: f64,
    rev: HashMap<Vec<usize>, usize>,
    #[allow(dead_code)]
    table: Vec<Vec<usize>>,
}

impl ComboScheme {
    pub fn new(m: usize, k: usize) -> Self {
        assert!(1 <= k && k < m, "need 1 <= K < M, got K={k} M={m}");
        let (n, bins, freqs) = build_tone_grid(m);
        let (table, rev, n_sym) = build_comb_tables(m, k);
        let bits_per_sym = ((n_sym as f64).log2().floor() as usize).max(1);
        let sym_cap = 1usize << bits_per_sym;
        ComboScheme {
            m,
            k,
            n,
            bins,
            freqs,
            bits_per_sym,
            sym_cap,
            preamble_seconds: crate::PREAMBLE_SECONDS,
            rev,
            table,
        }
    }

    /// Map one symbol's M-length tone-energy vector to `bits_per_sym` bits
    /// (MSB-first), exactly as `d3d4_combo_tracked.make_tracked_combo.demod`:
    /// top-K energy bins → sorted subset → reverse lookup (default 0) → bits.
    pub fn energies_to_bits(&self, e: &[f64], out: &mut Vec<u8>) {
        debug_assert_eq!(e.len(), self.m);
        let mut subset = top_k_indices(e, self.k);
        subset.sort_unstable();
        let sidx = (*self.rev.get(&subset).unwrap_or(&0)).min(self.sym_cap - 1);
        let bps = self.bits_per_sym;
        for j in 0..bps {
            out.push(((sidx >> (bps - 1 - j)) & 1) as u8);
        }
    }
}

/// Indices of the K largest values in `e` (unordered). Matches numpy
/// `argpartition(e, -K)[-K:]` for the no-tie case (real tone energies).
fn top_k_indices(e: &[f64], k: usize) -> Vec<usize> {
    let mut idx: Vec<usize> = (0..e.len()).collect();
    idx.sort_unstable_by(|&a, &b| {
        e[b].partial_cmp(&e[a]).unwrap_or(std::cmp::Ordering::Equal)
    });
    idx.truncate(k);
    idx
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grid_m16_matches_python() {
        let (n, bins, freqs) = build_tone_grid(16);
        assert_eq!(n, 77);
        assert_eq!(bins, (1..=16).collect::<Vec<_>>());
        let df = SAMPLE_RATE / 77.0;
        assert!((df - 623.3766233766).abs() < 1e-6);
        assert!((freqs[0] - df).abs() < 1e-9);
        assert!((freqs[15] - 16.0 * df).abs() < 1e-9);
        assert!(freqs[15] <= USABLE_F_HIGH + 1e-3);
    }

    #[test]
    fn comb_tables_m16k2_lex_order() {
        let (table, rev, n_sym) = build_comb_tables(16, 2);
        assert_eq!(n_sym, 120);
        assert_eq!(table[0], vec![0, 1]);
        assert_eq!(table[1], vec![0, 2]);
        assert_eq!(table[5], vec![0, 6]);
        assert_eq!(rev[&vec![0usize, 1]], 0);
        assert_eq!(rev[&vec![0usize, 2]], 1);
        assert_eq!(rev[&vec![14usize, 15]], 119);
    }

    #[test]
    fn scheme_sizing_m16k2() {
        let s = ComboScheme::new(16, 2);
        assert_eq!(s.bits_per_sym, 6);
        assert_eq!(s.sym_cap, 64);
    }

    #[test]
    fn energies_to_bits_topk() {
        let s = ComboScheme::new(16, 2);
        // tones 0,2 -> subset (0,2) -> rev=1 -> 000001
        let mut e = vec![0.1f64; 16];
        e[0] = 9.0;
        e[2] = 8.0;
        let mut bits = Vec::new();
        s.energies_to_bits(&e, &mut bits);
        assert_eq!(bits, vec![0, 0, 0, 0, 0, 1]);

        // tones 14,15 -> subset (14,15) -> rev=119; sidx=min(119,63)=63 -> 111111
        let mut e2 = vec![0.1f64; 16];
        e2[14] = 9.0;
        e2[15] = 8.0;
        let mut bits2 = Vec::new();
        s.energies_to_bits(&e2, &mut bits2);
        assert_eq!(bits2, vec![1, 1, 1, 1, 1, 1]);
    }
}
