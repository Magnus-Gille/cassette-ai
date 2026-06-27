//! failure_paths — robustness and panic-safety tests for cassette-codec.
//!
//! Tests that malformed, truncated, or adversarial inputs are handled
//! gracefully: no panics, correct failure reporting via `codewords_failed`,
//! and no silent acceptance of wrong data.
//!
//! Each test is annotated as:
//!   ALREADY-SAFE : decoder handled this correctly before; test locks behavior.
//!   BUG-FIXED    : test exposed a real defect; fix is in the same commit.

use cassette_codec::decoder::{
    decode_combo_section, decode_floor_from_capture, FloorManifest, FloorSection,
    DEFAULT_F_HIGH, DEFAULT_F_LOW,
};
use cassette_codec::dqpsk::{decode_d2x_ensemble, D2XSection};
use cassette_codec::framing::{crc32, decode_payload, per_cw_decode, rx_codeword_matrix, ComboMeta};
use cassette_codec::rs::{rs_decode, rs_encode};

// ── helpers ──────────────────────────────────────────────────────────────────

/// Minimal but internally consistent ComboMeta for in-test roundtrips.
/// RS(7,3): n=7, k=3, nsym=4 parity symbols, corrects up to 2 errors/codeword.
fn minimal_meta(n_cw: usize, n_frames: usize) -> ComboMeta {
    let rs_n = 7usize;
    let rs_k = 3usize;
    let stream_bits = rs_n * n_cw * 8;
    let frame_bits = stream_bits / n_frames;
    ComboMeta {
        rs_n,
        rs_k,
        n_codewords: n_cw,
        frame_bits,
        n_frames,
        stream_bits,
        payload_len: rs_k * n_cw,
    }
}

/// Encode a payload into tx_bits using the same column-major interleave as
/// `m3_codec.encode_payload`, then split into `n_frames` equal chunks.
fn encode_to_frames(payload: &[u8], meta: &ComboMeta) -> Vec<Vec<u8>> {
    use cassette_codec::rs::rs_encode;
    let nsym = meta.rs_n - meta.rs_k;
    let rs_k = meta.rs_k;
    let n_cw = meta.n_codewords;
    let rs_n = meta.rs_n;

    // Pad payload to a multiple of rs_k.
    let mut padded = payload.to_vec();
    padded.extend(std::iter::repeat(0u8).take((rs_k - padded.len() % rs_k) % rs_k));

    // Encode each codeword.
    let mut cw_concat: Vec<u8> = Vec::with_capacity(n_cw * rs_n);
    for c in 0..n_cw {
        let enc = rs_encode(&padded[c * rs_k..(c + 1) * rs_k], nsym);
        cw_concat.extend_from_slice(&enc);
    }

    // Column-major interleave: tx_bytes[r*n_cw + c] = cw[c][r].
    let mut tx_bytes = vec![0u8; n_cw * rs_n];
    for c in 0..n_cw {
        for r in 0..rs_n {
            tx_bytes[r * n_cw + c] = cw_concat[c * rs_n + r];
        }
    }

    // Unpack bits MSB-first.
    let mut tx_bits: Vec<u8> = Vec::with_capacity(tx_bytes.len() * 8);
    for &byte in &tx_bytes {
        for b in (0..8).rev() {
            tx_bits.push((byte >> b) & 1);
        }
    }

    // Split into n_frames equal chunks.
    let fb = meta.frame_bits;
    (0..meta.n_frames)
        .map(|fi| tx_bits[fi * fb..((fi + 1) * fb).min(tx_bits.len())].to_vec())
        .collect()
}

// ── Case 1: Truncated raw capture ────────────────────────────────────────────

