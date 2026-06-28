"""m3_codec.py — payload<->frames codec + the master3 robustness LADDER.

This is the codec layer for the PHYSICAL tape_v2 master3: it carries the REAL
153,823-byte cassette-LLM payload and aims for the FIRST byte-exact recovery of a
real file off a cassette, using the deep-dive #2 breakthrough (flutter-tracked
combinatorial k-of-M index modulation + global RS-interleave whole-file FEC).

It REUSES, without reinventing:
  * d3d4_combo_tracked.make_tracked_combo(M, K) — the flutter-tracked combinatorial
    PHY. Each frame is modulated independently (own 0.25 s chirp preamble) and
    demodulated with the dd_common per-symbol energy-lock tracker.
  * w4_endtoend.run_global's PROVEN encode/decode math — RS(n,k) over the payload,
    GLOBAL column-interleave of the 255-byte codewords across frames, per-frame
    independent modulation/demod/re-sync, de-interleave, RS-decode. That pipeline
    recovered the whole 153 KB LLM byte-exact through the worn channel. Here it is
    refactored into reusable encode_payload / decode_payload functions.

THE LADDER (RUNGS, robust -> frontier)
--------------------------------------
The actual clean capture last night measured ~0.44% flutter. A measured flutter
sweep of the tracked-combo PHY (SNR 30 dB, 0.88x clock) gives the robustness lever
that actually matters here -- and it OVERTURNS the classic "wide spacing = lower M
= more flutter-robust" heuristic:

    flutter   M12K2 surv   M16K2 surv   M20K2 surv
    0.44%       0.75         1.00         0.88
    0.70%       0.25         0.38         0.50

Lower M is WORSE, not better, for this PHY. The dominant failure mode is the
per-symbol energy-lock TIMING tracker losing lock, and a lower M means fewer
samples_per_sym (M12=58 vs M16=77), so a shorter symbol window the tracker loses
faster. Energy detection already immunises the *frequency* dimension against
flutter phase chaos, so widening tone spacing buys nothing; what helps is a LONGER
symbol (higher M) for the timing tracker, plus shorter frames for more re-syncs.
M8/M10 are non-viable (degenerate tiny-window demod: M8 fails even with no channel).

So the robustness lever on this ladder is the RS RATE and frame length, NOT M:
every rung uses the verified M16,K2 PHY (survival 1.0 at 0.44% flutter) and ladders
purely on FEC strength and re-sync density.

  - robust   : M=16,K=2, RS(255,127) rate 0.498, fb 2000 -- 64 of 255 sym/codeword
               correctable (25%), most re-syncs. Survives >=0.5% flutter excursions.
  - mid      : M=16,K=2, RS(255,159) rate 0.624, fb 3000 -- 48/255 (19%) correctable.
  - frontier : M=16,K=2, RS(255,191) rate 0.749, fb 4000 -- the deep-dive verified
               real champion reproduced exactly (w4 run_global): rawBER ~1.3e-3.

Frame size (frame_bytes) sets how many interleaved code bytes ride in one re-synced
modem frame. Smaller frames -> more independent re-syncs (more robust to accumulated
flutter drift) but more preamble overhead; we shrink frame_bytes on the robust rung
for extra drift immunity.
"""
from __future__ import annotations

import pathlib
import sys
import time
from dataclasses import dataclass

import numpy as np

# --- path bootstrap (mirror w4_endtoend.py / dd_common.py) -----------------
_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    _ROOT / "experiments" / "deepdive2",
    _ROOT / "experiments" / "capacity",
    _ROOT / "src",
    _ROOT / "tests" / "e2e",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import dd_common as dd                       # noqa: E402
import capture_scenarios as cs               # noqa: E402
from rs_backend import RSCodec               # noqa: E402
from d3d4_combo_tracked import make_tracked_combo  # noqa: E402

FS = dd.FS
CASS = _ROOT / "experiments" / "dpd" / "cassette_llm" / "stories260K_int4.cass"


# ===========================================================================
# Ladder rungs
# ===========================================================================
@dataclass(frozen=True)
class Rung:
    name: str
    M: int
    K: int
    rs_n: int
    rs_k: int
    frame_bytes: int

    @property
    def code_rate(self) -> float:
        return self.rs_k / self.rs_n


