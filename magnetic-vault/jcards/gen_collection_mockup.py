#!/usr/bin/env python3
"""
gen_collection_mockup.py — build collection_mockup.html, the SERIES-SYSTEM
comparison page for THE MAGNETIC VAULT.

This does NOT redesign the locked "MAGNETIC SPECIMEN" J-card (gen_jcard.py). It
reuses the exact template DNA — Fraunces display + Martian Mono, the spectrogram
hero band, the oversized flush-left cropped title with a spot-ink riso ghost, the
warm-ink (#1a1714) + bone (#efe7d6) base, paper grain, crop/registration furniture
— and explores ONLY the single ferric SPOT COLOUR, as a curated series palette.

Three palette VERSIONS (like a record label's editions), each a harmonious set of
4 coordinated spots over the charcoal/bone base:
  V1 OXIDE  — warm analogous aged-ferric metal (a shelf of aged tapes)
  V2 RISO   — muted equally-chalky risograph inks, varied hue (curated zine series)
  V3 TONAL  — graduated single-family ramp, max shelf-uniformity (one edition)

Each version shows (a) the 4 FRONT COVERS in a row and (b) a SHELF-SPINE STRIP of
the same 4 as case spines standing edge-to-edge on a shelf, so the across-the-set
harmony reads at a glance.

Bands are pre-rendered per (version, cassette) by gen_collection_bands.py and
base64-embedded so the page is fully self-contained.
"""
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "collection_assets"
OUT = HERE / "collection_mockup.html"

# ---- the 4 cassettes (DOOM keeps its real spectrogram window; the other three
# get a representative signal-trace band in the version's spot) ---------------
CASSETTES = [
    {
        "id": "doom", "cat": "MV-001", "no": "No.001",
        "title": "DOOM", "tclass": "t-short",
        "flex": "a cassette that plays DOOM",
        "spine_title": "DOOM",
        "tier": "PLAYS ON ANY DECK",
    },
    {
        "id": "willows", "cat": "MV-002", "no": "No.002",
        "title": "The Willows", "tclass": "t-mid",
        "flex": "a playable, self-narrating book",
        "spine_title": "THE WILLOWS",
        "tier": "PLAYS ON ANY DECK",
    },
    {
        "id": "grandmaster", "cat": "MV-005", "no": "No.005",
        "title": "Grandmaster", "tclass": "t-mid",
        "flex": "a cassette that plays chess",
        "spine_title": "GRANDMASTER",
        "tier": "PLAYS ON ANY DECK",
    },
    {
        "id": "great-library", "cat": "MV-006", "no": "No.006",
        "title": "The Great Library", "tclass": "t-long",
        "flex": "58 classic books on one tape",
        "spine_title": "THE GREAT LIBRARY",
        "tier": "HI-FI SETUP REQ.",
    },
]

# ---- the three tuned palettes (must match gen_collection_bands.py) ----------
VERSIONS = [
    {
        "key": "v1", "code": "V1", "name": "OXIDE",
        "blurb": "Warm analogous aged-ferric metal. The four spots are one "
                 "family of oxidised iron — burnt orange, ochre, rust, clay — "
                 "so the set reads like a shelf of aged tapes that lived together.",
        "spots": {
            "doom": "c75e34", "willows": "bf7e35",
            "grandmaster": "b1402c", "great-library": "97603a",
        },
        "labels": {
            "doom": "BURNT ORANGE", "willows": "OCHRE",
            "grandmaster": "RUST RED", "great-library": "CLAY UMBER",
        },
    },
    {
        "key": "v2", "code": "V2", "name": "RISO",
        "blurb": "Muted risograph inks, varied in hue but unified by an equal "
                 "chalky desaturation and matched value — coral, teal, mustard, "
                 "slate. A curated zine-series feel: different, yet clearly one run.",
        "spots": {
            "doom": "c56b50", "willows": "4a847a",
            "grandmaster": "b88c3d", "great-library": "5e7596",
        },
        "labels": {
            "doom": "FADED CORAL", "willows": "DUSTY TEAL",
            "grandmaster": "MUSTARD", "great-library": "SLATE BLUE",
        },
    },
    {
        "key": "v3", "code": "V3", "name": "TONAL",
        "blurb": "A graduated single-family ramp — sand, amber, terracotta, "
                 "oxblood — stepping evenly in value for maximum shelf-uniformity. "
                 "Reads as one deliberate edition, numbered by its own warmth.",
        "spots": {
            "doom": "d0a85f", "willows": "c5893f",
            "grandmaster": "ad5e3a", "great-library": "8a4a3a",
        },
        "labels": {
            "doom": "SAND", "willows": "AMBER",
            "grandmaster": "TERRACOTTA", "great-library": "OXBLOOD",
        },
    },
]


