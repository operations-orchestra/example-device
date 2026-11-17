"""The GUI's data endpoints. Each is a thin call to the Record's own read methods.

Rule: every endpoint that reads Record content requires ``as_of`` and returns nothing
known later. The exceptions are named explicitly:
  * ``meta``       - which Record is loaded and its time range (needed to set the clock)
  * ``next_known`` - returns a time only, never content
  * ``demo/*``     - demo-only endpoints that read planted.json, the generator's own list

The browser does no filtering of its own.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional

from aggregator import TABLES, RecordStore, StoredEntry
from utils import to_iso
from aggregator.view import scope

from orchestrator.agent import ScriptedBrain, diagnose, trigger_for

from . import precedents as prec


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- parameters
def _int(q: dict, key: str, required: bool = False, default: Optional[int] = None) -> Optional[int]:
    if key not in q or q[key] == "":
        if required:
            raise ApiError(f"missing required parameter '{key}'")
        return default
    try:
        return int(float(q[key]))
    except ValueError:
        raise ApiError(f"parameter '{key}' must be a number") from None


def _list(q: dict, key: str) -> Optional[list[str]]:
    return [v for v in q[key].split(",") if v] if q.get(key) else None


def _as_of(q: dict) -> int:
    return _int(q, "as_of", required=True)


def _element(store: RecordStore, q: dict, key: str = "element", required: bool = True) -> Optional[str]:
    name = q.get(key)
    if not name:
        if required:
            raise ApiError(f"missing required parameter '{key}'")
        return None
    if not store.has_element(name):
        raise ApiError(f"unknown element {name!r}", 404)
    return name


_QUANTITY = {"lv_voltage_status": "LV", "temperature_status": "temperature"}


def short_text(e: StoredEntry) -> str:
    """A few words saying what an entry records, for labels on charts."""
    p, t = e.payload, e.type

    def clip(text: str, n: int = 34) -> str:
        return text if len(text) <= n else text[: n - 1].rstrip() + "…"

    if t in _QUANTITY:
        return f"{e.element} {_QUANTITY[t]} {p.get('value')}"
    return {
        "quality_status": lambda: f"{e.element} quality: {p.get('value')}",
        "quality_reference": lambda: f"{e.element} reference updated",
        "supply_state": lambda: f"{e.element} {p.get('value')}",
        "control_link": lambda: f"{e.element} link {p.get('value')}",
        "configure": lambda: f"configure {p.get('result')}",
        "downtime": lambda: f"downtime {p.get('duration_s', 0) // 60} min",
        "cert_flag": lambda: f"{e.element} certified bad",
        "channel_flag": lambda: f"{e.element.split('-')[-1]} {p.get('flag')}",
        "fed_out_of_sync": lambda: f"{e.element} out of sync",
        "data_integrity_errors": lambda: f"{e.element} integrity errors",
        "run_stop": lambda: "run stopped",
        "config_change": lambda: f"{e.element} threshold changed",
        "followup": lambda: "follow-up: " + clip(p.get("text", ""), 32),
        "root_cause": lambda: "root cause written",
        "closing_note": lambda: "closed without a cause",
        "shift_note": lambda: clip(p.get("text", "")),
        "daily_run_summary": lambda: "daily run summary",
    }.get(t, lambda: t.replace("_", " "))()


def _e(entry: StoredEntry) -> dict[str, Any]:
    return {**asdict(entry), "short": short_text(entry)}


# ----------------------------------------------------------------------------- endpoints
def meta(store: RecordStore, q: dict, ctx: dict) -> dict:
    t0, t1 = store.time_span()
    m = store.meta()
    return {"banner": m.get("banner", ""), "synthetic": m.get("synthetic") == "true",
            "preset": m.get("preset"), "seed": m.get("seed"), "schema_version": m.get("schema_version"),
            "path": str(store.path), "size_mb": round(store.path.stat().st_size / 1e6, 2),
            "t0": t0, "t1": t1, "latest_known_at": store.latest_known_at(),
            "lumisection_s": int(m.get("lumisection_s", 23)), "has_planted": ctx["planted"] is not None}


def next_known(store: RecordStore, q: dict, ctx: dict) -> dict:
    t = _int(q, "t", required=True)
    return {"t": store.next_known_at(t, forward=q.get("direction", "next") != "previous",
                                     incident_id=_int(q, "incident"))}


def overview(store: RecordStore, q: dict, ctx: dict) -> dict:
    as_of = _as_of(q)
    periods = [{"mode": b["mode"], "t0": b["t_start"], "t1": b["t_end"]} for b in store.beam_modes(as_of)]
    counts = store.counts()
    return {
        "beam": periods,
        "downtime": [_e(e) for e in store.entries(as_of, types=["downtime"])],
        "incidents": [asdict(i) for i in store.incidents(as_of)],
        "entries_by_type": store.counts_by_type(as_of),
        "tables": counts["tables"], "elements_by_kind": counts["elements_by_kind"],
        "n_entries": store.count_entries(as_of),
    }


def elements(store: RecordStore, q: dict, ctx: dict) -> dict:
    _as_of(q)
    return {"elements": [{"name": n, "kind": store.element_kind(n), "parent": store.parent(n),
                          "related": store.related(n)} for n in store.elements()]}


def entries(store: RecordStore, q: dict, ctx: dict) -> dict:
    as_of = _as_of(q)
    els = None
    name = _element(store, q, required=False)
    if name:
        els = store.subtree(name) if q.get("below") == "1" else [name]
    filters = dict(elements=els, t0=_int(q, "t0"), t1=_int(q, "t1"), types=_list(q, "type"),
                   kinds=_list(q, "kind"), record_classes=_list(q, "class"),
                   sources=_list(q, "source"), text=q.get("q") or None)
    limit = min(_int(q, "limit", default=100), 500)
    rows = store.entries(as_of, limit=limit, offset=_int(q, "offset", default=0),
                         newest_first=q.get("order") == "newest", **filters)
    return {"total": store.count_entries(as_of, **filters), "entries": [_e(e) for e in rows]}


def entry(store: RecordStore, q: dict, ctx: dict) -> dict:
    as_of = _as_of(q)
    e = store.get_entry(_int(q, "id", required=True), as_of)
    if e is None:
        raise ApiError("no such entry is known to the Record at this time", 404)
    links = []
    for link in store.links(e.id, as_of):
        other = store.get_entry(link.dst_entry_id if link.src_entry_id == e.id else link.src_entry_id, as_of)
        links.append({**asdict(link), "direction": "out" if link.src_entry_id == e.id else "in",
                      "other": _e(other)})
    return {"entry": _e(e), "links": links, "superseded_by": store.superseded_by(e.id, as_of),
            "parts": [asdict(r) for r in store.parts(as_of, entry_id=e.id)],
            "incidents": [{"id": i, "role": r, "title": store.incident(i, as_of).title}
                          for i, r in store.incidents_of_entry(e.id, as_of)],
            "element_path": [e.element] + store.ancestors(e.element)}


def incidents(store: RecordStore, q: dict, ctx: dict) -> dict:
    return {"incidents": [asdict(i) for i in store.incidents(_as_of(q))]}


def incident(store: RecordStore, q: dict, ctx: dict) -> dict:
    as_of = _as_of(q)
    iid = _int(q, "id", required=True)
    view = store.incident(iid, as_of)
    if view is None:
        raise ApiError("this incident is not known to the Record at this time", 404)
    rows = store.incident_entries(iid, as_of)
    ids = {e.id for _, e in rows}
    links = {}
    for _, e in rows:
        for link in store.links(e.id, as_of):
            if link.src_entry_id in ids and link.dst_entry_id in ids:
                links[link.id] = asdict(link)
    return {"incident": asdict(view), "entries": [{"role": r, **_e(e)} for r, e in rows],
            "links": list(links.values()), "parts": [asdict(r) for r in store.parts(as_of, incident_id=iid)]}


# Readings and per-run data quality come from the source archives through their adapters,
# never from the Record.
READINGS = [("lv_voltage", "Low voltage", "V"), ("temperature", "Temperature", "°C")]
QUANTITIES = [("worst_ls_dead_fraction", "Dead channels (worst lumisection)", "fraction"),
              ("hot_fraction", "Hot channels", "fraction"),
              ("mean_occupancy", "Occupancy", "relative")]
STATUS_TYPES = {"lv_voltage_status": "low voltage", "temperature_status": "temperature", "quality_status": "quality"}
_FAULT_EVENTS = ("fed_out_of_sync", "data_integrity_errors", "config_change")
_NOTES = ("shift_note", "followup", "root_cause", "closing_note")


def timeline(store: RecordStore, q: dict, ctx: dict) -> dict:
    """Readings and recorded events for one element and its surroundings."""
    as_of = _as_of(q)
    name = _element(store, q)
    boxes, marks = scope(store, name)
    # up to four boxes are told apart by colour; more than that are all drawn, coloured by subdetector
    shown = boxes if len(boxes) > 4 else boxes[:4]
    group_of = {b: store.parent(b) for b in shown}
    ls = int(store.meta().get("lumisection_s", 23))
    span0, span1 = store.time_span()
    t0, t1 = _int(q, "t0", default=span0), _int(q, "t1", default=span1)
    archive = ctx.get("archive")
    panels = []
    for quantity, label, unit in READINGS:
        series = [{"box": box, "group": group_of[box],
                   "points": archive.fetch(box, quantity, t0, t1, as_of, max_points=600 if len(shown) <= 4 else 300) if archive else []}
                  for box in shown]
        panels.append({"type": quantity, "key": "v", "label": label, "unit": unit, "per_run": False,
                       "from_source": True, "series": series})
    dqm = ctx.get("dqm")
    for key, label, unit in QUANTITIES:
        series = []
        for box in shown:
            rows = dqm.fetch(box, t0, t1, as_of) if dqm else []
            series.append({"box": box, "group": group_of[box],
                           "points": [{"t0": r["t_start"], "t1": r["t_end"], "v": r[key], "run": r["run"]} for r in rows]})
        panels.append({"type": key, "key": key, "label": label, "unit": unit, "per_run": True,
                       "from_source": True, "series": series})

    experiment = store.elements("experiment")[0]
    detector_level = {n for n in marks if store.element_kind(n) in ("detector", "experiment")}
    strip = {"Stable beams": [], "Downtime": [], "Not certified yet": [], "Certified bad": [], "Reading status": [],
             "Quality status": [], "State change": [], "Fault event": [], "Logbook note": []}
    for b in store.beam_modes(as_of):
        if b["mode"] == "STABLE BEAMS":
            strip["Stable beams"].append({"id": None, "t0": b["t_start"], "t1": b["t_end"], "text": "stable beams"})
    # certification: a run is "not certified yet" for a subdetector until its completion is known
    subs = [n for n in marks if store.element_kind(n) == "subdetector"]
    done = {(c["run"], c["subdetector"]) for c in store.certification(as_of, subs)}
    for r in store.runs(as_of):
        missing = [sub for sub in subs if (r["run"], sub) not in done]
        if missing:
            strip["Not certified yet"].append({"id": None, "t0": r["t_start"], "t1": r["t_end"],
                                               "text": f"run {r['run']}: not certified yet for {', '.join(missing)}"})
    t_first = store.time_span()[0]
    for e in store.entries(as_of, parts=marks):
        p = e.payload
        if e.type == "downtime":
            strip["Downtime"].append({"id": e.id, "t0": e.t_start, "t1": e.t_end,
                                      "text": f"{p['duration_s'] // 60} min: {p['details']}"})
        elif e.type == "cert_flag":
            for a, b in p["bad_ls"]:
                strip["Certified bad"].append({"id": e.id, "t0": e.t_start + (a - 1) * ls, "t1": e.t_start + b * ls,
                                               "text": f"run {p['run']} lumisections {a}-{b}: {p['cause']}"})
        elif e.type.endswith("_status"):
            continue                                   # drawn below, as intervals
        elif e.kind == "state" and e.type != "beam_mode" and e.t_start > t_first:
            strip["State change"].append({"id": e.id, "t0": e.t_start, "text": f"{e.element} {e.type} = {p.get('value')}"})
        elif e.type in _FAULT_EVENTS or (e.type == "configure" and p.get("result") == "failed"):
            strip["Fault event"].append({"id": e.id, "t0": e.t_start, "planned": bool(p.get("planned")),
                                         "text": f"{e.element} {e.type}" + (f" ({p['attempt']})" if "attempt" in p else "")})
        elif e.type in _NOTES and e.element != experiment:
            routine = e.element in detector_level and not store.incidents_of_entry(e.id, as_of)
            strip["Logbook note"].append({"id": e.id, "t0": e.t_start, "routine": routine,
                                          "text": f"{p.get('author_role', '')}: {p.get('text', '')}"})
    # status rows: one bar per stretch in which a shown box was not normal
    for box in shown:
        for stype, label in STATUS_TYPES.items():
            changes = store.entries(as_of, elements=[box], types=[stype])
            row = "Quality status" if stype == "quality_status" else "Reading status"
            for cur, nxt in zip(changes, changes[1:] + [None]):
                if cur.payload["value"] != "normal":
                    strip[row].append({
                        "id": cur.id, "t0": cur.t_start, "t1": nxt.t_start if nxt else None, "value": cur.payload["value"],
                        "text": f"{box} {label}: {cur.payload['value']} (recorded {to_iso(cur.known_at)})"})
    groups = sorted({g for g in group_of.values()})
    return {"element": name, "kind": store.element_kind(name), "boxes": shown, "n_boxes": len(boxes),
            "colour_by": "box" if len(shown) <= 4 else "subdetector", "groups": groups,
            "marks": marks, "panels": panels, "strip": [{"row": k, "items": v} for k, v in strip.items()],
            "incidents": [asdict(i) for i in store.incidents(as_of, elements=marks)],
            "t0": span0, "t1": span1, "range": [t0, t1], "archive": bool(archive)}


def tables(store: RecordStore, q: dict, ctx: dict) -> dict:
    """The Record's tables: what each holds, its columns, and a few real rows."""
    as_of = _as_of(q)
    counts = store.table_counts(as_of)
    out = [{**t, "count": counts[t["name"]], "sample": store.table_sample(t["name"], as_of)} for t in TABLES]
    known = store.incidents(as_of)
    iid = _int(q, "incident") or (known[0].id if known else None)
    walk = store.incident_rows(iid, as_of) if iid and store.incident(iid, as_of) else None
    return {"tables": out, "incident_id": iid if walk else None, "walk": walk,
            "incidents": [{"id": i.id, "title": i.title} for i in known]}


