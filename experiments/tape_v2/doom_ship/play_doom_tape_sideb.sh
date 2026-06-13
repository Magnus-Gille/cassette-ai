#!/bin/bash
# play_doom_tape_sideb.sh -- play cassette SIDE B for recording.
#
# Order (per operator request): AUDIO FIRST, DATA AFTER.
#   1. "DECODED" -- the 9-track B-side album (plain audio, ~31.3 min)
#   2. ~4 s silence separator
#   3. GPL corresponding source as decodable data (~9.8 min)
#
# Total ~41 min -> fits a FULL C90 side B (45 min) with ~4 min margin.
#
# Operator SOP (same as side A -- do not skip):
#   * Dolby NR OFF at both record and playback.
#   * Record level ~7.0.
#   * Start the DECK RECORDING first, then run this script.
#   * Let it play all the way through (a live elapsed/ETA bar shows progress).
#
# The album is ordinary music -- it just plays in any deck, no decoding.
# The source section is decodable later from a capture (see end of script).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALBUM="$HERE/../bside_remix/sideB/SIDE_B_album.wav"
SOURCE="$HERE/m10doom3_sideB_source.wav"
GAP=4   # seconds of silence between music and the data section

for f in "$ALBUM" "$SOURCE"; do
  if [[ ! -f "$f" ]]; then echo "ERROR: missing $f" >&2; exit 1; fi
done

read ALBUM_S SOURCE_S < <(python3 - "$ALBUM" "$SOURCE" <<'EOF'
import sys, soundfile as sf
def s(p):
    i = sf.info(p); return int(round(i.frames / i.samplerate))
print(s(sys.argv[1]), s(sys.argv[2]))
EOF
)
TOTAL_S=$(( ALBUM_S + GAP + SOURCE_S ))
BARW=32

mmss() { printf '%02d:%02d' $(( $1 / 60 )) $(( $1 % 60 )); }

# overall progress bar against a single wall-clock START; $1 = current label
render_bar() {
  local NOW EL REM PCT FILL BAR
  NOW=$(date +%s); EL=$(( NOW - START )); EL=$(( EL > TOTAL_S ? TOTAL_S : EL ))
  REM=$(( TOTAL_S - EL )); PCT=$(( TOTAL_S > 0 ? EL * 100 / TOTAL_S : 100 ))
  FILL=$(( PCT * BARW / 100 ))
  BAR="$(printf '%*s' "$FILL" '' | tr ' ' '#')$(printf '%*s' $(( BARW - FILL )) '' | tr ' ' '-')"
  printf '\r  [%s / %s] %s %3d%% ETA %s  %-20s' \
    "$(mmss "$EL")" "$(mmss "$TOTAL_S")" "$BAR" "$PCT" "$(mmss "$REM")" "$1"
}

play_seg() {  # $1 = wav, $2 = label
  afplay "$1" &
  local APID=$!
  trap 'kill "$APID" 2>/dev/null; echo; echo "Aborted."; exit 130' INT
  while kill -0 "$APID" 2>/dev/null; do render_bar "$2"; sleep 1; done
  wait "$APID" 2>/dev/null || true
  trap - INT
}

echo "DOOM cassette SIDE B  (total $(mmss "$TOTAL_S"))"
echo "  1. DECODED -- album      $(mmss "$ALBUM_S")"
echo "  2. (silence)             00:0${GAP}"
echo "  3. GPL source -- data    $(mmss "$SOURCE_S")"
echo
echo "Checklist before recording:"
echo "  [ ] Dolby NR OFF (record + playback)"
echo "  [ ] Record level ~7.0"
echo "  [ ] FULL C90 side B (45 min), rewound, leader spooled past"
echo "  [ ] Deck is RECORDING *now*"
echo
read -r -p "Press ENTER to start playback (Ctrl-C to abort)... "

START=$(date +%s)
echo
play_seg "$ALBUM" "1/3 album (music)"

# silence separator (deck keeps recording dead air -- a clean music/data divider)
trap 'echo; echo "Aborted."; exit 130' INT
GAP_END=$(( $(date +%s) + GAP ))
while [ "$(date +%s)" -lt "$GAP_END" ]; do render_bar "2/3 gap (silence)"; sleep 1; done
trap - INT

play_seg "$SOURCE" "3/3 source (data)"

printf '\r  [%s / %s] %s 100%% ETA 00:00  %-20s\n' \
  "$(mmss "$TOTAL_S")" "$(mmss "$TOTAL_S")" "$(printf '%*s' "$BARW" '' | tr ' ' '#')" "done"

echo
echo "Done. Let the deck run ~2 s past the end, then stop it."
echo "Side B = music (just listen) + the GPL corresponding source as data."
echo "The source section rides on the tape for GPL compliance; it's described"
echo "by m10doom3_sideB_source_manifest.json (decoding it from a capture needs"
echo "that manifest -- see payloads/doom/DOOM_TAPE_REPORT.md). The album is the"
echo "main event -- it just plays in any deck."
