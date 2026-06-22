#!/usr/bin/env bash
# Reproduce the tape-ready int4 bundle for delphi-suite/stories-llama2-50k (existing).
# License: Apache-2.0 (HF cardData/tag). ship_clear.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
REPO="delphi-suite/stories-llama2-50k"
DST="payloads/built/delphi-stories-llama2-50k"

export HF_HUB_DISABLE_TELEMETRY=1
hf download "$REPO" --local-dir "$DST"

# int4 group-wise (g=64) quant, tie-aware, + tokenizer + config, xz -9e.
python3 payloads/built/quantize_llama_int4.py "$DST" "$DST"

echo "on-tape bundle: $(stat -f%z "$DST/tape_bundle.tar.xz") bytes"
