"""SQLite persistence layer.

Every public method opens a short-lived connection, which keeps the store safe
to use from Streamlit's rerun model and from tests with a temp file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

from .models import BUDGET_CATEGORIES, Activity, Expense, PackingItem, Trip, ValidationError

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    destination TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    trip_type TEXT NOT NULL DEFAULT 'city'
);
CREATE TABLE IF NOT EXISTS travelers (
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (trip_id, name)
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS budgets (
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    PRIMARY KEY (trip_id, category)
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    payer TEXT NOT NULL,
    category TEXT NOT NULL,
    spent_on TEXT
);
CREATE TABLE IF NOT EXISTS expense_participants (
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    PRIMARY KEY (expense_id, name)
);
CREATE TABLE IF NOT EXISTS packing_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    packed INTEGER NOT NULL DEFAULT 0,
    assignee TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_activities_trip ON activities(trip_id, day);
CREATE INDEX IF NOT EXISTS idx_expenses_trip ON expenses(trip_id);
CREATE INDEX IF NOT EXISTS idx_packing_trip ON packing_items(trip_id);
"""


class NotFoundError(LookupError):
    """Raised when a requested record does not exist."""


class TripStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- trips -------------------------------------------------------
    def create_trip(self, trip: Trip) -> Trip:
        trip.validate()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO trips (name, destination, start_date, end_date, trip_type)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    trip.name.strip(),
                    trip.destination.strip(),
                    trip.start_date.isoformat(),
                    trip.end_date.isoformat(),
                    trip.trip_type,
                ),
            )
            trip.id = int(cur.lastrowid or 0)
            self._write_travelers(conn, trip.id, trip.travelers)
        return trip

    @staticmethod
    def _write_travelers(conn: sqlite3.Connection, trip_id: int, names: list[str]) -> None:
        conn.execute("DELETE FROM travelers WHERE trip_id = ?", (trip_id,))
        conn.executemany(
            "INSERT INTO travelers (trip_id, position, name) VALUES (?, ?, ?)",
            [(trip_id, i, n) for i, n in enumerate(names)],
        )

    def _row_to_trip(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Trip:
        names = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM travelers WHERE trip_id = ? ORDER BY position", (row["id"],)
            )
        ]
        return Trip(
            name=row["name"],
            destination=row["destination"],
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            travelers=names,
            trip_type=row["trip_type"],
            id=row["id"],
        )

    def get_trip(self, trip_id: int) -> Trip:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"Trip {trip_id} not found")
            return self._row_to_trip(conn, row)

    def list_trips(self) -> list[Trip]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM trips ORDER BY start_date, id").fetchall()
            return [self._row_to_trip(conn, r) for r in rows]

    def update_trip(self, trip: Trip) -> Trip:
        """Save edits to a trip, refusing changes that would orphan existing data."""
        if trip.id is None:
            raise ValidationError("Trip has no id")
        trip.validate()
        old = self.get_trip(trip.id)
        removed = set(old.travelers) - set(trip.travelers)
        with self._conn() as conn:
            if removed:
                marks = ",".join("?" * len(removed))
                used = conn.execute(
                    f"SELECT COUNT(*) FROM expenses e WHERE e.trip_id = ? AND (e.payer IN ({marks})"
                    f" OR EXISTS (SELECT 1 FROM expense_participants p WHERE p.expense_id = e.id"
                    f" AND p.name IN ({marks})))",
                    (trip.id, *removed, *removed),
                ).fetchone()[0]
                if used:
                    raise ValidationError(
                        "Cannot remove a traveler who appears in the expense log: "
                        + ", ".join(sorted(removed))
                    )
            outside = conn.execute(
                "SELECT COUNT(*) FROM activities WHERE trip_id = ? AND (day < ? OR day > ?)",
                (trip.id, trip.start_date.isoformat(), trip.end_date.isoformat()),
            ).fetchone()[0]
            if outside:
                raise ValidationError(
                    f"{outside} activities fall outside the new dates; move or delete them first"
                )
            conn.execute(
                "UPDATE trips SET name = ?, destination = ?, start_date = ?, end_date = ?,"
                " trip_type = ? WHERE id = ?",
                (
                    trip.name.strip(),
                    trip.destination.strip(),
                    trip.start_date.isoformat(),
                    trip.end_date.isoformat(),
                    trip.trip_type,
                    trip.id,
                ),
            )
            self._write_travelers(conn, trip.id, trip.travelers)
            if removed:
                marks = ",".join("?" * len(removed))
                conn.execute(
                    f"UPDATE packing_items SET assignee = '' WHERE trip_id = ?"
                    f" AND assignee IN ({marks})",
                    (trip.id, *removed),
                )
        return trip

    def delete_trip(self, trip_id: int) -> None:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"Trip {trip_id} not found")

    # ---- activities --------------------------------------------------
    def add_activity(self, trip_id: int, a: Activity) -> Activity:
        trip = self.get_trip(trip_id)
        if not trip.start_date <= a.day <= trip.end_date:
            raise ValidationError("Activity date is outside the trip dates")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO activities"
                " (trip_id, day, start_time, end_time, title, location, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    trip_id,
                    a.day.isoformat(),
                    a.start.strftime("%H:%M"),
                    a.end.strftime("%H:%M"),
                    a.title.strip(),
                    a.location.strip(),
                    a.notes.strip(),
                ),
            )
            a.id = int(cur.lastrowid or 0)
        return a

    def add_activities(self, trip_id: int, items: list[Activity]) -> list[Activity]:
        return [self.add_activity(trip_id, a) for a in items]

    def list_activities(self, trip_id: int) -> list[Activity]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM activities WHERE trip_id = ? ORDER BY day, start_time, id",
                (trip_id,),
            ).fetchall()
        return [
            Activity(
                day=date.fromisoformat(r["day"]),
                start=time.fromisoformat(r["start_time"]),
                end=time.fromisoformat(r["end_time"]),
                title=r["title"],
                location=r["location"],
                notes=r["notes"],
                id=r["id"],
            )
            for r in rows
        ]

    def delete_activity(self, activity_id: int) -> None:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"Activity {activity_id} not found")

    def clear_activities(self, trip_id: int) -> int:
        with self._conn() as conn:
            return conn.execute("DELETE FROM activities WHERE trip_id = ?", (trip_id,)).rowcount

    # ---- budget ------------------------------------------------------
    def set_budget(self, trip_id: int, budget: dict[str, float]) -> None:
        self.get_trip(trip_id)
        rows = []
        for cat, amount in budget.items():
            if cat not in BUDGET_CATEGORIES:
                raise ValidationError(f"Unknown category: {cat}")
            if amount < 0:
                raise ValidationError("Budget amounts cannot be negative")
            rows.append((trip_id, cat, int(round(amount * 100))))
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO budgets (trip_id, category, amount_cents) VALUES (?, ?, ?)"
                " ON CONFLICT(trip_id, category)"
                " DO UPDATE SET amount_cents = excluded.amount_cents",
                rows,
            )

    def get_budget(self, trip_id: int) -> dict[str, float]:
        out = {c: 0.0 for c in BUDGET_CATEGORIES}
        with self._conn() as conn:
            for r in conn.execute(
                "SELECT category, amount_cents FROM budgets WHERE trip_id = ?", (trip_id,)
            ):
                out[r["category"]] = r["amount_cents"] / 100
        return out

    # ---- expenses ----------------------------------------------------
    def add_expense(self, trip_id: int, e: Expense) -> Expense:
        trip = self.get_trip(trip_id)
        unknown = ({e.payer} | set(e.participants)) - set(trip.travelers)
        if unknown:
            raise ValidationError("Not on this trip: " + ", ".join(sorted(unknown)))
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO expenses (trip_id, description, amount_cents, payer, category,"
                " spent_on) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    trip_id,
                    e.description.strip(),
                    int(round(e.amount * 100)),
                    e.payer,
                    e.category,
                    e.spent_on.isoformat() if e.spent_on else None,
                ),
            )
            e.id = int(cur.lastrowid or 0)
            conn.executemany(
                "INSERT INTO expense_participants (expense_id, name) VALUES (?, ?)",
                [(e.id, p) for p in e.participants],
            )
        return e

    def list_expenses(self, trip_id: int) -> list[Expense]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE trip_id = ? ORDER BY spent_on, id", (trip_id,)
            ).fetchall()
            parts: dict[int, list[str]] = {}
            for r in conn.execute(
                "SELECT p.expense_id, p.name FROM expense_participants p"
                " JOIN expenses e ON e.id = p.expense_id WHERE e.trip_id = ?"
                " ORDER BY p.rowid",
                (trip_id,),
            ):
                parts.setdefault(r["expense_id"], []).append(r["name"])
        return [
            Expense(
                description=r["description"],
                amount=r["amount_cents"] / 100,
                payer=r["payer"],
                participants=parts.get(r["id"], []),
                category=r["category"],
                spent_on=date.fromisoformat(r["spent_on"]) if r["spent_on"] else None,
                id=r["id"],
            )
            for r in rows
        ]

    def delete_expense(self, expense_id: int) -> None:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"Expense {expense_id} not found")

    # ---- packing -----------------------------------------------------
    def add_packing_items(self, trip_id: int, items: list[PackingItem]) -> list[PackingItem]:
        trip = self.get_trip(trip_id)
        existing = {i.name.lower() for i in self.list_packing(trip_id)}
        added = []
        with self._conn() as conn:
            for item in items:
                if item.assignee and item.assignee not in trip.travelers:
                    raise ValidationError(f"Not on this trip: {item.assignee}")
                if item.name.lower() in existing:
                    continue
                cur = conn.execute(
                    "INSERT INTO packing_items (trip_id, name, packed, assignee)"
                    " VALUES (?, ?, ?, ?)",
                    (trip_id, item.name, int(item.packed), item.assignee),
                )
                item.id = int(cur.lastrowid or 0)
                existing.add(item.name.lower())
                added.append(item)
        return added

    def list_packing(self, trip_id: int) -> list[PackingItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM packing_items WHERE trip_id = ? ORDER BY id", (trip_id,)
            ).fetchall()
        return [
            PackingItem(
                name=r["name"], packed=bool(r["packed"]), assignee=r["assignee"], id=r["id"]
            )
            for r in rows
        ]

    def set_packed(self, item_id: int, packed: bool) -> None:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE packing_items SET packed = ? WHERE id = ?", (int(packed), item_id)
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"Packing item {item_id} not found")

    def delete_packing_item(self, item_id: int) -> None:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM packing_items WHERE id = ?", (item_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"Packing item {item_id} not found")
