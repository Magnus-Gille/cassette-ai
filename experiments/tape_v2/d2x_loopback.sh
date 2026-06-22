#!/usr/bin/env bash
# Play the d2x calibration master through the LIVE loopback (deck in SOURCE monitor:
# Mac out -> deck IN -> source-monitor -> deck OUT -> UCA222 -> Mac) and capture via
# PortAudio, then decode -> byte-exact at ~4910 bps over the electrical chain?
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WAV="${2:-$HERE/cal_d2x_mono.wav}"
DUR="${1:-300}"                      # capture seconds (>= WAV length + a little)
mkdir -p "$HERE/captures"
STAMP="$(date +%Y%m%d_%H%M%S)"
CAP="$HERE/captures/d2x_loop_${STAMP}.wav"
[ -f "$WAV" ] || { echo "missing $WAV — run make_d2x_cal.py first"; exit 1; }
echo "loopback: capture ${DUR}s -> ${CAP##*/}  (playing ${WAV##*/})"
python3 "$HERE/capture_uca.py" "$DUR" "$CAP" &
CAPPID=$!
sleep 0.8                            # let the input stream warm up
afplay "$WAV"
wait "$CAPPID" || true
echo "--- decode ---"
python3 "$HERE/decode_d2x_cal.py" "$CAP"
