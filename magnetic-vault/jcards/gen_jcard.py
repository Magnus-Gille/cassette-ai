#!/usr/bin/env python3
"""
gen_jcard.py — PRINT-AT-HOME cassette J-card generator for THE MAGNETIC VAULT.

Reads the shop's release catalog (releases_data.json, extracted once from
../assets/releases.js) and emits ONE self-contained, print-ready HTML page per
release into out/<slug>.html. Each page is A4 LANDSCAPE (297x210 mm) and is
designed to be printed from a browser at 100% / ACTUAL SIZE.

A J-card is the folded paper insert for a standard Norelco cassette case. It is
ONE strip whose panels STACK along the short (vertical) edge — every panel
shares the same 101.6 mm (4") width (the cassette's width). Flat, top→bottom:

    +------------------------------------+
    |  FRONT COVER   101.6 x 63.5 mm     |  faces out the case front
    +------------------------------------+  <- fold (cover <-> spine)
    |  SPINE         101.6 x 12.7 mm     |  the narrow shelf-visible edge
    +------------------------------------+  <- fold (spine <-> flap)
    |  TUCK FLAP     101.6 x 25.4 mm     |  SHORT return, folds BEHIND cover
    +------------------------------------+
    |  +1 INSIDE     101.6 x 63.5 mm     |  decode block (J-CARD +1 panel)
    +------------------------------------+

The spine+flap fold so the short flap tucks BEHIND the bottom of the cover and
the spine becomes the narrow visible edge — that hooked short return is the "J".
The +1 inside panel (same size as the cover) folds out and carries the decode
HOW-TO / QR / sides / license, which won't fit on the 25.4 mm flap.

These physical dimensions are EXACT and load-bearing: at home-print, the cover
must measure 101.6 mm wide x 63.5 mm tall or the inlay won't seat in the case.
We render in real `mm` units with `@page { size: A4 landscape; margin: 0 }` so
101.6 mm renders as 101.6 mm.

Reuse: the bespoke inline-SVG label art is ported faithfully in art.py (mirror
of relArt() in releases.js); the palette / type come from the same design
system as assets/style.css (charcoal #211d18, cream #f4efe6, ferric #e6a24c,
Iowan/Palatino serif, monospace tape-label badges).

Usage:
    python3 gen_jcard.py              # generate every release
    python3 gen_jcard.py doom         # generate only doom.html
    python3 gen_jcard.py doom willows # generate a subset

Output: out/<slug>.html  (open -> Print -> A4 Landscape -> Scale 100%).
"""
import html
import json
import sys
from pathlib import Path

from art import rel_art

HERE = Path(__file__).resolve().parent
DATA = HERE / "releases_data.json"
OUT = HERE / "out"

QR_URL = "https://cassette.gille.ai"

# ---- physical J-card geometry (millimetres) --------------------------------
# Standard compact-cassette J-card. ONE strip; panels STACK along the SHORT
# (vertical) edge, every panel sharing the 101.6 mm (4") cover width. Verified
# standard dims (en.wikipedia.org/wiki/J-card; nationalaudiocompany /
# standardcassette templates). The cover must measure 101.6 x 63.5 mm to seat.
CARD_W_MM = 101.6        # shared width of every panel (4")  — load-bearing
COVER_H_MM = 63.5        # FRONT cover height (2.5")
SPINE_H_MM = 12.7        # SPINE height (0.5") — the narrow visible edge
FLAP_H_MM = 25.4         # TUCK flap height (1.0") — SHORT return, the J hook
INSIDE_H_MM = 63.5       # +1 INSIDE panel (decode block), same size as cover
# full flat card height (top -> bottom)
CARD_H_MM = COVER_H_MM + SPINE_H_MM + FLAP_H_MM + INSIDE_H_MM   # 165.1 mm
# vertical fold-line offsets from the top edge
FOLD1_MM = COVER_H_MM                          # cover <-> spine
FOLD2_MM = COVER_H_MM + SPINE_H_MM             # spine <-> flap
FOLD3_MM = COVER_H_MM + SPINE_H_MM + FLAP_H_MM  # flap <-> +1 inside panel

