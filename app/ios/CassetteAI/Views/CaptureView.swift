import SwiftUI
import AVFoundation

// ---------------------------------------------------------------------------
// CaptureView — the hero capture screen.
//
// Layout:
//   ┌──────────────────────────────────────────┐
//   │  Header: CASSETTE-AI + clock             │
//   │  Waterfall (scrolling FFT)               │
//   │  Level meter + CLIP indicator            │
//   │  Status badges (LOCKED / SNR / FLUTTER)  │
//   │  Big RECORD button                       │
//   │  After-stop card (chirp status + decode) │
//   └──────────────────────────────────────────┘
// ---------------------------------------------------------------------------

struct CaptureView: View {
    @EnvironmentObject private var engine: CaptureEngine
    @EnvironmentObject private var settings: AppSettings
    @State private var showDecodeSheet = false
    @State private var capturedFileURL: URL?
    @State private var permissionDenied = false

    // Level normalisation: -96 dBFS → 0, 0 dBFS → 1
    private var normalizedLevel: Float {
        let clamped = max(-96, min(0, engine.levelDb))
        return (clamped + 96) / 96
    }

    var body: some View {
        ZStack {
            Color.chassisBlack.ignoresSafeArea()

            VStack(spacing: 0) {
                // ---- Header ---------------------------------------------------
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("CASSETTE·AI")
                            .font(.system(size: 20, weight: .black, design: .monospaced))
                            .foregroundColor(.amber)
                            .tracking(3)
                        Text("CAPTURE ENGINE")
                            .font(.monoDigits(10))
                            .foregroundColor(.labelTertiary)
                            .tracking(2)
                    }
                    Spacer()
                    if engine.engineState == .recording {
                        ElapsedClock(seconds: engine.elapsedSeconds)
                    } else {
                        sampleRateLabel
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 10)

                // ---- Waterfall -----------------------------------------------
                WaterfallView(rows: engine.waterfallRows)
                    .frame(maxWidth: .infinity)
                    .frame(height: 220)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .padding(.horizontal, 16)

                // ---- Level meter ---------------------------------------------
                VStack(spacing: 8) {
                    HStack(spacing: 12) {
                        Text("IN")
                            .font(.monoDigits(10))
                            .foregroundColor(.labelTertiary)
                            .frame(width: 20)
                        VUBar(level: normalizedLevel, isClipping: engine.isClipping)
                        Text(String(format: "%+.1f", engine.levelDb))
                            .font(.monoDigits(13, weight: .medium))
                            .foregroundColor(engine.isClipping ? .warningRed : .amber)
                            .frame(width: 48, alignment: .trailing)
                            .monospacedDigit()
                        Text("dBFS")
                            .font(.monoDigits(10))
                            .foregroundColor(.labelTertiary)
                    }

                    if engine.isClipping {
                        HStack(spacing: 6) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(.warningRed)
                                .font(.system(size: 13))
                            Text("CLIPPING — lower input level or move phone back")
                                .font(.monoDigits(11))
                                .foregroundColor(.warningRed)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Color.warningRed.opacity(0.12))
                        .clipShape(Capsule())
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)

                // ---- Status strip -------------------------------------------
                HStack(spacing: 12) {
                    StatusPill(
                        label: "SYNC",
                        value: engine.engineState == .idle ? "OFFLINE" : "LISTENING",
                        color: engine.engineState != .idle ? .amber : .labelTertiary
                    )
                    StatusPill(
                        label: "SR",
                        value: engine.grantedSampleRate > 0
                            ? "\(Int(engine.grantedSampleRate / 1000))k"
                            : "—",
                        color: .labelSecondary
                    )
                    if settings.labMode {
                        StatusPill(label: "LAB", value: "ON", color: .phosphorGreen)
                    }
                    Spacer()
                }
                .padding(.horizontal, 20)

                Spacer()

                // ---- Error notice -------------------------------------------
                if let err = engine.errorMessage {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.circle")
                            .foregroundColor(.warningRed)
                        Text(err)
                            .font(.monoDigits(12))
                            .foregroundColor(.warningRed)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(12)
                    .background(Color.warningRed.opacity(0.10))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .padding(.horizontal, 20)
                    .padding(.bottom, 8)
                }

                // ---- After-stop card ----------------------------------------
                if let url = capturedFileURL, engine.engineState != .recording {
                    PostCaptureCard(fileURL: url, onDecode: {
                        showDecodeSheet = true
                    })
                    .padding(.horizontal, 16)
                    .padding(.bottom, 12)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                // ---- Record / Stop button ------------------------------------
                RecordButton(
                    state: engine.engineState,
                    onTap: handleRecordTap
                )
                .padding(.bottom, 24)
            }
        }
        .sheet(isPresented: $showDecodeSheet) {
            if let url = capturedFileURL {
                DecodeView(fileURL: url)
                    .environmentObject(settings)
            }
        }
        .task {
            await engine.startMonitoring()
        }
        .onDisappear {
            if engine.engineState == .recording {
                engine.stopRecording()
            }
        }
    }

