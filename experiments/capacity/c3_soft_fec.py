"""c3_soft_fec.py — Hypothesis C3: Soft-decision FEC credit for MFSK-32.

Claim: project_to_cassette uses a conservative hard-decision BER->code-rate
table. MFSK FFT bin energies are native SOFT information; a soft-decision
convolutional decoder extracts ~1.5-2 dB of coding gain and decodes reliably
at a HIGHER code rate than the hard table grants for the same raw BER.

Approach:
  1. Re-implement MFSK-32 with soft LLR output (log-sum-exp over bin energies).
  2. Encode payload with a rate-1/2 K=7 convolutional code (NASA standard poly).
  3. Use puncturing to sweep effective code rates: 1/2, 2/3, 3/4, 5/6, 7/8.
  4. Soft Viterbi decode using the FFT-derived LLRs.
  5. For each rate: measure post-decode BER and P_full over n_seeds.
  6. Best R where P_full=1.0 defines net_bps_soft.
  7. Compare vs hard-table projection at same raw BER.

ACCEPT: net_bps_soft >= 1.15 * 1075.6 = 1236.9 AND P_full=1.0 AND sanity_ber ~0.

Key: the scheme stores the target n_data_bits so the decoder knows exactly
how many bits to decode (resolving the pad-length ambiguity at the receiver).
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import capture_scenarios as cs   # noqa: E402
import hyp_common as hc           # noqa: E402

SAMPLE_RATE = 48_000
USABLE_F_LOW  = 400.0
USABLE_F_HIGH = 10_000.0
M = 32
BPS = 5  # log2(32)

# MFSK-32 tone grid (same as hyp_h2_mfsk.py)
USABLE_BW = USABLE_F_HIGH - USABLE_F_LOW
DELTA_F = USABLE_BW / (M - 1)
T_SYM = 1.0 / DELTA_F
N_SYM = int(round(T_SYM * SAMPLE_RATE))
FREQS = np.array([USABLE_F_LOW + i * DELTA_F for i in range(M)])
PREAMBLE = hc.make_preamble(0.25).astype(np.float32)

# Reference numbers from c0_reference.json
MFSK32_GROSS   = 1411.764705882353
MFSK32_NET     = 1075.6302521008402
MFSK32_RAW_BER = 0.002015625
ACCEPT_BAR     = 1.15 * MFSK32_NET  # 1236.97 bps


# ===========================================================================
# Convolutional code: K=7, rate 1/2, NASA standard generators
#   g1 = 0o133 = 91  = 1011011
#   g2 = 0o171 = 121 = 1111001
# ===========================================================================
K_CONV   = 7
G1       = 0o133
G2       = 0o171
N_STATES = 1 << (K_CONV - 1)  # 64 states

# Pre-build forward transition table: (state, bit) -> (next_state, o1, o2)
_FWD: dict[tuple[int, int], tuple[int, int, int]] = {}

for _s in range(N_STATES):
    for _b in range(2):
        _reg = (_b << (K_CONV - 1)) | _s
        _o1  = bin(_reg & G1).count('1') % 2
        _o2  = bin(_reg & G2).count('1') % 2
        _ns  = ((_b << (K_CONV - 2)) | (_s >> 1)) & (N_STATES - 1)
        _FWD[(_s, _b)] = (_ns, _o1, _o2)


def conv_encode(bits: np.ndarray) -> np.ndarray:
    """Rate-1/2 K=7 convolutional encoder.

    Returns 2*(len(bits) + K_CONV - 1) coded bits, including K_CONV-1 flush zeros.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    n_total = len(bits) + K_CONV - 1
    out = np.empty(2 * n_total, dtype=np.uint8)
    state = 0
    all_bits = np.concatenate([bits, np.zeros(K_CONV - 1, dtype=np.uint8)])
    for i, b in enumerate(all_bits):
        ns, o1, o2 = _FWD[(state, int(b))]
        out[2 * i]     = o1
        out[2 * i + 1] = o2
        state = ns
    return out


