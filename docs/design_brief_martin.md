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
