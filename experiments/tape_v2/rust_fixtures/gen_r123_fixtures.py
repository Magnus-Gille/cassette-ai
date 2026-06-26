"""Fixtures for the R1 (DQPSK), R2 (D2X mono), R3 (D2X stereo) rungs.

R1/R2 are MONO — reuse the per-channel `<chan>_nominal.wav` from gen_floor_fixtures.py.
R3 is STEREO (independent L/R payloads) — use the real wired stereo capture
`captures/fullspectrum_20260626_163324.wav`, global-sync each channel separately,
and dump L/R nominals + payloads + per-codeword CRCs.

Each fixture pins the Python target (minimal vs full-rescue) so the Rust port
knows exactly what to hit.

Run gen_floor_fixtures.py first. Then: python3 .../gen_r123_fixtures.py
"""
from __future__ import annotations
import json, pathlib, sys
import numpy as np, soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import analyze_master2 as am2          # noqa: E402
import m10_decode as m10               # noqa: E402
import fullspectrum_decode as fsd      # noqa: E402

OUT = _HERE / "fixtures"
SR = 48000
WIRED = ROOT / "experiments/tape_v2/captures/fullspectrum_20260626_163324.wav"


def _sec(man, name):
    return [s for s in man["ws_payloads"] if s["name"] == name][0]


def _sidecar(rel):
    return (ROOT / "experiments/tape_v2" / rel).read_bytes()


def _section_block(sec, use_R=False):
    dp = sec["dqpsk_params"]
    meta = sec["meta_R"] if (use_R and "meta_R" in sec) else sec["meta"]
    fs = sec.get("frame_starts_R") if use_R else sec["frame_starts"]
    fs = fs or sec["frame_starts"]
    return {
        "kind": sec["kind"], "scheme": sec["scheme"],
        "frame_starts": [int(s) for s in fs], "body_end": int(sec["body_end"]),
        "p": int(dp["P"]), "n": int(dp["N"]), "spacing": int(dp["spacing"]),
        "skip": dp.get("skip"), "pilot_hz": float(dp["pilot_hz"]),
        "drop_freqs_hz": [float(f) for f in dp.get("drop_freqs_hz", [])],
        "meta": {k: int(meta[k]) for k in ("rs_n", "rs_k", "n_codewords", "frame_bits",
                                           "n_frames", "stream_bits", "payload_len")},
    }


def _py_targets(audio_nom, sec, align):
    out = {}
    for rescue in (False, True):
        led = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
        r, _ = m10._decode_section(audio_nom, sec, align, led, rescue=rescue, verbose=False)
        out[rescue] = (r["rs_codewords_failed"], r["n_codewords"], bool(r["byte_exact"]), r.get("front_end_used"))
    return out


def mono_rung(man, name, tag):
    """R1 / R2: reuse the existing mono nominals (clean/normal/worn)."""
    sec = _sec(man, name)
    blk = _section_block(sec)
    crc = [int(c) for c in sec["crc32_codewords"]]
    payload = list(_sidecar(sec["payload_sidecar"]))
    rec = {"label": tag, "section": blk, "crc32_codewords": crc,
           "tx_chirp0": int(man["tx_chirp0"]), "tx_chirp1": int(man["tx_chirp1"]),
           "payload_len": blk["meta"]["payload_len"], "payload": payload, "channels": {}}
    for label in ("clean", "normal", "worn"):
        wf, jf = OUT / f"{label}_nominal.wav", OUT / f"{label}.json"
        if not (wf.exists() and jf.exists()):
            print(f"  [{tag}] skip {label}: {wf.name} missing"); continue
        align = int(json.loads(jf.read_text())["sync"]["align"])
        au, sr = sf.read(str(wf)); assert sr == SR
        t = _py_targets(np.asarray(au), sec, align)
        rec["channels"][label] = {"align": align}
        print(f"  [{tag}] {label:6s} align={align:+d} py_min={t[False][0]}/{t[False][1]} "
              f"py_rescue={t[True][0]}/{t[True][1]} be={t[True][2]} fe={t[True][3]}")
    (OUT / f"{tag}.json").write_text(json.dumps(rec))


def stereo_r3(man):
    """R3: independent-stereo D2X off the real wired capture; sync each channel."""
    sec = _sec(man, "fs_r3_top_d2x_p21_rs159")
    if not WIRED.exists():
        print("  [r3] skip: wired stereo capture missing"); return
    au, sr = sf.read(str(WIRED), always_2d=True); assert sr == SR
    rec = {"label": "r3_stereo", "tx_chirp0": int(man["tx_chirp0"]), "tx_chirp1": int(man["tx_chirp1"]),
           "channels": {}}
    for ci, (cname, use_R) in enumerate([("L", False), ("R", True)]):
        ch = au[:, ci].astype(np.float32)
        sync = am2.global_sync_and_resample(ch, man)
        align = int(sync["chirp0_nominal"]) - int(man["tx_chirp0"])
        nom = np.asarray(sync["audio_nominal"], dtype=np.float32)
        sf.write(str(OUT / f"r3_{cname}_nominal.wav"), nom, SR, subtype="FLOAT")
        s_ch = fsd._section_for_channel(sec, use_R)
        blk = _section_block(s_ch, use_R=use_R)
        crc = [int(c) for c in (s_ch.get("crc32_codewords") or sec["crc32_codewords"])]
        payload = list(_sidecar(s_ch["payload_sidecar"]))
        t = _py_targets(nom, s_ch, align)
        rec["channels"][cname] = {"align": align, "section": blk, "crc32_codewords": crc,
                                  "payload_len": blk["meta"]["payload_len"], "payload": payload}
        print(f"  [r3] {cname} align={align:+d} py_min={t[False][0]}/{t[False][1]} "
              f"py_rescue={t[True][0]}/{t[True][1]} be={t[True][2]} fe={t[True][3]}")
    (OUT / "r3.json").write_text(json.dumps(rec))


def main():
    man = json.loads((ROOT / "experiments/tape_v2/fullspectrum_manifest.json").read_text())
    print("[r1] DQPSK P10 RS191 (mono, reuse nominals):")
    mono_rung(man, "fs_r1_mid_dqpsk_p10_rs191", "r1")
    print("[r2] D2X P18 sp2 drop4 RS127 (mono):")
    mono_rung(man, "fs_r2_midhi_d2x_p18_rs127", "r2")
    print("[r3] D2X P21 sp2 drop1 RS159 (STEREO, wired capture):")
    stereo_r3(man)
    return 0


if __name__ == "__main__":
    sys.exit(main())
