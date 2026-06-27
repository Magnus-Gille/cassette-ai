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
    if tx1 <= tx0 {
        return Err(format!("tx_chirp1 ({tx1}) must be > tx_chirp0 ({tx0})"));
    }
    Ok(())
}

// ── Dimension caps (Fix B) ────────────────────────────────────────────────
// Derived from max real values across all experiments/tape_v2/*manifest*.json
// plus the Rust fixture manifests. Caps are set to comfortably above observed
// maxima so no valid tape is rejected, while bounding allocations.
//
//   Dimension       Max real   Cap
//   rs_n            255        255 (GF(2^8) hard limit; already enforced)
//   rs_k            223        254 (must be < rs_n)
//   n_codewords     1212       4096
//   frame_bits      40800      1_000_000
//   n_frames        155        1024
//   stream_bits     2_472_480  100_000_000
//   payload_len     153_823    10_000_000
//   p (DQPSK)       21         512   (tests reach 200)
//   n (DQPSK FFT)   256        65536 (power-of-two)
//   spacing         16         64
//   M (floor)       64         128
//   C(M,K) budget   41664      1_000_000
const MAX_N_CW: usize = 4_096;
const MAX_FRAME_BITS: usize = 1_000_000;
const MAX_N_FRAMES: usize = 1_024;
const MAX_STREAM_BITS: usize = 100_000_000;
const MAX_PAYLOAD_LEN: usize = 10_000_000;
const MAX_P: usize = 512;
const MAX_N_FFT: usize = 65_536;
const MAX_SPACING: usize = 64;
const MAX_M_FLOOR: usize = 128;
const COMB_BUDGET: u64 = 1_000_000;

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
    if frame_starts.windows(2).any(|w| w[1] <= w[0]) {
        return Err("frame_starts must be strictly increasing".into());
    }
    if let Some(&last) = frame_starts.last() {
        if body_end < last {
            return Err(format!("body_end={body_end} < last frame_start={last}"));
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
    if 2 * sk >= n {
        return Err(format!("DQPSK 2*skip ({}) must be < N ({n})", 2 * sk));
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
    match checked_binomial(m, k) {
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
    let m: JsonManifest = serde_json::from_str(manifest_json)
        .map_err(|e| JsValue::from_str(&format!("manifest parse error: {e}")))?;

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

    let m: JsonR0Manifest = serde_json::from_str(manifest_json)
        .map_err(|e| JsValue::from_str(&format!("manifest parse error: {e}")))?;

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

    let m: JsonD2XManifest = serde_json::from_str(manifest_json)
        .map_err(|e| JsValue::from_str(&format!("manifest parse error: {e}")))?;

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
        // n_codewords > 4096:
        assert!(
            v_framing(255, 127, 4097, 255, 1, 255 * 4097 * 8, 100, &[0], 99).is_err(),
            "n_codewords > 4096 must be rejected"
        );
        // frame_bits > 1_000_000:
        assert!(
            v_framing(255, 127, 1, 1_000_001, 1, 255 * 1 * 8, 100, &[0], 99).is_err(),
            "frame_bits > 1_000_000 must be rejected"
        );
        // n_frames > 1024:
        assert!(
            v_framing(255, 127, 1, 255 * 8, 1025, 255 * 1 * 8, 100,
                      &vec![0i64; 1025], 999).is_err(),
            "n_frames > 1024 must be rejected"
        );
        // stream_bits > 100_000_000 (need n_cw that makes rs_n*n_cw*8 > cap too):
        assert!(
            v_framing(255, 127, 50000, 1, 1, 102_000_000, 100, &[0], 99).is_err(),
            "stream_bits > 100_000_000 must be rejected"
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

    /// Fix A: arithmetic using values that would overflow u32 (wasm32 usize)
    /// must be caught by checked arithmetic. On 64-bit hosts these values also
    /// exceed dimension caps (tested above), so the cap fires first — but this
    /// test documents the contract: ANY input producing a product > u32::MAX
    /// must be rejected without panic, regardless of which guard fires.
    #[test]
    fn arithmetic_overflow_caught_by_checked_mul() {
        // rs_n * n_codewords * 8 overflows u32:
        // u32::MAX / (255 * 8) ≈ 2_097_664; 2_097_665 → product > u32::MAX.
        let big_ncw: usize = (u32::MAX as usize) / (255 * 8) + 1;
        assert!(
            v_framing(255, 127, big_ncw, 1, 1, 100, 10, &[0], 99).is_err(),
            "rs_n * n_codewords * 8 overflow (u32 wrap) must be caught"
        );
        // frame_bits * (n_frames-1) overflows u32:
        // 2^16 * 2^16 = 2^32 wraps u32; use fb = 2^16, nf-1 = 2^16 + 1 → overflow.
        let fb: usize = 1 << 16;
        let nf: usize = (1usize << 16) + 2;
        assert!(
            v_framing(255, 127, 1, fb, nf, 255 * 8, 100, &vec![0i64; nf], 999).is_err(),
            "frame_bits * (n_frames-1) overflow (u32 wrap) must be caught"
        );
        // spacing * (p + 8) overflows u32 in v_dqpsk:
        let big_sp: usize = (u32::MAX as usize) / (10 + 8) + 1;
        assert!(
            v_dqpsk(10, 256, big_sp, None).is_err(),
            "spacing * (p + 8) overflow (u32 wrap) must be caught"
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
        // frame_bits so large that (frame_bits)*(n_frames-1) overflows usize:
        // checked_mul must catch this before the subtraction.
        assert!(
            v_framing(7, 3, 2, usize::MAX / 4, 10, 112, 6,
                      &[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], 200).is_err(),
            "frame_bits*(n_frames-1) overflow must be caught"
        );
    }
}
