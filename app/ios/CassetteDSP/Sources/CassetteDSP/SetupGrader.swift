/// SetupGrader.swift — Pure-function tier grader.
///
/// Loads thresholds from a grading.json blob (Decodable) and maps measured
/// channel metrics to per-tier verdicts {pass, marginal, fail} plus a
/// human-readable advice string identifying the single most actionable fix.
///
/// All business logic is in data (grading.json), not code.  Thresholds should
/// be calibrated from real captures and shipped as a versioned JSON that can be
/// updated without an app release.
///
/// Usage:
///   let config = try GradingConfig.load(from: jsonData)
///   let metrics = CaptureMetrics(snrDBMedian: 36, ...)
///   let result  = SetupGrader.grade(metrics: metrics, config: config)
///   print(result.robust.verdict, result.robust.advice)

import Foundation

// MARK: - Inputs

/// Measured capture metrics fed into the grader.
public struct CaptureMetrics {
    /// Median per-tone SNR across 64 Schroeder carriers (dB).
    public var snrDBMedian: Double
    /// 10th-percentile per-tone SNR (worst-case carrier, dB).
    public var snrDBP10: Double
    /// Fraction of carriers below 8 dB SNR [0, 1].
    public var fracBelow8dB: Double
    /// Wow/flutter WRMS % (nil if not available, e.g. Stage A channel-only test).
    public var flutterWRMSPct: Double?
    /// Room noise floor in dBFS (e.g. -55.0).
    public var noiseFloorDBFS: Double?
    /// Whether the capture codec is lossless (true) or compressed (false, e.g. AAC).
    public var isLossless: Bool
    /// True if any samples exceeded the clipping threshold during capture.
    public var hasClipping: Bool

    public init(
        snrDBMedian: Double,
        snrDBP10: Double,
        fracBelow8dB: Double,
        flutterWRMSPct: Double? = nil,
        noiseFloorDBFS: Double? = nil,
        isLossless: Bool = true,
        hasClipping: Bool = false
    ) {
        self.snrDBMedian     = snrDBMedian
        self.snrDBP10        = snrDBP10
        self.fracBelow8dB    = fracBelow8dB
        self.flutterWRMSPct  = flutterWRMSPct
        self.noiseFloorDBFS  = noiseFloorDBFS
        self.isLossless      = isLossless
        self.hasClipping     = hasClipping
    }
}

// MARK: - Verdict

public enum TierVerdict: String, Codable {
    case pass
    case marginal
    case fail
}

public struct TierResult {
    public let tier: String
    public let verdict: TierVerdict
    /// Most actionable single fix for the user.
    public let advice: String

    public init(tier: String, verdict: TierVerdict, advice: String) {
        self.tier    = tier
        self.verdict = verdict
        self.advice  = advice
    }
}

public struct GradeResult {
    public let robust:   TierResult
    public let turbo:    TierResult
    public let moonshot: TierResult

    /// Highest tier that passes.
    public var highestPassing: TierResult? {
        [moonshot, turbo, robust].first { $0.verdict == .pass }
    }
}

// MARK: - Grading config (Decodable from grading.json)

/// Thresholds for each tier. All fields optional to allow partial overrides.
public struct TierThresholds: Decodable {
    public var minSNRMedian:  Double
    public var minSNRP10:     Double
    public var maxNulls:      Double   // max frac_below_8db
    public var maxFlutter:    Double?  // nil means flutter not checked for this tier
    public var requireLossless: Bool
    /// Marginal bands: metric can be within this offset of the hard threshold.
    public var marginalBand:  Double   // e.g. 2 dB — within band -> marginal instead of fail
}

public struct GradingConfig: Decodable {
    public var version: String
    public var robust:   TierThresholds
    public var turbo:    TierThresholds
    public var moonshot: TierThresholds

    // MARK: - Load from JSON data
    public static func load(from data: Data) throws -> GradingConfig {
        let decoder = JSONDecoder()
        return try decoder.decode(GradingConfig.self, from: data)
    }

    /// Bundled default thresholds.  Use these only when grading.json is
    /// unavailable (e.g. offline / first launch).  These are provisional
    /// values from the design doc — calibrate from real lab captures.
    public static var defaults: GradingConfig {
        GradingConfig(
            version: "0.1.0-provisional",
            robust: TierThresholds(
                minSNRMedian:  33.0,
                minSNRP10:     25.0,
                maxNulls:      0.30,
                maxFlutter:    0.60,
                requireLossless: false,
                marginalBand:  3.0
            ),
            turbo: TierThresholds(
                minSNRMedian:  36.0,
                minSNRP10:     30.0,
                maxNulls:      0.20,
                maxFlutter:    0.45,
                requireLossless: true,
                marginalBand:  2.0
            ),
            moonshot: TierThresholds(
                minSNRMedian:  38.0,
                minSNRP10:     32.0,
                maxNulls:      0.10,
                maxFlutter:    0.42,
                requireLossless: true,
                marginalBand:  2.0
            )
        )
    }
}

