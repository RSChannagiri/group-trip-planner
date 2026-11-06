"""Itinerary drafting: optional LLM with deterministic fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import time
from typing import Any

from .models import Activity, Trip

SLOTS = [
    (time(9, 0), time(11, 30), "Morning"),
    (time(12, 0), time(13, 30), "Lunch"),
    (time(14, 0), time(17, 0), "Afternoon"),
    (time(19, 0), time(21, 0), "Dinner"),
]

THEMES = {
    "city": [
        "Old town walking tour",
        "Museum visit",
        "Market and street food",
        "Neighborhood explore",
        "Park and viewpoint",
        "Shopping district",
        "Local cooking class",
    ],
    "beach": [
        "Beach morning",
        "Snorkeling",
        "Boat tour",
        "Coastal walk",
        "Spa time",
        "Sunset cruise",
        "Island hop",
    ],
    "hiking": [
        "Trailhead hike",
        "Summit attempt",
        "Lake loop",
        "Rest and stretch",
        "Waterfall trail",
        "Ridge walk",
        "Wildlife spotting",
    ],
    "ski": [
        "Ski lesson",
        "Groomed runs",
        "Backcountry tour",
        "Apres ski",
        "Snowshoe",
        "Hot springs",
        "Village stroll",
    ],
    "business": [
        "Client meetings",
        "Conference sessions",
        "Workshop",
        "Team offsite",
        "Networking",
        "Site visit",
        "Wrap-up",
    ],
}


def rule_based_draft(trip: Trip) -> list[Activity]:
    """Deterministic itinerary: 4 slots per day rotating through themes."""
    themes = THEMES[trip.trip_type]
    out: list[Activity] = []
    for i, day in enumerate(trip.days()):
        for start, end, label in SLOTS:
            if label == "Morning":
                title = themes[i % len(themes)]
            elif label == "Afternoon":
                title = themes[(i + 3) % len(themes)]
            else:
                title = f"{label} in {trip.destination}"
            if i == 0 and label == "Morning":
                title = f"Arrive in {trip.destination} and check in"
            if i == trip.num_days - 1 and label == "Dinner" and trip.num_days > 1:
                title = "Farewell dinner"
            out.append(
                Activity(day=day, start=start, end=end, title=title, location=trip.destination)
            )
    return out


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_llm_json(text: str, trip: Trip) -> list[Activity]:
    """Parse LLM JSON output into activities.

    Rows for days outside the trip are dropped. Raises ValueError if the
    response is not usable at all.
    """
    try:
        data: Any = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("activities", [])
    if not isinstance(data, list):
        raise ValueError("LLM response has no activity list")
    days = trip.days()
    out = []
    for row in data:
        try:
            idx = int(row["day"]) - 1
            if not 0 <= idx < len(days):
                continue
            out.append(
                Activity(
                    day=days[idx],
                    start=time.fromisoformat(str(row["start"])),
                    end=time.fromisoformat(str(row["end"])),
                    title=str(row["title"]),
                    location=str(row.get("location", "") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows, keep the good ones
    if not out:
        raise ValueError("No valid activities in LLM response")
    return out


def build_prompt(trip: Trip, preferences: str = "") -> str:
    return (
        f"Plan a {trip.num_days}-day {trip.trip_type} trip to {trip.destination} for "
        f"{len(trip.travelers)} travelers starting {trip.start_date:%B %d, %Y}. "
        f"Preferences: {preferences.strip() or 'none'}. "
        'Respond with only JSON: {"activities": [{"day": 1, "start": "09:00", "end": "11:00", '
        '"title": "...", "location": "..."}]}. Use 24-hour HH:MM times, days numbered from 1, '
        "and avoid overlapping times within a day."
    )


@dataclass
class DraftResult:
    activities: list[Activity]
    source: str  # "ai" or "template"
    note: str = ""


def make_client() -> Any | None:
    """Build an OpenAI-compatible client from env vars, or None if not configured."""
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI

        return OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None, timeout=30)
    except Exception:
        return None


def draft_itinerary(trip: Trip, preferences: str = "", client: Any = None) -> DraftResult:
    """Draft an itinerary with the LLM when available, else the offline template.

    Any LLM failure (network, auth, bad JSON) falls back to the template so the
    feature always works.
    """
    if client is None:
        client = make_client()
    if client is None:
        return DraftResult(rule_based_draft(trip), "template", "No OPENAI_API_KEY set")
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a concise group travel planner."},
                {"role": "user", "content": build_prompt(trip, preferences)},
            ],
            temperature=0.7,
        )
        content = resp.choices[0].message.content or ""
        return DraftResult(parse_llm_json(content, trip), "ai")
    except Exception as exc:  # noqa: BLE001 - any provider error means fall back
        return DraftResult(rule_based_draft(trip), "template", f"AI draft failed: {exc}")
