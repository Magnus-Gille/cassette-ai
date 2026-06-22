"""
art.py — MINIMAL ICON SYSTEM for THE MAGNETIC VAULT J-cards.

A unified, abstract pictogram set. Every release is ONE clean geometric glyph,
drawn in a single style on a shared 200x200 grid: a monoline (single stroke
weight) mark in ferric-amber on charcoal, with lots of negative space. No
literal illustration — these read like app-icon / transit-pictogram marks.

Design rules (keep these invariant across all glyphs):
  * viewBox 0 0 200 200, centred safe area inset ~34 px (glyph lives in ~132 px).
  * one ink colour (the release `accent`, default ferric #e6a24c) on charcoal.
  * stroke-only monoline, STROKE_W weight, round caps/joins; tiny solid accents
    (dots) allowed for emphasis. No gradients inside the glyph, no text.
  * the charcoal field carries one faint corner reel-dot motif so the set reads
    as a family (the "tape" tell) without clutter.

This module is the SINGLE SOURCE for the icon system; it is structured so each
glyph is a small pure function returning an SVG body string, ready to be
mirrored back into assets/releases.js relArt() later (same viewBox, same maths).
"""

# ---- design tokens ---------------------------------------------------------
FIELD = "#211d18"        # charcoal field
INK = "#e6a24c"          # default ferric-amber ink (overridden by accent)
STROKE_W = 7.0           # the one monoline weight
VB = 200                 # square viewBox


def _field(accent):
    """The shared charcoal field + faint family motif (two corner reel-dots).
    Kept extremely quiet so the glyph owns the composition."""
    return (
        f'<rect width="{VB}" height="{VB}" rx="22" fill="{FIELD}"/>'
        # faint family motif: two reel pin-dots, top corners, very low contrast
        f'<circle cx="26" cy="26" r="3.2" fill="{accent}" opacity="0.22"/>'
        f'<circle cx="174" cy="26" r="3.2" fill="{accent}" opacity="0.22"/>'
    )


def _wrap(body, accent):
    """Compose a finished icon SVG from a glyph body."""
    a = accent or INK
    return (
        f'<svg viewBox="0 0 {VB} {VB}" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-hidden="true">'
        f'{_field(a)}'
        f'<g fill="none" stroke="{a}" stroke-width="{STROKE_W}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</g>'
        f'</svg>'
    )


# ---------------------------------------------------------------------------
# DOOM glyph options — abstract, NOT a literal demon face.
# Each returns just the inner monoline body (the _wrap adds field + stroke).
# ---------------------------------------------------------------------------

def _doom_chevron(a):
    """Option A — DESCENT CHEVRONS. Three nested downward angle brackets: the
    iconic FPS 'forward / down into the level' arrow, abstracted. Reads as
    motion + threat without a face. Clean, instantly legible at thumbnail size."""
    return (
        '<path d="M62 70 L100 104 L138 70"/>'
        '<path d="M62 100 L100 134 L138 100"/>'
        # solid keystone dot — the 'lock-on' focus
        f'<circle cx="100" cy="156" r="5.5" fill="{a}" stroke="none"/>'
    )


def _doom_sigil(a):
    """Option B — CONTAINMENT SIGIL  (CHOSEN). A ring with a single inscribed
    downward triangle and a centred dot: an abstract warding mark. Geometric,
    ominous, symmetric — but no eyes, no mouth. Reads instantly as 'contained
    threat' = the Vault holding DOOM. The inverted triangle is a classic
    occult/hazard glyph, so it carries the DOOM mood while staying abstract."""
    return (
        '<circle cx="100" cy="100" r="58"/>'
        '<path d="M70 82 L130 82 L100 138 Z"/>'
        f'<circle cx="100" cy="100" r="6" fill="{a}" stroke="none"/>'
    )


def _doom_bolt(a):
    """Option C — VAULT BOLT. A bracketed square (the vault / cartridge) split
    by a single hard diagonal bolt — energy / breach. Squares + one slash:
    very app-icon, very minimal."""
    return (
        # bracketed frame (open corners = 'vault door ajar')
        '<path d="M58 78 L58 58 L78 58"/>'
        '<path d="M122 58 L142 58 L142 78"/>'
        '<path d="M142 122 L142 142 L122 142"/>'
        '<path d="M78 142 L58 142 L58 122"/>'
        # the bolt
        '<path d="M114 64 L84 102 L106 102 L86 136"/>'
    )


