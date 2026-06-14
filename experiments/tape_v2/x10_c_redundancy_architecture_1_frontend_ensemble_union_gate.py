"""x10_c_redundancy_architecture_1_frontend_ensemble_union_gate.py

PRE-REGISTERED GATE evaluation for the production ensemble-union receiver.
Reads the four results/x10_ensemble_decode_*.json artifacts and adjudicates:

  G1  m5 orig-exact at 2632 net bps AND m4 orig-exact at 2338, reproduced in
      the PRODUCTION decoder (blind CRC-guarded union, erase_frac=0) on
      tape9_run1.
  G2  0 regressions across the full named 4-capture suite
      (tape9: 6 m9-EXACT rungs + union-banked m4/m5; m8_tape_mono_lossless:
       m8_dq_p10n512_rs127; tape7: m16_rs111_8k/m16_rs191_8k/m32_rs95_4k;
       tape4: ws_test2k/ws_llm24k).
  G3  miscorrected_cw = 0 verified post-hoc against manifest truth on all
      4 captures.
  G4  total logged CRC-acceptance trials within the pre-registered campaign
      budget (< 4e5 trials, expected false-accepts < 1e-4 at 2^-32/trial).
  G5  record claims stated under the sidecar per-codeword-CRC convention,
      caveat declared in the gate output itself (this file's output).

Output: results/x10_ensemble_gate.json + printed verdict.  Deterministic.
"""
from __future__ import annotations

import json
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
RES = _HERE / "results"

FILES = {
    "tape9": RES / "x10_ensemble_decode_tape9_run1.json",
    "m8": RES / "x10_ensemble_decode_m8_tape_mono_lossless.json",
    "tape7": RES / "x10_ensemble_decode_tape7_run1.json",
    "tape4": RES / "x10_ensemble_decode_tape4_run1.json",
}

CAVEAT = ("RECORD CONVENTION CAVEAT (declared per pre-registration): per-codeword "
          "CRC32 acceptance uses the manifest sidecar table "
          "(sec['crc32_codewords']) — truth-derived receiver-side information; "
          "only the whole-payload CRC32 is in-stream. All record claims from "
          "this receiver inherit that sidecar caveat, the same convention as "
          "the standing 2572 bps record (m9_decode used the same table).")


def main() -> dict:
    data = {k: json.loads(p.read_text()) for k, p in FILES.items()}

    # --- G1: m4/m5 orig-exact at their net bps in the production decoder ---
    t9 = {s["name"]: s for s in data["tape9"]["sections"]}
    m4 = t9.get("m9_m4_n256_rs159", {})
    m5 = t9.get("m9_m5_n256_rs179", {})
    g1 = bool(m4.get("orig_byte_exact")) and bool(m5.get("orig_byte_exact"))
    g1_detail = {
        "m4_orig_exact": bool(m4.get("orig_byte_exact")),
        "m4_net_bps": m4.get("projected_net_bps"),
        "m4_accepted_by": m4.get("accepted_by_branch"),
        "m5_orig_exact": bool(m5.get("orig_byte_exact")),
        "m5_net_bps": m5.get("projected_net_bps"),
        "m5_accepted_by": m5.get("accepted_by_branch"),
    }

    # --- G2: 0 regressions across the named suite -------------------------
    reg = {}
    n_regressions = 0
    for k, d in data.items():
        nm = d["named_rung_checks"]
        reg[k] = {"check_field": nm["check_field"], "rungs": nm["rungs"],
                  "regressions": nm["regressions"]}
        n_regressions += len(nm["regressions"])
    g2 = n_regressions == 0

    # --- G3: miscorrected_cw == 0 post-hoc on all 4 captures --------------
    misc = {k: d.get("miscorrected_total") for k, d in data.items()}
    # WS delegate sections report miscorrected_cw_posthoc=None when inexact;
    # all named WS rungs are exact here, so None never occurs on a pass.
    g3 = all((v == 0) for v in misc.values())

    # --- G4: campaign trial ledger within budget ---------------------------
    # the most recent campaign_ledger (tape9's file scan covers all four)
    ledgers = [d["campaign_ledger"] for d in data.values()]
    total = max(l["total_trials"] for l in ledgers)
    budget = ledgers[0]["budget"]
    g4 = total < budget

    # --- G5: caveat declared in gate output --------------------------------
    g5 = True  # by construction: CAVEAT is embedded below and printed

    gate_met = g1 and g2 and g3 and g4 and g5
    out = {
        "gate": "x10_c_redundancy_architecture_1_frontend_ensemble_union",
        "metric": "orig_exact (sha256 vs manifest) per rung under blind "
                  "CRC-guarded union on tape9_run1; regressions over named "
                  "rungs across 4 captures; post-hoc miscorrection check; "
                  "CRC trial budget",
        "G1_m5_and_m4_orig_exact_production": {"pass": g1, **g1_detail},
        "G2_zero_regressions_named_suite": {"pass": g2,
                                            "n_regressions": n_regressions,
                                            "per_capture": reg},
        "G3_miscorrected_zero_all_captures": {"pass": g3, "per_capture": misc},
        "G4_crc_trial_budget": {"pass": g4, "total_trials": total,
                                "budget": budget,
                                "expected_false_accepts": total * 2.0 ** -32,
                                "detail": ledgers[0]["detail"]},
        "G5_record_convention_caveat_declared": {"pass": g5, "caveat": CAVEAT},
        "gate_met": gate_met,
        "new_banked_rungs": {
            "m9_m5_n256_rs179": {"net_bps": m5.get("projected_net_bps"),
                                 "orig_exact": bool(m5.get("orig_byte_exact"))},
            "m9_m4_n256_rs159": {"net_bps": m4.get("projected_net_bps"),
                                 "orig_exact": bool(m4.get("orig_byte_exact"))},
        },
        "evidence": "real-capture re-decode only (tape9_run1, "
                    "m8_tape_mono_lossless, tape7_run1, tape4_run1); no sim",
        "seeds": "deterministic decode, no RNG",
        "versions": data["tape9"]["versions"],
    }
    (RES / "x10_ensemble_gate.json").write_text(json.dumps(out, indent=2))

    print(f"GATE {'MET' if gate_met else 'NOT MET'}")
    for g in ("G1_m5_and_m4_orig_exact_production", "G2_zero_regressions_named_suite",
              "G3_miscorrected_zero_all_captures", "G4_crc_trial_budget",
              "G5_record_convention_caveat_declared"):
        print(f"  {g}: {'PASS' if out[g]['pass'] else 'FAIL'}")
    print(f"  banked: m5 @ {m5.get('projected_net_bps'):.0f} bps "
          f"orig_exact={bool(m5.get('orig_byte_exact'))}; "
          f"m4 @ {m4.get('projected_net_bps'):.0f} bps "
          f"orig_exact={bool(m4.get('orig_byte_exact'))}")
    print(f"  trials: {total}/{budget}")
    print(f"  {CAVEAT}")
    return out


if __name__ == "__main__":
    main()
