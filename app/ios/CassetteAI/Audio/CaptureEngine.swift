import AVFoundation
import Combine
import Foundation
import CassetteDSP

// ---------------------------------------------------------------------------
// CaptureEngine — AVAudioEngine wrapper for lossless 48 kHz float32 capture.
//
// Rules (non-negotiable per lab SOP):
//   • AVAudioSession category .playAndRecord (supports Stage-A tone play),
//     mode .measurement (minimises OS input processing / AGC).
//   • Voice processing explicitly NOT enabled on the input node.
//   • Writes float32 WAV via AVAudioFile (lossless; never AAC).
//   • Audio tap runs on a real-time thread: no allocation, no locks.
//     Buffers are dispatched to a serial queue for level/waterfall processing.
// ---------------------------------------------------------------------------

@MainActor
final class CaptureEngine: ObservableObject {

    // ---- Public state -------------------------------------------------------
    enum State {
        case idle
        case monitoring   // session active, not writing
        case recording    // writing to file
    }

    @Published private(set) var engineState: State = .idle
    @Published private(set) var levelDb: Float = -96.0
    @Published private(set) var isClipping: Bool = false
    @Published private(set) var elapsedSeconds: Double = 0
    @Published private(set) var fileURL: URL?
    @Published private(set) var grantedSampleRate: Double = 0
    @Published private(set) var errorMessage: String?

    // Waterfall rows: each [Float] is one FFT magnitude row, newest last.
    @Published private(set) var waterfallRows: [[Float]] = []
    private let maxWaterfallRows = 200

    // ---- Private state ------------------------------------------------------
    private var audioEngine: AVAudioEngine?
    private var audioFile: AVAudioFile?
    private var startDate: Date?
    private var elapsedTimer: Timer?
    private let processingQueue = DispatchQueue(label: "ai.cassette.capture", qos: .userInitiated)
    // Real DSP from CassetteDSP. Both are touched only on `processingQueue`.
    private let waterfall = WaterfallProcessor(fftSize: 2048, hopSize: 1024,
                                               sampleRate: 48_000,
                                               freqLo: 0, freqHi: 12_000)
    private let levelMeter = LevelMeter(sampleRate: 48_000, windowDuration: 0.05)

    // ---- Session configuration constants ------------------------------------
    private static let targetSampleRate: Double = 48_000
    private static let clippingThreshold: Float = -1.0  // dBFS

    // -------------------------------------------------------------------------
    // MARK: - Public API
    // -------------------------------------------------------------------------