def soft_viterbi(llrs: np.ndarray, n_input_bits: int) -> np.ndarray:
    """Soft Viterbi decoder.

    llrs:         float64 array, length >= 2*(n_input_bits + K_CONV - 1).
                  Convention: positive = coded bit likely 0.
    n_input_bits: number of source bits to decode.
    Returns:      decoded bits, length n_input_bits.
    """
    n_total = n_input_bits + K_CONV - 1
    NEG_INF = -1e18

    pm      = np.full(N_STATES, NEG_INF, dtype=np.float64)
    pm[0]   = 0.0
    trace_ps  = np.zeros((n_total, N_STATES), dtype=np.int16)
    trace_bit = np.zeros((n_total, N_STATES), dtype=np.uint8)

    for t in range(n_total):
        l1 = float(llrs[2 * t])     if 2 * t     < len(llrs) else 0.0
        l2 = float(llrs[2 * t + 1]) if 2 * t + 1 < len(llrs) else 0.0
        new_pm = np.full(N_STATES, NEG_INF, dtype=np.float64)
        for state in range(N_STATES):
            if pm[state] == NEG_INF:
                continue
            for bit in range(2):
                ns, o1, o2 = _FWD[(state, bit)]
                bm    = (l1 if o1 == 0 else -l1) + (l2 if o2 == 0 else -l2)
                total = pm[state] + bm
                if total > new_pm[ns]:
                    new_pm[ns]       = total
                    trace_ps[t, ns]  = state
                    trace_bit[t, ns] = bit
        pm = new_pm

    # Traceback from state 0 (encoder was flushed with zeros)
    state   = 0
    decoded = np.empty(n_total, dtype=np.uint8)
    for t in range(n_total - 1, -1, -1):
        decoded[t] = trace_bit[t, state]
        state      = int(trace_ps[t, state])
    return decoded[:n_input_bits]


# ---------------------------------------------------------------------------
# Standard IEEE 802.11 puncturing patterns for rate-1/2 K=7 codes
# (rate_name, numerator, denominator, keep_mask)
# keep_mask: 1 = keep, 0 = puncture; applied cyclically over pairs of coded bits.
# ---------------------------------------------------------------------------
PUNCT_PATTERNS: list[tuple[str, int, int, list[int]]] = [
    ("1/2", 1, 2, [1, 1]),
    ("2/3", 2, 3, [1, 1, 1, 0]),
    ("3/4", 3, 4, [1, 1, 1, 0, 0, 1]),
    ("5/6", 5, 6, [1, 1, 1, 0, 1, 0, 1, 0, 0, 1]),
    ("7/8", 7, 8, [1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1]),
]


