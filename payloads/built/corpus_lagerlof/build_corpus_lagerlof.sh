#!/usr/bin/env bash
# Reproduce 'corpus_lagerlof' — Selma Lagerlöf bilingual (Swedish + English) PD corpus.
# Swedish originals from Project Runeberg (proofread chapter HTML); English PD
# translations from Project Gutenberg (gutendex copyright=false). xz -9e on-tape.
# Author d.1940 -> PD in SE/EU (life+70, since 2011); pre-1929 -> US-PD. See PROVENANCE.md.
# Requires: python3, curl, xz. Builds all three 2026-06-15 corpora.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."   # payloads/built
python3 _build_new_corpora.py
echo "Built: $HERE/corpus_lagerlof.txt.xz"
ls -la "$HERE/corpus_lagerlof.txt.xz"
