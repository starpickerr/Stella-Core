import Foundation

let original = Date(timeIntervalSince1970: 1_000)
let later = Date(timeIntervalSince1970: 2_000)
assert(matchesMarkerOccurrence(candidateMarker: "stella://calendar/one", candidateOccurrence: original,
                               requestedMarker: "stella://calendar/one", requestedOccurrence: original))
assert(!matchesMarkerOccurrence(candidateMarker: "stella://calendar/one", candidateOccurrence: later,
                                requestedMarker: "stella://calendar/one", requestedOccurrence: original))
assert(!matchesMarkerOccurrence(candidateMarker: "stella://calendar/two", candidateOccurrence: original,
                                requestedMarker: "stella://calendar/one", requestedOccurrence: original))
print("Occurrence identity passed")
