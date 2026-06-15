#!/usr/bin/env python3
"""Build the three 2026-06-15 text corpora for cassette-ai.

  1. corpus_lagerlof          — Selma Lagerlöf, bilingual (SV originals + EN
                                translations). PUBLIC DOMAIN.
  2. corpus_blackwood         — Algernon Blackwood weird tales. PUBLIC DOMAIN.
  3. corpus_contemporary_cc   — modern CC-licensed fiction (Doctorow BY-NC-SA,
                                Watts BY-NC-SA, SCP Foundation BY-SA 3.0).

Sources (every URL HTTP-probed + license-verified live on 2026-06-15):
  * English PD translations / Blackwood : Project Gutenberg (gutendex copyright=false).
  * Swedish PD originals                : Project Runeberg (proofread chapter HTML /
                                          page OCR .txt; each title verified Lagerlöf).
  * Doctorow                            : craphound.com .txt (CC BY-NC-SA embedded).
  * Watts — Blindsight                  : rifters.com (CC BY-NC-SA 2.5 embedded).
  * SCP Foundation                      : scp-data export (site-wide CC BY-SA 3.0).

Requires: python3, curl (or urllib), xz. Run: python3 _build_new_corpora.py
Outputs <name>.txt (raw) + <name>.txt.xz (on-tape) + meta.json per corpus, and
the PROVENANCE.md / ATTRIBUTION.md license docs.
"""
import hashlib
import html as Hmod
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile

BUILT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BUILT, "_corpus_cache")
os.makedirs(CACHE, exist_ok=True)
UA = "Mozilla/5.0 (cassette-ai corpus builder; PD/CC text fetch)"


# --------------------------------------------------------------------------- #
# generic helpers
# --------------------------------------------------------------------------- #
def xz_compress(data: bytes) -> bytes:
    p = subprocess.run(["xz", "-9", "-e", "-c", "-T", "1"], input=data,
                       stdout=subprocess.PIPE, check=True)
    return p.stdout


def xz_decompress(data: bytes) -> bytes:
    p = subprocess.run(["xz", "-d", "-c"], input=data,
                       stdout=subprocess.PIPE, check=True)
    return p.stdout


def http_get(url: str, cache_name: str, min_size: int = 500) -> bytes:
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path) and os.path.getsize(path) > min_size:
        with open(path, "rb") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    if len(data) < min_size:
        raise RuntimeError(f"fetch too small ({len(data)} B) for {url}")
    with open(path, "wb") as f:
        f.write(data)
    time.sleep(0.4)
    return data


