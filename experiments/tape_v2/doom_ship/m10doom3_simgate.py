"""m10doom3_simgate.py -- BLOCKING sim gate for the v3 FRAME_BYTES re-freeze.

WHAT IS GATED: the v3 ship tape moves the r6 d2x rung from frame_bytes=510
(0.78 s frames, the geometry proven 0/72 twice on the real tape10) to
frame_bytes=10200 (10.7 s frames) to amortize the fixed per-frame overhead
(12000-sample preamble + 5760-sample gap + 1 ref symbol) over a 1.5 MB
payload. The carrier grid, symbol rate, RS code, interleave, CRC discipline
and receiver are ALL unchanged -- the ONLY new physics is the timing
front-end (EMA / resampling-PLL) holding lock over 10.7 s between per-frame
preamble re-syncs. That is exactly what this gate exercises, BEFORE printing.

GATE DESIGN (the x11_d2x_erasure pattern, reused wholesale):
  * mini-master built by the SAME m10doom3_master.build_tape transmit path
    (r6 scheme asserts included) at FB=10200, carrying an h9-packed slice of
    the v3 HTML (~8 frames, ~300 codewords -- enough interleave depth that
    the global column-major interleave behaves as on the ship tape).
  * cells: clean (no channel) + dg* x aac {off,on} x clk {0,+0.10,+0.17,
    +0.25}% x seed 0, where dg* = 0.35 is the x11 screen's frozen marginal
    diffuse-gain pick (results/x11_d2x_screen.json) and the channel is
    sim_v2.channel_v2(profile='tape7') after a polyphase constant-clock
    resample -- the xd.gen_capture/_apply_clock pattern verbatim.
  * decode: the v3 receiver path (m10doom3_decode.decode_section_bytes =
    frozen m10 stage A + the bytes-returning x11 rescue, armed).
  * PASS (every cell, including the marginal ones): 0 failed codewords AND
    packed byte-exact AND 0 miscorrections AND campaign false-accept bound
    < 1e-4.  The x11 gate (gate_met=true, 23/23 marginal d2x sections
    rescued, results/x11_d2x_gate_report.json) established this bar at
    FB=510; v3 must reproduce it at FB=10200 or the tape is NOT printed.

Usage (checkpointed; rerun resumes; --force-cells regenerates captures):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
        python3 experiments/tape_v2/doom_ship/m10doom3_simgate.py [--cell ID]

Output: doom_ship/results/m10doom3_simgate.json  (gate_pass: true/false)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
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

import analyze_master2 as am2  # noqa: E402
import m3_codec as codec  # noqa: E402
import sim_v2  # noqa: E402  (read-only)
import x11_d2x_erasure as xd  # noqa: E402  (read-only: _apply_clock pattern)
import m10doom3_master as v3m  # noqa: E402
import m10doom3_decode as v3d  # noqa: E402

SR = codec.FS
GATE_DIR = _HERE / "m10doom3_gate"
CAP_DIR = TAPE_V2 / "captures"            # gitignored
RESULTS_DIR = _HERE / "results"
RESULT_PATH = RESULTS_DIR / "m10doom3_simgate.json"

GATE_WAV = GATE_DIR / "m10doom3_gate_master.wav"
GATE_MANIFEST = GATE_DIR / "m10doom3_gate_manifest.json"
GATE_SIDECAR = GATE_DIR / "m10doom3_gate.bin"
GATE_SECTION = "m10doom3_gate_fb10200"

# h9-packed slice of the real v3 HTML; sized for ~8 FB=10200 frames
GATE_RAW_BYTES = 160_000
DG_STAR = 0.35                       # the x11 screen's frozen marginal pick
GATE_AACS = (False, True)
GATE_CLKS = (0.0, 0.10, 0.17, 0.25)
GATE_SEED = 0
FA_BUDGET = 1e-4


def cell_id(aac, clk):
    return f"dg{DG_STAR:.2f}_aac{int(bool(aac))}_clk{clk:+.2f}_s{GATE_SEED}"


def gate_cells():
    return ["clean"] + [cell_id(aac, clk) for aac in GATE_AACS
                        for clk in GATE_CLKS]


# ===========================================================================
def build_mini(force=False) -> dict:
    """Mini-master through the IDENTICAL v3 transmit path at FB=10200."""
    if GATE_WAV.exists() and GATE_MANIFEST.exists() and not force:
        man = json.loads(GATE_MANIFEST.read_text())
        return {"reused": True, "wav_seconds": man.get("wav_seconds")}
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    raw = v3m.HTML_PATH.read_bytes()[:GATE_RAW_BYTES]
    packed, pmeta = v3m.pack_doom(raw)
    assert v3m.unpack_doom(packed) == raw, "gate H9 roundtrip failed"
    res = v3m.build_tape(
        packed,
        out_wav=GATE_WAV,
        manifest_path=GATE_MANIFEST,
        sidecar_path=GATE_SIDECAR,
        payload_sidecar_rel=str(GATE_SIDECAR.relative_to(TAPE_V2)),
        section_name=GATE_SECTION,
        frame_bytes=v3m.FRAME_BYTES,
        tape_id="m10doom3_gate",
        role="FB=10200 long-frame physics gate (mini-master)",
        manifest_extra={"gate": "m10doom3_simgate",
                        "gate_raw_bytes": GATE_RAW_BYTES},
        entry_extra={
            "pack": {
                "algo": pmeta["algo"],
                "orig_len": pmeta["orig_len"],
                "packed_len": pmeta["packed_len"],
                "reduction_pct": pmeta["reduction_pct"],
                "sha256_orig": hashlib.sha256(raw).hexdigest(),
                "sha256_packed": hashlib.sha256(packed).hexdigest(),
            },
        },
    )
    res["reused"] = False
    return {k: res[k] for k in ("reused", "wav_seconds", "n_frames",
                                "n_codewords")}


# ===========================================================================
def gen_capture(aac, clk, force=False) -> pathlib.Path:
    """xd.gen_capture pattern verbatim: constant-clock polyphase resample of
    the WHOLE mini tape, then sim_v2.channel_v2(tape7, aac, diffuse_gain)."""
    cid = cell_id(aac, clk)
    cap = CAP_DIR / f"m10doom3_gate_{cid}.wav"
    if cap.exists() and not force:
        return cap
    x, sr = sf.read(str(GATE_WAV), dtype="float64", always_2d=False)
    assert sr == SR
    y, ratio = xd._apply_clock(x, clk)
    y = sim_v2.channel_v2(y, profile="tape7", aac=bool(aac),
                          seed_offset=int(GATE_SEED),
                          sim_overrides={"diffuse_gain": float(DG_STAR)})
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(str(cap), y.astype(np.float32), SR, subtype="FLOAT")
    print(f"[gate gen] {cap.name} ({len(y) / SR:.1f}s, ratio={ratio:.6f})",
          flush=True)
    return cap


def sync_load(cap: pathlib.Path):
    audio, sr = sf.read(str(cap), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)
    mani = json.loads(GATE_MANIFEST.read_text())
    sync = am2.global_sync_and_resample(audio, mani)
    align = int(sync["chirp0_nominal"]) - int(mani["tx_chirp0"])
    return sync["audio_nominal"], align, mani, {
        k: (float(v) if np.isscalar(v) else None)
        for k, v in sync.items() if k != "audio_nominal" and np.isscalar(v)}


# ===========================================================================
def run_cell(cid: str, ledger: dict, verbose=True) -> dict:
    t0 = time.time()
    if cid == "clean":
        cap = GATE_WAV
    else:
        parts = cid.split("_")
        aac = bool(int(parts[1][3:]))
        clk = float(parts[2][3:])
        cap = gen_capture(aac, clk)
    audio_nom, align, mani, sync = sync_load(cap)
    sec = mani["ws_payloads"][0]
    expected_packed = (TAPE_V2 / sec["payload_sidecar"]).read_bytes()
    r, assembled = v3d.decode_section_bytes(audio_nom, sec, align, ledger,
                                            rescue=True, x11_rescue=True,
                                            verbose=verbose)
    row = {
        "cell": cid,
        "capture": cap.name,
        "sync_speed": sync.get("speed"),
        "align": align,
        "n_codewords": r["n_codewords"],
        "n_frames": r["n_frames"],
        "cw_failed": int(r["rs_codewords_failed"]),
        "byte_exact": bool(assembled == expected_packed),
        "miscorrected": int(r["miscorrected_cw"]),
        "decoder_stage": r["decoder_stage"],
        "x11_rescue_fired": r.get("x11_rescue") is not None,
        "front_end_used": r.get("front_end_used"),
        "best_single_branch": r.get("best_single_branch"),
        "elapsed_s": round(time.time() - t0, 1),
    }
    row["pass"] = bool(row["cw_failed"] == 0 and row["byte_exact"]
                       and row["miscorrected"] == 0)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", action="append", default=[],
                    help="run only these cell ids (default: all + rollup)")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    out = (json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists()
           else {"experiment": "m10doom3 FB=10200 long-frame physics gate",
                 "preregistration": __doc__.split("Usage")[0],
                 "frame_bytes": v3m.FRAME_BYTES,
                 "dg_star": DG_STAR,
                 "cells_planned": gate_cells(),
                 "ledger": {"rs_attempts": 0, "crc_checks": 0,
                            "crc_rejects": 0, "crc_accepts": 0},
                 "rows": {}})
    ledger = out["ledger"]

    bres = build_mini(force=args.rebuild)
    out["mini_master"] = bres
    print(f"[gate] mini-master: {bres}", flush=True)

    todo = args.cell or gate_cells()
    for cid in todo:
        if cid in out["rows"] and not args.rebuild:
            print(f"[gate] {cid} already done "
                  f"(pass={out['rows'][cid]['pass']}), skip", flush=True)
            continue
        print(f"[gate] === cell {cid} ===", flush=True)
        row = run_cell(cid, ledger)
        out["rows"][cid] = row
        out["false_accept_bound"] = ledger["crc_checks"] * 2.0 ** -32
        out["fa_within_budget"] = bool(out["false_accept_bound"] < FA_BUDGET)
        RESULT_PATH.write_text(json.dumps(out, indent=2, default=v3d._jsafe))
        print(f"[gate] {cid}: cw_failed={row['cw_failed']}/"
              f"{row['n_codewords']} byte_exact={row['byte_exact']} "
              f"misc={row['miscorrected']} stage={row['decoder_stage']} "
              f"PASS={row['pass']} ({row['elapsed_s']}s) -> checkpointed",
              flush=True)

    done = [out["rows"].get(c) for c in gate_cells()]
    complete = all(r is not None for r in done)
    out["complete"] = complete
    out["gate_pass"] = bool(complete and all(r["pass"] for r in done)
                            and out.get("fa_within_budget", True))
    RESULT_PATH.write_text(json.dumps(out, indent=2, default=v3d._jsafe))
    print(f"\n[gate] complete={complete} "
          f"fa_bound={out.get('false_accept_bound', 0):.2e} "
          f"GATE_PASS={out['gate_pass']}")
    sys.exit(0 if out["gate_pass"] else 1)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
