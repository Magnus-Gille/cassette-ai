#include <stdlib.h>
#include <string.h>
#include "espeak-ng/speak_lib.h"
#include <emscripten.h>

static short *pcm_buf = NULL;
static int pcm_len = 0;
static int pcm_cap = 0;

static int synth_callback(short *wav, int numsamples, espeak_EVENT *events) {
    if (wav && numsamples > 0) {
        int needed = pcm_len + numsamples;
        if (needed > pcm_cap) {
            pcm_cap = needed * 2;
            pcm_buf = realloc(pcm_buf, pcm_cap * sizeof(short));
        }
        memcpy(pcm_buf + pcm_len, wav, numsamples * sizeof(short));
        pcm_len += numsamples;
    }
    return 0;
}

EMSCRIPTEN_KEEPALIVE
int espeak_init(void) {
    /* Data directory is preloaded at /espeak-ng-data in the WASM VFS */
    int sr = espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 200, "/espeak-ng-data", espeakINITIALIZE_DONT_EXIT);
    espeak_SetSynthCallback(synth_callback);
    return sr;
}

EMSCRIPTEN_KEEPALIVE
int espeak_set_voice_en(void) {
    return (int)espeak_SetVoiceByName("en");
}

EMSCRIPTEN_KEEPALIVE
int espeak_synth_text(const char *text) {
    pcm_len = 0;
    espeak_Synth(text, strlen(text)+1, 0, POS_CHARACTER, 0, espeakCHARS_AUTO, NULL, NULL);
    espeak_Synchronize();
    return pcm_len;
}

EMSCRIPTEN_KEEPALIVE
short *espeak_get_pcm_buf(void) {
    return pcm_buf;
}

EMSCRIPTEN_KEEPALIVE
int espeak_get_pcm_len(void) {
    return pcm_len;
}
