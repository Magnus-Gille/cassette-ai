#!/usr/bin/env bash
# Play the STEREO d2x master (same proven d2x body on L+R + crosstalk probes) through
# the live source-monitor loopback, capture via PortAudio, then: measure routing/
# crosstalk from the probes, and decode BOTH channels -> true 2x (~9820 bps) byte-exact?
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WAV="${2:-$HERE/cal_d2x_stereo.wav}"
DUR="${1:-312}"                      # capture seconds (>= stereo WAV length + margin)
mkdir -p "$HERE/captures"
CAP="$HERE/captures/d2x_stereo_loop_$(date +%Y%m%d_%H%M%S).wav"
[ -f "$WAV" ] || { echo "missing $WAV — run make_d2x_stereo_cal.py first"; exit 1; }
echo "stereo loopback: capture ${DUR}s -> ${CAP##*/}  (playing ${WAV##*/})"
python3 "$HERE/capture_uca.py" "$DUR" "$CAP" &
CAPPID=$!
sleep 0.8
afplay "$WAV"
if ! wait "$CAPPID"; then echo "capture FAILED (capture_uca.py exited non-zero) — aborting"; exit 1; fi
echo "--- routing / crosstalk (from probes) ---"
python3 "$HERE/analyze_stereo_cal.py" "$CAP" --sidecar "$HERE/cal_d2x_stereo.json" || true
echo "--- decode LEFT  (channel 0) ---"
python3 "$HERE/decode_d2x_cal.py" "$CAP" --channel 0
echo "--- decode RIGHT (channel 1) ---"
python3 "$HERE/decode_d2x_cal.py" "$CAP" --channel 1
