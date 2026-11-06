import json
from types import SimpleNamespace

import pytest

from trip_planner.drafter import (
    build_prompt,
    draft_itinerary,
    parse_llm_json,
    rule_based_draft,
)
from trip_planner.itinerary import find_conflicts
from trip_planner.models import TRIP_TYPES, Trip


class FakeClient:
    """Mimics openai.OpenAI().chat.completions.create."""

    def __init__(self, content=None, error=None):
        self.calls = []
        self._content, self._error = content, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        msg = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


LLM_JSON = json.dumps(
    {
        "activities": [
            {
                "day": 1,
                "start": "09:00",
                "end": "11:00",
                "title": "Belem Tower",
                "location": "Belem",
            },
            {"day": 2, "start": "13:00", "end": "15:00", "title": "Tram 28"},
            {"day": 9, "start": "13:00", "end": "15:00", "title": "Out of range"},
        ]
    }
)


@pytest.mark.parametrize("ttype", TRIP_TYPES)
def test_rule_based_draft_covers_every_day_without_conflicts(trip, ttype):
    t = Trip(trip.name, trip.destination, trip.start_date, trip.end_date, trip.travelers, ttype)
    acts = rule_based_draft(t)
    assert {a.day for a in acts} == set(t.days())
    assert find_conflicts(acts) == []


def test_rule_based_draft_is_deterministic_with_arrival_and_farewell(trip):
    a, b = rule_based_draft(trip), rule_based_draft(trip)
    assert [x.title for x in a] == [x.title for x in b]
    assert a[0].title.startswith("Arrive in Lisbon")
    assert a[-1].title == "Farewell dinner"


def test_parse_llm_json_drops_out_of_range_days(trip):
    acts = parse_llm_json(LLM_JSON, trip)
    assert [a.title for a in acts] == ["Belem Tower", "Tram 28"]
    assert acts[1].day == trip.days()[1] and acts[1].location == ""


def test_parse_llm_json_handles_code_fences_and_bare_list(trip):
    fenced = "```json\n" + json.dumps(json.loads(LLM_JSON)["activities"]) + "\n```"
    assert len(parse_llm_json(fenced, trip)) == 2


def test_parse_llm_json_skips_malformed_rows(trip):
    data = [
        {"day": 1, "start": "9am", "end": "10:00", "title": "bad"},
        {"day": 1, "start": "12:00", "end": "11:00", "title": "backwards"},
        {"day": 1, "title": "missing times"},
        {"day": 1, "start": "10:00", "end": "11:00", "title": "good"},
    ]
    assert [a.title for a in parse_llm_json(json.dumps(data), trip)] == ["good"]


@pytest.mark.parametrize("text", ["not json", "{}", '{"activities": "nope"}', "[]"])
def test_parse_llm_json_rejects_unusable(trip, text):
    with pytest.raises(ValueError):
        parse_llm_json(text, trip)


def test_build_prompt_mentions_trip_details(trip):
    p = build_prompt(trip, "seafood")
    assert "3-day" in p and "Lisbon" in p and "seafood" in p and "3 travelers" in p


def test_draft_uses_llm_when_client_works(trip):
    client = FakeClient(content=LLM_JSON)
    result = draft_itinerary(trip, "museums", client=client)
    assert result.source == "ai" and len(result.activities) == 2
    assert "museums" in client.calls[0]["messages"][-1]["content"]


def test_draft_falls_back_on_llm_error(trip):
    result = draft_itinerary(trip, client=FakeClient(error=RuntimeError("rate limited")))
    assert result.source == "template" and "rate limited" in result.note
    assert len(result.activities) == 4 * trip.num_days


def test_draft_falls_back_on_garbage_output(trip):
    assert (
        draft_itinerary(trip, client=FakeClient(content="Sure! Here you go")).source == "template"
    )


def test_draft_offline_without_api_key(trip, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = draft_itinerary(trip)
    assert result.source == "template" and "OPENAI_API_KEY" in result.note