# ---- per-release side contents ---------------------------------------------
# The catalog (releases.js) describes the work; the tape's physical A/B side
# breakdown lives here. For everything but DOOM we fall back to a sensible
# default derived from the release. DOOM is the proven flagship.
SIDE_CONTENT = {
    "doom": {
        "a": "DOOM — the full game. Freedoom Episode 1 (all 9 maps), in-browser "
             "sound, saves, and THE MAGNETIC VAULT bonus level. Decoded byte-exact.",
        "b": "DECODED — a 9-track album mastered from the actual data-transfer "
             "signal, followed by the complete GPL source.",
        "attribution": "Freedoom assets (BSD) · DOOM source © id Software, GPLv2 "
                       "· bonus level by The Magnetic Vault.",
    },
}


def esc(s):
    return html.escape(s or "", quote=True)


def strip_tags(s):
    """Catalog `decodes`/`flex` carry a little inline <b> markup — keep the
    emphasis but render it safely as <b> (everything else is plain text)."""
    if not s:
        return ""
    # The catalog only ever uses <b>…</b>; preserve that, escape the rest.
    import re
    parts = re.split(r"(</?b>)", s)
    out = []
    for p in parts:
        if p in ("<b>", "</b>"):
            out.append(p)
        else:
            out.append(html.escape(p))
    return "".join(out)


def make_qr_svg(url, target_mm=16.0):
    """Inline SVG QR of `url`. Returns (svg_str, ok). Falls back to a bordered
    placeholder box if segno is unavailable."""
    try:
        import segno
    except ImportError:
        ph = (
            f'<div class="qr-placeholder" style="width:{target_mm}mm;height:{target_mm}mm">'
            f'<span>QR</span></div>'
        )
        return ph, False

    qr = segno.make(url, error="m")
    # Build a crisp, dependency-free inline SVG sized in mm. We draw the matrix
    # ourselves so the QR scales to exactly target_mm and inherits the ink colour.
    matrix = qr.matrix
    n = len(matrix)              # modules per side (includes quiet zone below)
    quiet = 2                    # quiet-zone modules each side (scanner margin)
    dim = n + 2 * quiet
    rects = []
    for r, row in enumerate(matrix):
        run_start = None
        for cprev in range(len(row) + 1):
            on = cprev < len(row) and row[cprev]
            if on and run_start is None:
                run_start = cprev
            elif not on and run_start is not None:
                rects.append(
                    f'<rect x="{run_start + quiet}" y="{r + quiet}" '
                    f'width="{cprev - run_start}" height="1"/>'
                )
                run_start = None
    body = "".join(rects)
    svg = (
        f'<svg class="qr" viewBox="0 0 {dim} {dim}" '
        f'style="width:{target_mm}mm;height:{target_mm}mm" '
        f'shape-rendering="crispEdges" role="img" aria-label="QR code to {esc(url)}">'
        f'<rect width="{dim}" height="{dim}" fill="#ffffff"/>'
        f'<g fill="#211d18">{body}</g></svg>'
    )
    return svg, True


def tier_label(r):
    return "Plays on any deck" if r.get("tier") == "today" else "Hi-fi setup"