    // -------------------------------------------------------------------------

    private var sampleRateLabel: some View {
        Text(engine.grantedSampleRate > 0
             ? "\(Int(engine.grantedSampleRate / 1000))kHz MEAS"
             : "STANDBY")
            .font(.monoDigits(11))
            .foregroundColor(.labelTertiary)
            .tracking(1)
    }

    private func handleRecordTap() {
        switch engine.engineState {
        case .idle:
            Task { await engine.startMonitoring() }
        case .monitoring:
            capturedFileURL = nil
            engine.startRecording()
        case .recording:
            engine.stopRecording()
            capturedFileURL = engine.fileURL
        }
    }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

private struct RecordButton: View {
    let state: CaptureEngine.State
    let onTap: () -> Void

    private var label: String {
        switch state {
        case .idle:       return "ACTIVATE"
        case .monitoring: return "RECORD"
        case .recording:  return "STOP"
        }
    }

    private var color: Color {
        switch state {
        case .idle:       return .amber
        case .monitoring: return .warningRed
        case .recording:  return .warningRed
        }
    }

    @State private var pulse = false

    var body: some View {
        Button(action: onTap) {
            ZStack {
                if state == .recording {
                    Circle()
                        .stroke(color.opacity(0.4), lineWidth: 3)
                        .frame(width: 90, height: 90)
                        .scaleEffect(pulse ? 1.35 : 1.0)
                        .opacity(pulse ? 0 : 0.8)
                        .onAppear {
                            withAnimation(.easeOut(duration: 1.1).repeatForever(autoreverses: false)) {
                                pulse = true
                            }
                        }
                }
                Circle()
                    .fill(state == .recording ? Color.warningRed.opacity(0.18) : Color.panelDark)
                    .frame(width: 80, height: 80)
                    .overlay(Circle().strokeBorder(color, lineWidth: 2.5))

                if state == .recording {
                    RoundedRectangle(cornerRadius: 5)
                        .fill(color)
                        .frame(width: 22, height: 22)
                } else {
                    Circle()
                        .fill(color)
                        .frame(width: 28, height: 28)
                }
            }
        }
        .buttonStyle(.plain)
        .overlay(alignment: .bottom) {
            Text(label)
                .font(.monoDigits(11))
                .foregroundColor(color)
                .tracking(2)
                .offset(y: 52)
        }
        .padding(.bottom, 8)
    }
}

private struct ElapsedClock: View {
    let seconds: Double

    private var formatted: String {
        let m = Int(seconds) / 60
        let s = Int(seconds) % 60
        let ds = Int((seconds - Double(Int(seconds))) * 10)
        return String(format: "%02d:%02d.%d", m, s, ds)
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Color.warningRed)
                .frame(width: 7, height: 7)
            Text(formatted)
                .font(.monoDigits(16, weight: .medium))
                .foregroundColor(.warningRed)
                .monospacedDigit()
        }
    }
}

