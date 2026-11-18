"""The agent: tools that cannot see the future, a checked proposal, and the Fig. 2 story."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from adapters.control_archive import ControlArchive
from orchestrator.agent import Citation, ModelBrain, Proposal, ScriptedBrain, check, diagnose, trigger_for
from orchestrator.confidence import Settings, score, verdict
from orchestrator.tools import QueryLog, RecordTools


@pytest.fixture()
def pair(tiny):
    return [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"][:2]


def run(tiny, store, case, as_of=None):
    trig = trigger_for(store, case["incident_id"], as_of or case["ask_at"])
    return diagnose(trig, ScriptedBrain(), store, ControlArchive.find(tiny["db"]))


def test_fig2_new_then_known(tiny, store, pair):
    first, second = pair
    a = run(tiny, store, first)
    assert a["accepted"] and a["proposal"].verdict == "new" and a["proposal"].next_step == "escalate"
    b = run(tiny, store, second)
    p = b["proposal"]
    assert b["accepted"] and p.verdict == "known" and p.next_step == "recovery_procedure"
    assert p.precedent == first["incident_id"] and p.element == first["true_element"]
    assert "Power-cycle the control module" in p.diagnosis and "No cause was confirmed then" in p.diagnosis


def test_the_agent_sees_nothing_after_the_moment(tiny, store, pair):
    second = pair[1]
    r = run(tiny, store, second)
    for call in r["log"].calls:
        assert call.as_of == second["ask_at"]
        for eid in call.entry_ids:
            assert store.get_entry(eid, second["ask_at"]) is not None
    tools = RecordTools(store, second["ask_at"])
    with pytest.raises(ValueError):
        tools.state("HCAL", second["ask_at"] + 1)


def test_every_scripted_answer_on_the_planted_cases_passes_the_check(tiny, store):
    for case in tiny["planted_cases"]:
        if case["incident_id"]:
            r = run(tiny, store, case)
            assert r["accepted"], (case["id"], r["problems"])


def test_check_rejects_a_citation_no_tool_returned(tiny, store, pair):
    r = run(tiny, store, pair[1])
    p = r["proposal"]
    p.supporting.append(Citation(entry_id=1, query_id=1, why="made up"))
    assert any("unsupported" in x for x in check(p, r["log"]))
    assert check(Proposal("HCAL", "known", "", "escalate", "none"), QueryLog()) == ["'known' without a precedent"]


def test_confidence_learns_from_reviews_and_evidence():
    s = Settings()
    none = {k: {"confirmed": 0, "rejected": 0} for k in ("both", "symptom", "part")}
    assert score("symptom", none, 0, s)["confidence"] == pytest.approx(1 / 3, abs=1e-3)
    learned = {**none, "symptom": {"confirmed": 6, "rejected": 0}}
    assert score("symptom", learned, 0, s)["confidence"] == pytest.approx(7 / 9, abs=1e-3)
    assert score("both", none, 1, s)["confidence"] == pytest.approx(0.9, abs=1e-3)
    rejected = {**none, "part": {"confirmed": 0, "rejected": 5}}
    assert verdict(score("part", rejected, 0, s)["confidence"], s) == "new"


def test_the_gui_endpoint_shows_only_what_was_known(call, store, pair):
    second = pair[1]
    _, body = call("agent", id=second["incident_id"], as_of=second["ask_at"])
    assert body["accepted"] and body["proposal"]["verdict"] == "known"
    assert all(e["known_at"] <= second["ask_at"] for e in body["cited"].values())
    _, early = call("agent", id=second["incident_id"], as_of=second["t_event"] - 3600)
    assert early["trigger"] is None


@pytest.fixture()
def call(tiny):
    from pathlib import Path

    from viewer.server import handle_api
    db = Path(tiny["db"])
    return lambda route, **q: handle_api(db, db.with_name("planted.json"), route, {k: str(v) for k, v in q.items()})


def _fake_model(replies):
    """A stand-in for an OpenAI-compatible endpoint that answers with scripted messages."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"choices": [{"message": replies[min(len(seen), len(replies)) - 1](seen[-1])}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def test_model_brain_speaks_the_tool_calling_protocol(tiny, store, pair):
    second = pair[1]
    trig = trigger_for(store, second["incident_id"], second["ask_at"])

    def ask_events(_):
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "events", "arguments": json.dumps({"t0": trig.t_start - 3600, "t1": trig.as_of, "part": "HCAL"})}}]}

    def answer(request):
        result = json.loads(request["messages"][-1]["content"])
        cited = [{"entry_id": e["id"], "query_id": result["query_id"], "why": "symptom"} for e in result["entries"][:2]]
        return {"role": "assistant", "content": json.dumps({"element": "HCAL", "verdict": "new", "diagnosis": "unsure",
                                                            "next_step": "escalate", "relied_on": "none", "supporting": cited})}

    server, seen = _fake_model([ask_events, answer])
    try:
        r = diagnose(trig, ModelBrain(f"http://127.0.0.1:{server.server_port}/v1", "fake"), store)
    finally:
        server.shutdown()
    assert r["accepted"] and r["proposal"].brain == "model" and len(r["proposal"].supporting) == 2
    assert seen[0]["tools"] and {t["function"]["name"] for t in seen[0]["tools"]} == {
        "search_incidents", "get_incident", "state", "events", "co_occurring", "series"}