def b64_band(vkey, cid):
    p = ASSETS / f"{vkey}_{cid}.png"
    b = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b}"


def cover_html(v, c):
    spot = "#" + v["spots"][c["id"]]
    band = b64_band(v["key"], c["id"])
    return f"""
      <article class="cover" style="--spot:{spot}">
        <div class="spectro">
          <span class="axis"></span>
          <img class="spectro-img" src="{band}" alt="signal trace of {c['title']}" draggable="false">
          <span class="anno f-hi">18&nbsp;kHz</span>
          <span class="anno f-lo">0&nbsp;Hz</span>
          <span class="anno cap">SIGNAL · {c['title'].upper()}</span>
        </div>
        <div class="meat">
          <div class="speclabel">
            <span class="catno">{c['cat']}</span>
            <span>MAGNETIC SPECIMEN <span class="dim">{c['no']}</span></span>
          </div>
          <div class="titlewrap">
            <span class="ghost {c['tclass']}" aria-hidden="true">{c['title']}</span>
            <h1 class="{c['tclass']}">{c['title']}</h1>
          </div>
          <p class="flex">&ldquo;{c['flex']}&rdquo;</p>
          <div class="footrow">
            <div class="strap"><b>RECORDED BY HAND</b><br>DATA, NOT MUSIC · DECODE TO PLAY</div>
            <span class="tier">{c['tier']}</span>
          </div>
        </div>
      </article>"""


def spine_html(v, c):
    spot = "#" + v["spots"][c["id"]]
    return f"""
        <div class="spine" style="--spot:{spot}">
          <span class="s-band"></span>
          <span class="s-cat">{c['cat']}</span>
          <span class="s-title">{c['spine_title']}</span>
          <span class="s-foot">SIDE&nbsp;A</span>
          <span class="s-mv">MV</span>
        </div>"""


def swatches_html(v):
    items = []
    for c in CASSETTES:
        hexv = v["spots"][c["id"]]
        items.append(
            f'<span class="sw"><span class="chip" style="background:#{hexv}"></span>'
            f'<span class="sw-txt"><b>{v["labels"][c["id"]]}</b>'
            f'<span class="hex">#{hexv}</span></span></span>'
        )
    return "".join(items)


def version_section(v):
    covers = "".join(cover_html(v, c) for c in CASSETTES)
    spines = "".join(spine_html(v, c) for c in CASSETTES)
    swatches = swatches_html(v)
    return f"""
  <section class="version">
    <header class="vhead">
      <div class="vmark">
        <span class="vcode">{v['code']}</span>
        <span class="vname">{v['name']}</span>
      </div>
      <p class="vblurb">{v['blurb']}</p>
      <div class="swatches">{swatches}</div>
    </header>

    <div class="row-label"><span>FOUR COVERS · THE SET</span><i></i></div>
    <div class="covers">{covers}</div>

    <div class="row-label"><span>ON THE SHELF · CASE SPINES, EDGE TO EDGE</span><i></i></div>
    <div class="shelf">
      <div class="spines">{spines}</div>
      <div class="shelf-board"></div>
    </div>
  </section>"""


def build():
    sections = "".join(version_section(v) for v in VERSIONS)
    return PAGE.replace("{SECTIONS}", sections)


