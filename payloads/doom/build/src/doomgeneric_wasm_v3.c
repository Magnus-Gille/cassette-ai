//
// doomgeneric_wasm_v3.c — v3 emscripten backend for doomgeneric.
//
// Copy-and-extend of doomgeneric_wasm.c (which stays frozen for the v1/v2
// artifacts). Part of the cassette-ai DOOM-on-a-cassette artifact. GPL-2.0
// (same as the doomgeneric engine it links against).
//
// Video : DG_ScreenBuffer (0x00RRGGBB uint32) -> swizzle to RGBA -> canvas
//         2d context putImageData via EM_JS, straight from the wasm heap.
// Input : emscripten/html5.h keydown/keyup callbacks on the window target,
//         DOM keyCode -> doomkeys.h, 16-slot ring buffer (upstream pattern).
// Timing: emscripten_get_now(); DG_SleepMs is a no-op (browser main loop).
//
// NEW IN V3 (vs doomgeneric_wasm.c):
//  * Audio: real DG_sound_module (build with -DFEATURE_SOUND). DS* DMX lumps
//    (8-byte header: u8 format=3, u16le sample rate at +2, u32le length at +4,
//    then unsigned 8-bit PCM; vanilla pads 16 bytes at each end inside
//    `length`) are decoded ONCE per lump into cached WebAudio AudioBuffers
//    (honoring per-lump sample rate) and played through gain (sfx volume,
//    0..127) + stereo-panner (sep 0..254) nodes. The AudioContext is resumed
//    on the first user gesture (capture-phase keydown/mousedown/touchstart
//    listeners stay armed; the INSERT TAPE & PLAY click and/or the first
//    keypress unlocks it). Counters for verification:
//      window['__sfxPlayed']     — successful source.start() calls
//      window['__sfxDecoded']    — distinct lumps decoded to AudioBuffers
//      window['__audioCtxState'] — 'none'|'unavailable'|AudioContext.state
//    Music module is a no-op shim (D_* lumps on the tape are stubs; side B
//    of the cassette carries the real music).
//  * Boot: no -warp — D_DoomMain runs the title screen + DEMO1..4 attract
//    loop (define DG_WARP at compile time to restore the v2 warp-to-map
//    behaviour for smoke tests).
//  * Savegame persistence lives in pre_wad_v3.js (localStorage mirror of the
//    MEMFS /.savegame dir; window['__saveMirrored'] counter) — no engine
//    changes needed for it.
//

#include <stdint.h>
#include <stdio.h>
#include <ctype.h>

#include <emscripten.h>
#include <emscripten/html5.h>

#include "doomkeys.h"
#include "doomgeneric.h"

#include "i_sound.h"
#include "w_wad.h"
#include "z_zone.h"

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
// WebAudio SFX out (v3)
// ---------------------------------------------------------------------------
//
// All state lives on globalThis.dgAud (closure renames it consistently inside
// this compilation unit). Anything read from OUTSIDE the closure unit (test
// harness, shell page) uses string-keyed window['...'] properties, which the
// closure compiler never renames.

EM_JS(void, js_audio_init, (void), {
    var A = { ctx: null, bufs: {}, ch: [], dead: false, kick: null };
    globalThis.dgAud = A;
    window['__sfxPlayed'] = 0;
    window['__sfxDecoded'] = 0;
    window['__audioCtxState'] = 'none';

    var AC = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AC) {                       // e.g. the node smoke harness
        A.dead = true;
        window['__audioCtxState'] = 'unavailable';
        return;
    }

    var ctx;
    try { ctx = new AC(); }
    catch (e) {
        A.dead = true;
        window['__audioCtxState'] = 'unavailable';
        return;
    }
    A.ctx = ctx;

    var upd = function() { window['__audioCtxState'] = ctx.state; };
    upd();
    ctx.onstatechange = upd;

    // Autoplay policy: a context created outside a user-gesture call stack
    // starts 'suspended'. Keep capture-phase gesture listeners armed for the
    // whole session — the first key/click/touch (e.g. the INSERT TAPE & PLAY
    // button, or the first movement key) resumes it; they also cover the
    // browser re-suspending us later.
    A.kick = function() {
        if (A.ctx && A.ctx.state !== 'running') {
            A.ctx.resume().then(upd, function(){});
        }
    };
    A.kick();
    if (typeof document !== 'undefined' && document.addEventListener) {
        document.addEventListener('keydown', A.kick, true);
        document.addEventListener('mousedown', A.kick, true);
        document.addEventListener('touchstart', A.kick, true);
    }
});

