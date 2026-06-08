#!/usr/bin/env python3
"""Multi-tone capacity probe.

For increasing N, play a 1.2 s chord of N equal-energy log-spaced tones across
500-8000 Hz. The speaker is the nonlinear element: with many simultaneous tones
it generates intermodulation products that raise a 'distortion floor' between the
intended tones. We measure tone-to-floor ratio per chord -> the largest N where
all tones stay clearly above the floor is the usable parallel-carrier count
(i.e. is OFDM/many-subcarrier viable, or should we stick to one-tone-at-a-time
MFSK?).
"""
import sys, json
import numpy as np, soundfile as sf

SR=48000
NLIST=[2,4,8,16,32]
CHORD=1.2; GAP=0.6; LEAD=0.6
FLO,FHI=500.0,8000.0

def _freqs(n):
    return np.round(np.geomspace(FLO,FHI,n)).astype(int)

def gen(out):
    parts=[np.zeros(int(LEAD*SR))]; meta=[]
    for n in NLIST:
        fs=_freqs(n); ns=int(CHORD*SR); t=np.arange(ns)/SR
        chord=np.zeros(ns)
        for f in fs: chord+=np.sin(2*np.pi*f*t)
        chord*= (0.6/np.max(np.abs(chord)))    # normalize to avoid clipping (peak 0.6)
        fade=int(0.01*SR); chord[:fade]*=np.linspace(0,1,fade); chord[-fade:]*=np.linspace(1,0,fade)
        parts+=[chord, np.zeros(int(GAP*SR))]
        meta.append({"n":n,"freqs":fs.tolist()})
    parts.append(np.zeros(int(LEAD*SR)))
    x=np.concatenate(parts).astype(np.float32)
    sf.write(out,x,SR); json.dump(meta,open(out+".json","w"))
    print(f"gen: chords N={NLIST}  dur={len(x)/SR:.1f}s -> {out}")

def analyze(rec_path,ref_json):
    meta=json.load(open(ref_json))
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
            if (j-i)*fr/SR>0.4: runs.append((tt[i],tt[j-1]))
            i=j
        else: i+=1
    print(f"found {len(runs)} chords (expected {len(meta)})")
    print("-"*70)
    print(f"{'N':>3} {'min_tone_dB':>11} {'floor_dB':>9} {'tone/floor_dB':>13}  verdict")
    print("-"*70)
    for idx,m in enumerate(meta):
        if idx>=len(runs): break
        t0,t1=runs[idx]; c0=t0+0.15*(t1-t0); c1=t1-0.15*(t1-t0)
        seg=rec[int(c0*SR):int(c1*SR)]
        if len(seg)<2048: continue
        win=seg*np.hanning(len(seg))
        sp=np.abs(np.fft.rfft(win)); f=np.fft.rfftfreq(len(win),1/SR)
        def bandpow(fc,bw=25):
            b=(f>fc-bw)&(f<fc+bw); return sp[b].max() if b.any() else 0
        fs=m["freqs"]
        tones=np.array([bandpow(fc) for fc in fs])
        # floor: sample midpoints between adjacent tones (intermod/noise lands here)
        mids=[(fs[k]+fs[k+1])/2 for k in range(len(fs)-1)]
        if not mids: mids=[fs[0]*0.7]
        floor=np.median([bandpow(fc) for fc in mids])
        ref=np.median(tones)
        min_tone_db=20*np.log10(tones.min()/ref+1e-9)
        floor_db=20*np.log10(floor/ref+1e-9)
        t2f=20*np.log10(tones.min()/(floor+1e-12))
        verdict='clean' if t2f>12 else ('marginal' if t2f>6 else 'mushed')
        print(f"{m['n']:>3} {min_tone_db:>11.1f} {floor_db:>9.1f} {t2f:>13.1f}  {verdict}")
    print("-"*70)
    print("dB are rel. median tone level in that chord. tone/floor = weakest tone above the distortion floor.")

if __name__=="__main__":
    if sys.argv[1]=="gen": gen(sys.argv[2])
    elif sys.argv[1]=="analyze": analyze(sys.argv[2],sys.argv[3])
