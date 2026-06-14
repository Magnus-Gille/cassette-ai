"""Deep offline analysis of master_recorded.wav (no new recording).

Locates OOK frames by their (50 dB) pilot markers, then for every frame runs:
  - baseline decode (production modem)
  - channel-aware ERASURE decode (decision-directed, RS-erasure, the proven RX lever)
and measures per-carrier on/off SNR vs ground truth. Aggregates:
  - reliable-rate frontier: baseline vs erasure, phase-0 vs low-PAPR
  - per-carrier SNR(f) null comb, phase-0 vs low-PAPR (does low-PAPR raise SNR?)
  - Shannon/bit-loading capacity from the measured SNR
Outputs deep_results.json + deep_analysis.png.
"""
import json, os, tempfile, io, contextlib, hashlib
import numpy as np, soundfile as sf
from scipy.signal import correlate
from reedsolo import RSCodec, ReedSolomonError
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import master_lib as M
import chan_lib as C

SR = M.SR
MSG = ("The quick brown fox jumps over the lazy dog. Cassette AI proves data over sound "
       "works! 0123456789")
THR = M.mod.THR


def _pow(seg, f):
    n = len(seg)
    if n < 2: return 0.0
    wv = seg * np.hanning(n); k = np.exp(-2j * np.pi * f * np.arange(n) / SR)
    return np.abs(np.dot(wv, k)) / n


def locate_ook(rec, man):
    rx0 = int(np.argmax(np.abs(correlate(rec, M.chirp(True), mode="valid"))))
    rx1 = int(np.argmax(np.abs(correlate(rec, M.chirp(False), mode="valid"))))
    clock = (rx1 - rx0) / (man["tx_chirp1"] - man["tx_chirp0"])
    ook_secs = [s for s in man["sections"] if s["kind"] == "ook"]
    ook_start = (rx0 + (ook_secs[0]["start"] - man["tx_chirp0"]) * clock) / SR - 1.0
    w = int(0.03 * SR); hop = int(0.005 * SR)
    starts = np.arange(int(ook_start * SR), len(rec) - w, hop)
    pil = np.array([_pow(rec[s:s + w], M.MARK_F) for s in starts]); tt = (starts + w / 2) / SR
    mk = tt[pil > 0.25 * pil.max()]
    groups = []; cur = [mk[0]]
    for t in mk[1:]:
        if t - cur[-1] > 0.6: groups.append(cur); cur = [t]
        else: cur.append(t)
    groups.append(cur)
    return clock, list(zip(ook_secs, groups))


def truth_grid(meta):
    cw = bytes(RSCodec(meta["nsym"]).encode(MSG.encode()))
    bits = np.unpackbits(np.frombuffer(cw, np.uint8))
    pad = (-len(bits)) % meta["K"]
    if pad: bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
    return bits.reshape(meta["K"], -1).T[:meta["ndata_sym"]]


def decode_base(seg, meta):
    tmp = tempfile.mkdtemp(); wp = os.path.join(tmp, "f.wav"); jp = wp + ".json"
    sf.write(wp, seg.astype(np.float32), SR); json.dump(meta, open(jp, "w"))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): ok, data = M.mod.decode(wp, jp)
    except Exception: ok, data = False, b""
    return bool(ok)


