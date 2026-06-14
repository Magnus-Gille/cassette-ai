#!/bin/bash
#
# build_split.sh — split (js + wasm) size-optimized link of doomgeneric for the
# rawpack single-file HTML assembly (assemble_html.py).
#
# Differences vs build.sh (the SINGLE_FILE smoke build):
#   - NO -sSINGLE_FILE, NO --embed-file: the wasm and the WAD travel as raw
#     bytes inside the HTML via the windows-1252 rawpack carrier (lzma +2-5%
#     instead of base64's +18-38%).
#   - -sINCOMING_MODULE_JS_API=[wasmBinary,preRun]: the shell passes the
#     decoded wasm via Module.wasmBinary (zero fetches -> works on file://)
#     and writes the WAD into MEMFS from a preRun hook.
#   - --pre-js pre_wad.js: the MEMFS write of the WAD happens INSIDE the
#     closure unit (Module.FS export does not survive closure: the FS object's
#     method names get renamed). The shell passes bytes as Module['wadBinary'].
#   - DG_IWAD_PATH=/doom2.wad: mini.wad (miniwad) is not in d_iwad.c's iwads[]
#     table; serving it as doom2.wad selects commercial/Doom II mode, matching
#     its MAP01..MAP32 lump set.
#
# Output: pack/doom_pack.js + pack/doom_pack.wasm
#
set -euo pipefail
cd "$(dirname "$0")"

source /Users/magnus/repos/cassette-ai/tools/emsdk/emsdk_env.sh >/dev/null 2>&1

SRC=src
OBJ=obj
PACK=pack
mkdir -p "$OBJ" "$PACK"

SOURCES="dummy am_map doomdef doomstat dstrings d_event d_items d_iwad d_loop \
d_main d_mode d_net f_finale f_wipe g_game hu_lib hu_stuff info i_cdmus \
i_endoom i_joystick i_scale i_sound i_system i_timer memio m_argv m_bbox \
m_cheat m_config m_controls m_fixed m_menu m_misc m_random p_ceilng p_doors \
p_enemy p_floor p_inter p_lights p_map p_maputl p_mobj p_plats p_pspr p_saveg \
p_setup p_sight p_spec p_switch p_telept p_tick p_user r_bsp r_data r_draw \
r_main r_plane r_segs r_sky r_things sha1 sounds statdump st_lib st_stuff \
s_sound tables v_video wi_stuff w_checksum w_file w_main w_wad z_zone \
w_file_stdc i_input i_video doomgeneric"

CFLAGS="-Oz -flto -DDOOMGENERIC_RESX=320 -DDOOMGENERIC_RESY=200 \
-Wno-implicit-function-declaration"

echo "[1/3] compiling common objects (incremental)..."
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

echo "[2/3] compiling backend with DG_IWAD_PATH=/doom2.wad..."
emcc $CFLAGS -DDG_IWAD_PATH=\"/doom2.wad\" \
    -c "$SRC/doomgeneric_wasm.c" -o "$OBJ/doomgeneric_wasm_pack.o"

echo "[3/3] linking pack/doom_pack.js (split, closure, FS exported)..."
OBJS=""
for s in $SOURCES; do OBJS="$OBJS $OBJ/$s.o"; done
OBJS="$OBJS $OBJ/doomgeneric_wasm_pack.o"

emcc $OBJS -o "$PACK/doom_pack.js" \
    -Oz -flto --closure 1 \
    -sENVIRONMENT=web \
    -sMALLOC=emmalloc \
    -sINITIAL_MEMORY=67108864 \
    -sALLOW_MEMORY_GROWTH=0 \
    -sSTACK_SIZE=2097152 \
    "-sINCOMING_MODULE_JS_API=[wasmBinary,preRun]" \
    --pre-js pre_wad.js \
    -sSUPPORT_LONGJMP=0 \
    -sASSERTIONS=0

ls -la "$PACK/doom_pack.js" "$PACK/doom_pack.wasm"
