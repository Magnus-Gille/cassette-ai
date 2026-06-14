"""debug_decode.py — isolate WHY the real capture decodes at chance.

Strategy: take ONE known section (first mfsk32 rep), and brute-force scan the
window offset around where the analyzer thinks it is. If a BER dip appears, the
data is THERE and the analyzer's localization is the bug. If BER stays ~0.5
everywhere, the per-section signal is corrupted (acoustic/demod problem).
"""
import sys, pathlib, json
import numpy as np, soundfile as sf
from scipy.signal import correlate

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for p in ["src", "tests/e2e", "experiments/tape_v2"]:
    sys.path.insert(0, str(ROOT / p))
import hyp_common as hc
import modems_index
import analyze_master2 as AM

SR = 48000
CAP = "experiments/tape_v2/captures/voicememo_trim.wav"

manifest = json.loads((ROOT / "experiments/tape_v2/master2_manifest.json").read_text())
audio, sr = sf.read(ROOT / CAP, dtype="float32", always_2d=False)
if audio.ndim > 1:
    audio = audio.mean(axis=1)
print(f"loaded {len(audio)/sr:.0f}s @ {sr}")

# Run the analyzer's own sync so we debug the SAME positions it uses.
sync = AM.global_sync_and_resample(audio, manifest)
nom = sync["audio_nominal"]
align = sync["chirp0_nominal"] - sync["expected_chirp0"]
print(f"sync: speed={sync['speed']:.4f} chirp0_meas={sync['chirp0_meas']} "
      f"({sync['chirp0_meas']/SR:.2f}s) chirp0_nom={sync['chirp0_nominal']} "
      f"expected_c0={sync['expected_chirp0']} align={align} ({align/SR:.2f}s)")

# Where are the section preambles REALLY? Correlate nominal audio against the
# section preamble (800-3200, 0.25s) over the first 2 min.
pre = hc.make_preamble(0.25).astype(np.float64)
seg = nom[:120 * SR].astype(np.float64)
corr = np.abs(correlate(seg, pre, mode="valid"))
# top peaks
thr = corr.max() * 0.5
peaks = []
i = 0
while i < len(corr):
    if corr[i] > thr:
        j = i + np.argmax(corr[i:i + SR // 2])
        peaks.append(int(j))
        i = j + SR // 2
    else:
        i += 1
print(f"section-preamble peaks in first 120s (s): {[round(p/SR,2) for p in peaks[:12]]}")

# First mfsk32 section from manifest.
sec = next(s for s in manifest["sections"] if s["config"] == "mfsk32")
expected = (ROOT / "experiments/tape_v2" / sec["payload_sidecar"]).read_bytes()
tb = modems_index.tx_bits(expected, "mfsk32")
start = sec["start_sample"] + align
length = sec["length"]
print(f"\nfirst mfsk32 section: manifest_start={sec['start_sample']} "
      f"+align -> {start} ({start/SR:.2f}s) length={length} ({length/SR:.2f}s) "
      f"payload={len(expected)}B tx_bits={len(tb)}")

def ber_at(off_samples):
    w_lo = max(0, start + off_samples - int(0.3 * SR))
    w_hi = min(len(nom), start + off_samples + length + int(0.3 * SR))
    win = np.asarray(nom[w_lo:w_hi], dtype=np.float32)
    rb = modems_index.rx_bits(win, "mfsk32")
    m = min(len(tb), len(rb))
    if m == 0:
        return 1.0
    return (np.count_nonzero(tb[:m] != rb[:m]) + (len(tb) - m)) / len(tb)

# Brute-force scan offset +/- 3s in 10ms steps.
print("\nbrute-force offset scan (+/-3s, 10ms step):")
best = (1.0, 0)
for off in range(-int(3 * SR), int(3 * SR), int(0.01 * SR)):
    b = ber_at(off)
    if b < best[0]:
        best = (b, off)
print(f"  BEST: BER={best[0]:.3f} at offset {best[1]/SR:+.3f}s "
      f"(abs pos {(start+best[1])/SR:.2f}s)")
print(f"  BER at align-only (offset 0): {ber_at(0):.3f}")

# Also: what does find_preamble say inside the analyzer's window?
w_lo = max(0, start - int(0.3 * SR))
w_hi = min(len(nom), start + length + int(0.3 * SR))
win = np.asarray(nom[w_lo:w_hi], dtype=np.float32)
ds = hc.find_preamble(win, 0.25)
print(f"\nfind_preamble inside analyzer window: data_start={ds} ({ds/SR:.3f}s into window)")
print(f"  (window is {(w_hi-w_lo)/SR:.2f}s; preamble is 0.25s so expect ~0.30s if aligned)")
