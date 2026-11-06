"""Export itinerary to iCalendar and Markdown."""

from __future__ import annotations

from datetime import datetime

from .itinerary import group_by_day
from .models import Activity, Trip


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def to_ics(trip: Trip, activities: list[Activity], stamp: datetime | None = None) -> str:
    stamp = stamp or datetime(2026, 1, 1)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//group-trip-planner//EN",
        "CALSCALE:GREGORIAN",
    ]
    for i, a in enumerate(sorted(activities, key=lambda a: a.start_dt)):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{trip.id or 0}-{i}@group-trip-planner",
            f"DTSTAMP:{_fmt(stamp)}",
            f"DTSTART:{_fmt(a.start_dt)}",
            f"DTEND:{_fmt(a.end_dt)}",
            f"SUMMARY:{_esc(a.title)}",
        ]
        if a.location:
            lines.append(f"LOCATION:{_esc(a.location)}")
        if a.notes:
            lines.append(f"DESCRIPTION:{_esc(a.notes)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def to_markdown(trip: Trip, activities: list[Activity]) -> str:
    out = [
        f"# {trip.name}",
        "",
        f"**Destination:** {trip.destination}  ",
        f"**Dates:** {trip.start_date:%b %d, %Y} to {trip.end_date:%b %d, %Y}  ",
        f"**Travelers:** {', '.join(trip.travelers)}",
        "",
    ]
    for n, (day, acts) in enumerate(group_by_day(trip, activities).items(), 1):
        out.append(f"## Day {n}: {day:%A, %b %d}")
        out.append("")
        if not acts:
            out.append("_Free day_")
        for a in acts:
            loc = f" ({a.location})" if a.location else ""
            out.append(f"- {a.start:%H:%M}-{a.end:%H:%M} **{a.title}**{loc}")
        out.append("")
    return "\n".join(out)
