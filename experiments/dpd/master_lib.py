"""Shared rendering for the 15-minute experiment master.

Everything is anchored by two global sync CHIRPS (below the data band) so the whole
master maps from a known TX layout to the recording via one clock + offset (matched
filter), regardless of cassette speed. Each experiment section sits at a known TX
sample range in the manifest; the analyzer slices and dispatches by section kind.

OOK frames mirror the production modem byte-for-byte (so modem_frozen.decode reads
them) but add an optional per-carrier PHASE vector -> lets us A/B standard (phase 0,
high PAPR) vs Schroeder-phased (low PAPR) rendering with the SAME, phase-blind decoder.
"""
import importlib.util, os, json, hashlib
import numpy as np
from reedsolo import RSCodec

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("mf", os.path.join(HERE, "modem_frozen.py"))
mod = importlib.util.module_from_spec(_s); _s.loader.exec_module(mod)
SR = mod.SR; MARK_F = mod.MARK_F

# global sync chirps (matched-filter anchors), safely below the 1500 Hz data band
CHIRP_T = 0.20; CHIRP_LO = 900.0; CHIRP_HI = 1400.0


def chirp(up=True):
    n = int(CHIRP_T * SR); t = np.arange(n) / SR
    f0, f1 = (CHIRP_LO, CHIRP_HI) if up else (CHIRP_HI, CHIRP_LO)
    x = np.sin(2 * np.pi * (f0 * t + (f1 - f0) / (2 * CHIRP_T) * t ** 2))
    f = int(0.012 * SR); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
    return (0.7 * x).astype(np.float64)


def schroeder_phases(K):
    return np.array([np.pi * k * (k + 1) / K for k in range(K)])


def carriers(K, flo=1500.0, fhi=7000.0):
    return np.round(np.geomspace(flo, fhi, K)).astype(int)


def crest_factor_db(x):
    r = np.sqrt(np.mean(x ** 2))
    return 20 * np.log10((np.max(np.abs(x)) + 1e-12) / (r + 1e-12))


def _osym_phased(bitvec, fs, ns, phases):
    t = np.arange(ns) / SR; x = np.zeros(ns)
    for b, f, ph in zip(bitvec, fs, phases):
        if b: x += np.sin(2 * np.pi * f * t + ph)
    return x


def gen_ook_frame(msg, symdur_ms, K, nsym=48, chunk=4, phases=None, amp=0.6, lead=0.4):
    """Mirror modem_frozen.gen but with optional per-carrier phases and drive (amp).
    Returns (sig, meta). meta is compatible with modem_frozen.decode."""
    symdur = symdur_ms / 1000.0; ns = int(symdur * SR); fs = carriers(K)
    if phases is None: phases = np.zeros(K)
    data = msg.encode() if isinstance(msg, str) else msg
    cw = bytes(RSCodec(nsym).encode(data))
    bits = np.unpackbits(np.frombuffer(cw, np.uint8))
    pad = (-len(bits)) % K
    if pad: bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
    grid = bits.reshape(K, len(bits) // K).T
    ndata = len(grid)
    npad = (-ndata) % chunk
    if npad: grid = np.vstack([grid, np.zeros((npad, K), np.uint8)])
    nchunks = len(grid) // chunk
    allon = np.ones(K, np.uint8)
    t = np.arange(ns) / SR; pilot = np.sin(2 * np.pi * MARK_F * t)
    fade = int(min(0.004, symdur * 0.1) * SR)
    def render(vec, mark=False):
        x = _osym_phased(vec, fs, ns, phases)
        if mark: x = x + pilot * (np.max(np.abs(x)) / 2 if np.max(np.abs(x)) > 0 else 1)
        if np.max(np.abs(x)) > 0: x *= amp / np.max(np.abs(x))
        if fade > 0: x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
        return x
    parts = [np.zeros(int(lead * SR))]
    syms = [("mark", allon)]
    for j in range(nchunks):
        for g in grid[j * chunk:(j + 1) * chunk]: syms.append(("data", g))
        syms.append(("mark", allon))
    for kind, s in syms: parts.append(render(s, mark=(kind == "mark")))
    parts.append(np.zeros(int(lead * SR)))
    sig = np.concatenate(parts).astype(np.float64)
    meta = dict(symdur=symdur, K=K, freqs=fs.tolist(), ndata_sym=ndata, nbytes=len(cw),
                nsym=nsym, orig=len(data), chunk=chunk, nchunks=nchunks,
                sha=hashlib.sha256(data).hexdigest())
    return sig, meta


def gen_multitone(K, dur, phases_kind, amp):
    """All-K-carrier multitone for the PAPR/IMD probe. phases_kind in {inphase, schroeder,
    random}. Returns (sig, info incl. measured digital crest factor)."""
    ns = int(dur * SR); fs = carriers(K); t = np.arange(ns) / SR
    if phases_kind == "inphase": ph = np.zeros(K)
    elif phases_kind == "schroeder": ph = schroeder_phases(K)
    else:  # deterministic 'random' (no RNG -> reproducible); golden-ratio phases
        ph = (np.arange(K) * 2.399963) % (2 * np.pi)
    x = np.zeros(ns)
    for f, p in zip(fs, ph): x += np.sin(2 * np.pi * f * t + p)
    cf = crest_factor_db(x)
    x = x / (np.max(np.abs(x)) + 1e-9) * amp                # amp = peak drive level
    fade = int(0.02 * SR); x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
    return x.astype(np.float64), dict(kind=phases_kind, amp=amp, crest_db=float(cf),
                                      freqs=fs.tolist(), K=K)
