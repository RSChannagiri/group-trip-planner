"""Table builders shared by the Streamlit UI (kept here so they are testable)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from .budget import budget_status, per_person_targets, share_by_traveler
from .itinerary import find_conflicts
from .models import Activity, Expense, Trip


def itinerary_frame(activities: list[Activity]) -> pd.DataFrame:
    conflict_ids = {id(x) for pair in find_conflicts(activities) for x in pair}
    rows = [
        {
            "id": a.id,
            "Day": a.day,
            "Start": a.start.strftime("%H:%M"),
            "End": a.end.strftime("%H:%M"),
            "Activity": a.title,
            "Location": a.location,
            "Conflict": id(a) in conflict_ids,
        }
        for a in sorted(activities, key=lambda a: (a.day, a.start))
    ]
    cols = ["id", "Day", "Start", "End", "Activity", "Location", "Conflict"]
    return pd.DataFrame(rows, columns=cols)


def conflict_messages(activities: list[Activity]) -> list[str]:
    return [
        f"{a.day:%a %b %d}: '{a.title}' ({a.start:%H:%M}-{a.end:%H:%M}) overlaps "
        f"'{b.title}' ({b.start:%H:%M}-{b.end:%H:%M})"
        for a, b in find_conflicts(activities)
    ]


def budget_frame(trip: Trip, budget: dict[str, float], expenses: list[Expense]) -> pd.DataFrame:
    targets = per_person_targets(budget, len(trip.travelers))
    df = pd.DataFrame(budget_status(budget, expenses))
    df["per_person_target"] = df["category"].map(targets)
    return df


def per_person_frame(trip: Trip, budget: dict[str, float], expenses: list[Expense]) -> pd.DataFrame:
    """Each traveler's fair share of spending versus the per-person target."""
    target = round(sum(budget.values()) / len(trip.travelers), 2)
    shares = share_by_traveler(expenses, trip.travelers)
    return pd.DataFrame(
        [
            {
                "traveler": t,
                "share_spent": shares[t],
                "target": target,
                "remaining": round(target - shares[t], 2),
            }
            for t in trip.travelers
        ]
    )


def expense_frame(expenses: list[Expense]) -> pd.DataFrame:
    cols = ["id", "Date", "Description", "Category", "Paid by", "Amount", "Split with"]
    return pd.DataFrame(
        [
            {
                "id": e.id,
                "Date": e.spent_on,
                "Description": e.description,
                "Category": e.category,
                "Paid by": e.payer,
                "Amount": e.amount,
                "Split with": ", ".join(e.participants),
            }
            for e in expenses
        ],
        columns=cols,
    )


def countdown_days(trip: Trip, today: date) -> int:
    """Days until departure (0 or negative once the trip has started)."""
    return (trip.start_date - today).days
