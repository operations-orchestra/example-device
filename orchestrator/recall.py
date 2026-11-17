"""Recalling earlier incidents: what kind of symptom a problem shows, and which earlier
incidents share a part or a kind of symptom with it. Computed only from the Record."""
from __future__ import annotations

from typing import Optional

from aggregator import RecordStore, StoredEntry

GENERIC = {"shift_note"}            # every incident has logbook notes; they do not characterise a symptom
QUALIFIERS = ("result", "value", "flag", "state")
ACTIVE_ROLES = ("reported", "affected", "suspected", "cause")


def symptom_kind(entry: StoredEntry) -> Optional[str]:
    """A short label for what kind of symptom an entry is, e.g. 'configure:failed'."""
    if entry.type in GENERIC:
        return None
    for key in QUALIFIERS:
        if key in entry.payload:
            return f"{entry.type}:{entry.payload[key]}"
    return entry.type


def kinds_of(entries: list[StoredEntry]) -> set[str]:
    return {k for k in map(symptom_kind, entries) if k}


def incident_symptoms(store: RecordStore, incident_id: int, as_of: int) -> list[StoredEntry]:
    return [e for role, e in store.incident_entries(incident_id, as_of) if role == "symptom"]


def incident_parts(store: RecordStore, incident_id: int, as_of: int) -> set[str]:
    return {r.element for r in store.parts(as_of, incident_id=incident_id)
            if r.status != "rejected" and r.role in ACTIVE_ROLES}


def signature(shares_part: bool, same_symptom: bool) -> Optional[str]:
    """How a candidate matches: 'both', 'symptom', 'part', or None (not a candidate)."""
    if shares_part and same_symptom:
        return "both"
    return "symptom" if same_symptom else "part" if shares_part else None


def candidates(store: RecordStore, kinds: set[str], parts: set[str], before: int, as_of: int,
               exclude: Optional[int] = None) -> list[dict]:
    """Earlier incidents (started before ``before``) that share a part or a kind of symptom,
    as the Record knew them at ``as_of``."""
    out = []
    for inc in store.incidents(as_of):
        if inc.id == exclude or inc.t_start >= before:
            continue
        their_kinds = kinds_of(incident_symptoms(store, inc.id, as_of))
        their_parts = incident_parts(store, inc.id, as_of) or {inc.element}
        sig = signature(bool(their_parts & parts), bool(their_kinds & kinds))
        if sig:
            out.append({"incident": inc, "signature": sig, "shared_parts": sorted(their_parts & parts),
                        "shared_kinds": sorted(their_kinds & kinds)})
    return out
