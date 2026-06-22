#!/usr/bin/env bash
# Reproduce the tape-ready chess-gpt-4.5M payload (MIT, ship-clear).
# Needs: hf (huggingface-cli), python3 + torch + safetensors + numpy, xz.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILT="$(dirname "$HERE")"   # payloads/built

# 1. Verify license (definitive permissive tag)
curl -s "https://huggingface.co/api/models/derickio/chess-gpt-4.5M" \
  | python3 -c "import sys,json;print('license:',json.load(sys.stdin)['cardData']['license'])"

# 2. Fetch weights + tokenizer
hf download derickio/chess-gpt-4.5M --local-dir "$HERE/src"

# 3. Quantize (int4 + int8), bundle tokenizer/config, lzma(xz -9e), measure, round-trip check
python3 "$BUILT/build_chess_gpt.py"

echo "On-tape artifacts:"
ls -lh "$HERE"/chess_gpt_int*.bin.xz
