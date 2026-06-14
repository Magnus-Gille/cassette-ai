import SwiftUI
import AVFoundation

// ---------------------------------------------------------------------------
// TestSetupView — guided Stage-A channel calibration flow.
//
// Flow:
//   1. Explain: play calibration.wav from your stereo / phone speaker.
//   2. Capture ~30 s via CaptureEngine.
//   3. POST /api/setup-test → receive SetupTestResult.
//   4. Render tier badges (Robust / Turbo / Moonshot) + advice + raw metrics.
// ---------------------------------------------------------------------------

struct TestSetupView: View {
    @EnvironmentObject private var settings: AppSettings
    @StateObject private var engine = CaptureEngine()
    @State private var phase: Phase = .explain
    @State private var testResult: SetupTestResult?
    @State private var error: String?
    @State private var capturedURL: URL?

    enum Phase {
        case explain, calibrating, capturing, analysing, results, error
    }

    var body: some View {
        ZStack {
            Color.chassisBlack.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 0) {
                    // ---- Top header bar ------------------------------------
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("TEST SETUP")
                                .font(.system(size: 18, weight: .black, design: .monospaced))
                                .foregroundColor(.amber)
                                .tracking(3)
                            Text("STAGE A — CHANNEL ONLY")
                                .font(.monoDigits(10))
                                .foregroundColor(.labelTertiary)
                                .tracking(2)
                        }
                        Spacer()
                        PhaseIndicator(phase: phase)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, 16)

