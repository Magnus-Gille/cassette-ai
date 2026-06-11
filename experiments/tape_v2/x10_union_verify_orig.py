"""x10_union_verify_orig.py -- confirm the union-recovered m4/m5 packed blobs
unpack to the ORIGINAL payload (sha256 vs manifest) = orig-exact, the record
standard. Deterministic, no RNG."""
import json, pathlib, sys, hashlib, zlib
from fractions import Fraction
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
_HERE = pathlib.Path("/Users/magnus/repos/cassette-ai/experiments/tape_v2")
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT/"src", ROOT/"tests/e2e", ROOT/"experiments/deepdive2", ROOT/"experiments/capacity", _HERE):
    sys.path.insert(0, str(_p))
import analyze_master2 as am2, m3_codec as codec, m9_decode as md
from x9_resampling_pll import ResamplingPLLDemod
from h9_payload_codec import unpack_payload
from x10_union_probe import _rx_mat, _per_cw_decode, _assemble, FRONTENDS

SR = codec.FS
cap = str(_HERE/"captures/tape9_run1.wav")
manifest = json.loads((_HERE/"master9_manifest.json").read_text())
audio, sr = sf.read(cap, dtype="float32", always_2d=False)
if audio.ndim > 1: audio = audio.mean(axis=1)
if sr != SR:
    frac = Fraction(SR, sr).limit_denominator(20000)
    audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
sync = am2.global_sync_and_resample(audio, manifest)
audio_nom = sync["audio_nominal"]; align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
secs = {s["name"]: s for s in manifest["ws_payloads"]}
out = {}
for name in ("m9_m4_n256_rs159", "m9_m5_n256_rs179"):
    sec = secs[name]; sch = md._scheme_from_entry(sec); meta = sec["meta"]
    crc = sec["crc32_codewords"]; n_cw = meta["n_codewords"]
    union = [None]*n_cw
    for fe_name, kw in FRONTENDS:
        if all(m is not None for m in union): break
        dem = ResamplingPLLDemod(sch, **kw)
        rx, _ = md._demod_section_frames(audio_nom, sec, align, sch,
                                         lambda w, nd, d=dem: d.demod(w, nd))
        ok, msgs = _per_cw_decode(_rx_mat(rx, meta), meta, crc)
        for i in range(n_cw):
            if union[i] is None and msgs[i] is not None: union[i] = msgs[i]
    packed = _assemble(meta, union)
    orig = unpack_payload(packed)
    sha = hashlib.sha256(orig).hexdigest()
    pk = sec["pack"]
    out[name] = {"cw_unrecovered": sum(m is None for m in union),
                 "packed_exact": packed == (_HERE/sec["payload_sidecar"]).read_bytes(),
                 "orig_exact": sha == pk["sha256_orig"] and len(orig) == pk["orig_len"],
                 "orig_len": len(orig), "net_bps": sec.get("projected_net_bps")}
    print(name, out[name], flush=True)
(_HERE/"results/x10_union_orig_verify_tape9_run1.json").write_text(json.dumps(out, indent=2))
print("wrote results/x10_union_orig_verify_tape9_run1.json")
