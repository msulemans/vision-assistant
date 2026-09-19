// M013 supervised executor helper: the ONLY action-capable artifact in the
// project. Everything else reads.
//
// Modes:
//   ax_action --check     report the Accessibility trust state
//   ax_action --plan      evaluate every guard and post nothing
//   ax_action --perform   execute the action described on stdin
//
// The JSON spec arrives on stdin:
//   {"action":"press"|"type"|"key", "app":"Practice App",
//    "window_title":"Practice App", "element":{"identifier":"app:sync-toggle"},
//    "text":"hello", "key":"escape", "expect_window_frame":[x,y,w,h]}
//
// Output is one JSON object on stdout. Exit codes: 0 = performed or clean
// refusal, 2 = permission missing, 3 = usage/bad spec, 4 = runtime failure.
//
// Safety posture: clicks are AXPress actions on an element found by stable
// identifier — never coordinates; typing sets and re-reads AX focus first;
// key events require the target app to be frontmost; window geometry is
// re-verified (stale-frame guard); secure and disabled elements are refused.
// There are no synthetic mouse events anywhere in this file.
//
// Build: swiftc -O tools/ax_action.swift -o runs/m013-tools/ax_action

import AppKit
import ApplicationServices
import Foundation

let arguments = CommandLine.arguments

func emit(_ object: [String: Any], code: Int32) -> Never {
    do {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    } catch {
        FileHandle.standardError.write(Data("failed to encode JSON\n".utf8))
        exit(4)
    }
    exit(code)
}

func refuse(_ reason: String, code: Int32 = 0, extra: [String: Any] = [:]) -> Never {
    var object = extra
    object["performed"] = false
    object["reason"] = reason
    emit(object, code: code)
}

let mode = arguments.count >= 2 ? arguments[1] : ""

if mode == "--check" {
    emit(["trusted": AXIsProcessTrusted()], code: 0)
}

guard mode == "--plan" || mode == "--perform" else {
    FileHandle.standardError.write(Data("usage: ax_action --check | --plan | --perform\n".utf8))
    exit(3)
}

guard AXIsProcessTrusted() else {
    refuse("permission", code: 2)
}

let inputData = FileHandle.standardInput.readDataToEndOfFile()
guard
    let parsed = try? JSONSerialization.jsonObject(with: inputData),
    let spec = parsed as? [String: Any]
