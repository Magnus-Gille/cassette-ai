/* tslint:disable */
/* eslint-disable */

export function _start(): void;

/**
 * Diagnostic: expose global-sync internals + per-frame demod bit counts.
 */
export function debug_floor(samples: Float32Array, manifest_json: string): any;

/**
 * Decode the floor rung from a raw 48 kHz mono capture.
 *
 * `samples` — f32 PCM at 48 kHz (resample on the JS side if the recorder ran
 * at another rate). `manifest_json` — the bundled tape manifest (tx_chirp0/1,
 * section frame layout, RS/interleave meta).
 *
 * Returns a JS object: `{ bytes: Uint8Array, speed, align, cw_failed, n_cw,
 * lock_quality }`.
 */
export function decode_floor(samples: Float32Array, manifest_json: string): any;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly debug_floor: (a: number, b: number, c: number, d: number) => [number, number, number];
    readonly decode_floor: (a: number, b: number, c: number, d: number) => [number, number, number];
    readonly _start: () => void;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
