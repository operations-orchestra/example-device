"""The agent's tools: typed, read-only, and the only way it touches the Record.

No raw SQL. Every call goes into a query log and returns the log id, so a proposal can cite
exactly the call that produced each piece of evidence, and anyone can re-run it. All calls in
a session are made "as of" the moment the question was asked; nothing later is visible.

The log is kept in memory for the session. Writing it to the Record's ``query_log`` table
needs a Record opened for writing, which the read-only GUI does not have.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from aggregator import IncidentView, RecordStore, StoredEntry

from .recall import candidates

STATUS = "built"
ROLE = "Six read-only questions the agent may ask the Record and the source archive, each logged and re-runnable."
EXAMPLE = {
    "input": "state('HFP03', t=Mar 12 15:08) as of Mar 12 15:13",
    "output": "ToolResult(query_id=3, entries=[control_link = lost since Mar 12 09:25, LV normal, ...])",
    "produces": "dcs/control_link",
}
NORMAL = {"ok", "on", "normal"}


@dataclass(frozen=True)
class ToolResult:
    query_id: int                      # row in the query log; cite it
    entries: list[StoredEntry] = field(default_factory=list)
    incidents: list[IncidentView] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Call:
    id: int
    tool: str
    args: dict[str, Any]
    as_of: int
    entry_ids: list[int]
    incident_ids: list[int]
    summary: str


class QueryLog:
    """Every tool call of one session, in order."""

    def __init__(self) -> None:
        self.calls: list[Call] = []

    def add(self, tool: str, args: dict, as_of: int, entries: list[StoredEntry],
            incidents: list[IncidentView], summary: str) -> int:
        call = Call(len(self.calls) + 1, tool, args, as_of, [e.id for e in entries], [i.id for i in incidents], summary)
        self.calls.append(call)
        return call.id

    def returned(self, query_id: int) -> set[int]:
        """The entries a logged call returned (empty if there is no such call)."""
        return set(self.calls[query_id - 1].entry_ids) if 0 < query_id <= len(self.calls) else set()

    def as_dicts(self) -> list[dict]:
        return [asdict(c) for c in self.calls]


class RecordTools:
    """The six tools, bound to one Record, one moment and one query log."""

    def __init__(self, store: RecordStore, as_of: int, archive=None, log: Optional[QueryLog] = None):
        self.store, self.as_of, self.archive = store, as_of, archive
        self.log = log or QueryLog()

    def _t(self, t: Optional[int]) -> int:
        if t is not None and t > self.as_of:
            raise ValueError("a tool cannot ask about a time after the moment of the question")
        return self.as_of if t is None else t

    def _around(self, part: str) -> list[str]:
        """A part, its children (a box's channels), the parts it is connected to (supply, FED,
        boxes served), and its parent."""
        near = {part, *self.store.children(part), *(n for _, n in self.store.related(part))}
        parent = self.store.parent(part)
        if parent and self.store.element_kind(parent) not in ("experiment", "detector"):
            near.add(parent)
        return sorted(near)

    # -- the tools --------------------------------------------------------------------------
    def search_incidents(self, kinds: list[str], parts: list[str], before: int) -> ToolResult:
        """Earlier incidents and open issues that share a part or a kind of symptom: always the
        whole Record, never a window."""
        found = candidates(self.store, set(kinds), set(parts), before, self.as_of)
        incs = [c["incident"] for c in found]
        qid = self.log.add("search_incidents", {"kinds": kinds, "parts": parts, "before": before}, self.as_of, [], incs,
                           f"{len(found)} earlier incident(s) share a part or a kind of symptom")
        return ToolResult(qid, incidents=incs, data={"candidates": [
            {"id": c["incident"].id, "signature": c["signature"], "shared_parts": c["shared_parts"],
             "shared_kinds": c["shared_kinds"]} for c in found]})

    def get_incident(self, incident_id: int) -> ToolResult:
        """One incident with its labels, entries (with roles) and parts, as known now."""
        view = self.store.incident(incident_id, self.as_of)
        rows = self.store.incident_entries(incident_id, self.as_of) if view else []
        parts = [asdict(r) for r in self.store.parts(self.as_of, incident_id=incident_id)] if view else []
        qid = self.log.add("get_incident", {"incident_id": incident_id}, self.as_of, [e for _, e in rows],
                           [view] if view else [], f"incident #{incident_id}" + ("" if view else " not known"))
        return ToolResult(qid, entries=[e for _, e in rows], incidents=[view] if view else [],
                          data={"roles": {e.id: r for r, e in rows}, "parts": parts})

    def state(self, part: str, t: Optional[int] = None) -> ToolResult:
        """Every state of a part at t, looking back to the last change however old."""
        t = self._t(t)
        found = [s for s in (self.store.state_at(part, typ, t, self.as_of)
                             for typ in self.store.state_types(part, self.as_of)) if s]
        odd = [f"{s.type} = {s.payload.get('value')}" for s in found if s.payload.get("value") not in NORMAL]
        qid = self.log.add("state", {"part": part, "t": t}, self.as_of, found, [],
                           f"{part}: " + (", ".join(odd) if odd else "all normal"))
        return ToolResult(qid, entries=found)

    def events(self, t0: int, t1: int, part: str) -> ToolResult:
        """Entries in a time window that concern a part or the parts connected to it."""
        t1 = self._t(t1)
        found = self.store.entries(self.as_of, t0=t0, t1=t1, parts=self._around(part))
        qid = self.log.add("events", {"t0": t0, "t1": t1, "part": part}, self.as_of, found, [],
                           f"{len(found)} entries around {part}")
        return ToolResult(qid, entries=found)

    def co_occurring(self, entry_id: int, window_s: int) -> ToolResult:
        """What else happened within a window before an entry, on the parts it concerns and their neighbours."""
        e = self.store.get_entry(entry_id, self.as_of)
        if e is None:
            qid = self.log.add("co_occurring", {"entry_id": entry_id, "window_s": window_s}, self.as_of, [], [], "no such entry")
            return ToolResult(qid)
        near = sorted({n for r in self.store.parts(self.as_of, entry_id=entry_id) for n in self._around(r.element)})
        found = [x for x in self.store.entries(self.as_of, t0=e.t_start - window_s, t1=e.t_start, parts=near) if x.id != entry_id]
        qid = self.log.add("co_occurring", {"entry_id": entry_id, "window_s": window_s}, self.as_of, found, [],
                           f"{len(found)} entries in the {window_s // 3600} h before entry {entry_id}")
        return ToolResult(qid, entries=found)

    def series(self, part: str, quantity: str, t0: int, t1: Optional[int] = None) -> ToolResult:
        """A reading's series from the source archive (not the Record), as of the moment."""
        t1 = self._t(t1)
        pts = self.archive.fetch(part, quantity, t0, t1, self.as_of, max_points=60) if self.archive else []
        summary = (f"{part} {quantity}: {pts[0]['v']:.3f} -> {pts[-1]['v']:.3f}, lowest {min(p['v'] for p in pts):.3f}"
                   if pts else f"{part} {quantity}: no samples")
        qid = self.log.add("series", {"part": part, "quantity": quantity, "t0": t0, "t1": t1}, self.as_of, [], [], summary)
        return ToolResult(qid, data={"points": pts})


