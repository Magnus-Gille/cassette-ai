#!/usr/bin/env python3
"""MFSK over-the-air probe.

Each symbol = one of M log-spaced tones (500-8000 Hz) => log2(M) bits/symbol.
Tests several symbol rates. Decoder is self-clocking: it searches clock ratio
(near the known ~0.88 iPhone offset) and phase to maximize decode confidence
(top-tone / runner-up), then reports symbol-error-rate and net bits/sec.
"""
import sys, json
import numpy as np, soundfile as sf

SR=48000; FLO,FHI=500.0,8000.0
M=16
SYMMS=[80,40,25]      # ms per symbol -> 12.5/25/40 baud, 4 bits/sym
SEG_SYM=40            # symbols per rate segment
GAP=0.6; LEAD=0.6
SEED=7

def freqs(): return np.round(np.geomspace(FLO,FHI,M)).astype(int)

def gen(out):
    rng=np.random.default_rng(SEED); fs=freqs()
    parts=[np.zeros(int(LEAD*SR))]; meta=[]
    for ms in SYMMS:
        symdur=ms/1000.0; ns=int(symdur*SR); t=np.arange(ns)/SR
        syms=rng.integers(0,M,SEG_SYM); seg=[]
        fade=int(min(0.004,symdur*0.1)*SR)
        for s in syms:
            tone=np.sin(2*np.pi*fs[s]*t).copy()
            if fade>0: tone[:fade]*=np.linspace(0,1,fade); tone[-fade:]*=np.linspace(1,0,fade)
            seg.append(tone)
        seg=np.concatenate(seg)
        parts+=[seg, np.zeros(int(GAP*SR))]
        meta.append({"ms":ms,"symdur":symdur,"syms":syms.tolist()})
    parts.append(np.zeros(int(LEAD*SR)))
    x=np.concatenate(parts).astype(np.float32)*0.6
    sf.write(out,x,SR); json.dump({"M":M,"freqs":fs.tolist(),"segs":meta},open(out+".json","w"))
    print(f"gen: MFSK M={M}, rates {SYMMS}ms, {SEG_SYM} sym/seg  dur={len(x)/SR:.1f}s -> {out}")

def _pow(x,f):
    n=len(x); k=np.exp(-2j*np.pi*f*np.arange(n)/SR); return np.abs(np.dot(x,k))/n

def analyze(rec_path,ref_json):
    R=json.load(open(ref_json)); fs=np.array(R["freqs"]); meta=R["segs"]
    rec,_=sf.read(rec_path)
    if rec.ndim>1: rec=rec.mean(1)
    rec=rec-rec.mean()
    fr=int(0.03*SR)
    rms=np.array([np.sqrt((rec[s:s+fr]**2).mean()) for s in range(0,len(rec)-fr,fr)])
    tt=np.arange(len(rms))*fr/SR
    hot=rms>0.25*rms.max(); runs=[];i=0
    while i<len(hot):
        if hot[i]:
            j=i
            while j<len(hot) and hot[j]: j+=1
            if (j-i)*fr/SR>0.3: runs.append((tt[i],tt[j-1]));
            i=j
        else: i+=1
    print(f"found {len(runs)} segments (expected {len(meta)})")
    print("-"*70)
    print(f"{'rate':>7} {'baud':>5} {'SER%':>6} {'bits/s':>7} {'clock':>6}  result")
    print("-"*70)
    for idx,m in enumerate(meta):
        if idx>=len(runs): break
        t0,t1=runs[idx]; symdur=m["symdur"]; truth=np.array(m["syms"]); N=len(truth)
        d0=t0; d1=t1
        # precompute per-frame candidate powers on a fine grid
        w=int(min(symdur*0.6,0.04)*SR); hop=int(0.002*SR)
        starts=np.arange(int(d0*SR),int(d1*SR)-w,hop)
        P=np.empty((len(starts),len(fs)))
        for r,s in enumerate(starts):
            seg=rec[s:s+w]
            P[r]=[_pow(seg,f) for f in fs]
        if len(starts)<N: print(f"{m['ms']:>5}ms  too few frames"); continue
        tgrid=(starts+w/2)/SR
        best=(-1,None,None)
        for c in np.linspace(0.84,0.94,21):
            rs=symdur*c
            for ph in np.linspace(0,rs,10,endpoint=False):
                ct=d0+ph+rs*(np.arange(N)+0.5)
                if ct[-1]>d1: continue
                fi=np.clip(np.searchsorted(tgrid,ct),0,len(starts)-1)
                rows=P[fi]
                top=np.sort(rows,axis=1)
                conf=np.mean(top[:,-1]/(top[:,-2]+1e-12))
                if conf>best[0]: best=(conf,c,fi)
        if best[1] is None: print(f"{m['ms']:>5}ms  no alignment"); continue
        c=best[1]; rows=P[best[2]]; dec=np.argmax(rows,axis=1)
        ser=np.mean(dec!=truth)
        bits=np.log2(M)*(1/symdur)*(1-ser)         # net good bits/sec
        tag='clean' if ser==0 else ('usable' if ser<=0.05 else 'broken')
        print(f"{m['ms']:>5}ms {1000/m['ms']:>5.0f} {ser*100:>6.1f} {bits:>7.0f} {c:>6.2f}  {tag}")
    print("-"*70)
    print(f"M={M} -> {int(np.log2(M))} bits/symbol. bits/s = net error-free throughput.")

if __name__=="__main__":
    if sys.argv[1]=="gen": gen(sys.argv[2])
    elif sys.argv[1]=="analyze": analyze(sys.argv[2],sys.argv[3])
