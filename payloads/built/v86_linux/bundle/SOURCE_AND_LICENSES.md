# v86 Linux cassette — licenses & source

## Engine
- v86 (libv86.js, v86.wasm): BSD-2-Clause — see LICENSE.v86.bsd2. Source: https://github.com/copy/v86

## Firmware
- seabios.bin: SeaBIOS, LGPLv3 (the v86 build of SeaBIOS). Source: https://github.com/copy/v86 (tree: src/native/ / seabios submodule) and upstream https://github.com/coreboot/seabios
- vgabios.bin: SeaVGABIOS / LGPLv3, same SeaBIOS source tree.

## Operating system (GPL — ship source)
- linux.iso: a Buildroot Linux system (Linux kernel = GPL-2.0; BusyBox userland = GPL-2.0;
  glibc/uClibc + assorted permissive libs). Built with Buildroot (https://buildroot.uclibc.org/).
  Image provenance: https://github.com/copy/images (Readme cites Buildroot as the source).
  GPL COMPLIANCE: to satisfy GPL-2.0 §3, the corresponding source must be shippable alongside.
  Source: Buildroot release tree at https://buildroot.org/downloads/ + Linux kernel source at
  https://kernel.org. This bundle is therefore classified gpl_with_source (analogous to the
  DOOM side-B GPL source ship).
