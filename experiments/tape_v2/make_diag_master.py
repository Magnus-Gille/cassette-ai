#!/usr/bin/env python3
"""make_diag_master.py — Build the CASSETTE-AI DIAG-1 setup validation tape (RC v1).

Short (~2 min), stereo, self-contained. Record it to tape and play it back
through analyze_diag.py for a complete setup report card (PASS/WARN/FAIL on
all fault dimensions the team has discovered).

Outputs (all in experiments/tape_v2/):
  diag_master.wav          stereo float32 48 kHz  ~2 min  (gitignored)
  diag_manifest.json       tracked — probe windows + section offsets for the analyzer
  diag_sidecars/<cfg>_rep<r>.bin  payload sidecars for byte-exact decode check

TAPE LAYOUT (stereo — L=R except the routing probes):
  1.0 s  lead silence
  0.2 s  up-chirp (500→5000 Hz)           global sync anchor
  0.4 s  gap
  0.5 s  DC / short noise probe (silence) DC offset, initial noise floor
  0.4 s  gap
  1.5 s  L-only @ 1000 Hz / R silent      L/R routing + crosstalk L→R
  0.4 s  gap
  1.5 s  R silent / R-only @ 1700 Hz      L/R routing + crosstalk R→L
  0.4 s  gap
  5.0 s  silence  (mains-hum probe)       50/60 Hz hum level
  0.4 s  gap
 10.0 s  steady 3000 Hz tone              flutter/wow + clock
  0.4 s  gap
 10.0 s  Schroeder multitone comb (×2 rep × 5 s)  H(f), notch, HF rolloff
  0.4 s  gap
  2.0 s  IMD probe (1000 + 1500 + 2500 Hz trident)  THD/IMD reference
  0.4 s  gap
  DATA SECTIONS (both channels, interleaved):
    20 × mfsk32 @ 96 bytes     →  ~16 s   most-robust decode check
    15 × c1_gray_m16 @ 96 bytes →  ~11 s  mid decode check
    10 × c4_bpsk @ 96 bytes    →  ~16 s   aggressive OFDM (HF coverage)
    10 × c4_qpsk @ 96 bytes    →   ~4 s   aggressive narrow decode check
  0.4 s  gap
  0.2 s  down-chirp (5000→500 Hz)         global sync anchor
  1.0 s  tail silence

Total: ≈ 2 min 10 s

Run:  python3 experiments/tape_v2/make_diag_master.py
"""
from __future__ import annotations

import json
import pathlib
import struct
import sys
import zlib

import numpy as np
import soundfile as sf
from scipy.signal import chirp as _scipy_chirp

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
TAPE_V2 = ROOT / "experiments" / "tape_v2"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", TAPE_V2,
           ROOT / "experiments" / "capacity"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SR = 48_000
VERSION = "diag-rc1"
MASTER_ID = "diag_master_v1"

OUT_WAV = TAPE_V2 / "diag_master.wav"
OUT_MANIFEST = TAPE_V2 / "diag_manifest.json"
SIDECAR_DIR = TAPE_V2 / "diag_sidecars"

# ─── Layout constants ───────────────────────────────────────────────────────
LEAD = 1.0
TAIL = 1.0
GAP = 0.40
CHIRP_T = 0.20
CHIRP_F0, CHIRP_F1 = 500.0, 5000.0
CHIRP_AMP = 0.70

DC_PROBE_DUR = 0.5      # s silence for DC / initial noise
PROBE_L_HZ = 1000.0     # L-only routing probe
PROBE_R_HZ = 1700.0     # R-only routing probe (non-harmonic → swap-detectable)
PROBE_DUR = 1.5
PROBE_AMP = 0.5
HUM_PROBE_DUR = 5.0     # silence for mains-hum measurement
FLUTTER_TONE_HZ = 3000.0
FLUTTER_DUR = 10.0
FLUTTER_AMP = 0.5
COMB_DUR = 5.0          # one Schroeder-comb sweep
COMB_REPS = 2           # two sweeps for averaging → 10 s
COMB_AMP = 0.60
IMD_DUR = 2.0
IMD_TONES_HZ = (1000.0, 1500.0, 2500.0)
IMD_AMP = 0.5

