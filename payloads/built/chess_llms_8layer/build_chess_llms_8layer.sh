#!/usr/bin/env bash
# chess_llms_8layer is BLOCKED (no license on the weights). This script ONLY
# fetches + measures size for the dossier. It does NOT produce a shippable artifact.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# License probe (expected: license = None -> BLOCKED)
echo "== HF license tag =="
curl -s "https://huggingface.co/api/models/adamkarvonen/chess_llms" \
  | python3 -c "import sys,json;print('cardData.license:',(json.load(sys.stdin).get('cardData') or {}).get('license'))"
echo "== LICENSE file probe =="
for f in LICENSE LICENSE.txt LICENSE.md license; do
  printf '%s -> HTTP %s\n' "$f" \
    "$(curl -s -o /dev/null -w '%{http_code}' "https://huggingface.co/adamkarvonen/chess_llms/raw/main/$f")"
done

# Fetch single checkpoint for measurement only
hf download adamkarvonen/chess_llms lichess_8layers_ckpt_no_optimizer.pt --local-dir "$HERE/src"

# Measure raw + xz size (no shippable artifact retained)
RAW="$HERE/src/lichess_8layers_ckpt_no_optimizer.pt"
echo "raw_bytes: $(stat -f%z "$RAW")"
TMP="$(mktemp)"; cp "$RAW" "$TMP"; xz -9e -f "$TMP"
echo "xz_bytes:  $(stat -f%z "$TMP.xz")"; rm -f "$TMP.xz"
echo "BLOCKED: no license on weights -> no tape-ready artifact built."
