#!/usr/bin/env python3
"""
gen_jcard.py — PRINT-AT-HOME cassette J-card generator for THE MAGNETIC VAULT.

Reads the shop's release catalog (releases_data.json, extracted once from
../assets/releases.js) and emits ONE self-contained, print-ready HTML page per
release into out/<slug>.html. Each page is A4 LANDSCAPE (297x210 mm) and is
designed to be printed from a browser at 100% / ACTUAL SIZE.

A J-card is the folded paper insert for a standard Norelco cassette case. Flat,
left-to-right, it is:

    [ SPINE 12 mm ] [ FRONT cover 100 mm ] [ BACK flap 98 mm ]

all 63.5 mm tall (folding into a "J"). These physical dimensions are EXACT and
load-bearing: at home-print, the FRONT must measure 100 mm wide or the inlay
won't seat in the case. We render in real `mm` units with `@page { size: A4
landscape; margin: 0 }` so 100 mm renders as 100 mm.

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
# Standard Norelco compact-cassette case insert. The FRONT cover must be 100 mm
# wide and the whole card 63.5 mm tall to seat correctly.
SPINE_MM = 12.0      # the shelf-readable spine
FRONT_MM = 100.0     # the cover — MUST measure 100 mm on the printout
BACK_MM = 98.0       # the rear tuck-in flap
CARD_H_MM = 63.5     # full card height
CARD_W_MM = SPINE_MM + FRONT_MM + BACK_MM   # 210 mm flat

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
        spine_mm=SPINE_MM,
        front_mm=FRONT_MM,
        back_mm=BACK_MM,
        card_h=CARD_H_MM,
        card_w=CARD_W_MM,
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
# All dimensions in real mm. @page kills printer margins; the card is centred
# in the A4 printable area inside ~287x200 mm safe margins. Crop marks sit just
# outside the 4 corners; dashed fold lines separate spine|front and front|back.
# The "PRINT AT 100%" note + a 100 mm calibration ruler live in the page margin
# (outside the cut area) and are trimmed away with the offcut.
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

  /* A4 landscape sheet (297 x 210 mm). The card is centred inside the safe
     printable area; margin furniture lives in the outer band. */
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

  /* ---- the flat J-card, centred ------------------------------------- */
  .card-wrap {{
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    /* nudge up slightly so margin furniture has room */
    margin-top: -2mm;
  }}
  .card {{
    position: relative;
    width: {card_w}mm; height: {card_h}mm;
    display: flex; flex-direction: row;
    background: var(--paper);
    box-shadow: none;
  }}

  /* panels */
  .panel {{ position: relative; height: {card_h}mm; overflow: hidden; }}
  .spine {{ width: {spine_mm}mm; }}
  .front {{ width: {front_mm}mm; }}
  .back  {{ width: {back_mm}mm; }}

  /* ferric index-notch stripe down the very left edge (like a real inlay) */
  .card::before {{
    content:""; position:absolute; left:0; top:0; bottom:0; width:1.6mm; z-index:3;
    background: repeating-linear-gradient(180deg, var(--ferric) 0 3.4mm, var(--ferric-deep) 3.4mm 6.8mm);
    opacity:.92;
  }}

  /* ---- SPINE (vertical, shelf-readable) ----------------------------- */
  .spine {{
    background: var(--ink); color: var(--cream);
    display: flex; align-items: center; justify-content: center;
    border-right: .25mm solid var(--line);
  }}
  .spine .spine-txt {{
    writing-mode: vertical-rl; transform: rotate(180deg);
    white-space: nowrap; font-family: var(--mono);
    font-size: 3mm; letter-spacing: .22em; text-transform: uppercase;
    color: var(--cream); padding: 2mm 0;
  }}
  .spine .spine-txt b {{ color: var(--ferric); font-weight:700; }}
  .spine .spine-side {{ color: var(--ferric); }}

  /* ---- FRONT cover --------------------------------------------------- */
  .front {{
    background: var(--paper);
    display:flex; flex-direction:column;
    padding: 4.5mm 5mm 4mm;
    border-right: .25mm solid var(--line);
  }}
  .front .eyebrow {{
    font-family: var(--mono); font-size: 2.5mm; letter-spacing: .3em;
    text-transform: uppercase; color: var(--ferric-deep); margin: 0 0 2mm;
    display:flex; align-items:center; gap:2mm;
  }}
  .front .eyebrow .reel {{ width:4mm; height:4mm; flex:0 0 auto; }}
  .front .art {{
    width: 100%; height: 26mm; border:.25mm solid var(--line);
    border-left: 1.2mm solid var(--accent);
    overflow:hidden; margin: 0 0 3mm; background: var(--ink-2);
  }}
  .front .art svg {{ width:100%; height:100%; display:block; }}
  .front h1 {{
    font-family: var(--serif); font-weight:600;
    font-size: 8.5mm; line-height: 1.02; letter-spacing:-.01em;
    margin: 0 0 1.5mm; color: var(--ink);
  }}
  .front .flex {{
    font-family: var(--serif); font-style:italic; color: var(--rust);
    font-size: 3.3mm; line-height:1.25; margin: 0 0 auto;
  }}
  .front .tier {{
    align-self:flex-start; margin-top: 2.5mm;
    font-family: var(--mono); font-size: 2.3mm; font-weight:700;
    letter-spacing:.1em; text-transform:uppercase;
    color: var(--ferric-deep);
    border:.3mm solid rgba(201,122,38,.5); border-radius:1mm;
    padding: 1mm 2mm; display:inline-flex; align-items:center; gap:1.5mm;
  }}
  .front .tier .dot {{ width:1.6mm; height:1.6mm; border-radius:50%; background: currentColor; }}

  /* ---- BACK flap ----------------------------------------------------- */
  .back {{
    background: var(--cream);
    display:flex; flex-direction:column;
    padding: 3.5mm 4mm 3mm;
    gap: 1.6mm;
  }}
  .back .howto {{
    background: var(--ink); color: var(--cream);
    border-radius:1mm; padding: 2mm 2.6mm;
    display:flex; gap: 2.6mm; align-items:flex-start;
  }}
  .back .howto .qr-box {{ flex:0 0 auto; background:#fff; padding:.8mm;
    border-radius:.6mm; line-height:0; }}
  .back .howto .howtxt {{ flex:1; }}
  .back .howto h2 {{
    font-family: var(--mono); font-size:2.8mm; letter-spacing:.14em;
    text-transform:uppercase; color: var(--ferric); margin:0 0 1mm; font-weight:700;
  }}
  .back .howto p {{ margin:0; font-size: 2.4mm; line-height:1.4; color:#e7ddcc; }}
  .back .howto p b {{ color:#fff; }}
  .back .howto .url {{ color: var(--ferric); font-weight:700; }}

  .back .sides {{ display:flex; flex-direction:column; gap:1mm; }}
  .back .side {{
    display:flex; gap:2mm; font-size:2.35mm; line-height:1.35; color: var(--ink-soft);
    border-top:.25mm dotted var(--line); padding-top:1.2mm;
  }}
  .back .side .lab {{
    flex:0 0 auto; font-family: var(--mono); font-weight:700; color: var(--ink);
    letter-spacing:.06em;
  }}
  .back .side .lab b {{ color: var(--accent); }}

  .back .foot {{ margin-top:auto; }}
  .back .lic {{
    font-family: var(--mono); font-size:2.2mm; letter-spacing:.04em;
    color: var(--ink-soft); line-height:1.4; margin:1mm 0 0;
    border-top:.25mm solid var(--line); padding-top:1.4mm;
  }}
  .back .lic .badge {{
    font-weight:700; color: var(--ink); text-transform:uppercase; letter-spacing:.1em;
  }}
  .back .numbered {{
    font-family: var(--mono); font-size:2.3mm; color: var(--ink);
    margin-top:1.4mm; display:flex; align-items:center; gap:1.5mm;
    letter-spacing:.04em;
  }}
  .back .numbered .blank {{ display:inline-block; min-width:9mm;
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

  /* ---- dashed fold lines (spine|front and front|back) -------------- */
  .fold {{ position:absolute; top:0; bottom:0; width:0; z-index:4;
    border-left:.3mm dashed rgba(33,29,24,.55); }}
  .fold .lab {{ position:absolute; top:-4.4mm; left:50%; transform:translateX(-50%);
    font-size:2.1mm; letter-spacing:.18em; text-transform:uppercase;
    color: var(--ink-soft); }}
  .fold.f1 {{ left:{spine_mm}mm; }}
  .fold.f2 {{ left:calc({spine_mm}mm + {front_mm}mm); }}

  .qr-placeholder {{ border:.4mm solid var(--ink); display:flex;
    align-items:center; justify-content:center; font-size:3mm; font-weight:700;
    color: var(--ink); background:#fff; }}
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

  <!-- the flat J-card -->
  <div class="card-wrap">
    <!-- crop marks -->
    <span class="crop tl"></span><span class="crop tr"></span>
    <span class="crop bl"></span><span class="crop br"></span>
    <!-- fold lines -->
    <span class="fold f1"><span class="lab">fold</span></span>
    <span class="fold f2"><span class="lab">fold</span></span>

    <div class="card">
      <!-- SPINE -->
      <div class="panel spine">
        <div class="spine-txt"><b>{title}</b> &nbsp;·&nbsp; <span class="spine-side">side A</span></div>
      </div>

      <!-- FRONT cover -->
      <div class="panel front">
        <p class="eyebrow">
          <svg class="reel" viewBox="0 0 40 40" aria-hidden="true">
            <rect width="40" height="40" rx="7" fill="#211d18"/>
            <circle cx="14" cy="20" r="6.5" fill="none" stroke="#e6a24c" stroke-width="2"/><circle cx="14" cy="20" r="2" fill="#e6a24c"/>
            <circle cx="26" cy="20" r="6.5" fill="none" stroke="#e6a24c" stroke-width="2"/><circle cx="26" cy="20" r="2" fill="#e6a24c"/>
          </svg>
          The Magnetic Vault
        </p>
        <div class="art">{art_svg}</div>
        <h1>{title}</h1>
        <p class="flex">&ldquo;{flex}&rdquo;</p>
        <span class="tier"><span class="dot"></span>{tier}</span>
      </div>

      <!-- BACK flap -->
      <div class="panel back">
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
          <div class="side"><span class="lab"><b>A</b></span><span>{side_a}</span></div>
          <div class="side"><span class="lab"><b>B</b></span><span>{side_b}</span></div>
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
