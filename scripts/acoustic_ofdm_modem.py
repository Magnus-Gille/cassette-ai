#!/usr/bin/env python3
"""OFDM-style acoustic modem (experiment C).

K parallel OOK subcarriers; each OFDM symbol carries K bits (tone present=1).
Long symbols => fine frequency resolution AND many carriers at once (the win over
MFSK). Robust to the iPhone's ~0.88x clock and per-carrier gain variation:

Frame:  [lead silence][P0 = all-ON][data symbols...][P1 = all-ON][tail silence]
  - RMS segmentation finds the active block (bracketed by strong all-ON symbols).
  - clock ratio = block_len / ((Ndata+2)*symdur); refined by maximizing all-ON
    energy at the P0/P1 positions.
  - P0 gives per-carrier "on" gain g[c]; OOK threshold = g[c] * THR.

Usage:
  gen   <msg> <symdur_ms> <K> <out.wav>
  sim   <out.wav>            # decode a clock/noise-impaired synthetic channel
  decode <rec.wav> <out.wav.json>
"""
import sys, json, hashlib
import numpy as np, soundfile as sf
from reedsolo import RSCodec, ReedSolomonError

SR=48000; FLO,FHI=1500.0,7000.0    # strong, flat region of the channel
MARK_F=7800.0            # pilot tone present ONLY in marker symbols (data can't fake it)
THR=0.70                 # OOK threshold as fraction of per-carrier on-gain
NSYM=48                  # Reed-Solomon parity bytes (corrects NSYM/2 byte errors per block)
CHUNK=4                  # data symbols between re-sync pilot markers (tracks clock drift)
LEAD=0.5

def carriers(K): return np.round(np.geomspace(FLO,FHI,K)).astype(int)

def _osym(bitvec, fs, ns):
    t=np.arange(ns)/SR; x=np.zeros(ns)
    for b,f in zip(bitvec,fs):
        if b: x+=np.sin(2*np.pi*f*t)
    return x

def _bytes_to_bits(data, K):
    bits=np.unpackbits(np.frombuffer(data,dtype=np.uint8))
    pad=(-len(bits))%K
    if pad: bits=np.concatenate([bits,np.zeros(pad,np.uint8)])
    nsym=len(bits)//K
    # CARRIER-MAJOR: carrier c owns a contiguous bit-run -> a bad carrier = a byte BURST
    # (RS corrects bursts efficiently) instead of scattered single-byte errors.
    grid=bits.reshape(K,nsym).T                      # grid[s,c] = bits[c*nsym + s]
    return grid, len(data)

def gen(msg, symdur_ms, K, out):
    symdur=symdur_ms/1000.0; ns=int(symdur*SR); fs=carriers(K)
    data=msg.encode()
    cw=bytes(RSCodec(NSYM).encode(data))          # Reed-Solomon: data + NSYM parity
    grid,cwlen=_bytes_to_bits(cw,K)
    ndata=len(grid)
    npad=(-ndata)%CHUNK                             # pad to full chunks (regular marker grid)
    if npad: grid=np.vstack([grid,np.zeros((npad,K),np.uint8)])
    nchunks=len(grid)//CHUNK
    allon=np.ones(K,np.uint8)
    t=np.arange(ns)/SR; pilot=np.sin(2*np.pi*MARK_F*t)
    fade=int(min(0.004,symdur*0.1)*SR)
    parts=[np.zeros(int(LEAD*SR))]
    # regular grid: [mark][CHUNK data] x nchunks [mark]  -> markers at predictable slots
    syms=[]
    for j in range(nchunks):
        syms.append(("mark",allon))
        for g in grid[j*CHUNK:(j+1)*CHUNK]: syms.append(("data",g))
    syms.append(("mark",allon))
    for kind,s in syms:
        x=_osym(s,fs,ns)
        if kind=="mark": x=x+pilot*np.max(np.abs(x))/2 if np.max(np.abs(x))>0 else pilot
        if np.max(np.abs(x))>0: x*=(0.6/np.max(np.abs(x)))
        if fade>0: x[:fade]*=np.linspace(0,1,fade); x[-fade:]*=np.linspace(1,0,fade)
        parts.append(x)
    parts.append(np.zeros(int(LEAD*SR)))
    sig=np.concatenate(parts).astype(np.float32)
    sf.write(out,sig,SR)
    meta={"symdur":symdur,"K":K,"freqs":fs.tolist(),"ndata_sym":ndata,
          "nbytes":cwlen,"nsym":NSYM,"orig":len(data),"chunk":CHUNK,"nchunks":nchunks,
          "sha":hashlib.sha256(data).hexdigest()}
    json.dump(meta,open(out+".json","w"))
    json.dump({"msg":msg},open(out+".txt.json","w"))
    net=len(data)/(len(sig)/SR)
    print(f"gen: '{msg[:40]}...' {len(data)}B +{NSYM} RS -> {len(grid)} sym @ {symdur_ms}ms K={K} "
          f"({K/symdur:.0f} bps gross, ~{net:.0f} B/s net)  dur={len(sig)/SR:.1f}s")

