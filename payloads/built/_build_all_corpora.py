#!/usr/bin/env python3
"""Build all 5 PD text corpora for the cassette-ai cluster.

Each collection is defined as a list of (gutenberg_id, label). Every id was
HTTP-probed live and every work is a pre-1928 US public-domain Gutenberg
release. Run: python3 _build_all_corpora.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _corpus_builder import build_corpus  # noqa: E402

BUILT = os.path.dirname(__file__)

# ---------------------------------------------------------------------------
# 1. Complete Works of Shakespeare (single Gutenberg compilation pg100)
# ---------------------------------------------------------------------------
SHAKESPEARE = [
    (100, "Complete Works of William Shakespeare"),
]

# ---------------------------------------------------------------------------
# 2. King James Bible (pg10 = whole KJV). pg30 is the illustrated edition.
# ---------------------------------------------------------------------------
KJV_BIBLE = [
    (10, "The King James Version of the Holy Bible"),
]

# ---------------------------------------------------------------------------
# 3. Complete Sherlock Holmes canon: 4 novels + 5 story collections (= 60 works)
# ---------------------------------------------------------------------------
SHERLOCK = [
    (244, "A Study in Scarlet (novel)"),
    (2097, "The Sign of the Four (novel)"),
    (2852, "The Hound of the Baskervilles (novel)"),
    (3289, "The Valley of Fear (novel)"),
    (1661, "The Adventures of Sherlock Holmes (12 stories)"),
    (834, "The Memoirs of Sherlock Holmes (stories)"),
    (108, "The Return of Sherlock Holmes (13 stories)"),
    (2350, "His Last Bow (stories)"),
    (69700, "The Case-Book of Sherlock Holmes (stories)"),
]

# ---------------------------------------------------------------------------
# 4. Human Knowledge Starter Pack — ~18 foundational pre-1928 PD works
#    (science, philosophy, political foundations, foundational literature)
# ---------------------------------------------------------------------------
STARTER_PACK = [
    (2009, "Darwin — On the Origin of Species"),
    (30155, "Einstein — Relativity: The Special and General Theory"),
    (1497, "Plato — The Republic"),
    (2680, "Marcus Aurelius — Meditations"),
    (132, "Sun Tzu — The Art of War"),
    (1404, "Hamilton/Madison/Jay — The Federalist Papers"),
    (1232, "Machiavelli — The Prince"),
    (3300, "Adam Smith — The Wealth of Nations"),
    (1080, "Jonathan Swift — A Modest Proposal"),
    (84, "Mary Shelley — Frankenstein"),
    (100, "Shakespeare — Complete Works"),
    (1342, "Jane Austen — Pride and Prejudice"),
    (1727, "Homer — The Odyssey"),
    (2701, "Herman Melville — Moby-Dick"),
    (1400, "Charles Dickens — Great Expectations"),
    (98, "Charles Dickens — A Tale of Two Cities"),
    (76, "Mark Twain — Adventures of Huckleberry Finn"),
    (11, "Lewis Carroll — Alice's Adventures in Wonderland"),
]

# ---------------------------------------------------------------------------
# 5. The Great Library — ~58 PD classics across world literature
# ---------------------------------------------------------------------------
GREAT_LIBRARY = [
    (100, "Shakespeare — Complete Works"),
    (1342, "Austen — Pride and Prejudice"),
    (158, "Austen — Emma"),
    (161, "Austen — Sense and Sensibility"),
    (84, "Shelley — Frankenstein"),
    (345, "Stoker — Dracula"),
    (43, "Stevenson — Dr Jekyll and Mr Hyde"),
    (174, "Wilde — The Picture of Dorian Gray"),
    (2701, "Melville — Moby-Dick"),
    (76, "Twain — Huckleberry Finn"),
    (74, "Twain — The Adventures of Tom Sawyer"),
    (1400, "Dickens — Great Expectations"),
    (98, "Dickens — A Tale of Two Cities"),
    (1023, "Dickens — Bleak House"),
    (730, "Dickens — Oliver Twist"),
    (766, "Dickens — David Copperfield"),
    (1260, "Bronte (C.) — Jane Eyre"),
    (768, "Bronte (E.) — Wuthering Heights"),
    (145, "Eliot — Middlemarch"),
    (110, "Thackeray — Vanity Fair"),
    (1727, "Homer — The Odyssey"),
    (6130, "Homer — The Iliad"),
    (1399, "Tolstoy — Anna Karenina"),
    (2600, "Tolstoy — War and Peace"),
    (2554, "Dostoevsky — Crime and Punishment"),
    (28054, "Dostoevsky — The Brothers Karamazov"),
    (600, "Dostoevsky — Notes from the Underground"),
    (1399, "Tolstoy — Anna Karenina"),
    (996, "Cervantes — Don Quixote"),
    (1184, "Dumas — The Count of Monte Cristo"),
    (1257, "Dumas — The Three Musketeers"),
    (2413, "Flaubert — Madame Bovary"),
    (135, "Hugo — Les Miserables"),
    (1259, "Stendhal — The Red and the Black"),
    (2814, "Joyce — Dubliners"),
    (4300, "Joyce — Ulysses"),
    (64317, "Fitzgerald — The Great Gatsby"),
    (140, "Sinclair — The Jungle"),
    (205, "Thoreau — Walden"),
    (2680, "Marcus Aurelius — Meditations"),
    (1497, "Plato — The Republic"),
    (1232, "Machiavelli — The Prince"),
    (132, "Sun Tzu — The Art of War"),
    (2009, "Darwin — On the Origin of Species"),
    (30155, "Einstein — Relativity"),
    (3300, "Smith — The Wealth of Nations"),
    (132, "Sun Tzu — The Art of War"),
    (1080, "Swift — A Modest Proposal"),
    (829, "Swift — Gulliver's Travels"),
    (16328, "Beowulf"),
    (1322, "Whitman — Leaves of Grass"),
    (408, "Du Bois — The Souls of Black Folk"),
    (2542, "Ibsen — A Doll's House"),
    (1322, "Whitman — Leaves of Grass"),
    (215, "London — The Call of the Wild"),
    (1934, "Coleridge — Rime of the Ancient Mariner / poems"),
    (120, "Stevenson — Treasure Island"),
    (35, "Wells — The Time Machine"),
    (36, "Wells — The War of the Worlds"),
    (164, "Verne — Twenty Thousand Leagues Under the Sea"),
    (103, "Verne — Around the World in Eighty Days"),
    (1661, "Doyle — The Adventures of Sherlock Holmes"),
    (1080, "Swift — A Modest Proposal"),
    (5200, "Kafka — Metamorphosis"),
    (1250, "Kafka — Metamorphosis (alt)"),
    (244, "Doyle — A Study in Scarlet"),
    (514, "Alcott — Little Women"),
    (113, "Burnett — The Secret Garden"),
    (11, "Carroll — Alice's Adventures in Wonderland"),
    (12, "Carroll — Through the Looking-Glass"),
    (1952, "Gilman — The Yellow Wallpaper"),
    (219, "Conrad — Heart of Darkness"),
    (2148, "Poe — Works (Vol)"),
]


# ---------------------------------------------------------------------------
# 6. The Great Library — Essentials: a "best of the best" trim of the 58-work
#    Great Library, sized to fit ONE C90 cassette side (~1.58 MB @ 4910 bps)
#    together with the bundled eSpeak-ng TTS reader engine (~522 KB xz'd).
#    Criteria: universally recognizable, canonical, demo-worthy titles —
#    short/novella-length works (not "complete works" compilations, which
#    blow the budget at this bitrate) spanning multiple genres/authors.
# ---------------------------------------------------------------------------
GREAT_LIBRARY_ESSENTIALS = [
    (11, "Carroll — Alice's Adventures in Wonderland"),
    (46, "Dickens — A Christmas Carol"),
    (43, "Stevenson — The Strange Case of Dr Jekyll and Mr Hyde"),
    (5200, "Kafka — The Metamorphosis"),
    (932, "Poe — The Fall of the House of Usher"),
    (1064, "Poe — The Masque of the Red Death"),
    (1952, "Gilman — The Yellow Wallpaper"),
    (244, "Doyle — A Study in Scarlet"),
    (35, "Wells — The Time Machine"),
]


def dedup(works):
    """Remove duplicate gutenberg ids, preserving order; report final count."""
    seen = set()
    out = []
    for gid, label in works:
        if gid in seen:
            continue
        seen.add(gid)
        out.append((gid, label))
    return out


COLLECTIONS = {
    "corpus_shakespeare": SHAKESPEARE,
    "corpus_kjv_bible": KJV_BIBLE,
    "corpus_sherlock_holmes": SHERLOCK,
    "corpus_human_knowledge_starter": dedup(STARTER_PACK),
    "corpus_great_library": dedup(GREAT_LIBRARY),
    "corpus_great_library_essentials": dedup(GREAT_LIBRARY_ESSENTIALS),
}


def main():
    summary = {}
    for name, works in COLLECTIONS.items():
        out_dir = os.path.join(BUILT, name)
        try:
            meta, ev = build_corpus(name, works, out_dir)
            missing = [e for e in ev if not e["pg_header"]]
            summary[name] = {
                "n_works": meta["n_works"],
                "on_tape_mb": meta["on_tape_mb"],
                "raw_mb": meta["raw_mb"],
                "roundtrip_ok": meta["roundtrip_ok"],
                "all_pd_header": meta["all_have_pg_header"],
                "missing_header": [m["gid"] for m in missing],
            }
            print(f"[OK] {name}: {meta['n_works']} works, "
                  f"raw={meta['raw_mb']}MB on_tape={meta['on_tape_mb']}MB "
                  f"rt={meta['roundtrip_ok']} pd={meta['all_have_pg_header']}")
        except Exception as e:  # noqa: BLE001
            summary[name] = {"error": str(e)}
            print(f"[FAIL] {name}: {e}")
    with open(os.path.join(BUILT, "_corpus_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
