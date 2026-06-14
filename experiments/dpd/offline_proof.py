"""Offline proof of the DPD/channel-model thesis on the EXISTING recording.

Thesis: model the cassette->speaker->mic channel from the known signal, then
correct for it. We test the RECEIVER-side half that the existing recording can
prove non-circularly:

  A channel-aware decoder estimates per-carrier quality *blind* (no ground truth,
  only the received bimodal on/off energy separation), flags the worst carriers
  as ERASURES, and uses Reed-Solomon erasure decoding (corrects 2x as many
  erasures as errors). If configs that FAIL under the flat decoder become
  byte-exact, the loss was a correctable, structured channel effect.

Baseline = the modem's own threshold decode.  Channel-aware = same soft
energies + blind erasure flagging + RS erasure decode.
"""
import numpy as np
import chan_lib as C
from reedsolo import RSCodec, ReedSolomonError

rec = C.load_rec(); man = C.load_manifest(); frames = C.segment_frames(rec)
OFF0 = 3   # verified by [NN]-prefix matching (39/50 frames, 7 RS-pass)
THR = C.mod.THR


def soft_decode(m, meta):
    """Return measured soft energies P (Nd,K), per-chunk gains G, hard bits, and a
    BLIND per-carrier quality score (on/off separability, no ground truth)."""
    K = m["K"]; Nd = m["Nd"]; chunk = meta["chunk"]; G = m["G"]; P = m["P"][:Nd]
    # hard decision exactly like the modem: P > THR * g(chunk-start marker)
    hard = np.zeros((Nd, K), np.uint8); di = 0
    for j in range(len(G) - 1):
        g = np.maximum(G[j], 1e-9)
        for k in range(chunk):
            if di >= Nd: break
            hard[di] = (P[di] > THR * g[None, :]).astype(np.uint8)[0] if False else (P[di] > THR * g).astype(np.uint8)
            di += 1
    # BLIND quality per carrier: split each carrier's energies by the hard decision,
    # quality = (mean_on - mean_off) / (std_on + std_off + eps)  (Fisher-like ratio)
    q = np.full(K, np.inf)
    for c in range(K):
        col = P[:, c]; on = col[hard[:, c] == 1]; off = col[hard[:, c] == 0]
        if len(on) >= 2 and len(off) >= 2:
            q[c] = (on.mean() - off.mean()) / (on.std() + off.std() + 1e-9)
        elif len(on) and len(off):
            q[c] = (on.mean() - off.mean()) / (col.std() + 1e-9)
    return P, hard, q


def carrier_byte_spans(meta):
    """Map each carrier -> the byte indices it (mostly) owns, from the carrier-major
    interleave used by the modem (bit linear index = c*Nd + s)."""
    K = meta["K"]; Nd = meta["ndata_sym"]; nbytes = meta["nbytes"]
    spans = []
    for c in range(K):
        lo, hi = c * Nd, (c + 1) * Nd - 1          # linear bit indices owned by carrier c
        b0, b1 = lo // 8, hi // 8
        spans.append([b for b in range(b0, min(b1, nbytes - 1) + 1)])
    return spans


def bits_to_bytes(hard, meta):
    K = meta["K"]; Nd = meta["ndata_sym"]; nbytes = meta["nbytes"]
    linear = hard[:Nd].T.reshape(-1)[:nbytes * 8]
    return np.packbits(linear).tobytes()[:nbytes]


def rs_try(cw, meta, erase_pos=None):
    nsym = meta["nsym"]
    try:
        if erase_pos:
            dec = RSCodec(nsym).decode(cw, erase_pos=list(erase_pos))
        else:
            dec = RSCodec(nsym).decode(cw)
        data = bytes(dec[0])
        import hashlib
        return hashlib.sha256(data).hexdigest() == meta["sha"], data
    except (ReedSolomonError, Exception):
        return False, None


def run(idx, nerase_grid=(0, 1, 2, 3, 4, 5, 6)):
    e = man[idx]; meta = e["meta"]; i = idx - OFF0
    t0, t1 = frames[i]
    m = C.measure_frame(rec, t0, t1, meta)
    Nd = min(m["Nd"], len(C.truth_grid(e)))
    m["Nd"] = Nd
    P, hard, q = soft_decode(m, meta)
    spans = carrier_byte_spans(meta)
    cw = bits_to_bytes(hard, meta)
    base_ok, _ = rs_try(cw, meta)                 # baseline: modem-equivalent decode
    order = np.argsort(q)                          # worst carriers first
    best = (base_ok, 0)
    flips = None
    for ne in nerase_grid:
        if ne == 0:
            ok = base_ok
        else:
            erase_bytes = sorted(set(b for c in order[:ne] for b in spans[c]))
            if len(erase_bytes) > meta["nsym"]:    # can't erase more than parity symbols
                continue
            ok, _ = rs_try(cw, meta, erase_pos=erase_bytes)
        if ok and flips is None:
            flips = ne
    return dict(idx=idx, label=e["label"], K=meta["K"], base_ok=base_ok,
                aware_ok=(flips is not None), nerase=flips, qsort=q[order][:6])


if __name__ == "__main__":
    # all configs that the batch captured and that align (off0=3 -> idx 3..52, but only 50 frames)
    idxs = [man[OFF0 + i]["idx"] for i in range(len(frames))]
    rows = [run(idx) for idx in idxs]
    print(f"{'idx':>3} {'label':<16} {'K':>2} {'baseline':>9} {'chan-aware':>11} {'erased':>7}")
    print("-" * 56)
    nb = na = 0
    for r in rows:
        if r["base_ok"]: nb += 1
        if r["aware_ok"]: na += 1
        flip = "  <== FLIP" if (r["aware_ok"] and not r["base_ok"]) else ""
        print(f"{r['idx']:>3} {r['label']:<16} {r['K']:>2} "
              f"{'PASS' if r['base_ok'] else 'fail':>9} "
              f"{'PASS' if r['aware_ok'] else 'fail':>11} "
              f"{str(r['nerase']) if r['nerase'] else '-':>7}{flip}")
    print("-" * 56)
    print(f"baseline (flat decode):       {nb}/{len(rows)} byte-exact")
    print(f"channel-aware erasure decode: {na}/{len(rows)} byte-exact   (+{na-nb})")
