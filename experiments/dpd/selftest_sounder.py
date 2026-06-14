"""Pass sounder_master through a SYNTHETIC channel with known impairments, then check
analyze_sounder recovers them. Validates the sounder design before a real tape pass."""
import json, numpy as np, soundfile as sf
from scipy.signal import resample_poly, butter, sosfiltfilt
import analyze_sounder as A

sig, sr = sf.read("sounder_master.wav"); sig = sig.astype(np.float64)
meta = json.load(open("sounder_master.wav.json"))

# --- known synthetic channel ---
# 1) linear filter: bandpass 400-8000 + two notches (nulls) at 2.6 and 4.3 kHz
def notch(x, f0, bw):
    sos = butter(2, [f0 - bw, f0 + bw], "bandstop", fs=A.SR, output="sos")
    return sosfiltfilt(sos, x)
sos_bp = butter(4, [400, 8000], "bandpass", fs=A.SR, output="sos")
y = sosfiltfilt(sos_bp, sig)
y = notch(y, 2600, 250); y = notch(y, 4300, 250)
# 2) memoryless compression (speaker/tape saturation) -> harmonics
y = np.tanh(1.8 * y) / 1.8
# 3) cassette/phone clock 0.88x
y = resample_poly(y, 88, 100)
# 4) additive noise (~ -34 dB)
rng = np.random.default_rng(0); y = y + 0.02 * rng.standard_normal(len(y))
y *= 0.9 / (np.max(np.abs(y)) + 1e-9)
sf.write("/tmp/sounder_synth.wav", y.astype(np.float32), A.SR)

print("=== synthetic channel: bp 400-8k, notches @2.6k/4.3k, tanh comp, clock0.88, noise ===")
out = A.run("/tmp/sounder_synth.wav", "sounder_master.wav.json")
print()
# checks
ok = True
if not (0.86 < out["clock"] < 0.90): print("FAIL clock", out["clock"]); ok = False
H = np.array(out["H_mag_db"]); f = np.array(out["H_freq"])
# the two notches should appear as local minima in |H|
for fn in (2600, 4300):
    k = np.argmin(np.abs(f - fn)); win = H[max(0, k - 3):k + 4]
    dip = H[k] - np.median(H[(f > 1000) & (f < 6000)])
    print(f"  |H| at {fn} Hz dip = {dip:.1f} dB  {'(null detected)' if dip < -6 else '(MISSED)'}")
    if dip > -6: ok = False
thd_lo = out["sweeps"]["lo"]["thd_db"]; thd_hi = out["sweeps"]["hi"]["thd_db"]
print(f"  THD lo={thd_lo:.1f} hi={thd_hi:.1f} dB  (hi should be worse i.e. higher): "
      f"{'OK' if thd_hi > thd_lo - 2 else 'check'}")
print("\nSELF-TEST:", "PASS" if ok else "NEEDS WORK")
