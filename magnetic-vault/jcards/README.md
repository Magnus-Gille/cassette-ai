# Print-at-home J-cards — THE MAGNETIC VAULT

Generate a print-ready **cassette J-card** (the folded paper insert for a
standard Norelco case) for any release in the shop. Each card reuses the
storefront's bespoke inline-SVG label art, palette, and type — so the printed
inlay matches the cards on the website.

```
jcards/
├── gen_jcard.py        # the generator (reads releases_data.json + template)
├── art.py              # the minimal abstract ICON SYSTEM (single source; mirror to relArt())
├── releases_data.json  # the catalog, extracted once from assets/releases.js
├── out/<slug>.html     # one self-contained print-ready page per release
├── screenshots/        # rendered proofs (doom_screen.png, doom_print.pdf,
│                       #   doom_icon_options.png, icon_system.png)
└── README.md
```

A J-card is **ONE strip** whose panels **stack top-to-bottom**. Every panel
shares the same **101.6 mm (4″) width** — the cassette's width. The card folds
into a "J" in cross-section. Flat, top → bottom (this is the **J-CARD +1**
format — one extra inside panel carries the decode block):

```
+------------------------------------+
|  FRONT COVER   101.6 × 63.5 mm     |  faces out the case front
+------------------------------------+  ── fold ① (cover ↔ spine)
|  SPINE         101.6 × 12.7 mm     |  narrow shelf-visible edge (title)
+------------------------------------+  ── fold ② (spine ↔ flap)
|  TUCK FLAP     101.6 × 25.4 mm     |  SHORT return — folds BEHIND the cover
+------------------------------------+  ── fold ③ (flap ↔ +1 inside)
|  +1 INSIDE     101.6 × 63.5 mm     |  decode block (HOW TO PLAY · QR · A/B)
+------------------------------------+

  whole flat card = 101.6 × 165.1 mm
```

The **front cover must measure 101.6 mm wide × 63.5 mm tall** on the printout or
the inlay won't seat in the case. The page is A4 **landscape** with
`@page { margin: 0 }` and real `mm` units throughout, so 101.6 mm renders as
101.6 mm at 100 % scale.

### The J fold (cross-section)

Folding the spine + flap so the short flap tucks **behind** the bottom of the
cover — and the spine becomes the narrow visible edge — is what makes the "J":

```
   side view, looking along the cassette's long edge:

        ┌──────────────────────┐
        │                      │   ← FRONT COVER (faces out, 63.5 mm)
        │        cover         │
        │                      │
        └──────────────────────┘
        ▏ spine (12.7 mm) — bends 90°, wraps the case edge
        ┌──────────────────────┐
        │   tuck flap (short)  │   ← folds BACK, tucked BEHIND the cover
        └──────────────────────┘       (this short hooked return = the "J")

   the +1 INSIDE panel (63.5 mm) folds out from behind the flap and
   carries the decode HOW-TO; it sits flat against the cover's back.
```

In profile the cover hangs down, the spine bends across the top edge of the
case, and the short flap hooks back underneath — a "J" lying on its side. The
+1 inside panel is the extra leaf that opens out to reveal the decode block.

---

## Generate a card

Requires Python 3.10+ and `segno` (pure-python QR, no other deps):

```bash
pip install segno          # for a scannable QR; without it you get a placeholder box
cd magnetic-vault/jcards

python3 gen_jcard.py            # generate every release -> out/*.html
python3 gen_jcard.py doom       # just the DOOM card -> out/doom.html
python3 gen_jcard.py willows console   # a subset
```

Valid slugs: `doom · deck-test · willows · console · grandmaster ·
great-library · svenska · modern-shelf` (the `id` of each release in
`releases_data.json`).

### Keeping the data in sync with the shop

`releases_data.json` was extracted once from `../assets/releases.js`. If you add
or edit a release there, re-extract it:

```bash
node -e 'const fs=require("fs");const s=fs.readFileSync("../assets/releases.js","utf8");
  const a=eval(s.match(/const RELEASES = (\[[\s\S]*?\n\];)/)[1].replace(/;$/,""));
  fs.writeFileSync("releases_data.json",JSON.stringify(a,null,2));'
```

