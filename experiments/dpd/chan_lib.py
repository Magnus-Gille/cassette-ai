"""Channel-ID helpers for the cassette->speaker->iPhone DPD experiment.

Reuses the FROZEN modem (modem_frozen.py) so the other agent's in-progress edits
to scripts/acoustic_ofdm_modem.py can't perturb these measurements.

Pipeline:
  1. segment batch_recorded.wav into pilot-bounded frames (same method as the batch decoder)
  2. for a chosen manifest idx, regenerate the BYTE-EXACT transmit signal X
  3. cross-correlate X against each recorded frame to find the matching frame,
     the sample delay, and the cassette clock ratio (resample X to match)
  -> returns a clean (x_tx, y_rx) pair sampled on the SAME time base, ready for
     frequency-response / SNR / nonlinearity / time-base analysis.
"""
import importlib.util, json, os, tempfile
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt, resample_poly, correlate
from scipy.ndimage import uniform_filter1d

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REC  = os.path.join(ROOT, "RESULTS", "tape_test", "batch_recorded.wav")
MAN  = os.path.join(ROOT, "RESULTS", "tape_test", "batch_manifest.json")

_spec = importlib.util.spec_from_file_location("modem_frozen", os.path.join(HERE, "modem_frozen.py"))
mod = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(mod)
SR = mod.SR


def load_rec():
    rec, sr = sf.read(REC)
    assert sr == SR
    if rec.ndim > 1: rec = rec.mean(1)
    return (rec - rec.mean()).astype(np.float64)


def load_manifest():
    return json.load(open(MAN))


def segment_frames(rec):
    """Return list of (t0,t1) seconds for each pilot-bounded frame (batch-decoder method)."""
    sos = butter(4, [mod.MARK_F - 250, mod.MARK_F + 250], "bandpass", fs=SR, output="sos")
    env = uniform_filter1d(sosfiltfilt(sos, rec) ** 2, size=int(0.025 * SR))
    hop = int(0.01 * SR); e = env[::hop]; t = np.arange(len(e)) * hop / SR
    active = e > 0.12 * e.max()
    runs = []; i = 0
    while i < len(active):
        if active[i]:
            j = i
            while j < len(active) and active[j]: j += 1
            runs.append((t[i], t[j - 1])); i = j
        else: i += 1
    runs = [r for r in runs if r[1] - r[0] > 0.02]
    frames = []; cur = [runs[0]]
    for a, b in runs[1:]:
        if a - cur[-1][1] > 2.0: frames.append(cur); cur = [(a, b)]
        else: cur.append((a, b))
    frames.append(cur)
    return [(max(0, fr[0][0] - 0.7), fr[-1][1] + 0.7) for fr in frames]


def regen_tx(entry):
    """Regenerate the byte-exact transmit signal for a manifest entry. Returns (x, meta)."""
    cfg = entry["config"]
    mod.NSYM = cfg["nsym"]; mod.CHUNK = cfg["chunk"]
    mod.FLO = float(cfg["flo"]); mod.FHI = float(cfg["fhi"])
    tmp = tempfile.mkdtemp(); p = os.path.join(tmp, "tx.wav")
    mod.gen(entry["msg"], cfg["sd"], cfg["K"], p)
    x, _ = sf.read(p)
    return x.astype(np.float64), json.load(open(p + ".json"))


def _xcorr_peak(a, b):
    """Best lag (samples) of b within a, plus normalized peak score."""
    c = correlate(a, b, mode="valid")
    na = np.sqrt(uniform_filter1d(a ** 2, len(b)) * len(b))
    # normalize roughly by local energy of a over the window
    lag = int(np.argmax(np.abs(c)))
    nb = np.linalg.norm(b) + 1e-12
    win = a[lag:lag + len(b)]
    score = abs(np.dot(win, b)) / (np.linalg.norm(win) * nb + 1e-12)
    return lag, score


