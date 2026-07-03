# J-card design brief — what to finalize now (for Martin)

_Last updated: 2026-07-01. Source of truth for scope: `docs/kickstarter_planning.md`._

## The short version

The launch is **6 tapes**, sold as **two fixed 3-tape bundles**. Of the 6, **3 J-cards are
ready to finalize now** and **3 are on hold** until an engineering question resolves. The 3
ready ones sit across *both* bundles, so no complete bundle can be signed off yet — but please
start on these three; they will not change:

## ✅ Finalize now — specs are locked, will not move

| Tape | Payload size | Runtime | Cassette | Sides | Notes for the J-card |
|---|---|---|---|---|---|
| **DOOM** (flagship) | 1.47 MB | ~41.8 min | **C90** | Side A = game; **Side B** = decoded bonus album + GPLv3 source | Real-tape byte-exact proven. The hero tape — give it the strongest cover. |
| **TIC-80 / The Console** | 1.50 MB | ~40.7 min | **C90** | Single side | "A games console on a cassette" — 16 carts. |
| **Great Library + reader** | 1.02 MB | ~27.7 min | **C90** | Single side (+ GPLv3 eSpeak-ng source ships alongside) | 9 classics read aloud by a robotic voice. Titles: Alice in Wonderland · A Christmas Carol · Jekyll & Hyde · The Metamorphosis · The Fall of the House of Usher · The Masque of the Red Death · The Yellow Wallpaper · A Study in Scarlet · The Time Machine. |

All three are **single-side C90** (Great Library uses 62% of one side), proven, no dependency on
the open engineering work below. Side A/B copy is final for these.

## ⏸️ On hold — do NOT start these yet

Spec numbers (runtime, side A/B split) are **not final** for the three below. They each need a
single logical payload split across both tape sides, and that pattern isn't built/proven yet —
so the exact side-A/side-B breakdown Martin would print on the J-card could still change.

| Tape | Approx size | Likely cassette | Why held |
|---|---|---|---|
| **v86 Linux** | 2.54 MB | C90, both sides | Payload spans both sides — split not yet proven |
| **chess-GPT** | 3.02 MB | C90, both sides (thin margin) | Same |
| **Svenska / Den svenska samlingen** | 1.92 MB | **C60**, both sides | Same, and it's the only C60 (different shell size) |

I'll release these for design the moment the split-payload work lands.

## How the 3 ready tapes map onto the two bundles

- **Bundle 1 — "Boot & Play"** (DOOM · v86 Linux · TIC-80): **2 of 3 ready** — DOOM ✅, TIC-80 ✅,
  v86 held. Finalizing DOOM + TIC-80 clears most of this bundle.
- **Bundle 2 — "Read & Reason"** (Great Library + reader · chess-GPT · Svenska): **1 of 3 ready**
  — Great Library ✅, chess-GPT + Svenska held.

So the practical focus for now is the **three individual J-cards above (DOOM, TIC-80, Great
Library)**. Bundle-level artwork (a shared sleeve/outer for each 3-tape set, if we do one) has to
wait until all three tapes in that bundle are locked.

---

## Manufacturer template (skivtryck / DiscRepublic) — adapt all artwork to these dielines

Pulled from https://skivtryck.se/product/kassettband/ → "Mallar" (2026-07-03). Local copies of the
dieline PDFs live in `docs/skivtryck_templates/`. **Design to these exact geometries** — the artwork
is a fill inside a fixed die, not a free canvas.

### J-card dielines (all: 101 mm tall, **13 mm spine**, **2 mm bleed**, double-sided OUTSIDE+INSIDE = 4+4 colour)

| Template | Flat page | OUTSIDE panel order (left→right), widths | Best for |
|---|---|---|---|
| **JC11** (1 panel) | **103 × 101 mm** | Back **25** ‖ Spine **13** ‖ Front **65** | Too tight for a data tape (no room for decode instructions) — avoid |
| **JC21** (2 panels) | **166 × 101 mm** | Back **25** ‖ Spine **13** ‖ Front **65** ‖ +1 **63** | Budget option: cover + one inner panel |
| **JC31** (3 panels) | **227 × 101 mm** | Back **25** ‖ Spine **13** ‖ Front **65** ‖ +1 **63** ‖ +2 **61** | **Recommended default** — fits contents list *and* decode guide |

INSIDE prints the mirror of the same panels (hidden until the card is unfolded). Fold lines sit
between every panel. Spine text **≥ 6.5 pt**. Extra panels fold accordion-style behind the front.

### Recommended panel map (uniform design system across the 6 tapes) — JC31

| Panel | Size (mm) | Content |
|---|---|---|
| **Front** (OUTSIDE) | 65 × 101 | Flavour cover art + title + "THE MAGNETIC VAULT" wordmark + format badge (e.g. `C90 · SIDE A`) |
| **Spine** | 13 × 101 | Vertical lockup `THE MAGNETIC VAULT · DOOM · C90` (≥6.5 pt) |
| **Back** (OUTSIDE) | 25 × 101 | Slim back edge: edition no., short URL, "DATA CASSETTE" mark |
| **+1 panel** | 63 × 101 | **Contents** — DOOM side-B album tracklist / TIC-80's 16 carts / Great Library's 9 titles |
| **+2 panel** | 61 × 101 | **"How to read this tape"** — 3-step decode + companion-PWA URL + deck/line-quality note (this is the self-decoder expectation-setter, ties to Linear MAG-14) + GPLv3 source notice |
| **INSIDE** (all) | — | Liner notes / project story / QR to decoder / credits (Martin + Magnus) / full GPL — or a single flood colour to save ink |

The **Front panel is 65 × 101 mm (≈ portrait 0.64)** — design every cover to that aspect ratio, art
bleeding to the 2 mm bleed line, all vital elements inside the clearance/safe zone.

### On-shell label (UV print) — `Labels_uv_print.pdf`, 96.35 × 42.25 mm die

Cassette-shaped die with reel-window + hub cutouts; usable print band ≈ **54.5 × 12.5 mm** centred
between the hubs. Template **COLOUR: Transparent / Black / White** — this is the hook for the
**transparent-shell + laser-etch** idea (Linear MAG-17): a white/black UV mark on a clear shell over
a laser-etched pattern reads strongly. Keep the label layout hub-aware.

### Hard print specs (from `Kassettinfo.pdf` — bake into every export)

- **Resolution** 300 ppi at 1:1 · **Colour** CMYK · **ICC** ISO Coated v2 (FOGRA39)
- **Fonts** embed or convert to outlines · **Templates** remove all template/guide lines before export
- **Bleed** 2 mm · **Min text** 6.5 pt · Do NOT flatten/merge template lines with artwork
- **Audio delivery** DDP preferred (also accepts uncompressed .WAV / .AIFF) — relevant for how we
  hand them the side-A/B data signal

### Open cost question (for the skivtryck reply thread)
The base product lists "J-card (4+4 colour)" — **confirm whether the base price is JC11 (1-panel) and
JC21/JC31 are add-ons**, since the recommended 3-panel default changes unit cost across up to 6 SKUs.

> **Note on scope:** the above is *structural template adaptation* (dieline geometry, panel mapping,
> print specs) — the scaffolding artwork drops into. It is **not** cover-art work, which stays on
> **HOLD** (Linear MAG-19) until the tech is validated on more players.
