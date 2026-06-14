"""Product-grade PREAMBLE-DRIVEN adaptive modem (prototype) + synthetic end-to-end test.

Frame:  [LEAD][ PREAMBLE ][ markers + payload ]
        PREAMBLE = known per-carrier ON/OFF training that lets the phone measure, in
        whatever room it is played in, each carrier's ON level AND its OFF/leakage
        level -> true per-carrier SNR -> which carriers to erase/derate. (All-ON
        markers alone can't do this; that is why the existing recording needed the
        decision-directed fallback.)

The decoder bakes in NOTHING about the environment: it syncs by ENERGY-ENVELOPE
cross-correlation (immune to the channel's per-frequency phase scrambling), measures
per-carrier SNR from the preamble, then erases the dead carriers and RS-erasure-
decodes the payload. Validated against a synthetic channel with five deep frequency-
selective nulls + noise + compression: the flat decoder FAILS, the preamble-driven
decoder is byte-exact.

(Scope: this isolates the null-correction concept. Cassette speed offset / wow is a
separate, already-solved problem -- the production modem re-tracks timing at each
pilot marker, proven on the REAL recording at clock 0.89 in chan_lib.py -- so this
synthetic keeps clock = 1.0 rather than re-implement per-marker tracking here.)
"""
import importlib.util, os, numpy as np, hashlib
from scipy.signal import resample_poly, butter, sosfiltfilt
from scipy.ndimage import uniform_filter1d
from reedsolo import RSCodec, ReedSolomonError

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("mf", os.path.join(HERE, "modem_frozen.py"))
mod = importlib.util.module_from_spec(_s); _s.loader.exec_module(mod)
SR = mod.SR

# preamble pattern set: rows of per-carrier ON(1)/OFF(0), repeated for averaging.
def preamble_patterns(K, reps=3):
    # all-ON measures each carrier's received level; all-OFF (in-band silence) measures
    # the noise floor at that carrier. on/floor = the SNR that decides OOK in a null.
    base = [np.ones(K, np.uint8), np.zeros(K, np.uint8)]
    out = []
    for _ in range(reps): out += base
    return out


def gen(msg, symdur_ms, K, nsym=48, chunk=4):
    symdur = symdur_ms / 1000.0; ns = int(symdur * SR); fs = mod.carriers(K)
    data = msg.encode(); cw = bytes(RSCodec(nsym).encode(data))
    grid, _ = mod._bytes_to_bits(cw, K); ndata = len(grid)
    npad = (-ndata) % chunk
    if npad: grid = np.vstack([grid, np.zeros((npad, K), np.uint8)])
    nchunks = len(grid) // chunk
    t = np.arange(ns) / SR; pilot = np.sin(2 * np.pi * mod.MARK_F * t)
    fade = int(min(0.004, symdur * 0.1) * SR)
    def render(vec, mark=False):
        x = mod._osym(vec, fs, ns)
        if mark: x = x + pilot * (np.max(np.abs(x)) / 2 if np.max(np.abs(x)) > 0 else 1)
        if np.max(np.abs(x)) > 0: x *= 0.6 / np.max(np.abs(x))
        if fade > 0: x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
        return x
    parts = [np.zeros(int(0.5 * SR))]
    pre = preamble_patterns(K)
    for v in pre: parts.append(render(v))                # preamble (no pilot)
    parts.append(np.zeros(int(0.2 * SR)))                # gap separates preamble from payload
    allon = np.ones(K, np.uint8)
    parts.append(render(allon, mark=True))
    for j in range(nchunks):
        for g in grid[j * chunk:(j + 1) * chunk]: parts.append(render(g))
        parts.append(render(allon, mark=True))
    parts.append(np.zeros(int(0.5 * SR)))
    sig = np.concatenate(parts).astype(np.float32)
    meta = dict(symdur=symdur, K=K, freqs=fs.tolist(), nchunks=nchunks, chunk=chunk,
                nsym=nsym, nbytes=len(cw), ndata_sym=ndata, npre=len(pre),
                sha=hashlib.sha256(data).hexdigest(), orig=len(data))
    return sig, meta