def detector_map(store: RecordStore, q: dict, ctx: dict) -> dict:
    """The device's elements and their connections, with each element's state at the time control."""
    as_of = _as_of(q)
    els = []
    for name in store.elements():
        kind = store.element_kind(name)
        states = {}
        if kind != "channel":
            for stype in store.state_types(name, as_of):
                entry_ = store.state_at(name, stype, as_of, as_of)
                if entry_ is not None:
                    states[stype] = {"value": entry_.payload.get("value"), "since": entry_.t_start, "id": entry_.id}
        els.append({"name": name, "kind": kind, "parent": store.parent(name),
                    "related": store.related(name), "states": states})
    beams = store.beam_modes(as_of)
    if beams:
        for el in els:
            if el["kind"] == "experiment":
                el["states"]["beam_mode"] = {"value": beams[-1]["mode"], "since": beams[-1]["t_start"], "id": None}
    flags = [{"element": e.element, "flag": e.payload.get("flag"), "id": e.id}
             for e in store.entries(as_of, types=["channel_flag"], t0=as_of, t1=as_of)]
    open_issues = [{**asdict(i), "parts": [{"element": r.element, "role": r.role} for r in store.parts(as_of, incident_id=i.id)]}
                   for i in store.incidents(as_of) if i.status in ("open", "mitigated") and i.t_start <= as_of]
    return {"elements": els, "flags": flags, "open_issues": open_issues}


