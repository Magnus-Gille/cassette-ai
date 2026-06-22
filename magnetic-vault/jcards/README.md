# Print-at-home J-cards — THE MAGNETIC VAULT

Generate a print-ready **cassette J-card** (the folded paper insert for a
standard Norelco case) for any release in the shop.

### Aesthetic: "MAGNETIC SPECIMEN"

Each cassette is documented like a **declassified technical record** crossed with
a premium **Type-IV metal-tape inlay** (think TDK MA-R / Maxell MX), Swiss
typographic rigour, and risograph print warmth. **Typography is the hero — there
is no pictogram.** The design language is:

- a **specimen catalogue number** motif (`MV-001 · MAGNETIC SPECIMEN No.001`) set
  small in mono, like a museum/lab tag;
- an **oversized, characterful title** in a high-contrast optical serif, set
  flush-left and asymmetric, kissing the panel edge, with a **risograph
  misregistration ghost** offset ~0.5 mm in the spot ink;
- the **real measured numbers** as a precise mono spec table with hairline rules
  and dotted leaders — *this is* the graphic, not decoration;
- **the one image = the tape's own data**: a real duotone spectrogram rendered
  from the master WAV (`spectrogram.py`) — *the art is the data*;
- **crop + registration marks** and a **paper-grain / riso** texture so it reads
  as a print artifact, not a flat vector.

**Type:** [Fraunces](https://fonts.google.com/specimen/Fraunces) (display serif,
optical `opsz` 144 / weight 900) + [Martian Mono](https://fonts.google.com/specimen/Martian+Mono)
(instrument-grade technical mono), both `@import`-ed from Google Fonts.

**Palette:** ferric duotone — warm near-black ink `#1a1714`, bone/cream paper
`#efe7d6`, and **one ferric oxide spot per release** (DOOM = oxide red-orange
`#c75e34`). Per-release, only the single spot colour varies.

```
jcards/
├── gen_jcard.py        # the generator (reads releases_data.json + template)
├── spectrogram.py      # renders the duotone hero spectrogram from a master WAV
├── art.py              # legacy icon system — kept ONLY for the website (relArt mirror);
│                       #   the J-cards no longer use it (typography is the hero)
├── releases_data.json  # the catalog (incl. DOOM's catalogue №, spot, measured spec)
├── out/<slug>.html     # one self-contained print-ready page per release
├── out/spectrogram_doom.png   # the DOOM hero spectrogram (embedded base64 in the card)
├── screenshots/        # rendered proofs (doom_v3.png = the current design)
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

### The hero spectrogram (the one image)

The cover's hero image is **the tape's own data made visible** — a duotone
spectrogram (ferric on charcoal) rendered straight from the release's master WAV
by `spectrogram.py`. It is computed with a scipy STFT and mapped through a
hand-built ink → spot → bone colour ramp (riso warmth, not a clinical
matplotlib look); the dense vertical striations are the modem's narrowband
carriers — literally the bits.

```bash
# regenerate the DOOM hero from the real master (48 kHz, ~42 min):
python3 spectrogram.py \
  ../../experiments/tape_v2/doom_ship/m10doom3_master.wav \
  out/spectrogram_doom.png --spot c75e34 --start 600 --dur 8 \
  --width 1400 --height 460 --fmax 18000
```

The PNG is embedded as a base64 data-URI so each card stays self-contained. The
spectrogram is **DOOM-specific** for now; other releases get a CSS-drawn carrier
band placeholder (flagged `SIGNAL TRACE · SPECTROGRAM PENDING`) until their own
master is processed and a `"spectrogram"` filename + `"spec"` block are added to
their `releases_data.json` entry.

### Per-release data

Everything the card needs is driven from `releases_data.json`:

- **`catalogue`** — the specimen № (DOOM = `MV-001`; others are auto-minted from
  catalog order, `MV-002`…).
- **`accent`** — the single ferric spot colour for that release.
- **`spec`** — the measured numbers (`GROSS / NET / SNR / FLUTTER / CODEWORDS /
  INTEGRITY / …`) that fill the technical-record table. DOOM carries the real
  measured values (`GROSS 7875 bps · NET 4910 bps · SNR 38.9 dB · FLUTTER 0.38 %
  · 9225 codewords · 0 failed · BYTE-EXACT`).
- **`spectrogram`** — the hero PNG filename (DOOM only, for now).

Per-tape **side A / side B** contents live in the `SIDE_CONTENT` dict at the top
of `gen_jcard.py` (with terse `*_short` variants for the dossier panel).

> `art.py` (the old monoline icon system) is **no longer used by the J-cards** —
> typography is now the hero. It is kept only because `assets/releases.js`
> (`relArt()`) mirrors it for the website thumbnails.

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

To re-verify after editing the template (the current design proof is
`screenshots/doom_v3.png`):

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --window-size=1123,794 --force-device-scale-factor=3 \
  --virtual-time-budget=9000 --screenshot="screenshots/doom_v3.png" "file://$PWD/out/doom.html"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="screenshots/doom_print.pdf" "file://$PWD/out/doom.html"
```

(1123 × 794 px = A4 landscape at 96 dpi; `--virtual-time-budget` lets the Google
Fonts + the embedded spectrogram settle before capture.)
