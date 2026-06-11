#!/usr/bin/env python3
"""Measure the tape-payload size of an artifact (e.g. dist/doom_cassette.html).

The tape codec (experiments/tape_v2/h9_payload_codec.py) compresses with
lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME), so THAT number is the one
checked against the C60-side budget. lzma preset=9 (no EXTREME) is reported
too because the project ground-truth one-liner uses it; 9e is always <= 9.

Budgets (bytes, KiB-based: C60 side = 565 KiB at 2572 net bps minus sync):
    HARD CAP 530 KiB = 542,720 B | TARGET 500 KiB = 512,000 B | STRETCH 370 KiB = 378,880 B

NOTE: run with /usr/bin/python3 — the pyenv 3.10 build lacks the _lzma module.

Usage: /usr/bin/python3 measure_payload.py <file> [<file> ...]
"""
import lzma
import sys

HARD, TARGET, STRETCH = 530 * 1024, 500 * 1024, 370 * 1024


def measure(path: str) -> int:
    raw = open(path, "rb").read()
    l9 = len(lzma.compress(raw, preset=9))
    l9e = len(lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME))
    print(f"{path}")
    print(f"  raw                 : {len(raw):>9,} B  ({len(raw)/1024:.1f} KiB)")
    print(f"  lzma preset=9       : {l9:>9,} B  ({l9/1024:.1f} KiB)")
    print(f"  lzma preset=9|EXTREME: {l9e:>8,} B  ({l9e/1024:.1f} KiB)   <-- tape codec number")
    for name, lim in (("HARD CAP 530 KiB", HARD), ("TARGET 500 KiB", TARGET), ("STRETCH 370 KiB", STRETCH)):
        verdict = "PASS" if l9e <= lim else "FAIL"
        print(f"  {name:<20s}: {verdict}  (margin {lim - l9e:+,} B)")
    return 0 if l9e <= HARD else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(max(measure(p) for p in sys.argv[1:]))
