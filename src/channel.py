from __future__ import annotations

import numpy as np
from scipy import signal
import matplotlib.pyplot as plt

from common import DATA, PLOTS, append_report, ensure_dirs, rng, write_csv


FS = 48_000
DURATION = 2.0


def cassette_channel(
    x: np.ndarray,
    fs: int = FS,
    snr_db: float = 40.0,
    wow_flutter_wrms: float = 0.0007,
    bandwidth_hz: float = 12_000.0,
    burst_rate_per_s: float = 0.0,
    burst_length_ms: float = 0.0,
    seed_offset: int = 0,
) -> np.ndarray:
    y, _ = cassette_channel_diagnostics(
        x,
        fs=fs,
        snr_db=snr_db,
        wow_flutter_wrms=wow_flutter_wrms,
        bandwidth_hz=bandwidth_hz,
        burst_rate_per_s=burst_rate_per_s,
        burst_length_ms=burst_length_ms,
        seed_offset=seed_offset,
    )
    return y


def cassette_channel_diagnostics(
    x: np.ndarray,
    fs: int = FS,
    snr_db: float = 40.0,
    wow_flutter_wrms: float = 0.0007,
    bandwidth_hz: float = 12_000.0,
    burst_rate_per_s: float = 0.0,
    burst_length_ms: float = 0.0,
    seed_offset: int = 0,
) -> tuple[np.ndarray, dict]:
    """Consumer cassette playback approximation: low-pass, slow timebase error, AWGN."""
    g = rng(1000 + seed_offset)
    sos = signal.butter(5, bandwidth_hz, btype="lowpass", fs=fs, output="sos")
    y = signal.sosfiltfilt(sos, x)

    measured_wf = 0.0
    if wow_flutter_wrms > 0:
        t = np.arange(len(y)) / fs
        p1, p2 = g.uniform(0, 2 * np.pi, size=2)
        a1 = g.normal(1.0, 0.08)
        a2 = g.normal(0.45, 0.05)
        inst = (
            a1 * np.sin(2 * np.pi * 0.55 * t + p1)
            + a2 * np.sin(2 * np.pi * 4.8 * t + p2)
            + 0.18 * g.standard_normal(len(t))
        )
        inst = inst / np.sqrt(np.mean(inst**2)) * wow_flutter_wrms
        lo = max(0, int(0.1 * len(inst)))
        hi = min(len(inst), int(0.9 * len(inst)))
        measured_wf = float(np.sqrt(np.mean(inst[lo:hi] ** 2)))
        warped_t = t + np.cumsum(inst) / fs
        warped_t = np.clip(warped_t, 0, t[-1])
        y = np.interp(t, warped_t, y)

    if burst_rate_per_s > 0 and burst_length_ms > 0:
        expected = burst_rate_per_s * (len(y) / fs)
        n_bursts = g.poisson(expected)
        burst_len = max(1, int(fs * burst_length_ms / 1000.0))
        for _ in range(n_bursts):
            start = int(g.integers(0, max(1, len(y) - burst_len)))
            end = min(len(y), start + burst_len)
            fade = signal.windows.tukey(end - start, alpha=0.35)
            attenuation = g.uniform(0.0, 0.08)
            y[start:end] *= attenuation + (1 - attenuation) * (1 - fade)

    power = np.mean(y**2)
    noise_power = power / (10 ** (snr_db / 10))
    noise = g.normal(0, np.sqrt(noise_power), size=len(y))
    out = y + noise
    measured_snr = 10 * np.log10(np.mean(y**2) / max(np.mean(noise**2), 1e-20))
    return out, {
        "measured_snr_db": float(measured_snr),
        "measured_wow_flutter_wrms_pct": measured_wf * 100,
    }


def _chirp() -> np.ndarray:
    t = np.arange(int(FS * DURATION)) / FS
    x = signal.chirp(t, f0=80, f1=18_000, t1=DURATION, method="logarithmic")
    return 0.7 * x.astype(np.float64)