# Data section reps (one section = 96-byte payload):
N_MFSK32 = 20
N_GRAY = 15
N_BPSK = 10
N_QPSK = 10

# Tone comb: MFSK32 carrier grid (400-10 kHz, 32 tones, proven modem coverage)
try:
    from hyp_h2_mfsk import MFSKScheme as _MF
    COMB_FREQS = [float(f) for f in _MF(M=32, walsh_k=0).freqs]
except Exception:
    COMB_FREQS = [float(f) for f in np.linspace(400, 10000, 32)]


# ════════════════════════════════════════════════════════════════════════════
# Synthesis helpers
# ════════════════════════════════════════════════════════════════════════════

def _silence(dur: float) -> np.ndarray:
    return np.zeros(int(round(dur * SR)), dtype=np.float32)


def _tone(freq: float, dur: float, amp: float, fade: float = 0.02) -> np.ndarray:
    n = int(round(dur * SR))
    t = np.arange(n, dtype=np.float64) / SR
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    f = int(round(fade * SR))
    if 0 < f < n // 2:
        env = np.ones(n, dtype=np.float32)
        env[:f] = np.linspace(0.0, 1.0, f, dtype=np.float32)
        env[-f:] = np.linspace(1.0, 0.0, f, dtype=np.float32)
        x *= env
    return x


def _global_chirp(up: bool = True) -> np.ndarray:
    n = int(round(CHIRP_T * SR))
    t = np.arange(n, dtype=np.float64) / SR
    f0, f1 = (CHIRP_F0, CHIRP_F1) if up else (CHIRP_F1, CHIRP_F0)
    sig = _scipy_chirp(t, f0=f0, f1=f1, t1=CHIRP_T, method="linear")
    fade = int(0.01 * SR)
    sig[:fade] *= np.linspace(0, 1, fade)
    sig[-fade:] *= np.linspace(1, 0, fade)
    return (CHIRP_AMP * sig).astype(np.float32)


