"""Generate a CHANNEL SOUNDER master for the cassette->speaker->iPhone link.

This is the "known test sequence" for DPD-style channel identification. One master
WAV, recorded in one pass through the exact link, lets us measure things the OOK
data recording cannot:

  S1  Exponential sine sweeps (Farina), 2 levels  -> full linear H(f) magnitude+PHASE
                                                     AND harmonic distortion vs freq
                                                     (low vs high level = AM/AM compression)
  S2  Low-PAPR Schroeder multitone, 64 carriers   -> per-carrier SNR(f) at the data
                                                     band's operating level
  S3  Steady 3 kHz tone, 12 s                      -> wow/flutter (instantaneous freq drift)
  S4  Silence                                      -> noise floor

Sections are separated by silence and tagged by a 7800 Hz pilot burst (same marker
the modem/segmenter already keys on) plus a 1 kHz lead chirp for coarse alignment.

Decode with analyze_sounder.py after recording.
"""
import json, numpy as np, soundfile as sf

SR = 48000
MARK_F = 7800.0
OUT = "sounder_master.wav"


def pilot(dur=0.25):
    t = np.arange(int(dur * SR)) / SR
    x = 0.5 * np.sin(2 * np.pi * MARK_F * t)
    f = int(0.005 * SR); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
    return x


def silence(dur): return np.zeros(int(dur * SR))


def exp_sweep(f1, f2, T, amp):
    """Farina exponential sine sweep + its matched inverse filter (returned in meta)."""
    n = int(T * SR); t = np.arange(n) / SR
    L = T / np.log(f2 / f1)
    phase = 2 * np.pi * f1 * L * (np.exp(t / L) - 1.0)
    x = np.sin(phase)
    # fade ends
    f = int(0.02 * SR); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
    return (amp * x).astype(np.float64), dict(f1=f1, f2=f2, T=T, L=L, amp=amp)


def schroeder_multitone(freqs, T, amp):
    """Equal-amplitude multitone with Schroeder phases -> low crest factor (~ avoids
    driving the speaker into clipping, so SNR(f) reflects the real operating point)."""
    n = int(T * SR); t = np.arange(n) / SR
    K = len(freqs); x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K           # Schroeder phase
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    f = int(0.02 * SR); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
    return (amp * x).astype(np.float64), [float(f) for f in freqs]


def steady(f0, T, amp):
    n = int(T * SR); t = np.arange(n) / SR
    x = amp * np.sin(2 * np.pi * f0 * t)
    f = int(0.02 * SR); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
    return x.astype(np.float64)


def build():
    parts = [silence(2.0)]
    meta = {"SR": SR, "sections": []}
    pos = len(parts[0])

    def add(sig, kind, info):
        nonlocal pos
        # marker bursts bracket the section
        for s in (pilot(), silence(0.4), sig, silence(0.4), pilot(), silence(1.2)):
            parts.append(s)
        seg_start = pos + len(pilot()) + len(silence(0.4))
        meta["sections"].append(dict(kind=kind, start=int(seg_start),
                                     length=int(len(sig)), info=info))
        pos = seg_start + len(sig) + len(silence(0.4)) + len(pilot()) + len(silence(1.2))

    # S1: two sweeps at -12 and -3 dBFS to expose AM/AM compression
    for amp, tag in [(0.25, "lo"), (0.7, "hi")]:
        sw, mi = exp_sweep(80.0, 14000.0, 8.0, amp); mi["tag"] = tag
        add(sw, "sweep", mi)
    # S2: 64-tone Schroeder multitone over the usable acoustic band, 3 s, x2 for averaging
    freqs = np.round(np.geomspace(300, 11000, 64)).astype(int).tolist()
    for r in range(2):
        mt, ff = schroeder_multitone(freqs, 3.0, 0.6)
        add(mt, "multitone", dict(freqs=ff, rep=r))
    # S3: steady tone for wow/flutter
    add(steady(3000.0, 12.0, 0.5), "steady", dict(f0=3000.0))
    # S4: silence for noise floor
    add(silence(3.0), "noisefloor", {})

    sig = np.concatenate(parts).astype(np.float32)
    sig *= 0.95 / (np.max(np.abs(sig)) + 1e-9)
    sf.write(OUT, sig, SR)
    json.dump(meta, open(OUT + ".json", "w"), indent=1)
    print(f"wrote {OUT}  ({len(sig)/SR:.1f}s, {len(meta['sections'])} sections)")
    for s in meta["sections"]:
        print(f"  {s['kind']:<11} @ {s['start']/SR:6.2f}s  {s['length']/SR:5.1f}s  {s.get('info',{}).get('tag','')}")


if __name__ == "__main__":
    build()
