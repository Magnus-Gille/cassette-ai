"""w4_endtoend.py — Wave 4: real end-to-end whole-file recovery proof.

Closes the loop between the projected "net_bps at P_full=1.0" and an ACTUAL
recovered file. Takes real bytes from the 150 KB cassette-LLM, protects them with
an interleaved Reed-Solomon outer code at ~the projection's rate, modulates with
the deep-dive #2 real champion (M12,K2 flutter-tracked combinatorial), pushes the
whole stream through the HARSH real channel (worn + 0.88x clock + flutter + bursts)
ONCE, demodulates, de-interleaves, RS-decodes, and verifies the recovered bytes are
BIT-EXACT identical to the original.

This is the honest validation of the headline: if the projection says M12K2 carries
2525 net bps whole-file-recoverable on the worn deck, a real RS code at that rate
must actually recover a real file.
"""
from __future__ import annotations
import sys, pathlib, json, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "capacity"))
import numpy as np
import dd_common as dd
import capture_scenarios as cs
from reedsolo import RSCodec
from d3d4_combo_tracked import make_tracked_combo

RESULTS = pathlib.Path(__file__).parent / "results"
CASS = pathlib.Path(__file__).parent.parent / "dpd" / "cassette_llm" / "stories260K_int4.cass"

RS_N, RS_K = 255, 191        # rate 0.749, corrects 32 sym errors / 255 (~12.5%)


def rs_encode_blocks(data: bytes):
    """Split into K-byte chunks, RS(255,191)-encode each → list of 255-byte blocks."""
    rsc = RSCodec(RS_N - RS_K)
    blocks = []
    for i in range(0, len(data), RS_K):
        chunk = data[i:i + RS_K]
        blocks.append(bytes(rsc.encode(chunk)))   # len 255 (last chunk shorter+parity)
    return blocks, rsc


def interleave_bits(blocks):
    """Deep block interleave: stack block-bitstreams as rows, read columns. A burst
    that corrupts consecutive transmitted bits is spread one-bit-per-block."""
    bitrows = [np.unpackbits(np.frombuffer(b, np.uint8)) for b in blocks]
    L = max(len(r) for r in bitrows)
    mat = np.zeros((len(bitrows), L), np.uint8)
    for i, r in enumerate(bitrows):
        mat[i, :len(r)] = r
    return mat.T.reshape(-1), mat.shape   # column-major stream + shape


def deinterleave_bits(stream, shape):
    nrow, L = shape
    s = np.asarray(stream[:nrow * L], np.uint8)
    if len(s) < nrow * L:
        s = np.concatenate([s, np.zeros(nrow * L - len(s), np.uint8)])
    mat = s.reshape(L, nrow).T
    return mat   # (nblocks, L)


