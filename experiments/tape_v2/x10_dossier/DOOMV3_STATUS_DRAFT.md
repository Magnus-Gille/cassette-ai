# DOOM V3 STATUS DRAFT (for STATUS.md / Munin projects/cassette-ai)

**As of 2026-06-12, end of the DOOM v3 build. SHIPPED — ready to burn (both sides).**

## State

- **Standing real-tape record:** 5791 bps (tape10). **v3 SHIP config:** the r6 rung —
  **D2X_P21_N256_sp2_drop1, RS(255,159), net 4910.3 bps** (landed 0-failures on the first
  front-end branch TWICE on tape10, `results/x11_decode_results_tape10_run1.json`), with ONE
  physics delta: **FRAME_BYTES 510 → 10200** (10.7 s frames, 4736 bps on packed bytes), sim-gated
  before printing.
- **The artifact:** `payloads/doom/dist/doom_cassette_v3.html` — 4,851,786 B raw, **lzma-9
  1,569,568 B = 1.497 MB** (TARGET 1.50 MB met, HARD CAP 1.60 MB at 93.6 %), sha256
  `55390aac96bab0bdd66d22071675b3432e214f54cb61738f7b951ce4bef42aab`.
  Content: **full Freedoom Phase 1 Episode 1 (all nine maps E1M1–E1M9), full E1 bestiary, every
  placed weapon (plasma + chainsaw incl.), WebAudio SOUND EFFECTS (58/69 reachable DS* real,
  aliased to 51 PCM blobs), savegames persistent across reload (localStorage mirror), attract
  demo loop (real E1M6 DEMO1)**. Music lumps dropped — side B carries real music.
- **Tape side A to burn:** `doom_ship/m10doom3_master.wav` — **44.77 min** (fits the 45.0-min
  physical C90 side, 13.7 s margin), 248 frames / 9,898 codewords, peak 0.70 SOP.
- **Tape side B built:** `doom_ship/m10doom3_sideB_source.wav` — **9.76 min**, the GPL complete
  corresponding source (`dist/doom_v3_source.tar`, 198 entries, sha `06a5ae8c…`) at the identical
  modem; then music: 4 `bside_remix` tracks (≈8.1 min/pass; 35.2 min available).
- **Receiver:** `doom_ship/m10doom3_decode.py` — frozen m10 stage A verbatim + bytes-returning
  x11 d2x rescue, ARMED.
- **v1, v2, and every frozen file byte-identical** — all v3 work is new files
  (`*_v3.*` in `payloads/doom/build/`, `m10doom3_*` in `doom_ship/`, importing read-only).

## Gates on record (both blessings required by `play_doom_tape_v3.sh` before it will play)

1. **FB=10200 long-frame sim gate** (`results/m10doom3_simgate.json`): **gate_pass=true, 9/9
   cells** — clean + dg0.35 × aac{off,on} × clk{0,+0.10,+0.17,+0.25}% — every cell 0 failed
   codewords, byte-exact, 0 miscorrections (ensemble union recovered cells where the best single
   branch left up to 97 failing; rescue never fired). FA 3.9e-6 < 1e-4.
2. **No-channel self-check** (`results/m10doom3_results_selfcheck_nochan.json`): **BYTE-EXACT,
   0/9,898 cw**, `hann256_skip0_ema0.7`, stage m10_stock, sha matches manifest + dist. FA 2.3e-6.
3. **Side B self-check** (`results/m10doom3_sideB_source_report.json`): 0/2,072 cw, packed +
   original byte-exact, FA 4.8e-7.

## Live browser verification (2026-06-12 report pass, Playwright/Chromium)

- `__audioCtxState` = **running** after the INSERT TAPE & PLAY click; `__sfxPlayed` = **49** at
  the title screen from the attract demo alone, **332** after gameplay.
- Save/restore loop closed live: F2 save → MEMFS `doomsav0.dsg` 61,342 B → `__saveMirrored` 0→1 →
  localStorage `cassette_doom_v3:doomsav0.dsg` → **page reload** → restored into MEMFS pre-boot
  (`__dbgListSaves()` = `{"doomsav0.dsg":61342}`) → F3 loads it in-game.
- Proofs: `dist/v3_proof_{a_demo1,a_demo2,b_e1m1,c_fire_sound,d_combat,d_scan1,e_saved,
  e_restored,f_e1m5,f_e1m5_automap}.png` + live `v3_proof_g_*.jpeg`. E1M5 automap reads
  "PHOBOS LAB" — the whole episode is really in there.

## Next steps (physical, operator required)

1. Burn side A: deck recording first (Dolby OFF, level ~7.0, C90 rewound), then
   `bash experiments/tape_v2/doom_ship/play_doom_tape_v3.sh` (gate-checked; 44.77 min).
2. Burn side B: data FIRST — `afplay doom_ship/m10doom3_sideB_source.wav` — then the four
   `bside_remix/bside_{ambient,techno,melodic,concrete}.wav` tracks (loop to taste).
3. Capture side A per SOP (Voice Memos → iCloud → 48 kHz mono WAV) and decode:
   `python3 experiments/tape_v2/doom_ship/m10doom3_decode.py <capture.wav>` → must reproduce
   BYTE-EXACT against the manifest.

## Known gaps (full list: DOOM_TAPE_REPORT.md §V3.9)

- No physical burn yet; FB=10200 timing hold is sim-gated only until the loop closes.
- Emscripten MIT notice missing from side-B `LICENSES/` (one-file tar + WAV rebuild before
  distribution beyond personal use).
- `WAD_PROVENANCE.md` V3 section pending; `trim_freedoom_v3.py` docstring says tex70 but the
  shipped WAD is the tex60 ladder point.
- Git: `doomgeneric_wasm_v3.c`, `pre_wad_v3.js`, `smoke_node_v3.js`, `src_v3/`, v3 proofs are
  untracked (gitignore negations needed); commit on the feature branch next session.

## Frozen / conventions unchanged

`m10_master.py`, `m10_decode.py`, `x11_decode.py`, `m10doom_master.py`, `m10doom2_master.py`,
`master10_manifest.json`, all v1/v2 DOOM artifacts and build inputs. Per-cw CRC32 the only
acceptance channel; FA budget 1e-4 campaign-wide; gates frozen before experiments; sim is 5–8×
pessimistic on the reverb/timing axis (prediction-to-test, never a cut).
