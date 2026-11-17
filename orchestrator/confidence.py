"""How sure the agent is that an earlier incident is a precedent of the current problem.

Two sources, both shown:
1. Learned: for each match signature (shares a part, same kind of symptom, or both), the share
   of past precedent reviews known at the moment that confirmed it, smoothed by a prior that
   experts set (a Beta distribution: "as if" a confirmed and b rejected reviews had been seen).
2. Evidence now: each check that finds what the earlier incident's experts relied on multiplies
   the odds by a fixed factor.
The verdict follows from the best candidate, with thresholds that are settings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aggregator import RecordStore

from .recall import incident_parts, incident_symptoms, kinds_of, signature


@dataclass(frozen=True)
class Settings:
    priors: dict = field(default_factory=lambda: {"both": (3.0, 1.0), "symptom": (1.0, 2.0), "part": (1.0, 3.0)})
    evidence_factor: float = 3.0          # odds multiplier per matching piece of evidence
    known_at_least: float = 0.7
    new_below: float = 0.3

    def describe(self) -> dict:
        return {"priors": {k: {"confirmed": a, "rejected": b} for k, (a, b) in self.priors.items()},
                "evidence_factor": self.evidence_factor, "known_at_least": self.known_at_least,
                "new_below": self.new_below}


def learned_counts(store: RecordStore, as_of: int) -> dict[str, dict[str, int]]:
    """Confirmed and rejected reviews per signature, from the reviews known by ``as_of``."""
    counts = {sig: {"confirmed": 0, "rejected": 0} for sig in ("both", "symptom", "part")}
    for r in store.precedent_reviews(as_of):
        a, b = r["incident_id"], r["earlier_id"]
        sig = signature(bool(incident_parts(store, a, as_of) & incident_parts(store, b, as_of)),
                        bool(kinds_of(incident_symptoms(store, a, as_of)) & kinds_of(incident_symptoms(store, b, as_of))))
        if sig:
            counts[sig][r["status"]] += 1
    return counts


def score(sig: str, counts: dict, matches: int, settings: Settings) -> dict:
    """The confidence for one candidate, with every step of how it was reached."""
    a, b = settings.priors[sig]
    c, r = counts[sig]["confirmed"], counts[sig]["rejected"]
    start = (a + c) / (a + b + c + r)
    odds = start / (1 - start) * settings.evidence_factor ** matches
    final = odds / (1 + odds)
    steps = [f"prior for '{sig}': as if {a:g} confirmed and {b:g} rejected",
             f"reviews known now for '{sig}': {c} confirmed, {r} rejected",
             f"starting confidence ({a:g}+{c}) / ({a:g}+{b:g}+{c}+{r}) = {start:.2f}"]
    if matches:
        steps.append(f"{matches} piece(s) of evidence found again: odds x{settings.evidence_factor:g} each, giving {final:.2f}")
    return {"start": round(start, 3), "confidence": round(final, 3), "matches": matches, "steps": steps}


def verdict(confidence: float, settings: Settings) -> str:
    if confidence >= settings.known_at_least:
        return "known"
    return "uncertain" if confidence >= settings.new_below else "new"
