"""Sweep velocity-PLL + track width to extend the flutter envelope of M12K2."""
import sys; sys.path.insert(0,'experiments/deepdive2'); sys.path.insert(0,'experiments/capacity')
import dd_common as dd
import numpy as np, channel as ch
from scipy.signal import resample_poly; from fractions import Fraction
from d3d4_combo_tracked import make_tracked_combo, survival
def chan(audio,snr,fl,clock,seed):
    fr=Fraction(clock).limit_denominator(4000)
    x=resample_poly(audio.astype(np.float64),fr.numerator,fr.denominator)
    return ch.cassette_channel(x,snr_db=snr,wow_flutter_wrms=fl,bandwidth_hz=9000.0,
                               burst_rate_per_s=1.0,burst_length_ms=10.0,seed_offset=seed).astype(np.float32)
def test(sch,flpct,nseed=10):
    bers=[]
    for seed in range(nseed):
        rng=np.random.default_rng(10000+seed); bits=rng.integers(0,2,4000,dtype=np.uint8)
        a=np.asarray(sch.modulate(bits),dtype=np.float32)
        rx=chan(a,30.0,flpct/100.0,0.88,seed)
        rec=np.asarray(sch.demodulate(rx,48000),dtype=np.uint8)
        m=min(len(bits),len(rec)); bers.append((int(np.count_nonzero(bits[:m]!=rec[:m]))+(len(bits)-m))/len(bits))
    return float(np.mean(bers)),survival(bers)
# sanity: vel_gain=0 must match current (BER~0 no channel)
s0=make_tracked_combo(12,2,vel_gain=0.0); 
print('configs: (track,vel_gain,center_bias)')
for (tr,vg,cb) in [(3,0.0,0.03),(5,0.3,0.03),(7,0.3,0.05),(7,0.5,0.05),(9,0.4,0.06)]:
    sch=make_tracked_combo(12,2,track=tr,center_bias=cb,vel_gain=vg)
    san=dd.sanity_no_channel(sch)
    row=[]
    for fl in [0.25,0.44,0.7,1.0,1.5,2.2]:
        ber,sv=test(sch,fl); row.append(f'{fl}:{sv:.1f}/{ber:.2f}')
    print(f'tr{tr} vg{vg} cb{cb} san{san:.0e} | '+' '.join(row))
