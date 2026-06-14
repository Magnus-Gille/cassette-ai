/// ChirpSync.swift — Matched-filter detector for the global sync chirp.
///
/// Chirp parameters (from make_master2.py / analyze_master2.py):
///   f0 = 500 Hz, f1 = 5000 Hz, duration = 0.20 s, sample rate = 48 000 Hz
///   method = linear (instantaneous frequency increases linearly with time)
///   Up-chirp: 500 → 5000 Hz.  Down-chirp: 5000 → 500 Hz.
///
/// Detection strategy:
///   1. Coarse search: downsample the input by 8× (6 kHz), apply matched filter
///      to locate the chirp to within ±8 samples at full rate.
///   2. Fine search: zoom into a ±2048-sample window around each coarse peak
///      at full resolution and pick the exact sample offset.
///
/// For a 60 s capture at 48 kHz on Apple Silicon M-series, the coarse pass
/// processes 7.5k samples against a 1200-sample chirp — trivially < 100 ms.
/// The fine pass is bounded to a short window. Total well under 2 s.
///
/// Returns:
///   - sampleOffset: index into the input array where the chirp starts.
///   - normalizedCorrelation: peak correlation normalised to [0, 1].
///
/// Thread-safety: ChirpSync is not thread-safe. Instantiate per-call or
/// serialise access externally.

import Accelerate
import Foundation

public struct ChirpResult {
    /// Sample index (relative to the start of the audio passed to `detect`) where the
    /// chirp is estimated to start.
    public let sampleOffset: Int
    /// Normalised correlation peak in [0, 1]. Values > 0.3 indicate a confident detection.
    public let normalizedCorrelation: Float

    public init(sampleOffset: Int, normalizedCorrelation: Float) {
        self.sampleOffset = sampleOffset
        self.normalizedCorrelation = normalizedCorrelation
    }
}

public final class ChirpSync {
    // MARK: - Chirp parameters (must match make_master2.py)
    public static let chirpDuration: Double = 0.20
    public static let chirpF0: Double      = 500.0
    public static let chirpF1: Double      = 5_000.0
    public static let nominalSampleRate: Double = 48_000.0

    // MARK: - Reference templates (computed once at init)
    private let upChirpFull:   [Float]
    private let downChirpFull: [Float]
    private let upChirpDecim:   [Float]
    private let downChirpDecim: [Float]

    private let decimFactor: Int = 8
    private let chirpSamples: Int   // samples at 48 kHz

    // MARK: - Init
    public init(sampleRate: Double = ChirpSync.nominalSampleRate) {
        let n = Int((ChirpSync.chirpDuration * sampleRate).rounded())
        chirpSamples = n
        upChirpFull   = ChirpSync._makeChirp(n: n, sr: sampleRate, up: true)
        downChirpFull = ChirpSync._makeChirp(n: n, sr: sampleRate, up: false)
        upChirpDecim   = ChirpSync._decimate(upChirpFull, factor: decimFactor)
        downChirpDecim = ChirpSync._decimate(downChirpFull, factor: decimFactor)
    }

    // MARK: - Public API
    public func detect(_ audio: [Float], isUpChirp: Bool = true) -> ChirpResult {
        return audio.withUnsafeBufferPointer { detect($0, isUpChirp: isUpChirp) }
    }