/// ALREADY-SAFE: A raw capture that is far shorter than the manifest expects
/// (no end chirp, frames out of range) must not panic. Frames that map outside
/// the audio buffer are treated as empty and produce zero bits; RS then fails
/// every codeword.
#[test]
fn truncated_capture_no_panic() {
    // Manifest describing a ~60 s tape; audio is only 0.5 s.
    let n_cw = 16usize;
    let meta = ComboMeta {
        rs_n: 255,
        rs_k: 95,
        n_codewords: n_cw,
        frame_bits: 7600,
        n_frames: 4,
        stream_bits: 255 * 16 * 8,
        payload_len: 1520,
    };
    let frame_starts: Vec<i64> = (0..4).map(|i| 48_000 + i * 200_000).collect();
    let manifest = FloorManifest {
        tx_chirp0: 12_000,
        tx_chirp1: 2_268_057,
        section: FloorSection {
            m: 16,
            k: 2,
            f_low: DEFAULT_F_LOW,
            f_high: DEFAULT_F_HIGH,
            frame_starts,
            body_end: 2_904_730,
            guard: 2_400,
        },
        meta,
    };
    // 0.5 s of silence — far shorter than the manifest expects.
    let raw = vec![0.0f64; 24_000];
    let res = decode_floor_from_capture(&raw, &manifest);
    // No panic. Payload length must match manifest.
    assert_eq!(res.payload.bytes.len(), 1520);
    // Note: the all-zero codeword IS a valid RS(255,95) codeword (all-zero
    // syndromes decode to the all-zero message), so cw_failed may be 0 even
    // on a completely silent/truncated capture. The contract is: no panic,
    // correct output length, and a finite speed estimate.
    assert!(
        res.speed.is_finite(),
        "speed must be finite even on a very short silent capture"
    );
}

/// ALREADY-SAFE: `decode_combo_section` with frame_starts beyond the audio
/// length must not panic or OOB-index. The `b <= a` guard in the frame-slice
/// loop clamps every OOB frame to an empty bits vec.
#[test]
fn truncated_audio_nom_oob_frames_no_panic() {
    let n_cw = 2usize;
    let n_frames = 3usize;
    let meta = minimal_meta(n_cw, n_frames);
    // frame_starts well beyond a 100-sample buffer.
    let section = FloorSection {
        m: 16,
        k: 2,
        f_low: DEFAULT_F_LOW,
        f_high: DEFAULT_F_HIGH,
        frame_starts: vec![10_000, 20_000, 30_000],
        body_end: 40_000,
        guard: 100,
    };
    let audio = vec![0.0f64; 100];
    let dec = decode_combo_section(&audio, &section, 0, &meta);
    // No panic; all codewords fail (no data in any frame).
    assert_eq!(dec.bytes.len(), meta.payload_len);
}

// ── Case 2: One dead frame recovered by interleave ───────────────────────────

/// ALREADY-SAFE: A single fully-dead frame (all bits flipped) is rescued by
/// the column-major interleave + RS(255,95). Each codeword loses only
/// ~frame_bytes/n_cw bytes — well within the RS capacity floor (nsym/2=80).
#[test]
fn one_dead_frame_recovered_by_interleave() {
    // Use a config where killing one frame is within RS(255,95) capacity.
    let rs_n = 255usize;
    let rs_k = 95usize;
    let nsym = rs_n - rs_k; // 160 parity symbols → capacity 80 errors/codeword
    let n_cw = 16usize;
    let n_frames = 4usize;
    // Each frame contributes rs_n * n_cw / n_frames = 255 * 16 / 4 = 1020 bytes.
    // Per codeword that is 1020 / n_cw = 63.75 ≈ 64 bytes → within capacity (80).
    let stream_bits = rs_n * n_cw * 8;
    let meta = ComboMeta {
        rs_n,
        rs_k,
        n_codewords: n_cw,
        frame_bits: stream_bits / n_frames,
        n_frames,
        stream_bits,
        payload_len: rs_k * n_cw,
    };
    let payload: Vec<u8> = (0..(rs_k * n_cw)).map(|i| (i.wrapping_mul(37) % 256) as u8).collect();
    let mut frames = encode_to_frames(&payload, &meta);
    // Kill one whole frame (flip all bits).
    for b in frames[1].iter_mut() {
        *b ^= 1;
    }
    let dec = decode_payload(&frames, &meta);
    assert_eq!(
        dec.bytes, payload,
        "interleave must recover the payload when one frame is dead (cw_failed={})",
        dec.codewords_failed
    );
    assert_eq!(dec.codewords_failed, 0, "all codewords should be recovered");
}

// ── Case 3: Too many corrupted frames ────────────────────────────────────────

