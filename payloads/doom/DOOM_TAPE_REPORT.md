# DOOM on a Cassette — Ship Report

*(V1 report below, kept intact. The **V2 "looks-like-DOOM" upgrade** — real
Freedoom E1 maps, monsters, weapons — is appended at the bottom: see
**"V2 — DOOM that LOOKS like DOOM"**.)*

**Date:** 2026-06-12 · **Status:** SHIPPED (ready to burn)
**The artifact:** `/Users/magnus/repos/cassette-ai/payloads/doom/dist/doom_cassette.html` — a single
self-contained HTML file containing playable DOOM (WASM engine + permissively-licensed IWAD, raw
bytes, zero network), 583,617 B raw → **161.4 KB** as the tape-codec lzma blob.
**The tape:** `/Users/magnus/repos/cassette-ai/experiments/tape_v2/doom_ship/m10doom_master.wav` —
12.38 min at the proven 2572 net bps rung; self-check decode is **byte-exact**.
**SHA-256 (html, also in tape manifest):** `b3ec11ca6357a66068960883648de97a979a0ec98e490e67039e3f4a1c883802`

---

## 1. What was built

### Engine — doomgeneric → WASM (size-optimized split build)

- **Source:** `/Users/magnus/repos/cassette-ai/payloads/doom/doomgeneric/` — pristine git clone of
  [ozkl/doomgeneric](https://github.com/ozkl/doomgeneric) (GPL-2.0), upstream HEAD `dcb7a8d`
  (2026-04-12 "boolean fix"). Modified sources copied into `build/src/`; upstream tree untouched.
- **Toolchain:** Emscripten **6.0.0** from the local emsdk at
  `/Users/magnus/repos/cassette-ai/tools/emsdk` (gitignored; no brew/sudo/system mutation).
- **Build:** `/Users/magnus/repos/cassette-ai/payloads/doom/build/build_split.sh` →
  `build/pack/doom_pack.js` (23,236 B) + `build/pack/doom_pack.wasm` (320,733 B). Key choices:
  - `-Oz -flto --closure 1`, `-sMALLOC=emmalloc`, fixed 64 MB memory (`ALLOW_MEMORY_GROWTH=0`),
    `-sSUPPORT_LONGJMP=0`, `-sASSERTIONS=0`, `-sENVIRONMENT=web` — every flag chosen for size.
  - **Split** js+wasm (no `-sSINGLE_FILE`, no `--embed-file`): the wasm and the WAD travel as *raw
    bytes* in the HTML carrier (see §1.3) instead of base64, saving ~18–38% post-lzma.
  - `-sINCOMING_MODULE_JS_API=[wasmBinary,preRun]`: the shell hands the decoded wasm to
    `Module.wasmBinary` (zero fetches → works on `file://`); a `--pre-js pre_wad.js` hook writes the
    WAD into MEMFS *inside* the closure unit (the `FS` export does not survive closure renaming).
  - `DG_IWAD_PATH="/doom2.wad"`: miniwad is not in `d_iwad.c`'s `iwads[]` table; serving it as
    `doom2.wad` selects commercial/Doom II mode, matching its MAP01–MAP32 lump set.
  - Sound off (no `FEATURE_SOUND`) — the WAD carries stub `DS*` lumps + GENMIDI, but omitting the
    audio backend shrinks the WASM. Resolution 320×200, custom `doomgeneric_wasm.c` backend.

### WAD — miniwad (Freedoom-derived, BSD 3-clause)

Full provenance dossier: `/Users/magnus/repos/cassette-ai/payloads/doom/build/WAD_PROVENANCE.md`.

- **`mini.wad`** = verbatim `miniwad.wad` by **Simon Howard** (*fragglet*, Chocolate Doom
  maintainer), <https://github.com/fragglet/miniwad>, prebuilt zip fetched 2026-06-11 from
  `soulsphere.org/random/miniwad.zip`
  (zip SHA-256 `b4c98043…f80b2393`, wad SHA-256 `daed5e9d…c186fbfb`). 230,497 B raw.
- **License:** BSD 3-clause (Freedoom project copyright, 2001-2018) — permissive, product-safe.
  **No proprietary or shareware id Software content** anywhere in the chain; every lump is
  Freedoom-derived or purpose-made stub data.
- **Validated** (`build/validate_wad.py`, PASS): valid IWAD header, 2,438 lumps, 32 complete
  Doom II maps, all boot-critical lumps present (PLAYPAL…GENMIDI, 626 sprites, title demo loop).
  All maps are the same small box room by design — boots and plays in any port.
- **Why not a freedoom1.wad E1M1 trim:** measured asset closure was ~1.6–2.0 MB raw (~0.8–1.2 MB
  lzma) — over the tape cap before the engine is even counted. miniwad is 33.5 KB lzma'd.

### Assembly — the windows-1252 rawpack carrier

`/Users/magnus/repos/cassette-ai/payloads/doom/build/assemble_html.py` (+ `rawpack.py`) emits ONE
HTML file. The page is declared `<meta charset="windows-1252">`, in which every byte 0x00–0xFF maps
to exactly one code point — so the wasm and WAD sit as **raw bytes** inside non-executable
`<script type="o">` blocks, read back via `.textContent`. Only three byte values can't survive the
HTML parser (0x00, 0x0D, the 0x01 escape) plus `</script`/`<!--` sequences; the encoder does a
bijective byte swap against the payload's rarest bytes (within the same high-3-bit class, keeping
lzma's `lc=3` literal contexts intact), then escapes the rare leftovers. Measured lzma penalty:
**+2.1%** on the wasm vs base64's +37.7%. Round-trip verified for all 256 byte values + adversarial
sequences in Chromium (http:// and file://) and Safari (file://).

The page itself: GPL/BSD attribution comment in `<head>` (full miniwad license text reproduced),
cassette-styled splash with click-to-start (`#autostart` hash skips the click), the closure'd engine
JS inlined in a `startDoom()` wrapper, and a canvas-pixel poller that sets
`document.title='DOOM-OK px=N'` / `body[data-doom=ok]` once the engine renders — the automated
verification hook.

---

## 2. Size ledger vs budgets

Budgets (compressed payload = what goes on tape): **HARD CAP 530 KB** (C60 side at 2572 bps minus
sync overhead) · **TARGET ≤ 500 KB** · **STRETCH ≤ 370 KB**.

| Item | Size |
|---|---|
| `doom_cassette.html` raw | 569.9 KB (583,617 B) |
| — engine wasm (raw, inside) | 313.2 KB |
| — engine js (raw, inside) | 22.7 KB |
| — WAD (raw, inside) | 225.1 KB |
| gzip(html) (reference) | 206.7 KB |
| lzma preset-9 (budget yardstick) | 161.1 KB |
| **lzma 9-extreme via tape codec (`h9_payload_codec`, on tape)** | **161.4 KB (165,264 B)** |

**Verdict: 161.4 KB on tape = 30% of the hard cap, 44% of the stretch goal.** The artifact beats
the most aggressive budget by 208 KB — enough headroom to later add sound, real Freedoom maps, or a
second payload, and still fit one C60 side.

---

## 3. Playability proof

Verified in a real browser (Playwright; both `file://` and http://) — see screenshots in
`/Users/magnus/repos/cassette-ai/payloads/doom/dist/`:

- **`proof_boot_r0.png`** — engine booted to in-game MAP01 view (3D renderer + status bar live).
- **`proof_gameplay_r0.png`** — after input: player moved/fired, HUD ammo count changed (49),
  perspective shifted — the game *plays*, not just renders.
- Supporting: `screenshot_splash.png` (cassette splash), `screenshot_menu.png` /
  `screenshot_enter_menu.png` (menu opens), `screenshot_fire.png`, `screenshot_map01_moved.png`,
  `screenshot_file_webkit.png` + `screenshot_file_chromium.png` (**file:// double-click works in
  both engines** — no server needed).

The page's own `data-doom=ok` / `DOOM-OK px=N` hook (canvas pixel poller) confirmed rendering
programmatically in every run.

---

## 4. The tape — m10doom ship master

All deliverables in `/Users/magnus/repos/cassette-ai/experiments/tape_v2/doom_ship/`:

| File | What |
|---|---|
| `m10doom_master.py` | Encoder (builds the master WAV from `dist/doom_cassette.html`) |
| `m10doom_master.wav` | **The ship master: 742.8 s = 12.38 min**, 48 kHz FLOAT, peak 0.70 per SOP |
| `m10doom_decode.py` | Decoder (capture WAV → `doom_decoded.html`, sha256-verified) |
| `play_doom_tape.sh` | Operator playback script with the burn checklist baked in |
| `m10doom_manifest.json` | Frame/codeword manifest incl. CRC32-per-codeword + payload sha256 |
| `m10doom_dense375.bin` | Packed payload sidecar (165,264 B H9PC-lzma blob) |
| `results/m10doom_results_selfcheck.json` | Blocking self-check result (PASS) |
| `results/m10doom_results_sim_s0.json` | Channel-sim sanity data point (expected FAIL, see below) |

### Encode configuration — the proven rung, verbatim

Exactly the **m9_m8_dense375** rung, read verbatim from `m9_ladder.json` with hard assertions and
built through `m9_master.make_scheme`: **DQ_P22_N512_sp4**, `min_spacing_hz=375`, **RS(255,159)**,
gross 4125 / **net 2572.1 bps**. m9 framing reused 1:1 — global chirp pair + front Schroeder sounder
+ per-frame 0.25 s preamble + 0.12 s gaps + CRC32-per-codeword manifest guard. ONE continuous
payload section: **520 frames / 1040 codewords** — no ladder, no P1/P2 probes.

Payload: `doom_cassette.html` 583,617 B raw → 165,264 B H9PC-lzma blob (−71.7%). Note: the default
pyenv python lacks `_lzma`, so encoder and decoder carry a small subprocess bridge to
`/usr/bin/python3` producing a byte-identical `h9_payload_codec` H9PC-lzma container (auto-pick
semantics preserved; decode bridges identically).

Decoder reuses `m9_decode._decode_dqpsk_section` (resampling-PLL front-end + EMA fallbacks +
erasure sweep, CRC-guarded) and `analyze_master2` global sync via import; writes
`doom_decoded.html` and verifies sha256 against both the manifest hash and the dist file.

### Self-check (blocking) — PASS, byte-exact

Encode → decode the clean WAV → **BYTE-EXACT. 0/1040 codewords failed**, front-end
`resampling_pll`, sha256 `b3ec11ca6357…883802` equals the dist file. Verified twice, exit 0.
(`results/m10doom_results_selfcheck.json`.)

### Channel-sim sanity — FAIL, honest, non-blocking, *expected*

`channel_v2(tape7, aac=False, diffuse_gain=0.58, seed 0)` → 650/1040 RS codewords failed (best
front-end ema0.6), not byte-exact. This matches the rung's known history: m9_m8_dense375 is the rung
the sim **cannot** validate (flagged `HOLD-by-rule-sim-unvalidated-<750Hz` — the sim's flutter-ICI
model over-penalizes 375 Hz carrier spacing). The m9 dress rehearsal showed the identical pattern
(seed 0 FAIL, seed 1 PASS) while the **REAL tape9 capture decoded this exact rung BYTE-EXACT, 0/1040
codewords failed**, via resampling_pll (`m9_results_tape9_run1.json`). Sim is 5–8× pessimistic vs
real tape; data point recorded, not a blocker.

### Duration budget

12.38 min total (8.57 min payload at 2572 bps + 3.8 min framing/sync overhead) ≤ 29 min C60-side
budget — **16.6 min margin**. Fits one side of a C60 easily.

### Burn SOP (do not skip)

1. **Dolby NR OFF** at record AND playback. **Record level ~7.0** (8.5 saturates → IMD floor).
2. C60 side A loaded, fully rewound, leader spooled past. Start the deck **recording first**.
3. Run `bash /Users/magnus/repos/cassette-ai/experiments/tape_v2/doom_ship/play_doom_tape.sh`
   (it prints the checklist, waits for ENTER, then `afplay`s the master).
4. Let the **full** master play to the end down-chirp (a sync anchor); run the deck ~2 s past, stop.

### Decode SOP

1. Play tape back (speaker ~55, rms ~0.04, no clip). Capture on **iPhone Voice Memos** (lossless,
   sample-accurate clock — never Mac live-capture). Start the phone first, ~1 s lead-in, record to
   past the end chirp. File auto-syncs via iCloud as `.qta`.
2. `ffmpeg -hide_banner -loglevel error -y -i "<file>.qta" -ac 1 -ar 48000 capture.wav`
3. `python3 /Users/magnus/repos/cassette-ai/experiments/tape_v2/doom_ship/m10doom_decode.py capture.wav`
   → writes `doom_decoded.html`, verifies sha256 against the manifest. Double-click → play DOOM.

Housekeeping: `.gitignore` gained `experiments/tape_v2/doom_ship/*.wav` and
`…/doom_decoded.html` (large/regenerable, repo convention).

---

## 5. License compliance matrix

| Component | License | Where | Obligations met / required |
|---|---|---|---|
| doomgeneric engine (+ `doomgeneric_wasm.c` backend, build scripts) | **GPL-2.0** | wasm+js inside the HTML | Attribution comment in HTML `<head>`. **Complete corresponding source must accompany distribution** — the plan: binary on side A, source archive on side B (or GPL §3 written offer / URL in liner notes). Source = engine sources as built (`build/src/`), backend, build + assembly scripts. |
| miniwad / Freedoom assets | **BSD 3-clause** | `mini.wad` inside the HTML | Copyright notice + full license text **already reproduced verbatim** in the HTML head comment (from `build/miniwad/COPYING.adoc`). Must not use the Freedoom name to endorse the product. |
| Emscripten JS/wasm runtime support code | **MIT** (Emscripten's own license) | linked into `doom_pack.js`/`.wasm` | Include the MIT copyright notice in distribution credits. |
| Original id Software content | — | **NONE present** | No doom1.wad / shareware / retail lumps anywhere in the artifact or its inputs. |

**A commercial distribution must include:** (1) the GPL-2.0 license text + complete corresponding
source for the engine build (side B / written offer / URL — pick one and document it on the liner);
(2) the Freedoom BSD notice (already embedded in the artifact itself); (3) the Emscripten MIT
notice; (4) no GPL-incompatible added restrictions on the HTML file as a whole (the combined page
ships effectively under GPL-2.0 terms).

---

## 6. Honest gaps + next steps

1. **No physical burn yet.** The self-check is encode→decode on the clean master WAV; the chain to
   a *real* C60 (burn → play → Voice Memos capture → decode) has not been run for *this* master.
   The identical rung decoded byte-exact from real tape in the m9 campaign (tape9, 0/1040 cw), so
   confidence is high — but the headline claim isn't earned until the physical loop closes.
   **Next:** burn per §4 SOP, capture, decode, archive the results JSON.
2. **The channel sim cannot validate this rung** (375 Hz spacing; flutter-ICI model over-penalizes).
   Known, documented, evidenced as 5–8× pessimistic vs real tape — but it means the only pre-burn
   gate is the clean-WAV self-check. A sim fix (or a calibrated 375 Hz ICI model from the tape9
   capture) would restore an independent gate.
3. **Gameplay is minimal by design.** miniwad's 32 maps are the same small box room — it boots,
   renders, moves, shoots, but it isn't a *level*. With 208 KB of stretch headroom: graft 1–2 real
   Freedoom map geometries into miniwad (omgifol + texture remap, est. +20–60 KB compressed).
4. **No sound** (`FEATURE_SOUND` off to shrink the WASM; the WAD carries stub `DS*` lumps).
   Headroom exists to revisit.
5. **Side B source archive not yet assembled.** The GPL plan ("source on side B") is stated but the
   archive (engine src + scripts, lzma'd, second master WAV) hasn't been built. Required before any
   distribution beyond personal use. Estimated comfortably within a C60 side B at 2572 bps.
6. **Environment wart:** pyenv python lacks `_lzma`; the subprocess bridge to `/usr/bin/python3` is
   byte-identical but adds a moving part. Worth pinning in repo docs or fixing the pyenv build.
7. The big WAVs (`m10doom_master.wav`, `_sim_doom_s0.wav`) are gitignored and regenerable from
   `m10doom_master.py`, but the master used for an actual burn should be backed up (or its sha256
   recorded) so the burned tape stays decodable against a known manifest.

---
---

# V2 — DOOM that LOOKS like DOOM (2026-06-12)

**Status:** SHIPPED, self-check byte-exact (tape gate "partial" on duration only — see §V2.4)
**The artifact:** `/Users/magnus/repos/cassette-ai/payloads/doom/dist/doom_cassette_v2.html` —
1,974,000 B raw → **589.9 KB** lzma preset-9, within the 600 KB hard cap.
**SHA-256:** `4a88dd1489548ea4cfef6c93dc04f9c3eec92064ecf2da259c39574dc1ae1023`
(`dist/doom_cassette2.html`, the assembler's direct output, is byte-identical; `_v2` is the
canonical copy the tape encoder reads.)
**The tape:** `…/experiments/tape_v2/doom_ship/m10doom2_master.wav` — 43.99 min at the proven
2572 net bps rung; self-check decode **byte-exact, 0/3803 codewords failed**.
**V1 (`doom_cassette.html`, sha `b3ec11ca…`) is retained intact as the fallback** — nothing in the
v1 chain was modified.

## V2.1 What changed — miniwad → freedoom_trim.wad

V1 proved the pipeline but used miniwad (225 KB placeholder): flat untextured box rooms, no weapon
sprite, no monsters. The budget was then **re-derived from cassette physics** (see §V2.2) and the
headroom spent on assets. One new component, three thin variants — v1 files untouched:

| Component | v1 | v2 |
|---|---|---|
| WAD | `mini.wad` 230,497 B (placeholder) | **`build/freedoom_trim.wad` 1,616,811 B** — real Freedoom E1 content, sha256 `7c072573…d63cacb`, built by `build/trim_freedoom.py` from Freedoom 0.13.0 phase 1 (`freedoom1.wad`, BSD-3) |
| Engine pack | `pack/doom_pack.js/.wasm` (`/doom2.wad`, commercial mode) | `pack/doom_pack1.js` (23,237 B) + `doom_pack1.wasm` (320,733 B) via `build_split_doom1.sh` + `pre_wad1.js` — **only** difference is `DG_IWAD_PATH=/doom1.wad`, so `d_iwad.c` picks gamemission=doom and the E1-only lump set selects shareware mode |
| Assembler | `assemble_html.py` | `assemble_html2.py` (same windows-1252 rawpack carrier; Freedoom BSD-3 text embedded in `<head>`) |

**What `freedoom_trim.wad` keeps** (lump-audit verified; full dossier in
`build/WAD_PROVENANCE.md` §V2):

- **Maps:** real Freedoom **E1M1 + E1M2** with full BSP (141.9 / 139.3 KB of map data);
  E1M3–E1M9 are 351-B "THE END" stubs so no progression path hits a missing lump.
- **Monsters:** zombieman (POSS), shotgun guy (SPOS), imp (TROO), demon (SARG) — front-rotation-only
  sprites (Jaguar-DOOM style), 231 sprite frames / 61 prefixes total.
- **Weapons:** fist, pistol, shotgun, chaingun (+ rocket projectile frames).
- **Look:** 71 TEXTURE1 entries, 56 patches, 35 flats (the true closure of what E1M1/E1M2 + the
  shareware switch/anim/finale tables reference), real TITLEPIC.
- **Sounds stripped:** all 214 `DS*`/`DP*` lumps reduced to stubs (16.5 KB total, real PCM gone),
  14 `D_*` music stubs (868 B), GENMIDI kept (boot-required), DMXGUS dropped. The engine has no
  sound backend (v1 decision, unchanged), so this is free savings.

## V2.2 Size ledger vs budgets

Budgets re-derived from cassette physics (supersede V1 §2's 530/500/370 figures): at 2572 net bps
the all-in cost incl. framing is ~0.00427 s/byte ⇒ **C60 side ≈ 388 KB · C90 side ≈ 622 KB** of
lzma payload. **HARD CAP: artifact lzma-9 ≤ 600 KB** (C90 side with margin) · **TARGET ≤ 380 KB**
(C60 side, bonus not requirement).

| Item | Size |
|---|---|
| `doom_cassette_v2.html` raw | 1,927.7 KB (1,974,000 B) |
| — WAD (raw, inside) | 1,578.9 KB (1,616,811 B; 457.1 KB lzma standalone) |
| — engine wasm (raw, inside) | 313.2 KB (320,733 B) |
| — engine js (raw, inside) | 22.7 KB (23,237 B) |
| **lzma preset-9 (budget yardstick)** | **589.9 KB (604,072 B)** |
| lzma 9-extreme via tape codec (`h9_payload_codec`, on tape) | 590.4 KB (604,532 B) |

**Verdict: 589.9 KB = 98.3% of the 600 KB hard cap — PASS.** The C60 target (380 KB) is
deliberately not met: the brief was maximize DOOM-feel within the C90 cap. v1 (161.4 KB) remains
the C60 option. Note the cap squeaker has a consequence on tape duration — §V2.4.

## V2.3 Playability proof — it looks like DOOM now

Verified in a real browser; screenshots in `/Users/magnus/repos/cassette-ai/payloads/doom/dist/`
(the page's `data-doom=ok` / `DOOM-OK px=N` canvas hook confirmed rendering in every run):

- **`v2_proof_a_textures.png`** — E1M1 hangar boot: real wall textures (tech panels, hazard
  stripes), grated-floor flat, **pistol weapon sprite up**, full status bar (AMMO 50, HEALTH 100%).
- **`v2_proof_walk1.png`** — player moved through the level; perspective/geometry change.
- **`v2_proof_c_monster.png`** — a Freedoom zombieman at close range in a textured corridor;
  player has taken damage (HEALTH 94%) — **monsters exist and fight back**.
- **`v2_proof_d_firing.png`** — pistol **muzzle flash mid-shot**, a monster corpse on the floor,
  AMMO 49 / HEALTH 49%, blood-spattered face on the HUD.
- **`v2_proof_d_after_fire.png`** — post-shot frame of the same exchange.
- Supporting (assembly-time runs): `proof_v2_boot_e1m1.png`, `proof_v2_gameplay_fire.png`.

Flat gray box rooms → textured hangar with monsters, weapon sprite, working combat. That was the
entire point of v2.

## V2.4 The tape — m10doom2 ship master

Thin wrappers importing the **blessed v1 modules unchanged**, overriding only paths/names
(all in `/Users/magnus/repos/cassette-ai/experiments/tape_v2/doom_ship/`):

| File | What |
|---|---|
| `m10doom2_master.py` | Rebinds `m10doom_master` globals (HTML_PATH=`dist/doom_cassette_v2.html`, WAV/MANIFEST/SIDECAR/SECTION names) and calls v1 `build()`. **One documented deviation:** v1's hard length-assert rebound 29 → 45.0 min (physical C90 side) so a valid tape isn't destroyed by an assert; the 43- and 29-min planning gates are measured and printed instead. |
| `m10doom2_master.wav` | **The v2 ship master: 2639.3 s = 43.99 min**, peak 0.70 per SOP (gitignored) |
| `m10doom2_decode.py` | Rebinds `m10doom_decode` MANIFEST/DECODED/WAV paths, calls the proven v1 `decode()` chain unchanged → `doom2_decoded.html` |
| `play_doom_tape_v2.sh` | Operator SOP script (chmod +x); **notes a C90 tape is required** |
| `m10doom2_manifest.json` | Frame/codeword manifest incl. CRC32-per-codeword + payload sha256 |
| `m10doom2_dense375.bin` | Packed payload sidecar (604,532 B H9PC-lzma blob) |
| `results/m10doom_results_m10doom2_master.json` | Blocking self-check result (PASS) |

### Encode — identical proven config (m9_m8_dense375, verbatim)

**DQPSK P22 N512 sp4, RS(255,159), min_spacing 375 Hz, gross 4125 / net 2572.1 bps.** Input
`doom_cassette_v2.html` 1,974,000 B (sha256 `4a88dd14…1ae1023`) → H9PC lzma **604,532 B packed
(590.4 KB, −69.4%)** → **1902 frames / 3803 codewords** → `m10doom2_master.wav` 2639.3 s =
**43.99 min**, effective 6049.8 bps on the HTML.

### Self-check (blocking) — PASS, byte-exact

Clean no-channel decode of the master WAV: clock 1.0000×, align +0; **RS codewords failed
0/3803** (front-end `resampling_pll`, erase_frac 0.0); packed byte-exact; unpack OK; decoded HTML
1,974,000 B, **sha256 matches dist v2 EXACTLY** (independently re-verified with `shasum`).
VERDICT BYTE-EXACT, exit 0.

### Duration vs side budgets — and the constraint conflict

| Gate | Budget | v2 | Fits? |
|---|---|---|---|
| Physical C90 side | 45.0 min | 43.99 min | **YES, 1.0 min margin** |
| C90-with-margin planning gate | 43.0 min | 43.99 min | NO (by 0.99 min) |
| C60 side | 29.0 min | 43.99 min | NO (v1 covers this) |

The tape gate reads "partial" **only** because of the 43-min planning gate — and that miss is
**mathematically forced by the spec, not the implementation**: measured all-in cost is
0.004366 s/byte (1.37245 s per 318-B frame + 29 s fixed sync), slightly above the 0.00427
planning figure, so 43.0 min ⇔ packed ≤ 590,844 B ⇔ artifact lzma ≤ ~577 KB — but the 600 KB
hard cap *permits* artifacts that pack larger than that. A grid search over legal h9-compatible
lzma tunings (FORMAT_ALONE/XZ, lc/pb variants, preset 9e) found at best 600,164 B (43.67 min) —
still over 43 — so the blessed stock pack path was kept untouched. **To hit 43.0 min:** trim the
HTML to lzma-9 ≤ ~577 KB (≈14 KB lzma / ~2.3% of WAD trim). **Alternatively accept 43.99 min:**
it records fine on a physical C90 side with 1.0 min margin.

Housekeeping: `.gitignore` gained explicit `experiments/tape_v2/doom_ship/m10doom2_master.wav`
(documentation; the existing `doom_ship/*.wav` glob already covered it) and
`…/doom2_decoded.html`. Manifest/sidecar/results JSONs are small and tracked per v1 convention.

## V2.5 Burn SOP (updated) — v2 preferred, v1 fallback

1. **Use a C90 cassette** — the v2 master is 43.99 min; a C60 side cannot hold it.
2. **Dolby NR OFF** at record AND playback. **Record level ~7.0** (8.5 saturates → IMD floor).
3. C90 side A loaded, fully rewound, leader spooled past. Start the deck **recording first**.
4. Run `bash /Users/magnus/repos/cassette-ai/experiments/tape_v2/doom_ship/play_doom_tape_v2.sh`
   (prints the checklist incl. measured duration, waits for ENTER, then `afplay`s the master).
5. Let the **full** master play to the end down-chirp; run the deck ~2 s past, stop.
6. Decode: iPhone Voice Memos capture → iCloud → `ffmpeg … -ac 1 -ar 48000 capture.wav` →
   `python3 …/doom_ship/m10doom2_decode.py capture.wav` → `doom2_decoded.html`, sha-verified.

**Fallback:** the v1 chain is fully intact — `play_doom_tape.sh` + `m10doom_master.wav`
(12.38 min, fits a C60 side) + `m10doom_decode.py` → `doom_cassette.html` (miniwad edition).

## V2.6 License note

Asset license is **unchanged: BSD 3-clause (Freedoom)** — `freedoom_trim.wad` is a trim of
Freedoom: Phase 1 v0.13.0, same license as v1's miniwad (itself Freedoom-derived). The Freedoom
copyright + full BSD-3 text are reproduced verbatim in the v2 HTML `<head>` comment
(`assemble_html2.py`), with a credit line in the splash. Engine remains GPL-2.0 (V1 §5 compliance
matrix applies as-is, incl. the side-B source obligation). No id Software content anywhere.

**Provenance bookkeeping:** the trim step had **not** updated `build/WAD_PROVENANCE.md` — this was
caught during this report pass (2026-06-12) and fixed: the dossier now carries a full
**"V2 — freedoom_trim.wad"** section (upstream zip + input/output SHA-256s, lump-audit summary,
license obligations).

## V2.7 Honest gaps (v2-specific; V1 §6 items 1, 2, 5, 6 still apply)

1. **No physical burn of the v2 master yet** — same status as v1: self-check is byte-exact on the
   clean WAV; the real C90 loop (burn → play → Voice Memos → decode) is the next step.
2. **43.99 min vs the 43-min planning gate** — see §V2.4. Resolve either by a ~14 KB-lzma WAD trim
   or by accepting the 1.0-min physical C90 margin.
3. **E1M3+ are stubs** — two real maps, then "THE END". More maps cost ~140 KB raw (~40–60 KB
   lzma) each; the hard cap is already 98.3% spent, so that requires trading something out.
4. **Front-rotation-only sprites** — monsters always face you (Jaguar-DOOM trick). Invisible in
   normal play, visible if you circle-strafe a corpse.
5. **Still no sound** — and now it's a real loss (DOOM's shotgun deserves better), but the sound
   backend + real PCM lumps do not fit the remaining 10 KB of cap.
