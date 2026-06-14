"""Full channel model from master_recorded.wav: H(f) magnitude+phase (Farina sweep),
THD low vs high drive, SNR(f) (multitone), short-term wow (steady tone), and the
accumulated cassette DRIFT profile over the whole tape (what broke global-clock frame
location). Outputs channel_model_full.png + channel_model_full.json + a pre-emphasis curve.
"""
import json, numpy as np, soundfile as sf
from scipy.signal import correlate, hilbert, butter, sosfiltfilt
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import master_lib as M
import analyze_sounder as ASD

SR = M.SR


def _pow(seg, f):
    n = len(seg); wv = seg * np.hanning(n); k = np.exp(-2j * np.pi * f * np.arange(n) / SR)
    return np.abs(np.dot(wv, k)) / n


def main():
    man = json.load(open("master_manifest.json"))
    rec, _ = sf.read("master_recorded.wav"); rec = (rec - rec.mean()).astype(np.float64)
    rx0 = int(np.argmax(np.abs(correlate(rec, M.chirp(True), mode="valid"))))
    rx1 = int(np.argmax(np.abs(correlate(rec, M.chirp(False), mode="valid"))))
    clock = (rx1 - rx0) / (man["tx_chirp1"] - man["tx_chirp0"])
    t2r = lambda t: (rx0 + (t - man["tx_chirp0"]) * clock) / SR
    out = {"clock": clock}

    def slc(s):
        a = int(t2r(s["start"]) * SR); b = int(t2r(s["start"] + s["length"]) * SR)
        return rec[max(0, a):min(len(rec), b)]
    secs = {s["info"].get("tag", s["kind"]): s for s in man["sections"]
            if s["kind"] in ("sweep", "multitone_sounder", "steady")}

    fig, ax = plt.subplots(2, 3, figsize=(16, 9))

    # H(f) magnitude + phase from lo sweep
    sw = next(s for s in man["sections"] if s["kind"] == "sweep" and s["info"]["tag"] == "lo")
    fr, mag, ph, thd_lo = ASD.farina(slc(sw), sw["info"]["f1"], sw["info"]["f2"], sw["info"]["T"], 1.0)
    swh = next(s for s in man["sections"] if s["kind"] == "sweep" and s["info"]["tag"] == "hi")
    _, magh, _, thd_hi = ASD.farina(slc(swh), swh["info"]["f1"], swh["info"]["f2"], swh["info"]["T"], 1.0)
    band = (fr >= 200) & (fr <= 9000)
    ax[0, 0].semilogx(fr[band], mag[band] - np.median(mag[band]), lw=1)
    ax[0, 0].set_title(f"H(f) magnitude (normalised)\nTHD lo={thd_lo:.0f}dB hi={thd_hi:.0f}dB (compression)")
    ax[0, 0].set_xlabel("Hz"); ax[0, 0].set_ylabel("dB"); ax[0, 0].grid(True, which="both", alpha=0.3)
    ax[0, 0].axvspan(1500, 7000, alpha=0.1, color="green")
    # group delay from phase
    gd = -np.gradient(ph) / (2 * np.pi * (fr[1] - fr[0])) * 1000
    ax[0, 1].semilogx(fr[band], gd[band], lw=1, color="purple")
    ax[0, 1].set_title("Group delay (ms)\n(phase linearity — DPSK feasibility)")
    ax[0, 1].set_xlabel("Hz"); ax[0, 1].set_ylim(np.percentile(gd[band], 2), np.percentile(gd[band], 98))
    ax[0, 1].axvspan(1500, 7000, alpha=0.1, color="green"); ax[0, 1].grid(True, which="both", alpha=0.3)

    # SNR(f) from multitone
    mt = next(s for s in man["sections"] if s["kind"] == "multitone_sounder")
    f, snr = ASD.multitone_snr(slc(mt), mt["info"]["freqs"], 1.0)
    ax[0, 2].semilogx(f, snr, ".-", ms=3); ax[0, 2].axhline(8, color="green", ls="--")
    ax[0, 2].set_title(f"SNR(f) from 64-tone probe (median {np.median(snr):.0f}dB)")
    ax[0, 2].set_xlabel("Hz"); ax[0, 2].set_ylabel("SNR dB"); ax[0, 2].grid(True, which="both", alpha=0.3)
    out["snr_median_db"] = float(np.median(snr))

    # short-term wow from steady tone (instantaneous freq)
    st = next(s for s in man["sections"] if s["kind"] == "steady"); f0 = st["info"]["f0"]
    seg = slc(st); sos = butter(4, [f0 * 0.85, f0 * 1.15], "bandpass", fs=SR, output="sos")
    a = hilbert(sosfiltfilt(sos, seg)); inst = np.diff(np.unwrap(np.angle(a))) / (2 * np.pi) * SR
    inst = inst[int(0.2 * SR):-int(0.2 * SR)]
    from scipy.ndimage import uniform_filter1d
    insts = uniform_filter1d(inst, int(0.02 * SR))
    tt = np.arange(len(insts)) / SR
    ax[1, 0].plot(tt, (insts / f0 - 1) * 100, lw=0.5)
    ax[1, 0].set_title(f"Short-term wow (steady {f0:.0f}Hz)\nrms {np.std(insts)/f0*100:.2f}%")
    ax[1, 0].set_xlabel("s"); ax[1, 0].set_ylabel("speed dev %")
    out["wow_rms_pct"] = float(np.std(insts) / f0 * 100)

    # accumulated DRIFT profile: each OOK frame's actual pilot centre vs linear-clock prediction
    ook = [s for s in man["sections"] if s["kind"] == "ook"]
    ook_start = t2r(ook[0]["start"]) - 1.0; w = int(0.03 * SR); hop = int(0.005 * SR)
    starts = np.arange(int(ook_start * SR), len(rec) - w, hop)
    pil = np.array([_pow(rec[s:s + w], M.MARK_F) for s in starts]); tt2 = (starts + w / 2) / SR
    mk = tt2[pil > 0.25 * pil.max()]; groups = []; cur = [mk[0]]
    for t in mk[1:]:
        if t - cur[-1] > 0.6: groups.append(cur); cur = [t]
        else: cur.append(t)
    groups.append(cur)
    actual = np.array([np.mean(g) for g in groups[:len(ook)]])
    pred = np.array([t2r(s["start"] + s["length"] / 2) for s in ook[:len(actual)]])
    drift = actual - pred
    ax[1, 1].plot(pred / 60, drift, ".-", ms=3)
    ax[1, 1].set_title(f"Cassette DRIFT vs global clock\n(max |dev| {np.max(np.abs(drift)):.1f}s — why global slicing failed)")
    ax[1, 1].set_xlabel("tape position (min)"); ax[1, 1].set_ylabel("actual - predicted (s)")
    ax[1, 1].grid(alpha=0.3); ax[1, 1].axhline(0, color="k", lw=0.5)
    out["drift_max_s"] = float(np.max(np.abs(drift)))

    # pre-emphasis curve = inverse |H| over the data band (clamped)
    db = (fr >= 1500) & (fr <= 7000)
    pe = np.clip(-(mag[db] - np.median(mag[db])), -12, 12)
    ax[1, 2].semilogx(fr[db], pe, lw=1, color="darkorange")
    ax[1, 2].set_title(f"Pre-emphasis = 1/|H| (data band)\nrange {pe.min():.0f}..{pe.max():.0f} dB")
    ax[1, 2].set_xlabel("Hz"); ax[1, 2].set_ylabel("boost dB"); ax[1, 2].grid(True, which="both", alpha=0.3)
    out["thd_lo_db"] = float(thd_lo); out["thd_hi_db"] = float(thd_hi)

    plt.tight_layout(); plt.savefig("channel_model_full.png", dpi=110)
    json.dump(out, open("channel_model_full.json", "w"), indent=1)
    print(json.dumps(out, indent=1)); print("wrote channel_model_full.png, .json")


if __name__ == "__main__":
    main()