def carrier_spans(meta):
    K, Nd, nb = meta["K"], meta["ndata_sym"], meta["nbytes"]
    return [list(range(c * Nd // 8, min(((c + 1) * Nd - 1) // 8, nb - 1) + 1)) for c in range(K)]


def decode_erasure(rec, t0, t1, meta):
    """Decision-directed erasure decode + per-carrier SNR. Returns (ok_sha, snr_per_carrier)."""
    m = C.measure_frame(rec, t0, t1, meta); Nd = min(m["Nd"], len(truth_grid(meta)))
    P = m["P"][:Nd]; G = m["G"]; K = m["K"]; chunk = meta["chunk"]; T = truth_grid(meta)[:Nd]
    hard = np.zeros((Nd, K), np.uint8); di = 0
    for j in range(len(G) - 1):
        g = np.maximum(G[j], 1e-9)
        for k in range(chunk):
            if di >= Nd: break
            hard[di] = (P[di] > THR * g).astype(np.uint8); di += 1
    # blind separability + true SNR (vs ground truth, for the fingerprint only)
    q = np.full(K, 9.9); snr = np.full(K, np.nan)
    for c in range(K):
        on = P[:, c][hard[:, c] == 1]; off = P[:, c][hard[:, c] == 0]
        if len(on) >= 2 and len(off) >= 2:
            q[c] = (on.mean() - off.mean()) / (on.std() + off.std() + 1e-9)
        ton = P[:, c][T[:, c] == 1]; toff = P[:, c][T[:, c] == 0]
        if len(ton) and len(toff): snr[c] = 10 * np.log10(ton.mean() / max(toff.mean(), 1e-12))
    linear = hard[:Nd].T.reshape(-1)[:meta["nbytes"] * 8]
    cw = np.packbits(linear).tobytes()[:meta["nbytes"]]
    spans = carrier_spans(meta); order = sorted(range(K), key=lambda c: q[c])
    eb = []
    for n in range(0, 9):
        if n:
            c = order[n - 1]
            if q[c] >= 1.5: break
            ne = sorted(set(eb) | set(spans[c]))
            if len(ne) > meta["nsym"]: break
            eb = ne
        try:
            d = RSCodec(meta["nsym"]).decode(cw, erase_pos=eb) if eb else RSCodec(meta["nsym"]).decode(cw)
            if hashlib.sha256(bytes(d[0])).hexdigest() == meta["sha"]:
                return True, snr
        except (ReedSolomonError, Exception): pass
    return False, snr


def main():
    man = json.load(open("master_manifest.json"))
    rec, _ = sf.read("master_recorded.wav"); rec = (rec - rec.mean()).astype(np.float64)
    clock, frames = locate_ook(rec, man)
    print(f"clock={clock:.4f}  {len(frames)} OOK frames")

    base = {}; eras = {}; snr_pool = {"phase0": [], "lowpapr": []}
    for s, g in frames:
        meta = s["info"]; t0 = g[0] - 0.45; t1 = g[-1] + 0.45
        a = int(t0 * SR); b = int(t1 * SR); seg = rec[max(0, a):min(len(rec), b)]
        ph = meta["phase"]; key = (meta["gross"], ph)
        ok_b = decode_base(seg, meta)
        ok_e, snr = decode_erasure(rec, t0, t1, meta)
        base.setdefault(key, []).append(ok_b); eras.setdefault(key, []).append(ok_e or ok_b)
        for c, f in enumerate(meta["freqs"]):
            if not np.isnan(snr[c]): snr_pool[ph].append((f, snr[c]))

    rates = sorted({g for g, _ in base})
    print(f"\n{'rate':>5} | {'phase0 base/eras':>18} | {'lowPAPR base/eras':>18}")
    print("-" * 50)
    rows = {}
    for r in rates:
        cell = {}
        for ph in ("phase0", "lowpapr"):
            b = base.get((r, ph), []); e = eras.get((r, ph), [])
            cell[ph] = (sum(b), sum(e), len(b))
        rows[r] = cell
        p, l = cell["phase0"], cell["lowpapr"]
        print(f"{r:>5} | {p[0]:>2}/{p[1]:>2} of {p[2]:<8} | {l[0]:>2}/{l[1]:>2} of {l[2]:<8}")
    tb = {ph: sum(sum(v) for (r, p), v in base.items() if p == ph) for ph in ("phase0", "lowpapr")}
    te = {ph: sum(sum(v) for (r, p), v in eras.items() if p == ph) for ph in ("phase0", "lowpapr")}
    n = {ph: sum(len(v) for (r, p), v in base.items() if p == ph) for ph in ("phase0", "lowpapr")}
    print("-" * 50)
    print(f"TOTAL phase0 : baseline {tb['phase0']}/{n['phase0']} -> +erasure {te['phase0']}/{n['phase0']}")
    print(f"TOTAL lowPAPR: baseline {tb['lowpapr']}/{n['lowpapr']} -> +erasure {te['lowpapr']}/{n['lowpapr']}")

    # capacity from pooled SNR (9 dB gap)
    allsnr = np.array([s for ph in snr_pool for _, s in snr_pool[ph]])
    cap = np.maximum(np.log2(1 + 10 ** (allsnr / 10) / 10 ** 0.9), 0)
    print(f"\nper-carrier SNR median {np.median(allsnr):.1f} dB | Shannon(9dB gap) {np.median(cap):.2f} bits/carrier "
          f"(OOK uses 1) | carriers<8dB: {100*np.mean(allsnr<8):.0f}%")

    # ---- plots ----
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.5))
    for ph, col in (("phase0", "tab:red"), ("lowpapr", "tab:blue")):
        d = np.array(snr_pool[ph]);
        if len(d):
            ax[0].scatter(d[:, 0], d[:, 1], s=8, alpha=0.4, color=col, label=ph)
            bins = np.geomspace(1500, 7000, 22); idx = np.digitize(d[:, 0], bins)
            bx = [np.median(d[idx == k, 0]) for k in range(1, len(bins)) if (idx == k).any()]
            by = [np.median(d[idx == k, 1]) for k in range(1, len(bins)) if (idx == k).any()]
            ax[0].plot(bx, by, color=col, lw=2)
    ax[0].axhline(8, color="green", ls="--", label="OOK floor"); ax[0].legend()
    ax[0].set_xlabel("carrier freq (Hz)"); ax[0].set_ylabel("on/off SNR (dB)")
    ax[0].set_title("Per-carrier SNR null comb\n(phase-0 vs low-PAPR)")
    # pass-rate bars
    x = np.arange(len(rates)); wbar = 0.2
    for i, (ph, off) in enumerate((("phase0", -1.5), ("lowpapr", 0.5))):
        bb = [rows[r][ph][0] / rows[r][ph][2] for r in rates]
        ee = [rows[r][ph][1] / rows[r][ph][2] for r in rates]
        ax[1].bar(x + off * wbar, bb, wbar, color=("tab:red" if ph == "phase0" else "tab:blue"), alpha=0.5,
                  label=f"{ph} base")
        ax[1].bar(x + (off + 1) * wbar, ee, wbar, color=("tab:red" if ph == "phase0" else "tab:blue"),
                  label=f"{ph} +erasure")
    ax[1].set_xticks(x); ax[1].set_xticklabels([f"{r}" for r in rates]); ax[1].set_ylim(0, 1.05)
    ax[1].set_xlabel("gross bps"); ax[1].set_ylabel("byte-exact fraction")
    ax[1].set_title("Reliability: baseline vs +erasure"); ax[1].legend(fontsize=7)
    ax[2].hist(allsnr, bins=30, color="slateblue"); ax[2].axvline(8, color="green", ls="--")
    ax[2].axvline(np.median(allsnr), color="k", ls="--", label=f"med {np.median(allsnr):.1f}dB")
    ax[2].set_xlabel("per-carrier SNR (dB)"); ax[2].set_title("SNR distribution"); ax[2].legend()
    plt.tight_layout(); plt.savefig("deep_analysis.png", dpi=110)
    json.dump({"clock": clock,
               "frontier": {f"{r}": rows[r] for r in rates},
               "total": {"phase0": [tb["phase0"], te["phase0"], n["phase0"]],
                         "lowpapr": [tb["lowpapr"], te["lowpapr"], n["lowpapr"]]},
               "snr_median": float(np.median(allsnr)), "cap_median": float(np.median(cap))},
              open("deep_results.json", "w"), indent=1)
    print("\nwrote deep_results.json, deep_analysis.png")


if __name__ == "__main__":
    main()
