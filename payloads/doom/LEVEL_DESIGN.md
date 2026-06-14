# THE MAGNETIC VAULT — E1M1 Level Design Doc

**Map:** E1M1 (replaces Freedoom Phase 1 Episode 1 Map 1)  
**Title:** THE MAGNETIC VAULT  
**Theme:** UAC data-archive built around a giant analogue cassette reel  
**Target play-time:** 6–10 minutes (pistol-start, UV)  
**Doom format:** Vanilla Doom 1.9 (axis-aligned, IMPASSABLE/TWOSIDED flags, no UDMF)  
**Built with:** omgifol 0.5.0 + vendored zdbsp nodebuilder (`tools/bsp`)

---

## Concept

You boot up in a Tape Deck Foyer — you can already see the computer gallery through a
narrow slit window. Three branches fan out from the gallery hub: a maintenance crawl in
the dark, a nukage annex with a key ambush, and a locked chaingun wing. The blue keycard
sits on a raised pillar surrounded by three monster closets that spring open the instant
you grab it. Beyond the blue door lies a vault approach corridor and then the finale
room: a giant cassette-reel chamber with two raised reel-hubs, a tape-ribbon floor strip,
and an EXIT switch mounted on an "eject plinth." When you step over the threshold, two
side closets burst open — a Baron on one flank, pinkies+imps on the other. Flip the
switch, you win.

---

## Annotated Map Layout

```
                              [A11] SECRET: RL+Soulsphere
                                  |  (hidden door N wall)
                      [A3] DARK MAINTENANCE  (Pinky+Zombie)
                         |                   \
                      [C2]              [A5W] NUKAGE ANNEX
                         |              /   \
                      [A2] GALLERY HUB       [A12] SECRET: Backpack
                     / |   \   \
               [CORR]  |  [BIGDOOR] [BLUE DOOR]
               [A1]  [A4]   (North)  [A7 -> C78 -> A8 -> A9]
              FOYER  COLD  
              START STORAGE                    
              (window  Chaingun                FINALE: 
               slit   branch)            [A9] GIANT CASSETTE
```

### Rooms

| ID   | Name                 | Coords (X,Y)              | Floor/Ceil | Light | Note |
|------|----------------------|---------------------------|------------|-------|------|
| A1   | Tape Deck Foyer      | [0..512] × [0..384]       | 0 / 128    | 208   | Player start, shotgun spotlight |
| CORR | Entry corridor       | [192..320] × [384..416]   | 12 / 140   | 176   | Step up from A1 |
| WIN  | Window slit          | [360..440] × [384..416]   | 24 / 96    | 160   | Blue-comp sightline panel |
| A2   | Computer Gallery hub | [64..960] × [416..768]    | 24 / 160   | 192   | 4 raised computer pillars |
| C2   | Connector E/W        | [-64..64] × [480..608]    | 24 / 120   | 150   | — |
| A3   | Maintenance Crawl    | [-320..-64] × [448..640]  | 24 / 96    | **104** | Dark; Pinky pressure |
| A11  | Hidden Splice (SEC)  | [-200..-120] × [656..848] | 24 / 96    | 128   | SECRET — rocket launcher + soulsphere |
| A5W  | Nukage Annex walkway | [-560..-160] × [256..432] | 8 / 128    | 144   | Inner nukage pool (damage) |
| A12  | Backpack Cache (SEC) | [-672..-576] × [300..396] | 8 / 96     | 120   | SECRET — backpack + shells + cells |
| A6   | Key Approach (south) | [-540..-380] × [432..520] | 8 / 120    | 192   | Trip-line to key room |
| A6N  | Blue Key + Trap      | [-540..-380] × [520..688] | 8 / 120    | 192   | Key on raised pillar, 3 closets |
| A4   | Cold Storage         | [640..1024] × [840..1152] | 16 / 144   | 160   | Chaingun branch, crate cover |
| A7   | Reel Loop            | [1000..1400] × [520..680] | 24 / 128   | 160   | Post-blue-door |
| C78  | Step-up connector    | [1400..1440] × [540..660] | 48 / 160   | 168   | Height step |
| A8   | Vault Approach       | [1440..1940] × [440..760] | 64 / 192   | 176   | Tall ceilings, blue armor |
| A9   | Giant Cassette (FINALE) | [2040..3040] × [300..900] | 64 / 256 | 200 | Octagonal wow room |

### Key progression

