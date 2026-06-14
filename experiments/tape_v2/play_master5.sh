#!/bin/bash
# Play master5.wav at volume 75 with a live countdown + progress bar.
# 4 WS rungs (RS rate ladder), ~10.5 min total.
#
# Usage:  bash experiments/tape_v2/play_master5.sh
# Start your deck RECORDING first, then run this (it gives a 3s lead-in).

WAV="/Users/magnus/repos/cassette-ai/experiments/tape_v2/master5.wav"
[ -f "$WAV" ] || { echo "not found: $WAV"; exit 1; }

DUR=$(python3 -c "import soundfile as sf;print(int(round(sf.info('$WAV').duration)))" 2>/dev/null)
[ -z "$DUR" ] && DUR=$(afinfo "$WAV" 2>/dev/null | awk -F'[ :]+' '/estimated duration/{print int($4)}')
[ -z "$DUR" ] && DUR=629

osascript -e 'set volume output volume 75' 2>/dev/null
echo "master5.wav — RS rate ladder — $((DUR/60))m $((DUR%60))s."
echo "  4 WS rungs: RS(255,111) RS(255,159) RS(255,191) RS(255,223)"
echo "  Make sure the deck is RECORDING."
for i in 3 2 1; do printf "\r  starting in %d... " "$i"; sleep 1; done
printf "\r  ▶ playing — let it run to the end (don't stop the deck early)        \n"

afplay "$WAV" &
PID=$!
START=$(date +%s)
BARW=40
while kill -0 "$PID" 2>/dev/null; do
  NOW=$(date +%s); EL=$((NOW-START)); REM=$((DUR-EL)); [ "$REM" -lt 0 ] && REM=0
  FILL=$(( EL*BARW/DUR )); [ "$FILL" -gt "$BARW" ] && FILL=$BARW
  BAR=$(printf '%*s' "$FILL" '' | tr ' ' '#')$(printf '%*s' $((BARW-FILL)) '' | tr ' ' '-')
  printf "\r  [%s]  %02d:%02d elapsed | %02d:%02d left " "$BAR" $((EL/60)) $((EL%60)) $((REM/60)) $((REM%60))
  sleep 1
done
printf "\r  [%s]  done — STOP the deck (after ~1s of silence).                   \n" "$(printf '%*s' $BARW '' | tr ' ' '#')"
