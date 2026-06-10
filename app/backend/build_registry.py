"""build_registry.py — Build registry.json mapping tape IDs to distilled manifests.

Run this once (and again whenever master8_manifest.json changes):
    python3 app/backend/build_registry.py

Output: app/backend/registry.json
"""
from __future__ import annotations

import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
TAPE_V2 = REPO_ROOT / "experiments" / "tape_v2"
MANIFEST_PATH = TAPE_V2 / "master8_manifest.json"
REGISTRY_PATH = HERE / "registry.json"


def _sha256_file(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_registry() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())

    rungs = []
    for ws in manifest.get("ws_payloads", []):
        pack = ws.get("pack", {})
        rung_entry = {
            "name": ws["name"],
            "kind": ws["kind"],
            "phy": ws.get("phy", ""),
            "role": ws.get("role", ""),
            "gross_bps": ws.get("gross_bps"),
            "projected_net_bps": ws.get("projected_net_bps"),
            "effective_bps": ws.get("effective_bps"),
            "payload_len": ws.get("payload_len"),
            "pack_algo": pack.get("algo", "gzip"),
            "orig_len": pack.get("orig_len"),
            "sha256_packed": pack.get("sha256_packed"),
            "sha256_orig": pack.get("sha256_orig"),
        }
        # For DQPSK rungs include carrier info
        if ws["kind"] == "dqpsk":
            rung_entry["carrier_freqs_hz"] = ws.get("carrier_freqs_hz", [])
            rung_entry["pilot_hz"] = ws.get("pilot_hz")
            rung_entry["dqpsk_params"] = ws.get("dqpsk_params", {})
        rungs.append(rung_entry)

    # Payload description: what is stored on this tape?
    payload_description = (
        "stories260K int4-quantized TinyStories LLM (150 KB). "
        "Generates short stories when decoded. "
        "Multiple rungs carry adjacent 4–8 KB chunks of the LLM weights "
        "packed with gzip."
    )

    # Overall tape sha256 (from the largest sidecar as a fingerprint)
    tape_sha = None
    cass_path = pathlib.Path(manifest.get("cass_path", ""))
    if cass_path.exists():
        tape_sha = manifest.get("cass_sha256")

    entry = {
        "tape_id": "master8",
        "tape": manifest.get("tape", "master8"),
        "sample_rate": manifest.get("SR", 48000),
        "payload_description": payload_description,
        "payload_sha256": tape_sha,
        "rungs": rungs,
        "n_rungs": len(rungs),
        "global_chirp": manifest.get("global_chirp", {}),
        "sounder_sections_count": len(manifest.get("sounder_sections", [])),
    }

    registry = {"master8": entry}
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, default=float))
    print(f"[build_registry] wrote {REGISTRY_PATH}  ({len(rungs)} rungs)")
    return registry


if __name__ == "__main__":
    build_registry()
