#!/bin/bash
# Play master11.wav (the x12 probe tape) with a live progress bar.
# ONE recording, ONE global sync. 3 rungs, robust-early -> stretch-late,
# ~1.8 min total — this is a SHORT PROBE TAPE, not a record attempt:
#   c0  anchor-2572     DQPSK P22 N512 RS159 msp375  2572  (canary: MUST reprove or pass is VOID)
#   c1  d2x-4910        D2X  P21 N256 sp2 RS159      4910  (canary #2: best-proven d2x banker)
#   c3  dbpsk-p12-ext   DBPSK P12 N256 sp2 RS191     1685  (x12 GO probe: 8 mid + 4 ext bins
#                                                           9375-10500 Hz, 90-deg boundary —
#                                                           banks the >9 kHz DBPSK SER map)
#
# The standing record (5791, tape10) is NOT challenged by this tape; no rung
# rides above the proven 4910. The probe converts the last open frontier axis
# (>9 kHz ext bins) from model prediction to real-capture measurement.
#
# The tape is master11.wav (built by x12_master11_master.py, master_id=master11,
# print_authorized=true in master11_manifest.json — audio byte-identical to the
# gated x12_master_regate.wav). The decoder refuses any other manifest.
#
# Usage:  bash experiments/tape_v2/play_master11.sh
#
# OPERATOR SOP (do not skip — tape10 proved LOWER volume is FINE):
#   1. Dolby NR OFF (both record AND playback). Companding mangles the multitone.
#   2. Deck record level ~7.0 (NOT 8.5 — saturation blooms the IMD floor).
#   3. Phone: Voice Memos, quality LOSSLESS, START RECORDING ON THE PHONE FIRST.
#   4. THEN start the deck recording, THEN run this script (3s lead-in).
#   5. Let the FULL tape play — do NOT stop the deck until ~1s after the end
#      chirp. The chirp pair is the global sync anchor; clipping it breaks align.
#   6. Readback (later): speaker ~55, Voice Memos auto-syncs via iCloud; decode
#      with x12_master11_decode.py (see below).

WAV="/Users/magnus/repos/cassette-ai/experiments/tape_v2/master11.wav"
[ -f "$WAV" ] || { echo "not found: $WAV (run: python3 experiments/tape_v2/x12_master11_master.py)"; exit 1; }

AUTH=$(python3 -c "import json;print(json.load(open('/Users/magnus/repos/cassette-ai/experiments/tape_v2/master11_manifest.json'))['print_authorized'])" 2>/dev/null)
[ "$AUTH" = "True" ] || { echo "REFUSING: master11_manifest.json print_authorized=$AUTH (run the blocking self-check + --authorize first)"; exit 1; }

DUR=$(python3 -c "import soundfile as sf;print(int(round(sf.info('$WAV').duration)))" 2>/dev/null)
[ -z "$DUR" ] && DUR=$(afinfo "$WAV" 2>/dev/null | awk -F'[ :]+' '/estimated duration/{print int($4)}')
[ -z "$DUR" ] && DUR=108

osascript -e 'set volume output volume 75' 2>/dev/null
echo "master11.wav — x12 probe ladder — $((DUR/60))m $((DUR%60))s."
echo "  canary pair : c0 reprove-2572 + c1 d2x-4910 (abort rule: both or the pass is VOID)"
echo "  probe       : c3 DBPSK ext-band 1685 (banks the >9 kHz SER map either way)"
echo ""
echo "  SOP: Dolby OFF, record ~7.0. Phone Voice Memos LOSSLESS recording FIRST,"
echo "       THEN deck recording, THEN this script. Let it run PAST the end chirp."
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
echo "  Decode the capture (Voice Memos .qta -> wav -> x12_master11_decode):"
echo "    QTA=\"\$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta\""
echo "    ffmpeg -hide_banner -loglevel error -y -i \"\$QTA\" -ac 1 -ar 48000 experiments/tape_v2/captures/tape11_run1.wav"
echo "    python3 experiments/tape_v2/x12_master11_decode.py experiments/tape_v2/captures/tape11_run1.wav"
echo "  VALIDITY RULE: the pass is valid only if BOTH canaries (c0 2572 AND c1 4910)"
echo "  decode orig-exact on THIS capture. The c3 SER map banks either way."
