import sys, pathlib, json
sys.path.insert(0,'experiments/deepdive2'); sys.path.insert(0,'experiments/capacity')
import numpy as np, dd_common as dd
from d3d4_combo_tracked import make_tracked_combo, survival
grid=[(12,2),(12,3),(14,2),(14,3),(16,2),(16,3),(18,2),(18,3),(20,2),(20,3),(22,3)]
rows=[]
for (M,K) in grid:
    sch=make_tracked_combo(M,K)
    out=dd.evaluate_dual(sch,n_seeds=16)
    r={'M':M,'K':K,'bps':sch.bits_per_sym,'sanity':out['sanity_ber']}
    for ch in('sim','real'):
        d=out[ch]; r[ch+'_net']=d['net_bps']; r[ch+'_ber']=d['raw_ber']
        r[ch+'_surv']=survival(d['per_seed_ber']); r[ch+'_gross']=d['gross_bps']
        r[ch+'_catastrophic']=float(np.mean(np.array(d['per_seed_ber'])>0.15))
    rows.append(r)
    print('M%2dK%d bps%2d san%.0e |sim net%5.0f surv%.2f |real net%5.0f surv%.2f ber%.4f cat%.2f'%(
        M,K,r['bps'],r['sanity'],r['sim_net'],r['sim_surv'],r['real_net'],r['real_surv'],r['real_ber'],r['real_catastrophic']))
surv_ok=[r for r in rows if r['real_surv']>=0.95 and r['real_catastrophic']==0]
best=max(surv_ok,key=lambda r:r['real_net']) if surv_ok else None
json.dump({'grid':rows,'best_real':best},open('experiments/deepdive2/results/d3d4_refine.json','w'),indent=2,default=float)
print('BEST real robust:', 'M%dK%d real_net=%.0f sim_net=%.0f'%(best['M'],best['K'],best['real_net'],best['sim_net']) if best else None)