// MARK: - SetupGrader

public enum SetupGrader {
    /// Grade capture metrics against the provided thresholds.
    public static func grade(metrics: CaptureMetrics,
                              config: GradingConfig = .defaults) -> GradeResult {
        let robust   = _gradeTier("Robust",   metrics: metrics, t: config.robust,   prerequisite: nil)
        let turbo    = _gradeTier("Turbo",    metrics: metrics, t: config.turbo,    prerequisite: robust)
        let moonshot = _gradeTier("Moonshot", metrics: metrics, t: config.moonshot, prerequisite: turbo)
        return GradeResult(robust: robust, turbo: turbo, moonshot: moonshot)
    }

    // MARK: - Private
    private static func _gradeTier(
        _ name: String,
        metrics: CaptureMetrics,
        t: TierThresholds,
        prerequisite: TierResult?
    ) -> TierResult {
        // A higher tier cannot pass if its prerequisite failed.
        if let pre = prerequisite, pre.verdict == .fail {
            return TierResult(tier: name, verdict: .fail,
                              advice: "Fix \(pre.tier) tier issues first.")
        }

        // Evaluate each condition, collecting the worst failure.
        var failAdvice: String? = nil
        var marginalAdvice: String? = nil
        var verdict: TierVerdict = .pass

        func check(_ condition: Bool, _ near: Bool, _ advice: String) {
            if !condition {
                if verdict != .fail { verdict = near ? .marginal : .fail }
                if !condition && !near {
                    if failAdvice == nil { failAdvice = advice }
                } else {
                    if marginalAdvice == nil { marginalAdvice = advice }
                }
            }
        }

        // Clipping always blocks.
        if metrics.hasClipping {
            return TierResult(tier: name, verdict: .fail,
                              advice: "Lower the record level — clipping detected.")
        }

        // Lossless required?
        if t.requireLossless && !metrics.isLossless {
            return TierResult(tier: name, verdict: .fail,
                              advice: "Switch to lossless capture (AAC detected).")
        }

        let band = t.marginalBand

        // SNR median.
        let snrOk = metrics.snrDBMedian >= t.minSNRMedian
        let snrNear = !snrOk && metrics.snrDBMedian >= (t.minSNRMedian - band)
        check(snrOk, snrNear,
              snrNear ? "SNR is marginal — move phone closer or reduce room noise."
                      : "SNR too low — move phone closer or reduce room noise.")

        // SNR p10.
        let p10Ok = metrics.snrDBP10 >= t.minSNRP10
        let p10Near = !p10Ok && metrics.snrDBP10 >= (t.minSNRP10 - band)
        check(p10Ok, p10Near,
              p10Near ? "Some carriers are weak — check room reflections or phone angle."
                      : "Too many weak carriers — reduce reflections and move closer.")

        // Nulls (frac_below_8db).
        let nullsOk = metrics.fracBelow8dB <= t.maxNulls
        let nullsNear = !nullsOk && metrics.fracBelow8dB <= (t.maxNulls + 0.05)
        check(nullsOk, nullsNear,
              nullsNear ? "Room nulls detected — reposition the phone slightly."
                        : "Too many room nulls — try a different phone position.")

        // Flutter (only if available and threshold is set).
        if let flutterThreshold = t.maxFlutter, let flutter = metrics.flutterWRMSPct {
            let flutterOk = flutter <= flutterThreshold
            let flutterNear = !flutterOk && flutter <= (flutterThreshold + 0.1)
            check(flutterOk, flutterNear,
                  flutterNear ? "Flutter slightly high — check deck heads and pinch roller."
                              : "Flutter too high — clean deck heads or use a better deck.")
        }

        // Pick the most actionable advice string.
        let advice: String
        switch verdict {
        case .pass:
            advice = "\(name): all checks passed."
        case .marginal:
            advice = marginalAdvice ?? failAdvice ?? "\(name): marginal — small improvements recommended."
        case .fail:
            advice = failAdvice ?? marginalAdvice ?? "\(name): failed — see individual metrics."
        }

        return TierResult(tier: name, verdict: verdict, advice: advice)
    }
}