// Start `nsamples` of unsigned 8-bit PCM at `rate` Hz (from the wasm heap at
// `ptr`) on logical DOOM channel `ch`. Decodes to a cached AudioBuffer on
// first sight of `lump`; honors per-lump sample rate.
EM_JS(void, js_sfx_start, (int ch, int lump, const void *ptr, int nsamples,
                           int rate, int vol, int sep), {
    var A = globalThis.dgAud;
    if (!A || A.dead || !A.ctx) return;
    var ctx = A.ctx;

    var buf = A.bufs[lump];
    if (!buf) {
        buf = ctx.createBuffer(1, nsamples, rate);
        var d = buf.getChannelData(0);
        var s = HEAPU8.subarray(ptr, ptr + nsamples);
        for (var i = 0; i < nsamples; i++) {
            d[i] = (s[i] - 127.5) / 127.5;
        }
        A.bufs[lump] = buf;
        window['__sfxDecoded']++;
    }

    var old = A.ch[ch];
    if (old) {
        try { old.src.stop(); } catch (e) {}
        A.ch[ch] = null;
    }

    var src = ctx.createBufferSource();
    src.buffer = buf;
    var g = ctx.createGain();
    g.gain.value = vol / 127;
    src.connect(g);
    var out = g, pan = null;
    if (ctx.createStereoPanner) {
        pan = ctx.createStereoPanner();
        var p = (sep - 127) / 127;
        pan.pan.value = p < -1 ? -1 : (p > 1 ? 1 : p);
        g.connect(pan);
        out = pan;
    }
    out.connect(ctx.destination);
    A.ch[ch] = { src: src, g: g, pan: pan };

    if (ctx.state !== 'running' && A.kick) A.kick();
    src.start();
    window['__sfxPlayed']++;
});

EM_JS(void, js_sfx_stop, (int ch), {
    var A = globalThis.dgAud;
    if (!A) return;
    var c = A.ch[ch];
    if (c) {
        try { c.src.stop(); } catch (e) {}
        A.ch[ch] = null;
    }
});

EM_JS(void, js_sfx_update, (int ch, int vol, int sep), {
    var A = globalThis.dgAud;
    if (!A) return;
    var c = A.ch[ch];
    if (c) {
        c.g.gain.value = vol / 127;
        if (c.pan) {
            var p = (sep - 127) / 127;
            c.pan.pan.value = p < -1 ? -1 : (p > 1 ? 1 : p);
        }
    }
});

// ---------------------------------------------------------------------------
// DG_sound_module — the i_sound.c plugin interface (FEATURE_SOUND)
// ---------------------------------------------------------------------------

// Referenced by I_BindSoundVariables/m_config.c under FEATURE_SOUND; we do no
// resampling (WebAudio does), the variables just need to exist.
int use_libsamplerate = 0;
float libsamplerate_scale = 1.0f;

#define V3_NUM_CHANNELS 16

static boolean snd_use_prefix = true;
// Per-channel wall-clock end time (ms): cheap C-side SoundIsPlaying without
// round-tripping state out of JS.
static double snd_end_ms[V3_NUM_CHANNELS];

static snddevice_t sound_v3_devices[] =
{
    SNDDEVICE_SB,
    SNDDEVICE_PAS,
    SNDDEVICE_GUS,
    SNDDEVICE_WAVEBLASTER,
    SNDDEVICE_SOUNDCANVAS,
    SNDDEVICE_AWE32,
};

static boolean I_V3_InitSound(boolean use_sfx_prefix)
{
    snd_use_prefix = use_sfx_prefix;
    js_audio_init();
    return true;
}

static void I_V3_ShutdownSound(void)
{
}

static int I_V3_GetSfxLumpNum(sfxinfo_t *sfx)
{
    char namebuf[9];

    // Linked sfx lumps (e.g. chgun -> pistol): use the link target's lump.
    if (sfx->link != NULL)
    {
        sfx = sfx->link;
    }

    if (snd_use_prefix)
    {
        snprintf(namebuf, sizeof(namebuf), "ds%s", sfx->name);
    }
    else
    {
        snprintf(namebuf, sizeof(namebuf), "%s", sfx->name);
    }

    // Tolerate trimmed WADs: a missing DS* lump silently mutes that sound
    // (W_GetNumForName would I_Error the whole game).
    return W_CheckNumForName(namebuf);
}

static void I_V3_UpdateSound(void)
{
}

static void I_V3_UpdateSoundParams(int channel, int vol, int sep)
{
    if (channel < 0 || channel >= V3_NUM_CHANNELS)
    {
        return;
    }
    js_sfx_update(channel, vol, sep);
}