def test_model_brain_citations_are_checked(tiny, store, pair):
    second = pair[1]
    trig = trigger_for(store, second["incident_id"], second["ask_at"])
    lie = lambda _: {"role": "assistant", "content": json.dumps({  # noqa: E731
        "element": "HFP02", "verdict": "known", "precedent": 3, "diagnosis": "x", "next_step": "recovery_procedure",
        "relied_on": "recovery_action", "supporting": [{"entry_id": 5, "query_id": 1}]})}
    server, _ = _fake_model([lie])
    try:
        r = diagnose(trig, ModelBrain(f"http://127.0.0.1:{server.server_port}", "fake"), store)
    finally:
        server.shutdown()
    assert not r["accepted"] and "unsupported" in r["problems"][0]


def test_demo_command_runs(tiny, capsys):
    from orchestra_cli import main
    assert main(["demo", "--db", tiny["db"]]) == 0
    out = capsys.readouterr().out
    assert out.count("check        passed") == 3 and "verdict      new" in out and "verdict      known" in out


def test_agent_report_judges_by_later_reviews_only(call, tiny, store):
    end = store.latest_known_at()
    _, body = call("agent_report", as_of=end)
    rows = {r["id"]: r for r in body["rows"]}
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"][:2]
    assert rows[first["incident_id"]]["verdict"] == "new" and rows[first["incident_id"]]["outcome"] == "right"
    assert rows[second["incident_id"]]["outcome"] == "right" and rows[second["incident_id"]]["precedent"] == first["incident_id"]
    assert all(r["accepted"] for r in rows.values())
    # earlier, the reviews are not written yet: nothing can be judged
    _, early = call("agent_report", as_of=second["ask_at"] + 3600)
    assert {r["outcome"] for r in early["rows"]} <= {"not reviewed yet", "right"}
    assert all(r["asked"] <= second["ask_at"] + 3600 for r in early["rows"])
    assert body["learning"][0]["symptom"] == pytest.approx(1 / 3, abs=1e-3)


def test_profiles_keep_keys_out_of_the_file_and_out_of_sight(tmp_path, monkeypatch):
    import os

    from orchestrator.llm_config import ConfigError, config_path, get_profile, load_profiles

    monkeypatch.delenv("ORCHESTRA_LLM_CONFIG", raising=False)
    assert config_path().parent.name == "config"                       # profiles next to the code; keys elsewhere
    cfg = tmp_path / "llm.yaml"
    cfg.write_text("""
default: gw
profiles:
  gw:
    backend: openai_compatible
    options: {base_url: "https://gw.example/v1", model: m1, api_key_env: TEST_ORCH_KEY}
  local:
    backend: openai_compatible
    options: {base_url: "http://127.0.0.1:11434/v1", model: m2}
  mock:
    backend: mock
""")
    keys = tmp_path / "keys.env"
    monkeypatch.setenv("ORCHESTRA_LLM_CONFIG", str(cfg))
    monkeypatch.setenv("ORCHESTRA_KEYS_FILE", str(keys))
    monkeypatch.delenv("TEST_ORCH_KEY", raising=False)
    found, default = load_profiles()
    assert set(found) == {"gw", "local"} and default == "gw"           # "mock" is not an LLM brain here
    assert not found["gw"].key_available() and found["local"].key_available()
    keys.write_text("export TEST_ORCH_KEY=from-file\n")
    os.chmod(keys, 0o644)
    assert "chmod 600" in found["gw"].key_problem()                    # readable by others: refused
    os.chmod(keys, 0o600)
    assert get_profile().api_key() == "from-file"
    monkeypatch.setenv("TEST_ORCH_KEY", "secret-123")                  # the environment wins
    brain = ModelBrain.from_profile(get_profile())
    assert brain._key == "secret-123" and "secret-123" not in repr(brain)
    assert "secret-123" not in json.dumps(found["gw"].describe())
    cfg.write_text("profiles:\n  bad:\n    backend: openai_compatible\n    options: {base_url: x, model: y, api_key: oops}\n")
    with pytest.raises(ConfigError):
        load_profiles()


def test_git_holds_only_an_example_without_keys(monkeypatch):
    import yaml

    from orchestrator.llm_config import REPO, load_profiles

    import subprocess

    ignored = subprocess.run(["git", "check-ignore", "-q", "config/llm.yaml"], cwd=REPO)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "config/llm.yaml"], cwd=REPO, capture_output=True)
    assert ignored.returncode == 0 and tracked.returncode != 0         # the real profiles never enter git
    example = REPO / "config" / "llm.example.yaml"
    data = yaml.safe_load(example.read_text())
    assert all("api_key" not in (s.get("options") or {}) for s in data["profiles"].values())
    monkeypatch.setenv("ORCHESTRA_LLM_CONFIG", str(example))
    found, default = load_profiles()
    assert default == "local" and set(found) == {"local", "gateway"}
