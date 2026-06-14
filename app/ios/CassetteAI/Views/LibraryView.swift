import SwiftUI

// ---------------------------------------------------------------------------
// LibraryView — tape registry + QR-scan deep-link stub.
//
// Fetches manifests for a hardcoded list of known tape IDs (["master8"]).
// Displays each tape's name, tiers/rungs, and rate. QR scan stub explains
// the cassetteai://tape/<id> deep-link scheme.
// ---------------------------------------------------------------------------

struct LibraryView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var manifests: [TapeManifest] = []
    @State private var loading = false
    @State private var error: String?
    @State private var showQRInfo = false

    private let knownTapeIDs = ["master8"]

    var body: some View {
        ZStack {
            Color.chassisBlack.ignoresSafeArea()
            VStack(spacing: 0) {
                // ---- Header -----------------------------------------------
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("LIBRARY")
                            .font(.system(size: 18, weight: .black, design: .monospaced))
                            .foregroundColor(.amber)
                            .tracking(3)
                        Text("REGISTERED TAPES")
                            .font(.monoDigits(10))
                            .foregroundColor(.labelTertiary)
                            .tracking(2)
                    }
                    Spacer()
                    Button {
                        showQRInfo = true
                    } label: {
                        Image(systemName: "qrcode.viewfinder")
                            .font(.system(size: 22))
                            .foregroundColor(.amber)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 16)

                if loading {
                    Spacer()
                    ProgressView()
                        .tint(.amber)
                    Spacer()
                } else if let err = error {
                    errorView(err)
                } else {
                    tapeList
                }
            }
        }
        .sheet(isPresented: $showQRInfo) { QRInfoSheet() }
        .task { await loadManifests() }
    }

    // -------------------------------------------------------------------------

    private var tapeList: some View {
        ScrollView {
            VStack(spacing: 14) {
                if manifests.isEmpty {
                    emptyState
                } else {
                    ForEach(manifests) { manifest in
                        TapeCard(manifest: manifest)
                    }
                }
                Spacer(minLength: 40)
            }
            .padding(.horizontal, 20)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Spacer(minLength: 40)
            Image(systemName: "square.stack.3d.up.slash")
                .font(.system(size: 40))
                .foregroundColor(.labelTertiary)
            Text("No tapes loaded")
                .font(.monoDigits(15, weight: .medium))
                .foregroundColor(.labelSecondary)
            Text("Scan the QR code on a tape's J-card, or verify the backend is reachable.")
                .font(.monoDigits(12))
                .foregroundColor(.labelTertiary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
    }

    private func errorView(_ msg: String) -> some View {
        VStack(spacing: 16) {
            Spacer(minLength: 40)
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 36))
                .foregroundColor(.warningRed)
            Text(msg)
                .font(.monoDigits(13))
                .foregroundColor(.warningRed)
                .multilineTextAlignment(.center)
            Button("RETRY") { Task { await loadManifests() } }
                .font(.monoDigits(12, weight: .semibold))
                .foregroundColor(.chassisBlack)
                .padding(.horizontal, 24)
                .padding(.vertical, 10)
                .background(Color.amber)
                .clipShape(Capsule())
                .buttonStyle(.plain)
            Spacer()
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 20)
    }

    // -------------------------------------------------------------------------

    private func loadManifests() async {
        guard let backendURL = settings.resolvedBackendURL else { return }
        loading = true
        error = nil
        let client = BackendClient(baseURL: backendURL)
        var loaded: [TapeManifest] = []
        for id in knownTapeIDs {
            do {
                let m = try await client.fetchManifest(tapeId: id)
                loaded.append(m)
            } catch {
                // Skip individual failures; backend may not have all manifests yet.
            }
        }
        if loaded.isEmpty && !knownTapeIDs.isEmpty {
            self.error = "Could not load manifests from \(backendURL.host ?? "backend")."
        }
        manifests = loaded
        loading = false
    }
}

// ---------------------------------------------------------------------------
// TapeCard
// ---------------------------------------------------------------------------

private struct TapeCard: View {
    let manifest: TapeManifest

    private var maxBps: Int {
        manifest.rungs.map(\.bps).max() ?? 0
    }

