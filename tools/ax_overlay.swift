// M013 supervised-executor overlay: a click-through highlight over the target
// region, shown before confirmation. It cannot become key, ignores mouse
// events, posts nothing, and auto-expires.
//
// Usage: ax_overlay <x> <y> <w> <h> [--ms 1200]
// Coordinates are AX screen points (top-left origin); they are converted to
// Cocoa's bottom-left global space using the primary display height.
//
// Build: swiftc -O tools/ax_overlay.swift -o runs/m013-tools/ax_overlay

import AppKit

let arguments = CommandLine.arguments
guard arguments.count >= 5,
      let x = Double(arguments[1]), let y = Double(arguments[2]),
      let width = Double(arguments[3]), let height = Double(arguments[4]) else {
    FileHandle.standardError.write(Data("usage: ax_overlay x y w h [--ms 1200]\n".utf8))
    exit(3)
}
var durationMs = 1200.0
if let index = arguments.firstIndex(of: "--ms"), index + 1 < arguments.count,
   let parsed = Double(arguments[index + 1]) {
    durationMs = parsed
}

let primaryHeight = NSScreen.screens.first?.frame.height ?? 0
let cocoaY = primaryHeight - (y + height)
let rect = NSRect(x: x, y: cocoaY, width: width, height: height)

final class OverlayWindow: NSWindow {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let window = OverlayWindow(
    contentRect: rect,
    styleMask: .borderless,
    backing: .buffered,
    defer: false
)
window.isOpaque = false
window.backgroundColor = .clear
window.ignoresMouseEvents = true
window.hasShadow = false
window.level = .floating

let view = NSView(frame: NSRect(origin: .zero, size: rect.size))
view.wantsLayer = true
view.layer?.borderWidth = 3
view.layer?.borderColor = NSColor.systemRed.cgColor
view.layer?.backgroundColor = NSColor.systemRed.withAlphaComponent(0.12).cgColor
view.layer?.cornerRadius = 4
window.contentView = view

window.orderFrontRegardless()
DispatchQueue.main.asyncAfter(deadline: .now() + durationMs / 1000.0) {
    NSApp.terminate(nil)
}
app.run()
