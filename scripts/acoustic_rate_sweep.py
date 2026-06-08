#!/usr/bin/env python3
"""Sync-free acoustic tone-discriminability sweep.

Sends back-to-back segments of *alternating* 1200/2400 Hz tones at increasing
symbol rates, silence-separated. One recording tests every rate.

Per segment we compute d(t) = (P2400 - P1200)/(P2400 + P1200) on short frames,
then find the phase that best matches an ideal alternating square wave at that
rate. The resulting agreement (= 1 - bit error rate) and eye opening (mean |d|)
tell us how well the channel carries that rate -- no marker/clock sync needed.
"""
import sys, json
import numpy as np
import soundfile as sf

SR=48000; F0,F1=1200.0,2400.0
SEG=2.5            # seconds of tones per rate
GAP=0.7           # silence between segments
LEAD=0.6
RATES_MS=[100,50,40,30,25,20,15]   # ms per symbol

def _tone(f,n): return np.sin(2*np.pi*f*np.arange(n)/SR)

def gen(out):
    parts=[np.zeros(int(LEAD*SR))]
    meta=[]
    for ms in RATES_MS:
        symdur=ms/1000.0; ns=int(symdur*SR); nsym=int(round(SEG/symdur))
        seg=[]
        for k in range(nsym):
            seg.append(_tone(F1 if k%2 else F0, ns))
        seg=np.concatenate(seg)
        # short fade ends of segment to avoid clicks
        f=int(0.005*SR); seg[:f]*=np.linspace(0,1,f); seg[-f:]*=np.linspace(1,0,f)
        parts.append(seg); parts.append(np.zeros(int(GAP*SR)))
        meta.append({"ms":ms,"symdur":symdur,"nsym":nsym})
    parts.append(np.zeros(int(LEAD*SR)))
    x=np.concatenate(parts).astype(np.float32)*0.6
    sf.write(out,x,SR); json.dump(meta,open(out+".json","w"))
    print(f"gen: {len(RATES_MS)} rate segments {RATES_MS} ms  dur={len(x)/SR:.1f}s -> {out}")

def _power(x,f):
    n=len(x); k=np.exp(-2j*np.pi*f*np.arange(n)/SR); return np.abs(np.dot(x,k))/n

def analyze(rec_path,ref_json):
    meta=json.load(open(ref_json))
    rec,_=sf.read(rec_path)
    if rec.ndim>1: rec=rec.mean(1)
    rec=rec-rec.mean()
    # segment via RMS envelope
    fr=int(0.03*SR)
    rms=np.array([np.sqrt((rec[s:s+fr]**2).mean()) for s in range(0,len(rec)-fr,fr)])
    tt=np.arange(len(rms))*fr/SR
    hot=rms>0.25*rms.max()
    runs=[]; i=0
    while i<len(hot):
        if hot[i]:
            j=i
            while j<len(hot) and hot[j]: j+=1
            if (j-i)*fr/SR>0.4: runs.append((tt[i],tt[j-1]))   # ignore tiny blips
            i=j
        else: i+=1
    print(f"found {len(runs)} segments (expected {len(meta)})")
    if len(runs)!=len(meta):
        print("  segment count mismatch — printing what we have:")
    print("-"*64)
    print(f"{'rate':>8} {'baud':>6} {'agree%':>7} {'eye':>6} {'clock':>6}  result")
    print("-"*64)
    FRAME=0.006; HOP=0.002      # fixed fine grid, independent of rate
    results=[]
    for idx,m in enumerate(meta):
        if idx>=len(runs): break
        t0,t1=runs[idx]; symdur=m["symdur"]
        d0=t0+0.10*(t1-t0); d1=t1-0.10*(t1-t0)
        # --- pass 1: fine d(t) over segment ---
        w=int(FRAME*SR); hop=int(HOP*SR)
        starts=np.arange(int(d0*SR), int(d1*SR)-w, hop)
        d=np.empty(len(starts))
        for i,s in enumerate(starts):
            seg=rec[s:s+w]; p0=_power(seg,F0); p1=_power(seg,F1)
            d[i]=(p1-p0)/(p1+p0+1e-12)
        if len(d)<16: results.append((m,np.nan,np.nan,np.nan)); continue
        # --- estimate alternation period via FFT of d(t) ---
        dd=d-d.mean(); sp=np.abs(np.fft.rfft(dd*np.hanning(len(dd))))
        freqs=np.fft.rfftfreq(len(dd), HOP)          # Hz of the alternation envelope
        f_nom=1.0/(2*symdur)                          # expected alternation freq
        band=(freqs>0.55*f_nom)&(freqs<1.6*f_nom)
        if band.sum()<1: results.append((m,np.nan,np.nan,np.nan)); continue
        f_alt=freqs[band][np.argmax(sp[band])]
        rec_symdur=1.0/(2*f_alt)                      # recorded symbol length (s)
        clock=rec_symdur/symdur
        # --- pass 2: sample each symbol at its center, phase-aligned ---
        nsym=int((d1-d0)/rec_symdur)-1
        if nsym<6: results.append((m,np.nan,np.nan,clock)); continue
        best=0; eye=0
        ideal=np.where(np.arange(nsym)%2==0,1,-1)
        # search phase AND a small rate refinement (absorbs within-segment clock drift)
        for rs_ in rec_symdur*np.linspace(0.97,1.03,13):
            for ph in np.linspace(0,rs_,24,endpoint=False):
                ct=d0+ph+rs_*(np.arange(nsym)+0.5)
                fi=np.clip((((ct-d0)*SR-w/2)/hop).astype(int),0,len(d)-1)
                dc=d[fi]
                agree=np.mean(np.sign(dc)==ideal)
                a=max(agree,1-agree)
                if a>best: best=a; eye=np.mean(np.abs(dc))
        results.append((m,best,eye,clock))
        tag='clean' if best>=0.99 else ('usable' if best>=0.90 else 'broken')
        print(f"{m['ms']:>6}ms {1000/m['ms']:>6.0f} {best*100:>6.1f}% {eye:>6.2f} {clock:>6.2f}  {tag}")
    print("-"*64)
    print("agree% = recovered-vs-sent accuracy (1-BER) at the channel's own clock; eye = tone separation 0..1")
    return results

if __name__=="__main__":
    if sys.argv[1]=="gen": gen(sys.argv[2])
    elif sys.argv[1]=="analyze": analyze(sys.argv[2],sys.argv[3])
