"""m2_modem_survival.py — map which modem configs survive the REAL master2 channel.

Applies the m3_decode_v2 HARDENED demod approach (FFT-bin energy detection +
sounder-H(f) per-tone EQ + wide-window energy-concentration timing tracker) and a
GENIE ceiling to each FSK / combinatorial config present on the master2 ladder:
  mfsk32, c1_gray_m16, c2_m32_k2, c2_m32_k4, c2_m48_k6.

master2 sections are SELF-CONTAINED slices (0.25 s chirp preamble inside the slice,
payload wrapped in the canonical CRC frame). Ground-truth bits come from each
modem module's tx_bits(). We measure, per config, over many ladder reps:
  - N (samples/symbol)
  - raw BER (hardened tracked demod)
  - genie-ceiling BER (oracle symbol + best per-symbol timing within +/-track + EQ)
  - whether a robust RS (rate ~0.5, corrects ~25% symbols) would close it byte-exact

The hardened demod here is a single generic detector parameterised by each scheme's
tone bins / M / K, so it covers single-tone MFSK (K=1, optional gray map) and the
K-of-M combinatorial PHY uniformly.
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import correlate, resample_poly

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
_HERE = ROOT / "experiments" / "tape_v2"
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                       # noqa: E402
import analyze_master2 as am2                 # noqa: E402
import modems_index as mi                     # noqa: E402
import modems_combo as mc                     # noqa: E402
from hyp_h2_mfsk import MFSKScheme            # noqa: E402
from c1_gray_mfsk import GrayMFSKScheme       # noqa: E402
from c2_combo_mfsk import ComboMFSKScheme     # noqa: E402

SR = 48_000
MANIFEST_PATH = _HERE / "master2_manifest.json"
RESULTS_DIR = _HERE / "results"
PREAMBLE_SECONDS = 0.25
WINDOW_PAD = 0.30
TRACK = 15                 # +/- sample search window per symbol
CENTER_BIAS = 0.02
REPS_PER_CONFIG = 24       # reps to average per config (statistical stability)


# ---------------------------------------------------------------------------
# Per-config descriptor: scheme + bit<->symbol mapping + tx-bit ground truth
# ---------------------------------------------------------------------------
class ConfigSpec:
    def __init__(self, name):
        self.name = name
        if name == "mfsk32":
            self.scheme = MFSKScheme(M=32, walsh_k=0)
            self.kind = "mfsk"; self.M = 32; self.K = 1
            self.module = mi
        elif name == "c1_gray_m16":
            self.scheme = GrayMFSKScheme(M=16, bw_low=400.0, bw_high=7000.0, tsym_mult=1.0)
            self.kind = "gray"; self.M = 16; self.K = 1
            self.module = mi
            self.gray_inv = self.scheme._gray_inv  # tone-index -> data symbol
        else:
            M, K = {"c2_m32_k2": (32, 2), "c2_m32_k4": (32, 4),
                    "c2_m48_k6": (48, 6)}[name]
            self.scheme = ComboMFSKScheme(M=M, K=K, preamble_seconds=PREAMBLE_SECONDS)
            self.kind = "combo"; self.M = M; self.K = K
            self.module = mc
        s = self.scheme
        self.N = s.samples_per_sym
        self.bps = s.bits_per_sym
        self.freqs = np.asarray(s.freqs, dtype=np.float64)
        self.bins = np.clip(
            np.round(self.freqs * self.N / SR).astype(int), 0, self.N // 2)
        self.pre = np.asarray(hc.make_preamble(PREAMBLE_SECONDS), dtype=np.float64)
        if self.kind == "combo":
            self.rev = s._rev_table
            self.cap = s._sym_cap

    # --- ground truth bits for a (config, rep) section ---
    def tx_bits_for(self, rep):
        payload = _make_payload(self.name, rep)
        return np.asarray(self.module.tx_bits(payload, self.name), dtype=np.uint8)

    # --- detected energies (over M tone bins) -> symbol index (in bit space) ---
    def sym_from_energies(self, e_eq):
        if self.kind == "combo":
            tk = tuple(sorted(np.argpartition(e_eq, -self.K)[-self.K:].tolist()))
            return min(self.rev.get(tk, 0), self.cap - 1)
        tone = int(np.argmax(e_eq))
        if self.kind == "gray":
            return int(self.gray_inv[tone])     # tone -> data symbol
        return tone                              # plain MFSK: tone == symbol

    def sym_to_bits(self, si):
        return [(si >> (self.bps - 1 - j)) & 1 for j in range(self.bps)]

    # --- concentration lock score (carries timing info, coloration-robust) ---
    def lock(self, e_eq):
        srt = np.sort(e_eq)[::-1]
        return float((srt[self.K - 1] - srt[self.K]) / (srt[0] + 1e-9))


# payload builder — must match make_master2._make_payload exactly
_QUOTE = "The quick cassette plays on. "
_PAD_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _make_payload(config: str, rep: int) -> bytes:
    prefix = f"CASSETTE-AI v2 | {config} rep{rep:03d} | "
    filler = (_QUOTE + _PAD_CHARS) * 4
    raw = (prefix + filler)[:96]
    raw = raw.ljust(96)[:96]
    return raw.encode("ascii")


# ---------------------------------------------------------------------------
# Hardened tracked demod over one section window
# ---------------------------------------------------------------------------
def _energies(win, p, N, bins):
    seg = win[p:p + N]
    if len(seg) < N:
        if len(seg) < N // 2:
            return None
        seg = np.concatenate([seg, np.zeros(N - len(seg))])
    return np.abs(np.fft.rfft(seg, n=N))[bins]


def _demod_section(spec: ConfigSpec, win, nsym, eq, track=TRACK, genie_syms=None):
    """Tracked sweep. If genie_syms given, prefer offsets that decode the known
    symbol (oracle-timed ceiling). Returns recovered symbol-index list."""
    win = np.asarray(win, dtype=np.float64)
    c = np.abs(correlate(win, spec.pre, mode="valid"))
    dstart = int(np.argmax(c)) + len(spec.pre)
    N, bins = spec.N, spec.bins
    drift = 0.0
    out = []
    for s in range(nsym):
        base = dstart + s * N + int(round(drift))
        best = None       # (score, d, sym)
        fb_sym = None
        for d in range(-track, track + 1):
            e = _energies(win, base + d, N, bins)
            if e is None:
                continue
            e_eq = e / eq
            si = spec.sym_from_energies(e_eq)
            if fb_sym is None:
                fb_sym = si
            if genie_syms is not None:
                if si == genie_syms[s] and (best is None or abs(d) < best[0]):
                    best = (abs(d), d, si)
            else:
                lock = spec.lock(e_eq) * (1.0 - CENTER_BIAS * abs(d))
                if best is None or lock > best[0]:
                    best = (lock, d, si)
        if best is None:
            out.append(fb_sym if fb_sym is not None else 0)
            continue
        drift = drift + best[1]
        out.append(best[2])
    return out


def _eq_from_sounder(freqs, sounder):
    sf_freqs = np.asarray(sounder.get("sounder_freqs", []), dtype=np.float64)
    H_db = np.asarray(sounder.get("H_db", []), dtype=np.float64)
    if len(sf_freqs) < 2:
        return np.ones(len(freqs))
    Hlin = 10.0 ** (np.interp(freqs, sf_freqs, H_db) / 20.0)
    Hlin = Hlin / (Hlin.max() + 1e-12)
    return np.clip(Hlin, 1e-3, None)


def _syms_to_bits(spec, syms, nbits):
    bits = []
    for si in syms:
        bits.extend(spec.sym_to_bits(si))
    return np.array(bits[:nbits], dtype=np.uint8)


# ---------------------------------------------------------------------------
# Per-config evaluation over many reps
# ---------------------------------------------------------------------------
def eval_config(spec, audio_nom, manifest, align, sounder, reps_to_use):
    eq = _eq_from_sounder(spec.freqs, sounder)
    secs = [s for s in manifest["sections"] if s["config"] == spec.name]
    secs = sorted(secs, key=lambda s: s["rep"])[:reps_to_use]
    pad = int(WINDOW_PAD * SR)
    raw_err = raw_tot = gen_err = 0
    raw_byte_err = gen_byte_err = byte_tot = 0
    n_sec = 0
    for sec in secs:
        rep = sec["rep"]
        tb = spec.tx_bits_for(rep)
        nbits = len(tb)
        nsym = int(np.ceil(nbits / spec.bps))
        st = sec["start_sample"] + align
        flen = sec["length"]
        w_lo = max(0, st - pad)
        w_hi = min(len(audio_nom), st + flen + pad)
        win = audio_nom[w_lo:w_hi]
        if len(win) < spec.N * 4:
            continue
        nbytes = nbits // 8
        tb_bytes = np.packbits(tb[:nbytes * 8]) if nbytes else np.zeros(0, np.uint8)
        # raw tracked
        syms = _demod_section(spec, win, nsym, eq)
        rb = _syms_to_bits(spec, syms, nbits)
        m = min(len(tb), len(rb))
        raw_err += int(np.count_nonzero(tb[:m] != rb[:m])) + (nbits - m)
        rb_bytes = np.packbits(rb[:nbytes * 8]) if nbytes else np.zeros(0, np.uint8)
        raw_byte_err += int(np.count_nonzero(tb_bytes != rb_bytes))
        # genie: known symbol indices
        gt_syms = [int("".join(map(str, tb[i * spec.bps:(i + 1) * spec.bps])), 2)
                   for i in range(nsym) if (i + 1) * spec.bps <= nbits]
        # pad last partial
        while len(gt_syms) < nsym:
            gt_syms.append(0)
        gsyms = _demod_section(spec, win, nsym, eq, genie_syms=gt_syms)
        gb = _syms_to_bits(spec, gsyms, nbits)
        gm = min(len(tb), len(gb))
        gen_err += int(np.count_nonzero(tb[:gm] != gb[:gm])) + (nbits - gm)
        gb_bytes = np.packbits(gb[:nbytes * 8]) if nbytes else np.zeros(0, np.uint8)
        gen_byte_err += int(np.count_nonzero(tb_bytes != gb_bytes))
        raw_tot += nbits
        byte_tot += nbytes
        n_sec += 1
    raw_ber = raw_err / max(1, raw_tot)
    gen_ber = gen_err / max(1, raw_tot)
    raw_byte_er = raw_byte_err / max(1, byte_tot)
    gen_byte_er = gen_byte_err / max(1, byte_tot)
    # RS-closability: a robust interleaved RS(255,127) (rate 0.498) corrects up to
    # t=64 byte errors per 255-byte codeword -> ~0.251 byte-error fraction. With
    # deep interleave the BYTE-error rate is the RS input; closable if it sits
    # comfortably (margin) under that ceiling. The controlling number is the
    # byte-error rate an ACHIEVABLE decoder produces (raw), but we also report the
    # genie ceiling -- if even genie's byte-error rate exceeds ~0.25 the config is
    # un-closable by ANY tracker at this RS rate.
    raw_closable = bool(raw_byte_er < 0.18)            # margin under 0.251
    gen_closable = bool(gen_byte_er < 0.18)
    return {
        "config": spec.name, "N_samples": int(spec.N),
        "M": spec.M, "K": spec.K, "bps": spec.bps,
        "bin_hz": round(SR / spec.N, 1),
        "n_sections": n_sec,
        "raw_ber": round(raw_ber, 4),
        "genie_ber": round(gen_ber, 4),
        "raw_byte_err_rate": round(raw_byte_er, 4),
        "genie_byte_err_rate": round(gen_byte_er, 4),
        # rs_closable reports whether a robust RS(255,127) closes it for an
        # ACHIEVABLE (raw) decoder; genie_rs_closable is the ceiling.
        "rs_closable": raw_closable,
        "genie_rs_closable": gen_closable,
    }


def main():
    rec = _HERE / "captures" / "voicememo_run1.wav"
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(str(rec), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    print(f"[sync] loaded {len(audio)} samples ({len(audio)/SR:.1f}s) @ {SR}")
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    print(f"[sync] speed {sync['speed']:.4f}x align {align:+d} "
          f"(chirp0_nom {sync['chirp0_nominal']})")
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync)
        print(f"[sounder] flutter {sounder.get('flutter_wrms_pct')}% "
              f"SNRmed {sounder.get('snr_db_median')}dB "
              f"nf {sounder.get('noise_floor_dbfs')}dBFS")
    except Exception as e:
        print("[sounder] ERROR", e)
        sounder = {}

    configs = ["mfsk32", "c1_gray_m16", "c2_m32_k2", "c2_m32_k4", "c2_m48_k6"]
    results = []
    for name in configs:
        spec = ConfigSpec(name)
        r = eval_config(spec, audio_nom, manifest, align, sounder, REPS_PER_CONFIG)
        results.append(r)
        print(f"  {name:14} N={r['N_samples']:3d} binHz={r['bin_hz']:6.1f} "
              f"M={r['M']} K={r['K']} secs={r['n_sections']:2d} "
              f"rawBER={r['raw_ber']:.3f} genieBER={r['genie_ber']:.3f} "
              f"rawByteER={r['raw_byte_err_rate']:.3f} "
              f"genieByteER={r['genie_byte_err_rate']:.3f} "
              f"RSclose={r['rs_closable']} genieRSclose={r['genie_rs_closable']}")

    # longer-symbol probe: does even-longer symbol help? compare N ordering
    by_n = sorted(results, key=lambda r: r["N_samples"])
    m16 = next((r for r in results if r["config"] == "c1_gray_m16"), None)
    m32k2 = next((r for r in results if r["config"] == "c2_m32_k2"), None)
    # "markedly better" = genie BER clearly lower AND genie byte-error rate clearly
    # lower (closer to RS-closable) than M16. This is the honest re-tier validation.
    m32_validated = bool(
        m32k2 and m16 and
        m32k2["genie_ber"] < m16["genie_ber"] - 0.02 and
        m32k2["genie_byte_err_rate"] < m16["genie_byte_err_rate"] - 0.05 and
        m32k2["genie_rs_closable"])

    out = {
        "recording": str(rec),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {k: v for k, v in sounder.items()
                    if k not in ("H_db", "snr_db_per_tone", "sounder_freqs")},
        "reps_per_config": REPS_PER_CONFIG,
        "track": TRACK,
        "configs": results,
        "longer_symbol_ordering": [(r["config"], r["N_samples"], r["genie_ber"])
                                   for r in by_n],
        "m32_validated_vs_m16": m32_validated,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    outp = RESULTS_DIR / "real_modem_survival.json"
    outp.write_text(json.dumps(out, indent=2, default=float))
    print(f"[done] wrote {outp}")
    print(f"[done] m32_validated_vs_m16 = {m32_validated}")
    return out


if __name__ == "__main__":
    main()
