"""Summarizer: shortens long anonymized material into statements that cite their evidence. Skeleton.

A locally hosted open-weight language model, given CMS terminology, compresses logbook
threads, meeting slides and data-quality information. Every summary lists what it drew on,
so an expert can audit it for faithfulness, and names the model and prompt that wrote it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from anonymizer import Anonymized

STATUS = "skeleton"
ROLE = "Shortens long anonymized material into a statement that cites its sources."
EXAMPLE = {
    "input": "Twelve anonymized logbook entries and two slides about the trip of LV-HB-02",
    "output": "Summary(text='Ageing regulator module in LV-HB-02: the output voltage sagged for about 6 hours "
              "before the trip. Module replaced.', cites=[...], parts=['LV-HB-02'], model='...', prompt='root_cause/v1')",
    "produces": "expert/root_cause",
}


@dataclass(frozen=True)
class Summary:
    text: str
    cites: list[str]                   # pointers to the records it drew on
    parts: list[str] = field(default_factory=list)   # detector parts the summary is about
    model: str = ""                    # model name and version
    prompt: str = ""                   # prompt name and version


class Summarizer(Protocol):
    def summarize(self, records: list[Anonymized], purpose: str) -> Summary:
        """``purpose`` is e.g. "root_cause", "followup", "daily_summary"; it selects the prompt."""
        raise NotImplementedError

    def which_parts(self, record: Anonymized) -> list[str]:
        """Which detector parts a free-text record is about, when the source does not say."""
        raise NotImplementedError
