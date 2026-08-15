// Creates reminders in Apple Reminders via EventKit.
//
// EventKit rather than AppleScript because the Reminders scripting dictionary
// exposes no recurrence at all -- `sdef Reminders.app | grep -i recur` is empty,
// so osascript can only ever make one-shot reminders.

import EventKit
import Foundation

func die(_ msg: String, _ code: Int32) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(code)
}

let usage = """
usage: mkreminder "Title" [--list NAME] [--at HH:MM] [--repeat daily|weekly|monthly|yearly|none]
                          [--interval N] [--notes TEXT] [--force]

  --list      Reminders list to file it under (default: INBOX)
  --at        time of day; omit for a reminder with no time
  --repeat    recurrence frequency (default: none)
  --interval  every N days/weeks/... (default: 1)
  --force     create even if an open reminder with the same title exists
"""

var args = Array(CommandLine.arguments.dropFirst())
guard let title = args.first, !title.hasPrefix("--") else { die(usage, 64) }
args.removeFirst()

var listName = "INBOX"
var timeOfDay: (hour: Int, minute: Int)?
var frequency: EKRecurrenceFrequency?
var frequencyName = "none"
var interval = 1
var notes: String?
var force = false

func nextValue(_ flag: String) -> String {
    guard !args.isEmpty else { die("\(flag) needs a value\n\n\(usage)", 64) }
    return args.removeFirst()
}

while !args.isEmpty {
    let flag = args.removeFirst()
    switch flag {
    case "--list": listName = nextValue(flag)
    case "--notes": notes = nextValue(flag)
    case "--force": force = true
    case "--interval":
        let raw = nextValue(flag)
        guard let n = Int(raw), n > 0 else { die("--interval must be a positive integer", 64) }
        interval = n
    case "--at":
        let raw = nextValue(flag)
        let parts = raw.split(separator: ":")
        guard parts.count == 2, let h = Int(parts[0]), let m = Int(parts[1]),
            (0..<24).contains(h), (0..<60).contains(m)
        else { die("--at wants 24-hour HH:MM, got \(raw)", 64) }
        timeOfDay = (h, m)
    case "--repeat":
        let raw = nextValue(flag)
        switch raw {
        case "none": frequency = nil
        case "daily": frequency = .daily
        case "weekly": frequency = .weekly
        case "monthly": frequency = .monthly
        case "yearly": frequency = .yearly
        default: die("unknown --repeat \(raw)", 64)
        }
        frequencyName = raw
    default: die("unknown flag \(flag)\n\n\(usage)", 64)
    }
}

if frequency != nil && timeOfDay == nil {
    die("a repeating reminder needs --at HH:MM, or it fires at midnight", 64)
}

let store = EKEventStore()
var granted = false
let auth = DispatchSemaphore(value: 0)
let handler: (Bool, Error?) -> Void = { ok, err in
    granted = ok
    if let err = err {
        FileHandle.standardError.write("auth error: \(err)\n".data(using: .utf8)!)
    }
    auth.signal()
}
if #available(macOS 14.0, *) {
    store.requestFullAccessToReminders(completion: handler)
} else {
    store.requestAccess(to: .reminder, completion: handler)
}
auth.wait()
guard granted else {
    die("DENIED: no Reminders access. Grant the calling terminal Reminders in System Settings > Privacy & Security.", 2)
}

guard let list = store.calendars(for: .reminder).first(where: { $0.title == listName }) else {
    let available = store.calendars(for: .reminder).map(\.title).joined(separator: ", ")
    die("NO LIST: \(listName). Available: \(available)", 3)
}

if !force {
    let pred = store.predicateForIncompleteReminders(
        withDueDateStarting: nil, ending: nil, calendars: [list])
    var open: [EKReminder] = []
    let fetch = DispatchSemaphore(value: 0)
    store.fetchReminders(matching: pred) { found in
        open = found ?? []
        fetch.signal()
    }
    fetch.wait()
    if open.contains(where: { $0.title == title }) {
        print("EXISTS: \"\(title)\" is already open in \(listName) -- pass --force to add anyway")
        exit(0)
    }
}

let reminder = EKReminder(eventStore: store)
reminder.calendar = list
reminder.title = title
reminder.notes = notes

var due: Date?
if let time = timeOfDay {
    let cal = Calendar.current
    let now = Date()
    var comps = cal.dateComponents([.year, .month, .day], from: now)
    comps.hour = time.hour
    comps.minute = time.minute
    var start = cal.date(from: comps)!
    // Today's slot may already be behind us; roll to the next one.
    if start < now { start = cal.date(byAdding: .day, value: 1, to: start)! }
    due = start
    reminder.dueDateComponents = cal.dateComponents(
        [.year, .month, .day, .hour, .minute], from: start)
    // Reminders only notifies when there's an alarm; the UI adds one implicitly,
    // EventKit does not.
    reminder.addAlarm(EKAlarm(absoluteDate: start))
}

if let frequency = frequency {
    reminder.addRecurrenceRule(
        EKRecurrenceRule(recurrenceWith: frequency, interval: interval, end: nil))
}

do {
    try store.save(reminder, commit: true)
} catch {
    die("SAVE FAILED: \(error)", 4)
}

var summary = "CREATED: \"\(title)\" in \(listName)"
if let due = due {
    let fmt = DateFormatter()
    fmt.dateFormat = "yyyy-MM-dd HH:mm"
    summary += ", first due \(fmt.string(from: due))"
}
if frequency != nil {
    let noun = ["daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"][
        frequencyName]!
    summary += interval == 1 ? ", \(frequencyName)" : ", every \(interval) \(noun)s"
}
print(summary)
