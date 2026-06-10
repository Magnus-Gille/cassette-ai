import SwiftUI

// ---------------------------------------------------------------------------
// DecodeView — uploads captured WAV, polls for job completion, shows the
// channel metrics, per-rung results, and the glorious boot moment.
// ---------------------------------------------------------------------------

struct DecodeView: View {
    let fileURL: URL
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    @State private var phase: Phase = .idle
    @State private var jobId: String?
    @State private var pollJob: DecodeJob?
    @State private var result: DecodeResult?
    @State private var errorMsg: String?
    @State private var progress: Double = 0
    @State private var currentStage: String = "Preparing…"

    enum Phase {
        case idle, uploading, polling, done, error
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.chassisBlack.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 20) {
                        switch phase {
                        case .idle:
                            startPrompt
                        case .uploading, .polling:
                            decodeProgress
                        case .done:
                            if let r = result {
                                decodeDone(r)
                            }
                        case .error:
                            errorView
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 40)
                }
            }
            .navigationTitle("DECODE")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("CLOSE") { dismiss() }
                        .font(.monoDigits(13))
                        .foregroundColor(.amber)
                }
            }
            .task { await startDecode() }
        }
    }

    // -------------------------------------------------------------------------
    // MARK: - Phase views
    // -------------------------------------------------------------------------

    private var startPrompt: some View {
        VStack(spacing: 16) {
            Spacer(minLength: 60)
            ProgressView()
                .tint(.amber)
            Text("Initialising…")
                .font(.monoDigits(14))
                .foregroundColor(.labelSecondary)
        }
    }

    private var decodeProgress: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 30)
            // Big pulsing tape reel icon
            ZStack {
                Circle()
                    .stroke(Color.amber.opacity(0.18), lineWidth: 2)
                    .frame(width: 100, height: 100)
                Circle()
                    .trim(from: 0, to: progress)
                    .stroke(Color.amber, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    .frame(width: 100, height: 100)
                    .rotationEffect(.degrees(-90))
                    .animation(.linear(duration: 0.3), value: progress)

                Image(systemName: "waveform.circle")
                    .font(.system(size: 40))
                    .foregroundColor(.amber)
            }

            Text(currentStage.uppercased())
                .font(.monoDigits(13, weight: .semibold))
                .foregroundColor(.amber)
                .tracking(2)

            if let job = pollJob {
                StageRowList(stage: job.stage ?? "", progress: job.progress ?? 0)
            }

            Text(fileURL.lastPathComponent)
                .font(.monoDigits(10))
                .foregroundColor(.labelTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .padding(.top, 40)
    }

    private func decodeDone(_ r: DecodeResult) -> some View {
        VStack(spacing: 20) {
            // ---- Channel gauges -------------------------------------------
            PanelCard {
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader("CHANNEL METRICS")
                    LazyVGrid(columns: [
                        GridItem(.flexible()), GridItem(.flexible())
                    ], spacing: 10) {
                        GaugeTile(label: "SNR MED",
                                  value: String(format: "%.1f", r.snrDbMedian ?? 0),
                                  unit: "dB",
                                  accent: snrColor(r.snrDbMedian ?? 0))
                        GaugeTile(label: "SNR P10",
                                  value: String(format: "%.1f", r.snrDbP10 ?? 0),
                                  unit: "dB",
                                  accent: snrColor(r.snrDbP10 ?? 0))
                        GaugeTile(label: "NOISE",
                                  value: String(format: "%.1f", r.noiseFloorDbfs ?? 0),
                                  unit: "dBFS")
                        GaugeTile(label: "FLUTTER",
                                  value: r.flutterWrmsPct.map { String(format: "%.2f", $0) } ?? "—",
                                  unit: "%",
                                  accent: flutterColor(r.flutterWrmsPct))
                        GaugeTile(label: "CLOCK",
                                  value: String(format: "%.4f", r.clockRatio ?? 1.0),
                                  unit: "×")
                    }
                }
            }

            // ---- Rung results ---------------------------------------------
            PanelCard {
                VStack(alignment: .leading, spacing: 10) {
                    SectionHeader("DECODE RUNGS")
                    ForEach(r.rungResults ?? []) { rung in
                        RungResultRow(rung: rung)
                    }
                }
            }

            // ---- Boot moment ----------------------------------------------
            if let text = r.payloadText, !text.isEmpty {
                BootMomentView(text: text)
            } else {
                PanelCard {
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark.seal.fill")
                            .foregroundColor(.signalGreen)
                            .font(.system(size: 22))
                        Text("Decode complete — no text payload.")
                            .font(.monoDigits(13))
                            .foregroundColor(.labelSecondary)
                    }
                }
            }
        }
    }

    private var errorView: some View {
        VStack(spacing: 20) {
            Spacer(minLength: 60)
            Image(systemName: "xmark.octagon")
                .font(.system(size: 48))
                .foregroundColor(.warningRed)
            Text(errorMsg ?? "Unknown error")
                .font(.monoDigits(14))
                .foregroundColor(.warningRed)
                .multilineTextAlignment(.center)
            Button("RETRY") { Task { await startDecode() } }
                .font(.monoDigits(13, weight: .semibold))
                .foregroundColor(.chassisBlack)
                .padding(.horizontal, 28)
                .padding(.vertical, 12)
                .background(Color.amber)
                .clipShape(Capsule())
                .buttonStyle(.plain)
        }
    }

    // -------------------------------------------------------------------------
    // MARK: - Logic
    // -------------------------------------------------------------------------

    private func startDecode() async {
        guard let backendURL = settings.resolvedBackendURL else {
            phase = .error
            errorMsg = "Invalid backend URL. Check Settings."
            return
        }
        let client = BackendClient(baseURL: backendURL)
        phase = .uploading
        currentStage = "Uploading capture…"
        progress = 0.05

        do {
            let jid = try await client.submitDecode(wavURL: fileURL, tapeId: "master8")
            jobId = jid
            phase = .polling
            try await pollUntilDone(client: client, jobId: jid)
        } catch {
            phase = .error
            errorMsg = error.localizedDescription
        }
    }

    private func pollUntilDone(client: BackendClient, jobId: String) async throws {
        let stageOrder = ["saving", "sync", "channel", "demod", "fec", "unpack", "done"]
        while true {
            try await Task.sleep(nanoseconds: 1_200_000_000) // 1.2 s
            let job = try await client.pollJob(jobId)
            pollJob = job

            let stageName = job.stage ?? job.status
            currentStage = stageName.replacingOccurrences(of: "_", with: " ").uppercased()
            let stageIdx = stageOrder.firstIndex(of: stageName) ?? 0
            progress = Double(stageIdx + 1) / Double(stageOrder.count)

            if job.status == "done", let r = job.result {
                result = r
                phase = .done
                return
            }
            if job.status == "error" {
                throw BackendError.backendUnreachable(job.error ?? "Decode failed")
            }
        }
    }

    // ---- Colour helpers ----
    private func snrColor(_ db: Double) -> Color {
        if db >= 36 { return .signalGreen }
        if db >= 28 { return .amber }
        return .warningRed
    }

    private func flutterColor(_ pct: Double?) -> Color {
        guard let pct else { return .labelSecondary }
        if pct <= 0.45 { return .signalGreen }
        if pct <= 0.7  { return .marginalYellow }
        return .warningRed
    }
}