private struct StatusPill: View {
    let label: String
    let value: String
    var color: Color = .amber

    var body: some View {
        HStack(spacing: 5) {
            Text(label)
                .font(.monoDigits(9))
                .foregroundColor(.labelTertiary)
                .tracking(1.5)
            Text(value)
                .font(.monoDigits(11, weight: .semibold))
                .foregroundColor(color)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(Color.panelMid)
        .clipShape(Capsule())
    }
}

private struct PostCaptureCard: View {
    let fileURL: URL
    let onDecode: () -> Void
    @State private var isSharing = false

    var body: some View {
        PanelCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.signalGreen)
                        .font(.system(size: 18))
                    Text("Capture saved")
                        .font(.monoDigits(14, weight: .semibold))
                        .foregroundColor(.labelPrimary)
                }
                Text(fileURL.lastPathComponent)
                    .font(.monoDigits(11))
                    .foregroundColor(.labelSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)

                HStack(spacing: 10) {
                    Button(action: onDecode) {
                        Label("DECODE ON SERVER", systemImage: "arrow.up.circle.fill")
                            .font(.monoDigits(13, weight: .semibold))
                            .foregroundColor(.chassisBlack)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 10)
                            .background(Color.amber)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)

                    ShareLink(item: fileURL) {
                        Label("SHARE", systemImage: "square.and.arrow.up")
                            .font(.monoDigits(12))
                            .foregroundColor(.amber)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .overlay(Capsule().strokeBorder(Color.amberDim, lineWidth: 1.5))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// WaterfallView — Canvas-based scrolling spectrogram.
// Draws rows from engine.waterfallRows, bottom = newest, top = oldest.
// Frequency axis: 0 Hz (left) → Nyquist (right).
// Color map: black → amber (signal) → white (clipping).
// ---------------------------------------------------------------------------

struct WaterfallView: View {
    let rows: [[Float]]

    var body: some View {
        Canvas { ctx, size in
            guard !rows.isEmpty else {
                ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.panelMid))
                return
            }
            let rowH = size.height / CGFloat(rows.count)
            let binCount = rows[0].count

            for (rowIdx, row) in rows.enumerated() {
                let y = size.height - CGFloat(rowIdx + 1) * rowH
                let colW = size.width / CGFloat(binCount)
                for (binIdx, mag) in row.enumerated() {
                    // Map -96…0 dBFS to 0…1
                    let t = Double(max(0, min(1, (mag + 96) / 96)))
                    let color = spectralColor(t)
                    let rect = CGRect(x: CGFloat(binIdx) * colW, y: y,
                                      width: colW + 0.5, height: rowH + 0.5)
                    ctx.fill(Path(rect), with: .color(color))
                }
            }

            // Frequency tick marks
            let nyquistHz: Double = 24000
            let ticks: [(hz: Double, label: String)] = [
                (300, "300"), (1000, "1k"), (2000, "2k"), (4000, "4k"),
                (8000, "8k"), (11000, "11k")
            ]
            for tick in ticks {
                let x = CGFloat(tick.hz / nyquistHz) * size.width
                let tickPath = Path { p in
                    p.move(to: CGPoint(x: x, y: size.height - 12))
                    p.addLine(to: CGPoint(x: x, y: size.height))
                }
                ctx.stroke(tickPath, with: .color(.white.opacity(0.25)), lineWidth: 0.5)
            }
        }
        .background(Color.black)
    }

    private func spectralColor(_ t: Double) -> Color {
        // 0→black, 0.3→deep-amber, 0.7→bright-amber, 1.0→white
        if t < 0.3 {
            let u = t / 0.3
            return Color(red: u * 0.8, green: u * 0.35, blue: 0)
        } else if t < 0.7 {
            let u = (t - 0.3) / 0.4
            return Color(red: 0.8 + u * 0.2, green: 0.35 + u * 0.27, blue: 0)
        } else {
            let u = (t - 0.7) / 0.3
            return Color(red: 1.0, green: 0.62 + u * 0.38, blue: u)
        }
    }
}
