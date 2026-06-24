"""fullspectrum_decode.py -- ONE unified grading decoder for the full-spectrum tape.

Load a capture, run the PROVEN global chirp-pair sync ONCE
(analyze_master2.global_sync_and_resample), then for EACH ladder rung decode its
section on the relevant channel(s) via the PROVEN composed receiver
(m10_decode._decode_section) and check byte-exact against the rung's payload
sidecar. Prints a grading table and a GRADE line = the highest byte-exact rung
(per channel for the true-stereo top), and writes a results JSON to results/.

Channel handling:
  * MONO rungs (R0-R2): SAME payload on L and R. They self-test on each channel
    AND on a summed-mono (L=R)/2 mix (simulates an acoustic phone capture).
  * STEREO rung (R3): INDEPENDENT payloads on L vs R -- ch0 vs the L sidecar,
    ch1 vs the R sidecar. Both byte-exact => true 2x (~9820 bps). Summed to mono
    it is EXPECTED to fail (the channels add incoherently) -- reported honestly.

--channel:
    0 / 1  : decode that channel only (the L or R of a true-stereo capture).
    mono   : downmix (mean of channels) -- simulates an acoustic summed capture.
    auto   : (default) for a stereo file, decode BOTH channels independently and
             grade per channel; for a mono file, decode the single channel.

Usage:
    python3 fullspectrum_decode.py <capture.wav> [--channel auto|0|1|mono]
        [--manifest fullspectrum_manifest.json] [--out-tag TAG] [--no-rescue]

Exits 0 iff at least one rung was recovered byte-exact on the analyzed channel(s).
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
import warnings
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
DOOM_SHIP = _HERE / "doom_ship"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE, DOOM_SHIP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                              # noqa: E402
import m10_decode as m10                                   # noqa: E402
import m3_codec as codec                                   # noqa: E402 (floor RS/interleave framing)
from d3d4_combo_tracked import make_tracked_combo          # noqa: E402 (floor PHY)

SR = 48_000
DEFAULT_MANIFEST = _HERE / "fullspectrum_manifest.json"
RESULTS_DIR = _HERE / "results"


# ===========================================================================
def _load_channel(recording_path: str, channel) -> np.ndarray:
    """Load a capture and return one float64-ready mono signal at 48 kHz.

    channel: 0 / 1 -> that channel; "mono" -> mean of all channels (acoustic-sum
    simulation); a mono file is returned as-is (with a note if channel != 0)."""
    audio, sr = sf.read(str(recording_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        n_ch = audio.shape[1]
        if channel == "mono":
            audio = audio.mean(axis=1)
            print(f"[fullspectrum_decode] stereo -> summed mono (mean of {n_ch} ch)")
        else:
            ch = int(channel)
            if ch >= n_ch:
                raise ValueError(f"--channel {ch} but file has only {n_ch} channel(s)")
            audio = audio[:, ch]
            print(f"[fullspectrum_decode] stereo -> channel {ch}")
    else:
        if channel not in (0, "mono"):
            print(f"[fullspectrum_decode] WARN: mono file but --channel {channel}; "
                  f"using the single channel")

    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64),
                              frac.numerator, frac.denominator).astype(np.float32)
        print(f"[fullspectrum_decode] resampled {sr}->{SR} Hz "
              f"({frac.numerator}/{frac.denominator})")
    return np.asarray(audio, dtype=np.float32)


def _section_for_channel(sec: dict, use_R: bool) -> dict:
    """Return a copy of the manifest section whose payload_sidecar / crc /
    frame_starts / meta point at the channel being decoded. For the R channel of
    an INDEPENDENT-stereo rung this swaps in the *_R variants so _decode_section
    compares against the right per-channel payload."""
    s = copy.deepcopy(sec)
    if use_R:
        s["payload_sidecar"] = sec.get("payload_sidecar_R", sec["payload_sidecar"])
        s["crc32_codewords"] = sec.get("crc32_codewords_R", sec["crc32_codewords"])
        s["frame_starts"] = sec.get("frame_starts_R", sec["frame_starts"])
        s["meta"] = sec.get("meta_R", sec["meta"])
    return s


def _decode_combo_section(audio_nom: np.ndarray, sec: dict, align: int) -> dict:
    """Decode the R-1 FLOOR rung (non-coherent combinatorial-MFSK).

    The combo PHY is NOT decoded through m10._decode_section (that is the OFDM
    receiver). Instead each frame is sliced out of the globally-synced/resampled
    audio by its `frame_starts` (+ the global `align`) and handed to the combo
    demod, which SELF-SYNCS on its own per-frame chirp preamble (so a small align
    error is forgiven -- we start the slice a touch early for margin). The
    recovered per-frame bits go back through the SAME m3_codec RS(255,k) +
    global-interleave decode and are checked byte-exact against the sidecar.

    The floor rung is MONO (identical payload on L/R), so it is compared against
    the single sidecar regardless of which channel is being graded."""
    meta = sec["meta"]
    sch = make_tracked_combo(int(meta["M"]), int(meta["K"]))
    starts = [int(s) for s in sec["frame_starts"]]
    body_end = int(sec["body_end"])
    sidecar = (_HERE / sec["payload_sidecar"]).read_bytes()
    guard = int(0.05 * SR)            # start each slice ~50 ms early (preamble margin)
    n = len(audio_nom)

    frames_bits = []
    for i, st in enumerate(starts):
        a = max(0, align + st - guard)
        nxt = starts[i + 1] if i + 1 < len(starts) else body_end
        b = min(n, max(a + 1, align + int(nxt)))
        seg = np.asarray(audio_nom[a:b], dtype=np.float32)
        try:
            rb = np.asarray(sch.demodulate(seg, SR), dtype=np.uint8)
        except Exception:             # noqa: BLE001 - a dead frame -> RS interleave rescues
            rb = np.zeros(0, dtype=np.uint8)
        frames_bits.append(rb)

    recovered = codec.decode_payload(frames_bits, meta)
    n_fail = int(getattr(codec.decode_payload, "last_codewords_failed", 0))
    byte_exact = bool(recovered == sidecar)
    byte_errors = (sum(1 for x, y in zip(recovered, sidecar) if x != y)
                   + abs(len(recovered) - len(sidecar)))
    return {
        "name": sec["name"],
        "channel_mode": sec["channel_mode"],
        "phy": sec["phy"],
        "net_bps": sec["projected_net_bps"],
        "byte_exact": byte_exact,
        "rs_codewords_failed": n_fail,
        "n_codewords": int(meta["n_codewords"]),
        "byte_errors": int(byte_errors),
        "front_end_used": "combo_mfsk_tracked",
    }


def _decode_one_channel(audio_ch: np.ndarray, manifest: dict, channel_label: str,
                        use_R: bool, rescue: bool, verbose: bool) -> dict:
    """Sync ONCE, then decode every rung's section on this channel."""
    sync = am2.global_sync_and_resample(audio_ch, manifest)
    audio_nom = sync["audio_nominal"]
    align = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])
    if verbose:
        print(f"  [{channel_label}] sync: speed={sync['speed']:.5f}x align={align:+d} "
              f"resampled {sync['resample_num']}/{sync['resample_den']}")

    # sounder characterization (informational; the full report-card is deferred v2)
    sounder = None
    try:
        s = am2.analyze_sounder(audio_nom, manifest, sync)
        sounder = {k: s.get(k) for k in
                   ("snr_db_median", "snr_db_p10", "flutter_wrms_pct",
                    "noise_floor_dbfs")}
    except Exception as exc:  # noqa: BLE001 - informational only
        sounder = {"error": str(exc)}

    ledger = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
    rungs = []
    for sec in manifest["ws_payloads"]:
        if sec.get("kind") == "combo_mfsk":
            # R-1 floor: own decode path (self-syncing combo demod), not the OFDM
            # receiver. Mono rung -> same on both channels.
            rinfo = _decode_combo_section(audio_nom, sec, align)
            rungs.append(rinfo)
            if verbose:
                print(f"    [{channel_label}] {sec['name']:34s} "
                      f"net {sec['projected_net_bps']:7.0f}  "
                      f"cw {rinfo['rs_codewords_failed']}/{rinfo['n_codewords']}  "
                      f"byte_exact={rinfo['byte_exact']}")
            continue
        s = _section_for_channel(sec, use_R)
        r, _assembled = m10._decode_section(audio_nom, s, align, ledger,
                                            rescue=rescue, verbose=False)
        rungs.append({
            "name": sec["name"],
            "channel_mode": sec["channel_mode"],
            "phy": sec["phy"],
            "net_bps": sec["projected_net_bps"],
            "byte_exact": bool(r["byte_exact"]),
            "rs_codewords_failed": r["rs_codewords_failed"],
            "n_codewords": r["n_codewords"],
            "byte_errors": r["byte_errors"],
            "front_end_used": r.get("front_end_used"),
        })
        if verbose:
            print(f"    [{channel_label}] {sec['name']:34s} "
                  f"net {sec['projected_net_bps']:7.0f}  "
                  f"cw {r['rs_codewords_failed']}/{r['n_codewords']}  "
                  f"byte_exact={r['byte_exact']}")

    exact = [x for x in rungs if x["byte_exact"]]
    grade = max(exact, key=lambda x: x["net_bps"]) if exact else None
    return {
        "channel": channel_label,
        "sync": {k: (float(v) if isinstance(v, (np.floating, float))
                     else int(v) if isinstance(v, (np.integer, int)) else v)
                 for k, v in sync.items() if k != "audio_nominal"},
        "align": align,
        "sounder": sounder,
        "rungs": rungs,
        "grade_rung": grade["name"] if grade else None,
        "grade_net_bps": grade["net_bps"] if grade else 0.0,
        "ledger": ledger,
    }


