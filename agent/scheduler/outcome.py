"""Distinguish execution failure from a retryable delivery failure."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    error: str = ""
    retryable: bool = False

    def __bool__(self):
        return self.status == "completed"