    func requestPermission() async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        if status == .authorized { return true }
        return await AVCaptureDevice.requestAccess(for: .audio)
    }

    func startMonitoring() async {
        guard engineState == .idle else { return }
        errorMessage = nil

        guard await requestPermission() else {
            errorMessage = "Microphone access denied."
            return
        }

        do {
            try configureSession()
            try buildEngine()
            engineState = .monitoring
        } catch {
            errorMessage = "Audio setup failed: \(error.localizedDescription)"
        }
    }

    func startRecording() {
        guard engineState == .monitoring else { return }
        do {
            let url = try makeOutputURL()
            let format = audioEngine!.inputNode.outputFormat(forBus: 0)
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: format.sampleRate,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 32,
                AVLinearPCMIsFloatKey: true,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsNonInterleaved: false
            ]
            audioFile = try AVAudioFile(
                forWriting: url,
                settings: settings,
                commonFormat: .pcmFormatFloat32,
                interleaved: true
            )
            fileURL = url
            startDate = Date()
            startElapsedTimer()
            engineState = .recording
        } catch {
            errorMessage = "Failed to start recording: \(error.localizedDescription)"
        }
    }

    func stopRecording() {
        guard engineState == .recording else { return }
        stopElapsedTimer()
        audioFile = nil   // closes and flushes the file
        engineState = .monitoring
    }

    func stopMonitoring() {
        stopElapsedTimer()
        audioFile = nil
        audioEngine?.stop()
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine = nil
        engineState = .idle
        levelDb = -96.0
        isClipping = false
        elapsedSeconds = 0
        do {
            try AVAudioSession.sharedInstance().setActive(false)
        } catch {}
    }

    // -------------------------------------------------------------------------
    // MARK: - Private helpers
    // -------------------------------------------------------------------------

    private func configureSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord,
                                mode: .measurement,
                                options: [.defaultToSpeaker, .allowBluetooth])
        try session.setPreferredSampleRate(Self.targetSampleRate)
        try session.setPreferredIOBufferDuration(0.02)
        try session.setActive(true)
        grantedSampleRate = session.sampleRate
    }

    private func buildEngine() throws {
        let engine = AVAudioEngine()
        let inputNode = engine.inputNode
        // Do NOT call setVoiceProcessingEnabled(true) — kills AGC-free capture.

        let hwFormat = inputNode.outputFormat(forBus: 0)

        // Mono mixer node so we always process a single channel.
        let mixerNode = AVAudioMixerNode()
        engine.attach(mixerNode)
        let monoFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                       sampleRate: hwFormat.sampleRate,
                                       channels: 1,
                                       interleaved: true)!
        engine.connect(inputNode, to: mixerNode, format: hwFormat)
        engine.connect(mixerNode, to: engine.mainMixerNode, format: monoFormat)

        // Real-time tap — NO allocation inside the closure.
        inputNode.installTap(onBus: 0,
                             bufferSize: 4096,
                             format: hwFormat) { [weak self] buffer, _ in
            self?.handleAudioBuffer(buffer)
        }

        try engine.start()
        audioEngine = engine
    }

    // Called on real-time audio thread — dispatch work immediately.
    private func handleAudioBuffer(_ buffer: AVAudioPCMBuffer) {
        // Retain the buffer by copying the channel data pointer; dispatch for processing.
        guard let channelData = buffer.floatChannelData else { return }
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)

        // Copy first channel into a heap-allocated array for safe async use.
        var samples = [Float](repeating: 0, count: frameCount)
        for i in 0 ..< frameCount {
            // Average across channels if stereo.
            var sum: Float = 0
            for ch in 0 ..< channelCount {
                sum += channelData[ch][i]
            }
            samples[i] = sum / Float(channelCount)
        }

        processingQueue.async { [weak self] in
            self?.processSamples(samples)
        }
    }

    private func processSamples(_ samples: [Float]) {
        // ---- Level / clip detection (CassetteDSP.LevelMeter) ----------------
        levelMeter.push(samples)
        let rmsDb = levelMeter.rmsDB
        let clipping = levelMeter.isClipping

        // ---- FFT for waterfall (CassetteDSP.WaterfallProcessor) -------------
        // Drain any newly-completed rows. Each row is `binCount` floats in
        // [0, 1]; the WaterfallView consumes a -96…0 dBFS scale, so map back.
        waterfall.push(samples)
        let newRows = waterfall.drainRows().map { row -> [Float] in
            row.map { $0 * 96 - 96 }   // [0,1] → [-96, 0] dBFS-equivalent
        }

        // ---- Write to file if recording (from this queue) -------------------
        // Writing is done back on main thread to avoid data races on audioFile.
        let fileCopy = audioFile
        if let file = fileCopy {
            let frameCount = AVAudioFrameCount(samples.count)
            if let buf = AVAudioPCMBuffer(
                pcmFormat: AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                         sampleRate: file.processingFormat.sampleRate,
                                         channels: 1,
                                         interleaved: true)!,
                frameCapacity: frameCount
            ) {
                buf.frameLength = frameCount
                if let ptr = buf.floatChannelData?[0] {
                    samples.withUnsafeBufferPointer { src in
                        ptr.initialize(from: src.baseAddress!, count: samples.count)
                    }
                }
                try? file.write(from: buf)
            }
        }

        // ---- Publish to main thread -----------------------------------------
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.levelDb = rmsDb
            self.isClipping = clipping
            guard !newRows.isEmpty else { return }
            var rows = self.waterfallRows
            rows.append(contentsOf: newRows)
            if rows.count > self.maxWaterfallRows {
                rows.removeFirst(rows.count - self.maxWaterfallRows)
            }
            self.waterfallRows = rows
        }
    }

    private func makeOutputURL() throws -> URL {
        let docs = try FileManager.default.url(for: .documentDirectory,
                                                in: .userDomainMask,
                                                appropriateFor: nil,
                                                create: true)
        let ts = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
            .replacingOccurrences(of: ".", with: "-")
        return docs.appendingPathComponent("capture_\(ts).wav")
    }

    private func startElapsedTimer() {
        elapsedTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            guard let self, let start = self.startDate else { return }
            Task { @MainActor in
                self.elapsedSeconds = Date().timeIntervalSince(start)
            }
        }
    }

    private func stopElapsedTimer() {
        elapsedTimer?.invalidate()
        elapsedTimer = nil
    }
}
