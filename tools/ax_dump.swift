// Local read-only macOS Accessibility snapshot helper for the Vision Assistant
// (M012). Reads Accessibility attributes for one application — roles, names,
// identifiers, frames, enabled/focused state — and writes JSON to stdout.
//
// Read-only by design: this helper never performs Accessibility actions,
// never writes attribute values, never posts input events, and never reads
// or writes the pasteboard. The Python source-scan tests enforce those
// omissions.
//
// Modes:
//   ax_dump --check
//   ax_dump --request-permission
//   ax_dump --windows [--pid N | --app NAME | --frontmost]
//   ax_dump --dump [--pid N | --app NAME | --frontmost] [--max-depth D]
//
// Exit codes: 0 ok, 2 not permitted, 3 usage, 4 runtime failure.
//
// Build: swiftc -O tools/ax_dump.swift -o runs/m012-tools/ax_dump

import AppKit
import ApplicationServices
import Foundation

let arguments = CommandLine.arguments

func fail(_ message: String, code: Int32) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(code)
}

func writeJSON(_ object: [String: Any], code: Int32) -> Never {
    do {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    } catch {
        fail("failed to encode JSON", code: 4)
    }
    exit(code)
}

func argumentValue(_ name: String) -> String? {
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
        return nil
    }
    return arguments[index + 1]
}

func truncate(_ text: String, _ limit: Int) -> String {
    return text.count <= limit ? text : String(text.prefix(limit)) + "..."
}

// MARK: - Permission

let mode = arguments.count >= 2 ? arguments[1] : ""

switch mode {
case "--check":
    writeJSON(["trusted": AXIsProcessTrusted()], code: 0)
case "--request-permission":
    let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    _ = AXIsProcessTrustedWithOptions(options)
    writeJSON(["prompted": true, "trusted": AXIsProcessTrusted()], code: 0)
default:
    break
}

// MARK: - Read-only attribute helpers

func attribute(_ element: AXUIElement, _ name: CFString) -> CFTypeRef? {
    var value: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(element, name, &value)
    return result == .success ? value : nil
}

func stringAttribute(_ element: AXUIElement, _ name: CFString) -> String? {
    guard let value = attribute(element, name) else { return nil }
    if let text = value as? String { return text }
    if let number = value as? NSNumber { return number.stringValue }
    return nil
}

func boolAttribute(_ element: AXUIElement, _ name: CFString) -> Bool? {
    guard let value = attribute(element, name), let number = value as? NSNumber else {
        return nil
    }
    return number.boolValue
}

func pointAttribute(_ element: AXUIElement, _ name: CFString) -> CGPoint? {
    guard let value = attribute(element, name), CFGetTypeID(value) == AXValueGetTypeID() else {
        return nil
    }
    var point = CGPoint.zero
    if AXValueGetValue(value as! AXValue, .cgPoint, &point) { return point }
    return nil
}

func sizeAttribute(_ element: AXUIElement, _ name: CFString) -> CGSize? {
    guard let value = attribute(element, name), CFGetTypeID(value) == AXValueGetTypeID() else {
        return nil
    }
    var size = CGSize.zero
    if AXValueGetValue(value as! AXValue, .cgSize, &size) { return size }
    return nil
}

func frameObject(_ element: AXUIElement) -> [String: Double]? {
    guard
        let position = pointAttribute(element, kAXPositionAttribute as CFString),
        let size = sizeAttribute(element, kAXSizeAttribute as CFString)
    else { return nil }
    return [
        "x": Double(position.x),
        "y": Double(position.y),
        "w": Double(size.width),
        "h": Double(size.height),
    ]
}

let depthCap = Int(argumentValue("--max-depth") ?? "12") ?? 12
let nodeCap = 1500
var nodes = 0

func elementObject(_ element: AXUIElement, depth: Int) -> [String: Any] {
    nodes += 1
    var object: [String: Any] = [:]

    let role = stringAttribute(element, kAXRoleAttribute as CFString) ?? ""
    object["role"] = role
    let subrole = stringAttribute(element, kAXSubroleAttribute as CFString)
    if let subrole = subrole { object["subrole"] = subrole }

    if let title = stringAttribute(element, kAXTitleAttribute as CFString), !title.isEmpty {
        object["title"] = truncate(title, 200)
    }
    if let description = stringAttribute(element, kAXDescriptionAttribute as CFString), !description.isEmpty {
        object["description"] = truncate(description, 200)
    }
    if let identifier = stringAttribute(element, kAXIdentifierAttribute as CFString), !identifier.isEmpty {
        object["identifier"] = truncate(identifier, 200)
    }

    let secure = (subrole == "AXSecureTextField") || role.contains("Secure")
    if secure {
        object["secure"] = true
        object["value"] = "<redacted-secure>"
    } else if let value = stringAttribute(element, kAXValueAttribute as CFString), !value.isEmpty {
        object["value"] = truncate(value, 160)
    }

    if let enabled = boolAttribute(element, kAXEnabledAttribute as CFString) {
        object["enabled"] = enabled
    }
    if let focused = boolAttribute(element, kAXFocusedAttribute as CFString) {
        object["focused"] = focused
    }
    if let frame = frameObject(element) {
        object["frame"] = frame
    }

    if depth < depthCap, nodes < nodeCap,
       let children = attribute(element, kAXChildrenAttribute as CFString) as? [AXUIElement],
       !children.isEmpty {
        var childObjects: [[String: Any]] = []
        for child in children {
            if nodes >= nodeCap {
                object["truncated"] = true
                break
            }
            childObjects.append(elementObject(child, depth: depth + 1))
        }
        if !childObjects.isEmpty { object["children"] = childObjects }
    }
    return object
}

