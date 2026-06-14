#!/bin/bash
# Play master9.wav (the master9 deliverable tape) with a live progress bar.
# ONE recording, ONE global sync. 11 rungs + 2 diagnostic probes (P1 null-map,
# P2 pilot-jitter + IMD level-ramp), robust-early -> stretch-late:
#   M0  reprove-934   DQPSK P10 N512 RS127  934   (proven record canary)
#   M1  thin-159      DQPSK P10 N512 RS159  1169  (1.25x)
#   M2  thin-191      DQPSK P10 N512 RS191  1404  (1.50x  near-certain floor)
#   M3  drop-null-9c  DQPSK P9  N512 RS159  1052  (1.13x)
#   M4/M4b N256 cntr  DQPSK P10 N256 RS159  2338  (2.50x  CENTERPIECE bet)
#   M5/M6/M7 N256+    DQPSK P10/11 N256     2632-2896 (2.8-3.1x cliff-bracket)
#   M8  dense-375     DQPSK P22 N512 RS159  2572  (2.75x  HOLD flutter-ICI probe)
#   M9a freq-diff     FDQPSK P11 N512 RS159 1169  (1.25x  timing-immune lottery)
#
# Usage:  bash experiments/tape_v2/play_master9.sh
#
# OPERATOR SOP (do not skip):
#   1. Dolby NR OFF (both record AND playback). Companding mangles the multitone.
#   2. Deck record level ~7.0 (NOT 8.5 -- saturation blooms the IMD floor).
#   3. Phone: open Voice Memos, set quality to LOSSLESS (Settings > Voice Memos >
#      Audio Quality > Lossless), START RECORDING ON THE PHONE FIRST.
#   4. THEN start the deck recording, THEN run this script (3s lead-in).
#   5. Let the FULL tape play -- do NOT stop the deck until ~1s after the end
#      chirp. The chirp pair is the global sync anchor; clipping it breaks align.
#   6. Readback (later): speaker ~55, Voice Memos auto-syncs via iCloud; decode
#      with m9_decode.py (see below).

WAV="/Users/magnus/repos/cassette-ai/experiments/tape_v2/master9.wav"
[ -f "$WAV" ] || { echo "not found: $WAV (run: python3 experiments/tape_v2/m9_master.py)"; exit 1; }

DUR=$(python3 -c "import soundfile as sf;print(int(round(sf.info('$WAV').duration)))" 2>/dev/null)
[ -z "$DUR" ] && DUR=$(afinfo "$WAV" 2>/dev/null | awk -F'[ :]+' '/estimated duration/{print int($4)}')
[ -z "$DUR" ] && DUR=483

osascript -e 'set volume output volume 75' 2>/dev/null
echo "master9.wav — master9 deliverable ladder — $((DUR/60))m $((DUR%60))s."
echo "  N512 near-certain: M0 RS127 | M1 RS159 | M2 RS191 | M3 drop-null"
echo "  N256 record push : M4/M4b RS159 | M5 RS179 | M6 RS191 | M7 P11"
echo "  HOLD probes      : M8 dense-375 | M9a freq-differential"
echo "  + P1 null-map, P2 pilot-jitter + IMD level-ramp (diagnostics)"
echo ""
echo "  SOP: Dolby OFF, record ~7.0. Phone Voice Memos LOSSLESS recording FIRST,"
echo "       THEN deck recording, THEN this script. Let it run to the end chirp."
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
echo ""
echo "  Decode the capture (Voice Memos .qta -> wav -> m9_decode):"
echo "    QTA=\"\$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta\""
echo "    ffmpeg -hide_banner -loglevel error -y -i \"\$QTA\" -ac 1 -ar 48000 experiments/tape_v2/captures/tape9_run1.wav"
echo "    python3 experiments/tape_v2/m9_decode.py experiments/tape_v2/captures/tape9_run1.wav"
echo "  FIRST on the real capture: re-anchor the HF-flutter gate from P2(a) before claiming any N256 verdict."
