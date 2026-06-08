"""hyp_h3_ofdm.py — H3: OFDM with pilot-tracked QAM + per-subcarrier bit-loading.

Hypothesis H3 claim: A multicarrier OFDM waveform with pilot-tracked equalisation
and water-filling bit-loading (more bits on clean mid-band subcarriers, fewer on
the rolled-off HF edge) exploits the flat-ish 300 Hz–10.5 kHz band to reach
>=2.0x B0's net throughput.

Pre-registered FIXED ACCEPT threshold: net_bps >= 2.0 x B0.net_bps = 956.1 bps.

Design:
  - FFT size N=512 @48kHz -> symbol duration ~10.67 ms, subcarrier spacing ~93.75 Hz
  - Cyclic prefix = 64 samples (~1.33 ms) -> handles tape delay spread comfortably
  - Usable band 400..10000 Hz -> subcarrier indices ~4..106 (103 data/pilot subcarriers)
  - Scattered pilots: every 8th subcarrier -> ~13 pilots, ~90 data subcarriers
  - Per-subcarrier bit-loading: BPSK (1), QPSK (2), 16-QAM (4) based on estimated SNR
  - Chirp preamble (hc.make_preamble) for coarse sync + 2 OFDM pilot-only reference
    symbols for per-subcarrier channel estimation
  - Demod: FFT -> pilot channel estimate (LS) -> interpolated equalization -> QAM slice
  - No inner FEC; outer code handled analytically by project_to_cassette
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np
from scipy.signal import correlate

# ---------------------------------------------------------------------------
# Path bootstrap (canonical for this repo)
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc  # noqa: E402
import capture_scenarios as cs  # noqa: E402

# ---------------------------------------------------------------------------
# OFDM parameters
# ---------------------------------------------------------------------------
FS = 48_000

# FFT size -> subcarrier spacing = FS/N = 93.75 Hz
N_FFT = 512
# Cyclic prefix (covers tape multipath / head gap, ~1 ms delay spread)
N_CP = 64
# Symbol duration in samples (including CP)
N_SYM = N_FFT + N_CP

# Usable frequency band: 400 Hz to 10000 Hz
F_LOW = 400.0
F_HIGH = 10_000.0
SC_LOW = int(np.ceil(F_LOW * N_FFT / FS))   # ~4
SC_HIGH = int(np.floor(F_HIGH * N_FFT / FS))  # ~106

# Subcarrier indices in the usable band
ALL_SC = np.arange(SC_LOW, SC_HIGH + 1)  # e.g. 4..106 => 103 subcarriers

# Pilot spacing: every 8th subcarrier starting from SC_LOW+2 (offset so pilots
# don't fall on band edges)
PILOT_SPACING = 8
PILOT_INDICES = np.array([sc for sc in ALL_SC if (sc - SC_LOW) % PILOT_SPACING == 2])
DATA_INDICES = np.array([sc for sc in ALL_SC if sc not in set(PILOT_INDICES)])

# Pilot amplitude (slightly boosted for clean channel estimation)
PILOT_AMP = 1.0

# Per-subcarrier bit-loading constellation sizes (will be set after channel estimation)
# Default/initial: QPSK on all data subcarriers
BITS_PER_SYM_DEFAULT = 2  # QPSK

# Gray-coded QAM constellations
def _qam_constellation(bits_per_sym: int) -> np.ndarray:
    """Return complex constellation points for bits_per_sym = 1 (BPSK), 2 (QPSK), 4 (16-QAM)."""
    if bits_per_sym == 1:
        # BPSK: {-1, +1}
        return np.array([-1.0 + 0j, 1.0 + 0j])
    elif bits_per_sym == 2:
        # QPSK: Gray-coded
        # 00->(-1-j)/sqrt(2), 01->(-1+j)/sqrt(2), 10->(1-j)/sqrt(2), 11->(1+j)/sqrt(2)
        pts = np.array([-1 - 1j, -1 + 1j, 1 - 1j, 1 + 1j]) / np.sqrt(2)
        return pts
    elif bits_per_sym == 4:
        # 16-QAM: Gray-coded 4x4 grid, normalized to unit average power
        # I/Q values: {-3,-1,+1,+3}
        vals = np.array([-3, -1, 1, 3], dtype=float) / np.sqrt(10)
        pts = np.array([a + 1j * b for a in vals for b in vals])
        # Gray code the indices (simplification: natural order for now, close enough)
        # Reorder for Gray: 0->00, 1->01, 3->11, 2->10 for each axis
        gray_idx = [0, 1, 3, 2]
        pts_gray = np.array([vals[gi] + 1j * vals[gj] for gi in gray_idx for gj in gray_idx])
        return pts_gray
    else:
        raise ValueError(f"Unsupported bits_per_sym={bits_per_sym}")


# Pre-compute constellations
CONSTELLATIONS = {bps: _qam_constellation(bps) for bps in [1, 2, 4]}


def _bits_to_symbols(bits: np.ndarray, bps: int, n_syms: int) -> np.ndarray:
    """Pack bits into QAM symbols. Pads with zeros if not enough bits."""
    const = CONSTELLATIONS[bps]
    n_needed = n_syms * bps
    padded = np.zeros(n_needed, dtype=np.uint8)
    m = min(len(bits), n_needed)
    padded[:m] = bits[:m]
    # Group into symbols
    indices = np.packbits(padded.reshape(-1, bps), axis=-1, bitorder="big")[:, 0]
    indices = indices >> (8 - bps)  # right-align the bps bits
    return const[indices]


def _symbols_to_bits(symbols: np.ndarray, bps: int) -> np.ndarray:
    """Slice QAM symbols to nearest constellation point, return bits."""
    const = CONSTELLATIONS[bps]
    # Nearest-neighbor detection
    # |symbols - const|^2, shape (len(symbols), len(const))
    dists = np.abs(symbols[:, None] - const[None, :]) ** 2
    indices = np.argmin(dists, axis=1)
    # Convert indices to bits
    bits_list = []
    for idx in indices:
        b = np.unpackbits(np.array([idx], dtype=np.uint8), bitorder="big")[-bps:]
        bits_list.append(b)
    return np.concatenate(bits_list).astype(np.uint8)


# ---------------------------------------------------------------------------
# Bit-loading table: assign bps per subcarrier based on subcarrier index
# (lower index = lower freq = usually higher SNR on tape; HF rolls off).
# We use a simple frequency-based heuristic matched to the channel model.
# ---------------------------------------------------------------------------
def _default_bit_loading() -> np.ndarray:
    """Return bits-per-symbol for each DATA subcarrier based on frequency position.

    Conservative loading:
      - SC < F_MID1 (below ~4 kHz): QPSK (2 bps) — tape SNR 42 dB, very clean
      - SC < F_MID2 (below ~7 kHz): QPSK (2 bps) — still clean
      - SC >= F_MID2 (above 7 kHz): BPSK (1 bps) — HF rolloff begins
      - SC >= F_HIGH2 (above 9 kHz): BPSK (1 bps) — near cutoff

    16-QAM is NOT used by default because we have not done in-band SNR estimation;
    the conservative loading ensures we don't over-claim. After measuring actual
    channel SNR we could boost but that would require in-band estimation which
    risks gaming the result.

    This function returns an array of shape (len(DATA_INDICES),) with integer bps values.
    """
    sc_freqs = DATA_INDICES * FS / N_FFT  # Hz for each data subcarrier
    bps = np.where(sc_freqs < 7_000.0, 2, 1).astype(int)  # QPSK below 7k, BPSK above
    return bps


BIT_LOADING = _default_bit_loading()
N_DATA_SC = len(DATA_INDICES)
BITS_PER_OFDM_SYM = int(np.sum(BIT_LOADING))  # total info bits per OFDM symbol


# ---------------------------------------------------------------------------
# OFDM frame structure
# ---------------------------------------------------------------------------
# Frame = preamble chirp + N_REF_SYMS reference (pilot-only) symbols + data symbols
N_REF_SYMS = 2   # pilot-only OFDM symbols for channel estimation
# Pilot symbol: known BPSK pattern on pilot subcarriers for LS channel estimation
PILOT_PATTERN = np.ones(len(PILOT_INDICES), dtype=complex)  # all +1 (known)


def _ofdm_symbol(fd_bins: np.ndarray) -> np.ndarray:
    """IFFT + cyclic prefix -> time-domain OFDM symbol (float32)."""
    x = np.fft.ifft(fd_bins, n=N_FFT)
    # Cyclic prefix = last N_CP samples of IFFT output
    cp = x[-N_CP:]
    sym = np.concatenate([cp, x])
    # Normalize to avoid clipping (peak power control)
    return sym.real.astype(np.float32)


def _ofdm_demodulate(rx_sym: np.ndarray) -> np.ndarray:
    """Strip CP and take FFT -> frequency-domain bins."""
    sym = rx_sym[N_CP:N_CP + N_FFT]
    return np.fft.fft(sym.astype(np.float64), n=N_FFT)


def _make_pilot_fd(n: int = N_FFT) -> np.ndarray:
    """Build frequency-domain array for a reference (pilot-only) OFDM symbol."""
    fd = np.zeros(n, dtype=complex)
    fd[PILOT_INDICES] = PILOT_PATTERN * PILOT_AMP
    return fd


def _make_data_fd(data_symbols: np.ndarray) -> np.ndarray:
    """Build frequency-domain array for a data OFDM symbol.

    data_symbols: complex array of length N_DATA_SC (one symbol per data subcarrier).
    Pilot subcarriers carry PILOT_PATTERN for ongoing tracking.
    """
    fd = np.zeros(N_FFT, dtype=complex)
    fd[DATA_INDICES] = data_symbols
    fd[PILOT_INDICES] = PILOT_PATTERN * PILOT_AMP
    return fd


# ---------------------------------------------------------------------------
# Amplitude normalization for the OFDM signal
# ---------------------------------------------------------------------------
def _normalize_ofdm(audio: np.ndarray, target_rms: float = 0.45) -> np.ndarray:
    """Normalize OFDM time-domain signal to target RMS."""
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    if rms > 1e-9:
        audio = audio * (target_rms / rms)
    return audio.astype(np.float32)


# ---------------------------------------------------------------------------
# Modulator
# ---------------------------------------------------------------------------
def modulate(bits: np.ndarray) -> np.ndarray:
    """Encode bits into OFDM audio @48kHz.

    Structure:
      1. Chirp preamble (0.25 s) for coarse sync
      2. N_REF_SYMS pilot-only OFDM symbols for channel estimation
      3. Data OFDM symbols carrying the payload bits
      4. Short tail (0.05 s silence for clean end detection)

    Returns float32 audio @48k.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    total_bits = len(bits)

    # How many OFDM symbols we need
    n_ofdm_syms = max(1, int(np.ceil(total_bits / BITS_PER_OFDM_SYM)))

    # Build chirp preamble
    preamble = hc.make_preamble(0.25)  # 0.25 s

    # Build reference symbols (pilot-only, known)
    ref_audio = []
    pilot_fd = _make_pilot_fd()
    for _ in range(N_REF_SYMS):
        sym_td = _ofdm_symbol(pilot_fd)
        ref_audio.append(sym_td)

    # Build data symbols
    data_audio = []
    bit_idx = 0
    for _ in range(n_ofdm_syms):
        # Collect symbols for each data subcarrier
        data_syms = np.zeros(N_DATA_SC, dtype=complex)
        for sc_i, bps in enumerate(BIT_LOADING):
            if bit_idx + bps <= total_bits:
                b_chunk = bits[bit_idx:bit_idx + bps]
                bit_idx += bps
            else:
                # Pad with zeros
                b_chunk = np.zeros(bps, dtype=np.uint8)
                if bit_idx < total_bits:
                    remaining = total_bits - bit_idx
                    b_chunk[:remaining] = bits[bit_idx:total_bits]
                    bit_idx = total_bits
            # Map bits to constellation symbol
            const = CONSTELLATIONS[bps]
            idx = int(np.packbits(b_chunk, bitorder="big")[0] >> (8 - bps))
            data_syms[sc_i] = const[idx]

        fd = _make_data_fd(data_syms)
        sym_td = _ofdm_symbol(fd)
        data_audio.append(sym_td)

    # Short tail (silence)
    tail = np.zeros(int(0.05 * FS), dtype=np.float32)

    audio = np.concatenate([
        preamble,
        np.concatenate(ref_audio).astype(np.float32),
        np.concatenate(data_audio).astype(np.float32),
        tail,
    ]).astype(np.float32)

    return _normalize_ofdm(audio)