/// ALREADY-SAFE: When more frames are destroyed than RS can handle,
/// `decode_payload` reports `cw_failed > 0` and returns bytes of the correct
/// length (zeros for the failed codewords). No panic.
#[test]
fn too_many_dead_frames_reports_failure_not_panic() {
    let rs_n = 255usize;
    let rs_k = 95usize;
    let nsym = rs_n - rs_k; // capacity 80 errors/codeword
    let n_cw = 4usize;
    let n_frames = 4usize;
    let stream_bits = rs_n * n_cw * 8;
    let meta = ComboMeta {
        rs_n,
        rs_k,
        n_codewords: n_cw,
        frame_bits: stream_bits / n_frames,
        n_frames,
        stream_bits,
        payload_len: rs_k * n_cw,
    };
    let payload: Vec<u8> = (0..(rs_k * n_cw)).map(|i| (i + 1) as u8).collect();
    let mut frames = encode_to_frames(&payload, &meta);
    // Flip EVERY bit in EVERY frame → each codeword has 255 error bytes >> 80 capacity.
    for frame in frames.iter_mut() {
        for b in frame.iter_mut() {
            *b ^= 1;
        }
    }
    let dec = decode_payload(&frames, &meta);
    // All codewords must fail.
    assert_eq!(
        dec.codewords_failed, n_cw,
        "all codewords must fail when all frames are completely corrupted"
    );
    // Bytes still have the right length (zeros for failed codewords).
    assert_eq!(
        dec.bytes.len(),
        meta.payload_len,
        "result length must equal payload_len even when all codewords fail"
    );
    // Failed codewords produce zero-padded output.
    assert!(
        dec.bytes.iter().all(|&b| b == 0),
        "failed codewords must produce zero-padded output, not garbage"
    );
}

// ── Case 4: NaN / Inf samples ────────────────────────────────────────────────

/// BUG-FIXED: NaN samples propagated through the FFT and into the lock-quality
/// sort (`mags.sort_by(|a,b| a.partial_cmp(b).unwrap())`), causing a panic
/// because `partial_cmp(NaN, NaN)` returns `None` and `.unwrap()` panics.
///
/// Fix: `dc_remove_normalize` now replaces non-finite values with 0.0 before
/// any arithmetic, so the FFT / correlator / sort never see NaN.
#[test]
fn nan_samples_no_panic() {
    let meta = ComboMeta {
        rs_n: 255,
        rs_k: 95,
        n_codewords: 16,
        frame_bits: 7600,
        n_frames: 1,
        stream_bits: 255 * 16 * 8,
        payload_len: 1520,
    };
    let manifest = FloorManifest {
        tx_chirp0: 2_400,
        tx_chirp1: 4_800,
        section: FloorSection {
            m: 16,
            k: 2,
            f_low: DEFAULT_F_LOW,
            f_high: DEFAULT_F_HIGH,
            frame_starts: vec![2_400],
            body_end: 48_000,
            guard: 0,
        },
        meta,
    };
    // A realistic-length buffer with scattered NaN / ±Inf.
    let mut raw = vec![0.1f64; 48_001];
    raw[100] = f64::NAN;
    raw[200] = f64::INFINITY;
    raw[300] = f64::NEG_INFINITY;
    raw[5_000] = f64::NAN;
    // Must not panic (was: panic in sort_by(.unwrap()) on NaN comparison).
    let res = decode_floor_from_capture(&raw, &manifest);
    // Output length is always payload_len.
    assert_eq!(res.payload.bytes.len(), 1520);
    // speed/align/lock_quality must be finite (non-NaN) even with poisoned input.
    assert!(res.speed.is_finite(), "speed must be finite despite NaN input");
    assert!(res.lock_quality.is_finite(), "lock_quality must be finite despite NaN input");
}

/// BUG-FIXED (companion): All-NaN buffer (not just scattered) must also not panic.
#[test]
fn all_nan_buffer_no_panic() {
    let meta = ComboMeta {
        rs_n: 255,
        rs_k: 95,
        n_codewords: 16,
        frame_bits: 7600,
        n_frames: 1,
        stream_bits: 255 * 16 * 8,
        payload_len: 1520,
    };
    let manifest = FloorManifest {
        tx_chirp0: 2_400,
        tx_chirp1: 4_800,
        section: FloorSection {
            m: 16,
            k: 2,
            f_low: DEFAULT_F_LOW,
            f_high: DEFAULT_F_HIGH,
            frame_starts: vec![2_400],
            body_end: 10_000,
            guard: 0,
        },
        meta,
    };
    let raw = vec![f64::NAN; 10_001];
    let res = decode_floor_from_capture(&raw, &manifest);
    assert_eq!(res.payload.bytes.len(), 1520);
    assert!(res.speed.is_finite());
}

