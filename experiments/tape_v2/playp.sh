#!/usr/bin/env bash
# playp.sh <wav> — play a WAV via afplay with a live elapsed / remaining / total display.
# afplay itself prints no progress; this estimates position from wall-clock (afplay is real-time).
# Ctrl-C stops playback cleanly.
set -euo pipefail

WAV="${1:?usage: playp.sh <file.wav>}"
[ -f "$WAV" ] || { echo "no such file: $WAV" >&2; exit 1; }

# total length in whole seconds (ceil), via soundfile (already a project dep)
T=$(python3 -c "import soundfile as sf,sys,math; i=sf.info(sys.argv[1]); print(math.ceil(i.frames/i.samplerate))" "$WAV")
mmss(){ printf '%d:%02d' $(( $1/60 )) $(( $1%60 )); }

# recording standard: drive the deck at a fixed 75% system output volume
osascript -e 'set volume output volume 75' 2>/dev/null \
  && echo "🔊 output volume → 75% (recording standard)"

echo "▶ $(basename "$WAV")   total $(mmss "$T")"
afplay "$WAV" &
PID=$!
trap 'kill "$PID" 2>/dev/null; printf "\n■ stopped\n"; exit 0' INT TERM

START=$(date +%s)
W=30
while kill -0 "$PID" 2>/dev/null; do
  E=$(( $(date +%s) - START )); [ "$E" -gt "$T" ] && E=$T
  R=$(( T - E ))
  FILL=$(( T > 0 ? E * W / T : W ))
  BAR=$(printf '%*s' "$FILL" '' | tr ' ' '#')$(printf '%*s' $(( W - FILL )) '' | tr ' ' '-')
  printf '\r[%s] %s / %s  (-%s) ' "$BAR" "$(mmss "$E")" "$(mmss "$T")" "$(mmss "$R")"
  sleep 1
done
printf '\r[%s] %s / %s  done       \n' "$(printf '%*s' "$W" '' | tr ' ' '#')" "$(mmss "$T")" "$(mmss "$T")"
