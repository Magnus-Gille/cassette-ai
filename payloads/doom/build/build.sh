#!/bin/bash
#
# build.sh — size-optimized single-file emscripten build of doomgeneric.
#
# Usage: ./build.sh [path/to/iwad.wad] [--no-closure]
#
#   The IWAD is embedded into the output under its own basename (the name
#   must be one d_iwad.c recognizes: doom1.wad / doom2.wad / freedoom1.wad /
#   freedoom2.wad ...) and passed to the engine via a hardcoded -iwad argv.
#   Default: freedoom1.wad (smoke test; the stripped miniwad swaps in later).
#
# Output: doom.js (SINGLE_FILE — wasm + embedded WAD inlined as base64).
#
set -euo pipefail
cd "$(dirname "$0")"

source /Users/magnus/repos/cassette-ai/tools/emsdk/emsdk_env.sh >/dev/null 2>&1

WAD="${1:-freedoom1.wad}"
CLOSURE="--closure 1"
if [[ "${2:-}" == "--no-closure" || "${1:-}" == "--no-closure" ]]; then
    CLOSURE=""
    [[ "${1:-}" == "--no-closure" ]] && WAD="freedoom1.wad"
fi

if [[ ! -f "$WAD" ]]; then
    echo "error: IWAD '$WAD' not found" >&2
    exit 1
fi
WADBASE="$(basename "$WAD")"

SRC=src
OBJ=obj
mkdir -p "$OBJ"

# Default Makefile's non-sound source list, doomgeneric_xlib -> doomgeneric_wasm.
SOURCES="dummy am_map doomdef doomstat dstrings d_event d_items d_iwad d_loop \
d_main d_mode d_net f_finale f_wipe g_game hu_lib hu_stuff info i_cdmus \
i_endoom i_joystick i_scale i_sound i_system i_timer memio m_argv m_bbox \
m_cheat m_config m_controls m_fixed m_menu m_misc m_random p_ceilng p_doors \
p_enemy p_floor p_inter p_lights p_map p_maputl p_mobj p_plats p_pspr p_saveg \
p_setup p_sight p_spec p_switch p_telept p_tick p_user r_bsp r_data r_draw \
r_main r_plane r_segs r_sky r_things sha1 sounds statdump st_lib st_stuff \
s_sound tables v_video wi_stuff w_checksum w_file w_main w_wad z_zone \
w_file_stdc i_input i_video doomgeneric doomgeneric_wasm"

CFLAGS="-Oz -flto -DDOOMGENERIC_RESX=320 -DDOOMGENERIC_RESY=200 \
-DDG_IWAD_PATH=\"/$WADBASE\" -Wno-implicit-function-declaration"

echo "[1/2] compiling (parallel, -Oz -flto, no sound, 320x200)..."
pids=()
for s in $SOURCES; do
    if [[ "$SRC/$s.c" -nt "$OBJ/$s.o" ]]; then
        emcc $CFLAGS -c "$SRC/$s.c" -o "$OBJ/$s.o" &
        pids+=($!)
        # cap parallelism at ~10
        if (( ${#pids[@]} >= 10 )); then
            wait "${pids[0]}"; pids=("${pids[@]:1}")
        fi
    fi
done
wait

echo "[2/2] linking doom.js (SINGLE_FILE, embed $WADBASE)..."
OBJS=""
for s in $SOURCES; do OBJS="$OBJS $OBJ/$s.o"; done

emcc $OBJS -o doom.js \
    -Oz -flto $CLOSURE \
    -sENVIRONMENT=web \
    -sSINGLE_FILE=1 \
    -sMALLOC=emmalloc \
    -sINITIAL_MEMORY=67108864 \
    -sALLOW_MEMORY_GROWTH=0 \
    -sSTACK_SIZE=2097152 \
    -sINCOMING_MODULE_JS_API=[] \
    -sSUPPORT_LONGJMP=0 \
    -sASSERTIONS=0 \
    --embed-file "$WAD@/$WADBASE"

ls -la doom.js