// ---------------------------------------------------------------------------
// Stage progress rows
// ---------------------------------------------------------------------------

private struct StageRowList: View {
    let stage: String
    let progress: Double

    private let stages = ["saving", "sync", "channel", "demod", "fec", "unpack"]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(stages, id: \.self) { s in
                HStack(spacing: 10) {
                    let isDone = stageIndex(s) < stageIndex(stage)
                    let isCurrent = s == stage
                    Image(systemName: isDone ? "checkmark.circle.fill" : (isCurrent ? "circle.dotted" : "circle"))
                        .font(.system(size: 14))
                        .foregroundColor(isDone ? .signalGreen : (isCurrent ? .amber : .labelTertiary))
                    Text(s.uppercased())
                        .font(.monoDigits(12))
                        .foregroundColor(isDone ? .signalGreen : (isCurrent ? .amber : .labelTertiary))
                        .tracking(1.5)
                }
            }
        }
        .padding(.horizontal, 20)
    }

    private func stageIndex(_ s: String) -> Int {
        stages.firstIndex(of: s) ?? 99
    }
}

private struct RungResultRow: View {
    let rung: DecodeResult.RungResult

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: rung.passed ? "checkmark.circle.fill" : "xmark.circle")
                .foregroundColor(rung.passed ? .signalGreen : .warningRed)
                .font(.system(size: 16))
            VStack(alignment: .leading, spacing: 2) {
                Text(rung.label.uppercased())
                    .font(.monoDigits(12, weight: .semibold))
                    .foregroundColor(.labelPrimary)
                Text("\(rung.bps) bps")
                    .font(.monoDigits(10))
                    .foregroundColor(.labelSecondary)
            }
            Spacer()
            Text("\(rung.crcPassed)/\(rung.crcTotal) CRC")
                .font(.monoDigits(11))
                .foregroundColor(rung.passed ? .signalGreen : .labelTertiary)
                .monospacedDigit()
        }
        .padding(.vertical, 4)
    }
}

