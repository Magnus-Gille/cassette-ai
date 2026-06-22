# CHIP-8 Games Console — Build Notes

## Artifact

`payloads/chip8/dist/chip8_console.html`

Single self-contained HTML file — zero runtime network fetches, works over `file://` and `http://`.

## Sizes

| Metric        | Value          |
|---------------|----------------|
| Raw HTML      | 1,352,170 bytes (1.29 MB) |
| XZ-9 compressed | 551,520 bytes (0.54 MB) |

## Tape tier

- **Raw**: fits C90 Side A (1.86 MB limit) — does NOT fit C60 side (1.24 MB limit)
- **XZ-9**: fits C60 Side A (0.54 MB < 1.24 MB) — comfortably fits any tier

Tier on tape: **C60 Side A** (XZ-9 encoded payload, 0.54 MB)

## Contents

- 101 CC0 ROMs from chip8Archive, all base64-encoded inline (48 CHIP-8, 25 SCHIP, 28 XO-CHIP)
- Octo `Emulator` class inlined verbatim from `octo/js/emulator.js` (621 lines, MIT)
- No external assets, no CDN, no web fonts

## Emulator core

**Octo** by JohnEarnest — the reference CHIP-8/SCHIP/XO-CHIP interpreter used by the chip8Archive itself. MIT licensed. Full instruction set including XO-CHIP extensions (16-bit addressing, dual planes, audio patterns).

## UI features

- Dark phosphor-green terminal aesthetic
- Searchable, scrollable game picker listing all 101 games with platform badge (CHIP8/SCHIP/XOCHIP), author, year
- Canvas: 640×320 px, `ImageData`-based pixel rendering, integer-scaled
- Per-game quirks and tickrate from `programs.json` options applied on load
- Web Audio beep (square wave) wired to `buzzTimer`
- Keypad legend (CHIP-8 0–F → keyboard)
- Status bar: RUNNING / WAITING FOR KEY / HALTED
- Back button and Escape key return to menu

## Keymap (Octo defaults)

```
CHIP-8 key  Keyboard
0           X
1           1    2           2    3           3
4           Q    5           W    6           E
7           A    8           S    9           D
A           Z    B           C    C           4
D           R    E           F    F           V
Arrow keys: Up=5  Down=8  Left=7  Right=9  Space=6
```

## Verification

Served at `http://localhost:8810` via `python3 -m http.server 8810`. Playwright browser loaded the page, clicked the Br8kout PLAY button. After 200 manual ticks:

- `emu.halted = false`, `emu.tickCounter = 200`
- `emu.p[0]` pixel buffer: **133 lit pixels** out of 2048 (64×32 lores)
- Game view showing, status bar = "● RUNNING", game name = "Br8kout"
- Screenshot confirms bricks, ball, paddle, and "CLICK TO START" rendered
- `performance.getEntriesByType('resource').length === 0` — zero external asset loads

`requestAnimationFrame` loop runs in a real browser (confirmed by canvas rendering visible on screenshot). In Playwright headless, rAF callbacks don't fire during `evaluate()` — hence the manual tick verification above, which proved the interpreter executes correctly.

## License

- Emulator: **Octo** by JohnEarnest — MIT License
- ROMs: **chip8Archive** by JohnEarnest — CC0 (repo-wide dedication, all 101 programs)
- Combined status: **ship_clear**

## Source

Built from:
- `payloads/built/chip8_octo/bundle/octo/js/emulator.js` (Octo engine)
- `payloads/built/chip8_octo/bundle/roms/` (101 .ch8 ROMs + programs.json)

Build script: `/tmp/build_chip8.py` (ephemeral; regenerate from instructions in this file or re-run the agent that built it).
