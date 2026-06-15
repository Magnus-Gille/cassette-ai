# Print-at-home J-cards — THE MAGNETIC VAULT

Generate a print-ready **cassette J-card** (the folded paper insert for a
standard Norelco case) for any release in the shop. Each card reuses the
storefront's bespoke inline-SVG label art, palette, and type — so the printed
inlay matches the cards on the website.

```
jcards/
├── gen_jcard.py        # the generator (reads releases_data.json + template)
├── art.py              # faithful Python port of relArt() from assets/releases.js
├── releases_data.json  # the catalog, extracted once from assets/releases.js
├── out/<slug>.html     # one self-contained print-ready page per release
├── screenshots/        # rendered proofs (doom_screen.png, doom_print.pdf)
└── README.md
```

A J-card, laid flat, is three panels left-to-right that fold into a "J":

```
[ SPINE 12 mm ] [ FRONT cover 100 mm ] [ BACK flap 98 mm ]   — all 63.5 mm tall
```

The **front cover must measure 100 mm wide** on the printout or the inlay won't
seat in the case. The page is A4 **landscape** with `@page { margin: 0 }` and
real `mm` units throughout, so 100 mm renders as 100 mm at 100 % scale.

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

The label art lives in `art.py` (a mirror of `relArt()` in `releases.js`). If you
change a release's art in the JS, mirror that change in `art.py` so the printed
inlay still matches the site. Per-tape **side A / side B** contents live in the
`SIDE_CONTENT` dict at the top of `gen_jcard.py` — DOOM is filled in; add an
entry for any other tape you want bespoke side notes on (otherwise a sensible
default is derived from the catalog text).

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
   print scaled down — fix the scale setting and reprint. (The front cover is
   the same 100 mm, so once the ruler checks out, the cover is right.)
8. **Cut** along the four corner **crop marks** (the card is 210 × 63.5 mm).
9. **Fold** on the two dashed **"fold"** lines: spine ↔ front and front ↔ back.
10. **Tuck** it into the cassette case — front behind the window, the back flap
    folds in behind the cassette.

The "PRINT AT 100 %" note, the crop marks, the fold labels, and the 100 mm
ruler all sit **outside the cut line** and get trimmed away with the offcut.

### Future option: 2-up per sheet

An A4 landscape sheet (297 × 210 mm) easily fits **two** J-cards stacked
vertically (each is 63.5 mm tall, ≈ 140 mm of card in 210 mm). A `--2up` layout
that drops two cards on one sheet (shared crop marks, one ruler) is a planned
addition to `gen_jcard.py` to halve cardstock use.

---

## Verifying a card was generated correctly

The DOOM card was rendered in headless Chrome and verified three ways:

- **DOM measurement** (rendered @96 dpi → mm): front = **99.996 mm**, spine =
  11.997 mm, back = 97.999 mm, card = 209.996 × 63.500 mm, ruler = 99.996 mm.
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