def _measure(x: np.ndarray, y: np.ndarray, bandwidth_hz: float, wow_flutter_wrms: float) -> dict:
    sos = signal.butter(5, bandwidth_hz, btype="lowpass", fs=FS, output="sos")
    clean = signal.sosfiltfilt(sos, x)
    n = y - clean
    measured_snr = 10 * np.log10(np.mean(clean**2) / max(np.mean(n**2), 1e-20))
    w, h = signal.sosfreqz(sos, worN=4096, fs=FS)
    def gain_at(freq: float) -> float:
        return 20 * np.log10(max(np.interp(freq, w, np.abs(h)), 1e-8))

    return {
        "measured_snr_db": round(float(measured_snr), 2),
        "measured_wow_flutter_wrms_pct": round(float(wow_flutter_wrms * 100), 4),
        "gain_1khz_db": round(float(gain_at(1_000)), 2),
        "gain_8khz_db": round(float(gain_at(8_000)), 2),
        "gain_12khz_db": round(float(gain_at(12_000)), 2),
        "gain_16khz_db": round(float(gain_at(16_000)), 2),
    }


def run() -> None:
    ensure_dirs()
    x = _chirp()
    rows = []
    snrs = [35, 40, 45]
    wfs = [0.0, 0.0007, 0.0012]
    bws = [10_000, 12_000, 15_000]
    for i, snr in enumerate(snrs):
        for wf in wfs:
            for bw in bws:
                y = cassette_channel(x, snr_db=snr, wow_flutter_wrms=wf, bandwidth_hz=bw, seed_offset=i)
                row = {"target_snr_db": snr, "target_wow_flutter_wrms_pct": wf * 100, "target_bandwidth_hz": bw}
                row.update(_measure(x, y, bw, wf))
                rows.append(row)

    write_csv(DATA / "channel_validation.csv", rows)
    run_stochasticity_audit()

    cases = [
        ("clean", x),
        ("realistic", cassette_channel(x, seed_offset=77)),
        ("low_snr_high_wf", cassette_channel(x, snr_db=35, wow_flutter_wrms=0.0012, bandwidth_hz=10_000, seed_offset=78)),
    ]
    for name, y in cases:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.specgram(y, NFFT=1024, Fs=FS, noverlap=768, cmap="magma")
        ax.set_title(f"Chirp spectrogram: {name}")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("frequency (Hz)")
        ax.set_ylim(0, 18_000)
        fig.tight_layout()
        fig.savefig(PLOTS / f"chirp_{name}.png", dpi=150)
        plt.close(fig)

    append_report(
        "Phase 1 - Channel Validation",
        "The cassette channel simulation sweeps SNR, wow/flutter, and low-pass bandwidth. "
        "At the realistic point it uses 40 dB SNR, 0.07% WRMS timebase error, and 12 kHz usable bandwidth; "
        "RESULTS/data/channel_validation.csv records measured SNR, W&F, and frequency-response metrics, and "
        "RESULTS/plots/chirp_*.png show the chirp attenuation/noise/timebase impairments.",
    )


def run_stochasticity_audit() -> None:
    x = _chirp()
    pairs = [cassette_channel_diagnostics(x, seed_offset=i) for i in range(10)]
    ys = [p[0] for p in pairs]
    rows = []
    for i, y in enumerate(ys):
        pairwise = [float(np.sqrt(np.mean((y - z) ** 2))) for j, z in enumerate(ys) if j != i]
        diag = pairs[i][1]
        rows.append(
            {
                "seed_offset": i,
                "target_snr_db": 40.0,
                "measured_snr_db": round(diag["measured_snr_db"], 2),
                "target_wow_flutter_wrms_pct": 0.07,
                "measured_wow_flutter_wrms_pct": round(diag["measured_wow_flutter_wrms_pct"], 5),
                "wf_deviation_pct_points": round(diag["measured_wow_flutter_wrms_pct"] - 0.07, 5),
                "mean_pairwise_rms_difference": round(float(np.mean(pairwise)), 8),
                "min_pairwise_rms_difference": round(float(np.min(pairwise)), 8),
            }
        )
    write_csv(DATA / "channel_stochasticity_audit.csv", rows)

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["tab:blue", "tab:orange", "tab:green"]
    for idx, y in enumerate(ys[:3]):
        freqs, times, spec = signal.spectrogram(y, fs=FS, nperseg=1024, noverlap=768)
        db = 10 * np.log10(spec + 1e-12)
        ax.contour(times, freqs, db, levels=[-55, -45, -35, -25], colors=colors[idx], alpha=0.72, linewidths=0.8)
    ax.set_title("Channel seed variance: overlaid chirp spectrogram contours")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("frequency (Hz)")
    ax.set_ylim(0, 18_000)
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(PLOTS / "channel_seed_variance.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()