# robust -> frontier
RUNGS: list[Rung] = [
    Rung(name="robust",   M=16, K=2, rs_n=255, rs_k=127, frame_bytes=2000),
    Rung(name="mid",      M=16, K=2, rs_n=255, rs_k=159, frame_bytes=3000),
    Rung(name="frontier", M=16, K=2, rs_n=255, rs_k=191, frame_bytes=4000),
]

RUNGS_BY_NAME = {r.name: r for r in RUNGS}


# ===========================================================================
# encode: payload -> list of frame bit arrays (+ meta)
# ===========================================================================
def encode_payload(payload: bytes, rung: Rung):
    """RS(rs_n,rs_k)-encode the payload, GLOBAL column-interleave the codewords
    across frames, and chunk into per-frame bit arrays (each modulated
    independently downstream with make_tracked_combo(M,K)).

    Returns (frames: list[np.uint8 bit arrays], meta: dict). `meta` carries
    everything decode_payload needs: rung params, n_codewords, payload_len, the
    interleaved-stream bit length, and the per-frame bit length.
    """
    payload = bytes(payload)
    rsc = RSCodec(rung.rs_n - rung.rs_k)

    # pad to a whole number of rs_k-byte chunks so every codeword is exactly rs_n.
    pad = (-len(payload)) % rung.rs_k
    padded = payload + bytes(pad)
    cw = [bytes(rsc.encode(padded[i:i + rung.rs_k]))
          for i in range(0, len(padded), rung.rs_k)]
    n_cw = len(cw)

    # column-major interleave: byte j of every codeword travels together, so a
    # single corrupted frame hits only a few bytes per codeword (well within RS).
    mat = np.frombuffer(b"".join(cw), np.uint8).reshape(n_cw, rung.rs_n)
    tx_bytes = mat.T.reshape(-1)                       # (rs_n * n_cw,)
    tx_bits = np.unpackbits(tx_bytes).astype(np.uint8)  # (rs_n * n_cw * 8,)

    fb_bits = rung.frame_bytes * 8
    frames = [np.ascontiguousarray(tx_bits[i:i + fb_bits])
              for i in range(0, len(tx_bits), fb_bits)]

    meta = {
        "rung": rung.name,
        "M": rung.M, "K": rung.K,
        "rs_n": rung.rs_n, "rs_k": rung.rs_k,
        "frame_bytes": rung.frame_bytes,
        "frame_bits": fb_bits,
        "n_codewords": n_cw,
        "n_frames": len(frames),
        "stream_bits": int(len(tx_bits)),
        "payload_len": len(payload),
    }
    return frames, meta


# ===========================================================================
# decode: list of recovered frame bit arrays (+ meta) -> bytes
# ===========================================================================
def decode_payload(frames_bits, meta: dict) -> bytes:
    """Inverse of encode_payload: pad/truncate each recovered frame to its
    nominal bit length, concat, de-interleave the column-major byte matrix,
    RS-decode every codeword (tolerating a few fully-wrong frames — the whole
    point of the global interleave), and truncate to payload_len.
    """
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    fb_bits = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]
    rsc = RSCodec(rs_n - rs_k)

    # Reassemble the stream at the EXACT bit positions encode used: every frame
    # occupies fb_bits except the last, which is the remainder. A recovered frame
    # may be short (demod ran out) or long (overshoot) — pad/truncate to nominal
    # so de-interleave indices stay aligned even when whole frames are wrong.
    pieces = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else (stream_bits - fb_bits * (n_frames - 1))
        rb = (np.asarray(frames_bits[fi], dtype=np.uint8).ravel()
              if fi < len(frames_bits) else np.zeros(nominal, np.uint8))
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    rx_bits = np.concatenate(pieces)[:stream_bits]
    if len(rx_bits) < stream_bits:
        rx_bits = np.concatenate([rx_bits, np.zeros(stream_bits - len(rx_bits), np.uint8)])

    rx_bytes = np.packbits(rx_bits)[:n_cw * rs_n]
    rx_mat = rx_bytes.reshape(rs_n, n_cw).T            # de-interleave -> codewords

    recovered = bytearray()
    n_fail = 0
    for i in range(n_cw):
        try:
            recovered += rsc.decode(bytes(rx_mat[i]))[0]
        except Exception:
            n_fail += 1
            recovered += bytes(rs_k)                   # placeholder for a dead codeword
    decode_payload.last_codewords_failed = n_fail      # diagnostic side-channel
    return bytes(recovered)[:meta["payload_len"]]


decode_payload.last_codewords_failed = 0


