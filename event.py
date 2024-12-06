from dataclasses import dataclass
import datetime


@dataclass
class Event:
    datetime: datetime.datetime
    title: str
    description: str
    place: str
