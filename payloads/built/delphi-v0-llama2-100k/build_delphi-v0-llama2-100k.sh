#!/usr/bin/env bash
# Reproduce the tape-ready int4 bundle for delphi-suite/v0-llama2-100k (existing).
# License: MIT (HF cardData/tag). ship_clear.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
REPO="delphi-suite/v0-llama2-100k"
DST="payloads/built/delphi-v0-llama2-100k"

export HF_HUB_DISABLE_TELEMETRY=1
hf download "$REPO" --local-dir "$DST"

# int4 group-wise (g=64) quant, tie-aware, + tokenizer + config, xz -9e.
python3 payloads/built/quantize_llama_int4.py "$DST" "$DST"

echo "on-tape bundle: $(stat -f%z "$DST/tape_bundle.tar.xz") bytes"
