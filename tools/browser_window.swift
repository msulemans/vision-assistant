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
//        [--live-host <host>]   (M018E pilot scope change: when set, https://<host>
//                                is additionally allowed; absent = loopback-only,
//                                the frozen default. All other origins stay cancelled.)
// Commands (one JSON object per line on stdin, one reply per line on stdout):
//   {"id":1,"cmd":"navigate","url":"/news/"}
//   {"id":2,"cmd":"snapshot","path":"/tmp/x.png"}
//   {"id":3,"cmd":"click","x":220.0,"y":35.0,"seq":1}
//   {"id":10,"cmd":"targets"}                      (M018T: visible target list)
//   {"id":11,"cmd":"click_target","target":"t3","seq":1}
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
    var targetMeta: [String: [String: Any]] = [:]
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
        if let live = liveHost, url.scheme == "https", url.host == live {
            return url.port == nil || url.port == 443
        }
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
        case "targets":
            targetsCommand(id: id)
        case "click":
            click(id: id, req: req)
        case "click_target":
            clickTarget(id: id, req: req)
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
        guard sendClickEvents(at: point) else {
            respond(id, ["ok": false, "error": "event_failed"]); return
        }
        respond(id, ["ok": true, "url": currentURL()])
    }

    /// The single in-app click synthesis path (raw click and click_target).
    func sendClickEvents(at point: NSPoint) -> Bool {
        guard let down = mouseEvent(.leftMouseDown, at: point),
              let up = mouseEvent(.leftMouseUp, at: point) else { return false }
        window.sendEvent(down)
        window.sendEvent(up)
        return true
    }

    // ----------------------------------------------------------- M018T targets
    // Target-assisted observation (frozen in docs/M018T_TARGET_ASSISTED_PLAN.md):
    // a bounded list of visible actionable targets with opaque ids; clicks are
    // resolved by trusted code against the current frame. The extraction script
    // is compiled in — never sent over the protocol — and reads only the visible
    // rendered surface (no values, URLs, storage, hidden content, or scripts).

    let extractScript = """
    (function(){
    function collapse(s){return (s||"").replace(/[\\u0000-\\u001f\\u007f]+/g," ").replace(/\\s+/g," ").trim();}
    function cap(s,n){return s.length>n?s.slice(0,n):s;}
    function textOf(el){var t=el.innerText;if(t===undefined||t===null){t=el.textContent;}return collapse(t);}
    function labelOf(el,role){
    if(role==="link"||role==="button"){return cap(textOf(el),80)||"(no label)";}
    if(role==="select"){var o=el.selectedOptions&&el.selectedOptions[0];return cap(o?collapse(o.text||o.textContent):"",80)||"(no label)";}
    var t="";var lab=el.closest?el.closest("label"):null;
    if(!lab&&el.id){var q=document.querySelector('label[for="'+CSS.escape(el.id)+'"]');if(q){lab=q;}}
    if(lab){t=collapse(lab.innerText);}
    if(!t&&(role==="text_input"||role==="textarea")&&typeof el.placeholder==="string"){t=collapse(el.placeholder);}
    return cap(t,80)||"(no label)";
    }
    function roleOf(el){
    var name=el.tagName.toLowerCase();
    if(name==="a"){return "link";}
    if(name==="button"){return "button";}
    if(name==="select"){return "select";}
    if(name==="textarea"){return "textarea";}
    if(name==="input"){
    var t=(el.type||"text").toLowerCase();
    if(t==="checkbox"){return "checkbox";}
    if(t==="radio"){return "radio";}
    if(t==="submit"||t==="button"){return "button";}
    if(t==="text"||t==="search"||t==="email"||t==="url"||t==="tel"||t==="number"||t==="date"||t==="month"||t==="week"||t==="time"||t==="datetime-local"){return "text_input";}
    return null;
    }
    return null;
    }
    var els=document.querySelectorAll("a[href], button, input, select, textarea");
    var out=[];var total=0;var w=window.innerWidth;var h=window.innerHeight;
    window.__m018Targets={};
    for(var i=0;i<els.length;i++){
    var el=els[i];
    var role=roleOf(el);
    if(!role){continue;}
    if(el.closest('[aria-hidden="true"]')){continue;}
    if(el.getClientRects().length===0){continue;}
    var cs=window.getComputedStyle(el);
    if(cs.visibility==="hidden"||cs.visibility==="collapse"){continue;}
    if(cs.opacity==="0"){continue;}
    var r=el.getBoundingClientRect();
    var x=Math.max(0,r.left);var y=Math.max(0,r.top);
    var x2=Math.min(w,r.right);var y2=Math.min(h,r.bottom);
    if(x2-x<2||y2-y<2){continue;}
    total++;
    if(out.length>=40){continue;}
    var id="t"+(out.length+1);
    var disabled=(!!el.disabled)||el.matches('[aria-disabled="true"]')||cs.pointerEvents==="none";
    window.__m018Targets[id]=el;
    out.push({id:id,role:role,label:labelOf(el,role),rect:[x,y,x2-x,y2-y],
    enabled:!disabled,focused:document.activeElement===el});
    }
    return JSON.stringify({total:total,truncated:total>out.length,targets:out});
    })()
    """

    func targetsCommand(id: Int) {
        guard !loading else { respond(id, ["ok": false, "error": "navigating"]); return }
        webView.evaluateJavaScript(extractScript) { [weak self] result, _ in
            guard let self = self else { return }
            guard let json = result as? String,
                  let data = json.data(using: .utf8),
                  let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let raw = info["targets"] as? [[String: Any]] else {
                self.respond(id, ["ok": false, "error": "targets_unreadable"]); return
            }
            var meta: [String: [String: Any]] = [:]
            var clean: [[String: Any]] = []
            for item in raw {
                guard let tId = item["id"] as? String,
                      let role = item["role"] as? String,
                      let rect = item["rect"] as? [NSNumber], rect.count == 4 else { continue }
                let values = rect.map { $0.doubleValue }
                guard values.allSatisfy({ $0.isFinite }) else { continue }
                let label = String(((item["label"] as? String) ?? "(no label)").prefix(80))
                meta[tId] = ["rect": values]
                clean.append([
                    "id": tId, "role": role, "label": label, "rect": values,
                    "enabled": (item["enabled"] as? Bool) ?? false,
                    "focused": (item["focused"] as? Bool) ?? false,
                ])
            }
            self.targetMeta = meta
            self.respond(id, [
                "ok": true,
                "seq": self.seq,
                "total": (info["total"] as? NSNumber)?.intValue ?? clean.count,
                "truncated": (info["truncated"] as? Bool) ?? false,
                "targets": clean,
            ])
        }
    }

    func clickTarget(id: Int, req: [String: Any]) {
        guard !loading else { respond(id, ["ok": false, "error": "navigating"]); return }
        guard let target = req["target"] as? String,
              target.range(of: "^t[1-9][0-9]{0,2}$", options: .regularExpression) != nil else {
            respond(id, ["ok": false, "error": "refused_target_stale",
                         "detail": "malformed id"]); return
        }
        let currentSeq = self.seq
        if let requested = (req["seq"] as? NSNumber)?.intValue, requested != currentSeq {
            respond(id, ["ok": false, "error": "refused_target_stale",
                         "detail": "seq_mismatch", "seq": currentSeq]); return
        }
        guard let stored = targetMeta[target],
              let storedRect = stored["rect"] as? [Double], storedRect.count == 4 else {
            respond(id, ["ok": false, "error": "refused_target_stale",
                         "detail": "unknown_id"]); return
        }
        let script = """
        (function(){var el=(window.__m018Targets||{})["\(target)"];
        if(!el){return JSON.stringify({found:false});}
        var out={found:true,connected:!!el.isConnected};
        if(!out.connected){return JSON.stringify(out);}
        var cs=window.getComputedStyle(el);
        out.rendered=(el.getClientRects().length>0)&&cs.visibility!=="hidden"&&cs.visibility!=="collapse"&&cs.opacity!=="0"&&!el.closest('[aria-hidden="true"]');
        out.enabled=(!el.disabled)&&!el.matches('[aria-disabled="true"]')&&cs.pointerEvents!=="none";
        var r=el.getBoundingClientRect();var vw=window.innerWidth;var vh=window.innerHeight;
        var x=Math.max(0,r.left);var y=Math.max(0,r.top);
        var x2=Math.min(vw,r.right);var y2=Math.min(vh,r.bottom);
        out.rect=[x,y,Math.max(0,x2-x),Math.max(0,y2-y)];out.view_w=vw;out.view_h=vh;
        return JSON.stringify(out);})()
        """
        webView.evaluateJavaScript(script) { [weak self] result, _ in
            guard let self = self else { return }
            guard let json = result as? String,
                  let data = json.data(using: .utf8),
                  let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.respond(id, ["ok": false, "error": "targets_unreadable"]); return
            }
            if (info["found"] as? Bool) != true {
                self.respond(id, ["ok": false, "error": "refused_target_stale",
                                  "detail": "gone"]); return
            }
            if (info["connected"] as? Bool) != true {
                self.respond(id, ["ok": false, "error": "refused_target_stale",
                                  "detail": "detached"]); return
            }
            if (info["rendered"] as? Bool) != true {
                self.respond(id, ["ok": false, "error": "refused_target_hidden"]); return
            }
            if (info["enabled"] as? Bool) != true {
                self.respond(id, ["ok": false, "error": "refused_target_disabled"]); return
            }
            guard let freshRect = info["rect"] as? [NSNumber], freshRect.count == 4 else {
                self.respond(id, ["ok": false, "error": "targets_unreadable"]); return
            }
            let fresh = freshRect.map { $0.doubleValue }
            let (fx, fy, fw, fh) = (fresh[0], fresh[1], fresh[2], fresh[3])
            let moved = abs(fx - storedRect[0]) > 2.0 || abs(fy - storedRect[1]) > 2.0
                || abs(fw - storedRect[2]) > 2.0 || abs(fh - storedRect[3]) > 2.0
            if moved {
                self.respond(id, ["ok": false, "error": "refused_target_moved"]); return
            }
            let cx = fx + fw / 2.0
            let cy = fy + fh / 2.0
            let vw = (info["view_w"] as? NSNumber)?.doubleValue ?? Double(self.width)
            let vh = (info["view_h"] as? NSNumber)?.doubleValue ?? Double(self.height)
            if fw < 2.0 || fh < 2.0 || cx < 0 || cy < 0 || cx >= vw || cy >= vh {
                self.respond(id, ["ok": false, "error": "refused_target_offscreen"]); return
            }
            guard self.sendClickEvents(at: NSPoint(x: cx, y: Double(self.height) - cy)) else {
                self.respond(id, ["ok": false, "error": "event_failed"]); return
            }
            self.respond(id, ["ok": true, "url": self.currentURL()])
        }
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
var liveHost: String? = nil
var index = 1
let arguments = CommandLine.arguments
while index < arguments.count {
    let key = arguments[index]
    let value = index + 1 < arguments.count ? arguments[index + 1] : ""
    switch key {
    case "--port": port = Int(value) ?? 0
    case "--width": width = Double(value) ?? 1280.0
    case "--height": height = Double(value) ?? 720.0
    case "--live-host": liveHost = value.isEmpty ? nil : value
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