def _pow(x,f):
    n=len(x)
    if n<2: return 0.0
    x=x*np.hanning(n)                       # Hann window kills sidelobe leakage between carriers
    k=np.exp(-2j*np.pi*f*np.arange(n)/SR); return np.abs(np.dot(x,k))/n

def _segment(rec,gap_min=0.30,frame=0.02,skip=0.4):
    fr=int(frame*SR)
    rec=rec.copy(); rec[:int(skip*SR)]=0.0       # ignore startup transients
    rms=np.array([np.sqrt((rec[s:s+fr]**2).mean()) for s in range(0,len(rec)-fr,fr)])
    tt=np.arange(len(rms))*fr/SR; active=rms>0.12*rms.max()
    runs=[];i=0
    while i<len(active):
        if active[i]:
            j=i
            while j<len(active):
                if active[j]: j+=1; continue
                k=j
                while k<len(active) and not active[k]: k+=1
                if (k-j)*frame>=gap_min: break
                else: j=k
            runs.append((tt[i],tt[min(j,len(tt)-1)])); i=j
        else: i+=1
    runs=[r for r in runs if r[1]-r[0]>0.2]
    return max(runs,key=lambda r:r[1]-r[0]) if runs else (0,len(rec)/SR)

def _rs_decode_blocks(cw, nsym, orig, nsize=255):
    """Per-block Reed-Solomon decode (reedsolo chunks the codeword into <=nsize blocks
    shaped [data|parity]). Recovers every block that decodes; for blocks that fail, falls
    back to that block's RAW data bytes (parity stripped) so byte positions stay aligned
    to the original payload -- otherwise cw[:orig] mixes parity in and shifts everything.
    Returns (data_bytes, all_ok)."""
    rs=RSCodec(nsym); out=bytearray(); all_ok=True; i=0
    while i < len(cw):
        block=cw[i:i+nsize]; i+=nsize
        dlen=len(block)-nsym
        if dlen<=0:                                  # malformed trailing block
            all_ok=False; out+=bytes(block); continue
        try:
            out+=bytes(rs.decode(bytes(block))[0])
        except ReedSolomonError:
            all_ok=False; out+=bytes(block[:dlen])   # raw data, parity stripped
    return bytes(out[:orig]), all_ok

