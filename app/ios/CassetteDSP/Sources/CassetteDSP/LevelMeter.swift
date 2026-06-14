/// LevelMeter.swift — Streaming RMS / peak / clip-fraction over float PCM buffers.
///
/// Thread-safety: LevelMeter is not thread-safe. Call push() from a single
/// thread (typically the audio tap thread), read properties from the same
/// thread or after synchronising externally.
///
/// Usage:
///   let meter = LevelMeter(sampleRate: 48_000, windowDuration: 0.1)
///   meter.push(samples)           // from audio tap
///   print(meter.rmsDB, meter.peakDB, meter.clipFraction)

import Accelerate
import Foundation

public final class LevelMeter {
    // MARK: - Configuration
    public let sampleRate: Double
    /// Integration window length in samples.
    public let windowSamples: Int

    // MARK: - Running state
    /// Sum of squares accumulated in the current window.
    private var sumOfSquares: Double = 0.0
    /// Count of samples accumulated since last reset.
    private var sampleCount: Int = 0
    /// Running peak magnitude within the current window.
    private var runningPeak: Float = 0.0
    /// Count of clipped samples (|x| >= clippingThreshold) in current window.
    private var clippedSamples: Int = 0
    /// Total samples pushed in current window (for clip fraction denominator).
    private var totalWindowSamples: Int = 0

    /// Level (linear) above which a sample is considered clipped (default 0.99).
    public var clippingThreshold: Float = 0.99

    // MARK: - Published results (updated at each window boundary)
    /// RMS level in dBFS. Updated every `windowSamples` samples.
    public private(set) var rmsDB: Float = -120.0
    /// Peak level in dBFS. Updated every `windowSamples` samples.
    public private(set) var peakDB: Float = -120.0
    /// Fraction of samples that clipped [0, 1]. Updated every `windowSamples` samples.
    public private(set) var clipFraction: Float = 0.0
    /// True if any sample in the most recent window was clipped.
    public var isClipping: Bool { clipFraction > 0.0 }

    // MARK: - Init
    /// - Parameters:
    ///   - sampleRate: Audio sample rate in Hz (e.g. 48_000).
    ///   - windowDuration: Integration window in seconds (e.g. 0.1 for 100 ms).
    public init(sampleRate: Double = 48_000, windowDuration: Double = 0.1) {
        self.sampleRate = sampleRate
        self.windowSamples = max(1, Int((sampleRate * windowDuration).rounded()))
    }

    // MARK: - Push samples
    /// Feed a buffer of mono float32 samples. May be called from the audio thread.
    /// Updates `rmsDB`, `peakDB`, `clipFraction` whenever a full window is complete.
    public func push(_ samples: [Float]) {
        samples.withUnsafeBufferPointer { push($0) }
    }

    /// Feed raw pointer buffer — zero-copy path for audio tap callbacks.
    public func push(_ ptr: UnsafePointer<Float>, count: Int) {
        push(UnsafeBufferPointer(start: ptr, count: count))
    }

    public func push(_ buffer: UnsafeBufferPointer<Float>) {
        guard buffer.count > 0 else { return }

        var remaining = buffer.count
        var offset = 0

        while remaining > 0 {
            let space = windowSamples - sampleCount
            let chunk = min(space, remaining)
            let slice = UnsafeBufferPointer(
                start: buffer.baseAddress! + offset, count: chunk)

            // Accumulate sum-of-squares via vDSP.
            var sse: Float = 0.0
            vDSP_svesq(slice.baseAddress!, 1, &sse, vDSP_Length(chunk))
            sumOfSquares += Double(sse)

            // Peak magnitude.
            var localPeak: Float = 0.0
            vDSP_maxmgv(slice.baseAddress!, 1, &localPeak, vDSP_Length(chunk))
            if localPeak > runningPeak { runningPeak = localPeak }

            // Clip count: count samples with |x| >= threshold.
            // Use absolute value + threshold comparison.
            var absSlice = [Float](repeating: 0, count: chunk)
            vDSP_vabs(slice.baseAddress!, 1, &absSlice, 1, vDSP_Length(chunk))
            let thresh = clippingThreshold
            // Count how many abs values exceed threshold.
            var clippedInChunk = 0
            for v in absSlice where v >= thresh { clippedInChunk += 1 }
            clippedSamples += clippedInChunk
            totalWindowSamples += chunk
            sampleCount += chunk
            offset += chunk
            remaining -= chunk

            if sampleCount >= windowSamples {
                _flush()
            }
        }
    }

    // MARK: - Reset
    public func reset() {
        sumOfSquares = 0
        sampleCount = 0
        runningPeak = 0
        clippedSamples = 0
        totalWindowSamples = 0
        rmsDB = -120.0
        peakDB = -120.0
        clipFraction = 0.0
    }

    // MARK: - Private helpers
    private func _flush() {
        let n = sampleCount > 0 ? sampleCount : 1
        let rms = sqrt(sumOfSquares / Double(n))
        rmsDB  = Float(rms  > 1e-12 ? 20.0 * log10(rms)  : -120.0)
        peakDB = runningPeak > 1e-12 ? 20.0 * log10(runningPeak) : -120.0
        clipFraction = totalWindowSamples > 0
            ? Float(clippedSamples) / Float(totalWindowSamples)
            : 0.0
        // Reset accumulators for next window.
        sumOfSquares = 0
        sampleCount = 0
        runningPeak = 0
        clippedSamples = 0
        totalWindowSamples = 0
    }
}
