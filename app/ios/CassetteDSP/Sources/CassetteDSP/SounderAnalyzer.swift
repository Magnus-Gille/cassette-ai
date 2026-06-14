/// SounderAnalyzer.swift — Schroeder sounder analysis.
///
/// Ports the EXACT method from analyze_master2.py::analyze_sounder():
///   - 64 log-spaced carrier frequencies from 300 to 11 000 Hz.
///   - Per-tone magnitude: Hann-windowed FFT, max of |X[f]| in a ±30 Hz bin
///     window around each tone frequency.
///   - SNR per tone: tone peak vs median of off-tone band 80–140 Hz above.
///   - snr_db_median, snr_db_p10, frac_below_8db computed from per-tone SNR.
///   - noise_floor_dbfs: RMS of the silence section in dBFS.
///
/// Python reference tolerance:
///   snr_db_median / snr_db_p10 within ±2 dB of Python output.
///   noise_floor_dbfs within ±2 dB.
///
/// No third-party dependencies. Accelerate/vDSP for FFT.

import Accelerate
import Foundation

// MARK: - Output struct

public struct SounderMetrics {
    /// Frequencies of the 64 Schroeder tones (Hz).
    public let toneFrequencies: [Double]
    /// Per-tone SNR in dB (64 values).
    public let snrPerTone: [Double]
    /// Median per-tone SNR across all 64 tones.
    public let snrDBMedian: Double
    /// 10th-percentile per-tone SNR (worst-case carrier).
    public let snrDBP10: Double
    /// Fraction of tones below 8 dB SNR.
    public let fracBelow8dB: Double
    /// Noise floor (RMS of silence section) in dBFS.
    public let noiseFloorDBFS: Double?

    public init(
        toneFrequencies: [Double],
        snrPerTone: [Double],
        snrDBMedian: Double,
        snrDBP10: Double,
        fracBelow8dB: Double,
        noiseFloorDBFS: Double?
    ) {
        self.toneFrequencies = toneFrequencies
        self.snrPerTone = snrPerTone
        self.snrDBMedian = snrDBMedian
        self.snrDBP10 = snrDBP10
        self.fracBelow8dB = fracBelow8dB
        self.noiseFloorDBFS = noiseFloorDBFS
    }
}

// MARK: - SounderAnalyzer

public final class SounderAnalyzer {
    // Schroeder carrier parameters (must match make_master2.py::_build_sounder).
    public static let numTones: Int      = 64
    public static let toneFreqLo: Double = 300.0
    public static let toneFreqHi: Double = 11_000.0
    public static let defaultSampleRate: Double = 48_000.0

    /// 64 logarithmically-spaced carrier frequencies, rounded to integers.
    /// Matches: np.round(np.geomspace(300, 11000, 64)).astype(int)
    public static let toneFrequencies: [Double] = {
        let n = numTones
        return (0..<n).map { k -> Double in
            let ratio = Double(k) / Double(n - 1)
            return (toneFreqLo * pow(toneFreqHi / toneFreqLo, ratio)).rounded()
        }
    }()

    private let sampleRate: Double

    public init(sampleRate: Double = SounderAnalyzer.defaultSampleRate) {
        self.sampleRate = sampleRate
    }

