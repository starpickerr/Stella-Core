import Foundation
import EventKit
import Darwin

setvbuf(stdout, nil, _IONBF, 0)

struct BridgeFailure: Error {
    let message: String
    init(_ message: String) { self.message = message }
}

func emit(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed, .sortedKeys]),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
}

func text(_ object: [String: Any], _ key: String) -> String? {
    object[key] as? String
}

func required(_ object: [String: Any], _ key: String) throws -> String {
    guard let value = text(object, key), !value.isEmpty else { throw BridgeFailure("Missing \(key)") }
    return value
}

let formatter: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()
let fallbackFormatter = ISO8601DateFormatter()

func date(_ value: String?) -> Date? {
    guard let value else { return nil }
    return formatter.date(from: value) ?? fallbackFormatter.date(from: value)
}

func iso(_ value: Date?) -> String? {
    value.map { formatter.string(from: $0) }
}

func auth() -> String {
    switch EKEventStore.authorizationStatus(for: .event) {
    case .fullAccess, .authorized: return "full_access"
    case .notDetermined: return "not_determined"
    case .denied: return "denied"
    case .restricted: return "restricted"
    case .writeOnly: return "write_only"
    @unknown default: return "unknown"
    }
}

func requireAccess() throws {
    guard auth() == "full_access" else { throw BridgeFailure("Calendar full access is required") }
}

func recurrence(_ event: EKEvent) -> [String: Any] {
    guard let rule = event.recurrenceRules?.first else {
        return ["frequency": "none", "days": [], "until": NSNull(), "interval": 1,
                "count": 0, "rule_count": 0,
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
    let days = (rule.daysOfTheWeek ?? []).map { ($0.dayOfTheWeek.rawValue + 5) % 7 }
    return ["frequency": frequency, "days": days, "until": iso(rule.recurrenceEnd?.endDate) ?? NSNull(),
            "interval": rule.interval, "count": rule.recurrenceEnd?.occurrenceCount ?? 0,
            "rule_count": event.recurrenceRules?.count ?? 1,
            "month_days": (rule.daysOfTheMonth ?? []).map { $0.intValue },
            "months": (rule.monthsOfTheYear ?? []).map { $0.intValue },
            "week_numbers": (rule.weeksOfTheYear ?? []).map { $0.intValue },
            "year_days": (rule.daysOfTheYear ?? []).map { $0.intValue },
            "set_positions": (rule.setPositions ?? []).map { $0.intValue }]
}

func serialize(_ event: EKEvent) -> [String: Any] {
    let url = event.url?.absoluteString ?? ""
    let marker = url.hasPrefix("stella://calendar/") ? String(url.dropFirst("stella://calendar/".count)) : ""
    return [
        "calendar_id": event.calendar.calendarIdentifier,
        "event_id": event.eventIdentifier ?? "",
        "external_id": event.calendarItemExternalIdentifier ?? "",
        "occurrence_date": iso(event.occurrenceDate) ?? iso(event.startDate) ?? "",
        "stella_id": marker,
        "title": event.title ?? "", "description": event.notes ?? "", "location": event.location ?? "",
        "start_at": iso(event.startDate) ?? "", "end_at": iso(event.endDate) ?? "",
        "all_day": event.isAllDay, "timezone": event.timeZone?.identifier ?? TimeZone.current.identifier,
        "recurrence": recurrence(event), "is_detached": event.isDetached,
        "last_modified": iso(event.lastModifiedDate) ?? "",
        "writable": event.calendar.allowsContentModifications,
    ]
}

func calendars(_ store: EKEventStore) -> [[String: Any]] {
    store.calendars(for: .event).map { calendar in
        ["id": calendar.calendarIdentifier, "title": calendar.title,
         "source": calendar.source.title, "writable": calendar.allowsContentModifications]
    }
}

func scan(_ store: EKEventStore, _ ids: [String], _ start: Date, _ end: Date) -> [String: Any] {
    let all = Dictionary(uniqueKeysWithValues: store.calendars(for: .event).map { ($0.calendarIdentifier, $0) })
    var events: [[String: Any]] = []
    var successful: [String] = []
    var errors: [String] = []
    for id in ids {
        guard let calendar = all[id] else { errors.append(id); continue }
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: [calendar])
        let rows = store.events(matching: predicate)
        // A truncated scan must never be interpreted as a complete inventory.
        guard rows.count <= 20000 else { errors.append(id); continue }
        events.append(contentsOf: rows.map(serialize))
        successful.append(id)
    }
    return ["events": events, "successful_calendar_ids": successful, "failed_calendar_ids": errors]
}

func sameOccurrence(_ event: EKEvent, _ request: [String: Any]) -> Bool {
    guard let wanted = date(text(request, "occurrence_date")) else { return true }
    return abs((event.occurrenceDate ?? event.startDate).timeIntervalSince(wanted)) < 1
}

func findEvent(_ store: EKEventStore, _ request: [String: Any]) throws -> EKEvent? {
    let calendarID = try required(request, "calendar_id")
    if let eventID = text(request, "event_id"), !eventID.isEmpty,
       let event = store.event(withIdentifier: eventID),
       event.calendar.calendarIdentifier == calendarID, sameOccurrence(event, request) {
        return event
    }
    let marker = text(request, "stella_id") ?? ""
    let external = text(request, "external_id") ?? ""
    guard !marker.isEmpty || !external.isEmpty else { return nil }
    let start = date(text(request, "scan_start")) ?? Date().addingTimeInterval(-366 * 86400)
    let end = date(text(request, "scan_end")) ?? Date().addingTimeInterval(732 * 86400)
    let inventory = store.calendars(for: .event).first { $0.calendarIdentifier == calendarID }
    guard let inventory else { return nil }
    let rows = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: [inventory]))
    return rows.first { event in
        if !marker.isEmpty, event.url?.absoluteString == "stella://calendar/\(marker)" { return true }
        return !external.isEmpty && event.calendarItemExternalIdentifier == external && sameOccurrence(event, request)
    }
}

