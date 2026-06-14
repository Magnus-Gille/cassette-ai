"""Build the 15-minute experiment master (one WAV to record through the cassette link).

Three experiments, all anchored by two global sync chirps:
  A. CHANNEL SOUNDER  (~55s) : sweeps (H/THD), multitone (SNR(f)), steady (wow), silence
  B. PAPR / IMD SWEEP (~55s) : all-carrier multitone, {in-phase, low-PAPR, random} x 4 drive
                                levels -> does lower PAPR / lower drive cut the -10.5 dB
                                IMD floor?
  C. OOK A/B GRID     (~11m)  : 6 rates (250-533 gross bps) x {phase-0 (high PAPR),
                                low-PAPR phases} x 9 reps -> does low-PAPR rendering raise
                                the RELIABLE bitrate? Pass-rate statistics per cell.
                                Decoded by the proven (phase-blind) modem.

Outputs master.wav + master_manifest.json (TX sample offsets per section).
"""
import json, numpy as np, soundfile as sf
import master_lib as M
import make_sounder as S

SR = M.SR
rng = np.random.default_rng(7)


def lowpapr_phases(K, iters=6000):
    """Fixed-seed random-search phase set minimizing all-ON crest factor (reproducible)."""
    ns = int(0.06 * SR); fs = M.carriers(K); t = np.arange(ns) / SR
    base = np.array([np.sin(2 * np.pi * f * t) for f in fs])   # per-carrier waveforms
    best = (np.zeros(K), 1e9)
    r = np.random.default_rng(100 + K)
    for _ in range(iters):
        ph = r.uniform(0, 2 * np.pi, K)
        x = (base.T * np.cos(ph) - np.array([np.cos(2*np.pi*f*t) for f in fs]).T * np.sin(ph)).sum(1) \
            if False else np.sum([np.sin(2*np.pi*f*t+p) for f,p in zip(fs,ph)], axis=0)
        cf = np.max(np.abs(x)) / (np.sqrt(np.mean(x**2)) + 1e-12)
        if cf < best[1]: best = (ph, cf)
    return best[0]


OOK_CONFIGS = [(20, 80), (20, 60), (24, 80), (24, 60), (28, 60), (32, 60)]  # 250..533 gross
OOK_REPS = 11
MSG = ("The quick brown fox jumps over the lazy dog. Cassette AI proves data over sound "
       "works! 0123456789")
PAPR_KINDS = ["inphase", "lowpapr", "random"]
PAPR_AMPS = [0.2, 0.35, 0.5, 0.7]

GAP = 0.35


def build():
    LPP = {K: lowpapr_phases(K) for K in sorted({k for k, _ in OOK_CONFIGS} | {24})}
    parts = []; man = {"SR": SR, "sections": []}
    pos = 0
    def add_raw(sig):
        nonlocal pos; parts.append(sig.astype(np.float32)); pos += len(sig)
    def gap(d=GAP): add_raw(np.zeros(int(d * SR)))
    def add_section(sig, kind, info):
        start = pos; add_raw(sig)
        man["sections"].append(dict(kind=kind, start=int(start), length=int(len(sig)), info=info))
        gap()

    add_raw(np.zeros(int(1.0 * SR)))                     # lead
    man["tx_chirp0"] = pos; add_raw(M.chirp(up=True)); gap(0.4)

    # ---- A. CHANNEL SOUNDER ----
    for amp, tag in [(0.25, "lo"), (0.7, "hi")]:
        sw, mi = S.exp_sweep(80.0, 14000.0, 8.0, amp); mi["tag"] = tag
        add_section(sw, "sweep", mi)
    freqs = np.round(np.geomspace(300, 11000, 64)).astype(int).tolist()
    for r in range(2):
        mt, ff = S.schroeder_multitone(freqs, 3.0, 0.6)
        add_section(mt, "multitone_sounder", dict(freqs=ff, rep=r))
    add_section(S.steady(3000.0, 10.0, 0.5), "steady", dict(f0=3000.0))
    add_section(np.zeros(int(2.5 * SR)), "noisefloor", {})

    # ---- B. PAPR / IMD SWEEP ----
    for rep in range(2):
        for kind in PAPR_KINDS:
            for amp in PAPR_AMPS:
                sig, info = M.gen_multitone(24, 2.0, kind, amp); info["rep"] = rep
                add_section(sig, "papr", info)

    # ---- C. OOK A/B GRID ----
    for rep in range(OOK_REPS):
        for (K, sd) in OOK_CONFIGS:
            for phase_tag in ("phase0", "lowpapr"):
                ph = None if phase_tag == "phase0" else LPP[K]
                sig, meta = M.gen_ook_frame(MSG, sd, K, phases=ph)
                meta.update(phase=phase_tag, K=K, sd=sd, gross=round(K / (sd / 1000.0)), rep=rep)
                add_section(sig, "ook", meta)

    man["tx_chirp1"] = pos; add_raw(M.chirp(up=False)); add_raw(np.zeros(int(1.0 * SR)))

    sig = np.concatenate(parts)
    sig *= 0.95 / (np.max(np.abs(sig)) + 1e-9)
    sf.write("master.wav", sig.astype(np.float32), SR)
    json.dump(man, open("master_manifest.json", "w"))
    dur = len(sig) / SR
    nook = sum(1 for s in man["sections"] if s["kind"] == "ook")
    npapr = sum(1 for s in man["sections"] if s["kind"] == "papr")
    print(f"wrote master.wav  {dur/60:.1f} min ({dur:.0f}s)  {len(man['sections'])} sections")
    print(f"  sounder: 6   |  PAPR/IMD bursts: {npapr}  |  OOK frames: {nook} "
          f"({len(OOK_CONFIGS)} rates x 2 phase x {OOK_REPS} reps)")
    print(f"  OOK rates (gross bps): {[round(K/(sd/1000)) for K,sd in OOK_CONFIGS]}")
    for K in sorted(LPP):
        import master_lib as _M
        cf0 = _M.crest_factor_db(np.sum([np.sin(2*np.pi*f*np.arange(int(0.06*SR))/SR) for f in _M.carriers(K)],axis=0))
        cf1 = _M.crest_factor_db(np.sum([np.sin(2*np.pi*f*np.arange(int(0.06*SR))/SR+p) for f,p in zip(_M.carriers(K),LPP[K])],axis=0))
        print(f"  K={K}: all-ON crest  phase0={cf0:.1f}dB  lowPAPR={cf1:.1f}dB  (-{cf0-cf1:.1f}dB)")


if __name__ == "__main__":
    build()
