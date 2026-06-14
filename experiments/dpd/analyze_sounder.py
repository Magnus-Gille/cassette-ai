"""Analyze a recording of sounder_master.wav -> the channel model for DPD.

Outputs:
  - H(f): linear frequency response magnitude + phase (from Farina sweep deconvolution)
  - THD(f): harmonic distortion vs frequency, and compression (lo vs hi sweep)
  - SNR(f): per-carrier SNR from the multitone (the data-band operating point)
  - wow/flutter: instantaneous-frequency drift of the steady tone
  - a ready-to-use pre-emphasis curve  preemph(f) = 1/|H(f)|  (clamped)

Usage:  analyze_sounder.py <recorded.wav> [sounder_master.wav.json]
"""
import sys, json, numpy as np
from scipy.signal import butter, sosfiltfilt, hilbert, resample_poly
from scipy.ndimage import uniform_filter1d

SR = 48000; MARK_F = 7800.0


def _ref_sweep(info):
    f1, f2, T = info["f1"], info["f2"], info["T"]
    L = T / np.log(f2 / f1); t = np.arange(int(T * SR)) / SR
    return np.sin(2 * np.pi * f1 * L * (np.exp(t / L) - 1.0))


def align(rec, meta):
    """Find clock + global offset by cross-correlating the recording against the
    lo-level reference sweep (robust to distortion). Returns (clock, rec_master)
    where rec_master is the recording resampled to the master's time base, so every
    section sits at its known master sample range."""
    losec = next(s for s in meta["sections"] if s["kind"] == "sweep" and s["info"]["tag"] == "lo")
    ref = _ref_sweep(losec["info"])
    from scipy.signal import correlate
    best = None
    for c in np.linspace(0.80, 1.06, 27):
        rm = resample_poly(rec, 1000, int(round(1000 * c)))     # -> master time base
        if len(rm) < losec["start"] + len(ref): continue
        seg = rm[losec["start"]:losec["start"] + 3 * len(ref)] if len(rm) > losec["start"] + 3 * len(ref) \
              else rm[losec["start"]:]
        cc = correlate(seg, ref, mode="valid")
        pk = np.max(np.abs(cc)) / (np.linalg.norm(ref) + 1e-9)
        if best is None or pk > best[0]:
            best = (pk, c, rm, int(np.argmax(np.abs(cc))))
    _, clock, rm, lag = best
    # lag is offset of ref within seg that started at losec["start"] -> global shift
    shift = lag                                   # rec_master_idx = master_idx + shift (within section)
    return clock, rm, shift


def farina(rec_seg, f1, f2, T, clock=1.0):
    """Deconvolve an exp-sweep recording -> (freqs, |H| dB, phase, thd_db)."""
    L = T / np.log(f2 / f1)
    n = int(T * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f1 * L * (np.exp(t / L) - 1.0))
    # inverse filter: time-reversed, amplitude-whitened
    inv = x[::-1] * np.exp(-t[::-1] / L)
    inv /= np.sqrt(np.sum(inv ** 2))
    y = rec_seg
    if clock != 1.0:  # undo cassette/phone speed so sweep rate matches reference
        y = resample_poly(y, int(round(1000 / clock)), 1000)
    ir = np.convolve(y, inv, mode="full")
    pk = int(np.argmax(np.abs(ir)))
    # linear IR window around the main peak
    half = int(0.04 * SR)
    lin = ir[max(0, pk - half):pk + half] * np.hanning(2 * half)[:len(ir[max(0, pk - half):pk + half])]
    H = np.fft.rfft(lin, 1 << 16); fr = np.fft.rfftfreq(1 << 16, 1 / SR)
    band = (fr >= f1) & (fr <= min(f2, SR / 2))
    mag = 20 * np.log10(np.abs(H) + 1e-12)
    # 2nd harmonic IR sits earlier by dt = L*ln(2)
    dt2 = int(L * np.log(2) * SR)
    h2 = ir[max(0, pk - dt2 - half):pk - dt2 + half]
    thd = 20 * np.log10((np.sqrt(np.mean(h2 ** 2)) + 1e-12) / (np.sqrt(np.mean(lin ** 2)) + 1e-12))
    return fr[band], mag[band], np.unwrap(np.angle(H))[band], float(thd)