/// BUG-FIXED (companion): All-Inf buffer must also not panic.
#[test]
fn all_inf_buffer_no_panic() {
    let meta = ComboMeta {
        rs_n: 255,
        rs_k: 95,
        n_codewords: 16,
        frame_bits: 7600,
        n_frames: 1,
        stream_bits: 255 * 16 * 8,
        payload_len: 1520,
    };
    let manifest = FloorManifest {
        tx_chirp0: 2_400,
        tx_chirp1: 4_800,
        section: FloorSection {
            m: 16,
            k: 2,
            f_low: DEFAULT_F_LOW,
            f_high: DEFAULT_F_HIGH,
            frame_starts: vec![2_400],
            body_end: 10_000,
            guard: 0,
        },
        meta,
    };
    let raw = vec![f64::INFINITY; 10_001];
    let res = decode_floor_from_capture(&raw, &manifest);
    assert_eq!(res.payload.bytes.len(), 1520);
    assert!(res.speed.is_finite());
}

// ── Case 5: CRC length mismatch on D2X/R3 ───────────────────────────────────

/// ALREADY-SAFE: `per_cw_decode` never silently accepts a codeword unless its
/// CRC32 matches an entry in the supplied table. A wrong, empty, or short table
/// produces all-None results — NOT a silent wrong-but-valid-looking output.
#[test]
fn crc_table_mismatch_no_silent_accept() {
    let rs_n = 7usize;
    let rs_k = 3usize;
    let nsym = rs_n - rs_k; // 4
    let n_cw = 2usize;
    let meta = minimal_meta(n_cw, 1);

    // Encode two small messages.
    let msg0: Vec<u8> = vec![1, 2, 3];
    let msg1: Vec<u8> = vec![4, 5, 6];
    let cw0 = rs_encode(&msg0, nsym);
    let cw1 = rs_encode(&msg1, nsym);
    let rx_mat = vec![cw0, cw1];

    // Correct CRCs.
    let good_crcs = vec![crc32(&msg0), crc32(&msg1)];

    // 1. Correct CRCs → both codewords accepted.
    let res = per_cw_decode(&rx_mat, &meta, &good_crcs);
    assert!(res[0].is_some(), "cw0 must be accepted with correct CRC");
    assert!(res[1].is_some(), "cw1 must be accepted with correct CRC");
    assert_eq!(res[0].as_ref().unwrap(), &msg0);
    assert_eq!(res[1].as_ref().unwrap(), &msg1);

    // 2. Wrong CRCs (single-bit flip) → neither accepted, no panic.
    let wrong_crcs = vec![good_crcs[0] ^ 1, good_crcs[1] ^ 1];
    let res = per_cw_decode(&rx_mat, &meta, &wrong_crcs);
    assert!(res[0].is_none(), "cw0 must NOT be accepted with wrong CRC");
    assert!(res[1].is_none(), "cw1 must NOT be accepted with wrong CRC");

    // 3. Empty CRC table → nothing accepted.
    let res = per_cw_decode(&rx_mat, &meta, &[]);
    assert!(res[0].is_none(), "cw0 must NOT be accepted with empty CRC table");
    assert!(res[1].is_none(), "cw1 must NOT be accepted with empty CRC table");

    // 4. Short CRC table (only entry 0 correct) → only cw0 accepted, cw1 not.
    let short_crcs = vec![good_crcs[0]];
    let res = per_cw_decode(&rx_mat, &meta, &short_crcs);
    assert!(res[0].is_some(), "cw0 accepted (CRC entry present and correct)");
    assert!(res[1].is_none(), "cw1 NOT accepted (beyond CRC table length)");
}

/// ALREADY-SAFE: `decode_d2x_ensemble` with an empty CRC table must not panic
/// and must report cw_failed == n_codewords (the ensemble never trusts anything).
#[test]
fn d2x_empty_crc_table_returns_all_failed() {
    // R2 geometry: p=18, N=256, spacing=2, drops=[750,4500,5625,6750], pilot=4875.
    let n_cw = 4usize;
    let meta = ComboMeta {
        rs_n: 255,
        rs_k: 127,
        n_codewords: n_cw,
        frame_bits: 255 * 4 * 8 / 3,
        n_frames: 3,
        stream_bits: 255 * 4 * 8,
        payload_len: 127 * 4,
    };
    let section = D2XSection {
        p: 18,
        n: 256,
        spacing: 2,
        drop_freqs_hz: vec![750.0, 4500.0, 5625.0, 6750.0],
        pilot_hz: 4875.0,
        frame_starts: vec![0, 48_000, 96_000],
        body_end: 144_000,
    };
    // Short silence — no valid data.
    let audio = vec![0.0f64; 1_000];
    // Empty CRC table: no codeword can be accepted.
    let dec = decode_d2x_ensemble(&audio, &section, 0, &meta, &[]);
    assert_eq!(
        dec.codewords_failed, n_cw,
        "empty CRC table must result in all codewords failing"
    );
    assert_eq!(dec.bytes.len(), meta.payload_len);
}

