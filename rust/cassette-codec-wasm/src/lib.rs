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

/// Validate the framing meta + frame layout (shared by floor/dqpsk/d2x).
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
    if !(0 < rs_k && rs_k < rs_n && rs_n <= 255) {
        return Err(format!("need 0 < rs_k < rs_n <= 255, got rs_k={rs_k} rs_n={rs_n}"));
    }
    if n_frames == 0 || n_cw == 0 || frame_bits == 0 {
        return Err("n_frames / n_codewords / frame_bits must be > 0".into());
    }
    if frame_starts.len() != n_frames {
        return Err(format!("frame_starts.len()={} != n_frames={n_frames}", frame_starts.len()));
    }
    if stream_bits != rs_n * n_cw * 8 {
        return Err(format!("stream_bits={stream_bits} != rs_n*n_cw*8={}", rs_n * n_cw * 8));
    }
    if payload_len > rs_k * n_cw {
        return Err(format!("payload_len={payload_len} > rs_k*n_cw={}", rs_k * n_cw));
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
    Ok(())
}

/// Validate DQPSK/D2X carrier geometry. `skip` defaults to N/8 when absent.
fn v_dqpsk(p: usize, n: usize, spacing: usize, skip: Option<usize>) -> Result<(), String> {
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
    // the b0+spacing*(p+drops) comb must fit under Nyquist (bin <= N/2)
    if 4 + spacing * (p + 8) > n / 2 {
        return Err("DQPSK carrier comb exceeds Nyquist for the given p/spacing".into());
    }
    Ok(())
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
}
