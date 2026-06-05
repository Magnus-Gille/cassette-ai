"""Robust cassette-data-modem front-end (shared E2E library).

Wraps the existing CAS3/BFSK codec in ``src/cassette_format.py`` with a
playback-realistic decode pipeline that tolerates the impairments a real
record -> tape -> playback -> record loopback introduces:

  * arbitrary leading/trailing silence  -> chirp cross-correlation sync
  * arbitrary recording sample rate      -> resample to 48 kHz, downmix mono
  * gain + DC offset changes             -> DC removal + peak normalization
  * steady tape-speed error (~0.5-2%)    -> brute-force speed search

The codec itself is NOT reinvented here; we only build a robust front-end
around ``cf.encode_audio`` / ``cf._sync_chirp`` / ``cf._fsk_to_bits`` /
``cf._bits_to_bytes`` / ``cf.decode_container``.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
from dataclasses import dataclass

import numpy as np
import soundfile as sf
from scipy.signal import correlate, resample_poly

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))
import cassette_format as cf  # noqa: E402

SAMPLE_RATE = 48_000


# --------------------------------------------------------------------------
# Encoding / file IO
# --------------------------------------------------------------------------
def encode_payload_to_audio(payload: bytes) -> np.ndarray:
    """Thin wrapper over ``cf.encode_audio``; float32 @ 48 kHz."""
    return np.asarray(cf.encode_audio(payload), dtype=np.float32)


def _normalize_peak(audio: np.ndarray, peak: float) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float64)
    m = float(np.max(np.abs(audio))) if audio.size else 0.0
    if m > 0:
        audio = audio * (peak / m)
    return audio


def write_wav(
    path,
    audio48k: np.ndarray,
    *,
    sample_rate: int = SAMPLE_RATE,
    peak: float = 0.7,
    lead_silence_s: float = 0.5,
    tail_silence_s: float = 0.5,
) -> None:
    """Normalize to ``peak``, pad with silence, write 16-bit PCM mono."""
    audio = _normalize_peak(audio48k, peak)
    lead = np.zeros(int(round(lead_silence_s * sample_rate)), dtype=np.float64)
    tail = np.zeros(int(round(tail_silence_s * sample_rate)), dtype=np.float64)
    out = np.concatenate([lead, audio, tail]).astype(np.float32)
    sf.write(str(path), out, int(sample_rate), subtype="PCM_16")


def read_wav_any(path) -> tuple[np.ndarray, int]:
    """Read a wav (any sr); downmix stereo -> mono. NO resample here."""
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.float32)
    return audio, int(sr)


# --------------------------------------------------------------------------
# Resampling / preprocessing
# --------------------------------------------------------------------------
def _to_mono(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.float32)
    return audio


def _resample_ratio(audio: np.ndarray, ratio: float) -> np.ndarray:
    """Resample so that new_len ~= round(len * ratio) via a rational approx."""
    if abs(ratio - 1.0) < 1e-9:
        return np.asarray(audio, dtype=np.float64)
    # Rational approximation of ratio with a bounded denominator.
    up, down = _rational(ratio, max_den=2000)
    return resample_poly(np.asarray(audio, dtype=np.float64), up, down)


def _rational(ratio: float, max_den: int = 2000) -> tuple[int, int]:
    """Best up/down integer pair approximating ``ratio`` (up/down ~= ratio)."""
    from fractions import Fraction

    frac = Fraction(ratio).limit_denominator(max_den)
    up, down = frac.numerator, frac.denominator
    if up <= 0:
        up = 1
    return up, down


def to_48k_mono(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Downmix to mono and resample to 48 kHz if needed; float32."""
    audio = _to_mono(audio)
    if int(sample_rate) != SAMPLE_RATE:
        up, down = _rational(SAMPLE_RATE / float(sample_rate), max_den=4000)
        audio = resample_poly(audio.astype(np.float64), up, down)
    return np.asarray(audio, dtype=np.float32)


def preprocess(audio48k: np.ndarray) -> np.ndarray:
    """Subtract DC mean, normalize peak to ~1.0; float32."""
    audio = np.asarray(audio48k, dtype=np.float64)
    if audio.size:
        audio = audio - float(np.mean(audio))
        m = float(np.max(np.abs(audio)))
        if m > 0:
            audio = audio / m
    return audio.astype(np.float32)