    var body: some View {
        PanelCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(manifest.name.uppercased())
                            .font(.monoDigits(16, weight: .bold))
                            .foregroundColor(.labelPrimary)
                        Text(manifest.id)
                            .font(.monoDigits(10))
                            .foregroundColor(.labelTertiary)
                            .tracking(1.5)
                    }
                    Spacer()
                    // Max rate badge
                    VStack(spacing: 1) {
                        Text(formatBps(maxBps))
                            .font(.monoDigits(20, weight: .semibold))
                            .foregroundColor(.amber)
                            .monospacedDigit()
                        Text("MAX BPS")
                            .font(.monoDigits(8))
                            .foregroundColor(.labelTertiary)
                            .tracking(1.5)
                    }
                }

                if let desc = manifest.description {
                    Text(desc)
                        .font(.monoDigits(12))
                        .foregroundColor(.labelSecondary)
                        .lineLimit(2)
                }

                // Rung list
                VStack(spacing: 4) {
                    ForEach(manifest.rungs) { rung in
                        RungListRow(rung: rung)
                    }
                }

                HStack(spacing: 6) {
                    Image(systemName: "square.stack")
                        .font(.system(size: 12))
                        .foregroundColor(.labelTertiary)
                    Text("\(manifest.rungs.count) RUNGS")
                        .font(.monoDigits(10))
                        .foregroundColor(.labelTertiary)
                        .tracking(1.5)
                }
            }
        }
    }

    private func formatBps(_ bps: Int) -> String {
        if bps >= 1000 {
            return String(format: "%.1fk", Double(bps) / 1000.0)
        }
        return "\(bps)"
    }
}

private struct RungListRow: View {
    let rung: TapeManifest.TapeRung

    private var tierColor: Color {
        switch rung.tier.lowercased() {
        case "moonshot": return .phosphorGreen
        case "turbo":    return .amber
        default:         return .labelSecondary
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(tierColor)
                .frame(width: 6, height: 6)
            Text(rung.label.uppercased())
                .font(.monoDigits(11))
                .foregroundColor(.labelPrimary)
            Spacer()
            Text("\(rung.bps) bps")
                .font(.monoDigits(11))
                .foregroundColor(tierColor)
                .monospacedDigit()
            Text(rung.tier.uppercased())
                .font(.monoDigits(9))
                .foregroundColor(.labelTertiary)
                .tracking(1.5)
                .frame(width: 68, alignment: .trailing)
        }
    }
}

// ---------------------------------------------------------------------------
// QRInfoSheet — explains the deep-link scheme & DataScanner placeholder.
// ---------------------------------------------------------------------------

private struct QRInfoSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            Color.chassisBlack.ignoresSafeArea()
            VStack(spacing: 24) {
                Spacer(minLength: 8)

                // Mock QR frame
                ZStack {
                    RoundedRectangle(cornerRadius: 16)
                        .strokeBorder(Color.amber.opacity(0.6), lineWidth: 2)
                        .frame(width: 200, height: 200)
                    Image(systemName: "qrcode")
                        .font(.system(size: 80))
                        .foregroundColor(.amber.opacity(0.3))
                    // Corner targets
                    CornerTargets()
                }

                VStack(spacing: 10) {
                    Text("SCAN J-CARD QR")
                        .font(.monoDigits(18, weight: .bold))
                        .foregroundColor(.amber)
                        .tracking(2)
                    Text("Each tape's J-card carries a QR code that encodes:")
                        .font(.monoDigits(13))
                        .foregroundColor(.labelSecondary)
                        .multilineTextAlignment(.center)

                    Text("cassetteai://tape/<id>")
                        .font(.system(size: 14, weight: .medium, design: .monospaced))
                        .foregroundColor(.phosphorGreen)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(Color.black)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .overlay(
                            RoundedRectangle(cornerRadius: 6)
                                .strokeBorder(Color.phosphorGreen.opacity(0.4), lineWidth: 1)
                        )

                    Text("Scanning opens the tape in Library and pre-loads its manifest, tier map, and CRC tables.")
                        .font(.monoDigits(12))
                        .foregroundColor(.labelTertiary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20)
                }

                Text("Live QR scanning coming in the next build.")
                    .font(.monoDigits(11))
                    .foregroundColor(.labelTertiary)
                    .italic()

                Spacer()

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
            .padding(.horizontal, 30)
        }
    }
}

private struct CornerTargets: View {
    var body: some View {
        let size: CGFloat = 200
        let arm: CGFloat = 24
        let thick: CGFloat = 3
        let offset: CGFloat = 16

        ZStack {
            ForEach([0, 1, 2, 3], id: \.self) { corner in
                let xSign: CGFloat = corner % 2 == 0 ? -1 : 1
                let ySign: CGFloat = corner < 2 ? -1 : 1
                let x = xSign * (size / 2 - offset)
                let y = ySign * (size / 2 - offset)

                Path { p in
                    p.move(to: CGPoint(x: x, y: y + ySign * arm))
                    p.addLine(to: CGPoint(x: x, y: y))
                    p.addLine(to: CGPoint(x: x + xSign * arm, y: y))
                }
                .stroke(Color.amber, style: StrokeStyle(lineWidth: thick, lineCap: .round))
            }
        }
        .frame(width: size, height: size)
    }
}