static int I_V3_StartSound(sfxinfo_t *sfxinfo, int channel, int vol, int sep)
{
    const unsigned char *data;
    unsigned int lumplen;
    int lumpnum, samplerate, length, offset;

    if (channel < 0 || channel >= V3_NUM_CHANNELS)
    {
        return -1;
    }

    lumpnum = sfxinfo->lumpnum;
    if (lumpnum < 0)
    {
        return -1; // lump missing from (trimmed) WAD — mute, don't die
    }

    lumplen = W_LumpLength(lumpnum);
    data = W_CacheLumpNum(lumpnum, PU_STATIC);

    // DMX header: 03 00 | u16le rate | u32le length | samples (u8 PCM).
    if (lumplen < 8 || data[0] != 0x03 || data[1] != 0x00)
    {
        W_ReleaseLumpNum(lumpnum);
        return -1;
    }

    samplerate = (data[3] << 8) | data[2];
    length = (data[7] << 24) | (data[6] << 16) | (data[5] << 8) | data[4];

    if (length > (int)lumplen - 8)
    {
        length = (int)lumplen - 8;
    }

    // The DMX library skips the first and last 16 bytes (padding) of the
    // sample data — same heuristic as chocolate-doom's SDL backend. Keep
    // short lumps (stubs) whole.
    offset = 8;
    if (length > 48)
    {
        offset += 16;
        length -= 32;
    }

    // WebAudio AudioContext.createBuffer rejects rates outside [8000,96000].
    if (length <= 0 || samplerate < 8000 || samplerate > 96000)
    {
        W_ReleaseLumpNum(lumpnum);
        return -1;
    }

    js_sfx_start(channel, lumpnum, data + offset, length, samplerate,
                 vol, sep);
    snd_end_ms[channel] =
        emscripten_get_now() + (double)length * 1000.0 / (double)samplerate;

    // The AudioBuffer is cached JS-side; the zone lump can go back to cache.
    W_ReleaseLumpNum(lumpnum);

    return channel;
}

static void I_V3_StopSound(int channel)
{
    if (channel < 0 || channel >= V3_NUM_CHANNELS)
    {
        return;
    }
    js_sfx_stop(channel);
    snd_end_ms[channel] = 0.0;
}

static boolean I_V3_SoundIsPlaying(int channel)
{
    if (channel < 0 || channel >= V3_NUM_CHANNELS)
    {
        return false;
    }
    return emscripten_get_now() < snd_end_ms[channel];
}

// CacheSounds is optional (i_sound.c NULL-checks it). We decode lazily, one
// AudioBuffer per lump on first play, instead of all-at-boot.

sound_module_t DG_sound_module =
{
    sound_v3_devices,
    sizeof(sound_v3_devices) / sizeof(sound_v3_devices[0]),
    I_V3_InitSound,
    I_V3_ShutdownSound,
    I_V3_GetSfxLumpNum,
    I_V3_UpdateSound,
    I_V3_UpdateSoundParams,
    I_V3_StartSound,
    I_V3_StopSound,
    I_V3_SoundIsPlaying,
    NULL, // CacheSounds
};

// ---------------------------------------------------------------------------
// DG_music_module — no-op shim. The cassette WAD carries 62-byte D_* stubs
// (s_sound.c looks music lumps up unguarded); side B of the tape carries the
// actual music. RegisterSong returns NULL and every player call ignores it.
// ---------------------------------------------------------------------------

static snddevice_t music_v3_devices[] =
{
    SNDDEVICE_ADLIB,
    SNDDEVICE_SB,
    SNDDEVICE_GENMIDI,
    SNDDEVICE_AWE32,
};

static boolean I_V3_InitMusic(void)            { return true; }
static void I_V3_ShutdownMusic(void)           {}
static void I_V3_SetMusicVolume(int volume)    { (void)volume; }
static void I_V3_PauseSong(void)               {}
static void I_V3_ResumeSong(void)              {}
static void *I_V3_RegisterSong(void *data, int len)
{
    (void)data; (void)len;
    return NULL;
}
static void I_V3_UnRegisterSong(void *handle)  { (void)handle; }
static void I_V3_PlaySong(void *handle, boolean looping)
{
    (void)handle; (void)looping;
}
static void I_V3_StopSong(void)                {}
static boolean I_V3_MusicIsPlaying(void)       { return false; }

music_module_t DG_music_module =
{
    music_v3_devices,
    sizeof(music_v3_devices) / sizeof(music_v3_devices[0]),
    I_V3_InitMusic,
    I_V3_ShutdownMusic,
    I_V3_SetMusicVolume,
    I_V3_PauseSong,
    I_V3_ResumeSong,
    I_V3_RegisterSong,
    I_V3_UnRegisterSong,
    I_V3_PlaySong,
    I_V3_StopSong,
    I_V3_MusicIsPlaying,
    NULL, // Poll
};

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

#ifdef DG_WARP
    // v2 behaviour (smoke tests): boot straight into the first map.
    static char *dg_argv[] = { "doom", "-iwad", DG_IWAD_PATH, "-warp", "1", 0 };
    doomgeneric_Create(5, dg_argv);
#else
    // v3: no -warp — run the title screen + DEMO1..4 attract loop; the
    // player starts a game from the menu.
    static char *dg_argv[] = { "doom", "-iwad", DG_IWAD_PATH, 0 };
    doomgeneric_Create(3, dg_argv);
#endif

    emscripten_set_main_loop(doomgeneric_Tick, 0, 1);

    return 0;
}
