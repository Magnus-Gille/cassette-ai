"""w5: stress the M12K2 champion against the MEASURED worst-case tape channel
(experiments/dpd/channel_model.json: SNR ~12.6 dB, flutter ~2.2%, clock 0.88),
which is far harsher than the 'worn' preset proxy (36 dB / 0.25%). Robustness check."""
import sys, pathlib, json
sys.path.insert(0,'experiments/deepdive2'); sys.path.insert(0,'experiments/capacity')
import numpy as np, dd_common as dd, channel as ch, hyp_common as hc
from scipy.signal import resample_poly
from fractions import Fraction
from d3d4_combo_tracked import make_tracked_combo, survival

def measured_channel(audio, snr_db, flutter, bw, clock, seed):
    # apply clock (resample by ratio) then cassette_channel with measured params
    fr=Fraction(clock).limit_denominator(4000)
    x=resample_poly(audio.astype(np.float64),fr.numerator,fr.denominator)
    y=ch.cassette_channel(x,snr_db=snr_db,wow_flutter_wrms=flutter,bandwidth_hz=bw,
                          burst_rate_per_s=1.0,burst_length_ms=10.0,seed_offset=seed)
    return y.astype(np.float32)

cm=json.load(open('experiments/dpd/channel_model.json'))
snr_med=float(np.median(cm['snr_db'])); flutter=cm['flutter_pct']/100.0; clock=cm['clock']
print(f'measured tape: SNR_med~{snr_med:.1f}dB flutter~{flutter*100:.1f}% clock~{clock}')

out={}
for (M,K) in [(12,2),(16,2),(20,2)]:
    sch=make_tracked_combo(M,K)
    for cfg_name,(snr,fl,bw) in {'measured_worst':(max(snr_med,12.6),flutter,9000.0),
                                  'measured_midSNR':(20.0,flutter,9000.0)}.items():
        bers=[]
        for seed in range(12):
            rng=np.random.default_rng(10000+seed); bits=rng.integers(0,2,4000,dtype=np.uint8)
            a=np.asarray(sch.modulate(bits),dtype=np.float32)
            rx=measured_channel(a,snr,fl,bw,clock,seed)
            rec=np.asarray(sch.demodulate(rx,48000),dtype=np.uint8)
            m=min(len(bits),len(rec)); bers.append((int(np.count_nonzero(bits[:m]!=rec[:m]))+(len(bits)-m))/len(bits))
        ber=float(np.mean(bers)); proj=hc.project_to_cassette(ber,0,sch.gross_bps)
        surv=survival(bers); cat=float(np.mean(np.array(bers)>0.15))
        key=f'M{M}K{K}_{cfg_name}'; out[key]={'snr':snr,'flutter':fl,'ber':ber,'net':proj['net_bps'],'surv':surv,'cat':cat}
        print(f'{key}: SNR{snr:.0f} fl{fl*100:.1f}% BER{ber:.4f} net{proj["net_bps"]:.0f} surv{surv:.2f} cat{cat:.2f}')
json.dump(out,open('experiments/deepdive2/results/w5_measured.json','w'),indent=2,default=float)
print('[saved]')
