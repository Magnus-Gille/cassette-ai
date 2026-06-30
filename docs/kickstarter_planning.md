# Kickstarter planning — physical cassette campaign

Status: early planning, no decisions locked except the curated flavour set. Session 2026-06-30.

## Manufacturer

[skivtryck.se](https://skivtryck.se/product/kassettband/) — Swedish cassette duplication/printing
shop. Includes shell, recording/duplication, full-color A/B labels, J-card (4+4 color), case,
shrinkwrap; O-card and colored shells are add-ons. Pricing is a JS calculator on their site, no
static prices published.

**Real quote received:**

| Qty | Price/unit | Total |
|---|---|---|
| 50 | 134 SEK | 6,700 SEK |
| 300 | 67 SEK | 20,100 SEK |

**Open question with them (critical, ~2x swing on cost):** does the volume-discount tier apply
per individual SKU/artwork, or pooled across a mixed order of several flavours? Also still need
the 100/200-unit tier pricing, and freight cost for bulk shipment over the free <20kg threshold
(300+ units likely exceeds it).

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

## Curated launch flavour set (decided)

Picked for audience spread, not just tier rank, from `payloads/BUILT_PAYLOADS.md`:

1. DOOM tape (hero/flagship, already proven byte-exact off real tape; side B = source/album)
2. A tiny-LLM story tape (stories260K or delphi-llama2-12.8m)
3. chess-GPT (4.5M, "plays chess and beats Stockfish-low")
4. TIC-80 ("a games console on a cassette," 16 carts)
5. v86 Linux ("boots a full PC")
6. A corpus tape (Great Library or Human Knowledge — archival/preservation appeal)

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

## Pricing model

```
unit_cost      = duplication+print cost (real skivtryck number, at the qty tier actually hit)
               + packaging (~15 SEK/unit assumed) + ~5% defect/spares buffer
platform_take  = Kickstarter 5% + payment processing ~3-5%  →  budget ~9% off the top
backer_price   = unit_cost / (1 − platform_take − target_margin)   [used 35% target margin]
```
Shipping charged separately per region/at cost, not baked into pledge price.

**Funding floor**, 6-flavour curated set at 50-unit MOQ each (300 cassettes total):

| Scenario | Print cost | + packaging/pledge-mgr/buffer | Minimum goal |
|---|---|---|---|
| Conservative (no pooling) | 40,200 SEK | +~13,300 | **~53,500 SEK (~$5,100)** |
| Optimistic (pooled to 300-tier) | 20,100 SEK | +~11,400 | **~31,500 SEK (~$3,000)** |

**Suggested tiers** (conservative cost basis, will shift once real fulfillment cost is known):
Single 249 SEK (~$24) · 3-pack 670 SEK (~$64) · Collector's set (all 6) 1,195 SEK (~$114) ·
digital-only/no-physical-reward ~50 SEK (~$5).

**Income range (gross business profit, pre-tax, pre-fulfillment-fee-confirmation):**

| Scenario | Backers | Net income |
|---|---|---|
| Pessimistic | ~40, barely funds | ~0–5,000 SEK (~$0–500) |
| Realistic | ~150–250 | ~20,000–40,000 SEK (~$1,900–3,800) |
| Optimistic | ~400–500+ | ~80,000–120,000 SEK (~$7,600–11,400) |

This is a small-scale, low-risk hobby project economically, not a living — upside is real but
capped at this volume.

## Open items / next steps

1. Get the test/reference cassette from skivtryck (fullspectrum master, no processing) — gates
   which bps tier is safe to promise.
2. Ask skivtryck: per-SKU vs pooled pricing, 100/200-unit tier numbers, bulk-freight cost >20kg.
3. Get quotes from Waredock, F4E, Floship — sized for worldwide if possible.
4. Decide worldwide vs EU(+UK/NO/CH)-only shipping once 1-3 are answered. **Not yet decided.**
5. Confirm Kickstarter project currency options (native SEK vs EUR/USD).
6. Check Swedish VAT/OSS threshold status with accountant before launch.
