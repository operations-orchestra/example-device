"""The static demo: one HTML file holding the answers the pages need."""
import base64
import gzip
import json
import re

from viewer.static_export import export, key


def test_static_demo_holds_the_finished_record_and_every_replay_step(tiny, tmp_path):
    out = tmp_path / "demo.html"
    r = export(tiny["db"], out)
    html = out.read_text()
    packed = re.search(r'window\.ORCHESTRA_STATIC = "([^"]+)"', html).group(1)
    bundle = json.loads(gzip.decompress(base64.b64decode(packed)))
    answers, end = bundle["answers"], bundle["end"]
    assert r["answers"] == len(answers) and len(bundle["entries"]) == r["entries"]
    for route in ("overview", "incidents", "map", "built", "agent_report", "tables"):
        assert key(route, {"as_of": end}) in answers
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"][:2]
    frame = answers[key("replay", {"as_of": end, "id": second["incident_id"]})]
    for t in frame["steps"] + [frame["ask_time"]]:
        assert key("replay", {"as_of": t, "id": second["incident_id"]}) in answers
        assert key("agent", {"as_of": t, "id": second["incident_id"]}) in answers
    agent = answers[key("agent", {"as_of": frame["ask_time"], "id": second["incident_id"]})]
    assert agent["proposal"]["verdict"] == "known"
    # nothing in the file is later than the moment it was asked for
    early = answers[key("replay", {"as_of": frame["steps"][0], "id": second["incident_id"]})]
    assert all(e["known_at"] <= frame["steps"][0] for e in early["entries"])
    # the file carries only the Record's answers: no LLM profiles, endpoints or keys
    assert bundle["answers"].get(key("profiles", {})) is None and "base_url" not in html
