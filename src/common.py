from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "RESULTS" / "data"
PLOTS = ROOT / "RESULTS" / "plots"
REPORT = ROOT / "REPORT.md"
STATUS = ROOT / "STATUS.md"
SEED = 20260506


def ensure_dirs() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    PLOTS.mkdir(parents=True, exist_ok=True)


def rng(offset: int = 0) -> np.random.Generator:
    return np.random.default_rng(SEED + offset)


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        raise ValueError(f"no rows for {path}")
    ensure_dirs()
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def append_report(title: str, paragraph: str) -> None:
    ensure_dirs()
    existing = REPORT.read_text() if REPORT.exists() else "# Cassette AI Viability Report\n\n"
    marker = f"## {title}\n"
    section = f"{marker}\n{paragraph.strip()}\n\n"
    if marker in existing:
        before, rest = existing.split(marker, 1)
        next_idx = rest.find("\n## ")
        if next_idx == -1:
            existing = before + section
        else:
            existing = before + section + rest[next_idx + 1 :]
    else:
        existing = existing.rstrip() + "\n\n" + section
    REPORT.write_text(existing)


def save_json(path: Path, payload: dict) -> None:
    ensure_dirs()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))