# ============================================================================
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>THE MAGNETIC VAULT · Collection Palette Study — V1 / V2 / V3</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,900;1,9..144,400;1,9..144,500&family=Martian+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#1a1714; --ink-2:#2a241d; --ink-soft:#6b5f4f;
    --paper:#efe7d6; --paper-2:#e7dcc6; --cream:#f4efe6;
    --hair:rgba(26,23,20,.42); --hair-soft:rgba(26,23,20,.22);
    --ferric:#c75e34;
    --display:"Fraunces","Iowan Old Style",Palatino,Georgia,serif;
    --mono:"Martian Mono",ui-monospace,"SF Mono",Menlo,monospace;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;padding:0;}
  body{
    font-family:var(--mono); color:var(--ink);
    /* the studio backdrop: a warm graphite seamless, slight top-light vignette */
    background:
      radial-gradient(120% 80% at 50% -10%, #34302a 0%, #232019 46%, #16140f 100%);
    background-attachment:fixed;
    -webkit-font-smoothing:antialiased;
  }
  /* faint film-grain over the whole backdrop so it reads photographic, not flat */
  body::before{
    content:""; position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.06;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/><feColorMatrix type='saturate' values='0'/></filter><rect width='160' height='160' filter='url(%23n)'/></svg>");
    background-size:300px 300px; mix-blend-mode:overlay;
  }
  .wrap{position:relative; z-index:1; max-width:1180px; margin:0 auto; padding:64px 40px 96px;}

  /* ===================== MASTHEAD ===================== */
  .masthead{ margin-bottom:18px; border-bottom:1.5px solid rgba(239,231,214,.22); padding-bottom:30px;}
  .mh-kicker{ font-family:var(--mono); font-size:11px; letter-spacing:.42em; text-transform:uppercase;
    color:var(--ferric); font-weight:600; display:flex; align-items:center; gap:14px;}
  .mh-kicker i{ flex:1; height:1px; background:linear-gradient(90deg,rgba(199,94,52,.6),rgba(199,94,52,0));}
  .mh-title{ font-family:var(--display); font-weight:900;
    font-variation-settings:"opsz" 144; color:var(--cream);
    font-size:clamp(40px,6.6vw,82px); line-height:.92; letter-spacing:-.022em;
    margin:18px 0 0;}
  .mh-title em{ font-style:italic; font-weight:400; color:var(--ferric); }
  .mh-sub{ display:flex; flex-wrap:wrap; gap:10px 30px; margin-top:22px;
    font-family:var(--mono); font-size:12.5px; line-height:1.65; color:rgba(239,231,214,.72);
    font-weight:300; max-width:760px;}
  .mh-sub b{ color:var(--cream); font-weight:500;}
  .mh-meta{ margin-top:20px; display:flex; flex-wrap:wrap; gap:8px;}
  .mh-meta span{ font-family:var(--mono); font-size:10px; letter-spacing:.16em; text-transform:uppercase;
    color:rgba(239,231,214,.62); border:1px solid rgba(239,231,214,.2); padding:4px 9px; font-weight:400;}
  .mh-meta span b{color:var(--ferric); font-weight:600;}

  /* ===================== VERSION SECTION ===================== */
  .version{ margin-top:74px; }
  .vhead{ display:grid; grid-template-columns:auto 1fr; gap:8px 34px; align-items:start;
    margin-bottom:30px;}
  .vmark{ grid-row:span 2; display:flex; flex-direction:column; align-items:flex-start;
    border-left:2px solid var(--ferric); padding-left:16px;}
  .vcode{ font-family:var(--mono); font-size:13px; letter-spacing:.3em; color:var(--ferric);
    font-weight:700;}
  .vname{ font-family:var(--display); font-weight:900; font-variation-settings:"opsz" 144;
    font-size:46px; line-height:.9; color:var(--cream); letter-spacing:-.01em; margin-top:2px;}
  .vblurb{ margin:0; font-family:var(--mono); font-size:12.5px; line-height:1.7; font-weight:300;
    color:rgba(239,231,214,.74); max-width:680px;}
  .vblurb::first-line{ color:rgba(239,231,214,.92); }

  .swatches{ display:flex; flex-wrap:wrap; gap:11px 22px; align-self:end; padding-top:4px;}
  .sw{ display:flex; align-items:center; gap:8px;}
  .chip{ width:22px; height:22px; border-radius:2px; box-shadow:0 0 0 1px rgba(0,0,0,.3),
    inset 0 0 0 1px rgba(255,255,255,.12);}
  .sw-txt{ display:flex; flex-direction:column; line-height:1.25;}
  .sw-txt b{ font-family:var(--mono); font-size:9.5px; letter-spacing:.13em; text-transform:uppercase;
    color:rgba(239,231,214,.82); font-weight:600;}
  .sw-txt .hex{ font-family:var(--mono); font-size:9.5px; color:rgba(239,231,214,.5);
    font-weight:300; letter-spacing:.04em;}

  /* the small row caption above each strip */
  .row-label{ display:flex; align-items:center; gap:14px; margin:34px 0 16px;}
  .row-label span{ font-family:var(--mono); font-size:10px; letter-spacing:.3em; text-transform:uppercase;
    color:rgba(239,231,214,.55); font-weight:500; white-space:nowrap;}
  .row-label i{ flex:1; height:1px; background:rgba(239,231,214,.16);}

  /* ===================== THE 4 FRONT COVERS ===================== */
  .covers{ display:grid; grid-template-columns:repeat(4,1fr); gap:20px;}
  /* one front-cover face, rebuilt to the EXACT locked Magnetic-Specimen DNA.
     The real card is 101.6 x 63.5 mm (cover panel); we hold that 1.6:1 face
     ratio and let it scale fluidly. mm-equivalents are scaled to the rendered px
     via container width; values below are tuned to read identical to the print
     card at this column width. */
  .cover{
    --spot:#c75e34;
    position:relative; background:var(--paper); color:var(--ink);
    aspect-ratio:101.6 / 63.5; overflow:hidden;
    display:flex; flex-direction:column;
    box-shadow:0 1px 0 rgba(255,255,255,.18) inset,
      0 18px 34px -16px rgba(0,0,0,.7), 0 4px 10px -4px rgba(0,0,0,.5);
    border-radius:1px;
  }
  /* paper grain, exactly as the print card */
  .cover::after{
    content:""; position:absolute; inset:0; z-index:6; pointer-events:none;
    opacity:.5; mix-blend-mode:multiply;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='120' height='120' filter='url(%23n)' opacity='0.55'/></svg>");
    background-size:34%;
  }
  .cover .spectro{ position:relative; width:100%; height:35.4%; overflow:hidden;
    background:var(--ink); border-bottom:1.6px solid var(--spot);}
  .cover .spectro-img{ position:absolute; inset:0; width:100%; height:100%;
    object-fit:cover; display:block;}
  .cover .axis{ position:absolute; left:0; top:0; bottom:0; width:7%; z-index:1;
    background:linear-gradient(90deg,rgba(26,23,20,.78),transparent);}
  .cover .anno{ position:absolute; z-index:2; font-family:var(--mono);
    color:rgba(244,239,230,.62); font-weight:300; pointer-events:none;
    text-transform:uppercase; font-size:6.2px; letter-spacing:.13em;}
  .cover .anno.f-hi{ top:4px; left:6px;}
  .cover .anno.f-lo{ bottom:4px; left:6px;}
  .cover .anno.cap{ bottom:4px; right:7px; color:var(--spot); font-weight:500; letter-spacing:.16em;}

  .cover .meat{ flex:1; position:relative; display:flex; flex-direction:column;
    padding:5.2% 6% 4.6% 6.6%; min-height:0;}
  .cover .speclabel{ display:flex; align-items:baseline; justify-content:space-between; gap:6px;
    font-family:var(--mono); font-size:6.4px; letter-spacing:.14em; text-transform:uppercase;
    color:var(--ink); font-weight:500;}
  .cover .speclabel .catno{ color:var(--spot); font-weight:700;}
  .cover .speclabel .dim{ color:var(--ink-soft); font-weight:300;}

  .cover .titlewrap{ position:relative; margin:.4% -6% 0 0; line-height:0;}
  .cover h1{ font-family:var(--display); font-weight:900;
    font-variation-settings:"opsz" 144; margin:0; color:var(--ink);
    line-height:.84; letter-spacing:-.026em; white-space:nowrap; position:relative; z-index:2;}
  .cover h1.t-short{ font-size:64px;}
  .cover h1.t-mid{ font-size:33px;}
  .cover h1.t-long{ font-size:21px; letter-spacing:-.018em; white-space:normal; line-height:.92; margin-right:6%;}
  .cover .titlewrap .ghost{ position:absolute; left:0; top:0; z-index:1;
    font-family:var(--display); font-weight:900; font-variation-settings:"opsz" 144;
    margin:0; line-height:.84; letter-spacing:-.026em; white-space:nowrap;
    color:var(--spot); opacity:.88; transform:translate(1.1px,1px);
    -webkit-text-fill-color:var(--spot);}
  .cover .titlewrap .ghost.t-short{ font-size:64px;}
  .cover .titlewrap .ghost.t-mid{ font-size:33px;}
  .cover .titlewrap .ghost.t-long{ font-size:21px; letter-spacing:-.018em; white-space:normal; line-height:.92;}

  .cover .flex{ font-family:var(--display); font-style:italic; font-weight:400;
    font-size:9px; line-height:1.1; color:var(--ink-2); margin:3% 0 0; max-width:80%;}

  .cover .footrow{ margin-top:auto; display:flex; align-items:flex-end; justify-content:space-between;
    gap:7px; padding-top:3%; border-top:.8px solid var(--hair);}
  .cover .footrow .strap{ font-family:var(--mono); font-size:5.4px; letter-spacing:.1em;
    text-transform:uppercase; color:var(--ink-soft); font-weight:400; line-height:1.5;}
  .cover .footrow .strap b{ color:var(--ink); font-weight:600;}
  .cover .tier{ flex:0 0 auto; font-family:var(--mono); font-size:5.6px; font-weight:600;
    letter-spacing:.09em; text-transform:uppercase; color:var(--spot);
    border:.8px solid var(--spot); padding:2px 4px; white-space:nowrap;}

  /* ===================== THE SHELF (case spines) ===================== */
  .shelf{ position:relative; padding:0 2px; }
  .spines{ display:flex; gap:0; align-items:flex-end; justify-content:flex-start;
    height:316px; padding-left:8px;
    filter:drop-shadow(0 24px 18px rgba(0,0,0,.55));}
  /* each spine ~ a Norelco case spine standing up: narrow (~12mm feel), tall */
  .spine{ --spot:#c75e34;
    position:relative; width:34px; height:100%;
    background:linear-gradient(95deg, #14110d 0%, #201c15 16%, #221e17 82%, #100e0a 100%);
    border-right:1px solid rgba(0,0,0,.65);
    display:flex; flex-direction:column; align-items:center;
    padding:0 0 11px; overflow:hidden;}
  .spine:first-child{ border-left:1px solid rgba(0,0,0,.55); }
  /* a hairline sheen down the case edge for plastic realism */
  .spine::before{ content:""; position:absolute; top:0; bottom:0; left:0; width:6px; z-index:4;
    background:linear-gradient(90deg, rgba(255,255,255,.13), transparent);}
  .spine::after{ content:""; position:absolute; top:0; bottom:0; right:0; width:8px; z-index:4;
    background:linear-gradient(270deg, rgba(0,0,0,.6), transparent);}
  /* the ferric SPOT cap band at the head of the spine — the unifying stripe that
     makes the across-the-set palette read at a glance down the shelf */
  .spine .s-band{ position:relative; z-index:2; width:100%; height:34px; flex:0 0 auto;
    background:var(--spot);
    box-shadow:inset 0 -1px 0 rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.14);}
  /* tiny ink ticks on the colour cap, like a metal-tape spine */
  .spine .s-band::after{ content:""; position:absolute; inset:0;
    background:repeating-linear-gradient(0deg, rgba(26,23,20,.0) 0 5px, rgba(26,23,20,.14) 5px 6px);
    mix-blend-mode:multiply; opacity:.5;}
  .spine .s-cat, .spine .s-title, .spine .s-foot{ position:relative; z-index:3;}
  .spine .s-cat{ font-family:var(--mono); font-size:7.5px; letter-spacing:.05em; font-weight:700;
    color:var(--ink); writing-mode:vertical-rl; text-orientation:mixed; transform:rotate(180deg);
    position:absolute; top:5px; left:50%; margin-left:-6px;}
  .spine .s-title{ font-family:var(--mono); font-weight:600; font-size:11px; letter-spacing:.12em;
    text-transform:uppercase; color:var(--cream);
    writing-mode:vertical-rl; text-orientation:mixed; transform:rotate(180deg);
    flex:1; display:flex; align-items:flex-start; white-space:nowrap; padding-top:12px;}
  .spine .s-foot{ font-family:var(--mono); font-size:6.5px; letter-spacing:.18em; font-weight:400;
    color:rgba(239,231,214,.55); writing-mode:vertical-rl; text-orientation:mixed; transform:rotate(180deg);
    margin-top:6px;}
  .spine .s-mv{ position:relative; z-index:3; margin-top:8px; width:14px; height:14px; border-radius:50%;
    border:1px solid var(--spot); color:var(--spot);
    font-family:var(--mono); font-size:5.5px; font-weight:700; letter-spacing:.02em;
    display:flex; align-items:center; justify-content:center;}

  /* the shelf board + cast contact shadow so the spines stand on something */
  .shelf-board{ position:relative; height:16px; margin-top:0;
    background:linear-gradient(180deg,#2a251d 0%, #1c1812 60%, #0d0b08 100%);
    box-shadow:0 1px 0 rgba(239,231,214,.08) inset, 0 14px 26px -8px rgba(0,0,0,.7);
    border-top:1px solid rgba(239,231,214,.1);}
  .shelf-board::before{ content:""; position:absolute; left:6px; right:0; top:-26px; height:26px;
    background:linear-gradient(180deg, transparent, rgba(0,0,0,.38));
    filter:blur(2px); pointer-events:none;}

  /* ===================== COLOPHON ===================== */
  .colophon{ margin-top:88px; padding-top:26px; border-top:1px solid rgba(239,231,214,.18);
    display:flex; flex-wrap:wrap; gap:18px 40px; justify-content:space-between;
    font-family:var(--mono); font-size:10.5px; color:rgba(239,231,214,.55); font-weight:300;
    letter-spacing:.04em; line-height:1.7;}
  .colophon b{ color:rgba(239,231,214,.82); font-weight:500;}
  .colophon .c-mark{ font-family:var(--display); font-weight:900; font-variation-settings:"opsz" 144;
    color:var(--ferric); font-size:14px; letter-spacing:.02em;}

  @media (max-width:760px){
    .covers{ grid-template-columns:repeat(2,1fr);}
    .vhead{ grid-template-columns:1fr;}
  }
</style>
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <div class="mh-kicker">The Magnetic Vault &nbsp;·&nbsp; Series Palette Study <i></i> for the shelf</div>
    <h1 class="mh-title">Four tapes, <em>one edition.</em></h1>
    <div class="mh-sub">
      The Magnetic Specimen inlay is <b>locked</b> — Fraunces &amp; Martian Mono, the signal
      made visible, the oversized cropped title, the bone-paper dossier. Exactly one thing
      moves between releases: the single ferric <b>spot colour</b>. Below are three curated
      palette systems for the four-cassette set, each judged the only way a buyer really
      sees it — <b>together, on a shelf</b>.
    </div>
    <div class="mh-meta">
      <span><b>BASE</b> warm-ink #1a1714 / bone #efe7d6</span>
      <span><b>TYPE</b> Fraunces · Martian Mono</span>
      <span><b>SET</b> DOOM · Willows · Grandmaster · Great Library</span>
      <span><b>VARYING</b> 1 spot colour only</span>
    </div>
  </header>

  {SECTIONS}

  <footer class="colophon">
    <div><span class="c-mark">MV</span> &nbsp; THE MAGNETIC VAULT &nbsp;·&nbsp; collection palette study</div>
    <div>DOOM band = the real master spectrogram. The other three carry a representative
      signal trace in their spot. <b>Template unchanged — spot colour only.</b></div>
    <div>Charcoal / bone duotone &nbsp;·&nbsp; <b>cassette.gille.ai</b></div>
  </footer>

</div>
</body>
</html>
"""

if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(HERE.parent)}")
