#!/usr/bin/env bash
# Reproduce the CHIP-8 (Octo IDE + CC0 game archive) tape payload.
# License: Octo = MIT; chip8Archive ROMs = CC0 (repo-wide dedication). ship_clear.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# 1. Octo IDE (MIT) — gh-pages is the live runnable IDE
rm -rf octo_src && git clone --depth 1 https://github.com/JohnEarnest/Octo.git octo_src

# 2. CHIP-8 Archive (CC0) — 101 games + metadata
rm -rf archive_src && git clone --depth 1 https://github.com/JohnEarnest/chip8Archive.git archive_src

# 3. Assemble runnable bundle: trimmed Octo runtime + ROMs
rm -rf bundle && mkdir -p bundle/octo bundle/roms
cp octo_src/index.html octo_src/standalone.html bundle/octo/
cp -r octo_src/js octo_src/css octo_src/lib bundle/octo/
cp octo_src/LICENSE.txt bundle/octo/LICENSE.txt
# UI-essential images only (drop doc screenshots/gifs: 1.0MB -> ~68KB)
mkdir -p bundle/octo/images
for img in favicon.ico logo.png keypad.png close.png continue.png load.gif; do
  cp "octo_src/images/$img" bundle/octo/images/ 2>/dev/null || true
done
# CC0 ROMs + metadata + the CC0-dedication README (license evidence)
cp -r archive_src/roms/* bundle/roms/
cp archive_src/programs.json archive_src/authors.json bundle/roms/
cp archive_src/Readme.md bundle/roms/ARCHIVE_README.md

# 4. Compress -> on-tape bytes
tar cf bundle.tar -C bundle .
xz -9e -k -f bundle.tar
echo "on_tape_bytes: $(stat -f%z bundle.tar.xz)"
