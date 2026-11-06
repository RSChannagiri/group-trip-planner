from datetime import date, datetime, time

import pytest

from trip_planner.export import to_ics, to_markdown
from trip_planner.models import Activity, PackingItem, ValidationError
from trip_planner.packing import BASE, progress, template_for


@pytest.fixture
def acts():
    return [
        Activity(date(2027, 5, 2), time(14), time(16), "Tram 28, Alfama", notes="Line 1\nLine 2"),
        Activity(date(2027, 5, 1), time(9), time(11), "Belem; Tower", location="Belem"),
    ]


def test_ics_structure_and_crlf(trip, acts):
    ics = to_ics(trip, acts, stamp=datetime(2027, 1, 1, 12))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20270501T090000" in ics and "DTEND:20270502T160000" in ics
    assert "DTSTAMP:20270101T120000" in ics


def test_ics_escapes_special_characters(trip, acts):
    ics = to_ics(trip, acts)
    assert r"SUMMARY:Belem\; Tower" in ics
    assert r"SUMMARY:Tram 28\, Alfama" in ics
    assert r"DESCRIPTION:Line 1\nLine 2" in ics


def test_ics_events_sorted_with_unique_uids(trip, acts):
    ics = to_ics(trip, acts)
    assert ics.index("Belem") < ics.index("Tram 28")
    uids = [line for line in ics.split("\r\n") if line.startswith("UID:")]
    assert len(set(uids)) == 2


def test_markdown_lists_days_including_free_days(trip, acts):
    md = to_markdown(trip, acts)
    assert md.startswith("# Test Trip")
    assert "## Day 1: Saturday, May 01" in md
    assert "- 09:00-11:00 **Belem; Tower** (Belem)" in md
    assert "## Day 3" in md and "_Free day_" in md
    assert "Ana, Ben, Cy" in md


def test_packing_template_by_type_and_length():
    beach = [i.name for i in template_for("beach", 3)]
    assert "Sunscreen" in beach and all(b in beach for b in BASE)
    assert "Laundry bag" not in beach
    assert "Laundry bag" in [i.name for i in template_for("beach", 7)]
    assert "Laptop" in [i.name for i in template_for("business")]


def test_packing_template_unknown_type():
    with pytest.raises(ValidationError):
        template_for("space")


def test_packing_progress():
    assert progress([]) == 0.0
    items = [PackingItem("a", packed=True), PackingItem("b"), PackingItem("c"), PackingItem("d")]
    assert progress(items) == 0.25


def test_ics_folds_long_lines(trip):
    long = Activity(date(2027, 5, 1), time(9), time(10), "Sakura " * 30)
    lines = to_ics(trip, [long]).split("\r\n")
    assert all(len(line.encode()) <= 75 for line in lines)
    assert any(line.startswith(" ") for line in lines)
    unfolded = to_ics(trip, [long]).replace("\r\n ", "")
    assert "SUMMARY:" + "Sakura " * 29 + "Sakura" in unfolded