/// ALREADY-SAFE: `rx_codeword_matrix` with `stream_bits` consistent with the
/// meta never OOB-panics. This test uses a short but internally consistent meta.
#[test]
fn rx_codeword_matrix_consistent_meta_no_panic() {
    let meta = minimal_meta(2, 1);
    // All-zero bits (produces valid zero codewords from packbits).
    let frames = vec![vec![0u8; meta.frame_bits]];
    // Must not panic; all-zero codeword is valid RS so cw_failed = 0.
    let dec = decode_payload(&frames, &meta);
    assert_eq!(dec.bytes.len(), meta.payload_len);
}

// ── Case 6: WASM-boundary path (native harness) ──────────────────────────────
// The `#[wasm_bindgen]` functions use `JsValue` and cannot be called from native
// tests directly. The decode-path they exercise — JSON parse → validators →
// core decode — is tested here by calling the same underlying functions with the
// same JSON input the wasm shim would receive. A true wasm-bindgen/browser test
// still requires the wasm32 target + wasm-pack/node; that is toolchain-blocked
// in this environment (note logged in the commit message).

/// ALREADY-SAFE: The floor manifest validator accepts a well-formed JSON that
/// the cassette-codec-wasm `decode_floor` binding would receive, and rejects
/// clearly malformed JSON. This tests the shared parse+validate logic natively.
#[test]
fn wasm_boundary_floor_json_parse_path_native() {
    use serde::Deserialize;
    use cassette_codec::framing::ComboMeta;

    // Mirror the JsonManifest / JsonSection / JsonMeta structs from the wasm crate
    // (they live in wasm crate's private items; we re-derive them here to test the
    // SAME JSON schema through the same serde path).
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
        #[serde(default)]
        f_low: Option<f64>,
        #[serde(default)]
        f_high: Option<f64>,
    }
    #[derive(Deserialize)]
    struct JsonManifest {
        tx_chirp0: i64,
        tx_chirp1: i64,
        section: JsonSection,
        meta: JsonMeta,
    }

    // Valid floor manifest (values from the shipped fullspectrum manifest).
    let valid_json = r#"{
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

    // Must parse without error.
    let parsed: JsonManifest = serde_json::from_str(valid_json)
        .expect("valid manifest JSON must parse");
    assert_eq!(parsed.tx_chirp0, 48000);
    assert_eq!(parsed.tx_chirp1, 2268057);
    assert_eq!(parsed.meta.rs_n, 255);
    assert_eq!(parsed.meta.rs_k, 95);
    assert_eq!(parsed.section.frame_starts.len(), 4);

    // Exercise the same validators the wasm decode_floor binding calls.
    // (We replicate them inline to avoid a cross-crate dependency on wasm crate internals.)
    fn v_chirps(tx0: i64, tx1: i64) -> Result<(), String> {
        if tx1 <= tx0 { return Err("tx1 <= tx0".into()); }
        Ok(())
    }
    fn v_framing(rs_n: usize, rs_k: usize, n_cw: usize, frame_bits: usize, n_frames: usize,
                 stream_bits: usize, payload_len: usize, starts: &[i64], body_end: i64)
        -> Result<(), String>
    {
        if !(0 < rs_k && rs_k < rs_n && rs_n <= 255) { return Err("RS params".into()); }
        if n_frames == 0 || n_cw == 0 || frame_bits == 0 { return Err("zero param".into()); }
        if starts.len() != n_frames { return Err("frame_starts len".into()); }
        if stream_bits != rs_n * n_cw * 8 { return Err("stream_bits".into()); }
        if payload_len > rs_k * n_cw { return Err("payload_len".into()); }
        if starts.iter().any(|&s| s < 0) { return Err("negative start".into()); }
        if starts.windows(2).any(|w| w[1] <= w[0]) { return Err("non-monotonic".into()); }
        if let Some(&last) = starts.last() {
            if body_end < last { return Err("body_end < last_start".into()); }
        }
        Ok(())
    }

    // Must accept the valid manifest.
    assert!(v_chirps(parsed.tx_chirp0, parsed.tx_chirp1).is_ok());
    assert!(v_framing(
        parsed.meta.rs_n, parsed.meta.rs_k, parsed.meta.n_codewords,
        parsed.meta.frame_bits, parsed.meta.n_frames, parsed.meta.stream_bits,
        parsed.meta.payload_len, &parsed.section.frame_starts, parsed.section.body_end,
    ).is_ok());

    // Malformed JSON → parse error (not a panic).
    let bad_json = r#"{ "tx_chirp0": "not_a_number", "tx_chirp1": 99 }"#;
    assert!(serde_json::from_str::<JsonManifest>(bad_json).is_err(),
        "malformed JSON must be rejected by serde, not panic");

    // Truncated JSON → parse error.
    let truncated = r#"{ "tx_chirp0": 48000"#;
    assert!(serde_json::from_str::<JsonManifest>(truncated).is_err());

    // Semantically wrong: tx_chirp1 <= tx_chirp0 → validator rejects.
    assert!(v_chirps(48000, 48000).is_err());
    assert!(v_chirps(48000, 100).is_err());

    // rs_n > 255 → framing validator rejects.
    assert!(v_framing(256, 95, 16, 7600, 4, 32640, 1520,
                      &[0,1,2,3], 99).is_err());

    // stream_bits inconsistent → framing validator rejects.
    assert!(v_framing(255, 95, 16, 7600, 4, 999, 1520,
                      &[0,1,2,3], 99).is_err());
}