def _print_channel_table(res: dict) -> None:
    print(f"\n  === channel {res['channel']} ===")
    snd = res.get("sounder") or {}
    if snd.get("snr_db_median") is not None:
        print(f"  sounder: SNR med {snd['snr_db_median']:.1f} dB, "
              f"flutter {snd.get('flutter_wrms_pct', float('nan')):.2f}%, "
              f"nf {snd.get('noise_floor_dbfs', float('nan')):.1f} dBFS")
    print(f"  {'rung':<34} {'net bps':>8} {'mode':>7} {'cwFail':>8} "
          f"{'byte-exact':>11}")
    for x in res["rungs"]:
        cw = f"{x['rs_codewords_failed']}/{x['n_codewords']}"
        be = "YES" if x["byte_exact"] else "no"
        print(f"  {x['name']:<34} {x['net_bps']:>8.0f} {x['channel_mode']:>7} "
              f"{cw:>8} {be:>11}")
    if res["grade_rung"]:
        print(f"  GRADE [{res['channel']}]: highest byte-exact rung = "
              f"{res['grade_rung']} @ {res['grade_net_bps']:.0f} net bps")
    else:
        print(f"  GRADE [{res['channel']}]: NONE byte-exact")


# ===========================================================================
def decode(recording_path: str, channel="auto", manifest_path=None,
           out_tag=None, rescue=True, verbose=True) -> dict:
    mpath = pathlib.Path(manifest_path) if manifest_path else DEFAULT_MANIFEST
    if not mpath.is_absolute():
        mpath = _HERE / mpath
    manifest = json.loads(mpath.read_text())

    # Decide which channels to analyze.
    raw, _sr = sf.read(str(recording_path), dtype="float32", always_2d=False)
    n_ch = raw.shape[1] if raw.ndim > 1 else 1
    del raw

    plan: list[tuple[str, object, bool]] = []   # (label, channel-arg, use_R)
    if channel == "auto":
        if n_ch > 1:
            plan = [("L (ch0)", 0, False), ("R (ch1)", 1, True)]
        else:
            plan = [("mono", 0, False)]
    elif channel == "mono":
        plan = [("mono", "mono", False)]
    else:
        ch = int(channel)
        plan = [(f"ch{ch}", ch, ch == 1)]

    if verbose:
        print(f"[fullspectrum_decode] {recording_path}  "
              f"(manifest={mpath.name}, {n_ch}-ch, plan={[p[0] for p in plan]})")

    channel_results = []
    for label, ch_arg, use_R in plan:
        audio_ch = _load_channel(recording_path, ch_arg)
        channel_results.append(
            _decode_one_channel(audio_ch, manifest, label, use_R, rescue, verbose))

    if verbose:
        for res in channel_results:
            _print_channel_table(res)

    # ---- overall grade -------------------------------------------------------
    # stereo bps = sum of per-channel grade rates when independent channels are
    # both graded (auto on a stereo file decodes both); otherwise the single grade.
    any_exact = any(r["grade_rung"] for r in channel_results)
    if len(channel_results) == 2:
        stereo_net = sum(r["grade_net_bps"] for r in channel_results)
    else:
        stereo_net = channel_results[0]["grade_net_bps"]

    result = {
        "recording": str(recording_path),
        "manifest": mpath.name,
        "channel_arg": str(channel),
        "decoder": "fullspectrum_decode (global sync once + m10 _decode_section per rung)",
        "channels": channel_results,
        "aggregate_net_bps": stereo_net,
        "any_byte_exact": bool(any_exact),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    json_path = RESULTS_DIR / f"fullspectrum_results_{tag}.json"
    json_path.write_text(json.dumps(result, indent=2, default=float))
    if verbose:
        if len(channel_results) == 2:
            print(f"\n[fullspectrum_decode] AGGREGATE (L+R) = "
                  f"{stereo_net:.0f} net bps")
        print(f"[fullspectrum_decode] wrote {json_path.name}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Grade a full-spectrum tape capture across the rung ladder.")
    ap.add_argument("capture_wav")
    ap.add_argument("--channel", default="auto",
                    help="auto (default) | 0 | 1 | mono (downmix = acoustic sim)")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--out-tag", default=None)
    ap.add_argument("--no-rescue", action="store_true",
                    help="pass-1 ensemble union only (faster; skips late-window/ladder)")
    args = ap.parse_args()

    ch = args.channel
    if ch not in ("auto", "mono"):
        ch = int(ch)
    res = decode(args.capture_wav, channel=ch, manifest_path=args.manifest,
                 out_tag=args.out_tag, rescue=not args.no_rescue)
    sys.exit(0 if res["any_byte_exact"] else 1)
