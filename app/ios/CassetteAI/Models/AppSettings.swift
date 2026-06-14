import SwiftUI
import Combine

final class AppSettings: ObservableObject {
    @AppStorage("backendURL") var backendURL: String = "http://localhost:8765"
    @AppStorage("labMode") var labMode: Bool = false
    @AppStorage("captureFormat") var captureFormat: String = "WAV Float32 48 kHz"

    var resolvedBackendURL: URL? {
        URL(string: backendURL)
    }
}
