//
// doomgeneric_wasm.c — minimal SDL-free emscripten backend for doomgeneric.
//
// Part of the cassette-ai DOOM-on-a-cassette artifact. GPL-2.0 (same as the
// doomgeneric engine it links against).
//
// Video : DG_ScreenBuffer (0x00RRGGBB uint32) -> swizzle to RGBA -> canvas
//         2d context putImageData via EM_JS, straight from the wasm heap.
// Input : emscripten/html5.h keydown/keyup callbacks on the window target,
//         DOM keyCode -> doomkeys.h, 16-slot ring buffer (upstream pattern).
// Timing: emscripten_get_now(); DG_SleepMs is a no-op (browser main loop).
// Audio : none (built without -DFEATURE_SOUND).
//

#include <stdint.h>
#include <ctype.h>

#include <emscripten.h>
#include <emscripten/html5.h>

#include "doomkeys.h"
#include "doomgeneric.h"

#ifndef DG_IWAD_PATH
#define DG_IWAD_PATH "/doom2.wad"
#endif

// ---------------------------------------------------------------------------
// Key queue (same scheme as the upstream backends)
// ---------------------------------------------------------------------------

#define KEYQUEUE_SIZE 16

static unsigned short s_KeyQueue[KEYQUEUE_SIZE];
static unsigned int s_KeyQueueWriteIndex = 0;
static unsigned int s_KeyQueueReadIndex = 0;

static unsigned char convertToDoomKey(unsigned long keyCode)
{
    switch (keyCode)
    {
    case 13:  return KEY_ENTER;
    case 27:  return KEY_ESCAPE;
    case 37:  return KEY_LEFTARROW;
    case 39:  return KEY_RIGHTARROW;
    case 38:  return KEY_UPARROW;
    case 40:  return KEY_DOWNARROW;
    case 17:  return KEY_FIRE;       // Ctrl
    case 88:  return KEY_FIRE;       // X — Mac-safe fire (Ctrl+Arrow = macOS Mission Control space-switch)
    case 83:  return KEY_FIRE;       // S — fire (left-hand A/S/D cluster: strafe-fire-strafe)
    case 32:  return KEY_USE;        // Space
    case 16:  return KEY_RSHIFT;     // Shift
    case 18:  return KEY_LALT;       // Alt (also strafe modifier: Alt+arrow)
    case 65:  return KEY_STRAFE_L;   // A — strafe left  (left-hand cluster)
    case 68:  return KEY_STRAFE_R;   // D — strafe right (left-hand cluster)
    case 188: return KEY_STRAFE_L;   // , — strafe left  (alt)
    case 190: return KEY_STRAFE_R;   // . — strafe right (alt)
    case 9:   return KEY_TAB;
    case 8:   return KEY_BACKSPACE;
    case 112: return KEY_F1;
    case 113: return KEY_F2;
    case 114: return KEY_F3;
    case 115: return KEY_F4;
    case 116: return KEY_F5;
    case 117: return KEY_F6;
    case 118: return KEY_F7;
    case 119: return KEY_F8;
    case 120: return KEY_F9;
    case 121: return KEY_F10;
    case 122: return KEY_F11;
    case 187: return KEY_EQUALS;     // = / +
    case 189: return KEY_MINUS;      // - / _
    default:
        if (keyCode < 128)
        {
            return (unsigned char)tolower((int)keyCode);
        }
        return 0;
    }
}

static void addKeyToQueue(int pressed, unsigned long keyCode)
{
    unsigned char key = convertToDoomKey(keyCode);

    if (key == 0)
    {
        return;
    }

    s_KeyQueue[s_KeyQueueWriteIndex] = (unsigned short)((pressed << 8) | key);
    s_KeyQueueWriteIndex++;
    s_KeyQueueWriteIndex %= KEYQUEUE_SIZE;
}

