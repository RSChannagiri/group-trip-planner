from datetime import date

from trip_planner import budget, reports
from trip_planner.itinerary import find_conflicts
from trip_planner.seed import ensure_seeded, sample_travelers, seed_sample_trip


def test_sample_travelers_stable_and_unique():
    names = sample_travelers()
    assert names == sample_travelers() and len(set(names)) == 4


def test_seed_creates_tokyo_trip(store):
    trip = seed_sample_trip(store)
    assert trip.destination == "Tokyo, Japan" and trip.num_days == 7
    assert len(trip.travelers) == 4
    acts = store.list_activities(trip.id)
    assert {a.day for a in acts} == set(trip.days())
    assert len(find_conflicts(acts)) == 1  # one deliberate overlap to showcase detection
    assert len(store.list_expenses(trip.id)) == 15
    assert 0 < sum(i.packed for i in store.list_packing(trip.id)) < len(store.list_packing(trip.id))


def test_seed_balances_settle_in_at_most_three_payments(store):
    trip = seed_sample_trip(store)
    bal = budget.balances(store.list_expenses(trip.id), trip.travelers)
    assert round(sum(bal.values()), 2) == 0
    assert 0 < len(budget.settle_up(bal)) <= 3


def test_ensure_seeded_is_idempotent(store):
    ensure_seeded(store)
    ensure_seeded(store)
    assert len(store.list_trips()) == 1


def test_itinerary_frame_marks_conflicts(store):
    trip = seed_sample_trip(store)
    acts = store.list_activities(trip.id)
    df = reports.itinerary_frame(acts)
    assert len(df) == len(acts) and df["Conflict"].sum() == 2
    assert len(reports.conflict_messages(acts)) == 1
    assert reports.itinerary_frame([]).empty


def test_budget_and_per_person_frames(store):
    trip = seed_sample_trip(store)
    b, ex = store.get_budget(trip.id), store.list_expenses(trip.id)
    df = reports.budget_frame(trip, b, ex)
    assert df.loc[df.category == "Lodging", "per_person_target"].item() == 700
    pp = reports.per_person_frame(trip, b, ex)
    assert list(pp.traveler) == trip.travelers
    assert round(pp.share_spent.sum(), 2) == round(sum(e.amount for e in ex), 2)


def test_expense_frame_and_countdown(store):
    trip = seed_sample_trip(store)
    df = reports.expense_frame(store.list_expenses(trip.id))
    assert "Split with" in df.columns and len(df) == 15
    assert reports.expense_frame([]).empty
    assert reports.countdown_days(trip, date(2027, 3, 20)) == 7
