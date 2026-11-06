"""Budget planning, expense balances, and settle-up.

All money math is done in integer cents so balances always sum to exactly zero
and nobody is ever off by a rounding penny.
"""

from __future__ import annotations

from .models import BUDGET_CATEGORIES, Expense, ValidationError

# Above this many non-zero balances the exact optimizer gets slow (O(n * 2^n)),
# so we fall back to the greedy heuristic, which needs at most n - 1 transfers.
EXACT_SETTLE_LIMIT = 15

Transfer = tuple[str, str, float]


def to_cents(amount: float) -> int:
    return int(round(amount * 100))


def from_cents(cents: int) -> float:
    return round(cents / 100, 2)


def per_person_targets(budget: dict[str, float], num_travelers: int) -> dict[str, float]:
    """Planned spend per traveler for each category (equal split)."""
    if num_travelers <= 0:
        raise ValidationError("Need at least one traveler")
    return {c: round(budget.get(c, 0.0) / num_travelers, 2) for c in BUDGET_CATEGORIES}


def spent_by_category(expenses: list[Expense]) -> dict[str, float]:
    out = {c: 0 for c in BUDGET_CATEGORIES}
    for e in expenses:
        out[e.category] += to_cents(e.amount)
    return {c: from_cents(v) for c, v in out.items()}


def budget_status(budget: dict[str, float], expenses: list[Expense]) -> list[dict]:
    """One row per category: planned, spent, remaining, percent used, over flag."""
    spent = spent_by_category(expenses)
    rows = []
    for c in BUDGET_CATEGORIES:
        planned = round(budget.get(c, 0.0), 2)
        used = spent[c]
        rows.append(
            {
                "category": c,
                "planned": planned,
                "spent": used,
                "remaining": round(planned - used, 2),
                "pct_used": round(used / planned * 100, 1) if planned else None,
                "over": to_cents(used) > to_cents(planned),
            }
        )
    return rows


def split_cents(amount_cents: int, participants: list[str]) -> dict[str, int]:
    """Split an amount evenly; leftover cents go to participants in name order.

    Deterministic, so the same expense always produces the same shares.
    """
    if not participants:
        raise ValidationError("Expense needs at least one participant")
    base, extra = divmod(amount_cents, len(participants))
    shares = {}
    for i, p in enumerate(sorted(participants)):
        shares[p] = base + (1 if i < extra else 0)
    return shares


def _balances_cents(expenses: list[Expense], travelers: list[str]) -> dict[str, int]:
    bal = {t: 0 for t in travelers}
    for e in expenses:
        if e.payer not in bal:
            raise ValidationError(f"Unknown payer: {e.payer}")
        for p in e.participants:
            if p not in bal:
                raise ValidationError(f"Unknown participant: {p}")
        cents = to_cents(e.amount)
        bal[e.payer] += cents
        for p, share in split_cents(cents, e.participants).items():
            bal[p] -= share
    return bal


def balances(expenses: list[Expense], travelers: list[str]) -> dict[str, float]:
    """Net balance per traveler in dollars: positive means they are owed money."""
    return {k: from_cents(v) for k, v in _balances_cents(expenses, travelers).items()}


def share_by_traveler(expenses: list[Expense], travelers: list[str]) -> dict[str, float]:
    """How much of the group's spending each traveler consumed (their fair share)."""
    out = {t: 0 for t in travelers}
    for e in expenses:
        for p, share in split_cents(to_cents(e.amount), e.participants).items():
            if p not in out:
                raise ValidationError(f"Unknown participant: {p}")
            out[p] += share
    return {k: from_cents(v) for k, v in out.items()}


def _greedy(bal: dict[str, int]) -> list[tuple[str, str, int]]:
    """Largest debtor pays largest creditor until everyone is square."""
    debt = {k: -v for k, v in bal.items() if v < 0}
    cred = {k: v for k, v in bal.items() if v > 0}
    out: list[tuple[str, str, int]] = []
    while debt and cred:
        d = max(debt, key=lambda k: (debt[k], k))
        c = max(cred, key=lambda k: (cred[k], k))
        amt = min(debt[d], cred[c])
        out.append((d, c, amt))
        debt[d] -= amt
        cred[c] -= amt
        if debt[d] == 0:
            del debt[d]
        if cred[c] == 0:
            del cred[c]
    return out


def _zero_sum_groups(names: list[str], amounts: list[int]) -> list[list[str]]:
    """Partition people into the maximum number of groups that each sum to zero.

    A group of size m can always settle in m - 1 transfers, so maximizing the
    number of groups minimizes total transfers (n - groups). Bitmask DP.
    """
    n = len(names)
    full = (1 << n) - 1
    sums = [0] * (1 << n)
    for mask in range(1, full + 1):
        low = mask & -mask
        sums[mask] = sums[mask ^ low] + amounts[low.bit_length() - 1]
    best = [0] * (1 << n)
    for mask in range(1, full + 1):
        m = 0
        bits = mask
        while bits:
            low = bits & -bits
            bits ^= low
            m = max(m, best[mask ^ low])
        best[mask] = m + (1 if sums[mask] == 0 else 0)
    # Reconstruct by peeling people off; a group closes each time the
    # remaining set sums to zero.
    order: list[int] = []
    mask = full
    boundaries = []
    while mask:
        bonus = 1 if sums[mask] == 0 else 0
        if bonus:
            boundaries.append(len(order))
        bits = mask
        while bits:
            low = bits & -bits
            bits ^= low
            if best[mask ^ low] + bonus == best[mask]:
                order.append(low.bit_length() - 1)
                mask ^= low
                break
    boundaries.append(len(order))
    groups = []
    for a, b in zip(boundaries, boundaries[1:], strict=False):
        if b > a:
            groups.append([names[i] for i in order[a:b]])
    return groups


def settle_up(bal: dict[str, float]) -> list[Transfer]:
    """Transfers (from, to, amount) that clear every balance with the fewest payments.

    Exact for up to EXACT_SETTLE_LIMIT people with non-zero balances; greedy
    (at most n - 1 transfers) beyond that.
    """
    cents = {k: to_cents(v) for k, v in bal.items()}
    if sum(cents.values()) != 0:
        raise ValidationError("Balances must sum to zero")
    nonzero = {k: v for k, v in sorted(cents.items()) if v != 0}
    if not nonzero:
        return []
    if len(nonzero) > EXACT_SETTLE_LIMIT:
        raw = _greedy(nonzero)
    else:
        names = list(nonzero)
        raw = []
        for group in _zero_sum_groups(names, [nonzero[n] for n in names]):
            raw.extend(_greedy({n: nonzero[n] for n in group}))
    raw.sort(key=lambda t: (-t[2], t[0], t[1]))
    return [(d, c, from_cents(a)) for d, c, a in raw]
