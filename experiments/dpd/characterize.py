"""Build the channel fingerprint from the existing recording and render plots.

Pools per-carrier on/off energies across ALL captured configs. Because different
K values place carriers on different frequencies (geomspace 1500-7000 Hz), the pool
densely samples SNR(f) and reveals the channel's frequency-selective null comb --
the structure that flat OOK ignores and that bit-loading / pre-emphasis exploits.
"""
import json, numpy as np
import chan_lib as C
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rec = C.load_rec(); man = C.load_manifest(); frames = C.segment_frames(rec); OFF0 = 3

pool = []          # (freq, snr_db, biterr_for_that_carrier, nsym)
clocks = []; jit_rms = []; imd_floor = []
per_cfg = []
for i in range(len(frames)):
    e = man[OFF0 + i]; meta = e["meta"]
    t0, t1 = frames[i]
    m = C.measure_frame(rec, t0, t1, meta)
    tg = C.truth_grid(e); Nd = min(m["Nd"], len(tg))
    P, T = m["P"][:Nd], tg[:Nd]; K = m["K"]; fs = m["freqs"]
    clocks.append(m["clock"]); jit_rms.append(np.std(m["jitter"]) * 1000)
    # IMD/leakage floor: off-grid (between-carrier) marker energy vs on-grid marker energy
    if m["offgrid"].size:
        imd_floor.append(10 * np.log10((m["offgrid"].mean() + 1e-12) / (m["G"].mean() + 1e-12)))
    # per-carrier SNR + biterr (with modem threshold)
    chunk = meta["chunk"]; G = m["G"]
    hard = np.zeros_like(T); di = 0
    for j in range(len(G) - 1):
        g = np.maximum(G[j], 1e-9)
        for k in range(chunk):
            if di >= Nd: break
            hard[di] = (P[di] > C.mod.THR * g).astype(np.uint8); di += 1
    for c in range(K):
        on = P[:, c][T[:, c] == 1]; off = P[:, c][T[:, c] == 0]
        if len(on) < 2 or len(off) < 2: continue
        snr = 10 * np.log10(on.mean() / max(off.mean(), 1e-12))
        be = int((hard[:, c] != T[:, c]).sum())
        pool.append((fs[c], snr, be, Nd))

pool = np.array(pool)
freq, snr, be, nsym = pool[:, 0], pool[:, 1], pool[:, 2], pool[:, 3]
ber = be / nsym

summary = dict(
    n_configs=len(frames),
    clock_mean=float(np.mean(clocks)), clock_std=float(np.std(clocks)),
    jitter_rms_ms_med=float(np.median(jit_rms)),
    imd_floor_db_med=float(np.median(imd_floor)) if imd_floor else None,
    snr_median_db=float(np.median(snr)), snr_p10_db=float(np.percentile(snr, 10)),
    snr_p90_db=float(np.percentile(snr, 90)),
    frac_carriers_below_8db=float((snr < 8).mean()),
    frac_carriers_below_5db=float((snr < 5).mean()),
)
json.dump(summary, open("channel_summary.json", "w"), indent=1)
print(json.dumps(summary, indent=1))

# ---- plots ----
fig, ax = plt.subplots(2, 2, figsize=(12, 8))
# (1) SNR vs frequency -- the null comb
a = ax[0, 0]
sc = a.scatter(freq, snr, c=ber, cmap="inferno_r", s=18, vmin=0, vmax=0.3)
a.axhline(8, color="green", ls="--", lw=1, label="~8 dB OOK floor")
a.set_xlabel("carrier frequency (Hz)"); a.set_ylabel("on/off SNR (dB)")
a.set_title("Channel fingerprint: per-carrier SNR vs frequency\n(colour = bit-error rate on that carrier)")
a.legend(loc="lower left"); plt.colorbar(sc, ax=a, label="carrier BER")
# binned median to show the comb
bins = np.geomspace(1500, 7000, 24); idx = np.digitize(freq, bins)
bx = [np.median(freq[idx == k]) for k in range(1, len(bins)) if (idx == k).any()]
by = [np.median(snr[idx == k]) for k in range(1, len(bins)) if (idx == k).any()]
a.plot(bx, by, "c-", lw=2, label="binned median")
# (2) BER vs SNR -- the decision threshold
a = ax[0, 1]
a.scatter(snr, ber, s=14, alpha=0.5)
a.set_xlabel("per-carrier SNR (dB)"); a.set_ylabel("carrier BER")
a.set_title("Errors collapse onto low-SNR carriers\n(a few deep nulls dominate the byte budget)")
a.axvline(8, color="green", ls="--"); a.set_ylim(-0.02, 0.6)
# (3) time-base
a = ax[1, 0]
a.hist(clocks, bins=20, color="steelblue")
a.set_xlabel("estimated cassette/phone clock ratio")
a.set_ylabel("# configs")
a.set_title(f"Time base: clock={np.mean(clocks):.3f}±{np.std(clocks):.3f}\n"
            f"(static offset, NOT wow/flutter) | jitter med {np.median(jit_rms):.1f} ms")
# (4) SNR histogram
a = ax[1, 1]
a.hist(snr, bins=30, color="indianred")
a.axvline(np.median(snr), color="k", ls="--", label=f"median {np.median(snr):.1f} dB")
a.axvline(8, color="green", ls="--", label="OOK floor")
a.set_xlabel("per-carrier SNR (dB)"); a.set_ylabel("# carriers")
a.set_title(f"{(snr<8).mean()*100:.0f}% of carriers below 8 dB "
            f"(the erasure targets)")
a.legend()
plt.tight_layout(); plt.savefig("channel_fingerprint.png", dpi=110)
print("wrote channel_fingerprint.png, channel_summary.json")