def diff(store: RecordStore, q: dict, ctx: dict) -> dict:
    """What the Record learned between ``since`` and ``as_of``."""
    as_of = _as_of(q)
    since = _int(q, "since", required=True)
    lo, hi = min(since, as_of), max(since, as_of)
    got = store.became_known(lo, hi)
    return {"from": lo, "to": hi, "n_entries": got["n_entries"], "n_links": got["n_links"],
            "incident_changes": got["incident_changes"], "entries": [_e(e) for e in got["entries"][:60]]}


def precedents(store: RecordStore, q: dict, ctx: dict) -> dict:
    as_of = _as_of(q)
    iid = _int(q, "id")
    return prec.summary(store, as_of) if iid is None else prec.compare(store, iid, as_of)


# The Read API page: run one of the Record's read methods by hand.
READ_METHODS: dict[str, dict[str, Any]] = {
    "entries": {"doc": "Entries known by as_of whose event time overlaps [t0, t1].",
                "args": ["elements", "types", "kinds", "record_classes", "sources", "text", "t0", "t1", "limit"]},
    "state_at": {"doc": "The last state of this type on the element at or before t, however old.",
                 "args": ["element", "type", "t"]},
    "incidents": {"doc": "All incidents known by as_of, open and closed.", "args": ["elements"]},
    "incident": {"doc": "One incident as the Record knew it at as_of.", "args": ["incident_id"]},
    "incident_entries": {"doc": "The entries attached to an incident, with their roles.", "args": ["incident_id"]},
    "links": {"doc": "Links touching an entry; both ends must be known.", "args": ["entry_id"]},
    "related": {"doc": "Service-side neighbours of an element (supply, FED, boxes).", "args": ["element"]},
    "subtree": {"doc": "An element and everything below it.", "args": ["element"]},
    "ancestors": {"doc": "Everything above an element.", "args": ["element"]},
}


