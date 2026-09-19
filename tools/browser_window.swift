// M018B disposable browser helper: one WKWebView, fixed viewport, JSON-lines
// protocol on stdin/stdout.
//
// Safety posture (frozen in VISION_STATE M018B):
// - Non-persistent website data: no session, no profile, no cookies survive.
// - Navigation allowed only to the configured loopback port; everything else
//   is cancelled and counted (`blocked`).
// - Observation is a WebKit self-snapshot written by the caller-provided path
//   (no screen recording, no occlusion sensitivity).
// - Input is synthesized as in-app NSEvents delivered to this window's web
//   view only: no low-level event-posting APIs, no OS-level posting exists in
//   this file, so no other application can ever receive these events and no
//   input permission is required.
// - Typing requires a focused editable, non-password element (checked via a
//   trusted-side script before any key event is synthesized).
//
// Usage: browser_window --port <fixture-port> [--width 1280] [--height 720]
// Commands (one JSON object per line on stdin, one reply per line on stdout):
//   {"id":1,"cmd":"navigate","url":"/news/"}
//   {"id":2,"cmd":"snapshot","path":"/tmp/x.png"}
//   {"id":3,"cmd":"click","x":220.0,"y":35.0,"seq":1}
//   {"id":4,"cmd":"type","text":"hello"}
//   {"id":5,"cmd":"key","key":"enter"}
//   {"id":6,"cmd":"scroll","direction":"down","amount":2}
//   {"id":7,"cmd":"back"}
//   {"id":8,"cmd":"state"}
//   {"id":9,"cmd":"quit"}

import AppKit
import WebKit

final class Out {
    private let lock = NSLock()

    func send(_ payload: [String: Any]) {
        lock.lock()
        defer { lock.unlock() }
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let line = String(data: data, encoding: .utf8) else { return }
        print(line)
        fflush(stdout)
    }
}

final class Helper: NSObject, WKNavigationDelegate {
    let out = Out()
    let width: CGFloat
    let height: CGFloat
    let port: Int
    var window: NSWindow!
    var webView: WKWebView!
    var seq = 0
    var blocked = 0
    var loading = false
    var pendingLoadId: Int?
    var startedAt = Date()

    init(width: CGFloat, height: CGFloat, port: Int) {
        self.width = width
        self.height = height
        self.port = port
    }

    func start() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(
            frame: NSRect(x: 0, y: 0, width: width, height: height),
            configuration: configuration)
        webView.navigationDelegate = self
        window = NSWindow(
            contentRect: NSRect(x: 90, y: 90, width: width, height: height),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "browser_window (disposable)"
        window.isReleasedWhenClosed = false
        window.contentView = webView
        if #available(macOS 14.0, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(webView)
    }

    // ------------------------------------------------------------ navigation

    func allowed(_ url: URL) -> Bool {
        if url.scheme == "about" { return true }
        guard url.scheme == "http" else { return false }
        guard let host = url.host, host == "127.0.0.1" || host == "localhost" else { return false }
        return url.port == self.port
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let target = navigationAction.request.url ?? URL(string: "about:blank")!
        if allowed(target) {
            decisionHandler(.allow)
        } else {
            blocked += 1
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        loading = true
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loading = false
        finishPendingLoad(error: nil)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        loading = false
        finishPendingLoad(error: error)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        loading = false
        finishPendingLoad(error: error)
    }

    func finishPendingLoad(error: Error?) {
        guard let id = pendingLoadId else { return }
        pendingLoadId = nil
        if let error = error {
            respond(id, ["ok": false, "error": "navigation_failed",
                         "detail": error.localizedDescription])
        } else {
            respond(id, ["ok": true, "url": currentURL()])
        }
    }

    func currentURL() -> String {
        return webView.url?.absoluteString ?? "about:blank"
    }

    // --------------------------------------------------------------- replies

    func respond(_ id: Int, _ payload: [String: Any]) {
        var reply = payload
        reply["id"] = id
        out.send(reply)
    }

    // -------------------------------------------------------------- commands

    func handle(id: Int, cmd: String, req: [String: Any]) {
        switch cmd {
        case "navigate":
            guard let raw = req["url"] as? String, let url = resolveURL(raw) else {
                respond(id, ["ok": false, "error": "bad_url"]); return
            }
            guard allowed(url) else {
                respond(id, ["ok": false, "error": "blocked_origin", "url": raw]); return
            }
            pendingLoadId = id
            webView.load(URLRequest(url: url))
            DispatchQueue.main.asyncAfter(deadline: .now() + 8.0) { [weak self] in
                guard let self = self, self.pendingLoadId == id else { return }
                self.pendingLoadId = nil
                self.respond(id, ["ok": false, "error": "navigation_timeout",
                                  "url": self.currentURL()])
            }
        case "snapshot":
            guard let path = req["path"] as? String else {
                respond(id, ["ok": false, "error": "missing_path"]); return
            }
            snapshot(id: id, path: path)
        case "click":
            click(id: id, req: req)
        case "type":
            typeText(id: id, req: req)
        case "key":
            pressKey(id: id, req: req)
        case "scroll":
            scrollPage(id: id, req: req)
        case "back":
            webView.goBack()
            respond(id, ["ok": true, "url": currentURL()])
        case "state":
            state(id: id)
        case "quit":
            respond(id, ["ok": true])
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                NSApp.terminate(nil)
            }
        default:
            respond(id, ["ok": false, "error": "unknown_command"])
        }
    }

