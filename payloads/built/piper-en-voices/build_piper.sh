#!/usr/bin/env bash
# Reproduce the Piper English TTS voices tape payload.
# Repo weights: MIT. Per-voice DATASET license is the real gate -> we pick CC0 + public-domain voices only.
#   en_US/kathleen/low  -> dataset CC0          (x_low-equivalent; repo has NO x_low for English)
#   en_US/ljspeech/medium -> dataset public domain
# espeak-ng phonemizer frontend at inference is GPLv3 -> gpl_with_source if bundled.
# NOTE: no onnxruntime in this env -> fetch + size + license-verify only; no int8 quant validated.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="https://huggingface.co/rhasspy/piper-voices"

# 1. Verify repo license
curl -s "https://huggingface.co/api/models/rhasspy/piper-voices" \
  | python3 -c "import sys,json;print('repo license:',json.load(sys.stdin).get('cardData',{}).get('license'))"

# 2. Verify each voice's DATASET license (the binding one) from its MODEL_CARD
for spec in "kathleen/low" "ljspeech/medium"; do
  echo "--- en_US/$spec dataset license ---"
  curl -s "$BASE/raw/main/en/en_US/$spec/MODEL_CARD" | grep -i "license"
done

# 3. Fetch the two ship-clear .onnx voices + their json + model card
for spec in "kathleen/low/en_US-kathleen-low" "ljspeech/medium/en_US-ljspeech-medium"; do
  d=$(dirname "$spec"); base=$(basename "$spec")
  mkdir -p "$HERE/en_US/$d"
  curl -sL "$BASE/resolve/main/en/en_US/$spec.onnx"      -o "$HERE/en_US/$d/$base.onnx"
  curl -sL "$BASE/resolve/main/en/en_US/$spec.onnx.json" -o "$HERE/en_US/$d/$base.onnx.json"
  curl -sL "$BASE/raw/main/en/en_US/$d/MODEL_CARD"       -o "$HERE/en_US/$d/MODEL_CARD"
done

# 4. Measure on-tape (xz) size of the combined voice bundle
tar -cf /tmp/piper_both.tar -C "$HERE" en_US && xz -9 -e -f /tmp/piper_both.tar
echo "=== both voices on tape (xz) bytes ==="; stat -f%z /tmp/piper_both.tar.xz
