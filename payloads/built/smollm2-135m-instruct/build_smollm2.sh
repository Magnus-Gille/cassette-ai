#!/usr/bin/env bash
# Reproduce the SmolLM2-135M-Instruct tape payload build.
# License: apache-2.0 (verified via HF API cardData.license). Ship-clear.
# Produces int8/int4/int3 group-wise quantized bundles + xz on-tape sizes.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="HuggingFaceTB/SmolLM2-135M-Instruct"
SRC="$HERE/src"

# 1. Verify license definitively
curl -s "https://huggingface.co/api/models/$REPO" \
  | python3 -c "import sys,json;print('license:',json.load(sys.stdin).get('cardData',{}).get('license'))"

# 2. Fetch weights + tokenizer (hf handles LFS)
hf download "$REPO" model.safetensors --local-dir "$SRC"
hf download "$REPO" config.json tokenizer.json tokenizer_config.json \
  special_tokens_map.json vocab.json merges.txt generation_config.json --local-dir "$SRC"

# 3. Quantize (int8, int4, int3) + lzma(xz) + roundtrip sanity (in quantize_llm.py)
python3 "$HERE/../quantize_llm.py" "$SRC" "$HERE" SmolLM2-135M-Instruct 8,4,3

# 4. Report on-tape sizes
echo "=== on-tape (xz) sizes ==="
ls -la "$HERE"/bundle_int*.tar.xz | awk '{print $5, $9}'
cat "$HERE/quant_results.json"
