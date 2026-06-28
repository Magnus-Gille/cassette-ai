//! WASM bindings for `cassette-codec`. Exposes `decode_floor(samples, manifest)`
//! to the Magnetic Vault companion app. Keeps the core crate free of any web
//! dependencies — this thin shim is the only wasm-aware layer.

use cassette_codec::decoder::{
    decode_floor_from_capture, FloorManifest, FloorSection, DEFAULT_F_HIGH, DEFAULT_F_LOW,
};
use cassette_codec::framing::ComboMeta;
use serde::Deserialize;
use wasm_bindgen::prelude::*;

fn default_f_low() -> f64 { DEFAULT_F_LOW }
fn default_f_high() -> f64 { DEFAULT_F_HIGH }

#[derive(Deserialize)]
struct JsonMeta {
    #[serde(rename = "M")]
    m: usize,
    #[serde(rename = "K")]
    k: usize,
    rs_n: usize,
    rs_k: usize,
    n_codewords: usize,
    frame_bits: usize,
    n_frames: usize,
    stream_bits: usize,
    payload_len: usize,
}

#[derive(Deserialize)]
struct JsonSection {
    frame_starts: Vec<i64>,
    body_end: i64,
    guard_samples: i64,
    // narrowband manifests carry their tone-bank band; absent → full-spectrum default.
    #[serde(default = "default_f_low")]
    f_low: f64,
    #[serde(default = "default_f_high")]
    f_high: f64,
}

#[derive(Deserialize)]
struct JsonManifest {
    tx_chirp0: i64,
    tx_chirp1: i64,
    section: JsonSection,
    meta: JsonMeta,
}

#[wasm_bindgen(start)]
pub fn _start() {
    console_error_panic_hook::set_once();
}

// ---------------------------------------------------------------------------
// Input validation — the decode_* bindings parse untrusted manifest JSON + an
// arbitrary sample array. Core code asserts / indexes / subtracts on these, so a
// malformed manifest would TRAP (crash the page) instead of returning Err. These
// pure validators (unit-tested natively) gate every binding and return a JS error.
// ---------------------------------------------------------------------------

const MAX_SAMPLES: usize = 200_000_000; // ~70 min @ 48 kHz; rejects pathological inputs

fn v_samples(s: &[f32]) -> Result<(), String> {
    if s.is_empty() {
        return Err("empty sample array".into());
    }
    if s.len() > MAX_SAMPLES {
        return Err(format!("sample array too large ({} > {MAX_SAMPLES})", s.len()));
    }
    if !s.iter().all(|x| x.is_finite()) {
        return Err("sample array contains non-finite values".into());
    }
    Ok(())
}

fn v_chirps(tx0: i64, tx1: i64) -> Result<(), String> {
    if tx0 < 0 {
        return Err(format!("tx_chirp0 ({tx0}) must be >= 0"));
    }
    if tx1 <= tx0 {
        return Err(format!("tx_chirp1 ({tx1}) must be > tx_chirp0 ({tx0})"));
    }
    // M5: cap layout positions — core arithmetic (decoder.rs:85, dqpsk.rs:376)
    // does i64 add/sub on chirp positions; positions in the billions overflow
    // downstream index arithmetic even without wrapping the i64 itself.
    if tx1 > MAX_LAYOUT_SAMPLES as i64 {
        return Err(format!(
            "tx_chirp1 ({tx1}) exceeds MAX_LAYOUT_SAMPLES ({MAX_LAYOUT_SAMPLES})"
        ));
    }
    Ok(())
}

/// M4: gate every `serde_json::from_str` call — reject the JSON string before
/// deserializing if it exceeds `MAX_MANIFEST_JSON_BYTES`. This prevents serde
/// from allocating unbounded `Vec<i64>` / `Vec<f64>` / `Vec<u32>` fields
/// (frame_starts, drop_freqs_hz, crc32_codewords) from a hostile payload.
/// MEDIUM 3: bound guard_samples before reaching decoder.rs frame-slice arithmetic.
///
/// `guard` is subtracted from (align + frame_start) in decoder.rs:85. A negative
/// guard is semantically invalid (would start decoding AFTER the frame start).
/// A very large guard overflows the i64 subtraction even with saturating arithmetic
/// (i64::MIN.saturating_add(st).saturating_sub(i64::MAX) = i64::MIN → wrong frame).
/// Real guards are a short non-negative preamble margin (e.g. 2400 samples = 50ms).
fn v_guard_samples(guard: i64) -> Result<(), String> {
    if guard < 0 {
        return Err(format!(
            "guard_samples={guard} must be >= 0 (negative guard would start after the frame)"
        ));
    }
    if guard > MAX_LAYOUT_SAMPLES as i64 {
        return Err(format!(
            "guard_samples={guard} exceeds MAX_LAYOUT_SAMPLES ({MAX_LAYOUT_SAMPLES})"
        ));
    }
    Ok(())
}

fn v_manifest_json_size(s: &str) -> Result<(), String> {
    if s.len() > MAX_MANIFEST_JSON_BYTES {
        return Err(format!(
            "manifest JSON too large ({} > {MAX_MANIFEST_JSON_BYTES} bytes)",
            s.len()
        ));
    }
    Ok(())
}

// ── Dimension caps (Fix B, revised codex round 4 + self-review round 5) ─────
// Derived from REPO-WIDE max values (experiments/**/*manifest*.json including
// doom_ship) with generous headroom (≥4×). Previous caps were too low — doom
// manifests have n_codewords=9217 and n_frames=1902 (above old 4096/1024).
//
//   Dimension              Repo-wide max   Cap             Note
//   rs_n                   255             255             GF(2^8) hard limit
//   rs_k                   245             254             must be < rs_n
//   n_codewords            9217            32768           ~3.5× → next power of 2
//   frame_bits             81600           500_000         ~6× real max
//   n_frames               1902            8192            ~4.3× → power of 2
//   stream_bits            18_802_680      100_000_000     ~5.3× real max
//   payload_len            1_465_484       10_000_000      ~6.8× real max
//   p (DQPSK)              21              512             tests reach 200
//   n (DQPSK FFT)          256             65536           power-of-two
//   spacing                16              64              4× real max
//   (p+1)*nw basis         2816 (R3)       2_000_000       u64; ~710× real (CRITICAL 1)
//   M (floor)              64              128             2× real max
//   C(M,K) budget          41664           1_000_000       ~24× real max (count)
//   subset_element_budget  360 (M16/K2)    2_000_000       u64; M=22/K=11 → 8.5M blocked
//   MAX_FLOOR_N            306 (M=12 nb)   16384           caps resolved FFT window
//   MAX_D2X_DROPS          14              64              4.6× real max
//   MAX_MANIFEST_JSON      191 kB          2_097_152       (2 MiB)
//   MAX_LAYOUT_SAMPLES     126_610_624     300_000_000     ~90 min @ 48 kHz
//   MAX_FRAME_SPAN_SAMPLES 519_000 (doom)  5_000_000       ~9.6× real; fft_convolve alloc
//   guard_samples          2400            MAX_LAYOUT_SAMPLES  see v_guard_samples
const MAX_N_CW: usize = 32_768;
const MAX_FRAME_BITS: usize = 500_000;
const MAX_N_FRAMES: usize = 8_192;
const MAX_STREAM_BITS: usize = 100_000_000;
const MAX_PAYLOAD_LEN: usize = 10_000_000;
const MAX_P: usize = 512;
const MAX_N_FFT: usize = 65_536;
const MAX_SPACING: usize = 64;
/// CRITICAL 1: (p+1) × nw basis budget. DqpskScheme::from_geometry allocates
/// basis_re[nc][nw] and basis_im[nc][nw] (f64). Real max ≈ 2816 (R3: p=21, nw=128).
/// Cap 2_000_000 ≈ 710× real; blocks p=512/n=65536 attack (513×49152=25M > cap).
const MAX_DQPSK_BASIS: u64 = 2_000_000;
const MAX_M_FLOOR: usize = 128;
const MAX_FLOOR_N: usize = 16_384;
const MAX_D2X_DROPS: usize = 64;
const MAX_MANIFEST_JSON_BYTES: usize = 2_097_152; // 2 MiB
/// Maximum valid sample position in any manifest field (layout, chirps, frame_starts).
/// Derived from the longest real tape (m10doom2 tx_chirp1 = 126_610_624 ≈ 44 min @ 48kHz).
/// 300_000_000 ≈ 104 min: generous headroom for any realistic C-90 cassette.
const MAX_LAYOUT_SAMPLES: usize = 300_000_000;
const COMB_BUDGET: u64 = 1_000_000;
/// MEDIUM 2: subset element budget. build_comb_tables stores ncomb × k_eff usizes in
/// Vec<Vec<usize>> + HashMap keys. Real max: C(64,3)×4=166656. Cap 2_000_000 ≈ 12×;
/// blocks M=22/K=11 (705432×12=8.5M) while accepting C(128,3)×4=1.43M.
const SUBSET_ELEMENT_BUDGET: u64 = 2_000_000;
/// MEDIUM 4: max per-frame sample span. find_preamble→fft_convolve allocates
/// O(next_pow2(seg+pre)) Complex<f64>. 200M-sample single frame → ~8.6GB OOM.
/// Real max ≈ 519K (doom m10doom3). 5_000_000 ≈ 9.6× headroom.
const MAX_FRAME_SPAN_SAMPLES: i64 = 5_000_000;

/// Compute C(m, k) using u64 checked arithmetic.
/// Returns `None` on overflow (which would also exceed `COMB_BUDGET`).
fn checked_binomial(m: usize, k: usize) -> Option<u64> {
    if k > m {
        return Some(0);
    }
    let k = k.min(m - k); // use the smaller mirror
    let mut result: u64 = 1;
    for i in 0..k {
        // C(m,k) = product_{i=0}^{k-1} (m-i) / (i+1) — always exact (integer).
        result = result.checked_mul((m - i) as u64)? / (i + 1) as u64;
    }
    Some(result)
}

