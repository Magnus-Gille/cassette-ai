# v86 Linux — "boots a full Linux PC on a cassette" HTML artifact

A single self-contained HTML file that decodes-and-runs an entire x86 PC + Linux OS
in the browser, in the same spirit as the DOOM tape. **Zero runtime network fetches** —
the CPU emulator, firmware, and bootable Linux image are all embedded inline (base64).
Works over both `file://` and `http://`.

## Artifact

- **Deliverable:** `payloads/v86/dist/v86_linux.html`
- **Assembler:** `payloads/v86/build/assemble_v86_html.py` (regenerates the HTML from the
  tracked source bundle)
- **Verifier:** `payloads/v86/build/verify_boot.mjs` (headless-Chromium CDP boot proof)

## What's embedded (all inline, no fetches)

| Component | Source | Size | How it's fed to V86 |
|---|---|---|---|
| `libv86.js` | v86 npm 0.5.372 engine loader | 352 KB | inline `<script>` |
| `v86.wasm` | v86 x86→wasm JIT core | 2.07 MB | base64 → `wasm_fn(imports)` custom loader |
| `seabios.bin` | SeaBIOS firmware | 131 KB | base64 → `bios: {buffer}` |
| `vgabios.bin` | VGA BIOS | 36 KB | base64 → `vga_bios: {buffer}` |
| `linux.iso` | Buildroot Linux (ISO9660 bootable) | 5.67 MB | base64 → `cdrom: {buffer}` |

The v86 default loader *fetches* `build/v86.wasm` at runtime. We override it with a custom
`wasm_fn(imports) => WebAssembly.instantiate(inlinedBuffer, imports).then(r => r.instance.exports)`,
mirroring v86's internal contract, so the wasm comes from the inlined ArrayBuffer — no fetch.
BIOS / VGA BIOS / ISO use the documented `{buffer: ArrayBuffer}` image form.

Source assets live in `payloads/built/v86_linux/bundle/` (binaries gitignored, regenerable
via `payloads/built/v86_linux/build_v86_linux.sh`).

## Versions / image details

- **v86:** npm `v86@0.5.372` (prebuilt `libv86.js` + `v86.wasm`). License BSD-2-Clause.
- **Firmware:** SeaBIOS + VGABIOS as shipped by `copy/v86` (`bios/seabios.bin`,
  `bios/vgabios.bin`). License LGPLv3.
- **OS:** Buildroot `linux.iso` from `copy/images` — an ISO9660 bootable image. Boots a
  Linux kernel with an ext2 RAM disk root (~3.9 MB initramfs) and a BusyBox userspace,
  reaching a `Welcome to Buildroot` login. Configured here with 32 MB RAM, 2 MB VGA mem.

## Sizes & tier fit

- **Raw HTML:** 10,893,877 bytes (**10.894 MB**) — base64 inflates the ~8.3 MB of binaries ~33%.
- **xz -9:** 3,096,608 bytes (**3.097 MB**).

| Tier | Capacity | Fits? |
|---|---|---|
| C60 side | 1.24 MB | no |
| C90 side | 1.86 MB | no |
| **whole C90** | **3.73 MB** | **YES** (0.63 MB headroom) |

Note: the catalogue's 2.538 MB "on tape" figure is for the *raw bundle* (.tar.xz of the
binaries). This artifact is the larger *self-contained HTML* (base64 + libv86.js + HTML
chrome), so it lands at 3.097 MB xz — a whole-C90 payload rather than a single side.

## Verification (headless Chromium, CDP, over HTTP)

Served via `python3 -m http.server 8812`; loaded in a dedicated headless-Chromium instance
(the shared MCP browser was being navigated by concurrent sessions, so an isolated CDP
driver was used instead). `file://` is blocked in that harness but the inline-only design
is path-agnostic.

**Zero runtime fetches confirmed.** Total network requests: **2** —
`http://localhost:8812/v86_linux.html` (the page itself) and one `blob:` URL (v86's internal
worker, created from inline bytes). **No** offsite requests, **no** BIOS/wasm/ISO fetches,
**no** failed/4xx requests (favicon excluded).

**Linux booted — proof snippets:**

VGA text-mode console (kernel boot log, tail):
```
[    1.824936] hdc: v86 ATAPI CD-ROM, ATAPI CD/DVD-ROM drive
[    2.555003] RAMDISK: ext2 filesystem found at block 0
[    2.555003] RAMDISK: Loading 3883KiB [1 disk] into ram disk... done.
[    2.713897] VFS: Mounted root (ext2 filesystem) on device 1:0.
/root%
```

Serial terminal (userspace login reached):
```
Welcome to Buildroot
(none) login:
```

Status line flipped to: `✓ Linux booted from cassette — shell ready.`
The serial channel is interactive (a typed `uname -a` was accepted at the login prompt,
which then asked for `Password:` — confirming a live BusyBox getty). Kernel + userspace
both fully booted.

## License & source-ship note

- **v86** — BSD-2-Clause (Copyright © 2012 The v86 contributors).
- **SeaBIOS / VGABIOS** — LGPLv3.
- **Linux kernel + BusyBox (Buildroot image)** — **GPL-2.0**.

The GPL components make this **gpl_with_source**: corresponding source must ship alongside,
exactly like the DOOM tape's side B. Source pointers are in the page footer and in
`payloads/built/v86_linux/bundle/SOURCE_AND_LICENSES.md`:
v86 → https://github.com/copy/v86 · Buildroot → https://buildroot.org/downloads/ ·
kernel → https://kernel.org .