def multitone_snr(seg, freqs, clock=1.0):
    if clock != 1.0:
        seg = resample_poly(seg, int(round(1000 / clock)), 1000)
        freqs = [f for f in freqs]  # reference freqs unchanged after un-clocking
    w = np.hanning(len(seg)); S = np.abs(np.fft.rfft(seg * w)); fr = np.fft.rfftfreq(len(seg), 1 / SR)
    def lvl(f):
        k = np.argmin(np.abs(fr - f)); return S[max(0, k - 1):k + 2].max()
    sig = np.array([lvl(f) for f in freqs])
    midf = np.sqrt(np.array(freqs[:-1]) * np.array(freqs[1:]))
    noise = np.array([lvl(f) for f in midf])
    nfloor = np.interp(freqs, midf, noise)
    return np.array(freqs), 20 * np.log10(sig / (nfloor + 1e-9))


def wow_flutter(seg, f0, clock=1.0):
    sos = butter(4, [f0 * clock - 400, f0 * clock + 400], "bandpass", fs=SR, output="sos")
    a = hilbert(sosfiltfilt(sos, seg))
    inst = np.diff(np.unwrap(np.angle(a))) / (2 * np.pi) * SR
    inst = inst[int(0.1 * SR):-int(0.1 * SR)]
    # wow/flutter is slow (<20 Hz) modulation -> smooth out high-freq phase noise so we
    # measure genuine speed wander, not additive-noise jitter
    inst = uniform_filter1d(inst, size=int(0.02 * SR))
    f_mean = np.median(inst)
    return float(f_mean), float(np.std(inst) / f_mean * 100)  # mean Hz, flutter %


def estimate_clock(steady_seg, f0):
    sos = butter(4, [f0 * 0.7, f0 * 1.3], "bandpass", fs=SR, output="sos")
    a = hilbert(sosfiltfilt(sos, steady_seg))
    inst = np.diff(np.unwrap(np.angle(a))) / (2 * np.pi) * SR
    return float(np.median(inst[int(0.2*SR):-int(0.2*SR)]) / f0)


def run(rec_path, meta_path):
    import soundfile as sf
    meta = json.load(open(meta_path))
    rec, sr = sf.read(rec_path)
    if rec.ndim > 1: rec = rec.mean(1)
    rec = (rec - rec.mean())
    secs = meta["sections"]
    clock, rm, shift = align(rec, meta)
    out = {"clock": clock}
    print(f"clock (phone/cassette) = {clock:.4f}   (sections mapped from master layout)")
    def slc(s):
        a = s["start"] + shift; b = a + s["length"]
        return rm[max(0, a):min(len(rm), b)]
    for i, s in enumerate(secs):
        seg = slc(s)
        if s["kind"] == "sweep":
            fr, mag, ph, thd = farina(seg, s["info"]["f1"], s["info"]["f2"], s["info"]["T"], 1.0)
            out.setdefault("sweeps", {})[s["info"]["tag"]] = dict(thd_db=thd)
            # store coarse H for the lo sweep (the linear reference)
            if s["info"]["tag"] == "lo":
                bins = np.geomspace(300, 11000, 60)
                mg = np.interp(bins, fr, mag)
                out["H_freq"] = bins.tolist(); out["H_mag_db"] = mg.tolist()
            print(f"  sweep[{s['info']['tag']}]: THD = {thd:.1f} dB")
        elif s["kind"] == "multitone":
            f, snr = multitone_snr(seg, s["info"]["freqs"], 1.0)
            out.setdefault("snr_freq", f.tolist()); out["snr_db"] = snr.tolist()
        elif s["kind"] == "steady":
            fm, fl = wow_flutter(seg, s["info"]["f0"], 1.0)
            out["flutter_pct"] = fl
            print(f"  wow/flutter: {fl:.2f}% rms")
    # pre-emphasis curve from H (lo sweep): boost dips, clamp +/-12 dB
    if "H_mag_db" in out:
        h = np.array(out["H_mag_db"]); pe = np.clip(-(h - np.median(h)), -12, 12)
        out["preemph_db"] = pe.tolist()
        print(f"  pre-emphasis range: {pe.min():.1f}..{pe.max():.1f} dB")
    json.dump(out, open("channel_model.json", "w"), indent=1)
    print("wrote channel_model.json")
    return out


if __name__ == "__main__":
    rp = sys.argv[1]
    mp = sys.argv[2] if len(sys.argv) > 2 else "sounder_master.wav.json"
    run(rp, mp)
