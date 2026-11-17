"""The GUI's service: read-only, and never shows what the Record did not yet know."""
import hashlib
import json
import random
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from viewer.api import DEMO_ONLY, NO_AS_OF, ROUTES
from example_device import generate, preset
from viewer.server import handle_api, make_server

ARGS = {"entry": {"id": "33"}, "incident": {"id": "3"}, "timeline": {"element": "HFP02"},
        "diff": {"since": "0"}, "read": {"method": "incidents"}, "next_known": {"t": "0"},
        "replay": {"id": "3"}}


@pytest.fixture()
def call(tiny):
    db = Path(tiny["db"])

    def _call(route, **query):
        return handle_api(db, db.with_name("planted.json"), route, {k: str(v) for k, v in query.items()})
    return _call


def _known_times(obj):
    """Every 'known_at' anywhere in a JSON-like structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "known_at" and isinstance(value, int):
                yield value
            else:
                yield from _known_times(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _known_times(value)


@pytest.mark.parametrize("route", sorted(set(ROUTES) - NO_AS_OF))
def test_reads_are_refused_without_as_of(call, route):
    status, body = call(route, **ARGS.get(route, {}))
    assert status == 400 and "as_of" in body["error"]


def test_only_named_endpoints_skip_as_of():
    assert NO_AS_OF == {"meta", "next_known"} | DEMO_ONLY


@pytest.mark.parametrize("route", ["overview", "entries", "incidents", "timeline", "precedents", "read", "map", "replay", "built", "tables"])
def test_no_endpoint_returns_anything_from_the_future(call, store, route):
    t0, _ = store.time_span()
    rng = random.Random(11)
    for _ in range(12):
        as_of = rng.randrange(t0 + 3600, store.latest_known_at())
        status, body = call(route, as_of=as_of, **{**ARGS.get(route, {}), "limit": 500})
        assert status == 200, body
        late = [t for t in _known_times(body) if t > as_of]
        assert not late, f"{route} at {as_of} returned {len(late)} items known later"


def test_incident_and_entry_pages_hide_what_is_not_yet_known(call, tiny):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    status, _ = call("incident", id=first["incident_id"], as_of=first["ask_at"])
    assert status == 404                                       # not opened yet
    status, body = call("incident", id=first["incident_id"], as_of=second["ask_at"])
    assert status == 200
    assert body["incident"]["recovery_action"] and body["incident"]["confirmed_cause"] is None
    assert all(t <= second["ask_at"] for t in _known_times(body))
    assert not [link for link in body["links"] if link["link_type"] == "indirect"]


def test_diff_lists_what_was_learned_in_between(call, tiny):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    _, body = call("diff", as_of=second["ask_at"], since=first["ask_at"])
    whats = {(c["incident_id"], c["what"]) for c in body["incident_changes"]}
    assert (first["incident_id"], "incident opened") in whats
    assert (first["incident_id"], "recovery action recorded") in whats
    assert (first["incident_id"], "cause confirmed") not in whats
    assert all(first["ask_at"] < t <= second["ask_at"] for t in _known_times(body["entries"]))


def test_next_known_returns_a_time_only(call, tiny):
    case = tiny["planted_cases"][0]
    status, body = call("next_known", t=case["t_event"])
    assert status == 200 and set(body) == {"t"} and body["t"] > case["t_event"]
    _, back = call("next_known", t=body["t"], direction="previous")
    assert back["t"] < body["t"]


def test_precedent_rules_use_only_the_record(call, tiny, end):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    _, body = call("precedents", id=second["incident_id"], as_of=end)
    assert body["symptom_kinds"] == ["configure:failed"]
    assert [r["id"] for r in body["same_element"]] == [first["incident_id"]]
    assert [r["id"] for r in body["same_symptom"]] == [first["incident_id"]]
    earlier = body["same_symptom"][0]                      # shown as known when the crew asked
    assert earlier["recovery_action"] and earlier["confirmed_cause"] is None
    _, none = call("precedents", id=first["incident_id"], as_of=end)
    assert none["same_element"] == [] and none["same_symptom"] == []


def test_read_page_runs_the_real_method(call, tiny, store):
    case = next(c for c in tiny["planted_cases"] if c["mode"] == "configure_failure")
    _, body = call("read", method="state_at", element=case["true_element"], type="control_link",
                   t=case["t_event"], as_of=case["ask_at"])
    direct = store.state_at(case["true_element"], "control_link", case["t_event"], as_of=case["ask_at"])
    assert body["result"]["id"] == direct.id and body["result"]["payload"]["value"] == "lost"
    assert body["call"].startswith("store.state_at(as_of=")
    assert call("read", method="drop_everything", as_of=1)[0] == 400


def test_demo_endpoint_lists_each_planted_case_with_its_entries(call, tiny):
    status, body = call("demo/device")
    assert status == 200 and len(body["cases"]) == len(tiny["planted_cases"])
    assert all(case["entries"] for case in body["cases"])
    assert set(body["modes"]) >= {case["mode"] for case in body["cases"]}


def test_service_serves_the_page_and_leaves_the_record_untouched(tiny):
    db = Path(tiny["db"])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    server = make_server(db, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "Operations Record browser" in page and "app.js" in page
        assert b"buildChart" in urllib.request.urlopen(base + "/app.js").read()
        meta = json.load(urllib.request.urlopen(base + "/api/meta"))
        assert meta["synthetic"] is True and meta["has_planted"] is True
        incidents = json.load(urllib.request.urlopen(f"{base}/api/incidents?as_of={meta['latest_known_at']}"))
        assert len(incidents["incidents"]) == 5
        code = urllib.request.urlopen(base + "/source/example_device/generator.py").read().decode()
        assert 'id="L1"' in code and "def generate(" in code
        for bad in ("/api/incidents", "/../pyproject.toml", "/%2e%2e/%2e%2e/pyproject.toml", "/nope.js",
                    "/source/pyproject.toml", "/source/../pyproject.toml", "/source/tests/conftest.py",
                    "/source/example_device/../../README.md"):
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(base + bad)
    finally:
        server.shutdown()
        server.server_close()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_tables_page_shows_raw_rows_only_as_known(call, tiny, store):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    as_of = second["ask_at"]
    status, body = call("tables", as_of=as_of, incident=first["incident_id"])
    assert status == 200 and [t["name"] for t in body["tables"]] == [
        "element", "element_relation", "entry", "link", "incident", "incident_entry", "query_log", "meta"]
    by_name = {t["name"]: t for t in body["tables"]}
    assert by_name["entry"]["count"] == store.count_entries(as_of) < store.count_entries(store.latest_known_at())
    for name in ("entry", "link", "incident", "incident_entry"):
        sample = by_name[name]["sample"]
        for row in sample["rows"]:
            for col, value in zip(sample["columns"], row):
                if col.endswith("known_at") and value is not None:
                    assert value <= as_of, (name, col)
    # the walk through one incident: recovery is known, the cause is still blank
    inc = dict(zip(body["walk"]["incident"]["columns"], body["walk"]["incident"]["rows"][0]))
    assert inc["recovery_action"] and inc["confirmed_cause"] is None and inc["cause_known_at"] is None
    attached = {row[1] for row in body["walk"]["incident_entry"]["rows"]}
    assert attached == {row[0] for row in body["walk"]["entry"]["rows"]}
    assert body["walk"]["link"]["rows"] == []                 # the expert's links come with the cause
    # every documented column exists in the real table, in order
    for t in body["tables"]:
        if t["sample"]["rows"]:
            assert [c[0] for c in t["columns"]] == t["sample"]["columns"], t["name"]


def test_detector_map_shows_state_at_the_time_control(call, tiny):
    trip = next(c for c in tiny["planted_cases"] if c["mode"] == "lv_drift_trip")
    _, during = call("map", as_of=trip["t_event"] + 300)
    supply = next(e for e in during["elements"] if e["name"] == trip["true_element"])
    assert supply["states"]["supply_state"]["value"] == "tripped"
    assert ["powered_by_of", "HBP02"] in supply["related"] or supply["related"]
    _, before = call("map", as_of=trip["t_event"] - 300)
    assert next(e for e in before["elements"] if e["name"] == trip["true_element"])["states"]["supply_state"]["value"] == "on"
    hot = next(c for c in tiny["planted_cases"] if c["mode"] == "hot_channels")
    _, later = call("map", as_of=hot["ask_at"] + 600)
    assert {f["element"] for f in later["flags"]} and all(f["element"].startswith(hot["true_element"]) for f in later["flags"])
    assert [i["id"] for i in later["open_issues"]] == [hot["incident_id"]]


def test_replay_follows_an_incident_without_showing_the_future(call, tiny, store):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    end = store.latest_known_at()
    _, full = call("replay", id=second["incident_id"], as_of=end)
    assert full["frame"]["id"] == second["incident_id"] and full["steps"] == sorted(set(full["steps"]))
    ask = full["ask_time"]
    status, body = call("replay", id=second["incident_id"], as_of=ask)
    assert status == 200
    assert body["incident"] is None                               # the Record has not opened it yet
    assert body["entries"] and all(e["known_at"] <= ask for e in body["entries"])
    assert all(e["role"] is None for e in body["entries"])        # on record, not yet linked to an incident
    # only the symptoms the crew is looking at: the expert's later evidence must not appear early
    final_roles = {e["id"]: e["role"] for e in full["entries"]}
    assert {final_roles[e["id"]] for e in body["entries"]} == {"symptom"}
    assert "evidence" in final_roles.values()
    assert body["links"] == []
    assert [r["id"] for r in body["precedents"]["same_symptom"]] == [first["incident_id"]]
    earlier = body["precedents"]["same_symptom"][0]
    assert earlier["recovery_action"] and earlier["confirmed_cause"] is None
    assert all(t <= ask for t in _known_times(body))
    # one step later the Record has learned something about it
    nxt = next(t for t in full["steps"] if t > ask)
    _, later = call("replay", id=second["incident_id"], as_of=nxt, since=ask)
    assert later["learned"]["entries"] or later["learned"]["changes"]
    assert len(later["entries"]) >= len(body["entries"])
    # the first occurrence has no precedent under either rule
    _, one = call("replay", id=first["incident_id"], as_of=first["ask_at"])
    assert one["precedents"]["same_element"] == [] and one["precedents"]["same_symptom"] == []


def test_built_page_examples_are_real_rows(call, store, end):
    _, body = call("built", as_of=end)
    ex = body["examples"]
    assert ex["voltage"]["type"] == "lv_voltage_status" and ex["voltage"]["payload"]["value"] == "drifting down"
    assert ex["voltage"]["raw_ref"].startswith("source://control_archive/")
    assert body["archive"]["channels"] == 8 and body["share"]["status"] < body["share"]["total"]
    assert ex["quality"]["type"] == "occupancy_summary" and ex["note"]["type"] == "shift_note"
    assert store.get_entry(ex["voltage"]["id"], end).payload == ex["voltage"]["payload"]
    assert body["incident_example"]["n_links"] > 0
    # every "where in the code" link resolves to a real line
    assert all(spot and spot["line"] > 0 for spot in body["source"].values()), body["source"]
    # one real direct link and one real indirect link, each with both of its entries
    direct, indirect = body["links"]["direct"], body["links"]["indirect"]
    assert direct["link"]["link_type"] == "direct" and direct["src"]["type"] == "downtime" and direct["dst"]["type"] == "run_stop"
    assert indirect["link"]["link_type"] == "indirect" and indirect["dst"]["type"] == "root_cause" and indirect["link"]["rationale"]


def test_timeline_readings_come_from_the_archive_and_stop_at_the_moment(call, tiny, store):
    case = next(c for c in tiny["planted_cases"] if c["mode"] == "lv_drift_trip")
    t0, t1 = store.time_span()
    _, body = call("timeline", element="HBP02", as_of=case["ask_at"])
    volts = next(p for p in body["panels"] if p["type"] == "lv_voltage")
    assert volts["from_source"] and body["archive"]
    points = volts["series"][0]["points"]
    assert points and max(p["t0"] for p in points) <= case["ask_at"]
    status = next(r for r in body["strip"] if r["row"] == "Reading status")["items"]
    # five minutes after the trip, "off" is not on record yet: the rule needs it to hold for ten
    assert [i["value"] for i in status if i["text"].startswith("HBP02 low voltage")] == ["drifting down", "low"]
    # zooming in asks the source again, at full resolution
    _, zoom = call("timeline", element="HBP02", as_of=t1, t0=case["t_event"] - 1800, t1=case["t_event"])
    pts = next(p for p in zoom["panels"] if p["type"] == "lv_voltage")["series"][0]["points"]
    assert all(p["n"] == 1 for p in pts) and len(pts) > 20


def test_the_gui_can_switch_to_another_record(tiny, tmp_path):
    other = generate(preset("tiny", seed=2), tmp_path / "out" / "seed2")
    server = make_server(tiny["db"], port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def post(path):
        req = urllib.request.Request(base + "/api/use", data=json.dumps({"path": path}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(req)

    try:
        listing = json.load(urllib.request.urlopen(base + "/api/records"))
        assert listing["current"] == str(tiny["db"]) and any(r["path"] == str(tiny["db"]) for r in listing["records"])
        post(other["db"])
        meta = json.load(urllib.request.urlopen(base + "/api/meta"))
        assert meta["path"] == other["db"] and meta["seed"] == "2"
        for bad in (str(tmp_path / "nope.db"), tiny["planted"], str(Path(tiny["db"]).parent)):
            with pytest.raises(urllib.error.HTTPError):
                post(bad)
        assert json.load(urllib.request.urlopen(base + "/api/meta"))["path"] == other["db"]   # unchanged by bad requests
    finally:
        server.shutdown()
        server.server_close()


def test_timeline_for_the_whole_experiment_shows_every_box(call, store, end):
    _, body = call("timeline", element="CMS", as_of=end)
    assert sorted(body["boxes"]) == sorted(store.elements("readout_box"))
    volts = next(p for p in body["panels"] if p["type"] == "lv_voltage")
    assert all(s["group"] in body["groups"] for s in volts["series"])


def test_interfaces_page_is_read_from_the_skeletons(call, end):
    import importlib
    import inspect

    _, body = call("interfaces", as_of=end)
    titles = [i["title"] for i in body["interfaces"]]
    assert {"Source adapters", "Anonymizer", "Summarizer", "Sparsifier", "Query tools", "Diagnosis agent"} <= set(titles)
    for i in body["interfaces"]:
        assert i["role"] and i["items"], i["title"]
        if i["status"] == "skeleton":                # every method of an unbuilt part refuses to run
            module = importlib.import_module(i["file"][:-3].replace("/", ".").replace(".__init__", ""))
            for item in i["items"]:
                obj = getattr(module, item["name"])
                funcs = [obj] if item["kind"] == "function" else [getattr(obj, m["signature"].split("(")[0]) for m in item["methods"]]
                for f in funcs:
                    assert "raise NotImplementedError" in inspect.getsource(f), (i["title"], item["name"])
        if i["example"].get("produces"):
            src, typ = i["example"]["produces"].split("/")
            assert i["produced"]["source"] == src and i["produced"]["type"] == typ
