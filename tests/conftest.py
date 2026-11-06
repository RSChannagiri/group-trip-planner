from __future__ import annotations

from datetime import date

import pytest

from trip_planner.db import TripStore
from trip_planner.models import Trip


@pytest.fixture
def trip() -> Trip:
    return Trip(
        name="Test Trip",
        destination="Lisbon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        travelers=["Ana", "Ben", "Cy"],
        trip_type="city",
        id=1,
    )


@pytest.fixture
def store(tmp_path) -> TripStore:
    return TripStore(tmp_path / "trips.db")


@pytest.fixture
def saved_trip(store: TripStore, trip: Trip) -> Trip:
    trip.id = None
    return store.create_trip(trip)