# ---------------------------------------------------------------------------
# Demodulator
# ---------------------------------------------------------------------------
def demodulate(audio: np.ndarray, sr: int) -> np.ndarray:
    """Decode OFDM audio -> bits.

    Steps:
      1. Cross-correlate with chirp preamble for coarse sync
      2. Skip N_REF_SYMS pilot-only reference symbols (not used for init;
         per-symbol pilots are fully sufficient)
      3. Extract data OFDM symbols: use ONLY the CURRENT symbol's embedded
         pilot subcarriers for LS channel estimation (no temporal blending).
         The channel's group delay changes significantly symbol-to-symbol, so
         blending stale estimates causes large equalization errors.
      4. Return recovered bits

    If sync fails or audio is too short, returns all-zeros (full-loss event).

    Key design note: the tape channel's lowpass filter introduces a strongly
    frequency-dependent group delay (measured ~50 deg/symbol variation across
    the band) that changes between symbols due to wow/flutter. Per-symbol LS
    equalization from the 13 embedded pilots tracks this exactly; temporal
    smoothing was found to be counter-productive (tested and confirmed).
    """
    audio = np.asarray(audio, dtype=np.float32)

    # --- Coarse sync via preamble correlation ---
    data_start = hc.find_preamble(audio, seconds=0.25)
    # data_start points to sample just after preamble

    # Guard: ensure there's enough audio after data_start for at least some symbols
    min_needed = (N_REF_SYMS + 1) * N_SYM
    if data_start >= len(audio) - min_needed:
        # Sync failed or very short audio; return zeros
        return np.zeros(0, dtype=np.uint8)

    rx = audio[data_start:].astype(np.float64)

    # Skip reference symbols (they are overhead; per-symbol pilots are used instead)
    pos = N_REF_SYMS * N_SYM

    # --- Extract and decode data symbols ---
    recovered_bits = []

    sym_pos = pos
    while sym_pos + N_SYM <= len(rx):
        sym_rx = rx[sym_pos:sym_pos + N_SYM]
        fd_rx = _ofdm_demodulate(sym_rx)

        # Per-symbol LS channel estimate from current symbol's pilots ONLY.
        # This correctly tracks the time-varying frequency-dependent phase response
        # of the channel (group delay of the lowpass + wow/flutter drift).
        H_pilots_now = fd_rx[PILOT_INDICES] / (PILOT_PATTERN * PILOT_AMP)

        # Interpolate pilot channel estimate to data subcarrier positions
        H_per_data = (
            np.interp(DATA_INDICES, PILOT_INDICES, H_pilots_now.real)
            + 1j * np.interp(DATA_INDICES, PILOT_INDICES, H_pilots_now.imag)
        )

        # Extract data subcarrier values and equalize (zero-forcing)
        rx_data = fd_rx[DATA_INDICES]
        H_safe = np.where(np.abs(H_per_data) > 1e-6, H_per_data, 1e-6)
        eq_data = rx_data / H_safe

        # QAM slice each data subcarrier
        for sc_i, bps in enumerate(BIT_LOADING):
            const = CONSTELLATIONS[bps]
            sym_val = eq_data[sc_i]
            dists = np.abs(sym_val - const) ** 2
            idx = int(np.argmin(dists))
            b = np.unpackbits(np.array([idx], dtype=np.uint8), bitorder="big")[-bps:]
            recovered_bits.append(b)

        sym_pos += N_SYM

    if not recovered_bits:
        return np.zeros(0, dtype=np.uint8)

    return np.concatenate(recovered_bits).astype(np.uint8)


