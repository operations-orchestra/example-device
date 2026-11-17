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


def _e(entry: StoredEntry) -> dict[str, Any]:
    return asdict(entry)


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
    experiment = store.elements("experiment")[0]
    beam = store.entries(as_of, elements=[experiment], types=["beam_mode"])
    periods = [{"mode": cur.payload["value"], "t0": cur.t_start, "t1": nxt.t_start if nxt else None}
               for cur, nxt in zip(beam, beam[1:] + [None])]
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
            "links": list(links.values())}


# Readings come from the source archive through its adapter, never from the Record.
READINGS = [("lv_voltage", "Low voltage", "V"), ("temperature", "Temperature", "°C")]
QUANTITIES = [("occupancy_summary", "worst_ls_dead_fraction", "Dead channels (worst lumisection)", "fraction"),
              ("occupancy_summary", "hot_fraction", "Hot channels", "fraction"),
              ("occupancy_summary", "mean_occupancy", "Occupancy", "relative")]
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
    for etype, key, label, unit in QUANTITIES:
        series = []
        for box in shown:
            pts = []
            for e in store.entries(as_of, elements=[box], types=[etype]):
                pts.append({"id": e.id, "t0": e.t_start, "t1": e.t_end, "v": e.payload[key],
                            "lo": e.payload.get("min"), "hi": e.payload.get("max")})
            series.append({"box": box, "group": group_of[box], "points": pts})
        panels.append({"type": etype, "key": key, "label": label, "unit": unit,
                       "per_run": etype == "occupancy_summary", "series": series})

    experiment = store.elements("experiment")[0]
    detector_level = {n for n in marks if store.element_kind(n) in ("detector", "experiment")}
    beam = store.entries(as_of, elements=[experiment], types=["beam_mode"])
    strip = {"Stable beams": [], "Downtime": [], "Certified bad": [], "Reading status": [], "State change": [],
             "Fault event": [], "Logbook note": []}
    for cur, nxt in zip(beam, beam[1:] + [None]):
        if cur.payload["value"] == "STABLE BEAMS":
            strip["Stable beams"].append({"id": cur.id, "t0": cur.t_start, "t1": nxt.t_start if nxt else None,
                                          "text": "stable beams"})
    t_first = store.time_span()[0]
    for e in store.entries(as_of, elements=marks):
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
    # reading status: one bar per stretch in which a shown box's reading was not normal
    for box in shown:
        for quantity, label, _ in READINGS:
            changes = store.entries(as_of, elements=[box], types=[f"{quantity}_status"])
            for cur, nxt in zip(changes, changes[1:] + [None]):
                if cur.payload["value"] != "normal":
                    strip["Reading status"].append({
                        "id": cur.id, "t0": cur.t_start, "t1": nxt.t_start if nxt else None, "value": cur.payload["value"],
                        "text": f"{box} {label.lower()}: {cur.payload['value']} (recorded {to_iso(cur.known_at)})"})
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
    flags = [{"element": e.element, "flag": e.payload.get("flag"), "id": e.id}
             for e in store.entries(as_of, types=["channel_flag"], t0=as_of, t1=as_of)]
    open_issues = [asdict(i) for i in store.incidents(as_of)
                   if i.status in ("open", "mitigated") and i.t_start <= as_of]
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
    return {"frame": frame, "ask_time": prec.first_ask_time(store, iid),
            "steps": store.incident_step_times(iid),
            "incident": asdict(view) if view else None,
            "entries": [{"role": r, **_e(e)} for r, e in rows], "links": list(links.values()),
            "precedents": prec.at_moment(store, iid, as_of), "learned": learned}


ROOT = Path(__file__).resolve().parent.parent
# Where in the source each thing on the "how the Record is built" page is done.
# (file, text that starts the relevant code). Line numbers are looked up when asked,
# so the links keep pointing at the right place as the code changes.
SOURCE_SPOTS = {
    "calendar": ("example_device/plan.py", "def build_plan("),
    "voltage": ("example_device/generator.py", "# readings: the full series go to the control-system archive"),
    "status_rule": ("example_device/readings.py", "RULES = {"),
    "adapter": ("adapters/control_archive.py", "    def fetch("),
    "quality": ("example_device/generator.py", "# data-quality summary per run and box; certification per run and subdetector"),
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


def _archive_summary(archive) -> Optional[dict]:
    if archive is None:
        return None
    chans = archive.channels()
    return {"channels": len(chans), "samples": sum(c["n"] for c in chans),
            "cadence_s": chans[0]["cadence_s"] if chans else None,
            "bytes": sum((archive.dir / c["file"]).stat().st_size for c in chans)}


def built(store: RecordStore, q: dict, ctx: dict) -> dict:
    """Real rows used as worked examples on the 'how the Record is built' page."""
    as_of = _as_of(q)
    config = json.loads(store.meta().get("config", "{}"))
    volts = store.entries(as_of, types=["lv_voltage_status"])
    voltage = next((e for e in volts if e.payload["value"] == "drifting down"),
                   next((e for e in volts if e.payload["value"] != "normal"), volts[0] if volts else None))
    quality = store.entries(as_of, types=["occupancy_summary"])
    hot = next((e for e in quality if e.payload["hot_fraction"] > 0), quality[0] if quality else None)
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
    beam = store.entries(end, elements=[experiment], types=["beam_mode"])
    stops = {e.payload["run"]: e for e in store.entries(end, types=["run_stop"])}
    runs = [{"run": e.payload["run"], "fill": e.payload["fill"], "t0": e.t_start,
             "t1": stops[e.payload["run"]].t_start, "n_ls": stops[e.payload["run"]].payload["n_ls"],
             "reason": stops[e.payload["run"]].payload["reason"]}
            for e in store.entries(end, types=["run_start"])]
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
            "beam": [{"mode": c.payload["value"], "t0": c.t_start, "t1": n.t_start if n else None}
                     for c, n in zip(beam, beam[1:] + [None])]}


ROUTES: dict[str, Callable[[RecordStore, dict, dict], dict]] = {
    "meta": meta, "next_known": next_known, "overview": overview, "elements": elements,
    "entries": entries, "entry": entry, "incidents": incidents, "incident": incident,
    "timeline": timeline, "tables": tables, "map": detector_map, "diff": diff, "precedents": precedents, "read": read,
    "replay": replay, "built": built, "demo/planted": demo_planted, "demo/device": demo_device,
}
# Endpoints that may be called without as_of, and why (see the module docstring).
NO_AS_OF = {"meta", "next_known", "demo/planted", "demo/device"}
DEMO_ONLY = {"demo/planted", "demo/device"}