# ===========================================================================
# Self-test
# ===========================================================================
def _clean_roundtrip(payload: bytes, rung: Rung) -> bool:
    """encode -> (no channel) -> decode, must be byte-exact."""
    frames, meta = encode_payload(payload, rung)
    return decode_payload(frames, meta) == payload


def _real_channel(payload: bytes, rung: Rung, seed0: int = 0) -> dict:
    """encode -> per-frame make_tracked_combo(M,K).modulate -> cs.full_chain on
    CHANNELS['real'] -> demod -> decode. Mirrors w4_endtoend.run_global exactly.
    """
    frames, meta = encode_payload(payload, rung)
    sch = make_tracked_combo(rung.M, rung.K)
    cfg = dd.CHANNELS["real"]
    rx_frames = []
    raw_err_acc = 0
    raw_err_tot = 0
    audio_samples = 0
    t0 = time.time()
    for fi, fbits in enumerate(frames):
        audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
        audio_samples += len(audio)
        rx, sr, _ = cs.full_chain(audio, cfg["tape_preset"], cfg["capture_key"],
                                  speed_offset=cfg["speed_offset"], seed=seed0 + fi)
        rb = np.asarray(sch.demodulate(rx, sr), dtype=np.uint8).ravel()
        n = len(fbits)
        rb_cmp = rb[:n] if len(rb) >= n else np.concatenate([rb, np.zeros(n - len(rb), np.uint8)])
        raw_err_acc += int(np.count_nonzero(rb_cmp != fbits))
        raw_err_tot += n
        rx_frames.append(rb)
    recovered = decode_payload(rx_frames, meta)
    exact = recovered == payload
    raw_ber = raw_err_acc / max(1, raw_err_tot)
    audio_seconds = audio_samples / FS
    net_bps = sch.gross_bps * rung.code_rate
    return {
        "rung": rung.name, "payload_bytes": len(payload),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "codewords_failed": decode_payload.last_codewords_failed,
        "raw_ber": raw_ber, "real_byte_exact": bool(exact),
        "net_bps": net_bps, "gross_bps": sch.gross_bps,
        "audio_seconds": audio_seconds, "sim_seconds": time.time() - t0,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--bytes", type=int, default=32768,
                    help="payload slice for the self-test (>=32768 for the clean test)")
    ap.add_argument("--real-bytes", type=int, default=40000,
                    help="payload slice for the (slow) real-channel test per rung. "
                         "Needs enough frames for interleave depth: at the frontier "
                         "rate one fully-desynced frame must stay within RS correction, "
                         "which requires >~10 frames (the full 153KB has ~38).")
    ap.add_argument("--skip-real", action="store_true")
    args = ap.parse_args()

    full = CASS.read_bytes()
    clean_slice = full[:max(args.bytes, 32768)]
    real_slice = full[:args.real_bytes]

    print(f"payload source: {CASS}  ({len(full)} bytes)")
    print(f"clean slice {len(clean_slice)} B, real slice {len(real_slice)} B\n")

    print("=== (a) clean encode->decode (no channel), byte-exact ===")
    clean_ok_all = True
    for r in RUNGS:
        ok = _clean_roundtrip(clean_slice, r)
        clean_ok_all &= ok
        frames, meta = encode_payload(clean_slice, r)
        print(f"  {r.name:8s} M{r.M:2d}K{r.K} RS({r.rs_n},{r.rs_k}) rate{r.code_rate:.3f} "
              f"fb{r.frame_bytes}  frames={meta['n_frames']:3d} cw={meta['n_codewords']:3d}  "
              f"clean_byte_exact={ok}")
    print(f"  ALL clean byte-exact: {clean_ok_all}\n")

    if not args.skip_real:
        print("=== (b) end-to-end through dd CHANNELS['real'], byte-exact ===")
        print("    (frontier needs interleave depth: too-small payloads have too few")
        print("     frames, so one desynced frame can exceed RS at rate 0.749 -- the")
        print("     full 153KB payload gives ~38 frames, plenty. w4 verified this.)")
        for r in RUNGS:
            res = _real_channel(real_slice, r, seed0=0)
            print(f"  {r.name:8s} M{r.M:2d}K{r.K} RS({r.rs_n},{r.rs_k})  "
                  f"frames={res['n_frames']:3d} cwFail={res['codewords_failed']:3d} "
                  f"rawBER={res['raw_ber']:.4f} net={res['net_bps']:.0f}bps  "
                  f"REAL_byte_exact={res['real_byte_exact']}  ({res['sim_seconds']:.0f}s)")