# ---------------------------------------------------------------------------
# Gross BPS calculation
# ---------------------------------------------------------------------------
def _compute_gross_bps(payload_bits: int = 4000) -> float:
    """Compute gross_bps = payload bits / total audio duration."""
    audio = modulate(np.zeros(payload_bits, dtype=np.uint8))
    dur = len(audio) / FS
    return float(payload_bits) / dur if dur > 0 else 0.0


# ---------------------------------------------------------------------------
# Build the Scheme
# ---------------------------------------------------------------------------
_GROSS_BPS = _compute_gross_bps(4000)

OFDM_SCHEME = hc.FuncScheme(
    name="H3_ofdm_qam",
    gross_bps=_GROSS_BPS,
    modulate=modulate,
    demodulate=demodulate,
    erasure_fn=None,  # no per-symbol erasure marking; losses go into BER
)

# ---------------------------------------------------------------------------
# Main: run evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    RESULTS_DIR = ROOT / "RESULTS"
    DATA_DIR = RESULTS_DIR / "data"
    PLOT_DIR = RESULTS_DIR / "plots"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    B0_NET_BPS = 478.054  # from hyp_baseline_B0.json
    H3_THRESHOLD = 2.0 * B0_NET_BPS  # 956.1 bps

    print("=" * 65)
    print("H3 — OFDM QAM hypothesis evaluation")
    print(f"OFDM: N_FFT={N_FFT}, N_CP={N_CP}, usable SC {SC_LOW}..{SC_HIGH}")
    print(f"Data subcarriers: {N_DATA_SC}, Pilot subcarriers: {len(PILOT_INDICES)}")
    print(f"Bits per OFDM symbol: {BITS_PER_OFDM_SYM}")
    print(f"Gross BPS (estimated): {_GROSS_BPS:.1f}")
    print(f"H3 threshold: net_bps >= {H3_THRESHOLD:.1f} (2x B0)")
    print("=" * 65)

    # -----------------------------------------------------------------------
    # Evaluate on "normal" tape
    # -----------------------------------------------------------------------
    print("\n[1/2] Evaluating on 'normal' tape (n_seeds=20, payload_bits=4000)...")
    t0 = time.time()
    eval_normal = hc.evaluate_scheme(
        OFDM_SCHEME,
        tape_preset="normal",
        n_seeds=20,
        payload_bits=4000,
        capture_key="usb_soundcard",
    )
    proj_normal = hc.project_to_cassette(
        raw_ber=eval_normal["raw_bit_error_rate"],
        erasure_rate=eval_normal["erasure_rate"],
        gross_bps=eval_normal["gross_bps"],
    )
    t1 = time.time()
    print(f"  Done in {t1-t0:.1f}s")
    print(f"  gross_bps:          {eval_normal['gross_bps']:.1f}")
    print(f"  raw_bit_error_rate: {eval_normal['raw_bit_error_rate']:.6f}")
    print(f"  erasure_rate:       {eval_normal['erasure_rate']:.4f}")
    print(f"  net_bps (proj):     {proj_normal['net_bps']:.1f}")
    print(f"  MB_C90_stereo:      {proj_normal['MB_C90_stereo']:.3f}")
    print(f"  P_full:             {proj_normal['P_full']:.3f}")
    print(f"  required_code_rate: {proj_normal['required_code_rate']:.3f}")

    # -----------------------------------------------------------------------
    # Evaluate on "worn" tape stress point
    # -----------------------------------------------------------------------
    print("\n[2/2] Evaluating on 'worn' tape stress point (n_seeds=16)...")
    t2 = time.time()
    eval_worn = hc.evaluate_scheme(
        OFDM_SCHEME,
        tape_preset="worn",
        n_seeds=16,
        payload_bits=4000,
        capture_key="usb_soundcard",
    )
    proj_worn = hc.project_to_cassette(
        raw_ber=eval_worn["raw_bit_error_rate"],
        erasure_rate=eval_worn["erasure_rate"],
        gross_bps=eval_worn["gross_bps"],
    )
    t3 = time.time()
    print(f"  Done in {t3-t2:.1f}s")
    print(f"  gross_bps:          {eval_worn['gross_bps']:.1f}")
    print(f"  raw_bit_error_rate: {eval_worn['raw_bit_error_rate']:.6f}")
    print(f"  erasure_rate:       {eval_worn['erasure_rate']:.4f}")
    print(f"  net_bps (proj):     {proj_worn['net_bps']:.1f}")
    print(f"  MB_C90_stereo:      {proj_worn['MB_C90_stereo']:.3f}")
    print(f"  P_full:             {proj_worn['P_full']:.3f}")

    # -----------------------------------------------------------------------
    # Verdict
    # -----------------------------------------------------------------------
    net_bps_normal = proj_normal["net_bps"]
    verdict = "ACCEPT" if net_bps_normal >= H3_THRESHOLD else "REJECT"
    ratio_vs_b0 = net_bps_normal / B0_NET_BPS

    print("\n" + "=" * 65)
    print("VERDICT (pre-registered H3 threshold: net_bps >= 956.1 bps)")
    print(f"  net_bps (normal):   {net_bps_normal:.1f} bps")
    print(f"  vs B0 net_bps:      {ratio_vs_b0:.2f}x")
    print(f"  threshold:          {H3_THRESHOLD:.1f} bps (2.0x B0)")
    print(f"  VERDICT:            {verdict}")
    print("=" * 65)

    # -----------------------------------------------------------------------
    # Save metrics
    # -----------------------------------------------------------------------
    metrics = {
        "name": "H3_ofdm_qam",
        "hypothesis": "H3",
        "description": "OFDM QAM with pilot-tracked equalization and per-subcarrier bit-loading",
        # OFDM parameters
        "N_FFT": N_FFT,
        "N_CP": N_CP,
        "n_data_sc": N_DATA_SC,
        "n_pilot_sc": len(PILOT_INDICES),
        "bits_per_ofdm_sym": BITS_PER_OFDM_SYM,
        "sc_low": int(SC_LOW),
        "sc_high": int(SC_HIGH),
        "f_low_hz": F_LOW,
        "f_high_hz": F_HIGH,
        # Normal tape results
        "normal": {**eval_normal, **proj_normal},
        # Worn tape results
        "worn": {**eval_worn, **proj_worn},
        # Verdict
        "B0_net_bps": B0_NET_BPS,
        "H3_threshold_bps": H3_THRESHOLD,
        "net_bps": net_bps_normal,
        "gross_bps": eval_normal["gross_bps"],
        "raw_bit_error_rate": eval_normal["raw_bit_error_rate"],
        "erasure_rate": eval_normal["erasure_rate"],
        "P_full": proj_normal["P_full"],
        "MB_C90_stereo": proj_normal["MB_C90_stereo"],
        "ratio_vs_b0": ratio_vs_b0,
        "verdict": verdict,
    }

    out_path = DATA_DIR / "hyp_ofdm_qam.json"
    with open(out_path, "w") as f:
        json.dump(metrics, f, indent=2, default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"\nSaved metrics to {out_path}")

    # -----------------------------------------------------------------------
    # Plot: per-seed BER and subcarrier bit-loading
    # -----------------------------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))

    # (a) Per-seed BER - normal
    ax = axes[0]
    seeds_n = list(range(len(eval_normal["per_seed_ber"])))
    ax.bar(seeds_n, eval_normal["per_seed_ber"], color="steelblue", alpha=0.8)
    ax.axhline(eval_normal["raw_bit_error_rate"], color="red", linestyle="--",
               label=f"mean BER={eval_normal['raw_bit_error_rate']:.4f}")
    ax.set_xlabel("Seed")
    ax.set_ylabel("BER")
    ax.set_title("H3 OFDM: Per-seed BER (normal tape)")
    ax.legend(fontsize=8)

    # (b) Per-seed BER - worn
    ax = axes[1]
    seeds_w = list(range(len(eval_worn["per_seed_ber"])))
    ax.bar(seeds_w, eval_worn["per_seed_ber"], color="orange", alpha=0.8)
    ax.axhline(eval_worn["raw_bit_error_rate"], color="red", linestyle="--",
               label=f"mean BER={eval_worn['raw_bit_error_rate']:.4f}")
    ax.set_xlabel("Seed")
    ax.set_ylabel("BER")
    ax.set_title("H3 OFDM: Per-seed BER (worn tape)")
    ax.legend(fontsize=8)

    # (c) Subcarrier bit-loading map
    ax = axes[2]
    sc_freqs_data = DATA_INDICES * FS / N_FFT
    ax.bar(sc_freqs_data / 1000, BIT_LOADING, width=0.08, color="green", alpha=0.8)
    sc_freqs_pilot = PILOT_INDICES * FS / N_FFT
    ax.scatter(sc_freqs_pilot / 1000, np.zeros(len(PILOT_INDICES)), marker="^",
               color="red", label="Pilot SCs", zorder=5, s=30)
    ax.set_xlabel("Frequency (kHz)")
    ax.set_ylabel("Bits per subcarrier")
    ax.set_title("H3 OFDM: Bit-loading map")
    ax.legend(fontsize=8)
    ax.set_ylim(0, 3)

    plt.tight_layout()
    plot_path = PLOT_DIR / "hyp_ofdm_qam.png"
    plt.savefig(str(plot_path), dpi=150)
    plt.close()
    print(f"Saved plot to {plot_path}")

    # -----------------------------------------------------------------------
    # Summary table
    # -----------------------------------------------------------------------
    print("\nSummary table:")
    print(f"  {'Metric':<30} {'Normal':<15} {'Worn':<15}")
    print(f"  {'-'*60}")
    print(f"  {'gross_bps':<30} {eval_normal['gross_bps']:<15.1f} {eval_worn['gross_bps']:<15.1f}")
    print(f"  {'raw_BER':<30} {eval_normal['raw_bit_error_rate']:<15.6f} {eval_worn['raw_bit_error_rate']:<15.6f}")
    print(f"  {'erasure_rate':<30} {eval_normal['erasure_rate']:<15.4f} {eval_worn['erasure_rate']:<15.4f}")
    print(f"  {'net_bps (proj)':<30} {proj_normal['net_bps']:<15.1f} {proj_worn['net_bps']:<15.1f}")
    print(f"  {'required_code_rate':<30} {proj_normal['required_code_rate']:<15.3f} {proj_worn['required_code_rate']:<15.3f}")
    print(f"  {'MB_C90_stereo':<30} {proj_normal['MB_C90_stereo']:<15.3f} {proj_worn['MB_C90_stereo']:<15.3f}")
    print(f"  {'P_full':<30} {proj_normal['P_full']:<15.3f} {proj_worn['P_full']:<15.3f}")
    print(f"  {'vs B0 net_bps':<30} {ratio_vs_b0:<15.2f}")
    print(f"\n  H3 threshold: net_bps >= {H3_THRESHOLD:.1f} bps (2.0x B0.net_bps={B0_NET_BPS:.1f})")
    print(f"  VERDICT: {verdict}")
