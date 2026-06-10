import Foundation

// ---------------------------------------------------------------------------
// BackendClient — async/await JSON client for the CassetteAI decode backend.
// All methods tolerate a missing backend and surface clear errors.
// ---------------------------------------------------------------------------

enum BackendError: LocalizedError {
    case invalidURL
    case backendUnreachable(String)
    case httpError(Int)
    case decodingError(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid backend URL. Check Settings."
        case .backendUnreachable(let msg):
            return "Backend unreachable: \(msg)"
        case .httpError(let code):
            return "Backend returned HTTP \(code)."
        case .decodingError(let msg):
            return "Could not parse response: \(msg)"
        }
    }
}

final class BackendClient {
    private let baseURL: URL
    private let session: URLSession

    init(baseURL: URL) {
        self.baseURL = baseURL
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 300
        self.session = URLSession(configuration: config)
    }

    // -------------------------------------------------------------------------
    // MARK: - Endpoints
    // -------------------------------------------------------------------------

    /// POST /api/captures — upload WAV file, returns job ID.
    /// `tapeId` is sent as a form field for future per-tape decode routing; the
    /// current backend infers the tape from the capture, so it is optional.
    func submitDecode(wavURL: URL, tapeId: String) async throws -> String {
        let endpoint = baseURL.appendingPathComponent("api/captures")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        // tape_id field (currently advisory; backend infers tape from capture)
        body.appendFormField("tape_id", value: tapeId, boundary: boundary)
        // file field
        let fileData = try Data(contentsOf: wavURL)
        body.appendFile("file", filename: wavURL.lastPathComponent,
                        mimeType: "audio/wav", data: fileData, boundary: boundary)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await perform(request)
        try checkHTTP(response)
        struct JobResponse: Codable { let jobId: String; enum CodingKeys: String, CodingKey { case jobId = "job_id" } }
        let parsed = try decode(JobResponse.self, from: data)
        return parsed.jobId
    }

    /// GET /api/jobs/{id} — poll job status.
    func pollJob(_ jobId: String) async throws -> DecodeJob {
        let endpoint = baseURL.appendingPathComponent("api/jobs/\(jobId)")
        let request = URLRequest(url: endpoint)
        let (data, response) = try await perform(request)
        try checkHTTP(response)
        return try decode(DecodeJob.self, from: data)
    }

    /// POST /api/setup-test — upload WAV, returns tier grades.
    func submitSetupTest(wavURL: URL) async throws -> SetupTestResult {
        let endpoint = baseURL.appendingPathComponent("api/setup-test")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        let fileData = try Data(contentsOf: wavURL)
        body.appendFile("file", filename: wavURL.lastPathComponent,
                        mimeType: "audio/wav", data: fileData, boundary: boundary)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await perform(request)
        try checkHTTP(response)
        return try decode(SetupTestResult.self, from: data)
    }

    /// GET /api/tapes/{id}/manifest — fetch tape manifest.
    func fetchManifest(tapeId: String) async throws -> TapeManifest {
        let endpoint = baseURL.appendingPathComponent("api/tapes/\(tapeId)/manifest")
        let request = URLRequest(url: endpoint)
        let (data, response) = try await perform(request)
        try checkHTTP(response)
        return try decode(TapeManifest.self, from: data)
    }

    /// GET /api/calibration — returns calibration WAV data.
    func calibrationURL() -> URL {
        baseURL.appendingPathComponent("api/calibration")
    }

    // -------------------------------------------------------------------------
    // MARK: - Private helpers
    // -------------------------------------------------------------------------

    private func perform(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw BackendError.backendUnreachable(error.localizedDescription)
        }
    }

    private func checkHTTP(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200 ..< 300).contains(http.statusCode) else {
            throw BackendError.httpError(http.statusCode)
        }
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        let decoder = JSONDecoder()
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw BackendError.decodingError(error.localizedDescription)
        }
    }
}

// ---------------------------------------------------------------------------
// MARK: - Multipart helpers
// ---------------------------------------------------------------------------

private extension Data {
    mutating func appendFormField(_ name: String, value: String, boundary: String) {
        let line = "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n"
        if let d = line.data(using: .utf8) { append(d) }
    }

    mutating func appendFile(_ name: String, filename: String, mimeType: String,
                              data: Data, boundary: String) {
        let header = "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\nContent-Type: \(mimeType)\r\n\r\n"
        if let d = header.data(using: .utf8) { append(d) }
        append(data)
        if let d = "\r\n".data(using: .utf8) { append(d) }
    }
}