def read(store: RecordStore, q: dict, ctx: dict) -> dict:
    as_of = _as_of(q)
    method = q.get("method", "")
    if method not in READ_METHODS:
        raise ApiError(f"unknown read method {method!r}")
    kw: dict[str, Any] = {}
    for arg in READ_METHODS[method]["args"]:
        if not q.get(arg):
            continue
        if arg in ("elements", "types", "kinds", "record_classes", "sources"):
            kw[arg] = _list(q, arg)
        elif arg in ("t0", "t1", "t", "limit", "incident_id", "entry_id"):
            kw[arg] = _int(q, arg)
        else:
            kw[arg] = q[arg]
    for name in kw.get("elements") or ([kw["element"]] if "element" in kw else []):
        if not store.has_element(name):
            raise ApiError(f"unknown element {name!r}", 404)
    timeless = method in ("related", "subtree", "ancestors")
    if method == "entries":
        kw.setdefault("limit", 50)
    try:
        result = getattr(store, method)(**kw) if timeless else getattr(store, method)(as_of=as_of, **kw)
    except TypeError as exc:
        raise ApiError(f"missing or wrong arguments for {method}: {exc}") from None
    call_args = ([] if timeless else [f"as_of={as_of}"]) + [f"{k}={v!r}" for k, v in kw.items()]
    return {"call": f"store.{method}({', '.join(call_args)})", "result": _plain(result)}


