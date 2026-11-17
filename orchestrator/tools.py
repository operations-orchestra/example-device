"""The agent's tools: typed, read-only, and the only way it touches the Record. Skeleton.

No raw SQL. Each call is written to the Record's query log and returns its log id, so a
proposal can cite exactly the query that produced each piece of evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from aggregator import IncidentView, StoredEntry

STATUS = "skeleton"
ROLE = "Five read-only questions the agent may ask the Record, each logged and re-runnable."
EXAMPLE = {
    "input": "state('HFP02', t=2040-03-02 12:01, as_of=2040-03-02 12:06)",
    "output": "ToolResult(query_id=17, entries=[control_link = lost, since 2040-03-02 09:25])",
    "produces": "dcs/control_link",
}


@dataclass(frozen=True)
class ToolResult:
    query_id: int                      # row in the query log; cite it
    entries: list[StoredEntry] = field(default_factory=list)
    incidents: list[IncidentView] = field(default_factory=list)


class Tools(Protocol):
    def state(self, element: str, t: int, as_of: int) -> ToolResult:
        """Every state of the element at t, looking back to the last change however old."""
        raise NotImplementedError

    def events(self, t0: int, t1: int, scope: str, as_of: int) -> ToolResult:
        """Entries in a time window on a part and the parts around it."""
        raise NotImplementedError

    def co_occurring(self, entry_id: int, window_s: int, as_of: int) -> ToolResult:
        """What else happened near an entry, in time and on connected parts."""
        raise NotImplementedError

    def search_incidents(self, text: str, element: Optional[str], as_of: int) -> ToolResult:
        """Earlier incidents and open issues: always the whole Record, never a window."""
        raise NotImplementedError

    def get_incident(self, incident_id: int, as_of: int) -> ToolResult:
        """One incident with its labels and entries."""
        raise NotImplementedError
