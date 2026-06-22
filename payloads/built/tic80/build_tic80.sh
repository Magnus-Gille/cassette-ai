#!/usr/bin/env bash
# Reproduce the TIC-80 "games console on a cassette" tape payload.
# License: TIC-80 engine + demo carts are MIT (nesbox/TIC-80 LICENSE). ship_clear.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

REL="v1.1.2837"
ENGINE_ZIP="tic80-v1.1-html.zip"

# 1. Engine: official HTML/WASM release build (MIT)
curl -sL -o tic80-html.zip \
  "https://github.com/nesbox/TIC-80/releases/download/${REL}/${ENGINE_ZIP}"
rm -rf engine && mkdir -p engine && (cd engine && unzip -o -q ../tic80-html.zip)

# 2. LICENSE (MIT) — ship it
curl -sL -o LICENSE "https://raw.githubusercontent.com/nesbox/TIC-80/main/LICENSE"

# 3. Curated MIT demo carts (all from the repo's demos/, repo-wide MIT)
rm -rf carts && mkdir -p carts
BASE="https://raw.githubusercontent.com/nesbox/TIC-80/main/demos"
for c in tetris.lua quest.lua car.lua p3d.lua fire.lua palette.lua bpp.lua \
         luademo.lua fenneldemo.fnl jsdemo.js wrendemo.wren rubydemo.rb \
         schemedemo.scm music.lua sfx.lua font.lua; do
  curl -sL -o "carts/$c" "$BASE/$c"
done

# 4. Assemble tape bundle (engine + carts + license) and compress
rm -rf bundle && mkdir -p bundle
cp engine/tic80.wasm engine/tic80.js engine/index.html bundle/
cp -r carts bundle/carts
cp LICENSE bundle/LICENSE
tar cf bundle.tar -C bundle .
xz -9e -k -f bundle.tar   # -> bundle.tar.xz = on-tape bytes

echo "on_tape_bytes: $(stat -f%z bundle.tar.xz)"
