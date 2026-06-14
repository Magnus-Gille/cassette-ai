# Adversarial high-seed verification of the M14K2 real-survival headline.
import sys, json, pathlib
sys.path.insert(0,'experiments/deepdive2'); sys.path.insert(0,'experiments/capacity')
import numpy as np, dd_common as dd
from d3d4_combo_tracked import make_tracked_combo, survival
out={}
for (M,K) in [(14,2),(12,2),(16,2)]:
    sch=make_tracked_combo(M,K)
    ev=dd.evaluate_dual(sch,n_seeds=32)
    r={'M':M,'K':K,'sanity':ev['sanity_ber']}
    for ch in('sim','real'):
        d=ev[ch]; r[ch+'_net']=d['net_bps']; r[ch+'_ber']=d['raw_ber']
        r[ch+'_surv']=survival(d['per_seed_ber'])
        r[ch+'_cat']=float(np.mean(np.array(d['per_seed_ber'])>0.15))
        r[ch+'_maxber']=float(np.max(d['per_seed_ber']))
    out['M%dK%d'%(M,K)]=r
    print('M%dK%d san%.0e |sim net%5.0f surv%.2f |real net%5.0f surv%.2f ber%.4f cat%.2f maxber%.3f'%(
        M,K,r['sanity'],r['sim_net'],r['sim_surv'],r['real_net'],r['real_surv'],r['real_ber'],r['real_cat'],r['real_maxber']))
json.dump(out,open('experiments/deepdive2/results/d3d4_verify.json','w'),indent=2,default=float)
print('[saved] verify')
