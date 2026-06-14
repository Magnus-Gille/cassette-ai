"""Preamble-driven / decision-directed ADAPTIVE decoder, validated on the EXISTING
over-air recording (no re-record).

Product model: the intelligence lives in the phone app and adapts to whatever room
it is played in. It estimates per-carrier reliability LIVE and erases the carriers
that this particular room/speaker/phone killed, then RS-erasure-decodes (corrects 2x
as many erasures as errors).

Key finding from the data: the modem's all-ON marker symbols only reveal each
carrier's GAIN, which the modem already normalises out -- so gain alone is a USELESS
reliability metric (erasing low-gain carriers makes things worse). What predicts
errors is per-carrier on/off SEPARABILITY (true SNR incl. leakage). That can be had
two ways:
  - decision-directed: bootstrap it from the received payload itself (no overhead)  <- tested here
  - a real preamble that sends known ON and OFF patterns per carrier               <- make_preamble.py

The erase rule is DEPLOYABLE: erase carriers with separability below a fixed
threshold, worst-first, capped by RS capacity. The decoder never sees the answer.
"""
import numpy as np, hashlib
import chan_lib as C
from reedsolo import RSCodec, ReedSolomonError

rec = C.load_rec(); man = C.load_manifest(); frames = C.segment_frames(rec); OFF0 = 3
THR = C.mod.THR
Q_ERASE = 1.5          # separability threshold (p10-ish); below this a carrier is unreliable
MAXC = 8               # never erase more carriers than this


def carrier_bytes(meta):
    K, Nd, nbytes = meta["K"], meta["ndata_sym"], meta["nbytes"]
    return [list(range(c * Nd // 8, min(((c + 1) * Nd - 1) // 8, nbytes - 1) + 1)) for c in range(K)]


def hard_bits(m, meta):
    Nd, chunk, G, P, K = m["Nd"], meta["chunk"], m["G"], m["P"][:m["Nd"]], m["K"]
    hard = np.zeros((Nd, K), np.uint8); di = 0
    for j in range(len(G) - 1):
        g = np.maximum(G[j], 1e-9)
        for k in range(chunk):
            if di >= Nd: break
            hard[di] = (P[di] > THR * g).astype(np.uint8); di += 1
    return hard


def to_bytes(hard, meta):
    K, Nd, nbytes = meta["K"], meta["ndata_sym"], meta["nbytes"]
    return np.packbits(hard[:Nd].T.reshape(-1)[:nbytes * 8]).tobytes()[:nbytes]


def rs_decode(cw, meta, erase_bytes=None):
    """Return (rs_succeeded, sha_correct). rs_succeeded is what the DEPLOYED decoder
    can see (RS produced a codeword); sha_correct is our ground-truth check. In a real
    product a CRC in the payload replaces the sha as the acceptance test."""
    try:
        if erase_bytes:
            eb = sorted(set(erase_bytes))
            if len(eb) > meta["nsym"]: return False, False
            d = RSCodec(meta["nsym"]).decode(cw, erase_pos=eb)
        else:
            d = RSCodec(meta["nsym"]).decode(cw)
        return True, hashlib.sha256(bytes(d[0])).hexdigest() == meta["sha"]
    except (ReedSolomonError, Exception):
        return False, False


def separability(P, hard, K):
    """Per-carrier on/off cluster separation (Fisher-like). Higher = more reliable."""
    q = np.full(K, 9.9)
    for c in range(K):
        on = P[:, c][hard[:, c] == 1]; off = P[:, c][hard[:, c] == 0]
        if len(on) >= 2 and len(off) >= 2:
            q[c] = (on.mean() - off.mean()) / (on.std() + off.std() + 1e-9)
        elif len(on) and len(off):
            q[c] = (on.mean() - off.mean()) / (P[:, c].std() + 1e-9)
    return q


def adaptive(cw, q, spans, meta):
    """Escalating ladder: erase the worst-N carriers (by separability), N=0..MAXC,
    accept the FIRST hypothesis whose RS decode self-validates. Returns
    (accepted, sha_correct, n_erased). Monotonic: flat (N=0) is always tried first."""
    order = sorted(range(len(q)), key=lambda c: q[c])      # worst first
    eb = []
    for n in range(0, MAXC + 1):
        if n > 0:
            c = order[n - 1]
            if q[c] >= Q_ERASE: break                       # stop once carriers look fine
            ne = sorted(set(eb) | set(spans[c]))
            if len(ne) > meta["nsym"]: break
            eb = ne
        rs, sha = rs_decode(cw, meta, eb if n else None)
        if rs:
            return True, sha, n
    return False, False, 0


def main():
    print(f"adaptive decode: escalate erasures (worst carriers, separability<{Q_ERASE}), "
          f"accept first RS-valid hypothesis\n")
    print(f"{'idx':>3} {'label':<16} {'K':>2} {'flat':>5} {'adaptive':>9} {'#erased':>8}")
    print("-" * 52)
    nb = na = miscorr = 0
    for i in range(len(frames)):
        e = man[OFF0 + i]; meta = e["meta"]
        m = C.measure_frame(rec, *frames[i], meta)
        m["Nd"] = min(m["Nd"], len(C.truth_grid(e)))
        P = m["P"][:m["Nd"]]; K = m["K"]; spans = carrier_bytes(meta)
        hard = hard_bits(m, meta); cw = to_bytes(hard, meta)
        _, base = rs_decode(cw, meta)                       # flat correctness (sha)
        acc, sha, n = adaptive(cw, q := separability(P, hard, K), spans, meta)
        nb += base; na += sha
        if acc and not sha: miscorr += 1                    # RS said ok but wrong (need CRC)
        flip = "  <== FLIP" if (sha and not base) else ("  RS-miscorrect!" if (acc and not sha) else "")
        print(f"{e['idx']:>3} {e['label']:<16} {K:>2} {'PASS' if base else ' . ':>5} "
              f"{'PASS' if sha else ' . ':>9} {n if n else '-':>8}{flip}")
    print("-" * 52)
    print(f"flat baseline                : {nb}/{len(frames)}")
    print(f"adaptive (decision-directed) : {na}/{len(frames)}   (+{na-nb})")
    if miscorr:
        print(f"NOTE: {miscorr} RS-accepted-but-wrong -> a payload CRC is needed as the "
              f"real acceptance test (RS-success alone can miscorrect)")


if __name__ == "__main__":
    main()
