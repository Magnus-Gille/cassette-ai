#!/usr/bin/env bash
# Reproduce 'corpus_contemporary_cc' — modern Creative-Commons fiction corpus.
#   Cory Doctorow (craphound.com .txt, CC BY-NC-SA 3.0): Little Brother, Down and
#     Out in the Magic Kingdom, For the Win.
#   Peter Watts — Blindsight (rifters.com, CC BY-NC-SA 2.5).
#   SCP Foundation — 25 curated articles (scp-data export, site-wide CC BY-SA 3.0).
# xz -9e on-tape.
#
# ⚠️  NONCOMMERCIAL: this bundle contains NC works (Doctorow, Watts). cassette-ai must
#     remain non-commercial while it ships these. SCP is BY-SA (no NC) but ShareAlike.
#     Full per-work attribution + obligations: ATTRIBUTION.md.
# Requires: python3, curl, xz. Builds all three 2026-06-15 corpora.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."   # payloads/built
python3 _build_new_corpora.py
echo "Built: $HERE/corpus_contemporary_cc.txt.xz"
ls -la "$HERE/corpus_contemporary_cc.txt.xz"