private struct SectionHeader: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(.monoDigits(10))
            .foregroundColor(.labelTertiary)
            .tracking(2)
            .textCase(.uppercase)
    }
}

// ---------------------------------------------------------------------------
// BootMomentView — the climactic CRT terminal reveal.
//
// Characters type out one-by-one at ~28 chars/sec on a phosphor-green
// monospaced terminal. A blinking cursor follows the last character.
// The background uses a subtle scanline effect to sell the CRT illusion.
// ---------------------------------------------------------------------------

struct BootMomentView: View {
    let text: String

    @State private var displayedCount: Int = 0
    @State private var isTyping = false
    private let charsPerSecond: Double = 28

    private var displayedText: String {
        String(text.prefix(displayedCount))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header bar
            HStack {
                Circle().fill(Color.warningRed).frame(width: 9, height: 9)
                Circle().fill(Color.marginalYellow).frame(width: 9, height: 9)
                Circle().fill(Color.signalGreen).frame(width: 9, height: 9)
                Spacer()
                Text("PAYLOAD RUNTIME · BOOT SEQUENCE")
                    .font(.monoDigits(9))
                    .foregroundColor(.labelTertiary)
                    .tracking(1.5)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color.black.opacity(0.6))

            Divider().background(Color.white.opacity(0.08))

            // Terminal body
            ZStack(alignment: .topLeading) {
                // Scanline overlay
                ScanlineOverlay()
                    .allowsHitTesting(false)

                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(displayedText)
                                .font(.system(size: 14, weight: .regular, design: .monospaced))
                                .foregroundColor(.phosphorGreen)
                                .textSelection(.enabled)
                                .lineSpacing(4)
                            if isTyping || displayedCount < text.count {
                                HStack(spacing: 0) {
                                    BlinkingCursor()
                                }
                            }
                        }
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                        .id("bottom")
                    }
                    .onChange(of: displayedCount) { _, _ in
                        withAnimation(.none) {
                            proxy.scrollTo("bottom", anchor: .bottom)
                        }
                    }
                }
            }
            .frame(minHeight: 260)
            .background(
                LinearGradient(
                    colors: [Color(red: 0, green: 0.05, blue: 0),
                             Color.black],
                    startPoint: .top, endPoint: .bottom
                )
            )

            // Footer — completion status
            HStack {
                if displayedCount >= text.count {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.phosphorGreen)
                        .font(.system(size: 12))
                    Text("PAYLOAD RECEIVED · \(text.count) BYTES")
                        .font(.monoDigits(10))
                        .foregroundColor(.phosphorDim)
                        .tracking(1.5)
                } else {
                    ProgressView(value: Double(displayedCount), total: Double(text.count))
                        .tint(.phosphorGreen)
                        .frame(height: 3)
                }
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color.black.opacity(0.4))
        }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color.phosphorGreen.opacity(0.25), lineWidth: 1.5)
        )
        .shadow(color: Color.phosphorGreen.opacity(0.12), radius: 20)
        .onAppear { startTyping() }
    }

    private func startTyping() {
        guard !isTyping else { return }
        isTyping = true
        let interval = 1.0 / charsPerSecond

        // Use a recursive dispatch approach: lightweight, no timer accumulation.
        func typeNext() {
            guard displayedCount < text.count else {
                isTyping = false
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + interval) {
                displayedCount += 1
                typeNext()
            }
        }
        typeNext()
    }
}

private struct ScanlineOverlay: View {
    var body: some View {
        GeometryReader { geo in
            Canvas { ctx, size in
                let lineH: CGFloat = 3
                var y: CGFloat = 0
                while y < size.height {
                    let rect = CGRect(x: 0, y: y, width: size.width, height: 1)
                    ctx.fill(Path(rect), with: .color(.black.opacity(0.18)))
                    y += lineH
                }
            }
        }
    }
}
