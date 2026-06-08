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
out=os.path.join(os.path.dirname(rec_path),"batch_results.json")
if not runs:
    print("decode: NO pilot tone (7800 Hz) detected -- silent capture, wrong file, or level "
          "too low. No frames to decode.")
    json.dump([],open(out,"w")); sys.exit(2)
# split runs into frames where the gap between consecutive pilot runs > 2.0 s
frames=[]; cur=[runs[0]]
for a,b in runs[1:]:
    if a-cur[-1][1] > 2.0: frames.append(cur); cur=[(a,b)]
    else: cur.append((a,b))
frames.append(cur)
fbounds=[(max(0,fr[0][0]-0.7), min(len(rec)/SR, fr[-1][1]+0.7)) for fr in frames]
print(f"detected {len(frames)} frames (expected {len(manifest)})")

# --- align detected frames to manifest. Initial guess: best contiguous offset by span
#     DURATION (the recording is normally a contiguous run). Then the [NN] payload prefix
#     from successful decodes is the GROUND TRUTH (a frame only decodes byte-exact under its
#     own params) -- use it to correct a wrong global offset and to warn on real drops. ---
det_span=np.array([fr[-1][1]-fr[0][0] for fr in frames])
exp_span=np.array([m["meta"]["nchunks"]*(m["meta"]["chunk"]+1)*m["meta"]["symdur"] for m in manifest])
M=len(frames); N=len(manifest)
if M>N:                                              # more frames than experiments (false splits / extra audio)
    print(f"  !! {M} detected frames > {N} manifest entries; processing first {N}, ignoring extras")
    frames=frames[:N]; fbounds=fbounds[:N]; det_span=det_span[:N]; M=N
best=(1e18,0)
for off in range(0, max(1,N-M+1)):
    e=exp_span[off:off+M]
    if len(e)<M: break
    scale=np.median(det_span/(e+1e-9))
    err=np.sum((det_span-scale*e)**2)
    if err<best[0]: best=(err,off)
off0=best[1]
print(f"  initial align: detected frames -> manifest[{off0}:{off0+M}] (by duration)")

tmp=tempfile.mkdtemp()
def _decode_frame(i, mi):
    """Decode detected frame i against manifest[mi]; return (row, prefix_or_None)."""
    m=manifest[mi]; meta=m["meta"]; t0,t1=fbounds[i]
    seg=rec[int(t0*SR):int(t1*SR)]
    wp=os.path.join(tmp,"s.wav"); jp=os.path.join(tmp,"s.json")
    sf.write(wp,seg.astype(np.float32),SR); json.dump(meta,open(jp,"w"))
    buf=io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): ok,data=mod.decode(wp,jp)
    except Exception: ok,data=False,b""
    exp=m["msg"].encode(); L=max(len(exp),len(data))
    byteerr=sum(1 for k in range(L) if exp[k:k+1]!=data[k:k+1])
    pref=None
    try:
        s=data.decode("utf-8","replace")
        if len(s)>=4 and s[0]=="[" and s[3]=="]": pref=int(s[1:3])
    except Exception: pass
    cfg=m["config"]
    row=dict(idx=mi,label=m["label"],ok=bool(ok),byteerr=byteerr,orig=meta["orig"],
             K=cfg["K"],sd=cfg["sd"],chunk=cfg["chunk"],nsym=cfg["nsym"],
             gross=round(cfg["K"]/(cfg["sd"]/1000.0)),align="?")
    return row,pref

# pass 1: contiguous duration guess
amap=[off0+i for i in range(M)]
res=[_decode_frame(i,amap[i]) for i in range(M)]
# --- prefix-guided repair (review #3): a frame can decode under the WRONG manifest entry
# (so ok=False vs the guessed SHA) yet still carry a parseable [NN] prefix when params match.
# Treat that prefix as evidence: re-decode against manifest[prefix] and ACCEPT only if it
# then verifies byte-exact (self-validating). Fixes a wrong global offset AND mid-batch drops. ---
nrepair=0
for i in range(M):
    row,p=res[i]
    if (not row["ok"]) and p is not None and 0<=p<N and p!=amap[i]:
        nr,npref=_decode_frame(i,p)
        if nr["ok"]:                                  # only trust the prefix if it self-validates
            amap[i]=p; res[i]=(nr,npref); nrepair+=1
if nrepair:
    print(f"  prefix-guided repair: re-mapped {nrepair} frame(s) to their [NN] index")
# warn on monotonicity breaks (a genuinely dropped/extra frame we could not self-validate)
for i in range(1,M):
    if res[i][0]["ok"] and res[i-1][0]["ok"] and amap[i]<=amap[i-1]:
        print(f"  !! non-monotonic mapping at frame {i} (amap {amap[i-1]}->{amap[i]}); possible drop/extra")
rows=[]
for i,(row,p) in enumerate(res):
    row["idx"]=amap[i]; row["align"]="ok" if row["ok"] else "?"
    rows.append(row)

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
