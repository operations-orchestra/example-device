"""Direct links, built by the aggregator from shared identifiers and times. Skeleton.

Today the producers write their own links (the generator links each downtime row to the run
it stopped). In the design the aggregator builds direct links itself, so every producer gets
them the same way. Indirect links (expert reasoning) are not built here.
"""
from __future__ import annotations

from typing import Protocol

from .store import RecordStore

STATUS = "skeleton"
ROLE = "Links entries about the same part at the same time; context, not cause."
EXAMPLE = {
    "input": "a new downtime entry on HB, 2040-03-01 06:27 to 07:08",
    "output": "link(downtime -> run_stop of run 900003, relation='stopped_run', type='direct', status='confirmed')",
    "produces": "downtime/downtime",
}


class LinkRule(Protocol):
    """One kind of direct link, e.g. a downtime interval contains a run stop."""

    relation: str

    def candidates(self, store: RecordStore, entry_id: int, as_of: int) -> list[int]:
        raise NotImplementedError


def build_direct_links(store: RecordStore, entry_ids: list[int], rules: list[LinkRule]) -> int:
    """Apply every rule to newly written entries; returns how many links were written."""
    raise NotImplementedError
