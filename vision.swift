import Foundation
import Vision
import AppKit

// On-device helpers. Nothing here touches the network.
//   vision rects <image>  -> JSON list of paper-shaped quads, pixel coords, origin top-left
//   vision text  <image>  -> JSON list of {text, conf, x, y, w, h, angle}
//     angle: 0, 90, 180 or 270; the counter-clockwise turn (PIL's rotate())
//     that would make this line read left-to-right upright. Vision reads text
//     at any rotation and orders an observation's corners along the TEXT's
//     reading direction, so the topLeft->topRight vector says which way the
//     words run, whatever way the phone was held.

let args = CommandLine.arguments
guard args.count > 2, let img = NSImage(contentsOfFile: args[2]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("usage: vision rects|text <image>\n".data(using: .utf8)!); exit(1)
}
let W = CGFloat(cg.width), H = CGFloat(cg.height)
func px(_ p: CGPoint) -> [Int] { return [Int((p.x * W).rounded()), Int(((1 - p.y) * H).rounded())] }

var out: [[String: Any]] = []
let handler = VNImageRequestHandler(cgImage: cg, options: [:])

if args[1] == "rects" {
    let req = VNDetectRectanglesRequest()
    req.maximumObservations = 24
    req.minimumSize = 0.06          // each paper is at least 6% of the shorter image side
    req.minimumAspectRatio = 0.35   // shorter side over longer side
    req.maximumAspectRatio = 1.0
    req.minimumConfidence = 0.4
    req.quadratureTolerance = 25
    try handler.perform([req])
    for r in req.results ?? [] {
        out.append(["conf": Double(r.confidence),
                    "tl": px(r.topLeft), "tr": px(r.topRight),
                    "br": px(r.bottomRight), "bl": px(r.bottomLeft)])
    }
} else {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    req.recognitionLanguages = ["en-US", "es-ES"]   // Latin script only; stops Cyrillic look-alikes
    if args.count > 3, args[3] == "corrected" { req.usesLanguageCorrection = true }
    try handler.perform([req])
    for obs in req.results ?? [] {
        guard let c = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        // reading direction in pixel space (y down): Vision's y is up, so flip it
        let dx = (obs.topRight.x - obs.topLeft.x) * W
        let dy = -(obs.topRight.y - obs.topLeft.y) * H
        var deg = atan2(dy, dx) * 180 / .pi          // 0 = reads left to right
        deg = (deg / 90).rounded() * 90                // snap to a quarter turn
        let angle = (Int(deg) % 360 + 360) % 360
        out.append(["text": c.string, "conf": Double(c.confidence),
                    "x": Int(b.minX * W), "y": Int((1 - b.maxY) * H),
                    "w": Int(b.width * W), "h": Int(b.height * H),
                    "angle": angle])
    }
}
let data = try JSONSerialization.data(withJSONObject: out, options: [])
print(String(data: data, encoding: .utf8)!)
