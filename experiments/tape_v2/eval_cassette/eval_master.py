"""eval_master.py -- build the EVALUATION CASSETTE master (eval_master.wav).

A test tape, NOT a data carrier.  You play it into ANY deck+speaker+mic setup,
capture it, and run eval_decode.py -> a REPORT CARD telling you the highest data
TIER/bitrate that link supports, a channel characterization, and ranked advice.

LAYOUT (m10/bps_push architecture, reused VERBATIM where it matters so
analyze_master2.global_sync_and_resample + analyze_sounder work unchanged):

  1 s lead silence
  global up-chirp (tx_chirp0)                 -- 500->5000 Hz, the speed/clock anchor
  0.40 s gap
  front Schroeder sounder (~45 s)             -- 2x 64-tone probe + 12 s 3 kHz + 3 s sil
  0.40 s gap
  ADDED two-tone IMD probe (~3 s)             -- 1000 + 1300 Hz equal-amp; 3rd-order IMD
  0.40 s gap
  ADDED diffuse-contamination probe (~3 s)    -- 1-bin-spaced multitone; off-tone leakage
  0.40 s gap
  TIER LADDER (8 rungs, robust-floor -> cutting-edge), each ONE long RS-framed
  frame carrying ~256-512 bytes of seeded-random payload (byte-exact = "this tier
  works on your deck"):
    T0 ~329 net   DQPSK P2  N512 sp4  RS224   (sub for WS: lowest robust DQPSK)
    T1 ~540 net   DQPSK P3  N512 sp4  RS245   (sub for BFSK/CAS3 rate)
    T2 ~1100 net  DQPSK P8  N512 sp4  RS187   (sub for MFSK-32)
    T3 ~2572 net  DQPSK P22 N512 sp4  RS159   (the standing 2572 DQPSK record)
    T4 ~3362 net  D2X P18 drop RS127            (DOOM-mini)
    T5 ~4910 net  D2X P21 drop RS159            (DOOM 1.47 MB, PROVEN)
    T6 ~5791 net  r8 D2X P22  RS179             (chess-gpt int4 3.2 MB; the record)
    T7 ~6488 net  8-DPSK csi7 RS173             (chess-gpt + headroom; cutting edge)
  1 s silence
  global down-chirp (tx_chirp1)
  0.40 s gap
  1 s tail silence
  -> peak-normalize the whole mix to 0.70 (SOP).

FRAMING (clean RS(255,k) + CRC32-per-codeword + column-interleave, IDENTICAL to
bps_push_master.encode_rung -- reused verbatim so the decoder is the single
source of truth):  payload = seeded-random bytes (seed per tier, logged);
RS(255,rs_k)-encode each rs_k-byte chunk; CRC32 of each codeword's message;
column-major interleave; ONE long frame per tier (one preamble).

A HARD GATE lives in eval_decode.py --selfcheck: this master MUST self-decode
byte-exact (every tier) with no channel, and the sounder must read sane clean
values.  build() runs its own clean self-check too.

Run:
    python3 eval_master.py [--out eval_master.wav]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import pathlib
import sys
import warnings
import zlib

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
BPS_PUSH = ROOT / "experiments" / "tape_v2" / "bps_push_2026_06_14"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "capacity",
           ROOT / "experiments" / "tape_v2", BPS_PUSH / "harness",
           BPS_PUSH / "candidates", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from reedsolo import RSCodec                                  # noqa: E402
from make_master2 import (                                    # noqa: E402
    GLOBAL_CHIRP_T, _build_sounder, _make_global_chirp, _silence,
)
import evaluate as ev                                         # noqa: E402
from h4_dqpsk import DQPSKScheme                              # noqa: E402
from x10_b_aggr_05_dense2x_master import DROP_P18, DROP_P21   # noqa: E402

SR = 48_000
RS_N = 255

MASTER_ID = "eval_cassette_v1"
WAV_PATH = _HERE / "eval_master.wav"
MANIFEST_PATH = _HERE / "eval_manifest.json"

# Layout constants (m10/bps_push values, verbatim).
LEAD = 1.0
TAIL = 1.0
GAP_S = 0.40
FRAME_GAP_S = 0.12
PEAK = 0.70

# Per-tier deterministic payload seeds (logged; one per tier).
PAYLOAD_SEED_BASE = 20260615

# Added-probe parameters.
IMD_F1_HZ = 1000.0          # two-tone IMD probe, lower tone
IMD_F2_HZ = 1300.0          # two-tone IMD probe, upper tone (300 Hz spacing)
IMD_SECONDS = 3.0
IMD_AMP = 0.60
DIFFUSE_N = 512             # FFT size for the 1-bin-spaced diffuse probe
DIFFUSE_SECONDS = 3.0
DIFFUSE_AMP = 0.55
DIFFUSE_N_TONES = 24        # 1-bin-spaced tones in the strong low-mid band


# ===========================================================================
# Candidate module loader (hyphenated filename -> importlib spec)
# ===========================================================================
def _load_candidate(filename: str, modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, BPS_PUSH / "candidates" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dapsk = _load_candidate("dapsk16-strongmids.py", "dapsk16_strongmids")


# ===========================================================================
# The TIER LADDER -- the single source of truth for both encode + decode.
# Each entry: tier id, target net bps, scheme builder spec, rs_k, payload size,
# the real-payload "enables" label (anchored to payloads/README.md), and notes.
# ===========================================================================
# scheme spec kinds:
#   "dqpsk"        : DQPSKScheme(P,N,spacing) via make_dqpsk_funcscheme (tx=rx)
#   "dense2x_drop" : ev.build_dense2x_candidate(P,rs_k, drop_freqs_hz=...)
#   "dense2x"      : ev.build_dense2x_candidate(P,rs_k)        (full grid, r8 family)
#   "dapsk"        : _dapsk.build(variant)                     (8-DPSK higher-order)
TIERS = [
    {"tier": "T0", "net_target": 330, "kind": "dqpsk",
     "P": 2, "N": 512, "spacing": 4, "rs_k": 224, "payload_bytes": 448,
     "scheme_label": "DQPSK P2 N512 sp4 (substitute for wide-spaced-tone WS)",
     "substituted": True,
     "sub_note": "WS modem not cleanly buildable in repo; lowest robust DQPSK rung "
                 "at the same ~330 net bps with a KNOWN decode path.",
     "enables": "text / mnist 25 KB"},
    {"tier": "T1", "net_target": 540, "kind": "dqpsk",
     "P": 3, "N": 512, "spacing": 4, "rs_k": 245, "payload_bytes": 490,
     "scheme_label": "DQPSK P3 N512 sp4 (substitute for BFSK/CAS3 baseline rate)",
     "substituted": True,
     "sub_note": "BFSK/CAS3 (cassette_format) has no RS(255,k)+CRC32 frame API; "
                 "DQPSK P3 rung matches the ~540 net bps with a KNOWN decode path.",
     "enables": "delphi-llama2-100k 147 KB"},
    {"tier": "T2", "net_target": 1100, "kind": "dqpsk",
     "P": 8, "N": 512, "spacing": 4, "rs_k": 187, "payload_bytes": 374,
     "scheme_label": "DQPSK P8 N512 sp4 (substitute for MFSK-32)",
     "substituted": True,
     "sub_note": "MFSK-32 builder not in this campaign's DSP set; DQPSK P8 rung at "
                 "the same ~1100 net bps with a KNOWN decode path.",
     "enables": "stories260K int4 150 KB"},
    {"tier": "T3", "net_target": 2572, "kind": "dqpsk",
     "P": 22, "N": 512, "spacing": 4, "rs_k": 159, "payload_bytes": 318,
     "scheme_label": "DQPSK P22 N512 sp4 (the standing 2572 DQPSK record, m10 r0)",
     "substituted": False,
     "enables": "stories260K FP32 1.07 MB"},
    {"tier": "T4", "net_target": 3362, "kind": "dense2x_drop",
     "P": 18, "drop": "DROP_P18", "rs_k": 127, "payload_bytes": 381,
     "scheme_label": "D2X P18 drop RS127 (m10 r5, Dense2xDropScheme)",
     "substituted": False,
     "enables": "DOOM-mini"},
    {"tier": "T5", "net_target": 4910, "kind": "dense2x_drop",
     "P": 21, "drop": "DROP_P21", "rs_k": 159, "payload_bytes": 477,
     "scheme_label": "D2X P21 drop RS159 (m10 r6, DOOM tape, PROVEN byte-exact)",
     "substituted": False,
     "enables": "DOOM 1.47 MB | chess-gpt int4 borderline | all TinyStories"},
    {"tier": "T6", "net_target": 5791, "kind": "dense2x",
     "P": 22, "rs_k": 179, "payload_bytes": 358,
     "scheme_label": "r8 D2X P22 RS179 (the standing 5791 bps record)",
     "substituted": False,
     "enables": "chess-gpt int4 3.2 MB"},
    {"tier": "T7", "net_target": 6488, "kind": "dapsk",
     "variant": "e", "rs_k": 173, "payload_bytes": 346,
     "scheme_label": "8-DPSK csi7 RS173 (dapsk16 variant e; bulk + higher-order)",
     "substituted": False,
     "enables": "chess-gpt int4 3.2 MB + headroom"},
]


# ===========================================================================
# Uniform tier-scheme builder.  Returns a hyp_common FuncScheme with rs_k
# attached.  The decoder builds the SAME object from the manifest's spec, so
# this mapping is the single source of truth for both encode and decode.
# ===========================================================================
def build_tier_scheme(tier: dict):
    kind = tier["kind"]
    rs_k = int(tier["rs_k"])
    if kind == "dqpsk":
        tx = DQPSKScheme(tier["P"], tier["N"], tier["spacing"], min_spacing_hz=375.0)
        rx = DQPSKScheme(tier["P"], tier["N"], tier["spacing"], min_spacing_hz=375.0)
        fs = ev.make_dqpsk_funcscheme(
            tx, rx, name=f"{tier['tier']}_DQ_P{tier['P']}_N{tier['N']}_sp{tier['spacing']}",
            rs_k=rs_k)
    elif kind == "dense2x_drop":
        drop = {"DROP_P18": DROP_P18, "DROP_P21": DROP_P21}[tier["drop"]]
        fs = ev.build_dense2x_candidate(tier["P"], rs_k, drop_freqs_hz=drop,
                                        name=f"{tier['tier']}_D2Xdrop_P{tier['P']}")
    elif kind == "dense2x":
        fs = ev.build_dense2x_candidate(tier["P"], rs_k,
                                        name=f"{tier['tier']}_D2X_P{tier['P']}")
    elif kind == "dapsk":
        fs = _dapsk.build(tier["variant"])
        fs.rs_k = rs_k
    else:
        raise ValueError(f"unknown tier kind {kind!r}")
    fs.rs_k = int(rs_k)
    return fs


def _bits_per_sym(fs) -> int:
    """The tx scheme's bits/symbol -- needed to size nd for self-syncing demods.
    DQPSK adapter -> fs.tx_scheme; dense2x adapter -> fs.tx_scheme; dapsk -> fs._scheme."""
    sc = (getattr(fs, "tx_scheme", None) or getattr(fs, "_scheme", None)
          or getattr(fs, "rx_scheme", None))
    return int(sc.bits_per_sym)


def _preamble_seconds(fs) -> float:
    sc = (getattr(fs, "tx_scheme", None) or getattr(fs, "_scheme", None)
          or getattr(fs, "rx_scheme", None))
    return float(getattr(sc, "preamble_seconds", 0.25))


# ===========================================================================
# RS(255,k) + CRC32-per-codeword + column-interleave framing
# (byte-identical to bps_push_master.encode_rung; reproduced here so the eval
#  master is self-contained, and asserted equivalent in build()).
# ===========================================================================
def encode_tier(message: bytes, rs_k: int):
    """message len MUST be a multiple of rs_k.  Returns (coded_bits uint8,
    crc32_codewords list, meta)."""
    message = bytes(message)
    assert len(message) % rs_k == 0, (len(message), rs_k)
    rsc = RSCodec(RS_N - rs_k)
    n_cw = len(message) // rs_k

    crc32_codewords, cw_list = [], []
    for i in range(n_cw):
        chunk = message[i * rs_k:(i + 1) * rs_k]
        crc32_codewords.append(zlib.crc32(chunk) & 0xFFFFFFFF)
        cw_list.append(bytes(rsc.encode(chunk)))

    mat = np.frombuffer(b"".join(cw_list), np.uint8).reshape(n_cw, RS_N)
    tx_bytes = mat.T.reshape(-1)                       # column-major interleave
    coded_bits = np.unpackbits(tx_bytes).astype(np.uint8)

    meta = {"rs_n": RS_N, "rs_k": int(rs_k), "n_codewords": int(n_cw),
            "message_len": len(message), "coded_bits": int(len(coded_bits))}
    return coded_bits, crc32_codewords, meta


def _round_payload_to_rs(payload_bytes: int, rs_k: int) -> int:
    """Round the requested payload size up to the nearest multiple of rs_k
    (>= 1 codeword) so RS framing is exact."""
    n_cw = max(1, int(round(payload_bytes / rs_k)))
    return n_cw * rs_k


# ===========================================================================
# Added characterization probes (IMD + diffuse contamination)
# ===========================================================================
def _make_imd_probe() -> tuple[np.ndarray, dict]:
    """Two equal-amplitude tones (f1+f2).  Decoder measures the 3rd-order
    intermod products (2*f1-f2, 2*f2-f1) below the carriers -> saturation flag."""
    n = int(IMD_SECONDS * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * IMD_F1_HZ * t) + np.sin(2 * np.pi * IMD_F2_HZ * t)
    x /= np.max(np.abs(x)) + 1e-9
    fade = int(0.02 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    info = {
        "f1_hz": IMD_F1_HZ, "f2_hz": IMD_F2_HZ,
        "imd3_lo_hz": 2 * IMD_F1_HZ - IMD_F2_HZ,   # 700 Hz
        "imd3_hi_hz": 2 * IMD_F2_HZ - IMD_F1_HZ,   # 1600 Hz
    }
    return (IMD_AMP * x).astype(np.float32), info


def _make_diffuse_probe() -> tuple[np.ndarray, dict]:
    """A 1-bin-spaced multitone (adjacent FFT bins of N=512, in the strong
    low-mid band).  Decoder measures off-tone leakage fraction -> reverb/room
    diffuse floor (caps acoustic setups).  Mirrors spectral_contamination."""
    df = SR / DIFFUSE_N
    bin0 = int(round(1500.0 / df))             # ~1500 Hz start, strong band
    bins = bin0 + np.arange(DIFFUSE_N_TONES)   # 1-bin spacing (adjacent bins)
    freqs = bins * df
    n = int(DIFFUSE_SECONDS * SR)
    t = np.arange(n) / SR
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):              # Schroeder low-PAPR phasing
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    fade = int(0.02 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    info = {
        "N": DIFFUSE_N, "df_hz": df,
        "tone_bins": [int(b) for b in bins],
        "tone_freqs_hz": [round(float(f), 2) for f in freqs],
    }
    return (DIFFUSE_AMP * x).astype(np.float32), info


# ===========================================================================
def build(out_wav: pathlib.Path = WAV_PATH) -> str:
    parts: list[np.ndarray] = []
    pos = 0

    def add_raw(sig: np.ndarray) -> None:
        nonlocal pos
        sig = np.asarray(sig, dtype=np.float32)
        parts.append(sig)
        pos += len(sig)

    def add_gap(d: float = GAP_S) -> None:
        add_raw(_silence(d))

    manifest: dict = {
        "master_id": MASTER_ID,
        "product": "evaluation_cassette_v1",
        "SR": SR,
        "tx_chirp0": None,
        "tx_chirp1": None,
        "sounder_sections": [],
        "probe_sections": {},
        "global_chirp": {"T": GLOBAL_CHIRP_T, "f0": 500.0, "f1": 5000.0},
        "frame_gap_samples": int(FRAME_GAP_S * SR),
        "payload_seed_base": PAYLOAD_SEED_BASE,
        "tiers": [],
        "note": ("Evaluation cassette: carries NO useful payload. Each tier carries "
                 "seeded-random bytes; a byte-exact tier decode means 'this link "
                 "supports this tier'. 10 MB+ capacity tiers exist (electrical / "
                 "stereo) but have no curated payload yet -- flagged as a gap, not "
                 "shipped here."),
    }

    # ---- lead + global up-chirp ----
    add_raw(_silence(LEAD))
    manifest["tx_chirp0"] = pos
    add_raw(_make_global_chirp(up=True))
    add_gap()

    # ---- front Schroeder sounder (verbatim from make_master2) ----
    sounder_audio, sounder_sections = _build_sounder()
    sounder_start = pos
    for section in sounder_sections:
        section["start"] += sounder_start
    manifest["sounder_sections"] = sounder_sections
    add_raw(sounder_audio)
    add_gap()

    # ---- ADDED two-tone IMD probe ----
    imd_audio, imd_info = _make_imd_probe()
    imd_start = pos
    add_raw(imd_audio)
    manifest["probe_sections"]["imd"] = {
        "kind": "imd_twotone", "start": int(imd_start), "length": int(len(imd_audio)),
        "info": imd_info}
    add_gap()

    # ---- ADDED diffuse-contamination probe ----
    diff_audio, diff_info = _make_diffuse_probe()
    diff_start = pos
    add_raw(diff_audio)
    manifest["probe_sections"]["diffuse"] = {
        "kind": "diffuse_multitone", "start": int(diff_start),
        "length": int(len(diff_audio)), "info": diff_info}
    add_gap()

    # ---- TIER LADDER ----
    print(f"[build] master_id={MASTER_ID}  ({len(TIERS)} tiers)")
    print(f"[build] {'tier':5s} {'scheme':40s} {'rsk':>4} {'cw':>3} {'msgB':>5} "
          f"{'gross':>7} {'net':>7} {'sec':>6} {'sub':>4}")
    for ti, tier in enumerate(TIERS):
        rs_k = int(tier["rs_k"])
        seed = PAYLOAD_SEED_BASE + ti

        fs = build_tier_scheme(tier)
        bits_per_sym = _bits_per_sym(fs)

        # payload sizing: round to a whole number of rs_k-byte codewords.
        message_bytes = _round_payload_to_rs(int(tier["payload_bytes"]), rs_k)
        n_cw = message_bytes // rs_k
        rng = np.random.default_rng(seed)
        payload = rng.integers(0, 256, size=message_bytes, dtype=np.uint8).tobytes()

        # encode -> coded interleaved bits + per-codeword CRC32
        coded_bits, crc32_cw, _ = encode_tier(payload, rs_k)

        # modulate ONE long frame (one preamble).  dense2x adapter needs _nbits.
        mod_ref = getattr(fs, "_modulate_ref", None)
        if mod_ref is not None:
            mod_ref._nbits = len(coded_bits)
        frame_start = pos
        audio = np.asarray(fs.modulate(coded_bits), dtype=np.float32)
        body_end = frame_start + len(audio)
        add_raw(audio)
        add_raw(_silence(FRAME_GAP_S))
        seg_end = pos
        add_gap()

        nd = int(math.ceil(len(coded_bits) / bits_per_sym))
        gross = float(fs.gross_bps)
        net = gross * rs_k / RS_N
        sec_s = (seg_end - frame_start) / SR

        entry = {
            "tier": tier["tier"],
            "name": fs.name,
            "kind": tier["kind"],
            "scheme_label": tier["scheme_label"],
            "scheme_spec": {k: tier[k] for k in
                            ("kind", "P", "N", "spacing", "drop", "variant")
                            if k in tier},
            "substituted": bool(tier.get("substituted", False)),
            "sub_note": tier.get("sub_note", ""),
            "enables": tier["enables"],
            "net_target_bps": tier["net_target"],
            "rs_k": rs_k,
            "rs_n": RS_N,
            "n_codewords": n_cw,
            "message_bytes": message_bytes,
            "coded_bits": int(len(coded_bits)),
            "bits_per_sym": bits_per_sym,
            "n_data_symbols": nd,
            "gross_bps": gross,
            "projected_net_bps": net,
            "payload_seed": seed,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "crc32_codewords": crc32_cw,
            "segment_start_sample": int(frame_start),
            "body_end_sample": int(body_end),
            "body_samples": int(len(audio)),
            "segment_end_sample": int(seg_end),
            "frame_starts": [int(frame_start)],
            "preamble_seconds": _preamble_seconds(fs),
        }
        manifest["tiers"].append(entry)
        sub = "SUB" if entry["substituted"] else ""
        print(f"[build] {tier['tier']:5s} {fs.name:40s} {rs_k:>4} {n_cw:>3} "
              f"{message_bytes:>5} {gross:>7.0f} {net:>7.0f} {sec_s:>5.1f}s {sub:>4}")

    # ---- global down-chirp + tail (>=1 s silence around end chirp per SOP) ----
    add_raw(_silence(1.0))
    manifest["tx_chirp1"] = pos
    add_raw(_make_global_chirp(up=False))
    add_gap()
    add_raw(_silence(TAIL))

    audio_full = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio_full)))
    if peak > 1e-9:
        audio_full = (audio_full / peak * PEAK).astype(np.float32)
    dur_s = len(audio_full) / SR

    manifest["duration_seconds"] = dur_s

    sf.write(str(out_wav), audio_full, SR, subtype="FLOAT")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    print(f"\n[build] {out_wav} {dur_s:.1f}s ({dur_s/60:.2f} min), peak {PEAK}")
    print(f"[build] manifest -> {MANIFEST_PATH} (master_id={MASTER_ID})")
    return (f"{out_wav.name} {dur_s:.1f}s ({dur_s/60:.2f} min), "
            f"{len(manifest['tiers'])} tiers")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    print(build(pathlib.Path(args.out)))
