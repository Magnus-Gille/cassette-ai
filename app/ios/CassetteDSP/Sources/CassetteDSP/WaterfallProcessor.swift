/// WaterfallProcessor.swift — Streaming STFT for waterfall / spectrogram display.
///
/// Push mono float32 samples via `push(_:)`. Call `drainRows()` to consume
/// completed magnitude-dB rows. Each row is a [Float] of `binCount` values
/// normalised to [0, 1] over the configured frequency range.
///
/// Parameters:
///   - fftSize:      FFT window length (default 1024, power-of-two).
///   - hopSize:      Advance in samples between frames (default 512).
///   - sampleRate:   48 000 Hz.
///   - freqLo/Hi:    Frequency range to crop (default 0–12 000 Hz).
///
/// Thread-safety: not thread-safe. Push from one thread; drain from same thread.
///
/// Accelerate/vDSP usage:
///   - Hann window via vDSP_hann_window.
///   - vDSP_ctoz / vDSP_zvmags for magnitude.
///   - No heap allocation per frame after initialisation.

import Accelerate
import Foundation

public final class WaterfallProcessor {
    // MARK: - Configuration
    public let fftSize: Int
    public let hopSize: Int
    public let sampleRate: Double
    public let freqLo: Double
    public let freqHi: Double

    /// Number of frequency bins in each emitted row (after frequency-range crop).
    public let binCount: Int

    // MARK: - Private state
    private var ring: [Float]
    private var writePos: Int = 0
    private var samplesBuffered: Int = 0

    private let hannWindow: [Float]
    private let fftSetup: FFTSetup
    private let log2n: Int

    // Cropped bin index range [cropLo, cropHi).
    private let cropLo: Int
    private let cropHi: Int

    // Work buffers (allocated once).
    private var frameBuffer: [Float]
    private var windowed: [Float]
    private var splitRealEven: [Float]
    private var splitRealOdd: [Float]
    private var magnitudes: [Float]

    // Rolling max for normalisation (exponential moving average of per-frame max).
    private var rollingMax: Float = 1e-6
    private let rollingAlpha: Float = 0.02   // blend towards per-frame max

    // Output queue.
    private var rowQueue: [[Float]] = []

    // MARK: - Init
    public init(
        fftSize: Int = 1024,
        hopSize: Int = 512,
        sampleRate: Double = 48_000,
        freqLo: Double = 0,
        freqHi: Double = 12_000
    ) {
        precondition(fftSize > 0 && (fftSize & (fftSize - 1)) == 0,
                     "fftSize must be a power of two")
        precondition(hopSize > 0 && hopSize <= fftSize)

        self.fftSize = fftSize
        self.hopSize = hopSize
        self.sampleRate = sampleRate
        self.freqLo = freqLo
        self.freqHi = min(freqHi, sampleRate / 2)

        log2n = Int(log2(Double(fftSize)).rounded())
        guard let setup = vDSP_create_fftsetup(vDSP_Length(log2n), FFTRadix(FFT_RADIX2)) else {
            fatalError("vDSP_create_fftsetup failed for log2n=\(log2n)")
        }
        fftSetup = setup

        // Hann window.
        var hann = [Float](repeating: 0, count: fftSize)
        vDSP_hann_window(&hann, vDSP_Length(fftSize), Int32(vDSP_HANN_NORM))
        hannWindow = hann

        // Ring buffer — keep fftSize samples at all times.
        ring = [Float](repeating: 0, count: fftSize)

        // Work buffers.
        frameBuffer = [Float](repeating: 0, count: fftSize)
        windowed    = [Float](repeating: 0, count: fftSize)
        splitRealEven = [Float](repeating: 0, count: fftSize / 2)
        splitRealOdd  = [Float](repeating: 0, count: fftSize / 2)
        magnitudes    = [Float](repeating: 0, count: fftSize / 2 + 1)

        // Frequency bin mapping: bin k covers k * sr / fftSize Hz.
        let binHz = sampleRate / Double(fftSize)
        cropLo = max(0, Int((freqLo / binHz).rounded()))
        cropHi = min(fftSize / 2 + 1, Int((self.freqHi / binHz).rounded()) + 1)
        binCount = max(1, cropHi - cropLo)
    }

    deinit {
        vDSP_destroy_fftsetup(fftSetup)
    }

    // MARK: - Push samples
    public func push(_ samples: [Float]) {
        samples.withUnsafeBufferPointer { push($0) }
    }

    public func push(_ ptr: UnsafePointer<Float>, count: Int) {
        push(UnsafeBufferPointer(start: ptr, count: count))
    }

