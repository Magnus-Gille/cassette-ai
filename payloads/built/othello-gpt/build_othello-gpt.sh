#!/usr/bin/env bash
# Reproduce the tape-ready Othello-GPT payload (MIT, ship-clear).
# Needs: hf, python3 + torch + numpy, xz.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILT="$(dirname "$HERE")"

# 1. Verify license
curl -s "https://huggingface.co/api/models/Baidicoot/Othello-GPT-Transformer-Lens" \
  | python3 -c "import sys,json;print('license:',json.load(sys.stdin)['cardData']['license'])"

# 2. Fetch weights
hf download Baidicoot/Othello-GPT-Transformer-Lens --local-dir "$HERE/src"

# 3. Quantize (int4 + int8), bundle config, lzma(xz -9e), measure, round-trip check
#    (torch.load weights_only=True; attn.mask buffers stripped)
python3 "$BUILT/build_othello.py"

echo "On-tape artifacts:"
ls -lh "$HERE"/othello_int*.bin.xz
