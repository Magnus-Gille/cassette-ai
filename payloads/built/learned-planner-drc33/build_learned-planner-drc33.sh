#!/usr/bin/env bash
# Build: learned-planner DRC(3,3) Sokoban planner -> tape-ready quantized bundle
# License: Apache-2.0 (AlignmentResearch/learned-planner, verified cardData + README frontmatter)
# "A cassette that plans" — a recurrent ConvLSTM that plays Sokoban by internal planning.
set -euo pipefail
cd "$(dirname "$0")"

REPO=AlignmentResearch/learned-planner
CKPT=drc33/bkynosqi/cp_2002944000   # best DRC(3,3), 1,285,125 params

# 1. Fetch ONLY the best checkpoint (model = flax msgpack, cfg = hyperparams)
hf download "$REPO" \
  "$CKPT/model" "$CKPT/cfg.json" count_params.py \
  --local-dir .

# 2. Extract policy params (drop opt_state + critic value head), quantize int8 + int4,
#    lzma-compress the bundle, sanity round-trip.
python3 quantize_drc33.py

echo "Build complete. See meta.json for measured on-tape size."
