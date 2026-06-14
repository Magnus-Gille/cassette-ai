#!/bin/bash
# Play master10.wav (the master10 deliverable tape) with a live progress bar.
# ONE recording, ONE global sync. 10 rungs, robust-early -> stretch-late, with
# a FORENSIC tail canary at the very end:
#   r0  canary-2572    DQPSK P22 N512 RS159 msp375  2572  (MUST reprove or pass is VOID)
#   r1  n256-rs179     DQPSK P10 N256 RS179         2632  (proven: x10 ensemble union)
#   r2  n256-rs191     DQPSK P10 N256 RS191         2809  (proven: late-window + ladder)
#   r3  n256-p11       DQPSK P11 N256 RS179         2896  (proven: fallback record)
#   r4  n256-p11-twin  DQPSK P11 N256 RS179         2896  (realization insurance)
#   r5  d2x-p18-rs127  D2X  P18 N256 sp2 RS127      3362  (frontier derate)
#   r6  d2x-p21-rs159  D2X  P21 N256 sp2 RS159      4910  (frontier banker -- THE record attempt)
#   r7  d2x-p21-twin   D2X  P21 N256 sp2 RS159      4910  (realization insurance)
#   r8  d2x-p22-rs179  D2X  P22 N256 sp2 RS179      5791  (stretch; predicted FAIL, SER diagnostic)
#   r9  tail-canary    byte-identical r0 repeat        0  (FORENSIC ONLY: head-vs-tail differential)
#
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# !!  DO NOT PRINT x10_master10.wav or x10_master10_draft.wav -- they are  !!
# !!  STALE artifacts of the REJECTED toneplan-v2 candidate.  The tape is !!
# !!  master10.wav (built by m10_master.py, master_id=master10).          !!
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
#
# Usage:  bash experiments/tape_v2/play_master10.sh
#
# OPERATOR SOP (do not skip):
#   1. Dolby NR OFF (both record AND playback). Companding mangles the multitone.
#   2. Deck record level ~7.0 (NOT 8.5 -- saturation blooms the IMD floor).
#   3. Phone: open Voice Memos, set quality to LOSSLESS (Settings > Voice Memos >
#      Audio Quality > Lossless), START RECORDING ON THE PHONE FIRST.
#   4. THEN start the deck recording, THEN run this script (3s lead-in).
#   5. Let the FULL tape play -- do NOT stop the deck until ~1s after the end
#      chirp. The chirp pair is the global sync anchor; clipping it breaks align.
#      The LAST section (r9 tail canary, ~34s) matters: it is the head-vs-tail
#      forensic differential -- do not stop early because "the data is done".
#   6. Readback (later): speaker ~55, Voice Memos auto-syncs via iCloud; decode
#      with m10_decode.py (see below).
#   7. OPTIONAL zero-tape-cost: capture a SECOND playback of the same tape
#      (tape10_run2) -- feeds the replay-fusion machinery as a separate
#      multi-pass category (not a rung, not required).

WAV="/Users/magnus/repos/cassette-ai/experiments/tape_v2/master10.wav"
[ -f "$WAV" ] || { echo "not found: $WAV (run: python3 experiments/tape_v2/m10_master.py)"; exit 1; }

DUR=$(python3 -c "import soundfile as sf;print(int(round(sf.info('$WAV').duration)))" 2>/dev/null)
[ -z "$DUR" ] && DUR=$(afinfo "$WAV" 2>/dev/null | awk -F'[ :]+' '/estimated duration/{print int($4)}')
[ -z "$DUR" ] && DUR=363

osascript -e 'set volume output volume 75' 2>/dev/null
echo "master10.wav — master10 deliverable ladder — $((DUR/60))m $((DUR%60))s."
echo "  canary           : r0 reprove-2572 (abort rule: no canary, no records)"
echo "  proven N256      : r1 2632 | r2 2809 | r3 2896 | r4 2896-twin"
echo "  frontier dense2x : r5 3362 | r6 4910 (RECORD ATTEMPT) | r7 4910-twin"
echo "  stretch          : r8 5791 (predicted FAIL; SER diagnostic)"
echo "  forensic         : r9 tail canary (byte-identical r0 repeat, banks nothing)"
echo ""
echo "  SOP: Dolby OFF, record ~7.0. Phone Voice Memos LOSSLESS recording FIRST,"
echo "       THEN deck recording, THEN this script. Let it run PAST r9 to the end chirp."
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
echo "  Decode the capture (Voice Memos .qta -> wav -> m10_decode):"
echo "    QTA=\"\$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/<file>.qta\""
echo "    ffmpeg -hide_banner -loglevel error -y -i \"\$QTA\" -ac 1 -ar 48000 experiments/tape_v2/captures/tape10_run1.wav"
echo "    python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/captures/tape10_run1.wav"
echo "  RECORD RULE: nothing is a record unless r0 reproves 2572 orig-exact on THIS capture."