func recurrenceRule(_ payload: [String: Any]) throws -> EKRecurrenceRule? {
    let frequencyName = text(payload, "repeat_frequency") ?? "none"
    if frequencyName == "none" { return nil }
    let frequency: EKRecurrenceFrequency
    switch frequencyName {
    case "daily": frequency = .daily
    case "weekly": frequency = .weekly
    case "monthly": frequency = .monthly
    case "yearly": frequency = .yearly
    default: throw BridgeFailure("Unsupported recurrence")
    }
    var end: EKRecurrenceEnd? = nil
    if let until = text(payload, "repeat_until"), !until.isEmpty {
        let zone = TimeZone(identifier: text(payload, "repeat_timezone") ?? "UTC") ?? .gmt
        var parts = DateComponents()
        let numbers = until.split(separator: "-").compactMap { Int($0) }
        if numbers.count == 3 {
            parts.year = numbers[0]; parts.month = numbers[1]; parts.day = numbers[2]
            parts.hour = 23; parts.minute = 59; parts.second = 59; parts.timeZone = zone
            if let last = Calendar(identifier: .gregorian).date(from: parts) { end = EKRecurrenceEnd(end: last) }
        }
    }
    if frequency == .weekly, let days = payload["repeat_days"] as? [Int], !days.isEmpty {
        let ekDays = days.compactMap { EKWeekday(rawValue: (($0 + 1) % 7) + 1) }.map { EKRecurrenceDayOfWeek($0) }
        return EKRecurrenceRule(recurrenceWith: frequency, interval: 1,
            daysOfTheWeek: ekDays, daysOfTheMonth: nil, monthsOfTheYear: nil,
            weeksOfTheYear: nil, daysOfTheYear: nil, setPositions: nil, end: end)
    }
    return EKRecurrenceRule(recurrenceWith: frequency, interval: 1, end: end)
}

