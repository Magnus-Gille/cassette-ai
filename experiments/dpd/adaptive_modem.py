"""Adaptive cassette modem v1 — preamble-driven, wow-tracking, CRC-validated.

Designed for the real use case: ~10 cassettes played in ~10 uncontrolled rooms. ALL
channel intelligence is at the receiver (the phone app); nothing about the playback
environment is baked into the tape.

Frame
  [LEAD 0.5s silence]
  [PREAMBLE : (all-ON, all-OFF) x R]        per-carrier training (NO pilot tone)
  [GAP 0.2s silence]
  [PAYLOAD  : MARK, data x CHUNK, MARK, ... , MARK]   pilot tone on every MARK
  [TAIL 0.5s silence]

Payload bytes = CRC32(msg)[4] ++ msg  ->  Reed-Solomon(nsym)  ->  carrier-major
interleave -> K-carrier OOK symbols.

Decode
  1. ENVELOPE sync          : cross-correlate energy envelope vs known template ->
                              coarse (clock, marker0). Immune to per-freq phase scramble.
  2. PER-MARKER tracking     : snap each MARK to its local 7800 Hz pilot peak (guarded by
                              a 7400 Hz reference) -> follows cassette wow/flutter.
  3. PREAMBLE SNR            : per-carrier on(all-ON)/floor(all-OFF) -> live reliability.
  4. ERASURE LADDER          : try flat; if CRC fails, erase carriers worst-SNR-first and
                              retry; ACCEPT the first hypothesis whose CRC validates.
                              (CRC, not RS-success: RS alone can mis-correct.)
"""
import importlib.util, os, struct, zlib, json
import numpy as np
from scipy.signal import resample_poly, correlate
from scipy.ndimage import uniform_filter1d
from reedsolo import RSCodec, ReedSolomonError

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("mf", os.path.join(HERE, "modem_frozen.py"))
mod = importlib.util.module_from_spec(_s); _s.loader.exec_module(mod)
SR = mod.SR; MARK_F = mod.MARK_F; GUARD_F = 7400.0; THR = mod.THR
LEAD = 0.3; GAP = 0.2; TAIL = 0.3; PRE_REPS = 3
CHIRP_T = 0.15; CHIRP_LO = 1000.0; CHIRP_HI = 1450.0   # sync chirps live BELOW the data band
CHIRP_PAD = 0.1


def _chirp(up=True):
    n = int(CHIRP_T * SR); t = np.arange(n) / SR
    f0, f1 = (CHIRP_LO, CHIRP_HI) if up else (CHIRP_HI, CHIRP_LO)
    x = np.sin(2 * np.pi * (f0 * t + (f1 - f0) / (2 * CHIRP_T) * t ** 2))
    f = int(0.01 * SR); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
    return 0.6 * x


def preamble_patterns(K, reps=PRE_REPS):
    return [p for _ in range(reps) for p in (np.ones(K, np.uint8), np.zeros(K, np.uint8))]


def _frame_bytes(msg_bytes):
    return struct.pack(">I", zlib.crc32(msg_bytes) & 0xffffffff) + msg_bytes


def _unframe(data):
    if len(data) < 4: return None
    crc, body = struct.unpack(">I", data[:4])[0], data[4:]
    return body if (zlib.crc32(body) & 0xffffffff) == crc else None


