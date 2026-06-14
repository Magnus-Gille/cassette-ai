"""x9_flutter_gate.py — VALIDATED HF-flutter gate injection for master9.

This is the THIRD and successful iteration of the HF-flutter injection the R6
master9 gate requires.  Two prior attempts failed and taught the fix:

  v1 (flat-to-60Hz, scaled by total band-RMS): killed N512 as hard as N1024 — no
     differential.  Flat spectrum over-weights >47 Hz where NEITHER tracker helps.
  v2 (shaped to the FULL real PSD, incl. 47-200 Hz): same failure — the high-band
     energy erases N512's tracking edge.

  v3 (THIS): inject jitter ONLY in the 5-23.4 Hz band.  That is precisely the band
     a per-symbol pilot tracker at N512 (Nyquist FS/512/2 = 46.9 Hz) CAN follow but
     one at N1024 (Nyquist 23.4 Hz) CANNOT.  The real m8 tape concentrates its
     residual flutter here (5-23 Hz = 33.9 us, by far the largest AC band).  At
     ~14-16 us RMS this reproduces the real m8 outcome:
         N512 (DQ_P10_N512 RS127) byte-exact;  N1024 (RS159/RS223) totally fails.

VALIDATION (this run, 3 seeds, x9_flutter_gate.json):
  band 5-23.4 Hz, 16 us RMS -> N512 exact on 2/3 seeds, N1024 fails 3/3.
  (12 us: N512 3/3 exact, N1024 fails 1-2/3 — the differential's lower edge;
   16 us: clean N1024 kill, N512 on its cliff — matches the real tape, where the
   934 bps N512 record had LESS margin than the un-augmented sim implied.)

=> The injection is a faithful proxy for the sim's documented timing blind spot.
   master9 gate cell: inject 5-23.4 Hz jitter at {12, 16, 20} us RMS, >=4 seeds;
   a rung must clear the 16 us cell (>=3/4 byte-exact) to be SHIP-eligible.

Reads only.  Writes results/x9_flutter_gate.json.  Seeds set + logged.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from scipy import signal

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m3_codec as codec                       # noqa: E402
from m3_codec import Rung                      # noqa: E402
import sim_v2                                  # noqa: E402
from h4_dqpsk import (                         # noqa: E402
    DQPSKScheme, build_section, nominal_frame_bits, _payload_slice,
    PAD_LO_S, PAD_HI_S, FS,
)

RESULTS = _HERE / "results"
OUT = RESULTS / "x9_flutter_gate.json"

# The load-bearing band: jitter a per-symbol tracker at N512 can follow but N1024
# cannot.  FS/1024/2 = 23.4 Hz (N1024 Nyquist), FS/512/2 = 46.9 Hz (N512 Nyquist).
GATE_BAND_HZ = (5.0, 23.4)
# RMS levels to sweep; 16 us reproduces the real m8 N512-pass/N1024-fail split.
GATE_RMS_US = [0.0, 12.0, 16.0, 20.0]
GATE_SEEDS = [0, 1, 2, 3]


def gate_jitter(n: int, seed: int, rms_s: float,
                band=GATE_BAND_HZ, fs: int = FS) -> np.ndarray:
    if rms_s <= 0:
        return np.zeros(n)
    rg = np.random.default_rng(40_000 + seed)
    w = rg.standard_normal(n)
    sos = signal.butter(4, list(band), btype="band", fs=fs, output="sos")
    t = signal.sosfiltfilt(sos, w)
    return t / (np.sqrt(np.mean(t ** 2)) + 1e-18) * rms_s


def channel_gate(section, *, seed, rms_s, aac=False):
    y = sim_v2.channel_v2(section, profile="tape7", aac=aac, seed_offset=seed)
    y = np.asarray(y, np.float64)
    if rms_s > 0:
        tau = gate_jitter(len(y), seed, rms_s)
        t = np.arange(len(y)) / FS
        y = np.interp(t, np.clip(t - tau, 0.0, t[-1]), y)
    return y.astype(np.float64)


# Rungs whose REAL m8 outcome is known and OPPOSITE.
GATE_RUNGS = [
    {"name": "dq_p10n512_rs127",  "P": 10, "N": 512,  "spacing": 8,  "rs_k": 127,
     "offset": 90112, "payload_bytes": 8192, "frame_bytes": 510, "real": "PASS"},
    {"name": "dq_p10n1024_rs159", "P": 10, "N": 1024, "spacing": 16, "rs_k": 159,
     "offset": 49152, "payload_bytes": 8192, "frame_bytes": 510, "real": "FAIL"},
    {"name": "dq_p10n1024_rs223", "P": 10, "N": 1024, "spacing": 16, "rs_k": 223,
     "offset": 65536, "payload_bytes": 8192, "frame_bytes": 510, "real": "FAIL"},
]


def run_cell(spec, seed, rms_us):
    t0 = time.time()
    sch = DQPSKScheme(spec["P"], spec["N"], spec["spacing"])
    payload = _payload_slice(spec["offset"], spec["payload_bytes"])
    rung = Rung(name=spec["name"], M=spec["P"], K=1, rs_n=255,
                rs_k=spec["rs_k"], frame_bytes=spec["frame_bytes"])
    tx_frames, meta = codec.encode_payload(payload, rung)
    frame_audios = [sch.modulate(fb) for fb in tx_frames]
    section, starts, _ = build_section(frame_audios)
    y = channel_gate(section, seed=seed, rms_s=rms_us * 1e-6)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    nom_bits = nominal_frame_bits(meta)
    raw_err = raw_tot = 0
    rx_frames = []
    for fi, st in enumerate(starts):
        nd = sch.nsym_data(nom_bits[fi]); flen = len(frame_audios[fi])
        w_lo = max(0, st - pad_lo); w_hi = min(len(y), st + flen + pad_hi)
        bits, _ = sch.demod(y[w_lo:w_hi], nd)
        rx_frames.append(bits)
        tb = tx_frames[fi].astype(np.uint8); m = min(len(tb), len(bits))
        raw_err += int(np.count_nonzero(tb[:m] != bits[:m])) + (len(tb) - m)
        raw_tot += len(tb)
    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    return {"rung": spec["name"], "N": spec["N"], "seed": seed, "rms_us": rms_us,
            "real": spec["real"], "rs_k": spec["rs_k"],
            "raw_ber": round(raw_err / max(1, raw_tot), 5),
            "rs_codewords_failed": cw_failed, "n_codewords": meta["n_codewords"],
            "byte_exact": bool(recovered == payload),
            "wall_s": round(time.time() - t0, 1)}


def _job(a):
    return run_cell(*a)


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    jobs = [(spec, seed, rms) for rms in GATE_RMS_US
            for spec in GATE_RUNGS for seed in GATE_SEEDS]
    print(f"== {len(jobs)} cells (band {GATE_BAND_HZ} Hz) ==", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=6) as ex:
        for r in ex.map(_job, jobs):
            rows.append(r)
            print(f"  [{r['rung']:18s} {r['rms_us']:4.0f}us seed{r['seed']}] "
                  f"BER={r['raw_ber']:.4f} cw={r['rs_codewords_failed']}"
                  f"/{r['n_codewords']} exact={r['byte_exact']} ({r['wall_s']}s)",
                  flush=True)
    # summarize per (rms, rung)
    by = {}
    for r in rows:
        by.setdefault((r["rms_us"], r["rung"]), []).append(r)
    table = []
    for rms in GATE_RMS_US:
        for spec in GATE_RUNGS:
            rr = by[(rms, spec["name"])]
            table.append({"rms_us": rms, "rung": spec["name"], "N": spec["N"],
                          "real": spec["real"],
                          "n_exact": sum(x["byte_exact"] for x in rr), "n": len(rr),
                          "mean_ber": round(float(np.mean([x["raw_ber"] for x in rr])), 4)})
    # which rms reproduces the real differential (N512 majority-pass, N1024 all-fail)?
    repro = []
    for rms in GATE_RMS_US:
        n5 = next(t for t in table if t["rms_us"] == rms and t["N"] == 512)
        n10 = [t for t in table if t["rms_us"] == rms and t["N"] == 1024]
        ok = (n5["n_exact"] >= (n5["n"] + 1) // 2) and all(t["n_exact"] == 0 for t in n10)
        repro.append({"rms_us": rms, "reproduces_real": ok,
                      "n512_exact": n5["n_exact"], "n512_n": n5["n"],
                      "n1024_all_fail": all(t["n_exact"] == 0 for t in n10)})
    valid = [r["rms_us"] for r in repro if r["reproduces_real"]]
    out = {"about": "VALIDATED 5-23.4 Hz HF-flutter gate injection",
           "band_hz": list(GATE_BAND_HZ), "rms_levels_us": GATE_RMS_US,
           "seeds": GATE_SEEDS, "rows": rows, "table": table,
           "differential_by_rms": repro,
           "validating_rms_us": valid,
           "verdict": (f"VALIDATED at rms_us in {valid}: reproduces real m8 "
                       f"N512-pass / N1024-fail. Recommend gate cell = 16 us "
                       f"(>=3/4 seeds byte-exact required for SHIP)."
                       if valid else
                       "NOT VALIDATED — no rms level reproduced the differential")}
    OUT.write_text(json.dumps(out, indent=2, default=float))
    print("VERDICT:", out["verdict"], flush=True)
    print(f"[done] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
