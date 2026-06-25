//! Reed-Solomon GF(2^8) codec — byte-exact with Python `reedsolo` (RSCodec defaults).
//!
//! Field conventions (matching reedsolo / "RS codes for coders" Wikiversity):
//!   prim polynomial : 0x11d
//!   generator α     : 2
//!   fcr             : 0  (first consecutive root = α^0 = 1)
//!   nsize           : 255 (GF(2^8) − 1)
//!   nsym            : caller-supplied parity symbol count
//!
//! Polynomial representation: **high-degree-first** throughout (index 0 = leading
//! coefficient), matching reedsolo's internal convention.

// ── GF(2^8) tables ──────────────────────────────────────────────────────────

const PRIM: u32 = 0x11d;

struct Gf {
    exp: [u8; 512], // antilog; doubled to avoid mod when adding two logs < 255
    log: [u8; 256], // log[0] unused (defined as 0 but never read)
}

impl Gf {
    fn build() -> Self {
        let mut exp = [0u8; 512];
        let mut log = [0u8; 256];
        let mut x: u32 = 1;
        for i in 0..255usize {
            exp[i] = x as u8;
            log[x as usize] = i as u8;
            x <<= 1;
            if x & 0x100 != 0 {
                x ^= PRIM;
            }
        }
        for i in 255..512usize {
            exp[i] = exp[i - 255];
        }
        Gf { exp, log }
    }

    #[inline]
    fn mul(&self, x: u8, y: u8) -> u8 {
        if x == 0 || y == 0 {
            return 0;
        }
        self.exp[self.log[x as usize] as usize + self.log[y as usize] as usize]
    }

    #[inline]
    fn div(&self, x: u8, y: u8) -> u8 {
        debug_assert!(y != 0, "GF division by zero");
        if x == 0 {
            return 0;
        }
        let lx = self.log[x as usize] as usize;
        let ly = self.log[y as usize] as usize;
        self.exp[(lx + 255 - ly) % 255]
    }

    #[inline]
    fn inv(&self, x: u8) -> u8 {
        debug_assert!(x != 0, "GF inverse of zero");
        self.exp[255 - self.log[x as usize] as usize]
    }
}

static GF: std::sync::OnceLock<Gf> = std::sync::OnceLock::new();

fn gf() -> &'static Gf {
    GF.get_or_init(Gf::build)
}

// ── Polynomial helpers (HIGH-FIRST representation) ───────────────────────────

/// Evaluate p at x using Horner's method.  p[0] = coefficient of highest degree.
fn poly_eval(p: &[u8], x: u8) -> u8 {
    let g = gf();
    let mut y = 0u8;
    for &c in p {
        y = g.mul(y, x) ^ c;
    }
    y
}

/// Multiply two high-first polynomials.
fn poly_mul(p: &[u8], q: &[u8]) -> Vec<u8> {
    let g = gf();
    let mut r = vec![0u8; p.len() + q.len() - 1];
    for (i, &pi) in p.iter().enumerate() {
        for (j, &qj) in q.iter().enumerate() {
            r[i + j] ^= g.mul(pi, qj);
        }
    }
    r
}

/// Scale polynomial by a GF scalar.
fn poly_scale(p: &[u8], s: u8) -> Vec<u8> {
    let g = gf();
    p.iter().map(|&c| g.mul(c, s)).collect()
}

/// XOR-add, zero-padding the shorter polynomial on the left (high-first).
fn poly_add(p: &[u8], q: &[u8]) -> Vec<u8> {
    let len = p.len().max(q.len());
    let mut r = vec![0u8; len];
    for (i, &c) in p.iter().enumerate() {
        r[i + len - p.len()] ^= c;
    }
    for (i, &c) in q.iter().enumerate() {
        r[i + len - q.len()] ^= c;
    }
    r
}

// ── Generator polynomial ─────────────────────────────────────────────────────

/// g(x) = ∏_{i=0}^{nsym-1} (x − α^i) with fcr=0, generator=2.
fn rs_generator_poly(nsym: usize) -> Vec<u8> {
    let g = gf();
    let mut gen = vec![1u8];
    for i in 0..nsym {
        gen = poly_mul(&gen, &[1, g.exp[i]]);
    }
    gen
}

// ── Encode ───────────────────────────────────────────────────────────────────