def align_frame(rec, frames, entry, clock_grid=None):
    """Find which recorded frame matches `entry`, the clock ratio, and sample delay.

    Returns dict with y (recorded, clipped & resampled to TX time base), x (tx),
    clock, delay, score, frame_idx.
    """
    x, meta = regen_tx(entry)
    if clock_grid is None:
        # iPhone ~1.0; cassette wow gives small offsets. search a fine grid.
        clock_grid = np.linspace(0.94, 1.06, 25)
    best = None
    for (t0, t1) in frames:
        s, e = int(t0 * SR), int(min(len(rec), t1 * SR))
        yseg = rec[s:e]
        if len(yseg) < 0.5 * len(x): continue
        # coarse: try clock ratios, resample TX, slide
        for c in clock_grid:
            xr = resample_poly(x, int(round(1000 * c)), 1000)
            if len(xr) > len(yseg): continue
            lag, score = _xcorr_peak(yseg, xr)
            if best is None or score > best["score"]:
                best = dict(score=score, clock=c, delay=s + lag, frame=(t0, t1),
                            xlen=len(xr), x=xr, meta=meta)
    s = best["delay"]
    y = rec[s:s + best["xlen"]].copy()
    best["y"] = y; best["x"] = best["x"][:len(y)]
    return best


# ------------------------------------------------------------------ #
#  Real path: map frames<->manifest by duration (batch-decoder method),
#  then measure the channel IN THE DETECTOR'S DOMAIN (per-carrier energy).
# ------------------------------------------------------------------ #

def map_offset(frames, man):
    """Reproduce the batch decoder's contiguous frame->manifest[off0:] mapping."""
    det = np.array([t1 - t0 for (t0, t1) in frames])
    exp = np.array([m["meta"]["nchunks"] * (m["meta"]["chunk"] + 1) * m["meta"]["symdur"]
                    for m in man])
    M, N = len(frames), len(man)
    best = (1e18, 0)
    for off in range(0, max(1, N - M + 1)):
        e = exp[off:off + M]
        if len(e) < M: break
        scale = np.median(det / (e + 1e-9))
        err = np.sum((det - scale * e) ** 2)
        if err < best[0]: best = (err, off)
    return best[1]


def truth_grid(entry):
    """Byte-exact transmitted data-symbol grid[s,c] (1=tone on) for this config."""
    cfg = entry["config"]
    mod.NSYM = cfg["nsym"]
    data = entry["msg"].encode()
    cw = bytes(mod.RSCodec(cfg["nsym"]).encode(data))
    grid, _ = mod._bytes_to_bits(cw, cfg["K"])     # (Nd, K) symbol-major, pre-pad
    return grid.astype(np.uint8)