_DOOM_OPTIONS = {
    "chevron": _doom_chevron,   # A
    "sigil": _doom_sigil,       # B
    "bolt": _doom_bolt,         # C
}
# The chosen DOOM mark (see contact sheet screenshots/doom_icon_options.png):
DOOM_CHOICE = "sigil"


# ---------------------------------------------------------------------------
# The rest of the catalog — one clean abstract glyph each, same system.
# DOOM is the one nailed; these are sensible family members.
# ---------------------------------------------------------------------------

def _g_vu(a):
    """deck-test — a single needle swept across a quarter arc + tick. Meter,
    abstracted to one gauge stroke."""
    return (
        '<path d="M48 138 A60 60 0 0 1 152 138"/>'
        '<path d="M100 138 L132 88"/>'
        f'<circle cx="100" cy="138" r="6" fill="{a}" stroke="none"/>'
        f'<circle cx="138" cy="78" r="3.5" fill="{a}" stroke="none"/>'
    )


def _g_book(a):
    """willows — an open book as two facing arcs over a spine line. Minimal."""
    return (
        '<path d="M100 70 Q72 58 50 66 L50 134 Q72 126 100 138"/>'
        '<path d="M100 70 Q128 58 150 66 L150 134 Q128 126 100 138"/>'
        '<line x1="100" y1="70" x2="100" y2="138"/>'
    )


def _g_console(a):
    """console — a d-pad cross inside a rounded frame. Pure pictogram."""
    return (
        '<rect x="52" y="62" width="96" height="76" rx="12"/>'
        '<path d="M100 84 L100 116"/>'
        '<path d="M84 100 L116 100"/>'
        f'<circle cx="131" cy="92" r="4.5" fill="{a}" stroke="none"/>'
        f'<circle cx="131" cy="110" r="4.5" fill="{a}" stroke="none"/>'
    )


def _g_chess(a):
    """grandmaster — a crown reduced to three points + base. Abstract regalia."""
    return (
        '<path d="M60 132 L140 132"/>'
        '<path d="M64 122 L58 78 L82 104 L100 70 L118 104 L142 78 L136 122 Z"/>'
    )


def _g_library(a):
    """great-library — three book spines, varied height. Stacked rectangles."""
    return (
        '<rect x="60" y="76" width="20" height="64" rx="3"/>'
        '<rect x="90" y="62" width="20" height="78" rx="3"/>'
        '<rect x="120" y="86" width="20" height="54" rx="3"/>'
    )


def _g_svenska(a):
    """svenska — an offset cross (Nordic flag cross), single stroke. Clean."""
    return (
        '<rect x="52" y="62" width="96" height="76" rx="10"/>'
        '<line x1="86" y1="62" x2="86" y2="138"/>'
        '<line x1="52" y1="104" x2="148" y2="104"/>'
    )


def _g_shelf(a):
    """modern-shelf — a gift bow: two loops + knot. Abstract ribbon."""
    return (
        '<path d="M100 100 Q66 72 70 100 Q66 128 100 100"/>'
        '<path d="M100 100 Q134 72 130 100 Q134 128 100 100"/>'
        f'<circle cx="100" cy="100" r="6" fill="{a}" stroke="none"/>'
        '<path d="M100 106 L82 140"/>'
        '<path d="M100 106 L118 140"/>'
    )


def _g_default(a):
    """fallback — a single reel ring + hub. The house mark."""
    return (
        '<circle cx="100" cy="100" r="50"/>'
        f'<circle cx="100" cy="100" r="12" fill="{a}" stroke="none"/>'
    )


_GLYPHS = {
    "vu": _g_vu,
    "book": _g_book,
    "console": _g_console,
    "chess": _g_chess,
    "library": _g_library,
    "svenska": _g_svenska,
    "shelf": _g_shelf,
}


def rel_art(kind, accent=None):
    """Return the icon SVG for a release `kind`. Single source of truth for the
    minimal icon system. DOOM uses the chosen abstract mark (DOOM_CHOICE)."""
    a = accent or INK
    if kind == "doom":
        body = _DOOM_OPTIONS[DOOM_CHOICE](a)
    elif kind in _GLYPHS:
        body = _GLYPHS[kind](a)
    else:
        body = _g_default(a)
    return _wrap(body, a)


def doom_option_svg(name, accent=None):
    """Render a named DOOM option in isolation (for the contact sheet)."""
    a = accent or INK
    return _wrap(_DOOM_OPTIONS[name](a), a)
