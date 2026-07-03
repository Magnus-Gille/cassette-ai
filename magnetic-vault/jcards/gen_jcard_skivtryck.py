#!/usr/bin/env python3
"""
gen_jcard_skivtryck.py — the MAGNETIC SPECIMEN J-card re-fitted to skivtryck's
EXACT factory die (JC31, 3-panel, 13 mm spine), data-driven over the ready trio.

Difference vs gen_jcard.py (print-at-home): that one used its own ~101.6/63.5/
12.7/25.4 mm geometry with home crop marks. This conforms to the manufacturer
template from https://skivtryck.se → Mallar (docs/skivtryck_templates/):

    JC31: flat 227 x 101 mm · 2 mm bleed · panel order along the strip:
      Back 25 | Spine 13 | Front 65 | +1 63 | +2 61   (all 101 mm shared axis)

Presented in READING orientation (each panel upright, strip stacked top->bottom in
skivtryck's linear order). For the press file the whole artwork rotates 90° into
skivtryck's 227(w) x 101(h) die — one export rotation; folds/dims already match 1:1.

CONTENT SOURCE: docs/kickstarter_planning.md (the authoritative, current scope).
NB releases_data.json is stale for Great Library (says "58 books" — the cut
8-hour version); the current locked spec is 9 classics + robotic reader, 1.02 MB.

Emits out/<id>_skivtryck.html for the three ready-now tapes (DOOM, The Console,
The Great Library). DOOM embeds the real master spectrogram; the others show a
carrier-band placeholder until their master is captured.
"""
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

# ---- skivtryck JC31 die (mm) — load-bearing, from the factory template --------
CARD_AXIS = 101.0
P_BACK, P_SPINE, P_FRONT, P_PLUS1, P_PLUS2 = 25.0, 13.0, 65.0, 63.0, 61.0
STRIP = P_BACK + P_SPINE + P_FRONT + P_PLUS1 + P_PLUS2   # 227
BLEED, SAFE = 2.0, 3.0
QR_URL = "cassette.gille.ai"


def qr_svg(url, mm, ink="#1a1714"):
    import segno
    m = segno.make(f"https://{url}", error="m").matrix
    n = len(m); q = 2; dim = n + 2 * q
    rects = []
    for r, row in enumerate(m):
        s = None
        for c in range(len(row) + 1):
            on = c < len(row) and row[c]
            if on and s is None:
                s = c
            elif not on and s is not None:
                rects.append(f'<rect x="{s+q}" y="{r+q}" width="{c-s}" height="1"/>'); s = None
    return (f'<svg viewBox="0 0 {dim} {dim}" style="width:{mm}mm;height:{mm}mm" '
            f'shape-rendering="crispEdges"><rect width="{dim}" height="{dim}" fill="#efe7d6"/>'
            f'<g fill="{ink}">{"".join(rects)}</g></svg>')


QR = qr_svg(QR_URL, 14)


def spectro_datauri(fname):
    p = OUT / fname
    if p.exists():
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    return None


