"""The diagnosis agent: a fixed-shape proposal, checked before anyone sees it. Skeleton.

The agent proposes; a person decides. Two interchangeable brains: a scripted one (no model,
same answer every time, used by tests) and a model one (any endpoint speaking the
OpenAI-compatible tool-calling protocol). When unsure it says "new": a false "known"
misleads the crew.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from orchestrator.tools import Tools

STATUS = "skeleton"
ROLE = "Answers a crew's question with a structured proposal whose every citation was retrieved."
EXAMPLE = {
    "input": "'HCAL fails to configure and three automatic recoveries have failed. What should we do?' "
             "as of 2040-03-02 12:06",
    "output": "Proposal(element='HFP02', verdict='known', next_step='recovery_procedure', "
              "diagnosis='Same as #3: control module lost its link after the LV power cycle', "
              "supporting=[(28, query 17), (2556, query 19)], relied_on='recovery_action')",
    "produces": None,
}


@dataclass(frozen=True)
class Citation:
    entry_id: int
    query_id: int                      # the logged tool call that returned the entry


@dataclass(frozen=True)
class Proposal:
    element: str
    verdict: Literal["known", "new", "uncertain"]
    diagnosis: str
    next_step: Literal["check", "recovery_procedure", "escalate"]
    relied_on: Literal["certification", "recovery_action", "confirmed_cause", "none"]
    supporting: list[Citation] = field(default_factory=list)
    conflicting: list[Citation] = field(default_factory=list)


class Brain(Protocol):
    def propose(self, question: str, as_of: int, tools: Tools) -> Proposal:
        raise NotImplementedError


def diagnose(question: str, as_of: int, brain: Brain, tools: Tools) -> Proposal:
    """Ask the brain, then reject any proposal citing an entry no logged tool call returned."""
    raise NotImplementedError


def check(proposal: Proposal, session_queries: dict[int, set[int]]) -> list[str]:
    """Problems with a proposal: unsupported citations, a verdict without precedents, ..."""
    raise NotImplementedError
