"""sim_v2_validate.py — validate channel_v2 (real AAC round-trip) against the
REAL master7 tape decode (results/m7_results_tape7_run1.json).

Pushes the EXISTING master7.wav through channel_v2(profile='tape7', aac=True)
for seeds {0,1}, decodes with the m7_decode machinery (same pattern as
m7_sim_validate.py), and compares per-rung byte-exact outcomes to the real tape.

MATCH RULE per rung: sim matches real if byte_exact agrees on >=1 of 2 seeds
for the MARGINAL rungs (m16_rs159_8k, m32_rs95_4k — within ~2 codewords of
flipping on the real tape) and on BOTH seeds for the other 7.

ACCEPTANCE GATE: >=7/9 rungs match, AND m16_rs191_8k = PASS in sim (both
seeds), AND m32_rs111_4k = FAIL in sim (both seeds).

If the gate fails: tune ONE knob at a time, max 4 calibration iterations, in
order (1) diffuse_gain, (2) snr_delta_db +-1.5, (3) flutter_residual_frac.
Every iteration's matrix is logged to results/sim_v2_validation.json
(calibration_history). If still unreachable -> stop and report honestly.

Also runs an AAC-MECHANISM CHECK: rung m32_rs111_4k with aac=True vs aac=False
(1 seed, final calibration) — theory says aac=True should be clearly worse
(masking-skirt quantization noise adjacent to tonal peaks).

Usage:
    python3 experiments/tape_v2/sim_v2_validate.py            # full calibration run
    python3 experiments/tape_v2/sim_v2_validate.py --max-iters 0   # baseline only
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import time

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sim_v2      # noqa: E402
import m7_decode   # noqa: E402

SR = 48_000
RESULTS = _HERE / "results"
REAL_JSON = RESULTS / "m7_results_tape7_run1.json"
OUT_JSON = RESULTS / "sim_v2_validation.json"
MARGINAL = {"m16_rs159_8k", "m32_rs95_4k"}
GATE_PASS_RUNG = "m16_rs191_8k"   # proven 562 bps winner -> must PASS in sim
GATE_FAIL_RUNG = "m32_rs111_4k"   # proven AAC-killed turbo rung -> must FAIL in sim


def load_real() -> dict:
    d = json.loads(REAL_JSON.read_text())
    return {r["name"]: r for r in d["payloads"]}


def sim_pass(audio: np.ndarray, seed: int, tag: str, *, aac: bool = True,
             overrides: dict | None = None) -> list[dict]:
    """One full-master sim+decode pass. Returns m7_decode payload rows."""
    t0 = time.time()
    y = sim_v2.channel_v2(audio, profile="tape7", aac=aac,
                          seed_offset=int(seed), sim_overrides=overrides)
    pk = float(np.max(np.abs(y))) + 1e-12
    y = (y / pk * 0.95).astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp = tf.name
    sf.write(tmp, y, SR, subtype="FLOAT")
    out = m7_decode.decode(tmp, out_tag=tag, verbose=False)
    pathlib.Path(tmp).unlink(missing_ok=True)
    rows = out["payloads"]
    for r in rows:
        ok = "YES" if r["byte_exact"] else "no "
        print(f"    [{tag}] {r['name']:<14} {ok} raw{r['raw_ber']:.4f} "
              f"cw{r['rs_codewords_failed']}/{r['n_codewords']}", flush=True)
    print(f"    [{tag}] pass done in {time.time() - t0:.0f}s", flush=True)
    return rows


def build_matrix(real: dict, rows_by_seed: dict[int, list[dict]]) -> tuple[list[dict], int, bool]:
    seeds = sorted(rows_by_seed)
    names = [r["name"] for r in rows_by_seed[seeds[0]]]
    rungs, n_match = [], 0
    for nm in names:
        rp = bool(real[nm]["byte_exact"])
        per_seed = {}
        for s in seeds:
            r = next(x for x in rows_by_seed[s] if x["name"] == nm)
            per_seed[s] = {"byte_exact": bool(r["byte_exact"]),
                           "raw_ber": float(r["raw_ber"]),
                           "cw_failed": int(r["rs_codewords_failed"]),
                           "n_codewords": int(r["n_codewords"])}
        agree = [per_seed[s]["byte_exact"] == rp for s in seeds]
        match = any(agree) if nm in MARGINAL else all(agree)
        n_match += match
        rungs.append({
            "name": nm,
            "marginal": nm in MARGINAL,
            "real_byte_exact": rp,
            "real_raw_ber": float(real[nm]["raw_ber"]),
            "real_cw_failed": int(real[nm]["rs_codewords_failed"]),
            "sim_byte_exact_per_seed": {str(s): per_seed[s]["byte_exact"] for s in seeds},
            "sim_raw_ber": {str(s): per_seed[s]["raw_ber"] for s in seeds},
            "sim_cw_failed": {str(s): per_seed[s]["cw_failed"] for s in seeds},
            "match": bool(match),
        })
    by = {r["name"]: r for r in rungs}
    gate = (
        n_match >= 7
        and all(by[GATE_PASS_RUNG]["sim_byte_exact_per_seed"].values())
        and not any(by[GATE_FAIL_RUNG]["sim_byte_exact_per_seed"].values())
    )
    return rungs, n_match, gate


def harshness(rungs: list[dict]) -> int:
    """+1 per seed where sim FAILS a rung the real tape PASSED (sim too harsh),
    -1 per seed where sim PASSES a rung the real tape FAILED (sim too lenient)."""
    h = 0
    for r in rungs:
        for ok in r["sim_byte_exact_per_seed"].values():
            if r["real_byte_exact"] and not ok:
                h += 1
            elif not r["real_byte_exact"] and ok:
                h -= 1
    return h


def fmt_matrix(rungs: list[dict]) -> str:
    seeds = sorted(rungs[0]["sim_byte_exact_per_seed"].keys(), key=int) if rungs else []
    hdr = "  " + f"{'rung':<14} {'real':<5} " + " ".join(f"{'sim s'+s:<18}" for s in seeds) + " match"
    lines = [hdr]
    for r in rungs:
        cells = []
        for s in seeds:
            be = r["sim_byte_exact_per_seed"].get(s)
            cells.append(f"{'PASS' if be else 'FAIL'}(raw{r['sim_raw_ber'][s]:.3f},"
                         f"cw{r['sim_cw_failed'][s]})")
        marg = "*" if r["marginal"] else " "
        lines.append(f"  {r['name']:<14} {'PASS' if r['real_byte_exact'] else 'FAIL':<5} "
                     + " ".join(f"{c:<18}" for c in cells)
                     + f" {'OK' if r['match'] else 'X'}{marg}")
    return "\n".join(lines)


def gate_score(rungs: list[dict], seeds_available: list[int]) -> tuple:
    """Rank a probe by how close it is to the acceptance gate, using whatever
    seeds were run (1-seed probes allowed). Higher tuple sorts better.

    Priority (lexicographic):
      1. both gate constraints satisfied on the seeds run
         (m16_rs191 PASS, m32_rs111 FAIL)
      2. number of matched rungs
      3. -harshness magnitude (closer to balanced)
    """
    by = {r["name"]: r for r in rungs}
    seeds = [str(s) for s in seeds_available]
    pass_ok = all(by[GATE_PASS_RUNG]["sim_byte_exact_per_seed"].get(s, False)
                  for s in seeds)
    fail_ok = not any(by[GATE_FAIL_RUNG]["sim_byte_exact_per_seed"].get(s, True)
                      for s in seeds)
    n_match = sum(r["match"] for r in rungs)
    h = harshness(rungs)
    return (int(pass_ok) + int(fail_ok), n_match, -abs(h))


def run_cfg(audio, real, cfg, seeds, tag):
    """Run cfg over the given seeds; return (rungs, n_match, gate, entry)."""
    rows_by_seed = {}
    for s in seeds:
        rows_by_seed[s] = sim_pass(audio, s, f"{tag}_seed{s}", overrides=cfg)
    rungs, n_match, gate = build_matrix(real, rows_by_seed)
    print(fmt_matrix(rungs), flush=True)
    print(f"  -> cfg={cfg} matches {n_match}/{len(rungs)}, "
          f"harshness {harshness(rungs):+d}, "
          f"gate {'PASSED' if gate else 'failed'} (seeds {seeds})", flush=True)
    entry = {"config": dict(cfg), "seeds": list(seeds), "n_match": n_match,
             "gate": gate, "harshness": harshness(rungs), "rungs": rungs}
    return rungs, n_match, gate, entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1])
    ap.add_argument("--master", default=str(_HERE / "master7.wav"))
    ap.add_argument("--max-passes", type=int, default=14)
    args = ap.parse_args()

    print(f"[sim_v2_validate] AAC self-test: {sim_v2.test_aac_alignment()}", flush=True)
    real = load_real()
    audio, sr = sf.read(args.master, dtype="float32", always_2d=False)
    assert sr == SR, sr
    audio = audio.astype(np.float64)

    history = []
    passes_used = [0]  # mutable counter (1 pass == 1 seed full-master decode)
    seed0, seed1 = args.seeds[0], args.seeds[1]

    def record(entry):
        history.append(entry)

    # ---- Phase 1: search diffuse_gain at seed0 only (1 pass each) ----
    # Baseline 0.5 = all-PASS (too lenient). dg=0.7 (smoke) = M16 too harsh
    # (m16_rs191 raw .038 vs real .022 -> FAILs the gate-PASS rung) while M32
    # is about right. Sweet spot is between -> search 0.55..0.65.
    probe_gains = [0.55, 0.6, 0.65]
    probe_entries = []
    for g in probe_gains:
        if passes_used[0] >= args.max_passes:
            break
        cfg = {"diffuse_gain": g}
        print(f"\n=== PROBE diffuse_gain={g} (seed {seed0}) ===", flush=True)
        _, _, _, e = run_cfg(audio, real, cfg, [seed0], f"probe_dg{g}")
        passes_used[0] += 1
        e["phase"] = "diffuse_probe"
        record(e)
        probe_entries.append(e)

    # pick the probe whose seed0 outcome is closest to the gate
    probe_entries.sort(key=lambda e: gate_score(e["rungs"], e["seeds"]),
                       reverse=True)
    best_probe = probe_entries[0]
    best_score = gate_score(best_probe["rungs"], best_probe["seeds"])
    print(f"\n[search] best diffuse probe seed0: cfg={best_probe['config']} "
          f"score={best_score}", flush=True)

    # gate-constraint satisfied on seed0 means score[0]==2
    candidate_cfg = dict(best_probe["config"])

    # ---- Phase 2: if diffuse alone can't satisfy gate on seed0, add knob 2 ----
    # Spec: M16 too clean while M32 matches -> raise flutter_residual_frac
    # (timing jitter hurts long-N M16 margins). Otherwise nudge snr_db -1.5.
    if best_score[0] < 2 and passes_used[0] < args.max_passes:
        by = {r["name"]: r for r in best_probe["rungs"]}
        m16_too_clean = by[GATE_PASS_RUNG]["sim_byte_exact_per_seed"][str(seed0)] \
            and not by[GATE_FAIL_RUNG]["sim_byte_exact_per_seed"][str(seed0)]
        # If m16_rs191 still FAILS-as-PASS issue OR m32_rs111 still PASSES, try
        # flutter first (helps M16 margins), then snr.
        for second in ("flutter", "snr"):
            if passes_used[0] >= args.max_passes:
                break
            if second == "flutter":
                for fr in (0.25, 0.35):
                    if passes_used[0] >= args.max_passes:
                        break
                    cfg = dict(candidate_cfg)
                    cfg["flutter_residual_frac"] = fr
                    print(f"\n=== PROBE +flutter_residual_frac={fr} "
                          f"(seed {seed0}) ===", flush=True)
                    _, _, _, e = run_cfg(audio, real, cfg, [seed0],
                                         f"probe_fr{fr}")
                    passes_used[0] += 1
                    e["phase"] = "flutter_probe"
                    record(e)
                    sc = gate_score(e["rungs"], e["seeds"])
                    if sc > best_score:
                        best_score, best_probe, candidate_cfg = sc, e, dict(cfg)
            else:  # snr -1.5
                cfg = dict(candidate_cfg)
                cfg["snr_delta_db"] = -1.5
                print(f"\n=== PROBE +snr_delta_db=-1.5 (seed {seed0}) ===",
                      flush=True)
                _, _, _, e = run_cfg(audio, real, cfg, [seed0], "probe_snr")
                passes_used[0] += 1
                e["phase"] = "snr_probe"
                record(e)
                sc = gate_score(e["rungs"], e["seeds"])
                if sc > best_score:
                    best_score, best_probe, candidate_cfg = sc, e, dict(cfg)
            if best_score[0] >= 2:
                break

    print(f"\n[search] chosen candidate: cfg={candidate_cfg} "
          f"seed0_score={best_score}", flush=True)

    # ---- Phase 3: confirm chosen cfg on seed1 (full 2-seed rule) ----
    print(f"\n=== CONFIRM cfg={candidate_cfg} on both seeds ===", flush=True)
    rungs2, n_match2, gate2, conf_entry = run_cfg(
        audio, real, candidate_cfg, list(args.seeds), "confirm")
    passes_used[0] += len(args.seeds)
    conf_entry["phase"] = "confirm_2seed"
    record(conf_entry)

    final = conf_entry
    # --- AAC mechanism check: m32_rs111_4k, aac on vs off, 1 seed, final cfg ---
    fcfg = final["config"]
    seed0 = args.seeds[0]
    ber_on = final["rungs"][[r["name"] for r in final["rungs"]].index(GATE_FAIL_RUNG)][
        "sim_raw_ber"][str(seed0)]  # reuse the final-calibration aac=True pass
    print(f"\n=== AAC mechanism check ({GATE_FAIL_RUNG}, seed {seed0}, cfg={fcfg}) ===",
          flush=True)
    rows_noaac = sim_pass(audio, seed0, "simv2_mechcheck_noaac",
                          aac=False, overrides=fcfg)
    passes_used[0] += 1
    ber_off = next(r for r in rows_noaac if r["name"] == GATE_FAIL_RUNG)["raw_ber"]
    mech = {
        "rung": GATE_FAIL_RUNG, "seed": seed0, "config": fcfg,
        "raw_ber_aac_true": float(ber_on), "raw_ber_aac_false": float(ber_off),
        "aac_clearly_worse": bool(ber_on > 1.5 * ber_off),
    }
    print(f"  aac=True raw BER {ber_on:.4f}  vs  aac=False raw BER {ber_off:.4f} "
          f"-> AAC {'IS' if mech['aac_clearly_worse'] else 'is NOT clearly'} the adversary",
          flush=True)

    out = {
        "real_source": str(REAL_JSON),
        "profile": "tape7",
        "seeds": args.seeds,
        "aac_alignment": sim_v2.test_aac_alignment(),
        "match_rule": "marginal rungs (m16_rs159_8k, m32_rs95_4k): >=1/2 seeds; others: both seeds",
        "gate": f">=7/9 matches AND {GATE_PASS_RUNG} PASS (both seeds) AND {GATE_FAIL_RUNG} FAIL (both seeds)",
        "final_calibration": final["config"],
        "n_match": final["n_match"],
        "gate_passed": final["gate"],
        "rungs": final["rungs"],
        "calibration_history": history,
        "aac_mechanism_check": mech,
        "n_passes_used": passes_used[0],
    }
    RESULTS.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[sim_v2_validate] wrote {OUT_JSON}")
    print(f"FINAL: {final['n_match']}/9 matched, gate "
          f"{'PASSED' if final['gate'] else 'FAILED'}, cfg={final['config']}")


if __name__ == "__main__":
    main()
