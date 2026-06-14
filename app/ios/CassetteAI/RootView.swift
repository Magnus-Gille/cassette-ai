import SwiftUI

struct RootView: View {
    @EnvironmentObject private var settings: AppSettings
    @StateObject private var captureEngine = CaptureEngine()
    @State private var selectedTab: Tab = .capture

    enum Tab: Int, CaseIterable {
        case capture, testSetup, library, settings

        var title: String {
            switch self {
            case .capture:   return "CAPTURE"
            case .testSetup: return "TEST SETUP"
            case .library:   return "LIBRARY"
            case .settings:  return "SETTINGS"
            }
        }

        var systemImage: String {
            switch self {
            case .capture:   return "waveform"
            case .testSetup: return "tuningfork"
            case .library:   return "square.stack"
            case .settings:  return "gearshape"
            }
        }
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            CaptureView()
                .environmentObject(captureEngine)
                .tabItem {
                    Label(Tab.capture.title, systemImage: Tab.capture.systemImage)
                }
                .tag(Tab.capture)

            TestSetupView()
                .tabItem {
                    Label(Tab.testSetup.title, systemImage: Tab.testSetup.systemImage)
                }
                .tag(Tab.testSetup)

            LibraryView()
                .tabItem {
                    Label(Tab.library.title, systemImage: Tab.library.systemImage)
                }
                .tag(Tab.library)

            SettingsView()
                .tabItem {
                    Label(Tab.settings.title, systemImage: Tab.settings.systemImage)
                }
                .tag(Tab.settings)
        }
        .tint(Color.amber)
        .onOpenURL { url in
            handleDeepLink(url)
        }
    }

    private func handleDeepLink(_ url: URL) {
        // cassetteai://tape/<id>
        guard url.scheme == "cassetteai",
              url.host == "tape" else { return }
        selectedTab = .library
    }
}
