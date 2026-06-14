#!/bin/bash
# play_doom_tape.sh -- play the DOOM ship master for recording onto cassette.
#
# Operator SOP (from CLAUDE.md -- do not skip):
#   * Dolby NR OFF at both record and playback.
#   * Record level ~7.0 (NOT 8.5 -- saturation blooms the IMD floor).
#   * ~1 s of silence rides before/after the chirps; do not trim them.
#   * Start the DECK RECORDING first, then run this script.
#   * Let the FULL master play -- the end down-chirp is a sync anchor.
#
# Capture of the playback later: iPhone Voice Memos -> iCloud -> ffmpeg to
# 48 kHz mono WAV -> python3 m10doom_decode.py <capture.wav>   (see CLAUDE.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAV="$HERE/m10doom_master.wav"

if [[ ! -f "$WAV" ]]; then
  echo "ERROR: $WAV not found. Build it first:" >&2
  echo "  python3 $HERE/m10doom_master.py" >&2
  exit 1
fi

DUR=$(python3 - "$WAV" <<'EOF'
import sys, soundfile as sf
info = sf.info(sys.argv[1])
print(f"{info.frames / info.samplerate / 60:.2f}")
EOF
)

echo "DOOM ship tape: $WAV (${DUR} min)"
echo
echo "Checklist before recording:"
echo "  [ ] Dolby NR OFF (record + playback)"
echo "  [ ] Record level ~7.0"
echo "  [ ] C60 side A loaded, fully rewound, leader spooled past"
echo "  [ ] Deck is RECORDING *now*"
echo
read -r -p "Press ENTER to start playback (Ctrl-C to abort)... "

afplay "$WAV"

echo
echo "Done. Let the deck run ~2 s past the end, then stop it."
echo "Decode a capture with:"
echo "  python3 $HERE/m10doom_decode.py <capture.wav>"
