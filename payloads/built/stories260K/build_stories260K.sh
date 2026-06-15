#!/usr/bin/env bash
# Reproduce the tape-ready int4 bundle for karpathy stories260K (llama2.c format).
# License: MIT (karpathy/tinyllamas HF cardData/tag; llama2.c is MIT). ship_clear.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
DST_DL="payloads/built/stories260K_dl"
DST="payloads/built/stories260K"

export HF_HUB_DISABLE_TELEMETRY=1
hf download karpathy/tinyllamas \
  stories260K/stories260K.pt stories260K/stories260K.bin \
  stories260K/tok512.bin stories260K/tok512.model stories260K/readme.md \
  --local-dir "$DST_DL"

python3 payloads/built/build_stories260K.py "$DST_DL/stories260K" "$DST"
echo "on-tape bundle: $(stat -f%z "$DST/tape_bundle.tar.xz") bytes"
