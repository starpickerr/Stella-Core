"""Resource document shape reused from elearning_crawler."""
from dataclasses import dataclass


@dataclass
class Resource:
    course: dict
    id: str
    title: str
    summary: str
    text: str
    url: str
    timestamp: str = ""
