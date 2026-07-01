# Kickstarter planning — physical cassette campaign

Status: flavour set + cassette-length requirements now resolved; several engineering/vendor
validation gates still open. Session 2026-07-01 (major update — see bottom sections).

## Manufacturer

[skivtryck.se](https://skivtryck.se/product/kassettband/) — Swedish cassette duplication/printing
shop. Includes shell, recording/duplication, full-color A/B labels, J-card (4+4 color), case,
shrinkwrap; O-card and colored shells are add-ons. Pricing is a JS calculator on their site, no
static prices published.

**Real quotes received (2026-07-01, ex moms/unit):**

| Qty | C45 | C90 |
|---|---|---|
| 50 | 127 kr | 137 kr |
| 100 | 90 kr | ~99.5 kr (estimated, not quoted) |
| 200 | 74.50 kr | ~84 kr (estimated, not quoted) |
| 300 | 63.67 kr | 72.67 kr |

C45→C90 premium is a roughly fixed **+9–10 kr/unit** surcharge (not a percentage) — confirmed at
both the 50-unit and 300-unit real data points. 100/200-unit C90 figures are our own interpolation,
not quoted.

**Config gotcha found in every quote screenshot so far:** `Ljudoptimering` (audio optimization) was
set to **"Ja"** — this is very likely wrong for us (see risk section below) and needs an explicit
fresh quote/confirmation with it off.

**Open questions — email sent to skivtryck 2026-07-01** (Swedish, via Outlook, to
`info@skivtryck.se`), covering: disable audio optimization entirely + confirm flat 1:1 dub +
real-time vs high-speed duplication; a one-off test/reference cassette from our own supplied WAV;
whether the qty-discount tier is per-SKU or pooled across a mixed order (~2x cost swing either
way); combining multiple lengths (C45/C60/C90) in one order; how side-A/side-B content is
delivered to them (one file vs two); freight cost for bulk shipment over the ~20kg threshold;
and whether they have backer-level fulfillment experience/recommendations. **Awaiting reply.**

## Critical technical risk: commercial duplication is an unproven channel

All of this project's real-tape proofs (see top-level CLAUDE.md / `REAL_DECODE_FINDINGS.md`) were
tuned against home-deck recording with controlled levels (Dolby NR off, record ~7.0, no
processing). skivtryck's listed "audio optimization service" is built for music and could degrade
or break a data-bearing tone signal (EQ/compression/NR). **Before any committed order:**

1. Ask for a one-off test/reference cassette dub (not the full 50-unit MOQ) from a supplied WAV.
2. Tell them explicitly it's a data signal, not music — ask them to disable any audio
   optimization/processing and dub as close to 1:1 as their hardware allows.
3. Ask whether their duplication is real-time (1:1 speed) or high-speed.
4. Use `experiments/tape_v2/fullspectrum_master.py` output as the test content — it grades the
   whole rate ladder (R-1 floor combo-MFSK through R3 stereo D2X) under one sync, so one test
   cassette tells you which bps tier survives their actual production chain. Decode with
   `fullspectrum_decode.py` / `analyze_master2.py` when it comes back.

This gates everything downstream — which bps tier (and therefore which flavours/file sizes) is
safe to promise backers.

## Curated launch flavour set (LOCKED, 2026-07-01)

Revised from the 2026-06-30 draft after checking real build status against `payloads/BUILT_PAYLOADS.md`
and reasoning from first principles (flagship + one deliberate risk-bet + low-risk breadth,
avoiding redundant concepts). Final six:

1. **DOOM** — flagship, real-tape byte-exact proven (2026-06-13). Needs a full C90 side.
2. **Great Library + narrated reader** — trimmed to 9 short/novella classics (Alice in Wonderland,
   A Christmas Carol, Jekyll & Hyde, The Metamorphosis, The Fall of the House of Usher, The Masque
   of the Red Death, The Yellow Wallpaper, A Study in Scarlet, The Time Machine) after the original
   58-book/17.16 MB corpus was found to need ~8 hours of playback — commercially dead. Bundled with
   the eSpeak-ng robotic-voice reader (English-only, ~522 KB engine). Rebuilt 2026-07-01, final
   bundle **1,021,256 bytes**, fits one C90 side (1.66 MB budget) at 62% utilization. Willows was
   dropped as a standalone SKU (redundant "book read aloud" concept) — its narration feature lives
   on here instead. GPLv3 source (eSpeak-ng) ships alongside, same pattern as DOOM's side-B bundle.
3. **v86 Linux** ("boots a full PC from a cassette") — already built and measured (2.54 MB,
   `v86_linux` in BUILT_PAYLOADS.md), just missing a shop/J-card release entry. The deliberate
   marketing risk-bet, but lower engineering risk than first assumed since the payload itself is done.
4. **Grandmaster / chess-GPT** (4.5M, "plays chess and beats Stockfish-low") — built, already has a
   shop release. Covers the "AI on tape" hook; a standalone tiny-LLM story tape was deliberately
   NOT built as a separate flavour (redundant, harder to demo than chess, unbuilt).
5. **TIC-80 / The Console** ("a games console on a cassette," 16 carts) — built, already has a shop release.
6. **Svenska / "Den svenska samlingen"** (Selma Lagerlöf, bilingual) — confirmed actually built,
   license-verified, roundtrip-ok (1.92 MB) despite being missing from `BUILT_PAYLOADS.md`'s table
   (stale-doc omission, not an incomplete build). Kept for the Swedish-press angle.

Dropped from the earlier draft: standalone Willows (absorbed into Great Library), standalone
tiny-LLM story tape (redundant with chess-GPT), v86/story-tape-as-the-only-risk-bets framing.
SmolLM2-135M-Instruct ("chat with a cassette," real modern Apache-2.0 LLM) stays parked as a
stretch-goal — over budget at 43–60 MB vs. a ~34 MB dream-tape ceiling, needs int2/ternary
quantization work not yet done.

## Shipping scope — NOT DECIDED, open question

**Not settled as EU-only.** Magnus wants to keep worldwide shipping on the table if the logistics
and tax questions can be solved at reasonable cost/complexity — EU-only is a fallback, not the
plan. Decision is deferred until fulfillment quotes (below) come back.

Relevant facts gathered:
- skivtryck does **not** offer backer-level fulfillment, only bulk-ship to one address.
- US suspended the $800 de minimis exemption for **all** countries as of 2025-08-29 — every
  US-bound parcel now faces customs duties/paperwork regardless of value. This is the main
  worldwide-shipping complication to solve or explicitly disclose to backers (DDU framing).
- EU VAT: OSS registration only needed above €10,000/year EU-wide distance sales; below that,
  normal Swedish VAT rules apply — likely fine for a first campaign at this scale, but confirm
  with the accountant/Fortnox setup.
- Kickstarter supports per-reward shipping-destination restriction natively (not a workaround) if
  EU-only or EU+UK+NO+CH ends up being the answer.

**Fulfillment vendors to quote** (ask: "~300-900 units across up to 6 SKUs, bulk receipt from a
Swedish manufacturer, worldwide backer-level pick-pack-ship, pledge-manager integration —
BackerKit/Crowdox"):
- **Waredock** — has an actual Sweden node, EU-wide reach.
- **Fulfillment Europe (F4E)** — Scandinavia-focused, daily pick/pack.
- **Floship** — crowdfunding specialist, Crowdox/BackerKit-integrated, now has EU warehouses
  (Germany, Netherlands) instead of routing through Asia. No published pricing; genuinely unclear
  whether 300-900 units clears their typical minimums (built for thousand-plus-backer campaigns).

All three are quote-only — get real numbers before deciding worldwide vs EU-only, and before
trusting any profit projection below.

## Cassette length per flavour (resolved 2026-07-01)

Only **two bps tiers are real-tape-proven**: ~4910 bps mono (fully proven, the DOOM tape) and
~9820 bps independent stereo (proven only with the *same* payload on both channels — the
genuinely useful independent-per-channel split is still open/pending). Budget against the 4910
mono number; treat 9820 as aspirational for now.

| Payload | Size | Runtime @ 4910 bps | Cassette needed |
|---|---|---|---|
| DOOM | 1.47 MB | ~41.8 min | C90, one side |
| Great Library + reader | 1.02 MB (trimmed) | ~27.7 min | C90, one side (62% utilization) |
| v86 Linux | 2.54 MB | ~69 min | C90, **both sides** |
| chess-GPT | 3.02 MB | ~82 min | C90, **both sides** (thin margin) |
| TIC-80 | 1.50 MB | ~40.7 min | C90, one side |
| Svenska | 1.92 MB | ~52 min | Doesn't fit one C90 side; fits both sides of a **C60** |

## Open engineering gap: splitting one payload across both tape sides

Three of six flavours (v86 Linux, chess-GPT, Svenska) assume a single logical payload can be
**split across a side-flip** and reassembled on decode. **This has never been built or proven.**
The only shipped real-tape pattern (DOOM) puts *different* content on side A vs B (game vs.
decoded album + GPL source) — not one continuation. Until this is built and proven, these three
flavours' cassette-length assumption is unverified; the fallback if it doesn't pan out is the same
move already made on Great Library — trim to fit one side.

## Consumer-hardware validation (open, in progress)

The 4910 bps proof (DOOM, 2026-06-13) assumed a specific, favorable setup: Type-II CrO₂ C90 tape,
**acoustic** capture (deck speaker → air → iPhone Voice Memos), Dolby NR off, record ~7.0,
playback ~55 — on Magnus's own unnamed "known-good" deck (n=1, not brand-identified, not a random
consumer unit). Two more real data points since:

- **Grundig C4100** (worn 1970s mono portable) — real acoustic captures exist
  (`vm_grundig_39/40.wav`). Result: **fails ALL wideband rungs** — the limit is bandwidth
  (~≤2.4 kHz), not flutter (flutter was fine, 0.5–0.9%). The narrowband floor rung built to survive
  decks like this (~1129 net bps) is **far too slow for any of the six flavours** (DOOM alone would
  need ~173 min at that rate) — a deck like this is a hard no-go for every flagship title,
  regardless of skivtryck's duplication quality. Reinforces bundling a "Deck Test" tape with every
  reward tier so backers can check their hardware before/on arrival.
- **"We Are Rewind"** (newly bought, modern, currently-sold consumer deck — a much more
  representative sample than the Grundig or the unnamed reference unit) — first test (2026-06-30)
  failed, but inconclusively: root cause traced to a ~2.48x playback-duration stretch from a
  real-time recording stall (CoreAudio/`afplay` hiccup during the burn), reproduced identically on
  the known-good deck too. **Needs a clean re-burn** (disable sleep, close other audio apps, watch
  Console.app for coreaudiod hiccups) and re-test before this deck has a real verdict. A pass here
  would be meaningful (a nameable, currently-sold product, not an edge case); a failure would be a
  serious signal, unlike the Grundig case.
- **Planned third data point:** a cheap deck purchase in progress (Blocket used market, or a
  budget new-manufactured unit like "Studio 57," ~742 SEK — reviewed as "poor audio quality," which
  would test a third failure mode: modern-but-cheaply-made, distinct from old-worn or
  known-good/We-Are-Rewind).

This is layered on top of, and independent from, the still-untouched skivtryck duplication-chain
risk (below) — a clean deck test says nothing about whether skivtryck's actual commercial dub
process preserves the signal, and vice versa.

## Pricing model

```
unit_cost      = duplication+print cost (real skivtryck number, at the qty tier actually hit)
               + packaging (~15 SEK/unit assumed) + ~5% defect/spares buffer
platform_take  = Kickstarter 5% + payment processing ~3-5%  →  budget ~9% off the top
backer_price   = unit_cost / (1 − platform_take − target_margin)   [used 35% target margin]
```
Shipping charged separately per region/at cost, not baked into pledge price.

**Reward-structure net-profit scenarios** (2026-07-01, using real C90 pricing at 50/300 units,
estimated at 100/200, 15 kr/unit packaging + 5% buffer, 9% platform take, ~50 kr/order fulfillment
placeholder — no real fulfillment quote exists yet):

| Reward structure | Most expensive (40 backers) | Medium (200 backers) | Runaway success (450 backers) |
|---|---|---|---|
| 1 tape (DOOM only), 249 SEK | ~680 SEK (~$65) | ~14,500 SEK (~$1,380) | ~42,600 SEK (~$4,060) |
| 2×3 bundles, 670 SEK each | ~3,200–7,800 SEK (~$310–740) | ~39,800–66,800 SEK (~$3,790–6,360) | ~115,500–170,400 SEK (~$11,000–16,230) |
| Full library (all 6), 1,195 SEK | ~3,200–17,900 SEK (~$305–1,700) | ~82,800–132,800 SEK (~$7,880–12,650) | ~245,700–330,500 SEK (~$23,400–31,500) |

Ranges are `[no per-SKU pooling – full pooling]` where the skivtryck pooling question (still open,
email sent) matters. **Structural insight independent of that answer:** full-library concentrates
volume per SKU better than splitting into two bundles (every SKU gets the full backer count's
worth of orders, vs. ~half in the 2×3 split) — it's the safer bet at low backer counts even before
pooling is resolved. This is a small-scale, low-risk hobby project economically either way — real
upside, capped at this volume.

### The two 3×-tape bundles (fixed, not mix-match)

Backers pick a *fixed* bundle, never any-3-of-6 — a free pick would be C(6,3) = 20 pick-pack
combinations (a fulfillment nightmare); two fixed bundles collapse that to 2 SKUs. Split chosen
on a "runnable vs. readable" theme:

- **Bundle 1 — "Boot & Play"** (the interactive, demo-on-screen tapes): **DOOM · v86 Linux ·
  TIC-80**. Everything here boots into something you watch/play — the tapes you'd run live at a booth.
- **Bundle 2 — "Read & Reason"** (the rest): **Great Library + reader · chess-GPT · Svenska**.
  The books-and-brains half: two literature tapes plus the AI.

Notes carried from the design discussion:
- **Bundle 1 carries both headliners** (DOOM, the flagship, *and* v86 Linux, the marketing
  risk-bet) — so it's the stronger seller. Bundle 2's top draw is chess-GPT. Position/price Bundle 1
  as the hero bundle rather than pretending the two are equal.
- **Gating: one split-payload-across-sides–gated tape in each** — Bundle 1 waits on v86, Bundle 2
  waits on chess-GPT + Svenska. Neither bundle finalizes fully until that engineering gap (below)
  resolves; DOOM/TIC-80/Great Library are the ready-now members.
- **Formats are mixed within each bundle** (no single-spec bundle): Bundle 1 = two 1-side C90
  (DOOM, TIC-80) + one both-sides C90 (v86); Bundle 2 = one 1-side C90 (Great Library) + one
  both-sides C90 (chess-GPT) + one both-sides C60 (Svenska).

## Martin Ackerfors (J-cover design) — collaboration structure

- **Tool:** Linear (personal API key generated and verified 2026-07-01; board/issues not yet built
  — paused mid-setup for the product-scope work above). Chosen over Google Docs/Sheets (blocked —
  Magnus's Advanced Protection Program setting kills third-party OAuth apps like `gws`, no
  exception for self-built apps) and over MS365 (works, but clunkier comments/status UX). Native
  status/assignee/comment fields need zero manual config, unlike a spreadsheet.
- **Design finalization gating:** finalize DOOM, TIC-80, and Great Library now (all proven,
  single-side C90, no dependency on the split-payload-across-sides gap below — Great Library's
  numbers became final this session once its rebuild was verified). Hold spec-table numbers and
  side-A/B copy for v86 Linux, chess-GPT, and Svenska until that engineering gap resolves.
- **His rate:** found via Fortnox (voucher A41, fiscal year 1, 2025-11-03: "737 Ackerfors
  illustration," 938 kr incl. moms / 750 kr ex moms for a one-off illustration job). Hours unknown
  (Magnus's best guess: 1–2h, likely 1.5h) → implies **~375–750 kr/h**, midpoint ~500 kr/h. Not
  confirmed as an hourly rate — was a lump payment for a different (illustration, not J-card)
  engagement. **Still needs confirming directly with Martin** before locking a design budget line.

## Open items / next steps

1. ~~Get the test/reference cassette from skivtryck~~ — **email sent 2026-07-01** covering this
   plus every other open skivtryck question (audio processing, pooling, mixed lengths, side A/B
   format, freight, fulfillment). Awaiting reply.
2. Clean re-burn + re-test on "We Are Rewind" (watch for audio interruptions this time).
3. Buy a third test deck for hardware-diversity data (Blocket or a cheap new unit like Studio 57).
4. Build/prove the split-payload-across-both-sides engineering pattern (v86 Linux, chess-GPT, Svenska).
5. Get quotes from Waredock, F4E, Floship — sized for worldwide if possible; still zero real numbers.
6. Decide worldwide vs EU(+UK/NO/CH)-only shipping once 1/5 are answered. **Not yet decided.**
7. Confirm Kickstarter project currency options (native SEK vs EUR/USD).
8. Check Swedish VAT/OSS threshold status with accountant before launch.
9. Confirm Martin Ackerfors' actual hourly rate directly (currently an unconfirmed ~500 kr/h estimate).
10. Build the Linear tracker board (project, states, issues) and send Martin his prioritized brief
    (DOOM + TIC-80 + Great Library first; v86 Linux/chess-GPT/Svenska held for engineering validation).
