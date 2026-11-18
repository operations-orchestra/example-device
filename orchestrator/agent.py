"""The diagnosis agent: a fixed-shape proposal, checked before anyone sees it.

The agent proposes; a person decides. Two interchangeable brains: a scripted one (a fixed
procedure, no model, same answer every time, used by tests) and a model one (any endpoint
speaking the OpenAI-compatible tool-calling protocol). When unsure it says "new": a false
"known" misleads the crew.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional, Protocol

from aggregator import RecordStore

from .confidence import Settings, learned_counts, score, verdict
from .recall import kinds_of
from .tools import NORMAL, TOOL_SPECS, QueryLog, RecordTools

STATUS = "built"
ROLE = "Answers a crew's question with a structured proposal whose every citation was retrieved."
EXAMPLE = {
    "input": "Trigger(question='HCAL fails to configure ... What should we do?', as_of=Mar 12 15:13, "
             "symptoms=[configure failed x4, shift-leader note])",
    "output": "Proposal(verdict='known', confidence=0.90, element='HFP03', next_step='recovery_procedure', "
              "diagnosis='Same as #9: ...', supporting=[Citation(entry, query, why), ...])",
    "produces": None,
}


@dataclass(frozen=True)
class Trigger:
    """What starts the agent: the crew's question, the moment, and the symptoms they see.
    Shaped like a future automatic trigger, which would carry the same fields."""

    question: str
    as_of: int
    symptom_ids: list[int]
    part: str                          # where the crew sees the problem
    t_start: int                       # when the problem started


@dataclass(frozen=True)
class Citation:
    entry_id: int
    query_id: int                      # the logged tool call that returned the entry
    why: str = ""


@dataclass
class Proposal:
    element: str
    verdict: Literal["known", "new", "uncertain"]
    diagnosis: str
    next_step: Literal["check", "recovery_procedure", "escalate"]
    relied_on: Literal["certification", "recovery_action", "confirmed_cause", "none"]
    confidence: float = 0.0
    precedent: Optional[int] = None
    supporting: list[Citation] = field(default_factory=list)
    conflicting: list[Citation] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)   # every candidate with how its confidence was reached
    notes: list[str] = field(default_factory=list)
    brain: str = ""
    brain_label: str = ""              # e.g. the profile and model of an LLM brain


class Brain(Protocol):
    name: str

    def propose(self, trigger: Trigger, tools: RecordTools, settings: Settings) -> Proposal:
        raise NotImplementedError


# ----------------------------------------------------------------------------- scripted brain
class ScriptedBrain:
    """A fixed procedure: look at the symptoms, recall earlier incidents, open each, check now
    whether what their experts relied on is there again, score, and fill in the proposal."""

    name = "scripted"

    def propose(self, trigger: Trigger, tools: RecordTools, settings: Settings) -> Proposal:
        store, now = tools.store, trigger.as_of
        cites: list[Citation] = []
        notes: list[str] = []

        # 1. the symptoms, through a logged call so they can be cited
        first = min((store.get_entry(i, now) for i in trigger.symptom_ids), key=lambda e: e.t_start)
        seen = tools.events(first.t_start - 600, now, trigger.part)
        symptoms = [e for e in seen.entries if e.id in trigger.symptom_ids]
        cites += [Citation(e.id, seen.query_id, "symptom") for e in symptoms]
        kinds = sorted(kinds_of(symptoms))
        parts = sorted({trigger.part} | {e.element for e in symptoms})

        # 2. recall earlier incidents
        found = tools.search_incidents(kinds, parts, trigger.t_start)
        counts = learned_counts(store, now)
        scored = []
        for cand in sorted(found.data["candidates"], key=lambda c: ("both", "symptom", "part").index(c["signature"]))[:4]:
            # 3. open it, and check now what its experts relied on
            inc = tools.get_incident(cand["id"])
            view = inc.incidents[0]
            suspects = sorted({p["element"] for p in inc.data["parts"] if p["role"] in ("suspected", "cause")})
            # what its experts blamed can only be checked again when the match involves the same parts;
            # a same-symptom match on other parts says nothing about those parts now
            to_check = suspects if cand["signature"] != "symptom" else []
            matched, match_cites, missing = 0, [], []
            for part in to_check:
                st = tools.state(part, now)
                odd = [s for s in st.entries if s.payload.get("value") not in NORMAL]
                if odd:
                    matched += 1
                    match_cites += [Citation(s.id, st.query_id, f"{part} is {s.payload.get('value')} again, as in #{view.id}") for s in odd]
                else:
                    missing.append(part)
            recovery = [e for e in inc.entries if inc.data["roles"].get(e.id) == "action"]
            s = score(cand["signature"], counts, matched, settings)
            scored.append({"id": view.id, "title": view.title, "signature": cand["signature"],
                           "shared_parts": cand["shared_parts"], "shared_kinds": cand["shared_kinds"],
                           "recovery_action": view.recovery_action, "confirmed_cause": view.confirmed_cause,
                           "status": view.status, "suspects": suspects if to_check else [], "missing": missing, **s,
                           "_cites": match_cites, "_recovery": [Citation(e.id, inc.query_id, f"what was done in #{view.id}") for e in recovery]})

        # 4. context: what else happened shortly before the first symptom
        near = tools.co_occurring(first.id, 12 * 3600)
        changes = [e for e in near.entries if e.kind == "state" and e.payload.get("value") not in NORMAL][-3:]
        cites += [Citation(e.id, near.query_id, "shortly before the first symptom") for e in changes]

        best = max(scored, key=lambda c: c["confidence"], default=None)
        if best is None:
            v, conf = "new", 0.0
        else:
            v, conf = verdict(best["confidence"], settings), best["confidence"]

        # 5. a reading, from the source, when a supply is involved
        supplies = [p for p in (best["suspects"] if best else []) + parts if store.has_element(p) and store.element_kind(p) == "lv_supply"]
        if supplies:
            box = next((n for rel, n in store.related(supplies[0]) if rel == "powered_by_of"), None)
            if box:
                ser = tools.series(box, "lv_voltage", now - 6 * 3600, now)
                if ser.data["points"]:
                    notes.append(f"Fetched from the source: {tools.log.calls[ser.query_id - 1].summary} (query {ser.query_id})")

        if best:
            cites += best["_cites"]
        # the part at fault: one found in the same abnormal state as before; otherwise where the crew sees it
        element = next((c.why.split(" ")[0] for c in (best["_cites"] if best else [])), trigger.part)
        if v == "known" and best["recovery_action"]:
            step, relied = "recovery_procedure", "recovery_action"
            cites += best["_recovery"]
            diag = (f"Seen before as #{best['id']} ({best['title']}); confidence {conf:.2f}. What restored running then: "
                    f"{best['recovery_action']}." + (f" Cause then: {best['confirmed_cause']}" if best["confirmed_cause"] else " No cause was confirmed then."))
        elif v in ("known", "uncertain") and best:
            step, relied = "check", ("confirmed_cause" if best["confirmed_cause"] else "recovery_action" if best["recovery_action"] else "none")
            cites += best["_recovery"]
            diag = (f"Possibly the same as #{best['id']} ({best['title']}); confidence {conf:.2f}. Check before acting"
                    + (f"; last time: {best['recovery_action']}." if best["recovery_action"] else "."))
        else:
            step, relied = "escalate", "none"
            diag = "No earlier incident matches well enough: treat as a new problem and call the expert."
        if best and best["missing"]:
            notes.append(f"Not seen again now: {', '.join(best['missing'])} look normal.")
        return Proposal(element=element, verdict=v, diagnosis=diag, next_step=step, relied_on=relied, confidence=conf,
                        precedent=best["id"] if best and v != "new" else None, supporting=cites,
                        candidates=[{k: v2 for k, v2 in c.items() if not k.startswith("_")} for c in sorted(scored, key=lambda c: -c["confidence"])],
                        notes=notes, brain=self.name)


# -------------------------------------------------------------------------------- model brain
class ModelBrain:
    """A language model with the same tools, through any OpenAI-compatible chat endpoint.

    The model calls tools until it answers with one JSON object in the Proposal's shape. Its
    citations go through the same check as the scripted brain's.
    """

    name = "model"

    def __init__(self, base_url: str, model: str, api_key: str = "", max_turns: int = 12, timeout: float = 300,
                 label: str = ""):
        self.base_url, self.model, self._key = base_url.rstrip("/"), model, api_key
        self.max_turns, self.timeout = max_turns, timeout
        self.label = label or model

    @classmethod
    def from_profile(cls, profile) -> "ModelBrain":
        """A brain for a named profile (orchestrator/llm_config.py); the key is read now."""
        return cls(profile.base_url, profile.model, profile.api_key(), label=f"{profile.name}: {profile.model}")

    def __repr__(self) -> str:                 # never show the key
        return f"ModelBrain({self.label!r} at {self.base_url})"

    def _chat(self, messages: list[dict]) -> dict:
        body = json.dumps({"model": self.model, "messages": messages, "tools": TOOL_SPECS}).encode()
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self._key}"} if self._key else {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)["choices"][0]["message"]

    def propose(self, trigger: Trigger, tools: RecordTools, settings: Settings) -> Proposal:
        system = ("You help a detector shift crew. Use the tools to look at the Record as of the moment given; you "
                  "cannot see later. Answer with one JSON object with keys element, verdict (known|new|uncertain), "
                  "diagnosis, next_step (check|recovery_procedure|escalate), relied_on "
                  "(certification|recovery_action|confirmed_cause|none), confidence (0-1), precedent (incident id or null), "
                  "supporting (list of {entry_id, query_id, why}). Cite only entries a tool returned, with that call's "
                  "query_id. When unsure, say new.")
        user = (f"{trigger.question}\nMoment: {trigger.as_of}. Problem started {trigger.t_start} on {trigger.part}. "
                f"Symptom entries: {trigger.symptom_ids}.")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        methods = {s["function"]["name"]: getattr(tools, s["function"]["name"]) for s in TOOL_SPECS}
        for _ in range(self.max_turns):
            msg = self._chat(messages)
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                proposal = self._parse(msg.get("content") or "")
                proposal.brain_label = self.label
                return proposal
            for call in calls:
                fn = call["function"]
                try:
                    res = methods[fn["name"]](**json.loads(fn.get("arguments") or "{}"))
                    out = {"query_id": res.query_id, "summary": tools.log.calls[res.query_id - 1].summary,
                           "entries": [{"id": e.id, "type": e.type, "element": e.element, "t_start": e.t_start, "payload": e.payload}
                                       for e in res.entries[:40]],
                           "incidents": [asdict(i) for i in res.incidents], "data": res.data}
                except Exception as exc:          # a bad call is reported back to the model, not raised
                    out = {"error": str(exc)}
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(out, default=str)})
        return Proposal(element=trigger.part, verdict="new", diagnosis="The model did not answer within its turn limit.",
                        next_step="escalate", relied_on="none", brain=self.name, brain_label=self.label)

    def _parse(self, text: str) -> Proposal:
        start, end = text.find("{"), text.rfind("}")
        try:
            d = json.loads(text[start:end + 1])
        except ValueError:
            return Proposal(element="", verdict="new", diagnosis="The model's answer was not the JSON asked for: "
                            + text[:300], next_step="escalate", relied_on="none", brain=self.name)
        return Proposal(element=d.get("element", ""), verdict=d.get("verdict", "new"), diagnosis=d.get("diagnosis", ""),
                        next_step=d.get("next_step", "escalate"), relied_on=d.get("relied_on", "none"),
                        confidence=float(d.get("confidence", 0)), precedent=d.get("precedent"),
                        supporting=[Citation(int(c["entry_id"]), int(c["query_id"]), c.get("why", "")) for c in d.get("supporting", [])],
                        brain=self.name)


# ---------------------------------------------------------------------------------- running
def check(proposal: Proposal, log: QueryLog) -> list[str]:
    """Problems with a proposal. Every citation must name a logged call that returned that entry."""
    problems = []
    for c in proposal.supporting + proposal.conflicting:
        if c.entry_id not in log.returned(c.query_id):
            problems.append(f"entry {c.entry_id} was not returned by query {c.query_id}: unsupported claim")
    if proposal.verdict == "known" and proposal.precedent is None:
        problems.append("'known' without a precedent")
    if proposal.verdict not in ("known", "new", "uncertain"):
        problems.append(f"unknown verdict {proposal.verdict!r}")
    return problems


def diagnose(trigger: Trigger, brain: Brain, store: RecordStore, archive=None,
             settings: Optional[Settings] = None) -> dict:
    """Run a brain on a trigger. Returns the proposal, the query log and the check's problems.
    A proposal with problems is marked rejected, never passed on as if it were sound."""
    settings = settings or Settings()
    tools = RecordTools(store, trigger.as_of, archive)
    proposal = brain.propose(trigger, tools, settings)
    problems = check(proposal, tools.log)
    return {"proposal": proposal, "log": tools.log, "problems": problems, "accepted": not problems,
            "settings": settings, "learned": learned_counts(store, trigger.as_of)}


def trigger_for(store: RecordStore, incident_id: int, as_of: int, question: str = "") -> Optional[Trigger]:
    """The trigger a crew following this problem would give at ``as_of``: the symptoms on record."""
    frame = store.incident_frame(incident_id)
    symptoms = [e for role, e in store.incident_entries_seen(incident_id, as_of) if role in (None, "symptom")]
    if frame is None or not symptoms:
        return None
    return Trigger(question=question or f"{frame['title']}. Has this been seen before, and what should we do?",
                   as_of=as_of, symptom_ids=[e.id for e in symptoms], part=frame["element"], t_start=frame["t_start"])
