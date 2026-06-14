"""debug_timing.py — is the residual BER a symbol-TIMING problem?

Bypass find_preamble: take the first mfsk32 section at its globally-known
position, scan the symbol-grid start offset finely, and report BER. If a sharp
BER dip appears at some offset, the demod needs a fine timing search.
"""
import sys, pathlib, json
import numpy as np, soundfile as sf

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for p in ["src", "tests/e2e", "experiments/tape_v2"]:
    sys.path.insert(0, str(ROOT / p))
import hyp_common as hc
import analyze_master2 as AM
from hyp_h2_mfsk import MFSKScheme
import modems_index

SR = 48000
manifest = json.loads((ROOT / "experiments/tape_v2/master2_manifest.json").read_text())
audio, sr = sf.read(ROOT / "experiments/tape_v2/captures/voicememo_trim.wav", dtype="float32", always_2d=False)
if audio.ndim > 1:
    audio = audio.mean(axis=1)
sync = AM.global_sync_and_resample(audio, manifest)
nom = sync["audio_nominal"]
align = sync["chirp0_nominal"] - sync["expected_chirp0"]

sec = next(s for s in manifest["sections"] if s["config"] == "mfsk32")
expected = (ROOT / "experiments/tape_v2" / sec["payload_sidecar"]).read_bytes()
tb = modems_index.tx_bits(expected, "mfsk32")

sch = MFSKScheme(M=32, walsh_k=0)
N = sch.samples_per_sym
freqs = sch.freqs
bps = sch.bits_per_sym
print(f"mfsk32: N={N} samples/sym ({N/SR*1000:.2f}ms) bps={bps} ntones={len(freqs)}")

# Find the preamble end (data start) for this section via find_preamble on a
# tight window, then scan a FINE offset around it.
start = sec["start_sample"] + align
pad = int(0.3 * SR)
w_lo = max(0, start - pad)
window = np.asarray(nom[w_lo: min(len(nom), start + sec["length"] + pad)], dtype=np.float32)
ds = hc.find_preamble(window, 0.25)  # data start within window
print(f"find_preamble data_start = {ds} ({ds/SR:.3f}s into window)")

n_syms = len(tb) // bps

def ber_for_datastart(data, ds0):
    data = data[ds0:]
    nc = min(n_syms, len(data) // N)
    if nc == 0:
        return 1.0
    mat = data[:nc * N].reshape(nc, N).astype(np.float64)
    fft = np.fft.rfft(mat, n=N, axis=1)
    bins = np.clip(np.round(freqs * N / SR).astype(int), 0, fft.shape[1] - 1)
    en = np.abs(fft[:, bins]) ** 2
    syms = np.argmax(en, axis=1)
    rb = np.zeros(nc * bps, dtype=np.uint8)
    for i, s in enumerate(syms):
        rb[i*bps:(i+1)*bps] = np.unpackbits(np.array([int(s)], np.uint8))[-bps:]
    m = min(len(tb), len(rb))
    return (np.count_nonzero(tb[:m] != rb[:m]) + (len(tb) - m)) / len(tb)

print("\nfine symbol-grid offset scan (+/- 1.5 symbols, 1-sample step):")
best = (1.0, 0)
for off in range(-int(1.5 * N), int(1.5 * N)):
    b = ber_for_datastart(window, ds + off)
    if b < best[0]:
        best = (b, off)
print(f"  BEST BER={best[0]:.3f} at offset {best[1]:+d} samples ({best[1]/SR*1000:+.2f}ms)")
print(f"  BER at find_preamble data_start (offset 0): {ber_for_datastart(window, ds):.3f}")

# Also scan a small symbol-RATE correction (clock) at the best offset.
print("\nsymbol-rate (N) scan at best offset:")
bestN = (best[0], N)
for dN in np.arange(-0.20, 0.201, 0.02):
    Nf = N + dN
    data = window[ds + best[1]:]
    nc = min(n_syms, int(len(data) / Nf))
    if nc < 10: continue
    idx = (np.arange(nc) * Nf).astype(int)
    syms = []
    for st in idx:
        seg = data[st:st+N].astype(np.float64)
        if len(seg) < N: break
        fft = np.fft.rfft(seg, n=N)
        bins = np.clip(np.round(freqs*N/SR).astype(int),0,len(fft)-1)
        syms.append(int(np.argmax(np.abs(fft[bins])**2)))
    rb = np.zeros(len(syms)*bps, np.uint8)
    for i,s in enumerate(syms): rb[i*bps:(i+1)*bps]=np.unpackbits(np.array([s],np.uint8))[-bps:]
    m=min(len(tb),len(rb)); ber=(np.count_nonzero(tb[:m]!=rb[:m])+(len(tb)-m))/len(tb)
    if ber < bestN[0]: bestN=(ber,Nf)
print(f"  BEST BER={bestN[0]:.3f} at N={bestN[1]:.2f} (nominal {N})")
