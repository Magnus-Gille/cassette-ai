from __future__ import annotations

import json
import math
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy import signal

from channel import FS, cassette_channel
from common import DATA, PLOTS, ROOT, ensure_dirs, write_csv


SOURCES = [
    "noise-arch",
    "noise-arch-archive-201110",
]
CACHE = ROOT / "RESULTS" / "real_audio_cache"


def _json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def discover_items() -> list[dict]:
    items = []
    for coll in SOURCES:
        q = urllib.parse.quote(f"collection:{coll}")
        url = f"https://archive.org/advancedsearch.php?q={q}&fl[]=identifier&fl[]=title&rows=10&page=1&output=json"
        try:
            docs = _json(url)["response"]["docs"]
        except Exception:
            docs = []
        for d in docs:
            if d.get("identifier"):
                items.append({"identifier": d["identifier"], "title": d.get("title", d["identifier"]), "collection": coll})
    if len(items) < 3:
        items.extend(
            [
                {"identifier": "noise-arch", "title": "Noise-Arch collection landing item", "collection": "noise-arch"},
                {"identifier": "noise-arch-archive-201110", "title": "Noise-Arch October 2011 backup", "collection": "noise-arch"},
                {"identifier": "best-of-noise-arch", "title": "Best of Noise-Arch", "collection": "noise-arch"},
            ]
        )
    uniq = []
    seen = set()
    for item in items:
        if item["identifier"] not in seen:
            seen.add(item["identifier"])
            uniq.append(item)
    return uniq[:8]


def audio_url(identifier: str) -> tuple[str, str] | None:
    try:
        meta = _json(f"https://archive.org/metadata/{identifier}")
    except Exception:
        return None
    files = meta.get("files", [])
    preferred = [f for f in files if f.get("format", "").lower() in {"vbr mp3", "mp3", "ogg vorbis", "flac", "wave"}]
    preferred += [f for f in files if Path(f.get("name", "")).suffix.lower() in {".mp3", ".ogg", ".flac", ".wav"}]
    for f in preferred:
        name = f.get("name", "")
        if name:
            return f"https://archive.org/download/{identifier}/{urllib.parse.quote(name)}", name
    return None


def download_excerpt(identifier: str, url: str) -> Path | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.unquote(url)).suffix or ".mp3"
    out = CACHE / f"{identifier}{suffix}"
    wav = CACHE / f"{identifier}.wav"
    if not wav.exists():
        try:
            if not out.exists():
                urllib.request.urlretrieve(url, out)
            subprocess.run(
                ["ffmpeg", "-y", "-t", "45", "-i", str(out), "-ac", "1", "-ar", str(FS), str(wav)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except Exception:
            return None
    return wav if wav.exists() else None


def metrics(y: np.ndarray, fs: int = FS) -> dict:
    y = y.astype(np.float64)
    y = y - np.mean(y)
    if np.max(np.abs(y)) > 0:
        y = y / np.max(np.abs(y))
    f, pxx = signal.welch(y, fs=fs, nperseg=min(8192, len(y)))
    band = lambda lo, hi: float(np.mean(pxx[(f >= lo) & (f <= hi)])) if np.any((f >= lo) & (f <= hi)) else 0.0
    low = band(200, 3000)
    high = band(9000, 12000)
    noise = band(15000, 22000)
    snr = 10 * math.log10(max(low, 1e-20) / max(noise, 1e-20))
    response_12k = 10 * math.log10(max(high, 1e-20) / max(low, 1e-20))
    frame = max(1, int(0.01 * fs))
    rms = np.sqrt(np.convolve(y**2, np.ones(frame) / frame, mode="valid"))
    med = float(np.median(rms))
    drop = rms < med * 0.18
    changes = np.diff(np.r_[False, drop, False].astype(int))
    starts = np.where(changes == 1)[0]
    ends = np.where(changes == -1)[0]
    lengths = (ends - starts) / fs * 1000
    lengths = lengths[lengths >= 10]
    duration = len(y) / fs
    zc = np.where(np.diff(np.signbit(signal.sosfilt(signal.butter(4, [300, 3000], "bandpass", fs=fs, output="sos"), y))))[0]
    if len(zc) > 10:
        intervals = np.diff(zc) / fs
        wf = float(np.std(intervals) / max(np.mean(intervals), 1e-12) * 100)
    else:
        wf = 0.0
    return {
        "measured_snr_db": round(snr, 2),
        "freq_response_12k_vs_mid_db": round(response_12k, 2),
        "dropout_rate_per_s": round(float(len(lengths) / duration), 4),
        "median_dropout_length_ms": round(float(np.median(lengths)) if len(lengths) else 0.0, 2),
        "timebase_variation_proxy_pct": round(wf, 4),
    }


def sim_metrics() -> dict:
    t = np.arange(FS * 45) / FS
    x = 0.35 * np.sin(2 * np.pi * 1000 * t) + 0.15 * np.sin(2 * np.pi * 8000 * t)
    y = cassette_channel(x, burst_rate_per_s=0.1, burst_length_ms=100, seed_offset=777)
    return metrics(y)


def run() -> None:
    ensure_dirs()
    rows = []
    sim = sim_metrics()
    for item in discover_items():
        au = audio_url(item["identifier"])
        if not au:
            continue
        wav = download_excerpt(item["identifier"], au[0])
        if not wav:
            continue
        y, fs = sf.read(wav, always_2d=False)
        if y.ndim > 1:
            y = y[:, 0]
        m = metrics(y, fs)
        rows.append(
            {
                "source": "archive.org",
                "identifier": item["identifier"],
                "title": item["title"][:80],
                "url": f"https://archive.org/details/{item['identifier']}",
                **{f"real_{k}": v for k, v in m.items()},
                **{f"sim_{k}": v for k, v in sim.items()},
                "burstier_than_v2": m["dropout_rate_per_s"] > sim["dropout_rate_per_s"] * 5,
            }
        )
        if len(rows) >= 3:
            break
    if len(rows) < 3:
        raise RuntimeError("could not obtain three archive.org cassette audio excerpts")
    write_csv(DATA / "channel_model_vs_real.csv", rows)

    labels = [r["identifier"][:14] for r in rows] + ["v2 sim"]
    snr = [float(r["real_measured_snr_db"]) for r in rows] + [sim["measured_snr_db"]]
    drop = [float(r["real_dropout_rate_per_s"]) for r in rows] + [sim["dropout_rate_per_s"]]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].bar(labels, snr)
    axes[0].set_title("SNR proxy")
    axes[0].set_ylabel("dB")
    axes[0].tick_params(axis="x", rotation=25)
    axes[1].bar(labels, drop)
    axes[1].set_title("Dropout rate")
    axes[1].set_ylabel("events/s")
    axes[1].tick_params(axis="x", rotation=25)
    fig.tight_layout()
    fig.savefig(PLOTS / "sim_vs_real_metrics.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()