    func resolveURL(_ raw: String) -> URL? {
        if raw.hasPrefix("/") {
            return URL(string: "http://127.0.0.1:\(port)\(raw)")
        }
        return URL(string: raw)
    }

    func snapshot(id: Int, path: String) {
        let configuration = WKSnapshotConfiguration()
        configuration.snapshotWidth = NSNumber(value: Double(width))
        webView.takeSnapshot(with: configuration) { [weak self] image, error in
            guard let self = self else { return }
            if error != nil || image == nil {
                self.respond(id, ["ok": false, "error": "snapshot_failed"]); return
            }
            guard let tiff = image!.tiffRepresentation,
                  let rep = NSBitmapImageRep(data: tiff),
                  let png = rep.representation(using: .png, properties: [:]) else {
                self.respond(id, ["ok": false, "error": "encode_failed"]); return
            }
            do {
                try png.write(to: URL(fileURLWithPath: path))
            } catch {
                self.respond(id, ["ok": false, "error": "write_failed"]); return
            }
            self.seq += 1
            let pixelsWide = rep.pixelsWide
            let pixelsHigh = rep.pixelsHigh
            let scale = Double(pixelsWide) / Double(self.width)
            self.respond(id, [
                "ok": true,
                "seq": self.seq,
                "width": pixelsWide,
                "height": pixelsHigh,
                "scale": scale,
                "css_width": Double(self.width),
                "css_height": Double(self.height),
                "url": self.currentURL(),
            ])
        }
    }

    func click(id: Int, req: [String: Any]) {
        guard !loading else { respond(id, ["ok": false, "error": "navigating"]); return }
        guard let x = (req["x"] as? NSNumber)?.doubleValue,
              let y = (req["y"] as? NSNumber)?.doubleValue else {
            respond(id, ["ok": false, "error": "bad_point"]); return
        }
        let currentSeq = self.seq
        if let requested = (req["seq"] as? NSNumber)?.intValue, requested != currentSeq {
            respond(id, ["ok": false, "error": "stale_frame", "seq": currentSeq]); return
        }
        guard x >= 0, y >= 0, x < Double(width), y < Double(height) else {
            respond(id, ["ok": false, "error": "outside_viewport"]); return
        }
        let point = NSPoint(x: x, y: Double(height) - y)
        guard let down = mouseEvent(.leftMouseDown, at: point),
              let up = mouseEvent(.leftMouseUp, at: point) else {
            respond(id, ["ok": false, "error": "event_failed"]); return
        }
        window.sendEvent(down)
        window.sendEvent(up)
        respond(id, ["ok": true, "url": currentURL()])
    }

    func mouseEvent(_ type: NSEvent.EventType, at point: NSPoint) -> NSEvent? {
        return NSEvent.mouseEvent(
            with: type, location: point, modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: window.windowNumber, context: nil,
            eventNumber: 0, clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0)
    }

    let focusScript = """
    (function(){var e=document.activeElement||document.body;var t=(e.getAttribute&&e.getAttribute('type'))||'';
    return JSON.stringify({tag:e.tagName,type:t.toLowerCase(),
    editable:!!(e.isContentEditable||e.tagName==='INPUT'||e.tagName==='TEXTAREA'),
    password:t.toLowerCase()==='password',valueLength:(e.value||'').length});})()
    """