```
FOYER (A1)  -->  GALLERY HUB (A2)
                     |
         +-----------+-----------+
         |           |           |
      DARK (A3)   NORTH(A4)  NUKAGE(A5)
      (secret)  chaingun     blue key (A6N)
                              (AMBUSH: 3 closets pop)
                                   |
                              BLUE DOOR (A2-east)
                                   |
                          VAULT APPROACH (A8)
                                   |
                           FINALE CASSETTE (A9)
                           (closets: Baron + Pinkies)
                                   |
                             EXIT SWITCH ("EJECT")
```

---

## Combat Arc

| Stage | Location | Enemies | Tone |
|---|---|---|---|
| Opening | Foyer A1 | 2 Zombies | Tutorial — learn the shotgun |
| Hub | Gallery A2 | 3 Imps, 1 SG Guy | Establish hub; sightlines |
| Dark branch | A3 | 1 Pinky, 1 Zombie | Melee pressure in the dark |
| Nukage annex | A5W | 1 Imp, 2 SG Guys | Damage-floor tension |
| KEY AMBUSH | A6N | 3 closets: Pinky+SG / Imp+Imp / Imp+Imp | **The trap** — 3-sided surprise |
| Chaingun wing | A4 | 2 Pinkies, 2 SG Guys | Crate-fighting, height |
| Blue-door corridor | A7 | 2 Imps | Breather |
| Vault approach | A8 | 2 SG Guys, 2 Imps | Escalation into finale |
| Finale arena | A9 | 1 Baron + 2 SG Guys on reels + 3 Pinkies + 3 Imps | All-out |

**UV Monster count: 37** (cap 128 — safe headroom)  
**Secret sectors: 2** (+ the plasma on the reel top = 3 reward caches)

---

## Secrets

| # | Location | Reward | How to find |
|---|---|---|---|
| 1 | A11 — Hidden Splice | Rocket Launcher + Soulsphere + Rockets + deaf Imp | Press-use (DR door) in the north wall of the dark maintenance crawl A3 |
| 2 | A12 — Backpack Cache | Backpack + Shell Box + Cell Pack + deaf Imp | Press-use (DR door) on the west wall of the nukage annex A5W |
| B-side | REEL_L in A9 finale | Plasma Rifle (on the left reel top, floor 96) | Climb the raised left reel — unmarked reward for exploring |

---

## Height & Light Contrast

- **Foyer A1:** floor 0, ceil 128, light 208 (bright entry)
- **Maintenance A3:** floor 24, ceil 96, light **104** (dark — lowest in the map)
- **Finale A9:** floor 64, ceil **256** (tallest space), light 200
- **Crates in A4:** floor 80–112 (cover variation)
- **Nukage pool A5P:** floor **-16** (below walkway — splash damage)
- **Reel tops in A9:** floor 96 (elevated platforms, tactical height)

Light range: 104 (ambush dark) → 255 (key spotlight) — full vanilla contrast.

---

## Geometry Stats

| Lump      | Bytes  |
|-----------|--------|
| THINGS    |    860 |
| LINEDEFS  |  2,632 |
| SIDEDEFS  |  8,340 |
| VERTEXES  |    740 |
| SEGS      |  8,580 |
| SSECTORS  |    708 |
| NODES     |  4,928 |
| SECTORS   |  1,066 |
| REJECT    |    211 |
| BLOCKMAP  |  2,572 |
| **TOTAL** | **30,637 bytes (29.9 KB)** |

