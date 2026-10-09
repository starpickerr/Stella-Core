import Foundation
import EventKit

func reminderAuth() -> String {
    switch EKEventStore.authorizationStatus(for: .reminder) {
    case .fullAccess, .authorized: return "full_access"
    case .notDetermined: return "not_determined"
    case .denied: return "denied"
    case .restricted: return "restricted"
    case .writeOnly: return "write_only"
    @unknown default: return "unknown"
    }
}

func requireReminderAccess() throws {
    guard reminderAuth() == "full_access" else { throw BridgeFailure("Reminders full access is required") }
}

func reminderLists(_ store: EKEventStore) -> [[String: Any]] {
    store.calendars(for: .reminder).map { list in
        ["id": list.calendarIdentifier, "title": list.title, "source": list.source.title,
         "writable": list.allowsContentModifications]
    }
}

func fetchReminders(_ store: EKEventStore, _ list: EKCalendar) throws -> [EKReminder] {
    let predicate = store.predicateForReminders(in: [list])
    let semaphore = DispatchSemaphore(value: 0)
    var found: [EKReminder]?
    _ = store.fetchReminders(matching: predicate) { rows in
        found = rows
        semaphore.signal()
    }
    guard semaphore.wait(timeout: .now() + 30) == .success, let found else {
        throw BridgeFailure("Reminder list scan failed or timed out")
    }
    guard found.count <= 20000 else { throw BridgeFailure("Reminder list scan was truncated") }
    return found
}

func reminderRecurrence(_ reminder: EKReminder) -> [String: Any] {
    guard let rule = reminder.recurrenceRules?.first else {
        return ["frequency": "none", "days": [], "until": NSNull(), "rule_count": 0,
                "month_days": [], "months": [], "week_numbers": [], "year_days": [], "set_positions": []]
    }
    let frequency: String
    switch rule.frequency {
    case .daily: frequency = "daily"
    case .weekly: frequency = "weekly"
    case .monthly: frequency = "monthly"
    case .yearly: frequency = "yearly"
    @unknown default: frequency = "unsupported"
    }
    return ["frequency": frequency,
            "days": (rule.daysOfTheWeek ?? []).map { ($0.dayOfTheWeek.rawValue + 5) % 7 },
            "until": iso(rule.recurrenceEnd?.endDate) ?? NSNull(),
            "interval": rule.interval, "count": rule.recurrenceEnd?.occurrenceCount ?? 0,
            "rule_count": reminder.recurrenceRules?.count ?? 1,
            "month_days": (rule.daysOfTheMonth ?? []).map { $0.intValue },
            "months": (rule.monthsOfTheYear ?? []).map { $0.intValue },
            "week_numbers": (rule.weeksOfTheYear ?? []).map { $0.intValue },
            "year_days": (rule.daysOfTheYear ?? []).map { $0.intValue },
            "set_positions": (rule.setPositions ?? []).map { $0.intValue }]
}

func serializeReminder(_ reminder: EKReminder) -> [String: Any] {
    let due = reminderDateFields(reminder.dueDateComponents)
    let planned = reminderDateFields(reminder.startDateComponents)
    let url = reminder.url?.absoluteString ?? ""
    let marker = url.hasPrefix("stella://reminder/") ? String(url.dropFirst("stella://reminder/".count)) : ""
    let alarms = reminder.alarms ?? []
    return ["list_id": reminder.calendar.calendarIdentifier,
            "reminder_id": reminder.calendarItemIdentifier,
            "external_id": reminder.calendarItemExternalIdentifier ?? "",
            "stella_id": marker,
            "title": reminder.title ?? "", "notes": reminder.notes ?? "",
            "due_on": due.day ?? NSNull(), "due_time": due.time ?? NSNull(),
            "timezone": due.timezone, "planned_on": planned.day ?? NSNull(),
            "remind_at": iso(alarms.first?.absoluteDate) ?? NSNull(),
            "alarm_count": alarms.count,
            "priority": reminder.priority, "completed": reminder.isCompleted,
            "completed_at": iso(reminder.completionDate) ?? NSNull(),
            "recurrence": reminderRecurrence(reminder),
            "last_modified": iso(reminder.lastModifiedDate) ?? "",
            "writable": reminder.calendar.allowsContentModifications]
}

func reminderComponents(_ day: String?, _ time: String?, _ zoneName: String?) throws -> DateComponents? {
    guard let day, !day.isEmpty else { return nil }
    let parts = day.split(separator: "-").compactMap { Int($0) }
    guard parts.count == 3, parts[1] >= 1, parts[1] <= 12, parts[2] >= 1, parts[2] <= 31 else {
        throw BridgeFailure("Invalid reminder date")
    }
    var result = DateComponents()
    result.year = parts[0]; result.month = parts[1]; result.day = parts[2]
    if let time, !time.isEmpty {
        let clock = time.split(separator: ":").compactMap { Int($0) }
        guard clock.count == 2, clock[0] >= 0, clock[0] < 24, clock[1] >= 0, clock[1] < 60 else {
            throw BridgeFailure("Invalid reminder time")
        }
        result.hour = clock[0]; result.minute = clock[1]
    }
    result.timeZone = TimeZone(identifier: zoneName ?? "") ?? TimeZone.current
    return result
}

