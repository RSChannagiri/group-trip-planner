"""Domain models and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

BUDGET_CATEGORIES = ["Lodging", "Transport", "Food", "Activities", "Shopping", "Other"]
TRIP_TYPES = ["city", "beach", "hiking", "ski", "business"]
MAX_TRIP_DAYS = 60


class ValidationError(ValueError):
    """Raised when user input is invalid."""


@dataclass
class Trip:
    name: str
    destination: str
    start_date: date
    end_date: date
    travelers: list[str]
    trip_type: str = "city"
    id: int | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.name.strip():
            raise ValidationError("Trip name is required")
        if not self.destination.strip():
            raise ValidationError("Destination is required")
        if self.end_date < self.start_date:
            raise ValidationError("End date must be on or after start date")
        if (self.end_date - self.start_date).days + 1 > MAX_TRIP_DAYS:
            raise ValidationError(f"Trips are limited to {MAX_TRIP_DAYS} days")
        names = [t.strip() for t in self.travelers if t.strip()]
        if not names:
            raise ValidationError("At least one traveler is required")
        if len(set(n.lower() for n in names)) != len(names):
            raise ValidationError("Traveler names must be unique")
        self.travelers = names
        if self.trip_type not in TRIP_TYPES:
            raise ValidationError(f"Unknown trip type: {self.trip_type}")

    @property
    def num_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def days(self) -> list[date]:
        return [self.start_date + timedelta(days=i) for i in range(self.num_days)]


@dataclass
class Activity:
    day: date
    start: time
    end: time
    title: str
    location: str = ""
    notes: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValidationError("Activity title is required")
        if self.end <= self.start:
            raise ValidationError("Activity must end after it starts")

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.day, self.start)

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.day, self.end)


@dataclass
class Expense:
    description: str
    amount: float
    payer: str
    participants: list[str]
    category: str = "Other"
    spent_on: date | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValidationError("Expense description is required")
        if self.amount <= 0:
            raise ValidationError("Amount must be positive")
        if not self.participants:
            raise ValidationError("Expense needs at least one participant")
        if self.category not in BUDGET_CATEGORIES:
            raise ValidationError(f"Unknown category: {self.category}")
        if len(set(self.participants)) != len(self.participants):
            raise ValidationError("Participants must be unique")


@dataclass
class PackingItem:
    name: str
    packed: bool = False
    assignee: str = ""  # empty means shared by the whole group
    id: int | None = None

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError("Packing item name is required")


@dataclass
class TripBundle:
    """A trip with all of its child records."""

    trip: Trip
    activities: list[Activity] = field(default_factory=list)
    budget: dict[str, float] = field(default_factory=dict)
    expenses: list[Expense] = field(default_factory=list)
    packing: list[PackingItem] = field(default_factory=list)
