// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "CassetteDSP",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        .library(name: "CassetteDSP", targets: ["CassetteDSP"]),
    ],
    targets: [
        .target(
            name: "CassetteDSP",
            path: "Sources/CassetteDSP"
        ),
        .testTarget(
            name: "CassetteDSPTests",
            dependencies: ["CassetteDSP"],
            path: "Tests/CassetteDSPTests"
        ),
    ],
    swiftLanguageVersions: [.v5]
)
