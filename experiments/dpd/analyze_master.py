"""Analyze a recording of master.wav. Chirp-anchored: locate the two global chirps ->
clock + offset -> slice every manifest section -> dispatch to its analyzer.

Usage: analyze_master.py <recorded.wav> [master_manifest.json]
"""
import sys, json, os, tempfile, io, contextlib
import numpy as np, soundfile as sf
from scipy.signal import correlate
import master_lib as M
import analyze_sounder as ASD

SR = M.SR
MSG = ("The quick brown fox jumps over the lazy dog. Cassette AI proves data over sound "
       "works! 0123456789")


def _matched(rec, ref):
    return int(np.argmax(np.abs(correlate(rec, ref, mode="valid"))))


def _pow_at(seg, f):
    n = len(seg)
    if n < 2: return 0.0
    w = seg * np.hanning(n); k = np.exp(-2j * np.pi * f * np.arange(n) / SR)
    return np.abs(np.dot(w, k)) / n


def imd_floor(seg, freqs):
    """On-grid (carrier) power vs off-grid (geometric-midpoint) power -> IMD/leakage dB."""
    fs = np.array(freqs); mid = np.sqrt(fs[:-1] * fs[1:])
    on = np.median([_pow_at(seg, f) for f in fs])
    off = np.median([_pow_at(seg, f) for f in mid])
    return 20 * np.log10((off + 1e-12) / (on + 1e-12))


def decode_ook(seg, meta):
    tmp = tempfile.mkdtemp(); wp = os.path.join(tmp, "f.wav"); jp = wp + ".json"
    sf.write(wp, seg.astype(np.float32), SR); json.dump(meta, open(jp, "w"))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): ok, data = M.mod.decode(wp, jp)
    except Exception: ok, data = False, b""
    exp = MSG.encode(); L = max(len(exp), len(data))
    byteerr = sum(1 for k in range(L) if exp[k:k+1] != data[k:k+1])
    return bool(ok), byteerr


def segment_active(rec, gap_s=0.22, min_s=0.5):
    """Ordered list of (start,end) for energy-active segments separated by silence.
    Drift-immune: each section is located by its own energy, not a global clock."""
    fr = int(0.02 * SR); hop = fr
    rms = np.array([np.sqrt((rec[s:s + fr] ** 2).mean()) for s in range(0, len(rec) - fr, hop)])
    t = np.arange(len(rms)) * hop / SR                # seconds
    active = rms > 0.04 * rms.max()
    segs = []; i = 0
    while i < len(active):
        if active[i]:
            j = i
            while j < len(active):
                if active[j]: j += 1; continue
                k = j
                while k < len(active) and not active[k]: k += 1
                if (k - j) * hop / SR >= gap_s: break
                j = k
            segs.append((t[i], t[min(j, len(t) - 1)])); i = j
        else: i += 1
    return [(a, b) for a, b in segs if (b - a) >= min_s]