    public func detect(_ audio: UnsafeBufferPointer<Float>,
                       isUpChirp: Bool = true) -> ChirpResult {
        let n = audio.count
        guard n >= chirpSamples else {
            return ChirpResult(sampleOffset: 0, normalizedCorrelation: 0)
        }

        let refDecim = isUpChirp ? upChirpDecim : downChirpDecim
        let refFull  = isUpChirp ? upChirpFull  : downChirpFull

        // 1. Decimate input.
        let audioDecim = ChirpSync._decimate(audio, factor: decimFactor)

        // 2. Coarse matched-filter on decimated signal.
        let coarseCorr = ChirpSync._xcorrNormEnergy(signal: audioDecim, ref: refDecim)
        guard let coarsePeak = _argmax(coarseCorr) else {
            return ChirpResult(sampleOffset: 0, normalizedCorrelation: 0)
        }
        let normCorr = coarseCorr[coarsePeak]

        // Convert coarse index to full-rate index.
        let coarseFull = coarsePeak * decimFactor

        // 3. Fine search: ±2048 samples around the coarse position.
        let fineHalf = 2048
        let lo = max(0, coarseFull - fineHalf)
        let hi = min(n - refFull.count, coarseFull + fineHalf)

        var bestIdx = coarseFull
        var bestVal: Float = -1

        if lo <= hi {
            let fineLen = (hi + refFull.count) - lo
            let fineSlice: [Float] = (lo..<(lo + fineLen)).map { audio[$0] }
            let fineCorr = ChirpSync._xcorrNormEnergy(signal: fineSlice, ref: refFull)
            if let finePeak = _argmax(fineCorr) {
                bestVal = fineCorr[finePeak]
                bestIdx = lo + finePeak
            }
        }

        let finalCorr = bestVal >= 0 ? bestVal : normCorr

        return ChirpResult(sampleOffset: bestIdx,
                           normalizedCorrelation: max(0, min(1, finalCorr)))
    }

    // MARK: - Chirp generation
    static func _makeChirp(n: Int, sr: Double, up: Bool) -> [Float] {
        let f0 = up ? chirpF0 : chirpF1
        let f1 = up ? chirpF1 : chirpF0
        let t1 = chirpDuration
        let df = (f1 - f0)
        var result = [Float](repeating: 0, count: n)
        for i in 0..<n {
            let t = Double(i) / sr
            let phase = 2.0 * .pi * (f0 * t + df / (2.0 * t1) * t * t)
            result[i] = Float(sin(phase))
        }
        return result
    }

    // MARK: - Decimation
    static func _decimate(_ signal: [Float], factor: Int) -> [Float] {
        return signal.withUnsafeBufferPointer { _decimate($0, factor: factor) }
    }

    static func _decimate(_ signal: UnsafeBufferPointer<Float>, factor: Int) -> [Float] {
        guard factor > 1, signal.count > 0 else { return Array(signal) }
        let n = signal.count
        let outLen = n / factor
        var out = [Float](repeating: 0, count: outLen)
        let invF = Float(1.0 / Double(factor))
        for i in 0..<outLen {
            var sum: Float = 0
            let base = i * factor
            let end  = min(base + factor, n)
            // Use vDSP_sve for the chunk sum.
            vDSP_sve(signal.baseAddress! + base, 1, &sum, vDSP_Length(end - base))
            out[i] = sum * invF
        }
        return out
    }

    // MARK: - Normalised cross-correlation
    static func _xcorrNormEnergy(signal: [Float], ref: [Float]) -> [Float] {
        let validLen = signal.count - ref.count + 1
        guard validLen > 0 else { return [] }

        var refEnergySq: Float = 0
        vDSP_svesq(ref, 1, &refEnergySq, vDSP_Length(ref.count))
        let refNorm = sqrtf(refEnergySq)
        guard refNorm > 1e-12 else { return [Float](repeating: 0, count: validLen) }

        var result = [Float](repeating: 0, count: validLen)

        signal.withUnsafeBufferPointer { sigBuf in
            ref.withUnsafeBufferPointer { refBuf in
                for i in 0..<validLen {
                    var dot: Float = 0
                    vDSP_dotpr(sigBuf.baseAddress! + i, 1,
                               refBuf.baseAddress!,      1,
                               &dot, vDSP_Length(ref.count))
                    var windowESq: Float = 0
                    vDSP_svesq(sigBuf.baseAddress! + i, 1,
                               &windowESq, vDSP_Length(ref.count))
                    let windowNorm = sqrtf(windowESq)
                    let denom = windowNorm * refNorm
                    result[i] = denom > 1e-12 ? abs(dot) / denom : 0
                }
            }
        }
        return result
    }
}

// MARK: - Helpers
private func _argmax(_ arr: [Float]) -> Int? {
    guard !arr.isEmpty else { return nil }
    var idx: vDSP_Length = 0
    var val: Float = 0
    vDSP_maxvi(arr, 1, &val, &idx, vDSP_Length(arr.count))
    return Int(idx)
}
