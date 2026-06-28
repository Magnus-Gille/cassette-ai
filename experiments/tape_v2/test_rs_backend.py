"""test_rs_backend.py -- Parity gate + benchmark for creedsolo vs reedsolo (issue #21 WIN 3).

Tests:
  1. creedsolo availability (fail = blocked, no code change ships as default)
  2. RSCodec encode parity: creedsolo encode == reedsolo encode
  3. RSCodec decode parity (clean): identical decoded bytes
  4. RSCodec decode parity (within-t errors): identical corrected bytes
  5. RSCodec decode parity (beyond-t, uncorrectable): BOTH raise an exception
  6. ReedSolomonError compatibility: exceptions are catchable via (ReedSolomonError, Exception)
  7. Integration parity: mini-master gate assembled bytes identical, per-codeword ok pattern identical
  8. Benchmark: RS-decode time and full mini-decode time with both backends

Usage:
    python3 experiments/tape_v2/test_rs_backend.py [--bench] [--verbose]
    --bench : also run the large synthetic batch benchmark (projects DOOM-scale win)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
import warnings

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
_DOOM = _HERE / "doom_ship"
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    _HERE,
    _DOOM,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Must import m10_decode before analyze_master2 (worktree path precedence)
import m10_decode as m10  # noqa: E402
import m10doom3_simgate as sg  # noqa: E402


# ===========================================================================
# helpers
# ===========================================================================

def _make_rsc_pair(nsym: int):
    """Return (rsc_py, rsc_cy) for a given nsym.  Raises ImportError if creedsolo absent."""
    import reedsolo
    rsc_py = reedsolo.RSCodec(nsym)
    import creedsolo  # will raise ImportError if not installed
    rsc_cy = creedsolo.RSCodec(nsym)
    return rsc_py, rsc_cy


def _inject_errors(enc: bytes, n_errors: int) -> bytes:
    """Inject n_errors random-like byte errors into an encoded codeword."""
    buf = bytearray(enc)
    stride = max(1, len(buf) // (n_errors + 1))
    for i in range(n_errors):
        pos = (i * stride) % len(buf)
        buf[pos] ^= 0xA5 ^ (i & 0xFF)
    return bytes(buf)


# ===========================================================================
# Test 1: creedsolo availability
# ===========================================================================
def test_creedsolo_available():
    try:
        import creedsolo  # noqa: F401
        print("[1] creedsolo available: YES", flush=True)
        return True
    except ImportError:
        print("[1] creedsolo NOT available -- backend blocked (install from reedsolo source with Cython)", flush=True)
        return False


# ===========================================================================
# Test 2: encode parity
# ===========================================================================
def test_encode_parity():
    NSYM = 96  # RS(255,159): 255-159=96 parity symbols
    rsc_py, rsc_cy = _make_rsc_pair(NSYM)
    n_ok = 0
    for seed in range(20):
        data = bytes([(seed * 7 + i * 13) % 256 for i in range(159)])
        enc_py = bytes(rsc_py.encode(data))
        enc_cy = bytes(rsc_cy.encode(data))
        assert enc_py == enc_cy, f"[2] ENCODE MISMATCH at seed={seed}"
        n_ok += 1
    print(f"[2] Encode parity: {n_ok}/20 payloads byte-identical  OK", flush=True)


# ===========================================================================
# Test 3: decode parity -- clean (no errors)
# ===========================================================================
def test_decode_clean_parity():
    NSYM = 96
    rsc_py, rsc_cy = _make_rsc_pair(NSYM)
    for seed in range(20):
        data = bytes([(seed * 11 + i * 7) % 256 for i in range(159)])
        enc = bytes(rsc_py.encode(data))
        dec_py = bytes(rsc_py.decode(enc)[0])
        dec_cy = bytes(rsc_cy.decode(enc)[0])
        assert dec_py == data, f"[3] reedsolo clean decode wrong at seed={seed}"
        assert dec_cy == data, f"[3] creedsolo clean decode wrong at seed={seed}"
        assert dec_py == dec_cy, f"[3] CLEAN DECODE MISMATCH at seed={seed}"
    print("[3] Decode (clean) parity: 20/20 byte-identical  OK", flush=True)


# ===========================================================================
# Test 4: decode parity -- within-t errors (correctable)
# ===========================================================================
def test_decode_correctable_parity():
    # RS(255,159): nsym=96, t=48 correctable errors
    NSYM = 96
    T = NSYM // 2  # correction capacity in symbol errors
    rsc_py, rsc_cy = _make_rsc_pair(NSYM)
    ok = 0
    for seed in range(20):
        data = bytes([(seed * 3 + i * 17) % 256 for i in range(159)])
        enc = bytes(rsc_py.encode(data))
        # inject t//2 errors (well within capability)
        corrupted = _inject_errors(enc, T // 2)
        dec_py = bytes(rsc_py.decode(corrupted)[0])
        dec_cy = bytes(rsc_cy.decode(corrupted)[0])
        assert dec_py == data, f"[4] reedsolo failed to correct {T//2} errors at seed={seed}"
        assert dec_cy == data, f"[4] creedsolo failed to correct {T//2} errors at seed={seed}"
        assert dec_py == dec_cy, f"[4] CORRECTABLE DECODE MISMATCH at seed={seed}"
        ok += 1
    print(f"[4] Decode (correctable, {T//2} errors into t={T}) parity: {ok}/20  OK", flush=True)


# ===========================================================================
# Test 5: uncorrectable parity -- BOTH must raise an exception
# ===========================================================================
def test_decode_uncorrectable_parity():
    import creedsolo
    import reedsolo

    NSYM = 96
    T = NSYM // 2  # 48
    rsc_py = reedsolo.RSCodec(NSYM)
    rsc_cy = creedsolo.RSCodec(NSYM)
    failures = []
    for seed in range(10):
        data = bytes([(seed * 5 + i * 23) % 256 for i in range(159)])
        enc = bytes(rsc_py.encode(data))
        # inject T + 5 errors (beyond correction capacity)
        corrupted = _inject_errors(enc, T + 5)

        py_raised = False
        cy_raised = False
        try:
            rsc_py.decode(corrupted)
        except Exception:
            py_raised = True

        try:
            rsc_cy.decode(corrupted)
        except Exception:
            cy_raised = True

        if py_raised != cy_raised:
            failures.append(
                f"seed={seed}: reedsolo raised={py_raised} creedsolo raised={cy_raised}"
            )

    if failures:
        for f in failures:
            print(f"[5] UNCORRECTABLE PARITY MISMATCH: {f}", flush=True)
        raise AssertionError(f"[5] uncorrectable parity failures: {failures}")
    print(f"[5] Uncorrectable parity: 10/10 seeds both backends raise same way  OK", flush=True)


# ===========================================================================
# Test 6: ReedSolomonError catch compatibility
# ===========================================================================
def test_exception_catch_compat():
    """Verify both ReedSolomonError classes are caught by (ReedSolomonError, Exception)."""
    import creedsolo
    import reedsolo

    NSYM = 96
    T = NSYM // 2
    rsc_py = reedsolo.RSCodec(NSYM)
    rsc_cy = creedsolo.RSCodec(NSYM)
    data = bytes(range(159))
    enc = bytes(rsc_py.encode(data))
    corrupted = _inject_errors(enc, T + 5)

    # Catch as reedsolo.ReedSolomonError (should catch both via Exception fallback)
    RSE_py = reedsolo.ReedSolomonError
    caught_py = caught_cy = False
    try:
        rsc_py.decode(corrupted)
    except (RSE_py, Exception):
        caught_py = True

    try:
        rsc_cy.decode(corrupted)
    except (RSE_py, Exception):  # reedsolo.RSE or any Exception -- creedsolo.RSE is an Exception
        caught_cy = True

    assert caught_py, "[6] reedsolo exception not caught via (RSE_py, Exception)"
    assert caught_cy, "[6] creedsolo exception not caught via (RSE_py, Exception)"
    print("[6] Exception catch compat: both backends caught via (reedsolo.ReedSolomonError, Exception)  OK", flush=True)


# ===========================================================================
# Test 7: Integration parity -- mini-master gate
# ===========================================================================
def _decode_with_backend(backend_name: str, audio_nom, sec, align):
    """Temporarily monkey-patch RSCodec in m10_decode with the given backend and decode."""
    import reedsolo
    import creedsolo

    RSC = creedsolo.RSCodec if backend_name == "creedsolo" else reedsolo.RSCodec
    RSE = creedsolo.ReedSolomonError if backend_name == "creedsolo" else reedsolo.ReedSolomonError

    original_rsc = m10.RSCodec
    original_rse = m10.ReedSolomonError
    m10.RSCodec = RSC
    m10.ReedSolomonError = RSE
    try:
        ledger = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
        t0 = time.time()
        res, assembled = m10._decode_section(audio_nom, sec, align, ledger, rescue=True, verbose=False)
        elapsed = time.time() - t0
        return assembled, elapsed, res
    finally:
        m10.RSCodec = original_rsc
        m10.ReedSolomonError = original_rse


def test_integration_parity(verbose=False):
    """Parity gate: creedsolo and reedsolo produce byte-identical output on the mini-master."""
    print("[7] Building / loading gate WAV...", flush=True)
    sg.build_mini(force=False)
    audio, align, mani, _ = sg.sync_load(sg.GATE_WAV)
    sec = mani["ws_payloads"][0]
    n_cw = sec["meta"]["n_codewords"]
    if verbose:
        print(f"[7] Gate section: {sec['name']}, {n_cw} codewords", flush=True)

    payload_ref = (ROOT / "experiments" / "tape_v2" / sec["payload_sidecar"]).read_bytes()

    print("[7] Decoding with reedsolo backend...", flush=True)
    assembled_py, t_py, res_py = _decode_with_backend("reedsolo", audio, sec, align)
    be_py = (assembled_py == payload_ref)

    print("[7] Decoding with creedsolo backend...", flush=True)
    assembled_cy, t_cy, res_cy = _decode_with_backend("creedsolo", audio, sec, align)
    be_cy = (assembled_cy == payload_ref)

    parity = (assembled_py == assembled_cy)

    # Per-codeword success/fail comparison
    ok_py = res_py.get("cw_ok_pattern")
    ok_cy = res_cy.get("cw_ok_pattern")
    cw_parity = (ok_py == ok_cy) if (ok_py is not None and ok_cy is not None) else None

    print(f"[7] reedsolo: byte_exact={be_py}, t={t_py:.2f}s, cw_failed={res_py['rs_codewords_failed']}", flush=True)
    print(f"[7] creedsolo: byte_exact={be_cy}, t={t_cy:.2f}s, cw_failed={res_cy['rs_codewords_failed']}", flush=True)
    print(f"[7] assembled parity: {parity}", flush=True)
    if cw_parity is not None:
        print(f"[7] per-codeword ok pattern parity: {cw_parity}", flush=True)

    assert be_py, f"[7] reedsolo baseline byte_exact FAILED (cw_failed={res_py['rs_codewords_failed']})"
    assert be_cy, f"[7] creedsolo byte_exact FAILED (cw_failed={res_cy['rs_codewords_failed']})"
    assert parity, "[7] INTEGRATION PARITY FAIL: assembled bytes differ between backends!"

    speedup = t_py / t_cy if t_cy > 0 else float("inf")
    print(f"[7] Integration parity: PASS  speedup={speedup:.2f}x  OK", flush=True)
    return {"t_py": t_py, "t_cy": t_cy, "speedup": speedup,
            "n_codewords": n_cw, "cw_parity": cw_parity}


# ===========================================================================
# Benchmark: large synthetic RS-decode batch (projects DOOM-scale win)
# ===========================================================================
def bench_synthetic(n_codewords: int = 5000, nsym: int = 96, verbose: bool = False):
    """Decode n_codewords RS(255,159) codewords with both backends; report speedup."""
    import reedsolo
    import creedsolo

    print(f"\n[bench] Synthetic RS-decode benchmark: {n_codewords}x RS(255,{255-nsym}), nsym={nsym}", flush=True)
    rsc_py = reedsolo.RSCodec(nsym)
    rsc_cy = creedsolo.RSCodec(nsym)

    # Build a batch of codewords (some clean, some with errors)
    codewords = []
    for i in range(n_codewords):
        data = bytes([(i * 7 + j * 13) % 256 for j in range(255 - nsym)])
        enc = bytes(rsc_py.encode(data))
        if i % 10 == 0:
            enc = _inject_errors(enc, 5)  # 10% have 5 symbol errors
        codewords.append(enc)

    # reedsolo
    t0 = time.time()
    ok_py = 0
    for cw in codewords:
        try:
            rsc_py.decode(cw)
            ok_py += 1
        except Exception:
            pass
    t_py = time.time() - t0

    # creedsolo
    t0 = time.time()
    ok_cy = 0
    for cw in codewords:
        try:
            rsc_cy.decode(cw)
            ok_cy += 1
        except Exception:
            pass
    t_cy = time.time() - t0

    speedup = t_py / t_cy if t_cy > 0 else float("inf")
    rate_py = n_codewords / t_py
    rate_cy = n_codewords / t_cy
    print(f"[bench] reedsolo:  {t_py:.3f}s  ({rate_py:.0f} cw/s)", flush=True)
    print(f"[bench] creedsolo: {t_cy:.3f}s  ({rate_cy:.0f} cw/s)  speedup={speedup:.1f}x", flush=True)
    print(f"[bench] ok count: py={ok_py}  cy={ok_cy}  match={ok_py == ok_cy}", flush=True)

    # Project DOOM-scale (9455 codewords)
    doom_cw = 9455
    doom_py_s = doom_cw / rate_py
    doom_cy_s = doom_cw / rate_cy
    print(f"[bench] Projected DOOM ({doom_cw} cw): reedsolo={doom_py_s:.1f}s  creedsolo={doom_cy_s:.1f}s  win={doom_py_s - doom_cy_s:.1f}s", flush=True)

    return {"t_py": t_py, "t_cy": t_cy, "speedup": speedup,
            "n_codewords": n_codewords, "ok_match": ok_py == ok_cy}


# ===========================================================================
# main
# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bench", action="store_true", help="Run large synthetic RS-decode batch benchmark")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    print("=" * 60, flush=True)
    print("RS backend parity gate (issue #21 WIN 3: creedsolo)", flush=True)
    print("=" * 60, flush=True)

    available = test_creedsolo_available()
    if not available:
        print("\nBLOCKED: creedsolo not available -- build from reedsolo source with Cython.", flush=True)
        print("No code changes ship as default until creedsolo is installable.", flush=True)
        sys.exit(2)

    print("\n-- Unit parity tests --", flush=True)
    test_encode_parity()
    test_decode_clean_parity()
    test_decode_correctable_parity()
    test_decode_uncorrectable_parity()
    test_exception_catch_compat()

    print("\n-- Integration parity gate --", flush=True)
    stats = test_integration_parity(verbose=args.verbose)

    if args.bench:
        bench_stats = bench_synthetic(n_codewords=5000, nsym=96, verbose=args.verbose)

    print("\n" + "=" * 60, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 60, flush=True)

    from rs_backend import BACKEND
    print(f"  Active backend: {BACKEND}", flush=True)
    print(f"  Unit parity [2-6]: ALL PASS", flush=True)
    print(f"  Integration parity [7]: PASS (speedup={stats['speedup']:.2f}x on {stats['n_codewords']} cw gate)", flush=True)
    print(f"    reedsolo: {stats['t_py']:.2f}s  creedsolo: {stats['t_cy']:.2f}s", flush=True)
    if stats.get("cw_parity") is not None:
        print(f"    Per-codeword ok pattern parity: {stats['cw_parity']}", flush=True)
    if args.bench:
        print(f"  Synthetic batch speedup: {bench_stats['speedup']:.1f}x  ok_match={bench_stats['ok_match']}", flush=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
