#!/usr/bin/env python3
"""play_album.py — a tiny terminal jukebox for the DECODED Side B album.

Listen back, skip around, and jot feedback per track without leaving the player.
macOS only (uses the built-in `afplay`). Tracks are t1.wav .. t9.wav next to this
script; feedback is appended to FEEDBACK.md in the same folder.

Controls:
    n / →     next track
    p / ←     previous track
    r         restart current track
    space     pause / resume
    f         write a feedback note for the current track (pauses while you type)
    l         reprint the tracklist
    q         quit

Run:  python3 experiments/tape_v2/bside_remix/sideB/play_album.py
"""
from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
# Optional: play an alternate album folder (e.g. the feedback render) via
#   play_album.py /path/to/alt
TRACK_DIR = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else HERE
FEEDBACK = os.path.join(TRACK_DIR, "FEEDBACK.md")

# (file, title, listed duration) — Side B, "DECODED"
TRACKS = [
    ("t1.wav", "Leader Tape",            "2:30"),
    ("t2.wav", "Pilot Tone",             "3:30"),
    ("t3.wav", "Wow & Flutter",          "3:20"),
    ("t4.wav", "Three Seventy-Five",     "3:44"),
    ("t5.wav", "Preamble",               "4:23"),
    ("t6.wav", "Byte-Exact",             "3:33"),
    ("t7.wav", "Reed-Solomon",           "3:16"),
    ("t8.wav", "Diffuse Reverb",         "3:40"),
    ("t9.wav", "End Chirp (for Fable)",  "3:00"),
]

RED = "\033[31m"; DIM = "\033[2m"; BOLD = "\033[1m"; GRN = "\033[32m"; RST = "\033[0m"
CLEAR = "\033[2J\033[H"


def banner(current: int, paused: bool, elapsed: int) -> str:
    out = [CLEAR]
    out.append(f"{BOLD}╔════════════════════════════════════════════════╗{RST}")
    out.append(f"{BOLD}║   DECODED — Side B  ·  music from the DOOM tape ║{RST}")
    out.append(f"{BOLD}║   every sound is the real data-transfer signal ║{RST}")
    out.append(f"{BOLD}╚════════════════════════════════════════════════╝{RST}")
    out.append("")
    for i, (_f, title, dur) in enumerate(TRACKS):
        if i == current:
            mark = f"{RED}▶{RST}"
            line = f" {mark} {BOLD}{i+1}. {title}{RST}"
        else:
            line = f"   {DIM}{i+1}. {title}{RST}"
        out.append(f"{line}{DIM}{'.' * max(2, 34 - len(title))}{dur}{RST}")
    out.append("")
    f, title, dur = TRACKS[current]
    state = f"{RED}❚❚ PAUSED{RST}" if paused else f"{GRN}▶ playing{RST}"
    el = f"{elapsed//60}:{elapsed%60:02d}"
    out.append(f"  now: {BOLD}{title}{RST}   [{state}{RST}]  {el} / {dur}")
    out.append("")
    out.append(f"  {DIM}n·→ next   p·← prev   r restart   space pause   "
               f"f feedback   l list   q quit{RST}")
    out.append(f"  {DIM}feedback → {FEEDBACK}{RST}")
    return "\n".join(out)


def read_key(timeout: float):
    """Return a key token or None on timeout. Maps arrow escapes to 'n'/'p'."""
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":  # escape sequence (arrow keys)
        seq = sys.stdin.read(2) if select.select([sys.stdin], [], [], 0.01)[0] else ""
        if seq == "[C":
            return "n"  # right
        if seq == "[D":
            return "p"  # left
        return None
    return ch


def get_feedback(title: str, saved_termios) -> None:
    """Drop to line mode, prompt for a note, append to FEEDBACK.md."""
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_termios)
    try:
        print(f"\n{BOLD}feedback for “{title}”{RST} (blank to cancel):")
        note = input("  > ").strip()
        if note:
            with open(FEEDBACK, "a") as fh:
                fh.write(f"\n### {title}\n_{datetime.now():%Y-%m-%d %H:%M}_\n\n{note}\n")
            print(f"  {GRN}saved.{RST}")
            time.sleep(0.5)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        tty.setcbreak(sys.stdin.fileno())


def main() -> int:
    afplay = shutil.which("afplay")
    if not afplay:
        print("afplay not found (this player is macOS-only).")
        return 1
    missing = [f for f, _, _ in TRACKS if not os.path.exists(os.path.join(TRACK_DIR, f))]
    if missing:
        print("missing track WAVs:", ", ".join(missing))
        print("regenerate them with the per-track t*.py scripts in this folder.")
        return 1

    if not os.path.exists(FEEDBACK):
        with open(FEEDBACK, "w") as fh:
            fh.write("# Side B — listening feedback\n\n"
                     "Notes per track, for tuning the next soundtrack.\n")

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    i = 0
    proc = None
    try:
        while 0 <= i < len(TRACKS):
            f, title, _dur = TRACKS[i]
            proc = subprocess.Popen([afplay, os.path.join(TRACK_DIR, f)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            t0 = time.time()
            paused = False
            pause_started = 0.0
            paused_total = 0.0
            sys.stdout.write(banner(i, paused, 0))
            sys.stdout.flush()
            action = None
            last_draw = -1
            while True:
                if not paused and proc.poll() is not None:
                    action = "next"  # finished naturally
                    break
                key = read_key(0.2)
                if key in ("n",):
                    action = "next"; break
                elif key in ("p",):
                    action = "prev"; break
                elif key == "r":
                    action = "restart"; break
                elif key == "q":
                    action = "quit"; break
                elif key == " ":
                    paused = not paused
                    if paused:
                        proc.send_signal(signal.SIGSTOP); pause_started = time.time()
                    else:
                        proc.send_signal(signal.SIGCONT); paused_total += time.time() - pause_started
                elif key == "f":
                    was_paused = paused
                    if not was_paused:
                        proc.send_signal(signal.SIGSTOP); pause_started = time.time()
                    get_feedback(title, saved)
                    if not was_paused:
                        proc.send_signal(signal.SIGCONT); paused_total += time.time() - pause_started
                    last_draw = -1  # force redraw
                elif key == "l":
                    last_draw = -1
                # redraw ~once a second (elapsed clock)
                elapsed = int(time.time() - t0 - paused_total - (time.time() - pause_started if paused else 0))
                if elapsed != last_draw:
                    sys.stdout.write(banner(i, paused, max(0, elapsed)))
                    sys.stdout.flush()
                    last_draw = elapsed
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
            if action == "next":
                i += 1
            elif action == "prev":
                i = max(0, i - 1)
            elif action == "restart":
                pass
            elif action == "quit":
                break
        else:
            sys.stdout.write(CLEAR + f"{BOLD}album finished.{RST}\n")
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        print(f"\n{DIM}feedback saved to {FEEDBACK}{RST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
