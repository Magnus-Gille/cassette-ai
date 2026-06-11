#!/usr/bin/env bash
# Fetch candidate tape payloads (LLM models + DOOM) into payloads/.
# Idempotent: skips items already present. Never aborts the whole run on one failure;
# logs per-item OK/SKIP/FAIL to payloads/fetch_manifest.txt. See payloads/README.md.
#
# Usage: fetch_payloads.sh [all|llm|doom|overbudget]   (default: all)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
MANIFEST="$HERE/fetch_manifest.txt"
: > "$MANIFEST"
WHAT="${1:-all}"

log()  { printf '%s\n' "$*" | tee -a "$MANIFEST"; }
have() { command -v "$1" >/dev/null 2>&1; }

# hf download <repo> <localdir> [include-glob]
fetch_hf() {
  local repo="$1" dir="$2" inc="${3:-}"
  if [ -d "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then log "SKIP  hf  $repo (exists)"; return; fi
  mkdir -p "$dir"
  local args=(download "$repo" --local-dir "$dir")
  [ -n "$inc" ] && args+=(--include "$inc")
  if hf "${args[@]}" >/dev/null 2>&1; then log "OK    hf  $repo -> $dir"
  else log "FAIL  hf  $repo (see: hf ${args[*]})"; fi
}

# fetch_url <url> <outfile>
fetch_url() {
  local url="$1" out="$2"
  if [ -s "$out" ]; then log "SKIP  url $out (exists)"; return; fi
  mkdir -p "$(dirname "$out")"
  if curl -fsSL "$url" -o "$out"; then log "OK    url $out"
  else log "FAIL  url $url"; fi
}

# clone_git <url> <dir>
clone_git() {
  local url="$1" dir="$2"
  if [ -d "$dir/.git" ]; then log "SKIP  git $dir (exists)"; return; fi
  if git clone --depth 1 "$url" "$dir" >/dev/null 2>&1; then log "OK    git $url -> $dir"
  else log "FAIL  git $url"; fi
}

have hf  || { log "ERROR: 'hf' CLI not found (pip install huggingface_hub[cli])"; }
have git || { log "ERROR: 'git' not found"; }

log "=== fetch_payloads ($WHAT) ==="

if [ "$WHAT" = all ] || [ "$WHAT" = llm ]; then
  log "--- A. LLM models that fit a cassette ---"
  fetch_hf  karpathy/tinyllamas            llm_tape_fit/stories260K            "stories260K/*"
  fetch_url "https://github.com/onnx/models/raw/main/validated/vision/classification/mnist/model/mnist-12.onnx" \
            llm_tape_fit/mnist/mnist-12.onnx
  fetch_hf  delphi-suite/v0-mamba-200k     llm_tape_fit/delphi-v0-mamba-200k
  fetch_hf  delphi-suite/v0-llama2-100k    llm_tape_fit/delphi-v0-llama2-100k
  fetch_hf  delphi-suite/stories-llama2-50k llm_tape_fit/delphi-stories-llama2-50k
fi

if [ "$WHAT" = all ] || [ "$WHAT" = overbudget ] || [ "$WHAT" = llm ]; then
  log "--- C. Over-budget model candidates ---"
  fetch_hf  derickio/chess-gpt-4.5M        llm_over_budget/chess-gpt-4.5M
  fetch_hf  1aurent/ddpm-mnist             llm_over_budget/ddpm-mnist
  fetch_hf  gnsepili/shakespeare-rnn       llm_over_budget/shakespeare-rnn
  clone_git https://github.com/IraKorshunova/folk-rnn.git  llm_over_budget/folk-rnn
fi

if [ "$WHAT" = all ] || [ "$WHAT" = doom ]; then
  log "--- B. DOOM payload ---"
  clone_git https://github.com/ozkl/doomgeneric.git  doom/doomgeneric
  fetch_url "https://github.com/freedoom/freedoom/releases/download/v0.13.0/freedoom-0.13.0.zip" \
            doom/freedoom-0.13.0.zip
fi

log "=== done; summary ==="
grep -cE '^OK'   "$MANIFEST" | xargs -I{} echo "OK:   {}" | tee -a "$MANIFEST"
grep -cE '^SKIP' "$MANIFEST" | xargs -I{} echo "SKIP: {}" | tee -a "$MANIFEST"
grep -cE '^FAIL' "$MANIFEST" | xargs -I{} echo "FAIL: {}" | tee -a "$MANIFEST"
echo "Manifest: $MANIFEST"