def _pow_seg(seg, f):
    n = len(seg)
    if n < 2: return 0.0
    w = seg * np.hanning(n); k = np.exp(-2j * np.pi * f * np.arange(n) / SR)
    return np.abs(np.dot(w, k)) / n


def _envelope(x, win=0.02):
    e = uniform_filter1d(np.abs(x), int(win * SR))
    return e / (e.max() + 1e-12)


def sync(rec, meta, tx_ref):
    """Lock to the recording by cross-correlating the ENERGY ENVELOPE against the known
    transmit envelope (immune to the channel's per-frequency phase scrambling). Returns
    (clock, t_m0): clock = phone/cassette ratio, t_m0 = centre time of payload marker 0."""
    from scipy.signal import correlate
    er = _envelope(rec); ds = max(1, int(0.002 * SR))      # decimate envelopes for speed
    erd = er[::ds]
    best = None
    for clk in np.linspace(0.82, 1.02, 41):
        et = _envelope(resample_poly(tx_ref, int(round(1000 * clk)), 1000))[::ds]
        if len(et) >= len(erd): continue
        cc = correlate(erd - erd.mean(), et - et.mean(), mode="valid")
        k = int(np.argmax(cc)); score = cc[k] / (np.linalg.norm(et) + 1e-9)
        if best is None or score > best[0]: best = (score, clk, k * ds)
    _, clock, lag = best
    # marker0 centre in TX time, then scale by clock and add the matched lag
    npre = len(preamble_patterns(meta["K"]))
    tx_m0 = 0.5 + npre * meta["symdur"] + 0.2 + 0.5 * meta["symdur"]
    return clock, lag / SR + tx_m0 * clock


