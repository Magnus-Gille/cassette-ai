"""real_channel_sim.py — IMPROVED cassette channel that reproduces the REAL
acoustic loop, closing the sim/real gap documented in docs/REAL_CHANNEL.md.

`src/channel.py::cassette_channel` (FROZEN — do not edit) models band-limit +
wow/flutter + AWGN + dropouts + speed. It does NOT model the terms that actually
floor short-symbol modems on real audio:

  1. DIFFUSE reverb / room-IR / AAC re-quant leakage  -> a flat ~25% cross-bin
     contamination floor that does NOT shrink with symbol length (the hard limit).
  2. Calibrated HF rolloff from the measured H(f)      -> high tones ~10-20x weaker.
  3. ADJACENT-symbol ISI smear (a short reverb tail)   -> ~11% (M16) -> ~5% (M32)
     into +/-1 bins; SHRINKS with symbol length (modeled as fixed TIME, not fraction).

This wrapper calls cassette_channel for the (frozen) physics it already does well,
then layers the three missing terms, parameterized from real_channel_params.json.

Calibration target (docs/REAL_CHANNEL.md / real_channel_params.json):
  off-tone leakage on a 1-bin-spaced K-of-M symbol, genie-aligned, EQ'd:
    M16/N=77 : ~0.374 total  (adjacent 0.112 + distant 0.240)
    M32/N=159: ~0.307 total  (adjacent 0.047 + distant 0.251)
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
from scipy import signal

import sys
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from channel import cassette_channel  # noqa: E402  (FROZEN — never edited here)

FS = 48_000
PARAMS_PATH = ROOT / "experiments" / "tape_v2" / "real_channel_params.json"


def load_params(path: pathlib.Path = PARAMS_PATH) -> dict:
    return json.loads(path.read_text())


def _smooth_db(H_db, win=5):
    """Smooth the measured H(f) so isolated deep measurement NULLS (e.g. -49 dB
    spikes) become the gentle MONOTONE rolloff that the physical channel actually
    has. A sharp FIR notch + the decoder's 1e-3-clipped EQ would otherwise
    amplify transition-band ringing by ~1000x — a sim artifact, not real physics.
    We keep the overall HF rolloff (the calibration target) but drop the spikes."""
    H_db = np.asarray(H_db, float)
    k = np.ones(win) / win
    sm = np.convolve(np.pad(H_db, win, mode="edge"), k, mode="same")[win:-win]
    return sm


def _hf_fir(freqs_hz, H_db, fs=FS, ntaps=129):
    """FIR whose magnitude follows the (smoothed) measured H(f) rolloff."""
    freqs_hz = np.asarray(freqs_hz, float)
    H_db = _smooth_db(H_db)
    nyq = fs / 2.0
    f = np.concatenate([[0.0], freqs_hz, [nyq]])
    g = np.concatenate([[H_db[0]], H_db, [H_db[-1]]])
    g = 10.0 ** ((g - g.max()) / 20.0)
    f, idx = np.unique(f, return_index=True)
    g = g[idx]
    fn = f / nyq
    return signal.firwin2(ntaps, fn, g)


def _reverb_ir(tau_ms, g_diffuse, fs=FS, seed=12345, length_ms=40.0):
    """Direct path (delta) + exponentially-decaying DIFFUSE (white) tail.

    The white tail is frequency-FLAT: it smears energy uniformly across ALL bins,
    producing the length-independent ~25% distant-bin floor. g_diffuse sets its
    total energy relative to the direct path; we calibrate it (calibrate_diffuse)
    so distant-bin leakage on a 1-bin multitone matches the measured ~0.25.
    """
    tau = max(tau_ms, 1e-3) * fs / 1000.0
    L = int(length_ms * fs / 1000.0)
    n = np.arange(L)
    rg = np.random.default_rng(seed)
    tail = np.exp(-n / tau) * rg.standard_normal(L)
    tail[0] = 0.0
    e = np.sqrt(np.sum(tail**2)) + 1e-12
    tail = tail / e * g_diffuse  # tail energy = g_diffuse^2 of direct path
    ir = tail.copy()
    ir[0] = 1.0                  # direct path
    return ir


def real_channel(
    x: np.ndarray,
    *,
    params: dict | None = None,
    capture: str = "master3",          # "master3" (tape) or "master2" (voicememo/AAC)
    symbol_len: int | None = None,      # samples/symbol -> drives ISI smear strength
    snr_db: float | None = None,
    seed_offset: int = 0,
    add_reverb: bool = True,
    add_hf: bool = True,
    add_isi: bool = True,
) -> np.ndarray:
    """Push x through the FROZEN cassette_channel, then add the measured
    real-channel terms (diffuse reverb, calibrated HF rolloff, adjacent-symbol ISI).

    Set add_reverb/add_hf/add_isi=False to recover (approximately) the OLD sim.
    """
    if params is None:
        params = load_params()
    x = np.asarray(x, dtype=np.float64)

    sim0 = params.get("_sim", {})
    # The REAL decode pipeline removes BULK wow/flutter via the global chirp
    # resample + per-symbol timing tracker; what reaches the symbol detector is a
    # small RESIDUAL. Driving the frozen channel at the full measured flutter
    # (0.3-0.4%) here would double-count it and (because a fixed-grid genie cannot
    # follow cumulative drift over many long symbols) spuriously punish LONG
    # symbols. We therefore apply the measured-but-post-sync RESIDUAL flutter.
    flutter_full = params["flutter_wrms_pct"][capture] / 100.0
    residual_frac = sim0.get("flutter_residual_frac", 0.15)
    flutter = flutter_full * residual_frac
    snr = snr_db if snr_db is not None else params["snr_db"][f"median_{capture}"]

    # 1) frozen physics: band-limit + (residual) wow/flutter + AWGN + speed
    y = cassette_channel(
        x, fs=FS, snr_db=float(snr),
        wow_flutter_wrms=float(flutter),
        bandwidth_hz=12_000.0,
        seed_offset=seed_offset,
    )

    # 2) calibrated HF rolloff from the measured H(f)
    if add_hf:
        Hf = params["Hf_magnitude"]
        freqs = Hf[f"sounder_freqs_{capture}"]
        H_db = Hf[f"H_db_{capture}"]
        fir = _hf_fir(freqs, H_db)
        y = signal.fftconvolve(y, fir, mode="same")

    sim = sim0

    # 3) ADJACENT-bin leakage — a SHORT reverb tail of FIXED length in SAMPLES.
    #    Because the tail length is fixed in TIME, a longer symbol spends a smaller
    #    FRACTION of its window corrupted, so this term SHRINKS with symbol length
    #    (reproduces the measured 0.112 M16 -> 0.047 M32 adjacent split). This is
    #    the FFT-skirt + adjacent-symbol smear into +/-1 bins.
    if add_isi:
        tau_short = sim.get("adj_tail_samples", 16.0)
        g_adj = sim.get("adj_gain", 0.50)
        L = int(6 * tau_short)
        n = np.arange(L)
        rg = np.random.default_rng(2000 + seed_offset)
        tail = np.exp(-n / tau_short) * rg.standard_normal(L)
        tail[0] = 0.0
        tail = tail / (np.sqrt(np.sum(tail**2)) + 1e-12) * g_adj
        ir = tail.copy(); ir[0] = 1.0
        y = signal.fftconvolve(y, ir, mode="full")[: len(x)]

    # 4) DIFFUSE floor — reverb tail + room/speaker/mic + AAC re-quant smearing
    #    energy across ALL bins. Modeled as a CONVOLUTIONAL diffuse tail (a short
    #    exponentially-decaying white IR), NOT additive noise. A convolutional tail
    #    re-injects a smeared copy of the SIGNAL into all bins, so:
    #      - its cross-bin leakage FRACTION is ~length-independent (matches the flat
    #        0.240 M16 ~ 0.251 M32 distant floor), and
    #      - a longer FFT still concentrates each true tone into a narrower bin,
    #        giving M32 the real processing-gain edge over the broadband smear.
    #    This reproduces "M32 survives where M16 does not" without an adversarial
    #    additive floor that would (wrongly) punish the tone-dense M32 grid.
    if add_reverb:
        g_diffuse = sim.get("diffuse_gain", 0.62)
        sc = params["spectral_contamination"]["scaling"]
        tau = max(sc["reverb_tail_tau_ms"], 1e-3) * FS / 1000.0
        L = int(8 * tau)
        n = np.arange(L)
        rg = np.random.default_rng(3000 + seed_offset)
        tail = np.exp(-n / tau) * rg.standard_normal(L)
        tail[0] = 0.0
        tail = tail / (np.sqrt(np.sum(tail**2)) + 1e-12) * g_diffuse
        ir = tail.copy(); ir[0] = 1.0
        y = signal.fftconvolve(y, ir, mode="full")[: len(x)]

    return y.astype(np.float64)


# ---------------------------------------------------------------------------
# Calibration helper: tune diffuse_gain so distant-bin leakage hits ~0.25
# ---------------------------------------------------------------------------
def measure_leakage(scheme, params, capture, seed_reps=8, isi=True):
    """Modulate random K-of-M symbols, push through real_channel, genie-align +
    EQ + measure off-tone / adjacent / distant leakage exactly like the real
    measurement in docs/REAL_CHANNEL.md (so numbers are comparable)."""
    N = scheme.samples_per_sym
    M = scheme.M
    bins = np.clip(scheme._bin_indices, 0, N // 2)
    Hf = params["Hf_magnitude"]
    freqs_meas = np.asarray(Hf[f"sounder_freqs_{capture}"], float)
    H_db = np.asarray(Hf[f"H_db_{capture}"], float)
    Hlin = 10.0 ** (np.interp(scheme.freqs, freqs_meas, H_db) / 20.0)
    Hlin = Hlin / (Hlin.max() + 1e-12)
    eq = np.clip(Hlin, 1e-3, None)

    rg = np.random.default_rng(7)
    off, adj, dist = [], [], []
    for rep in range(seed_reps):
        nsym = 40
        bits = rg.integers(0, 2, size=nsym * scheme.bits_per_sym, dtype=np.uint8)
        audio = scheme.modulate(bits)
        y = real_channel(audio, params=params, capture=capture,
                         symbol_len=N, seed_offset=rep, add_isi=isi)
        # locate data start via preamble
        import hyp_common as hc
        ds = hc.find_preamble(y.astype(np.float32), scheme.preamble_seconds)
        # ground-truth lit tones per symbol
        for s in range(nsym):
            si = scheme._bits_to_sym(bits[s * scheme.bits_per_sym:(s + 1) * scheme.bits_per_sym])
            lit = set(scheme._table[si].tolist())
            # genie align: best +/-15 offset maximizing lit-tone energy
            best_e = None
            for d in range(-15, 16):
                p = ds + s * N + d
                if p < 0 or p + N > len(y):
                    continue
                e = np.abs(np.fft.rfft(y[p:p + N], n=N))[bins] / eq
                score = e[list(lit)].sum()
                if best_e is None or score > best_e[0]:
                    best_e = (score, e)
            if best_e is None:
                continue
            e = best_e[1]
            tot = e.sum() + 1e-12
            lit_e = e[list(lit)].sum()
            off.append(1.0 - lit_e / tot)
            # adjacent: +/-1 bin of any lit tone (excluding lit tones themselves)
            adjset = set()
            for t in lit:
                for dd in (-1, 1):
                    if 0 <= t + dd < M and (t + dd) not in lit:
                        adjset.add(t + dd)
            adj.append(e[list(adjset)].sum() / tot if adjset else 0.0)
            distset = [i for i in range(M) if i not in lit and i not in adjset]
            dist.append(e[distset].sum() / tot)
    return {
        "offtone_median": float(np.median(off)),
        "adjacent_median": float(np.median(adj)),
        "distant_median": float(np.median(dist)),
    }
