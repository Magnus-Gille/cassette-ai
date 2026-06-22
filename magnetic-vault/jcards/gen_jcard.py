#!/usr/bin/env python3
"""
gen_jcard.py — PRINT-AT-HOME cassette J-card generator for THE MAGNETIC VAULT.

Aesthetic: "MAGNETIC SPECIMEN" — each cassette is documented like a DECLASSIFIED
TECHNICAL RECORD crossed with a premium Type-IV metal-tape inlay (TDK MA-R /
Maxell MX), Swiss typographic rigour, and risograph print warmth. TYPOGRAPHY IS
THE HERO; there is no pictogram. The only image is the tape's OWN DATA made
visible — a real duotone spectrogram of the master signal (see spectrogram.py).

Design language:
  * a SPECIMEN CATALOGUE NUMBER motif ("MV-001 · MAGNETIC SPECIMEN No.001"),
    set small in mono like a museum/lab tag.
  * an oversized, characterful TYPOGRAPHIC title cropped by the panel edge —
    flush-left, asymmetric, with a riso misregistration shadow in the spot ink.
  * the REAL measured numbers as a precise mono spec table with hairline rules —
    this IS the graphic, not decoration.
  * crop + registration marks as intentional dossier furniture.
  * paper grain + a faint riso misregistration offset on one spot element.

Type: Fraunces (high-contrast optical serif, the display hero) + Martian Mono
(instrument-grade technical mono), both from Google Fonts. Palette: ferric
duotone — warm near-black ink, bone/cream paper, ONE ferric oxide spot per
release (DOOM = oxide red-orange #c75e34).

Reads the shop's release catalog (releases_data.json) and emits ONE
self-contained, print-ready HTML page per release into out/<slug>.html. Each page
is A4 LANDSCAPE (297x210 mm) and is designed to be printed at 100% / ACTUAL SIZE.

A J-card is the folded paper insert for a standard Norelco cassette case — ONE
strip whose panels STACK along the short (vertical) edge, every panel sharing the
101.6 mm (4") cassette width. Flat, top->bottom:

    +------------------------------------+
    |  FRONT COVER   101.6 x 63.5 mm     |  faces out the case front
    +------------------------------------+  <- fold (cover <-> spine)
    |  SPINE         101.6 x 12.7 mm     |  the narrow shelf-visible edge
    +------------------------------------+  <- fold (spine <-> flap)
    |  TUCK FLAP     101.6 x 25.4 mm     |  SHORT return, folds BEHIND cover
    +------------------------------------+
    |  +1 INSIDE     101.6 x 63.5 mm     |  decode block (J-CARD +1 panel)
    +------------------------------------+

These physical dimensions are EXACT and load-bearing: at home-print the cover
must measure 101.6 mm wide x 63.5 mm tall or the inlay won't seat. We render in
real `mm` units with `@page { size: A4 landscape; margin: 0 }`.

The hero spectrogram is DOOM-specific (rendered from the real master WAV via
spectrogram.py). Other releases get a placeholder band until their master is
processed; everything else (catalogue number, spot colour, spec table) is driven
from releases_data.json so the system stays reusable.

Usage:
    python3 gen_jcard.py              # generate every release
    python3 gen_jcard.py doom         # generate only doom.html
    python3 gen_jcard.py doom willows # generate a subset
"""
import base64
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "releases_data.json"
OUT = HERE / "out"

QR_URL = "https://cassette.gille.ai"

# ---- physical J-card geometry (millimetres) — LOAD-BEARING, DO NOT CHANGE ---
# Standard compact-cassette J-card. ONE strip; panels STACK along the SHORT
# (vertical) edge, every panel sharing the 101.6 mm (4") cover width. The cover
# must measure 101.6 x 63.5 mm to seat in a Norelco case.
CARD_W_MM = 101.6        # shared width of every panel (4")  — load-bearing
COVER_H_MM = 63.5        # FRONT cover height (2.5")
SPINE_H_MM = 12.7        # SPINE height (0.5") — the narrow visible edge
FLAP_H_MM = 25.4         # TUCK flap height (1.0") — SHORT return, the J hook
INSIDE_H_MM = 63.5       # +1 INSIDE panel (decode block), same size as cover
CARD_H_MM = COVER_H_MM + SPINE_H_MM + FLAP_H_MM + INSIDE_H_MM   # 165.1 mm
# vertical fold-line offsets from the top edge
FOLD1_MM = COVER_H_MM                           # cover <-> spine
FOLD2_MM = COVER_H_MM + SPINE_H_MM              # spine <-> flap
FOLD3_MM = COVER_H_MM + SPINE_H_MM + FLAP_H_MM  # flap <-> +1 inside panel

