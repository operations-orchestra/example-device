"""Layer 2: the Record keeps its promises."""
import pytest

from aggregator import RecordStore
from utils import Entry


def _entry(**kw):
    base = dict(source="dcs", record_class="MS", kind="state", type="supply_state", element="S1",
                t_start=100, known_at=100, payload={"value": "on"}, raw_ref="ref://x",
                producer="test", producer_version="1")
    base.update(kw)
    return Entry(**base)


@pytest.fixture()
def fresh(tmp_path):
    s = RecordStore.create(tmp_path / "r.db")
    s.add_element("DET", "detector")
    s.add_element("S1", "lv_supply", parent="DET")
    return s


def test_entry_round_trip(fresh):
    eid = fresh.add_entry(_entry(payload={"value": "on", "nested": {"a": [1, 2]}}))
    back = fresh.get_entry(eid, as_of=100)
    assert (back.source, back.record_class, back.kind, back.type, back.element) == \
        ("dcs", "MS", "state", "supply_state", "S1")
    assert back.payload == {"value": "on", "nested": {"a": [1, 2]}}
    assert (back.producer, back.producer_version, back.raw_ref) == ("test", "1", "ref://x")


def test_entry_must_name_a_producer_and_cannot_be_known_before_it_happened():
    with pytest.raises(ValueError):
        _entry(producer="")
    with pytest.raises(ValueError):
        _entry(t_start=100, known_at=99)
    with pytest.raises(ValueError):
        _entry(record_class="XX")


def test_unknown_element_is_rejected(fresh):
    with pytest.raises(KeyError):
        fresh.add_entry(_entry(element="nope"))


def test_a_correction_adds_a_version_and_keeps_the_old_entry(fresh):
    old = fresh.add_entry(_entry(payload={"value": "off"}))
    new = fresh.supersede(old, _entry(known_at=500, payload={"value": "on"}))
    assert [e.id for e in fresh.entries(as_of=499)] == [old]      # before the correction is known
    assert [e.id for e in fresh.entries(as_of=500)] == [new]      # afterwards
    assert fresh.get_entry(old, as_of=500).payload == {"value": "off"}   # still there
    assert fresh.get_entry(new, as_of=500).supersedes == old
    assert fresh.state_at("S1", "supply_state", 200, as_of=500).id == new


def test_incident_labels_are_write_once(fresh):
    iid = fresh.open_incident("trip", "S1", 100, 110)
    fresh.label_incident(iid, "recovery_action", "power-cycle", 120)
    with pytest.raises(ValueError):
        fresh.label_incident(iid, "recovery_action", "something else", 130)
    with pytest.raises(ValueError):
        fresh.label_incident(iid, "not_a_label", "x", 130)


def test_incident_status_follows_what_is_known(fresh):
    iid = fresh.open_incident("trip", "S1", 100, 110)
    fresh.label_incident(iid, "recovery_action", "power-cycle", 120)
    fresh.label_incident(iid, "confirmed_cause", "ageing module", 900)
    fresh.close_incident(iid, "closed", 900)
    assert fresh.incident(iid, as_of=109) is None
    assert fresh.incident(iid, as_of=110).status == "open"
    assert fresh.incident(iid, as_of=120).status == "mitigated"
    view = fresh.incident(iid, as_of=899)
    assert view.recovery_action == "power-cycle" and view.confirmed_cause is None
    assert fresh.incident(iid, as_of=900).status == "closed"


def test_create_refuses_to_overwrite(fresh):
    fresh.commit()
    with pytest.raises(FileExistsError):
        RecordStore.create(fresh.path)


def test_opened_record_is_read_only(fresh):
    import sqlite3

    fresh.close()
    ro = RecordStore.open(fresh.path)
    with pytest.raises(sqlite3.OperationalError):
        ro.add_element("X", "detector")