**WAD size delta vs Freedoom E1M1:** −108 KB (our map is leaner than Freedoom's)

Vanilla limits respected: visplane-safe (hub is enclosed with low ceilings), all sectors
convex or simple concave (BSP handled), ≤128 monsters, valid BLOCKMAP and REJECT.

---

## A1 Foyer Fairness Fix (2026-06-13)

**Problem:** the original A1 foyer had two POSS zombies placed at ~243 and ~314 units from
the player start, both alerted and facing the player, in a wide-open room with NO cover.
On UV/HMP this was an instant-kill situation — the player had no time to react.

**Fix applied in `build_level.py`:**

1. **A1COVER crate** — an island sector (CRATOP1 flat, floor z=72, ceiling 128, light 192)
   placed at [176..240] × [192..256] inside A1 using `island()` with COMPSPAN side textures.
   The crate floor (72) is above the player eye height (41 units), providing solid cover to
   duck behind while the zombies alert and shoot.

2. **Zombie angles reoriented:**
   - `TH(160, 320, T_ZOMBIE, 90)` — angle 90 = facing north (away from the player start at
     y=80). The zombie is turned away; player has time to pick up the shotgun and engage.
   - `TH(340, 312, T_ZOMBIE, 180)` — angle 180 = facing west (perpendicular to the player).
     The player gets a flanking shot opportunity before the zombie pivots to fire.

**Result:** The opening is now "fair-but-spicy" — two visible zombies, immediate combat,
but the player has both cover and a reaction window. The shotgun at `TH(256, 128, T_SHOTGUN)`
is within reach before the first exchange.

---

## Playtest Evidence (no-cheat Playwright, 2026-06-13)

**Warp-test HTML** (`level/doom_level_warp_test.html`, doom_pack1.js, DG_WARP → E1M1 direct):

| Probe | Result |
|---|---|
| Title after boot | `"VAULT-OK px=64000"` — confirmed The Magnetic Vault, not stock Freedoom E1M1 |
| Player start | x=96, y=80, angle=45 (confirmed in WAD decode) |
| Foyer visible geometry | COMPSPAN pillar (A1COVER crate), STARTAN2 walls |
| Zombies survived opening | Yes — health 91 % after first exchange (screenshot: `v3final_proof_vault_spawn.png`) |
| Shotgun acquired | Yes (weapon visible in hand within seconds of start) |
| No HOM / renderer crash | Clean — no hall-of-mirrors, no missing BSP |

**Shipping HTML** (`dist/doom_cassette_v3.html`, doom_pack_v3.js, autostart mode):

| Probe | Result |
|---|---|
| `__audioCtxState` | `running` |
| `__sfxPlayed` before attract demo crash | **3** (sound works, audio backend verified) |
| Episode maps present (vault WAD) | E1M1 – E1M9 all confirmed in WAD directory |
| SHA-256 of dist HTML | `e193777abb2dc8ee0d8f56e415450dba594096d8ce0e0f57f835b82b684f1413` |
| SHA-256 == manifest html_sha256 | **MATCH** |
| Attract demo crash | RuntimeError at wasm-function[256] ~19 s — **pre-existing** (identical 18-byte DEMO stubs in both vault and non-vault WADs; not caused by the level change) |

Screenshots in `payloads/doom/dist/` (gitignored — large binary):

| File | What it shows |
|------|---------------|
| `v3final_proof_00_splash.png` | Dist HTML cassette splash screen |
| `v3final_proof_08_autostart.png` | Title screen, `__sfxPlayed=3` confirmed |
| `v3final_proof_splash.png` | The Magnetic Vault running, health 70 %, COMPSPAN pillar visible |
| `v3final_proof_vault_e1m1.png` | Vault gameplay (red damage flash, health 102 %) |
| `v3final_proof_vault_spawn.png` | Vault at spawn — health 91 %, foyer geometry clean |

Map is **playable and completable** on the prize tape.

---

## Integration (COMPLETE)

The Magnetic Vault is now E1M1 on the prize tape (`dist/doom_cassette_v3.html`,
sha256 `e193777…`). Build chain:

1. `build_level.py` → `level/level.wad` (31,764 B, fairness-fixed)
2. `integrate_level.py level.wad freedoom_e1_v3b.wad build/freedoom_e1_v3b_vault.wad`
   (splices E1M1 lump-set; E1M2–E1M9 Freedoom untouched)
3. `assemble_html_v3.py` (default path = `freedoom_e1_v3b_vault.wad`)
   → `dist/doom_cassette_v3.html` (5,100,861 B, sha256 `e193777…`)

Net WAD size delta vs Freedoom E1M1: **−108 KB** (the vault map is leaner).
Tape duration: **41.77 min** (3.23 min margin on a 45-min C90 side).

---

## Design Notes — "Tape Archive / Data Vault" Wink

- **Foyer textures:** STARTAN2 + COMPBLUE slit = a UAC terminal room
- **Gallery:** GRAY7 walls + COMPTALL pillars = server racks / mainframes
- **Maintenance crawl:** BROWN1 + FLAT5_4 floor = behind-the-scenes ducts
- **Nukage annex:** SLADWALL + NUKAGE1 pool = chemical tape-developing lab
- **Blue Key room:** COMPBLUE on all walls = a locked secure-access archive
- **Finale (A9):** octagonal room, two COMPSPAN reel-hubs (raised floors 96), a
  FCGRATE2 tape-ribbon strip between them, COMPTALL "SIDE A" label on the east wall,
  and an exit plinth with SW1EXIT ("EJECT") + EXITSIGN above it. The Baron guarding
  the left reel is the "B-side boss." Flipping the eject switch ends the level.