# ---- per-release side contents ---------------------------------------------
SIDE_CONTENT = {
    "doom": {
        "a": "The full game. Freedoom Episode 1 (all 9 maps), in-browser sound, "
             "saves, and THE MAGNETIC VAULT bonus level. Decoded byte-exact.",
        "b": "DECODED — a 9-track album mastered from the actual data-transfer "
             "signal, followed by the complete GPL source.",
        "a_short": "DOOM — game, sound, saves + bonus level",
        "b_short": "DECODED — 9-track album + GPL source",
        "attribution": "Freedoom (BSD) · DOOM source © id Software, GPLv2.",
    },
}

# Default specimen spec block for releases without measured numbers yet.
DEFAULT_SPEC = {
    "FORMAT": "BFSK · CAS3",
    "GROSS": "—",
    "NET": "—",
    "SNR": "—",
    "FLUTTER": "—",
    "CODEWORDS": "—",
    "INTEGRITY": "—",
}


def esc(s):
    return html.escape(s or "", quote=True)


def strip_tags(s):
    """Catalog `decodes`/`flex` carry inline <b> markup — keep the emphasis."""
    if not s:
        return ""
    import re
    parts = re.split(r"(</?b>)", s)
    out = []
    for p in parts:
        out.append(p if p in ("<b>", "</b>") else html.escape(p))
    return "".join(out)


def make_qr_svg(url, target_mm=15.0, ink="#1a1714"):
    """Inline SVG QR of `url`. Returns (svg_str, ok). Placeholder if no segno."""
    try:
        import segno
    except ImportError:
        ph = (
            f'<div class="qr-placeholder" style="width:{target_mm}mm;height:{target_mm}mm">'
            f'<span>QR</span></div>'
        )
        return ph, False

    qr = segno.make(url, error="m")
    matrix = qr.matrix
    n = len(matrix)
    quiet = 2
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
        f'<rect width="{dim}" height="{dim}" fill="#efe7d6"/>'
        f'<g fill="{ink}">{body}</g></svg>'
    )
    return svg, True


def embed_spectrogram(slug, r):
    """Return (img_html, ok). Embeds the release's duotone spectrogram PNG as a
    base64 data URI so the card is fully self-contained. DOOM-specific for now;
    other releases get a CSS-drawn carrier-band placeholder."""
    fname = r.get("spectrogram")
    if fname:
        p = OUT / fname
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            return (
                f'<img class="spectro-img" '
                f'src="data:image/png;base64,{b64}" '
                f'alt="Duotone spectrogram of the {esc(r["title"])} master signal — '
                f'the data made visible." draggable="false">'
            ), True
    # placeholder: a CSS striation band so the layout still composes
    return ('<div class="spectro-img spectro-ph" aria-hidden="true"></div>'), False


def tier_label(r):
    return "PLAYS ON ANY DECK" if r.get("tier") == "today" else "HI-FI SETUP REQ."


def catalogue_no(r, idx=None):
    """Specimen catalogue number. An explicit `catalogue` in the data wins
    (DOOM = MV-001, the proven flagship); otherwise we mint one from the
    release's position in the catalog so the whole series is numbered."""
    if r.get("catalogue"):
        return r["catalogue"]
    n = (idx + 1) if idx is not None else 0
    return f"MV-{n:03d}"


def spec_rows(r):
    """The measured-numbers spec table — the dossier's graphic core."""
    spec = r.get("spec") or DEFAULT_SPEC
    # ordered, with verified/runtime pulled out for the footer note
    order = ["FORMAT", "GROSS", "NET", "SNR", "FLUTTER", "CODEWORDS",
             "INTEGRITY", "RUNTIME", "MEDIUM"]
    rows = []
    for k in order:
        if k in spec:
            v = spec[k]
            integ = ' data-ok="1"' if (k == "INTEGRITY" and "EXACT" in str(v)) else ""
            rows.append(
                f'<div class="spec-row"{integ}>'
                f'<span class="spec-k">{esc(k)}</span>'
                f'<span class="spec-dots" aria-hidden="true"></span>'
                f'<span class="spec-v">{esc(str(v))}</span></div>'
            )
    return "".join(rows)


