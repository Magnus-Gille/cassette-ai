#!/usr/bin/env bash
# Reproduce the v86 + Buildroot-Linux "bootable PC on a cassette" tape payload.
# License: v86 BSD-2-Clause; SeaBIOS/VGABIOS LGPLv3; Linux/Buildroot GPL-2.0.
# => gpl_with_source: ship source pointers (see SOURCE_AND_LICENSES.md).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# 1. v86 engine (BSD-2) from npm registry (prebuilt libv86.js + v86.wasm)
NPMURL=$(curl -sL https://registry.npmjs.org/v86 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); lv=d['dist-tags']['latest']; print(d['versions'][lv]['dist']['tarball'])")
curl -sL -o v86-npm.tgz "$NPMURL"
rm -rf engine && mkdir -p engine && tar xzf v86-npm.tgz -C engine --strip-components=1

# 2. Firmware (SeaBIOS LGPLv3) from copy/v86
mkdir -p bios
curl -sL -o bios/seabios.bin "https://raw.githubusercontent.com/copy/v86/master/bios/seabios.bin"
curl -sL -o bios/vgabios.bin "https://raw.githubusercontent.com/copy/v86/master/bios/vgabios.bin"

# 3. Buildroot Linux ISO (GPL-2.0 kernel + BusyBox) from copy/images
curl -sL -o linux.iso "https://raw.githubusercontent.com/copy/images/master/linux.iso"

# 4. Assemble bundle (engine + bios + iso + license/source notes)
rm -rf bundle && mkdir -p bundle/build bundle/bios
cp engine/build/libv86.js engine/build/v86.wasm bundle/build/
cp bios/seabios.bin bios/vgabios.bin bundle/bios/
cp linux.iso bundle/
cp engine/LICENSE bundle/LICENSE.v86.bsd2
# SOURCE_AND_LICENSES.md (GPL corresponding-source pointers) is written by hand — keep if present.
[ -f bundle/SOURCE_AND_LICENSES.md ] || cat > bundle/SOURCE_AND_LICENSES.md <<'EOF'
See payloads/built/v86_linux/meta.json license_evidence. v86=BSD-2; SeaBIOS=LGPLv3;
linux.iso=Buildroot (Linux kernel + BusyBox, GPL-2.0). gpl_with_source: source at
https://buildroot.org/downloads/ and https://kernel.org ; v86 at https://github.com/copy/v86 .
EOF

# 5. Compress -> on-tape bytes
tar cf bundle.tar -C bundle .
xz -9e -k -f bundle.tar
echo "on_tape_bytes: $(stat -f%z bundle.tar.xz)"