/// Validate the framing meta + frame layout (shared by floor/dqpsk/d2x).
///
/// Fix A: all products on untrusted fields use `u64` checked arithmetic so that
/// overflow is caught regardless of target pointer width (wasm32 = 32-bit usize).
/// Fix B: per-dimension caps above real maxima reject allocation-DoS values.
fn v_framing(
    rs_n: usize,
    rs_k: usize,
    n_cw: usize,
    frame_bits: usize,
    n_frames: usize,
    stream_bits: usize,
    payload_len: usize,
    frame_starts: &[i64],
    body_end: i64,
) -> Result<(), String> {
    // Fix B: dimension caps (before any arithmetic).
    if n_cw > MAX_N_CW {
        return Err(format!("n_codewords={n_cw} exceeds cap {MAX_N_CW}"));
    }
    if frame_bits > MAX_FRAME_BITS {
        return Err(format!("frame_bits={frame_bits} exceeds cap {MAX_FRAME_BITS}"));
    }
    if n_frames > MAX_N_FRAMES {
        return Err(format!("n_frames={n_frames} exceeds cap {MAX_N_FRAMES}"));
    }
    if stream_bits > MAX_STREAM_BITS {
        return Err(format!("stream_bits={stream_bits} exceeds cap {MAX_STREAM_BITS}"));
    }
    if payload_len > MAX_PAYLOAD_LEN {
        return Err(format!("payload_len={payload_len} exceeds cap {MAX_PAYLOAD_LEN}"));
    }
    if !(0 < rs_k && rs_k < rs_n && rs_n <= 255) {
        return Err(format!("need 0 < rs_k < rs_n <= 255, got rs_k={rs_k} rs_n={rs_n}"));
    }
    if n_frames == 0 || n_cw == 0 || frame_bits == 0 {
        return Err("n_frames / n_codewords / frame_bits must be > 0".into());
    }
    if frame_starts.len() != n_frames {
        return Err(format!("frame_starts.len()={} != n_frames={n_frames}", frame_starts.len()));
    }
    // Fix A: rs_n * n_cw * 8 via checked u64 (wasm32 usize is 32-bit: the product
    // can overflow even for individually-reasonable values under the caps above).
    let expected_sb = (rs_n as u64)
        .checked_mul(n_cw as u64)
        .and_then(|x| x.checked_mul(8));
    match expected_sb {
        None => {
            return Err(format!(
                "rs_n({rs_n}) * n_codewords({n_cw}) * 8 overflows"
            ))
        }
        Some(esb) if stream_bits as u64 != esb => {
            return Err(format!(
                "stream_bits={stream_bits} != rs_n*n_cw*8={esb}"
            ))
        }
        Some(_) => {}
    }
    // Fix A: rs_k * n_cw via checked u64.
    let max_payload = (rs_k as u64)
        .checked_mul(n_cw as u64)
        .ok_or_else(|| format!("rs_k({rs_k}) * n_codewords({n_cw}) overflows"))?;
    if payload_len as u64 > max_payload {
        return Err(format!("payload_len={payload_len} > rs_k*n_cw={max_payload}"));
    }
    if frame_starts.iter().any(|&s| s < 0) {
        return Err("frame_starts must be non-negative".into());
    }
    // M5: cap layout positions before they reach i64 add/sub in core paths.
    let layout_cap = MAX_LAYOUT_SAMPLES as i64;
    if frame_starts.iter().any(|&s| s > layout_cap) {
        return Err(format!(
            "a frame_start exceeds MAX_LAYOUT_SAMPLES ({MAX_LAYOUT_SAMPLES})"
        ));
    }
    if body_end > layout_cap {
        return Err(format!(
            "body_end={body_end} exceeds MAX_LAYOUT_SAMPLES ({MAX_LAYOUT_SAMPLES})"
        ));
    }
    if frame_starts.windows(2).any(|w| w[1] <= w[0]) {
        return Err("frame_starts must be strictly increasing".into());
    }
    if let Some(&last) = frame_starts.last() {
        if body_end < last {
            return Err(format!("body_end={body_end} < last frame_start={last}"));
        }
    }
    // MEDIUM 4: per-frame sample span cap — `find_preamble` (called by
    // tracked_tone_demod) allocates 2×next_pow2(seg_len+pre_len) Complex<f64>.
    // A 1-frame manifest with body_end=200M → seg≈200M → ~8.6GB WASM OOM.
    // Real max span ≈ 519K (doom m10doom3); 5_000_000 ≈ 9.6× headroom.
    // Safety: spans are non-negative because frame_starts is monotone and
    // body_end >= last frame_start (both verified above).
    {
        let max_span = frame_starts
            .windows(2)
            .map(|w| w[1] - w[0])
            .chain(frame_starts.last().map(|&s| body_end - s))
            .max()
            .unwrap_or(0);
        if max_span > MAX_FRAME_SPAN_SAMPLES {
            return Err(format!(
                "max frame span {max_span} samples exceeds MAX_FRAME_SPAN_SAMPLES=\
                 {MAX_FRAME_SPAN_SAMPLES} (would cause fft_convolve OOM)"
            ));
        }
    }
    // Guard against last-frame-nominal underflow in rx_codeword_matrix / dqpsk
    // demod loops: `stream_bits - frame_bits*(n_frames-1)` wraps to a huge usize
    // (release) or panics (debug) when (n_frames-1)*frame_bits >= stream_bits.
    // Fix A: use u64 checked arithmetic so this is safe on wasm32.
    if n_frames > 1 {
        match (frame_bits as u64).checked_mul((n_frames - 1) as u64) {
            None => {
                return Err(format!(
                    "frame_bits={frame_bits} * (n_frames-1)={} overflows",
                    n_frames - 1
                ))
            }
            Some(prior_bits) if prior_bits >= stream_bits as u64 => {
                return Err(format!(
                    "frame partition underflow: frame_bits*{nm1}={prior_bits} >= \
                     stream_bits={stream_bits} (last frame would have zero or negative bits)",
                    nm1 = n_frames - 1
                ))
            }
            Some(_) => {}
        }
    }
    Ok(())
}

/// Validate DQPSK/D2X carrier geometry. `skip` defaults to N/8 when absent.
///
/// Fix A: comb-fit arithmetic uses checked u64 (avoids wrapping on wasm32).
/// Fix B: caps on p, n, and spacing prevent allocation-DoS.
fn v_dqpsk(p: usize, n: usize, spacing: usize, skip: Option<usize>) -> Result<(), String> {
    // Fix B: dimension caps.
    if p > MAX_P {
        return Err(format!("DQPSK p={p} exceeds cap {MAX_P}"));
    }
    if n > MAX_N_FFT {
        return Err(format!("DQPSK n={n} exceeds cap {MAX_N_FFT}"));
    }
    if spacing > MAX_SPACING {
        return Err(format!("DQPSK spacing={spacing} exceeds cap {MAX_SPACING}"));
    }
    if p == 0 || spacing == 0 {
        return Err("DQPSK p and spacing must be > 0".into());
    }
    if n == 0 || !n.is_power_of_two() {
        return Err(format!("DQPSK N must be a power of two > 0, got {n}"));
    }
    let sk = skip.unwrap_or(n / 8);
    // C1: use checked u64 — on wasm32, `2 * sk` with large sk wraps to 0, making
    // the `>= n` check pass when it shouldn't. Checked arithmetic prevents this.
    let two_sk = (sk as u64)
        .checked_mul(2)
        .ok_or_else(|| format!("DQPSK 2*skip overflows (skip={sk})"))?;
    if two_sk >= n as u64 {
        return Err(format!("DQPSK 2*skip ({two_sk}) must be < N ({n})"));
    }
    // CRITICAL 1: (p+1) × nw basis product cap.
    // from_geometry allocates basis_re[nc][nw] and basis_im[nc][nw] (f64).
    // Per-dimension caps on p and n are insufficient — their PRODUCT can be huge:
    // p=512, n=65536, skip=n/8 → nw=49152 → 513×49152×2×8B ≈ 403MB → WASM OOM.
    {
        let nw = (n as u64) - two_sk; // safe: two_sk < n proven above
        match (p as u64 + 1).checked_mul(nw) {
            None => return Err(format!(
                "DQPSK basis (p+1)*nw overflows u64 (p={p}, n={n}, skip={sk})"
            )),
            Some(b) if b > MAX_DQPSK_BASIS => return Err(format!(
                "DQPSK basis (p+1)*nw={b} exceeds MAX_DQPSK_BASIS={MAX_DQPSK_BASIS} \
                 (p={p}, n={n}, skip={sk} → nw={nw}); \
                 allocates ~{}MB",
                b * 2 * 8 / 1_000_000
            )),
            Some(_) => {}
        }
    }
    // Fix A: comb-fit check via checked u64 (spacing*(p+8)+4 can wrap on wasm32).
    let comb_top = (p as u64)
        .checked_add(8)
        .and_then(|x| (spacing as u64).checked_mul(x))
        .and_then(|x| x.checked_add(4));
    match comb_top {
        None => return Err("DQPSK comb overflow (p/spacing too large)".into()),
        Some(top) if top > (n as u64) / 2 => {
            return Err("DQPSK carrier comb exceeds Nyquist for the given p/spacing".into())
        }
        Some(_) => {}
    }
    Ok(())
}