def decode_text(data: bytes) -> str:
    """Decode bytes preferring UTF-8 (Runeberg's modern files), falling back to
    latin-1 only if UTF-8 is invalid. Decoding UTF-8 bytes as latin-1 silently
    corrupts every accented character (å -> Ã¥), so the order matters."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", "replace")


def strip_html(h: str) -> str:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</p>", "\n\n", h, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", h)
    t = Hmod.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# --------------------------------------------------------------------------- #
# Project Gutenberg
# --------------------------------------------------------------------------- #
PG_START = re.compile(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
                      re.IGNORECASE | re.DOTALL)
PG_END = re.compile(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
                    re.IGNORECASE | re.DOTALL)


def fetch_gutenberg(gid: int):
    """Return (body, meta) for a Gutenberg id; verify PG header + strip boilerplate."""
    url = f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"
    raw = http_get(url, f"pg{gid}.txt", min_size=1000).decode("utf-8", "replace")
    is_pg = ("Project Gutenberg" in raw[:3000]) or bool(PG_START.search(raw[:5000]))
    mt = re.search(r"^Title:\s*(.+)$", raw[:5000], re.MULTILINE)
    ma = re.search(r"^Author:\s*(.+)$", raw[:5000], re.MULTILINE)
    title = mt.group(1).strip() if mt else ""
    author = ma.group(1).strip() if ma else ""
    body = raw
    ms = PG_START.search(raw)
    if ms:
        body = raw[ms.end():]
    me = PG_END.search(body)
    if me:
        body = body[:me.start()]
    body = body.strip()
    return body, {"pg_header": is_pg, "title": title, "author": author}


# --------------------------------------------------------------------------- #
# Project Runeberg (Swedish PD originals)
#   Two storage styles seen in the wild:
#     - proofread chapter HTML  (k01.html, k02.html, ...) -> clean text
#     - page OCR text           (NNN.txt, page-split)     -> concat, light clean
# --------------------------------------------------------------------------- #
def fetch_runeberg(code: str, kind: str):
    """kind='html' uses proofread chapter HTML; kind='ocr' uses page .txt OCR.
    Returns (body, title)."""
    zurl = f"https://runeberg.org/download.pl?mode=txtzip&work={code}"
    zbytes = http_get(zurl, f"runeberg_{code}.zip", min_size=2000)
    zpath = os.path.join(CACHE, f"runeberg_{code}.zip")
    z = zipfile.ZipFile(zpath)
    names = z.namelist()
    # title from the project index page
    ihtml = decode_text(http_get(f"https://runeberg.org/{code}/",
                                 f"runeberg_{code}_index.html", min_size=500))
    mt = re.search(r"<title>(.*?)</title>", ihtml, re.S)
    title = Hmod.unescape(mt.group(1).strip()) if mt else code

    if kind == "html":
        # chapter files: Runeberg uses several conventions across works:
        #   k01.html/i01.html (intro+chapter), 01.html, or bare 0.html/1.html.
        # Match <optional letters><digits><optional letters>.html; skip index.html
        # and the .lst/meta files. Sort by (letter-group, numeric) so intro 'i'
        # pages precede chapter 'k' pages and numbers order numerically.
        def chap_key(n):
            b = os.path.basename(n)
            m = re.match(r"^([a-z]*)(\d+)([a-z]*)\.html$", b)
            return (m.group(1), int(m.group(2)), m.group(3))
        chaps = [n for n in names
                 if re.match(r"^[a-z]*\d+[a-z]*\.html$", os.path.basename(n))
                 and os.path.basename(n) != "index.html"]
        chaps.sort(key=chap_key)
        parts = []
        for n in chaps:
            raw = decode_text(z.read(n))
            parts.append(strip_html(raw))
        body = "\n\n".join(p for p in parts if p.strip())
    elif kind == "ocr":
        # page OCR text files: NNNN.txt in numeric order
        pages = sorted((n for n in names
                        if re.match(r"^\d+\.txt$", os.path.basename(n))),
                       key=lambda n: int(re.match(r"(\d+)", os.path.basename(n)).group(1)))
        chunks = []
        for n in pages:
            txt = decode_text(z.read(n))
            chunks.append(txt)
        body = "".join(chunks)
        # light OCR cleanup: collapse hard-wrap hyphenation + excess blanklines
        body = re.sub(r"-\n(\w)", r"\1", body)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
    else:
        raise ValueError(kind)
    return body.strip(), title


# --------------------------------------------------------------------------- #
# craphound.com (Doctorow) + rifters.com (Watts)
# --------------------------------------------------------------------------- #
def fetch_url_text(url: str, cache_name: str, is_html: bool):
    data = http_get(url, cache_name, min_size=2000)
    # craphound .txt files are UTF-8 (with BOM); rifters .htm is latin-1
    if is_html:
        h = data.decode("latin-1", "replace")
        return strip_html(h)
    txt = data.decode("utf-8-sig", "replace")
    return txt.strip()


# --------------------------------------------------------------------------- #
# SCP Foundation (CC BY-SA 3.0) — scp-data export
# --------------------------------------------------------------------------- #
SCP_SERIES_BASE = ("https://raw.githubusercontent.com/scp-data/scp-api/master/"
                   "docs/data/scp/items/content_series-{n}.json")


def fetch_scp(items):
    """items = list of 'SCP-NNN' keys. Returns list of dicts with text+attribution.
    Loads SCP series 1-3 (covers SCP-001..2999) and resolves each item."""
    d = {}
    for n in (1, 2, 3):
        raw = http_get(SCP_SERIES_BASE.format(n=n), f"scp_series{n}.json",
                       min_size=10000)
        d.update(json.loads(raw))
    out = []
    for key in items:
        if key not in d:
            out.append({"key": key, "missing": True})
            continue
        e = d[key]
        text = strip_html(e.get("raw_content", "") or "")
        out.append({
            "key": key,
            "title": e.get("title", key),
            "creator": e.get("creator", "unknown"),
            "url": e.get("url", f"https://scp-wiki.wikidot.com/{e.get('link', key.lower())}"),
            "tags_cc": "_cc" in (e.get("tags") or []),
            "text": text,
            "chars": len(text),
        })
    return out


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def assemble(name, header_meta, works):
    """works = list of dict(section_label, text, **index_fields). Writes txt+xz+meta."""
    out_dir = os.path.join(BUILT, name)
    os.makedirs(out_dir, exist_ok=True)
    index = []
    bodies = []
    for w in works:
        text = w["text"]
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        idx = {k: v for k, v in w.items() if k != "text"}
        idx["chars"] = len(text)
        idx["sha256_12"] = sha
        index.append(idx)
        hdr = f"\n\n===== {w['section_label']} =====\n\n"
        bodies.append(hdr + text)

    index_header = dict(header_meta)
    index_header["n_works"] = len(works)
    index_header["works"] = index
    index_json = json.dumps(index_header, ensure_ascii=False, indent=1)
    full = ("CASSETTE-AI-CORPUS\n" + index_json +
            "\n===== TEXTS =====\n" + "".join(bodies))
    full_bytes = full.encode("utf-8")

    with open(os.path.join(out_dir, f"{name}.txt"), "wb") as f:
        f.write(full_bytes)
    comp = xz_compress(full_bytes)
    with open(os.path.join(out_dir, f"{name}.txt.xz"), "wb") as f:
        f.write(comp)
    roundtrip_ok = (xz_decompress(comp) == full_bytes)
    return {
        "on_tape_mb": round(len(comp) / 1e6, 4),
        "raw_mb": round(len(full_bytes) / 1e6, 4),
        "roundtrip_ok": roundtrip_ok,
        "n_works": len(works),
        "index": index,
        "out_dir": out_dir,
    }


def write_meta(out_dir, meta):
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


# ========================================================================== #
# 1. corpus_lagerlof  (bilingual, PUBLIC DOMAIN)
# ========================================================================== #
# Swedish originals on Project Runeberg. (code, kind, label)
# Only proofread chapter-HTML works are included: their text is clean PD body.
# The page-OCR-only works on Runeberg (e.g. kristleg, troll) are *excluded* because
# their OCR was produced from a *later* (still-in-copyright) Bonniers edition and the
# scan front-matter carries that edition's ISBN/© cover page — a provenance risk we
# refuse to ship. (The PD body text exists, but the OCR mixes in the modern edition's
# paratext, so we drop them rather than include unverifiable bytes.)
LAGERLOF_SV = [
    ("berling",  "html", "Gösta Berlings saga (1891)"),
    ("nilsholg", "html", "Nils Holgerssons underbara resa genom Sverige (1906–07)"),
    ("osynliga", "html", "Osynliga länkar (1894)"),
    ("herrgard", "html", "En herrgårdssägen (1899)"),
    ("jerusalm", "html", "Jerusalem (1901–02)"),
]
# English PD translations on Project Gutenberg (gutendex copyright=false). (gid, label)
LAGERLOF_EN = [
    (56158, "The Story of Gösta Berling (tr. Pauline Bancroft Flach)"),
    (10935, "The Wonderful Adventures of Nils (tr. Velma Swanston Howard)"),
    (14356, "The Emperor of Portugallia (tr. Velma Swanston Howard)"),
    (14273, "Invisible Links (tr. Pauline Bancroft Flach)"),
    (54615, "The Miracles of Antichrist (tr. Pauline Bancroft Flach)"),
    (44818, "Christ Legends (tr. Velma Swanston Howard)"),
]


def build_lagerlof():
    works = []
    for code, kind, label in LAGERLOF_SV:
        body, title = fetch_runeberg(code, kind)
        works.append({
            "section_label": f"[SV] {label}  ·  Selma Lagerlöf  ·  Project Runeberg /{code}/",
            "lang": "sv", "source": "Project Runeberg", "runeberg_code": code,
            "title": title, "author": "Selma Lagerlöf",
            "license": "Public Domain", "text": body,
        })
    for gid, label in LAGERLOF_EN:
        body, m = fetch_gutenberg(gid)
        works.append({
            "section_label": f"[EN] {label}  ·  Project Gutenberg #{gid}",
            "lang": "en", "source": "Project Gutenberg", "gutenberg_id": gid,
            "title": m["title"] or label, "author": m["author"] or "Selma Lagerlöf",
            "license": "Public Domain", "pg_header": m["pg_header"], "text": body,
        })
    res = assemble("corpus_lagerlof", {
        "collection": "corpus_lagerlof",
        "format": "cassette-ai bilingual PD text corpus v1",
        "theme": "Selma Lagerlöf — Swedish Nobel laureate (1909), bilingual SV+EN",
        "license": "Public Domain",
        "license_basis": ("Selma Lagerlöf d. 1940: PD in SE/EU since 2011 (life+70). "
                          "Swedish originals are her own pre-1929 texts (US-PD). English "
                          "translations are all Project Gutenberg releases with "
                          "copyright=false (PD translation)."),
        "source": "Project Runeberg (SV originals) + Project Gutenberg (EN translations)",
    }, works)
    meta = {
        "name": "corpus_lagerlof",
        "tier": "text-corpus",
        "theme": "Selma Lagerlöf — bilingual Swedish/English (the Swedish flex)",
        "license": "Public Domain",
        "license_status": "ship_clear",
        "license_evidence": (
            "Selma Lagerlöf died 1940 -> PD in SE/EU (life+70, since 2011). Swedish "
            "originals are her own pre-1929 works (also US-PD). All English translations "
            "are Project Gutenberg releases listed copyright=false (PD translation), "
            "verified live via gutendex on 2026-06-15. See PROVENANCE.md."),
        "n_works": res["n_works"],
        "n_swedish": len(LAGERLOF_SV), "n_english": len(LAGERLOF_EN),
        "on_tape_mb": res["on_tape_mb"], "raw_mb": res["raw_mb"],
        "quant": "lzma-text (xz -9e)",
        "runtime": "plain text reader (any device); index header is JSON; bilingual",
        "roundtrip_ok": res["roundtrip_ok"], "shippable": True,
        "path": res["out_dir"], "index": res["index"],
        "skipped": [
            {"work": "Kristuslegender / Troll och människor (Runeberg kristleg, troll)",
             "reason": ("Runeberg has these only as page-OCR from a later Bonniers "
                        "edition; the OCR carries that modern edition's ISBN/© cover "
                        "front-matter. The Lagerlöf body is PD, but to avoid shipping "
                        "non-PD paratext we excluded the OCR-only volumes and kept only "
                        "the proofread chapter-HTML originals.")},
            {"work": "Antikrists mirakler (Swedish original)",
             "reason": ("no clean PD Swedish full-text source located on Runeberg/"
                        "Litteraturbanken; the English translation (The Miracles of "
                        "Antichrist, PG #54615) IS included instead.")},
        ],
        "source_urls": ["https://runeberg.org/", "https://gutenberg.org/",
                        "https://gutendex.com/"],
    }
    write_meta(res["out_dir"], meta)
    write_lagerlof_provenance(res["out_dir"], res["index"])
    return meta


# ========================================================================== #
# 2. corpus_blackwood  (weird tales, PUBLIC DOMAIN)
# ========================================================================== #
BLACKWOOD = [
    (11438, "The Willows (1907)"),
    (10897, "The Wendigo (1910)"),
    (49222, "John Silence — Physician Extraordinary (1908)"),
    (9964,  "The Centaur (1911)"),
    (14471, "The Empty House and Other Ghost Stories (1906)"),
    (43816, "Incredible Adventures (1914)"),
    (77472, "Pan's Garden — A Volume of Nature Stories (1912)"),
]


def build_blackwood():
    works = []
    for gid, label in BLACKWOOD:
        body, m = fetch_gutenberg(gid)
        works.append({
            "section_label": f"{label}  ·  Algernon Blackwood  ·  Project Gutenberg #{gid}",
            "source": "Project Gutenberg", "gutenberg_id": gid,
            "title": m["title"] or label, "author": m["author"] or "Algernon Blackwood",
            "license": "Public Domain", "pg_header": m["pg_header"], "text": body,
        })
    res = assemble("corpus_blackwood", {
        "collection": "corpus_blackwood",
        "format": "cassette-ai PD text corpus v1",
        "theme": "Algernon Blackwood — classic weird/supernatural fiction",
        "license": "Public Domain",
        "license_basis": ("Algernon Blackwood d. 1951. All works here are pre-1929 "
                          "(US public domain) Project Gutenberg releases (copyright=false)."),
        "source": "Project Gutenberg (US public domain, pre-1929 works)",
    }, works)
    meta = {
        "name": "corpus_blackwood",
        "tier": "text-corpus",
        "theme": "Algernon Blackwood — weird tales (The Willows, The Wendigo, ...)",
        "license": "Public Domain",
        "license_status": "ship_clear",
        "license_evidence": (
            "Algernon Blackwood died 1951. Every work here is a pre-1929 US-public-domain "
            "Project Gutenberg release, each listed copyright=false (verified via gutendex "
            "2026-06-15) and carrying the canonical Project Gutenberg PD header. "
            "See PROVENANCE.md."),
        "n_works": res["n_works"],
        "on_tape_mb": res["on_tape_mb"], "raw_mb": res["raw_mb"],
        "quant": "lzma-text (xz -9e)",
        "runtime": "plain text reader (any device); index header is JSON",
        "roundtrip_ok": res["roundtrip_ok"], "shippable": True,
        "path": res["out_dir"], "index": res["index"],
        "all_have_pg_header": all(w.get("pg_header") for w in res["index"]),
        "source_urls": ["https://gutenberg.org/", "https://gutendex.com/"],
    }
    write_meta(res["out_dir"], meta)
    write_blackwood_provenance(res["out_dir"], res["index"])
    return meta


# ========================================================================== #
# 3. corpus_contemporary_cc  (modern, CC-licensed)
# ========================================================================== #
DOCTOROW = [
    ("https://craphound.com/littlebrother/Cory_Doctorow_-_Little_Brother.txt",
     "Little Brother (2008)", "littlebrother"),
    ("https://craphound.com/down/Cory_Doctorow_-_Down_and_Out_in_the_Magic_Kingdom.txt",
     "Down and Out in the Magic Kingdom (2003)", "down"),
    ("https://craphound.com/ftw/Cory_Doctorow_-_For_the_Win.txt",
     "For the Win (2010)", "ftw"),
]
# curated classic SCP set (Series I). Site-wide license: CC BY-SA 3.0.
SCP_ITEMS = [
    "SCP-002", "SCP-004", "SCP-005", "SCP-006", "SCP-035", "SCP-049", "SCP-055",
    "SCP-073", "SCP-087", "SCP-093", "SCP-096", "SCP-106", "SCP-173", "SCP-178",
    "SCP-231", "SCP-294", "SCP-343", "SCP-426", "SCP-500", "SCP-682", "SCP-914",
    "SCP-999", "SCP-1000", "SCP-1471", "SCP-2317",
]


def build_contemporary_cc():
    works = []
    attribution = []  # for ATTRIBUTION.md

    # --- Doctorow (CC BY-NC-SA 3.0) ---
    for url, label, slug in DOCTOROW:
        body = fetch_url_text(url, f"doctorow_{slug}.txt", is_html=False)
        works.append({
            "section_label": f"{label}  ·  Cory Doctorow  ·  CC BY-NC-SA 3.0  ·  {url}",
            "title": label, "author": "Cory Doctorow",
            "license": "CC BY-NC-SA 3.0", "source_url": url, "text": body,
        })
        attribution.append({
            "title": label, "author": "Cory Doctorow", "license": "CC BY-NC-SA 3.0",
            "license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
            "source_url": url, "noncommercial": True, "share_alike": True,
        })

    # --- Watts — Blindsight (CC BY-NC-SA 2.5) ---
    bs_url = "https://www.rifters.com/real/Blindsight.htm"
    bs = fetch_url_text(bs_url, "watts_blindsight.htm", is_html=True)
    works.append({
        "section_label": f"Blindsight (2006)  ·  Peter Watts  ·  CC BY-NC-SA 2.5  ·  {bs_url}",
        "title": "Blindsight", "author": "Peter Watts",
        "license": "CC BY-NC-SA 2.5", "source_url": bs_url, "text": bs,
    })
    attribution.append({
        "title": "Blindsight (2006)", "author": "Peter Watts", "license": "CC BY-NC-SA 2.5",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/2.5/",
        "source_url": bs_url, "noncommercial": True, "share_alike": True,
    })

    # --- SCP Foundation (CC BY-SA 3.0) ---
    scp = fetch_scp(SCP_ITEMS)
    scp_present = [s for s in scp if not s.get("missing")]
    scp_missing = [s["key"] for s in scp if s.get("missing")]
    # one combined SCP section (keep the bundle modest, attribution per article inside)
    parts = []
    for s in scp_present:
        parts.append(
            f"----- {s['key']}: {s['title']} -----\n"
            f"Author: {s['creator']}  |  {s['url']}  |  CC BY-SA 3.0\n\n{s['text']}\n")
    scp_text = "\n\n".join(parts)
    works.append({
        "section_label": (f"SCP Foundation — {len(scp_present)} curated articles  ·  "
                          f"CC BY-SA 3.0  ·  https://scp-wiki.wikidot.com/"),
        "title": f"SCP Foundation ({len(scp_present)} articles)",
        "author": "SCP Foundation community (per-article authors listed inline)",
        "license": "CC BY-SA 3.0", "source_url": "https://scp-wiki.wikidot.com/",
        "n_articles": len(scp_present), "articles": [
            {"id": s["key"], "title": s["title"], "author": s["creator"], "url": s["url"]}
            for s in scp_present],
        "text": scp_text,
    })
    for s in scp_present:
        attribution.append({
            "title": f"{s['key']}: {s['title']}", "author": s["creator"],
            "license": "CC BY-SA 3.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
            "source_url": s["url"], "noncommercial": False, "share_alike": True,
        })

    res = assemble("corpus_contemporary_cc", {
        "collection": "corpus_contemporary_cc",
        "format": "cassette-ai CC-licensed text corpus v1",
        "theme": "Modern Creative-Commons fiction (Doctorow, Watts, SCP Foundation)",
        "license": "MIXED — CC BY-NC-SA + CC BY-SA (see per-work tags)",
        "license_warning": ("CONTAINS NONCOMMERCIAL (NC) WORKS. cassette-ai must remain "
                            "non-commercial while it ships these. SCP is BY-SA (no NC) "
                            "but ShareAlike. See ATTRIBUTION.md."),
        "source": "craphound.com (Doctorow), rifters.com (Watts), scp-wiki / scp-data (SCP)",
    }, works)

    meta = {
        "name": "corpus_contemporary_cc",
        "tier": "text-corpus",
        "theme": "Modern CC-licensed fiction — Doctorow, Watts, SCP Foundation",
        "license": "MIXED: CC BY-NC-SA 3.0 / 2.5 (Doctorow, Watts) + CC BY-SA 3.0 (SCP)",
        "license_status": "cc_by_nc_sa_noncommercial",
        "license_warning": ("⚠️ This bundle contains NonCommercial (NC) works — cassette-ai "
                            "must remain non-commercial while it ships these."),
        "license_evidence": (
            "Doctorow .txt downloads embed 'Attribution-NonCommercial-ShareAlike 3.0' "
            "(verified per-file 2026-06-15). Watts Blindsight page embeds "
            "'Attribution-NonCommercial-ShareAlike 2.5 License'. SCP wiki licensing-guide "
            "confirms site-wide CC BY-SA 3.0. Full per-work breakdown in ATTRIBUTION.md."),
        "n_works": res["n_works"],
        "n_scp_articles": len(scp_present),
        "on_tape_mb": res["on_tape_mb"], "raw_mb": res["raw_mb"],
        "quant": "lzma-text (xz -9e)",
        "runtime": "plain text reader (any device); index header is JSON",
        "roundtrip_ok": res["roundtrip_ok"], "shippable": True,
        "noncommercial_required": True,
        "path": res["out_dir"], "index": res["index"],
        "skipped": [
            {"title": "Homeland (Doctorow)",
             "reason": "licensed CC BY-NC-ND (NoDerivs), not BY-NC-SA; out of scope"},
            {"title": "Pirate Cinema (Doctorow)",
             "reason": "licensed CC BY-NC-ND (NoDerivs), not BY-NC-SA; out of scope"},
        ],
        "scp_missing_from_export": scp_missing,
        "source_urls": ["https://craphound.com/", "https://www.rifters.com/",
                        "https://scp-wiki.wikidot.com/", "https://github.com/scp-data/scp-api"],
    }
    write_meta(res["out_dir"], meta)
    write_attribution(res["out_dir"], attribution, scp_missing)
    return meta


# --------------------------------------------------------------------------- #
# license / provenance docs
# --------------------------------------------------------------------------- #
def write_lagerlof_provenance(out_dir, index):
    lines = [
        "# PROVENANCE — corpus_lagerlof (PUBLIC DOMAIN)",
        "",
        "**Author:** Selma Lagerlöf (1858–1940), Swedish writer, first woman to win the",
        "Nobel Prize in Literature (1909) and first woman elected to the Swedish Academy.",
        "",
        "**Why public domain**",
        "",
        "- **Swedish originals:** Lagerlöf died **1940**, so all her works are PD in",
        "  Sweden/EU under *life + 70 years* (PD since **1 Jan 2011**). The originals",
        "  reproduced here are pre-1929 texts, also US public domain.",
        "- **English translations:** each is a Project Gutenberg release listed",
        "  `copyright=false` (i.e. PD — pre-1929 US publication; the translators'",
        "  rights have also lapsed). Verified live via gutendex.com on 2026-06-15.",
        "",
        "## Swedish originals — Project Runeberg",
        "",
        "| Work | Runeberg | Basis |",
        "|------|----------|-------|",
    ]
    for w in index:
        if w.get("lang") == "sv":
            lines.append(f"| {w['title']} | https://runeberg.org/{w['runeberg_code']}/ "
                         f"| Lagerlöf original, PD (author d.1940, pre-1929) |")
    lines += ["", "## English translations — Project Gutenberg", "",
              "| Work | Gutenberg | copyright |", "|------|-----------|-----------|"]
    for w in index:
        if w.get("lang") == "en":
            gid = w["gutenberg_id"]
            lines.append(f"| {w['title']} | https://www.gutenberg.org/ebooks/{gid} "
                         f"| false (PD) |")
    lines += [
        "",
        "## Excluded (to keep the bundle provably PD)",
        "",
        "- **Kristuslegender** and **Troll och människor** — Project Runeberg holds these",
        "  only as page-OCR scanned from a *later* Bonniers edition; that OCR's front",
        "  matter carries the modern edition's ISBN and `© Albert Bonniers Förlag` cover",
        "  page. The Lagerlöf text itself is PD, but rather than ship non-PD paratext we",
        "  kept only the proofread chapter-HTML originals.",
        "- **Antikrists mirakler** (Swedish original) — no clean PD Swedish full text was",
        "  located; the **English** translation (*The Miracles of Antichrist*, PG #54615,",
        "  copyright=false) is included instead.",
        "",
        "_All included texts fetched and verified non-empty on 2026-06-15._",
        "",
    ]
    with open(os.path.join(out_dir, "PROVENANCE.md"), "w") as f:
        f.write("\n".join(lines))


def write_blackwood_provenance(out_dir, index):
    lines = [
        "# PROVENANCE — corpus_blackwood (PUBLIC DOMAIN)",
        "",
        "**Author:** Algernon Blackwood (1869–1951), English writer of weird and",
        "supernatural fiction; among the most influential ghost-story writers in English.",
        "",
        "**Why public domain:** every work here was first published **before 1929** and is",
        "therefore in the US public domain. Each is a Project Gutenberg release listed",
        "`copyright=false` (verified via gutendex.com, 2026-06-15) and carries the",
        "canonical Project Gutenberg public-domain header.",
        "",
        "| Work | Gutenberg | First publ. | copyright |",
        "|------|-----------|-------------|-----------|",
    ]
    years = {11438: 1907, 10897: 1910, 49222: 1908, 9964: 1911,
             14471: 1906, 43816: 1914, 77472: 1912}
    for w in index:
        gid = w["gutenberg_id"]
        lines.append(f"| {w['title']} | https://www.gutenberg.org/ebooks/{gid} "
                     f"| {years.get(gid, 'pre-1929')} | false (PD) |")
    lines += ["", "_All texts fetched and verified non-empty on 2026-06-15._", ""]
    with open(os.path.join(out_dir, "PROVENANCE.md"), "w") as f:
        f.write("\n".join(lines))


def write_attribution(out_dir, attribution, scp_missing):
    has_nc = any(a["noncommercial"] for a in attribution)
    lines = [
        "# ATTRIBUTION & LICENSE NOTICE — corpus_contemporary_cc",
        "",
        "This bundle contains **modern, Creative-Commons-licensed** works. Unlike the",
        "public-domain corpora, these carry **conditions you must honour**.",
        "",
        "## ⚠️ NonCommercial (NC) warning",
        "",
        "**This bundle contains NonCommercial (NC) works — cassette-ai must remain",
        "non-commercial while it ships these.** The Cory Doctorow novels and Peter",
        "Watts's *Blindsight* are licensed **CC BY-NC-SA** (NonCommercial-ShareAlike):",
        "they may not be used for commercial purposes. The SCP material is **CC BY-SA**",
        "(no NC clause) but still **ShareAlike**.",
        "",
        "## License obligations summary",
        "",
        "- **CC BY** (all works): give **attribution** — author, title, source, license.",
        "- **CC BY-SA / BY-NC-SA** (all works): **ShareAlike** — any adaptation must be",
        "  distributed under the same (or a compatible) license, with a link to the license.",
        "- **CC BY-NC-SA** (Doctorow, Watts): additionally **NonCommercial** — no commercial use.",
        "",
        "License deeds:",
        "- CC BY-NC-SA 3.0 — https://creativecommons.org/licenses/by-nc-sa/3.0/",
        "- CC BY-NC-SA 2.5 — https://creativecommons.org/licenses/by-nc-sa/2.5/",
        "- CC BY-SA 3.0 — https://creativecommons.org/licenses/by-sa/3.0/",
        "",
        "## Per-work attribution",
        "",
        "### Cory Doctorow & Peter Watts (CC BY-NC-SA — NonCommercial)",
        "",
        "| Work | Author | License | Source |",
        "|------|--------|---------|--------|",
    ]
    for a in attribution:
        if a["noncommercial"]:
            lines.append(f"| {a['title']} | {a['author']} | "
                         f"[{a['license']}]({a['license_url']}) | {a['source_url']} |")
    lines += ["", "### SCP Foundation (CC BY-SA 3.0 — ShareAlike, commercial OK)", "",
              "Source wiki: https://scp-wiki.wikidot.com/ · License guide: "
              "https://scp-wiki.wikidot.com/licensing-guide · Data export: "
              "https://github.com/scp-data/scp-api", "",
              "All SCP content is licensed CC BY-SA 3.0 under the SCP wiki's site-wide",
              "license. Each article is attributed to its author below and inline in the",
              "corpus. (Some early articles predate the per-page `_cc` license box but",
              "remain covered by the site-wide CC BY-SA 3.0 license.)", "",
              "| Article | Author | Source |", "|---------|--------|--------|"]
    for a in attribution:
        if not a["noncommercial"]:
            lines.append(f"| {a['title']} | {a['author']} | {a['source_url']} |")
    if scp_missing:
        lines += ["", f"_SCP items requested but absent from the data export (skipped): "
                  f"{', '.join(scp_missing)}._"]
    lines += ["",
              "## Skipped (license out of scope)",
              "",
              "- **Homeland** (Doctorow) — CC BY-**NC-ND** (NoDerivs), not BY-NC-SA. Skipped.",
              "- **Pirate Cinema** (Doctorow) — CC BY-**NC-ND** (NoDerivs), not BY-NC-SA. Skipped.",
              "",
              "_Licenses confirmed from each source's own embedded notice on 2026-06-15._",
              ""]
    with open(os.path.join(out_dir, "ATTRIBUTION.md"), "w") as f:
        f.write("\n".join(lines))


def main():
    summary = {}
    for fn in (build_lagerlof, build_blackwood, build_contemporary_cc):
        try:
            m = fn()
            summary[m["name"]] = {
                "n_works": m["n_works"], "on_tape_mb": m["on_tape_mb"],
                "raw_mb": m["raw_mb"], "roundtrip_ok": m["roundtrip_ok"],
                "license_status": m["license_status"],
            }
            print(f"[OK] {m['name']}: {m['n_works']} works, raw={m['raw_mb']}MB "
                  f"on_tape={m['on_tape_mb']}MB rt={m['roundtrip_ok']} "
                  f"lic={m['license_status']}")
        except Exception as e:  # noqa: BLE001
            summary[fn.__name__] = {"error": repr(e)}
            print(f"[FAIL] {fn.__name__}: {e!r}")
            raise
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