static EM_BOOL onKeyDown(int eventType, const EmscriptenKeyboardEvent *e,
                         void *userData)
{
    (void)eventType; (void)userData;
    if (e->repeat)
    {
        return EM_TRUE; // swallow auto-repeat, DOOM tracks press/release
    }
    addKeyToQueue(1, e->keyCode);
    return EM_TRUE; // preventDefault (stops page scroll on arrows/space)
}

static EM_BOOL onKeyUp(int eventType, const EmscriptenKeyboardEvent *e,
                       void *userData)
{
    (void)eventType; (void)userData;
    addKeyToQueue(0, e->keyCode);
    return EM_TRUE;
}

// ---------------------------------------------------------------------------
// Canvas video out
// ---------------------------------------------------------------------------

EM_JS(void, js_init_canvas, (int w, int h), {
    var canvas = document.getElementById('canvas');
    canvas.width = w;
    canvas.height = h;
    globalThis.dgCtx = canvas.getContext('2d');
    globalThis.dgImage = globalThis.dgCtx.createImageData(w, h);
});

EM_JS(void, js_draw_frame, (const void *ptr, int w, int h), {
    globalThis.dgImage.data.set(
        HEAPU8.subarray(ptr, ptr + (w * h * 4)));
    globalThis.dgCtx.putImageData(globalThis.dgImage, 0, 0);
});

// DG_ScreenBuffer holds 0x00RRGGBB (alpha never set by i_video.c); canvas
// ImageData wants R,G,B,A bytes = little-endian uint32 0xAABBGGRR.
static uint32_t s_rgba[DOOMGENERIC_RESX * DOOMGENERIC_RESY];

// ---------------------------------------------------------------------------
// DG_* implementation
// ---------------------------------------------------------------------------

void DG_Init()
{
    js_init_canvas(DOOMGENERIC_RESX, DOOMGENERIC_RESY);

    emscripten_set_keydown_callback(EMSCRIPTEN_EVENT_TARGET_WINDOW, 0, 1,
                                    onKeyDown);
    emscripten_set_keyup_callback(EMSCRIPTEN_EVENT_TARGET_WINDOW, 0, 1,
                                  onKeyUp);
}

void DG_DrawFrame()
{
    const uint32_t *src = (const uint32_t *)DG_ScreenBuffer;
    int n = DOOMGENERIC_RESX * DOOMGENERIC_RESY;

    for (int i = 0; i < n; i++)
    {
        uint32_t px = src[i];
        s_rgba[i] = 0xFF000000u            // alpha — mandatory, else invisible
                  | ((px & 0x000000FFu) << 16)   // B
                  |  (px & 0x0000FF00u)          // G
                  | ((px >> 16) & 0xFFu);        // R
    }

    js_draw_frame(s_rgba, DOOMGENERIC_RESX, DOOMGENERIC_RESY);
}

void DG_SleepMs(uint32_t ms)
{
    (void)ms; // cooperative browser main loop — never block
}

uint32_t DG_GetTicksMs()
{
    return (uint32_t)emscripten_get_now();
}

int DG_GetKey(int *pressed, unsigned char *doomKey)
{
    if (s_KeyQueueReadIndex == s_KeyQueueWriteIndex)
    {
        return 0; // queue empty
    }

    unsigned short keyData = s_KeyQueue[s_KeyQueueReadIndex];
    s_KeyQueueReadIndex++;
    s_KeyQueueReadIndex %= KEYQUEUE_SIZE;

    *pressed = keyData >> 8;
    *doomKey = keyData & 0xFF;

    return 1;
}

void DG_SetWindowTitle(const char *title)
{
    (void)title;
}

int main(int argc, char **argv)
{
    (void)argc; (void)argv;

    // -warp 1: boot straight into MAP01 (no title/demo loop) — the cassette
    // artifact should drop the player into the game on start.
    static char *dg_argv[] = { "doom", "-iwad", DG_IWAD_PATH, "-warp", "1", 0 };

    doomgeneric_Create(5, dg_argv);

    emscripten_set_main_loop(doomgeneric_Tick, 0, 1);

    return 0;
}
