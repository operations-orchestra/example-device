"""Anonymizer: removes personal identifiers before anything enters the Record. Skeleton.

Two passes (proposal Sec. 2.3). A deterministic pass replaces each author and each known name
with the person's operational role, or removes it when no role is known. A second pass, a
locally hosted open-weight language model, finds names, initials and e-mail addresses the
first pass missed. No key from name to role is kept, so the result cannot be reversed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from adapters.base import RawRecord

STATUS = "skeleton"
ROLE = "Replaces names with operational roles, in two passes, keeping no key."
EXAMPLE = {
    "input": "RawRecord(author='Jane Doe', text='Called Jane D. about the hot towers around HBP02.')",
    "output": "Anonymized(author_role='DQM shifter', text='Called [HCAL DOC] about the hot towers around HBP02.', "
              "replaced=1, removed=0, found_by_model=1)",
    "produces": "elog/shift_note",
}


@dataclass(frozen=True)
class Anonymized:
    """A raw record with every personal identifier replaced or removed."""

    record: RawRecord                  # author set to None, text rewritten
    author_role: Optional[str]         # e.g. "HCAL DOC"; None when no role is known
    replaced: int                      # identifiers replaced by a role
    removed: int                       # identifiers removed, no role known
    found_by_model: int                # of those, how many only the second pass found


class RoleDirectory(Protocol):
    """Pass 1: who held which operational role at a given time (shift schedules, on-call lists)."""

    def role_of(self, name: str, t: int) -> Optional[str]:
        raise NotImplementedError


class Anonymizer(Protocol):
    def anonymize(self, record: RawRecord) -> Anonymized:
        """Both passes. Must run where the raw records are, before anything leaves that machine."""
        raise NotImplementedError

    def audit(self, sample: list[RawRecord], marked: list[list[str]]) -> float:
        """Recall on a sample in which experts marked every name: the fraction removed."""
        raise NotImplementedError
