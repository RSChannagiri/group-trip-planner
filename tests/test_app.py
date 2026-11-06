"""Headless smoke tests of the Streamlit app using AppTest."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from trip_planner.db import TripStore

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    monkeypatch.setenv("TRIP_PLANNER_DB", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return path


def run(at: AppTest) -> AppTest:
    at.run(timeout=30)
    assert not at.exception, at.exception
    return at


def test_app_seeds_and_renders_all_tabs(db_path):
    at = run(AppTest.from_file(APP))
    assert at.title[0].value == "Tokyo Spring Break"
    assert [t.label for t in at.tabs] == [
        "Itinerary",
        "Budget",
        "Expenses & settle-up",
        "Packing",
        "Export",
        "Trip settings",
    ]
    assert any("schedule conflict" in w.value for w in at.warning)
    assert any("pays" in m.value for m in at.markdown)


def test_app_add_activity_persists(db_path):
    at = run(AppTest.from_file(APP))
    form_inputs = [t for t in at.text_input if t.label == "Title"]
    form_inputs[0].input("Ghibli Museum")
    next(b for b in at.button if b.label == "Add to itinerary").click()
    run(at)
    store = TripStore(db_path)
    titles = [a.title for a in store.list_activities(store.list_trips()[0].id)]
    assert "Ghibli Museum" in titles


def test_app_rejects_invalid_expense(db_path):
    at = run(AppTest.from_file(APP))
    next(t for t in at.text_input if t.label == "Description").input("Taxi")
    next(b for b in at.button if b.label == "Add expense").click()
    run(at)  # amount left at 0
    assert any("positive" in e.value for e in at.error)


def test_app_offline_draft_adds_template_activities(db_path):
    at = run(AppTest.from_file(APP))
    next(c for c in at.checkbox if c.label.startswith("Replace")).check()
    next(b for b in at.button if b.label == "Draft itinerary").click()
    run(at)
    store = TripStore(db_path)
    assert len(store.list_activities(store.list_trips()[0].id)) == 28
    assert any("offline template" in w.value for w in at.warning)


def test_app_create_trip_from_sidebar(db_path):
    at = run(AppTest.from_file(APP))
    sb = at.sidebar
    next(t for t in sb.text_input if t.label == "Trip name").input("Banff Ski Week")
    next(t for t in sb.text_input if t.label == "Destination").input("Banff")
    sb.text_area[0].input("Priya, Jordan")
    sb.selectbox[0].select("ski")
    next(b for b in sb.button if b.label == "Create trip").click()
    run(at)
    assert at.title[0].value == "Banff Ski Week"
    store = TripStore(db_path)
    banff = next(t for t in store.list_trips() if t.name == "Banff Ski Week")
    assert "Goggles" in [i.name for i in store.list_packing(banff.id)]