def render(r, qr_svg, qr_ok, idx=None):
    slug = r["id"]
    accent = r.get("accent") or "#c75e34"
    title = r["title"]
    flex = r.get("flex", "")
    license_ = r.get("license", "")
    sides = SIDE_CONTENT.get(slug)
    spec = r.get("spec") or {}

    side_a = sides["a"] if sides else f"{title} — {strip_tags(r.get('decodes',''))}"
    side_b = sides["b"] if sides else "Continued / silence (single-side release)."
    side_a_short = (sides or {}).get("a_short", side_a)
    side_b_short = (sides or {}).get("b_short", side_b)
    attribution = (sides or {}).get(
        "attribution",
        f"Released under {license_}. Free-culture work, recorded by hand."
    )

    spectro_html, spectro_ok = embed_spectrogram(slug, r)

    verified = spec.get("VERIFIED", "hand-recorded & decode-verified")
    runtime = spec.get("RUNTIME", "")

    # specimen number from catalogue ("MV-001" -> "No.001")
    cat = catalogue_no(r, idx)
    num = cat.split("-")[-1] if "-" in cat else "—"
    specimen_no = f"No.{num}"
    # the hero annotation: real-WAV releases say "as recorded"; placeholders flag it
    if spectro_ok:
        spectro_caption = f"THE SOUND OF {title.upper()}, AS RECORDED"
    else:
        spectro_caption = "SIGNAL TRACE · SPECTROGRAM PENDING"

    # Title may be long (e.g. "Den svenska samlingen"); the cover sizes the
    # display face to roughly fit, cropping is intentional for short titles.
    title_class = "t-short" if len(title) <= 6 else ("t-mid" if len(title) <= 14 else "t-long")

    qr_note = "" if qr_ok else (
        '<p class="qr-fallback-note">QR placeholder — install <code>segno</code> '
        'and regenerate for a scannable code.</p>'
    )

    return TEMPLATE.format(
        slug=esc(slug),
        title_attr=esc(title),
        accent=accent,
        card_w=CARD_W_MM, card_h=CARD_H_MM,
        cover_h=COVER_H_MM, spine_h=SPINE_H_MM,
        flap_h=FLAP_H_MM, inside_h=INSIDE_H_MM,
        fold1_mm=FOLD1_MM, fold2_mm=FOLD2_MM, fold3_mm=FOLD3_MM,
        catalogue=esc(cat),
        specimen_no=esc(specimen_no),
        spectro_caption=esc(spectro_caption),
        spectro_html=spectro_html,
        title=esc(title), title_class=title_class,
        flex=strip_tags(flex),
        tier=esc(tier_label(r)),
        spec_rows=spec_rows(r),
        verified=esc(verified),
        runtime=esc(runtime),
        side_a=esc(side_a), side_b=esc(side_b),
        side_a_short=esc(side_a_short), side_b_short=esc(side_b_short),
        license=esc(license_),
        attribution=esc(attribution),
        qr_svg=qr_svg, qr_url=esc(QR_URL), qr_note=qr_note,
    )