else {
    refuse("bad_spec", code: 3)
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

func frameObject(_ element: AXUIElement) -> [String: Double]? {
    guard
        let positionValue = attribute(element, kAXPositionAttribute as CFString),
        let sizeValue = attribute(element, kAXSizeAttribute as CFString),
        CFGetTypeID(positionValue) == AXValueGetTypeID(),
        CFGetTypeID(sizeValue) == AXValueGetTypeID()
    else { return nil }
    var point = CGPoint.zero
    var size = CGSize.zero
    guard
        AXValueGetValue(positionValue as! AXValue, .cgPoint, &point),
        AXValueGetValue(sizeValue as! AXValue, .cgSize, &size)
    else { return nil }
    return [
        "x": Double(point.x),
        "y": Double(point.y),
        "w": Double(size.width),
        "h": Double(size.height),
    ]
}

func pidForAppName(_ name: String) -> pid_t? {
    let wanted = name.lowercased()
    for app in NSWorkspace.shared.runningApplications {
        let candidates = [
            app.localizedName,
            app.executableURL?.lastPathComponent,
            app.bundleURL?.deletingPathExtension().lastPathComponent,
        ]
        if candidates.compactMap({ $0?.lowercased() }).contains(wanted) {
            return app.processIdentifier
        }
    }
    return nil
}

func findElements(_ element: AXUIElement, identifier: String, depth: Int = 0) -> [AXUIElement] {
    var matches: [AXUIElement] = []
    if stringAttribute(element, kAXIdentifierAttribute as CFString) == identifier {
        matches.append(element)
    }
    if depth < 16, let children = attribute(element, kAXChildrenAttribute as CFString) as? [AXUIElement] {
        for child in children {
            matches.append(contentsOf: findElements(child, identifier: identifier, depth: depth + 1))
        }
    }
    return matches
}

func matchObject(_ element: AXUIElement) -> [String: Any] {
    var object: [String: Any] = [:]
    object["role"] = stringAttribute(element, kAXRoleAttribute as CFString) ?? ""
    object["title"] = stringAttribute(element, kAXTitleAttribute as CFString) ?? NSNull()
    object["identifier"] = stringAttribute(element, kAXIdentifierAttribute as CFString) ?? NSNull()
    if let frame = frameObject(element) { object["frame"] = frame }
    object["enabled"] = boolAttribute(element, kAXEnabledAttribute as CFString).map { $0 as Any } ?? NSNull()
    return object
}

// MARK: - Resolve target app and window

guard let appName = spec["app"] as? String else {
    refuse("bad_spec", code: 3)
}
guard let pid = pidForAppName(appName) else {
    refuse("app_not_running")
}

let appElement = AXUIElementCreateApplication(pid)
let axWindows = attribute(appElement, kAXWindowsAttribute as CFString) as? [AXUIElement] ?? []

let windowTitle = spec["window_title"] as? String
var window: AXUIElement?
if let windowTitle = windowTitle {
    for candidate in axWindows {
        if stringAttribute(candidate, kAXTitleAttribute as CFString) == windowTitle {
            window = candidate
            break
        }
    }
} else {
    window = axWindows.first
}
guard let targetWindow = window else {
    refuse("window_missing")
}

if let expected = spec["expect_window_frame"] as? [Double], expected.count == 4,
   let actual = frameObject(targetWindow) {
    let actualValues = [actual["x"]!, actual["y"]!, actual["w"]!, actual["h"]!]
    for (wanted, got) in zip(expected, actualValues) where abs(wanted - got) > 1.0 {
        refuse("stale_frame", extra: ["expected_frame": expected, "window_frame": actualValues])
    }
}

// MARK: - Guards for element actions

let action = spec["action"] as? String ?? ""

let pressedRoles: Set<String> = [
    "AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXMenuItem",
]
let typedRoles: Set<String> = ["AXTextField", "AXTextArea", "AXComboBox"]

func elementGuards(_ element: AXUIElement, allowedRoles: Set<String>) -> ([String: Any], String?) {
    var match = matchObject(element)
    let role = match["role"] as? String ?? ""
    let subrole = stringAttribute(element, kAXSubroleAttribute as CFString) ?? ""
    let secure = subrole == "AXSecureTextField" || role.contains("Secure")
    match["secure"] = secure
    if secure { return (match, "secure_element") }
    if boolAttribute(element, kAXEnabledAttribute as CFString) == false { return (match, "disabled_element") }
    if !allowedRoles.contains(role) { return (match, "role_mismatch") }
    return (match, nil)
}

switch action {
case "press", "type":
    guard
        let elementSpec = spec["element"] as? [String: Any],
        let identifier = elementSpec["identifier"] as? String
    else {
        refuse("bad_spec", code: 3)
    }
    let matches = findElements(targetWindow, identifier: identifier)
    if matches.isEmpty { refuse("not_found", extra: ["identifier": identifier]) }
    if matches.count > 1 { refuse("ambiguous", extra: ["identifier": identifier, "matches": matches.count]) }
    let element = matches[0]
    let allowed = action == "press" ? pressedRoles : typedRoles
    let (match, refusal) = elementGuards(element, allowedRoles: allowed)
    if let refusal = refusal { refuse(refusal, extra: ["match": match]) }

    if mode == "--plan" {
        emit(["performed": false, "planned": true, "match": match], code: 0)
    }

    if action == "press" {
        let result = AXUIElementPerformAction(element, kAXPressAction as CFString)
        guard result == .success else {
            refuse("perform_failed", extra: ["ax_error": Int(result.rawValue), "match": match])
        }
        emit(["performed": true, "action": "press", "match": match, "key_events": 0], code: 0)
    }

    // type: activate the target app, verify frontmost, focus, re-read, then
    // post Unicode key events. Keys can never land in another app: the
    // frontmost check runs immediately before posting and refuses otherwise.
    guard let text = spec["text"] as? String, !text.isEmpty, text.count <= 200 else {
        refuse("bad_spec", code: 3)
    }
    if text.unicodeScalars.contains(where: { $0.value < 32 }) {
        refuse("bad_spec", code: 3)
    }
    if let running = NSRunningApplication(processIdentifier: pid) {
        if #available(macOS 14.0, *) {
            running.activate()
        } else {
            running.activate(options: [.activateIgnoringOtherApps])
        }
    }
    var frontmostOK = false
    for _ in 0..<20 {
        if let front = NSWorkspace.shared.frontmostApplication, front.processIdentifier == pid {
            frontmostOK = true
            break
        }
        usleep(50000)
    }
    guard frontmostOK else {
        refuse("frontmost_mismatch", extra: ["match": match])
    }
    let focusResult = AXUIElementSetAttributeValue(
        element, kAXFocusedAttribute as CFString, kCFBooleanTrue
    )
    guard focusResult == .success, boolAttribute(element, kAXFocusedAttribute as CFString) == true else {
        refuse("focus_failed", extra: ["match": match])
    }
    var keyEvents = 0
    for character in text {
        guard
            let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true),
            let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false)
        else { refuse("perform_failed") }
        var units = Array(String(character).utf16)
        down.keyboardSetUnicodeString(stringLength: units.count, unicodeString: &units)
        up.keyboardSetUnicodeString(stringLength: units.count, unicodeString: &units)
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        keyEvents += 2
        usleep(8000)
    }
    emit(["performed": true, "action": "type", "match": match, "key_events": keyEvents], code: 0)

case "key":
    guard let key = spec["key"] as? String else {
        refuse("bad_spec", code: 3)
    }
    let keyCodes: [String: CGKeyCode] = ["escape": 53, "return": 36, "tab": 48]
    guard let keyCode = keyCodes[key] else {
        refuse("bad_spec", code: 3)
    }
    guard let front = NSWorkspace.shared.frontmostApplication, front.processIdentifier == pid else {
        refuse("frontmost_mismatch", extra: ["key": key])
    }
    if mode == "--plan" {
        emit(["performed": false, "planned": true, "match": ["key": key]], code: 0)
    }
    guard
        let down = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: true),
        let up = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: false)
    else { refuse("perform_failed") }
    down.post(tap: .cghidEventTap)
    up.post(tap: .cghidEventTap)
    emit(["performed": true, "action": "key", "match": ["key": key], "key_events": 2], code: 0)

default:
    refuse("bad_spec", code: 3)
}