def _schroeder_multitone(freqs: list, dur: float, amp: float) -> np.ndarray:
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    fade = int(0.02 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return (amp * x).astype(np.float32)


def _imd_probe(freqs: tuple, dur: float, amp: float) -> np.ndarray:
    """Multi-tone IMD reference probe: equal-amplitude sinusoids + Schroeder phases."""
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    fade = int(0.02 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return (amp * x).astype(np.float32)


# ════════════════════════════════════════════════════════════════════════════
# Data sections (using make_master2 modem API)
# ════════════════════════════════════════════════════════════════════════════

def _make_payload(cfg: str, rep: int) -> bytes:
    prefix = f"CASSETTE-AI DIAG v1 {cfg} rep{rep:03d} "
    filler = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 4
    raw = (prefix + filler)[:96]
    raw = raw.ljust(96)[:96]
    return raw.encode("ascii")


def _build_data_sections() -> tuple[list[np.ndarray], list[dict]]:
    """Build all data sections; return (audio_chunks, section_manifest_entries)."""
    import modems_index, modems_ofdm  # noqa: E402
    MODEM_MAP = {
        "mfsk32": (modems_index, N_MFSK32),
        "c1_gray_m16": (modems_index, N_GRAY),
        "c4_bpsk": (modems_ofdm, N_BPSK),
        "c4_qpsk": (modems_ofdm, N_QPSK),
    }
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    chunks: list[np.ndarray] = []
    entries: list[dict] = []
    pos_in_data = 0  # relative to data block start (absolute added by caller)

    for cfg, (mod, n_reps) in MODEM_MAP.items():
        for rep in range(n_reps):
            payload = _make_payload(cfg, rep)
            audio = mod.modulate(payload, cfg)
            # Save sidecar
            scar_name = f"{cfg}_rep{rep:03d}.bin"
            scar_path = SIDECAR_DIR / scar_name
            scar_path.write_bytes(payload)
            entries.append({
                "config": cfg,
                "rep": rep,
                "start_in_data": pos_in_data,   # relative; caller adds base offset
                "length": len(audio),
                "payload_sidecar": f"diag_sidecars/{scar_name}",
                "start_sample": None,            # filled in by build()
            })
            chunks.append(audio.astype(np.float32))
            # gap between sections
            gap = _silence(GAP)
            chunks.append(gap)
            pos_in_data += len(audio) + len(gap)

    return chunks, entries


# ════════════════════════════════════════════════════════════════════════════
# Manifest template (for tests + documentation)
# ════════════════════════════════════════════════════════════════════════════

def build_manifest_template() -> dict:
    """Return a manifest dict with all required keys (values are None placeholders)."""
    return {
        "version": VERSION,
        "master_id": MASTER_ID,
        "SR": SR,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "probe_L": {
            "freq_hz": PROBE_L_HZ, "channel": "L",
            "start_frame": None, "end_frame": None,
        },
        "probe_R": {
            "freq_hz": PROBE_R_HZ, "channel": "R",
            "start_frame": None, "end_frame": None,
        },
        "dc_probe": {"start_frame": None, "end_frame": None},
        "hum_probe": {"start_frame": None, "end_frame": None},
        "flutter_probe": {
            "freq_hz": FLUTTER_TONE_HZ,
            "start_frame": None, "end_frame": None,
        },
        "tone_comb": {
            "freqs_hz": COMB_FREQS,
            "reps": COMB_REPS,
            "dur_per_rep_s": COMB_DUR,
            "sections": [],   # list of {start_frame, end_frame}
        },
        "imd_probe": {
            "freqs_hz": list(IMD_TONES_HZ),
            "start_frame": None, "end_frame": None,
        },
        "sections": [],   # data sections
    }


# ════════════════════════════════════════════════════════════════════════════
# Main builder
# ════════════════════════════════════════════════════════════════════════════

def build(out_wav: pathlib.Path = OUT_WAV) -> dict:
    """Assemble diag_master.wav, manifest, and sidecars.  Returns manifest dict."""
    manifest = build_manifest_template()

    L_parts: list[np.ndarray] = []
    R_parts: list[np.ndarray] = []
    pos = 0

    def add(sigL: np.ndarray, sigR: np.ndarray) -> None:
        nonlocal pos
        sigL = np.asarray(sigL, dtype=np.float32)
        sigR = np.asarray(sigR, dtype=np.float32)
        assert len(sigL) == len(sigR), f"length mismatch: {len(sigL)} vs {len(sigR)}"
        L_parts.append(sigL)
        R_parts.append(sigR)
        pos += len(sigL)

    def add_both(sig: np.ndarray) -> None:
        add(sig, sig)

    def add_gap() -> None:
        add_both(_silence(GAP))

    # ── Lead silence ──────────────────────────────────────────────────────
    add_both(_silence(LEAD))

    # ── Up-chirp ──────────────────────────────────────────────────────────
    manifest["tx_chirp0"] = pos
    add_both(_global_chirp(up=True))
    add_gap()

    # ── DC / short noise probe ────────────────────────────────────────────
    dc_start = pos
    add_both(_silence(DC_PROBE_DUR))
    manifest["dc_probe"]["start_frame"] = dc_start
    manifest["dc_probe"]["end_frame"] = pos
    add_gap()

    # ── L-only routing probe (1000 Hz on L, silence on R) ─────────────────
    l_start = pos
    tone_L = _tone(PROBE_L_HZ, PROBE_DUR, PROBE_AMP)
    sil_probe = _silence(PROBE_DUR)
    add(tone_L, sil_probe)
    manifest["probe_L"]["start_frame"] = l_start
    manifest["probe_L"]["end_frame"] = pos
    add_gap()

    # ── R-only routing probe (silence on L, 1700 Hz on R) ─────────────────
    r_start = pos
    tone_R = _tone(PROBE_R_HZ, PROBE_DUR, PROBE_AMP)
    add(sil_probe, tone_R)
    manifest["probe_R"]["start_frame"] = r_start
    manifest["probe_R"]["end_frame"] = pos
    add_gap()

    # ── Mains-hum probe (silence) ──────────────────────────────────────────
    hum_start = pos
    add_both(_silence(HUM_PROBE_DUR))
    manifest["hum_probe"]["start_frame"] = hum_start
    manifest["hum_probe"]["end_frame"] = pos
    add_gap()

    # ── Flutter / clock tone (3000 Hz) ────────────────────────────────────
    fl_start = pos
    add_both(_tone(FLUTTER_TONE_HZ, FLUTTER_DUR, FLUTTER_AMP))
    manifest["flutter_probe"]["start_frame"] = fl_start
    manifest["flutter_probe"]["end_frame"] = pos
    add_gap()

    # ── Tone comb (Schroeder multitone, 2 × 5 s) ──────────────────────────
    comb_sections = []
    for rep in range(COMB_REPS):
        cs = pos
        add_both(_schroeder_multitone(COMB_FREQS, COMB_DUR, COMB_AMP))
        comb_sections.append({"start_frame": cs, "end_frame": pos})
        add_gap()
    manifest["tone_comb"]["sections"] = comb_sections

    # ── IMD probe (1000 + 1500 + 2500 Hz) ────────────────────────────────
    imd_start = pos
    add_both(_imd_probe(IMD_TONES_HZ, IMD_DUR, IMD_AMP))
    manifest["imd_probe"]["start_frame"] = imd_start
    manifest["imd_probe"]["end_frame"] = pos
    add_gap()

    # ── Data sections (both channels, same content) ───────────────────────
    data_base = pos
    data_chunks, entries = _build_data_sections()
    for e in entries:
        e["start_sample"] = data_base + e.pop("start_in_data")
    for chunk in data_chunks:
        add_both(chunk)
    manifest["sections"] = entries
    add_gap()

    # ── Down-chirp ────────────────────────────────────────────────────────
    manifest["tx_chirp1"] = pos
    add_both(_global_chirp(up=False))
    add_gap()

    # ── Tail silence ──────────────────────────────────────────────────────
    add_both(_silence(TAIL))

    # ── Assemble + peak-normalise ─────────────────────────────────────────
    L = np.concatenate(L_parts, dtype=np.float32)
    R = np.concatenate(R_parts, dtype=np.float32)
    stereo = np.column_stack([L, R])
    peak = float(np.max(np.abs(stereo)))
    if peak > 1e-9:
        stereo = (stereo / peak * 0.70).astype(np.float32)

    dur_s = len(L) / SR
    print(f"[build] diag_master: {dur_s:.1f} s  ({dur_s/60:.2f} min)  peak→0.70")

    # ── Write WAV + manifest ──────────────────────────────────────────────
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), stereo, SR, subtype="FLOAT")
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"[build] wrote {out_wav.name}  ({stereo.nbytes/1e6:.0f} MB)")
    print(f"[build] wrote {OUT_MANIFEST.name}")
    _print_layout(manifest, dur_s)

    return manifest