/// Encode `msg` into a codeword of length `msg.len() + nsym`.
/// Layout: [message bytes … | parity bytes …]
pub fn rs_encode(msg: &[u8], nsym: usize) -> Vec<u8> {
    let g = gf();
    let gen = rs_generator_poly(nsym);

    let mut lm = Vec::with_capacity(msg.len() + nsym);
    lm.extend_from_slice(msg);
    lm.extend(std::iter::repeat(0u8).take(nsym));

    for i in 0..msg.len() {
        let coef = lm[i];
        if coef != 0 {
            for j in 1..gen.len() {
                lm[i + j] ^= g.mul(gen[j], coef);
            }
        }
    }

    let mut cw = msg.to_vec();
    cw.extend_from_slice(&lm[msg.len()..]);
    cw
}

// ── Syndromes ─────────────────────────────────────────────────────────────────

/// syndromes[i] = codeword(α^i) for i = 0..nsym-1.
fn rs_syndromes(codeword: &[u8], nsym: usize) -> Vec<u8> {
    let g = gf();
    (0..nsym).map(|i| poly_eval(codeword, g.exp[i])).collect()
}

// ── Berlekamp-Massey ─────────────────────────────────────────────────────────

/// Returns the error-locator polynomial Λ(x) in HIGH-FIRST representation
/// with Λ[last] = 1 (constant term = 1).
///
/// Roots of Λ are at X_j^{-1} where X_j = α^{n-1-pos_j} for each error at
/// byte position pos_j.
///
/// Mirrors `reedsolo.rs_find_error_locator` (including the virtual synd_shift=1
/// effect, which is equivalent to feeding [0, S_0, ..., S_{nsym-1}] to a BM
/// without shift — the prepended 0 contributes nothing because it is always
/// accessed when the LFSR size is still 0).
fn berlekamp_massey(syndromes: &[u8]) -> Vec<u8> {
    let g = gf();
    let nsym = syndromes.len();

    // HIGH-FIRST: constant term = 1 is at index [len-1].
    let mut err_loc: Vec<u8> = vec![1u8]; // Λ = 1
    let mut old_loc: Vec<u8> = vec![1u8]; // B = 1

    for i in 0..nsym {
        // Discrepancy δ = S_i + Σ_{j=1}^{deg Λ} Λ_j · S_{i-j}
        // In high-first, Λ_j = err_loc[err_loc.len()-1-j].
        let mut delta = syndromes[i];
        let el = err_loc.len();
        for j in 1..el {
            // Skip when i < j (reedsolo's synd[0]=0 contributes nothing either)
            if i >= j {
                delta ^= g.mul(err_loc[el - 1 - j], syndromes[i - j]);
            }
        }

        // old_loc *= x  →  append 0 (high-first: one more power of x)
        old_loc.push(0u8);

        if delta != 0 {
            if old_loc.len() > err_loc.len() {
                let new_loc = poly_scale(&old_loc, delta);
                old_loc = poly_scale(&err_loc, g.inv(delta));
                err_loc = new_loc;
            }
            let scaled = poly_scale(&old_loc, delta);
            err_loc = poly_add(&err_loc, &scaled);
        }
    }

    let start = err_loc.iter().position(|&c| c != 0).unwrap_or(0);
    err_loc[start..].to_vec()
}

// ── Chien search ─────────────────────────────────────────────────────────────

/// Find error positions in the codeword.
///
/// Evaluates Λ(α^{-i}) for i = 0..n-1; when zero, position n-1-i has an error.
/// This is equivalent to reedsolo's approach (reverses Λ, evaluates reversed at α^i),
/// since reversed_Λ(α^i) = 0  ⟺  Λ(α^{-i}) = 0.
///
/// Returns None if the number of roots differs from deg(Λ) (uncorrectable).
fn chien_search(n: usize, err_loc: &[u8]) -> Option<Vec<usize>> {
    let g = gf();
    let expected = err_loc.len() - 1;
    let mut positions = Vec::with_capacity(expected);

    for i in 0..n {
        let xi_inv = if i == 0 { 1u8 } else { g.exp[255 - i] }; // α^{-i}
        if poly_eval(err_loc, xi_inv) == 0 {
            positions.push(n - 1 - i);
        }
    }

    if positions.len() != expected {
        return None;
    }
    Some(positions)
}

// ── Errata locator (product formula) ─────────────────────────────────────────