# --------------------------------------------------------------------------
# Chirp sync
# --------------------------------------------------------------------------
def find_data_start(audio48k: np.ndarray) -> tuple[int, float]:
    """Cross-correlate against ``cf._sync_chirp()`` to locate the chirp.

    Returns (data_start_sample, corr_peak) where data_start is the sample
    index of the first BFSK data bit (chirp_start + len(chirp)) and corr_peak
    is a roughly 0..1 normalized correlation strength.
    """
    audio = np.asarray(audio48k, dtype=np.float64)
    chirp = np.asarray(cf._sync_chirp(), dtype=np.float64)
    n_chirp = len(chirp)
    if len(audio) < n_chirp:
        return 0, 0.0

    # Sliding dot-product; 'valid' gives one value per candidate start offset.
    corr = correlate(audio, chirp, mode="valid")
    idx = int(np.argmax(np.abs(corr)))
    chirp_start = idx

    # Normalize: correlation peak / (||chirp|| * ||window||) -> ~cosine sim.
    window = audio[chirp_start : chirp_start + n_chirp]
    denom = float(np.linalg.norm(window) * np.linalg.norm(chirp))
    corr_peak = float(abs(corr[idx]) / denom) if denom > 0 else 0.0

    data_start = chirp_start + n_chirp
    return data_start, corr_peak


# --------------------------------------------------------------------------
# Demodulation
# --------------------------------------------------------------------------
def _ref_tones() -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(cf.SAMPLES_PER_BIT, dtype=np.float64) / SAMPLE_RATE
    zero = np.sin(2.0 * np.pi * cf.FREQ_ZERO * t)
    one = np.sin(2.0 * np.pi * cf.FREQ_ONE * t)
    return zero, one


def _safe_decode(container: bytes) -> cf.DecodeResult:
    """``cf.decode_container`` can raise on garbage (e.g. ZeroDivisionError on a
    corrupt header). Wrap it so the speed/offset search never crashes."""
    try:
        return cf.decode_container(container)
    except Exception as exc:  # noqa: BLE001
        return cf.DecodeResult(b"", None, 0, (), 0, False, False, (f"decode_exc:{type(exc).__name__}",))


def demod_adaptive(audio48k: np.ndarray, start: int, *, drift_search: int = 3) -> np.ndarray:
    """Non-coherent BFSK demod with per-bit timing recovery.

    The fixed-clock ``cf._fsk_to_bits`` cannot follow the cassette wow/flutter
    timebase warp: the 40-samples/bit clock drifts and bits smear after a few
    hundred bits. This demod re-centers each bit by searching +/- ``drift_search``
    samples for the symbol window of maximum tone energy, then nudges the running
    sample position toward that center. Output bits are bit-for-bit compatible
    with ``cf._bits_to_bytes`` -> ``cf.decode_container``.
    """
    audio = np.asarray(audio48k, dtype=np.float64)
    zero, one = _ref_tones()
    spb = cf.SAMPLES_PER_BIT
    n_bits = (len(audio) - int(start)) // spb
    if n_bits <= 0:
        return np.zeros(0, dtype=np.uint8)
    bits = np.empty(n_bits, dtype=np.uint8)
    pos = float(start)
    count = 0
    for _ in range(n_bits):
        center = int(round(pos))
        best_e = -1.0
        best_d = 0
        best_bit = 0
        for d in range(-drift_search, drift_search + 1):
            s = center + d
            if s < 0 or s + spb > len(audio):
                continue
            w = audio[s : s + spb]
            sz = abs(float(np.dot(w, zero)))
            so = abs(float(np.dot(w, one)))
            e = so if so > sz else sz
            if e > best_e:
                best_e = e
                best_d = d
                best_bit = 1 if so > sz else 0
        if best_e < 0:
            break
        bits[count] = best_bit
        count += 1
        # Re-center the clock toward the observed best offset (fractional nudge
        # keeps it stable while still tracking slow flutter drift).
        pos += spb + best_d * 0.5
    return bits[:count]


# --------------------------------------------------------------------------
# Robust decode
# --------------------------------------------------------------------------
@dataclass
class RobustResult:
    result: cf.DecodeResult
    start_sample: int
    corr_peak: float
    speed_ratio: float
    est_snr_db: float
    from_sample_rate: int