def gen(msg, symdur_ms, K, nsym=48, chunk=4):
    symdur = symdur_ms / 1000.0; ns = int(symdur * SR); fs = mod.carriers(K)
    body = msg.encode() if isinstance(msg, str) else msg
    payload = _frame_bytes(body)
    cw = bytes(RSCodec(nsym).encode(payload))
    grid, _ = mod._bytes_to_bits(cw, K); ndata = len(grid)
    npad = (-ndata) % chunk
    if npad: grid = np.vstack([grid, np.zeros((npad, K), np.uint8)])
    nchunks = len(grid) // chunk
    t = np.arange(ns) / SR; pilot = 0.6 * np.sin(2 * np.pi * MARK_F * t)
    fade = int(min(0.004, symdur * 0.1) * SR)
    def _fades(x):
        if fade > 0: x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
        return x
    def render(vec):
        x = mod._osym(vec, fs, ns)
        if np.max(np.abs(x)) > 0: x *= 0.6 / np.max(np.abs(x))
        return _fades(x)
    # MARK = a pure, strong pilot tone (no data carriers) -> unambiguous sync, zero
    # data-leakage into the 7800 Hz bin. Per-carrier gain reference comes from the
    # preamble (channel is stable within one cassette frame).
    mark = _fades(pilot.copy())
    parts = [np.zeros(int(LEAD * SR)), _chirp(up=True), np.zeros(int(CHIRP_PAD * SR))]
    for v in preamble_patterns(K): parts.append(render(v))
    parts.append(np.zeros(int(GAP * SR)))
    parts.append(mark.copy())
    for j in range(nchunks):
        for g in grid[j * chunk:(j + 1) * chunk]: parts.append(render(g))
        parts.append(mark.copy())
    parts += [np.zeros(int(CHIRP_PAD * SR)), _chirp(up=False), np.zeros(int(TAIL * SR))]
    sig = np.concatenate(parts).astype(np.float32)
    # TX sample offsets of the two chirp STARTS and of preamble-symbol-0 start
    tx_chirp0 = int(LEAD * SR)
    tx_pre0 = tx_chirp0 + len(_chirp()) + int(CHIRP_PAD * SR)
    tx_mark0 = tx_pre0 + len(preamble_patterns(K)) * ns + int(GAP * SR)
    n_payload = (nchunks * (chunk + 1) + 1) * ns
    tx_chirp1 = tx_mark0 + n_payload + int(CHIRP_PAD * SR)
    meta = dict(symdur=symdur, K=K, freqs=fs.tolist(), nchunks=nchunks, chunk=chunk,
                nsym=nsym, nbytes=len(cw), ndata_sym=ndata, npre=len(preamble_patterns(K)),
                payload_len=len(payload), orig=len(body), ns=ns,
                tx_chirp0=tx_chirp0, tx_pre0=tx_pre0, tx_mark0=tx_mark0, tx_chirp1=tx_chirp1)
    return sig, meta


# ----------------------------- receiver ------------------------------------ #
def _pow_seg(seg, f):
    n = len(seg)
    if n < 2: return 0.0
    w = seg * np.hanning(n); k = np.exp(-2j * np.pi * f * np.arange(n) / SR)
    return np.abs(np.dot(w, k)) / n


def _pilot_score(seg):
    return max(0.0, _pow_seg(seg, MARK_F) - _pow_seg(seg, GUARD_F))


def _matched(rec, ref):
    """Sample index in rec where ref best aligns (matched filter)."""
    return int(np.argmax(np.abs(correlate(rec, ref, mode="valid"))))


def sync(rec, meta):
    """Anchor on the two sync chirps (matched filter). Returns (clock, rx0): rx0 = rec
    sample of the first chirp's start; clock = phone/cassette speed ratio."""
    rx0 = _matched(rec, _chirp(up=True))
    rx1 = _matched(rec, _chirp(up=False))
    clock = (rx1 - rx0) / (meta["tx_chirp1"] - meta["tx_chirp0"])
    return clock, rx0


def _tx2rx(meta, clock, rx0, tx_sample):
    return rx0 + (tx_sample - meta["tx_chirp0"]) * clock


def _pilot_peak(rec, lo, hi, w):
    """Centroid of the guarded-pilot energy in [lo,hi] -> sub-sample marker centre (s)."""
    lo = max(0, lo); hi = min(len(rec) - w, hi)
    if hi <= lo: return None
    cand = np.arange(lo, hi, max(1, int(0.002 * SR)))
    sc = np.array([_pilot_score(rec[c:c + w]) for c in cand])
    if sc.max() <= 0: return None
    keep = sc >= 0.6 * sc.max()                       # the pilot plateau, not one noisy bin
    c0 = np.sum(cand[keep] * sc[keep]) / np.sum(sc[keep]) + w / 2
    return c0 / SR


def track_markers(rec, meta, clock, rx0):
    """Per-marker pilot tracking, each marker seeded by the chirp-anchored prediction and
    snapped to its local pilot peak -> follows cassette wow on top of the global clock."""
    ns = meta["ns"]; chunk = meta["chunk"]; nmark = meta["nchunks"] + 1
    step = (chunk + 1) * ns * clock
    w = int(min(meta["symdur"] * 0.72, 0.05) * clock * SR)
    mk = np.zeros(nmark)
    for j in range(nmark):
        pred = _tx2rx(meta, clock, rx0, meta["tx_mark0"] + j * (chunk + 1) * ns + 0.5 * ns)
        pk = _pilot_peak(rec, int(pred - 0.35 * step), int(pred + 0.35 * step), w)
        mk[j] = pk if pk is not None else pred / SR
    return mk


