import Foundation

var local = DateComponents()
local.year = 2026
local.month = 10
local.day = 10
local.hour = 14
local.minute = 0
local.timeZone = TimeZone(identifier: "Asia/Shanghai")
let fields = reminderDateFields(local)
precondition(fields.day == "2026-10-10")
precondition(fields.time == "14:00")
precondition(fields.timezone == "Asia/Shanghai")
print("Reminder fields passed")
