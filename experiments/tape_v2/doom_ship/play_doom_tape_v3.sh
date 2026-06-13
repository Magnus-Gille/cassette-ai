#!/bin/bash
# play_doom_tape_v3.sh -- play the DOOM v3 (Freedoom E1 + sound + saves) ship
# master for recording onto cassette SIDE A.
#
# Operator SOP (from CLAUDE.md -- do not skip):
#   * Dolby NR OFF at both record and playback.
#   * Record level ~7.0 (NOT 8.5 -- saturation blooms the IMD floor).
#   * ~1 s of silence rides before/after the chirps; do not trim them.
#   * Start the DECK RECORDING first, then run this script.
#   * Let the FULL master play -- the end down-chirp is a sync anchor.
#
# The v3 tape is ~41.8 min (trimmed; ~3.2 min margin): it needs a FULL C90 side
# (45 min), rewound to the very start with the leader spooled past. Side B carries
# real music. A live elapsed/ETA progress bar prints during playback.
#
# DO NOT PRINT unless BOTH blessings are on record:
#   1. doom_ship/results/m10doom3_simgate.json      -> "gate_pass": true
#      (FB=10200 long-frame physics gate: clean + 8 marginal channel cells)
#   2. doom_ship/results/m10doom3_results_selfcheck_nochan.json
#      -> "verdict": "BYTE-EXACT" (no-channel decode, rescue armed)
#
# Capture of the playback later: iPhone Voice Memos -> iCloud -> ffmpeg to
# 48 kHz mono WAV -> python3 m10doom3_decode.py <capture.wav>  (see CLAUDE.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAV="$HERE/m10doom3_master.wav"

if [[ ! -f "$WAV" ]]; then
  echo "ERROR: $WAV not found. Build it first:" >&2
  echo "  python3 $HERE/m10doom3_master.py" >&2
  exit 1
fi

GATE="$HERE/results/m10doom3_simgate.json"
SELF="$HERE/results/m10doom3_results_selfcheck_nochan.json"
python3 - "$GATE" "$SELF" <<'EOF'
import json, pathlib, sys
gate, selfc = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
ok = True
if not (gate.exists() and json.loads(gate.read_text()).get("gate_pass")):
    print("BLOCKED: FB=10200 sim gate not passed "
          "(run m10doom3_simgate.py to gate_pass=true)"); ok = False
if not (selfc.exists()
        and json.loads(selfc.read_text()).get("verdict") == "BYTE-EXACT"):
    print("BLOCKED: no-channel selfcheck not BYTE-EXACT "
          "(run m10doom3_decode.py)"); ok = False
sys.exit(0 if ok else 1)
EOF

DUR=$(python3 - "$WAV" <<'EOF'
import sys, soundfile as sf
info = sf.info(sys.argv[1])
print(f"{info.frames / info.samplerate / 60:.2f}")
EOF
)
TOTAL_S=$(python3 - "$WAV" <<'EOF'
import sys, soundfile as sf
info = sf.info(sys.argv[1])
print(int(round(info.frames / info.samplerate)))
EOF
)

echo "DOOM v3 ship tape: $WAV (${DUR} min)  [gates: PASSED]"
echo
echo "Checklist before recording:"
echo "  [ ] Dolby NR OFF (record + playback)"
echo "  [ ] Record level ~7.0"
echo "  [ ] FULL C90 side A (45 min) for ${DUR} min of master,"
echo "      fully rewound, leader spooled past"
echo "  [ ] Deck is RECORDING *now*"
echo
read -r -p "Press ENTER to start playback (Ctrl-C to abort)... "

# --- playback with a live elapsed / ETA progress bar -----------------------
# afplay has no progress output, so play it in the background and estimate
# position from wall-clock (afplay plays in real time). Ctrl-C stops the tape.
afplay "$WAV" &
APID=$!
trap 'kill "$APID" 2>/dev/null; echo; echo "Aborted."; exit 130' INT
START=$(date +%s)
BARW=32
echo
while kill -0 "$APID" 2>/dev/null; do
  NOW=$(date +%s); EL=$(( NOW - START ))
  EL=$(( EL > TOTAL_S ? TOTAL_S : EL ))
  REM=$(( TOTAL_S - EL ))
  PCT=$(( TOTAL_S > 0 ? EL * 100 / TOTAL_S : 100 ))
  FILL=$(( PCT * BARW / 100 ))
  BAR="$(printf '%*s' "$FILL" '' | tr ' ' '#')$(printf '%*s' $(( BARW - FILL )) '' | tr ' ' '-')"
  printf '\r  [%02d:%02d / %02d:%02d]  %s %3d%%  ETA %02d:%02d ' \
    $(( EL/60 )) $(( EL%60 )) $(( TOTAL_S/60 )) $(( TOTAL_S%60 )) "$BAR" "$PCT" $(( REM/60 )) $(( REM%60 ))
  sleep 1
done
wait "$APID" 2>/dev/null || true
trap - INT
printf '\r  [%02d:%02d / %02d:%02d]  %s 100%%  ETA 00:00 \n' \
  $(( TOTAL_S/60 )) $(( TOTAL_S%60 )) $(( TOTAL_S/60 )) $(( TOTAL_S%60 )) \
  "$(printf '%*s' "$BARW" '' | tr ' ' '#')"

echo
echo "Done. Let the deck run ~2 s past the end, then stop it."
echo "Decode a capture with:"
echo "  python3 $HERE/m10doom3_decode.py <capture.wav>"
