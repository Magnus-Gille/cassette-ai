#!/usr/bin/env bash
# Real-tape d2x STEREO proof — does the ~9820 bps stereo d2x rate survive a physical
# cassette? The electrical loopback proved it byte-exact with NO tape in the loop
# (crosstalk -56 dB). This runbook puts a real tape in the loop (wow/flutter/dropout)
# in TWO operator-gated phases:
#
#     ./d2x_tape_proof.sh record           # play master -> deck RECORD -> tape
#     (stop the deck, rewind to the start)
#     ./d2x_tape_proof.sh capture [secs]   # deck PLAY -> UCA222 -> capture, analyze, decode L+R
#
# WIRING (identical both phases — cables do not move, only the deck transport does):
#     Mac out (built-in 3.5mm headphone jack) -> RCA -> deck IN
#     deck OUT -> RCA -> UCA222 IN -> USB -> Mac
#   Mac DEFAULT OUTPUT must be the built-in headphone jack (System Settings > Sound).
#   Capture uses the UCA222 by name ("USB Audio CODEC") via PortAudio (capture_uca.py) —
#   NOT ffmpeg avfoundation (drops ~11.5% of samples on this machine).
#
# SOP (do not skip):
#   * Dolby NR OFF at BOTH record AND playback (companding mangles QAM/multitone).
#   * Record level ~7.0 — NOT 8.5 (8.5 saturates -> IMD floor blooms, kills dense carriers).
#   * Let the master run to the END chirp; ~1 s silence around the chirps = the sync anchors.
#   * The decoder self-syncs on the chirp pair, so arbitrary PLAY-timing slack is fine —
#     just press PLAY promptly so the whole master lands inside the capture window.
#
# PRE-FLIGHT (no tape, recommended before burning):
#     ./loopback_check.sh        # deck in RECORD-PAUSE (Dolby OFF) -> verify routing/level/clock
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WAV="$HERE/cal_d2x_stereo.wav"
SIDE="$HERE/cal_d2x_stereo.json"
CMD="${1:-}"

case "$CMD" in
  record)
    [ -f "$WAV" ] || { echo "missing $WAV — run: python3 make_d2x_stereo_cal.py"; exit 1; }
    echo ">>> RECORD phase"
    echo "    Checklist: blank tape loaded · Dolby NR OFF · record level ~7.0 · deck in RECORD (tape moving)."
    echo "    Mac default OUTPUT = built-in 3.5mm headphone jack (-> deck IN)."
    echo "    Playing $(basename "$WAV") (~297 s). Let it run to the end chirp, then STOP + REWIND the deck."
    afplay "$WAV"
    echo ">>> done playing. Stop the deck, rewind to the start, then run:  $0 capture"
    ;;
  capture)
    DUR="${2:-330}"   # >= 297.2 s master + generous slack for a manual PLAY start
    [ -f "$WAV" ] || { echo "missing $WAV"; exit 1; }
    mkdir -p "$HERE/captures"
    CAP="$HERE/captures/d2x_tape_$(date +%Y%m%d_%H%M%S).wav"
    echo ">>> CAPTURE phase: ${DUR}s -> ${CAP##*/}"
    echo "    Deck in PLAY (Dolby OFF). deck OUT -> UCA222 IN -> USB."
    echo "    Press PLAY on the deck NOW (capture warms up for 0.8 s first)."
    python3 "$HERE/capture_uca.py" "$DUR" "$CAP" &
    CAPPID=$!
    sleep 0.8
    if ! wait "$CAPPID"; then echo "capture FAILED (capture_uca.py exited non-zero) — aborting"; exit 1; fi
    echo "--- routing / crosstalk / clock (from front probes; informational) ---"
    python3 "$HERE/analyze_stereo_cal.py" "$CAP" --sidecar "$SIDE" || true
    echo "--- decode LEFT  (channel 0) ---"
    python3 "$HERE/decode_d2x_cal.py" "$CAP" --channel 0
    echo "--- decode RIGHT (channel 1) ---"
    python3 "$HERE/decode_d2x_cal.py" "$CAP" --channel 1
    echo ">>> capture saved: $CAP"
    echo ">>> 0 codeword failures on BOTH channels => ~9820 bps stereo d2x survives a real tape."
    ;;
  *)
    echo "usage: $0 {record | capture [seconds]}"
    echo
    echo "  pre-flight (no tape):  ./loopback_check.sh   # deck RECORD-PAUSE, verify routing/level/clock"
    echo "  1) $0 record    # deck RECORD — plays cal_d2x_stereo.wav to tape (~297 s)"
    echo "  2) stop + rewind the deck"
    echo "  3) $0 capture   # deck PLAY — captures, then decodes L + R"
    exit 1
    ;;
esac