def run(rec_path, man_path):
    man = json.load(open(man_path))
    rec, sr = sf.read(rec_path)
    if rec.ndim > 1: rec = rec.mean(1)
    rec = (rec - rec.mean()).astype(np.float64)
    rx0 = _matched(rec, M.chirp(up=True)); rx1 = _matched(rec, M.chirp(up=False))
    clock = (rx1 - rx0) / (man["tx_chirp1"] - man["tx_chirp0"])
    tx2rx = lambda t: (rx0 + (t - man["tx_chirp0"]) * clock) / SR
    # energy envelope (10 ms) for onset tracking
    fr = int(0.02 * SR)
    env = np.array([np.sqrt((rec[s:s + fr] ** 2).mean()) for s in range(0, len(rec) - fr, fr)])
    env_t = np.arange(len(env)) * fr / SR
    thr = 0.06 * np.median(env[env > 0.04 * env.max()])  # active threshold from typical level
    active = env > thr
    def next_onset(t_after):
        i = int(np.searchsorted(env_t, t_after))
        while i < len(active) and active[i]: i += 1      # skip if currently inside a burst
        while i < len(active) and not active[i]: i += 1   # to next silence->active edge
        return env_t[i] if i < len(active) else None

    ook = {}; papr = {}; sounder = {}
    secs = man["sections"]
    # --- sounder + PAPR: early on the tape, drift small -> global-clock slices ---
    for s in secs:
        k = s["kind"]
        if k not in ("sweep", "multitone_sounder", "steady", "papr"): continue
        a = int(tx2rx(s["start"]) * SR); b = int(tx2rx(s["start"] + s["length"]) * SR)
        seg = rec[max(0, a):min(len(rec), b)]; info = s["info"]
        if len(seg) < int(0.3 * SR): continue
        if k == "papr":
            papr.setdefault((info["kind"], info["amp"]), []).append(imd_floor(seg, info["freqs"]))
        elif k == "sweep":
            try:
                _, _, _, thd = ASD.farina(seg, info["f1"], info["f2"], info["T"], 1.0)
                sounder.setdefault("sweep", {})[info["tag"]] = round(thd, 1)
            except Exception: pass
        elif k == "multitone_sounder":
            _, snr = ASD.multitone_snr(seg, info["freqs"], 1.0)
            sounder["mt_snr_median"] = round(float(np.median(snr)), 1)
        elif k == "steady":
            _, fl = ASD.wow_flutter(seg, info["f0"], 1.0); sounder["flutter_pct"] = round(fl, 2)

    # --- OOK block: locate frames by PILOT MARKERS (50 dB clean). Inter-frame pilot gap
    #     (~1.1 s of lead+gap+lead) >> intra-frame marker gap (~0.3-0.4 s), so grouping
    #     markers by gap cleanly separates frames regardless of cassette drift. ---
    ook_secs = [s for s in secs if s["kind"] == "ook"]
    ook_start = tx2rx(ook_secs[0]["start"]) - 1.0
    w = int(0.03 * SR); hop = int(0.005 * SR)
    starts = np.arange(int(ook_start * SR), len(rec) - w, hop)
    pil = np.array([_pow_at(rec[s:s + w], M.MARK_F) for s in starts])
    tt = (starts + w / 2) / SR
    on = pil > 0.25 * pil.max()
    mk = tt[on]
    # group marker times into frames where the gap exceeds 0.6 s
    groups = []; cur = [mk[0]]
    for t in mk[1:]:
        if t - cur[-1] > 0.6: groups.append(cur); cur = [t]
        else: cur.append(t)
    groups.append(cur)
    nloc = 0
    for s, g in zip(ook_secs, groups):
        info = s["info"]
        a = int((g[0] - 0.45) * SR); b = int((g[-1] + 0.45) * SR)
        seg = rec[max(0, a):min(len(rec), b)]
        ok, be = decode_ook(seg, info)
        ook.setdefault((info["gross"], info["phase"]), []).append((ok, be)); nloc += 1
    print(f"sync: clock={clock:.4f}  ({len(rec)/SR/60:.1f} min)  "
          f"OOK frames: {len(groups)} pilot-groups for {len(ook_secs)} sections (decoded {nloc})")

    print("\n=== A. SOUNDER ===")
    print(f"  sweep THD lo/hi: {sounder.get('sweep')}   multitone median SNR: "
          f"{sounder.get('mt_snr_median')} dB   wow/flutter: {sounder.get('flutter_pct')}%")

    print("\n=== B. PAPR / IMD floor (dB below carriers; more negative = cleaner) ===")
    print("  amp |   inphase   lowpapr    random")
    amps = sorted({a for (_, a) in papr})
    for amp in amps:
        row = []
        for kind in ("inphase", "lowpapr", "random"):
            v = papr.get((kind, amp)); row.append(f"{np.mean(v):8.1f}" if v else "    -   ")
        print(f"  {amp:>4} | " + "  ".join(row))

    print("\n=== C. OOK A/B  (pass-rate by rate x phase) ===")
    print(f"  {'gross':>5} | {'phase0 pass':>14} {'avg byteerr':>12} | {'lowPAPR pass':>14} {'avg byteerr':>12}")
    for gross in sorted({g for (g, _) in ook}):
        cells = {}
        for ph in ("phase0", "lowpapr"):
            v = ook.get((gross, ph), [])
            npass = sum(1 for ok, _ in v if ok); be = np.mean([b for _, b in v]) if v else 0
            cells[ph] = (npass, len(v), be)
        p0, l0 = cells["phase0"], cells["lowpapr"]
        print(f"  {gross:>5} | {p0[0]:>6}/{p0[1]:<6} {p0[2]:>12.1f} | {l0[0]:>6}/{l0[1]:<6} {l0[2]:>12.1f}")
    # summary
    tot0 = [x for (g, ph), v in ook.items() if ph == "phase0" for x in v]
    tot1 = [x for (g, ph), v in ook.items() if ph == "lowpapr" for x in v]
    print(f"\n  TOTAL phase0 : {sum(1 for ok,_ in tot0 if ok)}/{len(tot0)} byte-exact")
    print(f"  TOTAL lowPAPR: {sum(1 for ok,_ in tot1 if ok)}/{len(tot1)} byte-exact")
    out = {"clock": clock, "sounder": sounder,
           "papr": {f"{k}|{a}": float(np.mean(v)) for (k, a), v in papr.items()},
           "ook": {f"{g}|{ph}": [int(sum(1 for ok,_ in v if ok)), len(v)] for (g, ph), v in ook.items()}}
    json.dump(out, open("master_results.json", "w"), indent=1)
    print("\nwrote master_results.json")


if __name__ == "__main__":
    rp = sys.argv[1]
    mp = sys.argv[2] if len(sys.argv) > 2 else "master_manifest.json"
    run(rp, mp)
