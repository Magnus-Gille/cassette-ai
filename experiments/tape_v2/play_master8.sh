#!/bin/bash
# Play master8.wav (the overnight-campaign deliverable) at volume 75 with a live
# progress bar. 9 rungs in ONE recording, one global sync:
#   6x WS (M16 K1/K2/K3 + M32 K2 turbo) + 3x DQPSK (P10).
#
# Usage:  bash experiments/tape_v2/play_master8.sh
# Start your deck RECORDING first, then run this (it gives a 3s lead-in).
# SOP: Dolby NR OFF, record ~7.0, readback speaker ~55, ~1s silence around chirps.

WAV="/Users/magnus/repos/cassette-ai/experiments/tape_v2/master8.wav"
[ -f "$WAV" ] || { echo "not found: $WAV"; exit 1; }

DUR=$(python3 -c "import soundfile as sf;print(int(round(sf.info('$WAV').duration)))" 2>/dev/null)
[ -z "$DUR" ] && DUR=$(afinfo "$WAV" 2>/dev/null | awk -F'[ :]+' '/estimated duration/{print int($4)}')
[ -z "$DUR" ] && DUR=574

osascript -e 'set volume output volume 75' 2>/dev/null
echo "master8.wav — overnight deliverable ladder — $((DUR/60))m $((DUR%60))s."
echo "  WS: M16 K1 RS191 | M32 K2 RS127/159 | M16 K2 RS159/191 | M16 K3 RS159"
echo "  DQPSK: P10 N1024 RS159/223 | P10 N512 RS127"
echo "  Make sure the deck is RECORDING (Dolby OFF, level ~7.0)."
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