    public func push(_ buffer: UnsafeBufferPointer<Float>) {
        guard buffer.count > 0 else { return }

        // Write into ring buffer.
        var remaining = buffer.count
        var src = 0
        while remaining > 0 {
            let chunk = min(remaining, fftSize - writePos)
            ring.withUnsafeMutableBufferPointer { dst in
                let dstPtr = dst.baseAddress! + writePos
                (buffer.baseAddress! + src).withMemoryRebound(to: Float.self, capacity: chunk) { _ in }
                dstPtr.initialize(from: buffer.baseAddress! + src, count: chunk)
            }
            writePos = (writePos + chunk) % fftSize
            samplesBuffered = min(samplesBuffered + chunk, fftSize)
            remaining -= chunk
            src += chunk
        }

        // Emit frames whenever we have a full hopSize of new data.
        // We accumulate hop counts separately.
        _pendingHopSamples += buffer.count
        while _pendingHopSamples >= hopSize && samplesBuffered >= fftSize {
            _pendingHopSamples -= hopSize
            _emitFrame()
        }
    }

    // Count of new samples since last frame.
    private var _pendingHopSamples: Int = 0

    // MARK: - Drain emitted rows
    /// Returns all rows accumulated since the last drain. Each row is `binCount` floats in [0, 1].
    public func drainRows() -> [[Float]] {
        let out = rowQueue
        rowQueue.removeAll(keepingCapacity: true)
        return out
    }

    // MARK: - Private
    private func _emitFrame() {
        // Read the most recent fftSize samples from the ring (linear copy).
        let tail = fftSize - writePos
        if tail > 0 {
            // samples from writePos..end
            frameBuffer.withUnsafeMutableBufferPointer { dst in
                ring.withUnsafeBufferPointer { src in
                    (dst.baseAddress!).initialize(
                        from: src.baseAddress! + writePos, count: tail)
                }
            }
        }
        if writePos > 0 {
            let front = writePos
            frameBuffer.withUnsafeMutableBufferPointer { dst in
                ring.withUnsafeBufferPointer { src in
                    (dst.baseAddress! + tail).initialize(
                        from: src.baseAddress!, count: front)
                }
            }
        }

        // Apply Hann window.
        vDSP_vmul(frameBuffer, 1, hannWindow, 1, &windowed, 1, vDSP_Length(fftSize))

        // FFT via vDSP (real-to-complex).
        windowed.withUnsafeMutableBufferPointer { wPtr in
            splitRealEven.withUnsafeMutableBufferPointer { evenPtr in
                splitRealOdd.withUnsafeMutableBufferPointer { oddPtr in
                    var split = DSPSplitComplex(
                        realp: evenPtr.baseAddress!,
                        imagp: oddPtr.baseAddress!)
                    // Pack interleaved real into split format.
                    wPtr.baseAddress!.withMemoryRebound(
                        to: DSPComplex.self, capacity: fftSize / 2) { complexPtr in
                        vDSP_ctoz(complexPtr, 2, &split, 1, vDSP_Length(fftSize / 2))
                    }
                    // Forward real FFT.
                    vDSP_fft_zrip(fftSetup, &split, 1,
                                   vDSP_Length(log2n), FFTDirection(FFT_FORWARD))
                    // Magnitudes (squared).
                    vDSP_zvmags(&split, 1, &magnitudes, 1, vDSP_Length(fftSize / 2))
                    // DC and Nyquist are packed in the split output:
                    // real[0] = DC, imag[0] = Nyquist.
                    magnitudes[0]          = evenPtr[0] * evenPtr[0]
                    magnitudes[fftSize / 2] = oddPtr[0]  * oddPtr[0]
                }
            }
        }

        // Convert to dB (magnitude, not power — take sqrt of squared mags).
        // magnitudes currently holds |X|^2.  dB = 10*log10(|X|^2) = 20*log10(|X|).
        let nMags = vDSP_Length(fftSize / 2 + 1)
        var magFloor: Float = 1e-12
        var threshMags = magnitudes   // copy to avoid exclusive-access violation
        vDSP_vthres(&threshMags, 1, &magFloor, &magnitudes, 1, nMags)
        // log10 via vForce.
        var logMags = [Float](repeating: 0, count: fftSize / 2 + 1)
        var nInt = Int32(fftSize / 2 + 1)
        vvlog10f(&logMags, magnitudes, &nInt)
        // dB = 10 * log10(|X|^2).
        var scale: Float = 10.0
        vDSP_vsmul(logMags, 1, &scale, &logMags, 1, nMags)

        // Crop to [cropLo, cropHi).
        let cropCount = cropHi - cropLo
        var row = [Float](repeating: 0, count: cropCount)
        for i in 0..<cropCount {
            row[i] = logMags[cropLo + i]
        }

        // Normalise to [0, 1].  Rolling max tracks the loudest frame seen.
        var frameMax: Float = 0
        vDSP_maxv(row, 1, &frameMax, vDSP_Length(cropCount))
        rollingMax = (1 - rollingAlpha) * rollingMax + rollingAlpha * max(rollingMax, frameMax)

        // Map: 0 dB = max (1.0), -60 dB below max = 0.0 (60 dB dynamic range).
        let dbRange: Float = 60.0
        var normRow = [Float](repeating: 0, count: cropCount)
        for i in 0..<cropCount {
            normRow[i] = max(0, min(1, (row[i] - rollingMax + dbRange) / dbRange))
        }

        rowQueue.append(normRow)
    }
}