# ---- the print-ready HTML/CSS template -------------------------------------
# All dimensions in real mm. @page kills printer margins; the card is centred in
# the A4 landscape printable area. ONE vertical strip 101.6 mm wide x 165.1 mm
# tall: COVER | SPINE | TUCK FLAP | +1 INSIDE. Crop + registration marks sit
# just outside the corners; THREE dashed fold lines separate the bands. The
# "PRINT AT 100%" note + a 100 mm calibration ruler live in the page margin.
TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SPECIMEN {catalogue} · {title_attr} · The Magnetic Vault</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,900;1,9..144,400;1,9..144,500&family=Martian+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:#1a1714;            /* warm near-black printer's ink              */
    --ink-2:#2a241d;
    --ink-soft:#6b5f4f;
    --paper:#efe7d6;          /* bone / cream paper                         */
    --paper-2:#e7dcc6;
    --cream:#f4efe6;
    --line:#1a1714;           /* hairline ink                               */
    --hair:rgba(26,23,20,.42);/* hairline rules, low weight                 */
    --hair-soft:rgba(26,23,20,.22);
    --spot:{accent};          /* the ONE ferric oxide spot (per release)    */
    --ferric:#c75e34;
    --display:"Fraunces","Iowan Old Style",Palatino,Georgia,serif;
    --mono:"Martian Mono",ui-monospace,"SF Mono",Menlo,monospace;
  }}
  @page {{ size: A4 landscape; margin: 0; }}
  * {{ box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  html, body {{ margin:0; padding:0; background:#fff; color:var(--ink); font-family:var(--mono); }}

  .sheet {{ position:relative; width:297mm; height:210mm; margin:0 auto; overflow:hidden; }}

  /* ---- margin furniture (trimmed away with the offcut) --------------- */
  .print-note {{
    position:absolute; top:6mm; left:0; right:0; text-align:center;
    font-family:var(--mono); font-size:3.1mm; letter-spacing:.22em; font-weight:600;
    color:var(--ferric); text-transform:uppercase;
  }}
  .print-note small {{ display:block; font-weight:300; font-size:2.4mm;
    letter-spacing:.06em; color:var(--ink-soft); text-transform:none; margin-top:1.1mm; }}

  .ruler {{ position:absolute; bottom:7mm; left:50%; transform:translateX(-50%);
    width:100mm; height:9mm; }}
  .ruler .bar {{ position:absolute; left:0; right:0; top:4mm; height:0; border-top:.35mm solid var(--ink); }}
  .ruler .tick {{ position:absolute; top:1.5mm; width:0; border-left:.3mm solid var(--ink); height:2.5mm; }}
  .ruler .tick.major {{ top:.5mm; height:3.5mm; border-left:.4mm solid var(--ink); }}
  .ruler .cap {{ position:absolute; bottom:0; left:0; right:0; text-align:center;
    font-family:var(--mono); font-size:2.2mm; letter-spacing:.1em; color:var(--ink-soft); }}
  .ruler .endlabel {{ position:absolute; top:-3mm; font-family:var(--mono); font-size:2.2mm; color:var(--ink-soft); }}
  .ruler .endlabel.l {{ left:-1mm; }} .ruler .endlabel.r {{ right:-12mm; }}

  /* ---- the flat J-card strip, centred ------------------------------- */
  .card-wrap {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); }}
  .card {{
    position:relative; width:{card_w}mm; height:{card_h}mm;
    display:flex; flex-direction:column; background:var(--paper);
  }}
  /* paper grain — a faint multi-tone noise over the whole card, riso warmth */
  .card::after {{
    content:""; position:absolute; inset:0; z-index:6; pointer-events:none;
    opacity:.5; mix-blend-mode:multiply;
    background-image:
      url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='120' height='120' filter='url(%23n)' opacity='0.55'/></svg>");
    background-size:34mm 34mm;
  }}

  .panel {{ position:relative; width:{card_w}mm; overflow:hidden; }}
  .cover  {{ height:{cover_h}mm; }}
  .spine  {{ height:{spine_h}mm; }}
  .flap   {{ height:{flap_h}mm; }}
  .inside {{ height:{inside_h}mm; }}

  /* ================= COVER (front, faces out) ======================== */
  .cover {{ background:var(--paper); display:flex; flex-direction:column; }}

  /* HERO: the tape's own data, full-bleed band across the cover top */
  .spectro {{ position:relative; width:{card_w}mm; height:22.5mm; overflow:hidden;
    background:var(--ink); border-bottom:.5mm solid var(--spot); }}
  .spectro-img {{ position:absolute; inset:0; width:100%; height:100%;
    object-fit:cover; display:block; image-rendering:auto; }}
  .spectro-ph {{ background:
      repeating-linear-gradient(0deg, var(--ink) 0 .5mm, #2a2018 .5mm 1mm),
      repeating-linear-gradient(90deg, transparent 0 1.2mm, rgba(199,94,52,.5) 1.2mm 1.4mm);
  }}
  /* faint annotation laid over the hero, in mono — "the art is the data" */
  .spectro .anno {{ position:absolute; z-index:2; font-family:var(--mono);
    color:rgba(244,239,230,.62); font-weight:300; pointer-events:none;
    text-transform:uppercase; }}
  .spectro .anno.f-hi {{ top:1.2mm; left:2mm; font-size:1.9mm; letter-spacing:.14em; }}
  .spectro .anno.f-lo {{ bottom:1.2mm; left:2mm; font-size:1.9mm; letter-spacing:.14em; }}
  .spectro .anno.cap {{ bottom:1.2mm; right:2.5mm; font-size:1.9mm; letter-spacing:.18em;
    color:rgba(199,94,52,.92); font-weight:500; }}
  .spectro .axis {{ position:absolute; left:0; top:0; bottom:0; width:7mm; z-index:1;
    background:linear-gradient(90deg, rgba(26,23,20,.78), transparent); }}

  /* the title block: flush-left, oversized, asymmetric, cropped */
  .cover .meat {{ flex:1; position:relative; display:flex; flex-direction:column;
    padding:2.3mm 5mm 2.2mm 5.5mm; min-height:0; }}

  .speclabel {{ display:flex; align-items:baseline; gap:2.4mm;
    font-family:var(--mono); font-size:2.05mm; letter-spacing:.16em;
    text-transform:uppercase; color:var(--ink); font-weight:500; }}
  .speclabel .catno {{ color:var(--spot); font-weight:700; }}
  .speclabel .dim {{ color:var(--ink-soft); font-weight:300; letter-spacing:.1em; }}

  /* big characterful title, OVERSIZED and cropped by the right panel edge;
     the title overruns the right padding so the panel's overflow:hidden clips
     the last glyph — intentional, dossier-stamp asymmetry. */
  .cover .titlewrap {{ position:relative; margin:.3mm -5mm 0 0; line-height:0; }}
  .cover h1 {{
    font-family:var(--display); font-weight:900;
    font-variation-settings:"opsz" 144, "SOFT" 0, "WONK" 0;
    margin:0; color:var(--ink); line-height:.84; letter-spacing:-.026em;
    white-space:nowrap; position:relative; z-index:2;
  }}
  .cover h1.t-short {{ font-size:25.5mm; }}
  .cover h1.t-mid   {{ font-size:14mm; }}
  .cover h1.t-long  {{ font-size:8.6mm; letter-spacing:-.018em; white-space:normal; line-height:.92; margin-right:5mm; }}
  /* the riso misregistration: a spot-ink ghost of the title, offset 0.45mm */
  .cover .titlewrap .ghost {{
    position:absolute; left:0; top:0; z-index:1;
    font-family:var(--display); font-weight:900;
    font-variation-settings:"opsz" 144;
    margin:0; line-height:.84; letter-spacing:-.026em; white-space:nowrap;
    color:var(--spot); opacity:.88;
    transform:translate(.5mm,.46mm);
    -webkit-text-fill-color:var(--spot);
  }}
  .cover .titlewrap .ghost.t-short {{ font-size:25.5mm; }}
  .cover .titlewrap .ghost.t-mid   {{ font-size:14mm; }}
  .cover .titlewrap .ghost.t-long  {{ font-size:8.6mm; letter-spacing:-.018em; white-space:normal; line-height:.92; }}

  .cover .flex {{
    font-family:var(--display); font-style:italic; font-weight:400;
    font-size:3.5mm; line-height:1.08; color:var(--ink-2); margin:1.3mm 0 0;
    max-width:80mm;
  }}

  .cover .footrow {{ margin-top:auto; display:flex; align-items:flex-end;
    justify-content:space-between; gap:3mm; padding-top:1.4mm;
    border-top:.3mm solid var(--hair); }}
  .cover .footrow .strap {{ font-family:var(--mono); font-size:1.85mm;
    letter-spacing:.12em; text-transform:uppercase; color:var(--ink-soft);
    font-weight:400; line-height:1.45; padding-top:1.2mm; }}
  .cover .footrow .strap b {{ color:var(--ink); font-weight:600; }}
  .cover .tier {{ flex:0 0 auto; font-family:var(--mono); font-size:1.95mm;
    font-weight:600; letter-spacing:.1em; text-transform:uppercase; color:var(--spot);
    border:.3mm solid var(--spot); padding:.9mm 1.8mm; white-space:nowrap; }}

  /* ================= SPINE (narrow shelf-visible edge) =============== */
  .spine {{ background:var(--ink); color:var(--cream);
    display:flex; align-items:center; justify-content:space-between;
    padding:0 4.5mm 0 5.5mm; }}
  .spine .l {{ font-family:var(--mono); font-size:2.5mm; letter-spacing:.14em;
    text-transform:uppercase; white-space:nowrap; font-weight:500; }}
  .spine .l .catno {{ color:var(--spot); font-weight:700; }}
  .spine .l .ttl {{ font-family:var(--display); font-weight:600; letter-spacing:.01em;
    text-transform:none; font-size:2.9mm; }}
  .spine .r {{ font-family:var(--mono); font-size:2.05mm; letter-spacing:.24em;
    text-transform:uppercase; color:rgba(244,239,230,.72); font-weight:300; white-space:nowrap; }}

  /* ================= TUCK FLAP (specimen classification) ============= */
  .flap {{ background:var(--paper-2); display:flex; flex-direction:column;
    justify-content:center; padding:2mm 5.5mm; gap:1.1mm;
    border-bottom:.3mm dashed var(--hair); }}
  .flap .clab {{ font-family:var(--mono); font-size:1.85mm; letter-spacing:.2em;
    text-transform:uppercase; color:var(--ink-soft); font-weight:500;
    border-bottom:.25mm solid var(--hair); padding-bottom:1mm; margin-bottom:.6mm;
    display:flex; justify-content:space-between; }}
  .flap .clab .catno {{ color:var(--spot); font-weight:700; }}
  .flap .srow {{ display:flex; gap:2mm; font-family:var(--mono); font-size:2.05mm;
    line-height:1.2; color:var(--ink-2); font-weight:300; }}
  .flap .srow .sd {{ flex:0 0 auto; font-weight:700; color:var(--spot); letter-spacing:.06em; }}
  .flap .srow .sv {{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}

  /* ================= +1 INSIDE (the technical spec dossier) ========= */
  .inside {{ background:var(--paper); display:flex; flex-direction:column;
    padding:3mm 5.5mm 2.6mm; gap:1.8mm; }}
  .inside .ihead {{ display:flex; align-items:baseline; justify-content:space-between;
    border-bottom:.4mm solid var(--ink); padding-bottom:1.2mm; }}
  .inside .ihead .t {{ font-family:var(--mono); font-size:2.4mm; letter-spacing:.2em;
    text-transform:uppercase; color:var(--ink); font-weight:600; }}
  .inside .ihead .catno {{ font-family:var(--mono); font-size:2.2mm;
    letter-spacing:.14em; color:var(--spot); font-weight:700; }}

  .inside .cols {{ display:flex; gap:4mm; flex:1; min-height:0; }}
  .inside .specblock {{ flex:1 1 52%; display:flex; flex-direction:column; gap:0; min-width:0; }}
  .spec-row {{ display:flex; align-items:baseline; gap:1.2mm;
    font-family:var(--mono); font-size:2.15mm; line-height:1.0;
    padding:.95mm 0; border-bottom:.25mm solid var(--hair-soft); }}
  .spec-row:first-child {{ border-top:.25mm solid var(--hair-soft); }}
  .spec-k {{ flex:0 0 auto; color:var(--ink-soft); letter-spacing:.12em;
    text-transform:uppercase; font-weight:500; }}
  .spec-dots {{ flex:1; align-self:center; height:0; margin:0 .6mm;
    border-bottom:.25mm dotted var(--hair); }}
  .spec-v {{ flex:0 0 auto; color:var(--ink); font-weight:600; letter-spacing:.02em; }}
  .spec-row[data-ok] .spec-v {{ color:var(--spot); font-weight:700; }}
  .spec-row[data-ok] .spec-v::after {{ content:" \2713"; }}

  .inside .rightcol {{ flex:1 1 46%; display:flex; flex-direction:column; gap:1.6mm; }}
  .inside .howto {{ display:flex; gap:2.4mm; align-items:flex-start; }}
  .inside .howto .qr-box {{ flex:0 0 auto; background:var(--paper); padding:.6mm;
    border:.3mm solid var(--ink); line-height:0; }}
  .inside .howto .htx {{ flex:1; min-width:0; }}
  .inside .howto h2 {{ font-family:var(--mono); font-size:2.15mm; letter-spacing:.16em;
    text-transform:uppercase; color:var(--ink); margin:0 0 1mm; font-weight:700;
    border-bottom:.25mm solid var(--hair); padding-bottom:.8mm; }}
  .inside .howto p {{ margin:0; font-family:var(--mono); font-size:1.95mm;
    line-height:1.4; color:var(--ink-2); font-weight:300; }}
  .inside .howto p b {{ font-weight:600; color:var(--ink); }}
  .inside .howto .url {{ color:var(--spot); font-weight:700; }}

  .inside .sides {{ display:flex; flex-direction:column; gap:0; margin-top:1.4mm; }}
  .inside .side {{ display:flex; gap:1.6mm; font-family:var(--mono); font-size:1.95mm;
    line-height:1.0; color:var(--ink-2); font-weight:400;
    border-top:.25mm solid var(--hair-soft); padding:.95mm 0; }}
  .inside .side .sd {{ flex:0 0 auto; font-weight:700; color:var(--spot);
    letter-spacing:.04em; }}
  .inside .side .sv {{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }}

  .inside .rightcol .attrib {{ margin:0; font-family:var(--mono); font-size:1.7mm;
    letter-spacing:.02em; color:var(--ink-soft); line-height:1.34; font-weight:300; }}
  .inside .rightcol .attrib .badge {{ font-weight:700; color:var(--ink);
    text-transform:uppercase; letter-spacing:.12em; }}

  .inside .foot {{ margin-top:auto; display:flex; align-items:flex-end;
    justify-content:space-between; gap:3mm; border-top:.4mm solid var(--ink);
    padding-top:1.3mm; }}
  .inside .foot .lic {{ font-family:var(--mono); font-size:1.85mm; letter-spacing:.06em;
    color:var(--ink-2); line-height:1.3; font-weight:400; flex:1; margin:0;
    text-transform:uppercase; }}
  .inside .foot .lic .ver {{ color:var(--ink-2); }}
  .inside .foot .num {{ flex:0 0 auto; font-family:var(--mono); font-size:1.95mm;
    color:var(--ink); letter-spacing:.06em; text-align:right; line-height:1.6; }}
  .inside .foot .num .blank {{ display:inline-block; min-width:7mm;
    border-bottom:.3mm solid var(--ink); text-align:center; }}
  .inside .foot .num small {{ display:block; font-size:1.6mm; color:var(--ink-soft);
    letter-spacing:.1em; text-transform:uppercase; font-weight:300; }}

  /* ---- crop marks (4 outer corners) --------------------------------- */
  .crop {{ position:absolute; width:5mm; height:5mm; z-index:5; }}
  .crop::before, .crop::after {{ content:""; position:absolute; background:var(--ink); }}
  .crop::before {{ width:.25mm; height:4mm; }}
  .crop::after  {{ height:.25mm; width:4mm; }}
  .crop.tl {{ left:-6.5mm; top:-6.5mm; }} .crop.tl::before {{ right:0; bottom:0; }} .crop.tl::after {{ right:0; bottom:0; }}
  .crop.tr {{ right:-6.5mm; top:-6.5mm; }} .crop.tr::before {{ left:0; bottom:0; }} .crop.tr::after {{ left:0; bottom:0; }}
  .crop.bl {{ left:-6.5mm; bottom:-6.5mm; }} .crop.bl::before {{ right:0; top:0; }} .crop.bl::after {{ right:0; top:0; }}
  .crop.br {{ right:-6.5mm; bottom:-6.5mm; }} .crop.br::before {{ left:0; top:0; }} .crop.br::after {{ left:0; top:0; }}

  /* ---- registration marks (target crosshair, dossier furniture) ----- */
  .reg {{ position:absolute; width:5mm; height:5mm; z-index:5; }}
  .reg svg {{ width:100%; height:100%; display:block; }}
  .reg.top {{ left:50%; top:-7mm; transform:translateX(-50%); }}
  .reg.bot {{ left:50%; bottom:-7mm; transform:translateX(-50%); }}

  /* ---- dashed fold lines -------------------------------------------- */
  .fold {{ position:absolute; left:0; right:0; height:0; z-index:4;
    border-top:.3mm dashed rgba(26,23,20,.5); }}
  .fold .lab {{ position:absolute; top:50%; left:-2mm; transform:translate(-100%,-50%);
    font-family:var(--mono); font-size:1.9mm; letter-spacing:.16em; text-transform:uppercase;
    color:var(--ink-soft); white-space:nowrap; font-weight:300; }}
  .fold.f1 {{ top:{fold1_mm}mm; }} .fold.f2 {{ top:{fold2_mm}mm; }} .fold.f3 {{ top:{fold3_mm}mm; }}

  .qr-placeholder {{ border:.4mm solid var(--ink); display:flex; align-items:center;
    justify-content:center; font-family:var(--mono); font-size:3mm; font-weight:700;
    color:var(--ink); background:var(--paper); }}
  .qr-fallback-note {{ font-size:1.7mm; color:var(--ferric); margin:1mm 0 0; }}

  /* screen-only convenience frame */
  @media screen {{
    body {{ background:#b9b1a1; padding:6mm 0; }}
    .sheet {{ background:#fff; box-shadow:0 4mm 22mm rgba(0,0,0,.3); }}
    .card {{ box-shadow:0 1mm 5mm rgba(0,0,0,.22); }}
  }}
</style>
</head>
<body>
<div class="sheet">

  <!-- margin furniture: trimmed with the offcut -->
  <div class="print-note">
    PRINT AT 100% — ACTUAL SIZE · DO NOT &lsquo;FIT TO PAGE&rsquo;
    <small>A4 · Landscape · Scale 100% / Actual size · then verify the 100 mm ruler below with a real ruler before cutting</small>
  </div>

  <div class="card-wrap">
    <!-- crop marks -->
    <span class="crop tl"></span><span class="crop tr"></span>
    <span class="crop bl"></span><span class="crop br"></span>
    <!-- registration crosshairs -->
    <span class="reg top">{REG_SVG}</span>
    <span class="reg bot">{REG_SVG}</span>
    <!-- fold lines -->
    <span class="fold f1"><span class="lab">fold</span></span>
    <span class="fold f2"><span class="lab">fold</span></span>
    <span class="fold f3"><span class="lab">fold</span></span>

    <div class="card">
      <!-- ========== COVER (front) ========== -->
      <div class="panel cover">
        <div class="spectro">
          <span class="axis"></span>
          {spectro_html}
          <span class="anno f-hi">18 kHz</span>
          <span class="anno f-lo">0 Hz</span>
          <span class="anno cap">{spectro_caption}</span>
        </div>
        <div class="meat">
          <div class="speclabel">
            <span><span class="catno">{catalogue}</span></span>
            <span>MAGNETIC SPECIMEN <span class="dim">{specimen_no}</span></span>
          </div>
          <div class="titlewrap">
            <span class="ghost {title_class}" aria-hidden="true">{title}</span>
            <h1 class="{title_class}">{title}</h1>
          </div>
          <p class="flex">&ldquo;{flex}&rdquo;</p>
          <div class="footrow">
            <div class="strap"><b>RECORDED BY HAND</b><br>DATA, NOT MUSIC · DECODE TO PLAY</div>
            <span class="tier">{tier}</span>
          </div>
        </div>
      </div>

      <!-- ========== SPINE ========== -->
      <div class="panel spine">
        <span class="l"><span class="catno">{catalogue}</span> &nbsp;<span class="ttl">{title}</span></span>
        <span class="r">SIDE A · THE MAGNETIC VAULT</span>
      </div>

      <!-- ========== TUCK FLAP ========== -->
      <div class="panel flap">
        <div class="clab"><span>SPECIMEN CONTENTS</span><span class="catno">{catalogue}</span></div>
        <div class="srow"><span class="sd">A</span><span class="sv">{side_a}</span></div>
        <div class="srow"><span class="sd">B</span><span class="sv">{side_b}</span></div>
      </div>

      <!-- ========== +1 INSIDE (the dossier) ========== -->
      <div class="panel inside">
        <div class="ihead">
          <span class="t">TECHNICAL RECORD</span>
          <span class="catno">{catalogue} · DECLASSIFIED</span>
        </div>
        <div class="cols">
          <div class="specblock">
            {spec_rows}
            <div class="sides">
              <div class="side"><span class="sd">A</span><span class="sv">{side_a_short}</span></div>
              <div class="side"><span class="sd">B</span><span class="sv">{side_b_short}</span></div>
            </div>
          </div>
          <div class="rightcol">
            <div class="howto">
              <div class="qr-box">{qr_svg}</div>
              <div class="htx">
                <h2>How to play</h2>
                <p><b>This is DATA, not music.</b> Play the tape into a computer and decode it with the free app at <span class="url">{qr_url}</span> — scan the code, or type it in.</p>
              </div>
            </div>
            {qr_note}
            <p class="attrib"><span class="badge">{license}</span> · {attribution}</p>
          </div>
        </div>
        <div class="foot">
          <p class="lic"><span class="ver">{verified}</span></p>
          <p class="num"><span class="blank">&nbsp;</span> / <span class="blank">&nbsp;</span>
            <small>specimen № of edition</small></p>
        </div>
      </div>
    </div>
  </div>

  <div class="ruler">
    <div class="bar"></div>
    <span class="endlabel l">0</span><span class="endlabel r">100&nbsp;mm</span>
    <div class="cap">CALIBRATION · should measure exactly 100&nbsp;mm</div>
  </div>

</div>
<script>
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

# A small registration-target crosshair (print furniture), inline so it embeds.
REG_SVG = (
    '<svg viewBox="0 0 20 20" aria-hidden="true">'
    '<circle cx="10" cy="10" r="6" fill="none" stroke="#1a1714" stroke-width="0.6"/>'
    '<line x1="10" y1="0" x2="10" y2="20" stroke="#1a1714" stroke-width="0.4"/>'
    '<line x1="0" y1="10" x2="20" y2="10" stroke="#1a1714" stroke-width="0.4"/>'
    '<circle cx="10" cy="10" r="1.4" fill="#c75e34"/>'
    '</svg>'
)
# inject the reg svg (kept out of .format() so its braces don't collide)
TEMPLATE = TEMPLATE.replace("{REG_SVG}", REG_SVG)


def main(argv):
    releases = json.loads(DATA.read_text())
    idx_of = {r["id"]: i for i, r in enumerate(releases)}
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
        out_path.write_text(render(by_id[slug], qr_svg, qr_ok, idx_of[slug]))
        written.append(out_path)
        print(f"  + {out_path.relative_to(HERE.parent)}")

    print(f"\nGenerated {len(written)} J-card(s) in the MAGNETIC SPECIMEN aesthetic. "
          f"QR: {'segno' if qr_ok else 'PLACEHOLDER'}.")
    print("Open one, Print -> A4 Landscape -> Scale 100% / Actual size, then check the ruler.")


if __name__ == "__main__":
    main(sys.argv)
