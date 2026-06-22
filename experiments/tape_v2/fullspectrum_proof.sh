#!/usr/bin/env bash
# FULL-SPECTRUM tape proof -- ONE stereo master + ONE grading decoder that
# characterize a setup across the whole d2x/m10 capability tier in a SINGLE pass.
#
#     ./fullspectrum_proof.sh record           # play the master -> deck RECORD -> tape
#     (stop the deck, rewind to the start)
#     ./fullspectrum_proof.sh capture [secs]   # deck PLAY -> UCA222 -> capture + grade
#
# The grade you get depends on the CAPTURE PATH:
#   * WIRED UCA222 (true stereo, independent L/R): recovers the mono rungs AND the
#     true-stereo top rung -> up to ~9820 bps (R3 P21 RS159 on BOTH channels).
#   * ACOUSTIC / phone (summed mono): recovers the robust LOW/MID rungs (R0-R2) and
#     reveals the acoustic ceiling; the stereo-only top rung CORRECTLY fails when
#     summed (the two channels add incoherently) -- that is honest, not a bug.
#
# RUNG LADDER (robust -> aggressive; all PROVEN m10 d2x/dqpsk family):
#   R0 robust  DQPSK P10 N256 sp4 RS(255,127) ~1868 net   MONO   (same payload L=R)
#   R1 mid     DQPSK P10 N256 sp4 RS(255,191) ~2809 net   MONO   (same payload L=R)
#   R2 mid-hi  D2X   P18 drop     RS(255,127) ~3362 net   MONO   (same payload L=R)
#   R3 top     D2X   P21 drop     RS(255,159) ~4910/ch    STEREO (INDEPENDENT L/R) -> ~9820
#
# DEFERRED TO v2 (documented, NOT faked): the sub-kbps BFSK/WS floor rungs (the
# 326/562 bps record-holders) and the full eval report-card (SNR/BW/flutter/clock/
# IMD scoring). The conservative floor here is the most-robust DQPSK rung (R0).
# The front Schroeder sounder IS on the tape (the decoder reads SNR/flutter/noise
# floor from it); only the full report-card SCORING logic is deferred.
#
# WIRING (identical both phases -- cables do not move, only the deck transport does):
#     Mac out (built-in 3.5mm headphone jack) -> RCA -> deck IN
#     deck OUT -> RCA -> UCA222 IN -> USB -> Mac
#   Mac DEFAULT OUTPUT must be the built-in headphone jack (System Settings > Sound).
#   Capture uses the UCA222 by name ("USB Audio CODEC") via PortAudio (capture_uca.py) --
#   NOT ffmpeg avfoundation (drops ~11.5% of samples on this machine).
#
# SOP (do not skip):
#   * Dolby NR OFF at BOTH record AND playback (companding mangles QAM/multitone).
#   * Record level ~7.0 -- NOT 8.5 (8.5 saturates -> IMD floor blooms, kills dense carriers).
#   * Readback speaker ~55; ~1 s silence around the start/end chirps (the sync anchors).
#   * Let the master run to the END chirp before stopping. The decoder self-syncs on
#     the chirp pair, so arbitrary PLAY-timing slack is fine -- just press PLAY promptly.
#
# PRE-FLIGHT (no tape, recommended before burning):
#     ./loopback_check.sh   # deck RECORD-PAUSE (Dolby OFF) -> verify routing/level/clock
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WAV="$HERE/fullspectrum_master.wav"
CMD="${1:-}"

case "$CMD" in
  record)
    [ -f "$WAV" ] || { echo "missing $WAV -- run: python3 fullspectrum_master.py"; exit 1; }
    echo ">>> RECORD phase"
    echo "    Checklist: blank tape loaded . Dolby NR OFF . record level ~7.0 . deck in RECORD (tape moving)."
    echo "    Mac default OUTPUT = built-in 3.5mm headphone jack (-> deck IN)."
    echo "    Playing $(basename "$WAV") (~84 s). Let it run to the end chirp, then STOP + REWIND the deck."
    afplay "$WAV"
    echo ">>> done playing. Stop the deck, rewind to the start, then run:  $0 capture"
    ;;
  capture)
    DUR="${2:-100}"   # >= 84 s master + generous slack for a manual PLAY start
    [ -f "$WAV" ] || { echo "missing $WAV"; exit 1; }
    mkdir -p "$HERE/captures"
    CAP="$HERE/captures/fullspectrum_$(date +%Y%m%d_%H%M%S).wav"
    echo ">>> CAPTURE phase: ${DUR}s -> ${CAP##*/}"
    echo "    Deck in PLAY (Dolby OFF). deck OUT -> UCA222 IN -> USB."
    echo "    Press PLAY on the deck NOW (capture warms up for 0.8 s first)."
    python3 "$HERE/capture_uca.py" "$DUR" "$CAP" &
    CAPPID=$!
    sleep 0.8
    if ! wait "$CAPPID"; then echo "capture FAILED (capture_uca.py exited non-zero) -- aborting"; exit 1; fi
    echo "--- GRADE: decode every rung on BOTH channels (auto) ---"
    python3 "$HERE/fullspectrum_decode.py" "$CAP" --channel auto
    echo
    echo "--- ACOUSTIC-CEILING check: same capture summed to mono (simulates a phone capture) ---"
    python3 "$HERE/fullspectrum_decode.py" "$CAP" --channel mono --out-tag "$(basename "${CAP%.wav}")_mono" || true
    echo ">>> capture saved: $CAP"
    echo ">>> Per-channel GRADE = highest byte-exact rung. Both channels at R3 (P21 RS159) => ~9820 bps stereo."
    ;;
  selftest)
    # Clean-master self-test (no tape): proves the master decodes byte-exact and the
    # summed-mono ceiling behaves honestly. Mirrors the build-time mandatory gate.
    [ -f "$WAV" ] || { echo "missing $WAV -- run: python3 fullspectrum_master.py"; exit 1; }
    echo "--- clean master, both channels (every rung must be byte-exact) ---"
    python3 "$HERE/fullspectrum_decode.py" "$WAV" --channel auto --out-tag selftest_clean
    echo
    echo "--- clean master summed to mono (R0-R2 byte-exact; R3 stereo-only EXPECTED to fail) ---"
    python3 "$HERE/fullspectrum_decode.py" "$WAV" --channel mono --out-tag selftest_summed_mono
    ;;
  *)
    echo "usage: $0 {record | capture [seconds] | selftest}"
    echo
    echo "  pre-flight (no tape):  ./loopback_check.sh   # deck RECORD-PAUSE, verify routing/level/clock"
    echo
    echo "  build the master first:  python3 fullspectrum_master.py"
    echo "    1) $0 record    # deck RECORD -- plays fullspectrum_master.wav to tape (~84 s)"
    echo "    2) stop + rewind the deck"
    echo "    3) $0 capture   # deck PLAY -- captures, then grades L + R + summed-mono ceiling"
    exit 1
    ;;
esac
