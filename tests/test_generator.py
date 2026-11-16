"""Layer 1: the generator produced what it claims."""
from pathlib import Path

import pytest

from aggregator import RecordStore
from example_device import SizeBudgetError, generate, preset
from example_device.config import FIRST_FILL_NUMBER, FIRST_RUN_NUMBER
from utils import from_iso


def test_same_seed_gives_identical_record(tiny, tmp_path):
    again = generate(preset("tiny"), tmp_path)
    a, b = RecordStore.open(tiny["db"]), RecordStore.open(again["db"])
    assert a.content_hash() == b.content_hash()
    assert Path(tiny["planted"]).read_text() == Path(again["planted"]).read_text()


def test_different_seed_gives_different_record(tiny, tmp_path):
    other = generate(preset("tiny", seed=2), tmp_path)
    assert RecordStore.open(tiny["db"]).content_hash() != RecordStore.open(other["db"]).content_hash()


def test_size_is_within_budget(tiny):
    assert Path(tiny["db"]).stat().st_size / 1e6 <= tiny["config"].max_size_mb


def test_budget_above_hard_cap_is_refused(tmp_path):
    with pytest.raises(SizeBudgetError):
        generate(preset("tiny", max_size_mb=101), tmp_path)
    assert not (tmp_path / "record.db").exists()


def test_budget_too_small_is_refused(tmp_path):
    with pytest.raises(SizeBudgetError):
        generate(preset("tiny", max_size_mb=0.05), tmp_path)
    assert not (tmp_path / "record.db").exists()


def test_small_preset_is_scaled_down_to_fit_a_tight_budget(tmp_path):
    result = generate(preset("small", max_size_mb=3), tmp_path)
    assert result["adjustments"]
    assert result["size_mb"] <= 3


def test_existing_record_is_not_overwritten_without_force(tiny):
    with pytest.raises(FileExistsError):
        generate(preset("tiny"), Path(tiny["db"]).parent)


def test_no_real_events_guard(store, end):
    """Dates are in 2040 or later; run and fill numbers are in the invented ranges."""
    entries = store.entries(end)
    assert min(e.t_start for e in entries) >= from_iso("2040-01-01")
    runs = [e.payload["run"] for e in entries if "run" in e.payload]
    fills = [e.payload["fill"] for e in entries if "fill" in e.payload]
    assert runs and min(runs) >= FIRST_RUN_NUMBER
    assert fills and min(fills) >= FIRST_FILL_NUMBER
    assert store.meta()["synthetic"] == "true"
    assert "NOT CMS DATA" in store.meta()["banner"]


def test_authors_are_roles_not_people(store, end):
    roles = {e.payload["author_role"] for e in store.entries(end) if "author_role" in e.payload}
    assert roles <= {"Shift leader", "DAQ shifter", "DCS shifter", "DQM shifter", "HCAL DOC",
                     "HCAL expert", "Run coordinator"}


def test_entries_are_well_formed(store, end):
    known_elements = set(store.elements())
    for e in store.entries(end):
        assert e.element in known_elements
        assert e.known_at >= e.t_start
        assert e.producer and e.raw_ref.startswith("synthetic://")


def test_every_planted_fault_is_in_the_record(tiny, store, end):
    cases = tiny["planted_cases"]
    assert {c["mode"] for c in cases} >= {"fed_comm_loss", "configure_failure", "lv_drift_trip",
                                          "hot_channels", "planned_change"}
    for case in cases:
        if case["mode"] == "planned_change":
            assert case["incident_id"] is None      # the trap is not an incident
            changes = store.entries(end, elements=[case["true_element"]], types=["config_change"])
            assert [c.t_start for c in changes] == [case["t_event"]]
            continue
        incident = store.incident(case["incident_id"], end)
        assert incident is not None and incident.t_start == case["t_event"]
        roles = {role for role, _ in store.incident_entries(incident.id, end)}
        assert "symptom" in roles
        assert incident.recovery_action            # every planted incident was recovered
        assert incident.status in ("closed", "unresolved")


def test_the_fig2_pair(tiny, store, end):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    assert first["expected"] == {"verdict": "new", "next_step": "escalate", "precedents": [],
                                 "recovery_known": False, "cause_known": False}
    assert second["expected"]["verdict"] == "known"
    assert second["expected"]["precedents"] == [first["incident_id"]]
    assert second["expected"]["next_step"] == "recovery_procedure"
    assert second["expected"]["cause_known"] is False     # the fix was known before the cause
    assert store.incident(first["incident_id"], end).confirmed_cause


def test_lv_trip_is_preceded_by_a_falling_voltage(tiny, store, end):
    case = next(c for c in tiny["planted_cases"] if c["mode"] == "lv_drift_trip")
    box = next(name for rel, name in store.related(case["true_element"]) if rel == "powered_by_of")

    def mean_voltage(hours_before):
        t = case["t_event"] - int(hours_before * 3600)
        return store.entries(end, elements=[box], types=["lv_voltage"], t0=t, t1=t)[0].payload["mean"]

    readings = [mean_voltage(h) for h in (5.5, 4, 2.5, 1)]
    assert readings == sorted(readings, reverse=True)      # falling, hour after hour
    assert readings[0] - readings[-1] > 0.2
    assert abs(mean_voltage(-4) - readings[0]) < 0.05      # back to nominal after the repair
