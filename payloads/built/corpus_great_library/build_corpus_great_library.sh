#!/usr/bin/env bash
# Reproduce the 'corpus_great_library' PD text corpus for cassette-ai.
# Fetches real Project Gutenberg texts (US public domain, pre-1928),
# strips PG boilerplate, assembles with a JSON index header, xz -9e.
# Requires: python3, curl, xz. Output: corpus_great_library.txt.xz (on-tape bytes).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."   # payloads/built
python3 _build_all_corpora.py
echo "Built: $HERE/corpus_great_library.txt.xz"
ls -la "$HERE/corpus_great_library.txt.xz"