    // MARK: - Main entry point
    /// Analyse a multitone sounder segment.
    ///
    /// - Parameters:
    ///   - multitoneSegment: Pre-trimmed audio containing the Schroeder multitone
    ///     probe. Should have 0.3 s trimmed from each end (caller's responsibility,
    ///     matching analyze_master2.py trim=0.3).
    ///   - silenceSegment: Pre-trimmed audio from the noise-floor silence section.
    ///     Pass nil if unavailable.
    public func analyze(
        multitoneSegment: [Float],
        silenceSegment: [Float]? = nil
    ) -> SounderMetrics {
        let freqs = SounderAnalyzer.toneFrequencies
        let snrArr = _computeSNR(segment: multitoneSegment, freqs: freqs)

        let snrSorted = snrArr.sorted()
        let median = _median(snrSorted)
        let p10    = _percentile(snrSorted, p: 0.10)
        let frac   = Double(snrArr.filter { $0 < 8.0 }.count) / Double(snrArr.count)

        var noiseFloorDBFS: Double? = nil
        if let sil = silenceSegment, !sil.isEmpty {
            let rms = _rms(sil)
            if rms > 0 { noiseFloorDBFS = 20.0 * log10(rms) }
        }

        return SounderMetrics(
            toneFrequencies: freqs,
            snrPerTone: snrArr,
            snrDBMedian: median,
            snrDBP10: p10,
            fracBelow8dB: frac,
            noiseFloorDBFS: noiseFloorDBFS
        )
    }

    // MARK: - Private: per-tone SNR
    /// Replicates analyze_master2.py::analyze_sounder inner SNR loop exactly.
    ///
    /// Key: the FFT is zero-padded to the next power-of-two. The frequency-axis
    /// bin spacing is sr/fftN (NOT sr/n), so we must use fftN for bin lookup.
    private func _computeSNR(segment: [Float], freqs: [Double]) -> [Double] {
        let n = segment.count
        guard n >= Int(sampleRate) else { return [Double](repeating: 0, count: freqs.count) }

        // Hann window (length n, matching np.hanning(n)).
        var window = [Float](repeating: 0, count: n)
        vDSP_hann_window(&window, vDSP_Length(n), Int32(vDSP_HANN_NORM))

        // Apply window to the segment.
        var windowed = [Float](repeating: 0, count: n)
        vDSP_vmul(segment, 1, window, 1, &windowed, 1, vDSP_Length(n))

        // FFT with zero-padding to next power of two. Returns (|X[k]|, fftN).
        let (magnitudes, fftN) = _computeMagnitudeSpectrum(windowed)

        // CRITICAL: bin k covers frequency k * sr / fftN Hz (zero-padded size).
        let binHz = sampleRate / Double(fftN)

        var snrArr = [Double](repeating: 0, count: freqs.count)
        for (idx, f) in freqs.enumerated() {
            // Tone bin window: ±30 Hz (matches Python: bl = searchsorted(fax, f-30)).
            let binLo = max(0, Int((f - 30.0) / binHz))
            var binHi = max(Int((f + 30.0) / binHz), binLo + 1)
            binHi = min(binHi, magnitudes.count)

            let tonePeak = magnitudes[binLo..<binHi].max() ?? 1e-12

            // Noise band: 80–140 Hz above the tone (Python: f+80 to f+140).
            let nl = min(magnitudes.count, Int((f + 80.0) / binHz))
            let nh = min(magnitudes.count, max(Int((f + 140.0) / binHz), nl + 1))
            let noiseSlice = magnitudes[nl..<nh]
            let noiseAmp: Double
            if noiseSlice.isEmpty {
                noiseAmp = 1e-9
            } else {
                noiseAmp = _medianDouble(noiseSlice.map { Double($0) })
            }
            let safeTone  = max(Double(tonePeak), 1e-12)
            let safeNoise = max(noiseAmp, 1e-12)
            snrArr[idx] = 20.0 * log10(safeTone / safeNoise)
        }
        return snrArr
    }

