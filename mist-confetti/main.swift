// Fullscreen click-through confetti burst, one transparent window per display.
//
// Constraints that shaped this, so nobody "simplifies" them back out:
//  - .accessory activation policy: the burst must never steal focus from whatever
//    Alex is doing. No dock icon, no menu bar, no key window.
//  - ignoresMouseEvents: the overlay covers the whole screen, so if it ever
//    swallowed a click it would be a trap rather than a celebration.
//  - screenSaver window level + .canJoinAllSpaces/.fullScreenAuxiliary: draws over
//    fullscreen apps and on whichever Space is front, without switching Spaces.
//  - CAEmitterLayer rather than hand-rolled animation: Core Animation runs the
//    particles on the render server, so a few thousand of them cost ~nothing.

import AppKit
import QuartzCore

var duration: Double = 4.0   // seconds the window stays up
var emitFor: Double = 1.3    // seconds the emitter keeps spawning
var intensity: Double = 1.0

let argv = CommandLine.arguments
for (i, a) in argv.enumerated() {
    let next = i + 1 < argv.count ? Double(argv[i + 1]) : nil
    switch a {
    case "--duration":  duration  = next ?? duration
    case "--emit":      emitFor   = next ?? emitFor
    case "--intensity": intensity = next ?? intensity
    case "-h", "--help":
        print("""
        usage: mist-confetti [--duration S] [--emit S] [--intensity N]
          --duration   how long the overlay lives (default 4.0)
          --emit       how long confetti keeps spawning (default 1.3)
          --intensity  particle multiplier (default 1.0)
        """)
        exit(0)
    default: break
    }
}

// A flat strip of color. Two sizes so the fall looks uneven rather than uniform.
func strip(_ w: Int, _ h: Int, _ color: NSColor) -> CGImage? {
    guard let ctx = CGContext(data: nil, width: w, height: h,
                              bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { return nil }
    ctx.setFillColor(color.cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    return ctx.makeImage()
}

let palette: [NSColor] = [
    NSColor(srgbRed: 0.98, green: 0.24, blue: 0.35, alpha: 1),  // red
    NSColor(srgbRed: 1.00, green: 0.78, blue: 0.16, alpha: 1),  // gold
    NSColor(srgbRed: 0.18, green: 0.80, blue: 0.51, alpha: 1),  // green
    NSColor(srgbRed: 0.25, green: 0.60, blue: 0.99, alpha: 1),  // blue
    NSColor(srgbRed: 0.70, green: 0.40, blue: 0.95, alpha: 1),  // violet
    NSColor(srgbRed: 1.00, green: 0.50, blue: 0.24, alpha: 1),  // orange
    NSColor(srgbRed: 0.99, green: 0.99, blue: 0.99, alpha: 1),  // white
]

func makeCells() -> [CAEmitterCell] {
    var cells: [CAEmitterCell] = []
    for color in palette {
        for (w, h) in [(10, 16), (14, 8), (8, 8)] {
            guard let img = strip(w, h, color) else { continue }
            let c = CAEmitterCell()
            c.contents = img
            c.birthRate = Float(26.0 * intensity)
            c.lifetime = 9.0
            c.velocity = 260
            c.velocityRange = 170
            // y-up coordinates, so "down" is -pi/2.
            c.emissionLongitude = -.pi / 2
            c.emissionRange = .pi / 5
            c.yAcceleration = -340          // gravity
            c.xAcceleration = CGFloat.random(in: -22...22)
            c.spin = 3.2
            c.spinRange = 7.5
            c.scale = 1.0
            c.scaleRange = 0.45
            c.alphaSpeed = -0.09
            cells.append(c)
        }
    }
    return cells
}

final class ConfettiView: NSView {
    let emitter = CAEmitterLayer()

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.addSublayer(emitter)
        emitter.emitterShape = .line
        emitter.renderMode = .unordered
        emitter.emitterCells = makeCells()
        layoutEmitter()
    }
    required init?(coder: NSCoder) { fatalError() }

    // Spawn along a line just above the top edge, spanning the full width.
    func layoutEmitter() {
        emitter.frame = bounds
        emitter.emitterPosition = CGPoint(x: bounds.midX, y: bounds.maxY + 12)
        emitter.emitterSize = CGSize(width: bounds.width * 1.05, height: 1)
    }

    override func layout() {
        super.layout()
        layoutEmitter()
    }

    func stopEmitting() { emitter.birthRate = 0 }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

var windows: [NSWindow] = []
var views: [ConfettiView] = []

for screen in NSScreen.screens {
    let w = NSWindow(contentRect: screen.frame,
                     styleMask: .borderless,
                     backing: .buffered,
                     defer: false,
                     screen: screen)
    w.isOpaque = false
    w.backgroundColor = .clear
    w.hasShadow = false
    w.ignoresMouseEvents = true
    w.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.screenSaverWindow)))
    w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
    w.setFrame(screen.frame, display: true)

    let v = ConfettiView(frame: NSRect(origin: .zero, size: screen.frame.size))
    w.contentView = v
    // orderFrontRegardless, not makeKeyAndOrderFront: showing up must not take focus.
    w.orderFrontRegardless()

    windows.append(w)
    views.append(v)
}

if windows.isEmpty { exit(0) }

DispatchQueue.main.asyncAfter(deadline: .now() + emitFor) {
    views.forEach { $0.stopEmitting() }
}
DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
    windows.forEach { $0.orderOut(nil) }
    app.terminate(nil)
}

app.run()