def _plain(x: Any) -> Any:
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if hasattr(x, "__dataclass_fields__"):
        return asdict(x)
    return str(x)


def replay(store: RecordStore, q: dict, ctx: dict) -> dict:
    """One incident as the Record stood at a moment, for stepping through how knowledge arrived.

    ``frame``, ``ask_time`` and ``steps`` describe the replay itself (which problem, and the
    moments at which something was learned: times only). Everything else is Record content
    known by ``as_of``.
    """
    as_of = _as_of(q)
    iid = _int(q, "id", required=True)
    frame = store.incident_frame(iid)
    if frame is None:
        raise ApiError("no such incident", 404)
    view = store.incident(iid, as_of)
    rows = store.incident_entries_seen(iid, as_of)
    ids = {e.id for _, e in rows}
    links = {}
    for _, e in rows:
        for link in store.links(e.id, as_of):
            if link.src_entry_id in ids and link.dst_entry_id in ids:
                links[link.id] = asdict(link)
    learned = None
    since = _int(q, "since")
    if since is not None and since < as_of:
        got = store.became_known(since, as_of, limit=2000)
        learned = {"since": since,
                   "entries": [_e(e) for e in got["entries"] if e.id in ids],
                   "changes": [c for c in got["incident_changes"] if c["incident_id"] == iid]}
    steps = store.incident_step_times(iid)
    # what each step taught, for steps already reached (later ones stay times only)
    labels = {"known_at": "incident opened", "recovery_action": "recovery action recorded",
              "confirmed_cause": "cause confirmed", "certification": "certification recorded"}
    notes: dict[int, list[str]] = {t: [] for t in steps if t <= as_of}
    for role, e in store.incident_entries_seen(iid, as_of):
        if e.known_at in notes:
            notes[e.known_at].append(short_text(e))
    for r in store.parts(as_of, incident_id=iid):
        if r.known_at in notes and r.role != "reported":
            notes[r.known_at].append(f"{r.role}: {r.element}")
    for t in notes:                         # incident changes: compare the incident just before and at t
        was, now = store.incident(iid, t - 1), store.incident(iid, t)
        if now and not was:
            notes[t].append(labels["known_at"])
        for field in ("recovery_action", "confirmed_cause", "certification"):
            if now and getattr(now, field) and not (was and getattr(was, field)):
                notes[t].append(labels[field])
    return {"frame": frame, "ask_time": prec.first_ask_time(store, iid),
            "steps": steps, "step_notes": {str(t): sorted(set(v), key=v.index) for t, v in notes.items()},
            "incident": asdict(view) if view else None,
            "entries": [{"role": r, **_e(e)} for r, e in rows], "links": list(links.values()),
            "precedents": prec.at_moment(store, iid, as_of), "learned": learned,
            "parts": [asdict(r) for r in store.parts(as_of, incident_id=iid)]}


ROOT = Path(__file__).resolve().parent.parent
# Where in the source each thing on the "how the Record is built" page is done.
# (file, text that starts the relevant code). Line numbers are looked up when asked,
# so the links keep pointing at the right place as the code changes.
SOURCE_SPOTS = {
    "calendar": ("example_device/plan.py", "def build_plan("),
    "voltage": ("example_device/generator.py", "# readings: the full series go to the control-system archive"),
    "status_rule": ("example_device/readings.py", "RULES = {"),
    "adapter": ("adapters/control_archive.py", "    def fetch("),
    "quality": ("example_device/generator.py", "# data quality: every run's numbers per box go to the data-quality archive"),
    "calendar_write": ("example_device/generator.py", "# the calendar: beam modes, fills and runs"),
    "certification": ("example_device/generator.py", "# certification: completed per run and subdetector"),
    "parts": ("example_device/generator.py", "    def ref("),
    "note": ("example_device/texts.py", "T: dict[str, list[str]] = {"),
    "direct_link": ("example_device/generator.py", "def downtime("),
    "indirect_link": ("example_device/generator.py", "def conclude("),
    "incident": ("example_device/generator.py", "def configure_failure("),
    "write": ("aggregator/store.py", "def add_entry("),
}


