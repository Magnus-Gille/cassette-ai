"""x12_master11_master.py -- assemble MASTER11 (the x12 burn tape).

master11 IS the print-authorized x12-regate ladder promoted to the official
master11 artifact name.  The builder REUSES the frozen x12_regate_master
build machinery VERBATIM (imported, never edited; only the output paths and
the master_id are repointed), so the audio is asserted BYTE-IDENTICAL to the
already gated + print-authorized x12_master_regate.wav when that artifact is
present on disk.

Ladder (ONE global sync, robust-early -> stretch-late, 3 sections, ~106 s):

  c0  x12_c0_anchor_2572    DQPSK DQ_P22_N512_sp4 msp375, RS(255,159),
                            49 cw / 25 frames -- BYTE-IDENTICAL m10_r0 canary
                            (2572.1 net bps; MANDATORY: no canary, no pass)
  c1  x12_c1_d2x_4910       dense2x D2X_P21_N256_sp2 drop{750}, RS(255,159),
                            72 cw / 36 frames -- BYTE-IDENTICAL m10_r6 d2x
                            banker (4910.3 net bps; MANDATORY canary #2)
  c3  x12_c3_dbpsk_p12_ext  DBPSK_P12_N256_sp2_ext, 90-deg boundary, 8 rule-
                            picked mid carriers + 4 ext bins (9375/9750/
                            10125/10500 Hz), pilot 4875, RS(255,191),
                            10 cw / 5 frames -- the only x12 GO (1685.3 net
                            bps probe; banks the >9 kHz DBPSK SER map)

All three rungs ship v1 framing (the x12 bulk-framing gate FAILED, G2/G3
K_s=1 -- results/x12_framing_report.json gate_met=false -- so NO bulk-framed
rung is allowed on tape; the framing-canary-pair rule is therefore moot).

print_authorized starts FALSE.  `--authorize` flips it ONLY after the
BLOCKING no-channel self-check of THIS tape's manifest
(results/x12_m11_results_selfcheck_nochan.json: 3/3 orig-exact, 0
miscorrections, canaries reproved) and it carries the x12-regate campaign
gate evidence (results/x12_frontier_regate.json final.print_authorized=true).

Run:
    python3 x12_master11_master.py               # build master11.wav (+manifest+sidecars)
    python3 x12_master11_master.py --authorize   # after the blocking self-check
Deterministic (LADDER_SEED inherited from the frozen builder, =20260612).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import x12_regate_master as xrm  # noqa: E402  (FROZEN -- imported, never edited)

WAV_PATH = _HERE / "master11.wav"
MANIFEST_PATH = _HERE / "master11_manifest.json"
SIDECAR_DIR = _HERE / "sidecars_x12_m11"
REGATE_WAV = _HERE / "x12_master_regate.wav"
REGATE_MANIFEST = _HERE / "x12_master_regate_manifest.json"
REGATE_JSON = _HERE / "results" / "x12_frontier_regate.json"
SELFCHECK_JSON = _HERE / "results" / "x12_m11_results_selfcheck_nochan.json"

MASTER_ID = "master11"


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _audio_sha(p: pathlib.Path) -> str:
    """sha256 over the float32 SAMPLE DATA (the WAV container's PEAK chunk
    embeds a write timestamp, so whole-file hashes never reproduce)."""
    import soundfile as sf
    x, sr = sf.read(str(p), dtype="float32", always_2d=False)
    return hashlib.sha256(x.tobytes()).hexdigest()


def build() -> str:
    # Repoint ONLY the frozen builder's output identity; every byte of build
    # logic (ladder derivation, canary byte-identity asserts vs master10,
    # CRC32 tables, normalization) runs verbatim from x12_regate_master.
    xrm.MASTER_ID = MASTER_ID
    xrm.MANIFEST_PATH = MANIFEST_PATH
    xrm.SIDECAR_DIR = SIDECAR_DIR

    # gzip-mtime trap (m10 ship report sec.5): a fresh pack_payload blob is
    # NOT byte-stable across builds.  Adopt the GATED c3 packed blob from
    # sidecars_x12_regate/ (the bytes the 8-seed blocking screen and the
    # print authorization actually adjudicated), exactly as the frozen
    # builder adopts the c0/c1 canaries from sidecars_m10/.  The frozen
    # build() asserts unpack(ref)==orig and len(ref)==packed_len.
    _orig_ladder = xrm._ladder
    _regate_c3 = _HERE / "sidecars_x12_regate" / "x12_c3_dbpsk_p12_ext.bin"

    def _ladder_m11():
        rungs = _orig_ladder()
        if _regate_c3.exists():
            for r in rungs:
                if r["name"] == "x12_c3_dbpsk_p12_ext":
                    r["reuse_sidecar"] = ("../sidecars_x12_regate/"
                                          "x12_c3_dbpsk_p12_ext")
        return rungs

    xrm._ladder = _ladder_m11
    try:
        msg = xrm.build(out_wav=WAV_PATH)
    finally:
        xrm._ladder = _orig_ladder

    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["master_id"] == MASTER_ID
    manifest["print_authorized"] = False
    manifest["print_block_reason"] = (
        "pending: BLOCKING no-channel self-check "
        "(python3 x12_master11_decode.py master11.wav --out-tag "
        "selfcheck_nochan) then x12_master11_master.py --authorize")
    manifest["audio_data_sha256"] = _audio_sha(WAV_PATH)
    manifest["framing"] = {
        "version": "v1 (per-frame preamble) on ALL rungs",
        "reason": "x12 bulk-framing gate FAILED (G2 real-tape ablation K_s=1,"
                  " results/x12_framing_report.json gate_met=false); rule: "
                  "bulk framing only on rungs where its gate passed -> none"}

    prov = {"promoted_from": "x12_master_regate.wav (the gated x12 artifact)",
            "regate_campaign": "results/x12_frontier_regate.json",
            "audio_byte_identical_to_regate": None}
    if REGATE_WAV.exists():
        same = _audio_sha(REGATE_WAV) == manifest["audio_data_sha256"]
        prov["audio_byte_identical_to_regate"] = bool(same)
        prov["regate_audio_data_sha256"] = _audio_sha(REGATE_WAV)
        assert same, ("master11.wav sample data is NOT byte-identical to the "
                      "gated x12_master_regate.wav -- determinism broken, "
                      "refusing")
    if REGATE_MANIFEST.exists():
        rm = json.loads(REGATE_MANIFEST.read_text())
        prov["regate_print_authorized"] = rm.get("print_authorized")
        # section-level identity: same payload shas + CRC tables, same offsets
        a = {s["name"]: (s["pack"]["sha256_packed"], tuple(s["crc32_codewords"]),
                         tuple(s["frame_starts"])) for s in manifest["ws_payloads"]}
        b = {s["name"]: (s["pack"]["sha256_packed"], tuple(s["crc32_codewords"]),
                         tuple(s["frame_starts"])) for s in rm["ws_payloads"]}
        assert a == b, "section tables diverge from the gated regate manifest"
        prov["section_tables_identical_to_regate"] = True
    manifest["provenance"] = prov
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))
    print(f"[m11] manifest -> {MANIFEST_PATH.name} (master_id={MASTER_ID}, "
          f"print_authorized=False pending self-check)")
    print(f"[m11] audio byte-identical to gated regate wav: "
          f"{prov['audio_byte_identical_to_regate']}")
    return msg


def authorize() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["master_id"] == MASTER_ID
    sc = json.loads(SELFCHECK_JSON.read_text())
    assert pathlib.Path(sc["recording"]).name == WAV_PATH.name, sc["recording"]
    assert sc["n_payloads"] == 3 and sc["n_orig_exact"] == 3, (
        f"self-check NOT clean: {sc['n_orig_exact']}/{sc['n_payloads']}")
    assert sc["miscorrected_total"] == 0, "miscorrections in self-check"
    assert sc["tape_pass_valid"], "canary pair did not reprove in self-check"
    regate = json.loads(REGATE_JSON.read_text())
    final = regate["stages"]["final"]
    assert final.get("print_authorized") is True, (
        "regate campaign final did not authorize printing")
    manifest["print_authorized"] = True
    manifest["print_block_reason"] = None
    manifest["authorization"] = {
        "selfcheck": str(SELFCHECK_JSON.relative_to(_HERE)),
        "selfcheck_orig_exact": f"{sc['n_orig_exact']}/{sc['n_payloads']}",
        "selfcheck_fa_bound": sc["crc_trial_ledger"]["false_accept_bound"]
        if "crc_trial_ledger" in sc else sc.get("false_accept_bound"),
        "campaign_gate": "results/x12_frontier_regate.json "
                         "final.print_authorized=true (selfcheck_clean + "
                         "8-seed sim_blocking_clean)",
        "verdicts": final.get("verdicts"),
        "authorized_utc": final.get("utc"),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))
    print(f"[m11] PRINT AUTHORIZED -> {MANIFEST_PATH.name}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorize", action="store_true")
    args = ap.parse_args()
    if args.authorize:
        authorize()
    else:
        print(build())
