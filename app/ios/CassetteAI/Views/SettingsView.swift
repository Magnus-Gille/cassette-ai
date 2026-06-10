import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var backendURLDraft: String = ""
    @State private var showAbout = false
    @FocusState private var urlFieldFocused: Bool

    var body: some View {
        ZStack {
            Color.chassisBlack.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 20) {
                    // ---- Header -------------------------------------------
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("SETTINGS")
                                .font(.system(size: 18, weight: .black, design: .monospaced))
                                .foregroundColor(.amber)
                                .tracking(3)
                            Text("SYSTEM CONFIGURATION")
                                .font(.monoDigits(10))
                                .foregroundColor(.labelTertiary)
                                .tracking(2)
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 12)

                    // ---- Backend URL ----------------------------------------
                    PanelCard {
                        VStack(alignment: .leading, spacing: 12) {
                            Label("BACKEND URL", systemImage: "server.rack")
                                .font(.monoDigits(11))
                                .foregroundColor(.amber)
                                .tracking(1)

                            TextField("http://localhost:8765", text: $backendURLDraft)
                                .font(.system(size: 13, weight: .regular, design: .monospaced))
                                .foregroundColor(.labelPrimary)
                                .textFieldStyle(.plain)
                                .keyboardType(.URL)
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                                .focused($urlFieldFocused)
                                .padding(10)
                                .background(Color.panelMid)
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 6)
                                        .strokeBorder(
                                            urlFieldFocused ? Color.amber : Color.white.opacity(0.08),
                                            lineWidth: urlFieldFocused ? 1.5 : 1
                                        )
                                )
                                .onSubmit { commitURL() }

                            HStack(spacing: 8) {
                                Circle()
                                    .fill(backendReachabilityColor)
                                    .frame(width: 7, height: 7)
                                Text(backendStatusText)
                                    .font(.monoDigits(11))
                                    .foregroundColor(.labelTertiary)
                            }

                            if backendURLDraft != settings.backendURL {
                                Button("SAVE") { commitURL() }
                                    .font(.monoDigits(12, weight: .semibold))
                                    .foregroundColor(.chassisBlack)
                                    .padding(.horizontal, 20)
                                    .padding(.vertical, 8)
                                    .background(Color.amber)
                                    .clipShape(Capsule())
                                    .buttonStyle(.plain)
                            }
                        }
                    }
                    .padding(.horizontal, 20)

                    // ---- Capture format (display only) ----------------------
                    PanelCard {
                        VStack(alignment: .leading, spacing: 12) {
                            Label("CAPTURE FORMAT", systemImage: "waveform")
                                .font(.monoDigits(11))
                                .foregroundColor(.amber)
                                .tracking(1)

                            HStack {
                                Text(settings.captureFormat)
                                    .font(.system(size: 13, weight: .medium, design: .monospaced))
                                    .foregroundColor(.labelPrimary)
                                Spacer()
                                Image(systemName: "lock.fill")
                                    .font(.system(size: 12))
                                    .foregroundColor(.labelTertiary)
                            }

                            Text("Fixed at float32 WAV, 48 kHz mono, lossless. Not configurable — changing this would degrade decode accuracy.")
                                .font(.monoDigits(11))
                                .foregroundColor(.labelTertiary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.horizontal, 20)

                    // ---- Lab mode toggle ------------------------------------
                    PanelCard {
                        VStack(alignment: .leading, spacing: 12) {
                            Label("LAB MODE", systemImage: "flask")
                                .font(.monoDigits(11))
                                .foregroundColor(.amber)
                                .tracking(1)

                            Toggle(isOn: $settings.labMode) {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text("Enable lab diagnostics")
                                        .font(.monoDigits(13))
                                        .foregroundColor(.labelPrimary)
                                    Text("Shows extra metrics, export tools, and raw JSON in all views.")
                                        .font(.monoDigits(11))
                                        .foregroundColor(.labelTertiary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            .tint(.amber)

                            if settings.labMode {
                                HStack(spacing: 6) {
                                    Image(systemName: "checkmark.circle.fill")
                                        .foregroundColor(.phosphorGreen)
                                        .font(.system(size: 13))
                                    Text("Lab mode active — extra diagnostics visible in all screens.")
                                        .font(.monoDigits(11))
                                        .foregroundColor(.phosphorGreen)
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 20)

                    // ---- About ---------------------------------------------
                    Button {
                        showAbout = true
                    } label: {
                        HStack {
                            Image(systemName: "info.circle")
                                .foregroundColor(.amber)
                            Text("ABOUT CASSETTE-AI")
                                .font(.monoDigits(13))
                                .foregroundColor(.amber)
                                .tracking(1)
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.system(size: 12))
                                .foregroundColor(.labelTertiary)
                        }
                        .padding(16)
                        .background(Color.panelDark)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 20)

                    Spacer(minLength: 40)
                }
            }
        }
        .sheet(isPresented: $showAbout) { AboutSheet() }
        .onAppear { backendURLDraft = settings.backendURL }
    }

    private var backendReachabilityColor: Color {
        guard URL(string: backendURLDraft) != nil else { return .warningRed }
        return .signalGreen
    }

    private var backendStatusText: String {
        guard URL(string: backendURLDraft) != nil else {
            return "Invalid URL"
        }
        return "Ready"
    }

    private func commitURL() {
        let trimmed = backendURLDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        if URL(string: trimmed) != nil {
            settings.backendURL = trimmed
        }
        urlFieldFocused = false
    }
}

// ---------------------------------------------------------------------------
// AboutSheet
// ---------------------------------------------------------------------------

private struct AboutSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            Color.chassisBlack.ignoresSafeArea()
            VStack(spacing: 24) {
                Spacer(minLength: 16)

                // Logo
                VStack(spacing: 6) {
                    Text("▶◀")
                        .font(.system(size: 48))
                        .foregroundColor(.amber)
                    Text("CASSETTE·AI")
                        .font(.system(size: 28, weight: .black, design: .monospaced))
                        .foregroundColor(.amber)
                        .tracking(4)
                    Text("DATA ON TAPE")
                        .font(.monoDigits(12))
                        .foregroundColor(.labelTertiary)
                        .tracking(3)
                }

                Divider().background(Color.white.opacity(0.08))
                    .padding(.horizontal, 40)

                VStack(alignment: .leading, spacing: 14) {
                    AboutRow(label: "CAPTURE", value: "AVAudioEngine, 48 kHz, float32 WAV")
                    AboutRow(label: "DECODE", value: "Hybrid: on-device front-end + server DSP")
                    AboutRow(label: "MODULATION", value: "DQPSK multi-carrier (master8)")
                    AboutRow(label: "FEC", value: "Reed-Solomon + CRC32")
                    AboutRow(label: "VERSION", value: "0.1.0 (MVP)")
                }
                .padding(.horizontal, 30)

                Spacer()

                Text("The analog dream of digital data.")
                    .font(.system(size: 13, weight: .light, design: .monospaced))
                    .foregroundColor(.labelTertiary)
                    .italic()

                Button("CLOSE") { dismiss() }
                    .font(.monoDigits(14, weight: .semibold))
                    .foregroundColor(.chassisBlack)
                    .padding(.horizontal, 40)
                    .padding(.vertical, 14)
                    .background(Color.amber)
                    .clipShape(Capsule())
                    .buttonStyle(.plain)
                    .padding(.bottom, 30)
            }
        }
    }
}

private struct AboutRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .top) {
            Text(label)
                .font(.monoDigits(10))
                .foregroundColor(.labelTertiary)
                .tracking(1.5)
                .frame(width: 90, alignment: .leading)
            Text(value)
                .font(.monoDigits(12))
                .foregroundColor(.labelSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
