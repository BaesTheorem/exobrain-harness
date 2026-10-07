// visionocr: print every text box Apple Vision finds in an image, one JSON object per line.
//
// Built on demand by shoptools/circular_ocr.py (swiftc, cached in shopping/.cache/) so the
// grocery circular lanes can read image-only ad PDFs without a Python OCR dependency.
// Coordinates are normalized to the image, origin bottom-left (Vision's own convention).
import AppKit
import Foundation
import Vision

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: visionocr <image> [<image>...]\n".data(using: .utf8)!)
    exit(2)
}
for path in args.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("visionocr: cannot read \(path)\n".data(using: .utf8)!)
        exit(1)
    }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    req.recognitionLanguages = ["en-US"]
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([req]) } catch {
        FileHandle.standardError.write("visionocr: \(error)\n".data(using: .utf8)!)
        exit(1)
    }
    for obs in req.results ?? [] {
        guard let c = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        let row: [String: Any] = [
            "file": path, "text": c.string, "conf": Double(c.confidence),
            "x": b.origin.x, "y": b.origin.y, "w": b.size.width, "h": b.size.height,
        ]
        let data = try! JSONSerialization.data(withJSONObject: row)
        print(String(data: data, encoding: .utf8)!)
    }
}
