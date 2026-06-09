"""eq_train_test.py — does TRAINING-BASED CHANNEL EQUALIZATION crack the
acoustic-channel decode wall?

The wall (see docs/REAL_CHANNEL.md, REAL_DECODE_FINDINGS.md): our real captures
decode 0/byte-exact. Limiter is NOT noise (~40 dB per-tone SNR) and NOT timing
(genie residual <1 symbol/frame). It is SPECTRAL CONTAMINATION: a ~25% diffuse,
length-INDEPENDENT off-tone-leakage floor with effective tail tau ~7.9 ms. A
symbol is ~3 ms, so this is INTER-SYMBOL INTERFERENCE from acoustic reverb
(room + speaker + mic) + AAC. Everything tried so far is per-tone MAGNITUDE EQ,
which cannot fix ISI.

HYPOTHESIS: a known training sequence at the start of the recording lets us
estimate the COMPLEX channel response H(f) (magnitude AND phase) and
EQUALIZE/deconvolve the reverb ISI. Reverb is linear convolution (invertible if
known); AAC-loss and deep spectral nulls are not.

This tool:
 1. ESTIMATES the complex channel from KNOWN training material in the recording:
    - the 64-tone Schroeder multitone sounder (deterministic tx phases) ->
      complex H(f) at 64 freqs (300-11000 Hz), the FULL tone band, WITH PHASE.
    - the global up-chirp (500-5000 Hz, fully known) -> time-domain impulse
      response h(t) via least-squares / matched-filter deconvolution (diagnostic
      + lower-band corroboration of the multitone estimate).
 2. EQUALIZES the captured data three ways and reports which wins:
    (a) frequency-domain complex MMSE EQ  W(f) = H*/(|H|^2 + eps), eps from the
        measured noise floor, applied per data-tone FFT bin (mag + PHASE).
    (b) a time-domain linear deconvolution FIR built from h(t) (MMSE-regularized),
        applied to the whole data window before tone detection.
    (c) magnitude-only EQ (the existing approach) as the BASELINE to beat.
    Equalization-amplified null bins (|H| below a threshold) are marked ERASURES.
 3. RE-MEASURES, per config (M16 from tape3, M32,K2 from master2):
    - off-tone leakage fraction (genie-aligned) BEFORE vs AFTER each EQ,
    - genie-ceiling byte-error, achievable (real tracker) byte-error,
    and attributes the residual floor (reverb-removed vs AAC/null-irreducible).

DECISIVE VERDICT: does training-based EQ bring M32,K2 (and/or M16) to RS-closable
on the ACHIEVABLE path (not just genie)? Or is there a hard residual?

Honesty rules: verify against the known sidecar bytes; genie is an upper bound;
the off-tone-leakage measurement is genie-ALIGNED so it is not a timing artifact;
if a residual AAC/null floor remains, quantify it.
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import correlate, resample_poly

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
_HERE = ROOT / "experiments" / "tape_v2"
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2", ROOT / "experiments" / "capacity",
           _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                       # noqa: E402
import analyze_master2 as am2                 # noqa: E402
import m3_codec as codec                      # noqa: E402
from d3d4_combo_tracked import make_tracked_combo  # noqa: E402
from c2_combo_mfsk import ComboMFSKScheme     # noqa: E402

SR = 48_000
RESULTS_DIR = _HERE / "results"
WINDOW_PAD = 0.30
TRACK = 15
CENTER_BIAS = 0.02

# Schroeder multitone params (MUST mirror make_master2._build_sounder / _schroeder_multitone)
SOUNDER_FREQS = np.round(np.geomspace(300, 11000, 64)).astype(int)
SOUNDER_AMP = 0.60
GLOBAL_CHIRP_T = 0.20
GLOBAL_CHIRP_F0 = 500.0
GLOBAL_CHIRP_F1 = 5000.0


# ===========================================================================
# Known-reference reconstruction (the training material)
# ===========================================================================
def schroeder_reference(dur_s: float) -> np.ndarray:
    """Reconstruct the EXACT transmitted Schroeder multitone (pre-fade core).

    Mirrors make_master2._schroeder_multitone: x = sum_k sin(2pi f_k t + ph_k),
    ph_k = pi k (k+1) / K, then normalized to unit peak. Used as the tx reference
    for complex H(f) = Y(f)/X(f) estimation. We return the NORMALIZED core (no
    fade, no amp) — the amplitude/scale cancels in the bin-ratio estimate."""
    n = int(dur_s * SR)
    t = np.arange(n) / SR
    K = len(SOUNDER_FREQS)
    x = np.zeros(n)
    for k, f in enumerate(SOUNDER_FREQS):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    return x


def global_chirp_reference(up: bool = True) -> np.ndarray:
    from scipy.signal import chirp as _chirp
    n = int(GLOBAL_CHIRP_T * SR)
    t = np.arange(n) / SR
    f0, f1 = ((GLOBAL_CHIRP_F0, GLOBAL_CHIRP_F1) if up
              else (GLOBAL_CHIRP_F1, GLOBAL_CHIRP_F0))
    return _chirp(t, f0=f0, f1=f1, t1=GLOBAL_CHIRP_T, method="linear")


# ===========================================================================
# 1. Complex channel estimation
# ===========================================================================
def estimate_Hf_complex(audio_nom, manifest, sync):
    """Estimate COMPLEX H(f) at the 64 sounder freqs (magnitude AND phase) from
    the known Schroeder multitone. Averages the two multitone reps.

    Method: grab the recorded multitone (trim fades), reconstruct the EXACT tx
    reference, and at each tone freq take the single-bin DFT of both rx and tx at
    that exact frequency (Goertzel-style projection — robust to bin straddling
    since the tones are not on the FFT grid of an arbitrary window). The complex
    ratio rx/tx is H(f) including the channel phase. The tx reference's own phase
    (Schroeder) is divided out, so the estimate is the TRUE channel transfer.

    Also returns the per-tone noise-floor magnitude for MMSE eps.
    """
    align = sync["chirp0_nominal"] - sync["expected_chirp0"]
    mts = [s for s in manifest["sounder_sections"] if s["kind"] == "multitone"]
    noise = next((s for s in manifest["sounder_sections"] if s["kind"] == "noisefloor"), None)
    freqs = SOUNDER_FREQS.astype(np.float64)

    H_acc = np.zeros(len(freqs), dtype=np.complex128)
    H_per_rep = []
    n_used = 0
    for mt in mts:
        st = mt["start"] + align
        ln = mt["length"]
        trim = int(0.3 * SR)
        rx = np.asarray(audio_nom[st + trim: st + ln - trim], dtype=np.float64)
        if rx.size < SR:
            continue
        # reconstruct tx reference of the SAME duration (full section), then trim
        # identically so rx and tx are sample-aligned in the steady region.
        tx_full = schroeder_reference(ln / SR)
        tx = tx_full[trim: ln - trim]
        m = min(len(rx), len(tx))
        rx, tx = rx[:m], tx[:m]
        t = np.arange(m) / SR
        Hr = np.zeros(len(freqs), dtype=np.complex128)
        for i, f in enumerate(freqs):
            ph = np.exp(-1j * 2 * np.pi * f * t)
            X = np.sum(tx * ph)
            Y = np.sum(rx * ph)
            if abs(X) > 1e-9:
                Hr[i] = Y / X
        H_acc += Hr
        H_per_rep.append(Hr)
        n_used += 1
    H = H_acc / max(1, n_used)

    # per-tone noise floor magnitude (for MMSE eps): project the silence section
    nf_mag = None
    if noise is not None:
        st = noise["start"] + align
        ln = noise["length"]
        trim = int(0.3 * SR)
        nseg = np.asarray(audio_nom[st + trim: st + ln - trim], dtype=np.float64)
        if nseg.size > SR:
            m = len(nseg)
            t = np.arange(m) / SR
            mags = []
            for f in freqs:
                ph = np.exp(-1j * 2 * np.pi * f * t)
                mags.append(abs(np.sum(nseg * ph)) / m)
            # scale to same projection normalization as H (H uses full-sum, not /m)
            nf_mag = np.asarray(mags) * m  # crude; only the RATIO to |H| matters
    return {
        "freqs": freqs,
        "H_complex": H,
        "H_mag": np.abs(H),
        "H_phase": np.angle(H),
        "noise_mag": nf_mag,
        "n_reps": n_used,
        "H_per_rep": H_per_rep,
    }


def channel_stability(chan):
    """THE load-bearing test for the equalization hypothesis.

    A linear time-invariant reverb has a FIXED complex H(f): two probes of the
    same channel must yield the SAME H(f) (magnitude AND phase). We have two
    multitone reps ~4 s apart. If their H(f) phase agrees, the channel is LTI and
    a single trained H(f) can equalize the data (deconvolve the reverb). If the
    phase does NOT reproduce, the channel is time-varying (flutter phase jitter +
    AAC frame-dependent nonlinearity) and NO single trained H(f) can invert it —
    which is the conclusive reason training-based EQ cannot work here.

    We remove a best-fit bulk delay (linear phase ramp) between reps first, so a
    mere sub-sample timing offset between probes is NOT mistaken for instability.
    """
    reps = chan.get("H_per_rep") or []
    if len(reps) < 2:
        return {"available": False}
    freqs = chan["freqs"]
    H0, H1 = reps[0], reps[1]
    # remove best-fit linear phase (a constant inter-rep delay) before judging
    dphase = np.unwrap(np.angle(H1 / (H0 + 1e-12)))
    A = np.vstack([freqs, np.ones_like(freqs)]).T
    coef, *_ = np.linalg.lstsq(A, dphase, rcond=None)
    delay_samples = float(coef[0] / (2 * np.pi) * SR)
    resid = (dphase - A @ coef + np.pi) % (2 * np.pi) - np.pi
    # coherence after delay-align (1=perfectly stable phase, 0=random)
    H1d = H1 * np.exp(-1j * (A @ coef))
    coh = np.abs((H0 + H1d) / 2) / ((np.abs(H0) + np.abs(H1d)) / 2 + 1e-12)
    mag_ratio = np.abs(H1) / (np.abs(H0) + 1e-12)
    return {
        "available": True,
        "interrep_delay_samples": delay_samples,
        "phase_diff_deg_median_raw": float(np.degrees(np.median(np.abs(
            (np.angle(H1 / (H0 + 1e-12)) + np.pi) % (2 * np.pi) - np.pi)))),
        "phase_diff_deg_median_after_delay": float(np.degrees(np.median(np.abs(resid)))),
        "phase_diff_deg_p90_after_delay": float(np.degrees(np.percentile(np.abs(resid), 90))),
        "phase_coherence_median": float(np.median(coh)),
        "mag_ratio_median": float(np.median(mag_ratio)),
        "verdict": ("LTI-stable (equalizable)"
                    if float(np.degrees(np.median(np.abs(resid)))) < 20.0
                    else "TIME-VARYING (NOT equalizable by a single trained H(f))"),
    }


def estimate_ht_from_chirp(audio_nom, manifest, sync, n_taps=512):
    """Time-domain impulse response h(t) from the known global up-chirp via
    MMSE/least-squares deconvolution. Diagnostic + lower-band corroboration
    (chirp only covers 500-5000 Hz). Returns h (n_taps) and its energy decay."""
    c0 = sync["chirp0_nominal"]
    up = global_chirp_reference(up=True)
    L = len(up)
    # grab a window around chirp0 generously (chirp + reverb tail)
    lo = max(0, c0 - 64)
    hi = min(len(audio_nom), c0 + L + n_taps + 64)
    rx = np.asarray(audio_nom[lo:hi], dtype=np.float64)
    # fine-align: matched filter of rx vs up
    corr = np.abs(correlate(rx, up, mode="valid"))
    pk = int(np.argmax(corr))
    # Matched-filter IR estimate: xcorr(rx, up). The chirp's autocorrelation is
    # nearly a delta over 500-5000 Hz, so xcorr(rx, up) ~= h * autocorr(up) ~= h
    # (band-limited). This is far more robust than a full Wiener inversion, which
    # is noise-dominated outside the chirp band. Gives the magnitude ENVELOPE of
    # the impulse response (the reverb-tail decay) for the lower band.
    seg = rx[pk: pk + L + n_taps]
    if len(seg) < L + n_taps:
        seg = np.concatenate([seg, np.zeros(L + n_taps - len(seg))])
    xc = correlate(seg, up, mode="valid")
    xc = xc / (np.max(np.abs(xc)) + 1e-12)
    h = xc[:n_taps]
    energy = h ** 2
    pk_i = int(np.argmax(energy))
    energy = energy[pk_i:]
    main_lobe = energy[:11].sum()   # +/-5 samples around the main peak
    tail = energy[6:]               # beyond the main lobe
    tau_samples = None
    decay = {}
    if tail.sum() > 0:
        ctail = np.cumsum(tail) / tail.sum()
        idx = int(np.searchsorted(ctail, 1 - 1 / np.e))
        tau_samples = idx + 1
        for ms in (1, 2, 4, 8):
            n = int(ms / 1000 * SR)
            if n - 1 < len(ctail):
                decay[f"cum_tail_energy_by_{ms}ms"] = float(ctail[n - 1])
    return {
        "h": h,
        "main_lobe_frac": float(main_lobe / (energy.sum() + 1e-12)),
        "tail_frac": float(tail.sum() / (energy.sum() + 1e-12)),
        "tau_samples_chirp": tau_samples,
        "tau_ms_chirp": (tau_samples / SR * 1e3) if tau_samples else None,
        "tail_energy_decay": decay,
    }


# ===========================================================================
# Per-tone complex EQ weights for a given scheme, from H(f)
# ===========================================================================
def tone_eq_weights(scheme_freqs, chan, mode="mmse_complex", null_db=-30.0):
    """Build per-data-tone equalizer weights from the estimated channel.

    mode:
      'mmse_complex' : W = H*/(|H|^2 + eps)  (mag + PHASE), eps from noise floor.
      'mag_only'     : W = 1/|H| (the existing approach; PHASE NOT corrected).
      'none'         : W = 1 (raw, no EQ).
    Returns (W complex per tone, erasure mask: True where bin is a deep null and
    EQ would amplify noise/contamination -> mark as erasure).
    """
    freqs = np.asarray(scheme_freqs, dtype=np.float64)
    Hf = np.interp(freqs, chan["freqs"], chan["H_complex"].real) \
        + 1j * np.interp(freqs, chan["freqs"], chan["H_complex"].imag)
    Hmag = np.abs(Hf)
    Hmag_n = Hmag / (Hmag.max() + 1e-12)
    # eps for MMSE: (noise / signal)^2 per tone, floored
    if chan.get("noise_mag") is not None:
        nf = np.interp(freqs, chan["freqs"], chan["noise_mag"])
        eps = (nf / (chan["H_mag"].max() + 1e-12)) ** 2
        eps = np.maximum(eps, 1e-4)
    else:
        eps = np.full(len(freqs), 1e-3)

    null_thresh = 10 ** (null_db / 20.0)
    erasure = Hmag_n < null_thresh

    if mode == "none":
        W = np.ones(len(freqs), dtype=np.complex128)
    elif mode == "mag_only":
        W = 1.0 / np.maximum(Hmag, Hmag.max() * 1e-3)
        W = W.astype(np.complex128)
    elif mode == "mmse_complex":
        Hn = Hf / (Hmag.max() + 1e-12)
        W = np.conj(Hn) / (np.abs(Hn) ** 2 + eps)
    else:
        raise ValueError(mode)
    # normalize so the strongest tone has unit weight (keeps detection scale sane)
    W = W / (np.max(np.abs(W)) + 1e-12)
    return W, erasure, Hmag_n


# ===========================================================================
# Tone detection with complex EQ
# ===========================================================================
def tone_complex(seg, freqs, N):
    """Complex single-bin projection (Goertzel) of seg at each tone freq.
    Returns complex amplitudes (so phase EQ is meaningful)."""
    if len(seg) < N:
        if len(seg) < N // 2:
            return None
        seg = np.concatenate([seg, np.zeros(N - len(seg))])
    seg = seg[:N]
    t = np.arange(N) / SR
    out = np.empty(len(freqs), dtype=np.complex128)
    for i, f in enumerate(freqs):
        out[i] = np.sum(seg * np.exp(-1j * 2 * np.pi * f * t))
    return out


def eq_energies(cplx, W, erasure):
    """Apply complex EQ then return |.|^2 energies; erasure bins set to 0 so they
    never win the top-K. Returns (energies, eq'd complex)."""
    if cplx is None:
        return None
    z = cplx * W
    e = np.abs(z) ** 2
    e = e.copy()
    e[erasure] = 0.0
    return e


# ===========================================================================
# Leakage measurement (genie-aligned) BEFORE/AFTER EQ
# ===========================================================================
def measure_leakage(win, dstart, N, freqs, lit_per_sym, K, W, erasure, track=TRACK):
    """For each symbol whose lit tones are KNOWN (lit_per_sym), genie-align to the
    +/-track offset that best concentrates energy on the lit tones (NOT a timing
    artifact), then measure off-tone leakage = 1 - (energy in lit) / total.
    Also split adjacent (+/-1 bin) vs distant. Returns medians."""
    leaks, adj, dist = [], [], []
    drift = 0.0
    for s, lit in enumerate(lit_per_sym):
        base = dstart + s * N + int(round(drift))
        best = None
        for d in range(-track, track + 1):
            seg = win[base + d: base + d + N]
            c = tone_complex(seg, freqs, N)
            if c is None:
                continue
            e = eq_energies(c, W, erasure)
            litE = e[list(lit)].sum()
            tot = e.sum() + 1e-12
            score = litE / tot
            if best is None or score > best[0]:
                best = (score, d, e)
        if best is None:
            continue
        _, d, e = best
        drift += d
        tot = e.sum() + 1e-12
        litE = e[list(lit)].sum()
        leaks.append(1.0 - litE / tot)
        # adjacent: +/-1 index of any lit tone (excluding lit themselves)
        adj_idx = set()
        for L in lit:
            for dd in (-1, 1):
                j = L + dd
                if 0 <= j < len(freqs) and j not in lit:
                    adj_idx.add(j)
        adjE = e[list(adj_idx)].sum() if adj_idx else 0.0
        distE = tot - litE - adjE
        adj.append(adjE / tot)
        dist.append(distE / tot)
    if not leaks:
        return None
    return {
        "offtone_leakage_median": float(np.median(leaks)),
        "adjacent_leakage_median": float(np.median(adj)),
        "distant_leakage_median": float(np.median(dist)),
        "n_symbols": len(leaks),
    }


# ===========================================================================
# Tracked / genie demod with complex EQ
# ===========================================================================
def _lock_score(e, K):
    srt = np.sort(e)[::-1]
    return float((srt[K - 1] - srt[K]) / (srt[0] + 1e-9))


def demod_section(win, dstart, nsym, freqs, N, K, rev_table, cap, W, erasure,
                  genie_syms=None, track=TRACK):
    """Tracked sweep with complex EQ. genie_syms -> oracle-timed ceiling."""
    drift = 0.0
    out = []
    for s in range(nsym):
        base = dstart + s * N + int(round(drift))
        best = None
        fb = None
        for d in range(-track, track + 1):
            seg = win[base + d: base + d + N]
            c = tone_complex(seg, freqs, N)
            if c is None:
                continue
            e = eq_energies(c, W, erasure)
            tk = tuple(sorted(np.argpartition(e, -K)[-K:].tolist()))
            si = min(rev_table.get(tk, 0), cap - 1)
            if fb is None:
                fb = si
            if genie_syms is not None:
                if si == genie_syms[s] and (best is None or abs(d) < best[0]):
                    best = (abs(d), d, si)
            else:
                lock = _lock_score(e, K) * (1.0 - CENTER_BIAS * abs(d))
                if best is None or lock > best[0]:
                    best = (lock, d, si)
        if best is None:
            out.append(fb if fb is not None else 0)
            continue
        drift += best[1]
        out.append(best[2])
    return out


def find_dstart(win, pre):
    c = np.abs(correlate(np.asarray(win, np.float64), pre, mode="valid"))
    return int(np.argmax(c)) + len(pre)



# ===========================================================================
# Per-config evaluation: builds known lit-tone sequence, runs leakage + BER
# for each EQ mode, for both genie and achievable paths.
# ===========================================================================
EQ_MODES = ["none", "mag_only", "mmse_complex"]


def _bits_to_syms(tb, bps, nsym):
    syms = []
    for i in range(nsym):
        chunk = tb[i * bps:(i + 1) * bps]
        if len(chunk) < bps:
            chunk = list(chunk) + [0] * (bps - len(chunk))
        syms.append(int("".join(map(str, np.asarray(chunk, int))), 2))
    return syms


def eval_m16_tape3(audio_nom, manifest, align, chan):
    """M16,K2 on tape3. Uses the robust rung's RS frames; ground truth from the
    sidecar via codec.encode_payload. Measures leakage + genie/achievable byte-ER
    per EQ mode on the test2k_robust payload (17 frames, manageable + decisive)."""
    sch = make_tracked_combo(16, 2)
    N, bps, K = sch.samples_per_sym, sch.bits_per_sym, sch.K
    freqs = np.asarray(sch.freqs, dtype=np.float64)
    table = sch._table
    rev, cap = sch._rev_table, sch._sym_cap
    pre = hc.make_preamble(sch.preamble_seconds).astype(np.float64)

    sec = next(p for p in manifest["payloads"] if p["name"] == "test2k_robust")
    rung = codec.RUNGS_BY_NAME[sec["rung"]]
    import dataclasses
    if sec["meta"].get("frame_bytes"):
        rung = dataclasses.replace(rung, frame_bytes=int(sec["meta"]["frame_bytes"]))
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    tx_frames, _ = codec.encode_payload(expected, rung)
    starts = sec["frame_starts"]
    meta = sec["meta"]
    n_frames = meta["n_frames"]
    pad = int(WINDOW_PAD * SR)

    res = {"config": "M16_K2_tape3", "N": N, "bin_hz": round(SR / N, 1),
           "M": 16, "K": 2, "payload": sec["name"], "n_frames": n_frames,
           "modes": {}}
    for mode in EQ_MODES:
        W, erasure, Hmag_n = tone_eq_weights(freqs, chan, mode=mode)
        n_eras = int(erasure.sum())
        all_leak, all_adj, all_dist = [], [], []
        frames_bits, genie_bits = [], []
        raw_err = raw_tot = gen_err = 0
        for fi in range(n_frames):
            tb = np.asarray(tx_frames[fi], dtype=np.uint8)
            nbits = len(tb)
            nsym = int(np.ceil(nbits / bps))
            flen = len(pre) + nsym * N
            st = starts[fi] + align
            w_lo = max(0, st - pad)
            w_hi = min(len(audio_nom), st + flen + pad)
            win = np.asarray(audio_nom[w_lo:w_hi], dtype=np.float64)
            dstart = find_dstart(win, pre)
            syms_true = _bits_to_syms(tb, bps, nsym)
            lit_per_sym = [table[min(si, cap - 1)] for si in syms_true]
            # leakage (genie-aligned) on first few frames only (enough symbols)
            if fi < 4:
                lk = measure_leakage(win, dstart, N, freqs, lit_per_sym, K, W, erasure)
                if lk:
                    all_leak.append(lk["offtone_leakage_median"])
                    all_adj.append(lk["adjacent_leakage_median"])
                    all_dist.append(lk["distant_leakage_median"])
            # achievable
            syms = demod_section(win, dstart, nsym, freqs, N, K, rev, cap, W, erasure)
            rb = np.array([b for si in syms for b in
                           [(si >> (bps - 1 - j)) & 1 for j in range(bps)]],
                          dtype=np.uint8)[:nbits]
            m = min(len(tb), len(rb))
            raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (nbits - m)
            frames_bits.append(rb)
            # genie
            gsyms = demod_section(win, dstart, nsym, freqs, N, K, rev, cap, W,
                                  erasure, genie_syms=syms_true)
            gb = np.array([b for si in gsyms for b in
                           [(si >> (bps - 1 - j)) & 1 for j in range(bps)]],
                          dtype=np.uint8)[:nbits]
            gm = min(len(tb), len(gb))
            gen_err += int(np.count_nonzero(tb[:gm] != gb[:gm])) + (nbits - gm)
            genie_bits.append(gb)
            raw_tot += nbits

        recovered = codec.decode_payload(frames_bits, meta)
        raw_exact = recovered == expected
        raw_byte_err = sum(a != b for a, b in zip(recovered, expected)) + abs(len(recovered) - len(expected))
        grec = codec.decode_payload(genie_bits, meta)
        gen_exact = grec == expected
        gen_byte_err = sum(a != b for a, b in zip(grec, expected)) + abs(len(grec) - len(expected))
        res["modes"][mode] = {
            "n_erasures": n_eras,
            "offtone_leakage_median": float(np.median(all_leak)) if all_leak else None,
            "adjacent_leakage_median": float(np.median(all_adj)) if all_adj else None,
            "distant_leakage_median": float(np.median(all_dist)) if all_dist else None,
            "raw_ber": raw_err / max(1, raw_tot),
            "genie_ber": gen_err / max(1, raw_tot),
            "raw_byte_err": raw_byte_err, "raw_byte_exact": bool(raw_exact),
            "genie_byte_err": gen_byte_err, "genie_byte_exact": bool(gen_exact),
            "payload_bytes": len(expected),
        }
    return res


# --- master2 M32,K2 evaluation (uses modem tx_bits, self-contained slices) ---
_QUOTE = "The quick cassette plays on. "
_PAD_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _make_payload(config, rep):
    prefix = f"CASSETTE-AI v2 | {config} rep{rep:03d} | "
    filler = (_QUOTE + _PAD_CHARS) * 4
    raw = (prefix + filler)[:96]
    return raw.ljust(96)[:96].encode("ascii")


def eval_m32_master2(audio_nom, manifest, align, chan, reps_to_use=12):
    """M32,K2 (c2_m32_k2) on master2. Self-contained slices; ground truth from
    modems_combo.tx_bits. Measures leakage + genie/achievable byte-ER per EQ mode,
    aggregated over reps. RS-closability judged on the byte-error rate."""
    import modems_combo as mc
    sch = ComboMFSKScheme(M=32, K=2, preamble_seconds=0.25)
    N, bps, K = sch.samples_per_sym, sch.bits_per_sym, sch.K
    freqs = np.asarray(sch.freqs, dtype=np.float64)
    table = sch._table
    rev, cap = sch._rev_table, sch._sym_cap
    pre = np.asarray(hc.make_preamble(0.25), dtype=np.float64)
    pad = int(WINDOW_PAD * SR)

    secs = [s for s in manifest["sections"] if s["config"] == "c2_m32_k2"]
    secs = sorted(secs, key=lambda s: s["rep"])[:reps_to_use]

    res = {"config": "M32_K2_master2", "N": N, "bin_hz": round(SR / N, 1),
           "M": 32, "K": 2, "n_reps": len(secs), "modes": {}}
    for mode in EQ_MODES:
        W, erasure, Hmag_n = tone_eq_weights(freqs, chan, mode=mode)
        n_eras = int(erasure.sum())
        all_leak, all_adj, all_dist = [], [], []
        raw_err = raw_tot = gen_err = 0
        raw_byte_err = gen_byte_err = byte_tot = 0
        for sec in secs:
            rep = sec["rep"]
            payload = _make_payload("c2_m32_k2", rep)
            tb = np.asarray(mc.tx_bits(payload, "c2_m32_k2"), dtype=np.uint8)
            nbits = len(tb)
            nsym = int(np.ceil(nbits / bps))
            st = sec["start_sample"] + align
            flen = sec["length"]
            w_lo = max(0, st - pad)
            w_hi = min(len(audio_nom), st + flen + pad)
            win = np.asarray(audio_nom[w_lo:w_hi], dtype=np.float64)
            if len(win) < N * 4:
                continue
            dstart = find_dstart(win, pre)
            syms_true = _bits_to_syms(tb, bps, nsym)
            lit_per_sym = [table[min(si, cap - 1)] for si in syms_true]
            lk = measure_leakage(win, dstart, N, freqs, lit_per_sym, K, W, erasure)
            if lk:
                all_leak.append(lk["offtone_leakage_median"])
                all_adj.append(lk["adjacent_leakage_median"])
                all_dist.append(lk["distant_leakage_median"])
            nbytes = nbits // 8
            tb_bytes = np.packbits(tb[:nbytes * 8])
            # achievable
            syms = demod_section(win, dstart, nsym, freqs, N, K, rev, cap, W, erasure)
            rb = np.array([b for si in syms for b in
                           [(si >> (bps - 1 - j)) & 1 for j in range(bps)]],
                          dtype=np.uint8)[:nbits]
            m = min(len(tb), len(rb))
            raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (nbits - m)
            rb_bytes = np.packbits(rb[:nbytes * 8])
            raw_byte_err += int(np.count_nonzero(tb_bytes != rb_bytes))
            # genie
            gsyms = demod_section(win, dstart, nsym, freqs, N, K, rev, cap, W,
                                  erasure, genie_syms=syms_true)
            gb = np.array([b for si in gsyms for b in
                           [(si >> (bps - 1 - j)) & 1 for j in range(bps)]],
                          dtype=np.uint8)[:nbits]
            gm = min(len(tb), len(gb))
            gen_err += int(np.count_nonzero(tb[:gm] != gb[:gm])) + (nbits - gm)
            gb_bytes = np.packbits(gb[:nbytes * 8])
            gen_byte_err += int(np.count_nonzero(tb_bytes != gb_bytes))
            raw_tot += nbits
            byte_tot += nbytes
        raw_byte_er = raw_byte_err / max(1, byte_tot)
        gen_byte_er = gen_byte_err / max(1, byte_tot)
        res["modes"][mode] = {
            "n_erasures": n_eras,
            "offtone_leakage_median": float(np.median(all_leak)) if all_leak else None,
            "adjacent_leakage_median": float(np.median(all_adj)) if all_adj else None,
            "distant_leakage_median": float(np.median(all_dist)) if all_dist else None,
            "raw_ber": raw_err / max(1, raw_tot),
            "genie_ber": gen_err / max(1, raw_tot),
            "raw_byte_err_rate": raw_byte_er,
            "genie_byte_err_rate": gen_byte_er,
            # RS(255,127) robust rung corrects ~0.251 byte-error fraction.
            "raw_rs_closable": bool(raw_byte_er < 0.18),
            "genie_rs_closable": bool(gen_byte_er < 0.18),
        }
    return res


# ===========================================================================
# main
# ===========================================================================
def _load_nominal(path, manifest):
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    return audio_nom, sync, align


def main():
    out = {"_about": "Training-based complex-channel equalization vs the acoustic "
           "ISI/leakage wall. Estimates complex H(f) from the known multitone "
           "sounder + h(t) from the global chirp, equalizes data tones (MMSE "
           "complex vs mag-only vs none), re-measures genie-aligned off-tone "
           "leakage + genie/achievable byte-error per config.",
           "_leakage_note": "Leakage here is measured with a COMPLEX Goertzel "
           "projection and a 'maximize lit-fraction' genie alignment, a tighter "
           "estimator than the FFT top-K measure in real_channel_params.json (so "
           "the absolute 'none' values run lower, e.g. M32 distant ~0.02 here vs "
           "~0.25 there). What is decisive is the DIRECTION: complex MMSE EQ "
           "RAISES leakage (does not remove it), confirming the trained H(f) is "
           "stale by the time the data plays.",
           "_decisive_metric": "channel_stability.phase_diff_deg_median_after_delay "
           "-- two sounder reps ~4s apart must give the SAME complex H(f) for a "
           "single trained EQ to invert the reverb. They do NOT (60-80 deg phase "
           "disagreement after removing a bulk delay), so the channel is "
           "time-varying and NOT equalizable by training."}

    # ----- M16,K2 on tape3 (master3) -----
    m3man = json.loads((_HERE / "master3_manifest.json").read_text())
    a3, s3, al3 = _load_nominal(_HERE / "captures" / "tape3_run1.wav", m3man)
    chan3 = estimate_Hf_complex(a3, m3man, s3)
    stab3 = channel_stability(chan3)
    ht3 = estimate_ht_from_chirp(a3, m3man, s3)
    print(f"[tape3] sync {s3['speed']:.4f}x align {al3:+d}; "
          f"chirp h(t): main-lobe {ht3['main_lobe_frac']:.3f}, "
          f"tail {ht3['tail_frac']:.3f}, tau~{ht3['tau_ms_chirp']} ms")
    print(f"[tape3] channel stability: inter-rep phase diff (after delay-align) "
          f"{stab3.get('phase_diff_deg_median_after_delay'):.1f} deg "
          f"-> {stab3.get('verdict')}")
    r_m16 = eval_m16_tape3(a3, m3man, al3, chan3)
    out["m16_tape3"] = r_m16
    out["m16_tape3"]["chirp_ht"] = {k: v for k, v in ht3.items() if k != "h"}
    out["m16_tape3"]["channel_stability"] = stab3
    _print_config(r_m16)

    # ----- M32,K2 on master2 (voicememo) -----
    m2man = json.loads((_HERE / "master2_manifest.json").read_text())
    a2, s2, al2 = _load_nominal(_HERE / "captures" / "voicememo_run1.wav", m2man)
    chan2 = estimate_Hf_complex(a2, m2man, s2)
    stab2 = channel_stability(chan2)
    ht2 = estimate_ht_from_chirp(a2, m2man, s2)
    print(f"[master2] sync {s2['speed']:.4f}x align {al2:+d}; "
          f"chirp h(t): main-lobe {ht2['main_lobe_frac']:.3f}, "
          f"tail {ht2['tail_frac']:.3f}, tau~{ht2['tau_ms_chirp']} ms")
    print(f"[master2] channel stability: inter-rep phase diff (after delay-align) "
          f"{stab2.get('phase_diff_deg_median_after_delay'):.1f} deg "
          f"-> {stab2.get('verdict')}")
    r_m32 = eval_m32_master2(a2, m2man, al2, chan2)
    out["m32_master2"] = r_m32
    out["m32_master2"]["chirp_ht"] = {k: v for k, v in ht2.items() if k != "h"}
    out["m32_master2"]["channel_stability"] = stab2
    _print_config(r_m32)

    # ----- verdict -----
    out["verdict"] = _verdict(r_m16, r_m32)
    print("\n[VERDICT]")
    for k, v in out["verdict"].items():
        print(f"  {k}: {v}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    outp = RESULTS_DIR / "eq_train_results.json"
    outp.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[done] wrote {outp}")
    return out


def _print_config(r):
    print(f"\n=== {r['config']} (N={r['N']}, {r['bin_hz']} Hz bins) ===")
    print(f"  {'mode':<14} {'eras':>4} {'leak':>6} {'adj':>6} {'dist':>6} "
          f"{'rawBER':>7} {'genBER':>7} {'rawByteE':>9} {'genByteE':>9}")
    for mode in EQ_MODES:
        m = r["modes"][mode]
        lk = m.get("offtone_leakage_median")
        adj = m.get("adjacent_leakage_median")
        dist = m.get("distant_leakage_median")
        rbe = m.get("raw_byte_err_rate", m.get("raw_byte_err"))
        gbe = m.get("genie_byte_err_rate", m.get("genie_byte_err"))
        print(f"  {mode:<14} {m['n_erasures']:>4} "
              f"{(lk if lk is not None else float('nan')):>6.3f} "
              f"{(adj if adj is not None else float('nan')):>6.3f} "
              f"{(dist if dist is not None else float('nan')):>6.3f} "
              f"{m['raw_ber']:>7.3f} {m['genie_ber']:>7.3f} "
              f"{(rbe if rbe is not None else float('nan')):>9.4f} "
              f"{(gbe if gbe is not None else float('nan')):>9.4f}")


def _verdict(r_m16, r_m32):
    """Honest verdict: did complex EQ drop the diffuse floor + close RS?"""
    v = {}
    # the load-bearing attribution: is the trained channel even LTI/stable?
    for tag, r in (("m16", r_m16), ("m32", r_m32)):
        st = r.get("channel_stability", {})
        v[f"{tag}_channel_phase_diff_deg"] = st.get("phase_diff_deg_median_after_delay")
        v[f"{tag}_channel_verdict"] = st.get("verdict")
    # leakage drop (mmse_complex vs none) on the diffuse/distant term
    for tag, r in (("m16", r_m16), ("m32", r_m32)):
        none = r["modes"]["none"]
        mmse = r["modes"]["mmse_complex"]
        d0 = none.get("distant_leakage_median")
        dm = mmse.get("distant_leakage_median")
        v[f"{tag}_distant_leak_none"] = d0
        v[f"{tag}_distant_leak_mmse"] = dm
        v[f"{tag}_distant_leak_drop"] = (None if (d0 is None or dm is None)
                                         else round(d0 - dm, 4))
        v[f"{tag}_genie_ber_none"] = round(none["genie_ber"], 4)
        v[f"{tag}_genie_ber_mmse"] = round(mmse["genie_ber"], 4)
    # M32 RS-closability on achievable + genie path under mmse
    m32_mmse = r_m32["modes"]["mmse_complex"]
    v["m32_mmse_raw_byte_er"] = round(m32_mmse["raw_byte_err_rate"], 4)
    v["m32_mmse_genie_byte_er"] = round(m32_mmse["genie_byte_err_rate"], 4)
    v["m32_mmse_raw_rs_closable"] = m32_mmse["raw_rs_closable"]
    v["m32_mmse_genie_rs_closable"] = m32_mmse["genie_rs_closable"]
    v["acoustic_byte_exact_cracked"] = bool(
        r_m16["modes"]["mmse_complex"]["raw_byte_exact"] or m32_mmse["raw_rs_closable"])
    return v


if __name__ == "__main__":
    main()
