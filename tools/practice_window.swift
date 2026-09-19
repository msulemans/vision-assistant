// Disposable practice window for the M013 supervised executor.
//
// A tiny AppKit app with five controls and stable Accessibility identifiers:
//   app:sync-toggle     checkbox "Sync"
//   app:notify-toggle   checkbox "Notifications"
//   app:search          text field (label "Search")
//   app:save            button "Save"
//   app:cancel          button "Cancel"
// Closing the window exits the process. Nothing is persisted anywhere.
//
// Build: swiftc -O tools/practice_window.swift -o runs/m013-tools/practice_window
// Run:   runs/m013-tools/practice_window

import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate

let window = NSWindow(
    contentRect: NSRect(x: 0, y: 0, width: 480, height: 300),
    styleMask: [.titled, .closable, .miniaturizable],
    backing: .buffered,
    defer: false
)
window.title = "Practice App"
window.isReleasedWhenClosed = false

let content = NSView(frame: NSRect(x: 0, y: 0, width: 480, height: 300))

func makeCheckbox(_ title: String, identifier: String, y: CGFloat) -> NSButton {
    let box = NSButton(checkboxWithTitle: title, target: nil, action: nil)
    box.frame = NSRect(x: 40, y: y, width: 240, height: 24)
    box.setAccessibilityIdentifier(identifier)
    box.setAccessibilityLabel(title)
    return box
}

let sync = makeCheckbox("Sync", identifier: "app:sync-toggle", y: 226)
let notify = makeCheckbox("Notifications", identifier: "app:notify-toggle", y: 194)

let label = NSTextField(labelWithString: "Search")
label.frame = NSRect(x: 40, y: 152, width: 60, height: 20)

let search = NSTextField(frame: NSRect(x: 110, y: 148, width: 330, height: 24))
search.setAccessibilityIdentifier("app:search")
search.setAccessibilityLabel("Search")
search.placeholderString = "Type here"

func makeButton(_ title: String, identifier: String, x: CGFloat) -> NSButton {
    let button = NSButton(title: title, target: nil, action: nil)
    button.frame = NSRect(x: x, y: 60, width: 110, height: 32)
    button.bezelStyle = .rounded
    button.setAccessibilityIdentifier(identifier)
    return button
}

let save = makeButton("Save", identifier: "app:save", x: 240)
let cancel = makeButton("Cancel", identifier: "app:cancel", x: 360)

content.addSubview(sync)
content.addSubview(notify)
content.addSubview(label)
content.addSubview(search)
content.addSubview(save)
content.addSubview(cancel)
window.contentView = content

window.center()
window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)

print("practice window ready: close the window (or Ctrl+C) to quit")
fflush(stdout)
app.run()