# ---- the ready trio (accurate current content from the planning doc) ---------
RELEASES = {
    "doom": {
        "cat": "MV-001", "no": "No.001", "title": "DOOM", "title_size": "26mm",
        "accent": "#c0492b",
        "flex": "a cassette that plays DOOM",
        "spectro": "spectrogram_doom.png",
        "spectro_cap": "THE SOUND OF DOOM, AS RECORDED",
        "tier": "PLAYS ON ANY DECK",
        "sides": [
            ("A", "<b>The full game.</b> Freedoom Episode 1 — all 9 maps, in-browser "
                  "sound, saves, and THE MAGNETIC VAULT bonus level. Decoded byte-exact "
                  "off a real cassette."),
            ("B", "<b>DECODED</b> — a 9-track album mastered from the actual "
                  "data-transfer signal, followed by the complete GPL source."),
        ],
        "contents_note": "C90 · Type-II CrO₂ · Dolby NR OFF. <b>One side of data ≈ 41 min 44 s.</b> "
                         "Freedoom (BSD) · DOOM source © id Software, GPLv2.",
        "spec": [("FORMAT", "d2x · m10doom3"), ("GROSS", "7875 bps"), ("NET", "4910 bps"),
                 ("SNR", "38.9 dB"), ("FLUTTER", "0.38 %"), ("CODEWORDS", "9225 · 0 failed"),
                 ("INTEGRITY", "BYTE-EXACT"), ("RUNTIME", "41 min 44 s / side")],
        "verified": "decoded off a real cassette · 2026-06-13",
        "attrib": '<span class="badge">GPL</span> · Free-culture work, recorded &amp; '
                  'decode-verified by hand · 2026-06-13.',
    },
    "console": {
        "cat": "MV-005", "no": "No.005", "title": "The Console", "title_size": "13.5mm",
        "accent": "#3f7fa3",
        "flex": "a whole games console on a cassette",
        "spectro": None,
        "spectro_cap": "SIGNAL TRACE · MASTER PENDING",
        "tier": "HI-FI SETUP REQ.",
        "sides": [
            ("A", "<b>The TIC-80 fantasy console</b> plus 16 playable game carts, "
                  "booting straight from the tape — an arcade pressed onto magnetic film."),
            ("·", "Single-side release. The console and every cart decode on-device "
                  "in the browser; nothing to install."),
        ],
        "contents_note": "C90 · Type-II CrO₂ · Dolby NR OFF · one side. "
                         "<b>1.50 MB ≈ 40 min 42 s.</b> TIC-80 © Nesbox, MIT · carts under their own licences.",
        "spec": [("FORMAT", "d2x · 4910 bps"), ("PAYLOAD", "1.50 MB"), ("CARTS", "16 games"),
                 ("RUNTIME", "40 min 42 s / side"), ("MEDIUM", "C90 · Type-II"),
                 ("SIDES", "one side of data"), ("INTEGRITY", "decode-verified"),
                 ("STATUS", "ready for master")],
        "verified": "spec locked · master capture pending",
        "attrib": '<span class="badge">MIT</span> · TIC-80 console © Nesbox · '
                  'carts under their own licences.',
    },
    "great-library": {
        "cat": "MV-002", "no": "No.002", "title": "The Great Library", "title_size": "9mm",
        "accent": "#b8860b",
        "flex": "nine classics, read aloud",
        "spectro": None,
        "spectro_cap": "SIGNAL TRACE · MASTER PENDING",
        "tier": "HI-FI SETUP REQ.",
        "sides": [
            ("A", "<b>Nine classics</b> — full text — with a built-in robotic-voice "
                  "reader (eSpeak-ng) that reads any of them aloud on-device."),
            ("·", "Alice in Wonderland · A Christmas Carol · Jekyll &amp; Hyde · "
                  "The Metamorphosis · The Fall of the House of Usher · The Masque of "
                  "the Red Death · The Yellow Wallpaper · A Study in Scarlet · The Time Machine."),
        ],
        "contents_note": "C90 · Type-II CrO₂ · Dolby NR OFF · one side (62% used). "
                         "<b>1.02 MB ≈ 27 min 42 s.</b> Texts public-domain · reader eSpeak-ng, GPLv3 (source ships alongside).",
        "spec": [("FORMAT", "d2x · 4910 bps"), ("PAYLOAD", "1.02 MB"), ("TITLES", "9 classics + reader"),
                 ("RUNTIME", "27 min 42 s / side"), ("MEDIUM", "C90 · Type-II"),
                 ("FILL", "one side · 62%"), ("INTEGRITY", "decode-verified"),
                 ("STATUS", "ready for master")],
        "verified": "spec locked · master capture pending",
        "attrib": '<span class="badge">PUBLIC DOMAIN</span> · texts free · reader '
                  'eSpeak-ng, GPLv3 (source alongside).',
    },
}


