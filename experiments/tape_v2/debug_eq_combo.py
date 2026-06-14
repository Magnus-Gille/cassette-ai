"""Test equalized combinatorial demod on the real capture — count CRC byte-exact passes."""
import sys, pathlib, json
import numpy as np, soundfile as sf

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for p in ["src", "tests/e2e", "experiments/tape_v2"]:
    sys.path.insert(0, str((ROOT / p).resolve()))
import hyp_common as hc, analyze_master2 as AM
import modems_combo as MC

SR = 48000
m = json.loads((ROOT / "experiments/tape_v2/master2_manifest.json").read_text())
y, sr = sf.read(ROOT / "experiments/tape_v2/captures/voicememo_trim.wav", dtype="float32", always_2d=False)
if y.ndim > 1:
    y = y.mean(1)
sync = AM.global_sync_and_resample(y, m)
nom = sync["audio_nominal"]
align = sync["chirp0_nominal"] - sync["expected_chirp0"]


def eq_demod_bits(window, cfg, equalize=True):
    sc = MC._get_scheme(cfg)
    N = sc.samples_per_sym
    ds = hc.find_preamble(window, sc.preamble_seconds)
    data = window[ds:]
    nc = len(data) // N
    if nc == 0:
        return np.zeros(0, np.uint8)
    mat = data[:nc * N].reshape(nc, N).astype(np.float64)
    fft = np.fft.rfft(mat, n=N, axis=1)
    bins = np.clip(sc._bin_indices, 0, fft.shape[1] - 1)
    en = np.abs(fft[:, bins])
    if equalize:
        # blind per-tone equalization: normalise each tone by its across-symbol
        # median energy (robust channel-gain estimate); flattens tape/AAC colouring.
        gain = np.median(en, axis=0, keepdims=True) + 1e-9
        en = en / gain
    topk = np.argpartition(en, -sc.K, axis=1)[:, -sc.K:]
    bps = sc.bits_per_sym
    out = np.empty(nc * bps, np.uint8)
    for i in range(nc):
        subset = tuple(sorted(topk[i].tolist()))
        si = min(sc._rev_table.get(subset, 0), sc._sym_cap - 1)
        out[i*bps:(i+1)*bps] = sc._sym_to_bits(si)
    return out


for cfg in ["c2_m32_k2", "c2_m32_k4", "c2_m48_k6"]:
    secs = [s for s in m["sections"] if s["config"] == cfg]
    raw_pass = eq_pass = 0
    raw_bers, eq_bers = [], []
    for sec in secs:
        exp = (ROOT / "experiments/tape_v2" / sec["payload_sidecar"]).read_bytes()
        tb = MC.tx_bits(exp, cfg)
        start = sec["start_sample"] + align
        pad = int(0.3 * SR)
        win = np.asarray(nom[max(0, start - pad): min(len(nom), start + sec["length"] + pad)], np.float32)
        for equalize, bers, passes_name in [(False, raw_bers, "raw"), (True, eq_bers, "eq")]:
            rb = eq_demod_bits(win, cfg, equalize)
            mm = min(len(tb), len(rb))
            ber = (np.count_nonzero(tb[:mm] != rb[:mm]) + (len(tb) - mm)) / len(tb)
            bers.append(ber)
            # CRC check via modems_combo framing
                # recount passes explicitly
    for sec in secs:
        exp = (ROOT / "experiments/tape_v2" / sec["payload_sidecar"]).read_bytes()
        start = sec["start_sample"] + align
        pad = int(0.3 * SR)
        win = np.asarray(nom[max(0, start - pad): min(len(nom), start + sec["length"] + pad)], np.float32)
        for equalize, flag in [(False, "raw"), (True, "eq")]:
            rb = eq_demod_bits(win, cfg, equalize)
            rec = MC._parse_frame(np.packbits(rb).tobytes())
            if rec == exp:
                if equalize: eq_pass += 1
                else: raw_pass += 1
    print(f"{cfg:12s} reps={len(secs):3d}  raw: BER {np.mean(raw_bers):.3f} pass {raw_pass:3d}   "
          f"EQ: BER {np.mean(eq_bers):.3f} pass {eq_pass:3d}")
