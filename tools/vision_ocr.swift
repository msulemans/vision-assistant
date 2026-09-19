// Local macOS Vision OCR helper for the Vision Assistant (M007).
//
// Reads one image path and writes a JSON array of recognized text lines to
// stdout: [{"text": ..., "x": ..., "y": ..., "w": ..., "h": ..., "confidence": ...}]
// Coordinates are top-left-origin source pixels. No network, no permissions.
//
// Build: swiftc -O tools/vision_ocr.swift -o runs/m007-tools/vision_ocr

import Foundation
import ImageIO
import Vision

let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    FileHandle.standardError.write(Data("usage: vision_ocr <image.png>\n".utf8))
    exit(2)
}

let url = URL(fileURLWithPath: arguments[1])
guard
    let source = CGImageSourceCreateWithURL(url as CFURL, nil),
    let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
else {
    FileHandle.standardError.write(Data("cannot read image at the given path\n".utf8))
    exit(3)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false  // literal extraction; do not invent words
if arguments.count >= 3 && arguments[2] == "--correction" {
    request.usesLanguageCorrection = true
}
let handler = VNImageRequestHandler(cgImage: image, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write(Data("vision request failed: \(error)\n".utf8))
    exit(4)
}

let pixelWidth = Double(image.width)
let pixelHeight = Double(image.height)
var rows: [[String: Any]] = []
for observation in request.results ?? [] {
    guard let candidate = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox  // normalized, origin bottom-left
    rows.append([
        "text": candidate.string,
        "x": Int((box.minX * pixelWidth).rounded()),
        "y": Int(((1.0 - box.maxY) * pixelHeight).rounded()),
        "w": Int((box.width * pixelWidth).rounded()),
        "h": Int((box.height * pixelHeight).rounded()),
        "confidence": Double(candidate.confidence),
    ])
}

do {
    let data = try JSONSerialization.data(withJSONObject: rows, options: [])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    FileHandle.standardError.write(Data("failed to encode results\n".utf8))
    exit(5)
}