    func typeText(id: Int, req: [String: Any]) {
        guard !loading else { respond(id, ["ok": false, "error": "navigating"]); return }
        guard let text = req["text"] as? String else {
            respond(id, ["ok": false, "error": "bad_text"]); return
        }
        if text.count > 200 { respond(id, ["ok": false, "error": "too_long"]); return }
        webView.evaluateJavaScript(focusScript) { [weak self] result, _ in
            guard let self = self else { return }
            guard let json = result as? String,
                  let data = json.data(using: .utf8),
                  let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.respond(id, ["ok": false, "error": "focus_unreadable"]); return
            }
            let editable = (info["editable"] as? Bool) ?? false
            let password = (info["password"] as? Bool) ?? false
            if password {
                self.respond(id, ["ok": false, "error": "password_field"]); return
            }
            if !editable {
                self.respond(id, ["ok": false, "error": "no_editable_focus"]); return
            }
            // One key event carries the whole string: multi-character key
            // events insert the full text reliably, while rapid per-character
            // events can coalesce in the text-input pipeline (observed live).
            self.sendKey(text, keyCode: 0)
            self.respond(id, ["ok": true, "typed": text.count])
        }
    }

    let specialKeys: [String: (String, UInt16)] = [
        "enter": ("\r", 36),
        "tab": ("\t", 48),
        "escape": ("\u{1b}", 53),
        "backspace": ("\u{8}", 51),
        "arrow_down": ("\u{F701}", 125),
        "arrow_up": ("\u{F700}", 126),
        "page_down": ("\u{F72D}", 121),
        "page_up": ("\u{F72C}", 116),
    ]

    func pressKey(id: Int, req: [String: Any]) {
        guard !loading else { respond(id, ["ok": false, "error": "navigating"]); return }
        guard let name = req["key"] as? String, let (characters, keyCode) = specialKeys[name] else {
            respond(id, ["ok": false, "error": "bad_key"]); return
        }
        sendKey(characters, keyCode: keyCode)
        respond(id, ["ok": true])
    }

    func sendKey(_ characters: String, keyCode: UInt16) {
        guard let down = keyEvent(.keyDown, characters: characters, keyCode: keyCode),
              let up = keyEvent(.keyUp, characters: characters, keyCode: keyCode) else { return }
        window.sendEvent(down)
        window.sendEvent(up)
    }

    func keyEvent(_ type: NSEvent.EventType, characters: String, keyCode: UInt16) -> NSEvent? {
        return NSEvent.keyEvent(
            with: type, location: .zero, modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: window.windowNumber, context: nil,
            characters: characters, charactersIgnoringModifiers: characters,
            isARepeat: false, keyCode: keyCode)
    }

    func scrollPage(id: Int, req: [String: Any]) {
        guard !loading else { respond(id, ["ok": false, "error": "navigating"]); return }
        let direction = (req["direction"] as? String) ?? ""
        let amount = (req["amount"] as? NSNumber)?.intValue ?? 0
        guard direction == "up" || direction == "down" else {
            respond(id, ["ok": false, "error": "bad_direction"]); return
        }
        guard amount >= 1 && amount <= 10 else {
            respond(id, ["ok": false, "error": "bad_amount"]); return
        }
        let (characters, keyCode) = direction == "down" ? specialKeys["page_down"]! : specialKeys["page_up"]!
        for _ in 0..<amount {
            sendKey(characters, keyCode: keyCode)
            usleep(25000)
        }
        respond(id, ["ok": true, "pages": amount])
    }

    func state(id: Int) {
        let script = """
        (function(){return JSON.stringify({url:location.href,ready:document.readyState});})()
        """
        webView.evaluateJavaScript(script) { [weak self] result, _ in
            guard let self = self else { return }
            var payload: [String: Any] = [
                "ok": true,
                "seq": self.seq,
                "loading": self.loading,
                "blocked": self.blocked,
                "can_go_back": self.webView.canGoBack,
                "url": self.currentURL(),
            ]
            if let json = result as? String,
               let data = json.data(using: .utf8),
               let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                payload["page"] = info
            }
            self.webView.evaluateJavaScript(self.focusScript) { focused, _ in
                if let json = focused as? String,
                   let data = json.data(using: .utf8),
                   let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    payload["focused"] = info
                }
                self.respond(id, payload)
            }
        }
    }

    func readerLoop() {
        while let line = readLine(strippingNewline: true) {
            guard let data = line.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let id = object["id"] as? Int,
                  let cmd = object["cmd"] as? String else {
                out.send(["ok": false, "error": "bad_command"])
                continue
            }
            DispatchQueue.main.async { self.handle(id: id, cmd: cmd, req: object) }
        }
        DispatchQueue.main.async { NSApp.terminate(nil) }
    }
}

// ---------------------------------------------------------------- bootstrap

var port = 0
var width = 1280.0
var height = 720.0
var index = 1
let arguments = CommandLine.arguments
while index < arguments.count {
    let key = arguments[index]
    let value = index + 1 < arguments.count ? arguments[index + 1] : ""
    switch key {
    case "--port": port = Int(value) ?? 0
    case "--width": width = Double(value) ?? 1280.0
    case "--height": height = Double(value) ?? 720.0
    default: break
    }
    index += 2
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let helper: Helper

    init(port: Int, width: Double, height: Double) {
        helper = Helper(width: CGFloat(width), height: CGFloat(height), port: port)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        helper.start()
        helper.out.send(["ok": true, "event": "ready", "port": helper.port,
                         "css_width": Double(helper.width), "css_height": Double(helper.height)])
        DispatchQueue.global(qos: .userInitiated).async {
            self.helper.readerLoop()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate(port: port, width: width, height: height)
app.delegate = delegate
app.run()
