#!/usr/bin/env python3
"""Generate a BATCH of OFDM experiments concatenated into one master WAV for the
laptop -> tape -> speaker -> phone loop. Record the master to tape in one pass,
play it back in one pass, then run tape_batch_decode.py on the phone capture.

Each experiment is one self-contained OFDM frame (own pilot markers), separated by
silence gaps. Frames are matched to experiments by order; each payload is prefixed
with its index "[NN]" as a cross-check. The batch decoder auto-segments the playback
by the 7800 Hz pilot tone (robust to tape hiss / leftover audio in the gaps).
"""
import importlib.util, json, os, tempfile
import numpy as np, soundfile as sf

HERE=os.path.dirname(os.path.abspath(__file__))
spec=importlib.util.spec_from_file_location("modem", os.path.join(HERE,"acoustic_ofdm_modem.py"))
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
SR=mod.SR
GAP=3.5            # silence between frames (s) -- must exceed within-frame marker spacing
LEAD0=3.0         # silence at the very start

OUT_WAV=os.path.join(HERE,"..","RESULTS","tape_test","batch_master.wav")
OUT_MAN=os.path.join(HERE,"..","RESULTS","tape_test","batch_manifest.json")

def filler(n):
    base=("Pack my box with five dozen liquor jugs. The five boxing wizards jump "
          "quickly. Sphinx of black quartz judge my vow. 0123456789. ")
    return (base*((n//len(base))+1))[:n]

MSG={22:"hello cassette ai 2026",
     97:"The quick brown fox jumps over the lazy dog. Cassette AI proves data over sound works! 0123456789",
     240:filler(240), 500:filler(500), 1000:filler(1000), 2000:filler(2000),
     4000:filler(4000), 8000:filler(8000)}

T_REPS=4          # repeats of the throughput grid (statistics on marginal configs)
R_REPS=8          # repeatability runs

# ---- experiment list --------------------------------------------------------
EXP=[]
def add(label,msg,sd,K,nsym=48,chunk=4,flo=1500.0,fhi=7000.0):
    EXP.append(dict(label=label,msg=msg,sd=sd,K=K,nsym=nsym,chunk=chunk,flo=flo,fhi=fhi))

# Group T -- throughput grid (97 B): find the tape's rate ceiling
for rep in range(1,T_REPS+1):
    for K,sd in [(16,100),(16,80),(20,80),(20,60),(24,80),(24,60),(28,60),(32,60),(24,50),(32,50)]:
        add(f"T:K{K}/{sd}ms#{rep}",MSG[97],sd,K)
# Group H -- re-sync density (K=24/60ms,97B): how much does tape wow/flutter need?
for ch in (2,4,8,16):
    add(f"H:chunk{ch}",MSG[97],60,24,chunk=ch)
# Group F -- FEC strength (K=24/60ms,97B,chunk4): minimal parity for the tape
for ns in (8,16,32,48,64):
    add(f"F:RS{ns}",MSG[97],60,24,nsym=ns)
# Group P -- payload size (K=20/80ms robust): sustained decoding under tape errors
# includes ~1 KB and larger -- the real use case is storing a file, not 97 bytes
for n in (22,97,240,500,1000,2000,4000,8000):
    add(f"P:{n}B",MSG[n],80,20)
# Group B -- carrier band (97B,K=16/80ms): does tape treble roll-off hurt high carriers?
add("B:low700-3k",MSG[97],80,16,flo=700,fhi=3000)
add("B:mid1.5-7k",MSG[97],80,16,flo=1500,fhi=7000)
add("B:high3-7k",MSG[97],80,16,flo=3000,fhi=7000)
add("B:wide700-9k",MSG[97],80,16,flo=700,fhi=9000)
# Group R -- repeatability (K=20/80ms,97B): tape consistency / variance
for r in range(1,R_REPS+1):
    add(f"R:rep{r}",MSG[97],80,20)
# Group X -- a couple of aggressive stretch goals
add("X:K32/50/RS64",MSG[97],50,32,nsym=64)
add("X:K28/55/chunk2",MSG[97],55,28,chunk=2)

# ---- build master -----------------------------------------------------------
def build():
    parts=[np.zeros(int(LEAD0*SR),np.float32)]
    manifest=[]; tmp=tempfile.mkdtemp()
    for i,e in enumerate(EXP):
        mod.NSYM=e["nsym"]; mod.CHUNK=e["chunk"]; mod.FLO=float(e["flo"]); mod.FHI=float(e["fhi"])
        msg=f"[{i:02d}]"+e["msg"]
        p=os.path.join(tmp,f"f{i}.wav")
        mod.gen(msg,e["sd"],e["K"],p)
        sig,_=sf.read(p); meta=json.load(open(p+".json"))
        parts.append(sig.astype(np.float32)); parts.append(np.zeros(int(GAP*SR),np.float32))
        manifest.append(dict(idx=i,label=e["label"],config=e,msg=msg,meta=meta,dur=len(sig)/SR))
    master=np.concatenate(parts)
    os.makedirs(os.path.dirname(OUT_WAV),exist_ok=True)
    sf.write(OUT_WAV,master,SR)
    json.dump(manifest,open(OUT_MAN,"w"))
    tot=len(master)/SR
    print(f"\n=== BATCH MASTER: {len(EXP)} experiments, {tot/60:.1f} min ({tot:.0f}s) ===")
    print(f"wrote {OUT_WAV}")
    print(f"wrote {OUT_MAN}")
    # group summary
    from collections import Counter
    g=Counter(e["label"].split(":")[0] for e in EXP)
    print("groups:", dict(g))

if __name__=="__main__":
    build()
