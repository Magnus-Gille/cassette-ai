import Foundation

// ---------------------------------------------------------------------------
// Wire models — decode the CassetteAI backend's JSON exactly as it ships.
// The Python backend (app/backend/server.py) is the source of truth; these
// Codables mirror its response shapes so the contract is verifiable.
// ---------------------------------------------------------------------------

// MARK: - Tape manifest  (GET /api/tapes/{id}/manifest)
// Backend returns the registry entry verbatim:
//   { tape_id, tape, payload_description, payload_sha256, sample_rate,
//     n_rungs, rungs: [ { name, role, kind, phy, gross_bps,
//                         projected_net_bps, effective_bps, ... } ] }

struct TapeManifest: Codable, Identifiable {
    let tapeId: String
    let tape: String?
    let payloadDescription: String?
    let payloadSha256: String?
    let sampleRate: Double?
    let rungs: [TapeRung]

    var id: String { tapeId }
    var name: String { tape ?? tapeId }
    var description: String? { payloadDescription }

    struct TapeRung: Codable, Identifiable {
        let name: String
        let role: String?
        let kind: String?
        let phy: String?
        let grossBps: Double?
        let projectedNetBps: Double?
        let effectiveBps: Double?

        var id: String { name }
        /// Human label for the rung (falls back to the internal config name).
        var label: String { role ?? name }
        /// Best single bps figure to surface in the UI.
        var bps: Int { Int((projectedNetBps ?? effectiveBps ?? grossBps ?? 0).rounded()) }
        /// Tier band derived from the rung's bps (design doc §4.1 bands).
        var tier: String {
            switch bps {
            case 1500...:  return "moonshot"
            case 931..<1500: return "turbo"
            default:       return "robust"
            }
        }

        enum CodingKeys: String, CodingKey {
            case name, role, kind, phy
            case grossBps         = "gross_bps"
            case projectedNetBps  = "projected_net_bps"
            case effectiveBps     = "effective_bps"
        }
    }

    enum CodingKeys: String, CodingKey {
        case tapeId             = "tape_id"
        case tape
        case payloadDescription = "payload_description"
        case payloadSha256      = "payload_sha256"
        case sampleRate         = "sample_rate"
        case rungs
    }
}

// MARK: - Setup-test result  (POST /api/setup-test)
// Backend returns:
//   { metrics: { snr_db_median, snr_db_p10, noise_floor_dbfs,
//                flutter_wrms_pct, frac_below_8db, clock_ratio, ... },
//     verdicts: [ { tier_id, tier_name, verdict: "YES"|"MARGINAL"|"NO",
//                   advice } ] }

struct SetupTestResult: Codable {
    let metrics: Metrics
    let verdicts: [Verdict]

    struct Metrics: Codable {
        let snrDbMedian: Double?
        let snrDbP10: Double?
        let noiseFloorDbfs: Double?
        let flutterWrmsPct: Double?
        let fracBelow8db: Double?
        let clockRatio: Double?

        enum CodingKeys: String, CodingKey {
            case snrDbMedian    = "snr_db_median"
            case snrDbP10       = "snr_db_p10"
            case noiseFloorDbfs = "noise_floor_dbfs"
            case flutterWrmsPct = "flutter_wrms_pct"
            case fracBelow8db   = "frac_below_8db"
            case clockRatio     = "clock_ratio"
        }
    }

    struct Verdict: Codable, Identifiable {
        let tierId: String
        let tierName: String
        /// "YES" | "MARGINAL" | "NO"
        let verdict: String
        let advice: String?

        var id: String { tierId }
        var pass: Bool     { verdict.uppercased() == "YES" }
        var marginal: Bool { verdict.uppercased() == "MARGINAL" }

        enum CodingKeys: String, CodingKey {
            case tierId   = "tier_id"
            case tierName = "tier_name"
            case verdict
            case advice
        }
    }

    // Convenience lookups by tier id.
    func verdict(_ tierId: String) -> Verdict? {
        verdicts.first { $0.tierId == tierId }
    }
    var robust: Verdict?   { verdict("robust") }
    var turbo: Verdict?    { verdict("turbo") }
    var moonshot: Verdict? { verdict("moonshot") }

    // Flat metric accessors used by the results UI.
    var snrDbMedian: Double    { metrics.snrDbMedian ?? 0 }
    var snrDbP10: Double       { metrics.snrDbP10 ?? 0 }
    var noiseFloorDbfs: Double { metrics.noiseFloorDbfs ?? 0 }
    var fracBelow8db: Double   { metrics.fracBelow8db ?? 0 }
    var captureLossless: Bool  { true }   // Stage-A bundled WAV is always lossless
}

// MARK: - Decode job  (POST /api/captures -> GET /api/jobs/{id})
// Backend job: { job_id, status, stage, progress, result?, error? }
// result mirrors m8_decode's manifest verification + payload.

struct DecodeJob: Codable {
    let jobId: String
    let status: String
    let stage: String?
    let progress: Double?
    let result: DecodeResult?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case jobId   = "job_id"
        case status
        case stage
        case progress
        case result
        case error
    }
}

struct DecodeResult: Codable {
    let snrDbMedian: Double?
    let snrDbP10: Double?
    let noiseFloorDbfs: Double?
    let flutterWrmsPct: Double?
    let clockRatio: Double?
    let rungResults: [RungResult]?
    let payloadText: String?
    let payloadType: String?

    struct RungResult: Codable, Identifiable {
        var id: String { label }
        let label: String
        let bps: Int
        let passed: Bool
        let crcPassed: Int
        let crcTotal: Int

        enum CodingKeys: String, CodingKey {
            case label, bps, passed
            case crcPassed = "crc_passed"
            case crcTotal  = "crc_total"
        }
    }

    enum CodingKeys: String, CodingKey {
        case snrDbMedian    = "snr_db_median"
        case snrDbP10       = "snr_db_p10"
        case noiseFloorDbfs = "noise_floor_dbfs"
        case flutterWrmsPct = "flutter_wrms_pct"
        case clockRatio     = "clock_ratio"
        case rungResults    = "rung_results"
        case payloadText    = "payload_text"
        case payloadType    = "payload_type"
    }
}
