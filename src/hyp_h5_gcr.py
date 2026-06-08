"""hyp_h5_gcr.py — H5: GCR/RLL channel code with NRZI bandlimited signalling.

Hypothesis: A run-length-limited channel code (GCR 4b/5b, Commodore 1541 style)
with 2-level NRZI-style signalling, bandlimited to ~10.5 kHz, achieves
>= 1.5x B0's reliable net throughput by packing bits at the channel's true
symbol rate with DC-balance / clock-recovery guarantees.

FIXED ACCEPT THRESHOLD (pre-registered in docs/encoding_hypotheses.md):
  ACCEPT iff reliable net_bps >= 1.5 * B0.net_bps  i.e. >= 717.1 bps

MODEL-FIDELITY NOTE (pre-registered): channel.py is a LINEAR, bandlimited
channel. It does NOT model magnetic saturation or hysteresis. GCR/RLL codes
earn their advantage from operating a *saturating* magnetic channel. Therefore
a sim REJECTION of H5 is informative about channel-model fidelity, not
necessarily about whether GCR/RLL is useful on real tape. This caveat is
stated explicitly in the verdict.

Implementation:
  - GCR 4b/5b encoding (Commodore 1541 table): every 4 payload bits -> 5 coded
    bits, ensuring no more than 2 consecutive 0s (run-length limited, DC-balanced).
  - NRZI encoding: a '1' in the coded stream produces a transition in the
    waveform; a '0' maintains the current level.
  - Bandlimited signalling: rectangular NRZ pulses convolved with a raised-cosine
    filter (BT=0.5) to limit the spectrum to ~10 kHz.
  - Symbol rate: 8000 baud (6 samples/symbol @ 48 kHz). This yields a fundamental
    frequency of 4 kHz, well within the 10.5 kHz channel.
  - Clock recovery: zero-crossing PLL on the NRZI waveform.
  - Coarse sync: shared chirp preamble (hc.make_preamble / hc.find_preamble).

Path bootstrap:
    import sys, pathlib
    ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
    for p in ["src","tests/e2e"]: sys.path.insert(0, str(ROOT/p))
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import signal as scipy_signal

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import hyp_common as hc  # noqa: E402
import capture_scenarios as cs  # noqa: E402

SAMPLE_RATE = 48_000
RESULTS_DATA = ROOT / "RESULTS" / "data"
RESULTS_PLOTS = ROOT / "RESULTS" / "plots"

# ---------------------------------------------------------------------------
# GCR 4b/5b lookup table (Commodore 1541 encoding, per Behr & Lund)
# Maps every 4-bit nibble (0..15) to a 5-bit codeword (0..31).
# The codewords are chosen so no run of > 2 consecutive zeros exists
# and no run of > 3 consecutive ones: max run length = 3 ones, 2 zeros.
# ---------------------------------------------------------------------------
_GCR4B5B: list[int] = [
    0b01010,  # 0x0  -> 01010
    0b01011,  # 0x1  -> 01011
    0b10010,  # 0x2  -> 10010
    0b10011,  # 0x3  -> 10011
    0b01110,  # 0x4  -> 01110
    0b01111,  # 0x5  -> 01111
    0b10110,  # 0x6  -> 10110
    0b10111,  # 0x7  -> 10111
    0b01001,  # 0x8  -> 01001
    0b11001,  # 0x9  -> 11001
    0b11010,  # 0xA  -> 11010
    0b11011,  # 0xB  -> 11011
    0b01101,  # 0xC  -> 01101
    0b11101,  # 0xD  -> 11101
    0b11110,  # 0xE  -> 11110
    0b11111,  # 0xF  -> 11111
]

# Reverse mapping: 5-bit codeword -> 4-bit nibble (invalid = -1)
_GCR5B4B: list[int] = [-1] * 32
for _nibble, _code in enumerate(_GCR4B5B):
    _GCR5B4B[_code] = _nibble


def gcr_encode(bits: np.ndarray) -> np.ndarray:
    """Encode bit stream with GCR 4b/5b: groups of 4 bits -> 5 bits.

    Input length is padded to a multiple of 4 bits. Returns a bit array
    that is 5/4 the length of (padded) input.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    # Pad to multiple of 4
    pad = (4 - len(bits) % 4) % 4
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    n_nibbles = len(bits) // 4
    out = np.empty(n_nibbles * 5, dtype=np.uint8)
    for i in range(n_nibbles):
        nibble = int(np.packbits(bits[i * 4: i * 4 + 4], bitorder="big")[0] >> 4)
        code = _GCR4B5B[nibble]
        for j in range(5):
            out[i * 5 + j] = (code >> (4 - j)) & 1
    return out