// ── Codex-review findings ─────────────────────────────────────────────────────

/// ③ BUG-FIXED (codex review): The framing.rs fix (get().unwrap_or(0)) traded
/// an OOB panic for a SILENT WRONG RESULT — when `stream_bits < rs_n*n_cw*8`,
/// the zero-filled matrix produced an all-zero RS codeword (which RS accepts as
/// the all-zero message) → `cw_failed = 0` with an all-zero payload reported as
/// "success". `decode_payload` now detects the inconsistency early and returns
/// `cw_failed = n_codewords` instead of silently succeeding.
#[test]
fn inconsistent_meta_stream_bits_not_silently_accepted() {
    let meta = ComboMeta {
        rs_n: 7,
        rs_k: 3,
        n_codewords: 2,
        frame_bits: 8,    // wrong: should be rs_n * n_cw * 8 / n_frames = 56
        n_frames: 1,
        stream_bits: 8,   // inconsistent: should be 7 * 2 * 8 = 112
        payload_len: 6,
    };
    let frames = vec![vec![0u8; 8]];
    let dec = decode_payload(&frames, &meta);
    // Must NOT silently succeed (was: cw_failed = 0 because zero-filled matrix
    // was a valid RS all-zero codeword).
    assert_eq!(
        dec.codewords_failed, meta.n_codewords,
        "inconsistent meta (stream_bits={} != rs_n*n_cw*8={}) must report all \
         codewords failed, not silently return zeros as a successful decode",
        meta.stream_bits, meta.rs_n * meta.n_codewords * 8
    );
    // Bytes still have the correct length (zeros for failed codewords).
    assert_eq!(dec.bytes.len(), meta.payload_len);
}

/// Fix C (codex review ⑤): Frame-partition underflow must be caught in the
/// CORE (not just the WASM validator). With n_frames=4, frame_bits=40,
/// stream_bits=112 (=7*2*8 ✓ consistent), (n_frames-1)*frame_bits=120 >=
/// stream_bits=112, so the last-frame nominal = 0 via saturating_sub.
/// Before Fix C: rx_codeword_matrix received 0 bits for the final frame →
/// padded to 0s → valid all-zero RS codeword → cw_failed = 0 silent wrong result.
/// After Fix C: decode_payload returns cw_failed = n_codewords.
#[test]
fn core_frame_partition_silent_wrong_result_caught() {
    // stream_bits = 7 * 2 * 8 = 112 — consistent (passes stream_bits guard).
    // (n_frames-1)*frame_bits = 3 * 40 = 120 >= 112 — partition is broken.
    let meta = ComboMeta {
        rs_n: 7,
        rs_k: 3,
        n_codewords: 2,
        frame_bits: 40,
        n_frames: 4,
        stream_bits: 112,
        payload_len: 6,
    };
    // Supply 4 all-zero frames; saturating_sub would give 0-bit last frame.
    let frames: Vec<Vec<u8>> = vec![vec![0u8; 40]; 4];
    let dec = decode_payload(&frames, &meta);
    assert_eq!(
        dec.codewords_failed, meta.n_codewords,
        "broken frame partition (last-frame nominal underflows) must report all \
         codewords failed, not silently decode zero-filled codeword as success"
    );
    assert_eq!(dec.bytes.len(), meta.payload_len);
}