def _run_one(raw: bytes, M=12, K=2, seed=0, channel="real"):
    """One frame: bytes -> RS+interleave -> M,K modem -> channel -> decode -> bytes."""
    blocks, rsc = rs_encode_blocks(raw)
    stream, shape = interleave_bits(blocks)
    sch = make_tracked_combo(M, K)
    audio = np.asarray(sch.modulate(stream.astype(np.uint8)), dtype=np.float32)
    cfg = dd.CHANNELS[channel]
    rx, sr, _ = cs.full_chain(audio, cfg["tape_preset"], cfg["capture_key"],
                              speed_offset=cfg["speed_offset"], seed=seed)
    rec_bits = np.asarray(sch.demodulate(rx, sr), dtype=np.uint8)
    n = shape[0] * shape[1]
    if len(rec_bits) < n:
        rec_bits = np.concatenate([rec_bits, np.zeros(n - len(rec_bits), np.uint8)])
    raw_bit_err = float(np.mean(rec_bits[:len(stream)] != stream[:len(rec_bits)]))
    mat = deinterleave_bits(rec_bits, shape)
    recovered = bytearray()
    n_fail = 0
    for i in range(len(blocks)):
        row_bits = mat[i]
        nbytes = (len(row_bits) // 8)
        block_bytes = np.packbits(row_bits[:nbytes * 8]).tobytes()
        try:
            recovered += rsc.decode(block_bytes)[0]
        except Exception:
            n_fail += 1
            recovered += bytes(RS_K)
    rec_trunc = bytes(recovered)[:len(raw)]
    return {"raw_bit_error": raw_bit_err, "rs_blocks_failed": n_fail,
            "byte_exact": rec_trunc == raw, "_recovered": rec_trunc}


def run(payload_bytes: int, M=12, K=2, seed=0, channel="real"):
    raw = CASS.read_bytes()[:payload_bytes]
    blocks, rsc = rs_encode_blocks(raw)
    stream, shape = interleave_bits(blocks)
    sch = make_tracked_combo(M, K)
    audio = np.asarray(sch.modulate(stream.astype(np.uint8)), dtype=np.float32)
    cfg = dd.CHANNELS[channel]
    t0 = time.time()
    rx, sr, _ = cs.full_chain(audio, cfg["tape_preset"], cfg["capture_key"],
                              speed_offset=cfg["speed_offset"], seed=seed)
    rec_bits = np.asarray(sch.demodulate(rx, sr), dtype=np.uint8)
    # align length to the interleaved stream
    n = shape[0] * shape[1]
    if len(rec_bits) < n:
        rec_bits = np.concatenate([rec_bits, np.zeros(n - len(rec_bits), np.uint8)])
    raw_bit_err = float(np.mean(rec_bits[:len(stream)] != stream[:len(rec_bits)]))
    mat = deinterleave_bits(rec_bits, shape)
    # RS-decode each block
    recovered = bytearray()
    n_fail = 0
    nblocks = len(blocks)
    for i in range(nblocks):
        row_bits = mat[i]
        nbytes = (len(row_bits) // 8)
        block_bytes = np.packbits(row_bits[:nbytes * 8]).tobytes()
        try:
            dec = rsc.decode(block_bytes)[0]
            recovered += dec
        except Exception:
            n_fail += 1
            recovered += bytes(RS_K)   # placeholder for failed block
    rec_trunc = bytes(recovered)[:len(raw)]
    exact = (rec_trunc == raw)
    byte_err = sum(a != b for a, b in zip(rec_trunc, raw))
    return {
        "payload_bytes": len(raw), "n_blocks": nblocks, "seed": seed,
        "channel": channel, "raw_bit_error": raw_bit_err,
        "rs_blocks_failed": n_fail, "byte_errors_after_rs": byte_err,
        "byte_exact": bool(exact), "audio_seconds": len(audio) / dd.FS,
        "sim_seconds": time.time() - t0,
        "code_rate": RS_K / RS_N, "gross_bps": sch.gross_bps,
        "net_bps_effective": sch.gross_bps * RS_K / RS_N,
    }


def run_framed(total_bytes, frame_bytes=4000, M=12, K=2, seed0=0, channel="real"):
    """Realistic framing: the file is sent as independent frames, each with its OWN
    chirp preamble (the modem re-syncs every frame). A single 300 s stream loses
    sync to accumulated flutter drift; periodic re-sync (standard in every real tape
    modem) fixes it. Each frame is an independent channel pass + demod; whole-file
    recovery = all frames byte-exact."""
    raw = CASS.read_bytes()[:total_bytes]
    frames = [raw[i:i + frame_bytes] for i in range(0, len(raw), frame_bytes)]
    recovered = bytearray()
    per_frame = []
    n_exact = 0
    t0 = time.time()
    for fi, fbytes in enumerate(frames):
        r = _run_one(fbytes, M, K, seed0 + fi, channel)
        per_frame.append({"frame": fi, "bytes": len(fbytes),
                          "raw_bit_error": r["raw_bit_error"],
                          "rs_failed": r["rs_blocks_failed"],
                          "byte_exact": r["byte_exact"]})
        recovered += r["_recovered"]
        n_exact += int(r["byte_exact"])
    whole_exact = (bytes(recovered)[:len(raw)] == raw)
    return {
        "total_bytes": len(raw), "n_frames": len(frames), "frame_bytes": frame_bytes,
        "frames_byte_exact": n_exact, "whole_file_byte_exact": bool(whole_exact),
        "per_frame_recovery_rate": n_exact / len(frames),
        "sim_seconds": time.time() - t0, "channel": channel,
        "code_rate": RS_K / RS_N,
    }


def run_global(total_bytes, frame_bytes=4000, M=12, K=2, seed0=0, channel="real"):
    """CD/DAT-style: re-sync framing (handles the 331 s drift) + GLOBAL byte
    interleaving of the RS coding across the WHOLE file. Each RS codeword's 255
    bytes are scattered across all frames (column interleave over codewords), so a
    single de-synced frame corrupts only a handful of bytes per codeword — each
    well within RS's correction power. This is what lets whole-file recovery hold
    at the mean-BER rate instead of being hostage to the worst frame."""
    raw = CASS.read_bytes()[:total_bytes]
    rsc = RSCodec(RS_N - RS_K)
    cw = []                                   # list of 255-byte codewords
    for i in range(0, len(raw), RS_K):
        cw.append(bytes(rsc.encode(raw[i:i + RS_K])))
    n_cw = len(cw)
    mat = np.frombuffer(b"".join(cw), np.uint8).reshape(n_cw, RS_N)
    tx_bytes = mat.T.reshape(-1)              # column-major: byte j of every codeword
    tx_bits = np.unpackbits(tx_bytes)
    # chunk into frames for independent re-sync
    fb_bits = frame_bytes * 8
    frames = [tx_bits[i:i + fb_bits] for i in range(0, len(tx_bits), fb_bits)]
    sch = make_tracked_combo(M, K)
    cfg = dd.CHANNELS[channel]
    rx_bits_all = []
    t0 = time.time()
    desync = 0
    for fi, fbits in enumerate(frames):
        audio = np.asarray(sch.modulate(fbits.astype(np.uint8)), dtype=np.float32)
        rx, sr, _ = cs.full_chain(audio, cfg["tape_preset"], cfg["capture_key"],
                                  speed_offset=cfg["speed_offset"], seed=seed0 + fi)
        rb = np.asarray(sch.demodulate(rx, sr), dtype=np.uint8)
        if len(rb) < len(fbits):
            rb = np.concatenate([rb, np.zeros(len(fbits) - len(rb), np.uint8)])
        rb = rb[:len(fbits)]
        if np.mean(rb != fbits) > 0.05:
            desync += 1
        rx_bits_all.append(rb)
    rx_bits = np.concatenate(rx_bits_all)[:len(tx_bits)]
    rx_bytes = np.packbits(rx_bits)[:n_cw * RS_N]
    rx_mat = rx_bytes.reshape(RS_N, n_cw).T    # de-interleave -> codewords
    recovered = bytearray()
    n_fail = 0
    for i in range(n_cw):
        try:
            recovered += rsc.decode(bytes(rx_mat[i]))[0]
        except Exception:
            n_fail += 1
            recovered += bytes(RS_K)
    rec = bytes(recovered)[:len(raw)]
    return {"total_bytes": len(raw), "n_codewords": n_cw, "n_frames": len(frames),
            "frame_bytes": frame_bytes, "frames_desynced": desync,
            "rs_codewords_failed": n_fail, "whole_file_byte_exact": bool(rec == raw),
            "byte_errors": sum(a != b for a, b in zip(rec, raw)),
            "code_rate": RS_K / RS_N, "gross_bps": sch.gross_bps,
            "net_bps_effective": sch.gross_bps * RS_K / RS_N,
            "sim_seconds": time.time() - t0, "channel": channel}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--bytes", type=int, default=12000)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--channel", default="real")
    ap.add_argument("--framed", action="store_true")
    ap.add_argument("--global-il", action="store_true")
    ap.add_argument("--frame-bytes", type=int, default=4000)
    args = ap.parse_args()

    if args.global_il:
        out = run_global(args.bytes, frame_bytes=args.frame_bytes, channel=args.channel)
        print(f"[{args.channel}] {out['n_frames']} frames, {out['n_codewords']} RS codewords, "
              f"{out['frames_desynced']} frames desynced, {out['rs_codewords_failed']} RS-fail, "
              f"byteErr={out['byte_errors']}, WHOLE-FILE byte-exact = "
              f"{out['whole_file_byte_exact']} (net {out['net_bps_effective']:.0f} bps, "
              f"{out['sim_seconds']:.0f}s)")
        json.dump(out, open(RESULTS / f"w4_global_{args.channel}_{args.bytes}.json", "w"),
                  indent=2, default=float)
        print(f"[saved] results/w4_global_{args.channel}_{args.bytes}.json")
        sys.exit(0)

    if args.framed:
        out = run_framed(args.bytes, frame_bytes=args.frame_bytes, channel=args.channel)
        print(f"[{args.channel}] {out['n_frames']} frames x {args.frame_bytes}B: "
              f"frames byte-exact {out['frames_byte_exact']}/{out['n_frames']}, "
              f"WHOLE-FILE byte-exact = {out['whole_file_byte_exact']} "
              f"({out['sim_seconds']:.0f}s)")
        json.dump(out, open(RESULTS / f"w4_framed_{args.channel}_{args.bytes}.json", "w"),
                  indent=2, default=float)
        print(f"[saved] results/w4_framed_{args.channel}_{args.bytes}.json")
        sys.exit(0)
    runs = []
    for s in range(args.seeds):
        r = run(args.bytes, seed=s, channel=args.channel)
        runs.append(r)
        print(f"seed{s} [{args.channel}] bytes={r['payload_bytes']} blocks={r['n_blocks']} "
              f"rawBER={r['raw_bit_error']:.4f} RSfail={r['rs_blocks_failed']} "
              f"byteErr={r['byte_errors_after_rs']} EXACT={r['byte_exact']} "
              f"({r['audio_seconds']:.0f}s audio, {r['sim_seconds']:.0f}s sim)")
    n_exact = sum(r["byte_exact"] for r in runs)
    out = {"runs": runs, "n_exact": n_exact, "n_seeds": args.seeds,
           "payload_bytes": args.bytes,
           "whole_file_recovery_rate": n_exact / args.seeds}
    tag = f"{args.channel}_{args.bytes}"
    json.dump(out, open(RESULTS / f"w4_endtoend_{tag}.json", "w"), indent=2, default=float)
    print(f"WHOLE-FILE byte-exact recovery: {n_exact}/{args.seeds} on {args.channel}")
    print(f"[saved] results/w4_endtoend_{tag}.json")
