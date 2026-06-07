#!/usr/bin/env python3
"""Decode a BATCH recording (phone capture of the tape playback of batch_master.wav).

Auto-segments the recording into frames by the 7800 Hz PILOT tone (robust to tape
hiss / leftover audio in the silence gaps), maps frames to experiments by order
(cross-checked via each payload's "[NN]" prefix), decodes each with its own params
from the manifest, and prints a grouped results table + saves batch_results.json.

Usage: tape_batch_decode.py <recorded.wav> [manifest.json]
"""
import importlib.util, json, os, sys, tempfile, io, contextlib
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt
from scipy.ndimage import uniform_filter1d

HERE=os.path.dirname(os.path.abspath(__file__))
spec=importlib.util.spec_from_file_location("modem", os.path.join(HERE,"acoustic_ofdm_modem.py"))
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
SR=mod.SR

rec_path=sys.argv[1]
man_path=sys.argv[2] if len(sys.argv)>2 else os.path.join(HERE,"..","RESULTS","tape_test","batch_manifest.json")
manifest=json.load(open(man_path))

rec,_=sf.read(rec_path)
if rec.ndim>1: rec=rec.mean(1)
rec=rec-rec.mean()
print(f"recording {len(rec)/SR/60:.1f} min; manifest has {len(manifest)} experiments")

# --- find frames via pilot-tone (7800 Hz) energy envelope ---
sos=butter(4,[mod.MARK_F-250,mod.MARK_F+250],"bandpass",fs=SR,output="sos")
env=uniform_filter1d(sosfiltfilt(sos,rec)**2, size=int(0.025*SR))
hop=int(0.01*SR); e=env[::hop]; t=np.arange(len(e))*hop/SR
active=e>0.12*e.max()
# group active samples into pilot runs (markers)
runs=[]; i=0
while i<len(active):
    if active[i]:
        j=i
        while j<len(active) and active[j]: j+=1
        runs.append((t[i],t[j-1])); i=j
    else: i+=1
runs=[r for r in runs if r[1]-r[0]>0.02]
# split runs into frames where the gap between consecutive pilot runs > 2.0 s
frames=[]; cur=[runs[0]]
for a,b in runs[1:]:
    if a-cur[-1][1] > 2.0: frames.append(cur); cur=[(a,b)]
    else: cur.append((a,b))
frames.append(cur)
fbounds=[(max(0,fr[0][0]-0.7), min(len(rec)/SR, fr[-1][1]+0.7)) for fr in frames]
print(f"detected {len(frames)} frames (expected {len(manifest)})")

# --- align detected frames to manifest by marker-span DURATION (robust to a missed
#     start / dropped frame: the recording is a contiguous prefix manifest[off:]) ---
det_span=np.array([fr[-1][1]-fr[0][0] for fr in frames])
exp_span=np.array([m["meta"]["nchunks"]*(m["meta"]["chunk"]+1)*m["meta"]["symdur"] for m in manifest])
M=len(frames); best=(1e18,0)
for off in range(0, max(1,len(manifest)-M+1)):
    e=exp_span[off:off+M]
    if len(e)<M: break
    scale=np.median(det_span/ (e+1e-9))           # clock scale (~0.85)
    err=np.sum((det_span-scale*e)**2)
    if err<best[0]: best=(err,off)
off=best[1]
print(f"  aligned: detected frames map to manifest[{off}:{off+M}]  (offset {off})")

# --- decode each frame with its experiment's params ---
tmp=tempfile.mkdtemp()
rows=[]; n=M
for i in range(n):
    m=manifest[off+i]; meta=m["meta"]; t0,t1=fbounds[i]
    seg=rec[int(t0*SR):int(t1*SR)]
    wp=os.path.join(tmp,"s.wav"); jp=os.path.join(tmp,"s.json")
    sf.write(wp,seg.astype(np.float32),SR); json.dump(meta,open(jp,"w"))
    buf=io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): ok,data=mod.decode(wp,jp)
    except Exception:
        ok,data=False,b""
    expected=m["msg"].encode()
    L=max(len(expected),len(data)); byteerr=sum(1 for k in range(L) if expected[k:k+1]!=data[k:k+1])
    # cross-check the [NN] prefix
    pref=None
    try:
        s=data.decode("utf-8","replace")
        if s.startswith("[") and s[3]=="]": pref=int(s[1:3])
    except Exception: pass
    align="ok" if pref==(off+i) else (f"->#{pref}" if pref is not None else "?")
    cfg=m["config"]
    gross=cfg["K"]/(cfg["sd"]/1000.0)
    rows.append(dict(idx=off+i,label=m["label"],ok=bool(ok),byteerr=byteerr,
                     orig=meta["orig"],K=cfg["K"],sd=cfg["sd"],chunk=cfg["chunk"],
                     nsym=cfg["nsym"],gross=round(gross),align=align))

# --- report ---
print("\n"+"="*78)
print(f"{'#':>3} {'experiment':<18} {'bytes':>5} {'gross':>6} {'result':>6} {'byteErr':>7} {'align':>6}")
print("-"*78)
passes=0
for r in rows:
    res="PASS" if r["ok"] else "FAIL"
    if r["ok"]: passes+=1
    print(f"{r['idx']:>3} {r['label']:<18} {r['orig']:>5} {r['gross']:>5}b {res:>6} {r['byteerr']:>7} {r['align']:>6}")
print("-"*78)
print(f"TOTAL: {passes}/{len(rows)} byte-exact")

# group summaries
from collections import defaultdict
grp=defaultdict(lambda:[0,0])
for r in rows:
    g=r["label"].split(":")[0]; grp[g][0]+=r["ok"]; grp[g][1]+=1
print("by group: "+"  ".join(f"{g}={p}/{n}" for g,(p,n) in sorted(grp.items())))
# throughput frontier: best gross that passed
ok_gross=[r["gross"] for r in rows if r["ok"] and r["label"].startswith(("T:","X:"))]
if ok_gross: print(f"throughput: highest PASS in T/X grid = {max(ok_gross)} bps gross")

out=os.path.join(os.path.dirname(rec_path),"batch_results.json")
json.dump(rows,open(out,"w"),indent=1)
print(f"saved {out}")
