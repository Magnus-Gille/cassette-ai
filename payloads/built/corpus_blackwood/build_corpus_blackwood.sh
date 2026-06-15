#!/usr/bin/env bash
# Reproduce 'corpus_blackwood' — Algernon Blackwood weird-tales PD corpus.
# Project Gutenberg plain text (gutendex copyright=false). Author d.1951; every
# work pre-1929 -> US public domain. xz -9e on-tape. See PROVENANCE.md.
# Requires: python3, curl, xz. Builds all three 2026-06-15 corpora.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."   # payloads/built
python3 _build_new_corpora.py
echo "Built: $HERE/corpus_blackwood.txt.xz"
ls -la "$HERE/corpus_blackwood.txt.xz"
