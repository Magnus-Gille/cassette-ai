//! WASM bindings for `cassette-codec`. Exposes `decode_floor(samples, manifest)`
//! to the Magnetic Vault companion app. Keeps the core crate free of any web
//! dependencies — this thin shim is the only wasm-aware layer.

use cassette_codec::decoder::{decode_floor_from_capture, FloorManifest, FloorSection};
use cassette_codec::framing::ComboMeta;
use serde::Deserialize;
use wasm_bindgen::prelude::*;

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

    let manifest = FloorManifest {
        tx_chirp0: m.tx_chirp0,
        tx_chirp1: m.tx_chirp1,
        section: FloorSection {
            m: m.meta.m,
            k: m.meta.k,
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