def render(rel):
    accent = rel["accent"]
    spec_rows = "".join(
        f'<div class="spec-row"{" data-ok=1" if k=="INTEGRITY" and v=="BYTE-EXACT" else ""}>'
        f'<span class="spec-k">{k}</span><span class="spec-dots"></span>'
        f'<span class="spec-v">{v}</span></div>' for k, v in rel["spec"])
    sides = "".join(
        f'<div class="side"><span class="sd">{sd}</span><span class="sv">{sv}</span></div>'
        for sd, sv in rel["sides"])

    uri = spectro_datauri(rel["spectro"]) if rel["spectro"] else None
    if uri:
        spectro_img = (f'<img src="{uri}" alt="Duotone spectrogram of the '
                       f'{rel["title"]} master signal">')
    else:
        spectro_img = '<div class="spectro-ph"></div>'

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>SPECIMEN {rel['cat']} · {rel['title']} · skivtryck JC31 die</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,900;1,9..144,400;1,9..144,500&family=Martian+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{
  --ink:#1a1714; --ink-2:#2a241d; --ink-soft:#6b5f4f;
  --paper:#efe7d6; --paper-2:#e7dcc6; --cream:#f4efe6;
  --hair:rgba(26,23,20,.42); --hair-soft:rgba(26,23,20,.22);
  --spot:{accent};
  --display:"Fraunces","Iowan Old Style",Palatino,Georgia,serif;
  --mono:"Martian Mono",ui-monospace,"SF Mono",Menlo,monospace;
  --bleed:#e6007e; --cut:#1ca0c4; --fold:#2f7bd6; --clear:rgba(28,160,196,.10);
}}
*{{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact;}}
html,body{{margin:0;padding:0;font-family:var(--mono);color:var(--ink);}}
@media screen{{ body{{background:#b9b1a1;padding:12mm;}} }}
@page{{ size:{STRIP+2*BLEED}mm {CARD_AXIS+2*BLEED}mm; margin:0; }}
.bleedbox{{position:relative;width:{CARD_AXIS+2*BLEED}mm;height:{STRIP+2*BLEED}mm;
  background:var(--paper);margin:0 auto;box-shadow:0 3mm 18mm rgba(0,0,0,.3);}}
.card{{position:absolute;left:{BLEED}mm;top:{BLEED}mm;width:{CARD_AXIS}mm;height:{STRIP}mm;
  display:flex;flex-direction:column;background:var(--paper);overflow:hidden;}}
.card::after{{content:"";position:absolute;inset:0;z-index:6;pointer-events:none;
  opacity:.45;mix-blend-mode:multiply;background-size:34mm 34mm;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='120' height='120' filter='url(%23n)' opacity='0.5'/></svg>");}}
.panel{{position:relative;width:{CARD_AXIS}mm;overflow:hidden;}}
.p-back{{height:{P_BACK}mm;}} .p-spine{{height:{P_SPINE}mm;}}
.p-front{{height:{P_FRONT}mm;}} .p-plus1{{height:{P_PLUS1}mm;}} .p-plus2{{height:{P_PLUS2}mm;}}

.guides{{position:absolute;inset:0;z-index:20;pointer-events:none;}}
.guides .bleedline{{position:absolute;inset:0;border:.3mm dashed var(--bleed);}}
.guides .cutline{{position:absolute;left:{BLEED}mm;top:{BLEED}mm;width:{CARD_AXIS}mm;height:{STRIP}mm;border:.3mm solid var(--cut);}}
.guides .clear{{position:absolute;left:{BLEED+SAFE}mm;top:{BLEED+SAFE}mm;width:{CARD_AXIS-2*SAFE}mm;height:{STRIP-2*SAFE}mm;outline:.25mm dashed rgba(28,160,196,.55);background:var(--clear);}}
.guides .fold{{position:absolute;left:{BLEED-4}mm;width:{CARD_AXIS+8}mm;height:0;border-top:.3mm dashed var(--fold);}}
.guides .fold span{{position:absolute;right:100%;top:-1.6mm;margin-right:1mm;font:1.9mm var(--mono);color:var(--fold);letter-spacing:.1em;white-space:nowrap;}}
.legend{{position:absolute;left:{BLEED}mm;bottom:-9mm;display:flex;gap:6mm;font:2.2mm var(--mono);color:var(--ink-soft);letter-spacing:.08em;}}
.legend i{{display:inline-block;width:6mm;height:0;vertical-align:middle;margin-right:1.2mm;}}
body.clean .guides,body.clean .legend{{display:none;}}

.p-back{{background:var(--paper-2);display:flex;align-items:center;justify-content:space-between;padding:0 6mm;border-bottom:.3mm dashed var(--hair);}}
.p-back .mv{{display:flex;align-items:baseline;gap:2.2mm;font:600 2.5mm var(--mono);letter-spacing:.14em;text-transform:uppercase;}}
.p-back .mv .k{{color:var(--spot);font-weight:700;}}
.p-back .mv .w{{font-family:var(--display);font-weight:600;letter-spacing:.02em;text-transform:none;font-size:3mm;}}
.p-back .r{{text-align:right;font:300 2.05mm var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft);line-height:1.5;}}
.p-back .r b{{color:var(--spot);font-weight:700;}}

.p-spine{{background:var(--ink);color:var(--cream);display:flex;align-items:center;justify-content:space-between;gap:4mm;padding:0 6mm;}}
.p-spine .l{{font:500 2.5mm var(--mono);letter-spacing:.14em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}}
.p-spine .l .k{{color:var(--spot);font-weight:700;}}
.p-spine .l .t{{font-family:var(--display);font-weight:600;font-size:3mm;text-transform:none;letter-spacing:.01em;}}
.p-spine .r{{flex:0 0 auto;font:400 2.05mm var(--mono);letter-spacing:.2em;text-transform:uppercase;color:rgba(244,239,230,.72);white-space:nowrap;}}

.p-front{{background:var(--paper);display:flex;flex-direction:column;}}
.spectro{{position:relative;width:{CARD_AXIS}mm;height:20mm;background:var(--ink);border-bottom:.5mm solid var(--spot);overflow:hidden;}}
.spectro img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;}}
.spectro-ph{{position:absolute;inset:0;background:
  repeating-linear-gradient(90deg,transparent 0 .9mm,color-mix(in srgb,var(--spot) 62%,transparent) .9mm 1.25mm),
  repeating-linear-gradient(0deg,rgba(244,239,230,.06) 0 .4mm,transparent .4mm 1.1mm),
  var(--ink);}}
.spectro .axis{{position:absolute;left:0;top:0;bottom:0;width:7mm;z-index:1;background:linear-gradient(90deg,rgba(26,23,20,.78),transparent);}}
.spectro .anno{{position:absolute;z-index:2;font:300 1.9mm var(--mono);color:rgba(244,239,230,.62);text-transform:uppercase;letter-spacing:.14em;}}
.spectro .hi{{top:1.1mm;left:2mm;}} .spectro .lo{{bottom:1.1mm;left:2mm;}}
.spectro .cap{{bottom:1.1mm;right:2.5mm;color:color-mix(in srgb,var(--spot) 90%,white);font-weight:500;letter-spacing:.16em;}}
.meat{{flex:1;display:flex;flex-direction:column;padding:2.6mm 6mm 2.4mm;min-height:0;}}
.speclabel{{display:flex;justify-content:space-between;align-items:baseline;font:500 2.05mm var(--mono);letter-spacing:.16em;text-transform:uppercase;}}
.speclabel .k{{color:var(--spot);font-weight:700;}}
.speclabel .dim{{color:var(--ink-soft);font-weight:300;letter-spacing:.1em;}}
.titlewrap{{position:relative;margin:.6mm 0 0;line-height:0;}}
.titlewrap h1,.titlewrap .ghost{{font-family:var(--display);font-weight:900;font-variation-settings:"opsz" 144;margin:0;line-height:.84;letter-spacing:-.026em;font-size:{rel['title_size']};white-space:nowrap;}}
.titlewrap h1{{position:relative;z-index:2;color:var(--ink);}}
.titlewrap .ghost{{position:absolute;left:0;top:0;z-index:1;color:var(--spot);opacity:.9;transform:translate(.5mm,.46mm);}}
.flex{{font-family:var(--display);font-style:italic;font-weight:400;font-size:3.6mm;line-height:1.08;color:var(--ink-2);margin:1.4mm 0 0;}}
.footrow{{margin-top:auto;display:flex;align-items:flex-end;justify-content:space-between;gap:3mm;padding-top:1.6mm;border-top:.3mm solid var(--hair);}}
.footrow .strap{{font:400 1.85mm var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft);line-height:1.5;}}
.footrow .strap b{{color:var(--ink);font-weight:600;}}
.tier{{flex:0 0 auto;font:600 1.95mm var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--spot);border:.3mm solid var(--spot);padding:.9mm 1.8mm;white-space:nowrap;}}

.p-plus1{{background:var(--paper);display:flex;flex-direction:column;padding:3mm 6mm 2.6mm;gap:1.6mm;}}
.ihead{{display:flex;justify-content:space-between;align-items:baseline;border-bottom:.4mm solid var(--ink);padding-bottom:1.2mm;}}
.ihead .t{{font:600 2.4mm var(--mono);letter-spacing:.2em;text-transform:uppercase;}}
.ihead .k{{font:700 2.2mm var(--mono);letter-spacing:.14em;color:var(--spot);}}
.side{{display:flex;gap:2mm;border-top:.25mm solid var(--hair-soft);padding:1.4mm 0;}}
.side:first-of-type{{border-top:none;}}
.side .sd{{flex:0 0 5mm;font:700 3mm var(--display);color:var(--spot);line-height:1;}}
.side .sv{{flex:1;font:300 2.15mm var(--mono);line-height:1.36;color:var(--ink-2);}}
.side .sv b{{font-weight:600;color:var(--ink);}}
.contents-note{{margin-top:auto;font:300 1.8mm var(--mono);letter-spacing:.04em;color:var(--ink-soft);line-height:1.4;border-top:.3mm solid var(--hair);padding-top:1.4mm;}}
.contents-note b{{color:var(--ink);font-weight:600;}}

.p-plus2{{background:var(--paper-2);display:flex;flex-direction:column;padding:3mm 6mm 2.6mm;gap:1.6mm;}}
.cols{{display:flex;gap:5mm;flex:1;min-height:0;}}
.specblock{{flex:1 1 50%;display:flex;flex-direction:column;overflow:hidden;}}
.spec-row{{display:flex;align-items:baseline;gap:1.2mm;font:2.05mm var(--mono);padding:.62mm 0;border-bottom:.25mm solid var(--hair-soft);}}
.spec-row:first-child{{border-top:.25mm solid var(--hair-soft);}}
.spec-k{{color:var(--ink-soft);letter-spacing:.1em;text-transform:uppercase;font-weight:500;}}
.spec-dots{{flex:1;height:0;margin:0 .6mm;align-self:center;border-bottom:.25mm dotted var(--hair);}}
.spec-v{{color:var(--ink);font-weight:600;white-space:nowrap;}}
.spec-row[data-ok] .spec-v{{color:var(--spot);font-weight:700;}}
.spec-row[data-ok] .spec-v::after{{content:" \\2713";}}
.rightcol{{flex:1 1 48%;display:flex;flex-direction:column;gap:1.8mm;}}
.howto{{display:flex;gap:2.6mm;}}
.howto .qr{{flex:0 0 auto;border:.3mm solid var(--ink);padding:.6mm;background:var(--paper);line-height:0;}}
.howto h2{{font:700 2.15mm var(--mono);letter-spacing:.16em;text-transform:uppercase;margin:0 0 1mm;border-bottom:.25mm solid var(--hair);padding-bottom:.8mm;}}
.howto p{{margin:0;font:300 1.95mm var(--mono);line-height:1.42;color:var(--ink-2);}}
.howto p b{{font-weight:600;color:var(--ink);}} .howto .url{{color:var(--spot);font-weight:700;}}
.attrib{{margin:0;font:300 1.72mm var(--mono);color:var(--ink-soft);line-height:1.36;}}
.attrib .badge{{font-weight:700;color:var(--ink);text-transform:uppercase;letter-spacing:.1em;}}
.foot{{margin-top:auto;display:flex;align-items:flex-end;justify-content:space-between;gap:3mm;border-top:.4mm solid var(--ink);padding-top:1.3mm;}}
.foot .lic{{margin:0;font:400 1.85mm var(--mono);letter-spacing:.05em;text-transform:uppercase;color:var(--ink-2);line-height:1.3;flex:1;}}
.foot .num{{flex:0 0 auto;text-align:right;font:2mm var(--mono);line-height:1.6;}}
.foot .num .b{{display:inline-block;min-width:7mm;border-bottom:.3mm solid var(--ink);}}
.foot .num small{{display:block;font-size:1.6mm;color:var(--ink-soft);letter-spacing:.1em;text-transform:uppercase;font-weight:300;}}
</style></head>
<body>
<div class="bleedbox">
  <div class="card">
    <div class="panel p-back">
      <div class="mv"><span class="k">{rel['cat']}</span><span class="w">The Magnetic Vault</span></div>
      <div class="r">MAGNETIC SPECIMEN {rel['no']}<br><b>DATA</b> · NOT MUSIC · {QR_URL}</div>
    </div>
    <div class="panel p-spine">
      <span class="l"><span class="k">{rel['cat']}</span> &nbsp;<span class="t">{rel['title']}</span> &nbsp;<span style="color:rgba(244,239,230,.5)">· THE MAGNETIC VAULT</span></span>
      <span class="r">SIDE A</span>
    </div>
    <div class="panel p-front">
      <div class="spectro">
        <span class="axis"></span>{spectro_img}
        <span class="anno hi">18 kHz</span><span class="anno lo">0 Hz</span>
        <span class="anno cap">{rel['spectro_cap']}</span>
      </div>
      <div class="meat">
        <div class="speclabel"><span class="k">{rel['cat']}</span>
          <span>MAGNETIC SPECIMEN <span class="dim">{rel['no']}</span></span></div>
        <div class="titlewrap"><span class="ghost">{rel['title']}</span><h1>{rel['title']}</h1></div>
        <p class="flex">&ldquo;{rel['flex']}&rdquo;</p>
        <div class="footrow">
          <div class="strap"><b>RECORDED BY HAND</b><br>DATA, NOT MUSIC · DECODE TO PLAY</div>
          <span class="tier">{rel['tier']}</span>
        </div>
      </div>
    </div>
    <div class="panel p-plus1">
      <div class="ihead"><span class="t">Specimen Contents</span><span class="k">{rel['cat']}</span></div>
      {sides}
      <p class="contents-note">{rel['contents_note']}</p>
    </div>
    <div class="panel p-plus2">
      <div class="ihead"><span class="t">Technical Record</span><span class="k">{rel['cat']} · DECLASSIFIED</span></div>
      <div class="cols">
        <div class="specblock">{spec_rows}</div>
        <div class="rightcol">
          <div class="howto"><div class="qr">{QR}</div>
            <div><h2>How to play</h2>
            <p><b>This is DATA, not music.</b> Play the tape into a computer and decode it with the free app at <span class="url">{QR_URL}</span> — scan the code, or type it in.</p></div>
          </div>
          <p class="attrib">{rel['attrib']}</p>
        </div>
      </div>
      <div class="foot">
        <p class="lic">{rel['verified']}</p>
        <p class="num"><span class="b">&nbsp;</span> / <span class="b">&nbsp;</span>
          <small>specimen № of edition</small></p>
      </div>
    </div>
  </div>
  <div class="guides">
    <div class="bleedline"></div><div class="cutline"></div><div class="clear"></div>
    <div class="fold" style="top:{BLEED+P_BACK}mm"><span>fold</span></div>
    <div class="fold" style="top:{BLEED+P_BACK+P_SPINE}mm"><span>fold</span></div>
    <div class="fold" style="top:{BLEED+P_BACK+P_SPINE+P_FRONT}mm"><span>fold</span></div>
    <div class="fold" style="top:{BLEED+P_BACK+P_SPINE+P_FRONT+P_PLUS1}mm"><span>fold</span></div>
  </div>
  <div class="legend">
    <span><i style="border-top:.4mm dashed var(--bleed)"></i>bleed 2mm</span>
    <span><i style="border-top:.4mm solid var(--cut)"></i>cut</span>
    <span><i style="border-top:.4mm dashed var(--fold)"></i>fold</span>
    <span>· JC31 227×101mm · reads upright; rotate 90° for skivtryck die</span>
  </div>
</div>
<script>
if(location.hash==='#clean')document.body.classList.add('clean');
addEventListener('keydown',e=>{{if(e.key==='c')document.body.classList.toggle('clean');}});
</script>
</body></html>"""


def main():
    for rid, rel in RELEASES.items():
        (OUT / f"{rid}_skivtryck.html").write_text(render(rel))
        print("wrote", (OUT / f"{rid}_skivtryck.html").name)


if __name__ == "__main__":
    main()
