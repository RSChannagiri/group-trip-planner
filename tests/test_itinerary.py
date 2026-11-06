from datetime import date, time

import pytest

from trip_planner.itinerary import check_in_trip, conflicts_with, find_conflicts, group_by_day
from trip_planner.models import Activity, ValidationError

D1, D2 = date(2027, 5, 1), date(2027, 5, 2)


def act(day, s, e, title="x", id=None):
    return Activity(day, time.fromisoformat(s), time.fromisoformat(e), title, id=id)


def test_no_conflicts_for_back_to_back():
    assert find_conflicts([act(D1, "09:00", "10:00"), act(D1, "10:00", "11:00")]) == []


def test_overlap_detected():
    a, b = act(D1, "09:00", "10:30", "a"), act(D1, "10:00", "11:00", "b")
    assert find_conflicts([b, a]) == [(a, b)]


def test_same_time_different_days_ok():
    assert find_conflicts([act(D1, "09:00", "10:00"), act(D2, "09:00", "10:00")]) == []


def test_nested_and_multiple_overlaps():
    big = act(D1, "08:00", "18:00", "big")
    small1 = act(D1, "09:00", "10:00", "s1")
    small2 = act(D1, "12:00", "13:00", "s2")
    pairs = find_conflicts([small2, big, small1])
    assert (big, small1) in pairs and (big, small2) in pairs
    assert len(pairs) == 2  # s1 and s2 do not overlap each other


def test_conflicts_with_excludes_self_by_identity_and_id():
    a = act(D1, "09:00", "10:00", id=5)
    copy = act(D1, "09:00", "10:00", id=5)
    other = act(D1, "09:30", "11:00", id=6)
    assert conflicts_with(a, [a, copy, other]) == [other]


def test_check_in_trip(trip):
    check_in_trip(act(D1, "09:00", "10:00"), trip)
    with pytest.raises(ValidationError):
        check_in_trip(act(date(2027, 6, 1), "09:00", "10:00"), trip)


def test_group_by_day_includes_empty_days_sorted(trip):
    late, early = act(D1, "15:00", "16:00", "late"), act(D1, "08:00", "09:00", "early")
    grouped = group_by_day(trip, [late, early])
    assert list(grouped) == trip.days()
    assert [a.title for a in grouped[D1]] == ["early", "late"]
    assert grouped[date(2027, 5, 3)] == []
