#!/usr/bin/env bash
# Live NO-TAPE wiring check for the UCA222 electrical path.
#
# Chain under test:
#   Mac out (built-in 3.5mm jack) -> RCA -> deck IN
#   deck (RECORD-PAUSE, Dolby OFF = source monitored straight through, tape NOT moving)
#   deck OUT -> RCA -> UCA222 IN -> USB -> Mac
#
# Plays the stereo probe out the Mac's DEFAULT OUTPUT (set it to the built-in
# headphone jack in System Settings > Sound) and captures from the UCA222, then
# reports routing / level / crosstalk / clock. Nothing is written to tape.
#
# Usage:  ./loopback_check.sh [capture_seconds]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROBE="$HERE/stereo_cal_quickcheck.wav"
DUR="${1:-16}"

[ -f "$PROBE" ] || { echo "missing $PROBE -- run: python3 make_stereo_cal_master.py"; exit 1; }
mkdir -p "$HERE/captures"
STAMP="$(date +%Y%m%d_%H%M%S)"
CAP="$HERE/captures/loopback_${STAMP}.wav"

# Find the UCA222 ("USB Audio CODEC") avfoundation audio index.
IDX="$(ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 \
        | grep 'USB Audio CODEC' | grep -oE '\] \[[0-9]+\]' | grep -oE '[0-9]+' | head -1 || true)"
[ -n "$IDX" ] || { echo "UCA222 not found in avfoundation audio devices -- is it plugged in?"; exit 1; }

echo "UCA222 = avfoundation audio [$IDX]   capture ${DUR}s -> ${CAP##*/}"
echo "  (Mac default OUTPUT must be the built-in headphone jack; deck in RECORD-PAUSE, Dolby OFF)"

ffmpeg -hide_banner -loglevel error -y -f avfoundation -i ":${IDX}" -ac 2 -ar 48000 -t "$DUR" "$CAP" &
FFPID=$!
sleep 0.6                         # let the capture warm up before the probe plays
afplay "$PROBE"
wait "$FFPID" || true

echo "----"
python3 "$HERE/analyze_stereo_cal.py" "$CAP"