def source_spots() -> dict[str, Optional[dict]]:
    out: dict[str, Optional[dict]] = {}
    for key, (rel, needle) in SOURCE_SPOTS.items():
        path = ROOT / rel
        line = None
        if path.is_file():
            line = next((n for n, text in enumerate(path.read_text().splitlines(), 1) if needle in text), None)
        out[key] = {"file": rel, "line": line, "href": f"/source/{rel}#L{line}"} if line else None
    return out


def _link_example(store: RecordStore, as_of: int, entry_type: str, link_type: str) -> Optional[dict]:
    for e in store.entries(as_of, types=[entry_type]):
        for link in store.links(e.id, as_of):
            if link.link_type == link_type:
                return {"link": asdict(link), "src": _e(store.get_entry(link.src_entry_id, as_of)),
                        "dst": _e(store.get_entry(link.dst_entry_id, as_of))}
    return None


# The parts of the design that are interfaces only, in the order data flows through them.
INTERFACE_FILES = [
    ("Source adapters", "feed", "adapters/base.py"),
    ("Control-system archive adapter", "feed", "adapters/control_archive.py"),
    ("Anonymizer", "feed", "anonymizer/__init__.py"),
    ("Summarizer", "feed", "summarizer/__init__.py"),
    ("Sparsifier", "feed", "sparsifier/__init__.py"),
    ("Direct-link builder", "aggregator", "aggregator/linker.py"),
    ("Query tools", "orchestrator", "orchestrator/tools.py"),
    ("Diagnosis agent", "orchestrator", "orchestrator/agent.py"),
]