def _print_layout(m: dict, dur_s: float) -> None:
    sr = m["SR"]
    print(f"\n  Tape layout ({dur_s:.1f} s):")
    def _t(k):
        v = m.get(k)
        return f"{v/sr:.2f}s" if v is not None else "?"
    print(f"  chirp0       @ {_t('tx_chirp0')}")
    print(f"  dc_probe     @ {m['dc_probe']['start_frame']/sr:.2f}-"
          f"{m['dc_probe']['end_frame']/sr:.2f}s")
    print(f"  probe_L      @ {m['probe_L']['start_frame']/sr:.2f}-"
          f"{m['probe_L']['end_frame']/sr:.2f}s  ({m['probe_L']['freq_hz']:.0f} Hz L-only)")
    print(f"  probe_R      @ {m['probe_R']['start_frame']/sr:.2f}-"
          f"{m['probe_R']['end_frame']/sr:.2f}s  ({m['probe_R']['freq_hz']:.0f} Hz R-only)")
    print(f"  hum_probe    @ {m['hum_probe']['start_frame']/sr:.2f}-"
          f"{m['hum_probe']['end_frame']/sr:.2f}s  (silence)")
    print(f"  flutter_tone @ {m['flutter_probe']['start_frame']/sr:.2f}-"
          f"{m['flutter_probe']['end_frame']/sr:.2f}s  ({m['flutter_probe']['freq_hz']:.0f} Hz)")
    for i, cs in enumerate(m['tone_comb']['sections']):
        print(f"  tone_comb[{i}] @ {cs['start_frame']/sr:.2f}-{cs['end_frame']/sr:.2f}s")
    print(f"  imd_probe    @ {m['imd_probe']['start_frame']/sr:.2f}-"
          f"{m['imd_probe']['end_frame']/sr:.2f}s")
    if m['sections']:
        first = m['sections'][0]
        last = m['sections'][-1]
        print(f"  data secs    @ {first['start_sample']/sr:.2f}-"
              f"{(last['start_sample']+last['length'])/sr:.2f}s "
              f"({len(m['sections'])} sections)")
    print(f"  chirp1       @ {_t('tx_chirp1')}")


