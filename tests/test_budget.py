import itertools
import random

import pytest

from trip_planner.budget import (
    _greedy,
    balances,
    budget_status,
    per_person_targets,
    settle_up,
    share_by_traveler,
    spent_by_category,
    split_cents,
)
from trip_planner.models import Expense, ValidationError


def exp(amount, payer, parts, cat="Food"):
    return Expense("x", amount, payer, parts, cat)


def apply(bal, transfers):
    out = dict(bal)
    for frm, to, amt in transfers:
        out[frm] = round(out[frm] + amt, 2)
        out[to] = round(out[to] - amt, 2)
    return out


def test_per_person_targets_split_evenly():
    t = per_person_targets({"Lodging": 1000, "Food": 300}, 4)
    assert t["Lodging"] == 250 and t["Food"] == 75 and t["Other"] == 0


def test_per_person_targets_requires_travelers():
    with pytest.raises(ValidationError):
        per_person_targets({}, 0)


def test_spent_by_category_avoids_float_drift():
    spent = spent_by_category([exp(0.1, "A", ["A"])] * 3)
    assert spent["Food"] == 0.3


def test_budget_status_flags_over_and_handles_zero_budget():
    rows = {
        r["category"]: r
        for r in budget_status({"Food": 100}, [exp(120, "A", ["A"]), exp(5, "A", ["A"], "Other")])
    }
    assert rows["Food"]["over"] and rows["Food"]["remaining"] == -20
    assert rows["Food"]["pct_used"] == 120.0
    assert rows["Other"]["pct_used"] is None and rows["Other"]["over"]
    assert rows["Lodging"]["over"] is False


def test_budget_status_exactly_on_budget_is_not_over():
    rows = budget_status({"Food": 100}, [exp(100, "A", ["A"])])
    assert not rows[2]["over"]


def test_split_cents_distributes_remainder_deterministically():
    assert split_cents(1000, ["C", "A", "B"]) == {"A": 334, "B": 333, "C": 333}
    assert sum(split_cents(1001, ["X", "Y"]).values()) == 1001


def test_balances_sum_to_exactly_zero_with_odd_splits():
    ex = [exp(10, "A", ["A", "B", "C"]), exp(7.01, "B", ["A", "B", "C"])]
    bal = balances(ex, ["A", "B", "C"])
    assert round(sum(bal.values()), 2) == 0
    assert bal["A"] == pytest.approx(10 - 3.34 - 2.34)


def test_balances_payer_not_participant():
    bal = balances([exp(30, "A", ["B", "C"])], ["A", "B", "C"])
    assert bal == {"A": 30, "B": -15, "C": -15}


def test_balances_unknown_people_rejected():
    with pytest.raises(ValidationError, match="payer"):
        balances([exp(10, "Z", ["A"])], ["A"])
    with pytest.raises(ValidationError, match="participant"):
        balances([exp(10, "A", ["Z"])], ["A"])


def test_share_by_traveler_counts_only_consumed():
    s = share_by_traveler([exp(30, "A", ["B", "C"])], ["A", "B", "C"])
    assert s == {"A": 0, "B": 15, "C": 15}


def test_settle_up_empty_and_balanced():
    assert settle_up({}) == []
    assert settle_up({"A": 0, "B": 0}) == []


def test_settle_up_simple():
    assert settle_up({"A": 20, "B": -20}) == [("B", "A", 20)]


def test_settle_up_rejects_unbalanced():
    with pytest.raises(ValidationError):
        settle_up({"A": 10, "B": -5})


def test_settle_up_beats_greedy_on_known_case():
    # Greedy pairs the biggest numbers and needs 4 payments; optimum is 3
    # because {A, D} and {B, C, E} each sum to zero.
    bal = {"A": 6.0, "B": 5.0, "C": 3.0, "D": -6.0, "E": -8.0}
    greedy = _greedy({k: int(v * 100) for k, v in bal.items()})
    best = settle_up(bal)
    assert len(best) == 3
    assert len(greedy) == 4
    assert all(abs(v) < 1e-9 for v in apply(bal, best).values())


def test_settle_up_finds_independent_pairs():
    bal = {"A": 10, "B": -10, "C": 25, "D": -25, "E": 7, "F": -7}
    assert len(settle_up(bal)) == 3


def brute_force_min(bal_cents):
    """Minimum transfers = n - max number of zero-sum blocks (exhaustive)."""
    names = [k for k, v in bal_cents.items() if v]
    n = len(names)
    best = 0
    for labels in itertools.product(range(n), repeat=n):
        groups = {}
        for name, lab in zip(names, labels, strict=True):
            groups.setdefault(lab, []).append(bal_cents[name])
        if all(sum(g) == 0 for g in groups.values()):
            best = max(best, len(groups))
    return n - best if n else 0


@pytest.mark.parametrize("seed", range(25))
def test_settle_up_is_optimal_and_clears_all_balances(seed):
    rng = random.Random(seed)
    n = rng.randint(2, 6)
    vals = [rng.choice([-1, 1]) * rng.randint(1, 5) * 500 for _ in range(n - 1)]
    vals.append(-sum(vals))
    bal = {f"P{i}": v / 100 for i, v in enumerate(vals)}
    transfers = settle_up(bal)
    assert all(abs(v) < 1e-9 for v in apply(bal, transfers).values())
    assert all(amt > 0 for _, _, amt in transfers)
    assert len(transfers) == brute_force_min({k: v for k, v in zip(bal, vals, strict=True)})


def test_settle_up_large_group_uses_greedy_but_still_settles():
    vals = [100 * (i + 1) for i in range(10)] + [-100 * (i + 1) for i in range(10)]
    bal = {f"P{i}": v / 100 for i, v in enumerate(vals)}
    transfers = settle_up(bal)
    assert len(transfers) <= len(bal) - 1
    assert all(abs(v) < 1e-9 for v in apply(bal, transfers).values())