def _describe_module(rel: str) -> dict:
    """Classes, fields, methods and the module's ROLE/STATUS/EXAMPLE, read from the code itself."""
    import ast

    path = ROOT / rel
    text = path.read_text()
    lines = text.splitlines()
    tree = ast.parse(text)
    consts: dict[str, Any] = {}
    items = []

    def sig(fn: ast.FunctionDef) -> str:
        args = ast.unparse(fn.args)
        ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
        return f"{fn.name}({args}){ret}"

    def doc1(node) -> str:
        d = ast.get_docstring(node) or ""
        return d.strip().split("\n\n")[0].replace("\n", " ")

    def comment(lineno: int) -> str:
        line = lines[lineno - 1]
        return line.split("#", 1)[1].strip() if "#" in line else ""

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("STATUS", "ROLE", "EXAMPLE"):
            consts[node.targets[0].id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            decos = [ast.unparse(d) for d in node.decorator_list]
            kind = "contract" if "Protocol" in bases else "record" if any(d.startswith("dataclass") for d in decos) else "implementation"
            fields = [{"name": ast.unparse(st.target), "type": ast.unparse(st.annotation), "note": comment(st.lineno)}
                      for st in node.body if isinstance(st, ast.AnnAssign)]
            methods = [{"signature": sig(st), "doc": doc1(st), "line": st.lineno}
                       for st in node.body if isinstance(st, ast.FunctionDef) and not st.name.startswith("_")]
            items.append({"name": node.name, "kind": kind, "doc": doc1(node), "line": node.lineno,
                          "fields": fields, "methods": methods})
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            items.append({"name": node.name, "kind": "function", "doc": doc1(node), "line": node.lineno,
                          "fields": [], "methods": [{"signature": sig(node), "doc": "", "line": node.lineno}]})
    return {"file": rel, "module_doc": (ast.get_docstring(tree) or "").strip(), "items": items, **consts}


def interfaces(store: RecordStore, q: dict, ctx: dict) -> dict:
    """The interfaces of the parts not built yet, read from their skeleton code, each with a real
    entry from this Record of the kind it would produce."""
    as_of = _as_of(q)
    out = []
    for title, group, rel in INTERFACE_FILES:
        mod = _describe_module(rel)
        example = mod.get("EXAMPLE") or {}
        produced = None
        if example.get("produces"):
            src, typ = example["produces"].split("/")
            found = store.entries(as_of, sources=[src], types=[typ])
            linked = [e for e in found if store.incidents_of_entry(e.id, as_of)]
            interesting = [e for e in found if e.payload.get("value") not in (None, "normal", "ok", "on")]
            pick = (linked or interesting or found or [None])[0]
            produced = _e(pick) if pick else None
        out.append({"title": title, "group": group, **mod, "status": mod.get("STATUS", "built"),
                    "role": mod.get("ROLE", ""), "example": example, "produced": produced})
    return {"interfaces": out}


def _part_example(store: RecordStore, as_of: int) -> Optional[dict]:
    """An incident whose parts arrived at different times: the best illustration of part references."""
    best = None
    for inc in store.incidents(as_of):
        parts = store.parts(as_of, incident_id=inc.id)
        if best is None or len({r.known_at for r in parts}) > len({r.known_at for r in best[1]}):
            best = (inc, parts)
    return {"incident": asdict(best[0]), "parts": [asdict(r) for r in best[1]]} if best else None


def _archive_summary(archive) -> Optional[dict]:
    if archive is None:
        return None
    chans = archive.channels()
    return {"channels": len(chans), "samples": sum(c["n"] for c in chans),
            "cadence_s": chans[0]["cadence_s"] if chans else None,
            "bytes": sum((archive.dir / c["file"]).stat().st_size for c in chans)}


def agent(store: RecordStore, q: dict, ctx: dict) -> dict:
    """What the scripted agent would propose for the problem being replayed, at this moment."""
    as_of = _as_of(q)
    iid = _int(q, "id", required=True)
    trig = trigger_for(store, iid, as_of)
    if trig is None:
        return {"trigger": None, "message": "No symptom of this problem is on record yet: there is nothing to ask about."}
    r = diagnose(trig, ScriptedBrain(), store, ctx.get("archive"))
    p = r["proposal"]
    cited = {}
    for c in p.supporting + p.conflicting:
        e = store.get_entry(c.entry_id, as_of)
        if e:
            cited[c.entry_id] = _e(e)
    return {"trigger": asdict(trig), "proposal": asdict(p), "log": r["log"].as_dicts(), "problems": r["problems"],
            "accepted": r["accepted"], "settings": r["settings"].describe(), "learned": r["learned"], "cited": cited}


_REPORT_CACHE: dict[tuple, dict] = {}


def agent_report(store: RecordStore, q: dict, ctx: dict) -> dict:
    """The scripted agent run on every incident, each at the moment its crew first asked, and
    judged against what the Record learned afterwards (later precedent reviews), as of ``as_of``.

    The judgement uses only the Record. The answer key is added separately, for the demo.
    """
    from orchestrator.confidence import Settings, learned_counts

    as_of = _as_of(q)
    key = (str(store.path), store.path.stat().st_mtime, as_of)
    if key in _REPORT_CACHE:
        return _REPORT_CACHE[key]
    rows = []
    reviews = store.precedent_reviews(as_of)
    for inc in store.incidents(as_of):
        asked = prec.first_ask_time(store, inc.id)
        if asked is None or asked > as_of:
            continue
        trig = trigger_for(store, inc.id, asked)
        if trig is None:
            continue
        r = diagnose(trig, ScriptedBrain(), store, ctx.get("archive"))
        p = r["proposal"]
        mine = [x for x in reviews if x["incident_id"] == inc.id]
        confirmed = {x["earlier_id"] for x in mine if x["status"] == "confirmed"}
        rejected = {x["earlier_id"] for x in mine if x["status"] == "rejected"}
        # judged by the reviews written after the incident was closed
        if p.verdict == "new":
            outcome = "missed" if confirmed else "right" if mine or inc.status in ("closed", "unresolved") else "not reviewed yet"
        elif p.precedent in confirmed:
            outcome = "right" if p.verdict == "known" else "too cautious"
        elif p.precedent in rejected:
            outcome = "wrong" if p.verdict == "known" else "right to doubt"
        else:
            outcome = "not reviewed yet"
        rows.append({"id": inc.id, "title": inc.title, "element": inc.element, "t_start": inc.t_start, "asked": asked,
                     "verdict": p.verdict, "confidence": p.confidence, "precedent": p.precedent, "next_step": p.next_step,
                     "part": p.element, "accepted": r["accepted"], "n_calls": len(r["log"].calls),
                     "signature": p.candidates[0]["signature"] if p.candidates else None,
                     "n_candidates": len(p.candidates), "outcome": outcome,
                     "confirmed_later": sorted(confirmed), "rejected_later": sorted(rejected)})
    # how the learned starting value of each signature moved as reviews came in
    s = Settings()
    times = sorted({x["known_at"] for x in reviews})
    learning = []
    for t in [store.time_span()[0]] + times:
        counts = learned_counts(store, t)
        learning.append({"t": t, **{sig: round((a + counts[sig]["confirmed"]) / (a + b + counts[sig]["confirmed"] + counts[sig]["rejected"]), 3)
                                    for sig, (a, b) in s.priors.items()},
                         "counts": counts})
    out = {"rows": rows, "settings": s.describe(), "learning": learning, "t1": store.time_span()[1]}
    _REPORT_CACHE[key] = out
    return out


def built(store: RecordStore, q: dict, ctx: dict) -> dict:
    """Real rows used as worked examples on the 'how the Record is built' page."""
    as_of = _as_of(q)
    config = json.loads(store.meta().get("config", "{}"))
    volts = store.entries(as_of, types=["lv_voltage_status"])
    voltage = next((e for e in volts if e.payload["value"] == "drifting down"),
                   next((e for e in volts if e.payload["value"] != "normal"), volts[0] if volts else None))
    quality = store.entries(as_of, types=["quality_status"])
    hot = next((e for e in quality if e.payload["value"] == "hot channels"),
               next((e for e in quality if e.payload["value"] != "normal"), quality[0] if quality else None))
    notes = store.entries(as_of, types=["shift_note"])
    note = next((e for e in notes if store.incidents_of_entry(e.id, as_of)), notes[0] if notes else None)
    incidents_ = store.incidents(as_of)
    example = None
    for inc in incidents_:
        attached = store.incident_entries(inc.id, as_of)
        n_links = len({l.id for _, e in attached for l in store.links(e.id, as_of) if l.link_type == "indirect"})
        if n_links:
            example = {"incident": asdict(inc), "n_entries": len(attached), "n_links": n_links}
            break
    by_type = store.counts_by_type(as_of)
    text_types = {"shift_note", "followup", "root_cause", "closing_note", "daily_run_summary", "cert_flag", "downtime"}
    return {"config": config, "counts": store.table_counts(as_of), "by_type": by_type,
            "n_text": sum(n for _, _, t, _, n in by_type if t in text_types),
            "examples": {"voltage": _e(voltage) if voltage else None, "quality": _e(hot) if hot else None,
                         "note": _e(note) if note else None},
            "incident_example": example, "source": source_spots(),
            "archive": _archive_summary(ctx.get("archive")),
            "status_rules": json.loads(store.meta().get("status_rules", "{}")),
            "calendar": {"runs": len(store.runs(as_of)), "fills": len(store.fills(as_of)),
                         "certified": len(store.certification(as_of))},
            "part_example": _part_example(store, as_of),
            "share": {"status": sum(n for _, _, t, _, n in by_type if t.endswith("_status")),
                      "total": sum(n for *_, n in by_type)},
            "links": {"direct": _link_example(store, as_of, "downtime", "direct"),
                      "indirect": _link_example(store, as_of, "root_cause", "indirect")}}


# ------------------------------------------------------------------ demo-only endpoints
def _planted(ctx: dict) -> dict:
    if ctx["planted"] is None:
        raise ApiError("no planted.json next to this Record", 404)
    return json.loads(Path(ctx["planted"]).read_text())


def demo_planted(store: RecordStore, q: dict, ctx: dict) -> dict:
    return _planted(ctx)


def demo_device(store: RecordStore, q: dict, ctx: dict) -> dict:
    """The generator's view: every planted case with the entries its script wrote.

    Demo only. Ignores the time control on purpose: it shows when each piece will become known.
    """
    data = _planted(ctx)
    end = store.latest_known_at()
    experiment = store.elements("experiment")[0]
    beam = store.beam_modes(end)
    runs = [{"run": r["run"], "fill": r["fill"], "t0": r["t_start"], "t1": r["t_end"], "n_ls": r["n_ls"],
             "reason": r["stop_reason"]} for r in store.runs(end)]
    cases = []
    for case in data["planted"]:
        roles = dict()
        if case["incident_id"]:
            roles = {e.id: r for r, e in store.incident_entries(case["incident_id"], end)}
        rows = [{"role": roles.get(i, ""), **_e(store.get_entry(i, end))} for i in case.get("entry_ids", [])]
        rows.sort(key=lambda r: (r["t_start"], r["known_at"], r["id"]))
        inc = store.incident(case["incident_id"], end) if case["incident_id"] else None
        cases.append({**case, "entries": rows, "incident": asdict(inc) if inc else None})
    return {"modes": data.get("modes", {}), "cases": cases, "runs": runs,
            "beam": [{"mode": b["mode"], "t0": b["t_start"], "t1": b["t_end"]} for b in beam]}


ROUTES: dict[str, Callable[[RecordStore, dict, dict], dict]] = {
    "meta": meta, "next_known": next_known, "overview": overview, "elements": elements,
    "entries": entries, "entry": entry, "incidents": incidents, "incident": incident,
    "timeline": timeline, "tables": tables, "map": detector_map, "diff": diff, "precedents": precedents, "read": read,
    "replay": replay, "built": built, "interfaces": interfaces, "agent": agent, "agent_report": agent_report, "demo/planted": demo_planted, "demo/device": demo_device,
}
# Endpoints that may be called without as_of, and why (see the module docstring).
NO_AS_OF = {"meta", "next_known", "demo/planted", "demo/device"}
DEMO_ONLY = {"demo/planted", "demo/device"}
