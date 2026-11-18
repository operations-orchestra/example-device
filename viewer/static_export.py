"""Write the Record browser as one self-contained HTML file, for people without the repository.

Every answer the pages need is computed now, from one Record, and embedded (gzip, base64) in
the page; the page's code is the same as the live GUI's, reading from the embedded answers
instead of the local service. What it holds:

* every page for the finished Record;
* Replay at every step of every incident, plus the moment its crew asks and the end, with the
  scripted agent's answer, the detector and the timeline at each of those moments;
* entries are filtered in the browser.

What it cannot do: moments other than those, readings at finer resolution than the whole-
calendar view, the LLM brain, the source-code view and the read API. The page says so.
"""
from __future__ import annotations

import base64
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from aggregator import RecordStore

from .api import _e
from .server import STATIC, handle_api

# Parameters that do not change an answer in the static demo (the page ignores them too).
DROP = {"since", "t0", "t1", "limit", "offset", "order"}


def key(route: str, params: dict) -> str:
    """The lookup key for an answer; app.js builds the same key."""
    kept = sorted((k, str(v)) for k, v in params.items() if k not in DROP and v not in (None, ""))
    return route + "?" + "&".join(f"{k}={v}" for k, v in kept)


def build_bundle(db: Path) -> dict:
    planted = db.with_name("planted.json")
    planted = planted if planted.exists() else None
    store = RecordStore.open(db)
    end = store.latest_known_at()
    answers: dict[str, object] = {}

    def put(route: str, **params) -> object:
        status, body = handle_api(db, planted, route, {k: str(v) for k, v in params.items()})
        # an error is an answer too ("not known to the Record at this time"); keep it
        answers[key(route, params)] = body if status == 200 else {"__error": body.get("error", "error")}
        return body if status == 200 else None

    # the finished Record
    put("meta")
    for route in ("elements", "overview", "incidents", "map", "built", "interfaces", "precedents", "agent_report"):
        put(route, as_of=end)
    for route in ("demo/planted", "demo/device"):
        if planted:
            put(route)
    incidents = store.incidents(end)
    put("tables", as_of=end)
    for inc in incidents:
        put("tables", as_of=end, incident=inc.id)
        put("incident", as_of=end, id=inc.id)
        put("precedents", as_of=end, id=inc.id)
    for e in store.entries(end):
        put("entry", as_of=end, id=e.id)
    for name in store.elements():
        if store.element_kind(name) != "channel":
            put("timeline", as_of=end, element=name)

    # replay: every step of every incident, the moment its crew asks, and the end
    from .precedents import first_ask_time

    moments_done: set[int] = set()
    for inc in incidents:
        frame = put("replay", as_of=end, id=inc.id)
        moments = sorted(set(frame["steps"]) | {first_ask_time(store, inc.id) or end, end})
        for t in moments:
            put("replay", as_of=t, id=inc.id)
            put("agent", as_of=t, id=inc.id)
            put("incident", as_of=t, id=inc.id)
            put("timeline", as_of=t, element=frame["frame"]["element"])
            if t not in moments_done:
                put("map", as_of=t)
                moments_done.add(t)
    entries = [_e(e) for e in store.entries(end)]
    return {"answers": answers, "entries": entries, "end": end,
            "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "record": db.name}


def export(db: str | Path, out: str | Path) -> dict:
    db, out = Path(db), Path(out)
    bundle = build_bundle(db)
    raw = json.dumps(bundle, separators=(",", ":"), default=str).encode()
    packed = base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode()
    html = (STATIC / "index.html").read_text()
    css = (STATIC / "style.css").read_text()
    js = (STATIC / "app.js").read_text()
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="app.js"></script>',
                        f'<script>window.ORCHESTRA_STATIC = "{packed}";</script>\n<script>\n{js}\n</script>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return {"path": str(out), "answers": len(bundle["answers"]), "entries": len(bundle["entries"]),
            "raw_mb": round(len(raw) / 1e6, 2), "file_mb": round(out.stat().st_size / 1e6, 2)}
