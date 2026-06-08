#!/usr/bin/env python3
"""Regression tests for the acoustic OFDM modem (scripts/acoustic_ofdm_modem.py).

These encode the byte-exact invariants the modem is built on -- they would have caught
most of the bugs found in cross-model review (interleave inversion, RS framing, marker
timing, the drift `sim`, the no-pilot guard).

Runs two ways:
  * `pytest tests/test_acoustic_modem.py`
  * `python3 tests/test_acoustic_modem.py`   (no pytest needed)
"""
import importlib.util, os, io, tempfile, contextlib
import numpy as np, soundfile as sf

HERE=os.path.dirname(os.path.abspath(__file__))
MODEM=os.path.join(HERE,"..","scripts","acoustic_ofdm_modem.py")
spec=importlib.util.spec_from_file_location("modem",MODEM)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
SR=mod.SR

CFGS=[(100,16),(80,20),(60,24)]           # (symdur_ms, K) -- small set, fast in CI
MSG="The quick brown fox 0123456789"

def _gen_decode(msg, sd, K, tmp, sim=False):
    wav=os.path.join(tmp,"t.wav")
    with contextlib.redirect_stdout(io.StringIO()):
        mod.gen(msg, sd, K, wav)
        ok,data=(mod.sim(wav) if sim else mod.decode(wav, wav+".json"))
    return ok,data

def test_clean_roundtrip():
    """gen -> decode is byte-exact for every config (interleave + RS + marker timing)."""
    with tempfile.TemporaryDirectory() as tmp:
        for sd,K in CFGS:
            ok,data=_gen_decode(MSG,sd,K,tmp)
            assert ok and data==MSG.encode(), f"clean roundtrip failed @ K{K}/{sd}ms: {data!r}"

def test_sim_drift_roundtrip():
    """gen -> sim (pitch-preserving clock drift) is byte-exact (review #1)."""
    with tempfile.TemporaryDirectory() as tmp:
        for sd,K in CFGS:
            ok,data=_gen_decode(MSG,sd,K,tmp,sim=True)
            assert ok and data==MSG.encode(), f"sim drift failed @ K{K}/{sd}ms: {data!r}"

def test_rs_multiblock_roundtrip():
    """A payload spanning multiple 255-byte Reed-Solomon blocks round-trips byte-exact."""
    big=("cassette-ai multiblock payload "*30).encode()[:600]
    with tempfile.TemporaryDirectory() as tmp:
        ok,data=_gen_decode(big.decode(),80,20,tmp)
        assert ok and data==big, f"multi-block RS roundtrip failed ({len(data)}B)"

def test_interleave_is_invertible():
    """Carrier-major bit-interleave and its decoder inversion are exact (review-class bug)."""
    for data in (b"abcdefghij", bytes(range(40)), b"\x00\xff"*17):
        for K in (12,16,24):
            grid,_=mod._bytes_to_bits(data,K)            # (nsym, K), carrier-major
            linear=grid.T.reshape(-1)[:len(data)*8]      # decoder's inversion
            rec=np.packbits(linear).tobytes()[:len(data)]
            assert rec==data, f"interleave not invertible K={K}, {len(data)}B"

def test_rs_block_fallback_preserves_alignment():
    """On an uncorrectable middle block, the fallback keeps payload byte positions aligned."""
    from reedsolo import RSCodec
    nsym=16; orig=600
    data=bytes((i*7)%256 for i in range(orig))
    cw=bytearray(RSCodec(nsym).encode(data))
    cw[300]^=0xFF; cw[301]^=0xFF; cw[302]^=0xFF       # corrupt a middle block beyond repair
    out,full_ok=mod._rs_decode_blocks(bytes(cw),nsym,orig)
    assert len(out)==orig, f"fallback length {len(out)} != {orig}"
    # first block (intact) must decode correctly -> byte positions stay aligned
    assert out[:200]==data[:200], "early payload bytes not aligned after a later-block failure"

def test_decode_silence_returns_false():
    """Decoding silence / a too-short input fails gracefully, not with an exception (review #5)."""
    with tempfile.TemporaryDirectory() as tmp:
        # need a meta to call decode; gen one, then decode pure silence against it
        wav=os.path.join(tmp,"t.wav")
        with contextlib.redirect_stdout(io.StringIO()): mod.gen(MSG,100,16,wav)
        sil=os.path.join(tmp,"sil.wav"); sf.write(sil,np.zeros(SR//2,np.float32),SR)
        with contextlib.redirect_stdout(io.StringIO()):
            ok,data=mod.decode(sil,wav+".json")
        assert ok is False and data==b"", "silence should decode to (False, b'')"

def test_missing_first_marker():
    """review #2 (fixed): a dropped FIRST marker is recovered -- decode() tries absolute
    marker offsets and self-validates via the RS/sha check, so the grid no longer hard-
    anchors marker 0 to the first detected pilot."""
    sd,K=100,16
    with tempfile.TemporaryDirectory() as tmp:
        wav=os.path.join(tmp,"t.wav")
        with contextlib.redirect_stdout(io.StringIO()): mod.gen(MSG,sd,K,wav)
        sig,_=sf.read(wav)
        lead=int(mod.LEAD*SR); sym=int(sd/1000*SR)
        sig[lead:lead+sym]=0.0                          # erase the first (all-on+pilot) marker
        sf.write(wav,sig.astype(np.float32),SR)
        with contextlib.redirect_stdout(io.StringIO()):
            ok,data=mod.decode(wav,wav+".json")
        assert ok and data==MSG.encode()

if __name__=="__main__":
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    npass=nfail=nxfail=0
    for t in tests:
        is_x=getattr(t,"_xfail",False)
        try:
            t();
            if is_x: print(f"XPASS  {t.__name__} (xfail test now passes!)"); npass+=1
            else: print(f"PASS   {t.__name__}"); npass+=1
        except AssertionError as e:
            if is_x: print(f"xfail  {t.__name__} (known limitation)"); nxfail+=1
            else: print(f"FAIL   {t.__name__}: {e}"); nfail+=1
        except Exception as e:
            print(f"ERROR  {t.__name__}: {type(e).__name__}: {e}"); nfail+=1
    print(f"\n{npass} passed, {nfail} failed, {nxfail} xfail")
    raise SystemExit(1 if nfail else 0)