/// Build Λ(x) = ∏_j (1 + Xj·x)  where Xj = α^{n-1-pos_j}.
///
/// reedsolo builds this fresh from the Chien-found positions (not from BM).
/// This gives the canonical normalization (constant term = 1) needed by Forney.
fn build_errata_loc(err_pos: &[usize], n: usize) -> Vec<u8> {
    let g = gf();
    let mut loc = vec![1u8];
    for &pos in err_pos {
        let coef_pos = (n - 1 - pos) % 255; // n-1-pos, reduce mod 255 for safety
        let xj = g.exp[coef_pos];            // Xj = α^{n-1-pos}
        // factor = xj·x + 1  →  [xj, 1] in high-first
        loc = poly_mul(&loc, &[xj, 1]);
    }
    loc
}

// ── Error evaluator polynomial ───────────────────────────────────────────────

/// Compute the error evaluator polynomial Ω used in Forney's formula.
///
/// reedsolo's `rs_correct_errata` calls:
///   `rs_find_error_evaluator(synd[::-1], errata_loc, len(errata_loc)-1)`
/// where `synd = [0, S_0, ..., S_{nsym-1}]`, so `synd[::-1] = [S_{nsym-1}, ..., S_0, 0]`.
///
/// In high-first representation: the reversed synd polynomial × errata_loc,
/// keeping the last `num_errors+1` terms (the low-degree / remainder part).
fn error_evaluator(syndromes: &[u8], errata_loc: &[u8]) -> Vec<u8> {
    // synd[::-1] from reedsolo's perspective = reversed([S_0..S_{nsym-1}]) ++ [0]
    //                                        = [S_{nsym-1}, ..., S_0, 0]
    let mut synd_rev: Vec<u8> = syndromes.iter().rev().cloned().collect();
    synd_rev.push(0u8); // the leading-0 of [0,S_0,...] becomes trailing after reversal

    let product = poly_mul(&synd_rev, errata_loc);

    // Keep the low-degree part: last (num_errors+1) terms in high-first.
    let keep = errata_loc.len(); // num_errors + 1
    if product.len() <= keep {
        product
    } else {
        product[product.len() - keep..].to_vec()
    }
}

// ── Forney algorithm ─────────────────────────────────────────────────────────

/// Apply Forney corrections in-place.
///
/// For each error at position `pos`:
///   Xj = α^{n-1-pos}
///   magnitude = Xj · Ω(Xj^{-1}) / Λ'(Xj^{-1})
///
/// where Λ'(Xj^{-1}) = ∏_{k≠j} (1 − Xj^{-1}·Xk)  (product-formula derivative,
/// exactly as reedsolo computes `err_loc_prime`).
fn forney_correct(codeword: &mut Vec<u8>, err_pos: &[usize], omega: &[u8], n: usize) {
    let g = gf();

    // Xj = α^{n-1-pos} for each error position
    let xs: Vec<u8> = err_pos
        .iter()
        .map(|&pos| g.exp[(n - 1 - pos) % 255])
        .collect();

    for (i, (&pos, &xi)) in err_pos.iter().zip(xs.iter()).enumerate() {
        let xi_inv = g.inv(xi);

        // Ω(Xj^{-1})
        let omega_val = poly_eval(omega, xi_inv);

        // Λ'(Xj^{-1}) = ∏_{k≠i} (1 − Xj^{-1}·Xk)
        let mut denom = 1u8;
        for (k, &xk) in xs.iter().enumerate() {
            if k != i {
                // 1 − Xi_inv * Xk = 1 ⊕ gf_mul(xi_inv, xk) (GF(2) subtraction = XOR)
                denom = g.mul(denom, 1 ^ g.mul(xi_inv, xk));
            }
        }

        if denom == 0 {
            // Degenerate (shouldn't occur with a truly correctable error pattern)
            continue;
        }

        // magnitude = Xi^{1−fcr} · Ω(Xi^{-1}) / Λ'(Xi^{-1})
        //           = Xi · Ω(Xi^{-1}) / denom           (fcr = 0)
        let magnitude = g.mul(xi, g.div(omega_val, denom));
        codeword[pos] ^= magnitude;
    }
}

// ── Error type ────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RsError(pub String);

// ── Public API ────────────────────────────────────────────────────────────────

