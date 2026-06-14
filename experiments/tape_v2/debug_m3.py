"""debug_m3.py — why does master3 decode at chance on the REAL capture?
Isolate the first frame of the first payload and test sync/demod hypotheses."""
import sys, pathlib, json, dataclasses
import numpy as np, soundfile as sf
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for p in ["src", "tests/e2e", "experiments/tape_v2", "experiments/deepdive2", "experiments/capacity"]:
    sys.path.insert(0, str(ROOT / p))
import hyp_common as hc
import analyze_master2 as am2
import m3_codec as codec
import dd_common as dd
from d3d4_combo_tracked import make_tracked_combo

SR = 48000
CAP = ROOT / "experiments/tape_v2/captures/tape3_run1.wav"
manifest = json.loads((ROOT / "experiments/tape_v2/master3_manifest.json").read_text())

audio, sr = sf.read(CAP, dtype="float32", always_2d=False)
if audio.ndim > 1: audio = audio.mean(1)
sync = am2.global_sync_and_resample(audio, manifest)
nom = sync["audio_nominal"]
align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
print(f"global: clock {sync['speed']:.4f} align {align:+d} ({align/SR:.2f}s)")

# first payload, first frame
sec = manifest["payloads"][0]
name = sec["name"]
rung = codec.RUNGS_BY_NAME[sec["rung"]]
meta = sec["meta"]
if meta.get("frame_bytes") and meta["frame_bytes"] != rung.frame_bytes:
    rung = dataclasses.replace(rung, frame_bytes=int(meta["frame_bytes"]))
expected = (ROOT / "experiments/tape_v2" / sec["payload_sidecar"]).read_bytes()
tx_frames, _ = codec.encode_payload(expected, rung)
sch = make_tracked_combo(rung.M, rung.K)
N = sch.samples_per_sym; bps = sch.bits_per_sym; freqs = sch.freqs
starts = sec["frame_starts"]
print(f"payload {name} rung {rung.name} M{rung.M}K{rung.K} N={N} bps={bps} nframes={len(starts)}")

def ber(rb, tb):
    m = min(len(rb), len(tb))
    return (np.count_nonzero(rb[:m] != tb[:m]) + abs(len(tb)-len(rb))) / max(len(tb),1)

# window for frame 0
fi = 0
nbits = len(tx_frames[fi])
flen = sch.preamble_seconds*SR + int(np.ceil(nbits/bps))*N
pad = int(0.3*SR)
st = starts[fi] + align
w_lo = max(0, int(st - pad)); w_hi = min(len(nom), int(st + flen + pad))
win = np.asarray(nom[w_lo:w_hi], dtype=np.float32)
tb = tx_frames[fi].astype(np.uint8)
print(f"\nframe0: nbits={nbits} flen={flen/SR:.2f}s window={(w_hi-w_lo)/SR:.2f}s")

# (1) per-frame speed estimate — is it misfiring?
r = dd.estimate_speed(win.astype(np.float64), seconds=sch.preamble_seconds)
print(f"(1) per-frame estimate_speed = {r:.4f}  (should be ~1.0 since global already corrected)")

# (2) find_preamble location in the window
ds = hc.find_preamble(win.astype(np.float64), sch.preamble_seconds)
print(f"(2) find_preamble data_start = {ds} ({ds/SR:.3f}s into {pad/SR:.2f}s-padded window; expect ~0.3s)")

# (3) current demod (do_speed=True) BER
rb_cur = np.asarray(sch.demodulate(win, SR), np.uint8).ravel()
print(f"(3) demod as-is (do_speed=True): BER {ber(rb_cur, tb):.3f}")

# (4) demod with do_speed=False (trust the global sync)
syms,_,_ = dd.tracked_tone_demod(win.astype(np.float64), freqs, N, bps,
    n_bits=1<<20, preamble_seconds=sch.preamble_seconds, do_speed=False)
rev=sch._rev_table; cap=sch._sym_cap; K=rung.K
out=[]
for e in syms:
    topk=tuple(sorted(np.argpartition(e,-K)[-K:].tolist()))
    si=min(rev.get(topk,0),cap-1)
    out.extend([(si>>(bps-1-j))&1 for j in range(bps)])
rb_nospeed=np.array(out,np.uint8)
print(f"(4) demod do_speed=False: BER {ber(rb_nospeed, tb):.3f}")

