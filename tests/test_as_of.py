"""Layer 3 (store level): reads never return what the Record did not yet know."""
import random


def test_entries_never_come_from_the_future(store, end):
    t0, t1 = store.time_span()
    rng = random.Random(7)
    for _ in range(40):
        as_of = rng.randrange(t0, end)
        got = store.entries(as_of)
        assert all(e.known_at <= as_of for e in got)
        assert len(got) == sum(1 for e in store.entries(end) if e.known_at <= as_of)


def test_incident_views_hide_later_knowledge(tiny, store, end):
    for case in tiny["planted_cases"]:
        if case["incident_id"] is None:
            continue
        # Five minutes after the event, the incident for that very event is not in the Record yet.
        assert store.incident(case["incident_id"], as_of=case["ask_at"]) is None
        final = store.incident(case["incident_id"], end)
        opened = final.known_at
        early = store.incident(case["incident_id"], as_of=opened)
        assert early.confirmed_cause is None and early.certification is None
        for role, entry in store.incident_entries(case["incident_id"], as_of=opened):
            assert entry.known_at <= opened and role not in ("cause", "evidence", "certification")


def test_links_are_hidden_until_known(tiny, store, end):
    case = next(c for c in tiny["planted_cases"] if c["mode"] == "configure_failure")
    evidence = [e for role, e in store.incident_entries(case["incident_id"], end) if role == "evidence"]
    assert evidence
    for e in evidence:
        assert store.links(e.id, end)
        assert store.links(e.id, as_of=case["ask_at"]) == []


def test_state_lookback_finds_a_change_made_hours_earlier(tiny, store):
    """The control link was lost when the low voltage came back, long before configure failed."""
    case = next(c for c in tiny["planted_cases"] if c["mode"] == "configure_failure")
    state = store.state_at(case["true_element"], "control_link", case["t_event"], as_of=case["ask_at"])
    assert state.payload["value"] == "lost"
    assert case["t_event"] - state.t_start >= 2 * 3600
    # and a healthy box says ok
    other = next(b for b in store.elements("readout_box") if b != case["true_element"])
    assert store.state_at(other, "control_link", case["t_event"], case["ask_at"]).payload["value"] == "ok"


def test_state_before_any_entry_is_none(store):
    t0, _ = store.time_span()
    assert store.state_at("HCAL", "control_link", t0 - 10, as_of=t0 - 10) is None
