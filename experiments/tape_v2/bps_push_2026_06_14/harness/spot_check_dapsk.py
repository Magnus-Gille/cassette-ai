"""Independent spot-check: re-run dapsk16 variant 'd' + bulk-frame myself,
confirm the gauntlet's headline numbers reproduce (don't trust self-reports)."""
import importlib.util, pathlib, sys
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score as sc, replay_channel as rc, evaluate as ev
rc.register_replay_channels(["tape10"])

def load(modpath, name):
    spec = importlib.util.spec_from_file_location(name, modpath)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m
    spec.loader.exec_module(m); return m

CAND = HERE.parent / "candidates"
dapsk = load(CAND / "dapsk16-strongmids.py", "dapsk16mod")

print("=== SPOT-CHECK dapsk16 variant 'd' (claimed model_net 6774) ===", flush=True)
fs = dapsk.build("d")
# clean self-check
rng = np.random.default_rng(0); bits = rng.integers(0,2,4000,dtype=np.uint8)
clean = np.mean(bits != fs.demodulate(np.asarray(fs.modulate(bits),np.float32),48000)[:len(bits)])
print(f"clean_ber={clean:.5f}  gross={fs.gross_bps:.0f}", flush=True)
r = sc.score_candidate(fs, channels=("replay_tape10",), also_simB=False, n_seeds=6, payload_bits=6000)
print(f"VERDICT={r['verdict']} worst_model_net={r['worst_model_net_bps']:.0f} "
      f"replay_ber={r['per_channel']['replay_tape10']['ber']:.4f}  (claim 6774)", flush=True)

print("\n=== SPOT-CHECK bulk-frame on r8 (claimed 7279 at long frame) ===", flush=True)
for pb in (6000, 40000):
    fr8 = ev.build_dense2x_candidate(22, 179, name=f"r8_pb{pb}")
    rr = sc.score_candidate(fr8, channels=("replay_tape10",), also_simB=False, n_seeds=6, payload_bits=pb)
    print(f"payload_bits={pb:6d} symbols~{pb//6} model_net={rr['worst_model_net_bps']:.0f} "
          f"ber={rr['per_channel']['replay_tape10']['ber']:.4f}", flush=True)
print("\n[spot-check done]", flush=True)
