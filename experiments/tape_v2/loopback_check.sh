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

echo "capture ${DUR}s from UCA222 (PortAudio) -> ${CAP##*/}"
echo "  (Mac default OUTPUT must be the built-in headphone jack; deck in RECORD-PAUSE, Dolby OFF)"

# Capture via PortAudio (sounddevice), NOT ffmpeg avfoundation -- the latter drops
# ~11.5% of samples on this machine. capture_uca.py picks the UCA222 by name.
python3 "$HERE/capture_uca.py" "$DUR" "$CAP" &
CAPPID=$!
sleep 0.6                         # let the input stream warm up before the probe plays
afplay "$PROBE"
wait "$CAPPID" || true

echo "----"
python3 "$HERE/analyze_stereo_cal.py" "$CAP"
