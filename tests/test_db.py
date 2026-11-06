import sqlite3
from dataclasses import replace
from datetime import date, time

import pytest

from trip_planner.db import NotFoundError, TripStore
from trip_planner.models import Activity, Expense, PackingItem, ValidationError


def test_create_and_get_trip_roundtrip(store, saved_trip):
    got = store.get_trip(saved_trip.id)
    assert got == saved_trip
    assert got.travelers == ["Ana", "Ben", "Cy"]  # order preserved


def test_list_trips_sorted_by_start(store, saved_trip):
    early = store.create_trip(
        replace(
            saved_trip,
            id=None,
            name="Early",
            start_date=date(2027, 1, 1),
            end_date=date(2027, 1, 2),
        )
    )
    assert [t.name for t in store.list_trips()] == ["Early", saved_trip.name]
    assert early.id != saved_trip.id


def test_get_missing_trip(store):
    with pytest.raises(NotFoundError):
        store.get_trip(999)


def test_store_persists_across_instances(tmp_path, trip):
    path = tmp_path / "p.db"
    trip.id = None
    TripStore(path).create_trip(trip)
    assert TripStore(path).list_trips()[0].destination == "Lisbon"


def test_activity_roundtrip_and_date_guard(store, saved_trip):
    a = store.add_activity(
        saved_trip.id,
        Activity(date(2027, 5, 2), time(9, 30), time(11), "Castle", "Alfama", "bring water"),
    )
    got = store.list_activities(saved_trip.id)
    assert got == [a] and got[0].start == time(9, 30)
    with pytest.raises(ValidationError, match="outside"):
        store.add_activity(saved_trip.id, Activity(date(2027, 6, 1), time(9), time(10), "No"))


def test_delete_and_clear_activities(store, saved_trip):
    a = store.add_activity(saved_trip.id, Activity(date(2027, 5, 1), time(9), time(10), "A"))
    store.add_activity(saved_trip.id, Activity(date(2027, 5, 1), time(11), time(12), "B"))
    store.delete_activity(a.id)
    assert [x.title for x in store.list_activities(saved_trip.id)] == ["B"]
    assert store.clear_activities(saved_trip.id) == 1
    with pytest.raises(NotFoundError):
        store.delete_activity(a.id)


def test_budget_defaults_upsert_and_validation(store, saved_trip):
    assert store.get_budget(saved_trip.id)["Food"] == 0
    store.set_budget(saved_trip.id, {"Food": 100.10})
    store.set_budget(saved_trip.id, {"Food": 250.55, "Lodging": 900})
    b = store.get_budget(saved_trip.id)
    assert b["Food"] == 250.55 and b["Lodging"] == 900
    with pytest.raises(ValidationError):
        store.set_budget(saved_trip.id, {"Food": -1})
    with pytest.raises(ValidationError):
        store.set_budget(saved_trip.id, {"Snacks": 10})


def test_expense_roundtrip_keeps_cents_and_participants(store, saved_trip):
    e = store.add_expense(
        saved_trip.id,
        Expense("Dinner", 33.33, "Ana", ["Cy", "Ana"], "Food", spent_on=date(2027, 5, 1)),
    )
    got = store.list_expenses(saved_trip.id)[0]
    assert got.amount == 33.33 and got.participants == ["Cy", "Ana"]
    assert got.spent_on == date(2027, 5, 1) and got.id == e.id


def test_expense_rejects_people_not_on_trip(store, saved_trip):
    with pytest.raises(ValidationError, match="Zed"):
        store.add_expense(saved_trip.id, Expense("x", 5, "Zed", ["Ana"]))


def test_delete_expense_cascades_participants(store, saved_trip):
    e = store.add_expense(saved_trip.id, Expense("x", 5, "Ana", ["Ana", "Ben"]))
    store.delete_expense(e.id)
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM expense_participants").fetchone()[0] == 0


def test_update_trip_blocks_orphaning(store, saved_trip):
    store.add_expense(saved_trip.id, Expense("x", 5, "Ana", ["Ana", "Cy"]))
    with pytest.raises(ValidationError, match="Cy"):
        store.update_trip(replace(saved_trip, travelers=["Ana", "Ben"]))
    store.add_activity(saved_trip.id, Activity(date(2027, 5, 3), time(9), time(10), "Late"))
    with pytest.raises(ValidationError, match="outside"):
        store.update_trip(replace(saved_trip, end_date=date(2027, 5, 2)))
    assert store.get_trip(saved_trip.id).end_date == date(2027, 5, 3)  # unchanged


def test_update_trip_allows_safe_edits(store, saved_trip):
    store.add_packing_items(saved_trip.id, [PackingItem("Tent", assignee="Ben")])
    store.update_trip(replace(saved_trip, name="Renamed", travelers=["Ana", "Cy", "Dee"]))
    got = store.get_trip(saved_trip.id)
    assert got.name == "Renamed" and got.travelers == ["Ana", "Cy", "Dee"]
    assert store.list_packing(saved_trip.id)[0].assignee == ""  # Ben's item now shared


def test_delete_trip_cascades(store, saved_trip):
    store.add_activity(saved_trip.id, Activity(date(2027, 5, 1), time(9), time(10), "A"))
    store.add_expense(saved_trip.id, Expense("x", 5, "Ana", ["Ana"]))
    store.add_packing_items(saved_trip.id, [PackingItem("Hat")])
    store.delete_trip(saved_trip.id)
    with sqlite3.connect(store.path) as conn:
        for table in ("activities", "expenses", "packing_items", "travelers", "budgets"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    with pytest.raises(NotFoundError):
        store.delete_trip(saved_trip.id)


def test_packing_dedupes_toggles_and_validates(store, saved_trip):
    added = store.add_packing_items(saved_trip.id, [PackingItem("Hat"), PackingItem("hat")])
    assert len(added) == 1
    store.set_packed(added[0].id, True)
    assert store.list_packing(saved_trip.id)[0].packed is True
    with pytest.raises(ValidationError):
        store.add_packing_items(saved_trip.id, [PackingItem("Map", assignee="Zed")])
    store.delete_packing_item(added[0].id)
    assert store.list_packing(saved_trip.id) == []
    with pytest.raises(NotFoundError):
        store.set_packed(added[0].id, False)
