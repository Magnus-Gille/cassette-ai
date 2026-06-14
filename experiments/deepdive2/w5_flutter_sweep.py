"""Find the flutter level where the M12K2 tracker breaks (operating envelope)."""
import sys; sys.path.insert(0,'experiments/deepdive2'); sys.path.insert(0,'experiments/capacity')
import dd_common as dd
import numpy as np, channel as ch, hyp_common as hc
from scipy.signal import resample_poly; from fractions import Fraction
from d3d4_combo_tracked import make_tracked_combo, survival
def chan(audio,snr,fl,clock,seed):
    fr=Fraction(clock).limit_denominator(4000)
    x=resample_poly(audio.astype(np.float64),fr.numerator,fr.denominator)
    return ch.cassette_channel(x,snr_db=snr,wow_flutter_wrms=fl,bandwidth_hz=9000.0,
                               burst_rate_per_s=1.0,burst_length_ms=10.0,seed_offset=seed).astype(np.float32)
sch=make_tracked_combo(12,2)
print('flutter sweep, M12K2, SNR=30dB, clock=0.88')
for flpct in [0.25,0.44,0.7,1.0,1.5,2.2]:
    bers=[]
    for seed in range(10):
        rng=np.random.default_rng(10000+seed); bits=rng.integers(0,2,4000,dtype=np.uint8)
        a=np.asarray(sch.modulate(bits),dtype=np.float32)
        rx=chan(a,30.0,flpct/100.0,0.88,seed)
        rec=np.asarray(sch.demodulate(rx,48000),dtype=np.uint8)
        m=min(len(bits),len(rec)); bers.append((int(np.count_nonzero(bits[:m]!=rec[:m]))+(len(bits)-m))/len(bits))
    print(f'  flutter {flpct:.2f}%: BER {np.mean(bers):.4f} surv {survival(bers):.2f} cat {np.mean(np.array(bers)>0.15):.2f}')
