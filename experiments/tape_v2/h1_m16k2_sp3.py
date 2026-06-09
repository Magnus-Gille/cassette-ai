"""h1_m16k2_sp3.py — H1: DENSIFY SYMBOLS, KEEP THE SPACING.

Hypothesis: WS_M16_K2_sp3_N256 (2-of-16 tones, same 3-bin/562.5 Hz spacing that
survives the real channel) carries 6 bits/sym vs the proven 4 -> 1125 gross bps.
At RS(255,159) that nets 701.5 bps, at RS(255,191) 842.6 bps — both beat the
proven 561.8 net bps baseline (WS_M16_K1_sp3_N256 @ RS(255,191)).

Harness (m5-style, sim_v2 faithful channel):
  payload (8 KB slice of stories260K_int4.cass, m7 offsets)
    -> m3_codec.encode_payload (RS(255,k) + global column interleave, fb=510)
    -> per-frame WideSpaceScheme.modulate (own 0.25 s preamble)
    -> ONE section wav (PILOT SOUNDER + frames + 0.12 s gaps)
    -> sim_v2.channel_v2(section, profile='tape7', aac=True, seed_offset=seed)
    -> EQ measured from the received pilot (per-tone bursts; the same
       signal-derived role the real masters' sounder section plays in
       m5/m7_decode — h1_debug.py showed the params-derived eq_for EQ is
       mismatched to the sim_v2 channel: control raw BER 0.114 vs 0.026
       with measured EQ)
    -> per-frame window (known start +/- 0.30 s pad) -> achievable
       contrast-detector + concentration-lock tracker (assault_widespace)
    -> m3_codec.decode_payload -> byte-exact vs truth (truth ONLY for scoring).

MANDATORY CONTROL: WS_M16_K1_sp3_N256 @ RS(255,191), seeds {0,1}. Expected from
sim_v2 calibration (results/sim_v2_validation.json): PASS seed 0 (raw ~.034,
0 cw failed), FAIL seed 1 (raw ~.039, many cw) — the documented RS-191 cliff.

Diagnostics (K2-specific, truth-aided, NOT used in the verdict):
  * tone-set confusion: per symbol, |detected pair ∩ true pair| in {0,1,2}
    (is the 2nd tone the failure source?)
  * error concentration: bit-errors per wrong byte (K2's RS advantage check).

Output: results/h1_m16k2_results.json  (+ verbose log on stdout).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                       # noqa: E402
import real_channel_sim as rcs                # noqa: E402
import sim_v2                                 # noqa: E402
import m3_codec as codec                      # noqa: E402
from m3_codec import Rung                     # noqa: E402
from assault_widespace import (               # noqa: E402
    build as ws_build, eq_for, _energies_at, _score, _sym_from_score,
)

FS = 48_000
GAP_S = 0.12          # inter-frame gap (matches m5_master WS_FRAME_GAP_S)
PAD_S = 0.30          # window pad around each frame (matches m5_decode)
RS_N = 255
FRAME_BYTES = 510     # matches m5/m7 rungs
TRACK = 15            # +/- samples, per-symbol concentration-lock tracker

CASS = ROOT / "experiments" / "dpd" / "cassette_llm" / "stories260K_int4.cass"
RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "h1_m16k2_results.json"

BASELINE_NET_BPS = 561.8


# ---------------------------------------------------------------------------
# pilot sounder: preamble + one burst per tone (signal-derived EQ, no truth)
# ---------------------------------------------------------------------------
PILOT_SYMS = 24          # symbols per tone burst
PILOT_MEAS = range(4, 20)  # middle symbols measured (skip edge transients)


def build_pilot(ws):
    parts = [np.asarray(ws._preamble, np.float32)]
    t = np.arange(PILOT_SYMS * ws.N) / FS
    for f in ws.freqs:
        parts.append((0.5 * np.sin(2 * np.pi * f * t)).astype(np.float32))
    return np.concatenate(parts)


def eq_from_pilot(ws, y, pad):
    """Measure per-tone channel magnitude from the received pilot bursts.
    Same normalize+clip convention as m5_decode._ws_eq_from_sounder."""
    N = ws.N
    tone_bins = np.clip(ws._bin_indices, 0, N // 2)
    search = np.asarray(y[: len(ws._preamble) + pad + N], np.float32)
    ds = hc.find_preamble(search, ws.preamble_seconds)
    yy = y.astype(np.float64)
    g = np.zeros(ws.M)
    for m in range(ws.M):
        acc = 0.0
        for s in PILOT_MEAS:
            p = ds + (m * PILOT_SYMS + s) * N
            seg = yy[p:p + N]
            if len(seg) < N:
                continue
            acc += np.abs(np.fft.rfft(seg, n=N))[tone_bins[m]]
        g[m] = acc / len(PILOT_MEAS)
    g = g / (g.max() + 1e-12)
    return np.clip(g, 0.05, None)


# ---------------------------------------------------------------------------
# modulate a whole section; demod per-frame (achievable tracker, returns syms)
# ---------------------------------------------------------------------------
def build_section(ws, frames_bits):
    parts, starts, pos = [], [], 0
    gap = np.zeros(int(GAP_S * FS), np.float32)
    pilot = build_pilot(ws)
    parts.append(pilot)
    pos += len(pilot)
    parts.append(gap)
    pos += len(gap)
    for fb in frames_bits:
        audio = np.asarray(ws.modulate(fb.astype(np.uint8)), np.float32)
        starts.append(pos)
        parts.append(audio)
        pos += len(audio)
        parts.append(gap)
        pos += len(gap)
    return np.concatenate(parts), starts


def demod_frame_syms(ws, eq, y_frame, nsym, detector="contrast", track=TRACK):
    """assault_widespace._demod_frame_achievable, but ALSO returns the chosen
    symbol indices (for the tone-confusion diagnostic). Identical decisions."""
    N, bps = ws.N, ws.bits_per_sym
    tone_bins = np.clip(ws._bin_indices, 0, N // 2)
    guard_bins = ws._guard_bins
    ds = hc.find_preamble(y_frame.astype(np.float32), ws.preamble_seconds)
    yy = y_frame.astype(np.float64)
    drift = 0.0
    bits_out, syms_out = [], []
    for sidx in range(nsym):
        base = ds + sidx * N + int(round(drift))
        best = None
        for d in range(-track, track + 1):
            et, eg = _energies_at(yy, base + d, N, tone_bins, guard_bins)
            if et is None:
                continue
            sc = _score(et, eg, eq, detector)
            si = _sym_from_score(ws, sc)
            srt = np.sort(sc)[::-1]
            lock = (srt[ws.K - 1] - srt[ws.K]) / (abs(srt[0]) + 1e-9)
            if best is None or lock > best[0]:
                best = (lock, si, d)
        if best is None:
            bits_out.extend([0] * bps)
            syms_out.append(0)
            continue
        bits_out.extend(ws._sym_to_bits(best[1]))
        syms_out.append(best[1])
        drift += best[2]
    return np.array(bits_out, np.uint8), syms_out


# ---------------------------------------------------------------------------
# one end-to-end run: (scheme, rs_k, payload, seed) -> result row
# ---------------------------------------------------------------------------
def run_one(ws, rs_k, payload, seed, *, label, diagnostics=False):
    t0 = time.time()
    rung = Rung(name=label, M=ws.M, K=ws.K, rs_n=RS_N, rs_k=rs_k,
                frame_bytes=FRAME_BYTES)
    tx_frames, meta = codec.encode_payload(payload, rung)
    section, starts = build_section(ws, tx_frames)

    y = sim_v2.channel_v2(section.astype(np.float64), profile="tape7",
                          aac=True, seed_offset=int(seed))
    y = y.astype(np.float32)

    pad = int(PAD_S * FS)
    eq = eq_from_pilot(ws, y, pad)   # signal-derived (sounder role), no truth
    pre = len(ws._preamble)
    N, bps = ws.N, ws.bits_per_sym

    raw_err = raw_tot = 0
    frames_rx = []
    conf = {"both": 0, "one": 0, "zero": 0, "unmapped": 0}  # tone-set confusion
    for fi, tb in enumerate(tx_frames):
        nbits = len(tb)
        nsym = int(np.ceil(nbits / bps))
        flen = pre + nsym * N
        st = starts[fi]
        w_lo = max(0, st - pad)
        w_hi = min(len(y), st + flen + pad)
        rb, syms = demod_frame_syms(ws, eq, y[w_lo:w_hi], nsym)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_tot += len(tb)
        frames_rx.append(rb)
        if diagnostics:
            # true symbol sequence for this frame
            tbits = tb
            padb = (-len(tbits)) % bps
            if padb:
                tbits = np.concatenate([tbits, np.zeros(padb, np.uint8)])
            for sidx in range(nsym):
                ts = ws._bits_to_sym(tbits[sidx * bps:(sidx + 1) * bps])
                ds_ = syms[sidx]
                if ds_ == ts:
                    conf["both"] += 1
                    continue
                tset = set(ws._table[ts].tolist())
                dset = set(ws._table[ds_].tolist())
                inter = len(tset & dset)
                if ds_ == 0 and inter == 0:
                    conf["unmapped"] += 1  # likely rev_table miss -> clipped to 0
                conf[{2: "both", 1: "one", 0: "zero"}[inter]] += 1

    recovered = codec.decode_payload(frames_rx, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == payload
    byte_err = sum(a != b for a, b in zip(recovered, payload)) + abs(
        len(recovered) - len(payload))

    # error-concentration diagnostic on the raw interleaved stream
    tx_bits = np.concatenate([f for f in tx_frames])
    rx_bits = np.concatenate([
        (np.concatenate([f, np.zeros(len(t) - len(f), np.uint8)])[:len(t)]
         if len(f) < len(t) else f[:len(t)])
        for f, t in zip(frames_rx, tx_frames)])
    nb = len(tx_bits) // 8
    txb = np.packbits(tx_bits[:nb * 8])
    rxb = np.packbits(rx_bits[:nb * 8])
    bad_bytes = int(np.count_nonzero(txb != rxb))
    bit_errs = int(np.count_nonzero(tx_bits[:nb * 8] != rx_bits[:nb * 8]))

    gross = ws.bits_per_sym * FS / ws.N
    net = gross * rs_k / RS_N
    row = {
        "label": label, "phy": ws.name, "rs_k": rs_k, "seed": int(seed),
        "gross_bps": round(gross, 1), "net_bps": round(net, 1),
        "n_frames": meta["n_frames"], "n_codewords": meta["n_codewords"],
        "raw_ber": round(raw_err / max(1, raw_tot), 5),
        "cw_failed": cw_failed,
        "byte_errors": byte_err,
        "byte_exact": bool(exact),
        "raw_byte_er": round(bad_bytes / max(1, nb), 5),
        "bit_errs_per_bad_byte": round(bit_errs / max(1, bad_bytes), 3),
        "section_seconds": round(len(section) / FS, 1),
        "wall_seconds": round(time.time() - t0, 1),
    }
    if diagnostics:
        row["pilot_eq"] = np.round(eq, 3).tolist()
        tot = max(1, sum(conf[k] for k in ("both", "one", "zero")))
        row["tone_confusion"] = {
            **conf,
            "frac_one_tone_wrong": round(conf["one"] / tot, 4),
            "frac_both_wrong": round(conf["zero"] / tot, 4),
            "sym_err_rate": round((conf["one"] + conf["zero"]) / tot, 4),
        }
    return row


def main():
    RESULTS.mkdir(exist_ok=True)
    full = CASS.read_bytes()
    assert len(full) == 153823, len(full)

    out = {"experiment": "h1_m16k2_sp3", "profile": "tape7", "aac": True,
           "baseline_net_bps": BASELINE_NET_BPS,
           "frame_bytes": FRAME_BYTES, "gap_s": GAP_S, "pad_s": PAD_S,
           "control": [], "h1": [], "sanity": {}}

    def flush():
        OUT_JSON.write_text(json.dumps(out, indent=2, default=float))

    # ---- build schemes ----
    ws_k1 = ws_build(16, 1, 3, 256)
    ws_k2 = ws_build(16, 2, 3, 256)
    assert ws_k1 is not None and ws_k1.name == "WS_M16_K1_sp3_N256"
    assert ws_k2 is not None and ws_k2.name == "WS_M16_K2_sp3_N256"
    print(f"[h1] K2 scheme: {ws_k2.name}  bits/sym={ws_k2.bits_per_sym}  "
          f"freqs {ws_k2.freqs[0]:.1f}..{ws_k2.freqs[-1]:.1f} Hz  "
          f"(n_symbols={ws_k2.n_symbols}, cap={ws_k2._sym_cap})", flush=True)
    out["sanity"]["k2_freqs_hz"] = [float(ws_k2.freqs[0]), float(ws_k2.freqs[-1])]
    out["sanity"]["k2_bits_per_sym"] = ws_k2.bits_per_sym

    # ---- no-channel sanity (demod-bug catch) ----
    from assault_widespace import eval_scheme
    params = rcs.load_params()
    for tag, ws in (("k1", ws_k1), ("k2", ws_k2)):
        s = eval_scheme(ws, params, "master3", detector="contrast",
                        reps=2, nsym=48, sanity=True)["sanity_ber"]
        out["sanity"][f"{tag}_nochannel_ber"] = s
        print(f"[h1] sanity {ws.name}: no-channel BER={s:.2e}", flush=True)
        assert s < 1e-6, f"demod bug: sanity BER {s}"
    flush()

    # ---- CONTROL: WS_M16_K1 @ RS(255,191), seeds {0,1} ----
    ctrl_payload = full[16384:16384 + 8192]
    for seed in (0, 1):
        r = run_one(ws_k1, 191, ctrl_payload, seed,
                    label="ctrl_m16k1_rs191")
        out["control"].append(r)
        print(f"[ctrl] seed{seed}: raw_ber={r['raw_ber']:.4f} "
              f"cw_failed={r['cw_failed']}/{r['n_codewords']} "
              f"byte_exact={r['byte_exact']} ({r['wall_seconds']}s)", flush=True)
        flush()

    # control sanity gate (documented cliff: PASS seed0, marginal/FAIL seed1)
    c0, c1 = out["control"]
    harness_ok = c0["raw_ber"] < 0.10 and c1["raw_ber"] < 0.10
    out["control_harness_ok"] = bool(harness_ok)
    if not harness_ok:
        print("[ctrl] HARNESS BROKEN: control at chance BER — aborting", flush=True)
        flush()
        return

    # ---- H1 ladder: K2 @ RS(255,{127,159,191}), seeds {0,1,2} ----
    offsets = {127: 0, 159: 8192, 191: 16384}   # m7-style distinct slices
    for rs_k in (127, 159, 191):
        payload = full[offsets[rs_k]:offsets[rs_k] + 8192]
        assert len(payload) == 8192
        for seed in (0, 1, 2):
            r = run_one(ws_k2, rs_k, payload, seed,
                        label=f"h1_m16k2_rs{rs_k}",
                        diagnostics=(seed == 0))
            out["h1"].append(r)
            tc = r.get("tone_confusion")
            extra = (f" symErr={tc['sym_err_rate']:.3f} "
                     f"oneTone={tc['frac_one_tone_wrong']:.3f}" if tc else "")
            print(f"[h1] rs{rs_k} seed{seed}: raw_ber={r['raw_ber']:.4f} "
                  f"cw_failed={r['cw_failed']}/{r['n_codewords']} "
                  f"byte_exact={r['byte_exact']} net={r['net_bps']}bps"
                  f"{extra} ({r['wall_seconds']}s)", flush=True)
            flush()

    # ---- verdict per pre-registered gate ----
    verdict = "FAIL"
    best = None
    for rs_k in (191, 159, 127):
        rows = [r for r in out["h1"] if r["rs_k"] == rs_k]
        n_exact = sum(r["byte_exact"] for r in rows)
        net = rows[0]["net_bps"]
        if net > BASELINE_NET_BPS and n_exact >= 2:
            verdict = "PASS"
            best = (rs_k, net, n_exact)
            break
        if net > BASELINE_NET_BPS and n_exact == 1 and verdict != "PASS":
            verdict = "PARTIAL"
            if best is None:
                best = (rs_k, net, n_exact)
    out["verdict"] = verdict
    out["best"] = ({"rs_k": best[0], "net_bps": best[1], "seeds_exact": best[2]}
                   if best else None)
    seed0 = {f"rs{r['rs_k']}": r["byte_exact"]
             for r in out["h1"] if r["seed"] == 0}
    out["seed0_only"] = seed0
    print(f"[h1] VERDICT={verdict} best={out['best']} seed0_only={seed0}",
          flush=True)
    flush()
    print(f"[h1] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
