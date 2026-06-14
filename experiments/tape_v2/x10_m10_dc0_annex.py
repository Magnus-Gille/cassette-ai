"""x10_m10_dc0_annex.py -- dc0 grid-widening gate CLOSURE annex (tape9, m6/m7).

The composed-regression run (x10_m10_results_composed_regression_tape9_run1)
re-validated the WIDENED late-window grid [0..80]: the truth-free decision-EVM
argmin chose the +80 edge on every base/section with EVM still falling, and on
m7 the edge improvement was 14.1% > the 10% flattening threshold -- the
pre-registered rule says "widen again and re-run".  Meanwhile the OPERATIVE
metric (cw_failed) was already FLAT AT ZERO from S32 to the S80 edge on both
bases of both sections (the rescue is exhausted; EVM keeps falling because a
later window holds a larger ISI-free energy fraction, not because decisions
keep improving).

This annex executes the widen-again step: scalar dc0-late branches at
S in {80, 88, 96, 112, 128, 160, 192} on the ema0.6 base for tape9 m6 + m7,
reporting dc0 decision-EVM AND per-branch cw_failed.  Expected (pre-stated):
cw_failed stays 0 well past 80 -- i.e. no decode improvement was left at the
edge -- and at large S the EVM statistic eventually decouples entirely from
decode correctness (approaching the one-symbol-misalignment degeneracy at
S -> N - skip).  Conclusion feeds X10_gate_report.md; the SHIPPED decoder grid
stays [0..80] with ALL scalar branches joining the strictly-additive union, so
an edge-riding argmin cannot cost a codeword by construction.

Run:  OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 x10_m10_dc0_annex.py
Out:  results/x10_m10_dc0_annex.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                               # noqa: E402
import m9_decode as m9d                                # noqa: E402
import hyp_common as hc                                # noqa: E402
from h4_dqpsk import PAD_LO_S, PAD_HI_S                # noqa: E402
from x10_b_cons_01_late_window_dc0 import (            # noqa: E402
    _shift_pass_ema, _decide_refine,
)
from m10_decode import (                               # noqa: E402
    _per_cw_decode, _rx_mat, _nominal_bits, _load_capture,
)

SR = codec.FS
ANNEX_SHIFTS = (80, 88, 96, 112, 128, 160, 192)
SECTIONS = ("m9_m6_n256_rs191", "m9_m7_n256_p11_9000")
OUT = _HERE / "results" / "x10_m10_dc0_annex.json"


def main():
    manifest = json.loads((_HERE / "master9_manifest.json").read_text())
    audio_nom, sync, _ = _load_capture(
        str(_HERE / "captures" / "tape9_run1.wav"), manifest,
        "composed_regression_tape9_run1")
    align = int(sync["align"])
    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    out = {"what": "dc0 grid widen-again annex (gate closure)",
           "capture": "captures/tape9_run1.wav", "base": "ema0.6",
           "annex_shifts": list(ANNEX_SHIFTS), "sections": {}}
    for name in SECTIONS:
        sec = secs[name]
        sch = m9d._scheme_from_entry(sec)
        meta = sec["meta"]
        crc = sec["crc32_codewords"]
        nom_bits = _nominal_bits(meta)
        pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
        flen = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
        P = len(sch.data_idx)
        t0 = time.time()
        q_by_shift = {s: [] for s in ANNEX_SHIFTS}
        evm_sum = np.zeros((P, len(ANNEX_SHIFTS)))
        evm_n = np.zeros(len(ANNEX_SHIFTS))
        for fi, st in enumerate(sec["frame_starts"]):
            nd = sch.nsym_data(nom_bits[fi])
            total = nd + 1
            st_i = int(st) + align
            w_lo = max(0, st_i - pad_lo)
            w_hi = min(len(audio_nom), st_i + flen + pad_hi)
            y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
            ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
            for si, s in enumerate(ANNEX_SHIFTS):
                c, dtau = _shift_pass_ema(sch, y, ds, total, 0.6, s)
                q, res = _decide_refine(sch, c, dtau)
                q_by_shift[s].append(q.astype(np.int8))
                evm_sum[:, si] += np.abs(res).sum(axis=0)
                evm_n[si] += res.shape[0]
        ledger = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0,
                  "crc_accepts": 0}
        rows = {}
        for si, s in enumerate(ANNEX_SHIFTS):
            rows[str(s)] = {"dc0_evm_deg": round(
                float(np.degrees(evm_sum[0, si] / max(evm_n[si], 1))), 3)}
        # stitched scalar branches need the center (shift 0) pass for carriers 1..P-1
        c0 = {}
        for fi, st in enumerate(sec["frame_starts"]):
            nd = sch.nsym_data(nom_bits[fi])
            total = nd + 1
            st_i = int(st) + align
            w_lo = max(0, st_i - pad_lo)
            w_hi = min(len(audio_nom), st_i + flen + pad_hi)
            y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
            ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
            c, dtau = _shift_pass_ema(sch, y, ds, total, 0.6, 0)
            q, _res = _decide_refine(sch, c, dtau)
            c0[fi] = q.astype(np.int8)
        for si, s in enumerate(ANNEX_SHIFTS):
            frames = []
            for fi in range(len(q_by_shift[s])):
                qs = c0[fi].copy()
                qs[:, 0] = q_by_shift[s][fi][:, 0]
                frames.append(np.asarray(sch.quadrants_to_bits(qs.astype(int)),
                                         np.uint8))
            ok, _msgs = _per_cw_decode(_rx_mat(frames, meta), meta, crc, ledger)
            rows[str(s)]["cw_failed"] = int((~ok).sum())
        out["sections"][name] = {
            "n_codewords": meta["n_codewords"], "rows": rows,
            "elapsed_s": round(time.time() - t0, 1)}
        print(f"[{name}] " + "  ".join(
            f"S{s}: evm={rows[str(s)]['dc0_evm_deg']}deg "
            f"cw={rows[str(s)]['cw_failed']}" for s in ANNEX_SHIFTS), flush=True)
    OUT.write_text(json.dumps(out, indent=2, default=float))
    print(f"[annex] wrote {OUT}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
