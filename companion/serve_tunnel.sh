#!/usr/bin/env bash
# serve_tunnel.sh — throwaway HTTPS tunnel for testing the Field Decoder on a phone.
#
# Serves THIS folder (companion/) over a temporary https://<random>.trycloudflare.com
# URL so iOS Safari will grant microphone access (getUserMedia needs a secure context).
# No Cloudflare account needed (quick tunnel). Ctrl-C stops both the server and tunnel.
#
# Usage:  ./companion/serve_tunnel.sh [port]
set -euo pipefail
PORT="${1:-8000}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v cloudflared >/dev/null || { echo "cloudflared not found — 'brew install cloudflared'"; exit 1; }

echo "[serve] companion/ on http://localhost:${PORT}"
( cd "$HERE" && python3 -m http.server "$PORT" >/tmp/companion_http.log 2>&1 ) &
HTTP_PID=$!
trap 'kill "$HTTP_PID" 2>/dev/null || true' EXIT
sleep 1

echo "[tunnel] opening public HTTPS URL (look for https://*.trycloudflare.com below)…"
echo "[tunnel] open that URL in iPhone Safari → Share → Add to Home Screen"
cloudflared tunnel --url "http://localhost:${PORT}"