# ════════════════════════════════════════════════════════════════════════════
# Self-test (verify byte-exact decode of all data sections from the WAV)
# ════════════════════════════════════════════════════════════════════════════

def self_test(wav_path: pathlib.Path = OUT_WAV,
              manifest: dict | None = None) -> bool:
    """Decode every data section from the WAV and compare to sidecars."""
    import modems_index, modems_ofdm
    MODEM_MAP = {
        "mfsk32": modems_index,
        "c1_gray_m16": modems_index,
        "c4_bpsk": modems_ofdm,
        "c4_qpsk": modems_ofdm,
    }
    if manifest is None:
        manifest = json.loads(OUT_MANIFEST.read_text())

    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio[:, 0]   # use L channel (same content as R)

    n_pass = n_fail = 0
    for sec in manifest.get("sections", []):
        cfg = sec["config"]
        mod = MODEM_MAP.get(cfg)
        if mod is None:
            continue
        scar = (TAPE_V2 / sec["payload_sidecar"]).read_bytes()
        start = sec["start_sample"]
        length = sec["length"]
        window = audio[max(0, start - 1000): start + length + 1000].astype(np.float32)
        try:
            rx = mod.demodulate(window, cfg)
            ok = (rx == scar)
        except Exception:
            ok = False
        if ok:
            n_pass += 1
        else:
            n_fail += 1
            print(f"  [FAIL] {cfg} rep{sec['rep']:03d}")

    print(f"[self_test] {n_pass}/{n_pass+n_fail} sections decode byte-exact")
    return n_fail == 0


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Build the CASSETTE-AI DIAG-1 setup validation tape.")
    ap.add_argument("--out", default=str(OUT_WAV),
                    help="output WAV path (default: diag_master.wav)")
    ap.add_argument("--no-selftest", action="store_true",
                    help="skip byte-exact self-test after build")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    manifest = build(out)

    if not args.no_selftest:
        print("\n[self_test] verifying byte-exact decode...")
        ok = self_test(out, manifest)
        if not ok:
            raise SystemExit("[self_test] FAILED — some sections did not decode byte-exact")
        print("[self_test] PASSED — all sections decode byte-exact from WAV")

    dur = manifest["tx_chirp1"] / manifest["SR"] + 1.0
    print(f"\nDone.  Record {out.name} to tape (duration ~{dur:.0f} s = "
          f"{dur/60:.1f} min), then:\n"
          f"  python3 experiments/tape_v2/analyze_diag.py <capture.wav> "
          f"--manifest {OUT_MANIFEST.name}")


if __name__ == "__main__":
    main()