def _score(result: cf.DecodeResult, corr_peak: float) -> tuple:
    """Higher is better. Prefer complete, then recovered frames, fewer bad,
    valid header present, then stronger chirp correlation."""
    header_ok = result.header is not None
    return (
        1 if result.complete else 0,
        result.tail_hash_ok,
        result.recovered_frames,
        -result.bad_frames,
        1 if header_ok else 0,
        corr_peak,
    )


def _decode_at(pre: np.ndarray, start: int) -> cf.DecodeResult:
    """Demodulate from ``start`` and decode. Tries the adaptive (timing-tracking)
    demod first, then the codec's fixed-clock demod as a fallback; returns the
    better result."""
    if len(pre) - start < cf.SAMPLES_PER_BIT:
        return _safe_decode(b"")
    bits_a = demod_adaptive(pre, start)
    res_a = _safe_decode(cf._bits_to_bytes(bits_a))
    bits_f = cf._fsk_to_bits(np.asarray(pre[start:], dtype=np.float32))
    res_f = _safe_decode(cf._bits_to_bytes(bits_f))
    return res_a if _score(res_a, 0.0) >= _score(res_f, 0.0) else res_f


def _decode_one(audio48k: np.ndarray, ratio: float) -> tuple[cf.DecodeResult, int, float, float]:
    """One speed-corrected decode pass. Returns (result, data_start, corr_peak, est_snr_db).

    Around the chirp-correlation start, a small fine-offset scan (sub-bit) is run
    because the bandlimited chirp peak can land a few samples off the true data
    start; the best-scoring offset is kept."""
    warped = _resample_ratio(audio48k, ratio)
    pre = preprocess(warped)
    data_start, corr_peak = find_data_start(pre)
    est_snr = _estimate_snr(pre, data_start)
    if len(pre) - data_start < cf.SAMPLES_PER_BIT:
        return _safe_decode(b""), data_start, corr_peak, est_snr

    best_res: cf.DecodeResult | None = None
    best_off = data_start
    best_sc: tuple | None = None
    half_bit = cf.SAMPLES_PER_BIT // 2
    for off in range(data_start - half_bit, data_start + half_bit + 1, 2):
        if off < 0:
            continue
        res = _decode_at(pre, off)
        sc = _score(res, corr_peak)
        if best_sc is None or sc > best_sc:
            best_sc, best_res, best_off = sc, res, off
            if res.complete:
                break
    assert best_res is not None
    return best_res, best_off, corr_peak, est_snr


def _estimate_snr(pre48k: np.ndarray, data_start: int) -> float:
    """Rough SNR: chirp-region power vs leading-silence-region power."""
    n_chirp = int(cf.SYNC_SECONDS * SAMPLE_RATE)
    chirp_start = data_start - n_chirp
    if chirp_start <= 0 or chirp_start > len(pre48k):
        return float("nan")
    sig = pre48k[chirp_start:data_start]
    noise = pre48k[: chirp_start]
    if sig.size == 0 or noise.size < SAMPLE_RATE // 50:
        return float("nan")
    sig_p = float(np.mean(sig.astype(np.float64) ** 2))
    noise_p = float(np.mean(noise.astype(np.float64) ** 2))
    if noise_p <= 0 or sig_p <= 0:
        return float("nan")
    return float(10.0 * np.log10(sig_p / noise_p))


def _speed_grid(speed_search: tuple[float, float, float]) -> list[float]:
    lo, hi, step = speed_search
    if step <= 0:
        ratios = [lo, hi]
    else:
        n = int(round((hi - lo) / step)) + 1
        ratios = [round(lo + i * step, 6) for i in range(n)]
    # Always include exact 1.0.
    if not any(abs(r - 1.0) < 1e-9 for r in ratios):
        ratios.append(1.0)
    # Search near 1.0 first so a clean signal short-circuits.
    ratios.sort(key=lambda r: abs(r - 1.0))
    return ratios


