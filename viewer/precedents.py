"""Two candidate rules for "has this been seen before?", computed only from the Record.

Rule A  same element:  an earlier incident on the same element.
Rule B  same symptom:  an earlier incident, on any element, whose symptom entries are of
                       the same kind as this problem's.

Neither rule uses the generator's fault mode: a real Record has no such thing. The
"symptom kind" of an incident is read from the entries people attached to it as symptoms.

This lives in the viewer for now so the two rules can be compared by eye. Once a rule is
chosen it belongs in the orchestrator's incident search.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from aggregator import RecordStore, StoredEntry

ASK_DELAY_S = 5 * 60          # the crew asks five minutes after the first symptom is on record
_GENERIC = {"shift_note"}     # every incident has logbook notes; they do not characterise a symptom
_QUALIFIERS = ("result", "value", "flag", "state")


def symptom_kind(entry: StoredEntry) -> Optional[str]:
    """A short label for what kind of symptom an entry is, e.g. 'configure:failed'."""
    if entry.type in _GENERIC:
        return None
    for key in _QUALIFIERS:
        if key in entry.payload:
            return f"{entry.type}:{entry.payload[key]}"
    return entry.type


def _symptoms(store: RecordStore, incident_id: int, as_of: int) -> list[StoredEntry]:
    return [e for role, e in store.incident_entries(incident_id, as_of) if role == "symptom"]


def ask_time(store: RecordStore, incident_id: int, as_of: int) -> Optional[int]:
    """Five minutes after the first symptom of this problem reached the Record."""
    symptoms = _symptoms(store, incident_id, as_of)
    return min(e.known_at for e in symptoms) + ASK_DELAY_S if symptoms else None


def compare(store: RecordStore, incident_id: int, as_of: int) -> dict[str, Any]:
    """For one problem, the precedents each rule finds, as the Record stood when the crew asked."""
    problem = store.incident(incident_id, as_of)
    if problem is None:
        return {"error": "this incident is not known to the Record at this time"}
    asked = min(ask_time(store, incident_id, as_of) or as_of, as_of)   # never later than the time control
    kinds = sorted({k for k in map(symptom_kind, _symptoms(store, incident_id, as_of)) if k})
    same_element, same_symptom = [], []
    for earlier in store.incidents(asked):
        if earlier.id == problem.id or earlier.t_start >= problem.t_start:
            continue
        earlier_kinds = {k for k in map(symptom_kind, _symptoms(store, earlier.id, asked)) if k}
        row = {**asdict(earlier), "symptom_kinds": sorted(earlier_kinds),
               "shared_kinds": sorted(earlier_kinds & set(kinds))}
        if earlier.element == problem.element:
            same_element.append(row)
        if row["shared_kinds"]:
            same_symptom.append(row)
    return {"problem": asdict(problem), "ask_time": asked, "symptom_kinds": kinds,
            "same_element": same_element, "same_symptom": same_symptom}


def summary(store: RecordStore, as_of: int) -> dict[str, Any]:
    """Across every incident known now: would each rule have called it 'known' when it happened?"""
    rows = []
    for inc in store.incidents(as_of):
        c = compare(store, inc.id, as_of)
        rows.append({
            "id": inc.id, "title": inc.title, "element": inc.element, "t_start": inc.t_start,
            "ask_time": c["ask_time"], "symptom_kinds": c["symptom_kinds"],
            "same_element": [r["id"] for r in c["same_element"]],
            "same_symptom": [r["id"] for r in c["same_symptom"]],
            "fix_known_same_element": any(r["recovery_action"] for r in c["same_element"]),
            "fix_known_same_symptom": any(r["recovery_action"] for r in c["same_symptom"]),
        })
    return {"incidents": rows,
            "known_by_same_element": sum(1 for r in rows if r["same_element"]),
            "known_by_same_symptom": sum(1 for r in rows if r["same_symptom"]),
            "disagree": sum(1 for r in rows if bool(r["same_element"]) != bool(r["same_symptom"]))}


def at_moment(store: RecordStore, incident_id: int, as_of: int) -> dict[str, Any]:
    """During a replay: the precedents each rule finds at this moment.

    Which entries count as this problem's symptoms is taken from the finished incident
    (the replay knows which problem it follows); only those already on record are used.
    Everything about earlier incidents is as the Record knew it at ``as_of``.
    """
    frame = store.incident_frame(incident_id)
    end = store.latest_known_at()
    seen = [e for e in _symptoms(store, incident_id, end) if e.known_at <= as_of]
    kinds = sorted({k for k in map(symptom_kind, seen) if k})
    same_element, same_symptom = [], []
    for earlier in store.incidents(as_of):
        if earlier.id == incident_id or earlier.t_start >= frame["t_start"]:
            continue
        earlier_kinds = {k for k in map(symptom_kind, _symptoms(store, earlier.id, as_of)) if k}
        row = {**asdict(earlier), "symptom_kinds": sorted(earlier_kinds),
               "shared_kinds": sorted(earlier_kinds & set(kinds))}
        if earlier.element == frame["element"]:
            same_element.append(row)
        if row["shared_kinds"]:
            same_symptom.append(row)
    return {"symptom_kinds": kinds, "same_element": same_element, "same_symptom": same_symptom}


def first_ask_time(store: RecordStore, incident_id: int) -> Optional[int]:
    """When a crew would first ask about this problem: 5 minutes after its first symptom is on record."""
    return ask_time(store, incident_id, store.latest_known_at())
