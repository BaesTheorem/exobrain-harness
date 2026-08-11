// MIST Notifier: the native notification arm of mist-notify.
//
// A tiny LSUIElement app that owns MIST's macOS notifications via
// UNUserNotificationCenter: banners with the MIST name + icon, action buttons,
// inline reply (relayed into the MIST Console chat), image attachments,
// grouping, and replace-by-id. mist-voice/bin/mist-notify invokes it and falls
// back to terminal-notifier when it's missing or not yet authorized.
//
// Why a separate app: usernoted validates the calling process against its
// Launch Services bundle record. The MIST Console launches python through a
// shell script, so its running executable never matches its bundle record and
// every UN call gets UNErrorDomain Code=1. A real Mach-O bundle executable in
// /Applications (NOT /tmp; temp-path apps fail the same validation) passes.
//
// Modes (argv):
//   post <spec.json>  - deliver one notification, write <spec.json>.result, exit
//   auth              - request authorization (fires the one-time system prompt)
//   (none)            - response handler: macOS launches us when a banner is
//                       clicked, a button pressed, or a reply submitted
import AppKit
import UserNotifications

let consolePort = 5014
let consoleBundle = "com.exobrain.mist-console"
let logPath = NSString(string: "~/Library/Logs/exobrain/mist-notifier.log").expandingTildeInPath

func nlog(_ s: String) {
    let df = DateFormatter()
    df.dateFormat = "yyyy-MM-dd HH:mm:ss"
    let line = "[\(df.string(from: Date()))] \(s)\n"
    let dir = (logPath as NSString).deletingLastPathComponent
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    if let h = FileHandle(forWritingAtPath: logPath) {
        h.seekToEndOfFile()
        h.write(line.data(using: .utf8)!)
        h.closeFile()
    } else {
        try? line.write(toFile: logPath, atomically: true, encoding: .utf8)
    }
}

struct ActionSpec: Codable { var label: String; var target: String }
struct ReplySpec: Codable { var sid: String? }
struct Spec: Codable {
    var title: String?
    var subtitle: String?
    var body: String?
    var sound: String?
    var link: String?
    var image: String?
    var group: String?
    var id: String?
    var urgency: String?
    var reply: ReplySpec?
    var actions: [ActionSpec]?
}

// Category ids must be stable across launches (Swift's hashValue is seeded per
// process), so identical button layouts reuse one registered category.
func stableHash(_ s: String) -> String {
    var h: UInt64 = 5381
    for b in s.utf8 { h = (h &* 33) ^ UInt64(b) }
    return String(format: "%016llx", h)
}

// ---- plumbing ----------------------------------------------------------------

@discardableResult
func run(_ path: String, _ args: [String], wait: Bool = true) -> Bool {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    do { try p.run() } catch {
        nlog("spawn \(path) failed: \(error)")
        return false
    }
    if wait { p.waitUntilExit(); return p.terminationStatus == 0 }
    return true
}

func httpGet(_ url: String, timeout: Double) -> Bool {
    guard let u = URL(string: url) else { return false }
    var req = URLRequest(url: u, timeoutInterval: timeout)
    req.httpMethod = "GET"
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    URLSession.shared.dataTask(with: req) { _, resp, _ in
        ok = (resp as? HTTPURLResponse)?.statusCode == 200
        sem.signal()
    }.resume()
    _ = sem.wait(timeout: .now() + timeout + 1)
    return ok
}

func httpPostJSON(_ url: String, _ body: [String: Any], timeout: Double) -> Bool {
    guard let u = URL(string: url),
          let data = try? JSONSerialization.data(withJSONObject: body) else { return false }
    var req = URLRequest(url: u, timeoutInterval: timeout)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = data
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    URLSession.shared.dataTask(with: req) { _, resp, _ in
        ok = (resp as? HTTPURLResponse)?.statusCode == 200
        sem.signal()
    }.resume()
    _ = sem.wait(timeout: .now() + timeout + 1)
    return ok
}

// ---- click / action targets --------------------------------------------------
// Same semantics as mist-notify's 4th arg: "console", "console:<sid>", any
// open-able URL/scheme/path, plus "cmd:<shell>" for action buttons.

func openConsole(sid: String?) {
    if let sid = sid, !sid.isEmpty {
        _ = httpGet("http://127.0.0.1:\(consolePort)/focus?sid=\(sid)", timeout: 2)
    }
    run("/usr/bin/open", ["-b", consoleBundle])
}

func runTarget(_ raw: String?) {
    let t = (raw ?? "").isEmpty ? "console" : raw!
    nlog("target: \(t)")
    if t == "console" { openConsole(sid: nil); return }
    if t.hasPrefix("console:") { openConsole(sid: String(t.dropFirst("console:".count))); return }
    if t.hasPrefix("cmd:") { run("/bin/zsh", ["-lc", String(t.dropFirst("cmd:".count))]); return }
    run("/usr/bin/open", [t])
}