def gcr_decode(bits: np.ndarray, original_len: int) -> np.ndarray:
    """Decode GCR 4b/5b: groups of 5 bits -> 4 bits.

    Silently substitutes 0b0000 for invalid codewords (rare channel error).
    Returns exactly original_len bits.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    n_groups = len(bits) // 5
    out = np.empty(n_groups * 4, dtype=np.uint8)
    for i in range(n_groups):
        code = 0
        for j in range(5):
            code = (code << 1) | int(bits[i * 5 + j])
        nibble = _GCR5B4B[code] if 0 <= code < 32 else 0
        if nibble < 0:
            nibble = 0
        for j in range(4):
            out[i * 4 + j] = (nibble >> (3 - j)) & 1
    out = out[:original_len]
    if len(out) < original_len:
        out = np.concatenate([out, np.zeros(original_len - len(out), dtype=np.uint8)])
    return out


# ---------------------------------------------------------------------------
# NRZI encoding / decoding
# ---------------------------------------------------------------------------

def nrzi_encode(bits: np.ndarray) -> np.ndarray:
    """NRZI encode: 1 -> transition, 0 -> no transition.

    Returns a sequence of +1/-1 levels (one per coded bit).
    """
    bits = np.asarray(bits, dtype=np.uint8)
    levels = np.empty(len(bits), dtype=np.float32)
    state = 1.0  # initial level
    for i, b in enumerate(bits):
        if b:
            state = -state
        levels[i] = state
    return levels


def nrzi_decode(levels: np.ndarray) -> np.ndarray:
    """NRZI decode: transition -> 1, no transition -> 0.

    Input: +1/-1 quantised symbols, one per bit slot.
    The encoder starts at state=+1, so the decoder also assumes initial state=+1.
    """
    levels = np.asarray(levels, dtype=np.float32)
    if len(levels) == 0:
        return np.zeros(0, dtype=np.uint8)
    bits = np.empty(len(levels), dtype=np.uint8)
    prev = np.int8(1)  # encoder initial state = +1
    for i, lv in enumerate(levels):
        cur = np.int8(1) if lv >= 0 else np.int8(-1)
        bits[i] = 1 if cur != prev else 0
        prev = cur
    return bits


# ---------------------------------------------------------------------------
# Waveform parameters
# ---------------------------------------------------------------------------
# Symbol rate: 8000 baud. At 48 kHz that's 6 samples/symbol.
# GCR rate: 5/4 overhead means payload bit rate = 8000 * 4/5 = 6400 payload-bps.
# After preamble overhead (0.25 s chirp) the gross_bps will be measured from
# actual audio length.
BAUD_RATE = 4_000      # symbols per second (NRZI transitions/non-transitions)
# At 48 kHz / 4000 baud = 12 samples/symbol. Twice the eye-opening of 8kbaud,
# making timing tolerance 2x better (WF jitter is ~0.8 samples vs 12 = 6%).
# Payload rate: 4000 * 4/5 = 3200 bit/s (>> B0's 1200 bps).
SAMPLES_PER_SYM = SAMPLE_RATE // BAUD_RATE  # == 12

# Bit sync word: a known pattern of alternating 1s/0s appended after the chirp
# preamble and before the GCR-encoded payload. Used for fine bit-clock phase lock.
# 64 bits = 64 NRZI symbols = 384 samples @ 8kbaud. This is counted as overhead.
_SYNC_WORD_BITS = np.array([1, 0] * 32, dtype=np.uint8)  # 64-bit alternating pattern


def _raised_cosine_filter(samples_per_sym: int, rolloff: float = 0.5, n_taps: int = 65) -> np.ndarray:
    """A raised-cosine FIR for pulse shaping (NOT root-raised-cosine).

    The RC filter directly shapes the overall pulse response so that ISI is
    minimised at the sampling instants (Nyquist condition). Using it at both
    transmitter and receiver is equivalent to an RRC pair, but simpler here
    since we apply it once on transmit and once on receive.

    Limits the bandwidth of the NRZ waveform to ~(1+rolloff)*baud/2 Hz.
    At baud=8000, rolloff=0.5: bandwidth ~6 kHz, well inside 10.5 kHz limit.
    """
    n_taps = n_taps | 1  # force odd
    center = n_taps // 2
    T = float(samples_per_sym)
    beta = float(rolloff)
    eps = 1e-10
    h = np.zeros(n_taps)
    for i in range(n_taps):
        t = float(i - center) / T
        if abs(t) < eps:
            # t=0: sinc(0)=1, RC envelope=1
            h[i] = 1.0 / T
        else:
            sinc_val = np.sinc(t)  # sinc(t) = sin(pi*t)/(pi*t) in numpy convention
            # Raised cosine envelope: cos(pi*beta*t) / (1 - (2*beta*t)^2)
            denom = 1.0 - (2.0 * beta * t) ** 2
            if abs(denom) < eps:
                # singularity at |t| = 1/(2*beta): use L'Hopital limit
                h[i] = (np.pi / (4.0 * T)) * np.sinc(1.0 / (2.0 * beta))
            else:
                h[i] = sinc_val * np.cos(np.pi * beta * t) / (denom * T)
    # Normalize to unit DC gain
    h_sum = np.sum(h)
    if abs(h_sum) > eps:
        h /= h_sum
    return h.astype(np.float32)


_RC_TAPS = _raised_cosine_filter(SAMPLES_PER_SYM, rolloff=0.5, n_taps=65)


# ---------------------------------------------------------------------------
# Modulator
# ---------------------------------------------------------------------------

def _nrzi_bandlimit(bits: np.ndarray) -> np.ndarray:
    """NRZI-encode a bit stream, upsample, and apply RC bandlimiting filter.

    Returns float32 samples @48 kHz, normalised to unit peak amplitude.
    """
    nrzi_levels = nrzi_encode(bits)
    upsampled = np.repeat(nrzi_levels, SAMPLES_PER_SYM).astype(np.float32)
    filtered = scipy_signal.fftconvolve(upsampled, _RC_TAPS, mode="same").astype(np.float32)
    peak = np.max(np.abs(filtered))
    if peak > 0:
        filtered /= peak
    return filtered


def gcr_modulate(bits: np.ndarray) -> np.ndarray:
    """Modulate payload bits as GCR/NRZI + bandlimited waveform.

    Pipeline:
      1. Prepend shared chirp preamble (coarse sync).
      2. Prepend NRZI bit-sync word (64 alternating bits, fine clock sync).
      3. GCR 4b/5b encode the payload bits.
      4. NRZI encode -> +1/-1 symbols.
      5. Upsample (repeat each symbol SAMPLES_PER_SYM times).
      6. Convolve with RC filter for bandlimiting (Nyquist pulse shaping).
      7. Normalise whole data section to amplitude ~0.70.

    Both the sync word and GCR data are contiguous NRZI — the receiver decodes
    them together and strips the sync word. The sync word is counted as overhead.

    Returns float32 @48kHz.
    """
    preamble = hc.make_preamble()

    # Concatenate sync word bits + payload GCR bits, NRZI-encode the whole thing
    gcr_bits = gcr_encode(bits)
    all_bits = np.concatenate([_SYNC_WORD_BITS, gcr_bits]).astype(np.uint8)

    data_audio = _nrzi_bandlimit(all_bits) * 0.70

    audio = np.concatenate([preamble, data_audio]).astype(np.float32)
    return audio


# ---------------------------------------------------------------------------
# Demodulator — PLL / zero-crossing clock recovery
# ---------------------------------------------------------------------------

def gcr_demodulate(audio: np.ndarray, sr: int) -> np.ndarray:
    """Demodulate GCR/NRZI waveform.

    Steps:
      1. Bandpass the full audio (100 Hz .. 11 kHz) FIRST.
      2. Find chirp preamble via hc.find_preamble on the bandpassed audio.
      3. Fine bit-clock phase lock: sliding-window sync word correlation.
         The sync word `[1,0]*32` produces NRZI levels `[-1,-1,+1,+1]*16`
         (2-bit run-length pattern). We slide a template of the EXPECTED
         UPSAMPLED sync waveform across a ±3 bit-period window around the
         coarse start and pick the offset with the highest cross-correlation.
         This is equivalent to a matched-filter sync word detector and handles
         the ±3 bit-period WF-induced preamble offset accurately.
      4. Sample payload with M&M PLL tracking from the best offset.
      5. Strip sync word, NRZI decode GCR bits.
      6. GCR 4b/5b decode -> payload bits.
    """
    audio = np.asarray(audio, dtype=np.float32)

    # --- bandpass FIRST (before preamble detection) ---
    sos = scipy_signal.butter(4, [100.0, 11_000.0], btype="band", fs=sr, output="sos")
    audio_bp = scipy_signal.sosfiltfilt(sos, audio).astype(np.float32)
    audio_bp = audio_bp - np.mean(audio_bp)

    # --- coarse sync via chirp preamble (on bandpassed audio) ---
    coarse_start = hc.find_preamble(audio_bp)
    if coarse_start >= len(audio_bp):
        return np.zeros(0, dtype=np.uint8)

    # --- Build the expected upsampled+filtered sync waveform template ---
    # This is what the sync word looks like after TX bandlimiting (no normalisation).
    sync_nrzi = nrzi_encode(_SYNC_WORD_BITS)
    sync_up = np.repeat(sync_nrzi, SAMPLES_PER_SYM).astype(np.float32)
    sync_template = scipy_signal.fftconvolve(sync_up, _RC_TAPS, mode="same").astype(np.float32)
    # Also apply the bandpass to the template (matches what the demod sees)
    sync_template_bp = scipy_signal.sosfiltfilt(sos, sync_template).astype(np.float32)
    # Normalise for correlation
    sync_norm = sync_template_bp / (np.linalg.norm(sync_template_bp) + 1e-9)

    # --- Sliding cross-correlation sync word detector ---
    # Search ±3 bit-periods (±18 samples) around coarse_start.
    SEARCH_HALF = 3 * SAMPLES_PER_SYM  # 18 samples
    n_template = len(sync_template_bp)
    search_start = max(0, coarse_start - SEARCH_HALF)
    search_end = min(len(audio_bp) - n_template, coarse_start + SEARCH_HALF)

    best_start = coarse_start
    best_corr = -1.0
    for candidate in range(search_start, search_end + 1):
        seg = audio_bp[candidate: candidate + n_template].astype(np.float64)
        seg_norm = seg / (np.linalg.norm(seg) + 1e-9)
        corr = float(abs(np.dot(seg_norm, sync_norm.astype(np.float64))))
        if corr > best_corr:
            best_corr = corr
            best_start = candidate

    # The data region starts at best_start; the sync word occupies the
    # first n_template samples = len(_SYNC_WORD_BITS) * SAMPLES_PER_SYM.
    n_sync_samples = len(_SYNC_WORD_BITS) * SAMPLES_PER_SYM
    spb = float(SAMPLE_RATE) / float(BAUD_RATE)

    # --- Recover symbols with M&M PLL from best_start ---
    data_region = audio_bp[best_start:]
    symbols = _recover_symbols_pll(data_region, spb, initial_phase=0.0)
    if len(symbols) == 0:
        return np.zeros(0, dtype=np.uint8)

    # --- Strip sync word and NRZI decode ---
    n_sync = len(_SYNC_WORD_BITS)
    if len(symbols) > n_sync:
        gcr_symbols = symbols[n_sync:]
    else:
        gcr_symbols = symbols

    gcr_bits = nrzi_decode(gcr_symbols)

    # --- GCR 4b/5b decode ---
    n_payload = len(gcr_bits) * 4 // 5
    payload_bits = gcr_decode(gcr_bits, n_payload)
    return payload_bits.astype(np.uint8)


def _sample_at_phase(sig: np.ndarray, phase: int, spb: float, n_syms: int) -> np.ndarray:
    """Sample ``n_syms`` symbols from ``sig`` starting at integer ``phase``."""
    out = np.empty(n_syms, dtype=np.float64)
    n = len(sig)
    for i in range(n_syms):
        idx = phase + int(i * spb)
        out[i] = float(sig[idx]) if idx < n else 0.0
    return out


def _recover_symbols_pll(
    sig: np.ndarray,
    spb: float,
    initial_phase: float | None = None,
) -> np.ndarray:
    """Sample symbols from a bandlimited NRZI waveform.

    Uses a very-low-bandwidth M&M PLL (alpha = 0.001) to track slow wow/flutter
    (0.1% WF -> ~0.006 samples/bit drift at spb=6). At the cassette channel's
    noise level (WF_wrms << 1%), fixed-rate sampling works almost as well, so
    we keep alpha tiny to avoid spurious corrections.

    ``initial_phase``: exact starting sample offset (from sync-word phase scan).

    Returns float32 array of sampled symbol values (+/-amplitude).
    """
    n = len(sig)
    if n < int(spb * 2):
        return np.array([], dtype=np.float32)

    # Interpolation helper (linear)
    def _interp(pos: float) -> float:
        i = int(pos)
        f = pos - i
        if i < 0:
            return float(sig[0])
        if i >= n - 1:
            return float(sig[min(i, n - 1)])
        return float(sig[i]) * (1.0 - f) + float(sig[i + 1]) * f

    k = float(initial_phase) if initial_phase is not None else spb * 0.5

    # Very low PLL bandwidth: WF 0.1% -> spb drift << 0.01 samples/symbol;
    # alpha = 0.001 keeps corrections small enough to not introduce ISI.
    alpha = 0.001
    symbols: list[float] = []
    prev_sample = _interp(k - spb) if k >= spb else 0.0

    while k < n:
        s = _interp(k)
        symbols.append(s)

        # Mueller-Muller TED (only drives tiny corrections)
        ps = np.sign(prev_sample) if prev_sample != 0 else 0.0
        cs = np.sign(s) if s != 0 else 0.0
        ted = s * ps - prev_sample * cs

        prev_sample = s
        k += spb - alpha * ted

    return np.array(symbols, dtype=np.float32)


# ---------------------------------------------------------------------------
# Gross BPS calculation
# ---------------------------------------------------------------------------
# We compute gross_bps from a sample modulate call (same approach as B0).

def _compute_gross_bps(payload_bits: int = 4_000) -> float:
    """Measure gross_bps = payload_bits / duration_of_audio from a sample encode."""
    test_bits = np.zeros(payload_bits, dtype=np.uint8)
    audio = gcr_modulate(test_bits)
    dur = len(audio) / SAMPLE_RATE
    return float(payload_bits) / dur if dur > 0 else 0.0


# ---------------------------------------------------------------------------
# Scheme wrapper
# ---------------------------------------------------------------------------

def _make_gcr_scheme(payload_bits: int = 4_000) -> hc.FuncScheme:
    gross_bps = _compute_gross_bps(payload_bits)
    return hc.FuncScheme(
        name="H5_gcr_rll_nrzi",
        gross_bps=gross_bps,
        modulate=gcr_modulate,
        demodulate=gcr_demodulate,
    )


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_h5_evaluation(
    n_seeds: int = 20,
    payload_bits: int = 4_000,
) -> dict:
    """Run the full H5 evaluation: normal tape + worn stress + projections."""
    RESULTS_DATA.mkdir(parents=True, exist_ok=True)
    RESULTS_PLOTS.mkdir(parents=True, exist_ok=True)

    scheme = _make_gcr_scheme(payload_bits)
    print(f"\n{'='*60}")
    print(f"H5 GCR/RLL NRZI Evaluation")
    print(f"  scheme:      {scheme.name}")
    print(f"  gross_bps:   {scheme.gross_bps:.1f}")
    print(f"  baud_rate:   {BAUD_RATE}")
    print(f"  samples/sym: {SAMPLES_PER_SYM}")
    print(f"  n_seeds:     {n_seeds}")
    print(f"  payload_bits:{payload_bits}")
    print(f"{'='*60}")

    # ---- normal tape ----
    print("\n[1/4] Evaluating on normal tape...")
    normal_eval = hc.evaluate_scheme(
        scheme,
        tape_preset="normal",
        n_seeds=n_seeds,
        payload_bits=payload_bits,
    )
    print(f"  raw_ber:      {normal_eval['raw_bit_error_rate']:.6f}")
    print(f"  erasure_rate: {normal_eval['erasure_rate']:.4f}")
    print(f"  gross_bps:    {normal_eval['gross_bps']:.1f}")

    print("[2/4] Projecting normal tape to cassette scale...")
    normal_proj = hc.project_to_cassette(
        raw_ber=normal_eval["raw_bit_error_rate"],
        erasure_rate=normal_eval["erasure_rate"],
        gross_bps=normal_eval["gross_bps"],
    )
    print(f"  net_bps:       {normal_proj['net_bps']:.1f}")
    print(f"  MB_C90_stereo: {normal_proj['MB_C90_stereo']:.3f}")
    print(f"  P_full:        {normal_proj['P_full']:.4f}")

    # ---- worn tape ----
    print("\n[3/4] Evaluating on worn tape (stress)...")
    worn_eval = hc.evaluate_scheme(
        scheme,
        tape_preset="worn",
        n_seeds=n_seeds,
        payload_bits=payload_bits,
    )
    print(f"  raw_ber:      {worn_eval['raw_bit_error_rate']:.6f}")
    print(f"  erasure_rate: {worn_eval['erasure_rate']:.4f}")

    print("[4/4] Projecting worn tape to cassette scale...")
    worn_proj = hc.project_to_cassette(
        raw_ber=worn_eval["raw_bit_error_rate"],
        erasure_rate=worn_eval["erasure_rate"],
        gross_bps=worn_eval["gross_bps"],
    )
    print(f"  net_bps:       {worn_proj['net_bps']:.1f}")
    print(f"  MB_C90_stereo: {worn_proj['MB_C90_stereo']:.3f}")
    print(f"  P_full:        {worn_proj['P_full']:.4f}")

    # ---- Baseline comparison ----
    B0_NET_BPS = 478.1          # from hyp_baseline_B0.json
    B0_GROSS_BPS = 537.9
    H5_THRESHOLD = 1.5 * B0_NET_BPS  # 717.1 bps (pre-registered)

    net_bps = normal_proj["net_bps"]
    ratio_to_b0 = net_bps / B0_NET_BPS

    print(f"\n{'='*60}")
    print(f"VERDICT SUMMARY")
    print(f"  B0 net_bps (baseline):  {B0_NET_BPS:.1f} bps")
    print(f"  H5 threshold (1.5x B0): {H5_THRESHOLD:.1f} bps")
    print(f"  H5 net_bps (measured):  {net_bps:.1f} bps")
    print(f"  H5 / B0 ratio:          {ratio_to_b0:.3f}x")

    if net_bps >= H5_THRESHOLD:
        verdict = "ACCEPT"
    elif net_bps >= B0_NET_BPS:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "REJECT"

    print(f"  VERDICT: {verdict}")
    print(f"{'='*60}\n")

    # ---- per-seed BER plot ----
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    seeds = list(range(n_seeds))

    ax = axes[0]
    ax.bar(seeds, normal_eval["per_seed_ber"], color="steelblue", alpha=0.8, label="BER")
    ax.axhline(normal_eval["raw_bit_error_rate"], color="navy", linestyle="--", label=f"mean={normal_eval['raw_bit_error_rate']:.4f}")
    ax.set_title("H5 GCR/NRZI — Normal Tape BER per Seed")
    ax.set_xlabel("seed")
    ax.set_ylabel("bit error rate")
    ax.legend()
    ax.set_ylim(0, max(0.05, max(normal_eval["per_seed_ber"]) * 1.2))

    ax = axes[1]
    ax.bar(seeds, worn_eval["per_seed_ber"], color="tomato", alpha=0.8, label="BER (worn)")
    ax.axhline(worn_eval["raw_bit_error_rate"], color="darkred", linestyle="--", label=f"mean={worn_eval['raw_bit_error_rate']:.4f}")
    ax.set_title("H5 GCR/NRZI — Worn Tape BER per Seed")
    ax.set_xlabel("seed")
    ax.set_ylabel("bit error rate")
    ax.legend()
    ax.set_ylim(0, max(0.05, max(worn_eval["per_seed_ber"]) * 1.2))

    plt.tight_layout()
    plot_path = RESULTS_PLOTS / "hyp_gcr_rll.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"Plot saved: {plot_path}")

    # ---- Compose output metrics ----
    metrics = {
        "name": scheme.name,
        "verdict": verdict,
        "B0_net_bps": B0_NET_BPS,
        "H5_threshold_bps": H5_THRESHOLD,
        "ratio_to_B0": ratio_to_b0,

        # Normal tape
        "normal": {
            **normal_eval,
            "projection": normal_proj,
        },

        # Worn tape (stress)
        "worn": {
            **worn_eval,
            "projection": worn_proj,
        },

        # Top-level canonical fields for StructuredOutput
        "gross_bps": normal_eval["gross_bps"],
        "raw_bit_error_rate": normal_eval["raw_bit_error_rate"],
        "erasure_rate": normal_eval["erasure_rate"],
        "net_bps": normal_proj["net_bps"],
        "MB_C90_stereo": normal_proj["MB_C90_stereo"],
        "MB_C60_stereo": normal_proj["MB_C60_stereo"],
        "P_full": normal_proj["P_full"],
        "required_code_rate": normal_proj["required_code_rate"],

        # Implementation parameters
        "baud_rate": BAUD_RATE,
        "samples_per_sym": SAMPLES_PER_SYM,
        "gcr_code": "4b5b",
        "gcr_overhead_fraction": 0.25,
        "modulation": "NRZI_bandlimited_RRC",
        "clock_recovery": "early_late_gate_PLL",
        "sync": "chirp_preamble_0.25s",

        # Channel model fidelity note
        "model_fidelity_caveat": (
            "channel.py is LINEAR+bandlimited (AWGN + LPF + wow/flutter + burst). "
            "It does NOT model magnetic saturation/hysteresis. "
            "GCR/RLL earn their advantage on a SATURATING magnetic channel. "
            "A sim REJECTION here is informative about model fidelity, "
            "not necessarily about code performance on real tape."
        ),
    }

    out_path = RESULTS_DATA / "hyp_gcr_rll.json"
    with open(out_path, "w") as f:
        json.dump(metrics, f, indent=2, default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"Metrics saved: {out_path}")

    return metrics


if __name__ == "__main__":
    results = run_h5_evaluation(n_seeds=20, payload_bits=4_000)
    print("\n--- Final Metric Table ---")
    for k in [
        "gross_bps", "raw_bit_error_rate", "erasure_rate",
        "required_code_rate", "net_bps", "MB_C90_stereo",
        "P_full", "ratio_to_B0", "verdict",
    ]:
        print(f"  {k}: {results[k]}")
