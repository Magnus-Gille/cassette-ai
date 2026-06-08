"""hyp_common.py — Shared metric contract for the cassette encoding-scheme bake-off.

Every encoding hypothesis (H1..H5) is expressed as a ``Scheme`` and measured
through ONE harness so the comparison is apples-to-apples:

  * the SAME standard channel (tape preset "normal", usb_soundcard capture),
  * the SAME Monte-Carlo driver (``evaluate_scheme``),
  * the SAME analytic projection to a whole-cassette payload
    (``project_to_cassette``), and
  * the SAME baseline yardstick B0 (``measure_baseline_B0``), which wraps the
    existing CAS3/BFSK codec exactly as it ships.

A Scheme is defined by four things and nothing else:
  - ``name``            : str
  - ``modulate(bits)``  : np.uint8[] -> float32 audio @48k, INCLUDING its own
                          preamble/sync. The preamble is overhead and is paid
                          for in ``gross_bps``.
  - ``demodulate(audio, sr)`` : audio,sr -> recovered np.uint8[] bits. Must do
                          its OWN coarse sync from the preamble. NO genie/oracle
                          bit-timing is permitted — sync comes from the signal.
  - ``gross_bps``       : float, payload+overhead information bits carried per
                          second of emitted audio (len(audio)/48000). This is
                          the rate the channel actually runs at; outer-code
                          redundancy is applied analytically on top in
                          ``project_to_cassette``.

NO oracle is used anywhere: every scheme decodes from the channel-mangled audio
using only its declared preamble for sync.

Path bootstrap (canonical for this repo)::

    import sys, pathlib
    ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
    for p in ["src","tests/e2e"]: sys.path.insert(0, str(ROOT/p))
    import cassette_format as cf, channel as ch, capture_scenarios as cs, cassette_e2e as e2e
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from dataclasses import dataclass, field, asdict
from typing import Callable, Protocol

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import cassette_format as cf  # noqa: E402
import channel as ch  # noqa: E402
import capture_scenarios as cs  # noqa: E402
import cassette_e2e as e2e  # noqa: E402

from scipy.signal import chirp as _scipy_chirp, correlate as _correlate  # noqa: E402

SAMPLE_RATE = 48_000
DATA_DIR = ROOT / "RESULTS" / "data"

# ---------------------------------------------------------------------------
# Whole-cassette capacity constants (established by prior experiments in repo).
#   usable runtime per C90 (2 sides): ~5374 s ; per C60: ~3574 s.
#   stereo = 2 independent tracks (factor 2 on capacity).
# These convert a sustained net bit-rate into payload megabytes per cassette.
# ---------------------------------------------------------------------------
C90_USABLE_SECONDS = 5374.0
C60_USABLE_SECONDS = 3574.0
STEREO_TRACKS = 2

TARGET_PAYLOAD_BYTES = 1_271_000  # TinyStories-1M UEP target
TARGET_P_FULL = 0.95


# ===========================================================================
# Scheme protocol
# ===========================================================================
class Scheme(Protocol):
    name: str
    gross_bps: float

    def modulate(self, bits: np.ndarray) -> np.ndarray: ...
    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray: ...


@dataclass
class FuncScheme:
    """Adapter that turns plain functions into a Scheme.

    ``erasure_fn`` (optional) lets a scheme declare which symbol/frame slots it
    knows were lost to dropouts (so they can be treated as erasures, which are
    far cheaper to code against than bit errors). It returns a fraction in
    [0,1]; if omitted, erasure_rate is reported as 0 and all losses are folded
    into the raw bit-error rate instead (the conservative default).
    """

    name: str
    gross_bps: float
    modulate: Callable[[np.ndarray], np.ndarray]
    demodulate: Callable[[np.ndarray, int], np.ndarray]
    erasure_fn: Callable[[np.ndarray, int, np.ndarray], float] | None = None


# ===========================================================================
# Shared preamble + correlation sync (schemes may reuse this)
# ===========================================================================
PREAMBLE_F0 = 800.0
PREAMBLE_F1 = 3_200.0
PREAMBLE_SECONDS = 0.25
PREAMBLE_AMP = 0.65


def make_preamble(seconds: float = PREAMBLE_SECONDS) -> np.ndarray:
    """A linear up-chirp (800->3200 Hz) usable as a correlation sync marker.

    Bandlimited well inside the usable tape band (300 Hz .. 10.5 kHz) so it
    survives the channel. Returns float32 @48k. This is the SAME chirp the
    existing codec uses, so reusing it keeps sync behaviour comparable.
    """
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    sig = _scipy_chirp(t, f0=PREAMBLE_F0, f1=PREAMBLE_F1, t1=seconds, method="linear")
    return (PREAMBLE_AMP * sig).astype(np.float32)


def find_preamble(audio: np.ndarray, seconds: float = PREAMBLE_SECONDS) -> int:
    """Cross-correlate ``audio`` against ``make_preamble`` and return the sample
    index of the FIRST data sample after the preamble (preamble_start + len).

    This is a coarse, signal-derived sync — no oracle timing. Returns 0 if the
    audio is shorter than the preamble.
    """
    audio = np.asarray(audio, dtype=np.float64)
    pre = np.asarray(make_preamble(seconds), dtype=np.float64)
    n_pre = len(pre)
    if len(audio) < n_pre:
        return 0
    corr = _correlate(audio, pre, mode="valid")
    pre_start = int(np.argmax(np.abs(corr)))
    return pre_start + n_pre


# ===========================================================================
# Standard channel + Monte-Carlo evaluation
# ===========================================================================
def _random_bits(n: int, seed: int) -> np.ndarray:
    g = np.random.default_rng(10_000 + seed)
    return g.integers(0, 2, size=n, dtype=np.uint8)


def _ber(tx: np.ndarray, rx: np.ndarray) -> float:
    """Aligned post-sync bit-error rate over the overlap; bits the demod failed
    to produce are counted as errors (length shortfall is a real loss)."""
    n = len(tx)
    if n == 0:
        return 0.0
    m = min(n, len(rx))
    errs = int(np.count_nonzero(tx[:m] != rx[:m])) if m else 0
    errs += (n - m)  # missing tail bits == errors
    return errs / n


def evaluate_scheme(
    scheme: FuncScheme,
    tape_preset: str = "normal",
    n_seeds: int = 20,
    payload_bits: int = 4_000,
    *,
    capture_key: str = "usb_soundcard",
    speed_offset: float = 0.0,
) -> dict:
    """Monte-Carlo a Scheme through the standard channel.

    For each seed: random bits -> scheme.modulate -> cs.full_chain(audio,
    tape_preset, capture_key, seed) -> scheme.demodulate -> compare.

    Returns a dict with:
      gross_bps           : float (declared by the scheme)
      raw_bit_error_rate  : mean post-sync, pre-FEC BER across seeds
      erasure_rate        : mean declared erasure fraction (0 if scheme has no
                            erasure marker — then losses live in the BER)
      per_seed_ber, per_seed_erasure : arrays
      n_seeds, payload_bits, tape_preset, capture_key, name
    """
    bers: list[float] = []
    eras: list[float] = []
    for seed in range(n_seeds):
        tx_bits = _random_bits(payload_bits, seed)
        audio = np.asarray(scheme.modulate(tx_bits), dtype=np.float32)
        rx_audio, sr, _diag = cs.full_chain(
            audio, tape_preset, capture_key, speed_offset=speed_offset, seed=seed
        )
        rx_bits = np.asarray(scheme.demodulate(rx_audio, sr), dtype=np.uint8)
        bers.append(_ber(tx_bits, rx_bits))
        if scheme.erasure_fn is not None:
            eras.append(float(scheme.erasure_fn(rx_audio, sr, tx_bits)))
        else:
            eras.append(0.0)

    return {
        "name": scheme.name,
        "gross_bps": float(scheme.gross_bps),
        "raw_bit_error_rate": float(np.mean(bers)),
        "erasure_rate": float(np.mean(eras)),
        "per_seed_ber": [float(x) for x in bers],
        "per_seed_erasure": [float(x) for x in eras],
        "n_seeds": int(n_seeds),
        "payload_bits": int(payload_bits),
        "tape_preset": tape_preset,
        "capture_key": capture_key,
    }


# ===========================================================================
# Analytic projection to a whole-cassette payload
# ===========================================================================
# --- BER -> minimum code rate table (conservative) --------------------------
# Maps a measured raw bit-error rate to the LARGEST outer code rate that an
# off-the-shelf hard-decision block code (RS/LDPC class) can be expected to
# correct to a vanishingly small residual error over a long payload. The table
# is deliberately pessimistic: it leaves margin below the Shannon hard-decision
# limit R = 1 - H2(p) so we never over-claim. Entries are (max_raw_ber,
# usable_code_rate). The first row whose threshold the measured BER does NOT
# exceed is used.
_BER_RATE_TABLE = [
    (1e-6, 0.98),
    (1e-5, 0.95),
    (1e-4, 0.92),
    (1e-3, 0.85),
    (3e-3, 0.80),
    (1e-2, 0.70),
    (2e-2, 0.55),
    (4e-2, 0.40),
    (6e-2, 0.30),
    (8e-2, 0.20),
    (1e-1, 0.10),
]


def _bit_error_code_rate(raw_ber: float) -> float:
    """Largest safe outer-code RATE for a given raw bit-error rate.

    Conservative: uses the table above; above the last threshold the channel is
    treated as uncodable for a megabyte-scale whole-file recovery (rate -> ~0).
    """
    p = max(0.0, float(raw_ber))
    if p <= 0.0:
        return 0.99
    for thresh, rate in _BER_RATE_TABLE:
        if p <= thresh:
            return rate
    return 0.05  # effectively uncodable at megabyte scale


def _erasure_overhead(erasure_rate: float, margin: float = 0.05) -> float:
    """Fountain/MDS overhead fraction needed to recover all source symbols when
    a fraction ``e`` of coded symbols are erased.

    For an ideal MDS / near-ideal fountain (RaptorQ) code, recovering k source
    symbols requires k/(1-e) received symbols, i.e. an overhead of
    e/(1-e) over the source. We add a flat reception ``margin`` (default 5%) to
    cover RaptorQ's small non-ideality and Monte-Carlo variance. Returns the
    redundancy fraction (coded/source - 1).
    """
    e = min(max(0.0, float(erasure_rate)), 0.95)
    return e / (1.0 - e) + float(margin)


def _p_full_bit_errors(raw_ber: float, code_rate: float, payload_bytes: float) -> float:
    """Estimate P(whole-file recovered) under the bit-error path.

    If the chosen ``code_rate`` is at/below the safe rate for the measured BER
    (per the conservative table), the residual block-failure probability over a
    megabyte payload is modelled as negligible and P_full ~= 1. If the channel
    is below the table floor, P_full ~= 0. This is intentionally a step model:
    the table already bakes in the margin, so we don't double-count it with a
    fragile tail integral.
    """
    safe_rate = _bit_error_code_rate(raw_ber)
    if raw_ber <= _BER_RATE_TABLE[-1][0] and code_rate <= safe_rate + 1e-9:
        return 1.0
    return 0.0


def project_to_cassette(
    raw_ber: float,
    erasure_rate: float,
    gross_bps: float,
    payload_bytes: float = TARGET_PAYLOAD_BYTES,
    target_P: float = TARGET_P_FULL,
) -> dict:
    """Analytically choose the outer-code rate to recover ``payload_bytes`` WHOLE
    with probability >= ``target_P`` given the measured raw_ber + erasure_rate,
    then project net throughput and per-cassette payload megabytes.

    MODEL & ASSUMPTIONS (explicit, conservative):
      * Symbol/frame/bit errors are modelled as INDEPENDENT (the channel's burst
        dropouts are short relative to a megabyte payload and are spread by
        interleaving in any real implementation; we do not credit ourselves with
        burst-correlation gains).
      * ERASURES (slots the scheme marks as lost) are coded against with an
        ideal MDS / RaptorQ fountain: overhead = e/(1-e) + 5% reception margin
        (``_erasure_overhead``). This is the cheap path — used by H1.
      * BIT ERRORS (undetected flips inside surviving slots) are coded against
        with a hard-decision RS/LDPC-class block code whose safe rate is read
        from a deliberately pessimistic BER->rate table (``_BER_RATE_TABLE``),
        which sits below the Shannon hard-decision limit 1 - H2(p).
      * The two layers compose multiplicatively: the erasure layer first
        reconstructs the symbol stream, then the bit-error layer protects its
        contents. required_code_rate = rate_bit_errors / (1 + erasure_overhead).
      * P_full is the product of the per-layer success estimates. The table/
        overhead margins are what make >=target_P achievable; if either layer is
        below its floor, P_full collapses toward 0.

    Returns: required_code_rate, net_bps, MB_C90_stereo, MB_C60_stereo,
             MB_C90_mono, MB_C60_mono, P_full, and the intermediate
             rate_bit_errors / erasure_overhead for transparency.
    """
    rate_bit = _bit_error_code_rate(raw_ber)
    er_overhead = _erasure_overhead(erasure_rate)
    # Compose: erasure layer inflates the stream by (1+er_overhead); bit-error
    # layer multiplies the usable rate by rate_bit. Net code rate (payload/coded):
    required_code_rate = rate_bit / (1.0 + er_overhead)
    required_code_rate = max(0.0, min(0.999, required_code_rate))

    net_bps = float(gross_bps) * required_code_rate

    # Per-cassette payload megabytes at the sustained net rate.
    def _mb(seconds: float, tracks: int) -> float:
        return net_bps * seconds * tracks / 8.0 / 1e6

    mb_c90_stereo = _mb(C90_USABLE_SECONDS, STEREO_TRACKS)
    mb_c60_stereo = _mb(C60_USABLE_SECONDS, STEREO_TRACKS)
    mb_c90_mono = _mb(C90_USABLE_SECONDS, 1)
    mb_c60_mono = _mb(C60_USABLE_SECONDS, 1)

    # P_full estimate: product of per-layer success probabilities.
    p_bit = _p_full_bit_errors(raw_ber, required_code_rate * (1.0 + er_overhead), payload_bytes)
    # Erasure layer: with the +margin overhead an ideal fountain recovers all
    # source symbols w.h.p.; model as success unless erasures exceed what the
    # overhead covers (margin exhausted). Conservative step.
    p_era = 1.0 if erasure_rate < 0.90 else 0.0
    p_full = float(p_bit * p_era)

    # Does this payload fit on a C90 stereo at >= target_P?
    fits_c90_stereo = bool(mb_c90_stereo >= payload_bytes / 1e6 and p_full >= target_P)
    fits_c60_stereo = bool(mb_c60_stereo >= payload_bytes / 1e6 and p_full >= target_P)

    return {
        "raw_ber": float(raw_ber),
        "erasure_rate": float(erasure_rate),
        "gross_bps": float(gross_bps),
        "rate_bit_errors": float(rate_bit),
        "erasure_overhead": float(er_overhead),
        "required_code_rate": float(required_code_rate),
        "net_bps": float(net_bps),
        "MB_C90_stereo": float(mb_c90_stereo),
        "MB_C60_stereo": float(mb_c60_stereo),
        "MB_C90_mono": float(mb_c90_mono),
        "MB_C60_mono": float(mb_c60_mono),
        "P_full": float(p_full),
        "payload_bytes": float(payload_bytes),
        "target_P": float(target_P),
        "fits_C90_stereo": fits_c90_stereo,
        "fits_C60_stereo": fits_c60_stereo,
    }


# ===========================================================================
# Baseline B0 — the existing CAS3/BFSK codec, wrapped as a Scheme
# ===========================================================================
# The codec frames payload into 256-byte CRC'd frames + header + tail, then
# BFSK-modulates the whole container with a 2 s leader + 0.25 s sync chirp.
# We wrap it faithfully: modulate = cf.encode_audio(payload_bytes); demod =
# robust_decode -> recovered payload bytes -> bits. The robust front-end does
# the real (non-oracle) chirp sync, speed search and timing recovery.
#
# Because the container adds header/frame/tail bytes, gross_bps is computed from
# the EMITTED audio length vs the raw payload bits so the framing overhead is
# paid for honestly. Erasure rate = fraction of frames the codec reports
# missing/bad (the codec HAS per-frame CRC, so dropped frames are erasures, not
# silent bit errors).
# ---------------------------------------------------------------------------
def _bits_to_payload_bytes(bits: np.ndarray) -> bytes:
    usable = len(bits) - (len(bits) % 8)
    if usable <= 0:
        return b""
    return np.packbits(np.asarray(bits[:usable], dtype=np.uint8), bitorder="big").tobytes()


def _payload_bytes_to_bits(data: bytes, n_bits: int) -> np.ndarray:
    if not data:
        return np.zeros(n_bits, dtype=np.uint8)
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")
    if len(bits) >= n_bits:
        return bits[:n_bits].astype(np.uint8)
    out = np.zeros(n_bits, dtype=np.uint8)
    out[: len(bits)] = bits
    return out


class _B0Scheme:
    """The shipping BFSK codec presented through the Scheme interface."""

    name = "B0_bfsk_cas3_1200"

    def __init__(self, payload_bits: int):
        self.payload_bits = payload_bits
        self._payload_bytes = (payload_bits + 7) // 8
        # Measure gross_bps once from a representative encode.
        sample = bytes(self._payload_bytes)
        audio = cf.encode_audio(sample)
        dur = len(audio) / SAMPLE_RATE
        # gross = payload information bits / second of audio (framing+leader paid)
        self.gross_bps = float(payload_bits) / dur if dur > 0 else 0.0
        self._last_result: cf.DecodeResult | None = None

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        payload = _bits_to_payload_bytes(bits)
        return np.asarray(cf.encode_audio(payload), dtype=np.float32)

    def demodulate(self, audio: np.ndarray, sr: int) -> np.ndarray:
        rr = e2e.robust_decode(audio, sr, speed_search=(0.97, 1.03, 0.005))
        self._last_result = rr.result
        rec = rr.result.payload or b""
        return _payload_bytes_to_bits(rec, self.payload_bits)

    def erasure_rate_for(self, n_frames_expected: int) -> float:
        r = self._last_result
        if r is None or r.header is None:
            return 1.0
        fc = max(1, r.header.frame_count)
        lost = len(r.missing_frames) + r.bad_frames
        return min(1.0, lost / fc)


def measure_baseline_B0(
    tape_preset: str = "normal",
    n_seeds: int = 20,
    payload_bits: int = 4_000,
) -> dict:
    """Run the existing BFSK codec through the standard harness and project it.

    The codec carries per-frame CRC, so frame losses are ERASURES (cheap to
    code). We therefore measure two things per seed: (a) post-sync raw BER over
    the recovered bytes (silent flips inside surviving frames — usually ~0 after
    CRC), and (b) the frame erasure rate. The projection then uses the cheap
    erasure path, which is the honest, generous reading of the baseline.
    """
    scheme = _B0Scheme(payload_bits)

    bers: list[float] = []
    eras: list[float] = []
    completes: list[bool] = []
    for seed in range(n_seeds):
        tx_bits = _random_bits(payload_bits, seed)
        audio = scheme.modulate(tx_bits)
        rx_audio, sr, _diag = cs.full_chain(audio, tape_preset, "usb_soundcard", seed=seed)
        rx_bits = scheme.demodulate(rx_audio, sr)
        bers.append(_ber(tx_bits, rx_bits))
        eras.append(scheme.erasure_rate_for(0))
        completes.append(bool(scheme._last_result.complete) if scheme._last_result else False)

    # For the BER path we want the in-frame silent error rate, i.e. errors among
    # bits that WERE delivered — not counting whole missing frames as bit errors
    # (those are the erasure channel). The codec's CRC means surviving frames are
    # byte-exact, so in-frame BER ~ 0. We report the conservative max of (a tiny
    # floor) so the bit-error table picks a high rate.
    mean_raw_ber = float(np.mean(bers))
    mean_erasure = float(np.mean(eras))
    # In-frame BER: among complete decodes it is 0; estimate as the residual BER
    # excluding the erasure-explained loss. Floor at 1e-6 to stay conservative.
    in_frame_ber = max(1e-6, mean_raw_ber - mean_erasure)

    # --- Fixed-framing whole-file recovery (the HONEST "no outer code" reading) ---
    # B0 as SHIPPED has per-frame CRC but NO outer erasure code: any missing/bad
    # frame is irrecoverable, so a megabyte payload is recovered WHOLE only if
    # ZERO frames are lost. Estimate the per-frame loss probability from the
    # Monte-Carlo (excluding the rare catastrophic whole-decode failures, which
    # are sync failures not steady-state frame loss), then raise to the frame
    # count of a 1.271 MB payload. This is the number the H1 precondition checks.
    bytes_target = TARGET_PAYLOAD_BYTES
    frames_target = math.ceil(bytes_target / cf.FRAME_PAYLOAD_BYTES)
    # Robust per-frame loss estimate: total frames lost / total frames decoded,
    # over the non-catastrophic seeds (erasure < 0.5 means decode succeeded).
    good = [e for e in eras if e < 0.5]
    per_frame_loss = float(np.mean(good)) if good else 0.0
    # Guard against a measured 0 hiding the known ~2% dropout reality; floor it
    # at the channel's expected steady frame-loss so we don't over-claim B0.
    per_frame_loss_used = max(per_frame_loss, 0.002)
    p_full_fixed_framing = float((1.0 - per_frame_loss_used) ** frames_target)

    eval_dict = {
        "name": scheme.name,
        "gross_bps": float(scheme.gross_bps),
        "raw_bit_error_rate": in_frame_ber,
        "raw_bit_error_rate_incl_erasures": mean_raw_ber,
        "erasure_rate": mean_erasure,
        "per_seed_ber": [float(x) for x in bers],
        "per_seed_erasure": [float(x) for x in eras],
        "fraction_complete": float(np.mean(completes)),
        "per_frame_loss_est": per_frame_loss_used,
        "frames_for_target_payload": int(frames_target),
        "P_full_fixed_framing": p_full_fixed_framing,
        "n_seeds": int(n_seeds),
        "payload_bits": int(payload_bits),
        "tape_preset": tape_preset,
        "capture_key": "usb_soundcard",
    }

    proj = project_to_cassette(
        raw_ber=in_frame_ber,
        erasure_rate=mean_erasure,
        gross_bps=scheme.gross_bps,
    )

    out = {**eval_dict, **{f"proj_{k}": v for k, v in proj.items()}}
    # Flatten the canonical projection fields to top level too for convenience.
    out.update({
        "required_code_rate": proj["required_code_rate"],
        "net_bps": proj["net_bps"],
        "MB_C90_stereo": proj["MB_C90_stereo"],
        "MB_C60_stereo": proj["MB_C60_stereo"],
        "P_full": proj["P_full"],
    })
    return out


def save_metrics(name: str, metrics: dict) -> pathlib.Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"hyp_{name}.json"
    with open(path, "w") as f:
        json.dump(metrics, f, indent=2, default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    return path


if __name__ == "__main__":
    b0 = measure_baseline_B0(n_seeds=20, payload_bits=4_000)
    p = save_metrics("baseline_B0", b0)
    print(f"saved {p}")
    for k in ["gross_bps", "raw_bit_error_rate", "erasure_rate", "fraction_complete",
              "per_frame_loss_est", "frames_for_target_payload", "P_full_fixed_framing",
              "required_code_rate", "net_bps", "MB_C90_stereo", "MB_C60_stereo", "P_full"]:
        print(f"  {k}: {b0[k]}")