# (5) with per-tone equalization on the energies (do_speed=False)
out2=[]
emat=np.array([e for e in syms])  # (nsym, M)
if len(emat):
    gain=np.median(emat,axis=0,keepdims=True)+1e-9
    for e in (emat/gain):
        topk=tuple(sorted(np.argpartition(e,-K)[-K:].tolist()))
        si=min(rev.get(topk,0),cap-1)
        out2.extend([(si>>(bps-1-j))&1 for j in range(bps)])
print(f"(5) do_speed=False + per-tone EQ: BER {ber(np.array(out2,np.uint8), tb):.3f}")

# (6) FFT-bin energy detection (like the old modem) + EQ + fine timing scan, frame0
print("\n--- FFT-bin detection on frame0 (vs matched-filter) ---")
data_all = win[ds:].astype(np.float64)
bins = np.clip(np.round(freqs * N / SR).astype(int), 0, N//2)
nsym_exp = nbits // bps
def fft_decode(data, eq=True, off=0):
    d = data[off:]
    nc = min(nsym_exp, len(d)//N)
    if nc < 1: return np.zeros(0, np.uint8)
    mat = d[:nc*N].reshape(nc, N)
    en = np.abs(np.fft.rfft(mat, n=N, axis=1)[:, bins])
    if eq: en = en / (np.median(en, axis=0, keepdims=True) + 1e-9)
    out=[]
    for e in en:
        topk=tuple(sorted(np.argpartition(e,-K)[-K:].tolist()))
        si=min(rev.get(topk,0),cap-1)
        out.extend([(si>>(bps-1-j))&1 for j in range(bps)])
    return np.array(out, np.uint8)
print(f"(6a) FFT-bin, no EQ:  BER {ber(fft_decode(data_all,eq=False), tb):.3f}")
print(f"(6b) FFT-bin, +EQ:   BER {ber(fft_decode(data_all,eq=True), tb):.3f}")
# (7) fine timing offset scan with FFT+EQ
best=(1.0,0)
for off in range(-N, N, 2):
    b=ber(fft_decode(data_all,eq=True,off=off), tb)
    if b<best[0]: best=(b,off)
print(f"(7) FFT+EQ best over timing offset +/-N: BER {best[0]:.3f} at off {best[1]} ({best[1]/SR*1000:+.1f}ms)")

# (8) GROUND TRUTH: is the frame where we think, and are the right tones present?
print("\n--- ground-truth tone check, frame0 ---")
from scipy.signal import correlate
pre = hc.make_preamble(sch.preamble_seconds).astype(np.float64)
c = np.abs(correlate(win.astype(np.float64), pre, mode="valid"))
pk = int(np.argmax(c))
print(f"(8) preamble corr peak at {pk/SR:.3f}s into window (ratio {c[pk]/np.median(c):.0f}); ds was {ds/SR:.3f}s")
# expected first data symbol's tones from tx bits
b0 = tb[:bps]
si0 = 0
for j in range(bps): si0 = (si0<<1)|int(b0[j])
# scheme: symbol index -> which K tones. use _table (sym->subset) if present
tbl = getattr(sch,'_table',None)
subset0 = tbl[si0] if tbl is not None and si0 < len(tbl) else None
print(f"(8) first tx symbol idx={si0}; expected lit tone indices (of {rung.M}) = {subset0}")
print(f"(8) tone freqs = {[int(f) for f in freqs]}")
# FFT the first data symbol (right after the corr-found preamble)
dstart = pk + len(pre)
sym = win[dstart:dstart+N].astype(np.float64)
S = np.abs(np.fft.rfft(sym, n=N))
faxis = np.fft.rfftfreq(N, 1/SR)
# energy at each tone freq
te = [float(S[np.argmin(np.abs(faxis-f))]) for f in freqs]
order = np.argsort(te)[::-1]
print(f"(8) measured top-{K} tone indices = {sorted(order[:K].tolist())}  (expected {sorted(subset0) if subset0 is not None else '?'})")
print(f"(8) per-tone energy (norm): {[round(x/max(te),2) for x in te]}")

# (9) per-symbol trace: fixed stride, where does it break? + stride scan
print("\n--- per-symbol trace (fixed stride N), frame0 ---")
exp_syms = []
for s in range(nsym_exp):
    b = tb[s*bps:(s+1)*bps]; v=0
    for j in range(bps): v=(v<<1)|int(b[j])
    exp_syms.append(v)
def detect_at(p):
    seg = win[p:p+N].astype(np.float64)
    if len(seg)<N: return None
    S=np.abs(np.fft.rfft(seg,n=N)); fa=np.fft.rfftfreq(N,1/SR)
    te=np.array([S[np.argmin(np.abs(fa-f))] for f in freqs])
    topk=tuple(sorted(np.argpartition(te,-K)[-K:].tolist()))
    return min(rev.get(topk,-1),cap-1)
dstart = pk + len(pre)
hits=[]
for s in range(min(40,nsym_exp)):
    got = detect_at(dstart + s*N)
    hits.append(got==exp_syms[s])
print("(9) first 40 symbols correct? ", "".join("1" if h else "0" for h in hits))
print(f"    correct in first 40: {sum(hits)}/40")
# (10) stride scan: maybe true symbol period != N
print("\n--- stride scan (effective samples/symbol) ---")
for Neff in [N-1, N-0.5, N, N+0.5, N+1, N+2]:
    ok=0
    for s in range(nsym_exp):
        got=detect_at(int(round(dstart + s*Neff)))
        if got==exp_syms[s]: ok+=1
    print(f"    Neff={Neff:6.1f}: {ok}/{nsym_exp} symbols correct (BER~{1-ok/nsym_exp:.2f})")

# (11) GENIE timing trace: for each symbol, search +/-N for a position that decodes
# it correctly; record the residual vs nominal. Reveals the true timing trajectory.
print("\n--- genie timing trace, frame0 (is a good tracker even possible?) ---")
dstart = pk + len(pre)
resid = []; genie_ok = 0
prev = 0
for s in range(nsym_exp):
    nom_p = dstart + s*N + prev   # carry previous residual (track-like)
    found = None
    for d in range(-N//2, N//2+1):
        if detect_at(nom_p + d) == exp_syms[s]:
            if found is None or abs(d) < abs(found): found = d
    if found is not None:
        genie_ok += 1; prev += found; resid.append(prev)
print(f"(11) genie-decodable symbols: {genie_ok}/{nsym_exp}")
if resid:
    import numpy as _np
    r = _np.array(resid)
    print(f"    timing residual over frame: start {r[0]:+d}, end {r[-1]:+d} samples, "
          f"range {r.max()-r.min()} samples ({(r.max()-r.min())/N:.1f} symbols of wander)")
    # is the per-symbol step small (trackable) or jumpy?
    steps = _np.diff(r)
    print(f"    per-symbol timing step: median {_np.median(_np.abs(steps)):.1f}, max {_np.abs(steps).max()} samples (track=+/-3 in current demod)")

# (12) detection ceiling with PROPER per-tone EQ (gain = high percentile = "on" level)
print("\n--- detection ceiling: proper per-tone EQ (90th-pct gain) ---")
dstart = pk + len(pre)
# build per-symbol energy matrix at nominal grid (no tracking) first
def energies_at(p):
    seg=win[p:p+N].astype(np.float64)
    if len(seg)<N: return None
    S=np.abs(np.fft.rfft(seg,n=N)); fa=np.fft.rfftfreq(N,1/SR)
    return np.array([S[np.argmin(np.abs(fa-f))] for f in freqs])
# genie-timed energy matrix (use residual trajectory from (11) re-derived)
emat=[]; prev=0
for s in range(nsym_exp):
    nom_p=dstart+s*N+prev; bestd=0; bestmatch=False
    for d in range(-N//2,N//2+1):
        e=energies_at(nom_p+d)
        if e is None: continue
        tk=tuple(sorted(np.argpartition(e,-K)[-K:].tolist()))
        if min(rev.get(tk,-1),cap-1)==exp_syms[s]: bestd=d; bestmatch=True; break
    prev+=bestd
    e=energies_at(dstart+s*N+prev); emat.append(e if e is not None else np.zeros(len(freqs)))
emat=np.array(emat)
for pct in [50, 75, 90]:
    gain=np.percentile(emat,pct,axis=0)+1e-9
    ok=0
    for s in range(nsym_exp):
        e=emat[s]/gain
        tk=tuple(sorted(np.argpartition(e,-K)[-K:].tolist()))
        if min(rev.get(tk,-1),cap-1)==exp_syms[s]: ok+=1
    print(f"    genie-timed + EQ(p{pct}): {ok}/{nsym_exp} correct (BER~{1-ok/nsym_exp:.2f})")
# and no-EQ genie ceiling for reference
ok=sum(1 for s in range(nsym_exp) if min(rev.get(tuple(sorted(np.argpartition(emat[s],-K)[-K:].tolist())),-1),cap-1)==exp_syms[s])
print(f"    genie-timed, NO EQ: {ok}/{nsym_exp}")
