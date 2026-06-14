"""m10doom_decode.py -- recover playable DOOM from a captured (or clean) WAV.

The receive side of the DOOM ship tape (m10doom_master.py). Reuses the proven
master9 chain WHOLESALE via import from m9_decode:

  * global sync: chirp pair + speed scan + resample-to-nominal
    (analyze_master2.global_sync_and_resample, via m9_decode).
  * section decode: m9_decode._decode_dqpsk_section -- the COMMON master9
    receiver (x9_resampling_pll continuous-tau-hat PLL front-end + h4 pilot-EMA
    fallbacks, RS errors-only + errors-and-erasures sweep, CRC32-per-codeword
    manifest guard against miscorrection).
  * payload unpack: h9 H9PC container (lzma bridge from m10doom_master when the
    interpreter lacks _lzma).

Output: doom_ship/doom_decoded.html + results JSON; the verdict line compares
sha256 of the decoded HTML against the manifest's recorded artifact hash (and
against payloads/doom/dist/doom_cassette.html when present on disk).

Usage:
    python3 experiments/tape_v2/doom_ship/m10doom_decode.py <capture.wav>
        [--out-tag TAG]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2/doom_ship
TAPE_V2 = _HERE.parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    TAPE_V2,
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m9_decode as m9d  # noqa: E402  (the proven receiver chain)
import analyze_master2 as am2  # noqa: E402
from m10doom_master import unpack_doom, MANIFEST_PATH, WAV_PATH  # noqa: E402

SR = m9d.SR
RESULTS_DIR = _HERE / "results"
DECODED_PATH = _HERE / "doom_decoded.html"


def decode(recording_path: str, out_tag: str | None = None,
           verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    sec = manifest["ws_payloads"][0]

    audio, sr = sf.read(recording_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)

    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    except Exception as exc:
        sounder = {"error": str(exc)}

    # ---- the ONE payload section, through the proven m9 receiver sweep ----
    r, recovered_packed = m9d._decode_dqpsk_section(audio_nom, sec, align)

    # ---- unpack + integrity vs the shipped artifact ----
    pack = sec["pack"]
    unpack_ok = orig_exact = False
    recovered_orig = b""
    try:
        recovered_orig = unpack_doom(recovered_packed)
        unpack_ok = True
        sha_o = hashlib.sha256(recovered_orig).hexdigest()
        orig_exact = (sha_o == pack["sha256_orig"]
                      and len(recovered_orig) == pack["orig_len"])
    except Exception as exc:
        r["unpack_error"] = str(exc)

    DECODED_PATH.write_bytes(recovered_orig)

    # independent check against the dist artifact, when it exists on disk
    dist = pathlib.Path(manifest["html_path"])
    dist_match = None
    if dist.exists():
        dist_match = (hashlib.sha256(dist.read_bytes()).hexdigest()
                      == hashlib.sha256(recovered_orig).hexdigest())

    payload_seconds = (sec["section_end"] - sec["section_start"]) / SR
    net_bps = sec["projected_net_bps"]
    eff_bps = pack["orig_len"] * 8 / payload_seconds

    r.update({
        "unpack_ok": unpack_ok,
        "orig_byte_exact": bool(orig_exact),
        "dist_file_match": dist_match,
        "pack_algo": pack["algo"],
        "orig_len": pack["orig_len"],
        "packed_len": pack["packed_len"],
        "effective_bps": eff_bps,
    })

    verdict = "BYTE-EXACT" if orig_exact else "FAIL"
    if verbose:
        print(f"[m10doom_decode] {recording_path}")
        print(f"  recovered clock: {sync['speed']:.4f}x "
              f"(offset {sync['speed_offset'] * 100:+.2f}%), align {align:+d}")
        if isinstance(sounder, dict) and sounder.get("flutter_wrms_pct") is not None:
            print(f"  sounder: flutter {sounder['flutter_wrms_pct']:.2f}%, "
                  f"SNR med {sounder['snr_db_median']:.1f} dB")
        print(f"  section {sec['phy']} RS({sec['meta']['rs_n']},{sec['meta']['rs_k']}): "
              f"cw failed {r['rs_codewords_failed']}/{r['n_codewords']}, "
              f"front-end {r.get('front_end_used')}, "
              f"erase_frac {r.get('erase_frac_used')}")
        print(f"  packed byte-exact: {r['byte_exact']}   "
              f"unpack: {unpack_ok}   orig sha256 match: {orig_exact}"
              + (f"   dist file match: {dist_match}" if dist_match is not None else ""))
        print(f"  decoded HTML -> {DECODED_PATH} ({len(recovered_orig)} B)")
        print(f"\n  VERDICT: {verdict}   net {net_bps:.1f} bps (PHY, RS-coded)   "
              f"effective {eff_bps:.1f} bps on the HTML "
              f"({pack['orig_len']} B in {payload_seconds:.1f} s of payload audio)")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    out = {
        "recording": str(recording_path),
        "tape": "m10doom",
        "verdict": verdict,
        "net_bps": net_bps,
        "effective_bps": eff_bps,
        "payload_seconds": payload_seconds,
        "decoded_html": str(DECODED_PATH),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {
            k: v for k, v in (sounder or {}).items()
            if k not in ("H_db", "snr_db_per_tone", "sounder_freqs", "H_phase",
                         "phase_rad", "H_phase_rad")
        },
        "payload": {k: v for k, v in r.items() if k != "sweep_attempts"}
        | {"sweep_attempts": r.get("sweep_attempts")},
    }
    json_path = RESULTS_DIR / f"m10doom_results_{tag}.json"
    json_path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"[m10doom_decode] wrote {json_path}")
    return out


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?", default=str(WAV_PATH),
                    help="captured tape-playback WAV (default: the clean master)")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    res = decode(args.recording, args.out_tag)
    sys.exit(0 if res["verdict"] == "BYTE-EXACT" else 1)
