import SwiftUI

// ---------------------------------------------------------------------------
// Design System — Tape-deck industrial aesthetic
//
// Palette: near-black chassis, amber VU-meter accent, phosphor green for CRT
// terminal text, steel gray for secondary text.
// Typography: SF Mono for all numeric readouts (monospaced numerals);
// SF Pro Display condensed for labels and headers.
// ---------------------------------------------------------------------------

extension Color {
    // Primary accent — amber VU meter needle
    static let amber = Color(red: 1.0, green: 0.62, blue: 0.0)
    static let amberDim = Color(red: 0.6, green: 0.37, blue: 0.0)

    // CRT phosphor green for terminal reveal
    static let phosphorGreen = Color(red: 0.18, green: 0.95, blue: 0.22)
    static let phosphorDim = Color(red: 0.08, green: 0.45, blue: 0.10)

    // Background tiers
    static let chassisBlack = Color(red: 0.07, green: 0.07, blue: 0.07)
    static let panelDark = Color(red: 0.11, green: 0.11, blue: 0.11)
    static let panelMid = Color(red: 0.16, green: 0.16, blue: 0.16)
    static let rackGray = Color(red: 0.22, green: 0.22, blue: 0.22)

    // Status
    static let signalGreen = Color(red: 0.18, green: 0.8, blue: 0.35)
    static let warningRed = Color(red: 0.92, green: 0.18, blue: 0.14)
    static let marginalYellow = Color(red: 0.97, green: 0.82, blue: 0.10)

    // Text
    static let labelPrimary = Color.white.opacity(0.92)
    static let labelSecondary = Color.white.opacity(0.55)
    static let labelTertiary = Color.white.opacity(0.30)
}

extension Font {
    /// Monospaced numeric readout — uses SF Mono
    static func monoDigits(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    /// Panel label — condensed, all-caps feel
    static func panelLabel(_ size: CGFloat) -> Font {
        .system(size: size, weight: .semibold, design: .default).monospaced()
    }
}

// ---------------------------------------------------------------------------
// Reusable gauge + panel components
// ---------------------------------------------------------------------------

/// Rounded panel card — the fundamental surface.
struct PanelCard<Content: View>: View {
    var padding: CGFloat = 16
    @ViewBuilder let content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .background(Color.panelDark)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
            )
    }
}

/// Amber VU-bar — horizontal level meter strip.
struct VUBar: View {
    let level: Float   // 0.0 … 1.0 normalised
    var isClipping: Bool = false
    var height: CGFloat = 8

    private var barColor: Color {
        if isClipping { return .warningRed }
        let normalized = Double(level)
        if normalized > 0.85 { return .marginalYellow }
        return .amber
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.panelMid)
                    .frame(height: height)
                Capsule()
                    .fill(barColor)
                    .frame(width: geo.size.width * CGFloat(min(level, 1.0)), height: height)
                    .animation(.linear(duration: 0.04), value: level)
            }
        }
        .frame(height: height)
    }
}

/// Small labeled gauge tile.
struct GaugeTile: View {
    let label: String
    let value: String
    let unit: String
    var accent: Color = .amber
    var warning: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.monoDigits(9))
                .foregroundColor(.labelTertiary)
                .textCase(.uppercase)
                .tracking(1.2)
            HStack(alignment: .lastTextBaseline, spacing: 2) {
                Text(value)
                    .font(.monoDigits(22, weight: .medium))
                    .foregroundColor(warning ? .warningRed : accent)
                Text(unit)
                    .font(.monoDigits(10))
                    .foregroundColor(.labelSecondary)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color.panelDark)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(warning ? Color.warningRed.opacity(0.6) : Color.white.opacity(0.08),
                              lineWidth: warning ? 1.5 : 1)
        )
    }
}

/// Tier badge pill.
struct TierBadge: View {
    enum Status { case pass, marginal, fail, unknown }
    let tier: String
    let status: Status
    let advice: String?

    private var iconAndColor: (icon: String, color: Color) {
        switch status {
        case .pass:     return ("checkmark.circle.fill", .signalGreen)
        case .marginal: return ("exclamationmark.circle.fill", .marginalYellow)
        case .fail:     return ("xmark.circle.fill", .warningRed)
        case .unknown:  return ("minus.circle", .labelTertiary)
        }
    }
    private var icon: String { iconAndColor.icon }
    private var color: Color { iconAndColor.color }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .foregroundColor(color)
                    .font(.system(size: 18, weight: .semibold))
                Text(tier)
                    .font(.monoDigits(16, weight: .bold))
                    .foregroundColor(.labelPrimary)
            }
            if let advice, !advice.isEmpty {
                Text(advice)
                    .font(.monoDigits(12))
                    .foregroundColor(.labelSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(color.opacity(0.35), lineWidth: 1.5)
        )
    }
}

// ---------------------------------------------------------------------------
// Blinking cursor for CRT terminal
// ---------------------------------------------------------------------------

struct BlinkingCursor: View {
    @State private var visible = true

    var body: some View {
        Rectangle()
            .fill(Color.phosphorGreen)
            .frame(width: 9, height: 17)
            .opacity(visible ? 1 : 0)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.53).repeatForever(autoreverses: true)) {
                    visible.toggle()
                }
            }
    }
}