// MARK: - Window matching (read-only CG window list)

struct WindowEntry {
    let number: Int
    let x: Double
    let y: Double
    let w: Double
    let h: Double
}

func onScreenWindows(for pid: pid_t) -> [WindowEntry] {
    guard
        let infoList = CGWindowListCopyWindowInfo(
            [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
        ) as? [[String: Any]]
    else { return [] }
    var entries: [WindowEntry] = []
    for info in infoList {
        guard
            let owner = info[kCGWindowOwnerPID as String] as? Int, owner == Int(pid),
            let number = info[kCGWindowNumber as String] as? Int,
            let boundsDict = info[kCGWindowBounds as String] as? NSDictionary,
            let rect = CGRect(dictionaryRepresentation: boundsDict as CFDictionary)
        else { continue }
        entries.append(
            WindowEntry(
                number: number,
                x: Double(rect.origin.x),
                y: Double(rect.origin.y),
                w: Double(rect.width),
                h: Double(rect.height)
            )
        )
    }
    return entries
}

func matchingWindowNumber(_ frame: [String: Double], entries: [WindowEntry]) -> Int? {
    guard
        let x = frame["x"], let y = frame["y"], let w = frame["w"], let h = frame["h"]
    else { return nil }
    for entry in entries {
        if abs(entry.x - x) <= 2.0, abs(entry.y - y) <= 2.0,
           abs(entry.w - w) <= 2.0, abs(entry.h - h) <= 2.0 {
            return entry.number
        }
    }
    return nil
}

// MARK: - Application snapshot

if mode == "--windows" || mode == "--dump" {
    guard AXIsProcessTrusted() else {
        writeJSON(["error": "permission", "trusted": false], code: 2)
    }

    let pid: pid_t
    if let raw = argumentValue("--pid") {
        guard let parsed = Int32(raw), parsed > 0 else { fail("--pid must be a positive integer", code: 3) }
        pid = parsed
    } else if let wanted = argumentValue("--app") {
        let target = wanted.lowercased()
        guard let app = NSWorkspace.shared.runningApplications.first(where: {
            ($0.localizedName ?? "").lowercased() == target
        }) else {
            fail("no running application named \(wanted)", code: 4)
        }
        pid = app.processIdentifier
    } else {
        guard let front = NSWorkspace.shared.frontmostApplication else {
            fail("no frontmost application", code: 4)
        }
        pid = front.processIdentifier
    }
    let appName = NSRunningApplication(processIdentifier: pid)?.localizedName ?? "Unknown"

    let appElement = AXUIElementCreateApplication(pid)
    let axWindows = attribute(appElement, kAXWindowsAttribute as CFString) as? [AXUIElement] ?? []
    let focusedWindow = attribute(appElement, kAXFocusedWindowAttribute as CFString)
    let cgEntries = mode == "--dump" ? onScreenWindows(for: pid) : []

    var windowsOut: [[String: Any]] = []
    for window in axWindows {
        var object: [String: Any] = [:]
        if let title = stringAttribute(window, kAXTitleAttribute as CFString) {
            object["title"] = truncate(title, 200)
        }
        let windowFrame = frameObject(window)
        if let windowFrame = windowFrame {
            object["frame"] = windowFrame
        }
        if let focusedWindow = focusedWindow {
            object["focused"] = CFEqual(focusedWindow, window)
        }
        if mode == "--dump" {
            if let windowFrame = windowFrame, let number = matchingWindowNumber(windowFrame, entries: cgEntries) {
                object["cg_window_id"] = number
            }
            // The window's own element object duplicates the window meta above;
            // only its children are attached.
            let windowElement = elementObject(window, depth: 0)
            if let children = windowElement["children"] {
                object["elements"] = children
            }
        }
        windowsOut.append(object)
    }

    writeJSON(
        [
            "app": appName,
            "pid": Int(pid),
            "trusted": true,
            "windows": windowsOut,
        ],
        code: 0
    )
}

fail(
    "usage: ax_dump --check | --request-permission | --windows | --dump "
        + "[--pid N | --app NAME | --frontmost] [--max-depth D]",
    code: 3
)