    // MARK: - FFT magnitude spectrum
    /// Returns (magnitudes, fftN):
    ///   magnitudes = |X[k]| for k in [0, fftN/2]  (fftN/2 + 1 values)
    ///   fftN = next power-of-two >= x.count
    ///
    /// The input `x` should already be windowed. Zero-pads to fftN internally.
    private func _computeMagnitudeSpectrum(_ x: [Float]) -> (mags: [Float], fftN: Int) {
        let n = x.count
        let fftN = _nextPow2(n)
        let log2n = Int(log2(Double(fftN)).rounded())

        // Zero-pad.
        var padded = [Float](repeating: 0, count: fftN)
        padded.withUnsafeMutableBufferPointer { dst in
            x.withUnsafeBufferPointer { src in
                dst.baseAddress!.initialize(from: src.baseAddress!, count: n)
            }
        }

        guard let setup = vDSP_create_fftsetup(vDSP_Length(log2n), FFTRadix(FFT_RADIX2)) else {
            return (mags: [Float](repeating: 0, count: fftN / 2 + 1), fftN: fftN)
        }
        defer { vDSP_destroy_fftsetup(setup) }

        var even = [Float](repeating: 0, count: fftN / 2)
        var odd  = [Float](repeating: 0, count: fftN / 2)
        var magsSq = [Float](repeating: 0, count: fftN / 2 + 1)

        padded.withUnsafeMutableBufferPointer { pPtr in
            even.withUnsafeMutableBufferPointer { ePtr in
                odd.withUnsafeMutableBufferPointer { oPtr in
                    var split = DSPSplitComplex(realp: ePtr.baseAddress!,
                                               imagp: oPtr.baseAddress!)
                    // Pack real signal into split-complex format:
                    // even-indexed samples -> real, odd-indexed -> imag.
                    pPtr.baseAddress!.withMemoryRebound(
                        to: DSPComplex.self, capacity: fftN / 2) { cPtr in
                        vDSP_ctoz(cPtr, 2, &split, 1, vDSP_Length(fftN / 2))
                    }
                    // Forward real FFT.
                    vDSP_fft_zrip(setup, &split, 1,
                                   vDSP_Length(log2n), FFTDirection(FFT_FORWARD))
                    // Squared magnitudes for bins 1..(N/2-1).
                    vDSP_zvmags(&split, 1, &magsSq, 1, vDSP_Length(fftN / 2))
                    // DC bin: real[0] = Re(X[0]), imag[0] = Re(X[N/2]).
                    magsSq[0]        = ePtr[0] * ePtr[0]
                    magsSq[fftN / 2] = oPtr[0] * oPtr[0]
                }
            }
        }

        // vDSP forward real FFT scales by 2× vs the standard DFT.
        // Divide by 2 before taking sqrt to get the correct |X[k]|.
        // (Scale factor cancels in SNR, but we want accurate magnitudes.)
        var mags = [Float](repeating: 0, count: fftN / 2 + 1)
        let halfScale: Float = 0.25   // (1/2)^2 under the sqrt = multiply magsSq by 0.25
        var magsSqScaled = [Float](repeating: 0, count: fftN / 2 + 1)
        vDSP_vsmul(magsSq, 1, [halfScale], &magsSqScaled, 1, vDSP_Length(fftN / 2 + 1))
        var count = Int32(fftN / 2 + 1)
        vvsqrtf(&mags, magsSqScaled, &count)
        return (mags: mags, fftN: fftN)
    }

    // MARK: - Helpers
    private func _nextPow2(_ n: Int) -> Int {
        var p = 1
        while p < n { p <<= 1 }
        return p
    }

    private func _rms(_ x: [Float]) -> Double {
        var sse: Float = 0
        vDSP_svesq(x, 1, &sse, vDSP_Length(x.count))
        return sqrt(Double(sse) / Double(x.count))
    }

    private func _median(_ sorted: [Double]) -> Double {
        guard !sorted.isEmpty else { return 0 }
        let n = sorted.count
        if n % 2 == 1 { return sorted[n / 2] }
        return (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
    }

    private func _percentile(_ sorted: [Double], p: Double) -> Double {
        guard !sorted.isEmpty else { return 0 }
        let idx = p * Double(sorted.count - 1)
        let lo  = Int(idx)
        let hi  = min(lo + 1, sorted.count - 1)
        let frac = idx - Double(lo)
        return sorted[lo] * (1 - frac) + sorted[hi] * frac
    }

    private func _medianDouble(_ arr: [Double]) -> Double {
        guard !arr.isEmpty else { return 1e-9 }
        return _median(arr.sorted())
    }
}
