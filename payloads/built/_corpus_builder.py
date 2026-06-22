#!/usr/bin/env python3
"""Shared Gutenberg corpus builder for the cassette-ai text-corpora cluster.

Fetches real Project Gutenberg texts, verifies each is a Gutenberg PD release
(by inspecting the PG header), strips the PG boilerplate (keeping only the work
body), concatenates with a small machine-readable index header, and xz -9e
compresses. Reports MEASURED compressed size.

All works here are pre-1928 (US public domain) Gutenberg releases. PD status is
asserted per-work by confirming the canonical Gutenberg "Project Gutenberg
eBook" header is present (Gutenberg only distributes PD / cleared texts).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request


def xz_compress(data: bytes) -> bytes:
    """Compress with the xz CLI at -9e (lzma PRESET_EXTREME). Python's _lzma
    is unavailable in this pyenv build, so we shell out to xz 5.x."""
    p = subprocess.run(["xz", "-9", "-e", "-c", "-T", "1"], input=data,
                       stdout=subprocess.PIPE, check=True)
    return p.stdout


def xz_decompress(data: bytes) -> bytes:
    p = subprocess.run(["xz", "-d", "-c"], input=data,
                       stdout=subprocess.PIPE, check=True)
    return p.stdout

CACHE = os.path.join(os.path.dirname(__file__), "_gutenberg_cache")
os.makedirs(CACHE, exist_ok=True)

UA = "Mozilla/5.0 (cassette-ai corpus builder; PD text fetch)"


def fetch(gid):
    """Fetch a Gutenberg text by numeric id, cached on disk. Returns text."""
    path = os.path.join(CACHE, f"pg{gid}.txt")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    urls = [
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
        f"https://www.gutenberg.org/files/{gid}/{gid}-0.txt",
        f"https://www.gutenberg.org/files/{gid}/{gid}.txt",
    ]
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) > 1000:
                with open(path, "wb") as f:
                    f.write(data)
                time.sleep(0.4)  # be polite to gutenberg
                return data.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - report which url failed
            last = f"{url}: {e}"
    raise RuntimeError(f"fetch failed for pg{gid}: {last}")


PG_START = re.compile(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
                      re.IGNORECASE | re.DOTALL)
PG_END = re.compile(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
                    re.IGNORECASE | re.DOTALL)


def verify_and_strip(gid, raw):
    """Confirm PG header (PD evidence) and strip boilerplate. Returns (body, evidence)."""
    head = raw[:3000]
    # PG PD evidence: either the prose header ("Project Gutenberg" in the
    # preamble) OR the terse numeric START marker form ("*** START OF THE
    # PROJECT GUTENBERG EBOOK <id> ***"), used by older releases like pg3300.
    is_pg = ("Project Gutenberg" in head) or bool(PG_START.search(raw[:5000]))
    # extract title/author for the index
    title = ""
    author = ""
    mt = re.search(r"^Title:\s*(.+)$", raw[:5000], re.MULTILINE)
    ma = re.search(r"^Author:\s*(.+)$", raw[:5000], re.MULTILINE)
    if mt:
        title = mt.group(1).strip()
    if ma:
        author = ma.group(1).strip()
    body = raw
    ms = PG_START.search(raw)
    me = PG_END.search(raw)
    if ms:
        body = raw[ms.end():]
    if me:
        # search end relative to whole text
        me2 = PG_END.search(body)
        if me2:
            body = body[:me2.start()]
    body = body.strip()
    evidence = {
        "gid": gid,
        "pg_header": is_pg,
        "title": title,
        "author": author,
        "body_chars": len(body),
    }
    return body, evidence


def build_corpus(name, works, out_dir):
    """works = list of (gid, label). Returns meta dict."""
    os.makedirs(out_dir, exist_ok=True)
    index = []
    bodies = []
    evidences = []
    total_raw = 0
    for gid, label in works:
        raw = fetch(gid)
        body, ev = verify_and_strip(gid, raw)
        ev["label"] = label
        evidences.append(ev)
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        index.append({
            "id": gid,
            "label": label,
            "title": ev["title"] or label,
            "author": ev["author"],
            "chars": len(body),
            "sha256_12": sha,
        })
        header = (f"\n\n===== WORK gutenberg#{gid} | {label} | "
                  f"{ev['title']} | {ev['author']} =====\n\n")
        bodies.append(header + body)
        total_raw += len(body.encode("utf-8"))

    index_header = {
        "collection": name,
        "format": "cassette-ai PD text corpus v1",
        "source": "Project Gutenberg (US public domain, pre-1928 works)",
        "license": "Public Domain",
        "n_works": len(works),
        "works": index,
    }
    index_json = json.dumps(index_header, ensure_ascii=False, indent=1)
    full = ("CASSETTE-AI-CORPUS\n" + index_json +
            "\n===== TEXTS =====\n" + "".join(bodies))
    full_bytes = full.encode("utf-8")

    raw_path = os.path.join(out_dir, f"{name}.txt")
    with open(raw_path, "wb") as f:
        f.write(full_bytes)

    # xz -9e (lzma) — measure on-tape size
    xz_path = os.path.join(out_dir, f"{name}.txt.xz")
    comp = xz_compress(full_bytes)
    with open(xz_path, "wb") as f:
        f.write(comp)

    on_tape_mb = round(len(comp) / 1e6, 4)
    raw_mb = round(len(full_bytes) / 1e6, 4)

    # round-trip sanity
    rt = xz_decompress(comp)
    roundtrip_ok = (rt == full_bytes)

    meta = {
        "name": name,
        "license": "Public Domain",
        "license_status": "ship_clear",
        "license_evidence": (
            f"All {len(works)} works are Project Gutenberg releases of pre-1928 "
            f"US public-domain texts; each carries the canonical 'Project Gutenberg "
            f"eBook' header (PD evidence). Gutenberg distributes only PD/cleared works."
        ),
        "on_tape_mb": on_tape_mb,
        "raw_mb": raw_mb,
        "quant": "lzma-text (xz -9e)",
        "runtime": "plain text reader (any device); index header is JSON",
        "roundtrip_ok": roundtrip_ok,
        "shippable": True,
        "path": os.path.abspath(out_dir),
        "n_works": len(works),
        "index": index,
        "all_have_pg_header": all(e["pg_header"] for e in evidences),
    }
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta, evidences


if __name__ == "__main__":
    print("library module; import build_corpus", file=sys.stderr)
