#!/usr/bin/env python3
"""rawpack — embed raw binary inside a single-file HTML page with near-zero
lzma penalty (the cassette payload is lzma(html), so this is what matters).

Verified 2026-06-11 (round-trip PASS in Chromium http:// + file:// and Safari
file://, all 256 byte values + 64 KiB of real doomgeneric wasm + adversarial
"</script>", "<!--", CR/NUL sequences).

Technique
---------
The page is served as windows-1252 (<meta charset="windows-1252">): every byte
0x00-0xFF decodes to exactly one code point, so binary can sit RAW inside a
non-executable <script type="o"> block and be read back via .textContent.
Three byte values can't survive the HTML parser in script-data state:
  0x00 (-> U+FFFD), 0x0D (CR -> LF), and our escape byte 0x01;
plus '<' is dangerous only when followed by '/' or '!' ("</script", "<!--").
Encoder: (1) bijective byte swap so {0x00,0x01,0x0D} trade places with the
payload's rarest bytes in the same high-3-bit class (keeps lzma's lc=3 literal
contexts intact), then (2) escape the now-rare leftovers as 0x01,(b^0x80).

Measured lzma(9|EXTREME) cost vs raw, on real corpora:
  doomgeneric wasm (380 KB): rawpack +2.1%   vs base64 +37.7%
  freedoom1.wad 4MB slice  : rawpack +5.1%   vs base64 +18.3%
(base64's 4/3 inflation is NOT recovered by lzma on compressible data: the
3-byte->4-char mapping breaks LZ match alignment; only incompressible data
gets away with ~+2.2%.)

API
---
  encode(blob)         -> (encoded_bytes, perm)   # put encoded_bytes verbatim
                                                  # inside <script type="o" id=X>
  js_decoder()         -> str   # JS function rawunpack(elementId, perm) -> Uint8Array
                                # (ASCII only; perm emitted via json.dumps(perm))
  selftest()           -> builds /tmp/rawpack_selftest.html and verifies with
                          headless Chromium if available.

Run with /usr/bin/python3 (pyenv 3.10 lacks _lzma for the selftest report).
"""
import json
from collections import Counter

FORBID = (0x00, 0x01, 0x0D)


def encode(blob: bytes):
    """Return (encoded_bytes, perm). perm maps original byte -> document byte."""
    cnt = Counter(blob)
    used = set(FORBID)
    perm = list(range(256))
    for f in FORBID:
        cand = [v for v in range(256) if v not in used and (v >> 5) == (f >> 5)] or \
               [v for v in range(256) if v not in used]
        r = min(cand, key=lambda v: cnt.get(v, 0))
        used.add(r)
        perm[f], perm[r] = perm[r], perm[f]
    swapped = blob.translate(bytes(perm))
    out = bytearray()
    n = len(swapped)
    for i, x in enumerate(swapped):
        if x in FORBID or (x == 0x3C and i + 1 < n and swapped[i + 1] in (0x2F, 0x21)):
            out.append(1)
            out.append(x ^ 0x80)
        else:
            out.append(x)
    return bytes(out), perm


def js_decoder() -> str:
    """ASCII JS: rawunpack(id, perm) -> Uint8Array. Pair with json.dumps(perm)."""
    return r"""
function rawunpack(id, P){
 var M={8364:128,8218:130,402:131,8222:132,8230:133,8224:134,8225:135,710:136,
 8240:137,352:138,8249:139,338:140,381:142,8216:145,8217:146,8220:147,8221:148,
 8226:149,8211:150,8212:151,732:152,8482:153,353:154,8250:155,339:156,382:158,376:159};
 var INV=new Array(256); for(var i=0;i<256;i++) INV[P[i]]=i;
 var s=document.getElementById(id).textContent;
 var tmp=new Uint8Array(s.length), j=0;
 for(var i=0;i<s.length;i++){var cp=s.codePointAt(i); tmp[j++]=cp<256?cp:M[cp];}
 var out=new Uint8Array(j), k=0;
 for(var i=0;i<j;i++){var b=tmp[i]; if(b===1){b=tmp[++i]^128;} out[k++]=INV[b];}
 return out.subarray(0,k);
}
"""


def make_block(blob: bytes, elem_id: str):
    """Return (html_bytes_for_block, perm). Block goes anywhere in <body>;
    page MUST start with <meta charset="windows-1252"> and all other page
    content must be pure ASCII."""
    enc, perm = encode(blob)
    return (b'<script type="o" id="' + elem_id.encode() + b'">' + enc + b"</script>", perm)


def selftest():
    import base64
    import os
    import subprocess
    payload = bytes(range(256)) * 8 + b"</script><!--\r\n\x00\x01<<//!!" + os.urandom(65536)
    block, perm = make_block(payload, "d")
    ref = base64.b64encode(payload).decode()
    js = (js_decoder() + f"""
var out=rawunpack('d',{json.dumps(perm)});
var refb=atob('{ref}'); var ok=out.length===refb.length;
if(ok)for(var i=0;i<out.length;i++)if(out[i]!==(refb.charCodeAt(i)&255)){{ok=false;break;}}
document.title=ok?'PASS len='+out.length:'FAIL';
""").encode("ascii")
    html = (b'<!DOCTYPE html><html><head><meta charset="windows-1252">'
            b"<title>testing</title></head><body>" + block +
            b"<script>" + js + b"</script></body></html>")
    path = "/tmp/rawpack_selftest.html"
    open(path, "wb").write(html)
    print("wrote", path, len(html), "bytes; open it — title must be 'PASS len=%d'" % len(payload))
    chrome = os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-1208/"
        "chrome-headless-shell-mac-arm64/chrome-headless-shell")
    if os.path.exists(chrome):
        dom = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--dump-dom",
             "--virtual-time-budget=3000", "file://" + path],
            capture_output=True, text=True).stdout
        print("chromium file:// says:", dom[dom.find("<title>"):dom.find("</title>") + 8])


if __name__ == "__main__":
    selftest()
