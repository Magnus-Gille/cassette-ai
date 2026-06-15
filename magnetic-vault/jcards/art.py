"""
art.py — faithful Python port of the bespoke inline-SVG label art from
magnetic-vault/assets/releases.js (function relArt).

Every release in the shop gets a hand-drawn cassette-inlay "spine art" panel,
drawn on a 320x180 (16:9) board and scaled to fit. The J-card reuses the EXACT
same art so the printed inlay matches the storefront card. This module mirrors
relArt() switch-by-kind; if the JS art changes, mirror the change here.

The one cosmetic difference vs. the web: print art omits the CSS `reel-spin`
animation classes (paper does not spin) but keeps the identical geometry.
"""
import math


def _reel(cx, cy, r, col):
    spokes = "".join(
        f'<line x1="{cx + math.cos(math.radians(a)) * r * 0.42:.2f}" '
        f'y1="{cy + math.sin(math.radians(a)) * r * 0.42:.2f}" '
        f'x2="{cx + math.cos(math.radians(a)) * r * 0.85:.2f}" '
        f'y2="{cy + math.sin(math.radians(a)) * r * 0.85:.2f}" '
        f'stroke="{col}" stroke-width="2"/>'
        for a in (0, 60, 120, 180, 240, 300)
    )
    return (
        f'<g style="transform-origin:{cx}px {cy}px">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{col}" stroke-width="2.5"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r * 0.34:.2f}" fill="{col}"/>'
        f"{spokes}</g>"
    )


def _base(kind, accent, inner):
    return (
        f'<svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" role="img" aria-hidden="true">'
        f'<defs><linearGradient id="g_{kind}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#2b2620"/><stop offset="1" stop-color="#17130e"/>'
        f"</linearGradient></defs>"
        f'<rect width="320" height="180" fill="url(#g_{kind})"/>'
        f'<rect width="320" height="180" fill="{accent}" opacity="0.05"/>'
        f"{inner}</svg>"
    )


