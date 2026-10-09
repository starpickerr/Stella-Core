import Foundation
import EventKit

func hasNonAbsoluteAlarm(_ alarms: [EKAlarm]) -> Bool {
    alarms.contains { $0.absoluteDate == nil }
}

struct ReminderDateFields {
    let day: String?
    let time: String?
    let timezone: String
}

func reminderDateFields(_ components: DateComponents?) -> ReminderDateFields {
    guard let components else { return ReminderDateFields(day: nil, time: nil, timezone: TimeZone.current.identifier) }
    let zone = components.timeZone ?? TimeZone.current
    let day: String?
    if let year = components.year, let month = components.month, let date = components.day {
        day = String(format: "%04d-%02d-%02d", year, month, date)
    } else {
        day = nil
    }
    let time = components.hour.map { hour in
        String(format: "%02d:%02d", hour, components.minute ?? 0)
    }
    return ReminderDateFields(day: day, time: time, timezone: zone.identifier)
}
