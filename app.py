"""Streamlit UI for the group trip planner.

All business logic lives in the trip_planner package; this file only wires
widgets to it.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

import streamlit as st

from trip_planner import budget as budget_logic
from trip_planner import reports
from trip_planner.db import TripStore
from trip_planner.drafter import draft_itinerary
from trip_planner.export import to_ics, to_markdown
from trip_planner.itinerary import conflicts_with
from trip_planner.models import (
    BUDGET_CATEGORIES,
    TRIP_TYPES,
    Activity,
    Expense,
    PackingItem,
    Trip,
    ValidationError,
)
from trip_planner.packing import progress, template_for
from trip_planner.seed import ensure_seeded

MONEY = st.column_config.NumberColumn(format="$%.2f")
DB_PATH = os.environ.get("TRIP_PLANNER_DB", str(Path(__file__).parent / "data" / "trips.db"))

st.set_page_config(page_title="Group Trip Planner", page_icon="🧳", layout="wide")


def get_store() -> TripStore:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    store = TripStore(DB_PATH)
    ensure_seeded(store)
    return store


def parse_names(raw: str) -> list[str]:
    return [n.strip() for n in raw.replace("\n", ",").split(",") if n.strip()]


store = get_store()

# ---------------------------------------------------------------- sidebar
st.sidebar.title("🧳 Group Trip Planner")
trips = store.list_trips()

with st.sidebar.expander("New trip", expanded=not trips):
    with st.form("new_trip", clear_on_submit=True):
        name = st.text_input("Trip name")
        dest = st.text_input("Destination")
        start = st.date_input("Start date", value=date.today() + timedelta(days=30))
        end = st.date_input("End date", value=date.today() + timedelta(days=34))
        people = st.text_area("Travelers (comma separated)")
        ttype = st.selectbox("Trip type", TRIP_TYPES)
        if st.form_submit_button("Create trip"):
            try:
                new = store.create_trip(Trip(name, dest, start, end, parse_names(people), ttype))
                assert new.id is not None
                store.add_packing_items(new.id, template_for(ttype, new.num_days))
                st.session_state["trip_id"] = new.id
                st.rerun()
            except ValidationError as exc:
                st.error(str(exc))

if not trips:
    st.info("Create a trip in the sidebar to get started.")
    st.stop()

ids = [t.id for t in trips]
if st.session_state.get("trip_id") not in ids:
    st.session_state["trip_id"] = ids[0]
trip_id = st.sidebar.selectbox(
    "Trip",
    ids,
    index=ids.index(st.session_state["trip_id"]),
    format_func=lambda i: next(f"{t.name} ({t.destination})" for t in trips if t.id == i),
)
st.session_state["trip_id"] = trip_id
trip = store.get_trip(trip_id)
activities = store.list_activities(trip_id)
expenses = store.list_expenses(trip_id)
budget = store.get_budget(trip_id)
packing = store.list_packing(trip_id)

# ---------------------------------------------------------------- header
st.title(trip.name)
days_out = reports.countdown_days(trip, date.today())
st.caption(
    f"📍 {trip.destination} · 🗓️ {trip.start_date:%a %b %d} to {trip.end_date:%a %b %d, %Y}"
    f" · 👥 {', '.join(trip.travelers)}"
)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Days", trip.num_days)
c2.metric("Travelers", len(trip.travelers))
c3.metric("Group budget", f"${sum(budget.values()):,.0f}")
c4.metric("Departs in", f"{days_out} days" if days_out > 0 else "Underway or done")

conflicts = reports.conflict_messages(activities)
if conflicts:
    st.warning(f"{len(conflicts)} schedule conflict(s). See the Itinerary tab.")

tab_it, tab_budget, tab_exp, tab_pack, tab_export, tab_settings = st.tabs(
    ["Itinerary", "Budget", "Expenses & settle-up", "Packing", "Export", "Trip settings"]
)

# ---------------------------------------------------------------- itinerary
with tab_it:
    for msg in conflicts:
        st.error(f"Conflict: {msg}")
    by_day = {}
    for a in activities:
        by_day.setdefault(a.day, []).append(a)
    for n, day in enumerate(trip.days(), 1):
        acts = sorted(by_day.get(day, []), key=lambda a: a.start)
        noun = "activity" if len(acts) == 1 else "activities"
        with st.expander(
            f"Day {n}: {day:%A, %b %d} ({len(acts)} {noun})",
            expanded=n == 1,
        ):
            if not acts:
                st.caption("Free day")
            for a in acts:
                clash = conflicts_with(a, acts)
                left, right = st.columns([6, 1])
                flag = " ⚠️" if clash else ""
                loc = f" · {a.location}" if a.location else ""
                left.markdown(f"**{a.start:%H:%M}-{a.end:%H:%M}** {a.title}{loc}{flag}")
                if right.button("Delete", key=f"del_act_{a.id}"):
                    store.delete_activity(a.id or 0)
                    st.rerun()

    st.subheader("Add activity")
    with st.form("add_activity", clear_on_submit=True):
        cols = st.columns(4)
        a_day = cols[0].selectbox(
            "Day", trip.days(), format_func=lambda d: f"{d:%a %b %d}", key="act_day"
        )
        a_start = cols[1].time_input("Start", value=time(10, 0), step=900)
        a_end = cols[2].time_input("End", value=time(12, 0), step=900)
        a_title = cols[3].text_input("Title")
        a_loc = st.text_input("Location")
        if st.form_submit_button("Add to itinerary"):
            try:
                new_act = Activity(a_day, a_start, a_end, a_title, a_loc)
                clash = conflicts_with(new_act, activities)
                store.add_activity(trip_id, new_act)
                if clash:
                    st.session_state["flash"] = "Added, but it overlaps: " + ", ".join(
                        c.title for c in clash
                    )
                st.rerun()
            except ValidationError as exc:
                st.error(str(exc))
    if flash := st.session_state.pop("flash", None):
        st.warning(flash)

    st.subheader("Draft an itinerary")
    st.caption(
        "Uses an OpenAI-compatible model when OPENAI_API_KEY is set; otherwise a built-in "
        "template drafts a balanced day plan offline."
    )
    prefs = st.text_input("Preferences (optional)", placeholder="food markets, anime, gardens")
    replace = st.checkbox("Replace the current itinerary", value=False)
    if st.button("Draft itinerary"):
        result = draft_itinerary(trip, prefs)
        if replace:
            store.clear_activities(trip_id)
        store.add_activities(trip_id, result.activities)
        label = "AI" if result.source == "ai" else "offline template"
        st.session_state["flash"] = f"Added {len(result.activities)} activities from {label}."
        st.rerun()

# ---------------------------------------------------------------- budget
with tab_budget:
    df = reports.budget_frame(trip, budget, expenses)
    total_planned = sum(budget.values())
    total_spent = sum(e.amount for e in expenses)
    m1, m2, m3 = st.columns(3)
    m1.metric("Planned", f"${total_planned:,.2f}")
    m2.metric("Spent", f"${total_spent:,.2f}")
    m3.metric("Per person target", f"${total_planned / len(trip.travelers):,.2f}")
    over = df[df["over"]]["category"].tolist()
    if over:
        st.error("Over budget: " + ", ".join(over))
    st.dataframe(
        df.rename(
            columns={
                "category": "Category",
                "planned": "Planned",
                "spent": "Spent",
                "remaining": "Remaining",
                "pct_used": "% used",
                "per_person_target": "Per person",
                "over": "Over?",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={k: MONEY for k in ("Planned", "Spent", "Remaining", "Per person")}
        | {"% used": st.column_config.NumberColumn(format="%.1f%%")},
    )
    st.bar_chart(df.set_index("category")[["planned", "spent"]], stack=False)
    st.subheader("Per person")
    st.dataframe(
        reports.per_person_frame(trip, budget, expenses).rename(
            columns={
                "traveler": "Traveler",
                "share_spent": "Fair share spent",
                "target": "Target",
                "remaining": "Remaining",
            }
        ),
        hide_index=True,
        column_config={k: MONEY for k in ("Fair share spent", "Target", "Remaining")},
    )

    with st.form("budget_form"):
        st.write("Edit category budgets (group total)")
        cols = st.columns(3)
        new_budget = {
            c: cols[i % 3].number_input(c, min_value=0.0, value=float(budget[c]), step=50.0)
            for i, c in enumerate(BUDGET_CATEGORIES)
        }
        if st.form_submit_button("Save budget"):
            store.set_budget(trip_id, new_budget)
            st.rerun()

# ---------------------------------------------------------------- expenses
with tab_exp:
    bal = budget_logic.balances(expenses, trip.travelers)
    transfers = budget_logic.settle_up(bal)
    left, right = st.columns(2)
    with left:
        st.subheader("Balances")
        for person, amount in bal.items():
            if amount > 0:
                st.write(f"🟢 **{person}** is owed ${amount:,.2f}")
            elif amount < 0:
                st.write(f"🔴 **{person}** owes ${-amount:,.2f}")
            else:
                st.write(f"⚪ **{person}** is settled")
    with right:
        st.subheader("Settle up")
        if not transfers:
            st.success("Everyone is square.")
        else:
            st.caption(f"{len(transfers)} payment(s), the fewest needed to clear all balances.")
            for frm, to, amt in transfers:
                st.write(f"**{frm}** pays **{to}** ${amt:,.2f}")

    st.subheader("Expense log")
    st.dataframe(
        reports.expense_frame(expenses).drop(columns="id"),
        hide_index=True,
        column_config={"Amount": MONEY},
    )

    with st.form("add_expense", clear_on_submit=True):
        st.write("Log an expense")
        cols = st.columns(4)
        e_desc = cols[0].text_input("Description")
        e_amt = cols[1].number_input("Amount ($)", min_value=0.0, step=1.0)
        e_payer = cols[2].selectbox("Paid by", trip.travelers)
        e_cat = cols[3].selectbox("Category", BUDGET_CATEGORIES)
        e_parts = st.multiselect("Split between", trip.travelers, default=trip.travelers)
        e_date = st.date_input("Date", value=trip.start_date)
        if st.form_submit_button("Add expense"):
            try:
                store.add_expense(
                    trip_id, Expense(e_desc, e_amt, e_payer, e_parts, e_cat, spent_on=e_date)
                )
                st.rerun()
            except ValidationError as exc:
                st.error(str(exc))

    if expenses:
        choice = st.selectbox(
            "Delete an expense",
            [e.id for e in expenses],
            format_func=lambda i: next(
                f"{e.description} (${e.amount:,.2f})" for e in expenses if e.id == i
            ),
        )
        if st.button("Delete expense"):
            store.delete_expense(choice or 0)
            st.rerun()

# ---------------------------------------------------------------- packing
with tab_pack:
    st.progress(progress(packing), text=f"{progress(packing):.0%} packed")
    for item in packing:
        who = item.assignee or "Group"
        checked = st.checkbox(f"{item.name} ({who})", value=item.packed, key=f"pack_{item.id}")
        if checked != item.packed:
            store.set_packed(item.id or 0, checked)
            st.rerun()
    with st.form("add_packing", clear_on_submit=True):
        cols = st.columns(2)
        p_name = cols[0].text_input("Item")
        p_who = cols[1].selectbox("Who brings it", ["Group", *trip.travelers])
        if st.form_submit_button("Add item"):
            try:
                assignee = "" if p_who == "Group" else p_who
                store.add_packing_items(trip_id, [PackingItem(p_name, assignee=assignee)])
                st.rerun()
            except ValidationError as exc:
                st.error(str(exc))
    if st.button(f"Add '{trip.trip_type}' template items"):
        store.add_packing_items(trip_id, template_for(trip.trip_type, trip.num_days))
        st.rerun()

# ---------------------------------------------------------------- export
with tab_export:
    slug = "".join(ch if ch.isalnum() else "-" for ch in trip.name.lower()).strip("-")
    st.download_button(
        "Download calendar (.ics)",
        to_ics(trip, activities, stamp=datetime.now()),
        file_name=f"{slug}.ics",
        mime="text/calendar",
    )
    md = to_markdown(trip, activities)
    st.download_button("Download itinerary (.md)", md, file_name=f"{slug}.md", mime="text/markdown")
    st.markdown(md)

# ---------------------------------------------------------------- settings
with tab_settings:
    with st.form("edit_trip"):
        s_name = st.text_input("Trip name", trip.name)
        s_dest = st.text_input("Destination", trip.destination)
        s_start = st.date_input("Start date", trip.start_date)
        s_end = st.date_input("End date", trip.end_date)
        s_people = st.text_area("Travelers", ", ".join(trip.travelers))
        s_type = st.selectbox("Trip type", TRIP_TYPES, index=TRIP_TYPES.index(trip.trip_type))
        if st.form_submit_button("Save changes"):
            try:
                store.update_trip(
                    Trip(s_name, s_dest, s_start, s_end, parse_names(s_people), s_type, trip_id)
                )
                st.rerun()
            except ValidationError as exc:
                st.error(str(exc))
    st.divider()
    confirm = st.checkbox("I understand this deletes the trip and everything in it")
    if st.button("Delete trip", disabled=not confirm, type="primary"):
        store.delete_trip(trip_id)
        st.session_state.pop("trip_id", None)
        st.rerun()
