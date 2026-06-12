#!/bin/bash
#
# build_v3.sh — v3 engine pack: copy-and-extend of build_split_doom1.sh.
#
#   v3 additions vs the (frozen) v2 build:
#     - FEATURE_SOUND: i_sound.c + m_config.c get v3 objects compiled with
#       -DFEATURE_SOUND (i_sound.c's <SDL_mixer.h> include is satisfied by
#       the empty stub in src_v3/); the backend doomgeneric_wasm_v3.c
#       provides DG_sound_module (WebAudio) + DG_music_module (no-op shim).
#     - pre_wad_v3.js: IWAD as /doom1.wad + localStorage savegame mirror.
#     - no -warp: title screen + DEMO attract loop (pass --warp for the v2
#       boot-straight-into-map behaviour, smoke tests only).
#
#   Outputs pack/doom_pack_v3.js + pack/doom_pack_v3.wasm. The v1/v2 packs,
#   sources and objects are untouched (v3-only objects get _v3 suffixes).
#
# Usage: ./build_v3.sh [--warp]
#
set -euo pipefail
cd "$(dirname "$0")"

source /Users/magnus/repos/cassette-ai/tools/emsdk/emsdk_env.sh >/dev/null 2>&1

WARP=""
if [[ "${1:-}" == "--warp" ]]; then
    WARP="-DDG_WARP"
fi

SRC=src
OBJ=obj
PACK=pack
mkdir -p "$OBJ" "$PACK"

# Common (sound-agnostic) engine objects — IDENTICAL flags to the v2 build,
# so the incremental obj/ cache is shared. i_sound + m_config are excluded:
# they need -DFEATURE_SOUND and get _v3 objects below.
SOURCES="dummy am_map doomdef doomstat dstrings d_event d_items d_iwad d_loop \
d_main d_mode d_net f_finale f_wipe g_game hu_lib hu_stuff info i_cdmus \
i_endoom i_joystick i_scale i_system i_timer memio m_argv m_bbox \
m_cheat m_controls m_fixed m_menu m_misc m_random p_ceilng p_doors \
p_enemy p_floor p_inter p_lights p_map p_maputl p_mobj p_plats p_pspr p_saveg \
p_setup p_sight p_spec p_switch p_telept p_tick p_user r_bsp r_data r_draw \
r_main r_plane r_segs r_sky r_things sha1 sounds statdump st_lib st_stuff \
s_sound tables v_video wi_stuff w_checksum w_file w_main w_wad z_zone \
w_file_stdc i_input i_video doomgeneric"

CFLAGS="-Oz -flto -DDOOMGENERIC_RESX=320 -DDOOMGENERIC_RESY=200 \
-Wno-implicit-function-declaration"

echo "[1/3] compiling common objects (incremental, shared with v2)..."
pids=()
for s in $SOURCES; do
    if [[ "$SRC/$s.c" -nt "$OBJ/$s.o" ]]; then
        emcc $CFLAGS -c "$SRC/$s.c" -o "$OBJ/$s.o" &
        pids+=($!)
        if (( ${#pids[@]} >= 10 )); then
            wait "${pids[0]}"; pids=("${pids[@]:1}")
        fi
    fi
done
wait

echo "[2/3] compiling v3 objects (-DFEATURE_SOUND${WARP:+ $WARP})..."
emcc $CFLAGS -DFEATURE_SOUND -Isrc_v3 \
    -c "$SRC/i_sound.c" -o "$OBJ/i_sound_v3.o" &
emcc $CFLAGS -DFEATURE_SOUND \
    -c "$SRC/m_config.c" -o "$OBJ/m_config_v3.o" &
emcc $CFLAGS -DFEATURE_SOUND $WARP -DDG_IWAD_PATH=\"/doom1.wad\" \
    -c "$SRC/doomgeneric_wasm_v3.c" -o "$OBJ/doomgeneric_wasm_v3.o" &
wait

echo "[3/3] linking pack/doom_pack_v3.js (split, closure, pre_wad_v3)..."
OBJS=""
for s in $SOURCES; do OBJS="$OBJS $OBJ/$s.o"; done
OBJS="$OBJS $OBJ/i_sound_v3.o $OBJ/m_config_v3.o $OBJ/doomgeneric_wasm_v3.o"

emcc $OBJS -o "$PACK/doom_pack_v3.js" \
    -Oz -flto --closure 1 \
    -sENVIRONMENT=web \
    -sMALLOC=emmalloc \
    -sINITIAL_MEMORY=67108864 \
    -sALLOW_MEMORY_GROWTH=0 \
    -sSTACK_SIZE=2097152 \
    "-sINCOMING_MODULE_JS_API=[wasmBinary,preRun]" \
    --pre-js pre_wad_v3.js \
    -sSUPPORT_LONGJMP=0 \
    -sASSERTIONS=0

ls -la "$PACK/doom_pack_v3.js" "$PACK/doom_pack_v3.wasm"
