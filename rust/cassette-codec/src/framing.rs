//! framing — global RS-interleave whole-file FEC (port of `m3_codec.decode_payload`).
//!
//! The encoder RS(255,k)-encodes the payload into codewords, then column-major
//! interleaves them across frames so a single corrupted frame only nicks a few
//! bytes of each codeword (well within RS correction). Decoding inverts that:
//! pad/truncate each recovered frame's bits to its nominal length, concat,
//! pack to bytes, de-interleave, RS-decode every codeword (tolerating a few
//! fully-dead frames), and truncate to the original payload length.

use crate::rs;

/// The framing parameters carried in the manifest section `meta` block.
#[derive(Debug, Clone)]
pub struct ComboMeta {
    pub rs_n: usize,
    pub rs_k: usize,
    pub n_codewords: usize,
    pub frame_bits: usize,
    pub n_frames: usize,
    pub stream_bits: usize,
    pub payload_len: usize,
}

/// Result of a payload decode: the bytes plus how many codewords RS gave up on.
pub struct DecodedPayload {
    pub bytes: Vec<u8>,
    pub codewords_failed: usize,
}

/// Pack bits MSB-first into bytes (numpy `packbits`). `bits` length is assumed a
/// multiple of 8 (the caller guarantees `stream_bits % 8 == 0`); a trailing
/// partial byte would be zero-padded on the low side, matching numpy.
fn packbits(bits: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity((bits.len() + 7) / 8);
    let mut i = 0;
    while i < bits.len() {
        let mut b = 0u8;
        for j in 0..8 {
            let bit = if i + j < bits.len() { bits[i + j] & 1 } else { 0 };
            b = (b << 1) | bit;
        }
        out.push(b);
        i += 8;
    }
    out
}

/// Inverse of `m3_codec.encode_payload`. `frames_bits[i]` is the recovered bit
/// array for frame i (may be short/long/empty — it is normalised here).
pub fn decode_payload(frames_bits: &[Vec<u8>], meta: &ComboMeta) -> DecodedPayload {
    let nsym = meta.rs_n - meta.rs_k;
    let fb = meta.frame_bits;
    let nf = meta.n_frames;

    // Reassemble the stream at the EXACT bit positions encode used.
    let mut rx_bits: Vec<u8> = Vec::with_capacity(meta.stream_bits);
    for fi in 0..nf {
        let nominal = if fi < nf - 1 {
            fb
        } else {
            meta.stream_bits - fb * (nf - 1)
        };
        let empty: Vec<u8> = Vec::new();
        let rb = frames_bits.get(fi).unwrap_or(&empty);
        for j in 0..nominal {
            rx_bits.push(if j < rb.len() { rb[j] & 1 } else { 0 });
        }
    }
    rx_bits.truncate(meta.stream_bits);
    while rx_bits.len() < meta.stream_bits {
        rx_bits.push(0);
    }

    // packbits then de-interleave: codeword i = bytes[r*n_cw + i] for r in 0..rs_n.
    let rx_bytes = packbits(&rx_bits);
    let n_cw = meta.n_codewords;
    let rs_n = meta.rs_n;
    debug_assert!(rx_bytes.len() >= n_cw * rs_n);

    let mut recovered: Vec<u8> = Vec::with_capacity(n_cw * meta.rs_k);
    let mut n_fail = 0usize;
    let mut codeword = vec![0u8; rs_n];
    for i in 0..n_cw {
        for r in 0..rs_n {
            codeword[r] = rx_bytes[r * n_cw + i];
        }
        match rs::rs_decode(&codeword, nsym) {
            Ok(msg) => recovered.extend_from_slice(&msg),
            Err(_) => {
                n_fail += 1;
                recovered.extend(std::iter::repeat(0u8).take(meta.rs_k));
            }
        }
    }
    recovered.truncate(meta.payload_len);
    DecodedPayload {
        bytes: recovered,
        codewords_failed: n_fail,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn packbits_msb_first() {
        assert_eq!(packbits(&[1, 0, 0, 0, 0, 0, 0, 1]), vec![0x81]);
        assert_eq!(packbits(&[1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]), vec![0xff, 0x80]);
    }

    // A self-contained encode→interleave→decode round trip (no channel), mirroring
    // m3_codec encode_payload, to prove de-interleave + RS reassembly is exact and
    // that whole-dead frames are rescued by the interleave.
    #[test]
    fn interleave_roundtrip_with_dead_frame() {
        let rs_n = 255usize;
        let rs_k = 95usize;
        let nsym = rs_n - rs_k;
        // frame_bytes must be <= (nsym/2)*n_cw for a single-frame kill to stay
        // within RS capacity after column de-interleave. With n_cw=16 and
        // cap=80, that's <=1280; use 1000 (=> ~63 corrupted bytes/codeword).
        let frame_bytes = 1000usize;
        // payload of 1520 bytes (matches the floor fixture)
        let payload: Vec<u8> = (0..1520u32).map(|i| (i.wrapping_mul(37) % 256) as u8).collect();

        // --- encode (mirror m3_codec.encode_payload) ---
        let pad = (rs_k - payload.len() % rs_k) % rs_k;
        let mut padded = payload.clone();
        padded.extend(std::iter::repeat(0u8).take(pad));
        let n_cw = padded.len() / rs_k;
        let mut cw_concat: Vec<u8> = Vec::with_capacity(n_cw * rs_n);
        for c in 0..n_cw {
            let enc = rs::rs_encode(&padded[c * rs_k..(c + 1) * rs_k], nsym);
            cw_concat.extend_from_slice(&enc);
        }
        // column-major interleave: tx_bytes[r*n_cw + c] = cw[c][r]
        let mut tx_bytes = vec![0u8; n_cw * rs_n];
        for c in 0..n_cw {
            for r in 0..rs_n {
                tx_bytes[r * n_cw + c] = cw_concat[c * rs_n + r];
            }
        }
        // unpackbits MSB-first
        let mut tx_bits: Vec<u8> = Vec::with_capacity(tx_bytes.len() * 8);
        for &byte in &tx_bytes {
            for b in (0..8).rev() {
                tx_bits.push((byte >> b) & 1);
            }
        }
        let fb_bits = frame_bytes * 8;
        let mut frames: Vec<Vec<u8>> = Vec::new();
        let mut i = 0;
        while i < tx_bits.len() {
            let end = (i + fb_bits).min(tx_bits.len());
            frames.push(tx_bits[i..end].to_vec());
            i += fb_bits;
        }
        let meta = ComboMeta {
            rs_n,
            rs_k,
            n_codewords: n_cw,
            frame_bits: fb_bits,
            n_frames: frames.len(),
            stream_bits: tx_bits.len(),
            payload_len: payload.len(),
        };

        // clean decode
        let dec = decode_payload(&frames, &meta);
        assert_eq!(dec.bytes, payload);
        assert_eq!(dec.codewords_failed, 0);

        // kill one whole frame -> interleave must still recover (each codeword
        // loses only ~frame_bytes/n_cw bytes, within RS capacity nsym/2=80).
        let mut frames_dead = frames.clone();
        if frames_dead.len() > 2 {
            for b in frames_dead[1].iter_mut() {
                *b ^= 1;
            }
        }
        let dec2 = decode_payload(&frames_dead, &meta);
        assert_eq!(dec2.bytes, payload, "interleave should rescue one dead frame");
    }
}