func sendReply(sid: String?, text: String) {
    var body: [String: Any] = ["text": text]
    if let sid = sid, !sid.isEmpty { body["sid"] = sid }
    let url = "http://127.0.0.1:\(consolePort)/notify-reply"
    if httpPostJSON(url, body, timeout: 5) { nlog("reply delivered"); return }
    // Console closed: boot it, then retry until its lazy startup answers.
    nlog("console down, booting it to deliver the reply")
    openConsole(sid: sid)
    for _ in 0..<15 {
        Thread.sleep(forTimeInterval: 2)
        if httpPostJSON(url, body, timeout: 5) { nlog("reply delivered after boot"); return }
    }
    // Never silently drop typed text.
    nlog("reply UNDELIVERED (console never answered): \(text)")
}

// ---- delegate ----------------------------------------------------------------

class Delegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var busy = 0
    var exitTimer: Timer?

    // Quit once idle: every instance is single-shot (post, auth, or one
    // response), but never mid-handler.
    func scheduleExit(_ after: Double) {
        DispatchQueue.main.async {
            self.exitTimer?.invalidate()
            self.exitTimer = Timer.scheduledTimer(withTimeInterval: after, repeats: false) { _ in
                if self.busy > 0 { self.scheduleExit(5); return }
                exit(0)
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler:
                                    @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        nlog("response: \(response.actionIdentifier)")
        busy += 1
        completionHandler()
        DispatchQueue.global().async {
            self.handle(response, info)
            DispatchQueue.main.async { self.busy -= 1; self.scheduleExit(2) }
        }
    }

    func handle(_ response: UNNotificationResponse, _ info: [AnyHashable: Any]) {
        switch response.actionIdentifier {
        case UNNotificationDismissActionIdentifier:
            return
        case "mist.reply":
            let text = (response as? UNTextInputNotificationResponse)?.userText ?? ""
            var sid = (info["reply"] as? [String: Any])?["sid"] as? String
            if (sid ?? "").isEmpty, let link = info["link"] as? String, link.hasPrefix("console:") {
                sid = String(link.dropFirst("console:".count))
            }
            if !text.isEmpty { sendReply(sid: sid, text: text) }
        case let a where a.hasPrefix("mist.act."):
            let i = Int(a.dropFirst("mist.act.".count)) ?? 0
            if let acts = info["actions"] as? [[String: Any]], i < acts.count {
                runTarget(acts[i]["target"] as? String)
            }
        default:   // UNNotificationDefaultActionIdentifier, the banner itself
            runTarget(info["link"] as? String)
        }
    }
}

// ---- post --------------------------------------------------------------------

func writeResult(_ specPath: String, ok: Bool, reason: String? = nil) {
    var r: [String: Any] = ["ok": ok]
    if let reason = reason { r["reason"] = reason }
    if let data = try? JSONSerialization.data(withJSONObject: r) {
        try? data.write(to: URL(fileURLWithPath: specPath + ".result"))
    }
}

func ensureAuthorized(_ center: UNUserNotificationCenter, wait: Double) -> UNAuthorizationStatus {
    let sem = DispatchSemaphore(value: 0)
    center.requestAuthorization(options: [.alert, .sound, .badge]) { _, err in
        if let err = err { nlog("requestAuthorization: \(err.localizedDescription)") }
        sem.signal()
    }
    // While the system prompt is on screen this callback doesn't fire; don't
    // hold the caller hostage; report the current status and let mist-notify
    // fall back for this one notification.
    _ = sem.wait(timeout: .now() + wait)
    var status = UNAuthorizationStatus.notDetermined
    let sem2 = DispatchSemaphore(value: 0)
    center.getNotificationSettings { s in status = s.authorizationStatus; sem2.signal() }
    _ = sem2.wait(timeout: .now() + 5)
    return status
}

func registerCategory(_ center: UNUserNotificationCenter, _ spec: Spec) -> String? {
    var acts: [UNNotificationAction] = []
    if spec.reply != nil {
        acts.append(UNTextInputNotificationAction(
            identifier: "mist.reply", title: "Reply", options: [],
            textInputButtonTitle: "Send", textInputPlaceholder: "Message MIST…"))
    }
    for (i, a) in (spec.actions ?? []).prefix(3).enumerated() {
        acts.append(UNNotificationAction(identifier: "mist.act.\(i)", title: a.label, options: []))
    }
    if acts.isEmpty { return nil }
    let key = (spec.reply != nil ? "R|" : "") +
        (spec.actions ?? []).map { "\($0.label)" }.joined(separator: "|")
    let catId = "mist.\(stableHash(key))"
    let cat = UNNotificationCategory(identifier: catId, actions: acts,
                                     intentIdentifiers: [], options: [])
    let sem = DispatchSemaphore(value: 0)
    center.getNotificationCategories { existing in
        // Layouts are content-hashed so repeats reuse a category; still cap the
        // set so one-off layouts can't grow it forever.
        var keep = existing.filter { $0.identifier != catId }
        if keep.count > 48 { keep = [] }
        keep.insert(cat)
        center.setNotificationCategories(keep)
        sem.signal()
    }
    _ = sem.wait(timeout: .now() + 5)
    // setNotificationCategories is async with no callback; give the daemon a
    // beat so the category exists before the notification referencing it lands.
    Thread.sleep(forTimeInterval: 0.15)
    return catId
}

func doPost(_ specPath: String, _ center: UNUserNotificationCenter) {
    guard let data = FileManager.default.contents(atPath: specPath),
          let spec = try? JSONDecoder().decode(Spec.self, from: data) else {
        nlog("post: unreadable spec \(specPath)")
        writeResult(specPath, ok: false, reason: "bad-spec")
        return
    }
    let status = ensureAuthorized(center, wait: 8)
    guard status == .authorized || status == .provisional else {
        nlog("post: not authorized (status \(status.rawValue))")
        writeResult(specPath, ok: false,
                    reason: status == .denied ? "denied" : "pending")
        return
    }

    let content = UNMutableNotificationContent()
    content.title = spec.title ?? "MIST"
    if let s = spec.subtitle, !s.isEmpty { content.subtitle = s }
    content.body = spec.body ?? ""
    switch spec.sound ?? "default" {
    case "", "none", "silent": break
    case "default": content.sound = .default
    case let name: content.sound = UNNotificationSound(named: UNNotificationSoundName(name))
    }
    if let g = spec.group, !g.isEmpty { content.threadIdentifier = g }
    if #available(macOS 12.0, *) {
        switch spec.urgency ?? "" {
        case "passive": content.interruptionLevel = .passive
        case "timeSensitive", "critical": content.interruptionLevel = .timeSensitive
        default: content.interruptionLevel = .active
        }
    }
    var userInfo: [String: Any] = ["link": spec.link ?? ""]
    if let r = spec.reply { userInfo["reply"] = ["sid": r.sid ?? ""] }
    if let acts = spec.actions {
        userInfo["actions"] = acts.map { ["label": $0.label, "target": $0.target] }
    }
    content.userInfo = userInfo
    if let catId = registerCategory(center, spec) { content.categoryIdentifier = catId }
    if let img = spec.image, FileManager.default.fileExists(atPath: img) {
        // Attachments are MOVED into the notification store; attach a copy.
        let ext = (img as NSString).pathExtension
        let tmp = NSTemporaryDirectory() + "mist-attach-" + UUID().uuidString + (ext.isEmpty ? "" : "." + ext)
        try? FileManager.default.copyItem(atPath: img, toPath: tmp)
        if let att = try? UNNotificationAttachment(identifier: "image",
                                                   url: URL(fileURLWithPath: tmp)) {
            content.attachments = [att]
        }
    }

    let ident = (spec.id ?? "").isEmpty ? "mist-" + UUID().uuidString : spec.id!
    let req = UNNotificationRequest(identifier: ident, content: content, trigger: nil)
    let sem = DispatchSemaphore(value: 0)
    var postErr: Error?
    center.add(req) { e in postErr = e; sem.signal() }
    _ = sem.wait(timeout: .now() + 8)
    if let e = postErr {
        nlog("post failed: \(e.localizedDescription)")
        writeResult(specPath, ok: false, reason: e.localizedDescription)
    } else {
        writeResult(specPath, ok: true)
    }
}

// ---- main --------------------------------------------------------------------

let center = UNUserNotificationCenter.current()
let delegate = Delegate()
// Delegate goes up in every mode: even a short-lived `post` instance can be the
// running app the moment a user clicks an older banner.
center.delegate = delegate
let nsapp = NSApplication.shared
nsapp.delegate = delegate

let args = CommandLine.arguments
if args.count >= 3 && args[1] == "post" {
    DispatchQueue.global().async {
        doPost(args[2], center)
        delegate.scheduleExit(1)
    }
    delegate.scheduleExit(30)
} else if args.count >= 2 && args[1] == "auth" {
    DispatchQueue.global().async {
        let status = ensureAuthorized(center, wait: 240)
        nlog("auth: status \(status.rawValue) (2 = authorized)")
        delegate.scheduleExit(1)
    }
    delegate.scheduleExit(260)
} else {
    // Launched by macOS to deliver a notification response.
    delegate.scheduleExit(20)
}
nsapp.run()