func run(_ request: [String: Any]) throws -> [String: Any] {
    let op = try required(request, "op")
    if op == "status" { return ["supported": true, "authorization": auth()] }
    let store = EKEventStore()
    if op == "request_access" {
        let semaphore = DispatchSemaphore(value: 0)
        var granted = false
        if #available(macOS 14.0, *) {
            store.requestFullAccessToEvents { result, _ in granted = result; semaphore.signal() }
        } else {
            store.requestAccess(to: .event) { result, _ in granted = result; semaphore.signal() }
        }
        guard semaphore.wait(timeout: .now() + 120) == .success else { throw BridgeFailure("Calendar permission request timed out") }
        store.reset()
        return ["authorization": auth(), "granted": granted]
    }
    try requireAccess()
    if op == "calendars" { return ["calendars": calendars(store)] }
    if op == "events" {
        let ids = request["calendar_ids"] as? [String] ?? []
        guard let start = date(text(request, "start")), let end = date(text(request, "end")), end > start else {
            throw BridgeFailure("Invalid scan window")
        }
        return scan(store, ids, start, end)
    }
    if op == "lookup" {
        return ["event": try findEvent(store, request).map(serialize) ?? NSNull()]
    }
    if op == "upsert" {
        let calendarID = try required(request, "calendar_id")
        guard let calendar = store.calendars(for: .event).first(where: { $0.calendarIdentifier == calendarID }) else {
            throw BridgeFailure("Calendar is unavailable")
        }
        guard calendar.allowsContentModifications else { throw BridgeFailure("Calendar is read only") }
        let existing = try findEvent(store, request)
        if (text(request, "event_id") ?? "") != "" || (text(request, "external_id") ?? "") != "" {
            guard existing != nil else { throw BridgeFailure("Linked event is unavailable") }
        }
        let event = existing ?? EKEvent(eventStore: store)
        event.calendar = calendar
        guard let start = date(text(request, "start_at")), let end = date(text(request, "end_at")), end > start else {
            throw BridgeFailure("Invalid event time")
        }
        event.title = try required(request, "title")
        event.notes = text(request, "description") ?? ""
        event.location = text(request, "location") ?? ""
        event.startDate = start; event.endDate = end
        event.isAllDay = request["all_day"] as? Bool ?? false
        event.timeZone = TimeZone(identifier: text(request, "repeat_timezone") ?? text(request, "timezone") ?? "UTC")
        if existing == nil, let marker = text(request, "stella_id"), !marker.isEmpty {
            event.url = URL(string: "stella://calendar/\(marker)")
        }
        if text(request, "stella_id") != nil, let rule = try recurrenceRule(request) {
            event.recurrenceRules = [rule]
        }
        let span: EKSpan = request["series"] as? Bool == true ? .futureEvents : .thisEvent
        try store.save(event, span: span, commit: true)
        return ["event": serialize(event)]
    }
    if op == "delete" {
        guard let event = try findEvent(store, request) else { throw BridgeFailure("Linked event is unavailable") }
        guard event.calendar.allowsContentModifications else { throw BridgeFailure("Calendar is read only") }
        try store.remove(event, span: request["series"] as? Bool == true ? .futureEvents : .thisEvent, commit: true)
        return ["deleted": true]
    }
    throw BridgeFailure("Unknown operation")
}

guard let line = readLine(), let data = line.data(using: .utf8),
      let request = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
    emit(["ok": false, "error": "Invalid request"])
    exit(1)
}
if text(request, "op") == "watch" {
    do {
        try requireAccess()
        let store = EKEventStore()
        let token = NotificationCenter.default.addObserver(forName: .EKEventStoreChanged, object: store, queue: nil) { _ in
            emit(["changed": true])
        }
        withExtendedLifetime(token) { RunLoop.main.run() }
    } catch {
        emit(["ok": false, "error": "Calendar full access is required"])
    }
} else {
    do {
        var result = try run(request)
        result["ok"] = true
        emit(result)
    } catch let failure as BridgeFailure {
        emit(["ok": false, "error": failure.message])
    } catch {
        emit(["ok": false, "error": "EventKit operation failed"])
    }
}