# The same six tools, described for a language model (OpenAI-compatible tool calling).
TOOL_SPECS = [
    {"type": "function", "function": {"name": "search_incidents", "description": RecordTools.search_incidents.__doc__.strip(),
     "parameters": {"type": "object", "properties": {"kinds": {"type": "array", "items": {"type": "string"}},
                    "parts": {"type": "array", "items": {"type": "string"}}, "before": {"type": "integer"}},
                    "required": ["kinds", "parts", "before"]}}},
    {"type": "function", "function": {"name": "get_incident", "description": RecordTools.get_incident.__doc__.strip(),
     "parameters": {"type": "object", "properties": {"incident_id": {"type": "integer"}}, "required": ["incident_id"]}}},
    {"type": "function", "function": {"name": "state", "description": RecordTools.state.__doc__.strip(),
     "parameters": {"type": "object", "properties": {"part": {"type": "string"}, "t": {"type": "integer"}}, "required": ["part"]}}},
    {"type": "function", "function": {"name": "events", "description": RecordTools.events.__doc__.strip(),
     "parameters": {"type": "object", "properties": {"t0": {"type": "integer"}, "t1": {"type": "integer"}, "part": {"type": "string"}},
                    "required": ["t0", "t1", "part"]}}},
    {"type": "function", "function": {"name": "co_occurring", "description": RecordTools.co_occurring.__doc__.strip(),
     "parameters": {"type": "object", "properties": {"entry_id": {"type": "integer"}, "window_s": {"type": "integer"}},
                    "required": ["entry_id", "window_s"]}}},
    {"type": "function", "function": {"name": "series", "description": RecordTools.series.__doc__.strip(),
     "parameters": {"type": "object", "properties": {"part": {"type": "string"}, "quantity": {"type": "string", "enum": ["lv_voltage", "temperature"]},
                    "t0": {"type": "integer"}, "t1": {"type": "integer"}}, "required": ["part", "quantity", "t0"]}}},
]
