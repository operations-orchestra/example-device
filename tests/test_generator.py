"""Layer 1: the generator produced what it claims."""
from pathlib import Path

import pytest

from adapters.control_archive import ControlArchive
from aggregator import RecordStore
from example_device import SizeBudgetError, generate, preset
from example_device.config import FIRST_FILL_NUMBER, FIRST_RUN_NUMBER
from utils import from_iso


def test_same_seed_gives_identical_record(tiny, tmp_path):
    again = generate(preset("tiny"), tmp_path)
    a, b = RecordStore.open(tiny["db"]), RecordStore.open(again["db"])
    assert a.content_hash() == b.content_hash()
    assert Path(tiny["planted"]).read_text() == Path(again["planted"]).read_text()
    for f in Path(tiny["archive"]).iterdir():
        assert f.read_bytes() == (Path(again["archive"]) / f.name).read_bytes()


def test_different_seed_gives_different_record(tiny, tmp_path):
    other = generate(preset("tiny", seed=2), tmp_path)
    assert RecordStore.open(tiny["db"]).content_hash() != RecordStore.open(other["db"]).content_hash()


def test_size_is_within_budget(tiny):
    archive = sum(f.stat().st_size for f in Path(tiny["archive"]).iterdir())
    assert (Path(tiny["db"]).stat().st_size + archive) / 1e6 <= tiny["config"].max_size_mb


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
        assert e.producer and e.raw_ref.startswith(("synthetic://", "source://control_archive/"))


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
    """The full series is in the archive; the Record holds only the status changes."""
    case = next(c for c in tiny["planted_cases"] if c["mode"] == "lv_drift_trip")
    box = next(name for rel, name in store.related(case["true_element"]) if rel == "powered_by_of")
    archive = ControlArchive.find(tiny["db"])

    def mean_voltage(hours_before):
        t = case["t_event"] - int(hours_before * 3600)
        return archive.fetch(box, "lv_voltage", t - 300, t + 300, end)[0]["v"]

    readings = [mean_voltage(h) for h in (5.5, 4, 2.5, 1)]
    assert readings == sorted(readings, reverse=True)      # falling, hour after hour
    assert readings[0] - readings[-1] > 0.2
    assert abs(mean_voltage(-4) - 8.0) < 0.06              # back to nominal after the repair
    statuses = [(e.t_start, e.payload["value"]) for e in store.entries(end, elements=[box], types=["lv_voltage_status"])
                if case["t_event"] - 6 * 3600 <= e.t_start <= case["t_event"] + 3600]
    assert [v for _, v in statuses] == ["drifting down", "low", "off", "normal"]
    assert case["t_event"] - statuses[0][0] > 3 * 3600      # the drift was on record hours ahead


def test_the_record_holds_no_time_series(tiny, store, end):
    types = {t for _, _, t, _, _ in store.counts_by_type(end)}
    assert not types & {"lv_voltage", "temperature"}
    status = sum(n for _, _, t, _, n in store.counts_by_type(end) if t.endswith("_status"))
    assert status < 0.2 * store.count_entries(end)
    archive = ControlArchive.find(tiny["db"])
    assert {(c["element"], c["quantity"]) for c in archive.channels()} == {
        (b, q) for b in store.elements("readout_box") for q in ("lv_voltage", "temperature")}
    for e in store.entries(end, types=["lv_voltage_status"]):   # every status points into the archive
        assert e.raw_ref.startswith("source://control_archive/") and e.known_at >= e.t_start


def test_archive_reads_respect_as_of(tiny, store):
    archive = ControlArchive.find(tiny["db"])
    t0, t1 = store.time_span()
    mid = (t0 + t1) // 2
    times, _ = archive.samples("HBP01", "lv_voltage", t0, t1, mid)
    assert times and max(times) <= mid
    full = archive.fetch("HBP01", "lv_voltage", t0 + 3600, t0 + 3600 + 1800, t1)
    assert all(p["n"] == 1 for p in full)                   # a short range comes back at full resolution
