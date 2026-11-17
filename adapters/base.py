"""What every source adapter does. Skeleton: only the control-system archive adapter exists.

An adapter is the only code that talks to an existing system. It reads, never writes, and
hands the rest of the feed records in one shape (``RawRecord``). Turning a raw record into
Record entries happens after anonymization, so an adapter never decides what the Record says.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Protocol

STATUS = "skeleton"
ROLE = "Reads one existing system, read-only, and returns its records in one shape."
EXAMPLE = {
    "input": "The logbook entry 4711 in the HCAL logbook: author Jane Doe, 2040-03-01 04:08, "
             "'HB occupancy shows a few hot towers around HBP02. Not stopping the run.', one plot attached",
    "output": "RawRecord(source='elog', native_id='4711', t_event=..., t_recorded=..., "
              "author='Jane Doe', text='HB occupancy shows ...', parts=['HBP02'], attachments=['plot.png'])",
    "produces": None,
}


@dataclass(frozen=True)
class RawRecord:
    """One record as the source gives it. May contain personal names: never stored as is."""

    source: str                          # e.g. "elog", "certification", "downtime", "runcontrol"
    native_id: str                       # the source's own identifier; becomes the pointer
    t_event: int                         # when it happened
    t_recorded: int                      # when the source recorded it (becomes known_at)
    fields: dict[str, Any] = field(default_factory=dict)
    text: str = ""                       # free text, if any
    author: Optional[str] = None         # a person; removed by the anonymizer
    parts: list[str] = field(default_factory=list)       # detector parts the source names explicitly
    attachments: list[str] = field(default_factory=list)  # e.g. plots attached to a logbook entry


class SourceAdapter(Protocol):
    """The contract. One implementation per existing system."""

    source: str

    def fetch(self, t0: int, t1: int, as_of: int) -> Iterator[RawRecord]:
        """Records whose event time overlaps [t0, t1] and that the source held by ``as_of``."""
        raise NotImplementedError

    def pointer(self, record: RawRecord) -> str:
        """A stable reference back into the source, stored on the entry instead of a copy."""
        raise NotImplementedError


class ElogAdapter:
    """Electronic logbook: shift and expert notes, with attachments (where incident plots live)."""

    source = "elog"

    def fetch(self, t0: int, t1: int, as_of: int) -> Iterator[RawRecord]:
        raise NotImplementedError

    def pointer(self, record: RawRecord) -> str:
        raise NotImplementedError


class CertificationAdapter:
    """Data certification: good or bad per subsystem and lumisection range, with the cause typed."""

    source = "certification"

    def fetch(self, t0: int, t1: int, as_of: int) -> Iterator[RawRecord]:
        raise NotImplementedError

    def pointer(self, record: RawRecord) -> str:
        raise NotImplementedError


class DowntimeAdapter:
    """The downtime database: interval, lost luminosity, category, short description."""

    source = "downtime"

    def fetch(self, t0: int, t1: int, as_of: int) -> Iterator[RawRecord]:
        raise NotImplementedError

    def pointer(self, record: RawRecord) -> str:
        raise NotImplementedError


class RunControlAdapter:
    """Run control: runs, configure attempts and their results, configuration changes."""

    source = "runcontrol"

    def fetch(self, t0: int, t1: int, as_of: int) -> Iterator[RawRecord]:
        raise NotImplementedError

    def pointer(self, record: RawRecord) -> str:
        raise NotImplementedError


class DataQualityAdapter:
    """Data-quality monitoring: histograms per run, as pointers; the plots relevant to an incident."""

    source = "dqm"

    def fetch(self, t0: int, t1: int, as_of: int) -> Iterator[RawRecord]:
        raise NotImplementedError

    def pointer(self, record: RawRecord) -> str:
        raise NotImplementedError