def render(r, qr_svg, qr_ok):
    slug = r["id"]
    accent = r.get("accent") or "#e6a24c"
    title = r["title"]
    flex = r.get("flex", "")
    decodes = r.get("decodes", "")
    license_ = r.get("license", "")
    art_svg = rel_art(r.get("art"), accent)
    sides = SIDE_CONTENT.get(slug)

    side_a = sides["a"] if sides else f"{title} — {decodes}"
    side_b = sides["b"] if sides else "Continued / silence (single-side release)."
    attribution = (sides or {}).get(
        "attribution",
        f"Released under {license_}. Free-culture work, recorded by hand."
    )

    qr_note = "" if qr_ok else (
        '<p class="qr-fallback-note">QR placeholder — install <code>segno</code> '
        '(pip install segno) and regenerate for a scannable code.</p>'
    )

    return TEMPLATE.format(
        slug=esc(slug),
        title_attr=esc(title),
        accent=accent,
        card_w=CARD_W_MM,
        card_h=CARD_H_MM,
        cover_h=COVER_H_MM,
        spine_h=SPINE_H_MM,
        flap_h=FLAP_H_MM,
        inside_h=INSIDE_H_MM,
        fold1_mm=FOLD1_MM,
        fold2_mm=FOLD2_MM,
        fold3_mm=FOLD3_MM,
        art_svg=art_svg,
        title=esc(title),
        flex=strip_tags(flex),
        tier=esc(tier_label(r)),
        side_a=esc(side_a),
        side_b=esc(side_b),
        license=esc(license_),
        attribution=esc(attribution),
        qr_svg=qr_svg,
        qr_url=esc(QR_URL),
        qr_note=qr_note,
    )