def measure_frame(rec, t0, t1, meta):
    """Instrumented decode of one frame slice.

    Returns dict with:
      P     (Nd,K) measured per-carrier power at each data-symbol center
      G     (nmark,K) measured per-carrier power in each all-ON marker
      tdet  detected marker centers (s);  mk linear-grid markers (s)
      jitter  tdet - linear_fit  (time-base wander, seconds)
      freqs, symdur, clock, win  (analysis window samples)
      offgrid  IMD/leakage floor: power at off-grid probe freqs in markers
    """
    symdur = meta["symdur"]; fs = np.array(meta["freqs"]); K = meta["K"]
    Nd = meta["ndata_sym"]; chunk = meta["chunk"]; nchunks = meta["nchunks"]
    seg = rec[int(t0 * SR):int(t1 * SR)].copy(); seg = seg - seg.mean()
    w = int(min(symdur * 0.72, 0.05) * SR)

    def sympow(center, freqs):
        s = int(center * SR - w / 2); e = s + w
        s = max(0, s); e = min(len(seg), e); x = seg[s:e]
        return np.array([mod._pow(x, f) for f in freqs])

    # pilot-marker timing (same as modem.decode)
    hop = int(0.005 * SR); starts = np.arange(int(0.3 * SR), max(int(0.3*SR)+1, len(seg) - w), hop)
    tg = (starts + w / 2) / SR
    pil = np.array([mod._pow(seg[s:s + w], mod.MARK_F) for s in starts])
    idx = np.where(pil > 0.30 * pil.max())[0]
    splits = np.where(np.diff(idx) > int(0.5 * symdur / 0.005))[0]
    groups = np.split(idx, splits + 1)
    cen = lambda g: np.sum(tg[g] * pil[g]) / np.sum(pil[g])
    tdet = np.array([cen(g) for g in groups])
    nmark = nchunks + 1
    t_first, t_last = tdet[0], tdet[-1]
    span = (nmark - 1) * (chunk + 1) * symdur
    clock = (t_last - t_first) / span
    sr = symdur * clock
    # snap to detected markers exactly like modem.decode (tol-based; interpolate misses)
    tol = 0.5 * (chunk + 1) * sr
    tdl = list(tdet)
    mk = []
    for j in range(nmark):
        et = t_first + j * (chunk + 1) * sr
        near = min(tdl, key=lambda x: abs(x - et))
        mk.append(near if abs(near - et) < tol else et)
    mk = np.array(mk)
    lin = np.array([t_first + j * (chunk + 1) * sr for j in range(nmark)])
    jitter = np.array([min(tdl, key=lambda x: abs(x - L)) - L for L in lin])

    # off-grid probe frequencies (midpoints between carriers) -> IMD/leakage floor
    midf = np.sqrt(fs[:-1] * fs[1:]) if len(fs) > 1 else np.array([])

    G = []; off = []
    for j in range(nmark):
        G.append(sympow(mk[j], fs))
        if len(midf): off.append(sympow(mk[j], midf))
    G = np.array(G); off = np.array(off) if off else np.zeros((nmark, 0))

    P = []; di = 0
    for j in range(nchunks):
        t0m = mk[j]; t1m = mk[j + 1]
        for i in range(chunk):
            if di >= Nd: break
            tc = t0m + (i + 1) * (t1m - t0m) / (chunk + 1)
            P.append(sympow(tc, fs)); di += 1
    P = np.array(P)
    return dict(P=P, G=G, tdet=tdet, mk=mk, jitter=jitter, clock=clock,
                freqs=fs, symdur=symdur, K=K, Nd=Nd, win=w, offgrid=off, midf=midf)


if __name__ == "__main__":
    rec = load_rec(); man = load_manifest()
    frames = segment_frames(rec)
    off0 = map_offset(frames, man)
    print(f"recorded {len(rec)/SR:.1f}s  detected {len(frames)} frames  "
          f"manifest {len(man)}  off0={off0}")
    # smoke: measure a known-PASS config (idx 12) and a FAIL config (idx 6, K28)
    for idx in (12, 6):
        i = idx - off0
        if not (0 <= i < len(frames)): print(idx, "not in capture"); continue
        e = man[idx]; t0, t1 = frames[i]
        m = measure_frame(rec, t0, t1, e["meta"]); tg = truth_grid(e)
        Nd = min(len(m["P"]), len(tg))
        P, T = m["P"][:Nd], tg[:Nd]
        on = np.array([P[:, c][T[:, c] == 1].mean() for c in range(m["K"])])
        offp = np.array([P[:, c][T[:, c] == 0].mean() if (T[:, c] == 0).any() else np.nan
                         for c in range(m["K"])])
        snr = 10 * np.log10(on / offp)
        print(f"\nidx{idx} K={m['K']} clock={m['clock']:.4f} "
              f"jitter_rms={np.std(m['jitter'])*1000:.1f}ms symdur={m['symdur']*1000:.0f}ms")
        print(f"  per-carrier SNR(on/off) dB: "
              f"{' '.join(f'{s:.0f}' for s in snr)}")
        print(f"  median SNR={np.nanmedian(snr):.1f}dB  worst={np.nanmin(snr):.1f}dB")