                    switch phase {
                    case .explain:     explainPhase
                    case .calibrating: calibratingPhase
                    case .capturing:   capturingPhase
                    case .analysing:   analysingPhase
                    case .results:     if let r = testResult { resultsPhase(r) }
                    case .error:       errorPhase
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 40)
            }
        }
    }

    // -------------------------------------------------------------------------
    // MARK: - Phase views
    // -------------------------------------------------------------------------

    private var explainPhase: some View {
        VStack(alignment: .leading, spacing: 20) {
            PanelCard {
                VStack(alignment: .leading, spacing: 12) {
                    Label("WHAT IS THIS?", systemImage: "info.circle")
                        .font(.monoDigits(12))
                        .foregroundColor(.amber)
                        .tracking(1)
                    Text("Stage A grades your **speaker + room + microphone** path. Play the calibration tone from your stereo or the phone's own speaker while this app listens.")
                        .font(.monoDigits(13))
                        .foregroundColor(.labelSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Stage A **cannot** measure tape flutter or deck health. Those are measured automatically from the sounder leader on your first real tape play.")
                        .font(.monoDigits(12))
                        .foregroundColor(.labelTertiary)
                        .italic()
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            PanelCard {
                VStack(alignment: .leading, spacing: 14) {
                    Label("HOW TO RUN THE TEST", systemImage: "list.number")
                        .font(.monoDigits(12))
                        .foregroundColor(.amber)
                        .tracking(1)

                    StepRow(number: "1", text: "Play the calibration tone from your speaker or stereo. You can use the backend link below, or an AirDropped copy.")
                    StepRow(number: "2", text: "Tap START CAPTURE below. Hold the phone near the speaker, same position you'd use to play a tape.")
                    StepRow(number: "3", text: "Wait ~30 seconds, then tap STOP & GRADE.")
                }
            }

            if let url = settings.resolvedBackendURL {
                HStack(spacing: 10) {
                    Image(systemName: "link")
                        .foregroundColor(.amberDim)
                    Text(url.appendingPathComponent("api/calibration").absoluteString)
                        .font(.monoDigits(11))
                        .foregroundColor(.labelTertiary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                .padding(12)
                .background(Color.panelMid)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            Button {
                Task { await beginCapture() }
            } label: {
                HStack {
                    Image(systemName: "mic.circle.fill")
                    Text("START CAPTURE")
                        .tracking(2)
                }
                .font(.monoDigits(15, weight: .bold))
                .foregroundColor(.chassisBlack)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(Color.amber)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)
            .padding(.top, 4)
        }
    }

    private var calibratingPhase: some View {
        VStack(spacing: 20) {
            Spacer(minLength: 20)
            ProgressView()
                .tint(.amber)
                .scaleEffect(1.5)
            Text("Activating microphone…")
                .font(.monoDigits(13))
                .foregroundColor(.labelSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
    }

    private var capturingPhase: some View {
        VStack(spacing: 20) {
            // Live level
            VStack(spacing: 10) {
                WaterfallView(rows: engine.waterfallRows)
                    .frame(height: 160)
                    .clipShape(RoundedRectangle(cornerRadius: 8))

                HStack(spacing: 12) {
                    Text("IN")
                        .font(.monoDigits(10))
                        .foregroundColor(.labelTertiary)
                        .frame(width: 20)
                    VUBar(level: normalizedLevel, isClipping: engine.isClipping, height: 10)
                    Text(String(format: "%+.1f", engine.levelDb))
                        .font(.monoDigits(13, weight: .medium))
                        .foregroundColor(engine.isClipping ? .warningRed : .amber)
                        .frame(width: 50, alignment: .trailing)
                        .monospacedDigit()
                    Text("dBFS")
                        .font(.monoDigits(10))
                        .foregroundColor(.labelTertiary)
                }
            }
            .padding(16)
            .background(Color.panelDark)
            .clipShape(RoundedRectangle(cornerRadius: 10))

            // Elapsed
            ElapsedCaptureBadge(seconds: engine.elapsedSeconds)

            // Stop button
            Button {
                stopAndAnalyse()
            } label: {
                HStack {
                    Image(systemName: "stop.circle.fill")
                    Text("STOP & GRADE")
                        .tracking(2)
                }
                .font(.monoDigits(15, weight: .bold))
                .foregroundColor(.chassisBlack)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(Color.amber)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)
        }
    }

    private var analysingPhase: some View {
        VStack(spacing: 20) {
            Spacer(minLength: 40)
            ZStack {
                Circle()
                    .stroke(Color.amber.opacity(0.20), lineWidth: 3)
                    .frame(width: 90, height: 90)
                ProgressView()
                    .tint(.amber)
                    .scaleEffect(1.8)
            }
            Text("ANALYSING…")
                .font(.monoDigits(14))
                .foregroundColor(.amber)
                .tracking(3)
            Text("Measuring SNR, noise floor, and carrier health")
                .font(.monoDigits(11))
                .foregroundColor(.labelTertiary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 40)
    }

    private func resultsPhase(_ r: SetupTestResult) -> some View {
        VStack(alignment: .leading, spacing: 16) {

            // ---- Tier badges -----------------------------------------------
            PanelCard {
                VStack(alignment: .leading, spacing: 12) {
                    Text("TIER VERDICT")
                        .font(.monoDigits(10))
                        .foregroundColor(.labelTertiary)
                        .tracking(2)

                    TierBadge(
                        tier: "ROBUST  ~560–930 bps",
                        status: verdictStatus(r.robust),
                        advice: r.robust?.advice
                    )
                    TierBadge(
                        tier: "TURBO   ~1.5–2.5 kbps",
                        status: verdictStatus(r.turbo),
                        advice: r.turbo?.advice
                    )
                    TierBadge(
                        tier: "MOONSHOT ~4–5 kbps",
                        status: verdictStatus(r.moonshot),
                        advice: r.moonshot?.advice
                    )

                    Text("⚠ Stage A grades speaker + room only. Deck flutter graded on first real tape play.")
                        .font(.monoDigits(11))
                        .foregroundColor(.labelTertiary)
                        .italic()
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 4)
                }
            }

            // ---- Raw metrics -----------------------------------------------
            DisclosureGroup {
                VStack(spacing: 10) {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                        GaugeTile(label: "SNR MED",
                                  value: String(format: "%.1f", r.snrDbMedian),
                                  unit: "dB")
                        GaugeTile(label: "SNR P10",
                                  value: String(format: "%.1f", r.snrDbP10),
                                  unit: "dB")
                        GaugeTile(label: "NOISE FLOOR",
                                  value: String(format: "%.1f", r.noiseFloorDbfs),
                                  unit: "dBFS")
                        GaugeTile(label: "NULL FRAC",
                                  value: String(format: "%.3f", r.fracBelow8db),
                                  unit: "")
                        GaugeTile(label: "LOSSLESS",
                                  value: r.captureLossless ? "YES" : "NO",
                                  unit: "",
                                  accent: r.captureLossless ? .signalGreen : .warningRed)
                    }
                }
                .padding(.top, 10)
            } label: {
                Text("RAW METRICS")
                    .font(.monoDigits(11))
                    .foregroundColor(.labelSecondary)
                    .tracking(1.5)
            }
            .tint(.amber)
            .padding(.horizontal, 4)

            // ---- Re-test button -------------------------------------------
            Button {
                phase = .explain
                testResult = nil
                engine.stopMonitoring()
            } label: {
                HStack {
                    Image(systemName: "arrow.counterclockwise")
                    Text("RUN TEST AGAIN")
                        .tracking(2)
                }
                .font(.monoDigits(13, weight: .semibold))
                .foregroundColor(.amber)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.amberDim, lineWidth: 1.5))
            }
            .buttonStyle(.plain)
        }
    }

    private var errorPhase: some View {
        VStack(spacing: 20) {
            Spacer(minLength: 40)
            Image(systemName: "xmark.octagon")
                .font(.system(size: 44))
                .foregroundColor(.warningRed)
            Text(error ?? "Something went wrong.")
                .font(.monoDigits(13))
                .foregroundColor(.warningRed)
                .multilineTextAlignment(.center)
            Button("TRY AGAIN") {
                phase = .explain
                error = nil
            }
            .font(.monoDigits(13, weight: .semibold))
            .foregroundColor(.chassisBlack)
            .padding(.horizontal, 28)
            .padding(.vertical, 12)
            .background(Color.amber)
            .clipShape(Capsule())
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity)
    }

    // -------------------------------------------------------------------------
    // MARK: - Logic
    // -------------------------------------------------------------------------

    private func beginCapture() async {
        phase = .calibrating
        await engine.startMonitoring()
        engine.startRecording()
        phase = .capturing
    }

    private func stopAndAnalyse() {
        engine.stopRecording()
        capturedURL = engine.fileURL
        engine.stopMonitoring()
        phase = .analysing
        Task { await runAnalysis() }
    }

    private func runAnalysis() async {
        guard let url = capturedURL,
              let backendURL = settings.resolvedBackendURL else {
            phase = .error
            error = "No capture or invalid backend URL."
            return
        }
        let client = BackendClient(baseURL: backendURL)
        do {
            let result = try await client.submitSetupTest(wavURL: url)
            testResult = result
            phase = .results
        } catch {
            self.error = error.localizedDescription
            phase = .error
        }
    }

    private func verdictStatus(_ v: SetupTestResult.Verdict?) -> TierBadge.Status {
        guard let v else { return .unknown }
        if v.pass { return .pass }
        if v.marginal { return .marginal }
        return .fail
    }

    private var normalizedLevel: Float {
        let clamped = max(-96, min(0, engine.levelDb))
        return (clamped + 96) / 96
    }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

private struct StepRow: View {
    let number: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number)
                .font(.monoDigits(13, weight: .bold))
                .foregroundColor(.amber)
                .frame(width: 20)
            Text(text)
                .font(.monoDigits(13))
                .foregroundColor(.labelSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct ElapsedCaptureBadge: View {
    let seconds: Double

    var body: some View {
        let target = 30.0
        let progress = min(seconds / target, 1.0)
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .stroke(Color.panelMid, lineWidth: 4)
                    .frame(width: 48, height: 48)
                Circle()
                    .trim(from: 0, to: progress)
                    .stroke(Color.amber, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                    .frame(width: 48, height: 48)
                    .rotationEffect(.degrees(-90))
                    .animation(.linear(duration: 0.1), value: progress)
                Text(String(format: "%.0f", seconds))
                    .font(.monoDigits(14, weight: .medium))
                    .foregroundColor(.amber)
                    .monospacedDigit()
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("RECORDING")
                    .font(.monoDigits(12))
                    .foregroundColor(.labelSecondary)
                    .tracking(2)
                Text("Target 30 s — stop when ready")
                    .font(.monoDigits(10))
                    .foregroundColor(.labelTertiary)
            }
        }
        .padding(14)
        .background(Color.panelDark)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

private struct PhaseIndicator: View {
    let phase: TestSetupView.Phase

    private var label: String {
        switch phase {
        case .explain:     return "READY"
        case .calibrating: return "STARTING"
        case .capturing:   return "LISTENING"
        case .analysing:   return "ANALYSING"
        case .results:     return "DONE"
        case .error:       return "ERROR"
        }
    }

    private var color: Color {
        switch phase {
        case .explain:     return .labelTertiary
        case .calibrating: return .amber
        case .capturing:   return .warningRed
        case .analysing:   return .amber
        case .results:     return .signalGreen
        case .error:       return .warningRed
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            if phase == .capturing {
                Circle()
                    .fill(Color.warningRed)
                    .frame(width: 7, height: 7)
            }
            Text(label)
                .font(.monoDigits(11))
                .foregroundColor(color)
                .tracking(1.5)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Color.panelMid)
        .clipShape(Capsule())
    }
}