def rel_art(kind, accent=None):
    c = accent or "#e6a24c"
    grid = "".join(
        f'<line x1="{20 + i * 35}" y1="20" x2="{20 + i * 35}" y2="160" '
        f'stroke="{c}" stroke-width="0.5" opacity="0.12"/>'
        for i in range(9)
    )

    if kind == "doom":  # demon-sigil mark + reels
        inner = (
            f"{grid}{_reel(70, 90, 30, c)}{_reel(250, 90, 30, c)}"
            f'<g transform="translate(160,90)" fill="none" stroke="{c}" stroke-width="3">'
            f'<path d="M0,-34 L26,-6 L18,30 L-18,30 L-26,-6 Z"/>'
            f'<circle cx="-9" cy="-2" r="4.5" fill="{c}"/><circle cx="9" cy="-2" r="4.5" fill="{c}"/>'
            f'<path d="M-13,14 Q0,24 13,14" stroke="{c}"/></g>'
            f'<text x="160" y="160" text-anchor="middle" fill="{c}" '
            f'font-family="ui-monospace,monospace" font-size="11" letter-spacing="4" opacity="0.8">BYTE-EXACT</text>'
        )
    elif kind == "vu":  # VU meter
        ticks = "".join(
            f'<line x1="{160 + math.cos(math.radians(-50 + i * 10)) * 108:.2f}" '
            f'y1="{150 + math.sin(math.radians(-50 + i * 10)) * 108:.2f}" '
            f'x2="{160 + math.cos(math.radians(-50 + i * 10)) * 122:.2f}" '
            f'y2="{150 + math.sin(math.radians(-50 + i * 10)) * 122:.2f}" '
            f'stroke="{"#c0492b" if i > 7 else c}" stroke-width="{2.5 if i > 7 else 1.5}"/>'
            for i in range(11)
        )
        inner = (
            f"{grid}"
            f'<path d="M40,140 A120,120 0 0 1 280,140" fill="none" stroke="{c}" stroke-width="2" opacity="0.4"/>'
            f"{ticks}"
            f'<line x1="160" y1="150" x2="{160 + math.cos(math.radians(-15)) * 100:.2f}" '
            f'y2="{150 + math.sin(math.radians(-15)) * 100:.2f}" stroke="#f4efe6" stroke-width="2.5" '
            f'style="transform-origin:160px 150px"/>'
            f'<circle cx="160" cy="150" r="6" fill="{c}"/>'
            f'<text x="248" y="60" fill="#c0492b" font-family="ui-monospace,monospace" font-size="13" font-weight="700">+3</text>'
            f'<text x="160" y="172" text-anchor="middle" fill="{c}" font-family="ui-monospace,monospace" '
            f'font-size="10" letter-spacing="3" opacity="0.8">YOUR DECK</text>'
        )
    elif kind == "book":  # open self-narrating book + soundwave
        lines = "".join(
            "".join(
                f'<line x1="{s * 8}" y1="{y}" x2="{s * 48}" y2="{y}" stroke-width="1.4" opacity="0.7"/>'
                for y in (-18, -8, 2)
            )
            for s in (-1, 1)
        )
        wave = "".join(
            (lambda h: f'<rect x="{-100 + i * 10}" y="{-h / 2:.2f}" width="3" height="{h:.2f}" '
                       f'rx="1.5" fill="{c}" opacity="0.85"/>')(4 + abs(math.sin(i * 0.9)) * 14)
            for i in range(21)
        )
        inner = (
            f"{grid}{_reel(255, 42, 18, c)}"
            f'<g transform="translate(160,84)" stroke="{c}" stroke-width="2" fill="none">'
            f'<path d="M-58,-30 Q-30,-38 0,-30 Q30,-38 58,-30 L58,34 Q30,26 0,34 Q-30,26 -58,34 Z"/>'
            f'<line x1="0" y1="-30" x2="0" y2="34"/>{lines}</g>'
            f'<g transform="translate(160,150)">{wave}</g>'
        )
    elif kind == "console":  # pixel arcade + d-pad
        pix = "".join(
            f'<rect x="{-62 + (i % 15) * 8}" y="{-24 + (i // 15) * 10}" width="6" height="6" '
            f'fill="{c}" opacity="{(i * 7 % 5) / 5 * 0.7 + 0.15:.3f}"/>'
            for i in range(60)
        )
        inner = (
            f"{grid}{_reel(60, 46, 18, c)}{_reel(260, 46, 18, c)}"
            f'<g transform="translate(160,92)">'
            f'<rect x="-72" y="-34" width="144" height="68" rx="8" fill="none" stroke="{c}" stroke-width="2.5"/>'
            f"{pix}</g>"
            f'<g transform="translate(160,154)" fill="{c}">'
            f'<rect x="-20" y="-3" width="40" height="6" rx="3"/><rect x="-3" y="-12" width="6" height="24" rx="3"/>'
            f'<circle cx="44" cy="0" r="5"/><circle cx="60" cy="0" r="5"/></g>'
        )
    elif kind == "chess":  # crown/knight + board
        board = "".join(
            (f'<rect x="{-54 + (i % 6) * 18}" y="{-54 + (i // 6) * 18}" width="18" height="18" '
             f'fill="{c}" opacity="0.18"/>') if ((i % 6) + (i // 6)) % 2 == 0 else ""
            for i in range(36)
        )
        inner = (
            f"{grid}{_reel(60, 46, 18, c)}{_reel(260, 46, 18, c)}"
            f'<g transform="translate(110,150)">{board}'
            f'<rect x="-54" y="-54" width="108" height="108" fill="none" stroke="{c}" stroke-width="1.5" opacity="0.5"/></g>'
            f'<g transform="translate(205,86)" fill="none" stroke="{c}" stroke-width="3">'
            f'<path d="M-16,34 L16,34 L13,4 Q22,-2 14,-14 Q24,-26 6,-30 Q10,-38 0,-42 Q-12,-34 -10,-22 '
            f'Q-26,-16 -16,-2 Q-22,4 -16,8 Z" stroke-linejoin="round"/>'
            f'<circle cx="-2" cy="-22" r="2.5" fill="{c}"/></g>'
        )
    elif kind == "library":  # stack of book spines + count
        spines = "".join(
            f'<rect x="{i * 18}" y="{(i % 3) * 4}" width="13" height="{100 - (i % 4) * 8}" '
            f'rx="2" fill="none" stroke="{c}" stroke-width="2" opacity="{0.5 + (i % 3) * 0.18:.2f}"/>'
            for i in range(13)
        )
        inner = (
            f"{grid}{_reel(265, 40, 16, c)}"
            f'<g transform="translate(40,30)">{spines}</g>'
            f'<text x="160" y="168" text-anchor="middle" fill="{c}" '
            f"font-family=\"'Iowan Old Style',Palatino,serif\" font-size=\"26\" font-style=\"italic\" opacity=\"0.95\">58 books</text>"
        )
    elif kind == "svenska":  # flag-tinted spine + label
        inner = (
            f"{grid}{_reel(60, 46, 18, c)}{_reel(260, 46, 18, c)}"
            f'<g transform="translate(160,96)">'
            f'<rect x="-70" y="-26" width="140" height="52" rx="5" fill="none" stroke="{c}" stroke-width="2"/>'
            f'<line x1="-26" y1="-26" x2="-26" y2="26" stroke="{c}" stroke-width="6" opacity="0.7"/>'
            f'<line x1="-70" y1="-2" x2="70" y2="-2" stroke="{c}" stroke-width="6" opacity="0.7"/>'
            f'<text x="22" y="6" text-anchor="middle" fill="{c}" '
            f"font-family=\"'Iowan Old Style',serif\" font-size=\"15\" font-style=\"italic\">SV / EN</text></g>"
            f'<text x="160" y="160" text-anchor="middle" fill="{c}" font-family="ui-monospace,monospace" '
            f'font-size="9" letter-spacing="3" opacity="0.75">LAGERLÖF</text>'
        )
    elif kind == "shelf":  # gift-ribbon shelf
        books = "".join(
            f'<rect x="{x - 7}" y="{-30 + (i % 2) * 6}" width="14" height="{64 - (i % 2) * 6}" '
            f'rx="2" fill="none" stroke="{c}" stroke-width="2" opacity="0.8"/>'
            for i, x in enumerate((-44, -22, 0, 22, 44))
        )
        inner = (
            f"{grid}{_reel(60, 46, 18, c)}{_reel(260, 46, 18, c)}"
            f'<g transform="translate(160,96)">{books}'
            f'<path d="M-2,-40 Q-22,-52 -14,-36 Q-2,-44 0,-30 Q2,-44 14,-36 Q22,-52 2,-40 Z" '
            f'fill="{c}" opacity="0.9"/></g>'
            f'<text x="160" y="166" text-anchor="middle" fill="{c}" font-family="ui-monospace,monospace" '
            f'font-size="9" letter-spacing="3" opacity="0.75">A GIFT</text>'
        )
    else:
        inner = f"{_reel(80, 90, 34, c)}{_reel(240, 90, 34, c)}"

    return _base(kind, c, inner)