def robust_decode(
    audio: np.ndarray,
    sample_rate: int,
    *,
    speed_search: tuple[float, float, float] = (0.94, 1.06, 0.005),
    verbose: bool = False,
) -> RobustResult:
    """Full robust pipeline. Resamples to 48k mono, then brute-forces a small
    speed grid; for each ratio it preprocesses, chirp-syncs, demodulates and
    decodes the container, keeping the best-scoring pass."""
    from_sr = int(sample_rate)
    base = to_48k_mono(audio, sample_rate)

    best: RobustResult | None = None
    best_score: tuple | None = None
    for ratio in _speed_grid(speed_search):
        result, data_start, corr_peak, est_snr = _decode_one(base, ratio)
        score = _score(result, corr_peak)
        if verbose:
            print(
                f"  ratio={ratio:.4f} start={data_start} corr={corr_peak:.3f} "
                f"complete={result.complete} recovered={result.recovered_frames} "
                f"bad={result.bad_frames} tail_ok={result.tail_hash_ok}"
            )
        if best_score is None or score > best_score:
            best_score = score
            best = RobustResult(
                result=result,
                start_sample=data_start,
                corr_peak=corr_peak,
                speed_ratio=ratio,
                est_snr_db=est_snr,
                from_sample_rate=from_sr,
            )
            # Short-circuit on a perfect decode.
            if result.complete:
                break

    assert best is not None
    return best


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------
def compare_payload(expected: bytes, result: cf.DecodeResult) -> dict:
    """Compare an expected payload against a DecodeResult's recovered payload."""
    recovered = result.payload or b""
    exp_len = len(expected)
    rec_len = len(recovered)
    byte_exact = recovered == expected
    sha_match = (
        hashlib.sha256(recovered).digest() == hashlib.sha256(expected).digest()
    )

    n = min(exp_len, rec_len)
    if n > 0:
        exp_arr = np.frombuffer(expected[:n], dtype=np.uint8)
        rec_arr = np.frombuffer(recovered[:n], dtype=np.uint8)
        byte_errors = int(np.count_nonzero(exp_arr != rec_arr))
        # Count length mismatch as additional errors over the longer length.
        byte_errors += abs(exp_len - rec_len)
        denom = max(exp_len, rec_len)
        byte_error_rate = byte_errors / denom if denom else 0.0
    else:
        byte_error_rate = 1.0 if (exp_len or rec_len) else 0.0

    recovered_fraction = (rec_len / exp_len) if exp_len else 1.0

    return {
        "byte_exact": bool(byte_exact),
        "sha_match": bool(sha_match),
        "recovered_bytes": rec_len,
        "expected_bytes": exp_len,
        "recovered_fraction": float(recovered_fraction),
        "byte_error_rate": float(byte_error_rate),
        "recovered_frames": result.recovered_frames,
        "bad_frames": result.bad_frames,
        "missing_frames": result.missing_frames,
        "complete": bool(result.complete),
    }


# --------------------------------------------------------------------------
# Self-verify
# --------------------------------------------------------------------------
def _self_check() -> int:
    sys.path.insert(0, str(SRC))
    import channel  # noqa: E402  (realistic playback simulator)

    payload = bytes(range(64)) + b"CASSETTE-E2E test 12345"
    a = encode_payload_to_audio(payload)

    # Nasty recording: silence pad, gain + DC, channel impairments, sr mismatch.
    lead = np.zeros(int(0.37 * SAMPLE_RATE), dtype=np.float32)
    tail = np.zeros(int(0.60 * SAMPLE_RATE), dtype=np.float32)
    padded = np.concatenate([lead, a, tail])
    gained = padded * 0.4 + 0.02  # gain + DC offset
    impaired = channel.cassette_channel(
        gained,
        snr_db=38,
        wow_flutter_wrms=0.0009,
        bandwidth_hz=11000,
        seed_offset=3,
    )
    # Resample whole thing to 44100 and claim sr=44100 (speed + rate mismatch).
    up, down = _rational(44100 / SAMPLE_RATE, max_den=4000)
    rec_44100 = resample_poly(impaired.astype(np.float64), up, down)

    rr = robust_decode(rec_44100, 44100, verbose=True)
    cmp = compare_payload(payload, rr.result)
    print()
    print(f"chosen speed_ratio = {rr.speed_ratio}")
    print(f"corr_peak          = {rr.corr_peak:.4f}")
    print(f"est_snr_db         = {rr.est_snr_db:.2f}")
    print(f"from_sample_rate   = {rr.from_sample_rate}")
    print(f"start_sample       = {rr.start_sample}")
    print(f"compare_payload    = {cmp}")

    ok = cmp["byte_exact"] or (cmp["sha_match"] and cmp["recovered_fraction"] >= 1.0)
    print()
    print("SELF-CHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_self_check())