func findReminder(_ store: EKEventStore, _ request: [String: Any]) throws -> EKReminder? {
    let listID = try required(request, "list_id")
    guard let list = store.calendars(for: .reminder).first(where: { $0.calendarIdentifier == listID }) else {
        throw BridgeFailure("Reminder list is unavailable")
    }
    if let identifier = text(request, "reminder_id"), !identifier.isEmpty,
       let found = store.calendarItem(withIdentifier: identifier) as? EKReminder,
       found.calendar.calendarIdentifier == listID { return found }
    let marker = text(request, "stella_id") ?? ""
    let external = text(request, "external_id") ?? ""
    guard !marker.isEmpty || !external.isEmpty else { return nil }
    let rows = try fetchReminders(store, list)
    let matches = rows.filter { reminder in
        if !marker.isEmpty && reminder.url?.absoluteString == "stella://reminder/\(marker)" { return true }
        return !external.isEmpty && reminder.calendarItemExternalIdentifier == external
    }
    return matches.count == 1 ? matches[0] : nil
}

func runReminder(_ request: [String: Any]) throws -> [String: Any] {
    let op = try required(request, "op")
    if op == "reminder_status" { return ["supported": true, "authorization": reminderAuth()] }
    let store = EKEventStore()
    if op == "reminder_request_access" {
        let semaphore = DispatchSemaphore(value: 0)
        var granted = false
        if #available(macOS 14.0, *) {
            store.requestFullAccessToReminders { result, _ in granted = result; semaphore.signal() }
        } else {
            store.requestAccess(to: .reminder) { result, _ in granted = result; semaphore.signal() }
        }
        guard semaphore.wait(timeout: .now() + 120) == .success else {
            throw BridgeFailure("Reminders permission request timed out")
        }
        store.reset()
        return ["authorization": reminderAuth(), "granted": granted]
    }
    try requireReminderAccess()
    if op == "reminder_lists" { return ["lists": reminderLists(store)] }
    if op == "reminders" {
        let ids = request["list_ids"] as? [String] ?? []
        let lists = Dictionary(uniqueKeysWithValues: store.calendars(for: .reminder).map { ($0.calendarIdentifier, $0) })
        var rows: [[String: Any]] = []
        var successful: [String] = []
        var failed: [String] = []
        for id in ids {
            guard let list = lists[id] else { failed.append(id); continue }
            do {
                rows.append(contentsOf: try fetchReminders(store, list).map(serializeReminder))
                successful.append(id)
            } catch { failed.append(id) }
        }
        return ["reminders": rows, "successful_list_ids": successful, "failed_list_ids": failed]
    }
    if op == "reminder_lookup" {
        return ["reminder": try findReminder(store, request).map(serializeReminder) ?? NSNull()]
    }
    if op == "reminder_upsert" {
        let listID = try required(request, "list_id")
        guard let list = store.calendars(for: .reminder).first(where: { $0.calendarIdentifier == listID }) else {
            throw BridgeFailure("Reminder list is unavailable")
        }
        guard list.allowsContentModifications else { throw BridgeFailure("Reminder list is read only") }
        let existing = try findReminder(store, request)
        if !(text(request, "reminder_id") ?? "").isEmpty || !(text(request, "external_id") ?? "").isEmpty {
            guard existing != nil else { throw BridgeFailure("Linked reminder is unavailable") }
        }
        let reminder = existing ?? EKReminder(eventStore: store)
        reminder.calendar = list
        reminder.title = try required(request, "title")
        reminder.notes = text(request, "notes") ?? ""
        let zone = text(request, "timezone")
        reminder.dueDateComponents = try reminderComponents(text(request, "due_on"), text(request, "due_time"), zone)
        reminder.startDateComponents = try reminderComponents(text(request, "planned_on"), nil, zone)
        if request.keys.contains("remind_at") {
            if hasNonAbsoluteAlarm(reminder.alarms ?? []) {
                throw BridgeFailure("Relative or location reminder alarm needs manual review")
            }
            if let requested = text(request, "remind_at"), !requested.isEmpty {
                guard let value = date(requested) else { throw BridgeFailure("Invalid remind_at") }
                reminder.alarms = [EKAlarm(absoluteDate: value)]
            } else {
                reminder.alarms = []
            }
        }
        if let priority = request["priority"] as? Int { reminder.priority = priority }
        if let completed = request["completed"] as? Bool {
            reminder.isCompleted = completed
            reminder.completionDate = completed ? date(text(request, "completed_at")) ?? Date() : nil
        }
        if request.keys.contains("repeat_frequency") {
            reminder.recurrenceRules = try recurrenceRule(request).map { [$0] }
        }
        if existing == nil, let marker = text(request, "stella_id"), !marker.isEmpty {
            reminder.url = URL(string: "stella://reminder/\(marker)")
        }
        try store.save(reminder, commit: true)
        return ["reminder": serializeReminder(reminder)]
    }
    if op == "reminder_delete" {
        guard let reminder = try findReminder(store, request) else {
            throw BridgeFailure("Linked reminder is unavailable")
        }
        guard reminder.calendar.allowsContentModifications else { throw BridgeFailure("Reminder list is read only") }
        try store.remove(reminder, commit: true)
        return ["deleted": true]
    }
    throw BridgeFailure("Unknown reminder operation")
}
