import Foundation

func matchesMarkerOccurrence(candidateMarker: String?, candidateOccurrence: Date,
                             requestedMarker: String, requestedOccurrence: Date?) -> Bool {
    guard candidateMarker == requestedMarker else { return false }
    guard let requestedOccurrence else { return true }
    return abs(candidateOccurrence.timeIntervalSince(requestedOccurrence)) < 1
}