def measure_preamble(rec, meta, clock, t_m0):
    """Read the preamble (indexed relative to the first payload marker) -> per-carrier
    SNR (dB), measured LIVE in whatever room the cassette is played."""
    symdur = meta["symdur"]; ns = int(symdur * clock * SR); fs = np.array(meta["freqs"]); K = meta["K"]
    pats = preamble_patterns(K); npre = len(pats)
    on = [[] for _ in range(K)]; off = [[] for _ in range(K)]
    for i, vec in enumerate(pats):
        # TX offset of preamble symbol i centre from marker0 centre = (i-npre)*symdur - 0.2
        dt = ((i - npre) * symdur - 0.2) * clock
        c = int((t_m0 + dt) * SR)
        seg = rec[c - ns // 3: c + ns // 3]
        if len(seg) < 8: continue
        p = np.array([_pow_seg(seg, f) for f in fs])
        for cc in range(K):
            (on if vec[cc] else off)[cc].append(p[cc])
    snr = np.full(K, 0.0)
    for cc in range(K):
        if on[cc] and off[cc]:
            snr[cc] = 10 * np.log10((np.mean(on[cc]) + 1e-12) / (np.mean(off[cc]) + 1e-12))
    return snr


def decode(rec, meta, tx_ref, snr=None, snr_erase_db=6.0):
    """Decode payload; if snr given, erase carriers below snr_erase_db (preamble-driven)."""
    rec = rec - rec.mean()
    clock, t_m0 = sync(rec, meta, tx_ref)
    symdur = meta["symdur"]; ns = int(symdur * clock * SR); fs = np.array(meta["freqs"]); K = meta["K"]
    chunk = meta["chunk"]; nchunks = meta["nchunks"]; Nd = meta["ndata_sym"]
    bits = []; di = 0
    mk0 = t_m0 * SR
    for j in range(nchunks):
        mc = mk0 + j * (chunk + 1) * ns                   # marker j centre
        gseg = rec[int(mc - ns // 3): int(mc + ns // 3)]
        g = np.maximum(np.array([_pow_seg(gseg, f) for f in fs]), 1e-9)
        for k in range(chunk):
            if di >= Nd: break
            sc = mc + (k + 1) * ns                         # data symbol centre
            seg = rec[int(sc - ns // 3): int(sc + ns // 3)]
            p = np.array([_pow_seg(seg, f) for f in fs])
            bits.append((p > mod.THR * g).astype(np.uint8)); di += 1
    grid = np.array(bits)
    linear = grid.T.reshape(-1)[:meta["nbytes"] * 8]
    cw = np.packbits(linear).tobytes()[:meta["nbytes"]]
    erase = None
    if snr is not None:
        bad = sorted([c for c in range(K) if snr[c] < snr_erase_db], key=lambda c: snr[c])
        eb = []
        for c in bad[:8]:
            lo, hi = c * Nd, (c + 1) * Nd - 1
            sp = list(range(lo // 8, min(hi // 8, meta["nbytes"] - 1) + 1))
            if len(set(eb) | set(sp)) > meta["nsym"]: break
            eb = sorted(set(eb) | set(sp))
        erase = eb
    try:
        d = RSCodec(meta["nsym"]).decode(cw, erase_pos=erase) if erase else RSCodec(meta["nsym"]).decode(cw)
        ok = hashlib.sha256(bytes(d[0])).hexdigest() == meta["sha"]
    except Exception:
        ok = False
    return ok, erase


# ---------------- synthetic end-to-end self-test ----------------
def _synth_channel(sig, seed=0):
    def notch(x, f0, bw):
        return sosfiltfilt(butter(2, [f0 - bw, f0 + bw], "bandstop", fs=SR, output="sos"), x)
    sos = butter(4, [900, 9000], "bandpass", fs=SR, output="sos")  # passes the 7800 Hz pilot
    y = sosfiltfilt(sos, sig)
    # frequency-selective nulls -- the impairment a static channel model fixes. (Cassette
    # speed offset / wow is a SEPARATE, already-solved problem: the production modem tracks
    # it per-marker; proven on the real recording at clock 0.89. We isolate the null-
    # correction concept here, so this synthetic keeps clock = 1.0.)
    # five deep nulls landing on carriers -> 5 byte-bursts, enough to overwhelm flat RS
    for f0, bw in [(2931, 110), (3583, 120), (4096, 130), (5355, 150), (6122, 160)]:
        y = notch(y, f0, bw)
    y = np.tanh(1.3 * y) / 1.3                            # mild compression / IMD
    rng = np.random.default_rng(seed)
    y = y + 0.012 * rng.standard_normal(len(y))
    return (y * 0.9 / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


if __name__ == "__main__":
    msg = ("CASSETTE-AI preamble-driven adaptive decode. Played in an UNKNOWN room, "
           "the phone learns the channel from the training tones and erases the dead "
           "carriers. 0123456789!")
    sig, meta = gen(msg, 70, 24)
    print(f"frame: K={meta['K']} symdur={meta['symdur']*1000:.0f}ms payload={meta['orig']}B "
          f"+RS{meta['nsym']}  preamble={meta['npre']} symbols ({meta['npre']*meta['symdur']:.1f}s)")
    rec = _synth_channel(sig)
    clock, t_m0 = sync(rec, meta, sig)
    print(f"sync: clock={clock:.3f}  first marker @ {t_m0:.2f}s")
    snr = measure_preamble(rec, meta, clock, t_m0)
    print(f"\nlive-measured per-carrier SNR from preamble (dB):")
    print("  " + " ".join(f"{s:3.0f}" for s in snr))
    print(f"  -> carriers flagged dead (<6 dB): "
          f"{[c for c in range(meta['K']) if snr[c] < 6]}  at freqs "
          f"{[meta['freqs'][c] for c in range(meta['K']) if snr[c] < 6]}")
    ok_flat, _ = decode(rec, meta, sig, snr=None)
    ok_adapt, er = decode(rec, meta, sig, snr=snr)
    print(f"\nflat decoder            : {'PASS (byte-exact)' if ok_flat else 'FAIL'}")
    print(f"preamble-driven decoder : {'PASS (byte-exact)' if ok_adapt else 'FAIL'}   "
          f"(erased {len(er or [])} payload bytes on dead carriers)")
    print(f"\nSELF-TEST: {'PASS -- preamble-driven beats flat through an unknown channel' if (ok_adapt and not ok_flat) else 'PASS (both ok)' if ok_adapt else 'NEEDS WORK'}")
