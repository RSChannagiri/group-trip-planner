"""Packing checklist templates."""

from __future__ import annotations

from .models import TRIP_TYPES, PackingItem, ValidationError

BASE = ["Passport / ID", "Phone charger", "Toiletries", "Medications", "Underwear", "Socks"]

TEMPLATES: dict[str, list[str]] = {
    "city": [
        "Comfortable walking shoes",
        "Day bag",
        "Power adapter",
        "Light jacket",
        "Transit card",
    ],
    "beach": ["Swimsuit", "Sunscreen", "Sunglasses", "Flip flops", "Beach towel", "Hat"],
    "hiking": ["Hiking boots", "Rain shell", "Headlamp", "Water filter", "First aid kit", "Map"],
    "ski": ["Ski jacket", "Base layers", "Goggles", "Gloves", "Neck gaiter", "Hand warmers"],
    "business": ["Laptop", "Business attire", "Notebook", "Business cards", "Presentation clicker"],
}


def template_for(trip_type: str, num_days: int = 1) -> list[PackingItem]:
    if trip_type not in TRIP_TYPES:
        raise ValidationError(f"Unknown trip type: {trip_type}")
    items = BASE + TEMPLATES[trip_type]
    if num_days >= 5:
        items = items + ["Laundry bag"]
    return [PackingItem(name=n) for n in items]


def progress(items: list[PackingItem]) -> float:
    if not items:
        return 0.0
    return sum(i.packed for i in items) / len(items)