def measure_preamble(rec, meta, clock, rx0):
    """Per-carrier SNR from the preamble (on=all-ON level, floor=all-OFF level), each
    preamble symbol located via the chirp-anchored TX->RX map."""
    ns = meta["ns"]; fs = np.array(meta["freqs"]); K = meta["K"]; pats = preamble_patterns(K)
    wn = int(0.66 * ns * clock)
    on = [[] for _ in range(K)]; off = [[] for _ in range(K)]
    for i, vec in enumerate(pats):
        c = int(_tx2rx(meta, clock, rx0, meta["tx_pre0"] + (i + 0.5) * ns))
        seg = rec[c - wn // 2: c + wn // 2]
        if len(seg) < 8: continue
        p = np.array([_pow_seg(seg, f) for f in fs])
        for cc in range(K): (on if vec[cc] else off)[cc].append(p[cc])
    snr = np.zeros(K); gain = np.zeros(K)
    for cc in range(K):
        if on[cc]: gain[cc] = np.mean(on[cc])
        if on[cc] and off[cc]:
            snr[cc] = 10 * np.log10((np.mean(on[cc]) + 1e-12) / (np.mean(off[cc]) + 1e-12))
    return snr, np.maximum(gain, 1e-9)


def _demod(rec, meta, mk, clock, gain):
    """Sample data symbols interpolated between tracked markers; threshold each carrier
    against its preamble-measured on-gain -> codeword bytes."""
    ns = int(meta["symdur"] * clock * SR); fs = np.array(meta["freqs"])
    chunk = meta["chunk"]; nchunks = meta["nchunks"]; Nd = meta["ndata_sym"]
    bits = []; di = 0
    for j in range(nchunks):
        t0m, t1m = mk[j] * SR, mk[j + 1] * SR
        for k in range(chunk):
            if di >= Nd: break
            sc = t0m + (k + 1) * (t1m - t0m) / (chunk + 1)
            seg = rec[int(sc - ns // 3): int(sc + ns // 3)]
            p = np.array([_pow_seg(seg, f) for f in fs])
            bits.append((p > THR * gain).astype(np.uint8)); di += 1
    grid = np.array(bits)
    linear = grid.T.reshape(-1)[:meta["nbytes"] * 8]
    return np.packbits(linear).tobytes()[:meta["nbytes"]]


def _carrier_spans(meta):
    K, Nd, nb = meta["K"], meta["ndata_sym"], meta["nbytes"]
    return [list(range(c * Nd // 8, min(((c + 1) * Nd - 1) // 8, nb - 1) + 1)) for c in range(K)]


def decode(rec, meta, q_erase=6.0, max_carriers=8, verbose=False):
    """Full adaptive decode. Returns (msg_bytes_or_None, info)."""
    rec = rec - rec.mean()
    clock, rx0 = sync(rec, meta)                 # chirp-anchored: exact position + clock
    snr, gain = measure_preamble(rec, meta, clock, rx0)
    mk = track_markers(rec, meta, clock, rx0)    # per-marker pilot tracking (rides wow)
    cw = _demod(rec, meta, mk, clock, gain)
    spans = _carrier_spans(meta); rs = RSCodec(meta["nsym"])
    order = sorted(range(meta["K"]), key=lambda c: snr[c])     # worst SNR first
    wow = float(np.std(np.diff(mk)) / (np.mean(np.diff(mk)) + 1e-9) * 100)
    tried = []
    eb = []
    for n in range(0, max_carriers + 1):
        if n > 0:
            c = order[n - 1]
            if snr[c] >= q_erase: break
            ne = sorted(set(eb) | set(spans[c]))
            if len(ne) > meta["nsym"]: break
            eb = ne
        try:
            dec = rs.decode(cw, erase_pos=eb) if eb else rs.decode(cw)
            body = _unframe(bytes(dec[0]))
            tried.append((n, "rs-ok" if body is None else "CRC-OK"))
            if body is not None:
                info = dict(clock=clock, wow_pct=wow, erased_carriers=n,
                            dead=[c for c in order[:n]], snr=snr.tolist(), accept="CRC", tries=tried)
                if verbose: print(f"  decode: clock={clock:.4f} wow={wow:.2f}% erased={n} -> CRC OK")
                return body, info
        except (ReedSolomonError, Exception):
            tried.append((n, "rs-fail"))
    return None, dict(clock=clock, wow_pct=wow, snr=snr.tolist(), accept=None, tries=tried)
