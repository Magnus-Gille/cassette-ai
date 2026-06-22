#!/usr/bin/env python3
"""
spectrogram.py — THE ONE IMAGE on a Magnetic Vault J-card is the tape's own data
made visible. This renders a DUOTONE spectrogram strip ("ferric on charcoal")
straight from a release's master WAV — the cover's hero image: *the art is the
data.*

It is intentionally NOT a matplotlib chart. We compute a short-time Fourier
transform with scipy, map magnitude (in dB) through a hand-built two-colour ramp
(charcoal ink -> bone -> ferric spot), and write a crisp PNG sized for the cover
panel. No axes furniture is baked in — the J-card annotates it faintly in CSS so
the type system owns the labels.

The strip is the data-transfer signal as it actually sounds: a wall of densely
packed narrowband carriers (the OFDM/QAM modem) — which on a spectrogram reads as
horizontal striations, the literal texture of the bits. We sample a window from
the body of the master (past the lead-in chirp) so the carriers are fully lit.

Usage:
    python3 spectrogram.py <master.wav> <out.png> [--spot RRGGBB] \
        [--start SEC] [--dur SEC] [--width PX] [--height PX] [--fmax HZ]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal


# ---- the ferric duotone ramp ----------------------------------------------
# A printer's-ink ramp: deepest = warm near-black (the charcoal field), midtones
# = the spot colour (oxide), highlights lift toward bone/cream. This is what
# gives the strip its riso/duotone warmth instead of a clinical jet/viridis look.
INK = (0x1a, 0x17, 0x14)        # warm near-black charcoal
BONE = (0xef, 0xe7, 0xd6)       # bone paper


def _hex(s):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _ramp(spot):
    """Build a 256-entry RGB lookup: ink -> spot -> (hot lift toward bone).
    `spot` is the per-release ferric oxide accent."""
    sr, sg, sb = spot
    lut = np.zeros((256, 3), np.uint8)
    for i in range(256):
        t = i / 255.0
        if t < 0.62:
            # ink -> spot (the carriers bloom from charcoal into the oxide spot)
            u = t / 0.62
            # ease so the floor stays dark and carriers pop
            u = u ** 1.35
            r = INK[0] + (sr - INK[0]) * u
            g = INK[1] + (sg - INK[1]) * u
            b = INK[2] + (sb - INK[2]) * u
        else:
            # spot -> bone (only the very hottest bins lift to cream)
            u = (t - 0.62) / 0.38
            u = u ** 1.1
            r = sr + (BONE[0] - sr) * u
            g = sg + (BONE[1] - sg) * u
            b = sb + (BONE[2] - sb) * u
        lut[i] = (round(r), round(g), round(b))
    return lut


def render(wav_path, out_path, spot="c75e34", start=None, dur=10.0,
           width=1100, height=440, fmax=None):
    spot_rgb = _hex(spot)
    info = sf.info(str(wav_path))
    sr = info.samplerate
    total = info.frames

    # Pick a window from the BODY of the signal (carriers fully lit), not the
    # lead-in chirp. Default: a slice ~12% into the file.
    if start is None:
        start = (total / sr) * 0.12
    n_start = int(start * sr)
    n_read = min(int(dur * sr), total - n_start)
    x, _ = sf.read(str(wav_path), start=n_start, frames=n_read, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)

    if fmax is None:
        fmax = sr / 2  # full Nyquist; the modem uses the whole audio band

    # STFT — narrow bins so the individual carriers resolve as striations.
    nper = 2048
    f, t, Zxx = signal.stft(x, fs=sr, nperseg=nper, noverlap=int(nper * 0.78),
                            window="hann")
    mag = np.abs(Zxx)
    # clip to fmax
    keep = f <= fmax
    f = f[keep]
    mag = mag[keep]

    # dB, normalised to a fixed dynamic range so the floor is dark and the
    # carriers are bright. 70 dB span reads as a clean riso duotone.
    db = 20 * np.log10(mag + 1e-9)
    db -= db.max()
    span = 72.0
    norm = np.clip((db + span) / span, 0, 1)

    # gentle gamma so midtone carriers sit in the spot-colour band of the ramp
    norm = norm ** 0.92

    # resample the time-freq grid to the target pixel size. Frequency goes
    # bottom->top, so flip rows.
    idx = (norm * 255).astype(np.uint8)
    img_lin = idx[::-1, :]  # low freq at bottom

    # nearest-resize to (height, width)
    yy = (np.linspace(0, img_lin.shape[0] - 1, height)).astype(int)
    xx = (np.linspace(0, img_lin.shape[1] - 1, width)).astype(int)
    grid = img_lin[yy][:, xx]

    lut = _ramp(spot_rgb)
    rgb = lut[grid]  # (H, W, 3)

    # write PNG without matplotlib — use Pillow if present, else a minimal
    # zlib-deflated PNG writer.
    _write_png(out_path, rgb)
    return {
        "samplerate": sr,
        "start_s": round(start, 2),
        "dur_s": round(n_read / sr, 2),
        "fmax_hz": int(fmax),
        "size": [width, height],
        "spot": "#" + spot,
    }


def _write_png(path, rgb):
    H, W, _ = rgb.shape
    try:
        from PIL import Image
        Image.fromarray(rgb, "RGB").save(str(path), optimize=True)
        return
    except ImportError:
        pass
    # dependency-free PNG (RGB, 8-bit) — zlib + manual chunks
    import struct
    import zlib

    raw = bytearray()
    for y in range(H):
        raw.append(0)  # filter type 0
        raw.extend(rgb[y].tobytes())
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        c += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return c

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", comp) + chunk(b"IEND", b""))
    Path(path).write_bytes(png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("out")
    ap.add_argument("--spot", default="c75e34")
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--dur", type=float, default=10.0)
    ap.add_argument("--width", type=int, default=1100)
    ap.add_argument("--height", type=int, default=440)
    ap.add_argument("--fmax", type=float, default=None)
    a = ap.parse_args()
    meta = render(a.wav, a.out, spot=a.spot, start=a.start, dur=a.dur,
                  width=a.width, height=a.height, fmax=a.fmax)
    print(meta)


if __name__ == "__main__":
    main()