/// Decode a codeword of `k + nsym` bytes.  Returns the `k` recovered message bytes.
/// Corrects up to `nsym/2` symbol errors.  Returns `Err` if uncorrectable.
pub fn rs_decode(codeword: &[u8], nsym: usize) -> Result<Vec<u8>, RsError> {
    let n = codeword.len();
    let k = n
        .checked_sub(nsym)
        .ok_or_else(|| RsError("nsym >= codeword length".into()))?;

    let syndromes = rs_syndromes(codeword, nsym);

    if syndromes.iter().all(|&s| s == 0) {
        return Ok(codeword[..k].to_vec());
    }

    // 1. Find the error locator polynomial via Berlekamp-Massey.
    let err_loc = berlekamp_massey(&syndromes);
    let num_errors = err_loc.len() - 1;
    if num_errors > nsym / 2 {
        return Err(RsError(format!(
            "too many errors: {} > {}",
            num_errors,
            nsym / 2
        )));
    }

    // 2. Chien search for error positions.
    let err_pos = chien_search(n, &err_loc)
        .ok_or_else(|| RsError("Chien search failed — uncorrectable".into()))?;

    // 3. Build errata locator from positions (product formula) — needed for Forney.
    //    reedsolo recomputes this from Chien results rather than using BM output.
    let errata_loc = build_errata_loc(&err_pos, n);

    // 4. Compute the error evaluator polynomial Ω.
    let omega = error_evaluator(&syndromes, &errata_loc);

    // 5. Apply Forney corrections.
    let mut corrected = codeword.to_vec();
    forney_correct(&mut corrected, &err_pos, &omega, n);

    // 6. Verify all syndromes are zero.
    let check = rs_syndromes(&corrected, nsym);
    if check.iter().any(|&s| s != 0) {
        return Err(RsError("Forney correction failed syndrome check".into()));
    }

    Ok(corrected[..k].to_vec())
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn load_fixture() -> serde_json::Value {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../experiments/tape_v2/rust_fixtures/fixtures/rs_vector.json"
        );
        let data = std::fs::read_to_string(path).expect("fixture file not found");
        serde_json::from_str(&data).expect("fixture parse error")
    }

    fn json_bytes(v: &serde_json::Value) -> Vec<u8> {
        v.as_array()
            .unwrap()
            .iter()
            .map(|x| x.as_u64().unwrap() as u8)
            .collect()
    }

    /// Encode must be byte-exact with reedsolo.
    #[test]
    fn test_encode_matches_reedsolo() {
        let fix = load_fixture();
        let nsym = fix["nsym"].as_u64().unwrap() as usize;
        let msg = json_bytes(&fix["msg"]);
        let expected = json_bytes(&fix["codeword"]);

        let got = rs_encode(&msg, nsym);
        assert_eq!(
            got,
            expected,
            "encode mismatch — first diff at byte index {:?}",
            got.iter().zip(&expected).position(|(a, b)| a != b)
        );
    }

    /// Clean codeword (no errors) must decode to original message.
    #[test]
    fn test_decode_clean() {
        let fix = load_fixture();
        let nsym = fix["nsym"].as_u64().unwrap() as usize;
        let msg = json_bytes(&fix["msg"]);
        let cw = json_bytes(&fix["codeword"]);

        let recovered = rs_decode(&cw, nsym).expect("clean decode failed");
        assert_eq!(recovered, msg);
    }

    /// Must correct exactly 40 injected byte errors (nsym=160 → capacity 80).
    #[test]
    fn test_decode_40_errors() {
        let fix = load_fixture();
        let nsym = fix["nsym"].as_u64().unwrap() as usize;
        let msg = json_bytes(&fix["msg"]);
        let corrupted = json_bytes(&fix["corrupted"]);

        let recovered = rs_decode(&corrupted, nsym).expect("corrected decode failed");
        assert_eq!(
            recovered,
            msg,
            "mismatch after correcting {} injected errors",
            fix["errpos"].as_array().unwrap().len()
        );
    }

    /// Property-style test: encode random messages, flip up to nsym/2 bytes, decode.
    #[test]
    fn test_roundtrip_random_errors() {
        let nsym = 20usize; // capacity = 10 errors
        let k = 235usize;

        // Deterministic LCG
        let mut state: u64 = 0xdeadbeef_cafebabe;
        let mut next = || -> u8 {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            (state >> 33) as u8
        };

        for trial in 0..8 {
            let msg: Vec<u8> = (0..k).map(|_| next()).collect();
            let mut cw = rs_encode(&msg, nsym);

            let max_err = nsym / 2; // = 10
            let step = cw.len() / (max_err + 1);
            for i in 0..max_err {
                let pos = step * (i + 1);
                cw[pos] ^= next() | 1; // non-zero flip
            }

            let recovered =
                rs_decode(&cw, nsym).unwrap_or_else(|e| panic!("trial {trial}: {e:?}"));
            assert_eq!(recovered, msg, "trial {trial} roundtrip mismatch");
        }
    }
}
