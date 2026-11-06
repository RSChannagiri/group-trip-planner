from datetime import date, time

import pytest

from trip_planner.models import Activity, Expense, PackingItem, Trip, ValidationError


def make_trip(**kw):
    base = dict(
        name="T",
        destination="D",
        start_date=date(2027, 1, 1),
        end_date=date(2027, 1, 2),
        travelers=["A", "B"],
    )
    base.update(kw)
    return Trip(**base)


def test_trip_days_inclusive():
    t = make_trip(end_date=date(2027, 1, 7))
    assert t.num_days == 7
    assert t.days()[0] == date(2027, 1, 1) and t.days()[-1] == date(2027, 1, 7)


def test_single_day_trip_allowed():
    assert make_trip(end_date=date(2027, 1, 1)).num_days == 1


@pytest.mark.parametrize(
    "kw, msg",
    [
        ({"name": "  "}, "name"),
        ({"destination": ""}, "Destination"),
        ({"end_date": date(2026, 12, 31)}, "End date"),
        ({"travelers": [" ", ""]}, "traveler"),
        ({"travelers": ["Ana", "ana"]}, "unique"),
        ({"trip_type": "cruise"}, "trip type"),
        ({"end_date": date(2027, 6, 1)}, "limited"),
    ],
)
def test_trip_validation(kw, msg):
    with pytest.raises(ValidationError, match=msg):
        make_trip(**kw)


def test_traveler_names_are_trimmed():
    assert make_trip(travelers=[" Ana ", "Ben", ""]).travelers == ["Ana", "Ben"]


def test_activity_must_end_after_start():
    with pytest.raises(ValidationError):
        Activity(date(2027, 1, 1), time(10), time(10), "Zero length")


def test_activity_requires_title():
    with pytest.raises(ValidationError):
        Activity(date(2027, 1, 1), time(9), time(10), "  ")


@pytest.mark.parametrize(
    "kw",
    [
        {"amount": 0},
        {"amount": -5},
        {"participants": []},
        {"category": "Bribes"},
        {"description": " "},
        {"participants": ["A", "A"]},
    ],
)
def test_expense_validation(kw):
    base = dict(description="Lunch", amount=10.0, payer="A", participants=["A", "B"])
    base.update(kw)
    with pytest.raises(ValidationError):
        Expense(**base)


def test_packing_item_name_required_and_trimmed():
    assert PackingItem("  Hat ").name == "Hat"
    with pytest.raises(ValidationError):
        PackingItem("   ")