def apply_puncture(coded: np.ndarray, mask: list[int]) -> np.ndarray:
    """Keep coded bits where mask (tiled cyclically) is 1."""
    ma  = np.array(mask, dtype=np.uint8)
    n   = len(coded)
    keep = np.tile(ma, (n // len(ma)) + 1)[:n]
    return coded[keep == 1]


def depuncture(rx_llrs: np.ndarray, mask: list[int], n_coded: int) -> np.ndarray:
    """Restore full-length LLR array by inserting 0.0 at punctured positions.

    Any kept positions for which rx_llrs is short (e.g. due to channel dropping
    the tail symbol) remain 0.0 — a neutral LLR, equivalent to an erasure.
    """
    out  = np.zeros(n_coded, dtype=np.float64)
    ma   = np.array(mask, dtype=np.uint8)
    keep = np.tile(ma, (n_coded // len(ma)) + 1)[:n_coded]
    kept_pos = np.where(keep == 1)[0]
    n_fill   = min(len(kept_pos), len(rx_llrs))
    out[kept_pos[:n_fill]] = rx_llrs[:n_fill]
    return out


# ===========================================================================
# MFSK-32 modulator (bit stream -> audio)
# ===========================================================================
def _bits_to_sym(bits_chunk: np.ndarray) -> int:
    return int(np.packbits(bits_chunk, bitorder='big')[0]) >> (8 - BPS)


def _sym_to_bits(sym: int) -> np.ndarray:
    return np.unpackbits(np.array([sym], dtype=np.uint8), bitorder='big')[-BPS:]


def mfsk32_modulate(bits: np.ndarray) -> np.ndarray:
    """MFSK-32 modulate. bits (uint8) -> float32 audio @48kHz including preamble."""
    bits = np.asarray(bits, dtype=np.uint8)
    pad  = (BPS - len(bits) % BPS) % BPS
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    n_syms = len(bits) // BPS

    t          = np.arange(N_SYM, dtype=np.float64) / SAMPLE_RATE
    tone_waves = np.array([np.sin(2.0 * math.pi * f * t) for f in FREQS], dtype=np.float32)

    body = np.empty(n_syms * N_SYM, dtype=np.float32)
    for i in range(n_syms):
        sym = _bits_to_sym(bits[i * BPS:(i + 1) * BPS])
        body[i * N_SYM:(i + 1) * N_SYM] = tone_waves[sym]

    audio = np.concatenate([PREAMBLE, body]).astype(np.float32)
    peak  = np.max(np.abs(audio))
    if peak > 0:
        audio = (audio / peak * 0.70).astype(np.float32)
    return audio


# ===========================================================================
# MFSK-32 soft demodulator (audio -> hard bits + per-bit LLRs)
# ===========================================================================
def mfsk32_demodulate_soft(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """MFSK-32 demodulate with soft LLR output.

    Returns:
      hard_bits: uint8 array (hard decisions)
      llrs:      float64 array of per-bit LLRs (positive = likely 0; negative = likely 1)
    """
    audio      = np.asarray(audio, dtype=np.float32)
    data_start = hc.find_preamble(audio, 0.25)
    N          = int(round(T_SYM * sr))
    data       = audio[data_start:]
    n_complete = len(data) // N

    if n_complete == 0:
        return np.zeros(0, dtype=np.uint8), np.zeros(0, dtype=np.float64)

    mat     = data[:n_complete * N].reshape(n_complete, N).astype(np.float64)
    fft_mat = np.fft.rfft(mat, n=N, axis=1)
    bin_idx = np.round(FREQS * N / sr).astype(int)
    bin_idx = np.clip(bin_idx, 0, fft_mat.shape[1] - 1)
    energies = np.abs(fft_mat[:, bin_idx]) ** 2  # (n_syms, M)

    best_syms = np.argmax(energies, axis=1)
    hard_bits = np.empty(n_complete * BPS, dtype=np.uint8)
    for i, sym in enumerate(best_syms):
        hard_bits[i * BPS:(i + 1) * BPS] = _sym_to_bits(sym)

    # Per-bit LLRs via log-sum-exp partition over bin energies
    # LLR_k = log[sum_{s: bit_k(s)=0} E_s] - log[sum_{s: bit_k(s)=1} E_s]
    log_e = np.log(np.maximum(energies, 1e-30))  # (n_syms, M)
    llrs  = np.empty(n_complete * BPS, dtype=np.float64)

    for k in range(BPS):
        bit_pos   = BPS - 1 - k  # k=0 -> MSB -> bit_pos=BPS-1
        mask0     = np.array([(s >> bit_pos) & 1 == 0 for s in range(M)])
        lse0      = np.logaddexp.reduce(log_e[:, mask0],  axis=1)
        lse1      = np.logaddexp.reduce(log_e[:, ~mask0], axis=1)
        llrs[k::BPS] = lse0 - lse1

    return hard_bits, llrs


# ===========================================================================
# Sanity loopback check
# ===========================================================================
def sanity_loopback(n_bits: int = 4000) -> float:
    """modulate -> demodulate (NO channel). Returns BER — must be ~0."""
    rng  = np.random.default_rng(999)
    bits = rng.integers(0, 2, size=n_bits, dtype=np.uint8)
    audio = mfsk32_modulate(bits)
    hard_bits, _ = mfsk32_demodulate_soft(audio, SAMPLE_RATE)
    n    = min(n_bits, len(hard_bits))
    errs = int(np.count_nonzero(bits[:n] != hard_bits[:n]))
    errs += (n_bits - n)
    return errs / n_bits


# ===========================================================================
# FEC-coded MFSK-32 Scheme (punctured convolutional code)
# ===========================================================================
class SoftFECScheme:
    """MFSK-32 + soft-decoded punctured convolutional FEC.

    The scheme stores the payload size (n_data_bits) so the decoder knows
    exactly how many bits to recover (avoids pad-length ambiguity).

    gross_bps = payload_bits / audio_duration : FEC overhead is paid here.
    net_bps_soft = gross_bps * fec_rate      : assuming post-FEC BER ~ 0
                                                (so no outer code needed).
    """

    def __init__(self, punct_name: str, n_data_bits: int = 4000):
        entry = next(e for e in PUNCT_PATTERNS if e[0] == punct_name)
        self.punct_name  = punct_name
        self.punct_num   = entry[1]
        self.punct_den   = entry[2]
        self.punct_mask  = entry[3]
        self.fec_rate    = entry[1] / entry[2]
        self.n_data_bits = n_data_bits
        self.name        = f"C3_mfsk32_soft_r{punct_name.replace('/','_')}"
        self.erasure_fn  = None

    def _n_coded(self) -> int:
        """Full coded length for n_data_bits source bits (including flush)."""
        return 2 * (self.n_data_bits + K_CONV - 1)

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        bits   = np.asarray(bits, dtype=np.uint8)
        coded  = conv_encode(bits)
        punct  = apply_puncture(coded, self.punct_mask)
        # Pad to multiple of BPS for MFSK symbol packing
        pad = (BPS - len(punct) % BPS) % BPS
        if pad:
            punct = np.concatenate([punct, np.zeros(pad, dtype=np.uint8)])
        return mfsk32_modulate(punct)

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        _, llrs = mfsk32_demodulate_soft(audio, sr)
        if len(llrs) == 0:
            return np.zeros(self.n_data_bits, dtype=np.uint8)
        # Depuncture: restore full coded length from received LLRs
        n_coded = self._n_coded()
        depu    = depuncture(llrs, self.punct_mask, n_coded)
        # Soft Viterbi decode
        return soft_viterbi(depu, self.n_data_bits)

    @property
    def gross_bps(self) -> float:
        """Gross bps: payload_bits / audio_duration (FEC overhead paid)."""
        audio = self.modulate(np.zeros(self.n_data_bits, dtype=np.uint8))
        dur   = len(audio) / SAMPLE_RATE
        return self.n_data_bits / dur if dur > 0 else 0.0


# ===========================================================================
# BER helpers
# ===========================================================================
def _random_bits(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(10_000 + seed).integers(0, 2, size=n, dtype=np.uint8)


def _ber(tx: np.ndarray, rx: np.ndarray) -> float:
    n = len(tx)
    if n == 0:
        return 0.0
    m    = min(n, len(rx))
    errs = int(np.count_nonzero(tx[:m] != rx[:m])) if m else 0
    errs += (n - m)
    return errs / n


# ===========================================================================
# Measure raw (pre-FEC) MFSK-32 BER through channel
# ===========================================================================
def _measure_raw_ber_mfsk32(n_seeds: int = 16, payload_bits: int = 4000) -> float:
    bers = []
    for seed in range(n_seeds):
        tx = _random_bits(payload_bits, seed)
        audio = mfsk32_modulate(tx)
        rx_audio, sr, _ = cs.full_chain(audio, "normal", "usb_soundcard", seed=seed)
        hard_bits, _ = mfsk32_demodulate_soft(rx_audio, sr)
        bers.append(_ber(tx, hard_bits))
    return float(np.mean(bers))


# ===========================================================================
# Evaluate a single puncturing rate over Monte Carlo seeds
# ===========================================================================
def evaluate_rate(
    punct_name: str,
    n_seeds: int = 16,
    payload_bits: int = 4000,
    tape_preset: str = "normal",
) -> dict:
    scheme = SoftFECScheme(punct_name, n_data_bits=payload_bits)
    gross  = scheme.gross_bps

    bers = []
    for seed in range(n_seeds):
        tx = _random_bits(payload_bits, seed)
        audio    = scheme.modulate(tx)
        rx_audio, sr, _ = cs.full_chain(audio, tape_preset, "usb_soundcard", seed=seed)
        rx_bits  = scheme.demodulate(rx_audio, sr)
        bers.append(_ber(tx, rx_bits))

    mean_ber = float(np.mean(bers))
    p_full   = 1.0 if max(bers) == 0.0 else 0.0
    # net_bps_soft: payload bits / audio duration.
    # When post-FEC BER=0, no outer code is needed, so net=gross of this scheme.
    # gross already accounts for FEC overhead (longer audio = lower rate).
    # DO NOT multiply by fec_rate again — that would double-count the overhead.
    net_soft = gross  # = payload_bits / audio_duration

    return {
        "punct_name":   punct_name,
        "fec_rate":     scheme.fec_rate,
        "gross_bps":    gross,
        "net_bps_soft": net_soft,
        "post_fec_ber": mean_ber,
        "p_full":       p_full,
        "per_seed_ber": [float(b) for b in bers],
        "n_seeds":      n_seeds,
        "payload_bits": payload_bits,
    }


# ===========================================================================
# Main
# ===========================================================================
def main() -> dict:
    print("=" * 72)
    print("C3 — Soft-decision FEC credit for MFSK-32")
    print(f"MFSK-32 reference: gross={MFSK32_GROSS:.1f}, raw_ber={MFSK32_RAW_BER:.4e}, "
          f"net={MFSK32_NET:.1f}")
    print(f"Accept bar: {ACCEPT_BAR:.1f} bps (1.15x reference), P_full=1.0")
    print("=" * 72)

    # ------------------------------------------------------------------
    # Step 0: Sanity loopback (no channel)
    # ------------------------------------------------------------------
    print("\n[0] Sanity loopback (no channel) ...")
    sanity_ber = sanity_loopback(4000)
    print(f"    Loopback BER = {sanity_ber:.6f}  (must be ~0)")
    bug_flag = sanity_ber > 0.01

    # ------------------------------------------------------------------
    # Step 1: Measure raw MFSK-32 BER through channel
    # ------------------------------------------------------------------
    print("\n[1] Measuring raw (pre-FEC) MFSK-32 BER (n_seeds=16) ...")
    t0      = time.time()
    raw_ber = _measure_raw_ber_mfsk32(n_seeds=16, payload_bits=4000)
    print(f"    raw_ber = {raw_ber:.4e}  (reference: {MFSK32_RAW_BER:.4e})  ({time.time()-t0:.1f}s)")

    hard_proj = hc.project_to_cassette(raw_ber, 0.0, MFSK32_GROSS)
    print(f"    Hard-table: code_rate={hard_proj['required_code_rate']:.3f}, "
          f"net_bps={hard_proj['net_bps']:.1f}")

    # ------------------------------------------------------------------
    # Step 2: Fast sweep (n_seeds=8)
    # ------------------------------------------------------------------
    print("\n[2] Fast sweep over puncturing rates (n_seeds=8) ...")
    fast_results = []
    for pname, _, _, _ in PUNCT_PATTERNS:
        print(f"    Rate {pname} ...", end="", flush=True)
        t0  = time.time()
        res = evaluate_rate(pname, n_seeds=8, payload_bits=4000)
        flag = " P_full=1 *" if res["p_full"] == 1.0 else f" BER={res['post_fec_ber']:.2e}"
        print(f"  gross={res['gross_bps']:.0f}  net_soft={res['net_bps_soft']:.0f}"
              f"  fec_ber={res['post_fec_ber']:.2e}{flag}  ({time.time()-t0:.1f}s)")
        fast_results.append(res)

    # ------------------------------------------------------------------
    # Step 3: Confirm best candidate(s) at n_seeds=16
    # ------------------------------------------------------------------
    good_fast = [r for r in fast_results if r["p_full"] == 1.0]
    if good_fast:
        # Confirm ALL candidates that passed the fast sweep at P_full=1.0
        # (n=8 can miss bad seeds; we confirm all at n=16 to find the true knee)
        candidates = sorted(good_fast, key=lambda x: x["fec_rate"])
        print(f"\n[3] Fast: {len(candidates)} rate(s) had P_full=1; confirming all at n_seeds=16 ...")
    else:
        # No P_full=1 in fast sweep; confirm the two lowest BER
        candidates = sorted(fast_results, key=lambda x: x["post_fec_ber"])[:2]
        print(f"\n[3] No P_full=1 in fast sweep; confirming lowest-BER candidate(s) ...")

    confirmed = []
    for cand in candidates:
        pname = cand["punct_name"]
        print(f"    Rate {pname} (n_seeds=16) ...", end="", flush=True)
        t0  = time.time()
        res = evaluate_rate(pname, n_seeds=16, payload_bits=4000)
        flag = " P_full=1 *" if res["p_full"] == 1.0 else f" BER={res['post_fec_ber']:.2e}"
        print(f"  gross={res['gross_bps']:.0f}  net_soft={res['net_bps_soft']:.0f}"
              f"  fec_ber={res['post_fec_ber']:.2e}{flag}  ({time.time()-t0:.1f}s)")
        confirmed.append(res)

    # ------------------------------------------------------------------
    # Step 4: Pick best result
    # ------------------------------------------------------------------
    good_conf = [r for r in confirmed if r["p_full"] == 1.0]
    best      = max(good_conf, key=lambda x: x["net_bps_soft"]) if good_conf \
                else min(confirmed, key=lambda x: x["post_fec_ber"])

    ratio   = best["net_bps_soft"] / MFSK32_NET
    verdict = "ACCEPT" if (
        best["net_bps_soft"] >= ACCEPT_BAR and
        best["p_full"] == 1.0 and
        sanity_ber < 0.01
    ) else "REJECT"

    # ------------------------------------------------------------------
    # Step 5: Print summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("RESULTS SUMMARY")
    print(f"  Sanity loopback BER         = {sanity_ber:.6f}")
    print(f"  Raw MFSK-32 BER             = {raw_ber:.4e}")
    print(f"  Hard-table code rate        = {hard_proj['required_code_rate']:.3f}")
    print(f"  Hard-table net_bps (ref)    = {MFSK32_NET:.1f}")
    print(f"  Best soft FEC rate          = {best['punct_name']}  "
          f"(R={best['fec_rate']:.4f})")
    print(f"  gross_bps (FEC overhead pd) = {best['gross_bps']:.1f}")
    print(f"  Soft net_bps                = {best['net_bps_soft']:.1f}")
    print(f"  Post-FEC BER                = {best['post_fec_ber']:.2e}")
    print(f"  P_full                      = {best['p_full']:.2f}")
    print(f"  Ratio vs MFSK-32            = {ratio:.3f}x")
    print(f"  Accept bar                  = {ACCEPT_BAR:.1f} (1.15x ref)")
    print(f"\n  VERDICT: {verdict}")
    print("=" * 72)

    # ------------------------------------------------------------------
    # Step 6: Save results
    # ------------------------------------------------------------------
    results = {
        "hypothesis":              "C3_soft_fec",
        "verdict":                 verdict,
        "sanity_loopback_ber":     sanity_ber,
        "bug_suspected":           bug_flag,
        "mfsk32_raw_ber_measured": raw_ber,
        "mfsk32_raw_ber_reference": MFSK32_RAW_BER,
        "hard_table_code_rate":    hard_proj["required_code_rate"],
        "hard_net_bps":            hard_proj["net_bps"],
        "mfsk32_reference_net_bps": MFSK32_NET,
        "accept_bar":              ACCEPT_BAR,
        "best":                    best,
        "all_fast_results":        fast_results,
        "all_confirmed_results":   confirmed,
        "gross_bps_mfsk32_reference": MFSK32_GROSS,
        "ratio_vs_mfsk32":         ratio,
        "metadata": {
            "n_seeds_fast":    8,
            "n_seeds_confirm": 16,
            "payload_bits":    4000,
            "tape_preset":     "normal",
            "capture_key":     "usb_soundcard",
            "conv_code":       f"K={K_CONV} g1={G1:#o} g2={G2:#o}",
            "M_mfsk":          M,
        },
    }

    out_dir  = ROOT / "experiments" / "capacity" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "c3_soft_fec.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {out_path}")

    return results


if __name__ == "__main__":
    main()