# ---- the print-ready HTML/CSS template -------------------------------------
# All dimensions in real mm. @page kills printer margins; the card is centred in
# the A4 landscape printable area. The card is ONE vertical strip 101.6 mm wide
# x 165.1 mm tall: COVER | SPINE | TUCK FLAP | +1 INSIDE, stacked top->bottom.
# Crop marks sit just outside the 4 corners; THREE dashed fold lines separate
# the bands. The "PRINT AT 100%" note + a 100 mm calibration ruler live in the
# page margin (outside the cut area) and are trimmed away with the offcut.
TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>J-card · {title_attr} · The Magnetic Vault</title>
<style>
  :root {{
    --ink:#211d18; --ink-2:#2b2620; --ink-soft:#4a4339;
    --cream:#f4efe6; --paper:#efe7d6; --line:#ddd2bf;
    --ferric:#e6a24c; --ferric-deep:#c97a26; --rust:#8a5a2b; --brick:#c0492b;
    --accent:{accent};
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Hoefler Text",Georgia,serif;
    --mono:ui-monospace,"SF Mono","DejaVu Sans Mono",Menlo,Consolas,monospace;
  }}
  @page {{ size: A4 landscape; margin: 0; }}
  * {{ box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  html, body {{ margin: 0; padding: 0; background:#fff; color: var(--ink);
    font-family: var(--mono); }}

  /* A4 landscape sheet (297 x 210 mm). The tall card strip is centred inside
     the safe printable area; margin furniture lives in the outer band. */
  .sheet {{
    position: relative;
    width: 297mm; height: 210mm;
    margin: 0 auto;
    overflow: hidden;
  }}

  /* ---- margin furniture (trimmed away) ------------------------------- */
  .print-note {{
    position: absolute; top: 7mm; left: 0; right: 0;
    text-align: center; font-family: var(--mono);
    font-size: 3.6mm; letter-spacing: .12em; font-weight: 700;
    color: var(--brick); text-transform: uppercase;
  }}
  .print-note small {{ display:block; font-weight:400; font-size:2.6mm;
    letter-spacing:.04em; color: var(--ink-soft); text-transform:none; margin-top:1mm; }}

  /* 100 mm calibration ruler in the bottom margin */
  .ruler {{
    position: absolute; bottom: 8mm; left: 50%; transform: translateX(-50%);
    width: 100mm; height: 9mm;
  }}
  .ruler .bar {{ position:absolute; left:0; right:0; top:4mm; height:0;
    border-top: .35mm solid var(--ink); }}
  .ruler .tick {{ position:absolute; top:1.5mm; width:0; border-left:.3mm solid var(--ink); height:2.5mm; }}
  .ruler .tick.major {{ top:0.5mm; height:3.5mm; border-left:.4mm solid var(--ink); }}
  .ruler .cap {{ position:absolute; bottom:0; left:0; right:0; text-align:center;
    font-size:2.4mm; letter-spacing:.06em; color: var(--ink-soft); }}
  .ruler .endlabel {{ position:absolute; top:-3mm; font-size:2.4mm; color: var(--ink-soft); }}
  .ruler .endlabel.l {{ left:-1mm; }}
  .ruler .endlabel.r {{ right:-9mm; }}

  /* ---- the flat J-card strip, centred ------------------------------- */
  /* The card is ONE vertical strip: COVER | SPINE | FLAP | +1 INSIDE,
     stacked top->bottom, all {card_w}mm wide. */
  .card-wrap {{
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
  }}
  .card {{
    position: relative;
    width: {card_w}mm; height: {card_h}mm;
    display: flex; flex-direction: column;
    background: var(--paper);
    box-shadow: none;
  }}

  /* panels — stacked, full width */
  .panel {{ position: relative; width: {card_w}mm; overflow: hidden; }}
  .cover  {{ height: {cover_h}mm; }}
  .spine  {{ height: {spine_h}mm; }}
  .flap   {{ height: {flap_h}mm; }}
  .inside {{ height: {inside_h}mm; }}

  /* ferric index-notch stripe down the very left edge (like a real inlay) */
  .card::before {{
    content:""; position:absolute; left:0; top:0; bottom:0; width:1.6mm; z-index:3;
    background: repeating-linear-gradient(180deg, var(--ferric) 0 3.4mm, var(--ferric-deep) 3.4mm 6.8mm);
    opacity:.92;
  }}

  /* ---- COVER (front, faces out) ------------------------------------- */
  .cover {{
    background: var(--paper);
    display:flex; flex-direction:column;
    padding: 4mm 5mm 3.5mm 6mm;
    border-bottom: .25mm solid var(--line);
  }}
  .cover .eyebrow {{
    font-family: var(--mono); font-size: 2.5mm; letter-spacing: .28em;
    text-transform: uppercase; color: var(--ferric-deep); margin: 0 0 2mm;
    display:flex; align-items:center; gap:2mm;
  }}
  .cover .eyebrow .reel {{ width:4mm; height:4mm; flex:0 0 auto; }}
  .cover .body {{ display:flex; gap:4.5mm; align-items:flex-start; flex:1; min-height:0; }}
  .cover .art {{
    flex:0 0 auto; width: 30mm; height: 30mm;
    overflow:hidden; line-height:0;
  }}
  .cover .art svg {{ width:100%; height:100%; display:block; }}
  .cover .titlewrap {{ display:flex; flex-direction:column; flex:1; min-width:0; height:100%; }}
  .cover h1 {{
    font-family: var(--serif); font-weight:600;
    font-size: 9mm; line-height: 1.0; letter-spacing:-.01em;
    margin: 0 0 1.5mm; color: var(--ink);
  }}
  .cover .flex {{
    font-family: var(--serif); font-style:italic; color: var(--rust);
    font-size: 3.4mm; line-height:1.25; margin: 0 0 auto;
  }}
  .cover .tier {{
    align-self:flex-start; margin-top: 2mm;
    font-family: var(--mono); font-size: 2.3mm; font-weight:700;
    letter-spacing:.1em; text-transform:uppercase;
    color: var(--ferric-deep);
    border:.3mm solid rgba(201,122,38,.5); border-radius:1mm;
    padding: 1mm 2mm; display:inline-flex; align-items:center; gap:1.5mm;
  }}
  .cover .tier .dot {{ width:1.6mm; height:1.6mm; border-radius:50%; background: currentColor; }}

  /* ---- SPINE (the narrow shelf-visible edge, reads horizontally) ---- */
  .spine {{
    background: var(--ink); color: var(--cream);
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 5mm 0 6mm;
    border-bottom: .25mm solid var(--line);
  }}
  .spine .spine-txt {{
    white-space: nowrap; font-family: var(--mono);
    font-size: 3mm; letter-spacing: .2em; text-transform: uppercase;
    color: var(--cream);
  }}
  .spine .spine-txt b {{ color: var(--ferric); font-weight:700; }}
  .spine .spine-side {{ color: var(--ferric); }}

  /* ---- TUCK FLAP (short return — minimal tracklist line) ------------ */
  .flap {{
    background: var(--cream);
    display:flex; flex-direction:column; justify-content:center;
    padding: 2.5mm 5mm 2.5mm 6mm;
    border-bottom: .25mm dashed var(--line);
    gap: 1mm;
  }}
  .flap .flap-row {{
    display:flex; gap:2mm; font-size:2.3mm; line-height:1.25; color: var(--ink-soft);
  }}
  .flap .flap-row .lab {{
    flex:0 0 auto; font-family: var(--mono); font-weight:700; color: var(--ink);
    letter-spacing:.06em;
  }}
  .flap .flap-row .lab b {{ color: var(--accent); }}
  .flap .flap-row .v {{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}

  /* ---- +1 INSIDE panel (the decode block — folds out) --------------- */
  .inside {{
    background: var(--cream);
    display:flex; flex-direction:column;
    padding: 3mm 5mm 3mm 6mm;
    gap: 1.6mm;
  }}
  .inside .howto {{
    background: var(--ink); color: var(--cream);
    border-radius:1mm; padding: 2mm 2.6mm;
    display:flex; gap: 2.6mm; align-items:flex-start;
  }}
  .inside .howto .qr-box {{ flex:0 0 auto; background:#fff; padding:.7mm;
    border-radius:.6mm; line-height:0; }}
  .inside .howto .howtxt {{ flex:1; }}
  .inside .howto h2 {{
    font-family: var(--mono); font-size:2.7mm; letter-spacing:.14em;
    text-transform:uppercase; color: var(--ferric); margin:0 0 .8mm; font-weight:700;
  }}
  .inside .howto p {{ margin:0; font-size: 2.3mm; line-height:1.32; color:#e7ddcc; }}
  .inside .howto p b {{ color:#fff; }}
  .inside .howto .url {{ color: var(--ferric); font-weight:700; }}

  .inside .sides {{ display:flex; flex-direction:column; gap:.8mm; }}
  .inside .side {{
    display:flex; gap:2mm; font-size:2.2mm; line-height:1.28; color: var(--ink-soft);
    border-top:.25mm dotted var(--line); padding-top:1mm;
  }}
  .inside .side .lab {{
    flex:0 0 auto; font-family: var(--mono); font-weight:700; color: var(--ink);
    letter-spacing:.06em;
  }}
  .inside .side .lab b {{ color: var(--accent); }}

  .inside .foot {{ margin-top:auto; }}
  .inside .lic {{
    font-family: var(--mono); font-size:2.1mm; letter-spacing:.04em;
    color: var(--ink-soft); line-height:1.32; margin:.8mm 0 0;
    border-top:.25mm solid var(--line); padding-top:1.2mm;
  }}
  .inside .lic .badge {{
    font-weight:700; color: var(--ink); text-transform:uppercase; letter-spacing:.1em;
  }}
  .inside .numbered {{
    font-family: var(--mono); font-size:2.2mm; color: var(--ink);
    margin-top:1.2mm; display:flex; align-items:center; gap:1.5mm;
    letter-spacing:.04em;
  }}
  .inside .numbered .blank {{ display:inline-block; min-width:9mm;
    border-bottom:.3mm solid var(--ink); text-align:center; }}

  /* ---- crop marks (4 outer corners, just outside the card) ---------- */
  .crop {{ position:absolute; width:5mm; height:5mm; z-index:5; }}
  .crop::before, .crop::after {{ content:""; position:absolute; background: var(--ink); }}
  .crop::before {{ width:.25mm; height:4mm; }}
  .crop::after  {{ height:.25mm; width:4mm; }}
  /* gap of 1.5mm between mark and card corner */
  .crop.tl {{ left:-6.5mm; top:-6.5mm; }}
  .crop.tl::before {{ right:0; bottom:0; }} .crop.tl::after {{ right:0; bottom:0; }}
  .crop.tr {{ right:-6.5mm; top:-6.5mm; }}
  .crop.tr::before {{ left:0; bottom:0; }} .crop.tr::after {{ left:0; bottom:0; }}
  .crop.bl {{ left:-6.5mm; bottom:-6.5mm; }}
  .crop.bl::before {{ right:0; top:0; }} .crop.bl::after {{ right:0; top:0; }}
  .crop.br {{ right:-6.5mm; bottom:-6.5mm; }}
  .crop.br::before {{ left:0; top:0; }} .crop.br::after {{ left:0; top:0; }}

  /* ---- dashed fold lines (3 horizontal folds across the strip) ------ */
  .fold {{ position:absolute; left:0; right:0; height:0; z-index:4;
    border-top:.3mm dashed rgba(33,29,24,.55); }}
  .fold .lab {{ position:absolute; top:50%; left:-2mm; transform:translate(-100%,-50%);
    font-size:2.1mm; letter-spacing:.16em; text-transform:uppercase;
    color: var(--ink-soft); white-space:nowrap; }}
  .fold.f1 {{ top:{fold1_mm}mm; }}
  .fold.f2 {{ top:{fold2_mm}mm; }}
  .fold.f3 {{ top:{fold3_mm}mm; }}

  .qr-placeholder {{ border:.4mm solid var(--ink); display:flex;
    align-items:center; justify-content:center; font-size:3mm; font-weight:700;
    color: var(--ink); background:#fff; width:16mm; height:16mm; }}
  .qr-fallback-note {{ font-size:1.9mm; color: var(--brick); margin:1mm 0 0; }}

  /* screen-only convenience frame so it reads as a card on screen too */
  @media screen {{
    body {{ background:#cfc8ba; padding: 6mm 0; }}
    .sheet {{ background:#fff; box-shadow: 0 4mm 20mm rgba(0,0,0,.25); }}
    .card {{ box-shadow: 0 1mm 4mm rgba(0,0,0,.18); }}
  }}
</style>
</head>
<body>
<div class="sheet">

  <!-- margin furniture: trimmed away with the offcut -->
  <div class="print-note">
    PRINT AT 100% — ACTUAL SIZE · do not &lsquo;fit to page&rsquo;
    <small>A4 · Landscape · Scale 100% / Actual size · then verify the ruler below with a real ruler before cutting</small>
  </div>

  <!-- the flat J-card strip (top->bottom: cover | spine | flap | +1 inside) -->
  <div class="card-wrap">
    <!-- crop marks -->
    <span class="crop tl"></span><span class="crop tr"></span>
    <span class="crop bl"></span><span class="crop br"></span>
    <!-- fold lines -->
    <span class="fold f1"><span class="lab">fold ·&nbsp;cover</span></span>
    <span class="fold f2"><span class="lab">fold ·&nbsp;spine</span></span>
    <span class="fold f3"><span class="lab">fold ·&nbsp;flap</span></span>

    <div class="card">
      <!-- COVER (front, faces out) -->
      <div class="panel cover">
        <p class="eyebrow">
          <svg class="reel" viewBox="0 0 40 40" aria-hidden="true">
            <rect width="40" height="40" rx="7" fill="#211d18"/>
            <circle cx="14" cy="20" r="6.5" fill="none" stroke="#e6a24c" stroke-width="2"/><circle cx="14" cy="20" r="2" fill="#e6a24c"/>
            <circle cx="26" cy="20" r="6.5" fill="none" stroke="#e6a24c" stroke-width="2"/><circle cx="26" cy="20" r="2" fill="#e6a24c"/>
          </svg>
          The Magnetic Vault
        </p>
        <div class="body">
          <div class="art">{art_svg}</div>
          <div class="titlewrap">
            <h1>{title}</h1>
            <p class="flex">&ldquo;{flex}&rdquo;</p>
            <span class="tier"><span class="dot"></span>{tier}</span>
          </div>
        </div>
      </div>

      <!-- SPINE (narrow shelf-visible edge) -->
      <div class="panel spine">
        <span class="spine-txt"><b>{title}</b> &nbsp;·&nbsp; <span class="spine-side">SIDE A</span></span>
        <span class="spine-txt">THE MAGNETIC VAULT</span>
      </div>

      <!-- TUCK FLAP (short return — minimal tracklist) -->
      <div class="panel flap">
        <div class="flap-row"><span class="lab"><b>A</b></span><span class="v">{side_a}</span></div>
        <div class="flap-row"><span class="lab"><b>B</b></span><span class="v">{side_b}</span></div>
      </div>

      <!-- +1 INSIDE panel (the decode block — folds out) -->
      <div class="panel inside">
        <div class="howto">
          <div class="qr-box">{qr_svg}</div>
          <div class="howtxt">
            <h2>&#9654; How to play</h2>
            <p><b>This is DATA, not music.</b> Play the tape into a computer and
            decode it with the free app at <span class="url">{qr_url}</span> —
            scan the code, or type it in.</p>
          </div>
        </div>
        {qr_note}
        <div class="sides">
          <div class="side"><span class="lab"><b>SIDE A</b></span><span>{side_a}</span></div>
          <div class="side"><span class="lab"><b>SIDE B</b></span><span>{side_b}</span></div>
        </div>
        <div class="foot">
          <p class="lic"><span class="badge">{license}</span> · {attribution}</p>
          <p class="numbered">Hand-recorded &amp; decode-verified ·
            № <span class="blank">&nbsp;</span> / <span class="blank">&nbsp;</span></p>
        </div>
      </div>
    </div>
  </div>

  <!-- 100 mm calibration ruler (margin furniture) -->
  <div class="ruler">
    <div class="bar"></div>
    <span class="endlabel l">0</span><span class="endlabel r">100&nbsp;mm</span>
    <div class="cap">measure: should be exactly 100&nbsp;mm</div>
  </div>

</div>
<script>
  // draw ruler ticks every 10 mm (major) + 5 mm (minor)
  (function () {{
    var ruler = document.querySelector('.ruler');
    for (var mm = 0; mm <= 100; mm += 5) {{
      var t = document.createElement('span');
      t.className = 'tick' + (mm % 10 === 0 ? ' major' : '');
      t.style.left = mm + 'mm';
      ruler.appendChild(t);
    }}
  }})();
</script>
</body>
</html>
"""


def main(argv):
    releases = json.loads(DATA.read_text())
    by_id = {r["id"]: r for r in releases}

    wanted = argv[1:] if len(argv) > 1 else [r["id"] for r in releases]
    OUT.mkdir(parents=True, exist_ok=True)

    qr_svg, qr_ok = make_qr_svg(QR_URL)
    if not qr_ok:
        print("  ! segno not installed — QR rendered as placeholder box.", file=sys.stderr)

    written = []
    for slug in wanted:
        if slug not in by_id:
            print(f"  ! unknown release '{slug}' (have: {', '.join(by_id)})", file=sys.stderr)
            continue
        out_path = OUT / f"{slug}.html"
        out_path.write_text(render(by_id[slug], qr_svg, qr_ok))
        written.append(out_path)
        print(f"  + {out_path.relative_to(HERE.parent)}")

    print(f"\nGenerated {len(written)} J-card(s). QR: {'segno' if qr_ok else 'PLACEHOLDER'}.")
    print("Open one, Print -> A4 Landscape -> Scale 100% / Actual size, then check the ruler.")


if __name__ == "__main__":
    main(sys.argv)
