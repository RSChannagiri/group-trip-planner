"""Itinerary helpers: conflict detection and grouping."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import Activity, Trip, ValidationError


def find_conflicts(activities: list[Activity]) -> list[tuple[Activity, Activity]]:
    """Return pairs of activities on the same day whose time ranges overlap."""
    conflicts: list[tuple[Activity, Activity]] = []
    by_day: dict[date, list[Activity]] = defaultdict(list)
    for a in activities:
        by_day[a.day].append(a)
    for day in sorted(by_day):
        items = sorted(by_day[day], key=lambda a: (a.start, a.end))
        for i, a in enumerate(items):
            for b in items[i + 1 :]:
                if b.start >= a.end:
                    break
                conflicts.append((a, b))
    return conflicts


def conflicts_with(new: Activity, existing: list[Activity]) -> list[Activity]:
    """Activities in `existing` that overlap with `new`."""
    return [
        a
        for a in existing
        if a is not new
        and (new.id is None or a.id != new.id)
        and a.day == new.day
        and a.start < new.end
        and new.start < a.end
    ]


def check_in_trip(activity: Activity, trip: Trip) -> None:
    if not trip.start_date <= activity.day <= trip.end_date:
        raise ValidationError("Activity date is outside the trip dates")


def group_by_day(trip: Trip, activities: list[Activity]) -> dict[date, list[Activity]]:
    """Every trip day mapped to its activities sorted by start time."""
    out: dict[date, list[Activity]] = {d: [] for d in trip.days()}
    for a in activities:
        out.setdefault(a.day, []).append(a)
    for d in out:
        out[d].sort(key=lambda a: a.start)
    return out