The label art is a **minimal abstract icon system** in `art.py` — one clean
geometric glyph per release (monoline, ferric-amber on charcoal, lots of
negative space; see `screenshots/icon_system.png`). `art.py` is the **single
source** for the icon system and is structured to be **mirrored back into**
`relArt()` in `assets/releases.js` (same 200×200 viewBox, same maths) when the
storefront is updated to match. The DOOM mark has three abstract options
(`_doom_chevron` / `_doom_sigil` / `_doom_bolt`, see
`screenshots/doom_icon_options.png`); the chosen one is set by `DOOM_CHOICE` (the
**containment sigil** — a ring with an inscribed inverted triangle + dot).
Per-tape **side A / side B** contents live in the `SIDE_CONTENT` dict at the top
of `gen_jcard.py` — DOOM is filled in; add an entry for any other tape you want
bespoke side notes on (otherwise a sensible default is derived from the catalog
text).

---

## Print at home (the important part)

1. Open `out/<slug>.html` in a browser (Chrome/Safari/Firefox all work).
2. **Print** (⌘P / Ctrl-P).
3. Set: **Paper = A4**, **Orientation = Landscape**.
4. Set **Scale = 100 % / "Actual size"** — **NOT** "Fit to page" / "Shrink to
   fit". This is the single setting that matters. If your dialog only offers
   "Fit", look for a "Scale" / "Custom" field and type **100**.
5. Turn **off** any "headers and footers".
6. Ideally print on **cardstock, 200–250 gsm**, via the **manual / rear feed**
   tray (heavy stock jams the auto-feed on most home printers). Plain paper
   works for a proof.
7. Before cutting, **verify with a real ruler**: the calibration bar in the
   bottom margin must measure **exactly 100 mm** end to end. If it's short, your
   print scaled down — fix the scale setting and reprint. (The cover width is
   101.6 mm, so once the 100 mm ruler checks out, the card is right.)
8. **Cut** along the four corner **crop marks** (the card is 101.6 × 165.1 mm —
   a tall strip).
9. **Fold** on the **three** dashed **"fold"** lines, in order top → bottom:
   - **① cover ↔ spine** — bend so the spine turns 90° away from the cover.
   - **② spine ↔ flap** — bend again so the short flap turns to run parallel to
     the cover.
   - **③ flap ↔ +1 inside** — the +1 panel folds out to show the decode block.
10. **Assemble the "J"**: the spine wraps the **edge** of the case, the **short
    tuck flap folds in BEHIND the bottom of the cover** (that hooked short return
    is the "J"), and the **+1 inside panel** lies flat behind the cover, readable
    when you lift it out. Slide the whole thing into the Norelco case — cover
    behind the front window, spine showing on the shelf.

The "PRINT AT 100 %" note, the crop marks, the fold labels, and the 100 mm
ruler all sit **outside the cut line** and get trimmed away with the offcut.

### Future option: 2-up per sheet

An A4 landscape sheet (297 × 210 mm) is 297 mm wide, so it fits **two** of these
101.6-mm-wide card strips **side by side** (≈ 203 mm of card across 297 mm). A
`--2up` layout that drops two cards on one sheet (shared crop marks, one ruler)
is a planned addition to `gen_jcard.py` to halve cardstock use.

---

## Verifying a card was generated correctly

The DOOM card was rendered in headless Chrome and verified three ways:

- **DOM measurement** (rendered @96 dpi → mm): **cover = 101.6 × 63.5 mm**
  (exact), spine = 101.6 × 12.7 mm, tuck flap = 101.6 × 25.4 mm, +1 inside =
  101.6 × 63.5 mm — bands sum to **165.1 mm**; whole card = 101.6 × 165.1 mm;
  ruler = 99.998 mm. No panel overflows its box.
- **Print-to-PDF MediaBox**: 297.0 × 209.9 mm (A4 landscape, exact).
- **QR**: segno version-2 (25 × 25), encodes `https://cassette.gille.ai`, drawn
  inline with a 2-module quiet zone, ~16 × 16 mm.

To re-verify after editing the template:

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --window-size=1123,794 --force-device-scale-factor=2 \
  --screenshot="screenshots/doom_screen.png" "file://$PWD/out/doom.html"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="screenshots/doom_print.pdf" "file://$PWD/out/doom.html"
```

(1123 × 794 px = A4 landscape at 96 dpi.)
