#!/usr/bin/env bash
# Build: 1aurent/ddpm-mnist -> tape-ready quantized bundle
# License: MIT (verified: HF cardData.license=mit + README frontmatter + license:mit tag)
# "Paints digits" — a tiny unconditional UNet2D DDPM that generates MNIST-style digit images.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Fetch weights + diffusion config + scheduler (the runtime needs all three)
hf download 1aurent/ddpm-mnist \
  diffusion_pytorch_model.safetensors config.json model_index.json scheduler_config.json README.md \
  --local-dir .

# 2. Quantize int8 + int4, bundle (quant weights + UNet config + scheduler), xz -9e, round-trip.
python3 quantize_ddpm.py

echo "Build complete. See meta.json for measured on-tape size."
