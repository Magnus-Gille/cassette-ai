#!/usr/bin/env python3
"""B-side remix: sound-palette extractor for master10 / tape10_run1.

Reads master10_manifest.json, probes both the clean master WAV and the real
cassette capture, and emits:

  * palette.json   -- every musically usable fact about the signal:
                      chirp params, section timeline (master + capture time),
                      carrier grids, measured frame-preamble period, deck
                      speed, and a 'musical_mapping' block (ET notes, scale
                      quantizations, BPM candidates).
  * ref_snippets.wav -- ~20 s stereo 48k/16-bit reference reel cut from the
                      REAL capture: d2x section, N512 section, start chirp,
                      Schroeder sounder, preamble rhythm; click-separated.

No data encoding. python3 + numpy/scipy/soundfile only. Deterministic.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import soundfile as sf
from scipy.signal import chirp as scipy_chirp
from scipy.signal import fftconvolve, find_peaks

SEED = 20260612  # fixed + logged (ladder seed of master10)
rng = np.random.default_rng(SEED)

HERE = pathlib.Path(__file__).resolve().parent
TAPE_V2 = HERE.parent
MANIFEST = TAPE_V2 / "master10_manifest.json"
MASTER_WAV = TAPE_V2 / "master10.wav"
CAPTURE_WAV = TAPE_V2 / "captures" / "tape10_run1.wav"
OUT_JSON = HERE / "palette.json"
OUT_SNIP = HERE / "ref_snippets.wav"

SR = 48000

# Frame preamble parameters (src/hyp_common.py: PREAMBLE_F0/F1/SECONDS/AMP --
# the SAME chirp every m3_codec frame starts with).
PRE_F0, PRE_F1, PRE_T, PRE_AMP = 800.0, 3200.0, 0.25, 0.65

A4 = 440.0
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def note_of(freq_hz: float) -> dict:
    """Nearest equal-tempered note (A4=440) + cents offset."""
    n = int(round(12.0 * np.log2(freq_hz / A4)))
    midi = 69 + n
    et = A4 * 2.0 ** (n / 12.0)
    cents = 1200.0 * np.log2(freq_hz / et)
    return {
        "freq_hz": float(freq_hz),
        "note": f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}",
        "midi": int(midi),
        "cents": round(float(cents), 1),
        "et_freq_hz": round(float(et), 2),
    }


def make_chirp(f0: float, f1: float, T: float, ratio: float = 1.0) -> np.ndarray:
    """Linear chirp template; ratio>1 = tape plays slow (longer, lower)."""
    n = int(round(T * ratio * SR))
    t = np.arange(n) / SR
    return scipy_chirp(t, f0=f0 / ratio, f1=f1 / ratio, t1=T * ratio,
                       method="linear").astype(np.float32)


def matched_filter(x: np.ndarray, template: np.ndarray) -> np.ndarray:
    """|cross-correlation|; index i = template start at sample i of x."""
    c = fftconvolve(x, template[::-1].astype(np.float64), mode="valid")
    return np.abs(c)


def seg(x: np.ndarray, start_s: float, dur_s: float) -> np.ndarray:
    a = max(0, int(start_s * SR))
    b = min(len(x), a + int(dur_s * SR))
    return x[a:b].copy()


def edge_fade(x: np.ndarray, ms: float = 6.0) -> np.ndarray:
    n = min(len(x) // 2, int(ms * 1e-3 * SR))
    if n > 0:
        r = np.linspace(0.0, 1.0, n)
        x[:n] *= r
        x[-n:] *= r[::-1]
    return x


def click(freq: float = 2093.0, dur: float = 0.014, amp: float = 0.6) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t) * np.exp(-t * 300.0)).astype(np.float64)


# --------------------------------------------------------------------------
# 1. manifest facts
# --------------------------------------------------------------------------
man = json.loads(MANIFEST.read_text())
assert man["SR"] == SR
gc = man["global_chirp"]                       # {"T":0.2,"f0":500,"f1":5000}
tx_c0, tx_c1 = man["tx_chirp0"], man["tx_chirp1"]
frame_gap_s = man["frame_gap_samples"] / SR    # 0.12 s

print(f"[manifest] global chirp {gc['f0']}->{gc['f1']} Hz, T={gc['T']} s; "
      f"up @ {tx_c0/SR:.3f} s, down @ {tx_c1/SR:.3f} s (master time)")

def family_of(scheme: str) -> str:
    if "N512" in scheme:
        return "N512_sp4"
    if scheme.startswith("D2X"):
        return "d2x_N256_sp2"
    return "N256_sp4"

sections = []
sections.append({"name": "lead_silence", "type": "silence",
                 "master_start_s": 0.0, "master_end_s": tx_c0 / SR})
sections.append({"name": "global_chirp_up", "type": "global_chirp",
                 "master_start_s": tx_c0 / SR,
                 "master_end_s": tx_c0 / SR + gc["T"]})
for s in man["sounder_sections"]:
    sections.append({"name": f"sounder_{s['kind']}_{s['info'].get('rep', 0)}"
                             if s["kind"] == "multitone" else f"sounder_{s['kind']}",
                     "type": f"sounder_{s['kind']}",
                     "master_start_s": s["start"] / SR,
                     "master_end_s": (s["start"] + s["length"]) / SR})

frame_periods = {}
for p in man["ws_payloads"]:
    fs = p["frame_starts"]
    d = int(np.median(np.diff(fs))) if len(fs) > 1 else 0
    fam = family_of(p["scheme"])
    frame_periods.setdefault(fam, d)
    sections.append({"name": p["name"], "type": f"dqpsk_{fam}",
                     "scheme": p["scheme"], "status": p["status"],
                     "n_frames": len(fs), "n_carriers": len(p["carrier_freqs_hz"]),
                     "frame_period_samples": d,
                     "master_start_s": fs[0] / SR,
                     "master_end_s": (fs[-1] + d) / SR})
sections.append({"name": "global_chirp_down", "type": "global_chirp",
                 "master_start_s": tx_c1 / SR,
                 "master_end_s": tx_c1 / SR + gc["T"]})

# Representative carrier grids
p_n512 = next(p for p in man["ws_payloads"]
              if family_of(p["scheme"]) == "N512_sp4" and p["status"] == "ACTIVE")
p_d2x = next(p for p in man["ws_payloads"]
             if family_of(p["scheme"]) == "d2x_N256_sp2")
print(f"[grids] N512 section: {p_n512['name']} ({len(p_n512['carrier_freqs_hz'])} carriers); "
      f"d2x section: {p_d2x['name']} ({len(p_d2x['carrier_freqs_hz'])} carriers)")

# --------------------------------------------------------------------------
# 2. locate the master in the capture (global chirps -> deck speed)
# --------------------------------------------------------------------------
cap, sr_cap = sf.read(CAPTURE_WAV, dtype="float64")
assert sr_cap == SR
print(f"[capture] {CAPTURE_WAV.name}: {len(cap)/SR:.2f} s")

up_t = make_chirp(gc["f0"], gc["f1"], gc["T"])
dn_t = make_chirp(gc["f1"], gc["f0"], gc["T"])

half = len(cap) // 2
mf_up = matched_filter(cap[:half], up_t)
cap_c0 = int(np.argmax(mf_up))
mf_dn = matched_filter(cap[half:], dn_t)
cap_c1 = half + int(np.argmax(mf_dn))

ratio = (cap_c1 - cap_c0) / (tx_c1 - tx_c0)   # >1 => deck plays slow
print(f"[sync] up-chirp @ {cap_c0/SR:.3f} s, down-chirp @ {cap_c1/SR:.3f} s "
      f"(capture time); deck speed ratio = {ratio:.6f} "
      f"({(1/ratio - 1)*100:+.3f}% pitch)")

def m2c(master_s: float) -> float:
    """Master seconds -> capture seconds."""
    return cap_c0 / SR + (master_s - tx_c0 / SR) * ratio

for s in sections:
    s["capture_start_s"] = round(m2c(s["master_start_s"]), 4)
    s["capture_end_s"] = round(m2c(s["master_end_s"]), 4)
    s["master_start_s"] = round(s["master_start_s"], 4)
    s["master_end_s"] = round(s["master_end_s"], 4)

# --------------------------------------------------------------------------
# 3. measure the frame-preamble period from the REAL capture
# --------------------------------------------------------------------------
pre_t = make_chirp(PRE_F0, PRE_F1, PRE_T, ratio=ratio)

def measure_period(payload: dict, label: str) -> dict:
    fs = payload["frame_starts"]
    nominal = int(np.median(np.diff(fs)))
    a = m2c(fs[0] / SR) - 0.4
    b = m2c((fs[-1] + 0.5 * nominal) / SR)   # stop before next section's tick
    region = seg(cap, a, b - a)
    mf = matched_filter(region, pre_t)
    dist = int(0.8 * nominal * ratio)
    pk, _ = find_peaks(mf, height=0.3 * mf.max(), distance=dist)
    period_cap = float(np.median(np.diff(pk))) / SR if len(pk) > 2 else None
    out = {
        "section": payload["name"],
        "n_preambles_found": int(len(pk)),
        "n_frames_expected": len(fs),
        "nominal_period_s": round(nominal / SR, 6),
        "measured_capture_period_s": round(period_cap, 6) if period_cap else None,
        "first_preamble_capture_s": round((a * SR + pk[0]) / SR, 4) if len(pk) else None,
    }
    print(f"[preamble:{label}] found {len(pk)}/{len(fs)} ticks; nominal "
          f"{out['nominal_period_s']} s, measured {out['measured_capture_period_s']} s")
    return out

period_n512 = measure_period(p_n512, "N512")
period_d2x = measure_period(p_d2x, "d2x")

# --------------------------------------------------------------------------
# 4. verify carrier grid in the capture (sanity: peaks where expected)
# --------------------------------------------------------------------------
def verify_carriers(payload: dict) -> dict:
    fs = payload["frame_starts"]
    mid = m2c((fs[len(fs) // 2] / SR) + PRE_T + frame_gap_s + 0.1)
    x = seg(cap, mid, 4.0)
    w = np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x * w))
    fax = np.fft.rfftfreq(len(x), 1 / SR)
    pw = spec ** 2
    hits, ratios = 0, []
    for f in payload["carrier_freqs_hz"]:
        f_play = f / ratio
        band = (fax > f_play - 100) & (fax < f_play + 100)   # DQPSK-broadened line
        gap = (fax > f_play + 150) & (fax < f_play + 225)    # inter-carrier gap
        if not band.any() or not gap.any():
            continue
        if pw[band].mean() > 2.0 * pw[gap].mean():
            hits += 1
            centroid = float((fax[band] * pw[band]).sum() / pw[band].sum())
            ratios.append(centroid / f)
    return {"section": payload["name"],
            "carriers_detected": f"{hits}/{len(payload['carrier_freqs_hz'])}",
            "median_freq_scale_vs_master": round(float(np.median(ratios)), 6) if ratios else None}

ver_n512 = verify_carriers(p_n512)
ver_d2x = verify_carriers(p_d2x)
print(f"[verify] N512 carriers in capture: {ver_n512['carriers_detected']} "
      f"(freq scale {ver_n512['median_freq_scale_vs_master']}); "
      f"d2x: {ver_d2x['carriers_detected']} ({ver_d2x['median_freq_scale_vs_master']})")

# --------------------------------------------------------------------------
# 5. musical mapping
# --------------------------------------------------------------------------
GRID = 375.0  # Hz spacing of both grids (48000/512*4 = 48000/256*2)

def lowest12(payload: dict) -> list[dict]:
    out = []
    for f in sorted(payload["carrier_freqs_hz"])[:12]:
        d = note_of(f)
        d["harmonic_of_375"] = int(round(f / GRID))
        out.append(d)
    return out

low_n512 = lowest12(p_n512)
low_d2x = lowest12(p_d2x)

SCALES = {
    # pitch-class sets (C=0). Grid fundamental 375 Hz ~ F#4 +23c -> F# scales.
    "Fsharp_major_pentatonic": {"pcs": [6, 8, 10, 1, 3], "names": "F# G# A# C# D#"},
    "Fsharp_natural_minor":    {"pcs": [6, 8, 9, 11, 1, 2, 4], "names": "F# G# A B C# D E"},
    "Fsharp_mixolydian":       {"pcs": [6, 8, 10, 11, 1, 3, 4], "names": "F# G# A# B C# D# E"},
}

def quantize(carriers: list[dict], pcs: list[int]) -> list[dict]:
    """For each carrier: keep if its nearest ET note is in scale, else give the
    nearest in-scale ET retune target (or 'drop' if >250 cents away)."""
    out = []
    for c in carriers:
        pc = c["midi"] % 12
        if pc in pcs:
            out.append({"freq_hz": c["freq_hz"], "action": "keep",
                        "note": c["note"], "cents_off_et": c["cents"]})
        else:
            cands = []
            for dm in range(-6, 7):
                midi2 = c["midi"] + dm
                if midi2 % 12 in pcs:
                    f2 = A4 * 2.0 ** ((midi2 - 69) / 12.0)
                    cands.append((abs(1200 * np.log2(f2 / c["freq_hz"])), midi2, f2))
            cents, midi2, f2 = min(cands)
            act = "retune" if cents <= 250 else "drop"
            out.append({"freq_hz": c["freq_hz"], "action": act,
                        "retune_to_note": f"{NOTE_NAMES[midi2 % 12]}{midi2 // 12 - 1}",
                        "retune_to_hz": round(f2, 2),
                        "retune_cents": round(float(np.sign(np.log2(f2 / c['freq_hz'])) * cents), 1)})
    return out

def bpm_block(nominal_s: float, measured_s: float | None, label: str) -> dict:
    base = 60.0 / nominal_s
    d = {"frame_period_s_nominal": round(nominal_s, 6),
         "bpm_1x": round(base, 2), "bpm_2x": round(2 * base, 2),
         "bpm_4x": round(4 * base, 2)}
    if measured_s:
        d["frame_period_s_measured_capture"] = round(measured_s, 6)
        d["bpm_1x_measured"] = round(60.0 / measured_s, 2)
    d["note"] = label
    return d

musical_mapping = {
    "grid_fundamental": {**note_of(GRID), "comment":
        "375 Hz grid spacing = quasi-harmonic series over F#4 (+23 cents sharp "
        "of ET). All carriers are integer harmonics of 375 Hz."},
    "lowest_12_carriers": {"N512_sp4": low_n512, "d2x_N256_sp2": low_d2x},
    "scale_quantizations": {
        name: {"scale_notes": sc["names"],
               "N512_sp4": quantize(low_n512, sc["pcs"]),
               "d2x_N256_sp2": quantize(low_d2x, sc["pcs"])}
        for name, sc in SCALES.items()
    },
    "harmonic_series_note": (
        "Played untouched the grid is a harmonic series on F# (+23c): harmonics "
        "1,2,4,8,16=F#; 3,6,12=C#; 5,10,20=A#; 9,18=G#; 7,14=E (-8c vs ET, the "
        "flat seventh); 11=C (-25c vs ET, tritone); 13=D# (-36c, the 4875 Hz "
        "pilot). Native key = F# major / F# mixolydian. For F# major pentatonic, "
        "retune only the 7th/14th-harmonic carriers (2625/5250 Hz ~ E) and the "
        "11th (4125 Hz ~ C) per the tables; for natural minor, retune the A# "
        "carriers (1875/3750 Hz) down to A."),
    "bpm_candidates": {
        "N512_sp4": bpm_block(period_n512["nominal_period_s"],
                              period_n512["measured_capture_period_s"],
                              "1.373 s frame -> 43.7 BPM half-time feel; "
                              "use 87.4 or 174.8 BPM grids"),
        "d2x_N256_sp2": bpm_block(period_d2x["nominal_period_s"],
                                  period_d2x["measured_capture_period_s"],
                                  "0.983 s frame -> 61.0 BPM; double to 122 BPM "
                                  "(house/techno sweet spot)"),
        "polyrhythm_note": "65888/47200 = 1.3960 ~ 7:5 between section families.",
    },
}

# --------------------------------------------------------------------------
# 6. render ref_snippets.wav (~20 s) from the REAL capture
# --------------------------------------------------------------------------
def cap_section_mid(payload: dict, dur: float) -> tuple[float, np.ndarray]:
    fs = payload["frame_starts"]
    start = m2c(fs[len(fs) // 2] / SR)
    return start, seg(cap, start, dur)

snip_plan = []
pieces = []

def add(label: str, source_start_s: float, audio: np.ndarray, target_peak=0.7):
    audio = audio.astype(np.float64)
    pk = np.abs(audio).max()
    if pk > 0:
        audio = audio * (target_peak / pk)
    edge_fade(audio)
    t0 = sum(len(p) for p in pieces) / SR
    pieces.append(audio)
    snip_plan.append({"label": label, "snippet_start_s": round(t0, 3),
                      "dur_s": round(len(audio) / SR, 3),
                      "capture_source_s": round(source_start_s, 3)})
    # separator: click + breath
    pieces.append(np.zeros(int(0.12 * SR)))
    pieces.append(click())
    pieces.append(np.zeros(int(0.18 * SR)))

# 4 s of a real d2x section (the dense buzzy texture)
s0, a0 = cap_section_mid(p_d2x, 4.0)
add("d2x_N256_sp2_real (m10_r5)", s0, a0)
# 4 s of a real N512 section
s1, a1 = cap_section_mid(p_n512, 4.0)
add("N512_sp4_real (m10_r0)", s1, a1)
# the start chirp (riser), with a little room before it
c0s = cap_c0 / SR - 0.3
add("global_up_chirp_real (500->5000 Hz, 0.2 s)", c0s, seg(cap, c0s, 1.2))
# the Schroeder sounder (noise splash) -- first multitone rep
snd = next(s for s in sections if s["type"] == "sounder_multitone")
add("schroeder_multitone_real (64 tones 300-11000 Hz)",
    snd["capture_start_s"], seg(cap, snd["capture_start_s"], 4.0))
# a preamble in rhythm: ~3.2 frame periods of r0 => three ticks + data
pre0 = period_n512["first_preamble_capture_s"] - 0.08
add("frame_preamble_rhythm_real (800->3200 Hz tick + data, 3 ticks)",
    pre0, seg(cap, pre0, 3.2 * period_n512["measured_capture_period_s"]))

mono = np.concatenate(pieces)
mono = mono * (10 ** (-1.0 / 20.0) / np.abs(mono).max())   # peak -1 dBFS
stereo = np.stack([mono, mono], axis=1)
sf.write(OUT_SNIP, stereo, SR, subtype="PCM_16")
print(f"[snippets] wrote {OUT_SNIP.name}: {len(mono)/SR:.1f} s, "
      f"peak {20*np.log10(np.abs(mono).max()):.2f} dBFS")

# --------------------------------------------------------------------------
# 7. palette.json
# --------------------------------------------------------------------------
palette = {
    "generated_by": "experiments/tape_v2/bside_remix/extract_palette.py",
    "seed": SEED,
    "sample_rate": SR,
    "sources": {
        "manifest": str(MANIFEST),
        "master_wav": {"path": str(MASTER_WAV), "duration_s": round(sf.info(MASTER_WAV).duration, 2)},
        "capture_wav": {"path": str(CAPTURE_WAV), "duration_s": round(len(cap) / SR, 2)},
    },
    "global_chirp": {
        "f0_hz": gc["f0"], "f1_hz": gc["f1"], "duration_s": gc["T"],
        "master_up_start_s": round(tx_c0 / SR, 4),
        "master_down_start_s": round(tx_c1 / SR, 4),
        "capture_up_start_s": round(cap_c0 / SR, 4),
        "capture_down_start_s": round(cap_c1 / SR, 4),
    },
    "deck_speed": {
        "capture_over_master_time_ratio": round(ratio, 6),
        "pitch_shift_pct": round((1 / ratio - 1) * 100, 4),
        "note": "capture_time = capture_up_start + (master_time - master_up_start) * ratio",
    },
    "frame_preamble": {
        "f0_hz": PRE_F0, "f1_hz": PRE_F1, "duration_s": PRE_T, "amplitude": PRE_AMP,
        "gap_after_s": round(frame_gap_s, 4),
        "measured": {"N512_sp4": period_n512, "d2x_N256_sp2": period_d2x},
    },
    "sections": sections,
    "carriers": {
        "N512_sp4": {
            "section": p_n512["name"], "spacing_hz": GRID,
            "pilot_hz": p_n512["pilot_hz_actual"],
            "freqs_hz": p_n512["carrier_freqs_hz"],
        },
        "d2x_N256_sp2": {
            "section": p_d2x["name"], "spacing_hz": GRID,
            "pilot_hz": p_d2x["pilot_hz_actual"],
            "dropped_freqs_hz": p_d2x["dqpsk_params"]["drop_freqs_hz"],
            "freqs_hz": p_d2x["carrier_freqs_hz"],
        },
        "comment": "DQPSK phase hops every symbol give the buzzy modem texture; "
                   "pilot at 4875 Hz (13th harmonic of 375) runs through everything.",
    },
    "sounders": {
        "multitone_freqs_hz": man["sounder_sections"][0]["info"]["freqs"],
        "steady_tone_hz": man["sounder_sections"][2]["info"]["f0"],
    },
    "capture_verification": {"N512_sp4": ver_n512, "d2x_N256_sp2": ver_d2x},
    "musical_mapping": musical_mapping,
    "ref_snippets": {"file": str(OUT_SNIP), "segments": snip_plan},
}
OUT_JSON.write_text(json.dumps(palette, indent=2))
print(f"[palette] wrote {OUT_JSON.name}")
