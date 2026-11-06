"""Sample data: a 7-day Tokyo trip for 4 friends.

Traveler names come from Faker with a fixed seed, so they are synthetic but
stable across runs (and tests can rely on them).
"""

from __future__ import annotations

from datetime import date, time, timedelta

from faker import Faker

from .db import TripStore
from .models import Activity, Expense, Trip
from .packing import template_for

SEED = 2027
START = date(2027, 3, 27)  # cherry blossom season


def sample_travelers(n: int = 4, seed: int = SEED) -> list[str]:
    fake = Faker("en_US")
    fake.seed_instance(seed)
    names: list[str] = []
    while len(names) < n:
        # alternate generators for a mixed group of friends
        gen = fake.first_name_female if len(names) % 2 == 0 else fake.first_name_male
        name = gen()
        if name not in names:
            names.append(name)
    return names


# (day offset, start, end, title, location)
ITINERARY: list[tuple[int, str, str, str, str]] = [
    (0, "14:00", "15:30", "Land at Haneda, IC cards and train to hotel", "Haneda Airport"),
    (0, "16:00", "17:00", "Check in", "Shinjuku hotel"),
    (0, "18:30", "20:30", "Izakaya dinner in Omoide Yokocho", "Shinjuku"),
    (1, "08:30", "10:30", "Tsukiji Outer Market breakfast", "Tsukiji"),
    (1, "11:00", "13:00", "teamLab Planets", "Toyosu"),
    (1, "15:00", "17:30", "Hanami picnic at Ueno Park", "Ueno"),
    (1, "19:00", "21:00", "Ramen crawl", "Ikebukuro"),
    (2, "09:00", "11:30", "Senso-ji and Nakamise street", "Asakusa"),
    (2, "11:00", "12:30", "Sumida river cruise", "Asakusa pier"),  # overlaps on purpose
    (2, "14:00", "16:00", "Tokyo Skytree observation deck", "Oshiage"),
    (2, "18:30", "20:30", "Monjayaki dinner", "Tsukishima"),
    (3, "07:30", "19:00", "Day trip to Hakone (Romancecar, ropeway, onsen)", "Hakone"),
    (4, "10:00", "12:00", "Meiji Jingu shrine walk", "Harajuku"),
    (4, "12:30", "14:30", "Takeshita Street and Omotesando", "Harajuku"),
    (4, "17:00", "18:00", "Shibuya Crossing and Shibuya Sky at sunset", "Shibuya"),
    (4, "19:30", "21:30", "Yakitori dinner", "Ebisu"),
    (5, "10:00", "13:00", "Akihabara arcades and electronics", "Akihabara"),
    (5, "14:00", "16:30", "Imperial Palace East Gardens", "Chiyoda"),
    (5, "18:00", "21:00", "Sushi omakase farewell dinner", "Ginza"),
    (6, "09:00", "11:00", "Last-minute souvenirs", "Tokyo Station"),
    (6, "12:00", "13:30", "Train to Haneda and fly home", "Haneda Airport"),
]

BUDGET = {
    "Lodging": 2800.0,
    "Transport": 900.0,
    "Food": 1600.0,
    "Activities": 800.0,
    "Shopping": 600.0,
    "Other": 200.0,
}


def sample_expenses(travelers: list[str]) -> list[Expense]:
    a, b, c, d = travelers[:4]
    everyone = list(travelers)
    rows = [
        ("Hotel, 6 nights (2 rooms)", 2640.00, a, everyone, "Lodging", 0),
        ("Suica top-ups", 160.00, b, everyone, "Transport", 0),
        ("Omoide Yokocho izakaya", 148.40, c, everyone, "Food", 0),
        ("Tsukiji breakfast", 86.20, d, everyone, "Food", 1),
        ("teamLab Planets tickets", 152.00, b, everyone, "Activities", 1),
        ("Ramen crawl", 64.00, a, everyone, "Food", 1),
        ("Skytree tickets", 96.00, c, everyone, "Activities", 2),
        ("Monjayaki dinner", 118.75, d, everyone, "Food", 2),
        ("Hakone Free Pass x4", 248.00, a, everyone, "Transport", 3),
        ("Hakone onsen entry", 72.00, c, [a, c, d], "Activities", 3),
        ("Shibuya Sky tickets", 88.00, d, everyone, "Activities", 4),
        ("Yakitori dinner", 132.60, b, everyone, "Food", 4),
        ("Retro game cartridges", 54.00, b, [b, c], "Shopping", 5),
        ("Sushi omakase", 520.00, c, everyone, "Food", 5),
        ("Airport limousine bus", 64.00, d, everyone, "Transport", 6),
    ]
    return [
        Expense(
            description=desc,
            amount=amt,
            payer=payer,
            participants=parts,
            category=cat,
            spent_on=START + timedelta(days=off),
        )
        for desc, amt, payer, parts, cat, off in rows
    ]


def seed_sample_trip(store: TripStore) -> Trip:
    """Insert the Tokyo sample trip and return it."""
    travelers = sample_travelers()
    trip = store.create_trip(
        Trip(
            name="Tokyo Spring Break",
            destination="Tokyo, Japan",
            start_date=START,
            end_date=START + timedelta(days=6),
            travelers=travelers,
            trip_type="city",
        )
    )
    assert trip.id is not None
    store.add_activities(
        trip.id,
        [
            Activity(
                day=START + timedelta(days=off),
                start=time.fromisoformat(s),
                end=time.fromisoformat(e),
                title=title,
                location=loc,
            )
            for off, s, e, title, loc in ITINERARY
        ],
    )
    store.set_budget(trip.id, BUDGET)
    for e in sample_expenses(travelers):
        store.add_expense(trip.id, e)
    items = template_for(trip.trip_type, trip.num_days)
    for i, item in enumerate(items[:5]):
        item.packed = True
        item.assignee = travelers[i % len(travelers)] if i % 2 else ""
    store.add_packing_items(trip.id, items)
    return trip


def ensure_seeded(store: TripStore) -> None:
    """Seed the sample trip only into an empty database."""
    if not store.list_trips():
        seed_sample_trip(store)