def decode(rec_path,meta_path):
    m=json.load(open(meta_path)); symdur=m["symdur"]; fs=np.array(m["freqs"])
    Nd=m["ndata_sym"]; nbytes=m["nbytes"]
    rec,_=sf.read(rec_path)
    if rec.ndim>1: rec=rec.mean(1)
    rec=rec-rec.mean()
    w=int(min(symdur*0.72,0.05)*SR)
    def sympow(center):
        s=int(center*SR-w/2); e=s+w; s=max(0,s); e=min(len(rec),e)
        seg=rec[s:e]; return np.array([_pow(seg,f) for f in fs])
    # --- robust timing via the PILOT tone (present only in marker symbols) ---
    hop=int(0.005*SR); starts=np.arange(int(0.3*SR),len(rec)-w,hop)
    tg=(starts+w/2)/SR
    pilot=np.array([_pow(rec[s:s+w],MARK_F) for s in starts])
    if len(pilot)==0 or pilot.max()<=0:
        print("decode: no signal / pilot tone found (input too short or silent)"); return False,b""
    idx=np.where(pilot>0.30*pilot.max())[0]
    if len(idx)<2:
        print("decode: could not find pilot markers"); return False,b""
    splits=np.where(np.diff(idx)>int(0.5*symdur/0.005))[0]
    groups=np.split(idx,splits+1)
    def cen(grp): return np.sum(tg[grp]*pilot[grp])/np.sum(pilot[grp])
    tdet=np.array([cen(g) for g in groups])
    chunk=m["chunk"]; nchunks=m["nchunks"]; nmark=nchunks+1
    # Fit the marker grid robustly instead of anchoring on the (transient-prone) endpoints:
    # assign each detected marker a relative index, least-squares fit a line, reject
    # outliers (false pilots / endpoint glitches), refit, then place all nmark markers.
    nom=(chunk+1)*symdur                             # nominal marker spacing (clock=1)
    if len(tdet)>=2:
        step0=np.median(np.diff(tdet))
        if not (step0>0): step0=nom
        rel=np.round((tdet-tdet[0])/step0).astype(int)
        for _ in range(2):                           # fit -> reject outliers -> refit
            A=np.vstack([np.ones_like(rel,dtype=float),rel]).T
            (a,b),*_=np.linalg.lstsq(A,tdet,rcond=None)
            if not (b>0): b=step0; a=tdet[0]
            resid=np.abs(tdet-(a+b*rel))
            keep=resid < 0.35*b
            if keep.sum()>=2 and keep.sum()<len(tdet):
                tdet=tdet[keep]; rel=rel[keep]
            else: break
        A=np.vstack([np.ones_like(rel,dtype=float),rel]).T
        (a,b),*_=np.linalg.lstsq(A,tdet,rcond=None)
        if not (b>0): b=step0; a=tdet[0]
    else:
        a=tdet[0]; b=nom
    c=b/nom; nmiss=nmark-len(tdet)                   # recovered clock ratio
    nsym=m.get("nsym",0)
    def _decode_at_offset(q):
        # q = absolute index of the FIRST detected marker (q>0 => a leading marker was
        # dropped). Grid: expected marker j sits at a + (j-q)*b.
        mk=[a+(j-q)*b for j in range(nmark)]
        bits=[]; di=0
        for j in range(nchunks):
            t0m,t1m=mk[j],mk[j+1]; g=np.maximum(sympow(t0m),1e-9)
            for i in range(chunk):
                if di>=Nd: break
                tc=t0m+(i+1)*(t1m-t0m)/(chunk+1)
                bits.append((sympow(tc)>THR*g).astype(np.uint8)); di+=1
        linear=np.array(bits).T.reshape(-1)[:nbytes*8]    # invert carrier-major interleave
        cw=np.packbits(linear).tobytes()[:nbytes]
        if nsym: data,full_ok=_rs_decode_blocks(cw,nsym,m.get("orig",len(cw)))
        else: data,full_ok=cw,True
        ok=(hashlib.sha256(data).hexdigest()==m["sha"])
        return ok,data,full_ok,mk,di
    # Don't hard-anchor the first detected marker to index 0: try a few absolute offsets;
    # the RS/sha check self-validates, so a dropped leading marker is recovered (review #2).
    res=_decode_at_offset(0)
    for q in (1,2):
        if res[0]: break
        r=_decode_at_offset(q)
        if r[0]: res=r; nmiss+=q
    ok,data,full_ok,mk,di=res
    rs_err=("corrected" if full_ok else "RS partial (some blocks failed; raw-stripped)") if nsym else None
    d0,d1=mk[0],mk[-1]
    print(f"  [{len(tdet)} markers found / {nmark} expected ({nmiss} missing/interp); decoded {di}/{Nd}]")
    print(f"decode: clock={c:.4f}  block={d0:.2f}-{d1:.2f}s  RS={rs_err}")
    print(f"  recovered {len(data)}B  sha_match={ok}")
    print(f"  text: {data.decode('utf-8',errors='replace')!r}")
    print(f"  VERDICT: {'PASS (byte-exact)' if ok else 'FAIL'}")
    return ok,data

def sim(out_path, drop_frac=0.12):
    """Decode a synthetic impaired copy modelling the OBSERVED iPhone-capture behaviour:
    pitch-PRESERVING time compression via periodic small sample drops (Continuity buffer
    drops -> ~0.88x duration with discrete timing steps), plus noise. This faithfully
    exercises the marker re-sync. (The old version used resample_poly, which time-compresses
    by *pitch-shifting* every carrier up by 1/0.88 -- the decoder searches fixed freqs, so
    that was a false regression test, not a test of the documented drift handling.)"""
    sig,_=sf.read(out_path)
    if sig.ndim>1: sig=sig.mean(1)
    rng=np.random.default_rng(0)
    seg=int(0.25*SR); drop=int(drop_frac*seg)        # drop `drop` samples every `seg`
    kept=[]; i=0
    while i < len(sig):
        kept.append(sig[i:i+seg]); i+=seg+drop        # drops shorten time, preserve pitch
    y=np.concatenate(kept) if kept else np.asarray(sig)
    y=y+0.015*rng.standard_normal(len(y))
    sf.write("/tmp/_sim.wav",y.astype(np.float32),SR)
    print(f"sim: pitch-preserving drift {len(sig)/SR:.2f}s -> {len(y)/SR:.2f}s "
          f"({len(y)/len(sig):.3f}x) + noise")
    return decode("/tmp/_sim.wav",out_path+".json")

if __name__=="__main__":
    cmd=sys.argv[1]
    if cmd=="gen": gen(sys.argv[2],float(sys.argv[3]),int(sys.argv[4]),sys.argv[5])
    elif cmd=="sim": sim(sys.argv[2])
    elif cmd=="decode": decode(sys.argv[2],sys.argv[3])