/// Validate D2X-specific drop/pilot geometry before calling
/// `DqpskScheme::new_dropnull`. That function has an internal
/// `assert_eq!(keep.len(), p)` which panics (traps the WASM page) on any
/// combination that leaves fewer or more data carriers than `p`. This
/// validator replicates the exact keep-count arithmetic from `new_dropnull`
/// and returns `Err` whenever the assert would fire.
///
/// Catches: duplicate drop freqs, drop freqs outside the comb, drop freqs
/// that match the pilot (wasting a drop slot), and N <= 128 (which would
/// make the hardcoded rect128 alternative frontend's nw = N - 2*64 ≤ 0).
fn v_d2x(
    p: usize,
    n: usize,
    spacing: usize,
    drop_freqs_hz: &[f64],
    pilot_hz: f64,
) -> Result<(), String> {
    if !pilot_hz.is_finite() || pilot_hz <= 0.0 {
        return Err(format!("D2X pilot_hz must be finite and positive, got {pilot_hz}"));
    }
    // M3: cap drop list length before allocating bins_full/freqs_full/drop_set.
    // Repo-wide max is 14 drops; MAX_D2X_DROPS=64 gives ~4.6× headroom.
    if drop_freqs_hz.len() > MAX_D2X_DROPS {
        return Err(format!(
            "D2X drop_freqs_hz.len()={} exceeds cap {MAX_D2X_DROPS}",
            drop_freqs_hz.len()
        ));
    }
    // A drop list longer than p is semantically impossible: there are at most
    // p+drops+1 comb bins total; more drops than p means no data carriers remain.
    if drop_freqs_hz.len() > p {
        return Err(format!(
            "D2X drop_freqs_hz.len()={} > p={p} — no data carriers would remain",
            drop_freqs_hz.len()
        ));
    }
    if drop_freqs_hz.iter().any(|f| !f.is_finite()) {
        return Err("D2X drop_freqs_hz contains non-finite values".into());
    }
    // For the hardcoded rect128 alternative frontend (skip=64 in decode_d2x_ensemble
    // PLAN), need N > 128 so nw = N - 2*64 > 0.
    if n <= 128 {
        return Err(format!(
            "D2X requires N > 128 for the rect128 analysis frontend (got N={n})"
        ));
    }
    // Replicate new_dropnull's keep-count arithmetic exactly.
    const FS_HZ: f64 = 48_000.0;
    let df = FS_HZ / n as f64;
    let b0 = (750.0 / df).round() as i64;
    let n_drop = drop_freqs_hz.len();
    // Fix A: nc_full via checked u64 (p + n_drop + 1 can overflow on wasm32 if
    // inputs are near usize::MAX, even though caps above bound them in practice).
    let nc_full = (p as u64)
        .checked_add(n_drop as u64)
        .and_then(|x| x.checked_add(1))
        .ok_or_else(|| "D2X: p + n_drop + 1 overflows".to_string())? as usize;
    let bins_full: Vec<i64> = (0..nc_full as i64)
        .map(|k| b0 + spacing as i64 * k)
        .collect();
    let freqs_full: Vec<f64> = bins_full.iter().map(|&b| b as f64 * df).collect();
    // pilot index = argmin |freqs_full[k] - pilot_hz|.
    let pilot_idx_full = freqs_full
        .iter()
        .enumerate()
        .min_by(|(_, a), (_, b)| {
            ((*a - pilot_hz).abs())
                .partial_cmp(&((*b - pilot_hz).abs()))
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(i, _)| i)
        .unwrap_or(0);
    // drop_set: integer-Hz rounded frequencies to remove (mirrors new_dropnull).
    let drop_set: Vec<i64> = drop_freqs_hz.iter().map(|&f| f.round() as i64).collect();
    // Check for duplicates in the drop list (would silently skip them, reducing keep count).
    let mut seen = std::collections::HashSet::new();
    for &fi in &drop_set {
        if !seen.insert(fi) {
            return Err(format!(
                "D2X drop_freqs_hz contains duplicate entry at ~{fi} Hz \
                 (keep.len() would be > p)"
            ));
        }
    }
    // Count how many comb carriers survive after removing pilot and drops.
    let mut keep_count = 0usize;
    for k in 0..nc_full {
        if k == pilot_idx_full {
            continue;
        }
        if drop_set.contains(&(freqs_full[k].round() as i64)) {
            continue;
        }
        keep_count += 1;
    }
    if keep_count != p {
        return Err(format!(
            "D2X drop_freqs_hz/pilot_hz combination yields {keep_count} data carriers \
             but p={p}: check for duplicate drops, frequencies matching the pilot, \
             or frequencies outside the carrier comb [would panic in new_dropnull]"
        ));
    }
    Ok(())
}

/// Validate that `build_tone_grid_band(m, f_low, f_high)` will succeed —
/// i.e. that the -10..30 FFT-size sweep finds at least one N for which M tones
/// land at exact integer FFT bins inside [f_low, f_high]. Replicates the exact
/// loop from `combo::build_tone_grid_band` so we can return `Err` instead of
/// reaching the panic on line 44 of that file.
///
/// Also validates C(M,K) against `COMB_BUDGET` — `build_comb_tables` allocates
/// a `Vec` of all C(M,K) subsets, which OOMs for large M and K.
///
/// Call this in `decode_floor` after the basic band check, before constructing
/// `FloorManifest` (which passes the band into `ComboScheme::new_band`).
fn v_floor_tone_grid(m: usize, k: usize, f_low: f64, f_high: f64) -> Result<(), String> {
    // Fix B: M cap — build_tone_grid builds a Vec<f64> of M freqs and a M×N table.
    if m > MAX_M_FLOOR {
        return Err(format!("floor M={m} exceeds cap {MAX_M_FLOOR}"));
    }
    // Basic sanity first (mirrors the band check already in decode_floor).
    if !f_low.is_finite() || !f_high.is_finite() || f_low <= 0.0 || f_high <= f_low {
        return Err(format!(
            "invalid floor band: f_low={f_low} f_high={f_high} \
             (must be finite, positive, f_low < f_high)"
        ));
    }
    if !(k >= 1 && k < m) {
        return Err(format!("floor needs 1 <= K < M, got K={k} M={m}"));
    }
    // Fix B: C(M,K) budget — build_comb_tables enumerates ALL C(M,K) subsets in a Vec.
    // OOM for large M and K (e.g. C(64,8) ≈ 4.4 billion).
    let ncomb = match checked_binomial(m, k) {
        None => {
            return Err(format!(
                "C({m},{k}) overflows u64 — refusing to build comb table"
            ))
        }
        Some(ncomb) if ncomb > COMB_BUDGET => {
            return Err(format!(
                "C({m},{k}) = {ncomb} exceeds combinatorial budget {COMB_BUDGET} \
                 (would OOM in build_comb_tables)"
            ))
        }
        Some(v) => v,
    };
    // MEDIUM 2: subset element budget. Each subset is a Vec<usize> of k_eff elements;
    // the HashMap uses the same-sized keys. M=22, K=11 → 705_432 × 12 ≈ 8.5M usizes
    // = ~136MB (64-bit) or ~34MB (32-bit) — OOM on wasm32.
    // k_eff = min(k, m-k): the mirror formula used in checked_binomial.
    let k_eff = k.min(m - k);
    match ncomb.checked_mul(k_eff as u64 + 1) {
        None => {
            return Err(format!(
                "C({m},{k}) × (k_eff+1) overflows — subset element count too large"
            ))
        }
        Some(ec) if ec > SUBSET_ELEMENT_BUDGET => {
            return Err(format!(
                "C({m},{k})={ncomb} × (k_eff+1)={} = {ec} elements exceeds \
                 SUBSET_ELEMENT_BUDGET={SUBSET_ELEMENT_BUDGET} (would OOM in build_comb_tables)",
                k_eff + 1
            ))
        }
        Some(_) => {}
    }
    // Replicate build_tone_grid_band's -10..30 search exactly.
    const SAMPLE_RATE: f64 = 48_000.0;
    let bw = f_high - f_low;
    let delta_f_est = bw / (m.max(2) - 1) as f64;
    for d_n in -10i64..30i64 {
        let n_candidate = ((SAMPLE_RATE / delta_f_est).round() as i64) + d_n;
        if n_candidate <= 0 { continue; }
        let n = n_candidate as usize;
        let delta_f = SAMPLE_RATE / n as f64;
        let b0 = (f_low / delta_f).ceil() as i64;
        let b1 = b0 + m as i64 - 1;
        let fa = b0 as f64 * delta_f;
        let fb = b1 as f64 * delta_f;
        if fa >= f_low - 1e-3 && fb <= f_high + 1e-3 {
            // C2: cap the resolved FFT window size N. The alloc cost in
            // tracked_tone_demod is proportional to M * N (two Vec<Vec<f64>>
            // of that shape). An ultra-narrow band (e.g. M=2, f_low=400.0,
            // f_high=400.001) gives N ≈ 48_000_000 → OOM. MAX_FLOOR_N=16384
            // is ≈54× the real max (N=306 for narrowband M=12).
            if n > MAX_FLOOR_N {
                return Err(format!(
                    "floor FFT window N={n} exceeds MAX_FLOOR_N={MAX_FLOOR_N} \
                     (band [{f_low}, {f_high}] Hz too narrow for M={m} tones)"
                ));
            }
            return Ok(());
        }
    }
    Err(format!(
        "no integer-bin tone grid exists for M={m} in [{f_low}, {f_high}] Hz \
         (would panic in build_tone_grid_band)"
    ))
}

fn err(e: String) -> JsValue {
    JsValue::from_str(&e)
}

/// Decode the floor rung from a raw 48 kHz mono capture.
///
/// `samples` — f32 PCM at 48 kHz (resample on the JS side if the recorder ran
/// at another rate). `manifest_json` — the bundled tape manifest (tx_chirp0/1,
/// section frame layout, RS/interleave meta).
///
/// Returns a JS object: `{ bytes: Uint8Array, speed, align, cw_failed, n_cw,
/// lock_quality }`.
#[wasm_bindgen]
pub fn decode_floor(samples: &[f32], manifest_json: &str) -> Result<JsValue, JsValue> {
    // M4: reject oversized JSON before serde allocates unbounded Vec fields.
    v_manifest_json_size(manifest_json).map_err(err)?;
    let m: JsonManifest = serde_json::from_str(manifest_json)
        .map_err(|e| JsValue::from_str(&format!("manifest parse error: {e}")))?;
    // M4 post-parse: bound Vec lengths that serde already allocated.
    if m.section.frame_starts.len() > MAX_N_FRAMES {
        return Err(err(format!(
            "frame_starts.len()={} exceeds cap {MAX_N_FRAMES}", m.section.frame_starts.len()
        )));
    }

    v_samples(samples).map_err(err)?;
    v_chirps(m.tx_chirp0, m.tx_chirp1).map_err(err)?;
    v_framing(m.meta.rs_n, m.meta.rs_k, m.meta.n_codewords, m.meta.frame_bits, m.meta.n_frames,
        m.meta.stream_bits, m.meta.payload_len, &m.section.frame_starts, m.section.body_end).map_err(err)?;
    if !(1 <= m.meta.k && m.meta.k < m.meta.m) {
        return Err(err(format!("floor needs 1 <= K < M, got K={} M={}", m.meta.k, m.meta.m)));
    }
    if !(m.section.f_low.is_finite() && m.section.f_high.is_finite() && m.section.f_low > 0.0
        && m.section.f_high > m.section.f_low) {
        return Err(err(format!("invalid band f_low={} f_high={}", m.section.f_low, m.section.f_high)));
    }
    // Validate that an integer-bin tone grid actually exists for (M, K, f_low, f_high)
    // before creating the FloorManifest — ComboScheme::new_band calls
    // build_tone_grid_band which panics (traps the WASM page) if no grid is found.
    v_floor_tone_grid(m.meta.m, m.meta.k, m.section.f_low, m.section.f_high).map_err(err)?;
    // MEDIUM 3: guard_samples used in (align + st - section.guard).max(0) at
    // decoder.rs. A negative or huge guard corrupts the frame boundary.
    v_guard_samples(m.section.guard_samples).map_err(err)?;

    let manifest = FloorManifest {
        tx_chirp0: m.tx_chirp0,
        tx_chirp1: m.tx_chirp1,
        section: FloorSection {
            m: m.meta.m,
            k: m.meta.k,
            f_low: m.section.f_low,
            f_high: m.section.f_high,
            frame_starts: m.section.frame_starts,
            body_end: m.section.body_end,
            guard: m.section.guard_samples,
        },
        meta: ComboMeta {
            rs_n: m.meta.rs_n,
            rs_k: m.meta.rs_k,
            n_codewords: m.meta.n_codewords,
            frame_bits: m.meta.frame_bits,
            n_frames: m.meta.n_frames,
            stream_bits: m.meta.stream_bits,
            payload_len: m.meta.payload_len,
        },
    };

    let raw: Vec<f64> = samples.iter().map(|&x| x as f64).collect();
    let res = decode_floor_from_capture(&raw, &manifest);

    let out = js_sys::Object::new();
    let bytes = js_sys::Uint8Array::from(&res.payload.bytes[..]);
    set(&out, "bytes", &bytes.into())?;
    set(&out, "speed", &JsValue::from_f64(res.speed))?;
    set(&out, "align", &JsValue::from_f64(res.align as f64))?;
    set(&out, "cw_failed", &JsValue::from_f64(res.payload.codewords_failed as f64))?;
    set(&out, "n_cw", &JsValue::from_f64(manifest.meta.n_codewords as f64))?;
    set(&out, "lock_quality", &JsValue::from_f64(res.lock_quality))?;
    Ok(out.into())
}

fn set(obj: &js_sys::Object, key: &str, val: &JsValue) -> Result<(), JsValue> {
    js_sys::Reflect::set(obj, &JsValue::from_str(key), val).map(|_| ())
}

/// Diagnostic: expose global-sync internals + per-frame demod bit counts.
///
/// Gated to debug builds only — it bypasses the validators that `decode_floor`
/// uses, so invalid `M`/`K`/chirp values can still panic via `ComboScheme::new`
/// etc. Rather than duplicate the full validation pipeline here, we simply
/// exclude it from the production WASM surface where untrusted input arrives.
/// Enable by building with `--cfg debug_assertions` (the default in debug mode).
#[cfg(debug_assertions)]
#[wasm_bindgen]
pub fn debug_floor(samples: &[f32], manifest_json: &str) -> Result<JsValue, JsValue> {
    use cassette_codec::combo::ComboScheme;
    use cassette_codec::global_sync::global_sync_and_resample;
    use cassette_codec::sync::tracked_tone_demod;

    let m: JsonManifest = serde_json::from_str(manifest_json)
        .map_err(|e| JsValue::from_str(&format!("{e}")))?;
    let raw: Vec<f64> = samples.iter().map(|&x| x as f64).collect();
    let sync = global_sync_and_resample(&raw, m.tx_chirp0, m.tx_chirp1);
    let align = sync.chirp0_nominal - m.tx_chirp0;
    let sch = ComboScheme::new(m.meta.m, m.meta.k);
    let n_total = sync.audio_nominal.len() as i64;
    let starts = &m.section.frame_starts;
    let guard = m.section.guard_samples;
    let mut counts: Vec<usize> = Vec::new();
    for (i, &st) in starts.iter().enumerate() {
        let a = (align + st - guard).max(0);
        let nxt = if i + 1 < starts.len() { starts[i + 1] } else { m.section.body_end };
        let b = n_total.min((a + 1).max(align + nxt));
        if b <= a { counts.push(0); continue; }
        let seg = &sync.audio_nominal[a as usize..b as usize];
        let syms = tracked_tone_demod(seg, &sch.freqs, sch.n, sch.bits_per_sym, 1 << 20,
            sch.preamble_seconds, 40, 3, true, 0.03, 0.0);
        counts.push(syms.len());
    }
    let out = js_sys::Object::new();
    set(&out, "align", &JsValue::from_f64(align as f64))?;
    set(&out, "speed", &JsValue::from_f64(sync.speed))?;
    set(&out, "chirp0_nominal", &JsValue::from_f64(sync.chirp0_nominal as f64))?;
    set(&out, "chirp0_meas", &JsValue::from_f64(sync.chirp0_meas as f64))?;
    set(&out, "chirp1_meas", &JsValue::from_f64(sync.chirp1_meas as f64))?;
    set(&out, "measured_spacing", &JsValue::from_f64(sync.measured_spacing as f64))?;
    set(&out, "nominal_len", &JsValue::from_f64(n_total as f64))?;
    set(&out, "resample", &JsValue::from_str(&format!("{}/{}", sync.resample_num, sync.resample_den)))?;
    set(&out, "frame_symbol_counts", &JsValue::from_str(&format!("{:?}", counts)))?;
    Ok(out.into())
}

// ---------------------------------------------------------------------------
// R0 coherent-DQPSK rung (survives acoustic capture where the floor rung dies)
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct JsonR0Meta {
    rs_n: usize,
    rs_k: usize,
    n_codewords: usize,
    frame_bits: usize,
    n_frames: usize,
    stream_bits: usize,
    payload_len: usize,
}

#[derive(Deserialize)]
struct JsonR0SectionBlk {
    frame_starts: Vec<i64>,
    body_end: i64,
    p: usize,
    n: usize,
    spacing: usize,
    skip: Option<usize>,
    pilot_hz: f64,
}

#[derive(Deserialize)]
struct JsonR0Manifest {
    tx_chirp0: i64,
    tx_chirp1: i64,
    section: JsonR0SectionBlk,
    meta: JsonR0Meta,
    #[serde(default)]
    crc32_codewords: Vec<u32>,
}

/// Decode the R0 robust-DQPSK rung from a raw 48 kHz mono capture.
/// Uses the full rescue ensemble (CRC-gated EMA-sweep union + late-window) when
/// the manifest carries per-codeword CRC32s — byte-exact even on acoustic
/// captures; falls back to the single-pass path otherwise. Same return shape as
/// `decode_floor`.
#[wasm_bindgen]
pub fn decode_r0(samples: &[f32], manifest_json: &str) -> Result<JsValue, JsValue> {
    use cassette_codec::dqpsk::{decode_r0_ensemble, decode_r0_section, R0Section};
    use cassette_codec::global_sync::global_sync_and_resample;

    // M4: reject oversized JSON before serde allocates unbounded Vec fields.
    v_manifest_json_size(manifest_json).map_err(err)?;
    let m: JsonR0Manifest = serde_json::from_str(manifest_json)
        .map_err(|e| JsValue::from_str(&format!("manifest parse error: {e}")))?;
    // M4 post-parse: bound Vec lengths.
    if m.section.frame_starts.len() > MAX_N_FRAMES {
        return Err(err(format!(
            "frame_starts.len()={} exceeds cap {MAX_N_FRAMES}", m.section.frame_starts.len()
        )));
    }
    if m.crc32_codewords.len() > MAX_N_CW + 1 {
        return Err(err(format!(
            "crc32_codewords.len()={} exceeds cap", m.crc32_codewords.len()
        )));
    }

    v_samples(samples).map_err(err)?;
    v_chirps(m.tx_chirp0, m.tx_chirp1).map_err(err)?;
    v_framing(m.meta.rs_n, m.meta.rs_k, m.meta.n_codewords, m.meta.frame_bits, m.meta.n_frames,
        m.meta.stream_bits, m.meta.payload_len, &m.section.frame_starts, m.section.body_end).map_err(err)?;
    v_dqpsk(m.section.p, m.section.n, m.section.spacing, m.section.skip).map_err(err)?;
    if !m.crc32_codewords.is_empty() && m.crc32_codewords.len() != m.meta.n_codewords {
        return Err(err(format!("crc32_codewords len {} != n_codewords {}",
            m.crc32_codewords.len(), m.meta.n_codewords)));
    }

    let raw: Vec<f64> = samples.iter().map(|&x| x as f64).collect();
    let sync = global_sync_and_resample(&raw, m.tx_chirp0, m.tx_chirp1);
    let align = sync.chirp0_nominal - m.tx_chirp0;

    let section = R0Section {
        p: m.section.p,
        n: m.section.n,
        spacing: m.section.spacing,
        skip: m.section.skip,
        pilot_hz: m.section.pilot_hz,
        frame_starts: m.section.frame_starts,
        body_end: m.section.body_end,
    };
    let meta = ComboMeta {
        rs_n: m.meta.rs_n,
        rs_k: m.meta.rs_k,
        n_codewords: m.meta.n_codewords,
        frame_bits: m.meta.frame_bits,
        n_frames: m.meta.n_frames,
        stream_bits: m.meta.stream_bits,
        payload_len: m.meta.payload_len,
    };
    let dec = if m.crc32_codewords.len() == m.meta.n_codewords {
        decode_r0_ensemble(&sync.audio_nominal, &section, align, &meta, &m.crc32_codewords)
    } else {
        decode_r0_section(&sync.audio_nominal, &section, align, &meta)
    };

    let out = js_sys::Object::new();
    let bytes = js_sys::Uint8Array::from(&dec.bytes[..]);
    set(&out, "bytes", &bytes.into())?;
    set(&out, "speed", &JsValue::from_f64(sync.speed))?;
    set(&out, "align", &JsValue::from_f64(align as f64))?;
    set(&out, "cw_failed", &JsValue::from_f64(dec.codewords_failed as f64))?;
    set(&out, "n_cw", &JsValue::from_f64(meta.n_codewords as f64))?;
    set(&out, "lock_quality", &JsValue::from_f64(sync.lock_quality))?;
    Ok(out.into())
}

// ---------------------------------------------------------------------------
// R2 / R3 — D2X (dense2x-drop) rung, mono or one stereo channel
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct JsonD2XSectionBlk {
    frame_starts: Vec<i64>,
    body_end: i64,
    p: usize,
    n: usize,
    spacing: usize,
    pilot_hz: f64,
    drop_freqs_hz: Vec<f64>,
}

#[derive(Deserialize)]
struct JsonD2XManifest {
    tx_chirp0: i64,
    tx_chirp1: i64,
    section: JsonD2XSectionBlk,
    meta: JsonR0Meta,
    crc32_codewords: Vec<u32>,
}

/// Decode a D2X rung (R2 mono, or one channel of the R3 stereo pair) from a raw
/// 48 kHz mono capture. For R3, call once per channel with that channel's CRCs.
/// Same return shape as `decode_floor`/`decode_r0`.
#[wasm_bindgen]
pub fn decode_d2x(samples: &[f32], manifest_json: &str) -> Result<JsValue, JsValue> {
    use cassette_codec::dqpsk::{decode_d2x_ensemble, D2XSection};
    use cassette_codec::global_sync::global_sync_and_resample;

    // M4: reject oversized JSON before serde allocates unbounded Vec fields.
    v_manifest_json_size(manifest_json).map_err(err)?;
    let m: JsonD2XManifest = serde_json::from_str(manifest_json)
        .map_err(|e| JsValue::from_str(&format!("manifest parse error: {e}")))?;
    // M4 post-parse: bound Vec lengths that serde already allocated.
    if m.section.frame_starts.len() > MAX_N_FRAMES {
        return Err(err(format!(
            "frame_starts.len()={} exceeds cap {MAX_N_FRAMES}", m.section.frame_starts.len()
        )));
    }
    if m.section.drop_freqs_hz.len() > MAX_D2X_DROPS {
        return Err(err(format!(
            "drop_freqs_hz.len()={} exceeds cap {MAX_D2X_DROPS}", m.section.drop_freqs_hz.len()
        )));
    }
    if m.crc32_codewords.len() > MAX_N_CW + 1 {
        return Err(err(format!(
            "crc32_codewords.len()={} exceeds cap", m.crc32_codewords.len()
        )));
    }

    v_samples(samples).map_err(err)?;
    v_chirps(m.tx_chirp0, m.tx_chirp1).map_err(err)?;
    v_framing(m.meta.rs_n, m.meta.rs_k, m.meta.n_codewords, m.meta.frame_bits, m.meta.n_frames,
        m.meta.stream_bits, m.meta.payload_len, &m.section.frame_starts, m.section.body_end).map_err(err)?;
    v_dqpsk(m.section.p, m.section.n, m.section.spacing, None).map_err(err)?;
    // D2X-specific: validate drop_freqs_hz / pilot_hz against new_dropnull's
    // keep-count invariant. Without this, a mismatched drop list silently passes
    // v_dqpsk and then panics (traps) at assert_eq!(keep.len(), p) inside
    // DqpskScheme::new_dropnull — reachable from both decode_d2x_ensemble plan
    // entries (primary hann256_skip0 and rect128_skip64 alternative frontend).
    v_d2x(m.section.p, m.section.n, m.section.spacing,
          &m.section.drop_freqs_hz, m.section.pilot_hz).map_err(err)?;
    if m.crc32_codewords.len() != m.meta.n_codewords {
        return Err(err(format!("crc32_codewords len {} != n_codewords {}",
            m.crc32_codewords.len(), m.meta.n_codewords)));
    }

    let raw: Vec<f64> = samples.iter().map(|&x| x as f64).collect();
    let sync = global_sync_and_resample(&raw, m.tx_chirp0, m.tx_chirp1);
    let align = sync.chirp0_nominal - m.tx_chirp0;

    let section = D2XSection {
        p: m.section.p,
        n: m.section.n,
        spacing: m.section.spacing,
        drop_freqs_hz: m.section.drop_freqs_hz,
        pilot_hz: m.section.pilot_hz,
        frame_starts: m.section.frame_starts,
        body_end: m.section.body_end,
    };
    let meta = ComboMeta {
        rs_n: m.meta.rs_n,
        rs_k: m.meta.rs_k,
        n_codewords: m.meta.n_codewords,
        frame_bits: m.meta.frame_bits,
        n_frames: m.meta.n_frames,
        stream_bits: m.meta.stream_bits,
        payload_len: m.meta.payload_len,
    };
    let dec = decode_d2x_ensemble(&sync.audio_nominal, &section, align, &meta, &m.crc32_codewords);

    let out = js_sys::Object::new();
    let bytes = js_sys::Uint8Array::from(&dec.bytes[..]);
    set(&out, "bytes", &bytes.into())?;
    set(&out, "speed", &JsValue::from_f64(sync.speed))?;
    set(&out, "align", &JsValue::from_f64(align as f64))?;
    set(&out, "cw_failed", &JsValue::from_f64(dec.codewords_failed as f64))?;
    set(&out, "n_cw", &JsValue::from_f64(meta.n_codewords as f64))?;
    set(&out, "lock_quality", &JsValue::from_f64(sync.lock_quality))?;
    Ok(out.into())
}

// ---------------------------------------------------------------------------
// Native unit tests for the manifest validators (run under
// `cargo test -p cassette-codec-wasm` — the crate is also an rlib). These pin
// the panic-prevention contract: a malformed manifest must be rejected by a
// validator BEFORE it reaches core code that would trap.
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // R0 framing (from the shipped manifest): rs_n=255 rs_k=127 n_cw=31
    // frame_bits=16000 n_frames=4 stream_bits=63240 payload_len=3937.
    fn good_framing() -> Result<(), String> {
        v_framing(255, 127, 31, 16000, 4, 63240, 3937,
            &[2023194, 2246010, 2468826, 2691642], 2904730)
    }

    #[test]
    fn samples_validation() {
        assert!(v_samples(&[0.1, 0.2, 0.3]).is_ok());
        assert!(v_samples(&[]).is_err());
        assert!(v_samples(&[0.1, f32::NAN]).is_err());
        assert!(v_samples(&[0.1, f32::INFINITY]).is_err());
    }

    #[test]
    fn chirp_validation() {
        assert!(v_chirps(48000, 4501370).is_ok());
        assert!(v_chirps(48000, 48000).is_err());   // zero spacing
        assert!(v_chirps(48000, 100).is_err());     // negative spacing
    }

    #[test]
    fn framing_validation_accepts_real_manifest() {
        assert!(good_framing().is_ok());
    }

    #[test]
    fn framing_validation_rejects_malformed() {
        // rs_k >= rs_n
        assert!(v_framing(255, 255, 31, 16000, 4, 63240, 3937, &[0,1,2,3], 99).is_err());
        // rs_n > 255
        assert!(v_framing(256, 127, 31, 16000, 4, 63240, 3937, &[0,1,2,3], 99).is_err());
        // frame_starts.len() != n_frames
        assert!(v_framing(255, 127, 31, 16000, 4, 63240, 3937, &[0,1,2], 99).is_err());
        // stream_bits inconsistent with rs_n*n_cw*8
        assert!(v_framing(255, 127, 31, 16000, 4, 999, 3937, &[0,1,2,3], 99).is_err());
        // payload_len too large
        assert!(v_framing(255, 127, 31, 16000, 4, 63240, 9_999_999, &[0,1,2,3], 99).is_err());
        // non-monotonic frame_starts
        assert!(v_framing(255, 127, 31, 16000, 4, 63240, 3937, &[0,5,3,9], 99).is_err());
        // body_end before last frame_start
        assert!(v_framing(255, 127, 31, 16000, 4, 63240, 3937, &[0,1,2,100], 50).is_err());
        // zero counts
        assert!(v_framing(255, 127, 0, 16000, 4, 0, 3937, &[0,1,2,3], 99).is_err());
    }

    #[test]
    fn dqpsk_geometry_validation() {
        assert!(v_dqpsk(10, 256, 4, None).is_ok());      // R0/R1
        assert!(v_dqpsk(18, 256, 2, Some(64)).is_ok());  // R2
        assert!(v_dqpsk(21, 256, 2, Some(64)).is_ok());  // R3
        assert!(v_dqpsk(0, 256, 4, None).is_err());      // p=0
        assert!(v_dqpsk(10, 255, 4, None).is_err());     // N not power of two
        assert!(v_dqpsk(10, 256, 4, Some(128)).is_err()); // 2*skip >= N
        assert!(v_dqpsk(200, 256, 8, None).is_err());    // comb past Nyquist
    }

    // ── WASM-boundary JSON-parse path (native harness, case 6) ───────────────
    // Tests that the full JSON-string → serde-deserialize → validator chain the
    // `decode_floor` / `decode_r0` / `decode_d2x` bindings use accepts valid
    // manifests and rejects malformed/adversarial ones. A true wasm-bindgen test
    // needs `wasm-pack` + `wasm32-unknown-unknown` + node, which are not
    // available in this environment; this native test covers the same logic.

    /// Round-trip: parse a well-formed floor manifest JSON and validate it.
    #[test]
    fn floor_manifest_json_roundtrip_validation() {
        // A compact but complete floor manifest (values from the shipped tape).
        let json = r#"{
            "tx_chirp0": 48000,
            "tx_chirp1": 2268057,
            "section": {
                "frame_starts": [224982, 625982, 1026982, 1427982],
                "body_end": 2268057,
                "guard_samples": 2400
            },
            "meta": {
                "M": 16, "K": 2,
                "rs_n": 255, "rs_k": 95,
                "n_codewords": 16,
                "frame_bits": 7600,
                "n_frames": 4,
                "stream_bits": 32640,
                "payload_len": 1520
            }
        }"#;
        let m: JsonManifest = serde_json::from_str(json)
            .expect("valid floor manifest must parse");
        assert!(v_chirps(m.tx_chirp0, m.tx_chirp1).is_ok());
        assert!(v_framing(
            m.meta.rs_n, m.meta.rs_k, m.meta.n_codewords,
            m.meta.frame_bits, m.meta.n_frames, m.meta.stream_bits,
            m.meta.payload_len, &m.section.frame_starts, m.section.body_end,
        ).is_ok());
        // stream_bits consistency: rs_n * n_cw * 8 = 255 * 16 * 8 = 32640.
        assert_eq!(m.meta.stream_bits, 255 * 16 * 8);
        // K/M floor-specific checks (mirrors the wasm decode_floor binding).
        assert!(m.meta.k >= 1 && m.meta.k < m.meta.m,
            "floor needs 1 <= K < M");
        // Band edges default when absent.
        assert!((m.section.f_low - DEFAULT_F_LOW).abs() < 1e-6);
        assert!((m.section.f_high - DEFAULT_F_HIGH).abs() < 1e-6);
    }

    /// Malformed JSON (bad types, truncated, extra fields) must return a parse
    /// error, not a panic.
    #[test]
    fn malformed_floor_manifest_json_rejected() {
        // Wrong type for tx_chirp0.
        let bad_type = r#"{"tx_chirp0": "not_a_number", "tx_chirp1": 99,
            "section": {"frame_starts":[], "body_end":0, "guard_samples":0},
            "meta": {"M":16,"K":2,"rs_n":255,"rs_k":95,"n_codewords":1,
                     "frame_bits":8,"n_frames":1,"stream_bits":2040,"payload_len":1}}"#;
        assert!(serde_json::from_str::<JsonManifest>(bad_type).is_err(),
            "wrong type must be a parse error");

        // Truncated JSON.
        assert!(serde_json::from_str::<JsonManifest>(r#"{"tx_chirp0": 48000"#).is_err());

        // Missing required field.
        assert!(serde_json::from_str::<JsonManifest>(r#"{"tx_chirp1": 99}"#).is_err());
    }

    /// Semantically invalid manifests (valid JSON, wrong values) must be
    /// rejected by the validators before reaching core decode code.
    #[test]
    fn invalid_manifest_values_rejected_by_validators() {
        // tx_chirp1 <= tx_chirp0 → chirp validator.
        assert!(v_chirps(100_000, 100_000).is_err(), "zero chirp spacing");
        assert!(v_chirps(100_000, 1_000).is_err(), "negative chirp spacing");

        // rs_n > 255 → framing validator.
        assert!(v_framing(256, 95, 4, 8160, 1, 8160, 380, &[0], 99).is_err());

        // stream_bits inconsistent → framing validator.
        let n_cw = 4usize;
        let rs_n = 255usize;
        let correct_stream_bits = rs_n * n_cw * 8;
        assert!(v_framing(rs_n, 95, n_cw, correct_stream_bits, 1,
                          correct_stream_bits + 1, 380, &[0], 99).is_err(),
                "off-by-one stream_bits must be rejected");

        // payload_len > rs_k * n_cw → framing validator.
        assert!(v_framing(255, 95, 4, 255*4*8, 1, 255*4*8, 99_999, &[0], 9999).is_err());

        // Negative frame_start → framing validator.
        assert!(v_framing(255, 95, 2, 255*2*8, 2, 255*2*8, 190, &[0, -1], 99).is_err());

        // Non-monotonic frame_starts → framing validator.
        assert!(v_framing(255, 95, 3, 255*3*8/3, 3, 255*3*8, 285, &[10, 5, 15], 99).is_err());
    }

    /// ① BUG-FIXED (codex review): `decode_d2x` validated generic DQPSK geometry
    /// but not D2X-specific `drop_freqs_hz`/`pilot_hz`, so a manifested with
    /// duplicate drops, drops outside the comb, or a drop matching the pilot
    /// would pass `v_dqpsk` then panic at `assert_eq!(keep.len(), p)` inside
    /// `DqpskScheme::new_dropnull`. `v_d2x` now gates these cases.
    #[test]
    fn d2x_drop_list_validated_before_decode() {
        // Valid R2 geometry: p=18, n=256, spacing=2, drops=[750,4500,5625,6750], pilot=4875.
        assert!(v_d2x(18, 256, 2, &[750.0, 4500.0, 5625.0, 6750.0], 4875.0).is_ok(),
            "valid R2 drop/pilot must be accepted");
        // Valid R3 geometry: p=21, n=256, spacing=2, drops=[750], pilot=4875.
        assert!(v_d2x(21, 256, 2, &[750.0], 4875.0).is_ok(),
            "valid R3 drop/pilot must be accepted");
        // Duplicate drop freq → keep.len() would be > p → panic without validator.
        assert!(v_d2x(18, 256, 2, &[750.0, 750.0, 4500.0, 5625.0, 6750.0], 4875.0).is_err(),
            "duplicate drop freq must be rejected");
        // Drop freq matching pilot → wastes a drop slot → keep.len() > p.
        assert!(v_d2x(18, 256, 2, &[4875.0, 4500.0, 5625.0, 6750.0], 4875.0).is_err(),
            "drop freq matching pilot must be rejected");
        // Drop freq not in comb (e.g., 1234 Hz when spacing=2 gives only even-multiple bins).
        assert!(v_d2x(18, 256, 2, &[1234.0, 4500.0, 5625.0, 6750.0], 4875.0).is_err(),
            "drop freq outside the comb must be rejected");
        // Non-finite pilot_hz.
        assert!(v_d2x(18, 256, 2, &[750.0, 4500.0, 5625.0, 6750.0], f64::NAN).is_err(),
            "NaN pilot_hz must be rejected");
        // Non-finite drop freq.
        assert!(v_d2x(18, 256, 2, &[f64::INFINITY, 4500.0, 5625.0, 6750.0], 4875.0).is_err(),
            "non-finite drop freq must be rejected");
        // N <= 128 → rect128 frontend would underflow (nw = N - 2*64 = 0 or negative).
        assert!(v_d2x(18, 128, 2, &[750.0, 4500.0, 5625.0, 6750.0], 4875.0).is_err(),
            "N=128 must be rejected (rect128 frontend needs N > 128)");
    }

    /// ④ FIXED (codex review): Replace the vacuous D2X test (which never
    /// deserialized `JsonD2XManifest`) with a real JSON round-trip that parses
    /// the full struct — including `drop_freqs_hz` and `crc32_codewords` —
    /// through serde, then validates the result through `v_d2x` + `v_framing`.
    #[test]
    fn d2x_manifest_json_full_roundtrip() {
        // R2 manifest: p=18, n=256, spacing=2, drops=[750,4500,5625,6750], pilot=4875.
        // Framing: rs_n=255, rs_k=127, n_cw=31, n_frames=3.
        // stream_bits = 255 * 31 * 8 = 63240. frame_bits = 63240 / 3 = 21080.
        // 31 crc32 entries (zeros here — realistic manifests carry real CRCs).
        let json = r#"{
            "tx_chirp0": 48000,
            "tx_chirp1": 2268057,
            "section": {
                "frame_starts": [300000, 1000000, 1700000],
                "body_end": 2268057,
                "p": 18,
                "n": 256,
                "spacing": 2,
                "pilot_hz": 4875.0,
                "drop_freqs_hz": [750.0, 4500.0, 5625.0, 6750.0]
            },
            "meta": {
                "rs_n": 255, "rs_k": 127,
                "n_codewords": 31,
                "frame_bits": 21080,
                "n_frames": 3,
                "stream_bits": 63240,
                "payload_len": 3937
            },
            "crc32_codewords": [
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,0
            ]
        }"#;
        let m: JsonD2XManifest = serde_json::from_str(json)
            .expect("valid D2X manifest JSON must parse");
        // serde correctly decoded all D2X-specific fields.
        assert_eq!(m.section.p, 18);
        assert_eq!(m.section.drop_freqs_hz, vec![750.0, 4500.0, 5625.0, 6750.0]);
        assert!((m.section.pilot_hz - 4875.0).abs() < 1e-6);
        assert_eq!(m.crc32_codewords.len(), 31);
        // Validators must accept this manifest.
        assert!(v_chirps(m.tx_chirp0, m.tx_chirp1).is_ok());
        assert!(v_framing(
            m.meta.rs_n, m.meta.rs_k, m.meta.n_codewords,
            m.meta.frame_bits, m.meta.n_frames, m.meta.stream_bits,
            m.meta.payload_len, &m.section.frame_starts, m.section.body_end,
        ).is_ok());
        assert!(v_dqpsk(m.section.p, m.section.n, m.section.spacing, None).is_ok());
        assert!(v_d2x(
            m.section.p, m.section.n, m.section.spacing,
            &m.section.drop_freqs_hz, m.section.pilot_hz,
        ).is_ok());
        // CRC table length must match n_codewords.
        assert_eq!(m.crc32_codewords.len(), m.meta.n_codewords);

        // Negative tests: malformed D2X JSON fields.
        // Wrong type for drop_freqs_hz entry → serde error.
        let bad_drop = r#"{
            "tx_chirp0": 48000, "tx_chirp1": 2268057,
            "section": {"frame_starts":[0],"body_end":1,"p":18,"n":256,"spacing":2,
                        "pilot_hz":4875.0,"drop_freqs_hz":["not_a_number"]},
            "meta":{"rs_n":255,"rs_k":127,"n_codewords":1,"frame_bits":2040,
                    "n_frames":1,"stream_bits":2040,"payload_len":127},
            "crc32_codewords":[0]
        }"#;
        assert!(serde_json::from_str::<JsonD2XManifest>(bad_drop).is_err(),
            "non-numeric drop_freqs_hz must be a serde parse error");

        // CRC table too short → validate separately (serde accepts it).
        let short_crc_json = r#"{
            "tx_chirp0": 48000, "tx_chirp1": 2268057,
            "section": {"frame_starts":[0,1,2],"body_end":3,"p":18,"n":256,"spacing":2,
                        "pilot_hz":4875.0,"drop_freqs_hz":[750.0,4500.0,5625.0,6750.0]},
            "meta":{"rs_n":255,"rs_k":127,"n_codewords":31,"frame_bits":21080,
                    "n_frames":3,"stream_bits":63240,"payload_len":3937},
            "crc32_codewords":[0,1,2]
        }"#;
        let m2: JsonD2XManifest = serde_json::from_str(short_crc_json).unwrap();
        assert_ne!(m2.crc32_codewords.len(), m2.meta.n_codewords,
            "short CRC table is caught at the length check in decode_d2x");
        // The decode_d2x binding checks: if crc32_codewords.len() != n_codewords → Err.
        assert!(m2.crc32_codewords.len() != m2.meta.n_codewords);
    }

    // ── Fix A + B: checked arithmetic + dimension caps ────────────────────────
    //
    // On wasm32, usize is 32-bit (max ~4 billion). Even values well under the
    // natural "safe" ceiling for individual dimensions can produce overflowing
    // PRODUCTS in the validator arithmetic:
    //   rs_n * n_codewords * 8 — on wasm32, n_cw ~ 17 million wraps the u32.
    //   frame_bits * (n_frames-1) — n_frames ~ 4000 at frame_bits=1M wraps.
    // Fixes:
    //   A — all product/sum arithmetic on untrusted fields uses checked_mul/add (u64).
    //   B — explicit per-dimension caps are checked BEFORE any arithmetic.
    //
    // Tests: dimension just over cap → Err; real manifest dimensions → Ok;
    // values that would overflow u32 (wasm32 usize) → Err (cap or arithmetic).

    /// Fix B: each manifest dimension has a per-cap reject (Err) at one over the cap.
    #[test]
    fn dimension_caps_reject_oversized_values() {
        // n_codewords > 32768 (MAX_N_CW):
        assert!(
            v_framing(255, 127, 32769, 255, 1, 255 * 32769 * 8, 100, &[0], 99).is_err(),
            "n_codewords > MAX_N_CW must be rejected"
        );
        // frame_bits > 500_000 (MAX_FRAME_BITS):
        assert!(
            v_framing(255, 127, 1, 500_001, 1, 255 * 1 * 8, 100, &[0], 99).is_err(),
            "frame_bits > MAX_FRAME_BITS must be rejected"
        );
        // n_frames > 8192 (MAX_N_FRAMES):
        assert!(
            v_framing(255, 127, 1, 255 * 8, 8193, 255 * 1 * 8, 100,
                      &vec![0i64; 8193], 999).is_err(),
            "n_frames > MAX_N_FRAMES must be rejected"
        );
        // stream_bits just over MAX_STREAM_BITS (n_cw=1 keeps all other caps in range
        // so the stream_bits cap is the operative guard, not the n_cw cap):
        assert!(
            v_framing(255, 127, 1, 255*8, 1, 100_000_001, 100, &[0], 99).is_err(),
            "stream_bits just over MAX_STREAM_BITS must be rejected (stream_bits cap fires)"
        );
        // payload_len > 10_000_000:
        assert!(
            v_framing(255, 127, 16, 255 * 8, 1, 255 * 16 * 8, 10_000_001, &[0], 99).is_err(),
            "payload_len > 10_000_000 must be rejected"
        );
        // p > 512:
        assert!(v_dqpsk(513, 256, 2, None).is_err(), "DQPSK p > 512 must be rejected");
        // n > 65536:
        assert!(v_dqpsk(10, 131072, 2, None).is_err(), "DQPSK n > 65536 must be rejected");
        // spacing > 64:
        assert!(v_dqpsk(10, 256, 65, None).is_err(), "DQPSK spacing > 64 must be rejected");
        // floor M > 128:
        assert!(
            v_floor_tone_grid(129, 2, 400.0, 10_000.0).is_err(),
            "floor M > 128 must be rejected"
        );
    }

    /// HIGH 5: the checked_mul helpers that protect wasm32 (32-bit usize wrap) are
    /// tested HERE directly at u64 overflow boundaries. These tests are meaningful
    /// on both 64-bit (where they prove the helpers return None correctly) AND on
    /// wasm32 (where bare usize multiply would silently wrap, causing security bugs).
    /// "Red without fix" = swapping a checked_mul back to bare `*` makes the
    /// assertion fail on 64-bit too, because the expression evaluates to Some(0)
    /// or Some(overflowed) instead of None.
    #[test]
    fn arithmetic_overflow_caught_by_checked_mul() {
        // 1. rs_n * n_cw * 8 at u64 overflow: v_framing uses (rs_n as u64).checked_mul(n_cw as u64)...
        let overflow_ncw: u64 = u64::MAX / (255 * 8) + 1; // 255 * this > u64::MAX
        assert!(
            (255u64).checked_mul(overflow_ncw).and_then(|x| x.checked_mul(8)).is_none(),
            "rs_n*n_cw*8 checked_mul chain must return None at u64 overflow boundary"
        );
        // 2. frame_bits * (n_frames-1) at u64 overflow: v_framing uses (fb as u64).checked_mul(nf-1).
        let overflow_fb: u64 = u64::MAX / 2 + 1;
        assert!(
            overflow_fb.checked_mul(2).is_none(),
            "frame_bits*(n_frames-1) checked_mul must return None at u64/2+1"
        );
        // 3. spacing * (p+8) at u64 overflow: v_dqpsk uses (spacing as u64).checked_mul(p+8).
        let overflow_sp: u64 = u64::MAX / 18 + 1; // p=10, p+8=18
        assert!(
            overflow_sp.checked_mul(18).is_none(),
            "spacing*(p+8) checked_mul must return None at u64 overflow boundary"
        );
        // 4. DQPSK basis (p+1)*nw at u64 overflow (CRITICAL 1): v_dqpsk uses (p+1).checked_mul(nw).
        let overflow_p1: u64 = u64::MAX / 65536 + 1;
        assert!(
            overflow_p1.checked_mul(65536).is_none(),
            "(p+1)*nw checked_mul must return None at u64 overflow boundary"
        );
        // 5. checked_binomial at u64 overflow: C(usize::MAX, 2) = usize::MAX*(usize::MAX-1)/2.
        // The first checked_mul step overflows u64 on both 32-bit and 64-bit.
        assert!(
            checked_binomial(usize::MAX, 2).is_none(),
            "checked_binomial(usize::MAX, 2) must return None (u64 overflow in first mul step)"
        );
        // ── Cap-rejection tests (caps fire first on 64-bit; document the boundary) ──
        // n_cw just over MAX_N_CW: cap fires before checked_mul arithmetic.
        assert!(
            v_framing(255, 127, MAX_N_CW + 1, 1, 1, 255 * 8, 100, &[0], 99).is_err(),
            "n_cw one over MAX_N_CW must be rejected (cap guard)"
        );
        // spacing just over MAX_SPACING: cap fires before spacing*(p+8) arithmetic.
        assert!(
            v_dqpsk(10, 256, MAX_SPACING + 1, None).is_err(),
            "spacing one over MAX_SPACING must be rejected (cap guard)"
        );
    }

    /// Fix B: a real manifest (fullspectrum floor rung, fs_rm1_floor_combo_m16k2_rs95)
    /// must validate Ok with all caps in place — caps must not reject real tape data.
    #[test]
    fn real_manifest_dimensions_validate_ok() {
        // rs_n=255, rs_k=95, n_cw=16, frame_bits=6400, n_frames=6,
        // stream_bits=32640, payload_len=1520.
        let starts: Vec<i64> = (0..6).map(|i| i * 200_000).collect();
        assert!(
            v_framing(255, 95, 16, 6400, 6, 32640, 1520, &starts, 1_500_000).is_ok(),
            "real floor manifest must pass v_framing"
        );
        // R0 DQPSK: p=10, n=256, spacing=4.
        assert!(v_dqpsk(10, 256, 4, None).is_ok(), "real R0 must pass v_dqpsk");
        // R2 D2X: p=18, n=256, spacing=2, drops=[750,4500,5625,6750].
        assert!(
            v_d2x(18, 256, 2, &[750.0, 4500.0, 5625.0, 6750.0], 4875.0).is_ok(),
            "real R2 must pass v_d2x"
        );
        // Floor: M=16, K=2.
        assert!(
            v_floor_tone_grid(16, 2, 400.0, 10_000.0).is_ok(),
            "real floor M=16/K=2 must pass v_floor_tone_grid"
        );
        // Narrowband floor (from MNIST rung): M=16, K=2, f_low=470, f_high=2200.
        assert!(
            v_floor_tone_grid(16, 2, 470.0, 2200.0).is_ok(),
            "narrowband M=16 must pass v_floor_tone_grid"
        );
    }

    /// Fix B: C(M,K) combinatorial budget. build_comb_tables allocates C(M,K)
    /// Vec<Vec<usize>> entries — OOM for large M and K. v_floor_tone_grid now
    /// computes checked_binomial(M,K) and rejects > 1_000_000 budget.
    #[test]
    fn floor_comb_budget_cap_rejects_huge_mk() {
        // C(64, 8) = 4_426_165_368 >> 1_000_000 budget → must be rejected.
        assert!(
            v_floor_tone_grid(64, 8, 400.0, 10_000.0).is_err(),
            "C(64,8) exceeds comb budget — must be rejected"
        );
        // C(16,2)=120, C(64,3)=41664 — both under budget → accepted.
        assert!(v_floor_tone_grid(16, 2, 400.0, 10_000.0).is_ok(), "C(16,2) within budget");
        assert!(v_floor_tone_grid(64, 3, 400.0, 10_000.0).is_ok(), "C(64,3)=41664 within budget");
        // C(128,3) = 357760 — under budget, valid M <= 128 cap.
        assert!(v_floor_tone_grid(128, 3, 400.0, 10_000.0).is_ok(), "C(128,3)=357760 within budget");
    }

    /// ② BUG-FIXED: `decode_floor` called `ComboScheme::new_band` which calls
    /// `build_tone_grid_band`, which panics (traps the WASM page) when no
    /// integer-bin grid fits M tones inside [f_low, f_high]. The band check in
    /// `decode_floor` only tested finiteness + f_high > f_low, not whether the
    /// requested grid actually exists. `v_floor_tone_grid` replicates the
    /// `build_tone_grid_band` search loop and returns `Err` if nothing fits.
    #[test]
    fn floor_tone_grid_invalid_band_rejected() {
        // M=32, f_low=400, f_high=500: bandwidth of 100 Hz can't fit 32 tones at
        // integer FFT-bin spacing → would panic in build_tone_grid_band (combo.rs:44).
        assert!(v_floor_tone_grid(32, 2, 400.0, 500.0).is_err(),
            "narrow band for M=32 must be rejected before reaching build_tone_grid_band");
        // Valid full-spectrum floor (M=16, full 400-10000 Hz): must be accepted.
        assert!(v_floor_tone_grid(16, 2, 400.0, 10_000.0).is_ok(),
            "standard M=16 full-spectrum floor must be accepted");
        // Non-finite f_low: must be rejected before the grid search (avoids NaN arith).
        assert!(v_floor_tone_grid(16, 2, f64::NAN, 10_000.0).is_err(),
            "NaN f_low must be rejected");
        // Inverted band (f_low >= f_high): must be rejected.
        assert!(v_floor_tone_grid(16, 2, 5_000.0, 1_000.0).is_err(),
            "inverted band (f_low >= f_high) must be rejected");
    }

    /// ③ BUG-FIXED: `v_framing` checked stream_bits == rs_n*n_cw*8 but NOT the
    /// frame-partition constraint. When (n_frames-1)*frame_bits >= stream_bits,
    /// the last-frame nominal computation `stream_bits - frame_bits*(nf-1)` in
    /// `rx_codeword_matrix` (framing.rs:63) underflows → wraps to a huge usize
    /// → huge Vec allocation → OOM or panic in release mode. `v_framing` now
    /// rejects any manifest where that subtraction would underflow.
    #[test]
    fn framing_partition_overflow_rejected() {
        // RS(7,3), n_cw=2, stream_bits=7*2*8=112, frame_bits=40, n_frames=4.
        // (n_frames-1)*frame_bits = 3*40 = 120 >= stream_bits=112 → underflow.
        assert!(
            v_framing(7, 3, 2, 40, 4, 112, 6, &[0, 40, 80, 120], 200).is_err(),
            "frame partition where (n_frames-1)*frame_bits >= stream_bits must be rejected"
        );
        // HIGH 5: frame_bits just under MAX_FRAME_BITS (499_999 < 500_000) so the
        // PARTITION guard fires, not the frame_bits cap. The partition check uses
        // (fb as u64).checked_mul((nf-1) as u64) — verified meaningful at u64 boundary
        // in arithmetic_overflow_caught_by_checked_mul above.
        // rs_n=255, n_cw=1, sb=2040; frame_bits=499_999, n_frames=3 →
        // (n_frames-1)*frame_bits = 2×499_999=999_998 >> stream_bits=2040.
        assert!(
            v_framing(255, 127, 1, 499_999, 3, 2040, 100,
                      &[0, 499_999, 999_998], 1_499_999).is_err(),
            "frame partition underflow (partition guard, not frame_bits cap) must be rejected"
        );
    }

    // ── Codex round 4 (C1/C2/M3/M4/M5/L6 + caps regression) ─────────────────

    /// C1: `v_dqpsk` `2*skip` overflow on wasm32 — skip capped and check uses u64.
    ///
    /// On wasm32 (usize=u32): `2 * (u32::MAX/2 + 1) = 2 * 2147483648` wraps to 0,
    /// so `0 >= n=256` is False → wrong Ok result. The fix uses `(sk as u64) * 2`
    /// and adds an explicit skip cap so large values are caught on all targets.
    /// On native 64-bit this test still validates the corrected guard path.
    #[test]
    fn v_dqpsk_skip_overflow_caught() {
        // HIGH 5: test the (sk as u64).checked_mul(2) helper directly at u64 boundary.
        // This is what protects wasm32 — on wasm32, 2*(u32::MAX/2+1) wraps to 0,
        // so the bare `2*sk >= n` check passes incorrectly. The u64 helper returns None.
        let overflow_sk: u64 = u64::MAX / 2 + 1;
        assert!(
            overflow_sk.checked_mul(2).is_none(),
            "2*skip u64 checked_mul must return None at u64/2+1 overflow boundary"
        );
        // skip = u32::MAX/2 + 1: on wasm32 2*skip wraps to 0, bypasses the check.
        // v_dqpsk uses (sk as u64).checked_mul(2), so it correctly computes 4_294_967_296
        // and rejects it (>= n=256). Test is valid on both 32-bit and 64-bit.
        let wasm32_wrap_skip: usize = (u32::MAX as usize) / 2 + 1;
        assert!(
            v_dqpsk(10, 256, 2, Some(wasm32_wrap_skip)).is_err(),
            "skip producing 2*skip >> n must be caught (u64 arithmetic, not wrap)"
        );
        // skip = n/2 exactly: two_sk = n → two_sk >= n → reject (nw would be 0).
        assert!(
            v_dqpsk(10, 256, 2, Some(128)).is_err(),
            "skip = n/2 (nw=0) must be rejected"
        );
        // skip = n/4: valid (nw = n/2 > 0); basis = (p+1)*nw = 11*128 = 1408 << cap.
        assert!(
            v_dqpsk(10, 256, 2, Some(64)).is_ok(),
            "skip = n/4 is a valid window inset"
        );
        // Default skip (None → n/8 = 32, nw = 192): valid.
        assert!(v_dqpsk(10, 256, 2, None).is_ok());
    }

    /// C2: Floor tone grid FFT window N must be capped.
    ///
    /// Before fix: M=2, K=1, f_low=400.0, f_high=400.001 passes the grid search
    /// (finds N≈48_000_000) and returns Ok — but tracked_tone_demod then allocates
    /// M×N ≈ 96 million doubles → OOM. After fix: `v_floor_tone_grid` caps the
    /// resolved N at `MAX_FLOOR_N` and returns Err for ultra-narrow bands.
    #[test]
    fn floor_huge_n_rejected() {
        // Ultra-narrow band: delta_f = 0.001 Hz → N ≈ 48_000_000 >> cap.
        assert!(
            v_floor_tone_grid(2, 1, 400.0, 400.001).is_err(),
            "band giving N >> MAX_FLOOR_N must be rejected to prevent M×N OOM alloc"
        );
        // Narrowband MNIST config (real): M=12, K=2, f_low=470, f_high=2200 → N=306, valid.
        assert!(
            v_floor_tone_grid(12, 2, 470.0, 2200.0).is_ok(),
            "real narrowband M=12 must still be accepted"
        );
    }

    /// Caps regression: doom_ship manifests have n_codewords=9217 and n_frames=1902,
    /// above the OLD 4096/1024 caps. The NEW caps (32768/8192) must accept them.
    #[test]
    fn doom_manifest_dimensions_validate_ok() {
        // m10doom3: rs_n=255, rs_k=245, n_cw=9217, frame_bits=81600, n_frames=231,
        // stream_bits=255*9217*8=18802680, payload_len=1465484.
        let n_cw = 9217usize;
        let stream_bits = 255 * n_cw * 8; // 18_802_680
        let starts: Vec<i64> = (0..231).map(|i| i as i64 * 519_000).collect();
        assert!(
            v_framing(255, 245, n_cw, 81600, 231, stream_bits, 1_465_484,
                      &starts, 120_000_000).is_ok(),
            "doom m10doom3 (n_cw=9217, n_frames=231) must pass updated caps"
        );
        // m10doom2: rs_n=255, rs_k=127, n_cw=3803, n_frames=1902, frame_bits=4080.
        // payload_len must be <= rs_k*n_cw = 127*3803 = 482_981.
        // last frame_start = 1901 * 69_000 = 131_169_000; body_end must be >= that.
        let n_cw2 = 3803usize;
        let stream_bits2 = 255 * n_cw2 * 8; // 7_758_120
        let payload_len2 = 127 * n_cw2; // 482_981 — the net-data capacity
        let starts2: Vec<i64> = (0..1902).map(|i| i as i64 * 69_000).collect();
        assert!(
            v_framing(255, 127, n_cw2, 4080, 1902, stream_bits2, payload_len2,
                      &starts2, 132_000_000).is_ok(),
            "doom m10doom2 (n_cw=3803, n_frames=1902) must pass updated caps"
        );
    }

    /// M3: D2X drop list length must be capped before allocation.
    ///
    /// Before fix: `v_d2x` allocated `bins_full`/`freqs_full`/`drop_set`/HashSet
    /// sized `p + n_drop + 1` before bounding `n_drop`. A JSON with 10 000 drops
    /// would allocate unchecked. After fix: len > MAX_D2X_DROPS → Err.
    #[test]
    fn d2x_drop_list_length_capped() {
        // 65 drops > MAX_D2X_DROPS (64) → must be rejected before any allocation.
        let too_many: Vec<f64> = (0..65).map(|i| 750.0 + i as f64 * 200.0).collect();
        assert!(
            v_d2x(18, 256, 2, &too_many, 4875.0).is_err(),
            "drop list length > MAX_D2X_DROPS must be rejected"
        );
        // drop_freqs_hz.len() > p must also be rejected even under MAX_D2X_DROPS.
        // p=3, 5 drops > p=3: too many drops for the comb to remain valid.
        let more_than_p: Vec<f64> = vec![750.0, 1500.0, 2250.0, 3000.0, 3750.0];
        assert!(
            v_d2x(3, 256, 2, &more_than_p, 4875.0).is_err(),
            "drop_freqs_hz.len() > p must be rejected"
        );
        // Real max (14 drops) is well under the cap and must be accepted when valid.
        let real_drops: Vec<f64> = vec![750.0, 4500.0, 5625.0, 6750.0];
        assert!(v_d2x(18, 256, 2, &real_drops, 4875.0).is_ok());
    }

    /// M4: manifest JSON size must be checked before serde allocation.
    ///
    /// Before fix: a 100 MB JSON string with a 10-million-element frame_starts array
    /// would be deserialized into an unbounded Vec<i64> before any validator ran.
    /// After fix: `v_manifest_json_size` is called first, rejecting strings above
    /// MAX_MANIFEST_JSON_BYTES (2 MiB — comfortably above the largest real manifest
    /// at 191 kB).
    #[test]
    fn manifest_json_size_capped() {
        // Exact cap boundary: one byte over must be rejected.
        let at_cap = "x".repeat(MAX_MANIFEST_JSON_BYTES);
        let over_cap = "x".repeat(MAX_MANIFEST_JSON_BYTES + 1);
        assert!(
            v_manifest_json_size(&at_cap).is_ok(),
            "JSON exactly at cap must be accepted"
        );
        assert!(
            v_manifest_json_size(&over_cap).is_err(),
            "JSON one byte over cap must be rejected"
        );
    }

    /// M5: layout sample positions must be bounded before reaching core arithmetic.
    ///
    /// `tx_chirp0/1`, `frame_starts[*]`, `body_end` flow into i64 add/sub in the
    /// core (decoder.rs:85, dqpsk.rs:376). A JSON with `tx_chirp1 = 2^62` would
    /// pass the existing `tx1 > tx0` check but cause issues downstream. After fix:
    /// `v_chirps` and `v_framing` reject any position above `MAX_LAYOUT_SAMPLES`.
    #[test]
    fn layout_positions_capped() {
        let cap = MAX_LAYOUT_SAMPLES as i64;
        // tx_chirp1 one over MAX_LAYOUT_SAMPLES → rejected by v_chirps.
        assert!(
            v_chirps(48000, cap + 1).is_err(),
            "tx_chirp1 > MAX_LAYOUT_SAMPLES must be rejected"
        );
        // Largest real tx_chirp1 = 126_610_624 (m10doom2) must still be accepted.
        assert!(
            v_chirps(48000, 126_610_624).is_ok(),
            "real doom tx_chirp1=126_610_624 must be accepted"
        );
        // frame_start over MAX_LAYOUT_SAMPLES → rejected by v_framing.
        let sb = 7 * 1 * 8; // rs_n=7, n_cw=1, stream_bits
        assert!(
            v_framing(7, 3, 1, sb, 1, sb, 3, &[cap + 1], cap + 2).is_err(),
            "frame_start > MAX_LAYOUT_SAMPLES must be rejected"
        );
        // body_end over MAX_LAYOUT_SAMPLES → rejected by v_framing.
        assert!(
            v_framing(7, 3, 1, sb, 1, sb, 3, &[0], cap + 1).is_err(),
            "body_end > MAX_LAYOUT_SAMPLES must be rejected"
        );
        // Real doom frame_start_max=126_549_088 must be accepted.
        let n_cw = 9217usize;
        let stream_bits = 255 * n_cw * 8;
        let starts: Vec<i64> = (0..231).map(|i| i as i64 * 519_000).collect();
        assert!(
            v_framing(255, 245, n_cw, 81600, 231, stream_bits, 1_465_484,
                      &starts, 120_000_000).is_ok(),
            "real doom layout positions must be accepted"
        );
    }

    // ── Self-review round 5 (CRITICAL 1 / MEDIUM 2-4 / HIGH 5) ──────────────

    /// CRITICAL 1: DQPSK basis allocation (p+1)×nw must be capped.
    ///
    /// `DqpskScheme::from_geometry` allocates `basis_re[nc][nw]` and `basis_im`
    /// where `nc = p+1`, `nw = n - 2*skip`. At p=MAX_P(512), n=MAX_N_FFT(65536),
    /// skip=n/8 → nw=49152: 513×49152×8×2 ≈ 403MB → WASM OOM. The per-dimension
    /// caps on p and n are NOT enough; their PRODUCT must be bounded too.
    /// After fix: `v_dqpsk` computes nw from validated sk and rejects if
    /// (p+1)*nw > MAX_DQPSK_BASIS.
    #[test]
    fn dqpsk_basis_product_capped() {
        // p=512 (= MAX_P), n=65536 (= MAX_N_FFT), skip=None (→ n/8=8192) →
        // nw = 65536 - 16384 = 49152. (p+1)*nw = 513*49152 = 25_205_376 > 2_000_000.
        // Both p and n individually pass their caps; only the PRODUCT guard blocks this.
        assert!(
            v_dqpsk(512, 65536, 1, None).is_err(),
            "p=MAX_P, n=MAX_N_FFT: (p+1)*nw=~25M exceeds basis cap → must be rejected"
        );
        // decode_r0 path (skip=n/8=8192, nw=49152): same issue.
        assert!(
            v_dqpsk(512, 65536, 1, Some(8192)).is_err(),
            "large-basis DQPSK must be rejected to prevent OOM in from_geometry"
        );
        // Real R0 config (p=10, n=256, skip=32 → nw=192): basis = 11*192 = 2112 << cap.
        assert!(v_dqpsk(10, 256, 4, None).is_ok(), "real R0 must still be accepted");
        // Real R3 config (p=21, n=256, skip=64 → nw=128): basis = 22*128 = 2816 << cap.
        assert!(v_dqpsk(21, 256, 2, Some(64)).is_ok(), "real R3 must still be accepted");
        // Direct helper: (p+1)*nw checked_mul at u64 boundary → None.
        let big_p1: u64 = u64::MAX / 65536 + 1;
        assert!(
            big_p1.checked_mul(65536).is_none(),
            "(p+1)*nw checked_mul must return None at u64 overflow boundary"
        );
    }

    /// MEDIUM 2: floor comb element budget — `build_comb_tables` stores ncomb×k_eff
    /// usizes in `subsets: Vec<Vec<usize>>` AND in the `HashMap` keys.
    ///
    /// The existing COMB_BUDGET caps C(M,K) at 1_000_000 entries, but each entry
    /// holds `k_eff` usizes. M=22, K=11 → C=705_432 < budget but each subset has
    /// 11 elements → 705_432×12 ≈ 8.5M usizes → ~136MB (64-bit) or ~68MB (32-bit).
    /// After fix: `v_floor_tone_grid` also checks ncomb × (k_eff+1) ≤ SUBSET_ELEMENT_BUDGET.
    #[test]
    fn floor_comb_subset_element_budget() {
        // M=22, K=11: C(22,11)=705_432 < COMB_BUDGET=1M (passes comb check alone),
        // k_eff=11, elements = 705_432 × 12 = 8_465_184 > SUBSET_ELEMENT_BUDGET → Err.
        assert!(
            v_floor_tone_grid(22, 11, 400.0, 10_000.0).is_err(),
            "M=22/K=11 subset element count ~8.5M must be rejected to prevent OOM"
        );
        // Real active config: M=16, K=2. C=120, k_eff=2, elements=360 << budget.
        assert!(
            v_floor_tone_grid(16, 2, 400.0, 10_000.0).is_ok(),
            "real M=16/K=2 must still be accepted"
        );
        // Legacy config: M=12, K=2. C=66, k_eff=2, elements=198 << budget.
        assert!(
            v_floor_tone_grid(12, 2, 470.0, 2200.0).is_ok(),
            "real narrowband M=12/K=2 must still be accepted"
        );
    }

    /// MEDIUM 3: `guard_samples` (i64) must be bounded before reaching decoder.rs.
    ///
    /// `FloorSection.guard` is added/subtracted from i64 frame positions in
    /// `decode_combo_section` (decoder.rs:85: `(align + st - section.guard).max(0)`).
    /// A very negative guard (i64::MIN) causes an i64 overflow/wrap in both debug
    /// (panic) and release (silent-wrong-result via saturating + .max(0)). After
    /// fix: `v_guard_samples` rejects any guard < 0 or > MAX_LAYOUT_SAMPLES.
    #[test]
    fn floor_guard_samples_capped() {
        // Negative guard is invalid: real guards are a small non-negative preamble margin.
        assert!(v_guard_samples(-1).is_err(), "negative guard_samples must be rejected");
        assert!(v_guard_samples(i64::MIN).is_err(), "i64::MIN guard_samples must be rejected");
        // Over-large guard: would cause overflow in align + st - guard arithmetic.
        assert!(
            v_guard_samples(MAX_LAYOUT_SAMPLES as i64 + 1).is_err(),
            "guard_samples > MAX_LAYOUT_SAMPLES must be rejected"
        );
        // Real value (2400 samples ≈ 50ms preamble at 48kHz): must be accepted.
        assert!(v_guard_samples(2400).is_ok(), "real guard_samples=2400 must pass");
        assert!(v_guard_samples(0).is_ok(), "guard_samples=0 must pass");
    }

    /// MEDIUM 4: per-frame sample span must be bounded before fft_convolve.
    ///
    /// `find_preamble` (called from tracked_tone_demod) allocates
    /// `2 × next_pow2(seg_len + pre_len) × Complex<f64>(16B)`. A 1-frame manifest
    /// with body_end=200M → seg_len=200M → alloc ≈ 2×268M×16B ≈ 8.6GB → WASM OOM.
    /// After fix: `v_framing` rejects any frame span > MAX_FRAME_SPAN_SAMPLES.
    #[test]
    fn frame_span_samples_capped() {
        // 1 frame, span = body_end - frame_starts[0] = 5_000_001 → Err.
        // stream_bits = 255*1*8 = 2040; all other caps in range.
        let sb = 255usize * 1 * 8;
        assert!(
            v_framing(255, 127, 1, sb, 1, sb, 127, &[0], 5_000_001).is_err(),
            "single-frame span 5_000_001 must be rejected by frame span cap"
        );
        // Span exactly at cap (5_000_000): must be accepted.
        assert!(
            v_framing(255, 127, 1, sb, 1, sb, 127, &[0], 5_000_000).is_ok(),
            "frame span exactly at cap (5_000_000) must be accepted"
        );
        // Real doom m10doom3 max span ≈ 630_000 << cap: must be accepted.
        let n_cw = 9217usize;
        let stream_bits = 255 * n_cw * 8;
        let starts: Vec<i64> = (0..231).map(|i| i as i64 * 519_000).collect();
        assert!(
            v_framing(255, 245, n_cw, 81600, 231, stream_bits, 1_465_484,
                      &starts, 120_000_000).is_ok(),
            "doom m10doom3 frame span ≈630K must be accepted"
        );
    }
}
